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
import signal
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".ai" / "agents"
RUNTIME_MANIFEST = ROOT / ".ai" / "runtime" / "runtime-manifest.yaml"
MODEL_POLICY = ROOT / ".ai" / "runtime" / "model-policy.yaml"
LOCAL_BIN = Path.home() / ".local" / "bin"
OPENCODE_BIN = Path.home() / ".opencode" / "bin"
GLOBAL_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"
LOCAL_STATE = Path.home() / ".local" / "state" / "multiengin"
OLLAMA_PID = LOCAL_STATE / "ollama.pid"
OLLAMA_LOG = LOCAL_STATE / "ollama.log"
# Runtime installers place user-owned executables here on fresh hosts. Include
# it before provisioning so the same `start` invocation can find them.
os.environ["PATH"] = (
    f"{OPENCODE_BIN}{os.pathsep}{LOCAL_BIN}{os.pathsep}"
    f"{os.environ.get('PATH', '')}"
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


def runtime_specs() -> dict[str, dict[str, Any]]:
    return runtime_manifest()["runtimes"]


def model_backends() -> dict[str, dict[str, Any]]:
    return runtime_manifest()["model_backends"]


def model_policy() -> dict[str, Any]:
    return load_document(MODEL_POLICY)


def run(command: list[str], cwd: Path = ROOT) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False, cwd=cwd
        )
    except FileNotFoundError:
        return False, "command not found"
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output


def first_line(output: str) -> str:
    return next((line.strip() for line in output.splitlines() if line.strip()), "")


def command_version(command: str) -> tuple[bool, str]:
    ok, output = run([command, "--version"])
    return ok, output


def version_at_least(
    output: str, minimum: str, version_pattern: str | None = None
) -> bool:
    pattern = version_pattern or r"(?<!\d)(\d+(?:\.\d+){0,2})(?!\d)"
    matches = list(re.finditer(pattern, output))
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
    provider = runtime["provider"]
    command = runtime["executable"]
    specification = runtime_specs().get(provider)
    if specification is None:
        return Check(f"{agent['name']} runtime", False, f"unknown provider {provider}")
    if specification["executable"] != command:
        return Check(
            f"{agent['name']} runtime",
            False,
            f"manifest executable {command} does not match provider adapter",
        )
    minimum = runtime.get("version", {}).get("minimum")
    if not shutil.which(command):
        return Check(f"{agent['name']} runtime", False, f"{command} is not installed")
    ok, output = command_version(command)
    if not ok:
        return Check(f"{agent['name']} runtime", False, f"cannot read {command} version")
    if minimum and not version_at_least(
        output, minimum, specification["version_pattern"]
    ):
        return Check(f"{agent['name']} runtime", False, f"requires {minimum}+; found {first_line(output)}")
    configuration = specification.get("configuration")
    if configuration and not (ROOT / configuration).is_file():
        return Check(
            f"{agent['name']} runtime",
            False,
            f"runtime configuration is missing: {configuration}",
        )
    return Check(f"{agent['name']} runtime", True, first_line(output))


def authentication_check(name: str) -> Check:
    if name == "github":
        command, remedy = ["gh", "auth", "status"], "gh auth login"
    else:
        specification = runtime_specs().get(name)
        if specification is None:
            return Check(
                f"{name} authentication",
                False,
                "no local health-check adapter",
                True,
            )
        command = [
            specification["executable"],
            *specification["authentication_check"],
        ]
        remedy = " ".join(
            [specification["executable"], *specification["login"]]
        )
    if not shutil.which(command[0]):
        return Check(f"{name} authentication", False, f"{command[0]} is not installed")
    return Check(f"{name} authentication", authenticated(command), f"run: {remedy}")


def backend_check() -> Check:
    specification = model_backends()["ollama"]
    command = [specification["executable"], *specification["health_check"]]
    if not shutil.which(command[0]):
        return Check("Ollama server", False, "ollama is not installed")
    ok, output = run(command)
    detail = "" if ok else first_line(output)
    return Check("Ollama server", ok, detail or "run: ollama serve")


