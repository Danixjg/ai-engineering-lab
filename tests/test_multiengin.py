"""Regression tests for the portable runtime's manifest resolution."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


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
        self.assertEqual(multiengin.select_agents(agents, ["builder-01"], False)[0]["runtime"]["provider"], "kiro")

    def test_version_compatibility_uses_numeric_comparison(self) -> None:
        self.assertTrue(multiengin.version_at_least("codex-cli 0.149.0", "0.149"))
        self.assertTrue(multiengin.version_at_least("kiro-cli 2.10.0", "2.9"))
        self.assertFalse(multiengin.version_at_least("node v20.0.0", "24"))

    def test_agent_selection_deduplicates_and_rejects_unknown_names(self) -> None:
        agents = multiengin.manifests()
        selected = multiengin.select_agents(agents, ["verifier-01", "verifier-01"], False)
        self.assertEqual([agent["name"] for agent in selected], ["verifier-01"])
        with self.assertRaisesRegex(ValueError, "unknown agent"):
            multiengin.select_agents(agents, ["does-not-exist"], False)


if __name__ == "__main__":
    unittest.main()
