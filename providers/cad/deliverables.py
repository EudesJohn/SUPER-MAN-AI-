"""Deliverables packager: one folder = everything an engineer opens in AutoCAD.

Layout (under <project>/cad/tractor/deliverables/) - organized by dimension,
like an experienced engineer hands over a package:

  3D_MODELES/                       everything SOLID (open in AutoCAD 3D)
    TRACTEUR_3D_ENSEMBLE.dxf        the WHOLE machine, real 3D (3DFACE, mm),
                                    one layer per group, AutoCAD colors
    PIECES/PIECE_<name>.dxf         each part alone, real 3D, its own layer
  2D_PLANS/                         everything DRAWN (sheets)
    PLANS_ENSEMBLE_ET_PIECES.dxf    all 2D sheets in ONE DXF (A3 grid)
    SCHEMA_ELECTRIQUE.dxf           the 12 V schematic (functional layers)
    CABLAGE.dxf                     the wiring routing sheet
  1D_DONNEES/                       everything LISTED (numbers, not drawings)
    NOMENCLATURE.csv                bill of materials: parts, mass, material
    CABLAGE_COMPLET.csv             wire schedule (id, from, to, mm2, fuse...)
    CIRCUITS_ELECTRIQUES.csv        sizing per circuit (I, gauge, dU, fuse)
    VERIFICATIONS.csv               independent verification outcomes
    INDEX_LIVRABLES.csv             what every file in this package is
  LISEZ-MOI.txt                     reading guide + honesty notes
  LIVRABLES_COMPLETS.zip            the whole folder as one download

Everything goes through the sandboxed writer - agents never touch the OS.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any, Callable

from providers.cad.dxf3d import assembly_dxf3d_content, part_dxf3d_content
from providers.cad.tractor import GROUP_SPECS, TractorBuild

Writer = Callable[[str, bytes], dict[str, Any]]

ACI_COLORS = {"white": 7, "red": 1, "yellow": 2, "green": 3, "cyan": 4,
              "blue": 5, "magenta": 6, "gray": 8}
GROUP_ACI = {
    "body": ACI_COLORS["green"], "structure": ACI_COLORS["gray"],
    "wheels": ACI_COLORS["blue"], "engine": ACI_COLORS["yellow"],
    "cabin": ACI_COLORS["cyan"], "electrical": ACI_COLORS["red"],
    "harness": ACI_COLORS["magenta"],
}
GROUP_MATERIAL = {
    "body": "PLASTIQUE", "structure": "ACIER", "wheels": "CAOUTCHOUC",
    "engine": "FONTE", "cabin": "PLASTIQUE/VERRE", "electrical": "PLOMB/PLASTIQUE",
    "harness": "CUIVRE/PLASTIQUE",
}


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")   # BOM: Excel-friendly


def _combined_2d_dxf(sheets, project_id: str) -> bytes:
    """All 2D sheets laid out on an A3 grid inside ONE DXF document."""
    from providers.cad.drawings import DXF_LAYERS, dxf_document, sheet_to_dxf

    COLS, DXF_W, DXF_H = 4, 420.0, 297.0
    entities: list[list[str]] = []
    for k, sheet in enumerate(sheets):
        dx = (k % COLS) * (DXF_W + 30.0)
        dy = (k // COLS) * (DXF_H + 30.0)
        for e in sheet_to_dxf(sheet, project_id):
            it = iter(e)
            out_tags: list[str] = []
            for code, val in zip(it, it):
                if code in ("10", "20", "11", "21", "12", "22", "13", "23"):
                    v = float(val) + (dx if code in ("10", "11", "12", "13") else dy)
                    val = f"{v:.3f}"
                out_tags += [code, val]
            entities.append(out_tags)
    return dxf_document(DXF_LAYERS, entities).encode("ascii", errors="replace")


def package_deliverables(
    build: TractorBuild,
    wire_schedule: list[dict[str, str]],
    design: dict[str, Any] | None,
    verifications: list[dict[str, Any]],
    out_rel: str,
    project_id: str,
    writer: Writer,
    workspace_root: Path,
    part_sheets: list | None = None,
    extra_2d: list[tuple[str, str]] | None = None,
    label: str = "TRACTEUR",
) -> dict[str, Any]:
    """Create the AutoCAD-ready deliverables folder + ZIP.

    part_sheets: Sheet objects (per-part + arrangement) to combine into one DXF.
    extra_2d: (rel_path, description) of 2D files already written by the caller
    (schematic + wiring DXF) to include in the package index/ZIP.
    label: machine name used in file names (TRACTEUR, VOITURE...).
    """
    base = f"{out_rel}/deliverables"
    written: list[str] = []
    index: list[list[str]] = []   # INDEX_LIVRABLES rows

    def w(rel: str, data: bytes, what: str, dim: str) -> None:
        writer(rel, data)
        written.append(rel)
        index.append([dim, rel.split("/deliverables/", 1)[1], what])

    # ============================ 3D_MODELES ============================ #
    d3 = f"{base}/3D_MODELES"
    assembly_rel = f"{d3}/{label}_3D_ENSEMBLE.dxf"
    w(assembly_rel,
      assembly_dxf3d_content(build.groups, GROUP_ACI).encode("ascii", errors="replace"),
      "Machine COMPLETE en 3D (3DFACE, mm) - 1 couche par groupe - AutoCAD", "3D")
    part_files: list[dict[str, str]] = []
    for name, m in build.part_meshes.items():
        rel = f"{d3}/PIECES/PIECE_{_safe_name(name)}.dxf"
        w(rel, part_dxf3d_content(m, name).encode("ascii", errors="replace"),
          f"Piece {name} en 3D seule - AutoCAD", "3D")
        part_files.append({"part": name, "path": rel, "triangles": m.n_triangles})

    # ============================= 2D_PLANS ============================= #
    d2 = f"{base}/2D_PLANS"
    combined_rel: str | None = None
    if part_sheets:
        combined_rel = f"{d2}/PLANS_ENSEMBLE_ET_PIECES.dxf"
        w(combined_rel, _combined_2d_dxf(part_sheets, project_id),
          "TOUTES les feuilles 2D (ensemble + pieces) dans UN DXF, grille A3", "2D")
    for rel, desc in extra_2d or []:
        written.append(rel)
        index.append(["2D", rel.split("/deliverables/", 1)[1], desc])

    # ============================ 1D_DONNEES ============================ #
    d1 = f"{base}/1D_DONNEES"
    # ---- BOM: bill of materials ----
    bom_rows = [[f"BOM-{i:03d}", p["name"], GROUP_MATERIAL.get(p["group"], p["group"].upper()),
                 p["group"], p["mass_kg"], "1", p.get("note", "")]
                for i, p in enumerate(build.parts, start=1)]
    w(f"{d1}/NOMENCLATURE.csv",
      _csv_bytes(["rep", "designation", "matiere", "groupe", "masse_kg", "qte", "observation"],
                 bom_rows),
      "Nomenclature (BOM) des pieces - Excel / import AutoCAD", "1D")

    # ---- wire schedule ----
    w(f"{d1}/CABLAGE_COMPLET.csv",
      _csv_bytes(["fil", "de", "vers", "circuit", "courant_A", "section_mm2",
                  "couleur", "fusible", "couche_DXF"],
                 [[r["id"], r["de"], r["vers"], r["circuit"], r["a"], r["mm2"],
                   r["couleur"], r["fusible"], r["layer"]] for r in wire_schedule]),
      "Tableau de cablage borne a borne - Excel / import AutoCAD", "1D")

    # ---- circuit sizing ----
    if design:
        circ_rows = [[c["name"], c["description"], c["kind"],
                      f"{c['current_a']:.2f}", f"{c['gauge_mm2']:g}", f"{c['capacity_a']:g}",
                      f"{c['drop_pct']:.2f}", f"F{c['fuse_a']:g}" if c["fuse_a"] else "sans*",
                      c["color"]] for c in design["circuits"]]
        w(f"{d1}/CIRCUITS_ELECTRIQUES.csv",
          _csv_bytes(["circuit", "description", "type", "courant_A", "section_mm2",
                      "capacite_A", "dU_%", "fusible", "couleur"], circ_rows),
          "Dimensionnement par circuit (courant/section/chute/fusible)", "1D")

    # ---- independent verifications ----
    if verifications:
        ver_rows = [[v.get("id", ""), v.get("subject", ""), v.get("outcome", ""),
                     v.get("detail", "")] for v in verifications]
        w(f"{d1}/VERIFICATIONS.csv",
          _csv_bytes(["id", "controle", "resultat", "detail"], ver_rows),
          "Resultats du moteur de verification independant", "1D")

    # ============================ LISEZ-MOI ============================= #
    readme_rel = f"{base}/LISEZ-MOI.txt"
    n3d = len(part_files)
    lines = [
        "LIVRABLES - AI ENGINEER (dossier organise par dimension)",
        f"Projet: {project_id}",
        "",
        "3D_MODELES/   ->  A OUVRIR DANS AUTOCAD (3D)",
        f"  {label}_3D_ENSEMBLE.dxf : machine complete, unite mm, une couche",
        "    par groupe avec couleurs AutoCAD (carrosserie vert, structure gris,",
        "    roues bleu, moteur jaune, electrique rouge, cabine cyan,",
        "    faisceau magenta).",
        f"  PIECES/ : {n3d} fichiers, une piece = un fichier 3D.",
        "",
        "2D_PLANS/     ->  FEUILLES 2D (AutoCAD)",
        "  PLANS_ENSEMBLE_ET_PIECES.dxf : toutes les feuilles 2D (grille A3).",
        "  SCHEMA-01.dxf : schema electrique 12 V sur calques fonctionnels.",
        "  CABLAGE-01.dxf : plan de cablage.",
        "",
        "1D_DONNEES/   ->  TABLEAUX (Excel / import AutoCAD)",
        "  NOMENCLATURE.csv : pieces, matieres, masses (BOM).",
        "  CABLAGE_COMPLET.csv : fils, de -> vers, sections, fusibles.",
        "  CIRCUITS_ELECTRIQUES.csv : dimensionnement par circuit.",
        "  VERIFICATIONS.csv : resultats de la verification independante.",
        "  INDEX_LIVRABLES.csv : ce que contient chaque fichier.",
        "",
        "HONNETE TECHNIQUE",
        "  - Le 3D DXF est facette (3DFACE), pas du B-Rep volumique: ouvrable",
        "    et cotable dans AutoCAD, mais pas une surface NURBS.",
        "  - Geometrie parametrique de synthese: A VALIDER avant fabrication.",
        "  - Sections/fusibles: dimensionnement deterministe, hypotheses",
        "    notees (HYP.); la verification independante a tourne (voir",
        "    VERIFICATIONS.csv).",
    ]
    w(readme_rel, "\r\n".join(lines).encode("utf-8"),
      "Guide de lecture du dossier + notes d'honnetete", "DOC")

    # ---- index written LAST so it lists every file, itself included ----
    index.append(["1D", "1D_DONNEES/INDEX_LIVRABLES.csv",
                  "Index de tous les fichiers du dossier"])
    w(f"{d1}/INDEX_LIVRABLES.csv",
      _csv_bytes(["dimension", "fichier", "contenu"], list(index)),
      "Index de tous les fichiers du dossier", "1D")

    # ============================== ZIP ================================= #
    zip_rel = f"{base}/LIVRABLES_COMPLETS.zip"
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in written:
            full = Path(workspace_root) / rel
            z.writestr("deliverables/" + rel.split("/deliverables/", 1)[1],
                       full.read_bytes())
    writer(zip_rel, zbuf.getvalue())

    return {
        "folder": base,
        "layout": {"3d": "3D_MODELES/", "2d": "2D_PLANS/", "data": "1D_DONNEES/"},
        "assembly_3d_dxf": assembly_rel,
        "label": label,
        "part_3d_dxf": part_files,
        "parts_count": len(part_files),
        "combined_2d_dxf": combined_rel,
        "bom_csv": f"{d1}/NOMENCLATURE.csv",
        "wiring_csv": f"{d1}/CABLAGE_COMPLET.csv",
        "circuits_csv": f"{d1}/CIRCUITS_ELECTRIQUES.csv" if design else None,
        "verifications_csv": f"{d1}/VERIFICATIONS.csv" if verifications else None,
        "index_csv": f"{d1}/INDEX_LIVRABLES.csv",
        "readme": readme_rel,
        "zip": zip_rel,
        "zip_bytes": len(zbuf.getvalue()),
        "file_count": len(written) + 1,
        "note": ("Dossier organise par dimension: 3D_MODELES (ensemble + pieces 3D AutoCAD), "
                 "2D_PLANS (feuilles DXF), 1D_DONNEES (nomenclature, cablage, circuits, "
                 "verifications, index)."),
    }
