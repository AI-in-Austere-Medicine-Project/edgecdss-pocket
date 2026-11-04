"""Ported from EdgeCDSS server/tests/test_dose_units.py, test_minimum_dose.py and
the age and population tests of test_drug_contracts.py, keeping their cases and
values. Real-entry tests read the exported bank; the rest use the same fixtures.
EdgeCDSS's dose_range / max_single / min_single are `rule`, `cap.max_single` and
`floor` here. What was not ported, and why: engine/tests/PORTED.md."""
import pathlib

import pytest

from engine import contracts as dc
from engine.bank import load_bank

BANK = load_bank(pathlib.Path(__file__).resolve().parents[2] / "bank")


def entry_for(drug, **match):
    for e in BANK.entries:
        if e["drug"] == drug and all(e.get(k) == v for k, v in match.items()):
            return e
    raise AssertionError(f"no {drug} entry matching {match}")


def test_grams_are_not_milligrams_dextrose():
    r = dc.resolve_dose(entry_for("dextrose", indication="symptomatic hypoglycaemia",
                                  population="adult"), 80.0)
    assert r["kind"] == dc.MASS
    assert r["dose_mg"] == 25000.0
    assert (r["display_value"], r["display_units"]) == (25.0, "g")


def test_grams_are_not_milligrams_calcium():
    r = dc.resolve_dose(entry_for("calcium gluconate",
                                  indication="hyperkalaemia — membrane stabilisation",
                                  population="adult"), 80.0)
    assert r["dose_mg"] == 1000.0
    assert (r["display_value"], r["display_units"]) == (1.0, "g")


def test_micrograms_are_not_milligrams_epinephrine():
    r = dc.resolve_dose(entry_for("epinephrine", indication="symptomatic bradycardia — push dose",
                                  population="adult"), 80.0)
    assert r["dose_mg"] == pytest.approx(0.01)
    assert (r["display_value"], r["display_units"]) == (10.0, "mcg")


def test_micrograms_per_kg_fentanyl():
    r = dc.resolve_dose(entry_for("fentanyl", indication="acute pain / analgesia", route="IN"), 80.0)
    assert r["dose_mg"] == pytest.approx(0.08)
    assert (r["display_value"], r["display_units"]) == (80.0, "mcg")


def test_grams_per_kg_dextrose_paediatric():
    r = dc.resolve_dose(entry_for("dextrose", indication="symptomatic hypoglycaemia",
                                  population="peds"), 20.0)
    assert r["dose_mg"] == 10000.0
    assert (r["display_value"], r["display_units"]) == (10.0, "g")


def test_milligrams_per_kg_still_work():
    r = dc.resolve_dose(entry_for("morphine", indication="acute pain / analgesia",
                                  population="adult", route="IV"), 70.0)
    assert r["dose_mg"] == 7.0
    assert (r["display_value"], r["display_units"]) == (7.0, "mg")


@pytest.mark.parametrize("units,per_kg", [
    ("IU", False), ("units", False), ("units/kg", True), ("mmol", False),
    ("mEq", False), ("", False), (None, False), ("milligrams", False),
    ("puffs", False), (5, False),
])
def test_an_unknown_unit_refuses_rather_than_assuming_mg(units, per_kg):
    kind, _mass, why = dc.classify_units(units, per_kg)
    assert kind == dc.UNKNOWN
    assert why
    e = {"rule": {"min": 1.0, "max": 1.0, "units": units, "per_kg": per_kg}}
    assert dc.resolve_dose(e, 80.0)["dose_mg"] is None


@pytest.mark.parametrize("units,per_kg", [("mg", True), ("mg/kg", False), ("mcg/kg", False)])
def test_units_contradicting_per_kg_refuse(units, per_kg):
    kind, _, why = dc.classify_units(units, per_kg)
    assert kind == dc.UNKNOWN and why


def test_a_rate_never_becomes_a_bolus():
    r = dc.resolve_dose(entry_for("epinephrine", indication="symptomatic bradycardia — infusion",
                                  population="adult"), 80.0)
    assert r["kind"] == dc.RATE
    assert r["dose_mg"] is None
    assert "not a bolus" in r["reason"]


def test_a_mcg_per_hour_rate_is_a_rate():
    # test_contracts_analgesia_batch1.py
    assert dc.classify_units("mcg/hr", False)[0] == dc.RATE


def test_a_weight_based_dose_without_a_weight_refuses():
    assert dc.resolve_dose(entry_for("morphine", indication="acute pain / analgesia",
                                     population="adult", route="IV"), None)["dose_mg"] is None


def test_an_unusable_max_single_unit_refuses_the_whole_entry():
    e = dict(entry_for("fentanyl", indication="acute pain / analgesia", route="IN"))
    e["cap"] = {"max_single": {"value": 100.0, "units": "IU", "rule": "x"}, "max_cumulative": None}
    r = dc.resolve_dose(e, 80.0)
    assert r["dose_mg"] is None and "max_single" in r["reason"]


# ── test_minimum_dose.py ───────────────────────────────────────────────────

def atropine_peds():
    return {"indication": "symptomatic bradycardia", "population": "peds", "route": "IV",
            "rule": {"min": 0.02, "max": 0.02, "units": "mg/kg", "per_kg": True},
            "cap": {"max_single": {"value": 0.5, "units": "mg", "rule": "maximum single dose 0.5 mg"},
                    "max_cumulative": {"value": 1.0, "units": "mg", "rule": "maximum total dose 1 mg"}},
            "floor": {"value": 0.1, "units": "mg",
                      "rule": "a smaller dose can cause paradoxical bradycardia"}}


