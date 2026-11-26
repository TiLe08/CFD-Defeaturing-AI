"""Export the geometry models of a design as an STL package for sharing.

    python -m pipeline.export_models --out dist/Elektrolyseur-Modelle --zip

For each base configuration and feature of a family's design two STL files
are written, in millimetres: platte/<id>.stl, the component (a section of
the plate), and fluid/<id>.stl, the fluid volume the CFD sees. F1: plate
section with one flow-field channel, feature on the channel floor, channel
open at the top and at both ends. F2: manifold milled into the plate
surface (open at the top), inlet and branch outlets through the plate edges,
feature on the header wall opposite the branches.

modelle.csv lists every model with its parameters. The CFD runs themselves
are 2D (infinite width); the 3D models give the contour a realistic width.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import trimesh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry.families import f1_channel, f2_manifold, f3_port, f4_pins  # noqa: E402
from geometry.features import Feature  # noqa: E402
from pipeline import sweep  # noqa: E402

MM = 1000.0
README = """# Elektrolyseur-Modelle (Flow-Aware Defeaturing)

Geometrien, mit denen das Projekt "Flow-Aware Defeaturing" trainiert und
testet. Alle STL-Dateien in Millimetern, binär, geschlossen (wasserdicht).

## F1_Flowfield-Kanal

Ausschnitt einer Bipolarplatte mit einem Strömungskanal. Auf dem
Kanalboden sitzt höchstens ein Feature quer zur Strömung (Typen siehe
unten).

- `platte/`: das Bauteil (Plattenausschnitt). Der Kanal ist oben offen
  (dort läge die poröse Transportschicht) und an beiden Enden offen.
- `fluid/`: der Strömungsraum im Kanal, so wie ihn die CFD sieht.
- Strömung in +x, Kanalboden bei y = 0, Kanaltiefe in y, Kanalbreite in z.
- Je Basiskonfiguration gibt es ein Modell ohne Feature (`..._without`)
  und acht bzw. zehn mit je einem Feature (`..._with_fN`). Basen `f1_...`
  haben Nuten und Rippen, Basen `f1x_...` die übrigen Feature-Typen.

## F2_Verteiler

Verteiler (Manifold) einer Zelle, in die Plattenoberfläche gefräst und
oben offen. Ein Sammelkanal (Breite H) läuft vom Einlass zu einem
geschlossenen Ende; vier Abzweige führen zu den Flowfield-Kanälen. Das
Feature sitzt an der Wand gegenüber den Abzweigen, unter einem der
Abzweige (Spalte `abzweig_ueber_feature`).

- `platte/`: Plattenausschnitt mit eingefrästem Verteiler; Einlass und
  Abzweige gehen durch den Plattenrand.
- `fluid/`: der Strömungsraum.
- Ebene x-y ist die Plattenebene, Tiefe in z.

## F3_Einlass-Port

Zulaufkanal (Höhe H), der mit einer Stufe (Höhe S) in die breitere Port-
bzw. Sammelkammer übergeht. Hinter der Stufe löst die Strömung ab und legt
einige Stufenhöhen weiter wieder an. Turbulent gerechnet (k-ω SST). Das
Feature sitzt am Kammerboden hinter der Stufe, Abstand in Spalte
`x_slot_over_S` (in Stufenhöhen).

- `platte/`: das Bauteil um den Port, nach oben und unten geschlossen, am Ein- und Auslass offen.
- `fluid/`: der Strömungsraum.
- Strömung in +x, Kammerboden bei y = 0, Breite in z.

## F4_Pin-Flowfield

Flowfield aus quadratischen Pins (Stege mit gerundeten Ecken, r = 0,1 H),
zwei versetzte Reihen zwischen zwei Seitenwänden, in die Plattenoberfläche
gefräst und oben offen. Das Feature sitzt an der Seitenwand y = 0 unter
einem Pin der ersten Reihe, wo die Strömung zwischen Pin und Wand
eingeengt wird.

- `platte/`: Plattenausschnitt mit Pinfeld; Ein- und Auslass durch den Plattenrand.
- `fluid/`: der Strömungsraum.
- Ebene x-y ist die Plattenebene, Tiefe in z.

