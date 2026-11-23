"""RSI holds whole for a child (owner, 2026-11-23): "hold the whole procedure for a child,
with "No signed RSI steps for a child." The formulary prints NONE for a child paralytic
and has no atropine pre-dose, so do not read a partial procedure."

The child's steps (P1 to P4) and their dose links stay in bank/ems/procedures.json, for
the record. None of them is read.
"""
import copy
import json

import pytest

from engine.bank import BANK_DIR, load_bank
from engine.procedures import ProceduresRefused, load_procedures
from engine.session import boot

CHILD_HELD = "No signed RSI steps for a child."
RAW = json.loads((BANK_DIR / "procedures.json").read_text())


def _walk(*said):
    s = boot()
    turns = [s.handle(line, spoken=True) for line in said]
    return s, turns


@pytest.mark.parametrize("said", [("rsi child twenty kilos",), ("rsi", "twenty kilos"),
                                  ("rsi", "child", "twenty kilos"), ("rsi twenty kilos",),
                                  ("rapid sequence intubation five years old eighteen kilos",)])
def test_a_child_hears_the_hold_and_no_step(said):
    s, turns = _walk(*said)
    assert (turns[-1].kind, turns[-1].say) == ("hold", CHILD_HELD)
    assert all(t.kind != "step" for t in turns)
    assert s.handle("next").say == "No steps running."


def test_a_child_said_during_an_adult_run_ends_it_with_the_hold():
    s, turns = _walk("rsi eighty kilos", "next", "child")
    assert turns[0].kind == "step"
    assert (turns[-1].kind, turns[-1].say) == ("hold", CHILD_HELD)
    assert s.handle("next").say == "No steps running."


def test_a_child_weight_said_during_an_adult_run_ends_it_too():
    s, turns = _walk("rsi", "eighty kilos", "next", "twelve kilos")
    assert (turns[-1].kind, turns[-1].say) == ("hold", CHILD_HELD)


def test_no_child_step_or_dose_is_reachable():
    s, _ = _walk("rsi child twenty kilos")
    for line in ("next", "next", "repeat", "start over", "ketamine"):
        t = s.handle(line, spoken=True)
        assert t.kind != "step" and "milligram" not in t.say, (line, t.say)


def test_an_adult_still_hears_the_steps():
    _, turns = _walk("rsi eighty kilos")
    assert turns[0].kind == "step" and "Step one of eleven" in turns[0].say


def test_failed_airway_for_a_child_is_unchanged():
    _, turns = _walk("failed airway child twenty kilos")
    assert turns[0].kind == "step" and "Unable to Intubate" in turns[0].say


def test_the_hold_is_recorded_as_the_owners_with_its_date_and_why():
    rsi = next(p for p in RAW["procedures"] if p["name"] == "rsi")
    held = rsi["child_held"]
    assert held["say"] == CHILD_HELD and held["by"] == "owner" and held["date"] == "2026-11-23"
    assert "NONE" in held["why"] and "atropine" in held["why"]
    assert rsi["order"]["child"][:3] == ["1", "P1", "2"]            # the signed order stays, unread
    assert load_procedures(BANK_DIR, load_bank(BANK_DIR))["rsi"].child_held == CHILD_HELD


@pytest.mark.parametrize("field", ["say", "by", "date"])
def test_a_child_hold_without_its_line_owner_or_date_refuses_the_file(tmp_path, field):
    raw = copy.deepcopy(RAW)
    rsi = next(p for p in raw["procedures"] if p["name"] == "rsi")
    rsi["child_held"][field] = ""
    import shutil
    shutil.copytree(BANK_DIR, tmp_path / "ems")
    (tmp_path / "ems" / "procedures.json").write_text(json.dumps(raw))
    with pytest.raises(ProceduresRefused, match="child hold"):
        load_procedures(tmp_path / "ems", load_bank(tmp_path / "ems"))
