"""The administration time, said with the dose (owner, 2026-11-22): "wherever a signed
entry states an administration time, Pocket says it with the dose, e.g. '...over five
minutes.'"

A time is "over N minutes / seconds / hours" (or a range, "over 3-5 minutes") in a
caution Pocket serves with the entry. For an EMS entry the printed row's route cell is
the entry's own, so a time there counts too ("IV/IO infusion over 10min"). A PFC quote is
free text that can cover other routes (ketamine IM's quote times the IV push), so it does
not. "Slow push" is not a time.
"""
import json
import pathlib

import pytest

from engine.session import admin_time, boot

BANK = pathlib.Path(__file__).resolve().parents[1] / "bank"
PFC = json.loads((BANK / "bank.json").read_text())["entries"]


def _entry(serve=(), quote="", set_="PFC"):
    return {"serve_cautions": list(serve), "quote": quote, "set": set_}


@pytest.mark.parametrize("text, said", [
    ("Give over 10 minutes.", "Over ten minutes."),
    ("Over 15 minutes", "Over fifteen minutes."),
    ("Push over 60 SECONDS.", "Over sixty seconds."),
    ("Slow IV push over 3-5 minutes.", "Over three to five minutes."),
    ("over 10–15 minutes", "Over ten to fifteen minutes."),
    ("over 1 min", "Over one minute."),
    ("Infuse over 10min", "Over ten minutes."),
    ("over 2 hours", "Over two hours."),
    ("Give IV/IO over 10 minutes (Better) or over 30 minutes (Best).", "Over ten minutes or over thirty minutes."),
])
def test_a_stated_time_is_said_in_words(text, said):
    assert admin_time(_entry([text])) == said


def test_no_time_is_said_where_none_is_stated():
    assert admin_time(_entry(["Slow IV push.", "Every 24 hours.", "Repeat in 5 min."])) is None
    assert admin_time(_entry([])) is None


def test_the_same_time_twice_is_said_once():
    assert admin_time(_entry(["over 10 minutes", "Loading dose over 10 minutes."])) == "Over ten minutes."


def test_an_ems_rows_route_cell_counts_and_a_pfc_quote_does_not():
    assert admin_time(_entry([], "Pain | 0.2mg/kg Max: 0.1mL | IV/IO infusion over 10min", "EMS")) == "Over ten minutes."
    assert admin_time(_entry([], "Over 10 min is the indication | 1 mg | IV", "EMS")) is None   # route cell only
    ket_im = [e for e in PFC if e["drug"] == "ketamine" and e["route"] == "IM" and "over 1 min" in (e["quote"] or "")]
    assert ket_im and admin_time(ket_im[0]) is None


def test_every_signed_pfc_entry_that_states_a_time_says_it():
    timed = [e for e in PFC if admin_time(e)]
    assert len(timed) == 13
    assert {e["drug"] for e in timed} == {"ketamine", "fentanyl", "ceftriaxone", "tranexamic acid",
                                          "levetiracetam", "calcium gluconate", "sodium chloride 3%"}


def test_the_time_follows_the_dose_and_volume():
    s = boot(BANK)
    s.handle("tranexamic acid for haemorrhage iv adult")
    assert s.handle("confirm").say == "Tranexamic acid two grams. Twenty mils of one hundred. Over ten minutes."
    s = boot(BANK)
    s.handle("ceftriaxone for sepsis iv adult")
    assert s.handle("confirm").say == ("Ceftriaxone two grams. No signed vial, no volume. "
                                       "Over ten minutes or over thirty minutes.")


def test_ems_entries_say_their_time_including_the_owners_four_rulings():
    ems = json.loads((BANK / "ems" / "bank.json").read_text())["entries"]
    assert len([e for e in ems if admin_time(e)]) == 28
    said = {e["ems_id"]: admin_time(e) for e in ems}
    assert said["EMS-037"] == "Over ten minutes."
    assert said["EMS-149"] == said["EMS-150"] == said["EMS-151"] == "Over five minutes."
    s = boot(BANK / "ems")
    s.handle("magnesium sulfate for torsades iv twenty kilos")
    assert s.handle("confirm").say.endswith("Two mils of five hundred. Over five minutes.")   # declared 500 mg/mL
