"""Hearing fixes before outside testers (owner, 2026-11-15).

Owner: "1. Routes: accept "i v", "iv", "intravenous", "in the vein"; "i m",
"intramuscular"; "i o", "intraosseous"; "p o", "by mouth", "oral"; "i n", "intranasal".
The clip heard as "i dvt kilos" must parse as IV. 2. The grammar's drug words come only
from the active set's signed drugs. An unsigned drug is not a recognisable word; it gets
"Not recognised." The ertapenem clip must not come back as rifampin. 3. Fix cefazolin's
phonetic spelling so the owner's clip is heard. 4. Any pair the clips or the sound-alike
check confuse always asks "X or Y?" before the read-back."

Fixtures: tests/fixtures/clips/w1_*.wav are Piper (en_US-lessac-low) saying the W1 example
"ketamine for agitation i v eighty kilos" (synthetic; the W1 tunnel run kept no audio, so
these are the same prompt re-synthesised until the same mishearings came back: "i dvt
kilos", "i'd it eighty", "ip eighty", "i viewed eighty"). The owner's gate clips are the
owner's voice and stay out of the repo: POCKET_OWNER_CLIPS (default bench-out/
gate-radxa-usbmic-20261111); those tests skip without them, and without the Vosk model
(POCKET_VOSK_MODEL).
"""
import json
import os
import pathlib
import wave

import pytest

from engine.bank import load_bank
from engine.session import Session, boot
from grammar.parser import parse
from grammar.vocabulary import build
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
SOUNDS = json.loads((ROOT / "grammar" / "sounds_like.json").read_text())
CLIPS = sorted((ROOT / "tests" / "fixtures" / "clips").glob("w1_*.wav"))
OWNER = pathlib.Path(os.getenv("POCKET_OWNER_CLIPS", ROOT / "bench-out" / "gate-radxa-usbmic-20261111"))
MODEL = pathlib.Path(os.getenv("POCKET_VOSK_MODEL", pathlib.Path.home() / "pocket-web" / "models"
                                / "vosk-model-small-en-us-0.15"))


def _vosk():
    try:
        import vosk
    except ImportError:
        return None
    return vosk


needs_model = pytest.mark.skipif(not (MODEL.exists() and _vosk()),
                                 reason=f"needs vosk and the model at {MODEL} (POCKET_VOSK_MODEL)")
needs_owner = pytest.mark.skipif(not (OWNER / "results.jsonl").exists(),
                                 reason=f"the owner's gate clips are not at {OWNER} (POCKET_OWNER_CLIPS)")


@pytest.fixture(scope="module")
def hearing():
    vosk = _vosk()
    vosk.SetLogLevel(-1)
    from voice.hear import Hearing
    return Hearing(vosk.Model(str(MODEL)), GRAMMAR, VOCAB)


def _heard(hearing, path):
    u = hearing.start()
    with wave.open(str(path)) as w:
        u.feed(w.readframes(w.getnframes()))
    return u.finish()


def _routes(text):
    return parse(text, VOCAB).routes


# ── 1. routes ───────────────────────────────────────────────────────────────

ROUTE_WORDS = [("i v", "IV"), ("iv", "IV"), ("intravenous", "IV"), ("in the vein", "IV"),
               ("i m", "IM"), ("intramuscular", "IM"), ("i o", "IO"), ("intraosseous", "IO"),
               ("p o", "PO"), ("by mouth", "PO"), ("oral", "PO"), ("i n", "IN"), ("intranasal", "IN")]


@pytest.mark.parametrize("said, route", ROUTE_WORDS)
def test_every_route_word_the_owner_listed_parses_as_its_route(said, route):
    assert _routes(f"ketamine for agitation {said} eighty kilos") == [route]


@pytest.mark.parametrize("said, route", ROUTE_WORDS)
def test_every_route_word_can_be_heard(said, route):
    """Each word is in the grammar, or (intraosseous, not in the model) has spellings."""
    entries = set(GRAMMAR["words"])
    spelled = {s for s, token in spoken.spellings().items() if token == said}
    assert set(said.split()) <= entries or spelled & entries, said


