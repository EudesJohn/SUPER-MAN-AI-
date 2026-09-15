"""Orchestrator (Master Engineer): coordinates the whole MVP workflow.

USER -> REQUIREMENTS -> PLAN -> SPECIALIZED AGENTS -> TOOLS/ENGINES ->
CALCULATIONS -> VERIFICATION -> REPORT -> VERSION.

The orchestrator never computes engineering values itself: it delegates to
agents, which delegate to deterministic engines.
"""
from __future__ import annotations

from typing import Any

from core.agents.base import (
    AgentContext,
    DocumentationEngineer,
    ElectricalEngineer,
    MechanicalEngineer,
    RequirementsEngineer,
    ResearchEngineer,
    VerificationEngineer,
)
from core.calculation import CalculationEngine
from core.events import EventBus
from core.memory import ProjectMemory
from core.models import Task, TaskStatus, VerificationOutcome
from core.planning import PlanEngine, TaskEngine
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine


class Orchestrator:
    def __init__(
        self,
        memory: ProjectMemory,
        bus: EventBus,
        calc: CalculationEngine,
        registry: ToolRegistry,
        verification: VerificationEngine,
        max_retries: int = 2,
        component_researcher=None,
    ) -> None:
        self.memory = memory
        self.bus = bus
        self.calc = calc
        self.registry = registry
        self.verification = verification
        # Persist every event of every project (event sourcing).
        bus.persist_hook = lambda event: memory.append_event(
            event["payload"].get("project_id"), event
        )
        self.max_retries = max_retries
        self.component_researcher = component_researcher

    async def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        project = self.memory.create_project(name, description)
        await self.bus.publish(
            "PROJECT_CREATED", {"project_id": project["id"], "name": name}
        )
        return project

    async def execute(self, project_id: str, cahier_des_charges: str) -> dict[str, Any]:
        if self.memory.get_project(project_id) is None:
            raise KeyError(f"project {project_id} does not exist")

        # Blackboard shared between agent handlers (results of prior tasks).
        state: dict[str, Any] = {"cahier_des_charges": cahier_des_charges}

        ctx = AgentContext(
            memory=self.memory,
            bus=self.bus,
            calc=self.calc,
            registry=self.registry,
            verification=self.verification,
            component_researcher=self.component_researcher,
        )
        agents = {
            "requirements_engineer": RequirementsEngineer(ctx),
            "research_engineer": ResearchEngineer(ctx),
            "mechanical_engineer": MechanicalEngineer(ctx),
            "electrical_engineer": ElectricalEngineer(ctx),
            "verification_engineer": VerificationEngineer(ctx),
            "documentation_engineer": DocumentationEngineer(ctx),
        }

        # ---------------- Step 1: requirements (needed to build ctx) ------ #
        reqs = agents["requirements_engineer"]
        pre_task = Task(project_id=project_id, title="Analyze requirements", agent=reqs.name)
        pre_task.input = {"cahier_des_charges": cahier_des_charges}
        req_result = await reqs.execute(pre_task)
        state["requirements"] = req_result["requirements"]
        state["requirement_ids"] = [
            r["id"] for r in state["requirements"] if r.get("value") is not None
        ]

        # Numeric context (SI) pulled from extracted requirements.
        by_dim = {r["quantity"]: r for r in state["requirements"] if r.get("value") is not None}
        state["mass_kg"] = by_dim["mass"]["value"] if "mass" in by_dim else None
        state["speed_m_s"] = by_dim["speed"]["value"] if "speed" in by_dim else None
        state["voltage_v"] = by_dim["voltage"]["value"] if "voltage" in by_dim else 400.0

        state["known_gaps"] = [
            d
            for d, key in (("mass", "mass_kg"), ("speed", "speed_m_s"))
            if state.get(key) is None
        ]

        # ---------------- Step 2: plan ----------------------------------- #
        plan = PlanEngine().build_transport_machine_plan(project_id, dict(state))
        for t in plan:
            self.memory.save_task(project_id, t)
        await self.bus.publish("PLAN_CREATED", {"project_id": project_id, "tasks": len(plan)})

        # ---------------- Step 3: handlers -------------------------------- #
        async def h_requirements(task: Task) -> dict[str, Any]:
            return {"requirements": state["requirements"], "count": len(state["requirements"])}

        async def h_research(task: Task) -> dict[str, Any]:
            t = task.model_copy(
                update={
                    "input": {
                        **task.input,
                        "power_w": state.get("power_w"),
                        "voltage_v": state.get("voltage_v"),
                    }
                }
            )
            out = await agents["research_engineer"].execute(t)
            if out.get("status") == "ok":
                state["component"] = out["component"]
            return out

        async def h_mechanical(task: Task) -> dict[str, Any]:
            out = await agents["mechanical_engineer"].execute(task)
            state["power_w"] = out["power"]["result"]
            return out

        async def h_verification_mech(task: Task) -> dict[str, Any]:
            return await agents["verification_engineer"].execute(task)

        async def h_electrical(task: Task) -> dict[str, Any]:
            t = task.model_copy(update={"input": {**task.input, "power_w": state.get("power_w")}})
            return await agents["electrical_engineer"].execute(t)

        async def h_verify_coverage(task: Task) -> dict[str, Any]:
            return await agents["verification_engineer"].execute(task)

        async def h_report(task: Task) -> dict[str, Any]:
            return await agents["documentation_engineer"].execute(task)

        handlers = {
            "requirements_engineer": h_requirements,
            "research_engineer": h_research,
            "mechanical_engineer": h_mechanical,
            "verification_engineer": h_verification_mech,  # used by both verify tasks
            "electrical_engineer": h_electrical,
            "documentation_engineer": h_report,
        }

        task_engine = TaskEngine(self.bus, self.memory, max_retries=self.max_retries)
        await task_engine.run_plan(plan, handlers)

        # ---------------- Step 4: persist verifications & version --------- #
        verifications = await self.verification.verify_project(project_id)
        all_pass = all(v.outcome == VerificationOutcome.PASS for v in verifications) and len(verifications) > 0
        summary_bits = []
        if state.get("power_w") is not None:
            summary_bits.append(f"shaft power {state['power_w']:.0f} W")
        if state.get("component") is not None:
            summary_bits.append(f"motor research {state['component']['status']}")
        summary_bits.append(f"{len(state['requirements'])} requirements")
        version = self.memory.create_version(
            project_id, "MVP run: " + ", ".join(summary_bits), created_by="orchestrator"
        )
        await self.bus.publish(
            "PROJECT_VALIDATED" if all_pass else "INFO",
            {"project_id": project_id, "all_verifications_pass": all_pass},
        )

        tasks_view = self.memory.list_tasks(project_id)
        return {
            "project_id": project_id,
            "requirements": state["requirements"],
            "known_gaps": state["known_gaps"],
            "power_w": state.get("power_w"),
            "tasks": [
                {"id": t["id"], "title": t["title"], "agent": t["agent"], "status": t["status"]}
                for t in tasks_view
            ],
            "verifications": [v.model_dump(mode="json") for v in verifications],
            "component": state.get("component"),
            "version": version,
            "all_verifications_pass": all_pass,
        }
