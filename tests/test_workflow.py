"""Contract and topology tests for the seven-role engineering workflow."""

from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("multiengin_workflow", ROOT / "scripts" / "multiengin.py")
assert SPEC and SPEC.loader
multiengin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = multiengin
SPEC.loader.exec_module(multiengin)


class WorkflowTests(unittest.TestCase):
    def test_repository_workflow_contract_is_ready(self) -> None:
        checks = multiengin.workflow_checks()
        self.assertTrue(multiengin.ready(checks), [check.detail for check in checks if not check.passed])

    def test_leader_instructions_define_durable_stage_handoff(self) -> None:
        checks = {check.check_id: check for check in multiengin.workflow_checks()}
        self.assertTrue(checks["WORKFLOW-LEADER-INSTRUCTIONS"].passed)
        leader = next(
            agent for agent in multiengin.manifests() if agent["name"] == "engineering-lead-01"
        )
        instructions = multiengin.instructions_path(leader).read_text(encoding="utf-8")
        for marker in ("--parent", "--stage", "multica squad activity"):
            self.assertIn(marker, instructions)

    def test_workflow_assigns_seven_roles_and_three_independent_reviews(self) -> None:
        workflow = multiengin.workflow_manifest()
        roles = workflow["squad"]["roles"]
        self.assertEqual(
            set(roles),
            {"leader", "builder", "integrator", "verifier", "reviewer", "security-adversary", "judge"},
        )
        independent_review = workflow["states"]["independent_review"]
        self.assertEqual(len(independent_review["parallel"]), 3)
        self.assertEqual(independent_review["barrier"]["mode"], "all_terminal")
        for branch in independent_review["parallel"]:
            self.assertIn("integration_result", multiengin.contracts(branch["input"]))

    def test_unknown_transition_and_unreachable_state_are_blocking(self) -> None:
        workflow = copy.deepcopy(multiengin.workflow_manifest())
        workflow["states"]["received"]["next"] = "missing_state"
        workflow["states"]["orphan"] = {"description": "Unreachable", "terminal": True}
        checks = {check.check_id: check for check in multiengin.workflow_checks(workflow=workflow)}
        self.assertFalse(checks["WORKFLOW-TRANSITIONS"].passed)
        self.assertFalse(checks["WORKFLOW-REACHABILITY"].passed)

    def test_agent_contract_drift_is_blocking(self) -> None:
        agents = copy.deepcopy(multiengin.manifests())
        verifier = next(agent for agent in agents if agent["agent_id"] == "AGENT-VERIFIER-01")
        verifier["outputs"].remove("verification_result")
        checks = {check.check_id: check for check in multiengin.workflow_checks(agents)}
        self.assertFalse(checks["WORKFLOW-CONTRACTS"].passed)
        self.assertIn("verification_result", checks["WORKFLOW-CONTRACTS"].detail)

    def test_live_squad_roles_are_checked_against_manifest_agents(self) -> None:
        agents = multiengin.manifests()
        workflow = multiengin.workflow_manifest()
        cloud_by_manifest_id = {
            agent["agent_id"]: {"id": f"cloud-{agent['name']}", "name": agent["name"]} for agent in agents
        }
        snapshot = multiengin.Discovery(
            workspace={"id": "workspace-01"},
            daemon={"daemon_id": "daemon-01", "workspaces": []},
            agents=tuple(cloud_by_manifest_id.values()),
            runtimes=(),
        )
        squad = {
            "id": "squad-01",
            "name": "Engineering Squad",
            "leader_id": cloud_by_manifest_id["AGENT-ENGINEERING-LEAD-01"]["id"],
        }
        members = tuple(
            {
                "member_id": cloud_by_manifest_id[manifest_id]["id"],
                "member_type": "agent",
                "role": role,
            }
            for role, manifest_id in workflow["squad"]["roles"].items()
        )
        checks = multiengin.squad_checks(agents, workflow, snapshot, (squad,), members)
        self.assertTrue(multiengin.ready(checks), [check.detail for check in checks if not check.passed])


if __name__ == "__main__":
    unittest.main()
