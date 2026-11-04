"""The replay corpus: every phrase, every expected output, read by hand against
bank.json and the rulings. Numbers checked against EdgeCDSS in test_golden.py."""
import json
import pathlib
import time

import pytest

from engine.session import boot

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = json.loads((ROOT / "tests" / "replay_corpus.json").read_text())


def test_the_corpus_has_fifty_cases():
    assert len(CORPUS) >= 50
    assert len({c["id"] for c in CORPUS}) == len(CORPUS)


@pytest.mark.parametrize("case", CORPUS, ids=[c["id"] for c in CORPUS])
def test_replay(case):
    s = boot(ROOT / "bank")
    read_back = False
    for phrase, kind, say in case["turns"]:
        turn = s.handle(phrase)
        assert (turn.kind, turn.say) == (kind, say), phrase
        # Rule 2 on every path: a dose only straight after a read-back and "confirm".
        if turn.kind == "dose":
            assert phrase == "confirm" and read_back
        read_back = turn.kind == "readback" or (read_back and turn.kind in ("why", "repeat", "unrecognised"))


def test_a_dose_is_followed_by_its_first_caution_and_its_contraindications():
    s = boot(ROOT / "bank")
    s.handle("ketamine for agitation iv eighty kilos")
    dose = s.handle("confirm")
    bank = json.loads((ROOT / "bank" / "bank.json").read_text())
    e = next(x for x in bank["entries"] if x["drug"] == "ketamine" and x["route"] == "IV"
             and x["population"] == "adult" and x["indication_class"] == "agitation")
    assert dose.after[0] == "Caution: " + e["serve_cautions"][0]
    assert dose.after[1] == "Contraindicated: " + "; ".join(e["contraindications"]) + "."
