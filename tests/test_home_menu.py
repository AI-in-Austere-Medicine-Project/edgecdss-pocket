"""Home menu, help and command lists (owner, 2026-11-21).

Owner: "Goal: someone who has never seen Pocket is using it within a few minutes. ...
RULE: none of this ever speaks a dose. Names and instructions only. A button press (or
Enter in typed mode) cuts off anything being spoken."

  1. Start-up: "Pocket ready. Research prototype, not for patient care. Say drugs,
     procedures, or help." Set name, version and hash go to the log, not the speaker.
  2. Home menu: "home" returns here from anywhere and repeats the menu line without the
     prototype sentence; "drugs" / "list drugs" reads the signed drug names, then "Say a
     drug name to begin."; "procedures" / "list procedures" the signed procedure names,
     then "Say a procedure name to begin."
  3. Help: the owner's text.
  4. What can I say: in every state, only the commands valid right now.
  5. Hearing: the new phrases are in the grammar, and none collides with a drug
     spelling, a number or a command already in use.
  7. One test per item, plus one proving no menu, list or help output contains a dose.

Item 6 (the web page) is tested in pi-cloud-cdss, which serves the page. The button and
Enter cut-off is in tests/test_device.py.
"""
import json
import os
import pathlib
import re
import wave

import pytest

from engine import words
from engine.bank import load_bank
from engine.procedures import load_procedures
from engine.session import (HELP_SPOKEN, HELP_WRITTEN, HOME_LINE, START_UP_LINE, TEST_NOTICE, Session, boot)
from grammar.parser import NUMBERS, parse
from grammar.vocabulary import (CONTROLS, MENU_CONTROLS, PROCEDURE_TERMS, ROUTES, CONDITIONS, build)

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = ROOT / "bank"
SIGNED = load_bank(BANK)
PROCEDURES = load_procedures(BANK, SIGNED)
VOCAB = build(SIGNED)
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
SOUNDS = json.loads((ROOT / "grammar" / "sounds_like.json").read_text())
NEW_PHRASES = ["home", "drugs", "list drugs", "procedures", "list procedures", "help", "what can i say"]
READBACK = "ketamine for agitation iv eighty kilos"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _session(log=None):
    """As boot(BANK) gives it, with the bank loaded once (the suite stays fast)."""
    return Session(SIGNED, clock=Clock(), log=log, procedures=PROCEDURES)


def _in_readback():
    s = _session()
    assert s.handle(READBACK).kind == "readback"
    return s


def _in_procedure():
    s = _session()
    s.handle("rsi 80kg")
    s.handle("next")
    return s


def _at_question():
    s = _session()
    for p in ("failed airway 80kg", "next", "next"):
        t = s.handle(p)
    assert t.kind == "ask" and t.written_text.startswith("Can you mask ventilate?")
    return s


STATES = {"idle": _session, "read-back": _in_readback, "procedure": _in_procedure,
          "question": _at_question}


# ── 1. start-up ─────────────────────────────────────────────────────────────

def test_1_start_up_says_pocket_ready_and_logs_the_set_version_and_hash():
    man = json.loads((BANK / "manifest.json").read_text())
    records = []
    s = boot(BANK, clock=Clock(), log=records.append)
    assert START_UP_LINE == ("Pocket ready. Research prototype, not for patient care. "
                             "Say drugs, procedures, or help.")
    assert s.announce.kind == "boot"
    assert s.announce.text == s.announce.written_text == START_UP_LINE
    for not_said in ("PFC", "set", "version", "one point four", man["sha256"]["bank.json"][:8]):
        assert not_said not in s.announce.text
    assert records[0]["event"] == "boot" and records[0]["set"] == "PFC set"
    assert records[0]["bank_version"] == man["bank_version"]
    assert records[0]["bank_hash"] == man["sha256"]["bank.json"]


# ── 2. home menu ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", STATES)
def test_2_home_returns_from_anywhere_with_the_menu_line(state):
    s = STATES[state]()
    t = s.handle("home")
    assert HOME_LINE == "Pocket ready. Say drugs, procedures, or help."
    assert (t.kind, t.text, t.written_text) == ("menu", HOME_LINE, HOME_LINE)
    assert "Research prototype" not in t.text
    assert s.handle("next").text == "No steps running."          # no procedure left
    assert s.handle("yes").text == "Nothing to confirm."         # no read-back left
    assert s._logged == 0


