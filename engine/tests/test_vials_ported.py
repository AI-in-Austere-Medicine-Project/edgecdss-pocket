"""Ported from EdgeCDSS test_drug_concentrations.py, test_dose_units.py and the
K1 and K3 tests. A kit is {drug: [vial, ...]} built from kit.json."""
import pytest

from engine import vials as v


def vial(conc, drug="ketamine", mass=None, volume=None, confirm=False):
    return {"drug": drug, "label": "x", "mass_mg": mass or conc, "volume_ml": volume or 1.0,
            "concentration_mg_ml": conc, "confirm_required": confirm,
            "signer": "clinician", "date": "2026-10-28"}


K3_DILUTION = {"concentration_mg_ml": 5.0, "from_concentration_mg_ml": 50.0, "drug_ml": 1.0,
               "diluent_ml": 9.0, "diluent": "normal saline"}


@pytest.mark.parametrize("dose_mg,conc,expected", [
    (6.25, 50.0, 0.125), (2.5, 50.0, 0.05), (7.5, 10.0, 0.75),
    (142.1, 50.0, 2.84), (96.0, 10.0, 9.6), (1000.0, 100.0, 10.0),
])
def test_a_volume_is_drawn_to_the_places_a_syringe_shows(dose_mg, conc, expected):
    assert v.volume_ml({"ketamine": [vial(conc)]}, "ketamine", dose_mg) == (expected, conc)


def test_three_places_still_escalate_when_they_would_misstate_the_dose():
    assert v.draw_precision(0.000412) == 4
    assert v.draw_precision(0.125) == 3
    assert v.draw_precision(2.842) == 2


@pytest.mark.parametrize("vol,ok", [
    (0.001, False), (0.049, False), (0.05, True), (2.4, True),
    (60.0, True), (61.0, False), (250.0, False),
])
def test_only_a_drawable_volume_is_served(vol, ok):
    assert v.drawable(vol)[0] is ok


def test_no_signed_vial_gives_no_volume():
    assert v.resolve({}, "ketamine") == (v.NONE_DECLARED, None)
    assert v.volume_ml({}, "ketamine", 50.0) == (None, None)


def test_two_signed_strengths_refuse_to_pick_one():
    kit = {"ketamine": [vial(50.0), vial(10.0)]}
    assert v.resolve(kit, "ketamine") == (v.NEEDS_CONFIRMATION, None)
    assert v.volume_ml(kit, "ketamine", 50.0) == (None, None)


def test_confirm_required_refuses_even_one_vial():
    kit = {"morphine": [vial(10.0, drug="morphine", confirm=True)]}
    assert v.resolve(kit, "morphine") == (v.NEEDS_CONFIRMATION, None)


def test_the_volume_moves_with_the_declared_concentration():
    assert v.volume_ml({"ketamine": [vial(50.0)]}, "ketamine", 100.0) == (2.0, 50.0)
    assert v.volume_ml({"ketamine": [vial(10.0)]}, "ketamine", 100.0) == (10.0, 10.0)


def test_k1_75_kg_without_a_dilution_draws_from_the_vial():
    r = v.dose_volume({"ketamine": [vial(50.0)]}, {"drug": "ketamine", "dilution": None}, 18.75)
    assert (r["volume_ml"], r["concentration_mg_ml"], r["diluted"]) == (0.375, 50.0, False)


def test_k3_under_half_a_mil_draws_from_the_signed_dilution():
    """#195 ruling 1: 75 kg gives 3.75 mL of 5 mg/mL."""
    r = v.dose_volume({"ketamine": [vial(50.0)]}, {"drug": "ketamine", "dilution": K3_DILUTION}, 18.75)
    assert (r["volume_ml"], r["concentration_mg_ml"], r["diluted"]) == (3.75, 5.0, True)


def test_k3_the_ped_20_kg_case():
    r = v.dose_volume({"ketamine": [vial(50.0)]}, {"drug": "ketamine", "dilution": K3_DILUTION}, 4.0)
    assert (r["volume_ml"], r["concentration_mg_ml"], r["diluted"]) == (0.8, 5.0, True)


def test_k3_half_a_mil_exactly_stays_at_the_vial():
    r = v.dose_volume({"ketamine": [vial(50.0)]}, {"drug": "ketamine", "dilution": K3_DILUTION}, 25.0)
    assert (r["volume_ml"], r["concentration_mg_ml"], r["diluted"]) == (0.5, 50.0, False)


def test_k3_a_recipe_for_another_vial_is_not_used():
    """"1 mL of 50 mg/mL + 9 mL" made from a 10 mg/mL vial is 1 mg/mL, not 5."""
    r = v.dose_volume({"ketamine": [vial(10.0)]}, {"drug": "ketamine", "dilution": K3_DILUTION}, 4.0)
    assert (r["volume_ml"], r["concentration_mg_ml"], r["diluted"]) == (0.4, 10.0, False)


def test_a_dose_too_small_for_the_vial_refuses_and_names_the_dilution():
    r = v.dose_volume({"ketamine": [vial(50.0)]}, {"drug": "ketamine", "dilution": K3_DILUTION}, 1.0)
    assert r["volume_ml"] is None
    assert r["refusal"] == v.TOO_SMALL
    assert r["recipe"] == K3_DILUTION


def test_a_dose_too_small_with_no_dilution_refuses():
    r = v.dose_volume({"epinephrine": [vial(1.0, drug="epinephrine")]},
                      {"drug": "epinephrine", "dilution": None}, 0.01)
    assert r["volume_ml"] is None
    assert r["refusal"] == v.TOO_SMALL
    assert r["recipe"] is None


def test_a_dose_too_large_for_a_push_refuses():
    r = v.dose_volume({"ketamine": [vial(1.0)]}, {"drug": "ketamine", "dilution": None}, 100.0)
    assert r["volume_ml"] is None
    assert r["refusal"] == v.TOO_LARGE
