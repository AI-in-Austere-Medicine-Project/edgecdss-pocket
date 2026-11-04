"""The word list is generated from the bank. Nothing outside it is recognised."""
import json
import pathlib

import pytest

from engine.bank import load_bank
from grammar.parser import parse
from grammar.vocabulary import build

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)


@pytest.mark.parametrize("word", ["ketamine", "ketorolac", "magnesium", "pain", "agitation",
                                  "iv", "io", "im", "in", "po", "line", "eighty", "kilos",
                                  "pounds", "estimated", "child", "years", "confirm", "cancel",
                                  "repeat", "why", "new", "patient", "log", "battery"])
def test_the_readme_vocabulary_is_in_the_word_list(word):
    assert word in VOCAB.words()


def test_every_signed_drug_can_be_named():
    for e in BANK.entries:
        assert VOCAB.named(e["drug"]), e["drug"]


def test_every_signed_class_can_be_named():
    for e in BANK.entries:
        assert VOCAB.class_terms_for(e["indication_class"]), e["indication_class"]


@pytest.mark.parametrize("phrase", ["zzz", "ketamine 80", "ketamine please", "ketamin"])
def test_a_word_outside_the_list_refuses_the_whole_phrase(phrase):
    p = parse(phrase, VOCAB)
    assert p.unknown
    assert p.drugs == []


def test_a_name_that_cannot_be_said_is_reported_not_silently_dropped():
    assert "d50" in VOCAB.unspeakable
    assert "sodium chloride 3%" in VOCAB.unspeakable
    assert "hypertonic saline" in VOCAB.drug_terms


@pytest.mark.parametrize("words,value", [
    ("eighty", 80), ("eighty five", 85), ("twenty-five", 25), ("one hundred", 100),
    ("one hundred seventy six", 176), ("one hundred and twenty", 120),
    ("zero point five", 0.5), ("seventy nine point eight", 79.8), ("two thousand", 2000),
])
def test_numbers(words, value):
    assert parse(f"{words} kilos", VOCAB).weight.value == value


@pytest.mark.parametrize("words", ["eighty ninety", "five five", "hundred point", "point five"])
def test_a_number_that_does_not_read_as_one_is_not_guessed(words):
    p = parse(f"{words} kilos", VOCAB)
    assert p.weight is None
    assert p.bad_number


def test_pounds_convert_like_edgecdss():
    w = parse("one hundred seventy six pounds", VOCAB).weight
    assert (w.value, w.unit, w.kg) == (176, "pounds", 79.8)


def test_estimated_before_or_after():
    assert parse("estimated eighty kilos", VOCAB).weight.estimated
    assert parse("eighty kilos estimated", VOCAB).weight.estimated
    assert not parse("eighty kilos", VOCAB).weight.estimated


def test_longest_name_wins():
    p = parse("calcium chloride", VOCAB)
    assert [d.generics for d in p.drugs] == [("calcium chloride",)]


def test_ambiguous_names_never_resolve():
    assert parse("keto", VOCAB).drugs[0].generics == ("ketamine", "ketorolac")
    assert parse("ket", VOCAB).drugs[0].generics == ("ketamine", "ketorolac")
    assert parse("ketamine", VOCAB).drugs[0].generics == ("ketamine",)
    assert parse("ketorolac", VOCAB).drugs[0].generics == ("ketorolac",)


def test_no_drug_name_shadows_a_class_route_or_control_word():
    from grammar.vocabulary import _reserved
    assert not set(VOCAB.drug_terms) & (set(VOCAB.class_terms) | _reserved() | VOCAB.label_words)


def test_a_bank_unit_with_no_words_refuses_the_bank(tmp_path):
    import hashlib
    import shutil
    from engine.session import boot
    d = tmp_path / "bank"
    shutil.copytree(ROOT / "bank", d)
    bank = json.loads((d / "bank.json").read_text())
    bank["entries"][0]["rule"]["units"] = "mcg/fortnight/min"
    (d / "bank.json").write_text(json.dumps(bank))
    man = json.loads((d / "manifest.json").read_text())
    man["sha256"]["bank.json"] = hashlib.sha256((d / "bank.json").read_bytes()).hexdigest()
    (d / "manifest.json").write_text(json.dumps(man))
    assert boot(d).announce.kind == "refused"
