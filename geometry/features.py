"""Feature definitions shared by all geometry families.

A feature is described in the local wall coordinate system of the base
geometry: position along the wall (s), width along the wall (w) and
height/depth normal to the wall (h). Concave features (groove) cut into
the solid, convex features (rib) protrude into the fluid.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

# kind -> category. The 2D cross-sections stand for typical small features of
# machined or moulded parts (milled plates, manifolds):
#   groove        rectangular groove (Nut)
#   rib           rectangular rib (Rippe, Steg)
#   engraving     three narrow, shallow slots (Gravur, Beschriftung)
#   round_groove  half-elliptic groove (Rundnut, Ausrundung)
#   chamfer_rib   rib with 45 degree chamfers (Fase), trapezoid
#   bump          half-elliptic bump (Noppe, Wulst)
#   wedge         step facing the flow, ramp back to the wall (Stufe mit Rampe)
FEATURE_TYPES = {"groove": "concave", "rib": "convex", "engraving": "concave",
                 "round_groove": "concave", "chamfer_rib": "convex", "bump": "convex",
                 "wedge": "convex"}
N_ARC = 24  # segments of a half ellipse


@dataclass(frozen=True)
class Feature:
    kind: str  # one of FEATURE_TYPES
    s: float  # centre position along the wall [m]
    w: float  # width along the wall [m]
    h: float  # depth (groove) or height (rib) [m]
    wall: str = ""  # wall carrying the feature where a family has several (A1: upper/lower)

    def __post_init__(self):
        if self.kind not in FEATURE_TYPES:
            raise ValueError(f"unknown feature kind {self.kind!r}")
        if self.w <= 0 or self.h <= 0:
            raise ValueError("feature width and height must be positive")

    @property
    def category(self) -> str:
        return FEATURE_TYPES[self.kind]

    def section(self) -> Polygon:
        """Cross-section in wall coordinates: x along the wall, y normal to it.

        Convex features lie in 0 <= y <= h (they are removed from the fluid),
        concave ones in -h <= y <= 0 (added to the fluid). The footprint on
        the wall is always s - w/2 ... s + w/2.
        """
        x0, x1, h, w = self.s - self.w / 2, self.s + self.w / 2, self.h, self.w
        sign = 1.0 if self.category == "convex" else -1.0
        if self.kind in ("groove", "rib"):
            return box(x0, min(0.0, sign * h), x1, max(0.0, sign * h))
        if self.kind == "engraving":  # 3 slots of w/5, gaps of w/5
            return unary_union([box(x0 + (2 * i) * w / 5, -h, x0 + (2 * i + 1) * w / 5, 0.0)
                                for i in range(3)])
        if self.kind in ("round_groove", "bump"):
            t = np.linspace(np.pi, 0.0, N_ARC + 1)
            pts = np.c_[self.s + 0.5 * w * np.cos(t), sign * h * np.sin(t)]
            pts[[0, -1]] = [(x0, 0.0), (x1, 0.0)]  # exact ends on the wall
            return Polygon(pts)
        if self.kind == "chamfer_rib":
            c = min(h, 0.25 * w)  # 45 degrees, top keeps at least half the width
            return Polygon([(x0, 0), (x1, 0), (x1, h - c), (x1 - c, h), (x0 + c, h), (x0, h - c)])
        if self.kind == "wedge":
            return Polygon([(x0, 0), (x1, 0), (x0, h)])
        raise ValueError(self.kind)

    def fill_factor(self) -> float:
        """Cross-section area / (w h): 1 for rectangles, pi/4 for half ellipses."""
        return float(self.section().area / (self.w * self.h))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        return cls(kind=d["kind"], s=d["s"], w=d["w"], h=d["h"], wall=d.get("wall", ""))