def test_2_home_keeps_the_patient():
    s = _in_procedure()
    s.handle("home")
    assert s.patient.weight_kg == 80
    assert s.handle("failed airway").written_text.startswith("Failed airway, adult, eighty kilos.")


def _signed_drug_names():
    return sorted({VOCAB.listed_name(d) for d in load_bank(BANK).signed_drugs})


@pytest.mark.parametrize("said", ["drugs", "list drugs"])
def test_2_drugs_reads_the_signed_drug_names_then_how_to_begin(said):
    t = _session().handle(said)
    names = _signed_drug_names()
    assert t.kind == "menu"
    assert t.written_text == f"Signed drugs: {', '.join(names)}. Say a drug name to begin."
    assert len(names) == len(load_bank(BANK).signed_drugs) == 25


def test_2_every_listed_drug_name_is_heard_as_that_drug():
    bank = load_bank(BANK)
    for drug in bank.signed_drugs:
        name = VOCAB.listed_name(drug)
        p = parse(name, VOCAB)
        assert [m.generics for m in p.drugs] == [(drug,)], (drug, name)
        # The model hears it: each word is in the grammar, or the name has a spelling there
        # (moxifloxacin is not in the model's own word list, and is heard by its spellings).
        grammar = set(GRAMMAR["words"])
        assert (all(w in grammar for w in name.split())
                or set(SOUNDS["spellings"].get(name, [])) & grammar), name


def test_2_no_unsigned_drug_is_listed():
    bank = load_bank(BANK)
    unsigned = {e["drug"] for e in bank.entries} - set(bank.signed_drugs)
    text = _session().handle("drugs").written_text.lower()
    for drug in unsigned:
        assert f" {words.say_name(drug).lower()}," not in text and f" {drug.lower()}." not in text


@pytest.mark.parametrize("said", ["procedures", "list procedures"])
def test_2_procedures_reads_the_signed_procedure_names_then_how_to_begin(said):
    s = _session()
    t = s.handle(said)
    assert t.kind == "menu"
    assert t.written_text == ("Signed procedures: rapid sequence intubation, failed airway. "
                              "Say a procedure name to begin.")
    for name in ("rapid sequence intubation", "failed airway"):
        s.handle(name)                               # each name starts its own steps
        assert s._run is not None and s._run.proc.title == name
        s.handle("home")


def test_2_procedures_come_from_the_signed_procedures_loaded():
    s = _session()
    s.procedures = {k: v for k, v in s.procedures.items() if k == "rsi"}
    assert s.handle("procedures").written_text.startswith("Signed procedures: rapid sequence intubation.")
    s.procedures = {}
    assert s.handle("procedures").written_text == "No signed procedures."


# ── 3. help ─────────────────────────────────────────────────────────────────

OWNER_HELP = (
    "Pocket gives signed drug doses and procedure steps by voice. Press the button, wait for "
    "the beep, speak, then press again. For a drug, say the drug, what it is for, the route and "
    "the weight. For example: ketamine for agitation, I V, eighty kilos. Pocket repeats what it heard. "
    "Say yes to hear the dose, or no to cancel. For a procedure, say its name and the weight. For "
    "example: R S I, eighty kilos. Then say next, back or repeat. Say new patient to start again. "
    "Say drugs or procedures to hear what Pocket knows. Say what can I say at any time.")


@pytest.mark.parametrize("state", STATES)
def test_3_help_speaks_the_owners_text_and_changes_nothing(state):
    s = STATES[state]()
    before = (s._pending, s._misses, s._run and (s._run.i, s._run.answer), s.req)
    t = s.handle("help")
    assert t.kind == "menu"
    # Spoken: the owner's text, with the route said as the owner's route words (2026-11-19).
    assert t.text == HELP_SPOKEN == OWNER_HELP.replace("I V,", "eye vee,")
    # Shown: the letters.
    assert t.written_text == HELP_WRITTEN == OWNER_HELP.replace("I V,", "IV,").replace("R S I,", "RSI,")
    assert (s._pending, s._misses, s._run and (s._run.i, s._run.answer), s.req) == before


