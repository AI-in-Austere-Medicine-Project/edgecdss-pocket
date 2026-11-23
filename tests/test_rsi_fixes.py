"""Fixes from the owner's typed RSI run on the Radxa (2026-11-21).

1. Typed numbers for weight and age: "80kg", "80 kg", "23kg".
2. "repeat" re-reads the current step, not the last message.
3. "start over" restarts the current procedure from step one.
4. Failed airway asks "Can you mask ventilate?", waits for yes or no, then reads that
   branch, in the signed text of each branch.
5. The start-up line is short: the set name and version. The full version and hash go
   to the log.
"""
import json
import pathlib
import shutil

import pytest

from engine.procedures import ProceduresRefused, load_procedures
from engine.session import TEST_NOTICE, boot
from grammar.parser import parse
from grammar.vocabulary import build
from engine.bank import load_bank
from engine.bank import PFC_RETIRED, RETIRED_FILE  # the retired PFC set: fixture data (2026-11-23)

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = PFC_RETIRED
VOCAB = build(load_bank(BANK, retired_ok=True))

FA1 = "Unable to Intubate: Can You Mask Ventilate? Improve position, video laryngoscope, gum elastic bougie change blade/operator."
FA2 = "More than ≈ 3 attempts at intubation may abolish your ability to mask ventilate due to edema caused by laryngoscopy."
FA3 = "YES → Surgical airway (Cricothyroidotomy or tracheostomy)."
FA4 = "NO → Emergency pathway. Seconds matter. Supraglottic airway or Surgical cricothyroidotomy."
P5 = ("Avoid surgical airway in <12 years old - use needle cricothyroidotomy (12-14 gauge), "
      "tracheostomy preferred over surgical cricothyroidotomy")
ASK = "Can you mask ventilate? Say yes or no."
STEP_6 = "Administer medications: Initiate RSI."


def _doses(s):
    return [r for r in s.records if "drug" in r]


# ── 1. typed numbers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed,kg", [("80kg", 80), ("80 kg", 80), ("23kg", 23), ("80 kilos", 80),
                                      ("80KG", 80), ("80.5 kg", 80.5), ("176 lbs", 79.8),
                                      ("100kg", 100)])
def test_a_typed_weight_is_read(typed, kg):
    p = parse(typed, VOCAB)
    assert not p.unknown and p.weight is not None and p.weight.kg == kg


@pytest.mark.parametrize("typed,years", [("6 years", 6), ("14 years", 14), ("18 months", 1.5)])
def test_a_typed_age_is_read(typed, years):
    p = parse(typed, VOCAB)
    assert not p.unknown and p.age is not None and p.age.years == years


def test_typed_numbers_read_exactly_as_their_words():
    for typed, said in [("80kg", "eighty kilos"), ("23 kg", "twenty three kilos"),
                        ("6 years", "six years"), ("80.5 kg", "eighty point five kilos")]:
        assert parse(typed, VOCAB) == parse(said, VOCAB), typed


@pytest.mark.parametrize("weight", ["80kg", "80 kg"])
def test_rsi_takes_a_typed_weight_at_the_weight_question(weight):
    s = boot(BANK, retired_ok=True)
    assert s.handle("rsi").written == "Weight?"
    turn = s.handle(weight)
    assert turn.kind == "step"
    assert turn.written.startswith("Rapid sequence intubation, adult, eighty kilos. Step one of eleven.")


def test_rsi_with_a_typed_weight_in_one_phrase_and_a_child_by_typed_age():
    s = boot(BANK, retired_ok=True)
    assert s.handle("rsi 80kg").written.startswith("Rapid sequence intubation, adult, eighty kilos.")
    s = boot(BANK, retired_ok=True)
    turn = s.handle("rsi child 4 years 23kg")
    assert turn.written.startswith("Rapid sequence intubation, child, four years, twenty-three kilos.")


def test_a_typed_amount_stays_words_and_the_engine_gives_its_own_dose():
    """B1 holds for typed numbers: a stated amount is read back as said, never computed on."""
    s = boot(BANK, retired_ok=True)
    readback = s.handle("ketamine 500 mg for agitation iv 80kg")
    assert readback.kind == "readback"
    assert "You said five hundred mg." in readback.written
    dose = s.handle("confirm")
    assert dose.written.startswith("Ketamine one hundred and sixty milligrams.")


def test_a_typed_number_alone_still_asks_the_unit():
    s = boot(BANK, retired_ok=True)
    s.handle("rsi")
    assert s.handle("80").written == "Kilos or pounds?"


