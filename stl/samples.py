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


def _naca_sym(t: float, c: float, n: int = 80) -> np.ndarray:
    """Closed outline of a symmetric NACA 4-digit profile (x along chord)."""
    beta = np.linspace(0, np.pi, n)
    x = 0.5 * (1 - np.cos(beta)) * c
    xc = x / c
    yt = 5 * t * c * (0.2969 * np.sqrt(xc) - 0.1260 * xc - 0.3516 * xc ** 2
                      + 0.2843 * xc ** 3 - 0.1036 * xc ** 4)  # closed trailing edge
    up = np.column_stack([x, yt])
    lo = np.column_stack([x[::-1], -yt[::-1]])[1:-1]
    return np.vstack([up, lo])[::-1]  # counter-clockwise


def demo_wing() -> tuple[trimesh.Trimesh, dict]:
    """Wing section like a wind-tunnel model with measurement holes. Units: mm.

    NACA 0024, chord 120, span 150 (z from 0 = root face to 150 = tip face):
      * a spanwise through bore d = 5.4 (assembly rod),
      * a blind pressure channel d = 2.4 from the root face, only 1 mm
        under the upper skin, ending in a pressure tap d = 1.5 that runs
        straight up to the skin.
    The thin wall over the channel and the sharp trailing edge are what
    the size-based opening turns into large "protrusions"; the tap meets
    the channel along a saddle-shaped rim. Both used to break detection
    or capping (wing model of the project, Nov 2026).

    Returns the mesh and facts for tests (volume of the plain profile body).
    """
    if m3d is None:
        raise ImportError("manifold3d is required for demo parts")
    M = m3d.Manifold
    c, t, span = 120.0, 0.24, 150.0
    outline = _naca_sym(t, c)
    body = m3d.CrossSection([outline.tolist()]).extrude(span)
    plain_volume = body.volume()
    seg = 48
    # through bore along the span
    bore = M.cylinder(span + 4, 2.7, 2.7, seg).translate([40.0, 0.0, -2.0])
    # pressure channel 1 mm under the upper skin at x = 30
    x0 = 30.0
    upper = outline[outline[:, 1] >= 0]
    upper = upper[np.argsort(upper[:, 0])]
    y_skin = float(np.interp(x0, upper[:, 0], upper[:, 1]))
    y0 = y_skin - 1.0 - 1.2
    channel = M.cylinder(101.0, 1.2, 1.2, 32).translate([x0, y0, -1.0])
    tap = M.cylinder(y_skin - y0 + 3.0, 0.75, 0.75, 24).rotate([-90.0, 0.0, 0.0]).translate([x0, y0, 98.0])
    wing = body - bore - channel - tap
    return _to_trimesh(wing), {"plain_volume": plain_volume, "chord": c, "span": span,
                                 "tap_at": (x0, y_skin, 98.0)}


def write_demo(path, unit_scale: float = 1.0):
    mesh, _ = demo_plate()
    mesh.apply_scale(unit_scale)
    mesh.export(path)
    return path