def test_3_each_help_example_asks_nothing_first():
    """Owner, 2026-11-21: the drug example goes straight to a read-back, with no question."""
    drug, procedure = re.findall(r"For example: ([^.]+)\.", HELP_WRITTEN)
    assert drug == "ketamine for agitation, IV, eighty kilos" and procedure == "RSI, eighty kilos"
    for said, spoken in ((drug, False), ("ketamine for agitation i v eighty kilos", True)):
        t = _session().handle(said, spoken=spoken)
        assert (t.kind, t.written_text) == ("readback", "Ketamine, agitation, IV, eighty kilos. Confirm?")
    for said in (procedure, "r s i eighty kilos"):
        t = _session().handle(said, spoken=True)
        assert t.kind == "step" and "Step one of eleven." in t.written_text, t.written_text


# ── 4. what can I say ───────────────────────────────────────────────────────

CAN_SAY = {
    "idle": "Say drugs, procedures, help, new patient, or a drug or procedure name.",
    "read-back": "Say yes, no, repeat, or why.",
    "procedure": "Say next, back, repeat, start over, failed airway, or home.",
    "question": "Say yes or no.",
}


@pytest.mark.parametrize("state", STATES)
def test_4_what_can_i_say_lists_only_what_works_now_and_changes_nothing(state):
    s = STATES[state]()
    t = s.handle("what can i say")
    assert t.kind == "menu" and t.written_text == CAN_SAY[state]
    if state == "read-back":               # not a miss: still pending, still one yes away
        assert s._misses == 0 and s.handle("yes").kind == "dose"
    if state == "question":
        assert s.handle("no").written_text.startswith("Step three of three. NO")
    if state == "procedure":
        assert s.handle("next").written_text.startswith("Step three of eleven.")


def test_4_each_command_it_lists_does_work_in_that_state():
    assert _in_readback().handle("why").kind == "why"
    assert _in_readback().handle("repeat").kind == "repeat"
    assert _in_readback().handle("no").text == "Cancelled."
    for cmd, kind in (("next", "step"), ("back", "step"), ("repeat", "repeat"),
                      ("start over", "step"), ("failed airway", "step"), ("home", "menu")):
        assert _in_procedure().handle(cmd).kind == kind, cmd
    for cmd in ("drugs", "procedures", "help", "new patient"):
        assert _session().handle(cmd).kind in ("menu", "control"), cmd


def test_4_waiting_for_a_weight_or_a_pair_says_what_answers_it():
    s = _session()
    s.handle("rsi")
    assert s.handle("what can i say").written_text == "Say the weight, for example eighty kilos."
    s = _session()
    s.handle("epinephrine", spoken=True)
    assert s.handle("what can i say").written_text == "Say epinephrine or norepinephrine."


# ── 5. hearing ──────────────────────────────────────────────────────────────

def test_5_the_new_phrases_are_commands_and_in_the_grammar():
    for phrase in NEW_PHRASES:
        assert phrase in MENU_CONTROLS and phrase in CONTROLS, phrase
        assert parse(phrase, VOCAB).controls == [phrase], phrase
        for w in phrase.split():
            assert w in GRAMMAR["words"], w


def test_5_no_new_phrase_collides_with_a_drug_a_spelling_a_number_or_a_command():
    old_controls = [c for c in CONTROLS if c not in MENU_CONTROLS]
    drug_words = {w for t in VOCAB.drug_terms for w in t.split()}
    spelled = {w for s in SOUNDS.get("spellings", SOUNDS) for w in str(s).split()}
    others = (set(VOCAB.drug_terms) | set(VOCAB.class_terms) | set(ROUTES) | set(CONDITIONS)
              | set(PROCEDURE_TERMS) | set(old_controls) | VOCAB.label_words)
    for phrase in NEW_PHRASES:
        assert phrase not in others, phrase
        for w in phrase.split():
            assert w not in NUMBERS, (phrase, w)
            assert w not in drug_words and w not in spelled, (phrase, w)
            assert w not in VOCAB.label_words, (phrase, w)
            assert w == "i" or w not in {x for c in old_controls for x in c.split()}, (phrase, w)
    # No old phrase is now read as a menu command.
    for term in list(VOCAB.drug_terms) + list(old_controls) + list(PROCEDURE_TERMS):
        assert not set(parse(term, VOCAB).controls) & set(MENU_CONTROLS), term


