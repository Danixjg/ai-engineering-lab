"""Regression tests for portable project blueprints and routing."""

from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "project_blueprint", ROOT / "scripts" / "project_blueprint.py"
)
assert SPEC and SPEC.loader
project_blueprint = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = project_blueprint
SPEC.loader.exec_module(project_blueprint)


class ProjectBlueprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blueprint = project_blueprint.load_document(
            ROOT / ".ai" / "blueprints" / "project.example.json"
        )
        self.policy = project_blueprint.load_document(project_blueprint.ROUTING_POLICY)

    def test_example_is_valid_and_routes_every_delivery_stage(self) -> None:
        self.assertEqual(project_blueprint.validate_blueprint(self.blueprint, self.policy), [])
        plan = project_blueprint.build_plan(self.blueprint)

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["leader_task"]["agent"]["name"], "engineering-lead-01")
        self.assertEqual(plan["schema_version"], "0.3")
        self.assertEqual(plan["model_portfolio"]["distinct_model_count"], 3)
        self.assertEqual(
            plan["model_portfolio"]["stage_diversity"]["independent-checks"],
            [
                "ollama/multica-granite4.1:3b",
                "ollama/multica-ministral-3:3b",
            ],
        )
        self.assertEqual(plan["recursion"]["max_parallel_tasks"], 1)
        self.assertEqual(
            [stage["name"] for stage in plan["stages"]],
            [
                "repository-bootstrap",
                "implementation",
                "integration",
                "independent-checks",
                "judgment",
            ],
        )
        checks = next(stage for stage in plan["stages"] if stage["name"] == "independent-checks")
        self.assertEqual(
            {task["agent"]["name"] for task in checks["tasks"]},
            {"verifier-01", "reviewer-01", "security-adversary-01"},
        )
        for stage in plan["stages"]:
            for task in stage["tasks"]:
                self.assertLessEqual(len(task["selected_skills"]), 4)

    def test_existing_repository_skips_bootstrap_stage(self) -> None:
        blueprint = copy.deepcopy(self.blueprint)
        blueprint["repository"] = {
            "mode": "existing",
            "url": "https://github.com/example-org/example-service.git",
            "default_branch": "main",
        }
        blueprint["execution"]["authorizations"] = [
            value
            for value in blueprint["execution"]["authorizations"]
            if value not in {"create_repository", "register_repository"}
        ]

        plan = project_blueprint.build_plan(blueprint)

        self.assertEqual(plan["status"], "ready")
        self.assertNotIn("repository-bootstrap", [stage["name"] for stage in plan["stages"]])

    def test_blueprint_cannot_exceed_recursion_policy(self) -> None:
        blueprint = copy.deepcopy(self.blueprint)
        blueprint["execution"]["max_depth"] = self.policy["recursion"]["max_depth"] + 1

        errors = project_blueprint.validate_blueprint(blueprint, self.policy)

        self.assertIn("execution.max_depth exceeds policy maximum 4", errors)

    def test_blueprint_rejects_unsupported_authority(self) -> None:
        blueprint = copy.deepcopy(self.blueprint)
        blueprint["execution"]["authorizations"].append("administer_production")

        errors = project_blueprint.validate_blueprint(blueprint, self.policy)

        self.assertIn(
            "execution.authorizations contains unsupported value administer_production",
            errors,
        )

    def test_missing_creation_authority_becomes_a_routing_gap(self) -> None:
        blueprint = copy.deepcopy(self.blueprint)
        blueprint["execution"]["authorizations"].remove("create_repository")

        plan = project_blueprint.build_plan(blueprint)

        self.assertEqual(plan["status"], "needs_human")
        self.assertIn("new repository delivery requires create_repository authorization", plan["gaps"])

    def test_submit_is_read_only_without_apply(self) -> None:
        plan = project_blueprint.build_plan(self.blueprint)
        with mock.patch.object(project_blueprint, "run_multica") as run_multica:
            result = project_blueprint.submit(
                blueprint=self.blueprint,
                plan=plan,
                control_repository="https://github.com/example/control.git",
                project_id=None,
                create_project=True,
                squad="Engineering Squad",
                start=True,
                apply=False,
            )

        run_multica.assert_not_called()
        self.assertFalse(result["apply"])
        self.assertEqual(result["project"]["action"], "create")
        self.assertEqual(result["issue"]["status"], "todo")

    def test_live_preflight_checks_squad_topology_and_skill_bindings(self) -> None:
        plan = project_blueprint.build_plan(self.blueprint)
        requirements = project_blueprint.routed_agent_requirements(plan)
        providers = project_blueprint.routed_agent_providers(plan)
        models = project_blueprint.routed_agent_models(plan)
        runtime_ids = {
            provider: f"runtime-{provider}" for provider in sorted(set(providers.values()))
        }
        agents = []
        for index, name in enumerate(sorted(requirements), start=1):
            agents.append(
                {
                    "id": f"agent-{index}",
                    "name": name,
                    "runtime_id": runtime_ids[providers[name]],
                    "model": models[name],
                }
            )
        agents_by_name = {agent["name"]: agent for agent in agents}
        runtimes = [
            {"id": runtime_id, "provider": provider, "status": "online"}
            for provider, runtime_id in runtime_ids.items()
        ]
        skills = [
            {"id": f"skill-{index}", "name": name}
            for index, name in enumerate(
                sorted({skill for values in requirements.values() for skill in values}),
                start=1,
            )
        ]
        lead_id = agents_by_name["engineering-lead-01"]["id"]

        def fake_multica(command: list[str], stdin: str | None = None):
            del stdin
            if command[1:3] == ["daemon", "status"]:
                return {"status": "running"}
            if command[1:3] == ["agent", "list"]:
                return agents
            if command[1:3] == ["runtime", "list"]:
                return runtimes
            if command[1:3] == ["squad", "list"]:
                return [{"id": "squad-1", "name": "Engineering Squad", "leader_id": lead_id}]
            if command[1:4] == ["squad", "member", "list"]:
                return [{"member_id": agent["id"]} for agent in agents]
            if command[1:3] == ["skill", "list"]:
                return skills
            if command[1:4] == ["agent", "skills", "list"]:
                agent_id = command[4]
                agent_name = next(agent["name"] for agent in agents if agent["id"] == agent_id)
                return [{"name": name} for name in requirements[agent_name]]
            self.fail(f"unexpected command: {command}")

        with mock.patch.object(project_blueprint, "run_multica", side_effect=fake_multica):
            errors = project_blueprint.preflight_live("Engineering Squad", plan)

        self.assertEqual(errors, [])

    def test_model_portfolio_rejects_model_concentration(self) -> None:
        plan = project_blueprint.build_plan(self.blueprint)
        concentrated = copy.deepcopy(plan)
        tasks = [concentrated["leader_task"]]
        tasks.extend(
            task for stage in concentrated["stages"] for task in stage["tasks"]
        )
        tasks.extend(concentrated["conditional_routes"])
        for task in tasks:
            task["agent"]["runtime"]["model"] = "ollama/multica-qwen3.5:2b"

        _, gaps = project_blueprint.evaluate_model_portfolio(
            concentrated["leader_task"],
            concentrated["stages"],
            concentrated["conditional_routes"],
            project_blueprint.load_document(project_blueprint.MODEL_POLICY),
        )

        self.assertTrue(any("missing required models" in gap for gap in gaps))
        self.assertTrue(any("model portfolio share" in gap for gap in gaps))
        self.assertTrue(any("model separation violated" in gap for gap in gaps))

    def test_local_profile_routes_high_risk_work_to_human(self) -> None:
        blueprint = copy.deepcopy(self.blueprint)
        blueprint["risk_level"] = "high"

        plan = project_blueprint.build_plan(blueprint)

        self.assertEqual(plan["status"], "needs_human")
        self.assertTrue(any("supports risk through medium" in gap for gap in plan["gaps"]))

    def test_render_embeds_the_normalized_contract_and_plan(self) -> None:
        plan = project_blueprint.build_plan(self.blueprint)

        rendered = project_blueprint.render_issue(
            self.blueprint, plan, "https://github.com/example/control.git"
        )

        self.assertIn("PROJECT-EXAMPLE-SERVICE", rendered)
        self.assertIn(plan["blueprint_digest"], rendered)
        self.assertIn("project-orchestration", rendered)


if __name__ == "__main__":
    unittest.main()
