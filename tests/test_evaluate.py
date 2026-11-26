import numpy as np
import pandas as pd

from models import evaluate as ev


def _synthetic(tmp_path):
    rng = np.random.default_rng(0)
    for fam in ("F1", "F2", "F3", "F4"):
        n = 80
        d = pd.DataFrame({
            "feature_id": [f"{fam}_{i}" for i in range(n)],
            "base_id": [f"{fam.lower()}_b{i // 8:03d}" for i in range(n)],
            "family": fam, "kind": "rib",
            "category": rng.choice(["convex", "concave"], n),
            **{c: rng.random(n) for c in ev.GEO + ev.FLOW_ONLY if c not in ("is_convex", "has_sep")},
            "has_sep": rng.random(n) > 0.5,
            "excluded": None,
        })
        d["dQ_rel"] = 0.04 * d.h_plus * (d.category == "convex") - 0.005
        d["dNu_rel"] = np.nan if fam == "F3" else 0.03 * d.h_over_delta
        d.to_parquet(tmp_path / f"ds_{fam}.parquet")
    return [f"ds_{f}" for f in ("F1", "F2", "F3", "F4")]


def test_threshold_reaches_recall_target():
    y = np.array([1] * 40 + [0] * 60)
    s = np.r_[np.linspace(0.3, 1, 40), np.linspace(0, 0.5, 60)]
    t = ev.threshold_for_recall(s, y)
    assert np.mean(s[y == 1] >= t) >= ev.RECALL_TARGET
    assert not np.mean(s[y == 1] >= np.nextafter(t, 2)) >= ev.RECALL_TARGET


def test_metrics_count_wrong_removals():
    m = ev.metrics([1, 1, 0, 0], [True, False, False, True])
    assert m["recall"] == 0.5 and m["specificity"] == 0.5 and m["wrongly_removed"] == 1


def test_run_all_on_synthetic_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "GRID", ev.GRID[:1])
    monkeypatch.setattr(ev, "TAUS", (0.010,))
    monkeypatch.setattr(ev, "N_BOOT", 200)
    files = _synthetic(tmp_path)
    res = ev.run_all(tmp_path, tmp_path / "out", files)
    assert {"dp_tau010", "nu_tau010"} <= set(res)
    s = res["dp_tau010"]
    # the label depends on h_plus: the flow model must beat the geometry model
    assert s["spec_mean"]["M1_flow"] > s["spec_mean"]["M1_geo"]
    assert (tmp_path / "out" / "auswertung_dp_tau010.md").exists()
    # family is never an input
    assert "family" not in ev.FLOW and "kind" not in ev.FLOW
