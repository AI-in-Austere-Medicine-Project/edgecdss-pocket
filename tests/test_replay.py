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
    for phrase, kind, say, *after in case["turns"]:
        turn = s.handle(phrase)
        assert (turn.kind, turn.say) == (kind, say), phrase
        if after:   # what follows the dose, where the case states it
            assert turn.after == after[0], phrase
        # Rule 2 on every path: a dose only straight after a read-back and "confirm".
        if turn.kind == "dose":
            assert phrase == "confirm" and read_back
        read_back = turn.kind == "readback" or (read_back and turn.kind in ("why", "repeat", "unrecognised"))


def test_a_dose_with_no_condition_stated_is_followed_by_nothing():
    # Owner ruling 2026-11-08: cautions follow the dose only when they name a stated
    # condition; otherwise they are in "why" (tests/test_cautions.py).
    s = boot(ROOT / "bank")
    s.handle("ketamine for agitation iv eighty kilos")
    assert s.handle("confirm").after == []
