"""2D meshes with gmsh for external profiles (F2), extruded to one cell in z.

snappyHexMesh refines isotropically, so the refinement needed at a profile
wall (cells of a few hundredths of a millimetre) would also be applied in z
of the 2D slab. gmsh meshes the plane directly, with a quad boundary layer
on the profile, and extrudes it by one layer (fallback named in the Handoff,
section 3.8).

The fluid is split into a window around the feature slot and the rest; the
rest is meshed from the clean profile only, so it is identical with and
without a feature (see mesh_profile).
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


def _insert_on_ring(ring: np.ndarray, pt: np.ndarray) -> tuple[np.ndarray, int]:
    """Insert pt into the closed ring on the segment it lies on."""
    n = len(ring)
    best, idx = np.inf, 0
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        ab = b - a
        u = np.clip(np.dot(pt - a, ab) / np.dot(ab, ab), 0.0, 1.0)
        d = np.linalg.norm(a + u * ab - pt)
        if d < best:
            best, idx = d, i
    return np.insert(ring, idx + 1, pt, axis=0), idx + 1


def _window_split(ring: np.ndarray, window: Polygon):
    """Split the profile ring at the two crossings with the window sides.

    Returns the crossing points (upstream side, downstream side) and the
    ring with both inserted, rotated so that it starts at the first crossing.
    """
    from shapely.geometry import LineString

    w = np.asarray(window.exterior.coords)[:4]
    prof = LineString(np.vstack([ring, ring[:1]]))
    cross = []
    for a, b in ((w[0], w[3]), (w[1], w[2])):
        hit = prof.intersection(LineString([a, b]))
        if hit.geom_type != "Point":
            raise ValueError("window side must cross the profile exactly once")
        cross.append(np.array([hit.x, hit.y]))
    r, i0 = _insert_on_ring(ring, cross[0])
    r = np.roll(r, -i0, axis=0)
    r, i1 = _insert_on_ring(r, cross[1])
    return cross, r, i1


def _split_geometry(solid: Polygon, window: Polygon) -> dict:
    """Profile ring split into the chain outside and inside the window."""
    from shapely.geometry import Point

    ring = np.asarray(solid.exterior.coords)[:-1]
    if not solid.exterior.is_ccw:
        ring = ring[::-1]
    cross, ring, i1 = _window_split(ring, window)
    n = len(ring)
    inner_first = window.buffer(1e-12).contains(Point(*(0.5 * (ring[0] + ring[1]))))
    idx_in = list(range(0, i1 + 1)) if inner_first else list(range(i1, n)) + [0]
    idx_out = list(range(i1, n)) + [0] if inner_first else list(range(0, i1 + 1))
    w = np.asarray(window.exterior.coords)[:4]
    # corner next to the first and to the last node of the inner chain
    c_first = w[3] if np.allclose(ring[idx_in[0]], cross[0]) else w[2]
    c_last = w[2] if np.allclose(c_first, w[3]) else w[3]
    return {"ring": ring, "idx_in": idx_in, "idx_out": idx_out,
            "c_first": c_first, "c_last": c_last}


def _mesh_region(region: str, g: dict, domain_bounds, clean_bounds, window_bounds,
                 footprint: Polygon, sizes: dict) -> dict:
    """2D mesh of one region ("outer" or "inner") in its own gmsh session.

    Returns node coordinates, triangles, quads (node indices) and the
    boundary edges of each patch.
    """
    import gmsh
    from shapely.geometry import LineString

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add(region)
        geo = gmsh.model.geo
        ring, far, slot = g["ring"], sizes["far"], sizes["slot"]
        idx = g["idx_out"] if region == "outer" else g["idx_in"]
        size = sizes["wall"] if region == "outer" else slot
        pts = {i: geo.addPoint(*ring[i], 0, size) for i in idx}
        chain = [geo.addLine(pts[a], pts[b]) for a, b in zip(idx[:-1], idx[1:])]
        # Interface (window sides and top in the fluid), discretised the same
        # way in both sessions so the two meshes share their nodes.
        first, last = g["idx_in"][0], g["idx_in"][-1]
        p_cf = geo.addPoint(*g["c_first"], 0, slot)
        p_cl = geo.addPoint(*g["c_last"], 0, slot)
        if first not in pts:
            pts[first] = geo.addPoint(*ring[first], 0, slot)
        if last not in pts:
            pts[last] = geo.addPoint(*ring[last], 0, slot)
        iface_pts = [(pts[last], p_cl, ring[last], g["c_last"]),
                     (p_cl, p_cf, g["c_last"], g["c_first"]),
                     (p_cf, pts[first], g["c_first"], ring[first])]
        iface = []
        for a, b, xa, xb in iface_pts:
            ln = geo.addLine(a, b)
            geo.mesh.setTransfiniteCurve(ln, max(2, int(np.ceil(np.linalg.norm(xb - xa) / slot)) + 1))
            iface.append(ln)
        groups = {"profile": chain}
        if region == "outer":
            x0, y0, x1, y1 = domain_bounds
            bp = [geo.addPoint(x, y, 0, far) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            box = [geo.addLine(bp[i], bp[(i + 1) % 4]) for i in range(4)]
            # outer chain runs from the last to the first inner node; close it
            # over the interface backwards
            hole = geo.addCurveLoop(chain + [-c for c in iface[::-1]])
            geo.addPlaneSurface([geo.addCurveLoop(box), hole])
            groups.update(farfield=[box[0], box[2]], outlet=[box[1]], inlet=[box[3]])
            dist_curves = chain + iface
        else:
            geo.addPlaneSurface([geo.addCurveLoop(chain + iface)])
            dist_curves = iface
        geo.synchronize()

        f = gmsh.model.mesh.field
        dist = f.add("Distance")
        f.setNumbers(dist, "CurvesList", dist_curves)
        f.setNumber(dist, "Sampling", 20)
        thr = f.add("Threshold")
        f.setNumber(thr, "InField", dist)
        f.setNumber(thr, "SizeMin", sizes["wall"])
        f.setNumber(thr, "SizeMax", far)
        f.setNumber(thr, "DistMin", sizes["bl_thickness"])
        f.setNumber(thr, "DistMax", sizes["near_dist"])
        sx0, sy0, sx1, sy1 = window_bounds
        slot_f = f.add("Box")
        f.setNumber(slot_f, "VIn", slot)
        f.setNumber(slot_f, "VOut", far)
        for k, v in zip(("XMin", "YMin", "XMax", "YMax", "ZMin", "ZMax"),
                        (sx0, sy0, sx1, sy1, -1.0, 1.0)):
            f.setNumber(slot_f, k, v)
        f.setNumber(slot_f, "Thickness", 2 * (sx1 - sx0))
        wake = f.add("Box")
        f.setNumber(wake, "VIn", sizes.get("wake", 4 * sizes["wall"]))
        f.setNumber(wake, "VOut", far)
        cx0, cy0, cx1, cy1 = clean_bounds
        chord = cx1 - cx0
        for k, v in zip(("XMin", "YMin", "XMax", "YMax", "ZMin", "ZMax"),
                        (cx0 - 0.1 * chord, cy0 - 0.15 * chord, cx1 + 1.0 * chord,
                         cy1 + 0.15 * chord, -1.0, 1.0)):
            f.setNumber(wake, k, v)
        f.setNumber(wake, "Thickness", chord)
        mn = f.add("Min")
        f.setNumbers(mn, "FieldsList", [thr, slot_f, wake])
        f.setAsBackgroundMesh(mn)

        # Layers: thick outside the window; inside it a thin one (thinner
        # than the smallest feature) and none in the feature footprint, where
        # layers would collide in groove corners or fold at a groove lip.
        if region == "outer":
            bl_lines, thick = chain, sizes["bl_thickness"]
        else:
            bl_lines = [ln for ln, a, b in zip(chain, idx[:-1], idx[1:])
                        if not footprint.intersects(LineString([ring[a], ring[b]]))]
            thick = sizes["slot_bl_thickness"]
        if bl_lines and thick > 0:
            bl = f.add("BoundaryLayer")
            f.setNumbers(bl, "CurvesList", bl_lines)
            f.setNumber(bl, "Size", sizes["y1"])
            f.setNumber(bl, "Ratio", sizes["ratio"])
            f.setNumber(bl, "Thickness", thick)
            f.setNumber(bl, "Quads", 1)
            f.setAsBoundaryLayer(bl)

        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay
        gmsh.option.setNumber("Mesh.Smoothing", 10)
        gmsh.model.mesh.generate(2)

        tags, xyz, _ = gmsh.model.mesh.getNodes()
        pos = {int(t): i for i, t in enumerate(tags)}
        xy = xyz.reshape(-1, 3)[:, :2]
        out = {"xy": xy, "tri": [], "quad": [], "edges": {}}
        for etype, _, enodes in zip(*gmsh.model.mesh.getElements(2)):
            if etype in (2, 3):
                k = 3 if etype == 2 else 4
                out["tri" if k == 3 else "quad"].append(
                    np.vectorize(pos.get)(enodes.reshape(-1, k)))
        for k in ("tri", "quad"):
            out[k] = np.vstack(out[k]) if out[k] else np.zeros((0, 3 if k == "tri" else 4), int)
        for name, curves in groups.items():
            e = []
            for c in curves:
                for etype, _, enodes in zip(*gmsh.model.mesh.getElements(1, c)):
                    if etype == 1:
                        e.append(np.vectorize(pos.get)(enodes.reshape(-1, 2)))
            out["edges"][name] = np.vstack(e)
        return out
    finally:
        gmsh.finalize()


def _merge(a: dict, b: dict, tol: float) -> dict:
    """Join two 2D meshes that share the nodes of their interface."""
    from scipy.spatial import cKDTree

    d, j = cKDTree(a["xy"]).query(b["xy"], distance_upper_bound=tol)
    shared = np.isfinite(d)
    new = np.flatnonzero(~shared)
    remap = np.empty(len(b["xy"]), int)
    remap[shared] = j[shared]
    remap[new] = len(a["xy"]) + np.arange(len(new))
    out = {"xy": np.vstack([a["xy"], b["xy"][new]]),
           "tri": np.vstack([a["tri"], remap[b["tri"]]]),
           "quad": np.vstack([a["quad"], remap[b["quad"]]]),
           "edges": {k: v.copy() for k, v in a["edges"].items()},
           "n_shared": int(shared.sum())}
    for k, v in b["edges"].items():
        out["edges"][k] = np.vstack([out["edges"][k], remap[v]]) if k in out["edges"] else remap[v]
    return out


def _ccw(xy: np.ndarray, el: np.ndarray) -> np.ndarray:
    """Order element nodes counter-clockwise (positive cell volumes)."""
    if len(el) == 0:
        return el
    p = xy[el]
    area = 0.5 * np.sum(p[:, :, 0] * np.roll(p[:, :, 1], -1, axis=1)
                        - np.roll(p[:, :, 0], -1, axis=1) * p[:, :, 1], axis=1)
    el = el.copy()
    el[area < 0] = el[area < 0][:, ::-1]
    return el


def _write_extruded_msh(path: Path, m: dict, dz: float) -> int:
    """Extrude the 2D mesh by one layer and write gmsh 2.2 ASCII."""
    xy, n = m["xy"], len(m["xy"])
    tri, quad = _ccw(xy, m["tri"]), _ccw(xy, m["quad"])
    names = ["front", "back", "fluid"] + sorted(m["edges"])
    phys = {k: i + 1 for i, k in enumerate(names)}
    lines, eid = [], 0

    def add(etype, tag, nodes):
        nonlocal eid
        eid += 1
        lines.append(f"{eid} {etype} 2 {tag} {tag} " + " ".join(str(v + 1) for v in nodes))

    for name, e in sorted(m["edges"].items()):
        for a, b in e:
            add(3, phys[name], (a, b, b + n, a + n))
    for t in tri:
        add(2, phys["front"], t[::-1])
        add(2, phys["back"], t + n)
    for q in quad:
        add(3, phys["front"], q[::-1])
        add(3, phys["back"], q + n)
    for t in tri:
        add(6, phys["fluid"], np.r_[t, t + n])
    for q in quad:
        add(5, phys["fluid"], np.r_[q, q + n])
    with open(path, "w") as fh:
        fh.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$PhysicalNames\n")
        fh.write(f"{len(names)}\n")
        for k in names:
            fh.write(f"{3 if k == 'fluid' else 2} {phys[k]} \"{k}\"\n")
        fh.write(f"$EndPhysicalNames\n$Nodes\n{2 * n}\n")
        for z in (0.0, dz):
            for i, (x, y) in enumerate(xy):
                fh.write(f"{i + 1 + (n if z else 0)} {x:.15g} {y:.15g} {z:.15g}\n")
        fh.write(f"$EndNodes\n$Elements\n{len(lines)}\n")
        fh.write("\n".join(lines))
        fh.write("\n$EndElements\n")
    return len(tri) + len(quad)


def _outer_cached(cache_dir: Path | None, args: tuple) -> dict:
    """Outer mesh of a base configuration, made once and then reused.

    gmsh's boundary-layer meshing is not reproducible (the same input can
    give a slightly different mesh), so the outer part is stored and every
    case with the same base configuration and sizes loads the same file.
    """
    import fcntl
    import hashlib
    import json

    if cache_dir is None:
        return _in_fresh_process(_mesh_region, "outer", *args)
    g, domain_b, clean_b, window_b, _, sizes = args
    key_src = json.dumps({"ring": np.round(g["ring"][g["idx_out"]], 12).tolist(),
                          "c": [np.round(g["c_first"], 12).tolist(), np.round(g["c_last"], 12).tolist()],
                          "b": [list(domain_b), list(clean_b), list(window_b)],
                          "sizes": {k: sizes[k] for k in sorted(sizes)}}, sort_keys=True)
    key = hashlib.sha1(key_src.encode()).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"outer_{key}.npz"
    with open(cache_dir / f"outer_{key}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not f.exists():
            m = _in_fresh_process(_mesh_region, "outer", *args)
            tmp = f.with_suffix(".tmp.npz")
            np.savez(tmp, xy=m["xy"], tri=m["tri"], quad=m["quad"],
                     **{f"edges_{k}": v for k, v in m["edges"].items()})
            tmp.replace(f)
        d = np.load(f)
        return {"xy": d["xy"], "tri": d["tri"], "quad": d["quad"],
                "edges": {k[6:]: d[k] for k in d.files if k.startswith("edges_")},
                "key": key}


def _in_fresh_process(fn, *args):
    """Run fn in a new process (gmsh keeps state between models)."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
        return ex.submit(fn, *args).result()


