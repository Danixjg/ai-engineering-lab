#!/usr/bin/env python3
"""Portable local-runtime manager for the AI Engineering Lab.

MultiEngin makes a machine capable of executing cloud-managed Multica agents.
It never copies credentials, workspace IDs, or cloud state into this repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".ai" / "agents"
RUNTIME_MANIFEST = ROOT / ".ai" / "runtime" / "runtime-manifest.yaml"
LOCAL_BIN = Path.home() / ".local" / "bin"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_HISTORY = STATE_HOME / "multiengin" / "runtime-history.json"
# Kiro's official installer creates this directory on fresh hosts. Include it
# before installation as well so the same `start` invocation can find Kiro.
os.environ["PATH"] = f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
AUTH_FAILURE = re.compile(
    r"not[ -]?logged|not authenticated|unauthenticated|invalid|expired|"
    r"login required|sign in|log in",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class Discovery:
    workspace: dict[str, Any]
    daemon: dict[str, Any]
    agents: tuple[dict[str, Any], ...]
    runtimes: tuple[dict[str, Any], ...]

    @property
    def workspace_id(self) -> str:
        return str(self.workspace.get("id", ""))


@dataclass(frozen=True)
class Reconciliation:
    manifest: dict[str, Any]
    workspace_agent: dict[str, Any]
    target_runtime: dict[str, Any]
    previous_runtime: dict[str, Any] | None

    @property
    def previous_runtime_id(self) -> str:
        return str(self.workspace_agent.get("runtime_id") or "")

    @property
    def target_runtime_id(self) -> str:
        return str(self.target_runtime["id"])

    @property
    def change_required(self) -> bool:
        return self.previous_runtime_id != self.target_runtime_id


def load_document(path: Path) -> dict[str, Any]:
    """Load JSON-compatible YAML without imposing a YAML dependency on workers."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path.relative_to(ROOT)} must be JSON-compatible YAML; "
            f"the portable CLI has no YAML package dependency ({error.msg})."
        ) from error
    if not isinstance(result, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return result


def manifests() -> list[dict[str, Any]]:
    found = [load_document(path) for path in sorted(AGENTS_DIR.glob("*.yaml"))]
    if not found:
        raise ValueError("no agent manifests found in .ai/agents")
    return found


def runtime_manifest() -> dict[str, Any]:
    return load_document(RUNTIME_MANIFEST)


def run(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return False, "command not found"
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output


def first_line(output: str) -> str:
    return next((line.strip() for line in output.splitlines() if line.strip()), "")


def json_output(command: list[str], description: str) -> Any:
    ok, output = run(command)
    if not ok:
        raise ValueError(f"cannot {description}: {first_line(output) or 'command failed'}")
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError(f"cannot {description}: Multica returned invalid JSON ({error.msg})") from error


def json_collection(payload: Any, key: str, description: str) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, dict):
        payload = payload.get(key)
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"cannot {description}: expected a JSON array")
    return tuple(payload)


def command_version(command: str) -> tuple[bool, str]:
    ok, output = run([command, "--version"])
    return ok, output


def version_at_least(output: str, minimum: str) -> bool:
    matches = list(re.finditer(r"(?<!\d)(\d+(?:\.\d+){0,2})(?!\d)", output))
    if not matches:
        return False
    # Some CLIs print non-version warnings before the version. Their version is
    # conventionally the final numeric token in the command's output.
    actual = tuple(int(value) for value in matches[-1].group(1).split("."))
    required = tuple(int(value) for value in minimum.split("."))
    width = max(len(actual), len(required))
    return actual + (0,) * (width - len(actual)) >= required + (0,) * (width - len(required))


def authenticated(command: list[str]) -> bool:
    ok, output = run(command)
    return ok and not AUTH_FAILURE.search(output)


