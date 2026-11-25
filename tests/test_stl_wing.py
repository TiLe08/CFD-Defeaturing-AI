"""Defeaturing on a wing model with measurement channels and on multi-body STLs.

Regression tests for the wing model of the project (Nov 2026): with the
default radius nothing was found (holes drowned in the large regions that
the opening shaves off thin walls), and found pressure channels were not
removed (their rim ran along the saddle where the tap meets the channel).
"""
import io

import numpy as np
import pytest
import trimesh

from app.core import Session
from stl import defeature
from stl import io as stlio
from stl.samples import demo_wing

m3d = pytest.importorskip("manifold3d")


def _stl(*meshes) -> bytes:
    return trimesh.exchange.stl.export_stl(trimesh.util.concatenate(meshes))


def _tm(man) -> trimesh.Trimesh:
    m = man.to_mesh()
    return trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts))


@pytest.fixture(scope="module")
def wing():
    mesh, info = demo_wing()
    s = Session.from_bytes(_stl(mesh), "fluegel.stl", "mm")
    s.analyse(max_voxels=3_000_000)  # default radius, as in the tool
    return s, info


def test_default_settings_find_bore_and_channel(wing):
    s, _ = wing
    feats = sorted(s.detection.features, key=lambda f: -f.h)
    assert [f.kind for f in feats] == ["concave", "concave"]
    bore, channel = feats
    assert bore.h == pytest.approx(0.150, rel=0.02) and bore.w == pytest.approx(5.4e-3, rel=0.05)
    assert channel.h == pytest.approx(0.100, rel=0.03) and channel.w == pytest.approx(2.4e-3, rel=0.05)
    assert channel.n_openings == 2  # root face and the tap on the skin


def test_channel_includes_tap_up_to_the_skin(wing):
    s, info = wing
    channel = min(s.detection.features, key=lambda f: f.h)
    x0, y_skin, z0 = np.array(info["tap_at"]) * 1e-3
    pts = s.mesh.vertices[np.unique(s.mesh.faces[channel.faces])]
    near_tap = pts[np.abs(pts[:, 2] - z0) < 1e-3]
    # the tap walls belong to the feature right up to the skin
    assert near_tap[:, 1].max() == pytest.approx(y_skin, abs=0.15e-3)


def test_remove_all_gives_plain_wing(wing):
    s, info = wing
    res = defeature.remove_features(s.mesh, s.detection, [f.id for f in s.detection.features])
    assert res.failed == {}
    assert res.watertight
    assert res.mesh.euler_number == 2  # no holes left (genus 0)
    assert res.mesh.volume == pytest.approx(info["plain_volume"] * 1e-9, rel=1e-3)
    again = Session.from_bytes(_stl(res.mesh), "x.stl", "m")
    again.analyse(max_voxels=3_000_000)
    assert again.detection.features == []


def test_export_protocol_reports_all_removed(wing):
    s, _ = wing
    _, proto = s.export({f.id: "remove" for f in s.detection.features}, out_unit="mm")
    assert proto["counts"]["removed"] == 2 and proto["counts"]["failed"] == 0
    assert proto["output"]["watertight"] is True


# ------------------------------------------------------------------ multi-body STLs
def _load(data):
    notes = []
    mesh = stlio.load_mesh(io.BytesIO(data), "mm", notes=notes)
    return mesh, notes


def test_overlapping_bodies_are_united():
    box = trimesh.creation.box([10, 10, 10])
    mesh, notes = _load(_stl(box, box.copy().apply_translation([5, 0, 0])))
    assert mesh.is_watertight and len(mesh.split()) == 1
    assert mesh.volume * 1e9 == pytest.approx(1500, rel=1e-6)
    assert "vereinigt" in notes[0]


def test_touching_bodies_are_united():
    # face to face: the shared edges are used by four triangles (non-manifold)
    box = trimesh.creation.box([10, 10, 10])
    mesh, notes = _load(_stl(box, box.copy().apply_translation([10, 0, 0])))
    assert mesh.is_watertight and len(mesh.split()) == 1
    assert mesh.volume * 1e9 == pytest.approx(2000, rel=1e-6)
    assert notes


def test_rod_in_wing_bore_like_a_cad_assembly():
    """Wing with a blind bore and a mounting rod sitting in it, exported as two bodies."""
    M = m3d.Manifold
    body = M.cube([60, 20, 80]).translate([0, -10, 0])
    bore = M.cylinder(40, 2.5, 2.5, 48).translate([30, 0, -1])
    rod = M.cylinder(70, 2.5, 2.5, 48).translate([30, 0, -30])  # ends at the bore bottom
    part = body - bore
    mesh, notes = _load(_stl(_tm(part), _tm(rod)))
    assert mesh.is_watertight and len(mesh.split()) == 1
    expected = (part + rod).volume()
    assert mesh.volume * 1e9 == pytest.approx(expected, rel=1e-4)
    assert notes


def test_separate_bodies_stay_separate_but_load():
    box = trimesh.creation.box([10, 10, 10])
    mesh, notes = _load(_stl(box, box.copy().apply_translation([30, 0, 0])))
    assert mesh.is_watertight and len(mesh.split()) == 2
    assert "getrennt" in notes[0]


def test_open_body_gives_helpful_error():
    ball = trimesh.creation.icosphere(subdivisions=3, radius=5)
    # a cap cut away: far too large for automatic repair
    open_ball = trimesh.Trimesh(ball.vertices, ball.faces[ball.triangles_center[:, 2] < 2.5])
    other = trimesh.creation.box([10, 10, 10]).apply_translation([30, 0, 0])
    with pytest.raises(stlio.MeshError) as err:
        _load(_stl(open_ball, other))
    msg = str(err.value)
    assert "offene Kanten" in msg and "Boolean" in msg