def test_the_i_dvt_kilos_hearing_can_no_longer_happen():
    """"dvt" took the v of "i v": it is not in the grammar (typed, it is still a condition)."""
    assert "dvt" not in GRAMMAR["words"] and "dvt" not in GRAMMAR["base_words"]
    assert parse("txa for haemorrhage dvt", VOCAB).conditions == ["thrombosis"]


@needs_model
@pytest.mark.parametrize("clip", CLIPS, ids=lambda p: p.stem)
def test_the_w1_clips_parse_as_iv(hearing, clip):
    """Including the clips heard as "i dvt kilos" on the old grammar."""
    heard, text, _ = _heard(hearing, clip)
    assert _routes(text) == ["IV"], heard
    assert Session(BANK).handle(text, spoken=True).text == "Ketamine, agitation, eye vee, eighty kilos. Confirm?"


def test_there_are_w1_iv_fixtures_including_the_i_dvt_ones():
    names = {p.stem for p in CLIPS}
    assert {"w1_iv_091", "w1_iv_104"} <= names and len(CLIPS) >= 8


# ── 2. the grammar's drug words: signed drugs only ──────────────────────────

def _unsigned_only_words():
    signed_words = VOCAB.words(signed_only=True)
    out = set()
    for n in BANK.no_signed_dose:
        for term in [n["drug"], *n["aliases"]]:
            out |= set(term.lower().replace("-", " ").split()) - signed_words
    return out


def test_no_word_only_an_unsigned_drug_uses_is_in_the_grammar():
    words = _unsigned_only_words()
    assert "rifampin" in words and "magnesium" in words
    for g in (GRAMMAR["words"], GRAMMAR["base_words"]):
        assert not words & {w for e in g for w in e.split()}, sorted(words & set(g))[:10]


def test_no_spelling_of_an_unsigned_drug_is_in_the_grammar():
    unsigned = {n["drug"] for n in BANK.no_signed_dose}
    signed_words = VOCAB.words(signed_only=True)
    entries = set(GRAMMAR["words"])
    for token, ss in SOUNDS["spellings"].items():
        if not set(token.split()) <= signed_words | set(spoken.SPELLED):
            assert not set(ss) & entries, token
    assert "ertapenem" not in unsigned        # signed: its spellings stay


def test_an_unsigned_name_heard_is_not_recognised():
    """What Vosk gives for a word outside the grammar."""
    assert Session(BANK).handle("[unk]", spoken=True).text == "Not recognised."


def test_typed_an_unsigned_drug_still_holds_by_name():
    """The grammar change is for hearing; typed text is read as before (README C2)."""
    assert boot(ROOT / "bank").handle("magnesium").text == "No signed dose for magnesium."


# ── 3. cefazolin ────────────────────────────────────────────────────────────

def test_cefazolin_is_spelled_as_the_owners_clip_is_heard():
    assert "suffers own" in SOUNDS["spellings"]["cefazolin"]
    assert "suffers own" in GRAMMAR["words"]
    assert spoken.normalise("suffers own") == "cefazolin"


# ── 4. a confused pair always asks "X or Y?" before the read-back ───────────

CONFUSABLE = json.loads((ROOT / "grammar" / "confusable.json").read_text())


def test_the_pairs_are_the_ones_the_clips_and_checks_confused():
    drugs = {tuple(sorted(r["pair"])) for r in CONFUSABLE["drugs"]}
    assert ("epinephrine", "norepinephrine") in drugs
    routes = {tuple(r["pair"]): r["terms"] for r in CONFUSABLE["routes"]}
    assert set(routes[("IM", "IN")]) == {"i m", "im", "i n", "in"}
    assert all(r.get("source") for r in CONFUSABLE["drugs"] + CONFUSABLE["routes"])


