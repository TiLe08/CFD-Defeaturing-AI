"""Gate-1 evaluation of the AP2 feasibility study.

    python -m pipeline.ap2_report --raw data/raw --workers 6 --planned-runs 900

Answers the three Gate-1 questions:
  1. Does the pipeline run?        (all cases solved, checkMesh, convergence)
  2. How long does a case take?    (runtime, budget for the planned data set)
  3. Is the feature effect larger than the numerical error?
     (|dQ_rel| against null tests and the GCI of dQ_rel)
Writes ap2_summary.md and ap2_features.csv next to the cases.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.build_dataset import build, load_cases, mark_uncertain  # noqa: E402


def gci(phi: tuple[float, float, float], n_cells: tuple[int, int, int], dim: int = 2) -> dict:
    """Grid convergence index after Celik et al. (2008), fine grid = index 0.

    phi and n_cells are ordered fine, medium, coarse. For oscillatory
    convergence (sign change) the procedure is not defined; the half range
    of the three values is returned as uncertainty instead.
    """
    f1, f2, f3 = phi
    h1, h2, h3 = (n ** (-1.0 / dim) for n in n_cells)
    r21, r32 = h2 / h1, h3 / h2
    e21, e32 = f2 - f1, f3 - f2
    out = {"r21": r21, "r32": r32, "phi_fine": f1}
    if e21 == 0 or e32 == 0 or e32 / e21 < 0:
        out.update(oscillatory=True, p=float("nan"),
                   u_abs=0.5 * (max(phi) - min(phi)))
        return out
    s = math.copysign(1.0, e32 / e21)
    p = 2.0
    for _ in range(100):
        q = math.log((r21 ** p - s) / (r32 ** p - s))
        p_new = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-10:
            break
        p = p_new
    phi_ext = (r21 ** p * f1 - f2) / (r21 ** p - 1)
    e_a = abs((f1 - f2) / f1) if f1 else float("inf")
    out.update(oscillatory=False, p=p, phi_ext=phi_ext,
               gci_fine=1.25 * e_a / (r21 ** p - 1),
               u_abs=1.25 * abs(f1 - f2) / (r21 ** p - 1))
    return out


def _res(cases, role):
    return [c for c in cases.values() if c["spec"]["role"] == role and c["result"]]


def report(raw: Path, workers: int, planned_runs: int, tau: float = 0.01) -> str:
    cases = load_cases(raw)
    lines = ["# AP2 / Gate 1: Auswertung", ""]

    # 1. pipeline
    states = pd.Series([c["status"].get("state", "planned") for c in cases.values()])
    solved = [c for c in cases.values() if c["result"]]
    n_mesh_ok = sum(c["result"]["checkmesh_ok"] for c in solved)
    n_conv = sum(c["result"]["converged"] for c in solved)
    lines += ["## 1. Läuft die Pipeline?", "",
              f"{len(cases)} Fälle: " + ", ".join(f"{k} {v}" for k, v in states.value_counts().items())
              + f". checkMesh OK: {n_mesh_ok}/{len(solved)}. Konvergiert: {n_conv}/{len(solved)}.", ""]
    for c in solved:
        r = c["result"]
        if not r["converged"]:
            lines.append(f"- nicht konvergiert: {r['case_id']} ({r['iterations']} Iterationen, "
                         f"Residuen {r['final_residuals']})")
    if any(r["dp_source"] != "function_object" for r in (c["result"] for c in solved)):
        lines.append("- Hinweis: Δp teils aus dem Endfeld statt aus der Zeitreihe "
                     "(Lauf ohne Function Objects), Iterationsstreuung dann unbekannt.")
    lines.append("")

    # 2. runtime
    rt = pd.Series([c["result"]["runtime_clock_s"] for c in solved if c["spec"]["role"] == "with"])
    cells = pd.Series([c["result"]["cells"] for c in solved if c["spec"]["role"] == "with"])
    if len(rt):
        hours = planned_runs * rt.median() / workers / 3600
        lines += ["## 2. Laufzeit", "",
                  f"Fälle mit Feature: Median {rt.median():.1f} s (max. {rt.max():.1f} s) "
                  f"bei Median {cells.median():.0f} Zellen. Bei {planned_runs} Läufen und "
                  f"{workers} parallelen Workern ergibt das etwa {hours:.1f} h reine Rechenzeit. "
                  "Die Laufzeit gilt für Fälle wie diesen (Re, Netz); höhere Re und "
                  "turbulente Familien sind teurer.", ""]

    # 3. effect vs numerical error
    ref_case = _res(cases, "without")[0]
    ref = ref_case["result"]
    dp0 = ref["dp"]
    nulls = {r["role"]: (r["dp"] - dp0) / dp0 for c in cases.values()
             if (r := c["result"]) and r["role"].startswith("null_")}
    lines += ["## 3. Feature-Effekt gegen numerischen Fehler", "",
              "Nullversuche (Abweichung von Δp ohne Feature, relativ):", ""]
    for k, v in nulls.items():
        lines.append(f"- {k}: {v:+.4%}")
    lines.append("")

    g_with = {c["spec"]["mesh"]["n_per_H"]: c for c in _res(cases, "gci_with")}
    g_wo = {c["spec"]["mesh"]["n_per_H"]: c for c in _res(cases, "gci_without")}
    u_gci = float("nan")
    if len(g_with) == 2 and len(g_wo) == 2:
        gf = g_with[max(g_with)]["spec"]["features"][0]
        ref_with = next((c for c in _res(cases, "with")
                         if c["spec"]["features"][0] == gf), None)
        if ref_with is not None:
            # order fine, medium, coarse: finest GCI level, main cases, coarsest
            fine, coarse = max(g_with), min(g_with)
            dq = lambda w, o: (w["result"]["dp"] - o["result"]["dp"]) / o["result"]["dp"]  # noqa: E731
            phi_dq = (dq(g_with[fine], g_wo[fine]), dq(ref_with, ref_case),
                      dq(g_with[coarse], g_wo[coarse]))
            n_c = (g_wo[fine]["result"]["cells"], ref["cells"],
                   g_wo[coarse]["result"]["cells"])
            phi_q = (g_wo[fine]["result"]["dp"], dp0, g_wo[coarse]["result"]["dp"])
            gq, gd = gci(phi_q, n_c), gci(phi_dq, n_c)
            u_gci = gd["u_abs"]
            lines += ["GCI (Celik et al. 2008; fein/mittel/grob = "
                      f"{n_c[0]}/{n_c[1]}/{n_c[2]} Zellen, r21 = {gq['r21']:.2f}, r32 = {gq['r32']:.2f}):", "",
                      f"- Δp ohne Feature: Werte {phi_q[0]:.6g} / {phi_q[1]:.6g} / {phi_q[2]:.6g}, "
                      + (f"p = {gq['p']:.2f}, GCI_fein = {gq['gci_fine']:.2%}" if not gq["oscillatory"]
                         else f"oszillierend, Unsicherheit ±{gq['u_abs']:.3g}"),
                      f"- ΔQ_rel der GCI-Nut: Werte {phi_dq[0]:+.4%} / {phi_dq[1]:+.4%} / {phi_dq[2]:+.4%}, "
                      + (f"p = {gd['p']:.2f}, Unsicherheit ±{gd['u_abs']:.4%}" if not gd["oscillatory"]
                         else f"oszillierend, Unsicherheit (halbe Spannweite) ±{gd['u_abs']:.4%}"), ""]
    u_num = max(abs(nulls.get("null_shift", 0.0)), 0.0 if math.isnan(u_gci) else u_gci)
    lines += [f"Numerische Unsicherheit von ΔQ_rel (größer aus Box-Verschiebung und GCI): ±{u_num:.4%}. "
              "Der Versuch ohne Verfeinerungsbox zeigt, wie groß der Fehler ohne konsistente "
              "Vernetzung wäre, und geht deshalb nicht in die Unsicherheit ein.", ""]

    df = mark_uncertain(build(raw), u_num, tau)
    df["resolvable"] = df.dQ_rel.abs() > 2 * df.label_uncertainty
    show = df[["feature_id", "kind", "h_over_L", "dQ_rel", "label_uncertainty", "resolvable",
               f"relevant_tau{tau * 1000:03.0f}", "label_uncertain", "h_plus", "excluded"]]
    lines += ["| Feature | Typ | h/H | ΔQ_rel | Unsicherheit | auflösbar (>2u) | relevant (τ = 1 %) | Label unsicher | h⁺ | ausgeschlossen |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for _, r in show.iterrows():
        lines.append(f"| {r.feature_id} | {r.kind} | {r.h_over_L:.3g} | {r.dQ_rel:+.4%} | "
                     f"±{r.label_uncertainty:.4%} | {'ja' if r.resolvable else 'nein'} | "
                     f"{'ja' if r[f'relevant_tau{tau * 1000:03.0f}'] else 'nein'} | {'ja' if r.label_uncertain else 'nein'} | "
                     f"{r.h_plus:.3g} | {r.excluded if isinstance(r.excluded, str) else ''} |")
    lines.append("")
    df.to_csv(raw / "ap2_features.csv", index=False)
    text = "\n".join(lines)
    (raw / "ap2_summary.md").write_text(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--workers", type=int, required=True,
                    help="parallel workers on your machine (cores - 1)")
    ap.add_argument("--planned-runs", type=int, default=900)
    ap.add_argument("--tau", type=float, default=0.01)
    a = ap.parse_args(argv)
    print(report(a.raw, a.workers, a.planned_runs, a.tau))


if __name__ == "__main__":
    main()
