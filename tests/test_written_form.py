"""Two forms of every answer (owner, 2026-11-19): the spoken form for the voice ("eye
vee", "pee oh") and a written form for a screen, with the route letters IV, IM, IO, IN,
PO and NEB. Only the routes differ; the written form is never spoken."""
import re

import pytest

from engine import words
from engine.session import Session, boot
from grammar.vocabulary import build, label_tokens
from test_reachable import BANK, ROOT, key, request
from engine.bank import PFC_RETIRED  # the retired PFC set: fixture data (2026-11-23)

VOCAB = build(BANK)
SPOKEN_ROUTE = re.compile(r"(?i)\b(eye vee|eye em|eye oh|pee oh|nebuliser)\b")
BARE = re.compile(r"(?<![A-Za-z])(IV|IM|IO|IN|PO|NEB)(?![A-Za-z])")


def _forms(turn):
    assert turn.written_text == " ".join([turn.written, *turn.written_after])
    assert len(turn.written_after) == len(turn.after)
    for written, said in zip([turn.written, *turn.written_after], [turn.say, *turn.after]):
        assert not SPOKEN_ROUTE.search(written), written     # on screen: letters
        assert not BARE.search(said), said                    # in the voice: words
        assert words.say_routes(written) == said, (written, said)


@pytest.mark.parametrize("e", BANK.entries, ids=key)
def test_every_signed_entry_has_both_forms(e):
    s = boot(PFC_RETIRED, retired_ok=True)
    turn = s.handle(request(e))
    for _ in range(4):
        _forms(turn)
        if turn.kind != "ask" or not turn.say.startswith("Which one"):
            break
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    assert turn.kind == "readback"
    assert re.search(rf"(?<![A-Za-z]){e['route']}(?![A-Za-z])", turn.written), turn.written
    for said in ("why", "repeat", "confirm", "why", "repeat"):
        _forms(s.handle(said))


def test_the_written_read_back_has_the_letters_and_the_spoken_one_the_words():
    s = Session(BANK)
    turn = s.handle("ketamine for agitation iv eighty kilos")
    assert turn.written == "Ketamine, agitation, IV, eighty kilos. Confirm?"
    assert turn.say == "Ketamine, agitation, eye vee, eighty kilos. Confirm?"
    po = Session(BANK).handle("acetaminophen for pain po seventy kilos")
    assert po.written == "Acetaminophen, pain, PO, seventy kilos. Confirm?"
    assert "pee oh" in po.say


def test_questions_holds_and_the_pair_question_have_both_forms():
    s = Session(BANK)
    turn = s.handle("ketamine for pain eighty kilos")
    assert turn.written == "Which route: IV, IM or IN?"
    _forms(turn)
    pair = Session(BANK).handle("fentanyl for pain i n eighty kilos", spoken=True)
    assert (pair.written, pair.say) == ("IM or IN?", "Eye em or intranasal?")
    held = Session(BANK).handle("morphine for pain in eighty kilos")
    assert held.written == "No signed IN dose of morphine for pain."
    _forms(held)


def test_the_boot_line_and_an_expired_read_back_have_both_forms():
    s = Session(BANK)
    _forms(s.announce)
    t = [0.0]
    s = Session(BANK, clock=lambda: t[0])
    s.handle("ketamine for agitation iv eighty kilos")
    t[0] = 31.0
    _forms(s.expire_pending())
