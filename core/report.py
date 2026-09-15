"""Technical report generation (section 28): Markdown report from memory.

The report contains ONLY what is actually stored: requirements, calculations,
verifications, assumptions, sources, versions. Missing information is printed
as INCONNU. This is a document, not a fabrication.
"""
from __future__ import annotations

from typing import Any


def generate_report(project_id: str, memory, registry=None) -> str:
    project = memory.get_project(project_id) or {"name": project_id, "description": ""}
    reqs = memory.list_requirements(project_id)
    calcs = memory.list_calculations(project_id)
    vers = memory.list_verifications(project_id)
    hyps = memory.list_assumptions(project_id)
    sources = memory.list_sources(project_id)
    versions = memory.list_versions(project_id)

    lines: list[str] = []
    lines.append(f"# Rapport technique - {project['name']}")
    lines.append("")
    lines.append(f"_Projet : `{project_id}` - genere par AI ENGINEER (MVP)_")
    lines.append("")
    if project.get("description"):
        lines.append(f"**Cahier des charges :** {project['description']}")
        lines.append("")

    # Requirements
    lines.append("## 1. Exigences")
    if not reqs:
        lines.append("_Aucune exigence enregistree._")
    for r in reqs:
        val = f" = {r['raw_value']}" if r.get("raw_value") else " (INCONNU)"
        lines.append(
            f"- **{r['id']}** [{r.get('priority', 'mandatory')}] {r['description']}{val}"
            f" - statut: {r.get('status', 'draft')} - confiance: {r.get('confidence', '?')}"
        )
    lines.append("")

    # Calculations
    lines.append("## 2. Calculs")
    if not calcs:
        lines.append("_Aucun calcul effectue._")
    for c in calcs:
        lines.append(f"### {c['id']} - {c['name']}")
        lines.append(f"- Formule : `{c['formula']}`")
        lines.append(f"- Entrees (SI) : {c['inputs']}")
        lines.append(f"- **Resultat : {c['result']:.4g} {c['result_unit']}**")
        if c.get("assumptions"):
            for a in c["assumptions"]:
                lines.append(f"- HYPOTHESE : {a}")
        if c.get("requirement_ids"):
            lines.append(f"- Trace : {', '.join(c['requirement_ids'])}")
        lines.append("")

    # Verifications
    lines.append("## 3. Verifications")
    if not vers:
        lines.append("_Aucune verification effectuee._")
    for v in vers:
        lines.append(f"- **{v['id']}** [{v['outcome']}] {v['subject']} : {v['detail']}")
    lines.append("")

    # Assumptions
    lines.append("## 4. Hypotheses")
    if not hyps:
        lines.append("_Aucune hypothese explicite enregistree (voir hypotheses dans les calculs)._")
    for h in hyps:
        lines.append(f"- **{h['id']}** {h['statement']}")
    lines.append("")

    # Sources
    lines.append("## 5. Sources")
    if not sources:
        lines.append("_Aucune source externe utilisee (mode hors-ligne)._")
    for s in sources:
        url = s.get("url") or "INCONNU"
        lines.append(f"- {s.get('title', 'INCONNU')} - {url} - confiance: {s.get('confidence', 'unknown')}")
    lines.append("")

    # Versions
    lines.append("## 6. Versions")
    if not versions:
        lines.append("_Aucune version enregistree._")
    for v in versions:
        lines.append(f"- V{v['number']}: {v['summary']} ({v['created_at']})")
    lines.append("")

    lines.append("---")
    lines.append(
        "**AVERTISSEMENT :** resultats generes automatiquement. Une validation humaine "
        "(et reglementaire le cas echeant) reste requise avant toute fabrication ou mise en service."
    )

    content = "\n".join(lines)
    out_dir = f"workspace/{project_id}/reports"
    import pathlib

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = f"{out_dir}/technical_report.md"
    pathlib.Path(path).write_text(content, encoding="utf-8")
    return path
