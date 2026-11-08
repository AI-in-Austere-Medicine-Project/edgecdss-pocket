"""Phase 2, speech in: the pieces that need no microphone and no model."""
import json
import pathlib
import subprocess
import sys

import pytest

from engine.bank import load_bank
from grammar.parser import parse
from grammar.vocabulary import build
from voice import bench, spoken
from voice.grammar import grammar_words

ROOT = pathlib.Path(__file__).resolve().parents[2]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)
CORPUS = json.loads((ROOT / "tests" / "replay_corpus.json").read_text())


# ── what the medic is asked to say, and what is scored ─────────────────────

@pytest.mark.parametrize("typed,said", [
    ("ketamine for pain iv eighty kilos", "ketamine for pain i v eighty kilos"),
    ("fent for pain in eighty kilos", "fent for pain i n eighty kilos"),
    ("sux for rsi", "sux for r s i"),
    ("ketamine five hundred milligrams in ten mils", "ketamine five hundred milligrams in ten mils"),
    ("Ketamine, pain, IV.", "ketamine pain i v"),
    ("txa for haemorrhage", "t x a for haemorrhage"),
])
def test_the_prompt_is_the_typed_phrase_as_it_is_said(typed, said):
    assert spoken.prompt(typed) == said


def test_every_prompt_parses_as_its_typed_phrase():
    for case in CORPUS:
        for phrase, *_ in case["turns"]:
            a, b = parse(phrase, VOCAB), parse(spoken.normalise(spoken.prompt(phrase)), VOCAB)
            assert a == b, phrase


@pytest.mark.parametrize("heard,text", [
    ("t x a for haemorrhage", "txa for haemorrhage"),
    ("ketamine for pain i v eighty kilos", "ketamine for pain i v eighty kilos"),
    ("[unk] for pain", "[unk] for pain"),
    ("", ""),
])
def test_what_vosk_returns_is_given_to_the_parser_unchanged_but_for_spelled_names(heard, text):
    assert spoken.normalise(heard) == text


def test_an_unknown_word_from_vosk_refuses_the_phrase():
    assert parse(spoken.normalise("ketamine [unk] pain"), VOCAB).unknown


# ── word error rate ───────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,hyp,errors,n", [
    ("ketamine for pain", "ketamine for pain", 0, 3),
    ("ketamine for pain", "ketamine pain", 1, 3),            # deletion
    ("ketamine for pain", "ketamine for for pain", 1, 3),    # insertion
    ("ketamine for pain", "morphine for pain", 1, 3),        # substitution
    ("confirm", "", 1, 1),
    ("i v", "i v", 0, 2),
    ("t x a for haemorrhage", "t x a for hemorrhage", 0, 4),   # one word, two spellings
    ("sleep apnoea", "sleep apnea", 0, 2),
    ("four kilos", "for kilos", 1, 2),                          # a homophone is an error
])
def test_word_errors(ref, hyp, errors, n):
    assert spoken.word_errors(ref, hyp) == (errors, n)


# ── the grammar handed to Vosk ────────────────────────────────────────────

def test_the_grammar_is_the_bank_words_the_model_knows_plus_letters_and_unk():
    known = {"ketamine", "for", "pain", "i", "v", "confirm"}
    words, missing = grammar_words(VOCAB, lambda w: w in known)
    assert "[unk]" in words
    assert set(words) - {"[unk]"} <= VOCAB.words() | set("abcdefghijklmnopqrstuvwxyz")
    assert "ketamine" in words and "atropine" not in words
    assert "atropine" in missing
    assert words == sorted(words)


def test_the_committed_grammar_file_matches_the_bank():
    g = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
    assert g["bank_hash"] == BANK.hash
    assert set(g["words"]) - {"[unk]"} <= VOCAB.words() | set("abcdefghijklmnopqrstuvwxyz")
    assert set(g["not_in_model"]) <= VOCAB.words()
    assert not set(g["words"]) & set(g["not_in_model"])


# ── the spoken replay ─────────────────────────────────────────────────────

def test_the_spoken_replay_is_fifty_phrases_of_whole_cases_the_model_can_hear():
    g = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
    heard = set(g["words"])
    cases = bench.select(CORPUS, heard, 50)
    phrases = [t for c in cases for t in c["turns"]]
    assert 50 <= len(phrases) < 50 + max(len(c["turns"]) for c in cases)
    ids = [c["id"] for c in CORPUS]
    assert [c["id"] for c in cases] == sorted((c["id"] for c in cases), key=ids.index)
    for phrase, *_ in phrases:
        assert set(spoken.prompt(phrase).split()) <= heard, phrase


# ── the text path stays ───────────────────────────────────────────────────

def test_the_text_path_needs_no_vosk():
    code = ("import sys; sys.modules['vosk'] = None\n"
            "from engine.session import boot\n"
            "s = boot('bank'); s.handle('ketamine for agitation iv eighty kilos')\n"
            "print(s.handle('confirm').say)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("Ketamine one hundred and sixty milligrams.")
