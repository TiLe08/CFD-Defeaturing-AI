"""Plan and run batches of CFD cases.

    python -m pipeline.sweep --design ap2 --out data/raw --workers 6
    python -m pipeline.sweep --design ap2 --out data/raw --plan-only

Every case gets its own directory with spec.json. Finished cases are skipped,
so the command can simply be started again after an interruption. Each
OpenFOAM case runs on one core; --workers sets how many run at the same time
(rule of thumb: number of physical cores minus one).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cfd import run_case as rc  # noqa: E402
from geometry.families.f1_channel import F1Params  # noqa: E402

# Settings shared by all F1 cases. Changing them after Gate 1 invalidates
# earlier labels, so they live here and are copied into every spec.json.
F1_MESH_FINE = {"n_per_H": 10, "level_surf": 1, "level_box": 2, "box": True,
                "box_shift": 0.0, "flip_normals": True}
F1_MESH_COARSE = {"n_per_H": 10, "level_surf": 0, "level_box": 0, "box": False,
                  "box_shift": 0.0, "flip_normals": True}
F1_SOLVER = {"max_iter": 5000, "res_p": 1e-6, "res_u": 1e-7, "n_avg": 100,
             "q_rel_tol": 1e-4}


def _spec(case_id, base_id, role, params, features, flow, mesh, **extra):
    return {"case_id": case_id, "base_id": base_id, "role": role,
            "family": "F1", "template": "f1_channel",
            "params": params, "features": features, "flow": flow,
            "mesh": deepcopy(mesh), "solver": dict(F1_SOLVER), **extra}


def design_ap2() -> list[dict]:
    """Feasibility study (AP2 / Gate 1) on one F1 base configuration.

    Roles:
      without        reference without feature (fine mesh, refinement box)
      with           one feature each, same mesh settings
      null_shift     without feature, refinement box shifted by half a cell
      null_nobox     without feature, no refinement box
      base_coarse    coarse base run, source of the flow descriptors
      gci_*          without / largest groove on three mesh levels
    """
    p = F1Params()
    params = {k: getattr(p, k) for k in ("H", "L_up", "L_down", "slot_w_max", "slot_h_max")}
    H, Re, nu = p.H, 100.0, 1e-6
    flow = {"U": Re * nu / H, "nu": nu, "Re": Re}
    base = "f1_ap2_b000"
    specs = [_spec(f"{base}_without", base, "without", params, [], flow, F1_MESH_FINE)]
    for kind in ("groove", "rib"):
        for h in (0.05, 0.1, 0.2):
            f = {"kind": kind, "s": p.s_slot, "w": 0.5 * H, "h": h * H}
            specs.append(_spec(f"{base}_with_{kind}_h{h:g}", base, "with", params,
                               [f], flow, F1_MESH_FINE))
    m = dict(F1_MESH_FINE, box_shift=0.5)
    specs.append(_spec(f"{base}_null_shift", base, "null_shift", params, [], flow, m))
    m = dict(F1_MESH_FINE, box=False)
    specs.append(_spec(f"{base}_null_nobox", base, "null_nobox", params, [], flow, m))
    specs.append(_spec(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                       F1_MESH_COARSE))
    # GCI: n_per_H 7 / 10 / 14 gives r of about 1.4 (Celik et al.: r > 1.3).
    gci_feature = {"kind": "groove", "s": p.s_slot, "w": 0.5 * H, "h": 0.2 * H}
    for n in (7, 14):
        m = dict(F1_MESH_FINE, n_per_H=n)
        specs.append(_spec(f"{base}_gci_without_n{n}", base, "gci_without", params,
                           [], flow, m))
        specs.append(_spec(f"{base}_gci_with_n{n}", base, "gci_with", params,
                           [gci_feature], flow, m))
    return specs


# F1 data set (AP3/AP4). Ranges fixed after Gate 1 (05.11.2026):
# - h/H >= 0.05: smaller features span fewer than two cells of the
#   refinement box (level 2) and are not resolved by the Gate-1 mesh.
# - Re 20-500: steady laminar channel flow.
F1_RANGES = {"Re": (20.0, 500.0), "h_over_H": (0.05, 0.5), "w_over_H": (0.1, 2.0)}
F1_SEED = 2026


def design_f1_lhs(n_base: int = 30, k: int = 8, seed: int = F1_SEED) -> list[dict]:
    """F1 data set: Latin hypercube over base configurations and features.

    Per base configuration: one run without feature (label reference), one
    coarse base run (descriptor source) and k runs with one feature each,
    half grooves and half ribs. h and Re are sampled log-uniformly. The
    lowest- and highest-Re bases additionally get the three-level GCI study.
    """
    from scipy.stats import qmc

    p = F1Params()
    params = {k_: getattr(p, k_) for k_ in ("H", "L_up", "L_down", "slot_w_max", "slot_h_max")}
    H, nu = p.H, 1e-6
    (re_lo, re_hi), (h_lo, h_hi), (w_lo, w_hi) = (F1_RANGES[n] for n in ("Re", "h_over_H", "w_over_H"))
    rng = np.random.default_rng(seed)
    base_pts = qmc.LatinHypercube(d=1, seed=seed).random(n_base)[:, 0]
    re_vals = 10 ** (np.log10(re_lo) + base_pts * (np.log10(re_hi) - np.log10(re_lo)))
    gci_bases = {int(np.argmin(re_vals)), int(np.argmax(re_vals))}
    specs = []
    for b, Re in enumerate(re_vals):
        base = f"f1_b{b:03d}"
        flow = {"U": float(Re * nu / H), "nu": nu, "Re": float(Re)}
        specs.append(_spec(f"{base}_without", base, "without", params, [], flow, F1_MESH_FINE))
        specs.append(_spec(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                           F1_MESH_COARSE))
        kinds = rng.permutation(["groove", "rib"] * (k // 2) + ["groove"] * (k % 2))
        feat_pts = qmc.LatinHypercube(d=3, seed=seed + 1000 + b).random(k)
        feats = []
        for j, (u_h, u_w, u_s) in enumerate(feat_pts):
            h = 10 ** (np.log10(h_lo) + u_h * (np.log10(h_hi) - np.log10(h_lo)))
            w = w_lo + u_w * (w_hi - w_lo)
            s = p.s_slot + (u_s - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": str(kinds[j]), "s": float(s), "w": float(w * H), "h": float(h * H)}
            feats.append(f)
            specs.append(_spec(f"{base}_with_f{j}", base, "with", params, [f], flow,
                               F1_MESH_FINE))
        if b in gci_bases:
            for n in (7, 14):
                m = dict(F1_MESH_FINE, n_per_H=n)
                specs.append(_spec(f"{base}_gci_without_n{n}", base, "gci_without", params,
                                   [], flow, m))
                specs.append(_spec(f"{base}_gci_with_n{n}", base, "gci_with", params,
                                   [feats[0]], flow, m))
    return specs


# F2 (NACA profile, turbulent, k-omega SST, wall-resolved y+ ~ 1). Sizes are
# fractions of the chord. Settings are a first proposal and are fixed in the
# F2 feasibility check (design "f2_trial"), like Gate 1 for F1.
F2_MESH_FINE = {"far": 0.5, "wall": 0.004, "slot": 0.0005, "wake": 0.01,
                "bl_thickness": 0.01, "slot_bl_thickness": 0.0002, "near_dist": 1.0, "ratio": 1.2, "y_plus": 1.0,
                "dz": 0.001, "slot_side": "upper"}
F2_MESH_COARSE = dict(F2_MESH_FINE, wall=0.008, slot=0.002, wake=0.02, ratio=1.3)
F2_SOLVER = {"max_iter": 4000, "res_p": 1e-5, "res_u": 1e-6, "n_avg": 200,
             "q_rel_tol": 1e-4}


def _spec_f2(case_id, base_id, role, params, features, flow, mesh):
    return {"case_id": case_id, "base_id": base_id, "role": role,
            "family": "F2", "template": "f2_naca",
            "params": params, "features": features, "flow": flow,
            "mesh": deepcopy(mesh), "solver": dict(F2_SOLVER)}


def design_f2_trial() -> list[dict]:
    """F2 feasibility check on one base configuration (NACA 2412, 4 deg, Re 3e5).

    Same roles as AP2: reference, features, null test (slot mesh with a
    finer far field), coarse base run.
    """
    from geometry.families.f2_naca import F2Params

    p = F2Params()
    params = {k: getattr(p, k) for k in ("c", "m", "p", "t", "alpha_deg", "x_up", "x_down",
                                          "y_half", "slot_s", "slot_w_max", "slot_h_max", "n_side")}
    c, nu, Re = p.c, 1.5e-5, 3e5
    flow = {"U": Re * nu / c, "nu": nu, "Re": Re, "turb_intensity": 0.005, "nut_ratio": 1.0}
    base = "f2_trial_b000"
    specs = [_spec_f2(f"{base}_without", base, "without", params, [], flow, F2_MESH_FINE)]
    for kind in ("groove", "rib"):
        for h in (0.002, 0.005, 0.01):
            f = {"kind": kind, "s": p.slot_s * c, "w": 0.05 * c, "h": h * c, "wall": "upper"}
            specs.append(_spec_f2(f"{base}_with_{kind}_h{h:g}", base, "with", params, [f],
                                  flow, F2_MESH_FINE))
    specs.append(_spec_f2(f"{base}_null_far", base, "null_far", params, [], flow,
                          dict(F2_MESH_FINE, far=0.4)))
    specs.append(_spec_f2(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                          F2_MESH_COARSE))
    return specs


DESIGNS = {"ap2": design_ap2, "f1": design_f1_lhs, "f2_trial": design_f2_trial}


def plan(specs: list[dict], out: Path) -> pd.DataFrame:
    """Write spec.json per case (never overwrite an existing, different spec)."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in specs:
        d = out / s["case_id"]
        d.mkdir(exist_ok=True)
        f = d / "spec.json"
        if f.exists() and json.loads(f.read_text()) != s:
            raise RuntimeError(f"{f} exists with a different spec; use a new case id")
        f.write_text(json.dumps(s, indent=2))
        rows.append({"case_id": s["case_id"], "base_id": s["base_id"],
                     "role": s["role"], "n_features": len(s["features"])})
    df = pd.DataFrame(rows)
    df.to_csv(out / "design.csv", index=False)
    return df


