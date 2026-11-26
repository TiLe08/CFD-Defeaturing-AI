import json

import numpy as np
import pandas as pd

from models import evaluate as ev
from models import llm


def _df(n=12):
    rng = np.random.default_rng(1)
    rows = []
    for fam in ("F1", "F2", "F3"):
        for i in range(n):
            r = {c: rng.random() for c in ev.FLOW}
            r.update(is_convex=i % 2, n_elem=1, has_sep=0, family=fam,
                     feature_id=f"{fam}_{i}", base_id=f"{fam}_b{i // 3}",
                     dQ_rel=0.05 if i % 2 else 0.001)
            rows.append(r)
    return pd.DataFrame(rows)


def test_parse_accepts_valid_and_rejects_invalid():
    assert llm.parse('{"decision": "Remove", "dq_estimate": "0.01", "reason": "x"}')["decision"] == "remove"
    assert np.isnan(llm.parse('{"decision": "keep", "dq_estimate": "big"}')["dq_estimate"])
    assert llm.parse("no json") is None
    assert llm.parse('{"decision": "maybe"}') is None


def test_prompt_has_no_family_or_kind_and_examples_only_from_other_families():
    df = _df()
    row = df.iloc[0]
    p = llm.build_prompt(row, None, 0.01)
    assert "F1" not in p and "family" not in p and "groove=" not in p
    train = df[df.family != row.family]
    nn = llm.nearest_examples(train, row)
    assert len(nn) == llm.K_SHOTS and set(df.loc[nn].family) <= {"F2", "F3"}


def test_run_with_fake_llm_uses_cache_and_counts_invalid(tmp_path):
    df = _df()
    calls = []

    def ask(prompt):
        calls.append(prompt)
        if len(calls) % 7 == 0:
            return "garbage"
        keep = "convex=1" in prompt.split("Now this feature:")[1]
        return json.dumps({"decision": "keep" if keep else "remove", "dq_estimate": 0.0})

    cache = llm.Cache(tmp_path / "c.jsonl")
    ans = llm.run_queries(df, ask, "fake", cache, log=lambda *a: None)
    n = len(df) * (1 + llm.N_REP)
    assert len(ans) == n and len(calls) == n
    # second run answers from the cache
    ans2 = llm.run_queries(df, ask, "fake", llm.Cache(tmp_path / "c.jsonl"), log=lambda *a: None)
    assert len(calls) == n and ans2.keep.tolist() == ans.keep.tolist()
    res = llm.evaluate_answers(df, ans)
    assert res.invalid.sum() == (~ans.valid).sum() > 0
    # invalid answers count as keep, so recall stays perfect for this rule
    assert (res.recall == 1).all()
    lofo = pd.DataFrame([{"fold": f, "model": m, "specificity": 0.4, "recall": 0.95}
                         for f in ("F1", "F2", "F3") for m in ("B1", "M1_flow")])
    text = llm.report(res, lofo, "fake", tmp_path)
    assert "H3" in text and (tmp_path / "auswertung_llm.md").exists()
