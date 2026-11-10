"""Demo parts with known features (for tests, the self-test and the UI demo).

Built with manifold3d booleans, so the STL looks like a CAD export:
large flat triangles, sharp edges, exact feature dimensions.
"""
from __future__ import annotations

import numpy as np
import trimesh

try:
    import manifold3d as m3d
except ImportError:  # pragma: no cover
    m3d = None


def _to_trimesh(man) -> trimesh.Trimesh:
    mesh = man.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)


def demo_plate() -> tuple[trimesh.Trimesh, list]:
    """Plate 100 x 60 x 10 mm with five features. Units: mm.

    Suitable radii: r_max = 4 mm (closing), r_convex = 3.5 mm (opening;
    must stay below half of the 8 mm floor under the pocket).

    Returns the mesh and the list of true features (kind, centre, h).
    """
    if m3d is None:
        raise ImportError("manifold3d is required for demo parts")
    M = m3d.Manifold
    plate = M.cube([100, 60, 10])
    seg = 48
    truth = []
    # 1 through hole d = 6
    plate = plate - M.cylinder(14, 3, 3, seg).translate([20, 20, -2])
    truth.append(("concave", (20, 20, 5), 10.0))
    # 2 blind pocket 6 x 6 x 2 on top
    plate = plate - M.cube([6, 6, 3]).translate([47, 17, 8])
    truth.append(("concave", (50, 20, 9), 2.0))
    # 3 boss d = 6, h = 3 on top
    plate = plate + M.cylinder(3, 3, 3, seg).translate([75, 20, 10])
    truth.append(("convex", (75, 20, 11.5), 3.0))
    # 4 engraved groove 24 x 1.6 x 1 on top ("text stroke")
    plate = plate - M.cube([24, 1.6, 2]).translate([20, 44, 9])
    truth.append(("concave", (32, 44.8, 9.5), 1.0))
    # 5 raised rib 20 x 2 x 1.5 on top ("embossed text")
    plate = plate + M.cube([20, 2, 1.5]).translate([60, 44, 10])
    truth.append(("convex", (70, 45, 10.75), 1.5))
    return _to_trimesh(plate), truth


def write_demo(path, unit_scale: float = 1.0):
    mesh, _ = demo_plate()
    mesh.apply_scale(unit_scale)
    mesh.export(path)
    return path
