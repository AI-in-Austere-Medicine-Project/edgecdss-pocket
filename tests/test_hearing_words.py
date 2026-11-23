"""The hearing check for routes, procedures and commands (owner, 2026-11-23: "extend the
hearing check to routes and commands in a separate PR, so "no" and "in the vein" are
starred on the page").

voice/tools/dryrun_words.py does for every route, procedure and command what
dryrun_drugs.py does for drug names: each said alone in the three held-out synthetic
voices, decoded with the committed grammar, and read by the parser. A clip is heard when
the parser reads the word's own meaning (its route, command, or procedure) and nothing else.
"""
import hashlib
import json
import pathlib

from grammar.vocabulary import CONTROLS, PROCEDURE_TERMS, ROUTES
from voice.tools import dryrun_drugs, dryrun_words

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "voice" / "dryrun_words.json").read_text())


def test_every_route_procedure_and_command_is_checked_once():
    words = dryrun_words.words()
    said = [w["word"] for w in words]
    assert len(said) == len(set(said))
    assert {w["word"] for w in words if w["kind"] == "command"} == set(CONTROLS)
    assert {w["word"] for w in words if w["kind"] == "procedure"} == {"rsi", *PROCEDURE_TERMS}
    assert {w["word"] for w in words if w["kind"] == "route"} == {r.replace(" ", "") if len(r) == 3 and r[1] == " " else r for r in ROUTES}


def test_letters_are_said_as_letters_and_phrases_as_words():
    assert dryrun_words.prompt("iv") == "i v" and dryrun_words.prompt("rsi") == "r s i"
    assert dryrun_words.prompt("in the vein") == "in the vein"         # not "i n the vein"
    assert dryrun_words.prompt("in") == "i n"


def test_the_check_is_of_this_grammar_in_the_held_out_voices():
    digest = hashlib.sha256((ROOT / "grammar" / "vosk_grammar.json").read_bytes()).hexdigest()
    assert D["grammar_sha256"] == digest
    assert D["voices"] == list(dryrun_drugs.VOICES)
    assert {r["word"] for r in D["rows"]} == {w["word"] for w in dryrun_words.words()}
    assert D["clips"] == len(D["rows"]) == 3 * D["words"]


def test_the_misses_include_no_and_in_the_vein():
    missed = {r["word"] for r in D["rows"] if not r["ok"]}
    assert {"no", "in the vein"} <= missed
    assert D["heard"] == sum(r["ok"] for r in D["rows"])


def test_a_clip_is_heard_only_as_its_own_meaning():
    for r in D["rows"]:
        if r["ok"]:
            assert r["got"] == r["want"] and r["want"], r
