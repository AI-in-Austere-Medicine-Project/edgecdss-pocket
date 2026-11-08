"""Owner ruling, 2026-11-08, on what follows a dose.

1. Dose first, always. A caution or contraindication is spoken after the dose only
   when it names a condition the medic stated for this patient ("burns"); every
   other caution goes to "why".
2. When no volume was computed, no spoken caution says a millilitre. The signed
   text in bank.json is unchanged; the spoken form is derived from it.
"""
import json
import pathlib
import re

import pytest

from engine.bank import load_bank
from engine.session import boot
from grammar.vocabulary import CONDITIONS, CONDITION_PATTERNS, build, label_tokens
from tests.test_reachable import key, request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)
ML = re.compile(r"(?i)(?<![a-z])(ml|cc)(?![a-z])")
SUX_RSI = "succinylcholine for rsi eighty kilos"


def entry(drug, route, population, cls):
    return next(e for e in BANK.entries if e["drug"] == drug and e["route"] == route
                and e["population"] == population and e["indication_class"] == cls)


@pytest.fixture
def s():
    return boot(ROOT / "bank")


# ── 1. Spoken only when it names a stated condition ─────────────────────────

def test_with_no_condition_stated_nothing_follows_the_dose(s):
    s.handle(SUX_RSI)
    dose = s.handle("confirm")
    assert dose.say == "Succinylcholine one hundred and twenty milligrams. Two point four mils of fifty."
    assert dose.after == []


def test_a_stated_condition_speaks_the_lines_that_name_it_after_the_dose(s):
    readback = s.handle(f"{SUX_RSI} burns")
    assert readback.say == "Succinylcholine, RSI, IV, eighty kilos, burns. Confirm?"
    dose = s.handle("confirm")
    assert dose.say == "Succinylcholine one hundred and twenty milligrams. Two point four mils of fifty."
    assert dose.after == [
        "Contraindicated: Burns.",
        "Caution: Contraindicated in hyperkalemia, burns >24hr, crush injury, denervation.",
    ]


def test_a_condition_said_on_its_own_is_noted_and_kept_for_this_patient(s):
    assert s.handle("crush injury").say == "Noted: crush injury."
    s.handle(SUX_RSI)
    assert s.handle("confirm").after == [
        "Caution: Contraindicated in hyperkalemia, burns >24hr, crush injury, denervation."]


def test_a_condition_the_entry_does_not_name_speaks_nothing(s):
    s.handle("ketamine for agitation iv eighty kilos burns")
    dose = s.handle("confirm")
    assert dose.kind == "dose"
    assert dose.after == []


def test_new_patient_clears_the_conditions(s):
    s.handle("burns")
    s.handle("new patient")
    s.handle(SUX_RSI)
    assert s.handle("confirm").after == []


def test_why_speaks_the_source_then_every_caution_and_contraindication(s):
    s.handle(SUX_RSI)
    s.handle("confirm")
    why = s.handle("why")
    e = entry("succinylcholine", "IV", "adult", "RSI")
    assert why.say.startswith(f"Source: {e['source']}.")
    assert why.after == ["Caution: " + c for c in e["serve_cautions"]] + [
        "Contraindicated: Burns; Spinal cord injury; Hyperkalemia."]


def test_why_says_when_there_are_no_contraindications():
    no_ci = next(e for e in BANK.entries if not e["contraindications"])
    *_, why = _dose_and_why(no_ci)
    assert why.after[-1] == "No contraindications listed."


# ── the condition words ────────────────────────────────────────────────────

@pytest.mark.parametrize("term", sorted(CONDITIONS))
def test_every_condition_word_names_at_least_one_signed_line(term):
    pattern = re.compile(CONDITION_PATTERNS[CONDITIONS[term]], re.I)
    lines = [t for e in BANK.entries for t in e["contraindications"] + e["serve_cautions"]]
    assert any(pattern.search(t) for t in lines), term


@pytest.mark.parametrize("term", sorted(CONDITIONS))
def test_no_condition_word_is_also_a_drug_indication_or_label_word(term):
    clash = set(VOCAB.drug_terms) | set(VOCAB.class_terms)
    if " " not in term:
        clash |= VOCAB.label_words
    assert term not in clash


def test_a_condition_is_heard_whole(s):
    p = s.parse("spinal cord injury")
    assert p.conditions == ["spinal cord injury"] and p.labels == []


# ── 2. No spoken mL unless a volume was computed ───────────────────────────

ALL_CONDITIONS = " ".join(sorted(set(CONDITIONS)))


def _dose_and_why(e):
    s = boot(ROOT / "bank")
    s.handle(ALL_CONDITIONS)
    turn = s.handle(request(e))
    for _ in range(4):
        if turn.kind == "readback":
            before = s.handle("why")
            dose = s.handle("confirm")
            return before, dose, s.handle("why")
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    raise AssertionError(request(e))


@pytest.mark.parametrize("e", BANK.entries, ids=key)
def test_no_spoken_caution_says_ml_unless_a_volume_was_computed(e):
    before, dose, after = _dose_and_why(e)
    assert before.kind == "why" and dose.kind == "dose" and after.kind == "why"
    assert not any(ML.search(line) for line in before.after), "why before the dose"
    if dose.data["record"]["volume_ml"] is None:
        for turn in (dose, after):
            spoken = [line for line in turn.after if ML.search(line)]
            assert spoken == [], key(e)


def test_with_a_volume_the_signed_caution_is_spoken_whole(s):
    # Ketamine IV analgesia: 4 mL of the dilution, so the dilution line keeps its mL.
    s.handle("ketamine for moderate pain iv eighty kilos")
    dose = s.handle("confirm")
    assert dose.data["record"]["volume_ml"] == 4.0
    e = entry("ketamine", "IV", "adult", "pain")
    assert s.handle("why").after[0] == "Caution: " + e["serve_cautions"][0]
    assert "mL" in e["serve_cautions"][0]


def test_without_a_volume_only_the_sentences_with_ml_drop(s):
    # "1 g is 10 mL of 10%. Slow push into a large vein; ..." keeps its second sentence.
    s.handle("calcium chloride for hypocalcaemia adult")
    s.handle("confirm")
    why = s.handle("why")
    assert "Caution: Slow push into a large vein; extravasation causes tissue necrosis (SMOG p.101)." in why.after


def test_the_signed_text_in_the_bank_is_unchanged():
    raw = json.loads((ROOT / "bank" / "bank.json").read_text())
    for e in BANK.entries:
        _dose_and_why(e)
    assert [e["serve_cautions"] for e in raw["entries"]] == [e["serve_cautions"] for e in BANK.entries]
    assert sum(bool(ML.search(c)) for e in raw["entries"] for c in e["serve_cautions"]) > 0