def test_5_a_drug_said_with_a_menu_word_is_still_one_command_at_a_time():
    assert _session().handle("help ketamine").text == "One command at a time."


MODEL = pathlib.Path(os.getenv("POCKET_VOSK_MODEL", pathlib.Path.home() / "pocket-web" / "models"
                                / "vosk-model-small-en-us-0.15"))
CLIPS = sorted((ROOT / "tests" / "fixtures" / "clips" / "menu").glob("*.wav"))


def _vosk():
    try:
        import vosk
        return vosk
    except ImportError:
        return None


@pytest.fixture(scope="module")
def hearing():
    if not (MODEL.exists() and _vosk()):
        pytest.skip(f"needs vosk and the model at {MODEL}")
    from voice.hear import Hearing
    vosk = _vosk()
    vosk.SetLogLevel(-1)
    return Hearing(vosk.Model(str(MODEL)), GRAMMAR, VOCAB)


def test_5_there_is_a_piper_and_three_kokoro_takes_of_every_new_phrase():
    said = {c.stem.split("__")[1].replace("_", " ") for c in CLIPS}
    assert said == set(NEW_PHRASES)
    assert len(CLIPS) == 4 * len(NEW_PHRASES)


@pytest.mark.parametrize("clip", CLIPS, ids=lambda c: c.stem)
def test_5_each_new_phrase_is_heard_as_itself_never_as_a_drug_or_a_dose_word(hearing, clip):
    phrase = clip.stem.split("__")[1].replace("_", " ")
    with wave.open(str(clip)) as w:
        pcm = w.readframes(w.getnframes())
    u = hearing.start()
    u.feed(pcm)
    heard, text, _ = u.finish()
    p = parse(text, VOCAB)
    # Never a collision: no drug, no confirm word, no other command.
    assert not p.drugs and not set(p.controls) & {"yes", "confirm", "correct", "affirmative"}, heard
    assert set(p.controls) <= {phrase}, heard
    if clip.stem in KNOWN_MISSES:                      # a miss: "Not recognised.", nothing else
        assert (heard, p.controls) == (KNOWN_MISSES[clip.stem], []), heard
    else:
        assert p.controls == [phrase], heard


# Measured 2026-11-21 (27 of 28 heard as said). A miss is pinned, so a change shows here.
KNOWN_MISSES = {"kokoro__drugs__bf_lily": "drugs as"}


# ── 7. never a dose ─────────────────────────────────────────────────────────

_DOSE = re.compile(r"(?i)\b(milligrams?|micrograms?|grams?|mg|mcg|mils?|ml|units?|per kilo\w*)\b|\d")


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("said", NEW_PHRASES)
def test_7_no_menu_list_or_help_output_contains_a_dose(state, said):
    records = []
    s = _session(log=records.append)
    {"idle": lambda: None, "read-back": lambda: s.handle(READBACK),
     "procedure": lambda: [s.handle("rsi 80kg"), s.handle("next")],
     "question": lambda: [s.handle(p) for p in ("failed airway 80kg", "next", "next")]}[state]()
    t = s.handle(said)
    assert t.kind == "menu"
    for line in (t.text, t.written_text):
        assert not _DOSE.search(line), (said, state, line)
    assert "dose" not in t.data and [r for r in records if r.get("event") != "boot"] == []
    assert not _DOSE.search(s.announce.text)


def test_7_a_test_bank_says_its_notice_before_pocket_ready(tmp_path):
    from tests.test_test_bank import make_test_bank
    os.environ["POCKET_TEST"] = "1"
    try:
        s = boot(make_test_bank(tmp_path))
    finally:
        del os.environ["POCKET_TEST"]
    assert s.announce.text == f"{TEST_NOTICE} {START_UP_LINE}"
