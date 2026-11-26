"""F5: 3D section of a bipolar plate flow channel (internal, laminar).

A straight rectangular channel of height H and width W (span, z) with one
3D feature on the floor (y = 0), centred in z. It checks whether what was
learned on the 2D families carries over to 3D (HANDOFF 3.4).

Feature kinds (all with height or depth h and streamwise size w):
- hole:        round cavity, diameter w (concave)
- boss:        round pin, diameter w (convex)
- groove_part: rectangular cavity, spanwise length b (concave)
- rib_part:    rectangular rib, spanwise length b (convex)

Regions as in F1: the floor with the feature is "bottomWall", ceiling and
both side walls are "topWall". All wall positions are multiples of H/10, so
no wall coincides with a face of the background mesh (see F4).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import trimesh

from geometry.families.f1_channel import to_multisolid_stl  # noqa: F401

REGIONS = ("inlet", "outlet", "topWall", "bottomWall")
ROUND = ("hole", "boss")
CONCAVE = ("hole", "groove_part")
F5_KINDS = ("hole", "boss", "groove_part", "rib_part")


@dataclass(frozen=True)
class F5Params:
    H: float = 0.002  # channel height [m]
    W: float = 2.0  # channel width (span) / H
    L_up: float = 8.0  # inlet to slot centre / H
    L_down: float = 12.0  # slot centre to outlet / H
    slot_w_max: float = 2.0  # largest streamwise feature size / H
    slot_h_max: float = 0.5  # largest depth / height / H

    def __post_init__(self):
        if abs(self.W * 10 - round(self.W * 10)) > 1e-9:
            raise ValueError("W must be a multiple of 0.1 H (background mesh)")

    @property
    def L(self) -> float:
        return (self.L_up + self.L_down) * self.H

    @property
    def s_slot(self) -> float:
        return self.L_up * self.H

    @property
    def y_top(self) -> float:
        return self.H

    @property
    def z_width(self) -> float:
        return self.W * self.H

    @property
    def loc(self) -> tuple[float, float]:
        return 0.5 * self.L_up * self.H, 0.5 * self.H

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(L=self.L, s_slot=self.s_slot, z_width=self.z_width)
        return d


@dataclass(frozen=True)
class Feature3D:
    kind: str
    s: float  # streamwise centre [m]
    w: float  # streamwise size (diameter for round kinds) [m]
    h: float  # depth / height [m]
    b: float = 0.0  # spanwise length [m] (round kinds: = w)

    @property
    def category(self) -> str:
        return "concave" if self.kind in CONCAVE else "convex"

    @property
    def span(self) -> float:
        return self.w if self.kind in ROUND else self.b

    def footprint_area(self) -> float:
        return np.pi / 4 * self.w ** 2 if self.kind in ROUND else self.w * self.b

    def volume(self) -> float:
        return self.footprint_area() * self.h

    @classmethod
    def from_dict(cls, d: dict) -> "Feature3D":
        if d["kind"] not in F5_KINDS:
            raise ValueError(f"unknown 3D feature kind {d['kind']}")
        return cls(kind=d["kind"], s=d["s"], w=d["w"], h=d["h"], b=d.get("b", 0.0))

    def to_dict(self) -> dict:
        return {"kind": self.kind, "s": self.s, "w": self.w, "h": self.h, "b": self.span}


def parse_features(dicts: list[dict]) -> list[Feature3D]:
    return [Feature3D.from_dict(d) for d in dicts]


def _check(p: F5Params, f: Feature3D) -> None:
    if f.category == "convex" and f.h >= 0.6 * p.H:
        raise ValueError("feature would block the channel")
    if f.span >= 0.9 * p.z_width:
        raise ValueError("feature touches the side walls")
    if f.s - f.w / 2 <= 0 or f.s + f.w / 2 >= p.L:
        raise ValueError("feature outside the channel")


def _solid(p: F5Params, f: Feature3D) -> trimesh.Trimesh:
    """Feature volume; concave ones reach below the floor, convex ones above."""
    zc = 0.5 * p.z_width
    eps = 0.05 * p.H  # overlap with the channel body for a clean boolean
    if f.category == "concave":
        y0, y1 = -f.h, eps
    else:
        y0, y1 = -eps, f.h
    if f.kind in ROUND:
        # built at unit size and scaled: at mm size trimesh merges close
        # vertices and the cylinder is no longer a closed volume
        m = trimesh.creation.cylinder(radius=0.5, height=1.0, sections=48)
        m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        m.apply_scale([f.w, y1 - y0, f.w])
        m.apply_translation([f.s, 0.5 * (y0 + y1), zc])
        return m
    m = trimesh.creation.box(extents=[f.w, y1 - y0, f.b])
    m.apply_translation([f.s, 0.5 * (y0 + y1), zc])
    return m


def make_mesh(p: F5Params, features: list[Feature3D]) -> trimesh.Trimesh:
    body = trimesh.creation.box(extents=[p.L, p.H, p.z_width])
    body.apply_translation([p.L / 2, p.H / 2, p.z_width / 2])
    for f in features:
        _check(p, f)
        solid = _solid(p, f)
        if f.category == "concave":
            body = trimesh.boolean.union([body, solid], engine="manifold")
        else:
            body = trimesh.boolean.difference([body, solid], engine="manifold")
    if not body.is_watertight or body.body_count != 1:
        raise ValueError("features split or break the fluid domain")
    return body


def regions_of(p: F5Params, mesh: trimesh.Trimesh) -> dict[str, trimesh.Trimesh]:
    n, c = mesh.face_normals, mesh.triangles_center
    tol = 1e-9 * max(p.L, 1.0)
    regions = np.full(len(mesh.faces), "bottomWall", dtype=object)
    top = ((np.abs(c[:, 1] - p.H) < tol) & (n[:, 1] > 0.5)) | \
          ((np.abs(c[:, 2]) < tol) & (n[:, 2] < -0.5)) | \
          ((np.abs(c[:, 2] - p.z_width) < tol) & (n[:, 2] > 0.5))
    regions[top] = "topWall"
    regions[(np.abs(c[:, 0]) < tol) & (n[:, 0] < -0.5)] = "inlet"
    regions[(np.abs(c[:, 0] - p.L) < tol) & (n[:, 0] > 0.5)] = "outlet"
    out = {}
    for name in REGIONS:
        idx = np.flatnonzero(regions == name)
        if len(idx):
            out[name] = mesh.submesh([idx], append=True, repair=False)
    return out


def wetted_area(regions: dict[str, trimesh.Trimesh]) -> float:
    return float(regions["topWall"].area + regions["bottomWall"].area)


def build(p: F5Params, features: list[Feature3D], z0: float = 0.0, z1: float = 0.0):
    """z0, z1 are ignored (3D); kept for the common build signature."""
    mesh = make_mesh(p, features)
    regions = regions_of(p, mesh)
    meta = {
        "family": "F5",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_area": wetted_area(regions),
        # 2D code reads wetted_length; in 3D the descriptors use the area
        "wetted_length": wetted_area(regions) / p.z_width,
        "fluid_volume": float(mesh.volume),
        "bounds": mesh.bounds.tolist(),
    }
    return mesh, regions, meta


def geometric_descriptors_3d(f: Feature3D, p: F5Params, wetted_area_base: float, Re: float) -> dict:
    """Same columns as the 2D geometric descriptors (descriptors/geometric.py)."""
    H = p.H
    return {
        "category": f.category,
        "h_over_L": f.h / H,
        "w_over_L": f.w / H,
        "h_over_w": f.h / f.w,
        "area_frac": f.footprint_area() / wetted_area_base,
        "fill_factor": f.volume() / (f.w * f.h * f.span),
        "n_elem": 1,
        # long axis across the flow = 90 deg (as the 2D features); round = 90
        "orient_deg": 0.0 if (f.kind not in ROUND and f.span < f.w) else 90.0,
        "Re": Re,
    }
