"""F3: inlet port of an electrolyzer cell or stack (internal, turbulent), 2D.

The feed channel (height H) opens with a backward-facing step of height S
into the wider port or header chamber (height H + S). Behind the step the
flow separates and reattaches several step heights downstream. The feature
sits on the chamber floor (y = 0) at a distance from the step that varies
per base: inside the recirculation zone, near reattachment or in the
recovering boundary layer.

Coordinates: inlet at x = 0, step at x = x_step, outlet at x = L; chamber
floor y = 0, step face from y = 0 to y = S, feed channel S <= y <= S + H.
The chamber floor with the feature is "bottomWall", every other wall
(step face, feed channel walls, chamber ceiling) is "topWall", so the snappy
mesh layout and the post-processing of F1 apply. All wall positions are
multiples of H/10 and lengths whole H, so no wall coincides with a face of
the background mesh (see F4).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from geometry.families.f1_channel import Geometry2D, to_multisolid_stl  # noqa: F401
from geometry.features import Feature

REGIONS = ("inlet", "outlet", "topWall", "bottomWall")


@dataclass(frozen=True)
class F3Params:
    H: float = 0.004  # feed channel height [m]
    S: float = 1.0  # step height / H (expansion ratio (H + S) / H)
    L_up: float = 10.0  # feed channel length / H
    x_slot: float = 4.0  # feature slot centre behind the step / S
    L_rec: float = 25.0  # chamber length behind the step / S (at least; L rounded to whole H)
    slot_w_max: float = 2.0  # largest feature width / H
    slot_h_max: float = 0.5  # largest groove depth / rib height / H

    def __post_init__(self):
        if abs(self.S * 10 - round(self.S * 10)) > 1e-9:
            raise ValueError("S must be a multiple of 0.1 H (background mesh)")

    @property
    def x_step(self) -> float:
        return self.L_up * self.H

    @property
    def L(self) -> float:
        return float(np.ceil(self.L_up + self.L_rec * self.S - 1e-9)) * self.H

    @property
    def s_slot(self) -> float:
        """Centre of the feature slot on the chamber floor [m]."""
        return self.x_step + self.x_slot * self.S * self.H

    @property
    def y_top(self) -> float:
        return (1.0 + self.S) * self.H

    @property
    def loc(self) -> tuple[float, float]:
        """A point inside the fluid (feed channel) for snappyHexMesh."""
        return 0.5 * self.x_step, (self.S + 0.5) * self.H

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(L=self.L, s_slot=self.s_slot, y_top=self.y_top, x_step=self.x_step)
        return d


def _check(p: F3Params, f: Feature) -> None:
    if f.category == "convex" and f.h >= 0.5 * p.y_top:
        raise ValueError("rib would block the chamber")
    if f.s - f.w / 2 <= p.x_step or f.s + f.w / 2 >= p.L:
        raise ValueError("feature outside the chamber floor")


def floor_line(p: F3Params, features: list[Feature]):
    """The chamber floor (bottomWall): y = 0 behind the step plus the feature outlines."""
    return unary_union([LineString([(p.x_step, 0.0), (p.L, 0.0)]),
                        *[f.section().boundary for f in features]])


def make_polygon(p: F3Params, features: list[Feature]) -> Geometry2D:
    H, S = p.H, p.S * p.H
    fluid = Polygon([(0.0, S), (p.x_step, S), (p.x_step, 0.0), (p.L, 0.0),
                     (p.L, p.y_top), (0.0, p.y_top)])
    grooves, ribs = [], []
    for f in features:
        _check(p, f)
        (grooves if f.category == "concave" else ribs).append(f.section())
    if grooves:
        fluid = unary_union([fluid, *grooves])
    if ribs:
        fluid = fluid.difference(unary_union(ribs))
    if fluid.geom_type != "Polygon":
        raise ValueError("features split the fluid domain")
    fluid = Polygon(np.round(np.asarray(fluid.exterior.coords), 12))
    return Geometry2D(params=p, features=list(features), polygon=fluid)


def extrude(geom: Geometry2D, z0: float, z1: float) -> dict[str, trimesh.Trimesh]:
    """Closed surface split into inlet, outlet, topWall, bottomWall, sides."""
    p = geom.params
    mesh = trimesh.creation.extrude_polygon(geom.polygon, height=z1 - z0)
    mesh.apply_translation([0.0, 0.0, z0])
    n, c = mesh.face_normals, mesh.triangles_center
    tol = 1e-9 * max(p.L, 1.0)
    floor = floor_line(p, geom.features)
    regions = np.full(len(mesh.faces), "topWall", dtype=object)
    regions[np.abs(n[:, 2]) > 0.5] = "sides"
    side = np.abs(n[:, 2]) <= 0.5
    # the step face (x = x_step, 0 <= y <= S) touches the floor line only at its foot
    on_floor = np.array([floor.distance(Point(x, y)) < tol for x, y in c[:, :2]])
    regions[side & on_floor] = "bottomWall"
    regions[side & (np.abs(c[:, 0]) < tol) & (n[:, 0] < -0.5)] = "inlet"
    regions[side & (np.abs(c[:, 0] - p.L) < tol) & (n[:, 0] > 0.5)] = "outlet"
    out = {}
    for name in (*REGIONS, "sides"):
        idx = np.flatnonzero(regions == name)
        if len(idx):
            out[name] = mesh.submesh([idx], append=True, repair=False)
    return out


def wetted_length(geom: Geometry2D) -> float:
    """Wall length of the 2D domain (perimeter minus inlet and outlet)."""
    p = geom.params
    return geom.polygon.exterior.length - p.H - p.y_top


def build(p: F3Params, features: list[Feature], z0: float, z1: float):
    geom = make_polygon(p, features)
    regions = extrude(geom, z0, z1)
    meta = {
        "family": "F3",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_length": wetted_length(geom),
        "fluid_area": geom.polygon.area,
        "bounds": list(geom.polygon.bounds),
    }
    return geom, regions, meta
