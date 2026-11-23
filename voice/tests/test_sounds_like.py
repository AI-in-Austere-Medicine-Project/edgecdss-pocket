"""Drug names the small model's word list does not hold, heard through phonetic
spellings: sequences of words it does hold, mapped back to the name before the parser
(owner ruling, phase 2). The model is unchanged."""
import hashlib
import json
import pathlib

import pytest

from engine.bank import BANK_DIR, load_bank
from engine.session import boot
from grammar.vocabulary import CONTROLS, FILLERS, build
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANK = load_bank(BANK_DIR)          # the one drug list, the EMS set (owner, 2026-11-23)
VOCAB = build(BANK)
SOUNDS = json.loads((ROOT / "grammar" / "sounds_like.json").read_text())
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
DRYRUN = json.loads((ROOT / "voice" / "dryrun_drugs.json").read_text())
MEDIC_FORMS = {"narcan": "naloxone", "versed": "midazolam", "benadryl": "diphenhydramine",
               "zofran": "ondansetron", "txa": "tranexamic acid"}


def test_every_signed_drug_has_a_name_the_model_can_hear():
    assert len(VOCAB.signed) == 32
    assert GRAMMAR["signed_drugs_not_sayable"] == []


def test_a_spelling_uses_only_words_that_mean_nothing_else_to_the_parser():
    """Every spelling Pocket can hear (owner ruling, 2026-11-23: the nine that held a word
    the EMS parser reads are removed)."""
    # Its own name's words excepted: "push dose amie" spells "push dose epi". Fillers
    # ("the", "and") are skipped by the parser, so they mean nothing: "i the" spells "iv".
    # The words only the home menu's longer commands use ("what can i say", "list drugs")
    # mean nothing alone (owner, 2026-11-21): "nor can" keeps spelling narcan. The whole
    # command, said in a spelling, would mean something: no spelling holds one.
    from grammar.vocabulary import menu_only_words
    assert menu_only_words(VOCAB) == {"what", "can", "say", "list"}   # not "i": "i v"
    meaningful = ((VOCAB.words() - set(FILLERS)) | {w for c in CONTROLS for w in c.split()}) - menu_only_words(VOCAB)
    kept = VOCAB.words(signed_only=True) | set(spoken.SPELLED)   # an unsigned name's spellings are never heard
    for name, spellings in SOUNDS["spellings"].items():
        if not set(name.split()) <= kept:
            continue
        own = set(name.split()) | set(spoken.SPELLED.get(name, "").split())  # "iv" is said "i v"
        for s in spellings:
            assert not (set(s.split()) - own) & meaningful, (name, s)
            for c in CONTROLS:
                assert f" {c} " not in f" {s} ", (name, s, c)


def test_no_spelling_belongs_to_two_names():
    seen = {}
    for token, spellings in SOUNDS["spellings"].items():
        for s in spellings:
            assert seen.setdefault(s, token) == token, s


def test_every_spelling_of_a_signed_word_is_in_the_grammar():
    """Spellings of unsigned drugs are left out (owner, 2026-11-15: the grammar's drug words
    are signed drugs only; tests/test_hearing_fixes.py), and the three NOT_IN_GRAMMAR."""
    from voice.grammar import NOT_IN_GRAMMAR
    entries = set(GRAMMAR["words"])
    kept = VOCAB.words(signed_only=True) | set(spoken.SPELLED)
    for token, spellings in SOUNDS["spellings"].items():
        if set(token.split()) <= kept:
            assert set(spellings) - set(NOT_IN_GRAMMAR) <= entries, token


def test_a_spelling_heard_is_the_name_to_the_parser():
    token, spellings = next((t, s) for t, s in SOUNDS["spellings"].items() if t == "rocuronium")
    assert spoken.normalise(f"{spellings[0]} for r s i eighty kilos") == "rocuronium for r s i eighty kilos"


@pytest.mark.parametrize("said,drug", sorted(MEDIC_FORMS.items()))
def test_the_medic_forms_name_their_drug(said, drug):
    s = boot()
    s.handle(said)
    assert s.req.drug == drug, said


def test_roc_still_asks():
    assert boot().handle("roc").say == "Ceftriaxone or rocuronium?"     # "rocephin": unsigned, still a name


# ── the dry run: synthetic held-out voices, before the spoken replay ─────────

def test_the_dry_run_is_of_this_grammar():
    digest = hashlib.sha256((ROOT / "grammar" / "vosk_grammar.json").read_bytes()).hexdigest()
    assert DRYRUN["grammar_sha256"] == digest


# The synthetic dry run missed 6 of 183 clips (3 drugs, 3 medic forms, see
# voice/dryrun_drugs.json). The owner made the medic's own voice the gate instead (phase 2):
# these stay as written, expected to fail on this record, and turn red if they pass.
SYNTHETIC_GATE = pytest.mark.xfail(strict=True, reason="synthetic dry run 242/258; the owner's voice is the gate")


@SYNTHETIC_GATE
def test_the_dry_run_heard_all_32_signed_drugs_in_every_held_out_voice():
    voices = DRYRUN["voices"]
    assert len(voices) >= 3 and not set(voices) & set(SOUNDS["voices"])
    for drug in sorted(VOCAB.signed):
        rows = [r for r in DRYRUN["rows"] if r["drug"] == drug and r["name"] == r["primary"]]
        assert {r["voice"] for r in rows} == set(voices), drug
        assert all(r["heard_as"] == [drug] for r in rows), (drug, rows)


def test_the_dry_run_heard_every_medic_form():
    # Every voice since the hearing fixes (2026-11-15); before them ancef and txa each
    # missed one voice, and this was an expected failure.
    for said, drug in MEDIC_FORMS.items():
        rows = [r for r in DRYRUN["rows"] if r["name"] == said]
        assert rows and all(r["heard_as"] == [drug] for r in rows), (said, rows)


def test_the_dry_run_never_heard_one_drug_as_another():
    # Signed, or unsigned: an unsigned name heard would show as its hold. A confusable
    # pair (grammar/confusable.json) asks "X or Y?" and never doses: its other drug is asked.
    for r in DRYRUN["rows"]:
        pair = set(VOCAB.confusable.get(r["drug"], ()))
        assert set(r["heard_as"]) <= {r["drug"]} | set(r["asks"]) | pair, r
        assert not r["turn"].startswith("No signed dose for"), r
