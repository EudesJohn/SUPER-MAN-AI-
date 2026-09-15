"""Agent system (section 3/8 of the spec): common interface + implementations.

Every agent implements the same interface. Agents NEVER compute engineering
numbers themselves and NEVER touch the OS: they orchestrate tools and the
deterministic engines (CalculationEngine, RequirementsEngine, ...).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.calculation import CalculationEngine
from core.models import Task, TaskStatus, VerificationResult, VerificationOutcome
from core.requirements import RequirementsEngine
from core.units import convert as unit_convert


class Agent(ABC):
    name: str = "agent"
    role: str = "generic"

    def __init__(self, context: "AgentContext") -> None:
        self.ctx = context

    @abstractmethod
    async def execute(self, task: Task) -> dict[str, Any]:
        """Perform the task and return structured output."""

    def capabilities(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role}


class AgentContext:
    """Shared services injected into every agent (dependency injection)."""

    def __init__(
        self,
        *,
        memory,
        bus,
        calc: CalculationEngine,
        registry,
        llm_gateway=None,
        router=None,
        verification=None,
        component_researcher=None,
    ) -> None:
        self.memory = memory
        self.bus = bus
        self.calc = calc
        self.registry = registry
        self.llm = llm_gateway
        self.router = router
        self.verification = verification
        self.component_researcher = component_researcher


# ---------------------------------------------------------------------- #
# Specialized agents
# ---------------------------------------------------------------------- #
class RequirementsEngineer(Agent):
    name = "requirements_engineer"
    role = "Extract formal requirements from the cahier des charges"

    async def execute(self, task: Task) -> dict[str, Any]:
        text = str(task.input.get("cahier_des_charges", ""))
        if not text.strip():
            raise ValueError("empty cahier des charges")
        reqs = RequirementsEngine().extract(text)
        for r in reqs:
            self.ctx.memory.add_requirement(task.project_id, r)
        await self.ctx.bus.publish(
            "REQUIREMENT_ADDED", {"count": len(reqs), "project_id": task.project_id}
        )
        return {"requirements": [r.model_dump() for r in reqs], "count": len(reqs)}


class ResearchEngineer(Agent):
    """Real web research when a SearchProvider is configured; otherwise
    missing data is declared INCONNU (never fabricated)."""

    name = "research_engineer"
    role = "Find and qualify technical information (web/datasheets)"

    async def execute(self, task: Task) -> dict[str, Any]:
        gaps = list(task.input.get("known_gaps", []))
        researcher = getattr(self.ctx, "component_researcher", None)
        if researcher is None:
            return {
                "status": "offline",
                "message": "Web research disabled (search.provider=none). Missing data must be treated as INCONNU.",
                "gaps": gaps,
            }
        power_w = task.input.get("power_w")
        if power_w is None:
            return {
                "status": "incomplete",
                "message": "Shaft power not computed yet - motor research skipped.",
                "gaps": gaps,
            }
        component = await researcher.research_motor(
            task.project_id,
            float(power_w),
            voltage_v=task.input.get("voltage_v"),
        )
        return {"status": "ok", "component": component, "gaps": gaps}


class MechanicalEngineer(Agent):
    name = "mechanical_engineer"
    role = "Mechanical sizing via deterministic calculators"

    async def execute(self, task: Task) -> dict[str, Any]:
        inputs = task.input
        mass = inputs.get("mass_kg")
        speed = inputs.get("speed_m_s")
        mu = float(inputs.get("friction_coefficient", 0.15))
        eta = float(inputs.get("efficiency", 0.8))

        if mass is None or speed is None:
            raise ValueError("INCONNU: mass or speed missing - cannot size drive without hypotheses")

        rec_power = self.ctx.calc.run(
            "motor_sizing_from_specs",
            {"mass_si": float(mass), "speed_si": float(speed), "friction_coefficient": mu, "efficiency": eta},
            assumptions=[
                f"friction coefficient mu={mu} (HYPOTHESIS)",
                f"transmission efficiency eta={eta} (HYPOTHESIS)",
                "horizontal transport, no acceleration phase (HYPOTHESIS)",
            ],
            requirement_ids=inputs.get("requirement_ids", []),
        )

        # Traction force is stored separately: it feeds downstream checks
        # (shafts, bearings, chassis) and the traceability graph.
        rec_force = self.ctx.calc.run(
            "traction_force",
            {"mass_si": float(mass), "friction_coefficient": mu, "acceleration_si": 0.0},
            assumptions=[f"friction coefficient mu={mu} (HYPOTHESIS)"],
            requirement_ids=inputs.get("requirement_ids", []),
        )

        # Transmission speed example: 200 mm drum/pulley diameter
        pulley_d = float(inputs.get("pulley_diameter_m", 0.2))
        rec_speed = self.ctx.calc.run(
            "linear_speed_to_rotational",
            {"speed_si": float(speed), "diameter_si": pulley_d},
            assumptions=[f"pulley diameter {pulley_d} m (HYPOTHESIS)"],
        )

        self.ctx.memory.add_calculation(task.project_id, rec_power)
        self.ctx.memory.add_calculation(task.project_id, rec_force)
        self.ctx.memory.add_calculation(task.project_id, rec_speed)

        await self.ctx.bus.publish(
            "CALCULATION_COMPLETED",
            {"project_id": task.project_id, "calc_id": rec_power.id, "name": rec_power.name,
             "result": rec_power.result, "unit": rec_power.result_unit},
        )
        return {
            "power": rec_power.model_dump(),
            "force": rec_force.model_dump(),
            "speed": rec_speed.model_dump(),
        }


class ElectricalEngineer(Agent):
    name = "electrical_engineer"
    role = "Electrical pre-sizing (three-phase current)"

    async def execute(self, task: Task) -> dict[str, Any]:
        power_w = task.input.get("power_w")
        voltage_v = float(task.input.get("voltage_v", 400))
        if power_w is None:
            raise ValueError("INCONNU: shaft power missing - run mechanical sizing first")
        # Three-phase line current: I = P / (sqrt(3) * U * cos(phi))
        cos_phi = float(task.input.get("cos_phi", 0.85))
        eta = float(task.input.get("eta_motor", 0.9))
        i = power_w / (3 ** 0.5 * voltage_v * cos_phi * eta)
        from core.models import CalculationRecord

        rec = CalculationRecord(
            name="three_phase_line_current",
            formula="I = P / (sqrt(3) * U * cos_phi * eta_motor)",
            inputs={"power_w": power_w, "voltage_v": voltage_v, "cos_phi": cos_phi, "eta_motor": eta},
            units={"result": "A"},
            result=round(i, 2),
            result_unit="A",
            assumptions=[f"cos_phi={cos_phi} (HYPOTHESIS)", f"motor efficiency={eta} (HYPOTHESIS)"],
        )
        self.ctx.memory.add_calculation(task.project_id, rec)
        return {"current": rec.model_dump()}


class DocumentationEngineer(Agent):
    name = "documentation_engineer"
    role = "Generate the technical report from stored records"

    async def execute(self, task: Task) -> dict[str, Any]:
        from core.report import generate_report

        path = generate_report(task.project_id, self.ctx.memory, self.ctx.registry)
        return {"report_path": path}


class VerificationEngineer(Agent):
    """Thin agent wrapper around the independent Verification Engine."""

    name = "verification_engineer"
    role = "Independently check designs, calculations and requirement coverage"

    async def execute(self, task: Task) -> dict[str, Any]:
        if self.ctx.verification is None:
            raise RuntimeError("VerificationEngine not configured")
        results = await self.ctx.verification.verify_project(task.project_id)
        return {"verifications": [r.model_dump() for r in results]}


class ElectricalDesignAgent(Agent):
    """Designs the low-voltage electrical system via the deterministic engine."""

    name = "electrical_design_engineer"
    role = "Design and size the 12 V electrical system (wires, fuses, drops)"

    async def execute(self, task: Task) -> dict[str, Any]:
        from core.electrical_design import DEFAULT_CIRCUITS, CircuitSpec, ElectricalDesignEngine

        circuits_raw = task.input.get("circuits") or [
            {"name": c.name, "description": c.description, "load_w": c.load_w,
             "length_m": c.length_m, "kind": c.kind}
            for c in DEFAULT_CIRCUITS
        ]
        circuits = [CircuitSpec(**c) for c in circuits_raw]
        engine = ElectricalDesignEngine(self.ctx.calc)
        design = engine.design(
            circuits,
            system_voltage=float(task.input.get("system_voltage", 12.0)),
            battery_ah=float(task.input.get("battery_ah", 80.0)),
            alternator_max_a=float(task.input.get("alternator_max_a", 90.0)),
            requirement_ids=list(task.input.get("requirement_ids", [])),
        )
        await self.ctx.bus.publish(
            "CALCULATION_COMPLETED",
            {"project_id": task.project_id, "name": "electrical_design",
             "result": len(design["circuits"]), "unit": "circuits"},
        )
        return {"design": design}


class TractorCadAgent(Agent):
    """Builds the parametric 3D tractor (mechanical + electrical routed in 3D)
    and exports STL groups through the sandboxed file tools."""

    name = "tractor_cad_engineer"
    role = "Parametric 3D assemblies (STL) via CAD provider + sandboxed writers"

    async def execute(self, task: Task) -> dict[str, Any]:
        import json

        from providers.cad.provider import detect_provider
        from providers.cad.tractor import build_tractor, export_tractor

        provider, notes = detect_provider(None)
        ok, reason = provider.availability()
        if not ok:
            raise RuntimeError(f"CAD provider unavailable: {reason}")

        build = build_tractor(task.input.get("tractor_spec") or None)
        out_rel = task.input.get("out_rel") or f"{task.project_id}/cad/tractor"
        registry = self.ctx.registry

        def writer(rel_path: str, data: bytes) -> dict[str, Any]:
            return registry.execute("write_file_bytes", agent=self.name, path=rel_path, content=data)

        result = export_tractor(build, out_rel, writer, provider)

        svg = None
        design = task.input.get("design")
        if design:
            from core.schematic import render_schematic_svg

            svg = render_schematic_svg(design, title=f"Tracteur 12 V - projet {task.project_id}")
            registry.execute("write_text", agent=self.name,
                             path=f"{out_rel}/electrical_schematic.svg", content=svg)
            registry.execute("write_text", agent=self.name,
                             path=f"{out_rel}/electrical_design.json",
                             content=json.dumps(design, ensure_ascii=False, indent=2))

        await self.ctx.bus.publish(
            "CAD_CREATED",
            {"project_id": task.project_id, "out": out_rel,
             "groups": sorted(result["files"]), "total_mass_kg": result["total_mass_kg"]},
        )
        return {"cad": result, "out_rel": out_rel, "svg": svg, "cad_notes": notes}


class MasterEngineer(Agent):
    """Coordinator: builds the plan, delegates, never computes itself."""

    name = "master_engineer"
    role = "Orchestrate the specialist agents and the workflow"

    async def execute(self, task: Task) -> dict[str, Any]:
        from core.planning import PlanEngine

        plan = PlanEngine().build_transport_machine_plan(task.project_id, task.input)
        return {"plan": [t.model_dump() for t in plan], "note": "plan built; executed by TaskEngine"}
