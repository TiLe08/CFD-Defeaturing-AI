"""2D meshes with gmsh for external profiles (F2), extruded to one cell in z.

snappyHexMesh refines isotropically, so the refinement needed at a profile
wall (cells of a few hundredths of a millimetre) would also be applied in z
of the 2D slab. gmsh meshes the plane directly, with a quad boundary layer
on the profile, and extrudes it by one layer (fallback named in the Handoff,
section 3.8).

The mesh size fields depend only on the base configuration and the slot
region, so runs with and without a feature share the same sizing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from shapely.geometry import Polygon


def first_cell_height(U: float, nu: float, L: float, y_plus: float = 1.0) -> float:
    """Wall distance for a target y+ from a flat-plate skin-friction estimate."""
    re = U * L / nu
    cf = 0.026 * re ** (-1.0 / 7.0)
    u_tau = U * np.sqrt(0.5 * cf)
    return y_plus * nu / u_tau


def mesh_profile(out_msh: Path, domain: Polygon, solid: Polygon, slot: Polygon,
                 sizes: dict, dz: float, clean: Polygon | None = None) -> dict:
    """Mesh domain minus solid; write gmsh 2.2 ASCII; return mesh stats.

    sizes: far (domain edges), wall (tangential size on the profile),
    slot (inside the slot region), y1 (first layer), ratio, bl_thickness,
    slot_bl_thickness (layer thickness inside the slot region),
    near_dist (distance over which sizes grow from wall to far).
    Physical groups: inlet, outlet, farfield, profile, front, back, fluid.
    """
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("f2")
        geo = gmsh.model.geo
        x0, y0, x1, y1 = domain.bounds
        far = sizes["far"]
        box_pts = [geo.addPoint(x, y, 0, far) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        bottom = geo.addLine(box_pts[0], box_pts[1])
        outlet = geo.addLine(box_pts[1], box_pts[2])
        top = geo.addLine(box_pts[2], box_pts[3])
        inlet = geo.addLine(box_pts[3], box_pts[0])
        outer = geo.addCurveLoop([bottom, outlet, top, inlet])

        ring = np.asarray(solid.exterior.coords)[:-1]
        pts = [geo.addPoint(x, y, 0, sizes["wall"]) for x, y in ring]
        wall_lines = [geo.addLine(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
        hole = geo.addCurveLoop(wall_lines)
        surf = geo.addPlaneSurface([outer, hole])
        geo.synchronize()

        f = gmsh.model.mesh.field
        dist = f.add("Distance")
        f.setNumbers(dist, "CurvesList", wall_lines)
        f.setNumber(dist, "Sampling", 20)
        thr = f.add("Threshold")
        f.setNumber(thr, "InField", dist)
        f.setNumber(thr, "SizeMin", sizes["wall"])
        f.setNumber(thr, "SizeMax", far)
        f.setNumber(thr, "DistMin", sizes["bl_thickness"])
        f.setNumber(thr, "DistMax", sizes["near_dist"])
        sx0, sy0, sx1, sy1 = slot.bounds
        slot_f = f.add("Box")
        f.setNumber(slot_f, "VIn", sizes["slot"])
        f.setNumber(slot_f, "VOut", far)
        for k, v in zip(("XMin", "YMin", "XMax", "YMax"), (sx0, sy0, sx1, sy1)):
            f.setNumber(slot_f, k, v)
        f.setNumber(slot_f, "ZMin", -1.0)
        f.setNumber(slot_f, "ZMax", 1.0)
        f.setNumber(slot_f, "Thickness", 2 * (sx1 - sx0))
        wake = f.add("Box")
        f.setNumber(wake, "VIn", sizes.get("wake", 4 * sizes["wall"]))
        f.setNumber(wake, "VOut", far)
        cx0, cy0, cx1, cy1 = solid.bounds
        chord = cx1 - cx0
        for k, v in zip(("XMin", "YMin", "XMax", "YMax", "ZMin", "ZMax"),
                        (cx0 - 0.1 * chord, cy0 - 0.15 * chord, cx1 + 1.0 * chord,
                         cy1 + 0.15 * chord, -1.0, 1.0)):
            f.setNumber(wake, k, v)
        f.setNumber(wake, "Thickness", chord)
        mn = f.add("Min")
        f.setNumbers(mn, "FieldsList", [thr, slot_f, wake])
        f.setAsBackgroundMesh(mn)

        # Inside the slot region features are of the order of the outer layer
        # thickness and would make the layers collide, so the slot lines get a
        # second, thin layer (same y1 and ratio, thinner than the smallest
        # feature). The outer layers then end at a height where the cells are
        # already coarse, instead of at the wall (skewed cells otherwise).
        from shapely.geometry import LineString, Point
        from shapely.ops import unary_union

        slot_zone = slot.buffer(0.0)
        in_slot = [slot_zone.contains(Point(*(0.5 * (ring[i] + ring[(i + 1) % len(ring)]))))
                   for i in range(len(ring))]
        # Lines created by a feature (not on the clean profile) get no layer:
        # layers meeting in the concave corners of a groove make gmsh fail.
        # The layer also stops a few cells before a feature: ending it at the
        # lip of a groove folds the last column of cells.
        mids = [Point(*(0.5 * (ring[i] + ring[(i + 1) % len(ring)]))) for i in range(len(ring))]
        on_clean = [True] * len(ring)
        if clean is not None:
            feat = [LineString([ring[i], ring[(i + 1) % len(ring)]])
                    for i, mp in enumerate(mids) if clean.exterior.distance(mp) > 1e-9]
            if feat:
                near = unary_union(feat).buffer(3 * sizes["slot"])
                on_clean = [clean.exterior.distance(mp) < 1e-9
                            and not near.intersects(LineString([ring[i], ring[(i + 1) % len(ring)]]))
                            for i, mp in enumerate(mids)]
        groups_bl = [([ln for ln, s in zip(wall_lines, in_slot) if not s], sizes["bl_thickness"]),
                     ([ln for ln, s, o in zip(wall_lines, in_slot, on_clean) if s and o],
                      sizes["slot_bl_thickness"])]
        for lines, thick in groups_bl:
            if not lines or thick <= 0:
                continue
            bl = f.add("BoundaryLayer")
            f.setNumbers(bl, "CurvesList", lines)
            f.setNumber(bl, "Size", sizes["y1"])
            f.setNumber(bl, "Ratio", sizes["ratio"])
            f.setNumber(bl, "Thickness", thick)
            f.setNumber(bl, "Quads", 1)
            f.setAsBoundaryLayer(bl)

        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay
        gmsh.option.setNumber("Mesh.RecombineAll", 0)
        gmsh.option.setNumber("Mesh.Smoothing", 10)

        ext = geo.extrude([(2, surf)], 0, 0, dz, numElements=[1], recombine=True)
        geo.synchronize()
        # ext: [top surface, volume, lateral surfaces in curve order]
        back = ext[0][1]
        vol = ext[1][1]
        lateral = [e[1] for e in ext[2:]]
        n_box = 4
        groups = {
            "farfield": [lateral[0], lateral[2]],
            "outlet": [lateral[1]],
            "inlet": [lateral[3]],
            "profile": lateral[n_box:],
            "front": [surf],
            "back": [back],
        }
        for name, tags in groups.items():
            gmsh.model.addPhysicalGroup(2, tags, name=name)
        gmsh.model.addPhysicalGroup(3, [vol], name="fluid")

        gmsh.model.mesh.generate(3)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.write(str(out_msh))
        types, tags, _ = gmsh.model.mesh.getElements(3)
        n_cells = int(sum(len(t) for t in tags))
        return {"cells": n_cells, "y1": sizes["y1"]}
    finally:
        gmsh.finalize()