def _run_one(case: str, bashrc: str | None, no_fo: bool) -> str:
    rc.run_case(Path(case), bashrc=bashrc, no_fo=no_fo)
    return rc.summary_line(Path(case))


def run(out: Path, case_ids: list[str], workers: int, bashrc: str | None,
        no_fo: bool = False) -> None:
    todo = [out / c for c in case_ids if rc.load_status(out / c)["state"] != "solved"]
    print(f"{len(case_ids)} cases, {len(case_ids) - len(todo)} already solved, "
          f"{len(todo)} to run on {workers} workers")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_run_one, str(c), bashrc, no_fo) for c in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            print(f"[{i}/{len(todo)}] {fut.result()}", flush=True)


def summary(out: Path, case_ids: list[str]) -> None:
    states = [rc.load_status(out / c)["state"] for c in case_ids]
    counts = pd.Series(states).value_counts().to_dict()
    print("\nSummary:", ", ".join(f"{k}: {v}" for k, v in counts.items()))
    for c, s in zip(case_ids, states):
        if s == "failed":
            print("  failed:", rc.summary_line(out / c))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", choices=sorted(DESIGNS), required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--foam-bashrc", default=os.environ.get("FOAM_BASHRC"))
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--no-function-objects", action="store_true",
                    help="debug only, see cfd.run_case")
    a = ap.parse_args(argv)
    df = plan(DESIGNS[a.design](), a.out)
    if a.plan_only:
        print(df.to_string(index=False))
        return
    run(a.out, list(df.case_id), a.workers, a.foam_bashrc, a.no_function_objects)
    summary(a.out, list(df.case_id))


if __name__ == "__main__":
    main()
