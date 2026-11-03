"""Build, mesh, solve and post-process one F1 case.

Usage:
    python -m cfd.run_case data/raw/<case_id>            # case dir with spec.json
    python -m cfd.run_case data/raw/<case_id> --build-only

The case directory must contain spec.json (written by pipeline/sweep.py).
Each step is recorded in status.json; a rerun skips finished steps, so the
script can be interrupted at any time. Results go to result.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cfd import postprocess  # noqa: E402
from geometry.features import Feature  # noqa: E402
from geometry.families import f1_channel  # noqa: E402

TEMPLATES = ROOT / "cfd" / "templates"
STEPS = ("blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "extrudeMesh",
         "fix2D", "checkMesh", "simpleFoam", "postprocess")
# Refinement history from snappyHexMesh, invalid after extrudeMesh.
STALE_MESH_FILES = ("cellLevel", "pointLevel", "level0Edge", "surfaceIndex")


# --------------------------------------------------------------------------
# Case construction
# --------------------------------------------------------------------------

def mesh_layout(spec: dict) -> dict:
    """All placeholder values that define the mesh, derived from the spec.

    The background mesh and the refinement box depend only on the base
    configuration (slot size), never on the active feature. Runs with and
    without feature therefore share the same mesh outside the feature.
    """
    p = f1_channel.F1Params(**spec["params"])
    m = spec["mesh"]
    H = p.H
    d = H / m["n_per_H"]  # background cell size
    off = 0.37  # keeps background faces away from walls and locationInMesh
    x0 = -(2 + off) * d
    nx = math.ceil((p.L - x0 + 2 * d) / d)
    y_low = p.slot_h_max * H
    y0 = -(math.ceil(y_low / d) + 2 + off) * d
    ny = math.ceil((H - y0 + 2 * d) / d)
    z0, z1 = 0.0, d
    bw = (0.5 * p.slot_w_max + 0.5) * H
    bh = (p.slot_h_max + 0.25) * H
    shift = m.get("box_shift", 0.0) * d
    box = m.get("box", True)
    return {
        "X0": x0, "X1": x0 + nx * d, "NX": nx,
        "Y0": y0, "Y1": y0 + ny * d, "NY": ny,
        "Z0": z0, "Z1": z1,
        "LEVEL_SURF": m["level_surf"],
        "LEVEL_BOX": m["level_box"] if box else 0,
        "BOX_X0": p.s_slot - bw + shift, "BOX_X1": p.s_slot + bw + shift,
        "BOX_Y0": -bh, "BOX_Y1": bh, "BOX_Z0": z0 - d, "BOX_Z1": z1 + d,
        "LOC_X": 0.5 * p.L_up * H + 0.0123 * d,
        "LOC_Y": 0.5 * H + 0.0317 * d,
        "LOC_Z": 0.4321 * d,
        "THICKNESS": d,
        "FLIP_NORMALS": "true" if m.get("flip_normals", True) else "false",
        "_d": d, "_stl_z": (z0 - d, z1 + d), "_slot_x": p.s_slot,
    }


def placeholders(spec: dict) -> dict:
    vals = {k: v for k, v in mesh_layout(spec).items() if not k.startswith("_")}
    s = spec["solver"]
    vals.update(U=spec["flow"]["U"], NU=spec["flow"]["nu"],
                MAX_ITER=s["max_iter"], RES_P=s["res_p"], RES_U=s["res_u"])
    return vals


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def render(text: str, values: dict) -> str:
    def sub(mo):
        key = mo.group(1)
        if key not in values:
            raise KeyError(f"no value for placeholder {{{{{key}}}}}")
        return _fmt(values[key])
    return re.sub(r"\{\{(\w+)\}\}", sub, text)


def build_case(case: Path, spec: dict) -> None:
    """Copy the template, fill placeholders, write the STL and metadata."""
    tmpl = TEMPLATES / spec["template"]
    values = placeholders(spec)
    for src in tmpl.rglob("*"):
        if src.is_file():
            dst = case / src.relative_to(tmpl)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(render(src.read_text(), values))
    p = f1_channel.F1Params(**spec["params"])
    feats = [Feature.from_dict(f) for f in spec["features"]]
    z0, z1 = mesh_layout(spec)["_stl_z"]
    _, regions, meta = f1_channel.build(p, feats, z0, z1)
    tri = case / "constant" / "triSurface"
    tri.mkdir(parents=True, exist_ok=True)
    (tri / "channel.stl").write_text(f1_channel.to_multisolid_stl(regions))
    (case / "geometry.json").write_text(json.dumps(meta, indent=2))
    # empty marker file so ParaView can open the case
    (case / "case.foam").touch()


# --------------------------------------------------------------------------
# Status handling
# --------------------------------------------------------------------------

def load_status(case: Path) -> dict:
    f = case / "status.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"state": "planned", "done": [], "error": None, "times": {}}


def save_status(case: Path, st: dict) -> None:
    tmp = case / "status.json.tmp"
    tmp.write_text(json.dumps(st, indent=2))
    tmp.replace(case / "status.json")


# --------------------------------------------------------------------------
# Running OpenFOAM
# --------------------------------------------------------------------------

def foam(case: Path, app: str, args: list[str], bashrc: str | None) -> None:
    cmd = " ".join([app, *args])
    if bashrc:
        cmd = f"source {bashrc} >/dev/null 2>&1 && {cmd}"
    with open(case / f"log.{app}", "w") as log:
        r = subprocess.run(["bash", "-c", cmd], cwd=case, stdout=log,
                           stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise RuntimeError(f"{app} exited with {r.returncode} (see log.{app})")


def fix_2d(case: Path, patches=("front", "back")) -> None:
    """Make the extruded mesh a valid 2D mesh.

    Sets the side patches to empty in polyMesh/boundary and removes the
    refinement history of snappyHexMesh, which no longer matches the mesh.
    """
    poly = case / "constant" / "polyMesh"
    for name in STALE_MESH_FILES:
        (poly / name).unlink(missing_ok=True)
    f = poly / "boundary"
    txt = f.read_text()
    for name in patches:
        pat = re.compile(rf"(\n\s*{name}\s*\n\s*\{{[^}}]*?type\s+)\w+;", re.S)
        txt, n = pat.subn(r"\g<1>empty;", txt)
        if n != 1:
            raise RuntimeError(f"patch {name} not found in boundary file")
        # inGroups of the original patch type would contradict "empty"
        pat_g = re.compile(rf"(\n\s*{name}\s*\n\s*\{{[^}}]*?)inGroups[^;]*;", re.S)
        txt = pat_g.sub(r"\g<1>inGroups 1(empty);", txt)
    f.write_text(txt)


def run_step(case: Path, step: str, spec: dict, bashrc: str | None,
             no_fo: bool = False) -> None:
    if step == "blockMesh":
        foam(case, "blockMesh", [], bashrc)
    elif step == "surfaceFeatureExtract":
        foam(case, "surfaceFeatureExtract", [], bashrc)
    elif step == "snappyHexMesh":
        foam(case, "snappyHexMesh", ["-overwrite"], bashrc)
    elif step == "extrudeMesh":
        foam(case, "extrudeMesh", [], bashrc)
    elif step == "fix2D":
        fix_2d(case)
    elif step == "checkMesh":
        foam(case, "checkMesh", [], bashrc)
    elif step == "simpleFoam":
        foam(case, "simpleFoam", ["-noFunctionObjects"] if no_fo else [], bashrc)
    elif step == "postprocess":
        lay = mesh_layout(spec)
        res = postprocess.collect(case, spec, d_bg=lay["_d"], slot_x=lay["_slot_x"])
        (case / "result.json").write_text(json.dumps(res, indent=2))
    else:
        raise ValueError(step)


def run_case(case: Path, bashrc: str | None = None, build_only: bool = False,
             retry_failed: bool = False, no_fo: bool = False) -> dict:
    case = Path(case)
    spec = json.loads((case / "spec.json").read_text())
    st = load_status(case)
    if st["state"] == "failed" and not retry_failed:
        return st
    if st["state"] == "planned":
        build_case(case, spec)
        st["state"] = "built"
        save_status(case, st)
    if build_only:
        return st
    st["error"] = None
    for step in STEPS:
        if step in st["done"]:
            continue
        t0 = time.time()
        try:
            run_step(case, step, spec, bashrc, no_fo)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            st.update(state="failed", error=f"{step}: {exc}")
            save_status(case, st)
            return st
        st["done"].append(step)
        st["times"][step] = round(time.time() - t0, 2)
        st["state"] = "meshed" if step == "checkMesh" else st["state"]
        save_status(case, st)
    st["state"] = "solved"
    save_status(case, st)
    return st


def summary_line(case: Path) -> str:
    st = load_status(case)
    name = case.name
    if st["state"] != "solved":
        return f"{name:<40} {st['state']:<8} {st.get('error') or ''}"
    r = json.loads((case / "result.json").read_text())
    return (f"{name:<40} solved   dp={r['dp']:.6g} (rel. sigma {r['dp_rel_sigma']:.1e}) "
            f"cells={r['cells']} conv={r['converged']} it={r['iterations']} "
            f"t={r['runtime_clock_s']}s mesh_ok={r['checkmesh_ok']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", type=Path)
    ap.add_argument("--foam-bashrc", default=os.environ.get("FOAM_BASHRC"),
                    help="OpenFOAM bashrc to source (default: $FOAM_BASHRC)")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--no-function-objects", action="store_true",
                    help="debug only: run the solver without function objects "
                         "(dp then comes from the final field, no sigma)")
    ap.add_argument("--clean", action="store_true",
                    help="delete everything except spec.json first")
    a = ap.parse_args(argv)
    if a.clean:
        for item in a.case.iterdir():
            if item.name != "spec.json":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
    run_case(a.case, a.foam_bashrc, a.build_only, a.retry_failed,
             a.no_function_objects)
    print(summary_line(a.case))


if __name__ == "__main__":
    main()
