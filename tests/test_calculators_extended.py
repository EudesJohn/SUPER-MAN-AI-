"""Reference-value tests for the extended calculators.

Each expected value is hand-computed independently; the calculator must match.
"""
from __future__ import annotations

import math

import pytest

from core.calculation import CalculationEngine


@pytest.fixture()
def eng():
    return CalculationEngine.default_engine()


# --------------------------------------------------------------------- #
# Bearing life
# --------------------------------------------------------------------- #
def test_bearing_life_ball_reference(eng):
    # L10h = (C/P)^3 * 1e6 / (60 n) = (14.3/5)^3 * 1e6 / (60*1450)
    expected = (14.3 / 5.0) ** 3 * 1e6 / (60.0 * 1450.0)
    rec = eng.run(
        "bearing_life_L10_hours",
        {"dynamic_capacity_N": 14300.0, "equivalent_load_N": 5000.0, "speed_rpm": 1450.0},
    )
    assert rec.result == pytest.approx(expected, rel=1e-9)
    assert rec.result_unit == "h"


def test_bearing_life_roller_reference(eng):
    # Roller: exponent 10/3 -> (20/8)^(10/3) * 1e6 / (60*900)
    expected = (20.0 / 8.0) ** (10.0 / 3.0) * 1e6 / (60.0 * 900.0)
    rec = eng.run(
        "bearing_life_L10_roller_hours",
        {"dynamic_capacity_N": 20000.0, "equivalent_load_N": 8000.0, "speed_rpm": 900.0},
    )
    assert rec.result == pytest.approx(expected, rel=1e-9)


def test_bearing_life_rejects_nonpositive(eng):
    with pytest.raises(ValueError):
        eng.run("bearing_life_L10_hours", {"dynamic_capacity_N": 0, "equivalent_load_N": 5.0, "speed_rpm": 100.0})


# --------------------------------------------------------------------- #
# Belt / chain
# --------------------------------------------------------------------- #
def test_belt_length_reference(eng):
    # L = 2*0.5 + pi*(0.1+0.2)/2 + (0.2-0.1)^2/(4*0.5)
    expected = 2 * 0.5 + math.pi * (0.1 + 0.2) / 2 + (0.2 - 0.1) ** 2 / (4 * 0.5)
    rec = eng.run("belt_length", {"d1_m": 0.1, "d2_m": 0.2, "center_distance_m": 0.5})
    assert rec.result == pytest.approx(expected, rel=1e-12)


def test_belt_speed_reference(eng):
    # v = pi * 0.1 * 1450 / 60 = 7.592... m/s
    expected = math.pi * 0.1 * 1450.0 / 60.0
    rec = eng.run("belt_speed", {"d1_m": 0.1, "n1_rpm": 1450.0})
    assert rec.result == pytest.approx(expected, rel=1e-12)


def test_transmission_ratio_reference(eng):
    rec = eng.run("transmission_ratio", {"d1_m": 0.1, "d2_m": 0.3})
    assert rec.result == pytest.approx(3.0, rel=1e-12)
    assert rec.result_unit == "-"


def test_chain_length_pitches_reference(eng):
    # p=12.7 mm, z1=19, z2=57, a=500 mm
    # Lp = 2*500/12.7 + (19+57)/2 + (12.7/500)*((57-19)/(2 pi))^2
    expected = 2 * 500 / 12.7 + (19 + 57) / 2 + (12.7 / 500) * ((57 - 19) / (2 * math.pi)) ** 2
    rec = eng.run(
        "chain_length_pitches",
        {"pitch_mm": 12.7, "z1": 19, "z2": 57, "center_distance_mm": 500.0},
    )
    assert rec.result == pytest.approx(expected, rel=1e-9)


# --------------------------------------------------------------------- #
# Deflection
# --------------------------------------------------------------------- #
def test_rect_inertia_reference(eng):
    # I = b h^3 / 12 = 0.05 * 0.1^3 / 12
    expected = 0.05 * 0.1**3 / 12.0
    rec = eng.run("rect_section_inertia", {"width_m": 0.05, "height_m": 0.1})
    assert rec.result == pytest.approx(expected, rel=1e-12)


def test_cantilever_deflection_reference(eng):
    # Steel E=210 GPa, I = b h^3/12 with b=0.05, h=0.1 -> delta = F L^3 / (3 E I)
    I = 0.05 * 0.1**3 / 12.0
    F, L, E = 1000.0, 1.0, 210e9
    expected = F * L**3 / (3.0 * E * I)
    rec_inertia = eng.run("rect_section_inertia", {"width_m": 0.05, "height_m": 0.1})
    rec = eng.run(
        "cantilever_deflection",
        {"force_N": F, "length_m": L, "young_modulus_Pa": E, "inertia_m4": rec_inertia.result},
    )
    assert rec.result == pytest.approx(expected, rel=1e-9)
    assert rec.result_unit == "m"


def test_simply_supported_deflection_reference(eng):
    I = 0.05 * 0.1**3 / 12.0
    F, L, E = 2000.0, 2.0, 210e9
    expected = F * L**3 / (48.0 * E * I)
    rec = eng.run(
        "simply_supported_center_deflection",
        {"force_N": F, "length_m": L, "young_modulus_Pa": E, "inertia_m4": I},
    )
    assert rec.result == pytest.approx(expected, rel=1e-9)


# --------------------------------------------------------------------- #
# Voltage drop
# --------------------------------------------------------------------- #
def test_voltage_drop_single_phase_reference(eng):
    # dU = 2 * 0.0225 * 50 * 16 / 2.5 = 14.4 V
    expected = 2.0 * 0.0225 * 50.0 * 16.0 / 2.5
    rec = eng.run(
        "voltage_drop",
        {
            "resistivity_ohm_mm2_per_m": 0.0225,
            "length_m": 50.0,
            "current_A": 16.0,
            "cross_section_mm2": 2.5,
            "phases": 1,
        },
    )
    assert rec.result == pytest.approx(expected, rel=1e-12)


def test_voltage_drop_three_phase_reference(eng):
    # dU = sqrt(3) * 0.0225 * 80 * 20 / 6
    expected = math.sqrt(3) * 0.0225 * 80.0 * 20.0 / 6.0
    rec = eng.run(
        "voltage_drop",
        {
            "resistivity_ohm_mm2_per_m": 0.0225,
            "length_m": 80.0,
            "current_A": 20.0,
            "cross_section_mm2": 6.0,
            "phases": 3,
        },
    )
    assert rec.result == pytest.approx(expected, rel=1e-12)


def test_voltage_drop_percent_reference(eng):
    rec = eng.run("voltage_drop_percent", {"drop_V": 8.0, "line_voltage_V": 400.0})
    assert rec.result == pytest.approx(2.0, rel=1e-12)


def test_voltage_drop_rejects_bad_phases(eng):
    with pytest.raises(ValueError):
        eng.run(
            "voltage_drop",
            {
                "resistivity_ohm_mm2_per_m": 0.0225,
                "length_m": 10.0,
                "current_A": 10.0,
                "cross_section_mm2": 2.5,
                "phases": 2,
            },
        )
