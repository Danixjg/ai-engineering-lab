#!/usr/bin/env python3
"""Local-first Codex engineering squad runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


LAB_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = LAB_ROOT / ".englab"
PLAN_SCHEMA = LAB_ROOT / ".ai" / "schemas" / "local-plan.schema.json"
RESULT_SCHEMA = LAB_ROOT / ".ai" / "schemas" / "local-agent-result.schema.json"
ROLE_FILES = {
    "lead": LAB_ROOT / ".kiro" / "agents" / "local-lead.md",
    "builder": LAB_ROOT / ".kiro" / "agents" / "builder.md",
    "integrator": LAB_ROOT / ".kiro" / "agents" / "integrator.md",
    "verifier": LAB_ROOT / ".kiro" / "agents" / "verifier.md",
    "reviewer": LAB_ROOT / ".kiro" / "agents" / "reviewer.md",
    "security-adversary": LAB_ROOT / ".kiro" / "agents" / "security-adversary.md",
    "judge": LAB_ROOT / ".kiro" / "agents" / "judge.md",
}
SUCCESS_STATUS = {
    "builder": "completed",
    "integrator": "integrated",
    "verifier": "pass",
    "reviewer": "pass",
    "security-adversary": "pass",
    "judge": "pass",
}


@dataclass(frozen=True)
class Worktree:
    role: str
    path: Path
    branch: str
    base_sha: str


@dataclass(frozen=True)
class CodexInvocation:
    role: str
    worktree: Worktree
    prompt: str
    sandbox: str
    output_path: Path
    event_log: Path
    error_log: Path


CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


class NeedsHumanError(ValueError):
    """Raised when a safe local workflow cannot proceed without a user decision."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_command_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def command_output(
    command: list[str], cwd: Path, description: str, runner: CommandRunner = default_command_runner
) -> str:
    completed = runner(command, cwd)
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        first = next((line.strip() for line in output.splitlines() if line.strip()), "command failed")
        raise ValueError(f"cannot {description}: {first}")
    return completed.stdout.strip()


def git(repo: Path, *args: str, runner: CommandRunner = default_command_runner) -> str:
    return command_output(["git", *args], repo, f"run git {' '.join(args)}", runner)


def repository_root(path: Path, runner: CommandRunner = default_command_runner) -> Path:
    resolved = path.resolve()
    root = git(resolved, "rev-parse", "--show-toplevel", runner=runner)
    return Path(root).resolve()


def resolve_commit(repo: Path, ref: str, runner: CommandRunner = default_command_runner) -> str:
    sha = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", runner=runner)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"git returned an invalid commit for {ref!r}: {sha!r}")
    return sha


def slug(value: str, fallback: str = "task") -> str:
    rendered = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return rendered[:48] or fallback


def project_key(repo: Path) -> str:
    digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{slug(repo.name, 'repo')}-{digest}"


def new_run_id(issue_file: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{slug(issue_file.stem)}"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"{description} was not produced: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{description} is not valid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def role_instructions(role: str) -> str:
    path = ROLE_FILES.get(role)
    if path is None or not path.is_file():
        raise ValueError(f"missing local role instructions for {role}: {path}")
    return path.read_text(encoding="utf-8")


def clean_worktree(repo: Path, runner: CommandRunner = default_command_runner) -> bool:
    return not git(repo, "status", "--porcelain", runner=runner)


def create_worktree(
    repo: Path,
    root: Path,
    run_id: str,
    role: str,
    base_sha: str,
    runner: CommandRunner = default_command_runner,
) -> Worktree:
    safe_role = slug(role, "agent")
    path = (root / safe_role).resolve()
    branch = f"englab/{slug(run_id)}/{safe_role}"
    if path.exists():
        raise ValueError(f"worktree path already exists: {path}")
    existing = runner(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo)
    if existing.returncode == 0:
        raise ValueError(f"worktree branch already exists: {branch}")
    path.parent.mkdir(parents=True, exist_ok=True)
    command_output(
        ["git", "worktree", "add", "-b", branch, str(path), base_sha],
        repo,
        f"create {role} worktree",
        runner,
    )
    return Worktree(role=role, path=path, branch=branch, base_sha=base_sha)


def codex_command(
    invocation: CodexInvocation,
    schema: Path,
    model: str | None,
    profile: str | None,
) -> list[str]:
    command = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        invocation.sandbox,
        "--cd",
        str(invocation.worktree.path),
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(invocation.output_path),
    ]
    if model:
        command.extend(["--model", model])
    if profile:
        command.extend(["--profile", profile])
    command.append(invocation.prompt)
    return command


