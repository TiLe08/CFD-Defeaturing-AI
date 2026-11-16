"""F2 (NACA profile): geometry, design, case set-up and mesh, without OpenFOAM."""
import json

import numpy as np
import pandas as pd
import pytest

from cfd import case_f2
from cfd import run_case as rc
from geometry.families import f2_naca
from geometry.features import Feature
from pipeline import build_dataset, sweep

P = f2_naca.F2Params()


def _feat(kind="groove", h=0.005, wall="upper", s=0.5, w=0.05):
    return Feature(kind=kind, s=s * P.c, w=w * P.c, h=h * P.c, wall=wall)


def test_naca_closed_trailing_edge_and_thickness():
    up, lo = f2_naca.naca4(P.m, P.p, P.t, P.c, P.n_side)
    assert np.allclose(up[-1], [P.c, 0]) and np.allclose(lo[-1], [P.c, 0])
    x = np.linspace(0.05, 0.95, 50) * P.c
    thick = np.interp(x, up[:, 0], up[:, 1]) - np.interp(x, lo[:, 0], lo[:, 1])
    assert thick.max() == pytest.approx(P.t * P.c, rel=0.02)


@pytest.mark.parametrize("kind,sign", [("groove", -1), ("rib", 1)])
@pytest.mark.parametrize("wall", ["upper", "lower"])
def test_feature_changes_area_by_its_footprint(kind, sign, wall):
    f = _feat(kind, wall=wall)
    a0 = f2_naca.profile_polygon(P, []).area
    a1 = f2_naca.profile_polygon(P, [f]).area
    assert (a1 - a0) == pytest.approx(sign * f.w * f.h, rel=0.05)


def test_invalid_features_are_rejected():
    with pytest.raises(ValueError):
        f2_naca.profile_polygon(P, [_feat(wall="")])
    with pytest.raises(ValueError):
        f2_naca.profile_polygon(P, [_feat(s=0.03)])


def test_body_frame_undoes_angle_of_attack():
    up, lo = f2_naca.naca4(P.m, P.p, P.t, P.c, P.n_side)
    ref = np.vstack([up, lo])
    rotated = np.asarray(f2_naca.profile_polygon(P, []).exterior.coords)
    back = f2_naca.body_frame(rotated, P)
    assert np.allclose(back.min(axis=0), ref.min(axis=0), atol=1e-9)
    assert np.allclose(back.max(axis=0), ref.max(axis=0), atol=1e-9)


def test_slot_box_contains_largest_feature():
    f = Feature(kind="rib", s=P.slot_s * P.c, w=P.slot_w_max * P.c,
                h=P.slot_h_max * P.c, wall="upper")
    diff = f2_naca.profile_polygon(P, [f]).difference(f2_naca.profile_polygon(P, []))
    assert f2_naca.slot_box(P).buffer(1e-12).contains(diff)


def test_f2_trial_design_shares_mesh_settings():
    specs = sweep.design_f2_trial()
    roles = [s["role"] for s in specs]
    assert roles.count("without") == 1 and roles.count("base_coarse") == 1
    without = next(s for s in specs if s["role"] == "without")
    for s in specs:
        assert s["family"] == "F2"
        if s["role"] == "with":
            assert s["mesh"] == without["mesh"]
            assert s["features"][0]["wall"] == "upper"


def test_f2_case_build_fills_placeholders(tmp_path):
    spec = next(s for s in sweep.design_f2_trial() if s["role"] == "with")
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    rc.run_case(tmp_path, build_only=True)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert "{{" not in f.read_text(), f
    assert json.loads((tmp_path / "geometry.json").read_text())["family"] == "F2"
    ph = case_f2.placeholders(spec)
    assert ph["K_INF"] > 0 and ph["OMEGA_INF"] > 0
    assert ph["AREF"] == pytest.approx(P.c * spec["mesh"]["dz"] * P.c)


def test_first_cell_height_targets_yplus_one():
    from cfd.mesh_gmsh import first_cell_height
    y1 = first_cell_height(45.0, 1.5e-5, 0.1, 1.0)
    assert 3e-6 < y1 < 2e-5


def test_f2_wall_tables_pick_side_and_skip_stagnation(tmp_path):
    x = np.linspace(0, P.c, 21)
    df = pd.concat([pd.DataFrame({"x": x, "side": s, "p": 0.0, "tau_x": 1.0,
                                  "tau_y": 0.0, "area": 1.0}) for s in ("upper", "lower")])
    df.to_csv(tmp_path / "wall_profile.csv", index=False)
    spec = {"family": "F2", "params": {"c": P.c}}
    wall, all_walls, cap = build_dataset.wall_tables(tmp_path, spec, _feat(wall="lower"))
    assert set(wall.side) == {"lower"} and wall.x.min() >= 0.02 * P.c
    assert len(all_walls) == 2 and cap == pytest.approx(0.1 * P.c)


def _gmsh_available():
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


@pytest.mark.skipif(not _gmsh_available(), reason="gmsh not installed")
def test_coarse_meshes_share_the_outer_mesh(tmp_path):
    base = next(s for s in sweep.design_f2_trial() if s["role"] == "base_coarse")
    groove = dict(base, features=[_feat("groove", h=0.005).to_dict()])
    stats = []
    for name, spec in (("without", base), ("groove", groove)):
        (tmp_path / name).mkdir()
        stats.append(case_f2.mesh(tmp_path / name, spec))
        assert (tmp_path / name / case_f2.MSH).stat().st_size > 0
    assert 5_000 < stats[0]["cells"] < 60_000
    assert stats[0]["outer_key"] == stats[1]["outer_key"]
    assert stats[0]["cells_outer"] == stats[1]["cells_outer"]
    assert len(list((tmp_path / case_f2.OUTER_CACHE).glob("*.npz"))) == 1
