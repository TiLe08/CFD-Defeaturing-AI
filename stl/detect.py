"""Feature candidates = regions where original and envelope differ (HANDOFF 3.7, step 2).

A triangle belongs to a concave feature if its centroid lies deeper than
eps inside the closed solid, and to a convex feature if it lies higher
than eps above the opened solid. Connected triangles of the same kind
form one feature. Working on the original triangles (instead of voxel
blobs) keeps the original geometry exact and lets defeaturing cut along
the real rim of the feature.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import trimesh

from .envelope import Envelope

KIND_LABEL = {"concave": "Vertiefung", "convex": "Vorsprung"}


@dataclass
class DetectedFeature:
    id: int
    kind: str  # "concave" | "convex"
    h: float  # depth / height [m]
    w: float  # narrow width of the opening [m]
    length: float  # long extent of the opening [m]
    area: float  # wetted area of the feature triangles [m^2]
    area_fraction: float  # area / total surface area
    footprint: float  # area of the opening [m^2]
    centroid: list
    normal: list  # outward normal of the opening
    n_faces: int
    n_openings: int
    faces: np.ndarray = field(repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("faces")
        d["kind_label"] = KIND_LABEL[self.kind]
        return d


@dataclass
class Detection:
    features: list
    face_feature: np.ndarray  # feature id per face, -1 = none
    eps: float
    r_max: float
    pitch: float
    warnings: list
    rejected: int = 0

    def by_id(self, fid: int) -> DetectedFeature:
        return self.features[fid]


def boundary_loops(faces: np.ndarray) -> list:
    """Closed loops of directed boundary edges of a face set (each a vertex list)."""
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    bnd = e[cnt[inv.ravel()] == 1]
    nxt = {}
    for u, v in bnd:
        nxt.setdefault(int(u), []).append(int(v))
    loops = []
    while nxt:
        u0 = next(iter(nxt))
        loop = [u0]
        u = u0
        while True:
            vs = nxt.get(u)
            if not vs:
                break
            v = vs.pop()
            if not vs:
                del nxt[u]
            if v == u0:
                break
            loop.append(v)
            u = v
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _plane(points: np.ndarray, ordered: bool = True):
    c = points.mean(0)
    if ordered and len(points) >= 3:
        nxt = np.roll(points, -1, 0)
        n = np.cross(points - c, nxt - c).sum(0)
    else:
        n = np.linalg.svd(points - c)[2][-1]
    nn = np.linalg.norm(n)
    n = n / nn if nn > 0 else np.array([0.0, 0.0, 1.0])
    return c, n


def _opening_geometry(mesh, faces_idx):
    loops = boundary_loops(mesh.faces[faces_idx])
    if not loops:
        pts = mesh.vertices[np.unique(mesh.faces[faces_idx])]
        return 0.0, 0.0, 0.0, pts.mean(0), np.array([0.0, 0.0, 1.0]), []
    sizes = []
    for lp in loops:
        p = mesh.vertices[lp]
        c, n = _plane(p)
        nxt = np.roll(p, -1, 0)
        sizes.append((0.5 * np.linalg.norm(np.cross(p - c, nxt - c).sum(0)), lp, c, n))
    sizes.sort(key=lambda s: -s[0])
    footprint, lp, c, n = sizes[0]
    p = mesh.vertices[lp] - c
    # in-plane extents of the largest opening
    u = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    q = np.stack([p @ u, p @ v], 1)
    ax = np.linalg.svd(q - q.mean(0))[2]
    ext = np.ptp(q @ ax.T, axis=0)
    # the boundary of the feature faces runs like a cap replacing them, so the
    # Newell normal of that loop is the outward normal of the opening
    return float(ext.max()), float(ext.min()), float(footprint), c, n, loops


MAX_RIM_DEVIATION = 0.6  # rim distance from its plane, relative to h


def _rim_deviation(p: np.ndarray) -> float:
    c, n = _plane(p)
    return float(np.abs((p - c) @ n).max())


def _face_samples(n: int = 4) -> np.ndarray:
    """Barycentric centroids of the n*n equal sub-triangles of a triangle."""
    pts = []
    for i in range(n):
        for j in range(n - i):
            pts.append(((i + 1 / 3) / n, (j + 1 / 3) / n))
            if i + j <= n - 2:
                pts.append(((i + 2 / 3) / n, (j + 2 / 3) / n))
    b = np.array(pts)
    return np.column_stack([1 - b.sum(1), b])


def face_coverage(mesh, field_fn, eps, n: int = 4, chunk: int = 200_000):
    """Fraction of each face's area lying farther than eps from the envelope."""
    bary = _face_samples(n)
    tri = mesh.triangles
    cov = np.empty(len(tri))
    for s in range(0, len(tri), chunk):
        t = tri[s:s + chunk]
        pts = np.einsum("sk,fkd->fsd", bary, t).reshape(-1, 3)
        cov[s:s + chunk] = (field_fn(pts).reshape(len(t), -1) > eps).mean(1)
    return cov


