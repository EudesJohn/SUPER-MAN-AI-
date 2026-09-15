"""DXF R12 (AC1009) writer - the format AutoCAD, QCAD and LibreCAD open natively.

We generate real drawing files: layers with AutoCAD Color Index, LINE, TEXT,
CIRCLE and ARC entities. A minimal reader is included so tests can verify the
round trip (write -> parse -> entities intact). No CAD license is required to
WRITE DXF; opening in AutoCAD is the user's choice - we never claim more than
"valid R12 DXF".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# AutoCAD Color Index (subset we use)
ACI = {"white": 7, "red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5,
       "magenta": 6, "gray": 8}


def dxf_document(layers: dict[str, int], entities: list[list[str]]) -> str:
    """Assemble a full DXF R12 document from layer defs and entity tag lists."""
    out: list[str] = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC"]
    out += ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", str(len(layers))]
    for name, color in layers.items():
        out += ["0", "LAYER", "2", name, "70", "0", "62", str(color), "6", "CONTINUOUS"]
    out += ["0", "ENDTAB", "0", "ENDSEC"]
    out += ["0", "SECTION", "2", "ENTITIES"]
    for e in entities:
        out += e
    out += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Entity builders (tag lists)
# --------------------------------------------------------------------------- #
def ent_line(layer: str, x1: float, y1: float, x2: float, y2: float) -> list[str]:
    return ["0", "LINE", "8", layer,
            "10", f"{x1:.3f}", "20", f"{y1:.3f}", "30", "0.0",
            "11", f"{x2:.3f}", "21", f"{y2:.3f}", "31", "0.0"]


def ent_text(layer: str, x: float, y: float, height: float, s: str) -> list[str]:
    return ["0", "TEXT", "8", layer,
            "10", f"{x:.3f}", "20", f"{y:.3f}", "30", "0.0",
            "40", f"{height:.2f}", "1", str(s)]


def ent_circle(layer: str, x: float, y: float, r: float) -> list[str]:
    return ["0", "CIRCLE", "8", layer,
            "10", f"{x:.3f}", "20", f"{y:.3f}", "30", "0.0", "40", f"{r:.3f}"]


def ent_arc(layer: str, x: float, y: float, r: float, start_deg: float, end_deg: float) -> list[str]:
    return ["0", "ARC", "8", layer,
            "10", f"{x:.3f}", "20", f"{y:.3f}", "30", "0.0", "40", f"{r:.3f}",
            "50", f"{start_deg:.2f}", "51", f"{end_deg:.2f}"]


def save_dxf(path: str | Path, layers: dict[str, int], entities: list[list[str]]) -> dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = dxf_document(layers, entities)
    p.write_text(content, encoding="ascii", errors="replace")
    return {"path": str(p), "bytes": len(content.encode("utf-8", errors="replace"))}


# --------------------------------------------------------------------------- #
# Minimal reader (round-trip verification in tests)
# --------------------------------------------------------------------------- #
def read_dxf(path: str | Path) -> dict[str, Any]:
    tags = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    pairs = [(tags[i].strip(), tags[i + 1]) for i in range(0, len(tags) - 1, 2)]
    result: dict[str, Any] = {"layers": {}, "lines": [], "texts": [], "circles": [], "arcs": []}

    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == "0" and val == "LAYER":
            name, color = "", 7
            j = i + 1
            while j < len(pairs) and pairs[j][0] != "0":
                if pairs[j][0] == "2":
                    name = pairs[j][1]
                elif pairs[j][0] == "62":
                    color = int(pairs[j][1])
                j += 1
            if name:
                result["layers"][name] = color
            i = j
            continue
        if code == "0" and val in ("LINE", "TEXT", "CIRCLE", "ARC"):
            entity = {"type": val, "layer": ""}
            j = i + 1
            while j < len(pairs) and pairs[j][0] != "0":
                k, v = pairs[j]
                if k in ("8", "10", "20", "11", "21", "40", "50", "51", "1"):
                    if k == "8":
                        entity["layer"] = v
                    elif k == "1":
                        entity["text"] = v
                    else:
                        entity[k] = float(v)
                j += 1
            result[{"LINE": "lines", "TEXT": "texts", "CIRCLE": "circles", "ARC": "arcs"}[val]].append(entity)
            i = j
            continue
        i += 1
    return result
