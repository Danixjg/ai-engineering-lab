"""Regression tests for the local-first Codex squad runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("englab", ROOT / "scripts" / "englab.py")
assert SPEC and SPEC.loader
englab = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = englab
SPEC.loader.exec_module(englab)


def command(directory: Path, *args: str) -> str:
    completed = subprocess.run(
        list(args), cwd=directory, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def initialize_repo(path: Path) -> str:
    path.mkdir()
    command(path, "git", "init", "--initial-branch=main")
    command(path, "git", "config", "user.email", "englab@example.test")
    command(path, "git", "config", "user.name", "EngLab Test")
    (path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    command(path, "git", "add", "README.md")
    command(path, "git", "commit", "-m", "initial")
    return command(path, "git", "rev-parse", "HEAD")


def result(
    role: str,
    task_id: str,
    status: str,
    commit_sha: str,
    summary: str = "completed",
) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "role": role,
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "commit_sha": commit_sha,
        "checks": [],
        "findings": [],
        "acceptance_criteria": [
            {"id": "AC-1", "status": "passed", "evidence": "fixture"}
        ],
    }


class FakeCodex:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.builder_commits: dict[str, str] = {}

    def __call__(
        self,
        invocation: englab.CodexInvocation,
        schema: Path,
        model: str | None,
        profile: str | None,
        *,
        runner: englab.CommandRunner,
    ) -> dict[str, object]:
        del schema, model, profile, runner
        if invocation.role == "lead":
            return {
                "schema_version": "0.1",
                "status": "ready",
                "task_id": "TASK-LOCAL-1",
                "objective": "Implement two independent fixture changes",
                "acceptance_criteria": [
                    {"id": "AC-1", "description": "Both files exist", "verification": "test"}
                ],
                "builder_tasks": [
                    {
                        "task_id": "TASK-A",
                        "title": "Add A",
                        "objective": "Add a.txt",
                        "acceptance_criteria": ["a.txt exists"],
                        "scope": ["a.txt"],
                    },
                    {
                        "task_id": "TASK-B",
                        "title": "Add B",
                        "objective": "Add b.txt",
                        "acceptance_criteria": ["b.txt exists"],
                        "scope": ["b.txt"],
                    },
                ],
                "questions": [],
            }
        if invocation.role == "builder":
            task_id = "TASK-A" if invocation.output_path.stem.endswith("task-a") else "TASK-B"
            filename = "a.txt" if task_id == "TASK-A" else "b.txt"
            with self.lock:
                (invocation.worktree.path / filename).write_text(task_id + "\n", encoding="utf-8")
                command(invocation.worktree.path, "git", "add", filename)
                command(invocation.worktree.path, "git", "commit", "-m", f"add {filename}")
                sha = command(invocation.worktree.path, "git", "rev-parse", "HEAD")
                self.builder_commits[task_id] = sha
            return result("builder", task_id, "completed", sha)
        if invocation.role == "integrator":
            with self.lock:
                for task_id in ("TASK-A", "TASK-B"):
                    command(
                        invocation.worktree.path,
                        "git",
                        "cherry-pick",
                        self.builder_commits[task_id],
                    )
                sha = command(invocation.worktree.path, "git", "rev-parse", "HEAD")
            return result("integrator", "TASK-LOCAL-1", "integrated", sha)
        candidate = command(invocation.worktree.path, "git", "rev-parse", "HEAD")
        return result(invocation.role, "TASK-LOCAL-1", "pass", candidate)


class EngLabTests(unittest.TestCase):
    def test_slug_is_safe_and_bounded(self) -> None:
        self.assertEqual(englab.slug("  Fix API / Parser! "), "fix-api-parser")
        self.assertLessEqual(len(englab.slug("x" * 100)), 48)

    def test_codex_command_uses_explicit_sandbox_and_structured_output(self) -> None:
        tree = englab.Worktree("reviewer", Path("/tmp/worktree"), "branch", "a" * 40)
        invocation = englab.CodexInvocation(
            role="reviewer",
            worktree=tree,
            prompt="review the candidate",
            sandbox="read-only",
            output_path=Path("/tmp/result.json"),
            event_log=Path("/tmp/events.jsonl"),
            error_log=Path("/tmp/error.log"),
        )
        rendered = englab.codex_command(
            invocation, ROOT / ".ai/schemas/local-agent-result.schema.json", None, None
        )
        self.assertEqual(rendered[:2], ["codex", "exec"])
        self.assertIn("--json", rendered)
        self.assertEqual(rendered[rendered.index("--sandbox") + 1], "read-only")
        self.assertIn("--output-schema", rendered)
        self.assertNotIn("danger-full-access", rendered)

    def test_create_worktree_uses_a_dedicated_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            repo = temporary / "repo"
            base = initialize_repo(repo)
            tree = englab.create_worktree(
                repo, repo / ".englab" / "worktrees", "RUN-1", "builder-a", base
            )
            self.assertTrue(tree.path.is_dir())
            self.assertEqual(tree.branch, "englab/run-1/builder-a")
            self.assertEqual(command(tree.path, "git", "rev-parse", "HEAD"), base)
            self.assertEqual(command(tree.path, "git", "branch", "--show-current"), tree.branch)

    def test_plan_rejects_more_tasks_than_authorized(self) -> None:
        payload = {
            "schema_version": "0.1",
            "status": "ready",
            "task_id": "TASK-1",
            "objective": "test",
            "acceptance_criteria": ["test"],
            "builder_tasks": [
                {
                    "task_id": f"TASK-{index}",
                    "title": "task",
                    "objective": "task",
                    "acceptance_criteria": ["done"],
                }
                for index in range(3)
            ],
            "questions": [],
        }
        with self.assertRaisesRegex(ValueError, "maximum is 2"):
            englab.validate_plan(payload, 2)

    def test_plan_stops_for_human_questions(self) -> None:
        payload = {
            "schema_version": "0.1",
            "status": "needs_human",
            "task_id": "TASK-1",
            "objective": "Choose an authentication policy",
            "acceptance_criteria": [{"id": "AC-1"}],
            "builder_tasks": [],
            "questions": ["Which identity provider is authorized?"],
        }
        with self.assertRaisesRegex(englab.NeedsHumanError, "identity provider"):
            englab.validate_plan(payload, 2)

    def test_failed_review_is_valid_evidence_for_judge(self) -> None:
        payload = result("reviewer", "TASK-1", "fail", "a" * 40)
        validated = englab.validate_result(
            payload, "reviewer", "a" * 40, require_success=False
        )
        self.assertEqual(validated["status"], "fail")

    def test_full_local_pipeline_reaches_human_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            repo = temporary / "repo"
            initialize_repo(repo)
            issue = temporary / "issue.md"
            issue.write_text("Add two independent fixture files.\n", encoding="utf-8")
            local_run = englab.LocalSquadRun(
                repo=repo,
                issue_file=issue,
                base_ref="HEAD",
                max_builders=2,
                model=None,
                profile=None,
                run_id="fixture-run",
                state_root=temporary / "state",
                codex_runner=FakeCodex(),
            )

            completed = local_run.execute()

            self.assertEqual(completed["status"], "ready_for_human")
            self.assertRegex(str(completed["candidate_sha"]), r"^[0-9a-f]{40}$")
            state = json.loads(local_run.state_file.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "ready_for_human")
            self.assertEqual(
                set(state["worktrees"]),
                {
                    "lead",
                    "builder-task-a",
                    "builder-task-b",
                    "integrator",
                    "verifier",
                    "reviewer",
                    "security-adversary",
                    "judge",
                },
            )


if __name__ == "__main__":
    unittest.main()
