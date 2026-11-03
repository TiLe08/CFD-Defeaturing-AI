import numpy as np
import pandas as pd
import pytest

from descriptors.flow import flow_descriptors, separation_distance
from descriptors.geometric import geometric_descriptors
from geometry.features import Feature


def poiseuille(H, L, U, nu, n=400):
    """Fully developed channel flow: wall data of both walls and a profile."""
    x = (np.arange(n) + 0.5) * L / n
    tau = 6 * nu * U / H
    p = 12 * nu * U / H ** 2 * (L - x)
    wall = pd.DataFrame({"x": x, "p": p, "tau_x": -tau, "tau_y": 0.0, "area": L / n})
    y = np.linspace(0, H, 201)
    prof = pd.DataFrame({"y": y, "Ux": 6 * U * y / H * (1 - y / H), "Uy": 0.0})
    return wall, prof


def descriptors_at_scale(scale):
    H, L, nu, Re = 0.002 * scale, 0.05 * scale, 1e-6, 100.0
    U = Re * nu / H
    wall, prof = poiseuille(H, L, U, nu)
    f = Feature("rib", 0.6 * L, 0.5 * H, 0.1 * H)
    d = flow_descriptors(f, wall, [wall, wall], prof, nu, U, H, delta_cap=0.5 * H)
    d.update(geometric_descriptors(f, H, 2 * L, Re))
    return d, f, U, nu, H


def test_descriptors_are_scale_invariant_at_equal_re():
    d1, *_ = descriptors_at_scale(1.0)
    d10, *_ = descriptors_at_scale(10.0)
    for k, v in d1.items():
        if isinstance(v, str):
            assert v == d10[k]
        else:
            assert d10[k] == pytest.approx(v, rel=1e-9, abs=1e-12), k


def test_h_plus_matches_definition():
    d, f, U, nu, H = descriptors_at_scale(1.0)
    u_tau = np.sqrt(6 * nu * U / H)
    assert d["h_plus"] == pytest.approx(f.h * u_tau / nu, rel=1e-9)
    assert d["dpds_nd"] == pytest.approx(-12 * nu / (U * H) * 2, rel=1e-6)
    assert d["has_sep"] == 0


def test_delta_from_profile_is_capped_at_half_height():
    d, f, U, nu, H = descriptors_at_scale(1.0)
    # parabola reaches 99 % of the maximum at about 0.45 H, below the cap
    assert d["delta_source"] == "profile"
    assert 0.4 < f.h / d["h_over_delta"] / H < 0.5


def test_separation_distance_finds_zero_crossing():
    x = np.linspace(0, 1, 101)
    wall = pd.DataFrame({"x": x, "tau_x": x - 0.305})
    dist, has = separation_distance(wall, 0.5, 0.6, L_ref=0.1)
    assert has == 1
    assert dist == pytest.approx((0.5 - 0.305) / 0.1, rel=1e-6)
