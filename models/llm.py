"""L0 (zero-shot) and L1 (few-shot) with a local LLM via Ollama (HANDOFF 3.9).

The LLM gets the same descriptors as M1_flow as text (never the family or
the feature type) and answers with JSON
    {"decision": "keep" | "remove", "dq_estimate": <float>, "reason": "..."}.

- Temperature 0, fixed seed.
- L1: the k = 5 nearest training examples (standardized D_flow space, scaler
  fitted on the training families only) with their true effect. Three
  repetitions per feature with permuted example order; the decision is the
  majority of the three.
- LOFO as for M1: examples only from the other families.
- Invalid answers are counted and treated as "keep".
- Every answer is cached in a JSONL file, so an interrupted run continues
  where it stopped.

Usage:
    python -m models.llm --data data/processed --out results/ap6_llm --model qwen2.5:7b
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from models import evaluate as ev

DEFAULT_MODEL = "qwen2.5:7b"
K_SHOTS = 5
N_REP = 3
TAU = 0.010
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

SYSTEM = """You are an expert in computational fluid dynamics (CFD).
A small geometric feature (a groove or a rib-like bump) sits on a wall of a flow domain.
Before meshing, an engineer wants to know whether the feature may be removed from the
geometry ("defeaturing") without changing the target quantity, the pressure loss of the
domain, by more than {tau_pct} % (relative change |dQ_rel| > {tau}).
Removing a feature that matters is much worse than keeping one that does not:
if in doubt, keep it.

All descriptors are dimensionless and come from a CFD run of the geometry without the feature:
- convex: 1 = protrudes into the flow (rib, bump), 0 = recessed (groove)
- h_over_L, w_over_L, h_over_w: height, width and aspect ratio, L = reference length
  (channel height or chord)
- area_frac: footprint width / total wetted wall length
- fill_factor: cross-section area / (w * h); n_elem: number of separate parts
- orient_deg: angle between the feature's long axis and the flow direction
- Re: Reynolds number of the flow; Re_h: local Reynolds number with the feature height
- h_plus: feature height in wall units (h * u_tau / nu); hydraulically smooth below about 5
- h_over_delta: height / local boundary-layer thickness
- cp_local: local pressure coefficient; dpds_nd: dimensionless wall pressure gradient
- force_frac: share of the feature footprint in the total wall friction force
- dist_sep_nd: distance to the nearest separation or reattachment point / L
  (100 = no separation in the domain); has_sep: 1 if the flow separates somewhere

Answer only with JSON: {{"decision": "keep" or "remove", "dq_estimate": <relative change of
the pressure loss caused by the feature, e.g. 0.02 for +2 %>, "reason": "<one sentence>"}}"""

INPUTS = ["is_convex", "h_over_L", "w_over_L", "h_over_w", "area_frac", "fill_factor",
          "n_elem", "orient_deg", "Re", "Re_h", "h_plus", "h_over_delta", "cp_local",
          "dpds_nd", "force_frac", "dist_sep_nd", "has_sep"]


def describe(row: pd.Series) -> str:
    parts = []
    for c in INPUTS:
        name = "convex" if c == "is_convex" else c
        v = row[c]
        parts.append(f"{name}={int(v)}" if c in ("is_convex", "n_elem", "has_sep")
                     else f"{name}={v:.4g}")
    return ", ".join(parts)


def example_text(row: pd.Series, tau: float) -> str:
    dec = "keep" if abs(row.dQ_rel) > tau else "remove"
    return (f"Feature: {describe(row)}\nAnswer: "
            + json.dumps({"decision": dec, "dq_estimate": round(float(row.dQ_rel), 5),
                          "reason": "measured in CFD"}))


def build_prompt(row: pd.Series, examples: list[pd.Series] | None, tau: float) -> str:
    sys = SYSTEM.format(tau=tau, tau_pct=f"{100 * tau:g}")
    shots = ""
    if examples:
        shots = ("\n\nSolved examples from other geometries (measured in CFD):\n\n"
                 + "\n\n".join(example_text(e, tau) for e in examples))
    return f"{sys}{shots}\n\nNow this feature:\nFeature: {describe(row)}\nAnswer:"


def parse(text: str) -> dict | None:
    """Decision and estimate from the answer, None if invalid."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        d = json.loads(text[start:end])
        dec = str(d.get("decision", "")).strip().lower()
        if dec not in ("keep", "remove"):
            return None
        try:
            est = float(d.get("dq_estimate"))
        except (TypeError, ValueError):
            est = np.nan
        return {"decision": dec, "dq_estimate": est, "reason": str(d.get("reason", ""))[:300]}
    except (ValueError, TypeError, AttributeError):
        return None


