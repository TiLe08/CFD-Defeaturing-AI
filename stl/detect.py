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


def face_coverage(mesh, field_fns, eps, n: int = 4, chunk: int = 200_000):
    """Fraction of each face's area lying farther than eps from the envelope.

    field_fns is one function or a list of functions; with a list the result
    has one column per function.
    """
    single = callable(field_fns)
    fns = [field_fns] if single else list(field_fns)
    bary = _face_samples(n)
    tri = mesh.triangles
    cov = np.empty((len(tri), len(fns)))
    for s in range(0, len(tri), chunk):
        t = tri[s:s + chunk]
        pts = np.einsum("sk,fkd->fsd", bary, t).reshape(-1, 3)
        for k, fn in enumerate(fns):
            cov[s:s + chunk, k] = (fn(pts).reshape(len(t), -1) > eps).mean(1)
    return cov[:, 0] if single else cov


def _height_over_opening(mesh, faces_idx, c, n, loops):
    """Depth/height h: largest distance of feature vertices from the opening plane."""
    vids = np.unique(mesh.faces[faces_idx])
    d = np.abs((mesh.vertices[vids] - c) @ n)
    if len(loops) >= 2:
        # e.g. a through hole: distance between the two openings counts as well
        cs = [mesh.vertices[lp].mean(0) for lp in loops]
        d = np.r_[d, [abs((x - c) @ n) for x in cs]]
    return float(d.max())


def _reject_reason(mesh, comp, eps, length, w, c, n, loops, h):
    if not loops or h <= eps:
        # flat patches (fillet slivers along sharp edges) are no features
        return "flat"
    span = np.ptp(mesh.vertices[np.unique(mesh.faces[comp])], axis=0)
    if (span >= 0.9 * mesh.extents).sum() >= 2:
        # a band around the whole part (e.g. its thin side walls) is no feature
        return "band"
    rim_dev = max(_rim_deviation(mesh.vertices[lp]) for lp in loops)
    if rim_dev > MAX_RIM_DEVIATION * h:
        # strips wrapped around an edge of the part (rounding by opening/
        # closing) have a strongly bent rim; real features have a flat-ish one
        return "bent rim"
    return None


RIM_PLANARITY = 0.05  # same as defeature.PLANARITY_TOL: rim deviation from its plane / rim size
MAX_GROW_RINGS = 150
MAX_GROW_AREA = 10.0  # added area per rim, relative to (rim size)^2


def _loop_planarity(V, lp):
    p = V[lp]
    c, n = _plane(p)
    return float(np.abs((p - c) @ n).max()) / (float(np.ptp(p, axis=0).max()) or 1.0)


