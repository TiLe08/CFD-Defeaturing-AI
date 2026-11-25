"""F4: pin flow field of a bipolar plate (internal, laminar), 2D in the plate plane.

Seen from above, the flow passes a field of square pins (lands that carry
the porous transport layer) between two side walls. Two staggered rows of
pins of size a sit between the side walls y = 0 and y = W. The feature sits
on the side wall y = 0 below one pin of the first row, where the flow is
squeezed between pin and wall.

As in F1/F2 the feature wall is "bottomWall", all other walls (the opposite
side wall and every pin) are "topWall", so case template, mesh layout and
post-processing apply unchanged. Pins are holes of the fluid polygon.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from geometry.families.f1_channel import Geometry2D, to_multisolid_stl  # noqa: F401
from geometry.features import Feature

REGIONS = ("inlet", "outlet", "topWall", "bottomWall")


@dataclass(frozen=True)
class F4Params:
    H: float = 0.002  # reference length [m]: channel width = W * H
    W: float = 4.0  # distance of the side walls / H
    a: float = 0.8  # pin size / H
    pitch: float = 2.0  # pin spacing along the flow / H
    n_cols: int = 6  # pins per row
    L_up: float = 6.0  # inlet to the first pin / H
    L_down: float = 8.0  # last pin to the outlet / H (at least; L is rounded to whole H)
    row_y: tuple = (1.25, 2.75)  # pin centre lines / H (second row shifted by pitch / 2)
    slot_col: int = 2  # the feature slot lies below this pin of the first row
    slot_w_max: float = 2.0  # largest feature width / H
    slot_h_max: float = 0.5  # largest groove depth / rib height / H
    r_corner: float = 0.1  # corner radius of the pins / H (milled pins; sharp corners gave skew cells)

    def pin_x0(self, row: int, i: int) -> float:
        """Left edge of pin i in a row [m]."""
        return (self.L_up + (i + 0.5 * row) * self.pitch) * self.H

    @property
    def L(self) -> float:
        last = self.L_up + (self.n_cols - 1 + 0.5) * self.pitch + self.a
        # rounded up to whole H: the outlet then sits at the same place
        # relative to the background cells as in F1 (an arbitrary L gave
        # skew faces at the outlet corner)
        return float(np.ceil(last + self.L_down - 1e-9)) * self.H

    @property
    def s_slot(self) -> float:
        """Centre of the feature slot on the wall y = 0 [m]."""
        return self.pin_x0(0, self.slot_col) + 0.5 * self.a * self.H

    @property
    def y_top(self) -> float:
        return self.W * self.H

    def pins(self) -> list:
        H, a = self.H, self.a
        out = []
        for row, yc in enumerate(self.row_y):
            for i in range(self.n_cols):
                x0, r = self.pin_x0(row, i), self.r_corner * H
                core = box(x0 + r, (yc - a / 2) * H + r, x0 + a * H - r, (yc + a / 2) * H - r)
                out.append(core.buffer(r, quad_segs=4))
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(L=self.L, s_slot=self.s_slot, y_top=self.y_top)
        return d


def _check(p: F4Params, f: Feature) -> None:
    gap = (p.row_y[0] - p.a / 2) * p.H  # wall to the first row
    if f.category == "convex" and f.h >= 0.9 * gap:
        raise ValueError("rib would close the gap below the pin")
    if f.s - f.w / 2 <= 0 or f.s + f.w / 2 >= p.L:
        raise ValueError("feature outside the channel")


def floor_line(p: F4Params, features: list[Feature]):
    """The feature wall (bottomWall): the line y = 0 plus the feature outlines."""
    return unary_union([LineString([(0.0, 0.0), (p.L, 0.0)]),
                        *[f.section().boundary for f in features]])


def make_polygon(p: F4Params, features: list[Feature]) -> Geometry2D:
    fluid = box(0.0, 0.0, p.L, p.y_top).difference(unary_union(p.pins()))
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
    rnd = lambda ring: np.round(np.asarray(ring.coords), 12)  # noqa: E731
    fluid = Polygon(rnd(fluid.exterior), [rnd(r) for r in fluid.interiors])
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
    regions[side & (np.abs(c[:, 0] - p.L) < tol) & (n[:, 0] > 0.5)] = "outlet"
    out = {}
    for name in (*REGIONS, "sides"):
        idx = np.flatnonzero(regions == name)
        if len(idx):
            out[name] = mesh.submesh([idx], append=True, repair=False)
    return out


def wetted_length(geom: Geometry2D) -> float:
    """Wall length of the 2D domain (all rings minus inlet and outlet)."""
    p = geom.params
    return geom.polygon.length - 2 * p.y_top


def build(p: F4Params, features: list[Feature], z0: float, z1: float):
    geom = make_polygon(p, features)
    regions = extrude(geom, z0, z1)
    meta = {
        "family": "F4",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_length": wetted_length(geom),
        "fluid_area": geom.polygon.area,
        "bounds": list(geom.polygon.bounds),
    }
    return geom, regions, meta
