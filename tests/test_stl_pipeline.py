"""STL pipeline (AP5 / tool stage 1) on the demo plate with five known features."""
import numpy as np
import pytest

from stl import defeature, detect, envelope
from stl import io as stlio
from stl.samples import demo_plate


@pytest.fixture(scope="module")
def plate():
    mesh, truth = demo_plate()
    mesh = stlio.from_arrays(mesh.vertices, mesh.faces)
    mesh.apply_scale(1e-3)
    # coarser grid than the tool default keeps the test fast
    env = envelope.build_envelope(mesh, r_max=0.004, r_convex=0.0035, max_voxels=5_000_000)
    det = detect.detect_features(mesh, env)
    return mesh, truth, det


def _match(det, truth):
    """truth index -> detected feature (by nearest centroid)."""
    out = {}
    for i, (kind, c, h) in enumerate(truth):
        c = np.array(c) * 1e-3
        best = min(det.features, key=lambda f: np.linalg.norm(np.array(f.centroid)[:2] - c[:2]))
        out[i] = best
    return out


def test_voxel_volume_matches_mesh(plate):
    mesh, _, _ = plate
    env = envelope.build_envelope(mesh, r_max=0.004, max_voxels=1_000_000)
    assert env.solid.sum() * env.pitch ** 3 == pytest.approx(mesh.volume, rel=0.03)
    assert env.closed.sum() >= env.solid.sum() >= env.opened.sum()


def test_all_five_features_found_and_nothing_else(plate):
    _, truth, det = plate
    assert len(det.features) == len(truth)
    found = _match(det, truth)
    assert len({f.id for f in found.values()}) == len(truth)
    for i, (kind, _, h) in enumerate(truth):
        f = found[i]
        assert f.kind == kind
        assert f.h == pytest.approx(h * 1e-3, rel=0.05)


def test_feature_widths(plate):
    _, truth, det = plate
    found = _match(det, truth)
    assert found[0].w == pytest.approx(6e-3, rel=0.05)  # hole d = 6
    assert found[3].w == pytest.approx(1.6e-3, rel=0.05)  # groove 1.6 wide
    assert found[3].length == pytest.approx(24e-3, rel=0.05)
    assert found[0].n_openings == 2  # through hole: top and bottom
    assert found[1].n_openings == 1  # blind pocket


@pytest.mark.parametrize("which", range(5))
def test_remove_single_feature_volume(plate, which):
    mesh, truth, det = plate
    f = _match(det, truth)[which]
    res = defeature.remove_features(mesh, det, [f.id])
    assert res.failed == {}
    assert res.watertight
    expected = {0: +np.pi * 3 ** 2 * 10, 1: +6 * 6 * 2, 2: -np.pi * 3 ** 2 * 3,
                3: +24 * 1.6 * 1, 4: -20 * 2 * 1.5}[which] * 1e-9
    assert res.mesh.volume - mesh.volume == pytest.approx(expected, rel=0.02)


def test_remove_all_gives_plain_plate(plate):
    mesh, _, det = plate
    res = defeature.remove_features(mesh, det, [f.id for f in det.features])
    assert res.watertight and not res.failed
    assert res.mesh.volume == pytest.approx(100 * 60 * 10 * 1e-9, rel=1e-6)
    assert np.allclose(res.mesh.bounds, [[0, 0, 0], [0.1, 0.06, 0.01]], atol=1e-9)
    env = envelope.build_envelope(res.mesh, r_max=0.004, r_convex=0.0035, max_voxels=1_000_000)
    assert detect.detect_features(res.mesh, env).features == []


def test_untouched_triangles_stay_exact(plate):
    mesh, _, det = plate
    res = defeature.remove_features(mesh, det, [det.features[0].id])
    kept = mesh.faces[det.face_feature != det.features[0].id]
    orig = {tuple(sorted(map(tuple, mesh.vertices[f].round(12)))) for f in kept}
    new = {tuple(sorted(map(tuple, res.mesh.vertices[f].round(12)))) for f in res.mesh.faces}
    assert orig <= new


def test_stl_roundtrip_units(tmp_path, plate):
    mesh, _, _ = plate
    p = stlio.save_stl(mesh, tmp_path / "x.stl", unit="mm")
    back = stlio.load_mesh(p, unit="mm")
    assert back.volume == pytest.approx(mesh.volume, rel=1e-6)


def test_open_mesh_is_rejected():
    import trimesh
    ball = trimesh.creation.icosphere(subdivisions=3)
    # cut away a cap: the hole is far too large for automatic repair
    keep = ball.triangles_center[:, 2] < 0.5
    with pytest.raises(stlio.MeshError):
        stlio.from_arrays(ball.vertices, ball.faces[keep])