def runtime_check(agent: dict[str, Any]) -> Check:
    runtime = agent["runtime"]
    command = runtime["executable"]
    minimum = runtime.get("version", {}).get("minimum")
    if not shutil.which(command):
        return Check(f"{agent['name']} runtime", False, f"{command} is not installed")
    ok, output = command_version(command)
    if not ok:
        return Check(f"{agent['name']} runtime", False, f"cannot read {command} version")
    if minimum and not version_at_least(output, minimum):
        return Check(f"{agent['name']} runtime", False, f"requires {minimum}+; found {first_line(output)}")
    return Check(f"{agent['name']} runtime", True, first_line(output))


def authentication_check(name: str) -> Check:
    commands = {
        "kiro": (["kiro-cli", "whoami"], "kiro-cli login"),
        "codex": (["codex", "login", "status"], "codex login"),
        "github": (["gh", "auth", "status"], "gh auth login"),
    }
    if name not in commands:
        return Check(f"{name} authentication", False, "no local health-check adapter", True)
    command, remedy = commands[name]
    if not shutil.which(command[0]):
        return Check(f"{name} authentication", False, f"{command[0]} is not installed")
    return Check(f"{name} authentication", authenticated(command), f"run: {remedy}")


def dependency_check(dependency: str, optional: bool) -> Check:
    if dependency == "docker":
        passed = bool(shutil.which("docker")) and run(["docker", "info"])[0]
        return Check("Docker", passed, "CLI missing or daemon unavailable", not optional)
    return Check(dependency, bool(shutil.which(dependency)), "command not found", not optional)


def repository_check() -> Check:
    return Check("Repository access", (ROOT / ".git").exists(), "repository checkout unavailable")


def agent_checks(agent: dict[str, Any]) -> list[Check]:
    checks = [runtime_check(agent)]
    dependencies = agent.get("dependencies", {})
    checks.extend(dependency_check(value, False) for value in dependencies.get("system", []))
    checks.extend(dependency_check(value, True) for value in dependencies.get("optional", []))
    checks.extend(authentication_check(value) for value in agent.get("authentication", {}).get("required", []))
    if "repository_access" in agent.get("health_checks", []):
        checks.append(repository_check())
    return checks


def daemon_running(output: str) -> bool:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("status") in {"running", "ready"}


def core_checks() -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("multica"):
        return [Check("Multica CLI", False, "run the approved Multica installation, then multica setup")]
    checks.append(Check("Multica CLI", True, first_line(run(["multica", "--version"])[1])))
    workspace_ok, _ = run(["multica", "workspace", "get", "--output", "json"])
    checks.append(Check("Multica workspace", workspace_ok, "run: multica setup"))
    daemon_ok, daemon = run(["multica", "daemon", "status", "--output", "json"])
    checks.append(Check("Multica daemon", daemon_ok and daemon_running(daemon), "run: multica daemon start"))

    compatibility = runtime_manifest()["compatibility"]
    python_ok, python_version = run(["python3", "--version"])
    checks.append(
        Check(
            "Python",
            python_ok and version_at_least(python_version, compatibility["python"]),
            f"requires {compatibility['python']}+",
        )
    )
    node_ok, node_version = run(["node", "--version"])
    checks.append(
        Check(
            "Node",
            node_ok and version_at_least(node_version, compatibility["node"]),
            f"requires {compatibility['node']}+",
        )
    )
    return checks


def print_check(check: Check, indent: str = "") -> None:
    mark = "✓" if check.passed else "✗"
    detail = "" if check.passed or not check.detail else f"  ({check.detail})"
    optional = " [optional]" if not check.blocking else ""
    print(f"{indent}{mark} {check.name}{optional}{detail}")


def ready(checks: Iterable[Check]) -> bool:
    return all(check.passed or not check.blocking for check in checks)


