"""Read OpenFOAM logs, function-object series and fields of one case.

Everything here works on files only, so it is testable without OpenFOAM.

Sources, in order of preference:
- dp:  per-iteration series from the pIn/pOut function objects; if missing,
       the final field (inlet p = owner-cell p, valid for zeroGradient).
- tau: the wallShearStress field written by the function object; if missing,
       a laminar estimate -nu * u_t / d from the wall-adjacent cell.
The source actually used is recorded in result.json.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from cfd import foamio

RE_TIME = re.compile(r"^Time = (\S+)", re.M)
RE_RES = re.compile(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)")
RE_CONV = re.compile(r"SIMPLE solution converged in (\d+) iterations")
RE_EXEC = re.compile(r"ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s")
RE_CELLS = re.compile(r"^\s*cells:\s+(\d+)", re.M)


# --------------------------------------------------------------------------
# Logs
# --------------------------------------------------------------------------

def parse_solver_log(text: str) -> dict:
    """Iterations, final initial residuals, convergence flag, runtimes."""
    times = RE_TIME.findall(text)
    res = {}
    for name, val in RE_RES.findall(text):
        res[name] = float(val)  # last occurrence wins = final iteration
    execs = RE_EXEC.findall(text)
    return {
        "iterations": int(float(times[-1])) if times else 0,
        "final_residuals": res,
        "residual_converged": RE_CONV.search(text) is not None,
        "finished": re.search(r"^End\s*$", text, re.M) is not None,
        "runtime_exec_s": float(execs[-1][0]) if execs else None,
        "runtime_clock_s": float(execs[-1][1]) if execs else None,
    }


def parse_checkmesh_log(text: str) -> dict:
    m = RE_CELLS.search(text)
    return {"cells": int(m.group(1)) if m else None,
            "checkmesh_ok": "Mesh OK." in text}


# --------------------------------------------------------------------------
# Function-object series
# --------------------------------------------------------------------------

def read_dat(files: list[Path]) -> pd.DataFrame:
    """Concatenate OpenFOAM .dat series (restarts write new time folders)."""
    frames = []
    for f in sorted(files, key=lambda p: float(p.parent.name)):
        rows = [ln.split() for ln in f.read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
        if rows:
            frames.append(pd.DataFrame(np.array(rows, dtype=float)[:, :2],
                                       columns=["iter", "value"]))
    if not frames:
        return pd.DataFrame(columns=["iter", "value"])
    df = pd.concat(frames).drop_duplicates("iter", keep="last")
    return df.sort_values("iter").reset_index(drop=True)


def dp_series(case: Path) -> pd.DataFrame:
    pp = Path(case) / "postProcessing"
    p_in = read_dat(list(pp.glob("pIn/*/surfaceFieldValue.dat")))
    p_out = read_dat(list(pp.glob("pOut/*/surfaceFieldValue.dat")))
    df = p_in.merge(p_out, on="iter", suffixes=("_in", "_out"))
    df["dp"] = df["value_in"] - df["value_out"]
    return df[["iter", "dp"]]


def tail_stats(values, n: int) -> tuple[float, float]:
    """Mean and standard deviation over the last n values."""
    tail = np.asarray(values, dtype=float)[-n:]
    if len(tail) == 0:
        return float("nan"), float("nan")
    return float(tail.mean()), float(tail.std(ddof=0))


# --------------------------------------------------------------------------
# Fields
# --------------------------------------------------------------------------

def latest_time(case: Path) -> Path:
    dirs = []
    for d in Path(case).iterdir():
        try:
            t = float(d.name)
        except ValueError:
            continue
        if d.is_dir() and t > 0:
            dirs.append((t, d))
    if not dirs:
        raise FileNotFoundError("no solution time directory")
    return max(dirs)[1]


def _patch_owner_values(mesh, internal, patch):
    idx = mesh.patch_faces(patch)
    return internal[mesh.owner[list(idx)]]


def dp_from_fields(case: Path, mesh: foamio.Mesh) -> float:
    t = latest_time(case)
    p, bf = foamio.read_field(t / "p")
    vals = {}
    for patch in ("inlet", "outlet"):
        idx = mesh.patch_faces(patch)
        area = np.linalg.norm(mesh.face_areas(idx), axis=1)
        v = bf.get(patch)
        if v is None:  # zeroGradient: face value = owner cell value
            v = _patch_owner_values(mesh, p, patch)
        v = np.broadcast_to(v[:, 0], area.shape)
        vals[patch] = float((v * area).sum() / area.sum())
    return vals["inlet"] - vals["outlet"]


def wall_data(case: Path, mesh: foamio.Mesh, patch: str, nu: float) -> tuple[pd.DataFrame, str]:
    """Face data of one wall patch: x, y, p, tau_x, tau_y (kinematic).

    The 2D mesh has exactly one face per wall segment, sorted by x.
    """
    t = latest_time(case)
    idx = list(mesh.patch_faces(patch))
    fc = mesh.face_centres(idx)
    p, _ = foamio.read_field(t / "p")
    df = pd.DataFrame({"x": fc[:, 0], "y": fc[:, 1],
                       "p": _patch_owner_values(mesh, p, patch)[:, 0]})
    f_tau = t / "wallShearStress"
    if f_tau.exists():
        _, bf = foamio.read_field(f_tau)
        tau = np.broadcast_to(bf[patch], (len(idx), 3))
        source = "function_object"
    else:
        U, _ = foamio.read_field(t / "U")
        sf = mesh.face_areas(idx)
        n = sf / np.linalg.norm(sf, axis=1)[:, None]  # outward normal
        u = U[mesh.owner[idx]]
        ut = u - (u * n).sum(axis=1)[:, None] * n
        cc = mesh.cell_centres[mesh.owner[idx]]
        d = np.abs(((cc - fc) * n).sum(axis=1))
        tau = -nu * ut / d[:, None]
        source = "laminar_estimate"
    df["tau_x"], df["tau_y"] = tau[:, 0], tau[:, 1]
    df["area"] = np.linalg.norm(mesh.face_areas(idx), axis=1)
    return df.sort_values("x").reset_index(drop=True), source


def profile(case: Path, mesh: foamio.Mesh, x: float, d_bg: float) -> pd.DataFrame:
    """Velocity in the cell column closest to x (for the boundary-layer edge)."""
    t = latest_time(case)
    U, _ = foamio.read_field(t / "U")
    cc = mesh.cell_centres
    sel = np.flatnonzero(np.abs(cc[:, 0] - x) < d_bg)
    df = pd.DataFrame({"y": cc[sel, 1], "dx": np.abs(cc[sel, 0] - x),
                       "Ux": U[sel, 0], "Uy": U[sel, 1]})
    df["yk"] = df.y.round(12)
    df = df.sort_values("dx").drop_duplicates("yk").sort_values("y")
    return df[["y", "Ux", "Uy"]].reset_index(drop=True)


# --------------------------------------------------------------------------
# result.json
# --------------------------------------------------------------------------

def collect(case: Path, spec: dict, d_bg: float, slot_x: float) -> dict:
    """Assemble result.json for a solved case and export wall/profile CSVs."""
    case = Path(case)
    sol = parse_solver_log((case / "log.simpleFoam").read_text())
    msh = parse_checkmesh_log((case / "log.checkMesh").read_text())
    mesh = foamio.Mesh(case)
    s = spec["solver"]
    series = dp_series(case)
    if len(series):
        dp_mean, dp_std = tail_stats(series["dp"], s["n_avg"])
        dp_source = "function_object"
    else:
        dp_mean, dp_std = dp_from_fields(case, mesh), float("nan")
        dp_source = "final_field"
    rel = dp_std / abs(dp_mean) if dp_mean else float("inf")
    stable = bool(rel < s["q_rel_tol"])  # False if no series (rel is NaN)
    U, nu = spec["flow"]["U"], spec["flow"]["nu"]
    tau_source = None
    for patch in ("bottomWall", "topWall"):
        df, tau_source = wall_data(case, mesh, patch, nu)
        df.to_csv(case / f"wall_{patch}.csv", index=False)
    profile(case, mesh, slot_x, d_bg).to_csv(case / "profile_slot.csv", index=False)
    return {
        "case_id": spec["case_id"],
        "base_id": spec["base_id"],
        "role": spec["role"],
        "dp": dp_mean,
        "dp_sigma": dp_std,
        "dp_rel_sigma": rel,
        "dp_over_dyn": dp_mean / (0.5 * U * U),
        "dp_source": dp_source,
        "tau_source": tau_source,
        "converged": bool(sol["finished"] and (sol["residual_converged"] or stable)),
        "q_stable": stable,
        **sol,
        **msh,
    }
