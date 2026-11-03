import numpy as np
import pytest
import trimesh

from geometry.features import Feature
from geometry.families import f1_channel as f1

P = f1.F1Params()
H = P.H


def _closed(regions):
    m = trimesh.util.concatenate(list(regions.values()))
    m.merge_vertices()
    return m


@pytest.mark.parametrize("kind,sign", [("groove", +1), ("rib", -1)])
def test_feature_changes_area_by_w_times_h(kind, sign):
    base = f1.make_polygon(P, [])
    f = Feature(kind, P.s_slot, 0.5 * H, 0.2 * H)
    g = f1.make_polygon(P, [f])
    assert g.polygon.area - base.polygon.area == pytest.approx(sign * f.w * f.h, rel=1e-9)
    # wetted length grows by both flanks
    assert f1.wetted_length(g) - f1.wetted_length(base) == pytest.approx(2 * f.h, rel=1e-9)


@pytest.mark.parametrize("feats", [[], [Feature("groove", P.s_slot, H, 0.3 * H)],
                                   [Feature("rib", P.s_slot, 0.2 * H, 0.1 * H)]])
def test_extruded_surface_is_watertight_and_labelled(feats):
    g = f1.make_polygon(P, feats)
    regions = f1.extrude(g, -1e-4, 2e-4)
    assert set(regions) == {"inlet", "outlet", "topWall", "bottomWall", "sides"}
    m = _closed(regions)
    assert m.is_watertight
    assert m.volume == pytest.approx(g.polygon.area * 3e-4, rel=1e-9)
    # inlet and outlet are exactly the channel cross section
    assert regions["inlet"].area == pytest.approx(H * 3e-4, rel=1e-9)
    assert regions["outlet"].area == pytest.approx(H * 3e-4, rel=1e-9)


def test_multisolid_stl_names():
    regions = f1.extrude(f1.make_polygon(P, []), 0, 1e-4)
    txt = f1.to_multisolid_stl(regions)
    solids = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("solid")]
    assert solids == list(regions)


def test_invalid_features_rejected():
    with pytest.raises(ValueError):
        f1.make_polygon(P, [Feature("rib", P.s_slot, 0.5 * H, 1.2 * H)])
    with pytest.raises(ValueError):
        Feature("hole", 0.0, 1.0, 1.0)