def select_agents(all_agents: list[dict[str, Any]], requested: list[str], select_all: bool) -> list[dict[str, Any]]:
    by_name = {agent["name"]: agent for agent in all_agents}
    by_id = {agent["agent_id"]: agent for agent in all_agents}
    if select_all:
        return all_agents
    if not requested and sys.stdin.isatty():
        print("\nAvailable agents:\n")
        for index, agent in enumerate(all_agents, start=1):
            runtime = agent["runtime"]
            capabilities = runtime.get("requirements", {}).get("capabilities", [])
            detail = f"{runtime['provider']}: {runtime['executable']}"
            if capabilities:
                detail += f"; {len(capabilities)} capabilities"
            print(f"  [{index}] {agent['name']}  ({detail})")
        raw = input("\nSelect agents (for example: 1,2 or all): ").strip()
        if raw.lower() == "all":
            return all_agents
        requested = [item.strip() for item in raw.split(",") if item.strip()]
        for item in requested[:]:
            if item.isdigit() and 1 <= int(item) <= len(all_agents):
                requested[requested.index(item)] = all_agents[int(item) - 1]["name"]
    if not requested:
        raise ValueError("select an agent, use --all, or run from an interactive terminal")
    selected: list[dict[str, Any]] = []
    unknown: list[str] = []
    for name in requested:
        agent = by_name.get(name) or by_id.get(name)
        if agent is None:
            unknown.append(name)
        elif agent not in selected:
            selected.append(agent)
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)}")
    return selected


def install_runtime(agent: dict[str, Any], dry_run: bool) -> bool:
    provider = agent["runtime"]["provider"]
    minimum = agent["runtime"].get("version", {}).get("minimum", "latest")
    installer = runtime_manifest().get("runtimes", {}).get(provider, {}).get("installer")
    if dry_run:
        print(f"  would install {provider} runtime ({minimum}+)")
        return True
    if installer == "kiro_cli":
        print("  installing Kiro CLI from its official installer...")
        return subprocess.run("curl -fsSL https://cli.kiro.dev/install | bash", shell=True, check=False).returncode == 0
    if installer == "codex_cli":
        if not shutil.which("npm"):
            print("  Node/npm is required before this runtime can be installed.")
            return False
        return subprocess.run(["npm", "install", "--global", f"@openai/codex@{minimum}"], check=False).returncode == 0
    print(f"  no installer is configured for runtime provider: {provider}")
    return False


def login(authentication: str, dry_run: bool) -> bool:
    commands = {
        "kiro": ["kiro-cli", "login"],
        "codex": ["codex", "login"],
        "github": ["gh", "auth", "login"],
    }
    command = commands.get(authentication)
    if command is None or not shutil.which(command[0]):
        print(f"  cannot authenticate {authentication}: required CLI is not installed")
        return False
    if dry_run:
        print(f"  would run: {' '.join(command)}")
        return True
    return subprocess.run(command, check=False).returncode == 0


