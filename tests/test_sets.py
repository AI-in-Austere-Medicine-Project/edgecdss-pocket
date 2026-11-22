"""Choosing the set on the device (owner, 2026-11-22): "Let me choose the set on the device
('E M S set' / 'P F C set'), and have the start-up line say which set is loaded."

One session holds both sets. Saying a set's name, letter by letter, loads it from anywhere:
a pending read-back is cancelled and the patient starts again (doses from one set never
mix with the other's patient). The device remembers the set across a power cut.
"""
import pathlib

import pytest

from engine.session import START_UP_LINE, boot, boot_sets, start_up_line
from voice import autostart, spoken

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRS = {"PFC": ROOT / "bank", "EMS": ROOT / "bank" / "ems"}


def _session(chosen="PFC", **kw):
    return boot_sets(DIRS, chosen, **kw)


def test_the_start_up_line_says_which_set_is_loaded():
    s = _session()
    assert s.announce.written == "Pocket ready. PFC set. Research prototype, not for patient care. Say drugs, procedures, or help."
    assert s.announce.say == "Pocket ready. P F C set. Research prototype, not for patient care. Say drugs, procedures, or help."
    assert _session("EMS").announce.say.startswith("Pocket ready. E M S set. Research prototype, not for patient care.")
    assert start_up_line("PFC set") == s.announce.written and "Research prototype, not for patient care." in START_UP_LINE


def test_saying_the_set_loads_it_and_says_so():
    s = _session()
    t = s.handle(spoken.normalise("e m s set"), spoken=True)
    assert t.kind == "menu" and t.say == "E M S set loaded. Research prototype, not for patient care. Say drugs, procedures, or help."
    assert s.set_name == "EMS set" and "adenosine" in s.bank.signed_drugs
    assert "adenosine" in s.handle("drugs").written
    s.handle("adenosine for svt iv adult")
    assert s.handle("confirm").say == "Adenosine twelve milligrams. Four mils of three."
    t = s.handle("pfc set")
    assert t.say.startswith("P F C set loaded.") and s.set_name == "PFC set" and "adenosine" not in s.bank.signed_drugs
    assert s.announce.written.startswith("Pocket ready. PFC set.")      # what a reconnect would say


def test_a_set_change_cancels_a_read_back_and_starts_a_new_patient():
    s = _session()
    assert s.handle("ketamine for agitation iv eighty kilos").kind == "readback"
    s.handle("ems set")
    assert s.handle("confirm").kind != "dose"
    assert s.patient.weight is None


def test_the_device_is_told_the_set_changed_and_remembers_it(tmp_path):
    seen = []
    s = _session(on_set=seen.append)
    s.handle("ems set")
    s.handle("ems set")
    assert seen == ["EMS", "EMS"]
    path = tmp_path / "state" / "set"
    assert autostart.saved_set(path) == "PFC"                     # nothing saved: the PFC set
    autostart.save_set(path, "EMS")
    assert autostart.saved_set(path) == "EMS" and path.read_text() == "EMS\n"
    path.write_text("garbage")
    assert autostart.saved_set(path) == "PFC"


def test_a_set_that_does_not_load_is_named_and_the_other_stays(tmp_path):
    s = boot_sets({"PFC": DIRS["PFC"], "EMS": tmp_path / "nothing"}, "PFC")
    t = s.handle("ems set")
    assert t.say.startswith("E M S set refused:") and s.set_name == "PFC set"
    assert boot_sets({"PFC": DIRS["PFC"], "EMS": tmp_path / "nothing"}, "EMS").set_name == "PFC set"


def test_the_set_words_are_spelled_letters():
    assert spoken.normalise("p f c set") == "pfc set" and spoken.normalise("e m s set") == "ems set"
    assert boot(DIRS["PFC"]).handle("ems set").kind == "menu"          # one set: it says it has no other