def mesh_profile(out_msh: Path, domain: Polygon, solid: Polygon, clean: Polygon,
                 window: Polygon, footprint: Polygon, sizes: dict, dz: float,
                 cache_dir: Path | None = None) -> dict:
    """Mesh domain minus solid, extruded by one cell; write gmsh 2.2 ASCII.

    The fluid is split into a window around the feature slot and the rest,
    and each part is meshed in its own gmsh process. The outer part depends
    only on the clean profile and is made once per base configuration and
    then reused (_outer_cached), so it is the same mesh, node for node, with
    and without a feature. (Meshed anew, gmsh's boundary-layer algorithm
    gives a different mesh each time, which added noise of several percent
    to c_d.) The interface is discretised identically in
    both parts, and the parts are joined at its nodes.

    window: rotated rectangle whose two short sides cross the profile once
    each; every feature lies inside footprint, footprint inside window.
    sizes: far, wall, slot, y1, ratio, bl_thickness, slot_bl_thickness,
    near_dist (see mesh_sizes in case_f2). cache_dir: where the outer mesh
    is stored for reuse (None: always mesh anew, not reproducible).
    Patches: inlet, outlet, farfield, profile, front, back; cells: fluid.
    """
    g = _split_geometry(solid, window)
    args = (g, domain.bounds, clean.bounds, window.bounds, footprint, sizes)
    outer = _outer_cached(cache_dir, args)
    inner = _in_fresh_process(_mesh_region, "inner", *args)
    n_iface = sum(max(2, int(np.ceil(np.linalg.norm(b - a) / sizes["slot"])) + 1)
                  for a, b in ((g["ring"][g["idx_in"][-1]], g["c_last"]),
                               (g["c_last"], g["c_first"]),
                               (g["c_first"], g["ring"][g["idx_in"][0]]))) - 2
    m = _merge(outer, inner, tol=1e-6 * sizes["y1"])
    if m["n_shared"] != n_iface:
        raise RuntimeError(f"window and outer mesh share {m['n_shared']} nodes, "
                           f"expected {n_iface}")
    n_cells = _write_extruded_msh(out_msh, m, dz)
    return {"cells": n_cells, "y1": sizes["y1"],
            "cells_outer": len(outer["tri"]) + len(outer["quad"]),
            "outer_key": outer.get("key", "")}