def invoke_codex(
    invocation: CodexInvocation,
    schema: Path,
    model: str | None,
    profile: str | None,
    runner: CommandRunner = default_command_runner,
) -> dict[str, Any]:
    command = codex_command(invocation, schema, model, profile)
    completed = runner(command, invocation.worktree.path)
    invocation.event_log.parent.mkdir(parents=True, exist_ok=True)
    invocation.event_log.write_text(completed.stdout, encoding="utf-8")
    invocation.error_log.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        detail = next(
            (line.strip() for line in completed.stderr.splitlines() if line.strip()),
            f"exit code {completed.returncode}",
        )
        raise ValueError(f"{invocation.role} Codex run failed: {detail}")
    return read_object(invocation.output_path, f"{invocation.role} result")


def validate_plan(payload: dict[str, Any], max_builders: int) -> dict[str, Any]:
    required = {
        "schema_version",
        "status",
        "task_id",
        "objective",
        "acceptance_criteria",
        "builder_tasks",
        "questions",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"local plan is missing: {', '.join(missing)}")
    if payload.get("status") == "needs_human":
        questions = payload.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError("a plan that needs human input must include questions")
        raise NeedsHumanError("planning needs human input: " + " | ".join(map(str, questions)))
    if payload.get("status") != "ready":
        raise ValueError(f"local plan returned invalid status {payload.get('status')!r}")
    tasks = payload.get("builder_tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("local plan must contain at least one builder task")
    if len(tasks) > max_builders:
        raise ValueError(f"local plan produced {len(tasks)} builder tasks; maximum is {max_builders}")
    task_ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("each builder task must be an object")
        for field in ("task_id", "title", "objective", "acceptance_criteria", "scope"):
            if not task.get(field):
                raise ValueError(f"builder task is missing {field}")
        task_ids.append(str(task["task_id"]))
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("builder task IDs must be unique")
    return payload


def validate_result(
    payload: dict[str, Any],
    role: str,
    expected_sha: str | None = None,
    require_success: bool = True,
) -> dict[str, Any]:
    if payload.get("role") != role:
        raise ValueError(f"{role} result identifies role {payload.get('role')!r}")
    expected_status = SUCCESS_STATUS[role]
    allowed_statuses = {
        "builder": {"completed", "failed", "blocked", "needs_human"},
        "integrator": {"integrated", "conflict", "blocked", "needs_human"},
        "verifier": {"pass", "fail", "blocked", "needs_human"},
        "reviewer": {"pass", "fail", "blocked", "needs_human"},
        "security-adversary": {"pass", "fail", "blocked", "needs_human"},
        "judge": {"pass", "fail", "blocked", "needs_human"},
    }
    if payload.get("status") not in allowed_statuses[role]:
        raise ValueError(f"{role} returned invalid status {payload.get('status')!r}")
    if require_success and payload.get("status") != expected_status:
        raise ValueError(
            f"{role} did not succeed: {payload.get('status') or 'missing status'} — "
            f"{payload.get('summary') or 'no summary'}"
        )
    commit_sha = payload.get("commit_sha")
    if expected_sha is not None and commit_sha != expected_sha:
        raise ValueError(f"{role} reviewed {commit_sha!r}; expected {expected_sha}")
    if role in {"builder", "integrator"} and not (
        isinstance(commit_sha, str) and re.fullmatch(r"[0-9a-f]{40}", commit_sha)
    ):
        raise ValueError(f"{role} result is missing commit_sha")
    return payload


def ensure_head(
    worktree: Worktree, reported_sha: str, runner: CommandRunner = default_command_runner
) -> None:
    actual = resolve_commit(worktree.path, "HEAD", runner)
    if actual != reported_sha:
        raise ValueError(
            f"{worktree.role} reported {reported_sha}, but its worktree HEAD is {actual}"
        )


def ensure_candidate_unchanged(
    worktree: Worktree, candidate_sha: str, runner: CommandRunner = default_command_runner
) -> None:
    ensure_head(worktree, candidate_sha, runner)
    unstaged = runner(["git", "diff", "--quiet"], worktree.path)
    staged = runner(["git", "diff", "--cached", "--quiet"], worktree.path)
    if unstaged.returncode != 0 or staged.returncode != 0:
        raise ValueError(f"{worktree.role} modified the candidate worktree")


def prompt_block(role: str, task: str) -> str:
    return (
        f"{role_instructions(role)}\n\n"
        "## Local runner contract\n\n"
        "You are running in an isolated Git worktree managed by englab. Follow the role "
        "boundaries above. Do not push, merge, create a pull request, or touch another "
        "worktree. The supplied EngLab output schema replaces any output schema named in "
        "the role instructions. Return only JSON conforming to the supplied schema.\n\n"
        f"## Assigned task\n\n{task}\n"
    )


class LocalSquadRun:
    def __init__(
        self,
        repo: Path,
        issue_file: Path,
        base_ref: str,
        max_builders: int,
        model: str | None,
        profile: str | None,
        run_id: str | None = None,
        state_root: Path = STATE_ROOT,
        runner: CommandRunner = default_command_runner,
        codex_runner: Callable[..., dict[str, Any]] = invoke_codex,
    ) -> None:
        self.runner = runner
        self.codex_runner = codex_runner
        self._state_lock = threading.Lock()
        self.repo = repository_root(repo, runner)
        self.issue_file = issue_file.resolve()
        if not self.issue_file.is_file():
            raise ValueError(f"issue file does not exist: {self.issue_file}")
        self.issue = self.issue_file.read_text(encoding="utf-8").strip()
        if not self.issue:
            raise ValueError("issue file is empty")
        self.base_ref = base_ref
        self.base_sha = resolve_commit(self.repo, base_ref, runner)
        self.max_builders = max_builders
        self.model = model
        self.profile = profile
        self.run_id = run_id or new_run_id(self.issue_file)
        self.project_root = state_root.resolve() / "projects" / project_key(self.repo)
        self.run_dir = self.project_root / "runs" / self.run_id
        self.worktree_root = self.project_root / "worktrees" / self.run_id
        self.state_file = self.run_dir / "state.json"
        if self.run_dir.exists() or self.worktree_root.exists():
            raise ValueError(f"run already exists: {self.run_id}")
        self.state: dict[str, Any] = {
            "schema_version": "0.1",
            "run_id": self.run_id,
            "status": "created",
            "repository": str(self.repo),
            "issue_file": str(self.issue_file),
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "worktrees": {},
            "artifacts": {},
            "candidate_sha": None,
            "errors": [],
        }

    def persist(self, status: str | None = None) -> None:
        with self._state_lock:
            if status:
                self.state["status"] = status
            self.state["updated_at"] = utc_now()
            atomic_json(self.state_file, self.state)

    def worktree(self, role: str, base_sha: str) -> Worktree:
        tree = create_worktree(
            self.repo, self.worktree_root, self.run_id, role, base_sha, self.runner
        )
        self.state["worktrees"][role] = {
            "path": str(tree.path),
            "branch": tree.branch,
            "base_sha": tree.base_sha,
        }
        self.persist()
        return tree

    def invocation(
        self, role: str, tree: Worktree, prompt: str, sandbox: str, artifact_name: str
    ) -> CodexInvocation:
        artifact = self.run_dir / "artifacts" / f"{artifact_name}.json"
        logs = self.run_dir / "logs"
        self.state["artifacts"][artifact_name] = str(artifact)
        self.persist()
        return CodexInvocation(
            role=role,
            worktree=tree,
            prompt=prompt,
            sandbox=sandbox,
            output_path=artifact,
            event_log=logs / f"{artifact_name}.jsonl",
            error_log=logs / f"{artifact_name}.stderr.log",
        )

    def codex(self, invocation: CodexInvocation, schema: Path = RESULT_SCHEMA) -> dict[str, Any]:
        return self.codex_runner(
            invocation, schema, self.model, self.profile, runner=self.runner
        )

    def plan(self) -> dict[str, Any]:
        self.persist("planning")
        tree = self.worktree("lead", self.base_sha)
        task = (
            f"Repository: {self.repo}\nBase commit: {self.base_sha}\n"
            f"Maximum independent builder tasks: {self.max_builders}\n\n"
            f"User issue:\n{self.issue}\n\n"
            "Create an implementation plan. Split only genuinely independent work into parallel "
            "builder tasks; otherwise return one task. Every builder task must be independently "
            "committable from the same base commit."
        )
        invocation = self.invocation(
            "lead", tree, prompt_block("lead", task), "read-only", "plan"
        )
        plan = validate_plan(self.codex(invocation, PLAN_SCHEMA), self.max_builders)
        self.state["task_id"] = plan["task_id"]
        self.persist("building")
        return plan

    def run_builder(
        self, plan: dict[str, Any], task: dict[str, Any], tree: Worktree
    ) -> dict[str, Any]:
        role_key = f"builder-{slug(str(task['task_id']))}"
        assignment = {
            "parent_task_id": plan["task_id"],
            "objective": plan["objective"],
            "global_acceptance_criteria": plan["acceptance_criteria"],
            "builder_task": task,
            "base_sha": self.base_sha,
            "branch": tree.branch,
        }
        prompt = prompt_block(
            "builder",
            json.dumps(assignment, indent=2)
            + "\n\nImplement only this builder task. Run relevant checks and commit all intended "
            "changes. The returned commit_sha must equal worktree HEAD.",
        )
        invocation = self.invocation(
            "builder", tree, prompt, "workspace-write", role_key
        )
        result = validate_result(self.codex(invocation), "builder")
        if result.get("task_id") != task["task_id"]:
            raise ValueError(
                f"builder returned task_id {result.get('task_id')!r}; expected {task['task_id']!r}"
            )
        ensure_head(tree, str(result["commit_sha"]), self.runner)
        result["worktree_role"] = role_key
        return result

    def build(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = list(plan["builder_tasks"])
        prepared = [
            (
                task,
                self.worktree(f"builder-{slug(str(task['task_id']))}", self.base_sha),
            )
            for task in tasks
        ]
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(self.max_builders, len(tasks))) as pool:
            futures = {
                pool.submit(self.run_builder, plan, task, tree): task for task, tree in prepared
            }
            for future in as_completed(futures):
                results.append(future.result())
        by_task = {str(result["task_id"]): result for result in results}
        ordered = [by_task[str(task["task_id"])] for task in tasks]
        self.persist("integrating")
        return ordered

    def integrate(self, plan: dict[str, Any], builders: list[dict[str, Any]]) -> dict[str, Any]:
        tree = self.worktree("integrator", self.base_sha)
        source_commits = [str(result["commit_sha"]) for result in builders]
        assignment = {
            "task_id": plan["task_id"],
            "base_sha": self.base_sha,
            "target_branch": tree.branch,
            "source_commits_in_order": source_commits,
            "builder_results": builders,
            "acceptance_criteria": plan["acceptance_criteria"],
        }
        prompt = prompt_block(
            "integrator",
            json.dumps(assignment, indent=2)
            + "\n\nIntegrate the source commits in the listed order from this clean base. Resolve "
            "only mechanical conflicts within the authorized task; otherwise return conflict. "
            "Run repository checks and leave the integrated candidate committed at HEAD.",
        )
        invocation = self.invocation(
            "integrator", tree, prompt, "workspace-write", "integration"
        )
        result = validate_result(self.codex(invocation), "integrator")
        ensure_head(tree, str(result["commit_sha"]), self.runner)
        self.state["candidate_sha"] = result["commit_sha"]
        self.persist("reviewing")
        return result

    def run_review(
        self,
        role: str,
        plan: dict[str, Any],
        integration: dict[str, Any],
        tree: Worktree,
    ) -> dict[str, Any]:
        candidate = str(integration["commit_sha"])
        assignment = {
            "task_id": plan["task_id"],
            "objective": plan["objective"],
            "acceptance_criteria": plan["acceptance_criteria"],
            "candidate_sha": candidate,
            "integration_result": integration,
        }
        sandbox = "workspace-write" if role == "verifier" else "read-only"
        prompt = prompt_block(
            role,
            json.dumps(assignment, indent=2)
            + "\n\nIndependently evaluate exactly candidate_sha. Do not commit or alter the "
            "candidate. Return pass only when supported by evidence.",
        )
        invocation = self.invocation(role, tree, prompt, sandbox, role)
        result = validate_result(
            self.codex(invocation), role, candidate, require_success=False
        )
        ensure_candidate_unchanged(tree, candidate, self.runner)
        return result

    def review(
        self, plan: dict[str, Any], integration: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        roles = ("verifier", "reviewer", "security-adversary")
        candidate = str(integration["commit_sha"])
        prepared = {role: self.worktree(role, candidate) for role in roles}
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            futures = {
                pool.submit(self.run_review, role, plan, integration, prepared[role]): role
                for role in roles
            }
            for future in as_completed(futures):
                role = futures[future]
                results[role] = future.result()
        self.persist("judging")
        return results

    def judge(
        self,
        plan: dict[str, Any],
        integration: dict[str, Any],
        reviews: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        candidate = str(integration["commit_sha"])
        tree = self.worktree("judge", candidate)
        assignment = {
            "task_id": plan["task_id"],
            "objective": plan["objective"],
            "acceptance_criteria": plan["acceptance_criteria"],
            "candidate_sha": candidate,
            "integration_result": integration,
            "independent_reviews": reviews,
        }
        prompt = prompt_block(
            "judge",
            json.dumps(assignment, indent=2)
            + "\n\nAggregate the evidence without changing the candidate. A pass is a "
            "recommendation for explicit human approval, not merge authority.",
        )
        invocation = self.invocation("judge", tree, prompt, "read-only", "judgment")
        result = validate_result(
            self.codex(invocation), "judge", candidate, require_success=False
        )
        ensure_candidate_unchanged(tree, candidate, self.runner)
        self.persist("ready_for_human" if result.get("status") == "pass" else "needs_human")
        return result

    def execute(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.persist()
        try:
            plan = self.plan()
            builders = self.build(plan)
            integration = self.integrate(plan, builders)
            reviews = self.review(plan, integration)
            judgment = self.judge(plan, integration, reviews)
        except NeedsHumanError as error:
            self.state["errors"].append(str(error))
            self.persist("needs_human")
            return {
                "run_id": self.run_id,
                "status": self.state["status"],
                "candidate_sha": None,
                "state_file": str(self.state_file),
                "judgment": None,
            }
        except Exception as error:
            self.state["errors"].append(str(error))
            self.persist("failed")
            raise
        return {
            "run_id": self.run_id,
            "status": self.state["status"],
            "candidate_sha": self.state["candidate_sha"],
            "state_file": str(self.state_file),
            "judgment": judgment,
        }


def doctor(repo: Path, runner: CommandRunner = default_command_runner) -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        root = repository_root(repo, runner)
        checks.append(("Git repository", True, str(root)))
    except ValueError as error:
        checks.append(("Git repository", False, str(error)))
        root = repo.resolve()
    checks.append(("Codex CLI", bool(shutil.which("codex")), "install and authenticate Codex"))
    if shutil.which("codex"):
        auth = runner(["codex", "login", "status"], root)
        checks.append(("Codex authentication", auth.returncode == 0, "run: codex login"))
    if checks[0][1]:
        checks.append(("Clean worktree", clean_worktree(root, runner), "commit or stash local changes"))
    required = [PLAN_SCHEMA, RESULT_SCHEMA, *ROLE_FILES.values()]
    missing = [str(path.relative_to(LAB_ROOT)) for path in required if not path.is_file()]
    checks.append(("Local workflow files", not missing, f"missing: {', '.join(missing)}"))
    print("EngLab Local Runner Check\n")
    for name, passed, detail in checks:
        mark = "✓" if passed else "✗"
        suffix = f"  ({detail})" if detail and (not passed or name == "Git repository") else ""
        print(f"{mark} {name}{suffix}")
    return 0 if all(passed for _, passed, _ in checks) else 1


def find_state(repo: Path, run_id: str | None) -> Path:
    project = STATE_ROOT / "projects" / project_key(repo)
    runs = project / "runs"
    if run_id:
        path = runs / run_id / "state.json"
        if not path.is_file():
            raise ValueError(f"run not found: {run_id}")
        return path
    candidates = sorted(runs.glob("*/state.json"), reverse=True) if runs.exists() else []
    if not candidates:
        raise ValueError(f"no local runs found for {repo}")
    return candidates[0]


def status(repo: Path, run_id: str | None, output: str) -> int:
    root = repository_root(repo)
    payload = read_object(find_state(root, run_id), "run state")
    if output == "json":
        print(json.dumps(payload, indent=2))
    else:
        print(f"EngLab run: {payload['run_id']}")
        print(f"Status: {payload['status']}")
        print(f"Repository: {payload['repository']}")
        print(f"Base: {payload['base_sha']}")
        if payload.get("candidate_sha"):
            print(f"Candidate: {payload['candidate_sha']}")
        print(f"State: {find_state(root, str(payload['run_id']))}")
        if payload.get("errors"):
            print("Errors:")
            for error in payload["errors"]:
                print(f"  - {error}")
    return 0 if payload.get("status") != "failed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="englab",
        description="Run an isolated local Codex engineering squad over a Git repository.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="check local runner readiness")
    doctor_parser.add_argument("--repo", type=Path, default=Path.cwd())

    run_parser = subparsers.add_parser("run", help="run a task through the local squad")
    run_parser.add_argument("issue", type=Path, help="Markdown or text file describing the task")
    run_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="target Git repository")
    run_parser.add_argument("--base", default="HEAD", help="base ref for every worktree")
    run_parser.add_argument("--max-builders", type=int, default=2, choices=range(1, 9))
    run_parser.add_argument("--model", help="Codex model override")
    run_parser.add_argument("--profile", help="Codex configuration profile")
    run_parser.add_argument("--run-id", help="stable run identifier (mainly for automation)")
    run_parser.add_argument("--dry-run", action="store_true", help="validate and show the run plan")

    status_parser = subparsers.add_parser("status", help="show durable local run state")
    status_parser.add_argument("run_id", nargs="?")
    status_parser.add_argument("--repo", type=Path, default=Path.cwd())
    status_parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            return doctor(args.repo)
        if args.command == "status":
            return status(args.repo, args.run_id, args.output)
        if not clean_worktree(repository_root(args.repo)) and args.base == "HEAD":
            raise ValueError(
                "target worktree has uncommitted changes; commit or stash them, or select an "
                "explicit committed --base"
            )
        local_run = LocalSquadRun(
            repo=args.repo,
            issue_file=args.issue,
            base_ref=args.base,
            max_builders=args.max_builders,
            model=args.model,
            profile=args.profile,
            run_id=args.run_id,
        )
        if args.dry_run:
            print("EngLab local squad dry run")
            print(f"Repository: {local_run.repo}")
            print(f"Base: {local_run.base_sha}")
            print(f"Issue: {local_run.issue_file}")
            print(f"Run ID: {local_run.run_id}")
            print(f"Maximum builders: {local_run.max_builders}")
            print("Stages: lead -> builders (parallel) -> integrator -> reviews (parallel) -> judge")
            return 0
        result = local_run.execute()
        print(json.dumps(result, indent=2))
        if result["status"] == "ready_for_human":
            print("\nCandidate is ready for explicit human review; EngLab did not merge it.")
            return 0
        print("\nEngLab stopped for human input; inspect the durable state and artifacts.")
        return 1
    except (OSError, ValueError) as error:
        print(f"EngLab error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
