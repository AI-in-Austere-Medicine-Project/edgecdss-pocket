"""No dilution in Pocket (owner rule, 2026-11-22): "When a volume is under 0.5 mL, Pocket
says the volume to the nearest 0.01 mL and adds 'Use a one mil syringe.' The 'too small
to draw' limit under 0.05 mL stays as it is."

This replaces K3 (owner, 2026-10-28), under which a volume under 0.5 mL was drawn from a
signed dilution. A signed dilution in an entry is no longer used.
"""
import pathlib

import pytest

from engine import vials as V
from engine.session import ONE_MIL_SYRINGE, boot

BANK = pathlib.Path(__file__).resolve().parents[1] / "bank"
KIT = {"x": [{"concentration_mg_ml": 10.0}]}
DILUTION = {"from_concentration_mg_ml": 10.0, "concentration_mg_ml": 1.0, "drug_ml": 1.0,
            "diluent_ml": 9.0, "diluent": "normal saline"}


@pytest.mark.parametrize("dose_mg, ml", [(4.9, 0.49), (1.234, 0.12), (0.75, 0.08), (0.5, 0.05), (2.0, 0.2)])
def test_under_half_a_mil_is_to_the_nearest_hundredth(dose_mg, ml):
    assert V.volume_ml(KIT, "x", dose_mg) == (ml, 10.0)


def test_a_signed_dilution_is_not_used():
    out = V.dose_volume(KIT, {"drug": "x", "dilution": DILUTION}, 1.234)
    assert (out["volume_ml"], out["concentration_mg_ml"], out["diluted"], out["recipe"]) == (0.12, 10.0, False, None)


def test_under_005_ml_is_still_too_small_to_draw_and_names_no_dilution():
    out = V.dose_volume(KIT, {"drug": "x", "dilution": DILUTION}, 0.49)
    assert out["volume_ml"] is None and out["refusal"] == V.TOO_SMALL and out["recipe"] is None
    assert V.MIN_DRAWABLE_ML == 0.05


def test_from_half_a_mil_up_the_rounding_is_unchanged():
    assert V.volume_ml(KIT, "x", 5.0) == (0.5, 10.0)
    assert V.volume_ml(KIT, "x", 13.33) == (1.3, 10.0)        # 1 to 10 mL: 0.1 (owner ruling, same day)


def test_pocket_adds_use_a_one_mil_syringe_under_half_a_mil():
    assert ONE_MIL_SYRINGE == "Use a one mil syringe."
    s = boot(BANK)
    s.handle("ketamine for pain iv twenty kilos")          # 0.2 mg/kg x 20 kg = 4 mg of 50 mg/mL
    said = s.handle("confirm").say
    assert "Zero point zero eight mils of five hundred per ten. Use a one mil syringe." in said   # as the label reads
    assert "Dilute" not in said and "dilution" not in said
    s = boot(BANK)
    s.handle("ketamine for pain iv four kilos")             # 0.016 mL: too small, no recipe
    assert s.handle("confirm").say == "Ketamine zero point eight milligrams. Too small to draw. No volume."


def test_a_volume_from_half_a_mil_says_no_syringe():
    s = boot(BANK)
    s.handle("ketamine for agitation iv eighty kilos")
    assert ONE_MIL_SYRINGE not in s.handle("confirm").say
