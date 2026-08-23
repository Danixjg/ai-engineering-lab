#!/usr/bin/env python3
"""Validate, route, render, and submit governed project blueprints."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".ai" / "agents"
SKILL_MANIFEST = ROOT / ".ai" / "skills" / "manifest.yaml"
MODEL_POLICY = ROOT / ".ai" / "runtime" / "model-policy.yaml"
ROUTING_POLICY = (
    ROOT
    / ".agents"
    / "skills"
    / "project-orchestration"
    / "references"
    / "routing-policy.json"
)
CONTROL_REMOTE = "origin"
PROJECT_ID = re.compile(r"^PROJECT-[A-Z0-9-]+$")
REQUIREMENT_ID = re.compile(r"^REQ-[A-Z0-9-]+$")
ACCEPTANCE_ID = re.compile(r"^AC-[A-Z0-9-]+$")
RISK_LEVELS = ("low", "medium", "high", "critical")
PRIORITIES = {"must", "should", "could"}
VERIFICATION_METHODS = {
    "automated_test",
    "static_analysis",
    "security_scan",
    "manual_review",
    "agent_review",
    "runtime_check",
}
EXPECTED_OUTPUTS = {
    "repository",
    "architecture",
    "source_changes",
    "tests",
    "documentation",
    "pull_request",
    "evidence_bundle",
}
AUTHORIZATIONS = {
    "create_multica_project",
    "create_repository",
    "register_repository",
    "create_issues",
    "create_branches",
    "push_branches",
    "open_pull_requests",
}
HUMAN_GATES = {
    "product_ambiguity",
    "permission_expansion",
    "destructive_change",
    "production_access",
    "deployment",
    "merge",
}


class BlueprintError(ValueError):
    """Raised when a blueprint or routing input is unusable."""


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_document(path: Path) -> dict[str, Any]:
    """Load a JSON or JSON-compatible YAML object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BlueprintError(f"document not found: {path}") from error
    except json.JSONDecodeError as error:
        raise BlueprintError(
            f"{relative(path)} must be JSON-compatible YAML: {error.msg} "
            f"at line {error.lineno}, column {error.colno}"
        ) from error
    if not isinstance(value, dict):
        raise BlueprintError(f"{relative(path)} must contain an object")
    return value


def require_string(value: Any, name: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name} must be a non-empty string")


def validate_records(
    records: Any,
    name: str,
    identifier_pattern: re.Pattern[str],
    errors: list[str],
) -> None:
    if not isinstance(records, list) or not records:
        errors.append(f"{name} must be a non-empty array")
        return
    seen: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"{name}[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier_pattern.fullmatch(identifier):
            errors.append(f"{prefix}.id has an invalid format")
        elif identifier in seen:
            errors.append(f"{prefix}.id duplicates {identifier}")
        else:
            seen.add(identifier)
        require_string(record.get("description"), f"{prefix}.description", errors)


