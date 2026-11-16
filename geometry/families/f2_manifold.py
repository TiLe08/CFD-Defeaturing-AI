"""F2: manifold of an electrolyzer cell (internal, laminar), 2D.

A header (Sammelkanal) of height H runs along x from the inlet at x = 0 to a
closed end. Branch channels of width b leave its top wall and run up to the
outlets at y = y_top; they stand for the flow-field channels fed by the
manifold. The feature sits on the header floor (y = 0) below one branch,
where the flow turns into the branches.

The geometry follows F1 (same Feature, same region names): the floor with
the feature is "bottomWall", every other wall is "topWall". The F1 case
template, mesh layout and post-processing therefore apply unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from geometry.families.f1_channel import Geometry2D, to_multisolid_stl  # noqa: F401
from geometry.features import Feature

REGIONS = ("inlet", "outlet", "topWall", "bottomWall")


@dataclass(frozen=True)
class F2Params:
    H: float = 0.003  # header height [m]
    L_up: float = 8.0  # inlet to first branch, in multiples of H
    n_branch: int = 4  # number of branch channels
    b: float = 0.5  # branch width / H
    pitch: float = 2.0  # branch spacing / H (left edge to left edge)
    L_end: float = 1.0  # last branch to closed end / H
    L_branch: float = 6.0  # branch length (header top to outlet) / H
    slot_branch: int = 1  # the feature slot lies below this branch (0 = first)
    slot_w_max: float = 2.0  # largest feature width / H
    slot_h_max: float = 0.5  # largest groove depth / rib height / H

    def branch_x0(self, i: int) -> float:
        return (self.L_up + i * self.pitch) * self.H

    @property
    def L(self) -> float:
        """Header length [m]."""
        return (self.L_up + (self.n_branch - 1) * self.pitch + self.b + self.L_end) * self.H

    @property
    def s_slot(self) -> float:
        """Centre of the feature slot on the floor: below branch slot_branch [m]."""
        return self.branch_x0(self.slot_branch) + 0.5 * self.b * self.H

    @property
    def y_top(self) -> float:
        return (1.0 + self.L_branch) * self.H

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(L=self.L, s_slot=self.s_slot, y_top=self.y_top)
        return d


def _check(p: F2Params, f: Feature) -> None:
    if f.category == "convex" and f.h >= p.H:
        raise ValueError("rib would block the header")
    if f.s - f.w / 2 <= 0 or f.s + f.w / 2 >= p.L:
        raise ValueError("feature outside the header")


def floor_line(p: F2Params, features: list[Feature]):
    """The floor (bottomWall): the line y = 0 plus the outlines of the features."""
    return unary_union([LineString([(0.0, 0.0), (p.L, 0.0)]),
                        *[f.section().boundary for f in features]])


def make_polygon(p: F2Params, features: list[Feature]) -> Geometry2D:
    H = p.H
    parts = [box(0.0, 0.0, p.L, H)]
    for i in range(p.n_branch):
        x0 = p.branch_x0(i)
        parts.append(box(x0, 0.5 * H, x0 + p.b * H, p.y_top))
    fluid = unary_union(parts)
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
    from shapely.geometry import Polygon
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
    on_floor = np.array([floor.distance(Point(x, y)) < tol for x, y in c[:, :2]])
    regions[side & on_floor] = "bottomWall"
    regions[side & (np.abs(c[:, 0]) < tol) & (n[:, 0] < -0.5)] = "inlet"
    regions[side & (np.abs(c[:, 1] - p.y_top) < tol) & (n[:, 1] > 0.5)] = "outlet"
    out = {}
    for name in (*REGIONS, "sides"):
        idx = np.flatnonzero(regions == name)
        if len(idx):
            out[name] = mesh.submesh([idx], append=True, repair=False)
    return out


def wetted_length(geom: Geometry2D) -> float:
    """Wall length of the 2D domain (perimeter minus inlet and outlets)."""
    p = geom.params
    return geom.polygon.exterior.length - p.H - p.n_branch * p.b * p.H


def build(p: F2Params, features: list[Feature], z0: float, z1: float):
    geom = make_polygon(p, features)
    regions = extrude(geom, z0, z1)
    meta = {
        "family": "F2",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_length": wetted_length(geom),
        "fluid_area": geom.polygon.area,
        "bounds": list(geom.polygon.bounds),
    }
    return geom, regions, meta
