"""The confirm step (owner, 2026-11-16).

Owner: "Confirm words: "confirm", "yes", "correct", "affirmative". Nothing else proceeds.
Cancel words: "no", "cancel", "negative", "stop", "wrong". Reply "Cancelled." and clear the
pending dose; keep the patient's weight and age. Anything else at the confirm step: "Say
confirm or cancel." After two misses, cancel. A pending read-back expires after 30 seconds
and is cancelled, so a later "yes" can never confirm an old dose. Safety test with Piper and
my clips: "no" said 20 times is never heard as a confirm word, and no cancel word is ever
heard as a confirm word. If any confirm word is confusable with a cancel word, drop it."

The owner's gate clips are drug names only; none says a confirm or cancel word, so the
acoustic test uses Piper (the voice the device speaks with: 20 takes of "no", 3 of every
other word) and the three held-out Kokoro voices of the dry run
(tests/fixtures/clips/confirm). It runs with the Vosk model (POCKET_VOSK_MODEL).
"""
import json
import os
import pathlib
import wave

import pytest

from engine.session import boot
from grammar.parser import parse
from grammar.vocabulary import CANCEL_WORDS, CONFIRM_WORDS, build
from engine.bank import load_bank

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = ROOT / "bank"
VOCAB = build(load_bank(BANK))
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
CLIPS = sorted((ROOT / "tests" / "fixtures" / "clips" / "confirm").glob("*.wav"))
MODEL = pathlib.Path(os.getenv("POCKET_VOSK_MODEL", pathlib.Path.home() / "pocket-web" / "models"
                                / "vosk-model-small-en-us-0.15"))
READBACK = "ketamine for agitation iv eighty kilos"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _session():
    clock = Clock()
    return boot(BANK, clock=clock), clock


def _at_readback():
    s, clock = _session()
    assert s.handle(READBACK).kind == "readback"
    return s, clock


# ── the words ───────────────────────────────────────────────────────────────

def test_the_confirm_and_cancel_words_are_the_owners():
    assert set(CONFIRM_WORDS) == {"confirm", "yes", "correct", "affirmative"}
    assert set(CANCEL_WORDS) == {"no", "cancel", "negative", "stop", "wrong"}
    assert not set(CONFIRM_WORDS) & set(CANCEL_WORDS)


def test_every_confirm_and_cancel_word_can_be_heard():
    entries = set(GRAMMAR["words"])
    for w in (*CONFIRM_WORDS, *CANCEL_WORDS):
        assert w in entries, w


@pytest.mark.parametrize("word", ["confirm", "yes", "correct", "affirmative"])
def test_each_confirm_word_proceeds(word):
    s, _ = _at_readback()
    turn = s.handle(word)
    assert turn.kind == "dose", turn.text


@pytest.mark.parametrize("word", ["no", "cancel", "negative", "stop", "wrong"])
def test_each_cancel_word_cancels_and_keeps_the_patient(word):
    s, _ = _at_readback()
    turn = s.handle(word)
    assert turn.text == "Cancelled."
    assert s.handle("confirm").text == "Nothing to confirm."
    again = s.handle("ketamine for agitation iv")        # weight kept: no "Weight?"
    assert again.kind == "readback" and "eighty kilos" in again.text, again.text


def test_age_is_kept_after_a_cancel_too():
    s, _ = _session()
    s.handle("ketamine for agitation iv child six years twenty kilos")
    s.handle("no")
    assert s.patient.age is not None and s.patient.weight is not None


# ── anything else at the confirm step ───────────────────────────────────────

@pytest.mark.parametrize("phrase", ["ok", "go", "give it", "repeat", "why", "eighty kilos",
                                    "yes eighty kilos", "confirm cancel", "new patient",
                                    "fentanyl", "[unk]", "zzz"])
def test_anything_else_asks_say_confirm_or_cancel_and_never_doses(phrase):
    s, _ = _at_readback()
    turn = s.handle(phrase)
    assert turn.text == "Say confirm or cancel.", (phrase, turn.text)
    assert turn.kind != "dose"