# ── 2. repeat re-reads the current step ─────────────────────────────────────

def _at_step_6(s):
    turn = s.handle("rsi eighty kilos")
    while STEP_6 not in turn.written:
        turn = s.handle("next")
    return turn


def test_repeat_after_a_cancelled_read_back_rereads_the_step():
    s = boot(BANK, retired_ok=True)
    step = _at_step_6(s)
    assert s.handle("ketamine").kind == "readback"
    assert s.handle("no").written == "Cancelled."
    again = s.handle("repeat")
    assert again.kind == "repeat" and again.written == step.written


def test_repeat_after_a_dose_at_a_step_rereads_the_step():
    s = boot(BANK, retired_ok=True)
    step = _at_step_6(s)
    s.handle("ketamine")
    assert s.handle("confirm").kind == "dose"
    assert s.handle("repeat").written == step.written


def test_repeat_after_why_rereads_the_step_not_the_source():
    s = boot(BANK, retired_ok=True)
    step = _at_step_6(s)
    s.handle("ketamine")
    s.handle("confirm")
    s.handle("why")
    assert s.handle("repeat").written == step.written


def test_repeat_while_a_read_back_waits_is_still_the_read_back():
    s = boot(BANK, retired_ok=True)
    _at_step_6(s)
    readback = s.handle("ketamine")
    assert s.handle("repeat").written == readback.written


def test_repeat_with_no_steps_running_is_still_the_last_message():
    s = boot(BANK, retired_ok=True)
    s.handle("ketamine for agitation iv eighty kilos")
    s.handle("confirm")
    why = s.handle("why")
    assert s.handle("repeat").written == why.written


# ── 3. start over ───────────────────────────────────────────────────────────

def test_start_over_goes_back_to_step_one_and_keeps_the_weight():
    s = boot(BANK, retired_ok=True)
    first = s.handle("rsi eighty kilos")
    for _ in range(4):
        s.handle("next")
    again = s.handle("start over")
    assert again.kind == "step" and again.written == first.written
    assert "Step two of eleven." in s.handle("next").written


def test_start_over_after_a_cancelled_read_back_drops_the_request():
    s = boot(BANK, retired_ok=True)
    _at_step_6(s)
    s.handle("ketamine")
    s.handle("no")
    turn = s.handle("start over")
    assert turn.written.startswith("Rapid sequence intubation, adult, eighty kilos. Step one of eleven.")
    assert s.handle("confirm").written == "Nothing to confirm."


def test_start_over_with_no_steps_running():
    assert boot(BANK, retired_ok=True).handle("start over").written == "No steps running."


def test_start_over_while_a_read_back_waits_is_a_miss():
    s = boot(BANK, retired_ok=True)
    _at_step_6(s)
    s.handle("ketamine")
    assert s.handle("start over").written == "Say confirm or cancel."


def test_start_over_restarts_failed_airway_after_its_answer():
    s = boot(BANK, retired_ok=True)
    first = s.handle("failed airway")
    s.handle("next"), s.handle("next"), s.handle("no")
    assert s.handle("start over").written == first.written


def test_start_and_over_are_in_the_grammar():
    words = set(json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())["words"])
    assert {"start", "over", "yes", "no"} <= words


# ── 4. failed airway: the question, then its branch ─────────────────────────

def _to_question(start="failed airway"):
    s = boot(BANK, retired_ok=True)
    one = s.handle(start)
    two = s.handle("next")
    ask = s.handle("next")
    return s, one, two, ask


def test_failed_airway_reads_two_steps_then_asks_the_question():
    s, one, two, ask = _to_question()
    assert one.written == f"Failed airway. Step one of three. {FA1}"
    assert two.written == f"Step two of three. {FA2}"
    assert ask.kind == "ask" and ask.written == ASK


@pytest.mark.parametrize("answer,text", [("yes", FA3), ("no", FA4)])
def test_the_answer_reads_its_branch_in_the_signed_text(answer, text):
    s, *_ , ask = _to_question()
    turn = s.handle(answer)
    assert turn.kind == "step" and turn.written == f"Step three of three. {text}"
    other = FA4 if answer == "yes" else FA3
    assert other not in turn.written
    assert s.handle("next").written == "End of failed airway steps."


@pytest.mark.parametrize("start", ["failed airway child six years", "failed airway child 6 years",
                                   "failed airway child twenty kilos", "failed airway child"])
