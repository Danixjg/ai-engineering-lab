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
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".ai" / "agents"
RUNTIME_MANIFEST = ROOT / ".ai" / "runtime" / "runtime-manifest.yaml"
WORKFLOW_MANIFEST = ROOT / ".ai" / "workflows" / "implementation.yaml"
LOCAL_BIN = Path.home() / ".local" / "bin"
OPENCODE_BIN = Path.home() / ".opencode" / "bin"
NPM_GLOBAL_BIN = Path(
    os.environ.get("NPM_CONFIG_PREFIX", str(Path.home() / ".npm-global"))
) / "bin"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_HISTORY = STATE_HOME / "multiengin" / "runtime-history.json"
OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"
# Kiro/mise and OpenCode's official installers use these directories. Include
# them before bootstrap so the same `start` invocation can find newly installed
# tools even when the parent shell has not reloaded its profile yet.
os.environ["PATH"] = os.pathsep.join(
    [str(OPENCODE_BIN), str(NPM_GLOBAL_BIN), str(LOCAL_BIN), os.environ.get("PATH", "")]
)
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
    check_id: str = ""
    category: str = "environment"


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
    clear_model: bool = False

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


def instructions_path(agent: dict[str, Any]) -> Path:
    raw_path = agent.get("instructions_file")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{agent.get('name', 'agent')} does not declare instructions_file")
    path = (ROOT / raw_path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"instructions file escapes the repository: {raw_path}")
    if not path.is_file():
        raise ValueError(f"instructions file does not exist: {raw_path}")
    return path


def runtime_manifest() -> dict[str, Any]:
    return load_document(RUNTIME_MANIFEST)


def workflow_manifest() -> dict[str, Any]:
    return load_document(WORKFLOW_MANIFEST)


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


def npm_global_bin() -> Path | None:
    if not shutil.which("npm"):
        return None
    ok, output = run(["npm", "prefix", "--global"])
    if not ok or not first_line(output):
        return None
    return Path(first_line(output)) / "bin"


def activate_npm_global_bin() -> bool:
    binary_directory = npm_global_bin()
    if binary_directory is None:
        return False
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if str(binary_directory) not in paths:
        os.environ["PATH"] = f"{binary_directory}{os.pathsep}{os.environ.get('PATH', '')}"
    return True


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


def activate_managed_language(language: str, minimum: str) -> bool:
    mise = shutil.which("mise") or str(LOCAL_BIN / "mise")
    if not Path(mise).exists():
        return False
    ok, location = run([mise, "where", f"{language}@{minimum}"])
    if not ok or not location:
        return False
    binary_directory = str(Path(first_line(location)) / "bin")
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if binary_directory not in paths:
        os.environ["PATH"] = f"{binary_directory}{os.pathsep}{os.environ.get('PATH', '')}"
    return True


def language_runtime_check(language: str, command: str, minimum: str) -> Check:
    activate_managed_language(language, minimum)
    ok, output = run([command, "--version"])
    return Check(
        language.title(),
        ok and version_at_least(output, minimum),
        f"requires {minimum}+",
        check_id=f"CORE-{language.upper()}",
        category="environment",
    )


