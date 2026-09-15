"""Plan Engine + Task Engine (sections 5 and 9).

The Planner produces a modifiable DAG of tasks before any design work.
The Task Engine executes them respecting dependencies, with retries and a
REQUIRES_REVIEW terminal state after repeated failures.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from core.events import EventBus
from core.memory import ProjectMemory
from core.models import Task, TaskStatus, utc_now_iso


class PlanEngine:
    """Builds an ordered task plan. Templates are declarative and editable."""

    def build_transport_machine_plan(self, project_id: str, ctx: dict[str, Any]) -> list[Task]:
        spec = [
            ("Analyze requirements", "requirements_engineer"),
            ("Compute traction force and motor power", "mechanical_engineer"),
            ("Research motor components (sourced)", "research_engineer"),
            ("Size transmission speed", "mechanical_engineer"),
            ("Verify shaft diameter against bending", "verification_engineer"),
            ("Compute electrical line current", "electrical_engineer"),
            ("Verify requirements coverage", "verification_engineer"),
            ("Generate engineering report", "documentation_engineer"),
        ]
        deps = {
            1: [0],
            2: [1],
            3: [1],
            4: [1],
            5: [1],
            6: [4, 5],
            7: [6],
        }
        tasks: list[Task] = []
        id_by_idx: dict[int, str] = {}
        for i, (title, agent) in enumerate(spec):
            t = Task(project_id=project_id, title=title, agent=agent, priority=5)
            id_by_idx[i] = t.id
            tasks.append(t)
        for i, task in enumerate(tasks):
            task.dependencies = [id_by_idx[j] for j in deps.get(i, [])]
            task.input = dict(ctx)
        return tasks

    def build_generic_plan(self, project_id: str, ctx: dict[str, Any]) -> list[Task]:
        spec = [
            ("Analyze requirements", "requirements_engineer"),
            ("Research missing technical data", "research_engineer"),
            ("Perform engineering calculations", "mechanical_engineer"),
            ("Verify results", "verification_engineer"),
            ("Generate engineering report", "documentation_engineer"),
        ]
        deps = {1: [0], 2: [1], 3: [2], 4: [3]}
        tasks: list[Task] = []
        id_by_idx: dict[int, str] = {}
        for i, (title, agent) in enumerate(spec):
            t = Task(project_id=project_id, title=title, agent=agent, priority=5)
            id_by_idx[i] = t.id
            tasks.append(t)
        for i, task in enumerate(tasks):
            task.dependencies = [id_by_idx[j] for j in deps.get(i, [])]
            task.input = dict(ctx)
        return tasks


class TaskEngine:
    def __init__(self, bus: EventBus, memory: ProjectMemory, max_retries: int = 2) -> None:
        self.bus = bus
        self.memory = memory
        self.max_retries = max_retries

    async def run_plan(
        self,
        tasks: list[Task],
        handlers: dict[str, Callable[[Task], Awaitable[dict[str, Any]]]],
    ) -> list[Task]:
        done: dict[str, bool] = {}
        pending = list(tasks)

        while pending:
            progress = False
            still: list[Task] = []
            for task in pending:
                if not all(done.get(d) for d in task.dependencies):
                    still.append(task)
                    continue
                await self._run_one(task, handlers.get(task.agent))
                done[task.id] = task.status in (TaskStatus.SUCCESS, TaskStatus.REQUIRES_REVIEW)
                progress = True
            if not progress:
                blocked_ids = [t.id for t in pending]
                for t in pending:
                    t.status = TaskStatus.BLOCKED
                    self.memory.save_task(t.project_id, t)
                raise RuntimeError(f"deadlock: tasks blocked on unmet dependencies: {blocked_ids}")
            pending = still
        return tasks

    async def _run_one(
        self, task: Task, handler: Callable[[Task], Awaitable[dict[str, Any]]] | None
    ) -> None:
        task.status = TaskStatus.RUNNING
        task.attempts += 1
        task.started_at = task.started_at or utc_now_iso()
        self.memory.save_task(task.project_id, task)
        await self.bus.publish(
            "TASK_STARTED",
            {"project_id": task.project_id, "task_id": task.id, "title": task.title, "agent": task.agent},
        )

        if handler is None:
            task.status = TaskStatus.FAILED
            task.errors.append(f"no handler registered for agent '{task.agent}'")
            task.finished_at = utc_now_iso()
            self.memory.save_task(task.project_id, task)
            await self.bus.publish("TASK_FAILED", {"task_id": task.id, "error": task.errors[-1]})
            return

        try:
            task.output = await handler(task)
            task.status = TaskStatus.SUCCESS
            task.finished_at = utc_now_iso()
            self.memory.save_task(task.project_id, task)
            await self.bus.publish(
                "TASK_COMPLETED",
                {"project_id": task.project_id, "task_id": task.id, "title": task.title, "agent": task.agent},
            )
        except Exception as exc:  # noqa: BLE001 - agents must fail cleanly
            task.errors.append(f"{type(exc).__name__}: {exc}")
            if task.attempts <= self.max_retries:
                task.status = TaskStatus.RETRYING
                await self._run_one(task, handler)
            else:
                task.status = TaskStatus.REQUIRES_REVIEW
                task.finished_at = utc_now_iso()
                self.memory.save_task(task.project_id, task)
                await self.bus.publish(
                    "TASK_FAILED",
                    {"project_id": task.project_id, "task_id": task.id, "error": task.errors[-1]},
                )
