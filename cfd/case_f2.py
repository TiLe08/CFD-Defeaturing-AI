"""F2 (NACA profile, turbulent) case: placeholders, mesh and post-processing.

The F1 path in run_case.py stays as it is; run_case dispatches on
spec["family"] and uses these functions for F2.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from cfd import foamio, postprocess
from cfd.mesh_gmsh import first_cell_height, mesh_profile
from geometry.features import Feature
from geometry.families import f2_naca

STEPS = ("gmsh", "gmshToFoam", "fix2D", "checkMesh", "simpleFoam", "postprocess")
MSH = "profile.msh"


def params(spec: dict) -> f2_naca.F2Params:
    return f2_naca.F2Params(**spec["params"])


def mesh_sizes(spec: dict) -> dict:
    """Absolute mesh sizes from the spec (fractions of the chord)."""
    p, m, fl = params(spec), spec["mesh"], spec["flow"]
    c = p.c
    sizes = {k: m[k] * c for k in ("far", "wall", "slot", "wake", "bl_thickness",
                                   "slot_bl_thickness", "near_dist")}
    sizes["ratio"] = m["ratio"]
    sizes["y1"] = first_cell_height(fl["U"], fl["nu"], c, m["y_plus"])
    return sizes


def placeholders(spec: dict) -> dict:
    p, fl, s = params(spec), spec["flow"], spec["solver"]
    k_inf = 1.5 * (fl["turb_intensity"] * fl["U"]) ** 2
    omega_inf = k_inf / (fl["nu"] * fl["nut_ratio"])
    dz = spec["mesh"]["dz"] * p.c
    return {"U": fl["U"], "NU": fl["nu"], "C": p.c, "AREF": p.c * dz,
            "COFR_X": 0.25 * p.c, "K_INF": k_inf, "OMEGA_INF": omega_inf,
            "MAX_ITER": s["max_iter"], "RES_P": s["res_p"], "RES_U": s["res_u"]}


def build_geometry(case: Path, spec: dict) -> None:
    p = params(spec)
    feats = [Feature.from_dict(f) for f in spec["features"]]
    _, meta = f2_naca.build(p, feats)
    (case / "geometry.json").write_text(json.dumps(meta, indent=2))


def mesh(case: Path, spec: dict) -> dict:
    p = params(spec)
    feats = [Feature.from_dict(f) for f in spec["features"]]
    solid = f2_naca.profile_polygon(p, feats)
    slot = f2_naca.slot_box(p, spec["mesh"].get("slot_side", "upper"))
    sizes = mesh_sizes(spec)
    side = spec["mesh"].get("slot_side", "upper")
    zone = f2_naca.feature_zone(p, side, margin=3 * sizes["slot"])
    stats = mesh_profile(case / MSH, f2_naca.domain_box(p), solid, slot,
                         sizes, dz=spec["mesh"]["dz"] * p.c, footprint=zone)
    (case / "mesh.json").write_text(json.dumps({k: float(v) for k, v in stats.items()}))
    return stats


# --------------------------------------------------------------------------
# Post-processing
# --------------------------------------------------------------------------

def read_coefficients(case: Path) -> pd.DataFrame:
    """forceCoeffs series with named columns (layout differs by version)."""
    files = sorted((case / "postProcessing" / "forceCoeffs").glob("*/*.dat"),
                   key=lambda f: float(f.parent.name))
    frames = []
    for f in files:
        header, rows = None, []
        for ln in f.read_text().splitlines():
            if ln.startswith("#"):
                cols = ln.lstrip("#").split()
                if cols and cols[0] == "Time":
                    header = cols
            elif ln.strip():
                rows.append(ln.split())
        if header and rows:
            frames.append(pd.DataFrame(np.array(rows, dtype=float)[:, :len(header)],
                                       columns=header[:len(rows[0])]))
    if not frames:
        return pd.DataFrame()
    return (pd.concat(frames).drop_duplicates("Time", keep="last")
            .sort_values("Time").reset_index(drop=True))


def wall_profile(case: Path, spec: dict, mesh_: foamio.Mesh) -> tuple[pd.DataFrame, str]:
    """Wall data on the profile with chordwise body-frame x and side."""
    p = params(spec)
    df, src = postprocess.wall_data(case, mesh_, "profile", spec["flow"]["nu"])
    xb = f2_naca.body_frame(df[["x", "y"]].to_numpy(), p)
    upper, lower = f2_naca.naca4(p.m, p.p, p.t, p.c, p.n_side)
    yc = 0.5 * (np.interp(xb[:, 0], upper[:, 0], upper[:, 1])
                + np.interp(xb[:, 0], lower[:, 0], lower[:, 1]))
    df["x_global"], df["y_global"] = df.x, df.y
    df["x"], df["y"] = xb[:, 0], xb[:, 1]
    df["side"] = np.where(xb[:, 1] >= yc, "upper", "lower")
    df = df.sort_values(["side", "x"]).reset_index(drop=True)
    # Wall shear in the surface frame: tau_x along the local tangent towards
    # the trailing edge, tau_y normal to it. A sign change of tau_x then
    # marks separation (in the global frame it also flips at the leading edge).
    a = np.deg2rad(p.alpha_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    tau_b = df[["tau_x", "tau_y"]].to_numpy() @ rot.T
    tan = np.zeros_like(tau_b)
    for side in ("upper", "lower"):
        i = np.flatnonzero(df.side == side)
        if len(i) > 1:
            t = np.gradient(df.loc[i, ["x", "y"]].to_numpy(), axis=0)
            tan[i] = t / np.linalg.norm(t, axis=1)[:, None]
    df["tau_x"] = (tau_b * tan).sum(axis=1)
    df["tau_y"] = tau_b[:, 1] * tan[:, 0] - tau_b[:, 0] * tan[:, 1]
    return df, src


def normal_profile(case: Path, spec: dict, mesh_: foamio.Mesh) -> pd.DataFrame:
    """Tangential speed along the wall normal above the slot (clean profile)."""
    p = params(spec)
    side = spec["mesh"].get("slot_side", "upper")
    upper, lower = f2_naca.naca4(p.m, p.p, p.t, p.c, p.n_side)
    pts, sign = (upper, 1.0) if side == "upper" else (lower, -1.0)
    pt, tan, nrm = f2_naca.surface_frame(pts, p.slot_s * p.c, sign)
    a = np.deg2rad(-p.alpha_deg)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    o = np.array([0.25 * p.c, 0.0])
    pt_g, tan_g, nrm_g = (pt - o) @ rot.T + o, tan @ rot.T, nrm @ rot.T
    t = postprocess.latest_time(case)
    U, _ = foamio.read_field(t / "U")
    cc = mesh_.cell_centres[:, :2] - pt_g
    dn, dt = cc @ nrm_g, cc @ tan_g
    band = spec["mesh"]["slot"] * p.c
    sel = np.flatnonzero((np.abs(dt) < band) & (dn > 0) & (dn < 0.05 * p.c))
    ut = U[sel, :2] @ tan_g
    return (pd.DataFrame({"y": dn[sel], "Ux": ut, "Uy": U[sel, :2] @ nrm_g})
            .sort_values("y").reset_index(drop=True))


def forces_from_fields(case: Path, spec: dict, mesh_: foamio.Mesh) -> tuple[float, float]:
    """Cd, Cl from the final fields (fallback without function objects).

    Pressure: owner-cell value (zeroGradient wall). Viscous: nu * u_t / d,
    valid for a wall-resolved mesh (y+ ~ 1), where nut vanishes at the wall.
    """
    p, fl = params(spec), spec["flow"]
    t = postprocess.latest_time(case)
    idx = list(mesh_.patch_faces("profile"))
    sf = mesh_.face_areas(idx)  # points out of the fluid, into the body
    pf, _ = foamio.read_field(t / "p")
    U, _ = foamio.read_field(t / "U")
    own = mesh_.owner[idx]
    f_p = (pf[own, 0][:, None] * sf).sum(axis=0)
    n = sf / np.linalg.norm(sf, axis=1)[:, None]
    u = U[own]
    ut = u - (u * n).sum(axis=1)[:, None] * n
    fc = mesh_.face_centres(idx)
    d = np.abs(((mesh_.cell_centres[own] - fc) * n).sum(axis=1))
    f_v = (fl["nu"] * ut / d[:, None] * np.linalg.norm(sf, axis=1)[:, None]).sum(axis=0)
    F = f_p + f_v
    q_ref = 0.5 * fl["U"] ** 2 * p.c * spec["mesh"]["dz"] * p.c
    return float(F[0] / q_ref), float(F[1] / q_ref)


def collect(case: Path, spec: dict) -> dict:
    case = Path(case)
    sol = postprocess.parse_solver_log((case / "log.simpleFoam").read_text())
    msh = postprocess.parse_checkmesh_log((case / "log.checkMesh").read_text())
    mesh_ = foamio.Mesh(case)
    s = spec["solver"]
    coeffs = read_coefficients(case)
    if len(coeffs) and "Cd" in coeffs:
        cd, cd_std = postprocess.tail_stats(coeffs["Cd"], s["n_avg"])
        cl, _ = postprocess.tail_stats(coeffs["Cl"], s["n_avg"]) if "Cl" in coeffs else (np.nan, 0)
        q_source = "function_object"
    else:
        (cd, cl), cd_std = forces_from_fields(case, spec, mesh_), float("nan")
        q_source = "final_field"
    rel = cd_std / abs(cd) if cd else float("inf")
    stable = bool(rel < s["q_rel_tol"])
    wall, tau_source = wall_profile(case, spec, mesh_)
    wall.to_csv(case / "wall_profile.csv", index=False)
    normal_profile(case, spec, mesh_).to_csv(case / "profile_slot.csv", index=False)
    yplus = _yplus_max(case)
    return {
        "case_id": spec["case_id"], "base_id": spec["base_id"], "role": spec["role"],
        "Q": cd, "Q_name": "c_d", "Q_sigma": cd_std, "Q_rel_sigma": rel,
        "cl": cl, "q_source": q_source, "tau_source": tau_source,
        "yplus_max": yplus,
        "converged": bool(sol["finished"] and (sol["residual_converged"] or stable)),
        "q_stable": stable,
        **sol, **msh,
    }


def _yplus_max(case: Path) -> float | None:
    try:
        f = postprocess.latest_time(case) / "yPlus"
        if not f.exists():
            return None
        _, bf = foamio.read_field(f)
        v = bf.get("profile")
        return None if v is None else float(np.max(v))
    except (FileNotFoundError, ValueError, KeyError, AttributeError, re.error):
        return None
