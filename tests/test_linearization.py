import numpy as np
import pytest

from freecad4parametricfea import fields as F, linearization as L


def test_linear_distribution_membrane_and_bending_exact():
    t = 12.0
    s = np.linspace(0, t, 61)
    sm, sb = 40.0, 25.0
    xx = sm + sb * (1 - 2 * s / t)
    T = np.zeros((len(s), 6))
    T[:, 0] = xx
    lin = L.linearize(s, T)
    assert lin["Sm"][0] == pytest.approx(sm, rel=1e-12)
    assert lin["Sb0"][0] == pytest.approx(sb, rel=1e-12)
    assert np.abs(lin["peak"]).max() < 1e-9
    summ = L.summary(lin)
    assert summ["PmPb_start_vonMises"] == pytest.approx(sm + sb)
    assert summ["PmPb_end_Tresca"] == pytest.approx(sm - sb)


def test_parabolic_distribution_has_peak():
    t = 10.0
    s = np.linspace(0, t, 201)
    xx = 100.0 * (1 - ((s - t / 2) / (t / 2)) ** 2)          # parabole nulle aux deux bords
    T = np.zeros((len(s), 6))
    T[:, 0] = xx
    lin = L.linearize(s, T)
    assert lin["Sm"][0] == pytest.approx(100 * 2 / 3, rel=1e-4)       # moyenne d'une parabole
    assert lin["Sb0"][0] == pytest.approx(0.0, abs=1e-6)             # symetrique : pas de flexion
    assert lin["peak"][len(s) // 2, 0] == pytest.approx(100 / 3, rel=1e-3)


def test_zero_length_rejected():
    with pytest.raises(ValueError):
        L.linearize(np.zeros(5), np.zeros((5, 6)))


def test_equivalents():
    T = np.array([100.0, 0, 0, 0, 0, 0])
    assert F.von_mises(T) == pytest.approx(100.0)
    assert F.tresca(T) == pytest.approx(100.0)
    pure_shear = np.array([0, 0, 0, 50.0, 0, 0])
    assert F.von_mises(pure_shear) == pytest.approx(50 * 3 ** 0.5)
    assert F.tresca(pure_shear) == pytest.approx(100.0)


def test_strain_vm_equals_stress_over_E():
    E, nu = 210000.0, 0.3
    s = np.array([[80.0, 20.0, -10.0, 15.0, 5.0, 0.0]])
    e = F.stress_to_strain(s, E, nu)
    assert F.equivalent_strain(e, nu)[0] == pytest.approx(F.von_mises(s)[0] / E, rel=1e-12)


def test_local_frame_orthonormal():
    et, ea, eb = L.local_frame([0, 0, 0], [1, 1, 0])
    for u in (et, ea, eb):
        assert np.linalg.norm(u) == pytest.approx(1.0)
    assert abs(et @ ea) < 1e-12 and abs(et @ eb) < 1e-12 and abs(ea @ eb) < 1e-12
    with pytest.raises(ValueError):
        L.local_frame([0, 0, 0], [0, 0, 1], ref=[0, 0, 5])
