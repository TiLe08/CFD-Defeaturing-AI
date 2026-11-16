"""Export the geometry models of a design as an STL package for sharing.

    python -m pipeline.export_models --design f1 --out dist/Elektrolyseur-Modelle --zip

For each base configuration and feature of the design two STL files are
written, in millimetres:

- platte/<id>.stl: section of a bipolar plate with one flow-field channel.
  The channel is open at the top (towards the porous transport layer) and
  at both ends; the feature sits on the channel floor.
- fluid/<id>.stl: the fluid volume of that channel (what the CFD sees), the
  2D channel contour extruded over the channel width.

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
from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry.families import f1_channel  # noqa: E402
from geometry.features import Feature  # noqa: E402
from pipeline import sweep  # noqa: E402

MM = 1000.0
README = """# Elektrolyseur-Modelle (Flow-Aware Defeaturing)

Geometrien, mit denen das Projekt "Flow-Aware Defeaturing" trainiert und
testet. Alle STL-Dateien in Millimetern, binär, geschlossen (wasserdicht).

## F1_Flowfield-Kanal

Ausschnitt einer Bipolarplatte mit einem Strömungskanal. Auf dem
Kanalboden sitzt höchstens ein Feature: eine Nut (Vertiefung) oder eine
Rippe (Erhebung), quer zur Strömung.

- `platte/`: das Bauteil (Plattenausschnitt). Der Kanal ist oben offen
  (dort läge die poröse Transportschicht) und an beiden Enden offen.
- `fluid/`: der Strömungsraum im Kanal, so wie ihn die CFD sieht.
- Strömung in +x, Kanalboden bei y = 0, Kanaltiefe in y, Kanalbreite in z.
- Je Basiskonfiguration gibt es ein Modell ohne Feature (`..._without`)
  und acht mit je einem Feature (`..._with_fN`).

## modelle.csv

Eine Zeile je Modell: Familie, Basis, Rolle, Feature-Typ, Lage s (Mitte,
ab Kanaleintritt), Breite w, Höhe bzw. Tiefe h (alle in mm), h/H und w/H
(H = Kanaltiefe) sowie die Reynolds-Zahl der CFD-Rechnung.

Ob ein Feature die Strömung relevant ändert (Label), steht im Datensatz
`dataset_f1.parquet` aus der CFD-Rechnung (Spalten `dQ_rel`,
`relevant_tau010`), nicht in diesem Paket.

Weitere Familien (Verteiler, Port, Steg-Flowfield, 3D-Ausschnitt) und
Realfälle folgen.
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


def f1_models(design: str = "f1"):
    """(model id, spec, features) for every unique geometry of the design."""
    for spec in sweep.DESIGNS[design]():
        if spec["family"] != "F1" or spec["role"] not in ("without", "with"):
            continue
        yield spec["case_id"], spec, [Feature.from_dict(f) for f in spec["features"]]


def export(design: str, out: Path) -> pd.DataFrame:
    rows = []
    fam = out / "F1_Flowfield-Kanal"
    for sub in ("platte", "fluid"):
        (fam / sub).mkdir(parents=True, exist_ok=True)
    for mid, spec, feats in f1_models(design):
        p = f1_channel.F1Params(**spec["params"])
        for sub, make in (("platte", f1_plate), ("fluid", f1_fluid)):
            m = make(p, feats)
            if not m.is_watertight:
                raise RuntimeError(f"{mid} {sub}: mesh is not watertight")
            m.apply_scale(MM)
            m.export(fam / sub / f"{mid}.stl")
        f = feats[0] if feats else None
        rows.append({
            "modell": mid, "familie": "F1", "bauteil": "Flowfield-Kanal (Bipolarplatte)",
            "basis": spec["base_id"], "rolle": spec["role"],
            "feature": f.kind if f else "", "s_mm": f.s * MM if f else np.nan,
            "w_mm": f.w * MM if f else np.nan, "h_mm": f.h * MM if f else np.nan,
            "h_over_H": f.h / p.H if f else np.nan, "w_over_H": f.w / p.H if f else np.nan,
            "Re": spec["flow"]["Re"], "H_mm": p.H * MM, "L_mm": p.L * MM,
            "kanalbreite_mm": f1_dims(p)["w_ch"] * MM,
            "stl_platte": f"F1_Flowfield-Kanal/platte/{mid}.stl",
            "stl_fluid": f"F1_Flowfield-Kanal/fluid/{mid}.stl",
        })
    df = pd.DataFrame(rows)
    df.to_csv(out / "modelle.csv", index=False, float_format="%.6g")
    (out / "LIESMICH.md").write_text(README, encoding="utf-8")
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", default="f1", choices=["f1", "ap2"])
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "Elektrolyseur-Modelle")
    ap.add_argument("--zip", action="store_true", help="also write <out>.zip")
    a = ap.parse_args(argv)
    if a.out.exists():
        shutil.rmtree(a.out)
    df = export(a.design, a.out)
    print(f"{len(df)} Modelle nach {a.out}")
    if a.zip:
        z = shutil.make_archive(str(a.out), "zip", a.out.parent, a.out.name)
        print(f"ZIP: {z}")


if __name__ == "__main__":
    main()
