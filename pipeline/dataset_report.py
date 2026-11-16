"""Short report on a data set: size, exclusions, class balance, runtime.

    python -m pipeline.dataset_report --raw data/raw --design f1

Only describes the labels and the data set; it fits no model. Writes
<raw>/dataset_<design>.md and data/processed/dataset_<design>.parquet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.build_dataset import TAUS, build  # noqa: E402


# base_id of each design (data/raw may hold several designs side by side)
BASE_PATTERNS = {"ap2": r"^f1_ap2_b\d{3}$", "f1": r"^f1_b\d{3}$",
                 "f2_trial": r"^f2_trial_b\d{3}$"}


def report(raw: Path, design: str, out_parquet: Path) -> str:
    df = build(raw)
    df = df[df.base_id.str.match(BASE_PATTERNS[design])]
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_parquet, index=False)
    ok = df[df.excluded.isna()]
    lines = [f"# Datensatz {design.upper()}", "",
             f"{len(df)} Features aus {df.base_id.nunique()} Basiskonfigurationen, "
             f"davon {len(ok)} gültig und {len(df) - len(ok)} ausgeschlossen.", ""]
    if len(df) > len(ok):
        lines += ["| Ausschlussgrund | Anzahl |", "| --- | --- |"]
        for reason, n in df.excluded.value_counts().items():
            lines.append(f"| {reason} | {n} |")
        lines.append("")

    lines += ["## Klassenbalance (Anteil „relevant“)", "",
              "| Typ | n | " + " | ".join(f"τ = {t:.1%}".replace(".", ",") for t in TAUS) + " |",
              "| --- | --- | " + " | ".join("---" for _ in TAUS) + " |"]
    for kind, g in [("alle", ok), *ok.groupby("kind")]:
        cells = [f"{g[f'relevant_tau{t * 1000:03.0f}'].sum()} ({g[f'relevant_tau{t * 1000:03.0f}'].mean():.0%})"
                 for t in TAUS]
        lines.append(f"| {kind} | {len(g)} | " + " | ".join(cells) + " |")
    lines.append("")

    lines += ["## Wertebereiche", "",
              "| Größe | Min | Median | Max |", "| --- | --- | --- | --- |"]
    for col in ("Re", "h_over_L", "w_over_L", "h_plus", "h_over_delta", "dQ_rel"):
        s = ok[col]
        lines.append(f"| {col} | {s.min():.3g} | {s.median():.3g} | {s.max():.3g} |")
    lines.append("")

    rt = ok.runtime_with_s
    lines += ["## Laufzeit", "",
              f"Fälle mit Feature: Median {rt.median():.1f} s, Maximum {rt.max():.1f} s, "
              f"Summe {rt.sum() / 60:.1f} min (seriell).", ""]
    text = "\n".join(lines)
    (raw / f"dataset_{design}.md").write_text(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--design", default="f1", choices=sorted(BASE_PATTERNS))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = a.out or ROOT / "data" / "processed" / f"dataset_{a.design}.parquet"
    print(report(a.raw, a.design, out))


if __name__ == "__main__":
    main()