## Feature-Typen (Spalte `feature`)

| Typ | Bedeutung | Querschnitt |
| --- | --- | --- |
| groove | Nut | Rechteck in die Wand |
| rib | Rippe, Steg | Rechteck auf der Wand |
| engraving | Gravur, Beschriftung | drei schmale Schlitze (je w/5) |
| round_groove | Rundnut, Ausrundung | halbe Ellipse in die Wand |
| chamfer_rib | Rippe mit Fase | Trapez, Fasen 45° |
| bump | Noppe, Wulst | halbe Ellipse auf der Wand |
| wedge | Stufe mit Rampe | steile Stufe gegen die Strömung, Rampe zurück |

F2-Basen `f2x_...` tragen ebenfalls die neuen Typen.

## modelle.csv

Eine Zeile je Modell: Familie, Basis, Rolle, Feature-Typ, Lage s (Mitte,
ab Kanaleintritt), Breite w, Höhe bzw. Tiefe h (alle in mm), h/H und w/H
(H = Kanaltiefe) sowie die Reynolds-Zahl der CFD-Rechnung.

Ob ein Feature die Strömung relevant ändert (Label), steht in den
Datensätzen `dataset_*.parquet` aus der CFD-Rechnung, nicht in diesem
Paket: Druckverlust (`dQ_rel`, `relevant_tau010`) und Wärmeübergang
(`dNu_rel`, `relevant_th_tau010`).

