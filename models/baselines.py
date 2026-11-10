"""Rule baselines (HANDOFF 3.9).

B0 (size rule): remove a feature if h / L_ref < s0. In the tool it is
only a *suggestion*; the user decides. Features close to the threshold
are marked "unsure" and kept by default (removing a relevant feature is
worse than keeping an irrelevant one, HANDOFF 3.10).

B1 (h+ rule) needs u_tau from a base calculation and follows in stage 3.
"""
from __future__ import annotations

REMOVE, KEEP, UNSURE = "remove", "keep", "unsure"


def b0_suggest(features, l_ref: float, s0: float = 0.02, band: float = 0.25) -> list:
    """Suggestion per feature: decision, ratio h/L_ref and a German reason."""
    if l_ref <= 0:
        raise ValueError("l_ref must be positive")
    out = []
    for f in features:
        h = f["h"] if isinstance(f, dict) else f.h
        fid = f["id"] if isinstance(f, dict) else f.id
        ratio = h / l_ref
        if ratio < s0 * (1 - band):
            dec = REMOVE
            why = f"h/L = {100 * ratio:.2f} % liegt unter der Schwelle {100 * s0:.2f} %"
        elif ratio > s0 * (1 + band):
            dec = KEEP
            why = f"h/L = {100 * ratio:.2f} % liegt über der Schwelle {100 * s0:.2f} %"
        else:
            dec = UNSURE
            why = (f"h/L = {100 * ratio:.2f} % liegt nahe der Schwelle {100 * s0:.2f} %, "
                   "bitte selbst entscheiden (Standard: behalten)")
        out.append({"id": fid, "decision": dec, "ratio": ratio, "reason": why, "model": "B0"})
    return out