@pytest.mark.parametrize("pair", [r["pair"] for r in CONFUSABLE["drugs"]])
def test_hearing_either_drug_of_a_pair_asks_x_or_y_first(pair):
    a, b = sorted(pair)
    ask = f"{a.capitalize()} or {b}?"
    for said in pair:
        s = boot(ROOT / "bank")
        turn = s.handle(f"{said} eighty kilos", spoken=True)
        assert turn.kind == "ask" and turn.say == ask, (said, turn.text)
        answer = s.handle(said, spoken=True)
        assert answer.say != ask and s.req.drug == said, answer.text


def test_the_pair_is_asked_before_the_read_back():
    s = boot(ROOT / "bank")
    turns = [s.handle(p, spoken=True) for p in
             ("epinephrine for anaphylaxis intramuscular eighty kilos", "epinephrine")]
    assert turns[0].say == "Epinephrine or norepinephrine?"
    assert turns[1].kind == "readback"
    assert turns[1].say.startswith("Epinephrine, anaphylaxis, eye em")


def test_a_letter_spelled_im_or_in_asks_im_or_in_first():
    for said in ("i m", "im", "i n", "in"):
        s = boot(ROOT / "bank")
        turn = s.handle(f"fentanyl for pain {said} eighty kilos", spoken=True)
        assert turn.say == "Eye em or intranasal?", (said, turn.text)
        answer = s.handle("intranasal", spoken=True)
        assert answer.kind == "readback" and ", intranasal," in answer.say


def test_the_route_answer_may_be_the_letters_again():
    s = boot(ROOT / "bank")
    s.handle("fentanyl for pain i n eighty kilos", spoken=True)
    assert s.handle("i n", spoken=True).say == "Fentanyl, pain, intranasal, eighty kilos. Confirm?"


def test_the_whole_route_words_do_not_ask():
    for said, route in (("intramuscular", "eye em"), ("intranasal", "intranasal")):
        s = boot(ROOT / "bank")
        turn = s.handle(f"ketamine for agitation {said} eighty kilos" if route == "eye em"
                        else f"fentanyl for pain {said} eighty kilos", spoken=True)
        assert turn.kind == "readback" and f", {route}," in turn.say, turn.text


def test_typed_text_cannot_be_misheard_so_it_does_not_ask():
    s = boot(ROOT / "bank")
    assert s.handle("fentanyl for pain in eighty kilos").kind == "readback"
    s = boot(ROOT / "bank")
    assert s.handle("epinephrine for anaphylaxis im eighty kilos").kind == "readback"


# ── the owner's clips ───────────────────────────────────────────────────────

def _owner_rows(hearing):
    names = [json.loads(l)["typed"] for l in (OWNER / "results.jsonl").read_text().splitlines()]
    rows = []
    for i, name in enumerate(names, 1):
        clip = OWNER / f"{i:03d}.wav"
        with wave.open(str(clip)) as w:
            if w.getnframes() / w.getframerate() > 15:     # Pocket's own 15 s limit
                continue
        heard, text, _ = _heard(hearing, clip)
        got = {g for d in parse(text, VOCAB).drugs for g in d.generics}
        want = {g for d in parse(name, VOCAB).drugs for g in d.generics}
        rows.append((name, heard, got, want))
    return rows


@needs_model
@needs_owner
def test_no_owner_clip_is_heard_as_another_drug(hearing):
    pairs = set(VOCAB.confusable.items())
    for name, heard, got, want in _owner_rows(hearing):
        allowed = set(want) | {x for g in want for x in VOCAB.confusable.get(g, ())}
        assert got <= allowed, (name, heard, sorted(got))


@needs_model
@needs_owner
def test_the_ertapenem_clip_is_not_rifampin_and_the_cefazolin_clip_is_cefazolin(hearing):
    rows = {name: (heard, got) for name, heard, got, _ in _owner_rows(hearing)}
    assert "rifampin" not in rows["ertapenem"][1] and "rifampin" not in rows["ertapenem"][0]
    assert rows["cefazolin"][1] == {"cefazolin"}, rows["cefazolin"]
