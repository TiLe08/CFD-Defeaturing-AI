"""F1: plane 2D channel with features on the bottom wall (internal, laminar).

The fluid domain is a 2D polygon in the x-y plane, extruded in z to a slab
that is thicker than the blockMesh background slab. snappyHexMesh then only
cuts in x-y, and extrudeMesh collapses the result to one cell in z.

Coordinates: inlet at x = 0, outlet at x = L, bottom wall at y = 0, top wall
at y = H. A groove cuts below y = 0, a rib protrudes above y = 0.

Note: F1 is built from shapely polygons instead of CadQuery. For a 2D
contour this is exact and avoids the OpenCascade dependency (see README).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import trimesh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from geometry.features import Feature

REGIONS = ("inlet", "outlet", "topWall", "bottomWall")


@dataclass(frozen=True)
class F1Params:
    H: float = 0.002  # channel height [m]
    L_up: float = 10.0  # upstream length in multiples of H (inlet to feature slot)
    L_down: float = 15.0  # downstream length in multiples of H
    slot_w_max: float = 2.0  # largest feature width in multiples of H (sets L)
    slot_h_max: float = 0.5  # largest groove depth / rib height in multiples of H

    @property
    def L(self) -> float:
        return (self.L_up + self.slot_w_max + self.L_down) * self.H

    @property
    def s_slot(self) -> float:
        """Centre of the feature slot on the bottom wall [m]."""
        return (self.L_up + 0.5 * self.slot_w_max) * self.H

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(L=self.L, s_slot=self.s_slot)
        return d


@dataclass
class Geometry2D:
    params: F1Params
    features: list[Feature] = field(default_factory=list)
    polygon: Polygon | None = None

    @property
    def y_min(self) -> float:
        return float(self.polygon.bounds[1])


def _check_feature(p: F1Params, f: Feature) -> None:
    if f.kind == "rib" and f.h >= p.H:
        raise ValueError("rib would block the channel")
    if f.s - f.w / 2 <= 0 or f.s + f.w / 2 >= p.L:
        raise ValueError("feature outside the channel")


def make_polygon(p: F1Params, features: list[Feature]) -> Geometry2D:
    """Fluid domain as a shapely polygon."""
    fluid = box(0.0, 0.0, p.L, p.H)
    grooves, ribs = [], []
    for f in features:
        _check_feature(p, f)
        rect = box(f.s - f.w / 2, -f.h if f.kind == "groove" else 0.0,
                   f.s + f.w / 2, 0.0 if f.kind == "groove" else f.h)
        (grooves if f.kind == "groove" else ribs).append(rect)
    if grooves:
        fluid = unary_union([fluid, *grooves])
    if ribs:
        fluid = fluid.difference(unary_union(ribs))
    if fluid.geom_type != "Polygon":
        raise ValueError("features split the fluid domain")
    # Snap coordinates to remove round-off slivers from the boolean operations.
    fluid = Polygon(np.round(np.asarray(fluid.exterior.coords), 12))
    return Geometry2D(params=p, features=list(features), polygon=fluid)


def extrude(geom: Geometry2D, z0: float, z1: float) -> dict[str, trimesh.Trimesh]:
    """Extrude the fluid polygon to a closed surface split into named regions.

    Cap faces (normal +-z) are returned as region "sides". They lie outside
    the background mesh and therefore never become patches.
    """
    p = geom.params
    mesh = trimesh.creation.extrude_polygon(geom.polygon, height=z1 - z0)
    mesh.apply_translation([0.0, 0.0, z0])
    n = mesh.face_normals
    c = mesh.triangles_center
    tol = 1e-9 * max(p.L, 1.0)
    regions = np.full(len(mesh.faces), "bottomWall", dtype=object)
    regions[np.abs(n[:, 2]) > 0.5] = "sides"
    side = np.abs(n[:, 2]) <= 0.5
    regions[side & (np.abs(c[:, 0]) < tol) & (n[:, 0] < -0.5)] = "inlet"
    regions[side & (np.abs(c[:, 0] - p.L) < tol) & (n[:, 0] > 0.5)] = "outlet"
    regions[side & (np.abs(c[:, 1] - p.H) < tol) & (n[:, 1] > 0.5)] = "topWall"
    out = {}
    for name in (*REGIONS, "sides"):
        idx = np.flatnonzero(regions == name)
        if len(idx):
            out[name] = mesh.submesh([idx], append=True, repair=False)
    return out


def to_multisolid_stl(regions: dict[str, trimesh.Trimesh]) -> str:
    """ASCII STL with one solid per region (read by snappyHexMesh as regions)."""
    parts = []
    for name, m in regions.items():
        txt = trimesh.exchange.stl.export_stl_ascii(m)
        # trimesh writes "solid <something>" / "endsolid <something>"
        lines = txt.strip().splitlines()
        lines[0] = f"solid {name}"
        lines[-1] = f"endsolid {name}"
        parts.append("\n".join(lines))
    return "\n".join(parts) + "\n"


def wetted_length(geom: Geometry2D) -> float:
    """Total wall length (both walls, incl. feature flanks) of the 2D domain."""
    p = geom.params
    return geom.polygon.exterior.length - 2 * p.H


def build(p: F1Params, features: list[Feature], z0: float, z1: float):
    """Convenience: polygon, regions and metadata for one case."""
    geom = make_polygon(p, features)
    regions = extrude(geom, z0, z1)
    meta = {
        "family": "F1",
        "params": p.to_dict(),
        "features": [f.to_dict() for f in features],
        "wetted_length": wetted_length(geom),
        "fluid_area": geom.polygon.area,
        "bounds": list(geom.polygon.bounds),
    }
    return geom, regions, meta
