"""STL export of the electrolyzer models (no OpenFOAM needed)."""
import pandas as pd
import pytest
import trimesh

from geometry.families import f1_channel
from geometry.features import Feature
from pipeline import export_models as em

P = f1_channel.F1Params()
H = P.H


@pytest.mark.parametrize("kind,sign", [("groove", -1), ("rib", 1)])
def test_plate_volume_changes_by_feature(kind, sign):
    f = Feature(kind=kind, s=P.s_slot, w=H, h=0.3 * H)
    v0 = em.f1_plate(P, []).volume
    v1 = em.f1_plate(P, [f]).volume
    w_ch = em.f1_dims(P)["w_ch"]
    assert v1 - v0 == pytest.approx(sign * f.w * f.h * w_ch, rel=1e-6)


def test_export_writes_watertight_models_and_table(tmp_path, monkeypatch):
    few = list(em.models("ap2"))[:3]
    monkeypatch.setattr(em, "models", lambda design: iter(few))
    df = em.export(["F1"], tmp_path, designs={"F1": "ap2"})
    assert len(df) == 3 and (tmp_path / "LIESMICH.md").exists()
    for rel in pd.concat([df.stl_platte, df.stl_fluid]):
        m = trimesh.load(tmp_path / rel)
        assert m.is_watertight
        assert m.bounds[1][0] == pytest.approx(P.L * em.MM, rel=1e-6)


@pytest.mark.parametrize("kind,sign", [("groove", -1), ("rib", 1)])
def test_manifold_plate_volume_changes_by_feature(kind, sign):
    from geometry.families import f2_manifold
    p = f2_manifold.F2Params()
    f = Feature(kind=kind, s=p.s_slot, w=0.5 * p.H, h=0.3 * p.H)
    v0, v1 = em.f2_plate(p, []).volume, em.f2_plate(p, [f]).volume
    assert v1 - v0 == pytest.approx(sign * f.w * f.h * em.f2_dims(p)["depth"], rel=1e-6)
    assert em.f2_fluid(p, [f]).is_watertight