def validate_string_array(
    value: Any,
    name: str,
    errors: list[str],
    *,
    allowed: set[str] | None = None,
    require_nonempty: bool = False,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{name} must be an array")
        return
    if require_nonempty and not value:
        errors.append(f"{name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{name} must contain only non-empty strings")
        return
    if len(value) != len(set(value)):
        errors.append(f"{name} must not contain duplicates")
    if allowed is not None:
        for item in sorted(set(value) - allowed):
            errors.append(f"{name} contains unsupported value {item}")


def validate_blueprint(
    blueprint: dict[str, Any], policy: dict[str, Any] | None = None
) -> list[str]:
    """Return deterministic validation errors for a Project Blueprint."""
    errors: list[str] = []
    allowed_top_level = {
        "$schema",
        "schema_version",
        "project_id",
        "title",
        "objective",
        "repository",
        "requirements",
        "acceptance_criteria",
        "constraints",
        "risk_level",
        "technology",
        "expected_outputs",
        "execution",
        "metadata",
    }
    for field in sorted(set(blueprint) - allowed_top_level):
        errors.append(f"unsupported top-level field {field}")
    if blueprint.get("schema_version") != "0.1":
        errors.append("schema_version must be 0.1")
    project_id = blueprint.get("project_id")
    if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
        errors.append("project_id must match ^PROJECT-[A-Z0-9-]+$")
    require_string(blueprint.get("title"), "title", errors)
    require_string(blueprint.get("objective"), "objective", errors)
    validate_records(blueprint.get("requirements"), "requirements", REQUIREMENT_ID, errors)
    validate_records(
        blueprint.get("acceptance_criteria"),
        "acceptance_criteria",
        ACCEPTANCE_ID,
        errors,
    )
    for index, requirement in enumerate(blueprint.get("requirements", [])):
        if isinstance(requirement, dict) and requirement.get("priority") not in PRIORITIES:
            errors.append(f"requirements[{index}].priority is invalid")
    for index, criterion in enumerate(blueprint.get("acceptance_criteria", [])):
        if not isinstance(criterion, dict):
            continue
        if criterion.get("verification") not in VERIFICATION_METHODS:
            errors.append(f"acceptance_criteria[{index}].verification is invalid")
        if not isinstance(criterion.get("required"), bool):
            errors.append(f"acceptance_criteria[{index}].required must be a boolean")

    repository = blueprint.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository must be an object")
    else:
        mode = repository.get("mode")
        if mode not in {"create", "existing"}:
            errors.append("repository.mode must be create or existing")
        require_string(repository.get("default_branch"), "repository.default_branch", errors)
        if mode == "create":
            require_string(repository.get("owner"), "repository.owner", errors)
            require_string(repository.get("name"), "repository.name", errors)
            if repository.get("visibility") not in {"private", "public", "internal"}:
                errors.append("repository.visibility must be private, public, or internal")
        if mode == "existing":
            require_string(repository.get("url"), "repository.url", errors)

    if blueprint.get("risk_level") not in RISK_LEVELS:
        errors.append("risk_level must be low, medium, high, or critical")
    validate_string_array(blueprint.get("constraints"), "constraints", errors)
    validate_string_array(
        blueprint.get("expected_outputs"),
        "expected_outputs",
        errors,
        allowed=EXPECTED_OUTPUTS,
        require_nonempty=True,
    )
    technology = blueprint.get("technology")
    if technology is not None:
        if not isinstance(technology, dict):
            errors.append("technology must be an object")
        else:
            for field in sorted(set(technology) - {"languages", "frameworks", "notes"}):
                errors.append(f"technology contains unsupported field {field}")
            for field in ("languages", "frameworks"):
                if field in technology:
                    validate_string_array(technology[field], f"technology.{field}", errors)
            if "notes" in technology and not isinstance(technology["notes"], str):
                errors.append("technology.notes must be a string")
    if "metadata" in blueprint and not isinstance(blueprint["metadata"], dict):
        errors.append("metadata must be an object")

    execution = blueprint.get("execution")
    if not isinstance(execution, dict):
        errors.append("execution must be an object")
        return errors
    require_string(execution.get("squad"), "execution.squad", errors)
    for field in sorted(
        set(execution)
        - {
            "squad",
            "max_depth",
            "max_children_per_issue",
            "max_parallel_tasks",
            "authorizations",
            "human_gates",
        }
    ):
        errors.append(f"execution contains unsupported field {field}")
    validate_string_array(
        execution.get("authorizations"),
        "execution.authorizations",
        errors,
        allowed=AUTHORIZATIONS,
    )
    validate_string_array(
        execution.get("human_gates"),
        "execution.human_gates",
        errors,
        allowed=HUMAN_GATES,
    )

    limits = (policy or load_document(ROUTING_POLICY))["recursion"]
    for field in ("max_depth", "max_children_per_issue", "max_parallel_tasks"):
        value = execution.get(field)
        maximum = limits[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"execution.{field} must be a positive integer")
        elif value > maximum:
            errors.append(f"execution.{field} exceeds policy maximum {maximum}")
    return errors


def blueprint_digest(blueprint: dict[str, Any]) -> str:
    canonical = json.dumps(blueprint, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_agents() -> list[dict[str, Any]]:
    return [load_document(path) for path in sorted(AGENTS_DIR.glob("*.yaml"))]


def overlap(required: Iterable[str], available: Iterable[str]) -> float:
    required_set = set(required)
    if not required_set:
        return 1.0
    return len(required_set & set(available)) / len(required_set)


def skill_score(
    name: str,
    skill: dict[str, Any],
    task: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[float, dict[str, float]] | None:
    if task["role"] not in skill.get("supported_roles", []):
        return None
    routing = skill.get("routing", {})
    components = {
        "capability_match": overlap(task.get("capabilities", []), routing.get("capabilities", [])),
        "task_type_match": float(routing.get("task_types", {}).get(task["task_type"], 0.0)),
        "artifact_match": overlap(task.get("artifacts", []), routing.get("artifacts", [])),
        "role_match": 1.0,
    }
    weights = policy["skill_selection"]["weights"]
    score = sum(components[key] * weights[key] for key in weights)
    score -= float(routing.get("context_cost", 0.0)) * float(
        policy["skill_selection"]["context_cost_penalty"]
    )
    return round(max(0.0, min(1.0, score)), 4), {
        key: round(value, 4) for key, value in components.items()
    }


def agent_score(
    agent: dict[str, Any],
    task: dict[str, Any],
    risk_level: str,
    policy: dict[str, Any],
    model_policy: dict[str, Any],
) -> tuple[float, dict[str, float]] | None:
    if agent.get("role") != task["role"]:
        return None
    routing = agent.get("routing", {})
    if risk_level not in routing.get("eligible_risk_levels", []):
        return None
    required_skills = set(task.get("required_skills", []))
    bound_skills = set(agent.get("skills", []))
    if not required_skills.issubset(bound_skills):
        return None
    components = {
        "capability_match": overlap(task.get("capabilities", []), routing.get("capabilities", [])),
        "task_type_match": 1.0 if task["task_type"] in routing.get("task_types", []) else 0.0,
        "required_skill_coverage": overlap(required_skills, bound_skills),
        "risk_match": 1.0,
        "manifest_priority": float(routing.get("priority", 0)) / 100.0,
        "model_affinity": float(
            model_policy.get("role_affinity", {})
            .get(task["role"], {})
            .get(agent.get("runtime", {}).get("model"), 0.0)
        ),
    }
    weights = {
        **policy["agent_delegation"]["weights"],
        **model_policy["selection"]["weights"],
    }
    score = sum(components[key] * weights[key] for key in weights)
    return round(score, 4), {key: round(value, 4) for key, value in components.items()}


def choose_agent(
    agents: list[dict[str, Any]],
    task: dict[str, Any],
    risk_level: str,
    policy: dict[str, Any],
    model_policy: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    candidates: list[tuple[float, str, dict[str, Any], dict[str, float]]] = []
    for agent in agents:
        scored = agent_score(agent, task, risk_level, policy, model_policy)
        if scored is None:
            continue
        score, components = scored
        candidates.append((score, agent["name"], agent, components))
    if not candidates:
        return None, (
            f"no {task['role']} agent passes risk and required-skill gates for "
            f"{task['template_id']}"
        )
    score, _, agent, components = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    return {
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "score": score,
        "score_breakdown": components,
        "runtime": {
            "provider": agent["runtime"]["provider"],
            "executable": agent["runtime"]["executable"],
            "model": agent["runtime"]["model"],
        },
        "runtime_check_required": True,
    }, None


def select_skills(
    catalog: dict[str, Any],
    agent: dict[str, Any] | None,
    task: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    required = set(task.get("required_skills", []))
    bound = set(agent.get("skills", [])) if agent else set()
    gaps = [f"{task['template_id']} requires unknown skill {name}" for name in sorted(required - set(catalog))]
    gaps.extend(
        f"{task['template_id']} requires {name}, which is not bound to its selected agent"
        for name in sorted(required - bound)
    )
    scored: list[dict[str, Any]] = []
    for name in sorted(bound & set(catalog)):
        result = skill_score(name, catalog[name], task, policy)
        if result is None:
            continue
        score, components = result
        mode = "required" if name in required else "selected"
        if mode != "required" and score < policy["skill_selection"]["selected_threshold"]:
            continue
        scored.append(
            {
                "name": name,
                "mode": mode,
                "score": score,
                "score_breakdown": components,
                "reason": "explicit task requirement" if mode == "required" else "routing score met threshold",
            }
        )
    scored.sort(key=lambda item: (item["mode"] != "required", -item["score"], item["name"]))
    limit = policy["skill_selection"]["max_selected_skills"]
    required_items = [item for item in scored if item["mode"] == "required"]
    optional_items = [item for item in scored if item["mode"] != "required"]
    return required_items + optional_items[: max(0, limit - len(required_items))], gaps


def route_task(
    template: dict[str, Any],
    agents: list[dict[str, Any]],
    catalog: dict[str, Any],
    policy: dict[str, Any],
    model_policy: dict[str, Any],
    risk_level: str,
    remaining_depth: int,
) -> tuple[dict[str, Any], list[str]]:
    selected_agent, agent_gap = choose_agent(
        agents, template, risk_level, policy, model_policy
    )
    agent_manifest = next(
        (agent for agent in agents if selected_agent and agent["agent_id"] == selected_agent["agent_id"]),
        None,
    )
    skills, skill_gaps = select_skills(catalog, agent_manifest, template, policy)
    routed = {
        key: value
        for key, value in template.items()
        if key not in {"capabilities", "artifacts", "required_skills"}
    }
    routed.update(
        {
            "capabilities": template.get("capabilities", []),
            "expected_artifacts": template.get("artifacts", []),
            "required_skills": template.get("required_skills", []),
            "remaining_depth": remaining_depth if template.get("recursive") else 0,
            "agent": selected_agent,
            "selected_skills": skills,
        }
    )
    gaps = ([agent_gap] if agent_gap else []) + skill_gaps
    return routed, gaps


def condition_matches(condition: str, blueprint: dict[str, Any]) -> bool:
    if condition == "always":
        return True
    if condition == "repository.mode=create":
        return blueprint["repository"]["mode"] == "create"
    raise BlueprintError(f"unsupported routing condition: {condition}")


def task_sequence(
    leader_task: dict[str, Any],
    stages: list[dict[str, Any]],
    conditional_routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tasks = [leader_task]
    tasks.extend(task for stage in stages for task in stage["tasks"])
    tasks.extend(conditional_routes)
    return tasks


def evaluate_model_portfolio(
    leader_task: dict[str, Any],
    stages: list[dict[str, Any]],
    conditional_routes: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Summarize and hard-gate the harness/backend/model execution stack."""
    agents: dict[str, dict[str, Any]] = {}
    roles: dict[str, set[str]] = {}
    harness_provider = policy["execution_stack"]["harness"]["provider"]
    for task in task_sequence(leader_task, stages, conditional_routes):
        agent = task.get("agent")
        if not agent:
            continue
        model = agent.get("runtime", {}).get("model")
        if not isinstance(model, str) or not model:
            continue
        agents[agent["agent_id"]] = agent
        roles.setdefault(task["role"], set()).add(model)

    models: dict[str, list[str]] = {}
    for agent in agents.values():
        model = agent["runtime"]["model"]
        models.setdefault(model, []).append(agent["name"])
    models = {
        model: sorted(names) for model, names in sorted(models.items())
    }
    total = len(agents)
    observed_share = max((len(names) / total for names in models.values()), default=0.0)
    stage_diversity = {
        stage["name"]: sorted(
            {
                task["agent"]["runtime"]["model"]
                for task in stage["tasks"]
                if task.get("agent")
            }
        )
        for stage in stages
    }
    portfolio_policy = policy["portfolio"]
    summary = {
        "harness": policy["execution_stack"]["harness"],
        "backend": policy["execution_stack"]["backend"],
        "capacity": policy["execution_stack"]["capacity"],
        "models": models,
        "distinct_model_count": len(models),
        "minimum_distinct_models": portfolio_policy["minimum_distinct_models"],
        "observed_maximum_model_share": round(observed_share, 4),
        "maximum_model_share": portfolio_policy["maximum_model_share"],
        "stage_diversity": stage_diversity,
    }

    gaps: list[str] = []
    invalid_harnesses = {
        agent["runtime"].get("provider")
        for agent in agents.values()
        if agent["runtime"].get("provider") != harness_provider
    }
    if invalid_harnesses:
        gaps.append(
            f"local model stack requires {harness_provider}; found: "
            + ", ".join(sorted(str(value) for value in invalid_harnesses))
        )
    missing = set(portfolio_policy["required_models"]) - set(models)
    if missing:
        gaps.append(
            "model portfolio is missing required models: "
            + ", ".join(sorted(missing))
        )
    minimum = portfolio_policy["minimum_distinct_models"]
    if len(models) < minimum:
        gaps.append(
            f"model portfolio has {len(models)} distinct models; requires {minimum}"
        )
    maximum = float(portfolio_policy["maximum_model_share"])
    if observed_share > maximum:
        gaps.append(
            f"model portfolio share {observed_share:.4f} exceeds {maximum:.4f}"
        )

    for constraint in policy.get("separation_constraints", []):
        left_role = constraint["left_role"]
        left_models = roles.get(left_role, set())
        for right_role in constraint["right_roles"]:
            shared = left_models & roles.get(right_role, set())
            if shared:
                gaps.append(
                    f"model separation violated for {left_role} and {right_role}: "
                    + ", ".join(sorted(shared))
                )

    for constraint in policy.get("stage_constraints", []):
        stage_name = constraint["stage"]
        observed = len(stage_diversity.get(stage_name, []))
        required = constraint["minimum_distinct_models"]
        if observed < required:
            gaps.append(
                f"stage {stage_name} has {observed} models; requires {required}"
            )
    return summary, gaps


def build_plan(blueprint: dict[str, Any]) -> dict[str, Any]:
    policy = load_document(ROUTING_POLICY)
    model_policy = load_document(MODEL_POLICY)
    errors = validate_blueprint(blueprint, policy)
    if errors:
        raise BlueprintError("invalid Project Blueprint:\n- " + "\n- ".join(errors))
    catalog = load_document(SKILL_MANIFEST)["skills"]
    agents = load_agents()
    risk = blueprint["risk_level"]
    depth = blueprint["execution"]["max_depth"]
    gaps: list[str] = []
    capacity = model_policy["execution_stack"]["capacity"]
    maximum_risk = capacity["maximum_risk_level"]
    if RISK_LEVELS.index(risk) > RISK_LEVELS.index(maximum_risk):
        gaps.append(
            f"local model profile {capacity['profile']} supports risk through "
            f"{maximum_risk}; {risk} requires human or stronger evaluated models"
        )

    authorizations = set(blueprint["execution"]["authorizations"])
    if "create_issues" not in authorizations:
        gaps.append("recursive delivery requires create_issues authorization")
    if blueprint["repository"]["mode"] == "create":
        for authorization in ("create_repository", "register_repository"):
            if authorization not in authorizations:
                gaps.append(f"new repository delivery requires {authorization} authorization")

    leader_task, task_gaps = route_task(
        policy["leader_task"], agents, catalog, policy, model_policy, risk, depth
    )
    gaps.extend(task_gaps)
    stages: list[dict[str, Any]] = []
    ordinal = 1
    for stage in policy["stages"]:
        if not condition_matches(stage["condition"], blueprint):
            continue
        tasks: list[dict[str, Any]] = []
        for template in stage["tasks"]:
            task, task_gaps = route_task(
                template, agents, catalog, policy, model_policy, risk, depth - 1
            )
            tasks.append(task)
            gaps.extend(task_gaps)
        stages.append(
            {
                "stage": ordinal,
                "name": stage["name"],
                "barrier": bool(stage["barrier"]),
                "tasks": tasks,
            }
        )
        ordinal += 1

    conditional: list[dict[str, Any]] = []
    for template in policy.get("conditional_routes", []):
        task, task_gaps = route_task(
            template, agents, catalog, policy, model_policy, risk, 0
        )
        conditional.append(task)
        gaps.extend(task_gaps)

    model_portfolio, model_gaps = evaluate_model_portfolio(
        leader_task, stages, conditional, model_policy
    )
    requested_parallel = blueprint["execution"]["max_parallel_tasks"]
    effective_parallel = min(requested_parallel, capacity["maximum_parallel_tasks"])
    model_portfolio["capacity"] = {
        **model_portfolio["capacity"],
        "requested_parallel_tasks": requested_parallel,
        "effective_parallel_tasks": effective_parallel,
    }
    gaps.extend(model_gaps)

    unique_gaps = sorted(set(gaps))
    return {
        "$schema": ".ai/schemas/routing-plan.schema.json",
        "schema_version": "0.3",
        "project_id": blueprint["project_id"],
        "blueprint_digest": blueprint_digest(blueprint),
        "status": "needs_human" if unique_gaps else "ready",
        "governance": policy["governance"]["always_apply"],
        "recursion": {
            "max_depth": depth,
            "max_children_per_issue": blueprint["execution"]["max_children_per_issue"],
            "max_total_descendants": policy["recursion"]["max_total_descendants"],
            "max_parallel_tasks": effective_parallel,
        },
        "model_portfolio": model_portfolio,
        "leader_task": leader_task,
        "stages": stages,
        "conditional_routes": conditional,
        "gaps": unique_gaps,
    }


def git_origin() -> str:
    completed = subprocess.run(
        ["git", "config", "--get", f"remote.{CONTROL_REMOTE}.url"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise BlueprintError("the control repository has no origin URL")
    return value


def render_issue(
    blueprint: dict[str, Any], plan: dict[str, Any], control_repository: str
) -> str:
    return "\n".join(
        [
            f"# Project delivery: {blueprint['title']}",
            "",
            blueprint["objective"],
            "",
            "## Execution directive",
            "",
            "This parent issue is assigned to the Engineering Squad. The squad leader must apply "
            "`project-orchestration`, retain the control repository as project context, and create "
            "bounded staged child issues. Child issues may narrow but never expand the authorizations below.",
            "",
            f"Control repository: `{control_repository}`",
            f"Initial routing status: `{plan['status']}`",
            "",
            "## Project Blueprint",
            "",
            "```json",
            json.dumps(blueprint, indent=2, sort_keys=True),
            "```",
            "",
            "## Initial routing plan",
            "",
            "```json",
            json.dumps(plan, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def run_multica(command: list[str], stdin: str | None = None) -> Any:
    completed = subprocess.run(
        command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise BlueprintError(f"Multica command failed ({' '.join(command[:3])}): {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BlueprintError("Multica returned invalid JSON") from error
    return value


def collection(value: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [item for item in value[key] if isinstance(item, dict)]
    raise BlueprintError(f"Multica returned an unexpected {key} response")


def routed_agent_requirements(plan: dict[str, Any]) -> dict[str, set[str]]:
    requirements: dict[str, set[str]] = {}
    tasks = [plan["leader_task"]]
    tasks.extend(task for stage in plan["stages"] for task in stage["tasks"])
    tasks.extend(plan.get("conditional_routes", []))
    for task in tasks:
        agent = task.get("agent")
        if not agent:
            continue
        requirements.setdefault(agent["name"], set()).update(task.get("required_skills", []))
    return requirements


def routed_agent_providers(plan: dict[str, Any]) -> dict[str, str]:
    providers: dict[str, str] = {}
    tasks = [plan["leader_task"]]
    tasks.extend(task for stage in plan["stages"] for task in stage["tasks"])
    tasks.extend(plan.get("conditional_routes", []))
    for task in tasks:
        agent = task.get("agent")
        if not agent:
            continue
        provider = agent.get("runtime", {}).get("provider")
        if not isinstance(provider, str) or not provider:
            continue
        previous = providers.setdefault(agent["name"], provider)
        if previous != provider:
            raise BlueprintError(
                f"routing plan assigns conflicting providers to {agent['name']}"
            )
    return providers


def routed_agent_models(plan: dict[str, Any]) -> dict[str, str]:
    models: dict[str, str] = {}
    tasks = [plan["leader_task"]]
    tasks.extend(task for stage in plan["stages"] for task in stage["tasks"])
    tasks.extend(plan.get("conditional_routes", []))
    for task in tasks:
        agent = task.get("agent")
        if not agent:
            continue
        model = agent.get("runtime", {}).get("model")
        if not isinstance(model, str) or not model:
            continue
        previous = models.setdefault(agent["name"], model)
        if previous != model:
            raise BlueprintError(
                f"routing plan assigns conflicting models to {agent['name']}"
            )
    return models


def preflight_live(squad_name: str, plan: dict[str, Any]) -> list[str]:
    """Check the live runtime, squad, agents, and bindings before a write."""
    errors: list[str] = []
    daemon = run_multica(["multica", "daemon", "status", "--output", "json"])
    if not isinstance(daemon, dict) or daemon.get("status") not in {"running", "ready"}:
        errors.append("Multica daemon is not running")

    agents = collection(
        run_multica(["multica", "agent", "list", "--output", "json"]), "agents"
    )
    agents_by_name = {agent.get("name"): agent for agent in agents if agent.get("name")}
    required = routed_agent_requirements(plan)
    desired_providers = routed_agent_providers(plan)
    desired_models = routed_agent_models(plan)
    for name in sorted(required):
        if name not in agents_by_name:
            errors.append(f"required live agent is missing: {name}")

    runtimes = collection(
        run_multica(["multica", "runtime", "list", "--output", "json"]),
        "runtimes",
    )
    runtimes_by_id = {
        runtime.get("id"): runtime for runtime in runtimes if runtime.get("id")
    }
    for name, expected_provider in sorted(desired_providers.items()):
        agent = agents_by_name.get(name)
        if not agent:
            continue
        runtime = runtimes_by_id.get(agent.get("runtime_id"))
        if runtime is None:
            errors.append(f"{name} has no resolvable live runtime binding")
            continue
        actual_provider = runtime.get("provider")
        if actual_provider != expected_provider:
            errors.append(
                f"{name} is bound to {actual_provider or 'unknown'}; "
                f"blueprint requires {expected_provider}"
            )
        if runtime.get("status") != "online":
            errors.append(
                f"{name} runtime {expected_provider} is {runtime.get('status') or 'unknown'}"
            )
        expected_model = desired_models.get(name)
        if expected_model and agent.get("model") != expected_model:
            errors.append(
                f"{name} model is {agent.get('model') or 'default'}; "
                f"blueprint requires {expected_model}"
            )

    squads = collection(
        run_multica(["multica", "squad", "list", "--output", "json"]), "squads"
    )
    squad = next((value for value in squads if value.get("name") == squad_name), None)
    if squad is None:
        errors.append(f"required live squad is missing: {squad_name}")
        return errors
    lead = agents_by_name.get("engineering-lead-01")
    if lead and squad.get("leader_id") != lead.get("id"):
        errors.append(f"{squad_name} is not led by engineering-lead-01")

    squad_id = squad.get("id")
    if not isinstance(squad_id, str):
        errors.append(f"{squad_name} has no usable id")
        return errors
    members = collection(
        run_multica(
            ["multica", "squad", "member", "list", squad_id, "--output", "json"]
        ),
        "members",
    )
    member_ids = {member.get("member_id") for member in members}
    for name in sorted(required):
        agent = agents_by_name.get(name)
        if agent and agent.get("id") not in member_ids:
            errors.append(f"{name} is not a member of {squad_name}")

    workspace_skills = collection(
        run_multica(["multica", "skill", "list", "--output", "json"]), "skills"
    )
    skill_names_by_id = {
        skill.get("id"): skill.get("name")
        for skill in workspace_skills
        if skill.get("id") and skill.get("name")
    }
    for name, names_required in sorted(required.items()):
        agent = agents_by_name.get(name)
        if not agent or not isinstance(agent.get("id"), str):
            continue
        bindings = collection(
            run_multica(
                [
                    "multica",
                    "agent",
                    "skills",
                    "list",
                    agent["id"],
                    "--output",
                    "json",
                ]
            ),
            "skills",
        )
        bound_names = {
            item.get("name")
            or item.get("skill_name")
            or skill_names_by_id.get(item.get("id") or item.get("skill_id"))
            for item in bindings
        }
        for skill_name in sorted(names_required - bound_names):
            errors.append(f"{name} is missing bound skill {skill_name}")
    return errors


def submission_preview(
    blueprint: dict[str, Any],
    plan: dict[str, Any],
    control_repository: str,
    project_id: str | None,
    create_project: bool,
    squad: str,
    start: bool,
) -> dict[str, Any]:
    project_action: dict[str, Any]
    if create_project:
        project_action = {
            "action": "create",
            "title": blueprint["title"],
            "status": "in_progress",
            "repository": control_repository,
        }
    else:
        project_action = {"action": "reuse", "project_id": project_id}
    return {
        "apply": False,
        "project": project_action,
        "issue": {
            "title": f"Deliver project: {blueprint['title']}",
            "assignee": squad,
            "status": "todo" if start else "backlog",
            "routing_status": plan["status"],
        },
    }


def submit(
    blueprint: dict[str, Any],
    plan: dict[str, Any],
    control_repository: str,
    project_id: str | None,
    create_project: bool,
    squad: str,
    start: bool,
    apply: bool,
) -> dict[str, Any]:
    preview = submission_preview(
        blueprint, plan, control_repository, project_id, create_project, squad, start
    )
    if not apply:
        return preview
    if plan["status"] != "ready":
        raise BlueprintError("routing plan is needs_human; resolve gaps before submission")
    authorizations = set(blueprint["execution"]["authorizations"])
    if "create_issues" not in authorizations:
        raise BlueprintError("submission requires create_issues authorization")
    if create_project and "create_multica_project" not in authorizations:
        raise BlueprintError("--create-project requires create_multica_project authorization")
    if not shutil.which("multica"):
        raise BlueprintError("multica CLI is not installed")
    preflight_errors = preflight_live(squad, plan)
    if preflight_errors:
        raise BlueprintError("live Multica preflight failed:\n- " + "\n- ".join(preflight_errors))

    resolved_project = project_id
    if create_project:
        project = run_multica(
            [
                "multica",
                "project",
                "create",
                "--title",
                blueprint["title"],
                "--description",
                blueprint["objective"],
                "--status",
                "in_progress",
                "--repo",
                control_repository,
                "--output",
                "json",
            ]
        )
        if not isinstance(project, dict):
            raise BlueprintError("created Multica project returned an unexpected response")
        resolved_project = project.get("id")
        if not isinstance(resolved_project, str) or not resolved_project:
            raise BlueprintError("created Multica project response has no id")

    assert resolved_project is not None
    issue_text = render_issue(blueprint, plan, control_repository)
    issue = run_multica(
        [
            "multica",
            "issue",
            "create",
            "--title",
            f"Deliver project: {blueprint['title']}",
            "--description-stdin",
            "--project",
            resolved_project,
            "--assignee",
            squad,
            "--status",
            "todo" if start else "backlog",
            "--output",
            "json",
        ],
        stdin=issue_text,
    )
    return {"apply": True, "project_id": resolved_project, "issue": issue}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "plan", "render", "preflight"):
        command = subparsers.add_parser(name)
        command.add_argument("blueprint", type=Path)
        if name == "render":
            command.add_argument("--control-repo")
        if name == "preflight":
            command.add_argument("--squad")

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("blueprint", type=Path)
    target = submit_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project-id")
    target.add_argument("--create-project", action="store_true")
    submit_parser.add_argument("--squad")
    submit_parser.add_argument("--control-repo")
    submit_parser.add_argument("--start", action="store_true")
    submit_parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        blueprint = load_document(args.blueprint.resolve())
        policy = load_document(ROUTING_POLICY)
        errors = validate_blueprint(blueprint, policy)
        if errors:
            raise BlueprintError("invalid Project Blueprint:\n- " + "\n- ".join(errors))
        if args.command == "validate":
            print(f"valid Project Blueprint: {blueprint['project_id']}")
            return 0
        plan = build_plan(blueprint)
        if args.command == "plan":
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0 if plan["status"] == "ready" else 3
        if args.command == "preflight":
            squad = args.squad or blueprint["execution"]["squad"]
            errors = preflight_live(squad, plan)
            result = {
                "status": "ready" if not errors else "needs_configuration",
                "squad": squad,
                "errors": errors,
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if not errors else 3
        control_repo = args.control_repo or git_origin()
        if args.command == "render":
            print(render_issue(blueprint, plan, control_repo))
            return 0 if plan["status"] == "ready" else 3
        squad = args.squad or blueprint["execution"]["squad"]
        result = submit(
            blueprint=blueprint,
            plan=plan,
            control_repository=control_repo,
            project_id=args.project_id,
            create_project=args.create_project,
            squad=squad,
            start=args.start,
            apply=args.apply,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BlueprintError, OSError) as error:
        print(f"Project Blueprint error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
