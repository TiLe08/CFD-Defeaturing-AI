"""Feature definitions shared by all geometry families.

A feature is described in the local wall coordinate system of the base
geometry: position along the wall (s), width along the wall (w) and
height/depth normal to the wall (h). Concave features (groove) cut into
the solid, convex features (rib) protrude into the fluid.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

FEATURE_TYPES = {"groove": "concave", "rib": "convex"}


@dataclass(frozen=True)
class Feature:
    kind: str  # "groove" or "rib"
    s: float  # centre position along the wall [m]
    w: float  # width along the wall [m]
    h: float  # depth (groove) or height (rib) [m]

    def __post_init__(self):
        if self.kind not in FEATURE_TYPES:
            raise ValueError(f"unknown feature kind {self.kind!r}")
        if self.w <= 0 or self.h <= 0:
            raise ValueError("feature width and height must be positive")

    @property
    def category(self) -> str:
        return FEATURE_TYPES[self.kind]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        return cls(kind=d["kind"], s=d["s"], w=d["w"], h=d["h"])
