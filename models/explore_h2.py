"""Exploratory follow-up to H2 (deviation from the frozen protocol, 26.11.2026).

The frozen run showed that flow descriptors generalize worse to an unseen
family than geometry alone. Suspected cause: absolute regime quantities
(Re, Re_h, h+) whose ranges differ per family (laminar F1/F2/F4 against
turbulent F3), so the trees extrapolate. Gradient boosting is invariant to
monotone transforms, so a log does not help; only ratios or leaving the
quantities out change what the model sees.

Variants (everything else exactly as in models/evaluate.py):
- M1_geo_noRe:   D_geo without Re
- M1_flow_noRe:  D_flow without Re and Re_h
- M1_flow_norm:  D_geo without Re, plus h/delta, c_p, dp/ds, force share,
                 distance to separation, separation flag and
                 u_tau / U = h+ / (h/L * Re) instead of h+, Re and Re_h

Results are reported as exploratory, never as the test of H2.

Usage:
    python -m models.explore_h2 --data /path/to/datensaetze --out results/ap6_h2
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from models import evaluate as ev

GEO_NO_RE = [c for c in ev.GEO if c != "Re"]
VARIANTS = {
    "M1_geo": ev.GEO,
    "M1_flow": ev.FLOW,
    "M1_geo_noRe": GEO_NO_RE,
    "M1_flow_noRe": [c for c in ev.FLOW if c not in ("Re", "Re_h")],
    "M1_flow_norm": GEO_NO_RE + ["h_over_delta", "cp_local", "dpds_nd", "force_frac",
                                 "dist_sep_nd", "has_sep", "utau_ratio"],
}


def add_ratios(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["utau_ratio"] = df.h_plus / (df.h_over_L * df.Re)  # u_tau / U_ref
    return df


def run(data: Path, out: Path, taus=(0.010,)) -> pd.DataFrame:
    out.mkdir(parents=True, exist_ok=True)
    ev.MODEL_SETS = VARIANTS
    df = add_ratios(ev.load(data))
    rows = []
    for tau in taus:
        lofo, _ = ev.run_lofo(df, "dp", tau)
        ind = ev.run_in_distribution(df, "dp", tau)
        for scheme, d in (("LOFO", lofo), ("in-distribution", ind)):
            g = d.groupby("model")[["specificity", "recall"]].mean()
            for m, r in g.iterrows():
                rows.append({"tau": tau, "scheme": scheme, "model": m, **r.to_dict()})
        pd.concat([lofo, ind]).to_csv(out / f"metriken_h2_tau{tau * 1000:03.0f}.csv", index=False)
    res = pd.DataFrame(rows)
    piv = res.pivot_table(index=["tau", "model"], columns="scheme", values=["specificity", "recall"])
    piv[("gap", "")] = piv[("specificity", "in-distribution")] - piv[("specificity", "LOFO")]
    lines = ["# H2 explorativ: Strömungsgrößen ohne absolute Regimegrößen", "",
             "Abweichung vom eingefrorenen Protokoll, nur explorativ. Mittel über die Familien.", "",
             "| τ | Modell | Spezifität LOFO | Recall LOFO | Spezifität innerhalb | Lücke |",
             "| --- | --- | --- | --- | --- | --- |"]
    for (tau, m), r in piv.iterrows():
        lines.append(f"| {tau:.1%} | {m} | {r[('specificity', 'LOFO')]:.0%} | "
                     f"{r[('recall', 'LOFO')]:.0%} | {r[('specificity', 'in-distribution')]:.0%} | "
                     f"{100 * r[('gap', '')]:+.0f} pp |")
    (out / "h2_explorativ.md").write_text("\n".join(lines) + "\n")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("results") / "ap6_h2")
    a = ap.parse_args(argv)
    run(a.data, a.out, ev.TAUS)
    print((a.out / "h2_explorativ.md").read_text())


if __name__ == "__main__":
    main()