def install_managed_language(language: str, minimum: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  would install {language} {minimum}+ with mise")
        return True
    mise = shutil.which("mise") or str(LOCAL_BIN / "mise")
    if not Path(mise).exists():
        print("  installing mise from its official installer...")
        result = subprocess.run("curl -fsSL https://mise.run | sh", shell=True, check=False)
        if result.returncode != 0:
            return False
        mise = str(LOCAL_BIN / "mise")
    if subprocess.run([mise, "use", "--global", f"{language}@{minimum}"], check=False).returncode != 0:
        return False
    return activate_managed_language(language, minimum)


def authenticated(command: list[str]) -> bool:
    ok, output = run(command)
    return ok and not AUTH_FAILURE.search(output)


def runtime_check(agent: dict[str, Any]) -> Check:
    runtime = agent["runtime"]
    command = runtime["executable"]
    minimum = runtime.get("version", {}).get("minimum")
    activate_npm_global_bin()
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
    if dependency == "ollama":
        passed = bool(shutil.which("ollama")) and run(["ollama", "list"])[0]
        return Check("Ollama", passed, "CLI missing or local model server unavailable", not optional)
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
    checks.append(language_runtime_check("python", "python3", compatibility["python"]))
    checks.append(language_runtime_check("node", "node", compatibility["node"]))
    return checks


def print_check(check: Check, indent: str = "") -> None:
    mark = "✓" if check.passed else "✗"
    detail = "" if check.passed or not check.detail else f"  ({check.detail})"
    optional = " [optional]" if not check.blocking else ""
    print(f"{indent}{mark} {check.name}{optional}{detail}")


def ready(checks: Iterable[Check]) -> bool:
    return all(check.passed or not check.blocking for check in checks)


def contracts(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def workflow_assignments(workflow: dict[str, Any]) -> list[tuple[str, str, set[str], set[str]]]:
    assignments: list[tuple[str, str, set[str], set[str]]] = []
    for state_name, state in workflow.get("states", {}).items():
        if not isinstance(state, dict):
            continue
        if isinstance(state.get("agent"), str):
            assignments.append(
                (state_name, state["agent"], contracts(state.get("input")), contracts(state.get("output")))
            )
        for branch in state.get("parallel", []):
            if isinstance(branch, dict) and isinstance(branch.get("agent"), str):
                label = f"{state_name}.{branch.get('name', 'branch')}"
                assignments.append(
                    (label, branch["agent"], contracts(branch.get("input")), contracts(branch.get("output")))
                )
    return assignments


def workflow_targets(state: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    if isinstance(state.get("next"), str):
        targets.add(state["next"])
    transition_groups = [state.get("transitions", {})]
    barrier = state.get("barrier", {})
    if isinstance(barrier, dict):
        transition_groups.append(barrier.get("transitions", {}))
    for transitions in transition_groups:
        if not isinstance(transitions, dict):
            continue
        for transition in transitions.values():
            if isinstance(transition, dict) and isinstance(transition.get("next"), str):
                targets.add(transition["next"])
    return targets


def workflow_checks(
    agent_manifests: list[dict[str, Any]] | None = None,
    workflow: dict[str, Any] | None = None,
) -> list[Check]:
    agent_manifests = manifests() if agent_manifests is None else agent_manifests
    workflow = workflow_manifest() if workflow is None else workflow
    states = workflow.get("states", {})
    if not isinstance(states, dict):
        return [
            Check(
                "Workflow states",
                False,
                "states must be an object",
                check_id="WORKFLOW-STATES",
                category="workflow",
            )
        ]
    checks: list[Check] = []
    entry = workflow.get("entry_state")
    checks.append(
        Check(
            "Workflow entry state",
            isinstance(entry, str) and entry in states,
            f"entry state {entry!r} is not declared",
            check_id="WORKFLOW-ENTRY",
            category="workflow",
        )
    )

    targets = {target for state in states.values() if isinstance(state, dict) for target in workflow_targets(state)}
    unknown_targets = sorted(targets - set(states))
    checks.append(
        Check(
            "Workflow transitions",
            not unknown_targets,
            f"unknown targets: {', '.join(unknown_targets)}",
            check_id="WORKFLOW-TRANSITIONS",
            category="workflow",
        )
    )

    reachable: set[str] = set()
    pending = [entry] if isinstance(entry, str) and entry in states else []
    while pending:
        state_name = pending.pop()
        if state_name in reachable:
            continue
        reachable.add(state_name)
        state = states.get(state_name, {})
        if isinstance(state, dict):
            pending.extend(workflow_targets(state) - reachable)
    unreachable = sorted(set(states) - reachable)
    checks.append(
        Check(
            "Workflow reachability",
            not unreachable,
            f"unreachable states: {', '.join(unreachable)}",
            check_id="WORKFLOW-REACHABILITY",
            category="workflow",
        )
    )

    by_id = {agent["agent_id"]: agent for agent in agent_manifests}
    assignments = workflow_assignments(workflow)
    missing_agents = sorted({agent_id for _, agent_id, _, _ in assignments if agent_id not in by_id})
    squad = workflow.get("squad", {})
    role_agents = set(squad.get("roles", {}).values()) if isinstance(squad, dict) else set()
    missing_agents.extend(sorted(agent_id for agent_id in role_agents if agent_id not in by_id))
    missing_agents = sorted(set(missing_agents))
    checks.append(
        Check(
            "Workflow agent manifests",
            not missing_agents,
            f"missing manifests: {', '.join(missing_agents)}",
            check_id="WORKFLOW-AGENTS",
            category="workflow",
        )
    )

    leader_manifest_id = squad.get("leader") if isinstance(squad, dict) else None
    leader_manifest = by_id.get(str(leader_manifest_id))
    leader_instruction_errors: list[str] = []
    if leader_manifest is None:
        leader_instruction_errors.append("leader manifest is missing")
    else:
        try:
            instructions = instructions_path(leader_manifest).read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            leader_instruction_errors.append(str(error))
        else:
            required_markers = ("--parent", "--stage", "multica squad activity")
            missing_markers = [marker for marker in required_markers if marker not in instructions]
            if missing_markers:
                leader_instruction_errors.append(
                    "leader instructions lack durable orchestration markers: "
                    + ", ".join(missing_markers)
                )
    checks.append(
        Check(
            "Workflow leader instructions",
            not leader_instruction_errors,
            " | ".join(leader_instruction_errors),
            check_id="WORKFLOW-LEADER-INSTRUCTIONS",
            category="workflow",
        )
    )

    contract_errors: list[str] = []
    for label, agent_id, required_inputs, required_outputs in assignments:
        manifest = by_id.get(agent_id)
        if manifest is None:
            continue
        missing_inputs = sorted(required_inputs - set(manifest.get("inputs", [])))
        missing_outputs = sorted(required_outputs - set(manifest.get("outputs", [])))
        if missing_inputs:
            contract_errors.append(f"{label} input: {', '.join(missing_inputs)}")
        if missing_outputs:
            contract_errors.append(f"{label} output: {', '.join(missing_outputs)}")
    checks.append(
        Check(
            "Workflow agent contracts",
            not contract_errors,
            " | ".join(contract_errors),
            check_id="WORKFLOW-CONTRACTS",
            category="workflow",
        )
    )

    parallel_states = [state for state in states.values() if isinstance(state, dict) and state.get("parallel")]
    barrier_ready = bool(parallel_states) and all(
        state.get("barrier", {}).get("mode") == "all_terminal" for state in parallel_states
    )
    same_candidate = all(
        "integration_result" in contracts(branch.get("input"))
        for state in parallel_states
        for branch in state.get("parallel", [])
        if isinstance(branch, dict)
    )
    checks.append(
        Check(
            "Independent review barrier",
            barrier_ready and same_candidate,
            "parallel reviews must use an all-terminal barrier and the same integration result",
            check_id="WORKFLOW-REVIEW-BARRIER",
            category="workflow",
        )
    )

    terminal_states = {name for name, state in states.items() if isinstance(state, dict) and state.get("terminal")}
    required_terminals = {"merged", "rejected", "blocked", "needs_human"}
    checks.append(
        Check(
            "Workflow terminal states",
            required_terminals.issubset(terminal_states),
            f"missing terminal states: {', '.join(sorted(required_terminals - terminal_states))}",
            check_id="WORKFLOW-TERMINALS",
            category="workflow",
        )
    )
    return checks


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
    if installer == "opencode_cli":
        if not shutil.which("npm"):
            print("  Node/npm is required before this runtime can be installed.")
            return False
        return subprocess.run(
            ["npm", "install", "--global", f"opencode-ai@{minimum}"], check=False
        ).returncode == 0
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
    compatibility = runtime_manifest()["compatibility"]
    language_commands = {"python": "python3", "node": "node"}
    missing_languages = [
        (language, minimum)
        for language, minimum in compatibility.items()
        if not language_runtime_check(language, language_commands[language], minimum).passed
    ]
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
            dependency
            for agent in selected
            for dependency in agent.get("dependencies", {}).get("system", [])
            if not dependency_check(dependency, False).passed
        }
    )
    if missing_languages or missing_runtimes or auths or missing_dependencies:
        print("Plan:")
        for language, minimum in missing_languages:
            print(f"  • install compatible language runtime: {language} {minimum}+")
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
    for language, minimum in missing_languages:
        if not install_managed_language(language, minimum, dry_run):
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


def model_reset_required(
    manifest: dict[str, Any],
    cloud_agent: dict[str, Any],
    current_runtime: dict[str, Any] | None,
    target_runtime: dict[str, Any],
) -> bool:
    model = str(cloud_agent.get("model") or "")
    if not model:
        return False
    current_provider = current_runtime.get("provider") if current_runtime else None
    target_provider = target_runtime.get("provider")
    if current_provider == target_provider:
        return False
    strategy = manifest["runtime"].get("requirements", {}).get("model_strategy", "preserve")
    if strategy == "runtime_default":
        return True
    metadata = target_runtime.get("metadata", {})
    advertised_models = metadata.get("models", []) if isinstance(metadata, dict) else []
    if isinstance(advertised_models, list) and model in advertised_models:
        return False
    raise ValueError(
        f"cannot preserve model {model!r} while moving {manifest['name']} from "
        f"{current_provider or 'an unknown provider'} to {target_provider or 'an unknown provider'}; "
        "set runtime.requirements.model_strategy to runtime_default or choose a compatible model"
    )


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
        clear_model = model_reset_required(manifest, cloud_agent, current, target)
        plan.append(Reconciliation(manifest, cloud_agent, target, current, clear_model))
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
            "previous_model": action.workspace_agent.get("model"),
            "model_strategy": action.manifest["runtime"].get("requirements", {}).get("model_strategy"),
            "current_model": "runtime_default" if action.clear_model else action.workspace_agent.get("model"),
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
        command = [
            "multica",
            "agent",
            "update",
            str(action.workspace_agent["id"]),
            "--runtime-id",
            action.target_runtime_id,
        ]
        if action.clear_model:
            command.extend(["--model", ""])
        command.extend(["--output", "json"])
        if dry_run:
            model_note = " --model <runtime-default>" if action.clear_model else ""
            print(
                f"    would run: multica agent update {action.workspace_agent['id']} "
                f"--runtime-id {action.target_runtime_id}{model_note}"
            )
            changes += 1
            continue
        ok, output = run(command)
        if not ok:
            raise ValueError(f"failed to rebind {name}: {first_line(output) or 'agent update failed'}")
        changes += 1
        try:
            record_runtime_history(action, workspace_id, history_file)
        except OSError as error:
            print(f"    warning: could not preserve previous runtime history: {error}", file=sys.stderr)
    return changes


def projected_discovery(snapshot: Discovery, plan: list[Reconciliation]) -> Discovery:
    actions = {
        str(action.workspace_agent.get("id")): action
        for action in plan
        if action.change_required
    }
    agents: list[dict[str, Any]] = []
    for agent in snapshot.agents:
        projected = dict(agent)
        action = actions.get(str(agent.get("id")))
        if action is not None:
            projected["runtime_id"] = action.target_runtime_id
            projected["runtime_bound"] = True
            if action.clear_model:
                projected["model"] = ""
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
    required_skills = set(agent.get("skills", []))
    enabled_skills = {
        str(skill.get("name"))
        for skill in cloud_agent.get("skills", [])
        if isinstance(skill, dict) and skill.get("enabled", True)
    }
    missing_skills = sorted(required_skills - enabled_skills)
    checks.append(
        Check(
            "Workspace skills",
            not missing_skills,
            f"missing enabled skills: {', '.join(missing_skills)}",
            check_id=f"{agent['agent_id']}-WORKSPACE-SKILLS",
            category="workspace",
        )
    )
    return checks


def squad_checks(
    agent_manifests: list[dict[str, Any]],
    workflow: dict[str, Any],
    snapshot: Discovery,
    squads: tuple[dict[str, Any], ...] | None = None,
    members: tuple[dict[str, Any], ...] | None = None,
) -> list[Check]:
    specification = workflow.get("squad", {})
    squad_name = specification.get("name")
    if squads is None:
        payload = json_output(["multica", "squad", "list", "--output", "json"], "list workspace squads")
        squads = json_collection(payload, "squads", "list workspace squads")
    squad = next((candidate for candidate in squads if candidate.get("name") == squad_name), None)
    checks = [
        Check(
            "Engineering squad exists",
            squad is not None,
            f"squad {squad_name!r} was not found",
            check_id="SQUAD-EXISTS",
            category="topology",
        )
    ]
    if squad is None:
        return checks
    if members is None:
        payload = json_output(
            ["multica", "squad", "member", "list", str(squad["id"]), "--output", "json"],
            "list engineering squad members",
        )
        members = json_collection(payload, "members", "list engineering squad members")

    manifest_by_id = {agent["agent_id"]: agent for agent in agent_manifests}
    cloud_by_name = {str(agent.get("name")): agent for agent in snapshot.agents}
    cloud_by_manifest_id: dict[str, dict[str, Any]] = {}
    missing_workspace_agents: list[str] = []
    for agent_id, manifest in manifest_by_id.items():
        cloud = cloud_by_name.get(manifest["name"])
        if cloud is None:
            missing_workspace_agents.append(manifest["name"])
        else:
            cloud_by_manifest_id[agent_id] = cloud
    checks.append(
        Check(
            "Manifest agents exist in workspace",
            not missing_workspace_agents,
            f"missing workspace agents: {', '.join(sorted(missing_workspace_agents))}",
            check_id="SQUAD-WORKSPACE-AGENTS",
            category="topology",
        )
    )

    leader_manifest_id = specification.get("leader")
    expected_leader = cloud_by_manifest_id.get(str(leader_manifest_id), {}).get("id")
    checks.append(
        Check(
            "Engineering squad leader",
            bool(expected_leader) and squad.get("leader_id") == expected_leader,
            "workspace squad leader does not match the workflow leader",
            check_id="SQUAD-LEADER",
            category="topology",
        )
    )

    actual_roles = {
        (str(member.get("member_id")), str(member.get("role")))
        for member in members
        if member.get("member_type") == "agent"
    }
    role_errors: list[str] = []
    expected_roles = specification.get("roles", {})
    for role, manifest_id in expected_roles.items():
        cloud_id = cloud_by_manifest_id.get(str(manifest_id), {}).get("id")
        if not cloud_id or (str(cloud_id), str(role)) not in actual_roles:
            role_errors.append(f"{role}={manifest_id}")
    checks.append(
        Check(
            "Engineering squad role assignments",
            not role_errors,
            f"missing or incorrect roles: {', '.join(role_errors)}",
            check_id="SQUAD-ROLES",
            category="topology",
        )
    )
    expected_count = len(expected_roles)
    checks.append(
        Check(
            "Engineering squad member count",
            len(actual_roles) == expected_count,
            f"expected {expected_count} agent members; found {len(actual_roles)}",
            check_id="SQUAD-MEMBER-COUNT",
            category="topology",
        )
    )
    return checks


def check_id(check: Check, prefix: str) -> str:
    if check.check_id:
        return check.check_id
    suffix = re.sub(r"[^A-Z0-9]+", "-", check.name.upper()).strip("-")
    return f"{prefix}-{suffix}"


def check_payload(check: Check, prefix: str) -> dict[str, Any]:
    return {
        "check_id": check_id(check, prefix),
        "name": check.name,
        "category": check.category,
        "status": "passed" if check.passed else "failed",
        "blocking": check.blocking,
        "detail": check.detail,
    }


def status_report(selected: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    global_checks = core_checks()
    global_checks.extend(workflow_checks())
    snapshot: Discovery | None = None
    try:
        snapshot = discover()
    except ValueError as error:
        global_checks.append(
            Check(
                "Workspace discovery",
                False,
                str(error),
                check_id="WORKSPACE-DISCOVERY",
                category="workspace",
            )
        )
    if snapshot is not None:
        try:
            global_checks.extend(squad_checks(manifests(), workflow_manifest(), snapshot))
        except ValueError as error:
            global_checks.append(
                Check(
                    "Squad discovery",
                    False,
                    str(error),
                    check_id="SQUAD-DISCOVERY",
                    category="topology",
                )
            )

    agent_reports: list[dict[str, Any]] = []
    all_ready = ready(global_checks)
    for agent in selected:
        checks = agent_checks(agent)
        if snapshot is not None:
            checks.extend(workspace_checks(agent, snapshot))
        else:
            checks.append(Check("Workspace binding", False, "workspace discovery unavailable"))
        agent_ready = ready(checks)
        all_ready = all_ready and agent_ready
        agent_reports.append(
            {
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "status": "ready" if agent_ready else "blocked",
                "checks": [check_payload(check, agent["agent_id"]) for check in checks],
            }
        )
    payload = {
        "schema_version": "0.1",
        "status": "ready" if all_ready else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": snapshot.workspace_id if snapshot is not None else None,
        "checks": [check_payload(check, "CORE") for check in global_checks],
        "agents": agent_reports,
    }
    return payload, all_ready


def print_status_payload(payload: dict[str, Any]) -> None:
    print(f"MultiEngin Workflow Status: {payload['status'].upper()}\n")
    print("Global checks")
    for check in payload["checks"]:
        mark = "✓" if check["status"] == "passed" else "✗"
        optional = " [optional]" if not check["blocking"] else ""
        detail = f"  ({check['detail']})" if check["status"] == "failed" and check["detail"] else ""
        print(f"  {mark} [{check['check_id']}] {check['name']}{optional}{detail}")
    for agent in payload["agents"]:
        print(f"\n{agent['name']}  {agent['status'].upper()}")
        for check in agent["checks"]:
            mark = "✓" if check["status"] == "passed" else "✗"
            optional = " [optional]" if not check["blocking"] else ""
            detail = f"  ({check['detail']})" if check["status"] == "failed" and check["detail"] else ""
            print(f"  {mark} [{check['check_id']}] {check['name']}{optional}{detail}")


def status_command(selected: list[dict[str, Any]], output: str) -> int:
    payload, all_ready = status_report(selected)
    if output == "json":
        print(json.dumps(payload, indent=2))
    else:
        print_status_payload(payload)
    return 0 if all_ready else 1


def workflow_check_command(output: str) -> int:
    checks = workflow_checks()
    payload = [check_payload(check, "WORKFLOW") for check in checks]
    if output == "json":
        print(json.dumps({"status": "ready" if ready(checks) else "blocked", "checks": payload}, indent=2))
    else:
        print("MultiEngin Workflow Contract Check\n")
        for check in checks:
            print_check(check)
    return 0 if ready(checks) else 1


def squad_check_command(output: str) -> int:
    snapshot = discover()
    checks = squad_checks(manifests(), workflow_manifest(), snapshot)
    payload = [check_payload(check, "SQUAD") for check in checks]
    if output == "json":
        print(json.dumps({"status": "ready" if ready(checks) else "blocked", "checks": payload}, indent=2))
    else:
        print("MultiEngin Squad Topology Check\n")
        for check in checks:
            print_check(check)
    return 0 if ready(checks) else 1


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


def sync_instructions(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    """Persist repository-owned instructions on matching workspace agents."""
    sources = [(agent, instructions_path(agent)) for agent in selected]
    payload = json_output(
        ["multica", "agent", "list", "--output", "json"], "list workspace agents"
    )
    workspace_agents = json_collection(payload, "agents", "list workspace agents")
    by_name = {str(agent.get("name")): agent for agent in workspace_agents}
    changes: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for manifest, path in sources:
        cloud_agent = by_name.get(str(manifest["name"]))
        if cloud_agent is None or not cloud_agent.get("id"):
            raise ValueError(f"workspace agent not found: {manifest['name']}")
        detail = json_output(
            ["multica", "agent", "get", str(cloud_agent["id"]), "--output", "json"],
            f"read workspace agent {manifest['name']}",
        )
        if isinstance(detail, dict) and isinstance(detail.get("agent"), dict):
            detail = detail["agent"]
        if not isinstance(detail, dict):
            raise ValueError(f"cannot read workspace agent {manifest['name']}: expected an object")
        instructions = path.read_text(encoding="utf-8")
        if detail.get("instructions") != instructions:
            changes.append((manifest, cloud_agent, instructions))

    if not changes:
        print("Workspace agent instructions are already current.")
        return 0

    print("Instruction sync plan:")
    for manifest, _, _ in changes:
        print(f"  • update {manifest['name']} from {manifest['instructions_file']}")
    if dry_run:
        return 0
    if not yes:
        if not sys.stdin.isatty():
            raise ValueError("instruction sync requires --yes in a non-interactive terminal")
        if input("\nPersist these instructions in Multica? [y/N] ").strip().lower() not in {
            "y",
            "yes",
        }:
            print("Cancelled.")
            return 1

    for manifest, cloud_agent, instructions in changes:
        ok, output = run(
            [
                "multica",
                "agent",
                "update",
                str(cloud_agent["id"]),
                "--instructions",
                instructions,
                "--output",
                "json",
            ]
        )
        if not ok:
            raise ValueError(
                f"cannot update workspace agent {manifest['name']}: "
                f"{first_line(output) or 'command failed'}"
            )
        print(f"  ✓ {manifest['name']} instructions persisted")
    return 0


def update(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    print("Updating MultiEngin manifests from the repository...")
    if dry_run:
        print("  would run: git pull --ff-only")
    elif subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT, check=False).returncode != 0:
        return 1
    selected_names = [agent["name"] for agent in selected]
    return start(select_agents(manifests(), selected_names, False), yes=yes, dry_run=dry_run)


def shell_profile(shell: str | None = None) -> Path:
    shell_name = Path(shell or os.environ.get("SHELL", "")).name
    if shell_name == "zsh":
        return Path.home() / ".zshrc"
    if shell_name == "bash":
        return Path.home() / ".bashrc"
    return Path.home() / ".profile"


def install_path(
    dry_run: bool,
    local_bin: Path = LOCAL_BIN,
    profile: Path | None = None,
) -> int:
    """Expose the repository launcher through a persistent user PATH entry."""
    launcher = ROOT / "bin" / "multiengin"
    destination = local_bin / "multiengin"
    profile = shell_profile() if profile is None else profile
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink() or destination.resolve() != launcher.resolve():
            raise ValueError(f"refusing to replace existing launcher: {destination}")
        link_change = False
    else:
        link_change = True

    home_local_bin = Path.home() / ".local" / "bin"
    path_value = "$HOME/.local/bin" if local_bin == home_local_bin else str(local_bin)
    path_lines = [f'export PATH="{path_value}:$PATH"']
    global_npm_bin = npm_global_bin()
    if global_npm_bin is not None and global_npm_bin.exists():
        npm_path_value = (
            "$HOME/" + str(global_npm_bin.relative_to(Path.home()))
            if global_npm_bin.is_relative_to(Path.home())
            else str(global_npm_bin)
        )
        path_lines.append(f'export PATH="{npm_path_value}:$PATH"')
    existing_profile = profile.read_text(encoding="utf-8") if profile.exists() else ""
    missing_path_lines = [line for line in path_lines if line not in existing_profile.splitlines()]

    if dry_run:
        if link_change:
            print(f"would link: {destination} -> {launcher}")
        for path_line in missing_path_lines:
            print(f"would add to {profile}: {path_line}")
        if not link_change and not missing_path_lines:
            print(f"MultiEngin is already installed in PATH via {destination}")
        return 0

    if link_change:
        local_bin.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(launcher)
    if missing_path_lines:
        profile.parent.mkdir(parents=True, exist_ok=True)
        separator = "" if not existing_profile or existing_profile.endswith("\n") else "\n"
        with profile.open("a", encoding="utf-8") as stream:
            stream.write(
                f"{separator}\n# MultiEngin launcher and managed runtime CLIs\n"
                + "\n".join(missing_path_lines)
                + "\n"
            )
    print(f"MultiEngin launcher: {destination}")
    print(f"PATH profile: {profile}")
    if missing_path_lines:
        print(f"Reload with: source {profile}")
    return 0


def configure_opencode(
    model: str,
    base_url: str,
    target: Path = OPENCODE_CONFIG,
) -> int:
    """Create a non-secret OpenCode configuration for an Ollama model host."""
    model_id = model.removeprefix("ollama/").strip()
    if not model_id or not re.fullmatch(r"[A-Za-z0-9._:/+-]+", model_id):
        raise ValueError("model must be a non-empty Ollama model ID")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an HTTP(S) URL with a host")
    if target.exists():
        raise ValueError(f"refusing to replace existing OpenCode configuration: {target}")
    payload = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (local)",
                "options": {"baseURL": base_url.rstrip("/")},
                "models": {model_id: {"name": f"Local {model_id}"}},
            }
        },
        "model": f"ollama/{model_id}",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    print(f"OpenCode local model: ollama/{model_id}")
    print(f"OpenCode configuration: {target}")
    return 0


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
    command_help = {
        "install-path": "install multiengin and managed runtime CLIs on the user PATH",
        "configure-opencode": "configure OpenCode to use an Ollama-hosted model",
        "start": "prepare this machine and bind selected workspace agents",
        "doctor": "check local tools, authentication, and workspace bindings",
        "agents": "list configured agents and their readiness",
        "status": "report host, workflow, squad, and agent readiness",
        "workflow-check": "validate the repository workflow contract",
        "squad-check": "validate the live Multica squad topology",
        "sync-instructions": "persist repository-owned instructions on workspace agents",
        "update": "pull manifest updates and reconcile selected agents",
        "stop": "stop only this machine's Multica daemon",
    }
    examples = """examples:
  First-time setup:
    multiengin install-path
    multiengin configure-opencode --model qwen3.5:2b

  Start iteration agents:
    multiengin start builder-01 reviewer-01
    multiengin start --all

  Inspect readiness:
    multiengin doctor builder-01
    multiengin agents --all
    multiengin status --all
    multiengin status --all --output json

  Validate workflow configuration:
    multiengin workflow-check
    multiengin squad-check

  Persist squad-leader orchestration:
    multiengin sync-instructions engineering-lead-01 --yes

  Maintain this worker:
    multiengin update builder-01 reviewer-01
    multiengin stop

Use `multiengin COMMAND --help` for command-specific options.
Agent arguments accept manifest names such as `builder-01` or agent IDs."""
    parser = argparse.ArgumentParser(
        prog="multiengin",
        description="Prepare and reconcile local runtimes for Multica engineering agents.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    for name in ("start", "doctor", "agents", "update", "status"):
        command = subparsers.add_parser(name, help=command_help[name], description=command_help[name])
        command.add_argument(
            "agents", nargs="*", metavar="AGENT", help="agent manifest name or agent ID"
        )
        command.add_argument("--all", action="store_true", help="select every configured agent")
        if name == "status":
            command.add_argument("--output", choices=("table", "json"), default="table")
        if name in {"start", "update"}:
            command.add_argument("--yes", action="store_true", help="do not ask before provisioning")
            command.add_argument("--dry-run", action="store_true", help="show mutations without performing them")
    sync_parser = subparsers.add_parser(
        "sync-instructions",
        help=command_help["sync-instructions"],
        description=command_help["sync-instructions"],
    )
    sync_parser.add_argument(
        "agents", nargs="*", metavar="AGENT", help="agent manifest name or agent ID"
    )
    sync_parser.set_defaults(all=False)
    sync_parser.add_argument("--yes", action="store_true", help="do not ask before updating agents")
    sync_parser.add_argument("--dry-run", action="store_true", help="show updates without applying them")
    for name in ("workflow-check", "squad-check"):
        command = subparsers.add_parser(name, help=command_help[name], description=command_help[name])
        command.add_argument("--output", choices=("table", "json"), default="table")
    path_parser = subparsers.add_parser(
        "install-path", help=command_help["install-path"], description=command_help["install-path"]
    )
    path_parser.add_argument("--dry-run", action="store_true")
    opencode_parser = subparsers.add_parser(
        "configure-opencode",
        help=command_help["configure-opencode"],
        description=command_help["configure-opencode"],
    )
    opencode_parser.add_argument("--model", required=True, help="installed Ollama model ID")
    opencode_parser.add_argument(
        "--base-url", default="http://127.0.0.1:11434/v1", help="Ollama OpenAI-compatible endpoint"
    )
    stop_parser = subparsers.add_parser(
        "stop", help=command_help["stop"], description=command_help["stop"]
    )
    stop_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "stop":
            return stop(args.dry_run)
        if args.command == "install-path":
            return install_path(args.dry_run)
        if args.command == "configure-opencode":
            return configure_opencode(args.model, args.base_url)
        if args.command == "workflow-check":
            return workflow_check_command(args.output)
        if args.command == "squad-check":
            return squad_check_command(args.output)
        selected = select_agents(manifests(), args.agents, args.all)
        if args.command == "sync-instructions":
            return sync_instructions(selected, args.yes, args.dry_run)
        if args.command == "doctor":
            return doctor(selected)
        if args.command == "agents":
            return list_agents(selected)
        if args.command == "status":
            return status_command(selected, args.output)
        if args.command == "start":
            return start(selected, args.yes, args.dry_run)
        return update(selected, args.yes, args.dry_run)
    except (ValueError, OSError) as error:
        print(f"MultiEngin error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
