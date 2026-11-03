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


def design_f1_lhs(n_base: int, k: int, seed: int) -> list[dict]:
    """Draft for AP4: Latin hypercube over F1 base configurations.

    Per base configuration: one run without feature, k runs with one feature,
    one coarse base run. Ranges are placeholders until Gate 1.
    """
    from scipy.stats import qmc

    p = F1Params()
    params = {k_: getattr(p, k_) for k_ in ("H", "L_up", "L_down", "slot_w_max", "slot_h_max")}
    H, nu = p.H, 1e-6
    rng = np.random.default_rng(seed)
    base_pts = qmc.LatinHypercube(d=1, seed=seed).random(n_base)
    re_vals = 10 ** qmc.scale(base_pts, [np.log10(20)], [np.log10(500)])[:, 0]
    specs = []
    for b, Re in enumerate(re_vals):
        base = f"f1_b{b:03d}"
        flow = {"U": Re * nu / H, "nu": nu, "Re": float(Re)}
        specs.append(_spec(f"{base}_without", base, "without", params, [], flow, F1_MESH_FINE))
        specs.append(_spec(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                           F1_MESH_COARSE))
        feat_pts = qmc.LatinHypercube(d=3, seed=seed + 1000 + b).random(k)
        for j, (u_h, u_w, u_s) in enumerate(feat_pts):
            h = 10 ** (np.log10(0.02) + u_h * (np.log10(p.slot_h_max) - np.log10(0.02)))
            w = 0.1 + u_w * (p.slot_w_max - 0.1)
            kind = "groove" if rng.random() < 0.5 else "rib"
            s = p.s_slot + (u_s - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": kind, "s": float(s), "w": float(w * H), "h": float(h * H)}
            specs.append(_spec(f"{base}_with_f{j}", base, "with", params, [f], flow,
                               F1_MESH_FINE))
    return specs


DESIGNS = {"ap2": design_ap2}


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
