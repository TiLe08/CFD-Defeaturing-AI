"""Flow descriptors of one feature from the coarse base run (D_flow part).

Inputs are the wall data of the base geometry (without the feature): face
centres x, pressure p and wall shear stress tau (kinematic, as written by
OpenFOAM for incompressible solvers), plus the velocity profile above the
feature slot. All outputs are dimensionless.

The same function is used in training (base_coarse run of a parametric
geometry) and in application (base run on the envelope of an STL), so both
see identical definitions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from geometry.features import Feature

FLOW_COLUMNS = ["h_plus", "h_over_delta", "cp_local", "dpds_nd", "force_frac",
                "dist_sep_nd", "has_sep", "Re_h", "delta_source"]

NO_SEPARATION = 100.0  # fill value for dist_sep_nd when tau_x never changes sign
UPSTREAM_LEAD = 2.0  # window starts this many feature heights upstream


def feature_window(f: Feature) -> tuple[float, float]:
    return f.s - 0.5 * f.w - UPSTREAM_LEAD * f.h, f.s + 0.5 * f.w


def _weighted_mean(v, w):
    return float(np.sum(v * w) / np.sum(w))


def boundary_layer_thickness(profile: pd.DataFrame, y_wall: float, cap: float) -> tuple[float, str]:
    """delta_99 from a wall-normal profile, capped (channel: half height).

    Returns the thickness and its source ("profile" or "cap").
    """
    prof = profile[profile.y >= y_wall].sort_values("y")
    if len(prof) < 3:
        return cap, "cap"
    u = prof.Ux.to_numpy()
    i_max = int(np.argmax(u))
    hit = np.flatnonzero(u[: i_max + 1] >= 0.99 * u[i_max])
    delta = float(prof.y.iloc[hit[0]] - y_wall)
    return (delta, "profile") if delta < cap else (cap, "cap")


def separation_distance(wall: pd.DataFrame, x0: float, x1: float, L_ref: float) -> tuple[float, int]:
    """Distance from the window [x0, x1] to the nearest sign change of tau_x."""
    w = wall.sort_values("x")
    t = w.tau_x.to_numpy()
    s = np.sign(t)
    idx = np.flatnonzero(s[:-1] * s[1:] < 0)
    if len(idx) == 0:
        return NO_SEPARATION, 0
    x = w.x.to_numpy()
    xs = x[idx] - t[idx] * (x[idx + 1] - x[idx]) / (t[idx + 1] - t[idx])
    d = np.where((xs >= x0) & (xs <= x1), 0.0, np.minimum(np.abs(xs - x0), np.abs(xs - x1)))
    return float(d.min() / L_ref), 1


def flow_descriptors(f: Feature, wall: pd.DataFrame, all_walls: list[pd.DataFrame],
                     profile: pd.DataFrame | None, nu: float, U_ref: float,
                     L_ref: float, delta_cap: float) -> dict:
    """Flow descriptors at the location of feature f.

    wall: data of the wall that carries the feature (columns x, p, tau_x,
    tau_y, area). all_walls: every wall patch, for the force fraction.
    """
    x0, x1 = feature_window(f)
    win = wall[(wall.x >= x0) & (wall.x <= x1)]
    if len(win) < 2:
        raise ValueError("feature window contains fewer than two wall faces")
    tau_mag = np.hypot(win.tau_x, win.tau_y).to_numpy()
    a = win.area.to_numpy()
    u_tau = np.sqrt(_weighted_mean(tau_mag, a))
    q = 0.5 * U_ref ** 2
    slope = np.polyfit(win.x.to_numpy(), win.p.to_numpy(), 1)[0]
    f_win = float(np.sum(tau_mag * a))
    f_all = float(sum(np.sum(np.hypot(w.tau_x, w.tau_y) * w.area) for w in all_walls))
    if profile is not None:
        delta, delta_src = boundary_layer_thickness(profile, 0.0, delta_cap)
    else:
        delta, delta_src = delta_cap, "cap"
    dist, has_sep = separation_distance(wall, x0, x1, L_ref)
    return {
        "h_plus": f.h * u_tau / nu,
        "h_over_delta": f.h / delta,
        "cp_local": _weighted_mean(win.p.to_numpy(), a) / q,
        "dpds_nd": slope * L_ref / q,
        # footprint share of the friction force; window area scaled to the
        # feature width so the lead region does not inflate it
        "force_frac": f_win / f_all * (f.w / (x1 - x0)),
        "dist_sep_nd": dist,
        "has_sep": has_sep,
        "Re_h": U_ref * f.h / nu,
        "delta_source": delta_src,
    }
