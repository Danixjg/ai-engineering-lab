"""Regression tests for the portable runtime's manifest resolution."""

from __future__ import annotations

import importlib.util
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


class MultiEnginTests(unittest.TestCase):
    def test_manifests_cover_the_configured_agents(self) -> None:
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
        self.assertEqual(
            multiengin.select_agents(agents, ["builder-01"], False)[0]["runtime"]["provider"],
            "opencode",
        )
        self.assertEqual(
            {agent["name"]: agent["runtime"]["provider"] for agent in agents},
            {agent["name"]: "opencode" for agent in agents},
        )
        self.assertEqual(set(multiengin.runtime_specs()), {"opencode"})
        self.assertEqual(
            {agent["runtime"]["model"] for agent in agents},
            {
                "ollama/multica-granite4.1:3b",
                "ollama/multica-ministral-3:3b",
                "ollama/multica-qwen3.5:2b",
            },
        )
        policy = multiengin.model_policy()
        self.assertEqual(
            set(policy["model_builds"]),
            set(policy["portfolio"]["required_models"]),
        )
        for build in policy["model_builds"].values():
            modelfile = ROOT / build["modelfile"]
            self.assertTrue(modelfile.is_file())
            self.assertIn("PARAMETER num_ctx 65536", modelfile.read_text())
        for agent in agents:
            self.assertTrue((ROOT / agent["instructions_path"]).is_file())
            specification = multiengin.runtime_specs()[agent["runtime"]["provider"]]
            self.assertEqual(agent["runtime"]["executable"], specification["executable"])

    def test_version_compatibility_uses_numeric_comparison(self) -> None:
        self.assertTrue(multiengin.version_at_least("codex-cli 0.149.0", "0.149"))
        self.assertTrue(multiengin.version_at_least("kiro-cli 2.10.0", "2.9"))
        self.assertFalse(multiengin.version_at_least("node v20.0.0", "24"))
        opencode = "opencode 1.2.3\nbackend sdk 9.9.9"
        self.assertTrue(
            multiengin.version_at_least(
                opencode, "1.2", r"opencode (\d+(?:\.\d+){1,2})"
            )
        )
        self.assertFalse(
            multiengin.version_at_least(
                opencode, "1.3", r"opencode (\d+(?:\.\d+){1,2})"
            )
        )

    def test_publish_runtime_executable_exposes_opencode_to_multica(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "install" / "opencode"
            source.parent.mkdir()
            source.write_text("runtime", encoding="utf-8")
            local_bin = root / "local-bin"
            with (
                mock.patch.object(multiengin, "LOCAL_BIN", local_bin),
                mock.patch.object(
                    multiengin.shutil, "which", return_value=str(source)
                ),
            ):
                published, changed = multiengin.publish_runtime_executable(
                    "opencode", False
                )
                published_again, changed_again = (
                    multiengin.publish_runtime_executable("opencode", False)
                )

            target = local_bin / "opencode"
            self.assertTrue(published)
            self.assertTrue(changed)
            self.assertEqual(target.resolve(), source.resolve())
            self.assertTrue(published_again)
            self.assertFalse(changed_again)

    def test_publish_runtime_configuration_supports_fresh_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config" / "opencode.json"
            with mock.patch.object(multiengin, "GLOBAL_OPENCODE_CONFIG", target):
                published, changed = multiengin.publish_runtime_configuration(
                    "opencode", False
                )
                published_again, changed_again = (
                    multiengin.publish_runtime_configuration("opencode", False)
                )

            self.assertTrue(published)
            self.assertTrue(changed)
            self.assertEqual(target.resolve(), (ROOT / "opencode.json").resolve())
            self.assertTrue(published_again)
            self.assertFalse(changed_again)

    def test_agent_selection_deduplicates_and_rejects_unknown_names(self) -> None:
        agents = multiengin.manifests()
        selected = multiengin.select_agents(agents, ["verifier-01", "verifier-01"], False)
        self.assertEqual([agent["name"] for agent in selected], ["verifier-01"])
        with self.assertRaisesRegex(ValueError, "unknown agent"):
            multiengin.select_agents(agents, ["does-not-exist"], False)

    def test_reconciliation_plan_moves_agents_to_local_models(self) -> None:
        agents = multiengin.manifests()
        runtimes = [
            {"id": "runtime-codex", "provider": "codex", "status": "online"},
            {"id": "runtime-opencode", "provider": "opencode", "status": "online"},
        ]
        live_agents = []
        for index, agent in enumerate(agents, start=1):
            live_agents.append(
                {
                    "id": f"live-agent-{index}",
                    "name": agent["name"],
                    "runtime_id": "runtime-codex",
                    "model": "",
                    "status": "working" if agent["name"] == "verifier-01" else "idle",
                }
            )

        changes, errors = multiengin.reconciliation_plan(
            agents, runtimes, live_agents
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            {change["name"] for change in changes},
            {agent["name"] for agent in agents},
        )
        verifier = next(
            change for change in changes if change["name"] == "verifier-01"
        )
        self.assertEqual(verifier["to_provider"], "opencode")
        self.assertEqual(
            verifier["to_model"], "ollama/multica-granite4.1:3b"
        )
        self.assertEqual(verifier["status"], "working")


if __name__ == "__main__":
    unittest.main()
