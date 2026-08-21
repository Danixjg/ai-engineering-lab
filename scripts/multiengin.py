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
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".ai" / "agents"
RUNTIME_MANIFEST = ROOT / ".ai" / "runtime" / "runtime-manifest.yaml"
LOCAL_BIN = Path.home() / ".local" / "bin"
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
    node_ok, node_version = run(["node", "--version"])
    checks.append(Check("Node", node_ok and version_at_least(node_version, compatibility["node"]), f"requires {compatibility['node']}+"))
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
            print(f"  [{index}] {agent['name']}  ({runtime['provider']}: {runtime['executable']})")
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
    if dry_run:
        print(f"  would install {provider} runtime ({minimum}+)" )
        return True
    if provider == "kiro":
        print("  installing Kiro CLI from its official installer...")
        return subprocess.run("curl -fsSL https://cli.kiro.dev/install | bash", shell=True, check=False).returncode == 0
    if provider == "codex":
        if not shutil.which("npm"):
            print("  Node/npm is required before Codex can be installed.")
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


def start(selected: list[dict[str, Any]], yes: bool, dry_run: bool) -> int:
    print("MultiEngin\nPortable Engineering Runtime\n")
    print("Selected: " + ", ".join(agent["name"] for agent in selected))
    missing_runtimes = [agent for agent in selected if not runtime_check(agent).passed]
    auths = sorted({auth for agent in selected for auth in agent.get("authentication", {}).get("required", []) if not authentication_check(auth).passed})
    missing_dependencies = sorted({check.name for agent in selected for check in agent_checks(agent) if not check.passed and check.blocking and check.name in {"git", "Docker"}})
    if missing_runtimes or auths or missing_dependencies:
        print("\nPlan:")
        for agent in missing_runtimes:
            print(f"  • install required runtime for {agent['name']}: {agent['runtime']['provider']}")
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
    for authentication in auths:
        if not login(authentication, dry_run):
            return 1
    if not run(["multica", "daemon", "status", "--output", "json"])[1].find('"status": "running"') >= 0:
        print("Starting Multica daemon...")
        if not dry_run and subprocess.run(["multica", "daemon", "start"], check=False).returncode != 0:
            return 1

    print("Built-in Kiro and Codex runtimes are detected and registered by the Multica daemon.")
    print("Skills remain cloud-managed and are synchronized through the selected Multica workspace.")
    return doctor(selected, include_core=True)


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