def _grow_rims(mesh, comp, taken, nbrs, on_surface):
    """Extend a feature over short passages until its rims reach the surface.

    A pressure tap or a small cross hole that connects a deep channel to the
    outer skin is shallower than one voxel, so it is not part of the feature
    and the feature's rim runs along the saddle-shaped intersection of the
    two holes, deep inside the part. Capping there would fail or leave the
    tap as a pit. For every rim that is not flat, grow the feature ring by
    ring across it (never into faces of other features, at most a small
    area) and keep the growth only if the grown band is a clean tube whose
    far rim lies on the outer surface (on_surface).
    """
    V, F = mesh.vertices, mesh.faces
    A = mesh.area_faces
    loops = boundary_loops(F[comp])
    bad = [lp for lp in loops if _loop_planarity(V, lp) > RIM_PLANARITY]
    if not bad:
        return comp
    current = set(int(x) for x in comp)
    vf = mesh.vertex_faces
    for lp0 in bad:
        size = float(np.ptp(V[lp0], axis=0).max())
        rim0 = set(lp0)
        band: set = set()
        lp = lp0
        added = 0.0
        ok = False
        for _ in range(MAX_GROW_RINGS):
            blocked = current | band
            ring = {int(f) for v in lp for f in vf[v] if f >= 0 and f not in blocked and not taken[f]}
            # close pinholes next to the new ring: a free face whose three
            # edge neighbours all belong to the grown region
            grown = blocked | ring
            for f in {int(g) for r in ring for g in nbrs[r]} - grown:
                if not taken[f] and all(int(g) in grown for g in nbrs[f]):
                    ring.add(f)
            if not ring:
                break
            added += float(A[list(ring)].sum())
            if added > MAX_GROW_AREA * size ** 2:
                break
            band |= ring
            # the band must stay a tube: the old rim on one side, one new rim
            band_loops = boundary_loops(F[np.fromiter(band, int)])
            if len(band_loops) != 2:
                break
            far = [x for x in band_loops if set(x) != rim0]
            if len(far) != 1:
                break
            lp = far[0]
            if on_surface(V[lp]):
                ok = True
                break
        if ok:
            current |= band
    return np.asarray(sorted(current))


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
    cov = face_coverage(mesh, [env.depth_closed, env.height_opened], eps)
    cov_any = cov.max(1)
    adj = mesh.face_adjacency

    def components(mask):
        both = mask[adj[:, 0]] & mask[adj[:, 1]]
        return [np.asarray(sorted(c)) for c in trimesh.graph.connected_components(
            adj[both], nodes=np.flatnonzero(mask), min_len=min_faces)]

    # Work items are (faces, kind); kind is None while concave and convex
    # faces are still mixed (kind then follows from the geometry).
    work = [(c, None) for c in components(cov_any >= min_coverage)]
    total_area = float(mesh.area)
    feats = []
    rejected = 0
    face_feature = np.full(len(mesh.faces), -1)
    accepted = []

    def split_by_kind(comp):
        cc = cov[comp, 0] >= cov[comp, 1]
        parts = []
        for k, sel in (("concave", cc), ("convex", ~cc)):
            sel = sel & (cov[comp, 0 if k == "concave" else 1] >= min_coverage)
            if sel.any():
                mask = np.zeros(len(mesh.faces), bool)
                mask[comp[sel]] = True
                parts += [(x, k) for x in components(mask)]
        return parts

    while work:
        comp, kind = work.pop()
        length, w, footprint, c, n, loops = _opening_geometry(mesh, comp)
        # Rounding by opening/closing next to a feature can pull thin triangles
        # of the surrounding surface into the region. They lie in the plane of
        # the opening and face the same way; trim them and split again if needed.
        if loops:
            d = np.abs((mesh.vertices[mesh.faces[comp]] - c) @ n).max(1)
            flat = (d <= eps) & (mesh.face_normals[comp] @ n > 0.9)
            if flat.any() and not flat.all():
                mask = np.zeros(len(mesh.faces), bool)
                mask[comp[~flat]] = True
                work += [(x, kind) for x in components(mask)]
                continue
        h = _height_over_opening(mesh, comp, c, n, loops) if loops else 0.0
        reason = _reject_reason(mesh, comp, eps, length, w, c, n, loops, h)
        if reason is not None:
            if kind is None:
                # Concave and convex regions that touch are merged above. On
                # parts with thin walls (a wing with channels close to the
                # skin, a thin trailing edge) the opening shaves off large
                # areas, and every hole then drowns in one huge region. Split
                # the region by kind and try the parts on their own.
                parts = split_by_kind(comp)
                if parts and not (len(parts) == 1 and len(parts[0][0]) == len(comp)):
                    work += parts
                    continue
            rejected += 1
            continue
        if kind is None:
            # concave if the feature surface lies below its opening, convex if above
            vids = np.unique(mesh.faces[comp])
            kind = "concave" if float(((mesh.vertices[vids] - c) @ n).mean()) < 0 else "convex"
        accepted.append((comp, kind, length, w, footprint, c, n, loops, h))
    taken = np.zeros(len(mesh.faces), bool)
    for a in accepted:
        taken[a[0]] = True
    grown = []
    # edge neighbours per face (CSR), for growing features over short passages
    a = np.concatenate([adj, adj[:, ::-1]])
    a = a[np.argsort(a[:, 0], kind="stable")]
    starts = np.searchsorted(a[:, 0], np.arange(len(mesh.faces) + 1))
    nbrs = [a[starts[i]:starts[i + 1], 1] for i in range(len(mesh.faces))] if accepted else []
    for comp, k, length, w, footprint, c, n, loops, h in accepted:
        if k == "concave":
            on_surface = lambda p: bool(env.depth_closed(p).max() <= 0.5 * eps)  # noqa: E731
        else:
            on_surface = lambda p: bool(env.height_opened(p).max() <= 0.5 * eps)  # noqa: E731
        new = _grow_rims(mesh, comp, taken, nbrs, on_surface)
        if len(new) != len(comp):
            taken[new] = True
            comp = new
            length, w, footprint, c, n, loops = _opening_geometry(mesh, comp)
            h = _height_over_opening(mesh, comp, c, n, loops)
        grown.append((comp, k, length, w, footprint, c, n, loops, h))
    for comp, k, length, w, footprint, c, n, loops, h in sorted(
            grown, key=lambda a: -mesh.area_faces[a[0]].sum()):
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