def global_model_configuration_check() -> Check:
    required = set(model_policy()["portfolio"]["required_models"])
    ok, output = run(["opencode", "models", "ollama"], cwd=Path.home())
    exposed = {line.strip() for line in output.splitlines() if line.strip()}
    return Check(
        "OpenCode global model config",
        ok and required <= exposed,
        "run: ./bin/multiengin start --all",
    )


def available_models() -> set[str]:
    specification = model_backends()["ollama"]
    ok, output = run([specification["executable"], "list"])
    if not ok:
        return set()
    lines = [line.split() for line in output.splitlines()[1:] if line.strip()]
    return {parts[0] for parts in lines if parts}


def model_check(agent: dict[str, Any]) -> Check:
    model = agent.get("runtime", {}).get("model", "")
    prefix = "ollama/"
    if not model.startswith(prefix):
        return Check(f"{agent['name']} model", False, f"unsupported model id {model}")
    local_name = model[len(prefix) :]
    if local_name not in available_models():
        return Check(
            f"{agent['name']} model",
            False,
            f"run: ollama pull {local_name}",
        )
    runtime = agent["runtime"]
    ok, output = run([runtime["executable"], "models", "ollama"])
    configured_models = {
        line.strip() for line in output.splitlines() if line.strip().startswith(prefix)
    }
    return Check(
        f"{agent['name']} model",
        ok and model in configured_models,
        "OpenCode's Ollama provider does not expose the pinned model",
    )


def dependency_check(dependency: str, optional: bool) -> Check:
    if dependency == "docker":
        passed = bool(shutil.which("docker")) and run(["docker", "info"])[0]
        return Check("Docker", passed, "CLI missing or daemon unavailable", not optional)
    return Check(dependency, bool(shutil.which(dependency)), "command not found", not optional)


def repository_check() -> Check:
    return Check("Repository access", (ROOT / ".git").exists(), "repository checkout unavailable")


def agent_checks(agent: dict[str, Any]) -> list[Check]:
    checks = [runtime_check(agent), backend_check(), model_check(agent)]
    dependencies = agent.get("dependencies", {})
    checks.extend(dependency_check(value, False) for value in dependencies.get("system", []))
    checks.extend(dependency_check(value, True) for value in dependencies.get("optional", []))
    checks.extend(authentication_check(value) for value in agent.get("authentication", {}).get("required", []))
    if "repository_access" in agent.get("health_checks", []):
        checks.append(repository_check())
    return checks


def core_checks() -> list[Check]:
    checks: list[Check] = []
    if not shutil.which("multica"):
        return [Check("Multica CLI", False, "run the approved Multica installation, then multica setup")]
    checks.append(Check("Multica CLI", True, first_line(run(["multica", "--version"])[1])))
    workspace_ok, _ = run(["multica", "workspace", "get", "--output", "json"])
    checks.append(Check("Multica workspace", workspace_ok, "run: multica setup"))
    daemon_ok, daemon = run(["multica", "daemon", "status", "--output", "json"])
    running = daemon_ok and re.search(r'"status"\s*:\s*"(?:running|ready)"', daemon) is not None
    checks.append(Check("Multica daemon", running, "run: multica daemon start"))

    compatibility = runtime_manifest()["compatibility"]
    python_ok, python_version = run(["python3", "--version"])
    checks.append(Check("Python", python_ok and version_at_least(python_version, compatibility["python"]), f"requires {compatibility['python']}+"))
    checks.append(backend_check())
    checks.append(global_model_configuration_check())
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
            print(
                f"  [{index}] {agent['name']}  "
                f"({runtime['provider']}: {runtime['model']})"
            )
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
    specification = runtime_specs().get(provider)
    if specification is None:
        print(f"  no runtime adapter is configured for provider: {provider}")
        return False
    if dry_run:
        print(f"  would provision {provider} runtime ({minimum}+)" )
        return True
    installer = specification["installer"]
    if installer == "opencode_cli":
        print("  installing OpenCode from its official installer...")
        return subprocess.run(
            "curl -fsSL https://opencode.ai/install | bash",
            shell=True,
            check=False,
        ).returncode == 0
    print(f"  {specification.get('installation_hint', f'install {provider} manually')}")
    return False