def bootstrap(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> bool:
    missing_runtimes = [agent for agent in selected if not runtime_check(agent).passed]
    auths = sorted(
        {
            auth
            for agent in selected
            for auth in agent.get("authentication", {}).get("required", [])
            if not authentication_check(auth).passed
        }
    )
    missing_dependencies = sorted(
        {
            check.name
            for agent in selected
            for check in agent_checks(agent)
            if not check.passed and check.blocking and check.name in {"git", "Docker"}
        }
    )
    if missing_runtimes or auths or missing_dependencies:
        print("Plan:")
        for agent in missing_runtimes:
            print(f"  • install required runtime for {agent['name']}: {agent['runtime']['provider']}")
        for auth in auths:
            print(f"  • authenticate {auth}")
        for dependency in missing_dependencies:
            print(f"  • install or start required dependency: {dependency}")
        if not yes and sys.stdin.isatty() and input("\nProceed? [Y/n] ").strip().lower() not in {"", "y", "yes"}:
            print("Cancelled.")
            return False

    if not shutil.which("multica"):
        print("BLOCKED: Multica CLI is required. Install it and run `multica setup`, then retry.")
        return False
    workspace_ok = run(["multica", "workspace", "get", "--output", "json"])[0]
    if not workspace_ok:
        print("Connecting this machine to Multica Cloud...")
        if dry_run:
            print("  would run: multica setup")
            return False
        if subprocess.run(["multica", "setup"], check=False).returncode != 0:
            return False
    for agent in missing_runtimes:
        if not install_runtime(agent, dry_run):
            return False
    for authentication in auths:
        if not login(authentication, dry_run):
            return False

    daemon_ok, daemon = run(["multica", "daemon", "status", "--output", "json"])
    if not daemon_ok or not daemon_running(daemon):
        print("Starting Multica daemon...")
        if dry_run:
            print("  would run: multica daemon start")
            return False
        if subprocess.run(["multica", "daemon", "start"], check=False).returncode != 0:
            return False
    return True


def discover() -> Discovery:
    workspace = json_output(["multica", "workspace", "get", "--output", "json"], "read the active workspace")
    daemon = json_output(["multica", "daemon", "status", "--output", "json"], "read daemon status")
    agents_payload = json_output(["multica", "agent", "list", "--output", "json"], "list workspace agents")
    runtimes_payload = json_output(["multica", "runtime", "list", "--output", "json"], "list workspace runtimes")
    if not isinstance(workspace, dict) or not workspace.get("id"):
        raise ValueError("cannot read the active workspace: missing workspace ID")
    if not isinstance(daemon, dict) or not daemon.get("daemon_id"):
        raise ValueError("cannot read daemon status: missing daemon ID")
    return Discovery(
        workspace=workspace,
        daemon=daemon,
        agents=json_collection(agents_payload, "agents", "list workspace agents"),
        runtimes=json_collection(runtimes_payload, "runtimes", "list workspace runtimes"),
    )


def local_runtime_ids(snapshot: Discovery) -> set[str]:
    ids: set[str] = set()
    workspaces = snapshot.daemon.get("workspaces", [])
    if not isinstance(workspaces, list):
        workspaces = []
    for workspace in workspaces:
        if isinstance(workspace, dict) and str(workspace.get("id")) == snapshot.workspace_id:
            ids.update(str(runtime_id) for runtime_id in workspace.get("runtimes", []))
    if ids:
        return ids
    daemon_id = str(snapshot.daemon.get("daemon_id", ""))
    return {
        str(runtime["id"])
        for runtime in snapshot.runtimes
        if runtime.get("id") and str(runtime.get("daemon_id", "")) == daemon_id
    }


def runtime_incompatibilities(agent: dict[str, Any], runtime: dict[str, Any]) -> list[str]:
    specification = agent["runtime"]
    requirements = specification.get("requirements", {})
    metadata = runtime.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    reasons: list[str] = []
    provider = specification.get("provider")
    if provider and runtime.get("provider") != provider:
        reasons.append(f"provider is {runtime.get('provider') or 'unknown'}, requires {provider}")
    required_mode = requirements.get("runtime_mode")
    if required_mode and runtime.get("runtime_mode") != required_mode:
        reasons.append(f"mode is {runtime.get('runtime_mode') or 'unknown'}, requires {required_mode}")
    required_capabilities = set(requirements.get("capabilities", []))
    reported_capabilities = metadata.get("capabilities", [])
    runtime_capabilities = set(reported_capabilities if isinstance(reported_capabilities, list) else [])
    missing = sorted(required_capabilities - runtime_capabilities)
    if missing:
        reasons.append(f"missing capabilities: {', '.join(missing)}")
    minimum = specification.get("version", {}).get("minimum")
    version = str(metadata.get("version", ""))
    if minimum and not version_at_least(version, minimum):
        reasons.append(f"version is {version or 'unknown'}, requires {minimum}+")
    return reasons


def compatible_local_runtimes(agent: dict[str, Any], snapshot: Discovery) -> list[dict[str, Any]]:
    local_ids = local_runtime_ids(snapshot)
    candidates = [
        runtime
        for runtime in snapshot.runtimes
        if str(runtime.get("id", "")) in local_ids
        and runtime.get("status") == "online"
        and not runtime_incompatibilities(agent, runtime)
    ]
    return sorted(
        candidates,
        key=lambda runtime: (str(runtime.get("last_seen_at", "")), str(runtime.get("id", ""))),
        reverse=True,
    )


def workspace_agent(agent: dict[str, Any], snapshot: Discovery) -> dict[str, Any] | None:
    return next((candidate for candidate in snapshot.agents if candidate.get("name") == agent["name"]), None)


def no_compatible_runtime_message(agent: dict[str, Any], snapshot: Discovery) -> str:
    local_ids = local_runtime_ids(snapshot)
    local = [runtime for runtime in snapshot.runtimes if str(runtime.get("id", "")) in local_ids]
    if not local:
        return f"no local runtimes were registered for workspace agent {agent['name']}"
    details: list[str] = []
    for runtime in local:
        reasons = runtime_incompatibilities(agent, runtime)
        if runtime.get("status") != "online":
            reasons.append(f"status is {runtime.get('status') or 'unknown'}")
        if reasons:
            details.append(f"{runtime.get('name') or runtime.get('id')}: {'; '.join(reasons)}")
    suffix = f" ({' | '.join(details)})" if details else ""
    return f"no compatible local runtime exists for workspace agent {agent['name']}{suffix}"


def plan_reconciliation(selected: list[dict[str, Any]], snapshot: Discovery) -> list[Reconciliation]:
    plan: list[Reconciliation] = []
    runtimes_by_id = {str(runtime.get("id")): runtime for runtime in snapshot.runtimes}
    local_ids = local_runtime_ids(snapshot)
    for manifest in selected:
        cloud_agent = workspace_agent(manifest, snapshot)
        if cloud_agent is None:
            raise ValueError(f"workspace agent not found: {manifest['name']}")
        candidates = compatible_local_runtimes(manifest, snapshot)
        if not candidates:
            raise ValueError(no_compatible_runtime_message(manifest, snapshot))
        current_id = str(cloud_agent.get("runtime_id") or "")
        current = runtimes_by_id.get(current_id)
        if (
            current is not None
            and current_id in local_ids
            and current.get("status") == "online"
            and not runtime_incompatibilities(manifest, current)
        ):
            target = current
        else:
            target = candidates[0]
        plan.append(Reconciliation(manifest, cloud_agent, target, current))
    return plan


def runtime_history_detail(runtime: dict[str, Any] | None, fallback_id: str = "") -> dict[str, Any]:
    if runtime is None:
        return {"id": fallback_id}
    return {
        key: runtime.get(key)
        for key in ("id", "name", "provider", "daemon_id", "device_info", "status", "last_seen_at")
        if runtime.get(key) is not None
    }


def record_runtime_history(action: Reconciliation, workspace_id: str, history_file: Path = RUNTIME_HISTORY) -> None:
    if not action.previous_runtime_id or not action.change_required:
        return
    history: dict[str, Any] = {"schema_version": "0.1", "entries": []}
    if history_file.exists():
        try:
            loaded = json.loads(history_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
                history = loaded
        except (json.JSONDecodeError, OSError):
            pass
    history["entries"].append(
        {
            "workspace_id": workspace_id,
            "workspace_agent_id": action.workspace_agent.get("id"),
            "workspace_agent_name": action.workspace_agent.get("name"),
            "previous_runtime_id": action.previous_runtime_id,
            "current_runtime_id": action.target_runtime_id,
            "previous_runtime": runtime_history_detail(action.previous_runtime, action.previous_runtime_id),
            "current_runtime": runtime_history_detail(action.target_runtime),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    history_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = history_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(history_file)


def apply_reconciliation(
    plan: list[Reconciliation],
    workspace_id: str,
    dry_run: bool,
    history_file: Path = RUNTIME_HISTORY,
) -> int:
    changes = 0
    for action in plan:
        name = action.manifest["name"]
        if not action.change_required:
            print(f"  ✓ {name}: already bound to compatible local runtime {action.target_runtime_id}")
            continue
        previous = action.previous_runtime_id or "unbound"
        print(f"  ↻ {name}: {previous} -> {action.target_runtime_id}")
        if dry_run:
            print(
                f"    would run: multica agent update {action.workspace_agent['id']} "
                f"--runtime-id {action.target_runtime_id}"
            )
            changes += 1
            continue
        ok, output = run(
            [
                "multica",
                "agent",
                "update",
                str(action.workspace_agent["id"]),
                "--runtime-id",
                action.target_runtime_id,
                "--output",
                "json",
            ]
        )
        if not ok:
            raise ValueError(f"failed to rebind {name}: {first_line(output) or 'agent update failed'}")
        changes += 1
        try:
            record_runtime_history(action, workspace_id, history_file)
        except OSError as error:
            print(f"    warning: could not preserve previous runtime history: {error}", file=sys.stderr)
    return changes


def projected_discovery(snapshot: Discovery, plan: list[Reconciliation]) -> Discovery:
    targets = {
        str(action.workspace_agent.get("id")): action.target_runtime_id
        for action in plan
        if action.change_required
    }
    agents: list[dict[str, Any]] = []
    for agent in snapshot.agents:
        projected = dict(agent)
        if str(agent.get("id")) in targets:
            projected["runtime_id"] = targets[str(agent.get("id"))]
            projected["runtime_bound"] = True
        agents.append(projected)
    return Discovery(snapshot.workspace, snapshot.daemon, tuple(agents), snapshot.runtimes)


def workspace_checks(agent: dict[str, Any], snapshot: Discovery) -> list[Check]:
    cloud_agent = workspace_agent(agent, snapshot)
    if cloud_agent is None:
        return [Check("Workspace agent", False, f"{agent['name']} was not found in the active workspace")]
    checks = [Check("Workspace agent", True, str(cloud_agent.get("id", "")))]
    runtime_id = str(cloud_agent.get("runtime_id") or "")
    runtime = next((candidate for candidate in snapshot.runtimes if str(candidate.get("id")) == runtime_id), None)
    local = runtime_id in local_runtime_ids(snapshot)
    compatible = runtime is not None and not runtime_incompatibilities(agent, runtime)
    checks.append(
        Check(
            "Compatible local binding",
            bool(runtime_id and local and compatible),
            "agent is not bound to a compatible runtime on this machine",
        )
    )
    checks.append(
        Check(
            "Workspace runtime online",
            runtime is not None and local and runtime.get("status") == "online",
            "bound local runtime is not online",
        )
    )
    healthy_agent_status = cloud_agent.get("status") not in {"disabled", "error", "offline"}
    checks.append(
        Check(
            "Workspace agent status",
            healthy_agent_status,
            f"status is {cloud_agent.get('status') or 'unknown'}",
        )
    )
    return checks


def needs_daemon_refresh(selected: list[dict[str, Any]], snapshot: Discovery) -> bool:
    return any(not compatible_local_runtimes(agent, snapshot) for agent in selected)


def refresh_daemon(dry_run: bool) -> bool:
    print("Refreshing the Multica daemon so local runtimes are registered...")
    if dry_run:
        print("  would run: multica daemon restart")
        return False
    return subprocess.run(["multica", "daemon", "restart"], check=False).returncode == 0


def start(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    print("MultiEngin\nPortable Engineering Runtime\n")
    print("Selected: " + ", ".join(agent["name"] for agent in selected))

    print("\n[1/4] Bootstrap")
    if not bootstrap(selected, yes, dry_run):
        return 1
    print("  ✓ local tools, authentication, workspace, and daemon prepared")

    print("\n[2/4] Discover")
    snapshot = discover()
    print(f"  ✓ workspace: {snapshot.workspace.get('name') or snapshot.workspace_id}")
    print(f"  ✓ {len(snapshot.agents)} workspace agents; {len(local_runtime_ids(snapshot))} local runtimes")
    if needs_daemon_refresh(selected, snapshot):
        if not refresh_daemon(dry_run):
            if dry_run:
                print("BLOCKED: a daemon refresh is required before runtime IDs can be reconciled.")
            return 1
        snapshot = discover()
        print(f"  ✓ refreshed; {len(local_runtime_ids(snapshot))} local runtimes discovered")

    print("\n[3/4] Reconcile")
    plan = plan_reconciliation(selected, snapshot)
    changes = apply_reconciliation(plan, snapshot.workspace_id, dry_run)
    if not changes:
        print("  ✓ no workspace bindings changed")

    print("\n[4/4] Verify")
    verified_snapshot = projected_discovery(snapshot, plan) if dry_run else discover()
    return doctor(selected, include_core=True, snapshot=verified_snapshot)


def doctor(
    selected: list[dict[str, Any]],
    include_core: bool = True,
    snapshot: Discovery | None = None,
) -> int:
    print("MultiEngin Environment Check\n")
    core = core_checks() if include_core else []
    for check in core:
        print_check(check)
    if core:
        print()
    all_ready = ready(core)
    discovery_error = ""
    if snapshot is None and shutil.which("multica"):
        try:
            snapshot = discover()
        except ValueError as error:
            discovery_error = str(error)
            all_ready = False
    if discovery_error:
        print_check(Check("Workspace discovery", False, discovery_error))
        print()
    for agent in selected:
        checks = agent_checks(agent)
        if snapshot is not None:
            checks.extend(workspace_checks(agent, snapshot))
        status = "READY" if ready(checks) else "BLOCKED"
        print(f"{agent['name']}  {status}")
        for check in checks:
            print_check(check, "  ")
        print()
        all_ready = all_ready and ready(checks)
    return 0 if all_ready else 1


def list_agents(selected: list[dict[str, Any]]) -> int:
    print("Configured agents\n")
    snapshot: Discovery | None = None
    discovery_error = ""
    if shutil.which("multica"):
        try:
            snapshot = discover()
        except ValueError as error:
            discovery_error = str(error)
    all_ready = not discovery_error
    for agent in selected:
        checks = agent_checks(agent)
        cloud_checks = workspace_checks(agent, snapshot) if snapshot is not None else []
        combined = checks + cloud_checks
        print(f"{agent['name']}")
        print(f"  Runtime: {agent['runtime']['provider']} ({agent['runtime']['executable']})")
        print(f"  Local status: {'READY' if ready(checks) else 'BLOCKED'}")
        if cloud_checks:
            print(f"  Workspace status: {'ONLINE' if ready(cloud_checks) else 'BLOCKED'}")
        elif discovery_error:
            print(f"  Workspace status: UNAVAILABLE ({discovery_error})")
        print(f"  Skills: {', '.join(agent.get('skills', []))}")
        all_ready = all_ready and ready(combined)
    return 0 if all_ready else 1


def update(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    print("Updating MultiEngin manifests from the repository...")
    if dry_run:
        print("  would run: git pull --ff-only")
    elif subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT, check=False).returncode != 0:
        return 1
    selected_names = [agent["name"] for agent in selected]
    return start(select_agents(manifests(), selected_names, False), yes=yes, dry_run=dry_run)


def stop(dry_run: bool) -> int:
    if not shutil.which("multica"):
        print("Multica CLI is not installed; no local daemon to stop.")
        return 0
    if dry_run:
        print("would run: multica daemon stop")
        return 0
    result = subprocess.run(["multica", "daemon", "stop"], check=False)
    if result.returncode == 0:
        print("Local Multica daemon stopped. The Multica Cloud workspace remains active.")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "doctor", "agents", "update"):
        command = subparsers.add_parser(name)
        command.add_argument("agents", nargs="*", metavar="AGENT")
        command.add_argument("--all", action="store_true", help="select every configured agent")
        if name in {"start", "update"}:
            command.add_argument("--yes", action="store_true", help="do not ask before provisioning")
            command.add_argument("--dry-run", action="store_true", help="show mutations without performing them")
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "stop":
            return stop(args.dry_run)
        selected = select_agents(manifests(), args.agents, args.all)
        if args.command == "doctor":
            return doctor(selected)
        if args.command == "agents":
            return list_agents(selected)
        if args.command == "start":
            return start(selected, args.yes, args.dry_run)
        return update(selected, args.yes, args.dry_run)
    except (ValueError, OSError) as error:
        print(f"MultiEngin error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