Weitere Familien (3D-Ausschnitt) und Realfälle
folgen.
"""


def f1_dims(p: f1_channel.F1Params) -> dict:
    """Plate dimensions for the F1 export: all in multiples of H."""
    return {"w_ch": p.H, "land": p.H, "t": p.H}


def f1_fluid(p: f1_channel.F1Params, feats: list[Feature]) -> trimesh.Trimesh:
    geom = f1_channel.make_polygon(p, feats)
    return trimesh.creation.extrude_polygon(geom.polygon, height=f1_dims(p)["w_ch"])


def f1_plate(p: f1_channel.F1Params, feats: list[Feature]) -> trimesh.Trimesh:
    d = f1_dims(p)
    e = 0.05 * p.H  # the cut reaches past the plate faces (no coplanar faces)
    fluid = f1_channel.make_polygon(p, feats).polygon
    cut2d = unary_union([fluid, box(-e, 0.0, 0.0, p.H + e), box(p.L, 0.0, p.L + e, p.H + e),
                         box(0.0, p.H - 1e-9 * p.H, p.L, p.H + e)])
    # the top box overlaps the channel top only by a sliver, so ribs stay
    cut = trimesh.creation.extrude_polygon(cut2d, height=d["w_ch"])
    cut.apply_translation([0.0, 0.0, d["land"]])
    plate = trimesh.creation.box(bounds=[[0.0, -d["t"], 0.0],
                                         [p.L, p.H, 2 * d["land"] + d["w_ch"]]])
    return trimesh.boolean.difference([plate, cut], engine="manifold")


def f2_dims(p: f2_manifold.F2Params) -> dict:
    """Manifold milled into the plate surface: depth, wall margin, floor."""
    return {"depth": p.H, "margin": p.H, "t": p.H}


def f2_fluid(p: f2_manifold.F2Params, feats: list[Feature]) -> trimesh.Trimesh:
    geom = f2_manifold.make_polygon(p, feats)
    return trimesh.creation.extrude_polygon(geom.polygon, height=f2_dims(p)["depth"])


def f2_plate(p: f2_manifold.F2Params, feats: list[Feature]) -> trimesh.Trimesh:
    d = f2_dims(p)
    m, e, H = d["margin"], 0.05 * p.H, p.H
    poly = f2_manifold.make_polygon(p, feats).polygon
    # extensions overlap the fluid by a full H, so the union has no slivers
    ext = [box(-m - e, 0.0, H, H)]  # inlet through the plate edge
    for i in range(p.n_branch):  # branches through the opposite edge
        x0 = p.branch_x0(i)
        ext.append(box(x0, p.y_top - H, x0 + p.b * H, p.y_top + m + e))
    u = unary_union([poly, *ext])
    u = Polygon(np.round(np.asarray(u.exterior.coords), 12)).simplify(0)  # drop float twins
    cut = trimesh.creation.extrude_polygon(u, height=d["depth"] + e)
    plate = trimesh.creation.box(bounds=[[-m, -m, -d["t"]], [p.L + m, p.y_top + m, d["depth"]]])
    return trimesh.boolean.difference([plate, cut], engine="manifold")


def f3_dims(p: f3_port.F3Params) -> dict:
    """Port section in the plate: as F1 (lands of width H on both sides, floor H)."""
    return {"w_ch": p.H, "land": p.H, "t": p.H}


def f3_fluid(p: f3_port.F3Params, feats: list[Feature]) -> trimesh.Trimesh:
    geom = f3_port.make_polygon(p, feats)
    return trimesh.creation.extrude_polygon(geom.polygon, height=f3_dims(p)["w_ch"])


def f3_plate(p: f3_port.F3Params, feats: list[Feature]) -> trimesh.Trimesh:
    """Solid around the port: closed in y (floor and ceiling), open at inlet and outlet."""
    d = f3_dims(p)
    e = 0.05 * p.H
    fluid = f3_port.make_polygon(p, feats).polygon
    S = p.S * p.H
    cut2d = unary_union([fluid, box(-e, S, p.H, p.y_top), box(p.L - p.H, 0.0, p.L + e, p.y_top)])
    cut2d = Polygon(np.round(np.asarray(cut2d.exterior.coords), 12)).simplify(0)
    cut = trimesh.creation.extrude_polygon(cut2d, height=d["w_ch"])
    cut.apply_translation([0.0, 0.0, d["land"]])
    plate = trimesh.creation.box(bounds=[[0.0, -d["t"], 0.0],
                                         [p.L, p.y_top + d["t"], 2 * d["land"] + d["w_ch"]]])
    return trimesh.boolean.difference([plate, cut], engine="manifold")


def f4_dims(p: f4_pins.F4Params) -> dict:
    """Pin field milled into the plate surface: depth, wall margin, floor."""
    return {"depth": p.H, "margin": p.H, "t": p.H}


def f4_fluid(p: f4_pins.F4Params, feats: list[Feature]) -> trimesh.Trimesh:
    geom = f4_pins.make_polygon(p, feats)
    return trimesh.creation.extrude_polygon(geom.polygon, height=f4_dims(p)["depth"])


def f4_plate(p: f4_pins.F4Params, feats: list[Feature]) -> trimesh.Trimesh:
    """Plate section with the pin field; inlet and outlet through the plate edges."""
    d = f4_dims(p)
    m, e, H = d["margin"], 0.05 * p.H, p.H
    poly = f4_pins.make_polygon(p, feats).polygon
    # extensions overlap the fluid by a full H (no slivers), never reach a pin
    ext = [box(-m - e, 0.0, H, p.y_top), box(p.L - H, 0.0, p.L + m + e, p.y_top)]
    u = unary_union([poly, *ext])
    rnd = lambda ring: np.round(np.asarray(ring.coords), 12)  # noqa: E731
    u = Polygon(rnd(u.exterior), [rnd(r) for r in u.interiors]).simplify(0)
    cut = trimesh.creation.extrude_polygon(u, height=d["depth"] + e)
    plate = trimesh.creation.box(bounds=[[-m, -m, -d["t"]], [p.L + m, p.y_top + m, d["depth"]]])
    return trimesh.boolean.difference([plate, cut], engine="manifold")


FAMILIES = {
    "F1": {"designs": ("f1", "f1x"), "folder": "F1_Flowfield-Kanal", "bauteil": "Flowfield-Kanal (Bipolarplatte)",
           "params": f1_channel.F1Params, "platte": f1_plate, "fluid": f1_fluid,
           "width_mm": lambda p: f1_dims(p)["w_ch"] * MM},
    "F2": {"designs": ("f2", "f2x"), "folder": "F2_Verteiler", "bauteil": "Verteiler (Manifold) mit Kanalabgängen",
           "params": f2_manifold.F2Params, "platte": f2_plate, "fluid": f2_fluid,
           "width_mm": lambda p: f2_dims(p)["depth"] * MM},
    "F3": {"designs": ("f3",), "folder": "F3_Einlass-Port", "bauteil": "Einlass-Port mit Stufe (Zelle/Stack)",
           "params": f3_port.F3Params, "platte": f3_plate, "fluid": f3_fluid,
           "width_mm": lambda p: f3_dims(p)["w_ch"] * MM},
    "F4": {"designs": ("f4",), "folder": "F4_Pin-Flowfield", "bauteil": "Pin-Flowfield (Bipolarplatte)",
           "params": f4_pins.F4Params, "platte": f4_plate, "fluid": f4_fluid,
           "width_mm": lambda p: f4_dims(p)["depth"] * MM},
}


def models(design: str):
    """(model id, spec, features) for every unique geometry of a design."""
    for spec in sweep.DESIGNS[design]():
        if spec["role"] not in ("without", "with"):
            continue
        yield spec["case_id"], spec, [Feature.from_dict(f) for f in spec["features"]]


def export(families: list[str], out: Path, designs: dict | None = None) -> pd.DataFrame:
    """Write the STL files of the given families, modelle.csv and LIESMICH.md."""
    rows = []
    for fam_id in families:
        fam = FAMILIES[fam_id]
        folder = out / fam["folder"]
        for sub in ("platte", "fluid"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        todo = (designs or {}).get(fam_id, fam["designs"])
        for mid, spec, feats in (m for d in ([todo] if isinstance(todo, str) else todo)
                                 for m in models(d)):
            p = fam["params"](**spec["params"])
            for sub in ("platte", "fluid"):
                m = fam[sub](p, feats)
                if not m.is_watertight:
                    raise RuntimeError(f"{mid} {sub}: mesh is not watertight")
                m.apply_scale(MM)
                m.export(folder / sub / f"{mid}.stl")
            f = feats[0] if feats else None
            row = {
                "modell": mid, "familie": fam_id, "bauteil": fam["bauteil"],
                "basis": spec["base_id"], "rolle": spec["role"],
                "feature": f.kind if f else "", "s_mm": f.s * MM if f else np.nan,
                "w_mm": f.w * MM if f else np.nan, "h_mm": f.h * MM if f else np.nan,
                "h_over_H": f.h / p.H if f else np.nan, "w_over_H": f.w / p.H if f else np.nan,
                "Re": spec["flow"]["Re"], "H_mm": p.H * MM, "L_mm": p.L * MM,
                "tiefe_bzw_breite_mm": fam["width_mm"](p),
            }
            if fam_id == "F3":
                row.update(S_over_H=p.S, x_slot_over_S=p.x_slot)
            if fam_id == "F4":
                row.update(pin_a_over_H=p.a, pitch_over_H=p.pitch, n_pins=len(p.pins()))
            if fam_id == "F2":
                row.update(n_abzweige=p.n_branch, b_over_H=p.b, pitch_over_H=p.pitch,
                           abzweig_ueber_feature=p.slot_branch + 1)
            row.update(stl_platte=f"{fam['folder']}/platte/{mid}.stl",
                       stl_fluid=f"{fam['folder']}/fluid/{mid}.stl")
            rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(out / "modelle.csv", index=False, float_format="%.6g")
    (out / "LIESMICH.md").write_text(README, encoding="utf-8")
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--families", nargs="+", default=sorted(FAMILIES), choices=sorted(FAMILIES))
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "Elektrolyseur-Modelle")
    ap.add_argument("--zip", action="store_true", help="also write <out>.zip")
    a = ap.parse_args(argv)
    if a.out.exists():
        shutil.rmtree(a.out)
    df = export(a.families, a.out)
    print(f"{len(df)} Modelle nach {a.out}")
    if a.zip:
        z = shutil.make_archive(str(a.out), "zip", a.out.parent, a.out.name)
        print(f"ZIP: {z}")


if __name__ == "__main__":
    main()