def publish_runtime_executable(provider: str, dry_run: bool) -> tuple[bool, bool]:
    """Expose a user-installed runtime on the PATH inherited by Multica."""
    specification = runtime_specs().get(provider)
    if specification is None:
        return False, False
    executable = specification["executable"]
    source_value = shutil.which(executable)
    if not source_value:
        return False, False
    source = Path(source_value).resolve()
    target = LOCAL_BIN / executable
    if target.exists():
        return True, False
    if target.is_symlink():
        print(f"  BLOCKED: replace the broken runtime link manually: {target}")
        return False, False
    if dry_run:
        print(f"  would expose {provider} to Multica: {target} -> {source}")
        return True, True
    try:
        LOCAL_BIN.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    except OSError as error:
        print(f"  BLOCKED: could not expose {provider} to Multica: {error}")
        return False, False
    print(f"  exposed {provider} to Multica: {target} -> {source}")
    return True, True


def publish_runtime_configuration(provider: str, dry_run: bool) -> tuple[bool, bool]:
    """Expose project runtime configuration to fresh Multica task worktrees."""
    specification = runtime_specs().get(provider)
    configuration = specification.get("configuration") if specification else None
    if provider != "opencode" or not configuration:
        return True, False
    source = (ROOT / configuration).resolve()
    target = GLOBAL_OPENCODE_CONFIG
    if not source.is_file():
        print(f"  BLOCKED: runtime configuration is missing: {configuration}")
        return False, False
    if target.exists():
        return True, False
    if target.is_symlink():
        print(f"  BLOCKED: replace the broken runtime config link manually: {target}")
        return False, False
    if dry_run:
        print(f"  would expose {provider} configuration: {target} -> {source}")
        return True, True
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    except OSError as error:
        print(f"  BLOCKED: could not expose {provider} configuration: {error}")
        return False, False
    print(f"  exposed {provider} configuration: {target} -> {source}")
    return True, True


def start_model_backend(dry_run: bool) -> bool:
    if backend_check().passed:
        return True
    specification = model_backends()["ollama"]
    executable = specification["executable"]
    if not shutil.which(executable):
        print("  Ollama is not installed; install it with the approved OS package.")
        return False
    if dry_run:
        print("  would start the local Ollama server")
        return True
    LOCAL_STATE.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    capacity = model_policy()["execution_stack"]["capacity"]
    environment.update(
        {
            "OLLAMA_CONTEXT_LENGTH": str(capacity["context_tokens"]),
            "OLLAMA_MAX_LOADED_MODELS": str(capacity["maximum_loaded_models"]),
            "OLLAMA_NUM_PARALLEL": str(capacity["maximum_parallel_tasks"]),
        }
    )
    log = OLLAMA_LOG.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [executable, *specification["server"]],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=environment,
    )
    log.close()
    OLLAMA_PID.write_text(str(process.pid), encoding="utf-8")
    for _ in range(20):
        if backend_check().passed:
            return True
        if process.poll() is not None:
            break
        time.sleep(0.5)
    print(f"  Ollama did not become ready; inspect {OLLAMA_LOG}")
    return False


def provision_model(model: str, dry_run: bool) -> bool:
    local_name = model.removeprefix("ollama/")
    build = model_policy().get("model_builds", {}).get(model)
    if build:
        source = build["source"]
        modelfile = ROOT / build["modelfile"]
        if not modelfile.is_file():
            print(f"  model build file is missing: {build['modelfile']}")
            return False
        if dry_run:
            print(f"  would build local model {local_name} from {source}")
            return True
        if source not in available_models() and subprocess.run(
            ["ollama", "pull", source], check=False, cwd=ROOT
        ).returncode != 0:
            return False
        return subprocess.run(
            ["ollama", "create", local_name, "-f", str(modelfile)],
            check=False,
            cwd=ROOT,
        ).returncode == 0
    if dry_run:
        print(f"  would pull local model {local_name}")
        return True
    return subprocess.run(
        ["ollama", "pull", local_name], check=False, cwd=ROOT
    ).returncode == 0


