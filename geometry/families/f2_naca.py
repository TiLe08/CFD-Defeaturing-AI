"""F2: NACA 4-digit profile with surface features (external, turbulent).

The profile is built in its body frame (leading edge at the origin, chord
along +x), features are added there, and the result is rotated by the angle
of attack about the quarter chord. The flow always comes from -x.

A feature sits on the upper or lower side ("wall" = "upper" / "lower") at
the chordwise body-frame position s. Its rectangle is aligned with the local
surface tangent: a groove is cut into the profile, a rib is added to it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from geometry.features import Feature


@dataclass(frozen=True)
class F2Params:
    c: float = 0.1  # chord [m]
    m: float = 0.02  # max camber / c
    p: float = 0.4  # position of max camber / c
    t: float = 0.12  # thickness / c
    alpha_deg: float = 4.0  # angle of attack
    x_up: float = 5.0  # domain extent upstream of the leading edge [c]
    x_down: float = 10.0  # downstream of the leading edge [c]
    y_half: float = 5.0  # half height of the domain [c]
    slot_s: float = 0.5  # centre of the feature slot (x/c, body frame)
    slot_w_max: float = 0.1  # largest feature width [c]
    slot_h_max: float = 0.01  # largest feature height/depth [c]
    n_side: int = 200  # points per side of the clean profile

    @property
    def name(self) -> str:
        return f"NACA{round(self.m * 100)}{round(self.p * 10)}{round(self.t * 100):02d}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["name"] = self.name
        return d


def naca4(m: float, p: float, t: float, c: float, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Upper and lower surface (each n points, LE to TE), closed trailing edge."""
    beta = np.linspace(0.0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta))  # cosine spacing, x/c
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2
                  + 0.2843 * x ** 3 - 0.1036 * x ** 4)  # -0.1036: closed TE
    if m > 0 and 0 < p < 1:
        yc = np.where(x < p, m / p ** 2 * (2 * p * x - x ** 2),
                      m / (1 - p) ** 2 * (1 - 2 * p + 2 * p * x - x ** 2))
        dyc = np.where(x < p, 2 * m / p ** 2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    else:
        yc = np.zeros_like(x)
        dyc = np.zeros_like(x)
    th = np.arctan(dyc)
    upper = np.column_stack([x - yt * np.sin(th), yc + yt * np.cos(th)]) * c
    lower = np.column_stack([x + yt * np.sin(th), yc - yt * np.cos(th)]) * c
    upper[-1] = lower[-1] = [c, 0.0]
    return upper, lower


def surface_frame(side_pts: np.ndarray, x: float, outward_sign: float):
    """Point, unit tangent (towards TE) and outward normal at chordwise x."""
    xs = side_pts[:, 0]
    i = int(np.clip(np.searchsorted(xs, x), 1, len(xs) - 1))
    a, b = side_pts[i - 1], side_pts[i]
    f = (x - a[0]) / (b[0] - a[0])
    pt = a + f * (b - a)
    tan = (b - a) / np.linalg.norm(b - a)
    nrm = outward_sign * np.array([-tan[1], tan[0]])
    return pt, tan, nrm


def feature_rect(pt, tan, nrm, f: Feature) -> Polygon:
    """Rectangle in the local surface frame; overlaps the surface on purpose."""
    lo, hi = (-f.h, 0.5 * f.h) if f.kind == "groove" else (-0.5 * f.h, f.h)
    corners = [pt + u * tan + v * nrm
               for u, v in ((-f.w / 2, lo), (f.w / 2, lo), (f.w / 2, hi), (-f.w / 2, hi))]
    return Polygon(corners)


def profile_polygon(p: F2Params, features: list[Feature]) -> Polygon:
    """Solid profile with features, rotated by the angle of attack."""
    upper, lower = naca4(p.m, p.p, p.t, p.c, p.n_side)
    solid = Polygon(np.vstack([upper, lower[::-1][1:-1]]))
    for f in features:
        if f.wall not in ("upper", "lower"):
            raise ValueError("F2 features need wall='upper' or 'lower'")
        if not (0.05 * p.c < f.s - f.w / 2 and f.s + f.w / 2 < 0.95 * p.c):
            raise ValueError("feature too close to leading or trailing edge")
        pts, sign = (upper, 1.0) if f.wall == "upper" else (lower, -1.0)
        rect = feature_rect(*surface_frame(pts, f.s, sign), f)
        solid = solid.difference(rect) if f.kind == "groove" else unary_union([solid, rect])
    if solid.geom_type != "Polygon":
        raise ValueError("features split the profile")
    solid = affinity.rotate(solid, -p.alpha_deg, origin=(0.25 * p.c, 0.0))
    return Polygon(np.round(np.asarray(solid.exterior.coords), 12)).buffer(0)


def domain_box(p: F2Params) -> Polygon:
    return box(-p.x_up * p.c, -p.y_half * p.c, p.x_down * p.c, p.y_half * p.c)


def slot_box(p: F2Params, side: str = "upper") -> Polygon:
    """Region around the feature slot (rotated with the profile).

    It depends only on the base configuration, so runs with and without a
    feature get the same local mesh refinement.
    """
    upper, lower = naca4(p.m, p.p, p.t, p.c, p.n_side)
    pts, sign = (upper, 1.0) if side == "upper" else (lower, -1.0)
    pt, tan, nrm = surface_frame(pts, p.slot_s * p.c, sign)
    half = 0.5 * p.slot_w_max * p.c + 2 * p.slot_h_max * p.c
    a, b = -2 * p.slot_h_max * p.c, 4 * p.slot_h_max * p.c
    poly = Polygon([pt + u * tan + v * nrm for u, v in
                    ((-half, a), (half, a), (half, b), (-half, b))])
    return affinity.rotate(poly, -p.alpha_deg, origin=(0.25 * p.c, 0.0))


def body_frame(xy: np.ndarray, p: F2Params) -> np.ndarray:
    """Undo the angle-of-attack rotation (for wall data in chordwise x)."""
    a = np.deg2rad(p.alpha_deg)
    o = np.array([0.25 * p.c, 0.0])
    r = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return (xy - o) @ r.T + o


def wetted_length(p: F2Params, features: list[Feature]) -> float:
    return profile_polygon(p, features).exterior.length


def build(p: F2Params, features: list[Feature]):
    solid = profile_polygon(p, features)
    meta = {
        "family": "F2",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_length": solid.exterior.length,
        "profile_area": solid.area,
        "bounds": list(solid.bounds),
    }
    return solid, meta