def ollama_ask(prompt: str, model: str, url: str = OLLAMA_URL, timeout: float = 300) -> str:
    req = {"model": model, "prompt": prompt, "stream": False, "format": "json",
           "options": {"temperature": 0, "seed": ev.SEED, "num_predict": 200, "num_ctx": 4096}}
    if model.startswith(("qwen3", "deepseek-r1")):
        req["think"] = False  # reasoning models: no long thinking phase
    body = json.dumps(req).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


def nearest_examples(train: pd.DataFrame, row: pd.Series, k: int = K_SHOTS) -> list[int]:
    """Indices of the k nearest training rows in standardized D_flow space."""
    X = train[ev.FLOW].to_numpy(float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    d = np.linalg.norm((X - mu) / sd - (row[ev.FLOW].to_numpy(float) - mu) / sd, axis=1)
    return list(train.index[np.argsort(d, kind="stable")[:k]])


class Cache:
    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.data[r["key"]] = r

    def get(self, key):
        return self.data.get(key)

    def put(self, rec):
        self.data[rec["key"]] = rec
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")


def run_queries(df: pd.DataFrame, ask, model: str, cache: Cache, tau: float = TAU,
                log=print) -> pd.DataFrame:
    """All L0 and L1 queries (LOFO). ask(prompt) -> answer text."""
    rng = np.random.default_rng(ev.SEED)
    jobs = []
    for f in sorted(df.family.unique()):
        train = df[df.family != f]
        for i, row in df[df.family == f].iterrows():
            jobs.append(("L0", 0, i, None))
            nn = nearest_examples(train, row)
            for rep in range(N_REP):
                order = list(rng.permutation(nn)) if rep else nn
                jobs.append(("L1", rep, i, order))
    n_todo = sum(cache.get(f"{model}|{v}|{df.feature_id[i]}|{r}") is None for v, r, i, _ in jobs)
    log(f"{len(jobs)} Abfragen, davon {n_todo} noch offen")
    t0, done = time.time(), 0
    out = []
    for variant, rep, i, order in jobs:
        row = df.loc[i]
        key = f"{model}|{variant}|{row.feature_id}|{rep}"
        rec = cache.get(key)
        if rec is None:
            prompt = build_prompt(row, [df.loc[j] for j in order] if order else None, tau)
            try:
                text = ask(prompt)
            except Exception as exc:  # noqa: BLE001 - counted as invalid
                text = f"ERROR {exc}"
            rec = {"key": key, "answer": text}
            cache.put(rec)
            done += 1
            if done % 50 == 0:
                eta = (time.time() - t0) / done * (n_todo - done) / 60
                log(f"  {done}/{n_todo} neu, noch etwa {eta:.0f} min")
        p = parse(rec["answer"])
        out.append({"variant": variant, "rep": rep, "feature_id": row.feature_id,
                    "family": row.family, "base_id": row.base_id, "valid": p is not None,
                    "keep": True if p is None else p["decision"] == "keep",
                    "dq_estimate": np.nan if p is None else p["dq_estimate"]})
    return pd.DataFrame(out)


def evaluate_answers(df: pd.DataFrame, ans: pd.DataFrame, tau: float = TAU) -> pd.DataFrame:
    y = (df.set_index("feature_id").dQ_rel.abs() > tau).astype(int)
    rows = []
    l1 = ans[ans.variant == "L1"]
    majority = (l1.groupby("feature_id").keep.mean() >= 0.5)
    for f in sorted(df.family.unique()):
        ids = df.feature_id[df.family == f]
        a0 = ans[(ans.variant == "L0")].set_index("feature_id").loc[ids]
        rows.append({"model": "L0", "fold": f, "invalid": int((~a0.valid).sum()),
                     **ev.metrics(y[ids], a0.keep)})
        rows.append({"model": "L1", "fold": f,
                     "invalid": int((~l1[l1.feature_id.isin(ids)].valid).sum()),
                     **ev.metrics(y[ids], majority[ids])})
        reps = [ev.metrics(y[ids], l1[l1.rep == r].set_index("feature_id").loc[ids].keep)
                for r in range(N_REP)]
        spec = [r["specificity"] for r in reps]
        rows[-1]["spec_rep_min"], rows[-1]["spec_rep_max"] = min(spec), max(spec)
        agree = l1[l1.feature_id.isin(ids)].groupby("feature_id").keep.nunique().eq(1).mean()
        rows[-1]["agreement_reps"] = agree
    return pd.DataFrame(rows)


def report(res: pd.DataFrame, lofo: pd.DataFrame, model: str, out: Path) -> str:
    spec = res.pivot(index="fold", columns="model", values="specificity")
    rec = res.pivot(index="fold", columns="model", values="recall")
    ref = lofo.pivot(index="fold", columns="model", values="specificity")
    refr = lofo.pivot(index="fold", columns="model", values="recall")
    L = [f"# Auswertung LLM ({model}), Druckverlust, τ = 1 %", "",
         "LOFO, Spezifität (Recall). B1 und M1_flow aus `models/evaluate.py` zum Vergleich.", "",
         "| Testfamilie | B1 | M1_flow | L0 | L1 | ungültig L0/L1 | Übereinstimmung L1-Wdh. |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for f in spec.index:
        r0 = res[(res.fold == f) & (res.model == "L0")].iloc[0]
        r1 = res[(res.fold == f) & (res.model == "L1")].iloc[0]
        L.append(f"| {f} | {ref.loc[f, 'B1']:.0%} ({refr.loc[f, 'B1']:.0%}) | "
                 f"{ref.loc[f, 'M1_flow']:.0%} ({refr.loc[f, 'M1_flow']:.0%}) | "
                 f"{spec.loc[f, 'L0']:.0%} ({rec.loc[f, 'L0']:.0%}) | "
                 f"{spec.loc[f, 'L1']:.0%} ({rec.loc[f, 'L1']:.0%}) | "
                 f"{r0.invalid}/{r1.invalid} | {r1.agreement_reps:.0%} |")
    m = {k: spec[k].mean() for k in ("L0", "L1")}
    b1, m1 = ref["B1"].mean(), ref["M1_flow"].mean()
    L.append(f"| Mittel | {b1:.0%} | {m1:.0%} | {m['L0']:.0%} ({rec['L0'].mean():.0%}) | "
             f"{m['L1']:.0%} ({rec['L1'].mean():.0%}) | | |")
    h3a = abs(m["L0"] - b1) <= 0.05
    gap = m1 - m["L0"]
    h3b = gap > 0 and (m["L1"] - m["L0"]) >= 0.5 * gap
    L += ["", "## H3", "",
          f"- L0 − B1 = {100 * (m['L0'] - b1):+.0f} pp (Kriterium ±5 pp): {'ja' if h3a else 'nein'}",
          f"- L1 schließt {100 * (m['L1'] - m['L0']) / gap:.0f} % des Abstands L0 → M1_flow "
          f"(Kriterium ≥ 50 %): {'ja' if h3b else 'nein'}" if gap > 0 else
          "- L0 liegt bereits auf oder über M1_flow, Kriterium nicht anwendbar.",
          f"- H3 bestätigt: {'ja' if h3a and h3b else 'nein'}", ""]
    text = "\n".join(L) + "\n"
    (out / "auswertung_llm.md").write_text(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("results") / "ap6_llm")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--url", default=OLLAMA_URL)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    df = ev.load(a.data)
    cache = Cache(a.out / f"antworten_{a.model.replace(':', '_').replace('/', '_')}.jsonl")
    ans = run_queries(df, lambda p: ollama_ask(p, a.model, a.url), a.model, cache)
    ans.to_csv(a.out / "antworten.csv", index=False)
    res = evaluate_answers(df, ans)
    res.to_csv(a.out / "metriken_llm.csv", index=False)
    lofo, _ = ev.run_lofo(df, "dp", TAU)
    print(report(res, lofo, a.model, a.out))


if __name__ == "__main__":
    main()
