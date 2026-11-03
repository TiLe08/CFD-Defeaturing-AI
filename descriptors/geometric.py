"""Geometric descriptors D_geo of one feature (dimensionless, local).

The family is never a model input. L_ref is the family's reference length
(F1: channel height H).
"""
from __future__ import annotations

from geometry.features import Feature

GEO_COLUMNS = ["category", "h_over_L", "w_over_L", "h_over_w", "area_frac",
               "orient_deg", "Re"]


def geometric_descriptors(f: Feature, L_ref: float, wetted_length_base: float,
                          Re: float, orient_deg: float = 90.0) -> dict:
    """D_geo for one feature.

    area_frac uses the footprint of the feature on the base wall (w in 2D,
    i.e. area per unit depth) relative to the total wetted length of the base
    geometry. orient_deg is the angle between the feature's long axis and the
    local flow direction; in 2D every feature spans the width, so it is 90.
    """
    return {
        "category": f.category,
        "h_over_L": f.h / L_ref,
        "w_over_L": f.w / L_ref,
        "h_over_w": f.h / f.w,
        "area_frac": f.w / wetted_length_base,
        "orient_deg": orient_deg,
        "Re": Re,
    }
