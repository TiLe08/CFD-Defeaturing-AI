"""Turn solved cases into the feature table (one row per feature).

    python -m pipeline.build_dataset --raw data/raw --out data/processed/dataset.parquet

Per base configuration the cases with role "without" (label reference) and
"base_coarse" (descriptor source) must be solved. Every "with" case gives
one row. Cases that failed, did not converge or failed checkMesh are kept
in the table with a reason in "excluded", so exclusions can be counted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from descriptors.flow import flow_descriptors  # noqa: E402
from descriptors.geometric import geometric_descriptors  # noqa: E402
from geometry.features import Feature  # noqa: E402

TAUS = (0.005, 0.01, 0.02)


def load_cases(raw: Path) -> dict[str, dict]:
    cases = {}
    for spec_f in sorted(raw.glob("*/spec.json")):
        d = spec_f.parent
        spec = json.loads(spec_f.read_text())
        status = json.loads((d / "status.json").read_text()) if (d / "status.json").exists() else {}
        res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else None
        cases[spec["case_id"]] = {"dir": d, "spec": spec, "status": status, "result": res}
    return cases


def exclusion_reason(c: dict | None) -> str | None:
    if c is None:
        return "missing"
    if c["result"] is None:
        return f"not solved ({c['status'].get('state', 'planned')})"
    r = c["result"]
    if not r["checkmesh_ok"]:
        return "checkMesh failed"
    if not r["converged"]:
        return "not converged"
    return None


def _q(r: dict) -> float:
    """Target quantity: Q (F2: c_d), F1 results store it as dp."""
    return float(r["Q"] if "Q" in r else r["dp"])


def _rel_sigma(r: dict) -> float:
    v = r.get("Q_rel_sigma", r.get("dp_rel_sigma"))
    return float("nan") if v is None else float(v)


def reference_length(spec: dict) -> float:
    return spec["params"]["c"] if spec["family"] == "F2" else spec["params"]["H"]


def wall_tables(case_dir: Path, spec: dict, f: Feature):
    """Wall carrying the feature, all walls, and the cap for delta_99.

    F1: bottom and top wall of the channel, delta capped at half the height.
    F2: upper and lower side of the profile; the stagnation region
    (x < 0.02 c) is left out of the feature wall so that the stagnation point
    is not taken for separation. delta capped at 0.1 c.
    """
    if spec["family"] == "F2":
        c = spec["params"]["c"]
        df = pd.read_csv(case_dir / "wall_profile.csv")
        sides = {s: df[df.side == s] for s in ("upper", "lower")}
        wall = sides[f.wall]
        return wall[wall.x >= 0.02 * c], list(sides.values()), 0.1 * c
    walls = {n: pd.read_csv(case_dir / f"wall_{n}.csv") for n in ("bottomWall", "topWall")}
    return walls["bottomWall"], list(walls.values()), 0.5 * spec["params"]["H"]


def build(raw: Path) -> pd.DataFrame:
    cases = load_cases(raw)
    by_base: dict[str, dict[str, list]] = {}
    for cid, c in cases.items():
        by_base.setdefault(c["spec"]["base_id"], {}).setdefault(c["spec"]["role"], []).append(c)
    rows = []
    for base_id, roles in sorted(by_base.items()):
        ref = (roles.get("without") or [None])[0]
        coarse = (roles.get("base_coarse") or [None])[0]
        for c in roles.get("with", []):
            spec = c["spec"]
            f = Feature.from_dict(spec["features"][0])
            row = {"feature_id": spec["case_id"], "base_id": base_id,
                   "family": spec["family"], "kind": f.kind,
                   "case_with": spec["case_id"],
                   "case_without": ref["spec"]["case_id"] if ref else None}
            reason = exclusion_reason(c) or exclusion_reason(ref) or exclusion_reason(coarse)
            L_ref, nu, U = reference_length(spec), spec["flow"]["nu"], spec["flow"]["U"]
            if ref is not None and ref["result"] is not None:
                wl = json.loads((ref["dir"] / "geometry.json").read_text())["wetted_length"]
                row.update(geometric_descriptors(f, L_ref, wl, U * L_ref / nu))
            if coarse is not None and coarse["result"] is not None:
                prof_f = coarse["dir"] / "profile_slot.csv"
                prof = pd.read_csv(prof_f) if prof_f.exists() else None
                try:
                    wall, all_walls, cap = wall_tables(coarse["dir"], coarse["spec"], f)
                    row.update(flow_descriptors(f, wall, all_walls, prof, nu, U, L_ref,
                                                delta_cap=cap))
                except ValueError as exc:
                    reason = reason or f"descriptor: {exc}"
            if c["result"] is not None and ref is not None and ref["result"] is not None:
                rw, r0 = c["result"], ref["result"]
                q_w, q_0 = _q(rw), _q(r0)
                dq = (q_w - q_0) / q_0
                row.update(Q_with=q_w, Q_without=q_0, dQ_rel=dq,
                           sigma_iter_with=_rel_sigma(rw), sigma_iter_without=_rel_sigma(r0),
                           cells_with=rw["cells"], cells_without=r0["cells"],
                           runtime_with_s=rw["runtime_clock_s"],
                           runtime_without_s=r0["runtime_clock_s"])
                for tau in TAUS:
                    row[f"relevant_tau{tau * 1000:03.0f}"] = bool(abs(dq) > tau)
            row["excluded"] = reason
            rows.append(row)
    return pd.DataFrame(rows)


def mark_uncertain(df: pd.DataFrame, u_num: float, tau: float = 0.01) -> pd.DataFrame:
    """Flag labels whose distance to tau is below the numerical uncertainty.

    u_num is the relative uncertainty of dQ_rel (from null test and GCI);
    iterative scatter of both runs is added where available.
    """
    it = np.sqrt(df.sigma_iter_with.fillna(0) ** 2 + df.sigma_iter_without.fillna(0) ** 2)
    u = np.sqrt(u_num ** 2 + it ** 2)
    out = df.copy()
    out["label_uncertainty"] = u
    out["label_uncertain"] = (out.dQ_rel.abs() - tau).abs() < u
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "dataset.parquet")
    a = ap.parse_args(argv)
    df = build(a.raw)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False)
    n_ex = df.excluded.notna().sum()
    print(f"{len(df)} features, {n_ex} excluded -> {a.out}")
    if n_ex:
        print(df.loc[df.excluded.notna(), ["feature_id", "excluded"]].to_string(index=False))


if __name__ == "__main__":
    main()