def test_a_3kg_infant_is_raised_to_the_minimum():
    r = dc.resolve_dose(atropine_peds(), 3.0)
    assert (r["dose_mg"], r["display_value"], r["display_units"]) == (0.1, 0.1, "mg")
    assert r["floor_applied"] is True


def test_the_floor_is_reported_in_the_medics_own_words():
    note = dc.resolve_dose(atropine_peds(), 3.0)["floor_note"]
    assert "MINIMUM DOSE 0.1 mg" in note
    assert "paradoxical bradycardia" in note


def test_five_kg_is_the_boundary_and_is_not_raised():
    r = dc.resolve_dose(atropine_peds(), 5.0)
    assert r["dose_mg"] == 0.1
    assert r["floor_applied"] is False


def test_just_under_five_kg_is_raised():
    r = dc.resolve_dose(atropine_peds(), 4.9)
    assert r["floor_applied"] is True
    assert r["dose_mg"] == 0.1


def test_an_ordinary_child_is_untouched():
    r = dc.resolve_dose(atropine_peds(), 10.0)
    assert r["dose_mg"] == 0.2
    assert r["floor_applied"] is False
    assert r["floor_note"] == ""


def test_the_cap_still_wins_at_the_top():
    r = dc.resolve_dose(atropine_peds(), 40.0)
    assert r["dose_mg"] == 0.5
    assert r["floor_applied"] is False
    assert r["capped"] is True


def test_an_entry_with_no_floor_is_unchanged():
    e = atropine_peds()
    e["floor"] = None
    r = dc.resolve_dose(e, 3.0)
    assert r["dose_mg"] == 0.06
    assert r["floor_applied"] is False


def test_a_per_kg_floor_scales():
    e = atropine_peds()
    e["rule"] = {"min": 0.001, "max": 0.001, "units": "mg/kg", "per_kg": True}
    e["floor"] = {"value": 0.01, "units": "mg/kg", "rule": ""}
    r = dc.resolve_dose(e, 10.0)
    assert r["dose_mg"] == 0.1
    assert r["floor_applied"] is True


def test_a_floor_in_another_unit_converts():
    e = atropine_peds()
    e["floor"] = {"value": 100.0, "units": "mcg", "rule": ""}
    assert dc.resolve_dose(e, 3.0)["dose_mg"] == 0.1


def test_a_fixed_dose_entry_can_carry_a_floor_without_a_weight():
    e = atropine_peds()
    e["rule"] = {"min": 0.05, "max": 0.05, "units": "mg", "per_kg": False}
    r = dc.resolve_dose(e, None)
    assert r["dose_mg"] == 0.1
    assert r["floor_applied"] is True


def test_an_unusable_floor_unit_refuses_the_whole_dose():
    e = atropine_peds()
    e["floor"] = {"value": 0.1, "units": "tablets", "rule": ""}
    r = dc.resolve_dose(e, 3.0)
    assert r["dose_mg"] is None
    assert "min_single" in r["reason"]


# ── age and population, test_drug_contracts.py ─────────────────────────────

def test_a_stated_age_under_the_floor_excludes_the_entry():
    assert dc.age_exclusion({"min_age_months": 3}, 2 / 12)
    assert dc.age_exclusion({"min_age_months": 3}, 3 / 12) is None


def test_an_unknown_age_blocks_nothing():
    assert dc.age_exclusion({"min_age_months": 3}, None) is None


def test_ruling_2_an_age_band_is_read_from_the_label():
    assert dc.age_band({"indication": "RSI paralytic — under 5 years"}) == (0.0, 5.0)
    assert dc.age_band({"indication": "RSI paralytic — 5 years and above"}) == (5.0, 200.0)
    assert dc.age_band({"indication": "RSI paralytic"}) is None


def test_the_population_specific_entry_replaces_the_shared_one():
    """Owner ruling 2026-09-18 (#65): ketamine analgesia serves SMOG's paediatric
    0.2 mg/kg to children, not NASEMSO's all-ages 0.25 mg/kg."""
    label = "moderate to severe pain / analgesia"
    shared = entry_for("ketamine", indication=label, population="adult|peds")
    peds = entry_for("ketamine", indication=label, population="peds", route="IV")
    assert dc.prefer_population_specific([shared, peds]) == [peds]


def test_a_child_is_not_offered_an_adult_entry_nor_an_adult_a_childs():
    adult, peds = {"population": "adult"}, {"population": "peds"}
    both = {"population": "adult|peds"}
    assert dc.fits_population(adult, child=False) and not dc.fits_population(adult, child=True)
    assert dc.fits_population(peds, child=True) and not dc.fits_population(peds, child=False)
    assert dc.fits_population(both, child=True) and dc.fits_population(both, child=False)


def test_range_text_is_the_rule_as_the_source_wrote_it():
    assert dc.range_text({"rule": {"min": 10.0, "max": 20.0, "units": "mcg", "per_kg": False}}) == "10-20 mcg"
    assert dc.range_text({"rule": {"min": 0.25, "max": 0.25, "units": "mg/kg", "per_kg": True}}) == "0.25 mg/kg"
    assert dc.range_text({"rule": {"min": 1.0, "max": 1.0, "units": "IU", "per_kg": False}}) is None
