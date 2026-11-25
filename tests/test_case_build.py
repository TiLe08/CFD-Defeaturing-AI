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
    # per base: without, base_coarse, 3 features; plus GCI (4 runs) on 2 bases
    assert len(a) == 4 * (2 + 3) + 2 * 4


def test_f1_design_respects_ranges_and_balance():
    specs = sweep.design_f1_lhs()
    feats = [s for s in specs if s["role"] == "with"]
    assert len(feats) == 30 * 8
    H = specs[0]["params"]["H"]
    lo, hi = sweep.F1_RANGES["h_over_H"]
    assert all(lo <= s["features"][0]["h"] / H <= hi for s in feats)
    kinds = [s["features"][0]["kind"] for s in feats]
    assert kinds.count("rib") == kinds.count("groove")
    re = [s["flow"]["Re"] for s in specs if s["role"] == "without"]
    assert min(re) >= 20 and max(re) <= 500


def test_thermal_template_renders_with_pr_from_spec():
    spec = _spec()
    vals = rc.placeholders(spec)
    assert vals["DT"] == pytest.approx(spec["flow"]["nu"] / rc.THERMAL_DEFAULTS["Pr"])
    tmpl = rc.TEMPLATES / spec["template"] / "thermal"
    for f in tmpl.rglob("*"):
        if f.is_file():
            assert "{{" not in rc.render(f.read_text(), vals), f
    spec["thermal"] = {"Pr": 7.0}
    assert rc.placeholders(spec)["DT"] == pytest.approx(spec["flow"]["nu"] / 7.0)


def test_solved_case_without_thermal_step_needs_run(tmp_path):
    spec = _spec()
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    old = [s for s in rc.STEPS if s != "scalarTransport"]
    rc.save_status(tmp_path, {"state": "solved", "done": old, "error": None, "times": {}})
    assert rc.needs_run(tmp_path)
    rc.save_status(tmp_path, {"state": "solved", "done": list(rc.STEPS), "error": None, "times": {}})
    assert not rc.needs_run(tmp_path)
    rc.save_status(tmp_path, {"state": "failed", "done": [], "error": "x", "times": {}})
    assert not rc.needs_run(tmp_path)


def test_port_case_is_turbulent_without_thermal_step(tmp_path):
    spec = next(s for s in sweep.design_f3_trial() if s["role"] == "with")
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    rc.run_case(tmp_path, build_only=True)
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.suffix != ".stl":
            assert "{{" not in f.read_text(), f
    assert "kOmegaSST" in (tmp_path / "constant/turbulenceProperties").read_text()
    assert "scalarTransport" not in rc.steps_for(spec)
    vals = rc.placeholders(spec)
    assert vals["K_IN"] > 0 and vals["OMEGA_IN"] > 0
    lay = rc.mesh_layout(spec)
    p = rc.family_params(spec)
    assert p.S * p.H < lay["LOC_Y"] < p.y_top  # snappy seed point in the feed channel


def test_failed_mesh_retries_with_shifted_feature(tmp_path, monkeypatch):
    spec = next(s for s in sweep.design_f3_lhs() if s["role"] == "with")
    case = tmp_path / spec["case_id"]
    case.mkdir()
    (case / "spec.json").write_text(json.dumps(spec))
    (case / "log.checkMesh").write_text("Failed 1 mesh checks.")
    calls = []
    monkeypatch.setattr(rc, "run_case", lambda c, *a, **k: calls.append(c) or {})
    assert rc._may_shift(spec)
    rc._retry_shifted(case, spec, None, True)
    new = json.loads((case / "spec.json").read_text())
    H = spec["params"]["H"]
    assert new["mesh_retry"]["k"] == 1
    assert new["features"][0]["s"] - spec["features"][0]["s"] == pytest.approx(H / 400)
    assert rc.planned_spec(new) == spec
    assert not (case / "log.checkMesh").exists() and calls == [case]
    # the sweep accepts the shifted spec as the planned one
    sweep.plan([spec], tmp_path)
    assert json.loads((case / "spec.json").read_text())["mesh_retry"]["k"] == 1
    # after the last shift no further retry
    new["mesh_retry"]["k"] = len(rc.MESH_SHIFTS)
    assert not rc._may_shift(new)
