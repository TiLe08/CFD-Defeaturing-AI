import textwrap

import numpy as np
import pytest

from cfd import foamio, postprocess as pp
from pipeline.ap2_report import gci

LOG = textwrap.dedent("""\
    Time = 1

    smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.01, No Iterations 2
    GAMG:  Solving for p, Initial residual = 1, Final residual = 0.04, No Iterations 5
    ExecutionTime = 0.05 s  ClockTime = 0 s

    Time = 2

    smoothSolver:  Solving for Ux, Initial residual = 1e-07, Final residual = 1e-09, No Iterations 2
    GAMG:  Solving for p, Initial residual = 2e-07, Final residual = 1e-09, No Iterations 5
    ExecutionTime = 0.10 s  ClockTime = 1 s


    SIMPLE solution converged in 2 iterations

    End
    """)


def test_parse_solver_log():
    r = pp.parse_solver_log(LOG)
    assert r["iterations"] == 2
    assert r["residual_converged"] and r["finished"]
    assert r["final_residuals"] == {"Ux": 1e-7, "p": 2e-7}
    assert r["runtime_clock_s"] == 1.0


def test_parse_checkmesh_log():
    r = pp.parse_checkmesh_log("    cells:            8891\n...\nMesh OK.\n")
    assert r == {"cells": 8891, "checkmesh_ok": True}
    assert not pp.parse_checkmesh_log("cells: 3\n Failed 1 mesh checks.\n")["checkmesh_ok"]


def test_dp_series_handles_restart(tmp_path):
    for fo, val in (("pIn", 5.0), ("pOut", 1.0)):
        for t0, its in (("0", range(1, 4)), ("3", range(3, 6))):
            d = tmp_path / "postProcessing" / fo / t0
            d.mkdir(parents=True)
            rows = "\n".join(f"{i}\t{val + (0.1 if t0 == '3' else 0)}" for i in its)
            (d / "surfaceFieldValue.dat").write_text("# Time  areaAverage(p)\n" + rows)
    s = pp.dp_series(tmp_path)
    assert list(s.iter) == [1, 2, 3, 4, 5]
    assert s.dp.iloc[-1] == pytest.approx(4.0)  # restart values win


def test_tail_stats():
    m, s = pp.tail_stats([0, 0, 1, 1, 1], 3)
    assert (m, s) == (1.0, 0.0)


def test_read_field_nonuniform(tmp_path):
    f = tmp_path / "U"
    f.write_text(textwrap.dedent("""\
        FoamFile { version 2.0; format ascii; class volVectorField; object U; }
        dimensions [0 1 -1 0 0 0 0];
        internalField nonuniform List<vector> 2((1 0 0) (2 0 0));
        boundaryField
        {
            inlet { type fixedValue; value uniform (1 0 0); }
            wall  { type noSlip; }
            "(front|back)" { type empty; }
        }
        """))
    internal, bf = foamio.read_field(f)
    assert internal.shape == (2, 3) and internal[1, 0] == 2
    assert bf["wall"] is None and bf["inlet"].tolist() == [[1, 0, 0]]
    assert "(front|back)" in bf


def test_gci_recovers_second_order():
    n = (40000, 10000, 2500)  # r = 2 in 2D
    h = [k ** -0.5 for k in n]
    phi = tuple(1.0 + 0.3 * hh ** 2 for hh in h)
    g = gci(phi, n)
    assert not g["oscillatory"]
    assert g["p"] == pytest.approx(2.0, rel=1e-6)
    assert g["phi_ext"] == pytest.approx(1.0, rel=1e-9)


def test_gci_flags_oscillation():
    g = gci((1.0, 1.1, 0.95), (4, 2, 1))
    assert g["oscillatory"] and g["u_abs"] == pytest.approx(0.075)
