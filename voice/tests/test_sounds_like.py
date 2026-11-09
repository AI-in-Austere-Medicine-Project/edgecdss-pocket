"""Drug names the small model's word list does not hold, heard through phonetic
spellings: sequences of words it does hold, mapped back to the name before the parser
(owner ruling, phase 2). The model is unchanged."""
import hashlib
import json
import pathlib

import pytest

from engine.bank import load_bank
from engine.session import boot
from grammar.vocabulary import CONTROLS, build
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)
SOUNDS = json.loads((ROOT / "grammar" / "sounds_like.json").read_text())
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
DRYRUN = json.loads((ROOT / "voice" / "dryrun_drugs.json").read_text())
MEDIC_FORMS = {"rocephin": "ceftriaxone", "ancef": "cefazolin", "keppra": "levetiracetam",
               "cal gluc": "calcium gluconate", "txa": "tranexamic acid"}


def test_every_signed_drug_has_a_name_the_model_can_hear():
    assert len(VOCAB.signed) == 25
    assert GRAMMAR["signed_drugs_not_sayable"] == []


def test_a_spelling_uses_only_words_that_mean_nothing_else_to_the_parser():
    # Its own name's words excepted: "push dose amie" spells "push dose epi".
    meaningful = VOCAB.words() | {w for c in CONTROLS for w in c.split()}
    for name, spellings in SOUNDS["spellings"].items():
        for s in spellings:
            assert not (set(s.split()) - set(name.split())) & meaningful, (name, s)


def test_no_spelling_belongs_to_two_names():
    seen = {}
    for token, spellings in SOUNDS["spellings"].items():
        for s in spellings:
            assert seen.setdefault(s, token) == token, s


def test_every_spelling_is_in_the_grammar():
    entries = set(GRAMMAR["words"])
    for spellings in SOUNDS["spellings"].values():
        assert set(spellings) <= entries


def test_a_spelling_heard_is_the_name_to_the_parser():
    token, spellings = next((t, s) for t, s in SOUNDS["spellings"].items() if t == "rocuronium")
    assert spoken.normalise(f"{spellings[0]} for r s i eighty kilos") == "rocuronium for r s i eighty kilos"


@pytest.mark.parametrize("said,drug", sorted(MEDIC_FORMS.items()))
def test_the_medic_forms_name_their_drug(said, drug):
    s = boot(ROOT / "bank")
    s.handle(said)
    assert s.req.drug == drug, said


def test_roc_still_asks():
    assert boot(ROOT / "bank").handle("roc").say == "Ceftriaxone or rocuronium?"


# ── the dry run: synthetic held-out voices, before the spoken replay ─────────

def test_the_dry_run_is_of_this_grammar():
    digest = hashlib.sha256((ROOT / "grammar" / "vosk_grammar.json").read_bytes()).hexdigest()
    assert DRYRUN["grammar_sha256"] == digest


# The synthetic dry run missed 6 of 183 clips (3 drugs, 3 medic forms, see
# voice/dryrun_drugs.json). The owner made the medic's own voice the gate instead (phase 2):
# these stay as written, expected to fail on this record, and turn red if they pass.
SYNTHETIC_GATE = pytest.mark.xfail(strict=True, reason="synthetic dry run 177/183; the owner's voice is the gate")


@SYNTHETIC_GATE
def test_the_dry_run_heard_all_25_signed_drugs_in_every_held_out_voice():
    voices = DRYRUN["voices"]
    assert len(voices) >= 3 and not set(voices) & set(SOUNDS["voices"])
    for drug in sorted(VOCAB.signed):
        rows = [r for r in DRYRUN["rows"] if r["drug"] == drug and r["name"] == r["primary"]]
        assert {r["voice"] for r in rows} == set(voices), drug
        assert all(r["heard_as"] == [drug] for r in rows), (drug, rows)


@SYNTHETIC_GATE
def test_the_dry_run_heard_every_medic_form():
    for said, drug in MEDIC_FORMS.items():
        rows = [r for r in DRYRUN["rows"] if r["name"] == said]
        assert rows and all(r["heard_as"] == [drug] for r in rows), (said, rows)


def test_the_dry_run_never_heard_one_drug_as_another():
    # Signed, or unsigned: an unsigned name heard would show as its hold.
    for r in DRYRUN["rows"]:
        assert set(r["heard_as"]) <= {r["drug"]} | set(r["asks"]), r
        assert not r["turn"].startswith("No signed dose for"), r
