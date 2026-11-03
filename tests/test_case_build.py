import json

import pytest

from cfd import run_case as rc
from pipeline import sweep


def _spec(role="with"):
    return next(s for s in sweep.design_ap2() if s["role"] == role)


def test_rendering_leaves_no_placeholders(tmp_path):
    spec = _spec()
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    rc.run_case(tmp_path, build_only=True)
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.suffix not in (".stl",):
            assert "{{" not in f.read_text(), f
    assert (tmp_path / "constant/triSurface/channel.stl").exists()
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "built"


def test_mesh_layout_identical_with_and_without_feature():
    lay_with = rc.mesh_layout(_spec("with"))
    lay_without = rc.mesh_layout(_spec("without"))
    assert lay_with == lay_without


def test_background_mesh_encloses_slot_and_keeps_walls_off_faces():
    spec = _spec("without")
    lay = rc.mesh_layout(spec)
    H = spec["params"]["H"]
    assert lay["Y0"] < -spec["params"]["slot_h_max"] * H
    d = lay["_d"]
    for y in (0.0, H):  # walls must not coincide with background faces
        frac = ((y - lay["Y0"]) / d) % 1
        assert 0.05 < frac < 0.95


def test_fix_2d_sets_empty(tmp_path):
    poly = tmp_path / "constant/polyMesh"
    poly.mkdir(parents=True)
    (poly / "boundary").write_text(
        "FoamFile{}\n2\n(\n    front\n    {\n        type patch;\n        nFaces 4;\n"
        "        startFace 0;\n    }\n    back\n    {\n        type patch;\n"
        "        inGroups 1(patch);\n        nFaces 4;\n        startFace 4;\n    }\n)\n")
    (poly / "cellLevel").write_text("x")
    rc.fix_2d(tmp_path)
    txt = (poly / "boundary").read_text()
    assert txt.count("type empty;") == 2
    assert "inGroups 1(empty);" in txt
    assert not (poly / "cellLevel").exists()


def test_plan_refuses_to_overwrite_changed_spec(tmp_path):
    specs = sweep.design_ap2()
    sweep.plan(specs, tmp_path)
    specs[0]["flow"]["U"] *= 2
    with pytest.raises(RuntimeError):
        sweep.plan(specs, tmp_path)


def test_lhs_design_is_reproducible():
    a = sweep.design_f1_lhs(4, 3, seed=1)
    b = sweep.design_f1_lhs(4, 3, seed=1)
    assert a == b
    assert len(a) == 4 * (2 + 3)
