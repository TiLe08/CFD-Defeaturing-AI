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


def _clean(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
    if not mesh.is_watertight:
        raise MeshError(
            "Die STL ist nicht geschlossen (nicht wasserdicht). Bitte eine "
            "geschlossene Oberfläche exportieren."
        )
    trimesh.repair.fix_normals(mesh)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def load_mesh(source, unit: str = "mm", file_type: str = "stl") -> trimesh.Trimesh:
    """Load an STL (path or file object) and return a clean mesh in metres."""
    if unit not in UNIT_SCALE:
        raise ValueError(f"unknown unit {unit!r}, choose from {sorted(UNIT_SCALE)}")
    loaded = trimesh.load(source, file_type=file_type, force="mesh", process=True)
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise MeshError("Die Datei enthält keine Dreiecke.")
    mesh = _clean(loaded.copy())
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