def test_one_miss_then_a_confirm_word_still_doses():
    s, _ = _at_readback()
    s.handle("ok")
    assert s.handle("yes").kind == "dose"


def test_two_misses_cancel():
    s, _ = _at_readback()
    assert s.handle("ok").text == "Say confirm or cancel."
    assert s.handle("go").text == "Cancelled."
    assert s.handle("yes").text == "Nothing to confirm."
    assert s.patient.weight is not None


def test_misses_are_counted_per_read_back():
    s, _ = _at_readback()
    s.handle("ok")
    s.handle("no")                                       # cancelled
    s.handle(READBACK)
    assert s.handle("ok").text == "Say confirm or cancel."   # a fresh count


def test_outside_the_confirm_step_a_confirm_word_has_nothing_to_confirm():
    s, _ = _session()
    for w in CONFIRM_WORDS:
        assert s.handle(w).text == "Nothing to confirm."


# ── a pending read-back expires after 30 seconds ────────────────────────────

def test_a_yes_within_30_seconds_doses():
    s, clock = _at_readback()
    clock.t += 29
    assert s.handle("yes").kind == "dose"


def test_a_yes_after_30_seconds_never_confirms_the_old_dose():
    s, clock = _at_readback()
    clock.t += 31
    turn = s.handle("yes")
    assert turn.kind != "dose" and turn.text == "Nothing to confirm."


def test_the_device_loop_can_announce_the_expiry():
    s, clock = _at_readback()
    clock.t += 10
    assert s.expire_pending() is None
    clock.t += 21
    turn = s.expire_pending()
    assert turn is not None and turn.text == "Cancelled."
    assert s.expire_pending() is None                     # once
    assert s.patient.weight is not None


# ── acoustic safety: never a cancel word heard as a confirm word ───────────

def _vosk():
    try:
        import vosk
        return vosk
    except ImportError:
        return None


needs_model = pytest.mark.skipif(not (MODEL.exists() and _vosk()),
                                 reason=f"needs vosk and the model at {MODEL}")


@pytest.fixture(scope="module")
def hearing():
    vosk = _vosk()
    vosk.SetLogLevel(-1)
    from voice.hear import Hearing
    return Hearing(vosk.Model(str(MODEL)), GRAMMAR, VOCAB)


def _heard_controls(hearing, clip):
    u = hearing.start()
    with wave.open(str(clip)) as w:
        u.feed(w.readframes(w.getnframes()))
    heard, text, _ = u.finish()
    return heard, parse(text, VOCAB).controls


def _said(clip):
    return clip.stem.split("__")[1]


def test_there_are_twenty_piper_nos_and_every_word_in_three_kokoro_voices():
    names = [c.stem for c in CLIPS]
    assert sum(n.startswith("piper__no__") for n in names) == 20
    for w in (*CONFIRM_WORDS, *CANCEL_WORDS):
        assert sum(n.startswith(f"kokoro__{w}__") for n in names) == 3, w


@needs_model
def test_no_said_twenty_times_is_never_heard_as_a_confirm_word(hearing):
    for clip in [c for c in CLIPS if c.stem.startswith("piper__no__")]:
        heard, controls = _heard_controls(hearing, clip)
        assert not set(controls) & {"confirm"}, (clip.name, heard)
        s, _ = _at_readback()
        assert s.handle(heard, spoken=True).kind != "dose", (clip.name, heard)


@needs_model
@pytest.mark.parametrize("clip", CLIPS, ids=lambda p: p.stem)
def test_a_cancel_word_is_never_heard_as_a_confirm_word_nor_the_reverse(hearing, clip):
    heard, controls = _heard_controls(hearing, clip)
    said = _said(clip)
    s, _ = _at_readback()
    turn = s.handle(heard, spoken=True)
    if said in CANCEL_WORDS:
        assert turn.kind != "dose", (clip.name, heard)
    else:
        assert turn.text != "Cancelled.", (clip.name, heard)
