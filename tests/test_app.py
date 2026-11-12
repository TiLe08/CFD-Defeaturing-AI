"""Web API of the tool: load -> analyse -> decide -> export (no browser)."""
import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402
from models.baselines import b0_suggest  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def analysed(client):
    d = client.post("/api/demo").json()
    a = client.post("/api/analyse", json={"session": d["session"], "r_max": 4, "r_convex": 3.5,
                                          "s0": 0.02, "max_voxels": 5_000_000}).json()
    return d, a


def test_load_and_analyse(analysed):
    d, a = analysed
    assert d["unit"] == "mm" and d["mesh"]["n_faces"] > 100
    assert len(a["features"]) == 5
    assert a["params"]["r_max"] == pytest.approx(4)  # reported in the file's unit
    for f in a["features"]:
        assert f["suggestion"]["decision"] in ("remove", "keep", "unsure")
        assert f["kind_label"] in ("Vertiefung", "Vorsprung")


def test_export_zip_and_protocol(client, analysed):
    d, a = analysed
    dec = {str(f["id"]): "remove" for f in a["features"]}
    dec[str(a["features"][0]["id"])] = "keep"
    r = client.post("/api/export", json={"session": d["session"], "decisions": dec, "out_unit": "m"})
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = sorted(z.namelist())
    assert names == ["beispielplatte_defeatured.stl", "beispielplatte_defeaturing.json"]
    proto = json.loads(z.read("beispielplatte_defeaturing.json"))
    assert proto["schema"] == "fad-defeaturing/1"
    assert proto["counts"] == {**proto["counts"], "detected": 5, "removed": 4, "kept": 1, "failed": 0}
    assert proto["output"]["watertight"] is True
    assert proto["output"]["unit"] == "m"
    # STL really is in metres: plate is 0.1 m long
    import trimesh
    m = trimesh.load(io.BytesIO(z.read("beispielplatte_defeatured.stl")), file_type="stl")
    assert m.extents.max() == pytest.approx(0.1, rel=0.2)


def test_preview_matches_decision(client, analysed):
    d, a = analysed
    r = client.post("/api/preview", json={"session": d["session"], "decisions": {}}).json()
    assert r["watertight"] and r["mesh"]["n_faces"] == d["mesh"]["n_faces"]


def test_bad_file_gives_readable_error(client):
    r = client.post("/api/load", files={"file": ("x.stl", b"solid x\nendsolid x\n")}, data={"unit": "mm"})
    assert r.status_code == 400
    assert "Dreiecke" in r.json()["detail"] or "geschlossen" in r.json()["detail"]


def test_unknown_session(client):
    r = client.post("/api/analyse", json={"session": "nope"})
    assert r.status_code == 404


def test_b0_rule():
    feats = [{"id": 0, "h": 0.001}, {"id": 1, "h": 0.01}, {"id": 2, "h": 0.002}]
    s = b0_suggest(feats, l_ref=0.1, s0=0.02)
    assert [x["decision"] for x in s] == ["remove", "keep", "unsure"]
