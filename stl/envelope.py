"""Envelope ("Hülle") of a closed surface by voxel morphology (HANDOFF 3.7, step 1).

The solid is voxelised by ray parity along z. Morphological closing with
a ball of radius r_max fills cavities narrower than about 2 r_max (holes,
grooves, engravings); opening removes protrusions thinner than about
2 r_max (screw heads, ribs, embossed text). Both are computed with
Euclidean distance transforms, which is exact for balls and much faster
than binary_closing with a large structuring element.

The two distance fields that detection needs are kept:
    depth_closed(p): how far p lies inside the closed solid  -> concave depth
    height_opened(p): how far p lies outside the opened solid -> convex height
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy import ndimage

DEFAULT_MAX_VOXELS = 8_000_000
MIN_VOXELS_PER_RADIUS = 3.0


@dataclass
class Envelope:
    origin: np.ndarray  # world position of voxel (0,0,0) centre minus pitch/2 [m]
    pitch: float  # voxel edge length [m]
    r_max: float  # closing radius [m] (concave features)
    r_convex: float  # opening radius [m] (convex features)
    solid: np.ndarray  # bool grid, voxel centre inside original
    closed: np.ndarray  # bool grid after closing
    opened: np.ndarray  # bool grid after opening
    dist_in_closed: np.ndarray  # float32, voxel units, distance to outside of `closed`
    dist_out_opened: np.ndarray  # float32, voxel units, distance to `opened`
    warnings: list

    @property
    def shape(self):
        return self.solid.shape

    def _index(self, points):
        return ((np.asarray(points, float) - self.origin) / self.pitch - 0.5).T

    def _sample(self, field, points):
        return ndimage.map_coordinates(field, self._index(points), order=1, mode="nearest")

    def depth_closed(self, points) -> np.ndarray:
        """Depth [m] of surface points inside the closed solid (concave features)."""
        d = self._sample(self.dist_in_closed, points) - 0.5
        return np.clip(d, 0.0, None) * self.pitch

    def height_opened(self, points) -> np.ndarray:
        """Height [m] of surface points above the opened solid (convex features)."""
        d = self._sample(self.dist_out_opened, points) - 0.5
        return np.clip(d, 0.0, None) * self.pitch

    def voxel_of(self, points) -> np.ndarray:
        idx = np.floor((np.asarray(points, float) - self.origin) / self.pitch).astype(int)
        return np.clip(idx, 0, np.array(self.shape) - 1)


def choose_pitch(mesh: trimesh.Trimesh, r_max: float, max_voxels: int = DEFAULT_MAX_VOXELS,
                 pitch: float | None = None):
    """As fine as the voxel budget allows (at most r_max / 20)."""
    warnings = []
    pad = r_max * 1.5
    ext = mesh.extents + 2 * pad
    budget_pitch = float(np.cbrt(np.prod(ext) / max_voxels))
    if pitch is None:
        pitch = max(r_max / 20.0, budget_pitch)
    if r_max / pitch < MIN_VOXELS_PER_RADIUS:
        warnings.append(
            f"Voxelgitter grob: r_max entspricht nur {r_max / pitch:.1f} Voxeln. "
            "Kleine Features werden unsicher erkannt; r_max erhöhen oder "
            "max_voxels anheben."
        )
    return float(pitch), pad, warnings


def voxelize_solid(mesh: trimesh.Trimesh, pitch: float, pad: float):
    """Inside/outside of voxel centres by counting z-ray crossings."""
    origin = mesh.bounds[0] - pad
    shape = np.ceil((mesh.bounds[1] + pad - origin) / pitch).astype(int) + 1
    nx, ny, nz = shape
    # tiny irrational shift avoids rays hitting edges/vertices exactly
    jitter = np.array([1.37e-4, 2.91e-4]) * pitch
    tri = mesh.triangles  # (n, 3, 3)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    ok = np.abs(det) > 1e-30
    a, b, c, det = a[ok], b[ok], c[ok], det[ok]
    gx = (np.stack([a[:, 0], b[:, 0], c[:, 0]], 1) - origin[0] - jitter[0]) / pitch - 0.5
    gy = (np.stack([a[:, 1], b[:, 1], c[:, 1]], 1) - origin[1] - jitter[1]) / pitch - 0.5
    ix0 = np.ceil(gx.min(1)).astype(int)
    ix1 = np.floor(gx.max(1)).astype(int)
    iy0 = np.ceil(gy.min(1)).astype(int)
    iy1 = np.floor(gy.max(1)).astype(int)
    cx = np.maximum(ix1 - ix0 + 1, 0)
    cy = np.maximum(iy1 - iy0 + 1, 0)
    counts = cx * cy
    cols, zs = [], []
    order = np.flatnonzero(counts)
    chunk = 2_000_000
    start = 0
    while start < len(order):
        # take triangles until the chunk of (triangle, column) pairs is full
        csum = np.cumsum(counts[order[start:]])
        stop = start + max(1, int(np.searchsorted(csum, chunk)))
        sel = order[start:stop]
        start = stop
        rep = np.repeat(sel, counts[sel])
        k = np.arange(len(rep)) - np.repeat(np.cumsum(counts[sel]) - counts[sel], counts[sel])
        ix = ix0[rep] + k % cx[rep]
        iy = iy0[rep] + k // cx[rep]
        px = origin[0] + jitter[0] + (ix + 0.5) * pitch
        py = origin[1] + jitter[1] + (iy + 0.5) * pitch
        A, B, C, D = a[rep], b[rep], c[rep], det[rep]
        l1 = ((px - A[:, 0]) * (C[:, 1] - A[:, 1]) - (C[:, 0] - A[:, 0]) * (py - A[:, 1])) / D
        l2 = ((B[:, 0] - A[:, 0]) * (py - A[:, 1]) - (px - A[:, 0]) * (B[:, 1] - A[:, 1])) / D
        inside = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        z = A[:, 2] + l1 * (B[:, 2] - A[:, 2]) + l2 * (C[:, 2] - A[:, 2])
        cols.append((ix * ny + iy)[inside])
        zs.append(z[inside])
    solid = np.zeros(shape, dtype=bool)
    if not cols:
        return solid, origin
    col = np.concatenate(cols)
    z = np.concatenate(zs)
    srt = np.lexsort((z, col))
    col, z = col[srt], z[srt]
    # position of each crossing inside its column
    first = np.r_[True, col[1:] != col[:-1]]
    grp_start = np.flatnonzero(first)
    grp_len = np.diff(np.r_[grp_start, len(col)])
    rank = np.arange(len(col)) - np.repeat(grp_start, grp_len)
    even_len = np.repeat(grp_len % 2 == 0, grp_len)
    enter = (rank % 2 == 0) & even_len
    ei = np.flatnonzero(enter)
    c_in, z_in, z_out = col[ei], z[ei], z[ei + 1]
    k0 = np.ceil((z_in - origin[2]) / pitch - 0.5).astype(int)
    k1 = np.floor((z_out - origin[2]) / pitch - 0.5).astype(int)
    keep = k1 >= k0
    c_in, k0, k1 = c_in[keep], np.clip(k0[keep], 0, nz), np.clip(k1[keep] + 1, 0, nz)
    diff = np.zeros((nx * ny, nz + 1), dtype=np.int32)
    np.add.at(diff, (c_in, k0), 1)
    np.add.at(diff, (c_in, k1), -1)
    solid = (np.cumsum(diff[:, :nz], axis=1) > 0).reshape(nx, ny, nz)
    return solid, origin


def build_envelope(mesh: trimesh.Trimesh, r_max: float, max_voxels: int = DEFAULT_MAX_VOXELS,
                   pitch: float | None = None, r_convex: float | None = None) -> Envelope:
    """Closing with radius r_max (concave features), opening with r_convex.

    r_convex defaults to r_max. It must stay below half the thinnest wall
    of the part, otherwise opening removes the wall itself.
    """
    r_convex = r_max if r_convex is None else r_convex
    if r_max <= 0 or r_convex <= 0:
        raise ValueError("radii must be positive")
    pitch, pad, warnings = choose_pitch(mesh, max(r_max, r_convex), max_voxels, pitch)
    if min(r_max, r_convex) / pitch < MIN_VOXELS_PER_RADIUS and not warnings:
        warnings.append("Voxelgitter grob im Verhältnis zum kleineren Radius.")
    solid, origin = voxelize_solid(mesh, pitch, pad)
    edt = ndimage.distance_transform_edt
    rc, ro = r_max / pitch, r_convex / pitch
    dilated = edt(~solid) <= rc
    closed = edt(dilated) > rc
    eroded = edt(solid) > ro
    opened = edt(~eroded) <= ro
    closed |= solid
    opened &= solid
    return Envelope(
        origin=origin,
        pitch=pitch,
        r_max=r_max,
        r_convex=r_convex,
        solid=solid,
        closed=closed,
        opened=opened,
        dist_in_closed=edt(closed).astype(np.float32),
        dist_out_opened=edt(~opened).astype(np.float32),
        warnings=warnings,
    )
