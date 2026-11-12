"""Remove selected features from the original surface (HANDOFF 3.7, step 3).

The triangles of each removed feature are cut out and the opening is
closed with a flat cap triangulated along the original rim. All other
triangles stay untouched, so sharp edges elsewhere are preserved exactly
(no global remeshing). Openings that lie in one plane and are nested
(e.g. a ring groove) are capped together as a polygon with holes.

A feature whose opening cannot be capped cleanly (strongly curved or
self-intersecting rim, e.g. a slot that runs over an edge of the part)
is left in place and reported, never silently mangled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import mapbox_earcut as earcut
import numpy as np
import trimesh
from shapely.geometry import Point, Polygon

from .detect import Detection, boundary_loops

PLANARITY_TOL = 0.05  # max. rim deviation from its plane, relative to rim size
CAP_TOL_H = 0.5  # max. rim deviation from the flat cap, relative to feature height


@dataclass
class DefeatureResult:
    mesh: trimesh.Trimesh
    removed: list
    failed: dict = field(default_factory=dict)  # feature id -> reason
    cap_deviation: dict = field(default_factory=dict)  # feature id -> max rim distance to cap [m]
    watertight: bool = True

    def summary(self) -> dict:
        return {
            "removed": self.removed,
            "failed": {str(k): v for k, v in self.failed.items()},
            "cap_deviation_m": {str(k): v for k, v in self.cap_deviation.items()},
            "watertight": self.watertight,
            "faces": int(len(self.mesh.faces)),
            "volume_m3": float(self.mesh.volume),
        }


def _frame(n):
    u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _newell(p):
    c = p.mean(0)
    n = np.cross(p - c, np.roll(p, -1, 0) - c).sum(0)
    return c, n / (np.linalg.norm(n) or 1.0)


class CapError(RuntimeError):
    pass


def _cap_group(V, loops):
    """Triangulate one set of coplanar rims. loops run like the remaining surface."""
    pts = [V[lp] for lp in loops]
    # cap normal: Newell normal of the reversed largest rim
    areas = []
    for p in pts:
        c, n = _newell(p[::-1])
        areas.append(np.linalg.norm(np.cross(p - c, np.roll(p, -1, 0) - c).sum(0)))
    outer = int(np.argmax(areas))
    c, n = _newell(pts[outer][::-1])
    allp = np.concatenate(pts)
    size = np.ptp(allp, axis=0).max()
    dev = float(np.abs((allp - c) @ n).max())
    if dev > PLANARITY_TOL * size:
        raise CapError(f"Öffnung nicht eben (Abweichung {dev * 1e3:.2f} mm)")
    u, v = _frame(n)
    rings2d = [np.column_stack([(p - c) @ u, (p - c) @ v]) for p in pts]
    order = [outer] + [i for i in range(len(loops)) if i != outer]
    shell = Polygon(rings2d[outer])
    for i in order[1:]:
        if not shell.buffer(0).contains(Point(rings2d[i][0])):
            raise CapError("Öffnungen nicht ineinander")
    verts2d = np.concatenate([rings2d[i] for i in order])
    ends = np.cumsum([len(rings2d[i]) for i in order]).astype(np.uint32)
    tri = np.asarray(earcut.triangulate_float64(verts2d, ends), dtype=np.int64).reshape(-1, 3)
    if len(tri) == 0:
        raise CapError("Triangulierung fehlgeschlagen")
    # a jagged or slightly self-touching rim is fine as long as the triangles
    # tile the opening exactly once (no overlaps, no gaps)
    q = verts2d[tri]
    e1, e2 = q[:, 1] - q[:, 0], q[:, 2] - q[:, 0]
    tri_area = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum()

    def shoelace(r):
        return 0.5 * abs(np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))

    poly_area = shoelace(rings2d[outer]) - sum(shoelace(rings2d[i]) for i in order[1:])
    if poly_area <= 0 or abs(tri_area - poly_area) > 0.01 * poly_area:
        raise CapError("Rand schneidet sich selbst")
    vid = np.concatenate([np.asarray(loops[i]) for i in order])
    faces = vid[tri]
    tn = np.cross(V[faces[:, 1]] - V[faces[:, 0]], V[faces[:, 2]] - V[faces[:, 0]])
    flip = tn @ n < 0
    faces[flip] = faces[flip][:, ::-1]
    return faces, dev


def _group_loops(V, loops, owners):
    """Group rims that share an owner feature and are coplanar and nested."""
    info = []
    for lp in loops:
        c, n = _newell(V[lp])
        info.append((c, n, np.ptp(V[lp], axis=0).max()))
    parent = list(range(len(loops)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(loops)):
        for j in range(i + 1, len(loops)):
            if not owners[i] & owners[j]:
                continue
            ci, ni, si = info[i]
            cj, nj, sj = info[j]
            tol = PLANARITY_TOL * max(si, sj)
            if abs(ni @ nj) > 0.995 and abs((cj - ci) @ ni) < tol:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(loops)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def remove_features(mesh: trimesh.Trimesh, detection: Detection, remove_ids) -> DefeatureResult:
    remove = sorted({int(i) for i in remove_ids})
    failed: dict = {}
    for _ in range(len(remove) + 1):
        active = [i for i in remove if i not in failed]
        result = _try_remove(mesh, detection, active)
        if isinstance(result, DefeatureResult) and not result.watertight:
            # find the feature(s) whose cap breaks the closed surface
            broken = {}
            for fid in active:
                single = _try_remove(mesh, detection, [fid])
                if not isinstance(single, DefeatureResult) or not single.watertight:
                    broken[fid] = "Deckel ergibt keine geschlossene Oberfläche"
            if not broken:  # only the combination fails: keep the last one
                broken[active[-1]] = "Deckel ergibt zusammen mit Nachbar keine geschlossene Oberfläche"
            failed.update(broken)
            continue
        if isinstance(result, DefeatureResult):
            result.failed = failed
            return result
        failed.update(result)  # {feature id: reason}
    raise RuntimeError("defeaturing did not converge")


def _try_remove(mesh, detection, active):
    V = mesh.vertices
    F = mesh.faces
    if not active:
        return DefeatureResult(mesh=mesh.copy(), removed=[])
    gone = np.isin(detection.face_feature, active)
    keep_faces = F[~gone]
    # which removed feature owns each directed rim edge
    owner_of_edge = {}
    for fi in np.flatnonzero(gone):
        a, b, c = F[fi]
        fid = int(detection.face_feature[fi])
        for u, v in ((a, b), (b, c), (c, a)):
            owner_of_edge[(int(u), int(v))] = fid
    loops = boundary_loops(keep_faces)
    owners = []
    for lp in loops:
        own = set()
        for k in range(len(lp)):
            u, v = lp[k], lp[(k + 1) % len(lp)]
            if (v, u) in owner_of_edge:
                own.add(owner_of_edge[(v, u)])
        owners.append(own)
    caps, dev_by_feat, bad = [], {}, {}
    for grp in _group_loops(V, loops, owners):
        own = set().union(*(owners[i] for i in grp))
        try:
            faces, dev = _cap_group(V, [loops[i] for i in grp])
        except CapError as exc:
            for fid in own:
                bad[fid] = str(exc)
            continue
        too_far = [fid for fid in own if dev > CAP_TOL_H * detection.features[fid].h]
        if too_far:
            for fid in too_far:
                bad[fid] = (f"Öffnung zu stark gekrümmt für einen ebenen Deckel "
                            f"(Abweichung {dev * 1e3:.2f} mm)")
            continue
        caps.append(faces)
        for fid in own:
            dev_by_feat[fid] = max(dev_by_feat.get(fid, 0.0), dev)
    if bad:
        return bad
    new_faces = np.concatenate([keep_faces] + caps) if caps else keep_faces
    out = trimesh.Trimesh(V.copy(), new_faces, process=True)
    out.remove_unreferenced_vertices()
    return DefeatureResult(
        mesh=out,
        removed=list(active),
        cap_deviation={k: float(v) for k, v in dev_by_feat.items()},
        watertight=bool(out.is_watertight and out.is_winding_consistent),
    )
