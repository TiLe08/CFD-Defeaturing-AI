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
# Feature types added on 16.11.2026 (option A: more feature types instead of
# more families), computed as separate designs f1x / f2x so that f1 / f2 stay
# unchanged. Smallest width per type: every element of the cross-section must
# span at least two cells of the refinement box (H/40), as for h >= 0.05 H.
NEW_KINDS = ("engraving", "round_groove", "chamfer_rib", "bump", "wedge")
KIND_W_MIN = {"engraving": 0.5}  # three slots of w/5: w/5 >= 0.1 H


def _kinds(rng, kinds, k):
    """k feature types, as evenly as possible, in random order."""
    return rng.permutation((list(kinds) * (k // len(kinds) + 1))[:k])


def _width(u, kind, lo, hi):
    lo = max(lo, KIND_W_MIN.get(kind, lo))
    return lo + u * (hi - lo)


def design_f1_lhs(n_base: int = 30, k: int = 8, seed: int = F1_SEED,
                  kinds=("groove", "rib"), prefix: str = "f1") -> list[dict]:
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
        base = f"{prefix}_b{b:03d}"
        flow = {"U": float(Re * nu / H), "nu": nu, "Re": float(Re)}
        specs.append(_spec(f"{base}_without", base, "without", params, [], flow, F1_MESH_FINE))
        specs.append(_spec(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                           F1_MESH_COARSE))
        kind_list = _kinds(rng, kinds, k)
        feat_pts = qmc.LatinHypercube(d=3, seed=seed + 1000 + b).random(k)
        feats = []
        for j, (u_h, u_w, u_s) in enumerate(feat_pts):
            h = 10 ** (np.log10(h_lo) + u_h * (np.log10(h_hi) - np.log10(h_lo)))
            w = _width(u_w, str(kind_list[j]), w_lo, w_hi)
            s = p.s_slot + (u_s - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": str(kind_list[j]), "s": float(s), "w": float(w * H), "h": float(h * H)}
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


# A1 (application example: NACA profile, turbulent, k-omega SST, wall-resolved y+ ~ 1). Sizes are
# fractions of the chord. Settings are a first proposal and are fixed in the
# A1 feasibility check (design "a1_trial"), like Gate 1 for F1.
A1_MESH_FINE = {"far": 0.5, "wall": 0.004, "slot": 0.0005, "wake": 0.01,
                "bl_thickness": 0.01, "slot_bl_thickness": 0.0002, "near_dist": 1.0, "ratio": 1.2, "y_plus": 1.0,
                "dz": 0.001, "slot_side": "upper"}
A1_MESH_COARSE = dict(A1_MESH_FINE, wall=0.008, slot=0.002, wake=0.02, ratio=1.3)
A1_SOLVER = {"max_iter": 4000, "res_p": 1e-5, "res_u": 1e-6, "n_avg": 200,
             "q_rel_tol": 1e-4}


def _spec_a1(case_id, base_id, role, params, features, flow, mesh):
    return {"case_id": case_id, "base_id": base_id, "role": role,
            "family": "A1", "template": "a1_naca",
            "params": params, "features": features, "flow": flow,
            "mesh": deepcopy(mesh), "solver": dict(A1_SOLVER)}


def design_a1_trial() -> list[dict]:
    """A1 feasibility check on one base configuration (NACA 2412, 4 deg, Re 3e5).

    Same roles as AP2: reference, features, null test (slot mesh with a
    finer far field), coarse base run.
    """
    from geometry.families.a1_naca import A1Params

    p = A1Params()
    params = {k: getattr(p, k) for k in ("c", "m", "p", "t", "alpha_deg", "x_up", "x_down",
                                          "y_half", "slot_s", "slot_w_max", "slot_h_max", "n_side")}
    c, nu, Re = p.c, 1.5e-5, 3e5
    flow = {"U": Re * nu / c, "nu": nu, "Re": Re, "turb_intensity": 0.005, "nut_ratio": 1.0}
    base = "a1_trial_b000"
    specs = [_spec_a1(f"{base}_without", base, "without", params, [], flow, A1_MESH_FINE)]
    for kind in ("groove", "rib"):
        for h in (0.002, 0.005, 0.01):
            f = {"kind": kind, "s": p.slot_s * c, "w": 0.05 * c, "h": h * c, "wall": "upper"}
            specs.append(_spec_a1(f"{base}_with_{kind}_h{h:g}", base, "with", params, [f],
                                  flow, A1_MESH_FINE))
    # null tests: window meshed anew (outer mesh shared), and outer mesh changed
    specs.append(_spec_a1(f"{base}_null_remesh", base, "null_remesh", params, [], flow,
                          A1_MESH_FINE))
    specs.append(_spec_a1(f"{base}_null_far", base, "null_far", params, [], flow,
                          dict(A1_MESH_FINE, far=0.4)))
    specs.append(_spec_a1(f"{base}_base_coarse", base, "base_coarse", params, [], flow,
                          A1_MESH_COARSE))
    return specs


def design_f2_trial(Re: float = 100.0) -> list[dict]:
    """F2 feasibility check: manifold with four branches, one base configuration.

    Same mesh settings and roles as AP2: reference without feature, grooves
    and ribs of three heights below the second branch, a null test with the
    refinement box shifted by half a cell, and the coarse base run.
    """
    from dataclasses import asdict

    from geometry.families.f2_manifold import F2Params

    p = F2Params()
    params = asdict(p)
    H, nu = p.H, 1e-6
    flow = {"U": Re * nu / H, "nu": nu, "Re": Re}
    base = "f2_trial_b000"

    def spec(cid, role, feats, mesh):
        return _spec(f"{base}_{cid}", base, role, params, feats, flow, mesh, family="F2")

    specs = [spec("without", "without", [], F1_MESH_FINE)]
    for kind in ("groove", "rib"):
        for h in (0.1, 0.25, 0.5):
            f = {"kind": kind, "s": p.s_slot, "w": 0.5 * H, "h": h * H}
            specs.append(spec(f"with_{kind}_h{h:g}", "with", [f], F1_MESH_FINE))
    specs.append(spec("null_shift", "null_shift", [], dict(F1_MESH_FINE, box_shift=0.5)))
    specs.append(spec("base_coarse", "base_coarse", [], F1_MESH_COARSE))
    return specs


# F2 data set: manifold geometry and Re vary per base, features as in F1.
F2_RANGES = {"Re": (20.0, 500.0), "b_over_H": (0.3, 1.0), "pitch_over_H": (1.5, 3.0),
             "h_over_H": (0.05, 0.5), "w_over_H": (0.1, 2.0)}
F2_SEED = 2027


def design_f2_lhs(n_base: int = 20, k: int = 8, seed: int = F2_SEED,
                  kinds=("groove", "rib"), prefix: str = "f2") -> list[dict]:
    """F2 data set: Latin hypercube over manifold configurations and features.

    Per base: Re, branch width b, branch pitch and the branch above the
    feature slot (first to last) vary; one run without feature, one coarse
    base run and k runs with one feature each (half grooves, half ribs).
    The lowest- and highest-Re bases also get the GCI study.
    """
    from dataclasses import asdict

    from scipy.stats import qmc

    from geometry.families.f2_manifold import F2Params

    R = F2_RANGES
    nu = 1e-6
    rng = np.random.default_rng(seed)
    pts = qmc.LatinHypercube(d=4, seed=seed).random(n_base)

    def lin(u, key):
        lo, hi = R[key]
        return lo + u * (hi - lo)

    def log(u, key):
        lo, hi = np.log10(R[key][0]), np.log10(R[key][1])
        return 10 ** (lo + u * (hi - lo))

    re_vals = log(pts[:, 0], "Re")
    gci_bases = {int(np.argmin(re_vals)), int(np.argmax(re_vals))}
    specs = []
    for bi, (u_re, u_b, u_p, u_slot) in enumerate(pts):
        n_br = F2Params().n_branch
        p = F2Params(b=float(lin(u_b, "b_over_H")), pitch=float(lin(u_p, "pitch_over_H")),
                     slot_branch=int(min(n_br - 1, u_slot * n_br)))
        params, H, Re = asdict(p), p.H, float(re_vals[bi])
        flow = {"U": Re * nu / H, "nu": nu, "Re": Re}
        base = f"{prefix}_b{bi:03d}"

        def spec(cid, role, feats, mesh):
            return _spec(f"{base}_{cid}", base, role, params, feats, flow, mesh, family="F2")

        specs += [spec("without", "without", [], F1_MESH_FINE),
                  spec("base_coarse", "base_coarse", [], F1_MESH_COARSE)]
        kind_list = _kinds(rng, kinds, k)
        feats = []
        for j, (u_h, u_w, u_s) in enumerate(qmc.LatinHypercube(d=3, seed=seed + 1000 + bi).random(k)):
            h = log(u_h, "h_over_H")
            w = _width(u_w, str(kind_list[j]), *R["w_over_H"])
            s = p.s_slot + (u_s - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": str(kind_list[j]), "s": float(s), "w": float(w * H), "h": float(h * H)}
            feats.append(f)
            specs.append(spec(f"with_f{j}", "with", [f], F1_MESH_FINE))
        if bi in gci_bases:
            for n in (7, 14):
                m = dict(F1_MESH_FINE, n_per_H=n)
                specs += [spec(f"gci_without_n{n}", "gci_without", [], m),
                          spec(f"gci_with_n{n}", "gci_with", [feats[0]], m)]
    return specs


def design_f4_trial(Re: float = 50.0) -> list[dict]:
    """F4 feasibility check: pin flow field, one base configuration (as F2 trial)."""
    from dataclasses import asdict

    from geometry.families.f4_pins import F4Params

    p = F4Params()
    params = asdict(p)
    H, nu = p.H, 1e-6
    flow = {"U": Re * nu / H, "nu": nu, "Re": Re}
    base = "f4_trial_b000"

    def spec(cid, role, feats, mesh):
        return _spec(f"{base}_{cid}", base, role, params, feats, flow, mesh, family="F4")

    specs = [spec("without", "without", [], F1_MESH_FINE)]
    for kind in ("groove", "rib", "bump"):
        for h in (0.1, 0.25, 0.5):
            f = {"kind": kind, "s": p.s_slot, "w": 0.8 * H, "h": h * H}
            specs.append(spec(f"with_{kind}_h{h:g}", "with", [f], F1_MESH_FINE))
    specs.append(spec("null_shift", "null_shift", [], dict(F1_MESH_FINE, box_shift=0.5)))
    specs.append(spec("base_coarse", "base_coarse", [], F1_MESH_COARSE))
    return specs


# F4 data set: pin flow field. Re is kept low (10-60, based on H) so that
# the flow behind the pins stays steady; pin flow fields of electrolyzers run
# in this laminar range. First sandbox run with 10-150: every base above
# Re ~ 75 with large pins had a residual stuck at 1e-2 (unsteady wake).
# All seven feature types.
F4_RANGES = {"Re": (10.0, 60.0), "a_over_H": (0.5, 1.0), "pitch_over_H": (1.5, 3.0),
             "h_over_H": (0.05, 0.5), "w_over_H": (0.1, 2.0)}
F4_SEED = 2030
ALL_KINDS = ("groove", "rib", "wedge", "bump", "round_groove", "chamfer_rib", "engraving")


def design_f4_lhs(n_base: int = 20, k: int = 10, seed: int = F4_SEED) -> list[dict]:
    """F4 data set: Latin hypercube over pin fields and features, all feature types."""
    from dataclasses import asdict

    from scipy.stats import qmc

    from geometry.families.f4_pins import F4Params

    R = F4_RANGES
    nu = 1e-6
    rng = np.random.default_rng(seed)
    pts = qmc.LatinHypercube(d=3, seed=seed).random(n_base)

    def lin(u, key):
        return R[key][0] + u * (R[key][1] - R[key][0])

    def log(u, key):
        lo, hi = np.log10(R[key][0]), np.log10(R[key][1])
        return 10 ** (lo + u * (hi - lo))

    re_vals = log(pts[:, 0], "Re")
    gci_bases = {int(np.argmin(re_vals)), int(np.argmax(re_vals))}
    specs = []
    for bi, (_, u_a, u_p) in enumerate(pts):
        p = F4Params(a=float(lin(u_a, "a_over_H")), pitch=float(lin(u_p, "pitch_over_H")))
        params, H, Re = asdict(p), p.H, float(re_vals[bi])
        flow = {"U": Re * nu / H, "nu": nu, "Re": Re}
        base = f"f4_b{bi:03d}"

        def spec(cid, role, feats, mesh):
            return _spec(f"{base}_{cid}", base, role, params, feats, flow, mesh, family="F4")

        specs += [spec("without", "without", [], F1_MESH_FINE),
                  spec("base_coarse", "base_coarse", [], F1_MESH_COARSE)]
        kind_list = _kinds(rng, ALL_KINDS, k)
        gap = p.row_y[0] - p.a / 2  # convex features must stay below the pin
        feats = []
        for j, (u_h, u_w, u_s) in enumerate(qmc.LatinHypercube(d=3, seed=seed + 1000 + bi).random(k)):
            kind = str(kind_list[j])
            h = log(u_h, "h_over_H")
            if kind in ("rib", "chamfer_rib", "bump", "wedge"):
                h = min(h, 0.8 * gap)
            w = _width(u_w, kind, *R["w_over_H"])
            s = p.s_slot + (u_s - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": kind, "s": float(s), "w": float(w * H), "h": float(h * H)}
            feats.append(f)
            specs.append(spec(f"with_f{j}", "with", [f], F1_MESH_FINE))
        if bi in gci_bases:
            for n in (7, 14):
                m = dict(F1_MESH_FINE, n_per_H=n)
                specs += [spec(f"gci_without_n{n}", "gci_without", [], m),
                          spec(f"gci_with_n{n}", "gci_with", [feats[0]], m)]
    return specs


# F3 (inlet port, turbulent): k-omega SST with wall functions, solver
# settings as A1. No temperature: scalarTransportFoam has no turbulent
# diffusivity, a turbulent heat transfer model is out of scope (stated as a
# limitation).
F3_SOLVER = {"max_iter": 4000, "res_p": 1e-5, "res_u": 1e-6, "n_avg": 200, "q_rel_tol": 1e-4}
F3_THERMAL = {"enabled": False}


def _spec_f3(case_id, base_id, role, params, features, flow, mesh):
    s = _spec(case_id, base_id, role, params, features, flow, mesh, family="F3",
              template="f3_port", thermal=dict(F3_THERMAL))
    s["solver"] = dict(F3_SOLVER)
    return s


def design_f3_trial(Re: float = 1e4) -> list[dict]:
    """F3 feasibility check: backward-facing step, feature inside the recirculation."""
    from dataclasses import asdict

    from geometry.families.f3_port import F3Params

    p = F3Params()
    params = asdict(p)
    H, nu = p.H, 1e-6
    flow = {"U": Re * nu / H, "nu": nu, "Re": Re, "turb_intensity": 0.05}
    base = "f3_trial_b000"

    def spec(cid, role, feats, mesh):
        return _spec_f3(f"{base}_{cid}", base, role, params, feats, flow, mesh)

    specs = [spec("without", "without", [], F1_MESH_FINE)]
    for kind in ("groove", "rib"):
        for h in (0.1, 0.25, 0.5):
            f = {"kind": kind, "s": p.s_slot, "w": 0.5 * H, "h": h * H}
            specs.append(spec(f"with_{kind}_h{h:g}", "with", [f], F1_MESH_FINE))
    specs.append(spec("null_shift", "null_shift", [], dict(F1_MESH_FINE, box_shift=0.5)))
    specs.append(spec("base_coarse", "base_coarse", [], F1_MESH_COARSE))
    return specs


# F3 data set: Re 5e3-3e4 (based on the feed channel height), step height
# S/H 0.5-2 (in steps of 0.1 H), slot position behind the step 1-12 S (inside
# the recirculation, near reattachment, recovery). All seven feature types.
F3_RANGES = {"Re": (5e3, 3e4), "S_over_H": (0.5, 2.0), "x_slot_over_S": (1.0, 12.0),
             "h_over_H": (0.05, 0.5), "w_over_H": (0.1, 2.0)}
F3_SEED = 2031


def design_f3_lhs(n_base: int = 20, k: int = 10, seed: int = F3_SEED) -> list[dict]:
    """F3 data set: Latin hypercube over ports and features, all feature types."""
    from dataclasses import asdict

    from scipy.stats import qmc

    from geometry.families.f3_port import F3Params

    R = F3_RANGES
    nu = 1e-6
    rng = np.random.default_rng(seed)
    pts = qmc.LatinHypercube(d=3, seed=seed).random(n_base)

    def lin(u, key):
        return R[key][0] + u * (R[key][1] - R[key][0])

    def log(u, key):
        lo, hi = np.log10(R[key][0]), np.log10(R[key][1])
        return 10 ** (lo + u * (hi - lo))

    re_vals = log(pts[:, 0], "Re")
    gci_bases = {int(np.argmin(re_vals)), int(np.argmax(re_vals))}
    specs = []
    for bi, (_, u_s, u_x) in enumerate(pts):
        S = round(float(lin(u_s, "S_over_H")), 1)
        x_lo = max(R["x_slot_over_S"][0], 1.2 / S)  # slot (+-1 H) must stay behind the step
        x_slot = x_lo + u_x * (R["x_slot_over_S"][1] - x_lo)
        p = F3Params(S=S, x_slot=float(x_slot))
        params, H, Re = asdict(p), p.H, float(re_vals[bi])
        flow = {"U": Re * nu / H, "nu": nu, "Re": Re, "turb_intensity": 0.05}
        base = f"f3_b{bi:03d}"

        def spec(cid, role, feats, mesh):
            return _spec_f3(f"{base}_{cid}", base, role, params, feats, flow, mesh)

        specs += [spec("without", "without", [], F1_MESH_FINE),
                  spec("base_coarse", "base_coarse", [], F1_MESH_COARSE)]
        kind_list = _kinds(rng, ALL_KINDS, k)
        feats = []
        for j, (u_h, u_w, u_sl) in enumerate(qmc.LatinHypercube(d=3, seed=seed + 1000 + bi).random(k)):
            kind = str(kind_list[j])
            h = log(u_h, "h_over_H")
            w = _width(u_w, kind, *R["w_over_H"])
            s = p.s_slot + (u_sl - 0.5) * (p.slot_w_max - w) * H
            f = {"kind": kind, "s": float(s), "w": float(w * H), "h": float(h * H)}
            feats.append(f)
            specs.append(spec(f"with_f{j}", "with", [f], F1_MESH_FINE))
        if bi in gci_bases:
            for n in (7, 14):
                m = dict(F1_MESH_FINE, n_per_H=n)
                specs += [spec(f"gci_without_n{n}", "gci_without", [], m),
                          spec(f"gci_with_n{n}", "gci_with", [feats[0]], m)]
    return specs


def design_f1x() -> list[dict]:
    """F1 with the new feature types: 15 bases x 10 features (2 per type)."""
    return design_f1_lhs(n_base=15, k=10, seed=2028, kinds=NEW_KINDS, prefix="f1x")


def design_f2x() -> list[dict]:
    """F2 with the new feature types: 15 bases x 10 features (2 per type)."""
    return design_f2_lhs(n_base=15, k=10, seed=2029, kinds=NEW_KINDS, prefix="f2x")


DESIGNS = {"ap2": design_ap2, "f1": design_f1_lhs, "f2": design_f2_lhs, "f2_trial": design_f2_trial,
           "a1_trial": design_a1_trial, "f1x": design_f1x, "f2x": design_f2x,
           # everything of one family in one run (used by the Windows scripts)
           "f1_alle": lambda: design_f1_lhs() + design_f1x(),
           "f2_alle": lambda: design_f2_lhs() + design_f2x(),
           "f4_trial": design_f4_trial, "f4": design_f4_lhs, "f3_trial": design_f3_trial,
           "f3": design_f3_lhs}


def plan(specs: list[dict], out: Path) -> pd.DataFrame:
    """Write spec.json per case (never overwrite an existing, different spec)."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in specs:
        d = out / s["case_id"]
        d.mkdir(exist_ok=True)
        f = d / "spec.json"
        if f.exists():
            old = json.loads(f.read_text())
            if rc.planned_spec(old) != s:
                raise RuntimeError(f"{f} exists with a different spec; use a new case id")
            # keep a spec shifted by the mesh retry (see run_case)
        else:
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
    todo = [out / c for c in case_ids if rc.needs_run(out / c)]
    print(f"{len(case_ids)} cases, {len(case_ids) - len(todo)} complete or failed, "
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
