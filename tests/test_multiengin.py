"""Regression tests for portable runtime discovery and reconciliation."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("multiengin", ROOT / "scripts" / "multiengin.py")
assert SPEC and SPEC.loader
multiengin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = multiengin
SPEC.loader.exec_module(multiengin)

CAPABILITIES = [
    "agent-skill-v1",
    "execution-manifest-v1",
    "local-worktree-v1",
    "rpc-v1",
    "skill-bundles-v1",
]


def agent_manifest(name: str = "verifier-01", provider: str = "codex") -> dict[str, object]:
    return {
        "schema_version": "0.3",
        "agent_id": "AGENT-TEST-01",
        "name": name,
        "runtime": {
            "provider": provider,
            "executable": provider,
            "version": {"minimum": "0.149" if provider == "codex" else "2.0"},
            "requirements": {
                "runtime_mode": "local",
                "capabilities": CAPABILITIES,
                "model_strategy": "runtime_default",
            },
        },
    }


def runtime(
    runtime_id: str,
    provider: str = "codex",
    *,
    daemon_id: str = "daemon-new",
    status: str = "online",
    capabilities: list[str] | None = None,
) -> dict[str, object]:
    version = "codex-cli 0.149.0" if provider == "codex" else "kiro-cli 2.19.0"
    return {
        "id": runtime_id,
        "daemon_id": daemon_id,
        "name": f"{provider} ({daemon_id})",
        "provider": provider,
        "runtime_mode": "local",
        "status": status,
        "last_seen_at": "2026-08-25T15:25:22Z",
        "metadata": {"capabilities": CAPABILITIES if capabilities is None else capabilities, "version": version},
    }


def discovery(
    manifest: dict[str, object],
    *,
    bound_runtime_id: str,
    runtimes: list[dict[str, object]],
    local_runtime_ids: list[str],
    model: str = "",
) -> multiengin.Discovery:
    return multiengin.Discovery(
        workspace={"id": "workspace-01", "name": "Engineering"},
        daemon={
            "daemon_id": "daemon-new",
            "status": "running",
            "workspaces": [{"id": "workspace-01", "runtimes": local_runtime_ids}],
        },
        agents=(
            {
                "id": "workspace-agent-01",
                "name": manifest["name"],
                "runtime_bound": True,
                "runtime_id": bound_runtime_id,
                "model": model,
                "status": "idle",
            },
        ),
        runtimes=tuple(runtimes),
    )


class MultiEnginTests(unittest.TestCase):
    def test_bare_command_prints_documented_usage(self) -> None:
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["multiengin"]), mock.patch("sys.stdout", output):
            result = multiengin.main()

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("usage: multiengin [-h] COMMAND ...", rendered)
        self.assertIn("commands:", rendered)
        self.assertIn("multiengin install-path", rendered)
        self.assertIn("multiengin configure-opencode --model qwen3.5:2b", rendered)
        self.assertIn("multiengin start builder-01 reviewer-01", rendered)
        self.assertIn("multiengin COMMAND --help", rendered)

    def test_manifests_cover_configured_agents_and_declare_runtime_requirements(self) -> None:
        agents = multiengin.manifests()
        self.assertEqual(
            {agent["name"] for agent in agents},
            {
                "engineering-lead-01",
                "builder-01",
                "integrator-01",
                "verifier-01",
                "reviewer-01",
                "security-adversary-01",
                "judge-01",
            },
        )
        for agent in agents:
            self.assertEqual(agent["schema_version"], "0.4")
            requirements = agent["runtime"]["requirements"]
            self.assertEqual(requirements["runtime_mode"], "local")
            self.assertTrue(set(CAPABILITIES).issubset(requirements["capabilities"]))
            self.assertIn(requirements["model_strategy"], {"preserve", "runtime_default"})
        selected = multiengin.select_agents(agents, ["builder-01"], False)
        self.assertEqual(selected[0]["runtime"]["provider"], "opencode")
        reviewer = multiengin.select_agents(agents, ["reviewer-01"], False)[0]
        self.assertEqual(reviewer["runtime"]["provider"], "opencode")
        self.assertIn("ollama", selected[0]["dependencies"]["system"])

    def test_runtime_manifest_declares_opencode_installer(self) -> None:
        runtime = multiengin.runtime_manifest()["runtimes"]["opencode"]
        self.assertEqual(runtime["executable"], "opencode")
        self.assertEqual(runtime["installer"], "opencode_cli")

    def test_ollama_dependency_requires_a_reachable_local_server(self) -> None:
        with (
            mock.patch.object(multiengin.shutil, "which", return_value="/usr/local/bin/ollama"),
            mock.patch.object(multiengin, "run", return_value=(False, "connection refused")),
        ):
            check = multiengin.dependency_check("ollama", False)
        self.assertFalse(check.passed)
        self.assertEqual(check.name, "Ollama")
        self.assertIn("server unavailable", check.detail)

    def test_opencode_installer_uses_pinned_npm_package(self) -> None:
        manifest = agent_manifest(name="builder-01", provider="opencode")
        manifest["runtime"]["version"]["minimum"] = "1.17.7"
        with (
            mock.patch.object(multiengin.shutil, "which", return_value="/usr/bin/npm"),
            mock.patch.object(multiengin.subprocess, "run") as command,
        ):
            command.return_value.returncode = 0
            installed = multiengin.install_runtime(manifest, dry_run=False)
        self.assertTrue(installed)
        command.assert_called_once_with(
            ["npm", "install", "--global", "opencode-ai@1.17.7"], check=False
        )

    def test_install_path_is_idempotent_and_persists_local_bin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            local_bin = temporary / "bin"
            profile = temporary / ".bashrc"
            self.assertEqual(multiengin.install_path(False, local_bin, profile), 0)
            self.assertEqual(multiengin.install_path(False, local_bin, profile), 0)
            destination = local_bin / "multiengin"
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), ROOT / "bin" / "multiengin")
            path_line = f'export PATH="{local_bin}:$PATH"'
            self.assertEqual(profile.read_text(encoding="utf-8").count(path_line), 1)
            completed = multiengin.subprocess.run(
                [str(destination), "--help"], text=True, capture_output=True, check=False
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("install-path", completed.stdout)

    def test_configure_opencode_writes_private_local_ollama_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opencode.json"
            self.assertEqual(
                multiengin.configure_opencode(
                    "ollama/qwen3.5:2b", "http://127.0.0.1:11434/v1", target
                ),
                0,
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["model"], "ollama/qwen3.5:2b")
            self.assertIn("qwen3.5:2b", payload["provider"]["ollama"]["models"])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                multiengin.configure_opencode(
                    "qwen3.5:2b", "http://127.0.0.1:11434/v1", target
                )

    def test_version_compatibility_uses_numeric_comparison(self) -> None:
        self.assertTrue(multiengin.version_at_least("codex-cli 0.149.0", "0.149"))
        self.assertTrue(multiengin.version_at_least("kiro-cli 2.10.0", "2.9"))
        self.assertFalse(multiengin.version_at_least("node v20.0.0", "24"))

    def test_language_runtime_check_uses_numeric_minimum(self) -> None:
        with (
            mock.patch.object(multiengin, "activate_managed_language", return_value=False),
            mock.patch.object(multiengin, "run", return_value=(True, "v24.1.0")),
        ):
            check = multiengin.language_runtime_check("node", "node", "24")
        self.assertTrue(check.passed)
        self.assertEqual(check.check_id, "CORE-NODE")

    def test_agent_selection_deduplicates_and_rejects_unknown_names(self) -> None:
        agents = multiengin.manifests()
        selected = multiengin.select_agents(agents, ["verifier-01", "verifier-01"], False)
        self.assertEqual([agent["name"] for agent in selected], ["verifier-01"])
        with self.assertRaisesRegex(ValueError, "unknown agent"):
            multiengin.select_agents(agents, ["does-not-exist"], False)

    def test_sync_instructions_updates_changed_workspace_agent(self) -> None:
        lead = next(
            agent for agent in multiengin.manifests() if agent["name"] == "engineering-lead-01"
        )
        expected = multiengin.instructions_path(lead).read_text(encoding="utf-8")
        with (
            mock.patch.object(
                multiengin,
                "json_output",
                side_effect=[
                    {"agents": [{"id": "lead-cloud-01", "name": "engineering-lead-01"}]},
                    {"id": "lead-cloud-01", "instructions": "old instructions"},
                ],
            ),
            mock.patch.object(multiengin, "run", return_value=(True, "{}")) as command,
        ):
            result = multiengin.sync_instructions([lead], yes=True, dry_run=False)

        self.assertEqual(result, 0)
        command.assert_called_once_with(
            [
                "multica",
                "agent",
                "update",
                "lead-cloud-01",
                "--instructions",
                expected,
                "--output",
                "json",
            ]
        )

    def test_sync_instructions_is_idempotent(self) -> None:
        lead = next(
            agent for agent in multiengin.manifests() if agent["name"] == "engineering-lead-01"
        )
        expected = multiengin.instructions_path(lead).read_text(encoding="utf-8")
        with (
            mock.patch.object(
                multiengin,
                "json_output",
                side_effect=[
                    {"agents": [{"id": "lead-cloud-01", "name": "engineering-lead-01"}]},
                    {"agent": {"id": "lead-cloud-01", "instructions": expected}},
                ],
            ),
            mock.patch.object(multiengin, "run") as command,
        ):
            result = multiengin.sync_instructions([lead], yes=True, dry_run=False)

        self.assertEqual(result, 0)
        command.assert_not_called()

    def test_rebinds_same_workspace_agent_from_old_machine_and_preserves_history(self) -> None:
        manifest = agent_manifest()
        old = runtime("runtime-old", daemon_id="daemon-old", status="offline")
        current = runtime("runtime-new")
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[old, current],
            local_runtime_ids=["runtime-new"],
        )

        plan = multiengin.plan_reconciliation([manifest], snapshot)
        self.assertEqual(plan[0].target_runtime_id, "runtime-new")
        self.assertEqual(plan[0].previous_runtime_id, "runtime-old")
        self.assertTrue(plan[0].change_required)

        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "runtime-history.json"
            with mock.patch.object(multiengin, "run", return_value=(True, "{}")) as command:
                changed = multiengin.apply_reconciliation(plan, snapshot.workspace_id, False, history_file)
            self.assertEqual(changed, 1)
            command.assert_called_once_with(
                [
                    "multica",
                    "agent",
                    "update",
                    "workspace-agent-01",
                    "--runtime-id",
                    "runtime-new",
                    "--output",
                    "json",
                ]
            )
            entry = json.loads(history_file.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(entry["previous_runtime_id"], "runtime-old")
            self.assertEqual(entry["current_runtime_id"], "runtime-new")
            self.assertEqual(entry["previous_runtime"]["daemon_id"], "daemon-old")
            self.assertEqual(entry["current_runtime"]["daemon_id"], "daemon-new")

    def test_capability_mismatch_blocks_rebinding(self) -> None:
        manifest = agent_manifest()
        missing_rpc = [capability for capability in CAPABILITIES if capability != "rpc-v1"]
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[runtime("runtime-new", capabilities=missing_rpc)],
            local_runtime_ids=["runtime-new"],
        )

        with self.assertRaisesRegex(ValueError, "missing capabilities: rpc-v1"):
            multiengin.plan_reconciliation([manifest], snapshot)

    def test_cross_provider_rebinding_uses_runtime_default_model_strategy(self) -> None:
        manifest = agent_manifest(provider="codex")
        old = runtime("runtime-old", provider="kiro", daemon_id="daemon-old", status="offline")
        current = runtime("runtime-new", provider="codex")
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[old, current],
            local_runtime_ids=["runtime-new"],
            model="ollama/workspace-model",
        )

        plan = multiengin.plan_reconciliation([manifest], snapshot)
        self.assertTrue(plan[0].clear_model)
        projected = multiengin.projected_discovery(snapshot, plan)
        self.assertEqual(projected.agents[0]["model"], "")
        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "runtime-history.json"
            with mock.patch.object(multiengin, "run", return_value=(True, "{}")) as command:
                multiengin.apply_reconciliation(plan, snapshot.workspace_id, False, history_file)
        command.assert_called_once_with(
            [
                "multica",
                "agent",
                "update",
                "workspace-agent-01",
                "--runtime-id",
                "runtime-new",
                "--model",
                "",
                "--output",
                "json",
            ]
        )

    def test_cross_provider_rebinding_blocks_unverified_preserved_model(self) -> None:
        manifest = agent_manifest(provider="codex")
        manifest["runtime"]["requirements"]["model_strategy"] = "preserve"
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[
                runtime("runtime-old", provider="kiro", daemon_id="daemon-old", status="offline"),
                runtime("runtime-new", provider="codex"),
            ],
            local_runtime_ids=["runtime-new"],
            model="ollama/workspace-model",
        )

        with self.assertRaisesRegex(ValueError, "cannot preserve model"):
            multiengin.plan_reconciliation([manifest], snapshot)

    def test_fails_when_no_compatible_runtime_exists(self) -> None:
        manifest = agent_manifest(provider="codex")
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[runtime("runtime-new", provider="kiro")],
            local_runtime_ids=["runtime-new"],
        )

        with self.assertRaisesRegex(ValueError, "no compatible local runtime exists"):
            multiengin.plan_reconciliation([manifest], snapshot)

    def test_repeated_reconciliation_is_idempotent(self) -> None:
        manifest = agent_manifest()
        current = runtime("runtime-new")
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-new",
            runtimes=[current],
            local_runtime_ids=["runtime-new"],
        )

        plan = multiengin.plan_reconciliation([manifest], snapshot)
        self.assertFalse(plan[0].change_required)
        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "runtime-history.json"
            with mock.patch.object(multiengin, "run") as command:
                changed = multiengin.apply_reconciliation(plan, snapshot.workspace_id, False, history_file)
            self.assertEqual(changed, 0)
            command.assert_not_called()
            self.assertFalse(history_file.exists())

    def test_failed_update_does_not_record_runtime_history(self) -> None:
        manifest = agent_manifest()
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-old",
            runtimes=[runtime("runtime-new")],
            local_runtime_ids=["runtime-new"],
        )
        plan = multiengin.plan_reconciliation([manifest], snapshot)

        with tempfile.TemporaryDirectory() as directory:
            history_file = Path(directory) / "runtime-history.json"
            with mock.patch.object(multiengin, "run", return_value=(False, "update rejected")):
                with self.assertRaisesRegex(ValueError, "failed to rebind"):
                    multiengin.apply_reconciliation(plan, snapshot.workspace_id, False, history_file)
            self.assertFalse(history_file.exists())

    def test_start_runs_bootstrap_discover_reconcile_verify_in_order(self) -> None:
        manifest = agent_manifest()
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-new",
            runtimes=[runtime("runtime-new")],
            local_runtime_ids=["runtime-new"],
        )
        output = io.StringIO()
        with (
            mock.patch.object(multiengin, "bootstrap", return_value=True),
            mock.patch.object(multiengin, "discover", side_effect=[snapshot, snapshot]) as discover_command,
            mock.patch.object(multiengin, "doctor", return_value=0) as doctor_command,
            mock.patch("sys.stdout", output),
        ):
            result = multiengin.start([manifest], yes=True, dry_run=False)

        self.assertEqual(result, 0)
        self.assertEqual(discover_command.call_count, 2)
        doctor_command.assert_called_once_with([manifest], include_core=True, snapshot=snapshot)
        rendered = output.getvalue()
        stages = [rendered.index(f"[{index}/4]") for index in range(1, 5)]
        self.assertEqual(stages, sorted(stages))

    def test_verification_requires_online_compatible_runtime_on_current_daemon(self) -> None:
        manifest = agent_manifest()
        current = runtime("runtime-new")
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-new",
            runtimes=[current],
            local_runtime_ids=["runtime-new"],
        )
        self.assertTrue(multiengin.ready(multiengin.workspace_checks(manifest, snapshot)))

        offline_snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-new",
            runtimes=[runtime("runtime-new", status="offline")],
            local_runtime_ids=["runtime-new"],
        )
        self.assertFalse(multiengin.ready(multiengin.workspace_checks(manifest, offline_snapshot)))

    def test_verification_blocks_when_required_workspace_skill_is_missing(self) -> None:
        manifest = agent_manifest()
        manifest["skills"] = ["run-verification"]
        snapshot = discovery(
            manifest,
            bound_runtime_id="runtime-new",
            runtimes=[runtime("runtime-new")],
            local_runtime_ids=["runtime-new"],
        )

        checks = multiengin.workspace_checks(manifest, snapshot)

        skill_check = next(check for check in checks if check.name == "Workspace skills")
        self.assertFalse(skill_check.passed)
        self.assertEqual(skill_check.detail, "missing enabled skills: run-verification")


if __name__ == "__main__":
    unittest.main()
