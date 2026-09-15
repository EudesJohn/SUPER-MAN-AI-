"""API-level tests using FastAPI TestClient (in-process, offline)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app, STATE
from core.calculation import CalculationEngine
from core.components import ComponentResearcher
from core.events import EventBus
from core.memory import ProjectMemory
from core.research import WebResearchEngine
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Fresh in-process state for each test (lifespan runs on __enter__).
    STATE.clear()
    # Disable web research for deterministic offline tests.
    monkeypatch.setenv("AI_ENGINEER_TEST", "1")
    with TestClient(app) as c:
        # Override research config to disabled after lifespan init.
        from core.config import AppConfig

        STATE["config"] = AppConfig()
        STATE["component_researcher"] = None
        STATE["orchestrator"].component_researcher = None
        yield c


SPEC = (
    "Je veux concevoir une machine industrielle capable de transporter 500 kg "
    "a 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence."
)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_execute_then_summary_reassembles_run(client):
    # Create + execute
    prj = client.post("/projects", json={"name": "Hist test", "description": "desc"}).json()
    pid = prj["id"]
    res = client.post(f"/projects/{pid}/execute", json={"cahier_des_charges": SPEC}).json()
    assert res["power_w"] is not None

    # Summary must reassemble everything from memory alone
    s = client.get(f"/projects/{pid}/summary").json()
    assert s["project_id"] == pid
    assert s["name"] == "Hist test"
    assert len(s["requirements"]) >= 4
    assert s["power_w"] == pytest.approx(res["power_w"], rel=1e-9)
    assert len(s["tasks"]) >= 6
    assert all(t["status"] == "SUCCESS" for t in s["tasks"])
    assert s["versions"], "version missing from summary"
    assert s["all_verifications_pass"] is True
    assert s["known_gaps"] == []


def test_summary_404(client):
    assert client.get("/projects/PRJ-inexistant/summary").status_code == 404


def test_summary_without_numeric_requirements(client):
    prj = client.post("/projects", json={"name": "Sparse", "description": ""}).json()
    client.post(f"/projects/{prj['id']}/execute",
                json={"cahier_des_charges": "Une machine qui transporte des choses."})
    s = client.get(f"/projects/{prj['id']}/summary").json()
    assert set(s["known_gaps"]) == {"mass", "speed"}
    assert s["component"] is None


def test_research_disabled_returns_400(client):
    prj = client.post("/projects", json={"name": "NoSearch", "description": ""}).json()
    r = client.post(f"/projects/{prj['id']}/research", json={"query": "moteur"})
    assert r.status_code == 400
    assert "disabled" in r.json()["detail"]


def test_components_endpoint_lists_sourced_components(client):
    """With a fake researcher wired in, execute stores a component and the
    endpoint returns it."""
    from tests.test_research import FakeFetcher, FakeProvider

    engine = WebResearchEngine(
        STATE["memory"], STATE["bus"], FakeProvider(
            ["https://www.sew-eurodrive.fr/a", "https://www.nord.com/b"]
        ), FakeFetcher({"https://www.sew-eurodrive.fr/a", "https://www.nord.com/b"}),
    )
    researcher = ComponentResearcher(engine)
    STATE["component_researcher"] = researcher
    STATE["orchestrator"].component_researcher = researcher

    prj = client.post("/projects", json={"name": "Comp", "description": ""}).json()
    client.post(f"/projects/{prj['id']}/execute",
                json={"cahier_des_charges": "transporter 100 kg a 10 m/min sous 400 V triphase"})
    comps = client.get(f"/projects/{prj['id']}/components").json()
    assert len(comps) == 1
    assert comps[0]["status"] == "SOURCED"
    assert len(comps[0]["manufacturer_domains"]) >= 2
