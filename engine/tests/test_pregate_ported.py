"""The pre-gate's questions and holds, ported from EdgeCDSS test_ask_which_indication.py,
test_weight_confidence.py, test_a39_unsigned_drug_holds_before_model.py and the A34,
A35 and K1 tests. EdgeCDSS tests these through the pipeline's text; Pocket has no
pipeline, so each case is the same request through the session."""
import pathlib

import pytest

from engine.session import boot

BANK = pathlib.Path(__file__).resolve().parents[2] / "bank"


@pytest.fixture
def s():
    return boot(BANK)


# ── which indication (owner, 2026-10-15) ───────────────────────────────────

def test_the_live_failure_a_drug_with_no_indication_is_asked(s):
    """"Need to give ketamine 89kg IV established" served post-intubation sedation."""
    assert s.handle("ketamine eighty nine kilos iv").say == \
        "Which indication: sedation, pain, agitation, RSI or seizure?"


def test_the_answer_selects_the_indication(s):
    s.handle("ketamine eighty nine kilos iv")
    assert s.handle("agitation").kind == "readback"


def test_a_reply_that_names_no_class_is_asked_again(s):
    first = s.handle("ketamine eighty nine kilos iv")
    assert s.handle("iv").say == first.say


def test_a_stated_route_counts_only_the_entries_on_it(s):
    """"epinephrine IM": anaphylaxis only, so no question."""
    assert s.handle("epinephrine im eighty kilos").say == \
        "Epinephrine, anaphylaxis, IM, eighty kilos. Confirm?"


# ── A34 / A35: the route ───────────────────────────────────────────────────

def test_a34_a_route_with_no_entry_for_it_holds_and_offers_nothing(s):
    turn = s.handle("morphine for pain in eighty kilos")
    assert turn.kind == "hold"
    assert turn.text == "No signed IN dose of morphine for pain."


def test_a34_iv_and_io_are_one_route(s):
    s.handle("ketamine for agitation io eighty kilos")
    assert s.handle("confirm").say.startswith("Ketamine one hundred and sixty milligrams.")


def test_a35_ketamine_for_pain_im_serves_the_signed_entry_not_2_mg_per_kg(s):
    s.handle("ketamine for pain im eighty kilos")
    assert s.handle("confirm").say.startswith("Ketamine forty milligrams.")


# ── F-1: weight confidence; child gates ────────────────────────────────────

def test_f1_an_estimate_never_doses(s):
    assert "estimate" in s.handle("ketamine for agitation iv estimated eighty kilos").say
    assert s.handle("confirm").say == "Nothing to confirm."


def test_f1_an_estimate_under_the_ceiling_is_still_a_child(s):
    s.handle("morphine for pain iv estimated twenty kilos")
    assert s.handle("twenty kilos").say == "Morphine, pain, IV, child, twenty kilos. Confirm?"


def test_a_child_with_no_weight_is_asked_even_for_a_fixed_dose(s):
    """Epinephrine anaphylaxis is 0.15 mg fixed; a child still gets nothing without a weight."""
    assert s.handle("child epinephrine for anaphylaxis").say == "Weight?"


def test_a_known_age_decides_child_in_both_directions(s):
    s.handle("ten years")
    s.handle("forty five years")
    assert s.handle("morphine for pain iv eighty kilos").say == \
        "Morphine, pain, IV, forty-five years, eighty kilos. Confirm?"


def test_40_kg_is_not_a_child_39_is(s):
    assert "child" not in s.handle("morphine for pain iv forty kilos").say
    s2 = boot(BANK)
    assert "child" in s2.handle("morphine for pain iv thirty nine kilos").say


def test_65_a_stated_age_under_the_floor_blocks_the_entry(s):
    """OWNER RULING 2026-09-18 (#65): ketamine, age under 3 months."""
    turn = s.handle("ketamine for pain iv two months five kilos")
    assert turn.kind == "hold"
    assert turn.text == "No signed dose of ketamine for this age."


def test_65_at_the_floor_the_entry_serves(s):
    assert s.handle("ketamine for pain iv three months five kilos").kind == "readback"


# ── A39: unsigned holds; a pending question clears ─────────────────────────

def test_a39_after_a_weight_the_hold_is_the_same(s):
    s.handle("seventy five kilos")
    assert s.handle("magnesium").text == "No signed dose for magnesium."


def test_a39_after_a_pending_question_the_hold_is_the_same(s):
    s.handle("ketamine for pain")
    assert s.handle("magnesium").text == "No signed dose for magnesium."


def test_live_log_a_new_drug_clears_the_pending_question(s):
    """"Now I need to give mag": the ketamine question must not swallow it."""
    s.handle("ketamine eighty kilos")
    assert s.handle("morphine for pain iv").say == "Morphine, pain, IV, eighty kilos. Confirm?"


# ── the signed bank's own shape ────────────────────────────────────────────

def test_a_multi_vial_drug_gives_milligrams_only(tmp_path):
    """Pocket has no vial question in its grammar: more than one signed vial is mg only."""
    from engine import vials as v
    kit = {"x": [{"concentration_mg_ml": 1.0, "confirm_required": False},
                 {"concentration_mg_ml": 2.0, "confirm_required": False}]}
    assert v.dose_volume(kit, {"drug": "x", "dilution": None}, 1.0)["volume_ml"] is None


def test_the_read_back_comes_before_any_number_of_the_dose(s):
    readback = s.handle("ketamine for agitation iv eighty kilos")
    assert "milligrams" not in readback.text


def test_a_dose_is_logged_with_a_time():
    records = []
    s = boot(BANK, log=records.append, now=lambda: "2026-11-04T12:00:00Z")
    s.handle("ketamine for agitation iv eighty kilos")
    s.handle("confirm")
    assert len(records) == 1
    r = records[0]
    assert r["time"] == "2026-11-04T12:00:00Z"
    assert (r["drug"], r["route"], r["weight_kg"], r["dose"]) == ("ketamine", "IV", 80.0, "160 mg")
    assert r["bank_hash"] == s.announce.data["hash"]


def test_a_cancelled_dose_is_not_logged():
    records = []
    s = boot(BANK, log=records.append)
    s.handle("ketamine for agitation iv eighty kilos")
    s.handle("cancel")
    assert records == []