def test_a_child_under_12_or_of_unknown_age_hears_p5_on_yes(start):
    s, *_ = _to_question(start)
    assert s.handle("yes").written == f"Step three of three. {P5}"
    s, *_ = _to_question(start)
    assert s.handle("no").written == f"Step three of three. {FA4}"


def test_a_child_of_14_hears_the_surgical_airway_line_on_yes():
    s, *_ = _to_question("failed airway child fourteen years")
    assert s.handle("yes").written == f"Step three of three. {FA3}"


@pytest.mark.parametrize("said", ["next", "confirm", "correct", "negative", "eighty kilos", "why"])
def test_at_the_question_only_yes_or_no_answers(said):
    s, *_ = _to_question()
    assert s.handle(said).written == "Say yes or no."
    assert s.handle("no").written == f"Step three of three. {FA4}"


def test_at_the_question_repeat_back_and_cancel():
    s, one, two, ask = _to_question()
    assert s.handle("repeat").written == ASK
    assert s.handle("back").written == two.written
    assert s.handle("next").written == ASK
    s.handle("yes")
    assert s.handle("repeat").written == f"Step three of three. {FA3}"
    assert s.handle("back").written == ASK
    assert s.handle("cancel").written == "Cancelled."
    assert s.handle("yes").written == "Nothing to confirm."


def test_the_question_is_signed_text_and_the_branches_are_the_signed_steps():
    raw = json.loads((BANK / "procedures.json").read_text())
    fa = next(p for p in raw["procedures"] if p["name"] == "failed airway")
    steps = {s["id"]: s["text"] for s in fa["steps"]}
    assert steps == {"FA1": FA1, "FA2": FA2, "FA3": FA3, "FA4": FA4, "P5": P5}
    assert fa["order"] == {"adult": ["FA1", "FA2"], "child": ["FA1", "FA2"]}
    assert fa["branch"] == {"ask": "Can you mask ventilate?", "yes": "FA3", "no": "FA4"}
    assert fa["branch"]["ask"].lower() in steps["FA1"].lower()


def _edited(tmp_path, edit):
    d = tmp_path / "bank"
    shutil.copytree(BANK, d, ignore=shutil.ignore_patterns(RETIRED_FILE))   # a scratch copy, not retired
    raw = json.loads((d / "procedures.json").read_text())
    edit(next(p for p in raw["procedures"] if p["name"] == "failed airway"))
    (d / "procedures.json").write_text(json.dumps(raw))
    return d


@pytest.mark.parametrize("edit", [
    lambda p: p["branch"].update(ask="Can you intubate?"),       # not in the signed text
    lambda p: p["branch"].update(yes="FA9"),                     # no such step
    lambda p: p["branch"].pop("no"),                             # one branch only
])
def test_a_branch_that_is_not_signed_refuses_the_file(tmp_path, edit):
    d = _edited(tmp_path, edit)
    with pytest.raises(ProceduresRefused):
        load_procedures(d)
    assert boot(d).handle("failed airway").written == "No signed steps for failed airway."


def test_the_question_is_said_and_written_alike():
    s, *_, ask = _to_question()
    assert ask.say == ask.written == ASK


# ── 5. the start-up line ────────────────────────────────────────────────────

def test_the_start_up_line_names_no_set_and_no_version():
    """Superseded by the home menu's start-up line (owner, 2026-11-21: tests/test_home_menu.py);
    the set named in it (2026-11-22) was removed with the one drug list (owner, 2026-11-23).
    The set name and version are still logged, never spoken."""
    s = boot(BANK, retired_ok=True)
    assert s.announce.kind == "boot"
    assert s.announce.written == s.announce.say
    assert "PFC set" not in s.announce.say and "version" not in s.announce.say


def test_the_full_version_and_hash_go_to_the_log():
    man = json.loads((BANK / "manifest.json").read_text())
    records = []
    s = boot(BANK, retired_ok=True, log=records.append, now=lambda: "2026-11-21T12:00:00Z")
    assert records == [{"event": "boot", "time": "2026-11-21T12:00:00Z", "set": "PFC set",
                        "bank_version": man["bank_version"], "bank_hash": man["sha256"]["bank.json"],
                        "kit_id": man["kit_id"], "test": False}]
    assert _doses(s) == []
    assert s.handle("log").written == "Zero doses logged."


def test_a_refused_bank_logs_nothing_and_says_why():
    records = []
    s = boot(ROOT / "no-such-bank", log=records.append)
    assert s.announce.kind == "refused" and records == []