def _height_over_opening(mesh, faces_idx, c, n, loops):
    """Depth/height h: largest distance of feature vertices from the opening plane."""
    vids = np.unique(mesh.faces[faces_idx])
    d = np.abs((mesh.vertices[vids] - c) @ n)
    if len(loops) >= 2:
        # e.g. a through hole: distance between the two openings counts as well
        cs = [mesh.vertices[lp].mean(0) for lp in loops]
        d = np.r_[d, [abs((x - c) @ n) for x in cs]]
    return float(d.max())


def detect_features(mesh: trimesh.Trimesh, env: Envelope, eps: float | None = None,
                    min_coverage: float = 0.5, min_faces: int = 1) -> Detection:
    """Group triangles that deviate from the envelope into features.

    A face counts as feature surface if at least `min_coverage` of its area
    lies deeper than eps inside the closed solid (concave) or higher than
    eps above the opened solid (convex). Area coverage instead of a single
    centroid test suppresses the thin fillet slivers that closing and
    opening create along every sharp edge.
    """
    if eps is None:
        # one voxel: the smallest reliably detectable depth is about 2-3 voxels
        eps = 1.0 * env.pitch
    cov = face_coverage(mesh, lambda p: np.maximum(env.depth_closed(p), env.height_opened(p)), eps)
    adj = mesh.face_adjacency

    def components(mask):
        both = mask[adj[:, 0]] & mask[adj[:, 1]]
        return [np.asarray(sorted(c)) for c in trimesh.graph.connected_components(
            adj[both], nodes=np.flatnonzero(mask), min_len=min_faces)]

    # Rounding by opening/closing next to a feature can pull thin triangles of
    # the surrounding surface into the region. They lie in the plane of the
    # opening and face the same way; trim them and split again if needed.
    work = components(cov >= min_coverage)
    candidates = []
    while work:
        comp = work.pop()
        _, _, _, c, n, loops = _opening_geometry(mesh, comp)
        if loops:
            d = np.abs((mesh.vertices[mesh.faces[comp]] - c) @ n).max(1)
            flat = (d <= eps) & (mesh.face_normals[comp] @ n > 0.9)
            if flat.any() and not flat.all():
                mask = np.zeros(len(mesh.faces), bool)
                mask[comp[~flat]] = True
                work += components(mask)
                continue
        candidates.append(comp)

    total_area = float(mesh.area)
    feats = []
    rejected = 0
    face_feature = np.full(len(mesh.faces), -1)
    for comp in sorted(candidates, key=lambda c: -mesh.area_faces[c].sum()):
        length, w, footprint, c, n, loops = _opening_geometry(mesh, comp)
        h = _height_over_opening(mesh, comp, c, n, loops) if loops else 0.0
        if not loops or h <= eps:
            # flat patches (fillet slivers along sharp edges) are no features
            rejected += 1
            continue
        span = np.ptp(mesh.vertices[np.unique(mesh.faces[comp])], axis=0)
        if (span >= 0.9 * mesh.extents).sum() >= 2:
            # a band around the whole part (e.g. its thin side walls) is no feature
            rejected += 1
            continue
        rim_dev = max(_rim_deviation(mesh.vertices[lp]) for lp in loops)
        if rim_dev > MAX_RIM_DEVIATION * h:
            # strips wrapped around an edge of the part (rounding by opening/
            # closing) have a strongly bent rim; real features have a flat-ish one
            rejected += 1
            continue
        # concave if the feature surface lies below its opening, convex if above
        vids = np.unique(mesh.faces[comp])
        k = "concave" if float(((mesh.vertices[vids] - c) @ n).mean()) < 0 else "convex"
        area = float(mesh.area_faces[comp].sum())
        fid = len(feats)
        face_feature[comp] = fid
        feats.append(DetectedFeature(
            id=fid, kind=k, h=h, w=w, length=length, area=area,
            area_fraction=area / total_area, footprint=footprint,
            centroid=[float(x) for x in c], normal=[float(x) for x in n],
            n_faces=len(comp), n_openings=len(loops), faces=comp,
        ))
    return Detection(features=feats, face_feature=face_feature, eps=float(eps),
                     r_max=env.r_max, pitch=env.pitch, warnings=list(env.warnings),
                     rejected=rejected)
