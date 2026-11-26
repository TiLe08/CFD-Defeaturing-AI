"""Evaluation of B0, B1, M1_geo and M1_flow (HANDOFF 2, 3.3, 3.9, 3.10).

The procedure is fixed in docs/auswertungsprotokoll.md and must not be
tuned on the test folds. In short:

- Leave-one-family-out (LOFO): train on all families but one, test on it.
- Decision threshold chosen on the training families only, so that the
  recall of "relevant" there is at least 0.95. Reported on the test fold:
  recall (safety) and specificity (share of irrelevant features removed).
- B0: relevant if h/L >= s0. B1: relevant if h+ >= s1. Both thresholds
  fitted on the training families (the rule's only parameter).
- M1: gradient boosting (scikit-learn). Hyperparameters and the threshold
  from an inner LOFO over the training families (out-of-fold scores).
- In-distribution reference for H2: pooled data, 5 folds grouped by base
  configuration. Gap = in-distribution specificity - LOFO specificity.
- Cluster bootstrap over base configurations for M1_flow - B1.
- Grouped permutation importance (geometry vs. flow) on the test folds.

The family is never a model input.

Usage:
    python -m models.evaluate --data /path/to/datensaetze --out results/ap6
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold

SEED = 20261126
RECALL_TARGET = 0.95
TAUS = (0.005, 0.010, 0.020)
N_BOOT = 2000

GEO = ["is_convex", "h_over_L", "w_over_L", "h_over_w", "area_frac", "fill_factor",
       "n_elem", "orient_deg", "Re"]
FLOW_ONLY = ["h_plus", "h_over_delta", "cp_local", "dpds_nd", "force_frac",
             "dist_sep_nd", "has_sep", "Re_h"]
FLOW = GEO + FLOW_ONLY
GRID = [{"max_depth": d, "learning_rate": lr, "max_iter": 300, "min_samples_leaf": 10}
        for d, lr in itertools.product((2, 3), (0.05, 0.1))]

DEFAULT_FILES = ("dataset_f1_alle", "dataset_f2_alle", "dataset_f3", "dataset_f4")


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def load(data_dir: Path, files=DEFAULT_FILES) -> pd.DataFrame:
    """All valid features of all families, one row per feature."""
    frames = [pd.read_parquet(Path(data_dir) / f"{f}.parquet") for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = df[df.excluded.isna()].copy()
    df["is_convex"] = (df.category == "convex").astype(int)
    df["has_sep"] = df.has_sep.astype(int)
    return df.reset_index(drop=True)


def label(df: pd.DataFrame, target: str = "dp", tau: float = 0.010) -> pd.Series:
    col = "dQ_rel" if target == "dp" else "dNu_rel"
    return (df[col].abs() > tau).astype(int)


# --------------------------------------------------------------------------
# Thresholds and metrics
# --------------------------------------------------------------------------

def threshold_for_recall(score, y, target: float = RECALL_TARGET) -> float:
    """Largest t with recall(score >= t) >= target on (score, y)."""
    score, y = np.asarray(score, float), np.asarray(y, int)
    pos = np.sort(score[y == 1])
    if len(pos) == 0:
        return -np.inf
    k = int(np.floor((1.0 - target) * len(pos) + 1e-9))  # positives allowed below t
    return float(pos[k])


def metrics(y, keep) -> dict:
    """keep = predicted relevant (feature is kept). Removal of a relevant
    feature is the critical error."""
    y, keep = np.asarray(y, int), np.asarray(keep, bool)
    tp = int(np.sum(keep & (y == 1)))
    fn = int(np.sum(~keep & (y == 1)))
    tn = int(np.sum(~keep & (y == 0)))
    fp = int(np.sum(keep & (y == 0)))
    rec = tp / (tp + fn) if tp + fn else np.nan
    spec = tn / (tn + fp) if tn + fp else np.nan
    prec = tp / (tp + fp) if tp + fp else np.nan
    f1 = 2 * prec * rec / (prec + rec) if tp else 0.0
    removed = tn + fn
    return {"n": len(y), "n_rel": tp + fn, "recall": rec, "specificity": spec, "f1": f1,
            "accuracy": (tp + tn) / len(y), "n_removed": removed,
            "wrongly_removed": fn, "wrong_share_removed": fn / removed if removed else np.nan}


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def _clf(params):
    return HistGradientBoostingClassifier(random_state=SEED, **params)


def _oof_scores(X, y, groups, params) -> np.ndarray:
    """Out-of-fold probabilities, one fold per group (inner LOFO) or per
    GroupKFold split when groups are base ids."""
    out = np.full(len(y), np.nan)
    ug = np.unique(groups)
    splits = ([(groups != g, groups == g) for g in ug] if len(ug) <= 4 else
              [(np.isin(np.arange(len(y)), tr), np.isin(np.arange(len(y)), te))
               for tr, te in GroupKFold(n_splits=3).split(X, y, groups)])
    for tr, te in splits:
        if len(np.unique(y[tr])) < 2:
            out[te] = y[tr].mean()
            continue
        out[te] = _clf(params).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return out


def fit_m1(X, y, groups):
    """Hyperparameters by inner CV (average precision), threshold from the
    out-of-fold scores of the chosen setting, final model on all data."""
    best, best_ap, best_oof = None, -1.0, None
    for params in GRID:
        oof = _oof_scores(X, y, groups, params)
        ap = average_precision_score(y, oof)
        if ap > best_ap:
            best, best_ap, best_oof = params, ap, oof
    model = _clf(best).fit(X, y)
    return model, threshold_for_recall(best_oof, y), best


def evaluate_split(df, y, train, test, inner_groups, rng) -> tuple[list, dict]:
    """All models on one split. Returns metric rows and per-feature decisions."""
    rows, keep = [], {}
    ytr, yte = y[train], y[test]
    for name, col in (("B0", "h_over_L"), ("B1", "h_plus")):
        t = threshold_for_recall(df.loc[train, col], ytr)
        keep[name] = df.loc[test, col].to_numpy() >= t
        rows.append({"model": name, "threshold": t, **metrics(yte, keep[name])})
    importance = {}
    for name, cols in (("M1_geo", GEO), ("M1_flow", FLOW)):
        Xtr, Xte = df.loc[train, cols].to_numpy(float), df.loc[test, cols].to_numpy(float)
        model, t, params = fit_m1(Xtr, ytr, inner_groups)
        p = model.predict_proba(Xte)[:, 1]
        keep[name] = p >= t
        rows.append({"model": name, "threshold": t, "params": json.dumps(params),
                     "ap_test": average_precision_score(yte, p) if yte.any() else np.nan,
                     **metrics(yte, keep[name])})
        if name == "M1_flow" and yte.any() and not yte.all():
            importance = grouped_importance(model, Xte, yte, cols, rng)
    return rows, {"keep": keep, "importance": importance}


def grouped_importance(model, X, y, cols, rng, n_rep: int = 20) -> dict:
    """Drop in average precision when a whole group of columns is permuted."""
    base = average_precision_score(y, model.predict_proba(X)[:, 1])
    out = {}
    for gname, gcols in (("Geometrie", GEO), ("Strömung", FLOW_ONLY)):
        idx = [cols.index(c) for c in gcols]
        drops = []
        for _ in range(n_rep):
            Xp = X.copy()
            perm = rng.permutation(len(X))
            Xp[:, idx] = X[perm][:, idx]
            drops.append(base - average_precision_score(y, model.predict_proba(Xp)[:, 1]))
        out[gname] = float(np.mean(drops))
    return out


def cluster_bootstrap(y, keep_a, keep_b, bases, rng, n: int | None = None) -> tuple[float, float]:
    """95 % interval of specificity(a) - specificity(b), resampling base configurations."""
    y, bases = np.asarray(y), np.asarray(bases)
    n = n or N_BOOT
    ub = np.unique(bases)
    idx_of = {b: np.flatnonzero(bases == b) for b in ub}
    diffs = []
    for _ in range(n):
        idx = np.concatenate([idx_of[b] for b in rng.choice(ub, len(ub))])
        neg = y[idx] == 0
        if not neg.any():
            continue
        diffs.append(np.mean(~keep_a[idx][neg]) - np.mean(~keep_b[idx][neg]))
    return tuple(np.percentile(diffs, [2.5, 97.5]))


def regression_mae(df, train, test, cols, target_col) -> float:
    m = HistGradientBoostingRegressor(random_state=SEED, max_depth=3, learning_rate=0.05,
                                      max_iter=300, min_samples_leaf=10)
    m.fit(df.loc[train, cols].to_numpy(float), df.loc[train, target_col].to_numpy(float))
    pred = m.predict(df.loc[test, cols].to_numpy(float))
    return float(np.mean(np.abs(pred - df.loc[test, target_col].to_numpy(float))))


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

def run_lofo(df, target="dp", tau=0.010) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    y = label(df, target, tau).to_numpy()
    fam = df.family.to_numpy()
    tcol = "dQ_rel" if target == "dp" else "dNu_rel"
    rows, extra = [], []
    for f in sorted(np.unique(fam)):
        train, test = fam != f, fam == f
        r, info = evaluate_split(df, y, train, test, fam[train], rng)
        lo, hi = cluster_bootstrap(y[test], info["keep"]["M1_flow"], info["keep"]["B1"],
                                   df.base_id[test], rng)
        for row in r:
            row.update(fold=f, scheme="LOFO")
            if row["model"].startswith("M1"):
                cols = GEO if row["model"] == "M1_geo" else FLOW
                row["mae_dq"] = regression_mae(df, train, test, cols, tcol)
        rows += r
        extra.append({"fold": f, "spec_diff_M1flow_B1_ci_lo": lo, "spec_diff_M1flow_B1_ci_hi": hi,
                      **{f"perm_{k}": v for k, v in info["importance"].items()}})
    return pd.DataFrame(rows), pd.DataFrame(extra)


def run_in_distribution(df, target="dp", tau=0.010, n_splits: int = 5) -> pd.DataFrame:
    """Pooled data, folds grouped by base configuration; metrics per family."""
    rng = np.random.default_rng(SEED + 1)
    y = label(df, target, tau).to_numpy()
    bases = df.base_id.to_numpy()
    keep = {m: np.zeros(len(df), bool) for m in ("B0", "B1", "M1_geo", "M1_flow")}
    gkf = GroupKFold(n_splits=n_splits)
    for tr, te in gkf.split(df, y, bases):
        train = np.isin(np.arange(len(df)), tr)
        test = ~train
        _, info = evaluate_split(df, y, train, test, bases[train], rng)
        for m in keep:
            keep[m][test] = info["keep"][m]
    rows = []
    for f in sorted(df.family.unique()):
        sel = (df.family == f).to_numpy()
        for m in keep:
            rows.append({"model": m, "fold": f, "scheme": "in-distribution",
                         **metrics(y[sel], keep[m][sel])})
    return pd.DataFrame(rows)


def summarize(lofo: pd.DataFrame, ind: pd.DataFrame, extra: pd.DataFrame) -> dict:
    piv = lofo.pivot(index="fold", columns="model", values="specificity")
    rec = lofo.pivot(index="fold", columns="model", values="recall")
    ind_spec = ind.pivot(index="fold", columns="model", values="specificity")
    gap = (ind_spec - piv).mean()
    h1_diff = (piv["M1_flow"] - piv["B1"])
    return {
        "spec_mean": piv.mean().to_dict(),
        "recall_mean": rec.mean().to_dict(),
        "gap_mean": gap.to_dict(),
        "H1": {"diff_mean_pp": 100 * h1_diff.mean(), "folds_better": int((h1_diff > 0).sum()),
               "recall_not_worse": bool(rec["M1_flow"].mean() >= rec["B1"].mean()),
               "confirmed": bool(100 * h1_diff.mean() >= 10 and (h1_diff > 0).sum() >= 3
                                 and rec["M1_flow"].mean() >= rec["B1"].mean())},
        "H2": {"gap_flow": gap.get("M1_flow"), "gap_geo": gap.get("M1_geo"),
               "confirmed": bool(gap.get("M1_flow") <= 0.5 * gap.get("M1_geo"))
               if gap.get("M1_geo", 0) > 0 else None},
    }


def _fmt(v, pct=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{100 * v:.0f} %" if pct else f"{v:.3g}"


def write_report(out: Path, target: str, tau: float, lofo, ind, extra, summ, n_by_fam) -> str:
    title = "Druckverlust" if target == "dp" else "Nusselt-Zahl"
    L = [f"# Auswertung {title}, τ = {tau:.1%}".replace(".", ","), "",
         "Verfahren nach docs/auswertungsprotokoll.md. Schwelle auf den Trainingsfamilien "
         f"für Recall ≥ {RECALL_TARGET:.2f}.".replace("0.95", "0,95"), "",
         "| Familie | n | relevant |", "| --- | --- | --- |"]
    for f, (n, r) in n_by_fam.items():
        L.append(f"| {f} | {n} | {r} ({r / n:.0%}) |")
    L += ["", "## LOFO: Spezifität (Recall) je Testfamilie", "",
          "| Testfamilie | B0 | B1 | M1_geo | M1_flow |", "| --- | --- | --- | --- | --- |"]
    for f, g in lofo.groupby("fold"):
        g = g.set_index("model")
        L.append(f"| {f} | " + " | ".join(
            f"{_fmt(g.loc[m, 'specificity'])} ({_fmt(g.loc[m, 'recall'])})"
            for m in ("B0", "B1", "M1_geo", "M1_flow")) + " |")
    L.append("| Mittel | " + " | ".join(
        f"{_fmt(summ['spec_mean'][m])} ({_fmt(summ['recall_mean'][m])})"
        for m in ("B0", "B1", "M1_geo", "M1_flow")) + " |")
    L += ["", "## Innerhalb der Familien (gruppiert nach Basis) und Generalisierungslücke", "",
          "| Familie | B0 | B1 | M1_geo | M1_flow |", "| --- | --- | --- | --- | --- |"]
    for f, g in ind.groupby("fold"):
        g = g.set_index("model")
        L.append(f"| {f} | " + " | ".join(
            f"{_fmt(g.loc[m, 'specificity'])} ({_fmt(g.loc[m, 'recall'])})"
            for m in ("B0", "B1", "M1_geo", "M1_flow")) + " |")
    L.append("| Lücke (Mittel) | " + " | ".join(
        f"{100 * summ['gap_mean'][m]:+.0f} pp" for m in ("B0", "B1", "M1_geo", "M1_flow")) + " |")
    L += ["", "## Hypothesen", "",
          f"- H1: M1_flow − B1 = {summ['H1']['diff_mean_pp']:+.1f} pp Spezifität im Mittel, "
          f"besser in {summ['H1']['folds_better']} von {lofo.fold.nunique()} Folds, Recall nicht schlechter: "
          f"{'ja' if summ['H1']['recall_not_worse'] else 'nein'}. "
          f"Kriterium erfüllt: {'ja' if summ['H1']['confirmed'] else 'nein'}.",
          f"- H2: Lücke M1_flow {100 * summ['H2']['gap_flow']:+.0f} pp, M1_geo "
          f"{100 * summ['H2']['gap_geo']:+.0f} pp. Kriterium (flow ≤ halbe geo-Lücke) erfüllt: "
          f"{ {True: 'ja', False: 'nein', None: 'nicht anwendbar (geo-Lücke ≤ 0)'}[summ['H2']['confirmed']] }.",
          "", "## Bootstrap und Permutation Importance (M1_flow, Testfamilie)", "",
          "| Testfamilie | 95 %-KI Spezifität M1_flow − B1 | Abfall AP Geometrie | Abfall AP Strömung |",
          "| --- | --- | --- | --- |"]
    for _, r in extra.iterrows():
        L.append(f"| {r.fold} | {100 * r.spec_diff_M1flow_B1_ci_lo:+.0f} bis "
                 f"{100 * r.spec_diff_M1flow_B1_ci_hi:+.0f} pp | "
                 f"{r.get('perm_Geometrie', np.nan):.3f} | {r.get('perm_Strömung', np.nan):.3f} |")
    m1 = lofo[lofo.model.str.startswith("M1")]
    L += ["", "## Regression (MAE von ΔQ_rel, LOFO)", "",
          "| Testfamilie | M1_geo | M1_flow |", "| --- | --- | --- |"]
    for f, g in m1.groupby("fold"):
        g = g.set_index("model")
        L.append(f"| {f} | {g.loc['M1_geo', 'mae_dq']:.4f} | {g.loc['M1_flow', 'mae_dq']:.4f} |")
    text = "\n".join(L) + "\n"
    (out / f"auswertung_{target}_tau{tau * 1000:03.0f}.md").write_text(text)
    return text


def run_all(data_dir: Path, out: Path, files=DEFAULT_FILES) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df = load(data_dir, files)
    results = {}
    for target in ("dp", "nu"):
        d = df if target == "dp" else df[df.dNu_rel.notna()].reset_index(drop=True)
        if d.family.nunique() < 3:
            continue
        for tau in TAUS:
            y = label(d, target, tau)
            n_by_fam = {f: (int((d.family == f).sum()), int(y[d.family == f].sum()))
                        for f in sorted(d.family.unique())}
            lofo, extra = run_lofo(d, target, tau)
            ind = run_in_distribution(d, target, tau)
            summ = summarize(lofo, ind, extra)
            tag = f"{target}_tau{tau * 1000:03.0f}"
            pd.concat([lofo, ind]).to_csv(out / f"metriken_{tag}.csv", index=False)
            extra.to_csv(out / f"bootstrap_importance_{tag}.csv", index=False)
            write_report(out, target, tau, lofo, ind, extra, summ, n_by_fam)
            results[tag] = summ
    (out / "zusammenfassung.json").write_text(json.dumps(results, indent=2, default=float))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="folder with dataset_*.parquet")
    ap.add_argument("--out", type=Path, default=Path("results") / "ap6")
    ap.add_argument("--files", nargs="+", default=list(DEFAULT_FILES))
    a = ap.parse_args(argv)
    res = run_all(a.data, a.out, a.files)
    print(json.dumps(res.get("dp_tau010", {}), indent=2, default=float))


if __name__ == "__main__":
    main()
