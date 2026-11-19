"""Routes as they sound (owner's choices, 2026-11-19): IV "eye vee", IM "eye em", IO "eye
oh", IN "intranasal", PO "pee oh", NEB "nebuliser". No spoken line has a bare route
abbreviation: not a read-back, question or hold, and not the signed text when it is
spoken ("why", cautions). The signed text, the bank and the log keep the letters."""
import json
import re

import pytest

from engine import words
from engine.session import Session, boot
from test_reachable import BANK, ROOT, key, request
from grammar.vocabulary import label_tokens, build

VOCAB = build(BANK)
BARE = re.compile(r"(?<![A-Za-z])(IV|IM|IO|IN|PO|NEB)(?![A-Za-z])")
CHOSEN = {"IV": "eye vee", "IM": "eye em", "IO": "eye oh", "IN": "intranasal",
          "PO": "pee oh", "NEB": "nebuliser"}


def _no_bare(turn):
    for line in [turn.say, *turn.after]:
        assert not BARE.search(line), line


def test_the_owners_spellings():
    assert words.ROUTE_WORDS == CHOSEN


@pytest.mark.parametrize("text, said", [
    ("IV", "eye vee"), ("IM", "eye em"), ("IO", "eye oh"), ("IN", "intranasal"),
    ("PO", "pee oh"), ("NEB", "nebuliser"),
    ("Load 1 mg/kg IV/IO over 60 seconds", "Load 1 mg/kg eye vee or eye oh over 60 seconds"),
    ("0.4–2mg IV/IM/SC/IN; repeat", "0.4–2mg eye vee or eye em or SC or intranasal; repeat"),
    ("breakthrough pain — IM/IN", "breakthrough pain — eye em or intranasal"),
    ("NASEMSO prefers IN/IM over IV or IO", "NASEMSO prefers intranasal or eye em over eye vee or eye oh"),
    # Words that only contain the letters are left alone.
    ("IVP via the ETT, in labour, INR, POCUS, nebulised", "IVP via the ETT, in labour, INR, POCUS, nebulised"),
])
def test_say_routes(text, said):
    assert words.say_routes(text) == said


@pytest.mark.parametrize("e", BANK.entries, ids=key)
def test_every_signed_entry_spoken_without_bare_routes(e):
    s = boot(ROOT / "bank")
    turn = s.handle(request(e))
    for _ in range(4):
        _no_bare(turn)
        if turn.kind != "ask" or not turn.say.startswith("Which one"):
            break
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    assert turn.kind == "readback", turn.text
    assert CHOSEN[e["route"]] in turn.say, turn.say
    for said in ("why", "repeat", "confirm", "why", "repeat"):
        turn = s.handle(said)
        _no_bare(turn)
    assert s.records[-1]["route"] in CHOSEN   # the log keeps the letters


def test_questions_and_holds_say_routes():
    s = Session(BANK)
    s.handle("eighty kilos")
    asked = s.handle("ketamine for pain")
    assert asked.say.startswith("Which route: eye vee"), asked.say
    _no_bare(asked)
    held = Session(BANK)
    held.handle("eighty kilos")
    turn = held.handle("morphine for pain po")
    _no_bare(turn)
    io = Session(BANK).handle("ketamine for agitation io eighty kilos")
    assert "eye oh" in io.say, io.say


def test_confusable_route_question_said_as_routes():
    s = Session(BANK)
    turn = s.handle("ketamine for pain i n eighty kilos")
    _no_bare(turn)


def test_signed_text_and_log_keep_the_letters():
    bank = json.loads((ROOT / "bank" / "bank.json").read_text())
    assert any("IV/IO" in c for e in bank["entries"] for c in e["serve_cautions"])
    s = Session(BANK)
    s.handle("morphine for pain iv eighty kilos")
    dose = s.handle("confirm")
    assert dose.kind == "dose"
    assert dose.data["record"]["route"] == "IV"
