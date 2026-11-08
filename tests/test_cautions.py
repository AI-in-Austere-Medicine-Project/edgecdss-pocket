"""Owner ruling, 2026-11-08, on what follows a dose.

1. Dose first, always. A caution or contraindication is spoken after the dose only
   when it names a condition the medic stated for this patient ("burns"); every
   other caution goes to "why".
2. When no volume was computed, no spoken caution states a volume. Concentrations
   (mg/mL, 1:1,000) are kept (owner, 2026-11-08 second review). The signed text in
   bank.json is unchanged; the spoken form is derived from it. Quotes under "why" are
   read word for word.
3. A stated contraindication holds the dose, as EdgeCDSS's A12 does: it is a gate,
   not a caution (owner, second review). Dose first means dose before caution when
   the dose serves.
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
# A stated volume: "10 mL", "0.1 mL/kg", "100 cc". Not a concentration: "1 mg/mL".
VOLUME = re.compile(r"(?i)(?<![a-z/])(ml|cc)(?![a-z])")
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


def test_a_stated_condition_a_caution_names_is_spoken_after_the_dose(s):
    readback = s.handle(f"{SUX_RSI} crush injury")
    assert readback.say == "Succinylcholine, RSI, IV, eighty kilos, crush injury. Confirm?"
    dose = s.handle("confirm")
    assert dose.say == "Succinylcholine one hundred and twenty milligrams. Two point four mils of fifty."
    assert dose.after == [
        "Caution: Contraindicated in hyperkalemia, burns >24hr, crush injury, denervation."]


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
    assert s.handle(SUX_RSI).kind == "readback"
    assert s.handle("confirm").after == []


# ── 3. A stated contraindication holds ─────────────────────────────────────

HELD_SUX = "Held. Succinylcholine is contraindicated with {}. Rocuronium is the signed alternative."


def test_the_owners_example_holds(s):
    turn = s.handle("Succinylcholine, RSI, eighty kilos, burns")
    assert (turn.kind, turn.text) == ("hold", HELD_SUX.format("burns"))
    assert s.handle("confirm").say == "Nothing to confirm."
    assert s.records == []


@pytest.mark.parametrize("said,named", [
    ("spinal cord injury", "spinal cord injury"), ("hyperkalemic", "hyperkalaemia"),
    ("high potassium", "hyperkalaemia"), ("burns spinal cord injury", "burns and spinal cord injury"),
])
def test_each_signed_succinylcholine_contraindication_holds(s, said, named):
    assert s.handle(f"{SUX_RSI} {said}").text == HELD_SUX.format(named)


def test_a_condition_said_first_holds_the_later_request(s):
    s.handle("burns")
    assert s.handle(SUX_RSI).text == HELD_SUX.format("burns")


def test_a_condition_said_at_the_read_back_holds(s):
    assert s.handle(SUX_RSI).kind == "readback"
    assert s.handle("burns").text == HELD_SUX.format("burns")
    assert s.handle("confirm").say == "Nothing to confirm."


def test_a_child_is_held_too_with_the_childs_alternative(s):
    turn = s.handle("succinylcholine for rsi child three years fifteen kilos burns")
    assert turn.text == HELD_SUX.format("burns")


def test_after_the_hold_the_alternative_doses(s):
    s.handle(f"{SUX_RSI} burns")
    assert s.handle("rocuronium for rsi").kind == "readback"
    dose = s.handle("confirm")
    assert dose.say.startswith("Rocuronium") and dose.after == []


def test_an_alternative_contraindicated_too_is_not_named(s):
    turn = s.handle("midazolam for seizure iv eighty kilos glaucoma")
    assert turn.kind == "hold"
    assert turn.say.startswith("Held. Midazolam is contraindicated with glaucoma.")
    assert "orazepam" not in turn.text    # lorazepam is contraindicated with glaucoma too


def test_a_relative_or_qualified_contraindication_does_not_hold(s):
    # "Uncontrolled hypertension is a relative contraindication only; otherwise none in
    # cardiac arrest": spoken after the dose, not a gate.
    s.handle("epinephrine for cardiac arrest iv eighty kilos hypertension")
    dose = s.handle("confirm")
    assert dose.kind == "dose"
    assert dose.after[0].startswith("Contraindicated: Uncontrolled hypertension is a relative")


def test_every_hold_names_only_signed_alternatives():
    from engine.session import holding_conditions
    from engine.words import say_name
    names = {say_name(d) for d in {e["drug"] for e in BANK.entries}}
    held = 0
    for e in BANK.entries:
        for cond in holding_conditions(e, CONDITION_PATTERNS):
            said = next(k for k, v in CONDITIONS.items() if v == cond)
            turn, _ = _walk_to(e, said)
            assert turn.kind == "hold", (key(e), said)
            held += 1
            alt = turn.say.split(f"contraindicated with {cond}.")[1].strip()
            if alt.startswith("Signed alternatives: "):
                alts = alt[len("Signed alternatives: "):-1].split(", ")
            elif alt:
                alts = [alt[:-len(" is the signed alternative.")]]
            else:
                alts = []
            assert {a.lower() for a in alts} <= names, alt
            assert say_name(e["drug"]) not in {a.lower() for a in alts}
    assert held > 0


def _walk_to(e, said):
    s = boot(ROOT / "bank")
    turn = s.handle(f"{request(e)} {said}")
    for _ in range(4):
        if turn.kind != "ask" or not turn.say.startswith("Which one"):
            return turn, s
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    return turn, s


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

def _dose_and_why(e, conditions=""):
    s = boot(ROOT / "bank")
    if conditions:
        s.handle(conditions)
    turn = s.handle(request(e))
    for _ in range(4):
        if turn.kind == "readback":
            before = s.handle("why")
            dose = s.handle("confirm")
            return before, dose, s.handle("why")
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    raise AssertionError(request(e))


def _dose_and_why_no_gate(e):
    """Every condition a caution names but no contraindication of this entry gates on."""
    from engine.session import holding_conditions
    said = [k for k, c in CONDITIONS.items() if c not in holding_conditions(e, CONDITION_PATTERNS)]
    return _dose_and_why(e, " ".join(sorted(said)))


@pytest.mark.parametrize("e", BANK.entries, ids=key)
def test_no_spoken_caution_states_a_volume_unless_one_was_computed(e):
    before, dose, after = _dose_and_why_no_gate(e)
    assert before.kind == "why" and dose.kind == "dose" and after.kind == "why"
    assert not any(VOLUME.search(line) for line in before.after), "why before the dose"
    if dose.data["record"]["volume_ml"] is None:
        for turn in (dose, after):
            spoken = [line for line in turn.after if VOLUME.search(line)]
            assert spoken == [], key(e)


@pytest.mark.parametrize("cls,route,line", [
    ("cardiac arrest", "iv", "Caution: Not the 1 mg/mL (1:1,000) ampoule undiluted: SMOG p.112."),
    ("anaphylaxis", "im", "Caution: Use the 1 mg/mL concentration for the IM route."),
])
def test_epinephrine_concentration_warnings_are_spoken(s, cls, route, line):
    s.handle(f"epinephrine for {cls} {route} eighty kilos")
    assert s.handle("confirm").data["record"]["volume_ml"] is None
    assert line in s.handle("why").after


def test_quotes_under_why_are_word_for_word():
    for e in BANK.entries:
        if e["quote"] and re.search(r"(?i)ml", e["quote"]):
            before, *_ = _dose_and_why_no_gate(e)
            assert e["quote"] in before.say, key(e)


def test_with_a_volume_the_signed_caution_is_spoken_whole(s):
    # Ketamine IV analgesia: 4 mL of the dilution, so the dilution line keeps its mL.
    s.handle("ketamine for moderate pain iv eighty kilos")
    dose = s.handle("confirm")
    assert dose.data["record"]["volume_ml"] == 4.0
    e = entry("ketamine", "IV", "adult", "pain")
    assert s.handle("why").after[0] == "Caution: " + e["serve_cautions"][0]
    assert "mL" in e["serve_cautions"][0]


def test_without_a_volume_only_the_sentences_with_a_volume_drop(s):
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
    assert sum(bool(VOLUME.search(c)) for e in raw["entries"] for c in e["serve_cautions"]) > 0
