"""Loading and saving STL files with explicit units.

Internally everything is in metres (snappyHexMesh works in m). The unit
of the input file has to be given, because STL itself carries none.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

UNIT_SCALE = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "in": 0.0254}


class MeshError(ValueError):
    """The STL cannot be processed (e.g. not closed)."""


def split_bodies(mesh: trimesh.Trimesh) -> list:
    """Split a triangle soup into bodies, also where bodies touch.

    Where two bodies of an assembly touch, their vertices coincide and an
    edge is used by four triangles instead of two (non-manifold), so plain
    connectivity glues the bodies into one broken surface. Here every
    triangle is paired, across each of its edges, with one triangle that
    runs the edge the other way: the next one when turning around the edge
    into the solid behind the triangle. Bodies of zero volume (two touching
    walls paired with each other) are dropped by the caller.
    """
    f = mesh.faces
    V = mesh.vertices
    n = len(f)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    third = np.concatenate([f[:, 2], f[:, 0], f[:, 1]])
    fid = np.tile(np.arange(n), 3)
    fwd = e[:, 0] < e[:, 1]
    key = np.where(fwd[:, None], e, e[:, ::-1])
    order = np.lexsort((fid, key[:, 1], key[:, 0]))
    key, fwd, fid, third = key[order], fwd[order], fid[order], third[order]
    start = np.r_[0, np.flatnonzero((np.diff(key, axis=0) != 0).any(1)) + 1, len(key)]
    multi = np.flatnonzero(np.diff(start) > 2)
    simple = np.flatnonzero(np.diff(start) == 2)
    a = start[simple]
    ok = fwd[a] != fwd[a + 1]
    pairs = [np.column_stack([fid[a[ok]], fid[a[ok] + 1]])]
    normals = mesh.face_normals
    for gi in multi:
        sl = slice(start[gi], start[gi + 1])
        u, v = V[key[sl.start, 0]], V[key[sl.start, 1]]
        d = (v - u) / (np.linalg.norm(v - u) or 1.0)
        e1 = np.cross(d, [1.0, 0, 0] if abs(d[0]) < 0.9 else [0, 1.0, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        w = V[third[sl]] - u
        theta = np.arctan2(w @ e2, w @ e1)
        tang = np.column_stack([-np.sin(theta), np.cos(theta)]) @ np.vstack([e1, e2])
        faces_here = fid[sl]
        is_fwd = fwd[sl]
        # direction (+1/-1 in theta) from each face into the solid behind it
        into = np.sign(-(normals[faces_here] * tang).sum(1))
        free_back = set(np.flatnonzero(~is_fwd).tolist())
        for k in np.flatnonzero(is_fwd):
            if not free_back:
                break
            # the partner closes the wedge: its outward side faces away from
            # the wedge (into[j] == -into[k]); a coincident triangle (turn
            # of 0) would enclose nothing and comes last
            cand = [j for j in free_back if into[j] == -into[k]] or list(free_back)

            def turn(j):
                t = ((theta[j] - theta[k]) * into[k]) % (2 * np.pi)
                return t if t > 1e-9 else 2 * np.pi

            j = min(cand, key=turn)
            free_back.discard(j)
            pairs.append(np.array([[faces_here[k], faces_here[j]]]))
    pairs = np.concatenate(pairs) if pairs else np.zeros((0, 2), int)
    groups = trimesh.graph.connected_components(pairs, nodes=np.arange(n), min_len=1)
    bodies = []
    for g in groups:
        b = trimesh.Trimesh(V, f[np.sort(g)], process=False)
        b.remove_unreferenced_vertices()
        bodies.append(b)
    return bodies


def _basic_clean(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    return mesh


def _try_fill(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    if not mesh.is_watertight:
        try:
            trimesh.repair.fill_holes(mesh)
        except Exception:  # repair is best effort (needs networkx)
            pass
    return mesh


def _union(bodies) -> trimesh.Trimesh | None:
    """Boolean union of closed bodies with manifold3d (None if not possible)."""
    try:
        import manifold3d as m3d
    except ImportError:  # pragma: no cover
        return None
    total = None
    for b in bodies:
        man = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(b.vertices, np.float64),
                                    tri_verts=np.asarray(b.faces, np.uint32)))
        if man.status() != m3d.Error.NoError or man.is_empty():
            return None
        total = man if total is None else total + man
    out = total.to_mesh()
    res = trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=True)
    return res if len(res.faces) else None


def _open_edges(mesh: trimesh.Trimesh) -> int:
    e = np.sort(mesh.edges, axis=1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return int((cnt != 2).sum())


def _clean(mesh: trimesh.Trimesh, notes: list | None = None) -> trimesh.Trimesh:
    """Clean up, repair small holes and merge several bodies into one solid.

    CAD programs often export an assembly ("composite part") as several
    closed bodies in one STL, which overlap or touch. Each body on its own
    is fine, but together they are no valid surface for meshing, and the
    voxel inside/outside test counts overlaps as outside. They are merged
    by a boolean union, which is what the user would otherwise do in CAD.
    """
    notes = [] if notes is None else notes
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    bodies = split_bodies(mesh)
    if len(bodies) == 1:
        mesh = _try_fill(_basic_clean(mesh))
    if len(bodies) > 1 or not mesh.is_watertight:
        bodies = [_try_fill(_basic_clean(b)) for b in bodies]
        # two touching walls paired with each other enclose nothing
        tiny = 1e-9 * float(np.prod(mesh.extents))
        bodies = [b for b in bodies if not (b.is_watertight and abs(b.volume) <= tiny)]
        open_bodies = [b for b in bodies if not b.is_watertight]
        if len(bodies) == 1:
            mesh = bodies[0]
        if len(bodies) > 1 and not open_bodies:
            for b in bodies:
                trimesh.repair.fix_normals(b)
                if b.volume < 0:
                    b.invert()
            merged = _union(bodies)
            if merged is not None and merged.is_watertight:
                n_after = len(merged.split(only_watertight=False))
                if n_after == 1:
                    notes.append(f"Die Datei bestand aus {len(bodies)} einzelnen Körpern. Sie wurden "
                                 "automatisch zu einem Körper vereinigt (wie Boolean-Vereinigen im CAD).")
                else:
                    notes.append(f"Die Datei bestand aus {len(bodies)} einzelnen Körpern. Wo sie sich "
                                 f"berühren oder überlappen, wurden sie vereinigt; {n_after} Körper "
                                 "liegen getrennt voneinander und bleiben getrennt.")
                mesh = merged
            else:
                raise MeshError(
                    f"Die Datei besteht aus {len(bodies)} einzelnen Körpern, die sich nicht "
                    "automatisch vereinigen ließen. Bitte im CAD-Programm alle Teile mit "
                    "Boolean vereinigen und als ein Teil exportieren.")
        if not mesh.is_watertight:
            n_open = sum(_open_edges(b) for b in open_bodies) if open_bodies else _open_edges(mesh)
            parts = (f" Die Datei besteht aus {len(bodies)} Teilen, {len(open_bodies)} davon "
                     "sind offen." if len(bodies) > 1 else "")
            raise MeshError(
                "Die STL ist nicht geschlossen (nicht wasserdicht): "
                f"{n_open} offene Kanten.{parts} Tipp: Im CAD-Programm die Teile mit "
                "Boolean zu einem Körper vereinigen, als ein Teil (nicht als Baugruppe "
                "oder Composite Part) exportieren und eine feine STL-Auflösung wählen.")
    trimesh.repair.fix_normals(mesh)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def load_mesh(source, unit: str = "mm", file_type: str = "stl", notes: list | None = None) -> trimesh.Trimesh:
    """Load an STL (path or file object) and return a clean mesh in metres.

    notes (optional list) receives German messages about repairs made.
    """
    if unit not in UNIT_SCALE:
        raise ValueError(f"unknown unit {unit!r}, choose from {sorted(UNIT_SCALE)}")
    loaded = trimesh.load(source, file_type=file_type, force="mesh", process=True)
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise MeshError("Die Datei enthält keine Dreiecke.")
    mesh = _clean(loaded.copy(), notes)
    mesh.apply_scale(UNIT_SCALE[unit])
    return mesh


def from_arrays(vertices, faces) -> trimesh.Trimesh:
    return _clean(trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces, int), process=True))


def save_stl(mesh: trimesh.Trimesh, path, unit: str = "m", solid_name: str = "defeatured") -> Path:
    """Write a binary STL in the requested unit."""
    path = Path(path)
    out = mesh.copy()
    out.apply_scale(1.0 / UNIT_SCALE[unit])
    out.metadata["name"] = solid_name
    path.write_bytes(trimesh.exchange.stl.export_stl(out))
    return path
