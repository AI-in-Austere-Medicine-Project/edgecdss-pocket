"""Volumes and strengths as spoken (owner rulings, 2026-11-22).

Rounding: under 0.5 mL, the nearest 0.01 mL and "Use a one mil syringe." (owner rule,
tests/test_one_mil_syringe.py); 0.5 to 1 mL, the nearest 0.01 mL; 1 to 10 mL, the nearest
0.1 mL; 10 mL and over, the nearest 1 mL. Safeguards kept: a rounding that would move the
dose more than 5 % takes one more decimal place; a volume never rounds above the signed
maximum; under 0.05 mL is too small to draw.

Label wording, as proposed: the strength as the vial's label reads it, "one sixty per five"
(160 mg / 5 mL), milligrams unsaid, grams and micrograms said.
"""
import pathlib

import pytest

from engine import vials as V
from engine.session import boot

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _kit(conc, label="x"):
    return {"x": [{"concentration_mg_ml": conc, "label": label}]}


@pytest.mark.parametrize("dose_mg, conc, ml", [
    (0.75, 10.0, 0.08),         # under 0.5: 0.01 (0.075 -> 0.08, the owner's rule as given)
    (7.5, 10.0, 0.75),          # 0.5 to 1: 0.01
    (8.75, 10.0, 0.88),
    (13.33, 10.0, 1.3),         # 1 to 10: 0.1
    (17.5, 10.0, 1.8),
    (93.75, 10.0, 9.4),
    (164.0, 10.0, 16.0),        # 10 and over: 1
    (525.0, 10.0, 53.0),        # half up: 52.5 -> 53
])
def test_each_band_rounds_to_its_step(dose_mg, conc, ml):
    assert V.volume_ml(_kit(conc), "x", dose_mg) == (ml, conc)


def test_no_rounding_moves_the_dose_more_than_5_percent():
    """With these steps the worst case is the foot of a band (1.05 mL -> 1.1, +4.8 %), so
    the safeguard holds everywhere; it is kept in the code for any step that would not."""
    for i in range(500, 60000, 7):                 # 0.5 to 60 mL
        true = i / 1000
        ml, _ = V.volume_ml(_kit(1.0), "x", true)
        assert abs(ml - true) / true <= 0.05, (true, ml)
    assert V.volume_ml(_kit(10.0), "x", 10.5) == (1.1, 10.0)


def test_a_volume_never_rounds_above_the_signed_maximum():
    assert V.volume_ml(_kit(10.0), "x", 17.5) == (1.8, 10.0)
    assert V.volume_ml(_kit(10.0), "x", 17.5, max_mg=17.5) == (1.7, 10.0)     # 1.8 would be 18 mg
    assert V.volume_ml(_kit(10.0), "x", 0.75, max_mg=0.75) == (0.07, 10.0)    # under 0.5 too


@pytest.mark.parametrize("label, conc, said", [
    ("160 mg / 5 mL oral liquid", 32.0, "one sixty per five"),
    ("1 g / 10 mL", 100.0, "one gram per ten"),
    ("12 mg / 4 mL", 3.0, "twelve per four"),
    ("500 mg / 10 mL vial", 50.0, "five hundred per ten"),
    ("50 mg/mL (vial size not stated)", 50.0, "fifty per mil"),
    ("50 mcg/mL (vial size not stated)", 0.05, "fifty micrograms per mil"),
    ("D10W 25 g / 250 mL", 100.0, "twenty-five grams per two fifty"),
    ("2.5 mg / 3 mL nebule", 0.833333, "two point five per three"),
    ("1000 mg / 10 mL ampoule", 100.0, "one thousand per ten"),
    ("5 g / 200 mL (reconstituted)", 25.0, "five grams per two hundred"),
    ("1 mg / 1 mL", 1.0, "one per mil"),
    ("a label with no strength", 7.0, "seven"),                         # falls back to mg per mL
])
def test_the_strength_is_said_as_its_label_reads(label, conc, said):
    assert V.label_words({"label": label, "concentration_mg_ml": conc}) == said


def test_the_owners_examples_as_pocket_says_them():
    s = boot(ROOT / "bank" / "ems")
    s.handle("acetaminophen for fever po twenty kilos")
    assert s.handle("confirm").say == "Acetaminophen three hundred milligrams. Nine point four mils of one sixty per five."
    s = boot(ROOT / "bank" / "ems")
    s.handle("fentanyl for pain iv adult")
    assert "Zero point five mils of fifty micrograms per mil." in s.handle("confirm").say


def test_the_pfc_ketamine_dilution_cautions_are_not_said_and_stay_in_the_record():
    """Owner ruling, 2026-11-22: "PFC ketamine dilution cautions: drop them from what Pocket
    says; keep the signed text in the record." (No dilution in Pocket.)"""
    import json
    from engine.session import caution_lines
    entries = [e for e in json.loads((ROOT / "bank" / "bank.json").read_text())["entries"]
               if e["drug"] == "ketamine" and e["route"] == "IV"]
    held = [c for e in entries for c in e["serve_cautions"] if "dilution" in c.lower()]
    assert len(held) == 6                                             # still in the signed record
    for e in entries:
        said = " ".join(caution_lines(e, True))
        assert "dilution" not in said.lower()
    s = boot(ROOT / "bank")
    s.handle("ketamine for moderate pain iv eighty kilos")
    s.handle("confirm")
    assert "dilution" not in " ".join(s.handle("why").after).lower()