def stop_model_backend(dry_run: bool) -> bool:
    if not OLLAMA_PID.exists():
        return True
    if dry_run:
        print("would stop the MultiEngin-managed Ollama server")
        return True
    try:
        pid = int(OLLAMA_PID.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    OLLAMA_PID.unlink(missing_ok=True)
    return True


def login(authentication: str, dry_run: bool) -> bool:
    if authentication == "github":
        command = ["gh", "auth", "login"]
    else:
        specification = runtime_specs().get(authentication)
        command = (
            [specification["executable"], *specification["login"]]
            if specification
            else None
        )
    if not command or not shutil.which(command[0]):
        print(f"  cannot authenticate {authentication}: required CLI is not installed")
        return False
    if dry_run:
        print(f"  would run: {' '.join(command)}")
        return True
    return subprocess.run(command, check=False).returncode == 0


def start(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    print("MultiEngin\nPortable Engineering Runtime\n")
    print("Selected: " + ", ".join(agent["name"] for agent in selected))
    missing_runtimes = list(
        {
            agent["runtime"]["provider"]: agent
            for agent in selected
            if not runtime_check(agent).passed
        }.values()
    )
    backend_missing = not backend_check().passed
    installed_models = available_models() if not backend_missing else set()
    missing_models = sorted(
        {
            agent["runtime"]["model"]
            for agent in selected
            if agent["runtime"]["model"].removeprefix("ollama/")
            not in installed_models
        }
    )
    auths = sorted({auth for agent in selected for auth in agent.get("authentication", {}).get("required", []) if not authentication_check(auth).passed})
    missing_dependencies = sorted(
        {
            check.name
            for agent in selected
            for value in agent.get("dependencies", {}).get("system", [])
            for check in [dependency_check(value, False)]
            if not check.passed
        }
    )
    if missing_runtimes or backend_missing or missing_models or auths or missing_dependencies:
        print("\nPlan:")
        for agent in missing_runtimes:
            print(f"  • install required runtime for {agent['name']}: {agent['runtime']['provider']}")
        if backend_missing:
            print("  • start the local Ollama model server")
        for model in missing_models:
            action = "build" if model in model_policy().get("model_builds", {}) else "pull"
            print(f"  • {action} {model}")
        for auth in auths:
            print(f"  • authenticate {auth}")
        for dependency in missing_dependencies:
            print(f"  • install or start required dependency: {dependency}")
        if not yes and sys.stdin.isatty() and input("\nProceed? [Y/n] ").strip().lower() not in {"", "y", "yes"}:
            print("Cancelled.")
            return 1

    if not shutil.which("multica"):
        print("\nBLOCKED: Multica CLI is required. Install it and run `multica setup`, then retry.")
        return 1
    workspace_ok = run(["multica", "workspace", "get", "--output", "json"])[0]
    if not workspace_ok:
        print("\nConnecting this machine to Multica Cloud...")
        if not dry_run and subprocess.run(["multica", "setup"], check=False).returncode != 0:
            return 1
    for agent in missing_runtimes:
        if not install_runtime(agent, dry_run):
            return 1
    runtime_catalog_changed = False
    for provider in sorted({agent["runtime"]["provider"] for agent in selected}):
        published, changed = publish_runtime_executable(provider, dry_run)
        if not published:
            return 1
        runtime_catalog_changed = runtime_catalog_changed or changed
        configured, _ = publish_runtime_configuration(provider, dry_run)
        if not configured:
            return 1
    if not start_model_backend(dry_run):
        return 1
    for model in missing_models:
        if not provision_model(model, dry_run):
            return 1
    for authentication in auths:
        if not login(authentication, dry_run):
            return 1
    daemon_ok, daemon_output = run(
        ["multica", "daemon", "status", "--output", "json"]
    )
    daemon_status: dict[str, Any] = {}
    if daemon_ok:
        try:
            daemon_status = json.loads(daemon_output)
        except json.JSONDecodeError:
            daemon_ok = False
    daemon_running = daemon_ok and daemon_status.get("status") == "running"
    capacity = model_policy()["execution_stack"]["capacity"]
    daemon_command = [
        "multica",
        "daemon",
        "restart" if daemon_running else "start",
        "--max-concurrent-tasks",
        str(capacity["maximum_parallel_tasks"]),
    ]
    if runtime_catalog_changed and daemon_running:
        if int(daemon_status.get("active_task_count", 0)) > 0:
            print("\nBLOCKED: Multica has active tasks; restart it after they finish so it can discover OpenCode.")
            return 1
        print("Refreshing Multica runtime discovery...")
        if not dry_run and subprocess.run(daemon_command, check=False).returncode != 0:
            return 1
    elif not daemon_running:
        print("Starting Multica daemon...")
        if not dry_run and subprocess.run(daemon_command, check=False).returncode != 0:
            return 1

    providers = ", ".join(sorted(runtime_specs()))
    print(f"Configured {providers} harness is connected to the local Ollama model backend.")
    print("Skills remain cloud-managed; use project preflight to verify their live bindings.")
    return doctor(selected, include_core=True)


def json_collection(command: list[str], key: str) -> list[dict[str, Any]]:
    ok, output = run(command)
    if not ok:
        raise ValueError(f"Multica command failed ({' '.join(command[:3])}): {output}")
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError("Multica returned invalid JSON") from error
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [item for item in value[key] if isinstance(item, dict)]
    raise ValueError(f"Multica returned an unexpected {key} response")


def reconciliation_plan(
    selected: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    live_agents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    runtimes_by_id = {
        runtime.get("id"): runtime for runtime in runtimes if runtime.get("id")
    }
    online_by_provider: dict[str, list[dict[str, Any]]] = {}
    for runtime in runtimes:
        provider = runtime.get("provider")
        if provider and runtime.get("status") == "online":
            online_by_provider.setdefault(provider, []).append(runtime)
    live_by_name = {
        agent.get("name"): agent for agent in live_agents if agent.get("name")
    }
    changes: list[dict[str, Any]] = []
    errors: list[str] = []
    for manifest in selected:
        name = manifest["name"]
        desired_provider = manifest["runtime"]["provider"]
        desired_model = manifest["runtime"]["model"]
        live = live_by_name.get(name)
        if live is None:
            errors.append(f"live agent is missing: {name}")
            continue
        current_runtime = runtimes_by_id.get(live.get("runtime_id"), {})
        current_provider = current_runtime.get("provider")
        current_model = live.get("model") or ""
        if (
            current_provider == desired_provider
            and current_runtime.get("status") == "online"
            and current_model == desired_model
        ):
            continue
        if (
            current_provider == desired_provider
            and current_runtime.get("status") == "online"
        ):
            target_runtime = current_runtime
        else:
            candidates = online_by_provider.get(desired_provider, [])
            if len(candidates) != 1:
                errors.append(
                    f"{name} requires exactly one online {desired_provider} runtime; "
                    f"found {len(candidates)}"
                )
                continue
            target_runtime = candidates[0]
        changes.append(
            {
                "agent_id": live.get("id"),
                "name": name,
                "status": live.get("status"),
                "from_provider": current_provider,
                "to_provider": desired_provider,
                "from_model": current_model,
                "to_model": desired_model,
                "runtime_id": target_runtime["id"],
            }
        )
    return changes, errors


def reconcile(selected: list[dict[str, Any]], apply: bool) -> int:
    if not shutil.which("multica"):
        print("MultiEngin error: Multica CLI is not installed", file=sys.stderr)
        return 2
    runtimes = json_collection(
        ["multica", "runtime", "list", "--output", "json"], "runtimes"
    )
    live_agents = json_collection(
        ["multica", "agent", "list", "--output", "json"], "agents"
    )
    changes, errors = reconciliation_plan(selected, runtimes, live_agents)
    print("MultiEngin Runtime Reconciliation\n")
    for change in changes:
        activity = (
            f" [agent is {change['status']}]"
            if change.get("status") not in {"idle", None}
            else ""
        )
        print(
            f"  {change['name']}: {change['from_provider'] or 'unbound'} -> "
            f"{change['to_provider']}; {change['from_model'] or 'default'} -> "
            f"{change['to_model']}{activity}"
        )
    for error in errors:
        print(f"  BLOCKED: {error}")
    if errors:
        return 1
    if not changes:
        print("  Runtime bindings are already in sync.")
        return 0
    if not apply:
        print("\nPreview only. Re-run with --apply after active agent tasks finish.")
        return 0
    busy = [
        change for change in changes if change.get("status") not in {"idle", None}
    ]
    if busy:
        names = ", ".join(change["name"] for change in busy)
        print(f"\nBLOCKED: active agents cannot be rebound: {names}")
        return 1
    for change in changes:
        ok, output = run(
            [
                "multica",
                "agent",
                "update",
                change["agent_id"],
                "--runtime-id",
                change["runtime_id"],
                "--model",
                change["to_model"],
                "--output",
                "json",
            ]
        )
        if not ok:
            print(f"  FAILED: {change['name']}: {output}", file=sys.stderr)
            return 1
        print(
            f"  updated {change['name']} -> {change['to_provider']} / "
            f"{change['to_model']}"
        )
    return 0


def doctor(selected: list[dict[str, Any]], include_core: bool = True) -> int:
    print("MultiEngin Environment Check\n")
    core = core_checks() if include_core else []
    for check in core:
        print_check(check)
    if core:
        print()
    all_ready = ready(core)
    for agent in selected:
        checks = agent_checks(agent)
        status = "READY" if ready(checks) else "BLOCKED"
        print(f"{agent['name']}  {status}")
        for check in checks:
            print_check(check, "  ")
        print()
        all_ready = all_ready and ready(checks)
    return 0 if all_ready else 1


def list_agents(selected: list[dict[str, Any]]) -> int:
    print("Configured agents\n")
    for agent in selected:
        checks = agent_checks(agent)
        print(f"{agent['name']}")
        print(f"  Runtime: {agent['runtime']['provider']} ({agent['runtime']['executable']})")
        print(f"  Model: {agent['runtime']['model']}")
        print(f"  Local status: {'READY' if ready(checks) else 'BLOCKED'}")
        print(f"  Skills: {', '.join(agent.get('skills', []))}")
    return 0


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
        print("Multica CLI is not installed; stopping only managed model services.")
        return 0 if stop_model_backend(dry_run) else 1
    if dry_run:
        print("would run: multica daemon stop")
        stop_model_backend(True)
        return 0
    result = subprocess.run(["multica", "daemon", "stop"], check=False)
    if result.returncode == 0:
        print("Local Multica daemon stopped. The Multica Cloud workspace remains active.")
    backend_stopped = stop_model_backend(False)
    return result.returncode if result.returncode != 0 or backend_stopped else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "doctor", "agents", "update", "reconcile"):
        command = subparsers.add_parser(name)
        command.add_argument("agents", nargs="*", metavar="AGENT")
        command.add_argument("--all", action="store_true", help="select every configured agent")
        if name in {"start", "update"}:
            command.add_argument("--yes", action="store_true", help="do not ask before provisioning")
            command.add_argument("--dry-run", action="store_true", help="show mutations without performing them")
        if name == "reconcile":
            command.add_argument(
                "--apply", action="store_true", help="apply runtime binding changes"
            )
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
        if args.command == "reconcile":
            return reconcile(selected, args.apply)
        if args.command == "start":
            return start(selected, args.yes, args.dry_run)
        return update(selected, args.yes, args.dry_run)
    except (ValueError, OSError) as error:
        print(f"MultiEngin error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
