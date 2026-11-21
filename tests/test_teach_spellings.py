"""The spelling step from the teach page (owner, 2026-11-21): voice/tools/teach_spellings.py.

Owner: "build the spelling step as one repeatable command: read the teach results (my
clips plus contributors' heard text), add the safe sound-alike spellings, refuse any that
collide with another drug, number or command, re-score my clips as the gate, and report
before/after."

The teach page's files and the decoders are stand-ins here (the owner's clips stay out of
the repo); the rules, the bank and the committed spellings are the real ones.
"""
import json
import pathlib
import wave

import pytest

from engine.bank import load_bank
from grammar.parser import parse
from grammar.vocabulary import build
from voice import spoken
from voice.tools import teach_spellings as ts

ROOT = pathlib.Path(__file__).resolve().parents[1]
VOCAB = build(load_bank(ROOT / "bank"))
SOUNDS = json.loads((ROOT / "grammar" / "sounds_like.json").read_text())
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
CURRENT = {s: t for t, ss in SOUNDS["spellings"].items() for s in ss}


BANK = load_bank(ROOT / "bank")


def rules():
    return ts.Rules(VOCAB, lambda w: True, CURRENT, BANK)


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\0\0" * 1600)


def take(root, speaker, word, n, heard, open_="", audio=False, kind="drug"):
    d = root / speaker / f"{kind}-{word.replace(' ', '-')}"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"word_id": d.name, "kind": kind, "say": word, "take": n, "open": open_ or heard,
           "open_alternatives": [open_ or heard, "an alternative it ranked lower"],
           "pocket": {"heard": heard, "text": heard, "decoder": "spelled"}}
    (d / f"take{n}.json").write_text(json.dumps(rec))
    if audio:
        _wav(d / f"take{n}.wav")
    return d


# ── reading what the teach page saved ───────────────────────────────────────

def test_it_reads_every_speakers_takes_and_says_what_was_saved(tmp_path):
    take(tmp_path, "speaker-1", "atropine", 1, "add troy pin", audio=True)
    take(tmp_path, "speaker-1", "atropine", 2, "atropine", audio=True)
    take(tmp_path, "speaker-4", "atropine", 1, "add troy pin")
    take(tmp_path, "speaker-4", "kilos", 1, "kilos", kind="weight")       # not a name
    (tmp_path / "speaker-4" / "session.jsonl").write_text('{"event": "skip"}\n{"event": "take"}\n')
    takes = ts.read_takes(tmp_path)
    assert [(t.speaker, t.say, t.wav is not None) for t in takes] == [
        ("speaker-1", "atropine", True), ("speaker-1", "atropine", True), ("speaker-4", "atropine", False)]
    assert "an alternative it ranked lower" not in takes[0].heard       # n-best guesses are not evidence
    s = ts.summary(takes, tmp_path)
    assert s["speaker-1"] == {"names": 1, "takes": 2, "with_audio": 2, "takes_per_name": {2: 1}, "skips": 0}
    assert s["speaker-4"]["with_audio"] == 0 and s["speaker-4"]["skips"] == 1


# ── what is refused ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("token, spelling, why", [
    ("fentanyl", "i don't know", "'i'"),                    # "i" is half of "i v"
    ("fentanyl", "you don't know", "everyday words only"),
    ("epi", "at the", "everyday words only"),
    ("fent", "french", "one everyday word"),
    ("versed", "first said", "too unlike"),
    ("atropine", "add repeat", "'repeat'"),                       # a command
    ("atropine", "add eight pin", "'eight'"),                     # a number
    ("acetaminophen", "the pain of fun", "'pain'"),               # an indication word
    ("atropine", "at i v pin", "'i'"),                            # a route's letters
    ("atropine", "atropine", "is the name itself"),
    ("atropine", "add trope ketamine", "'ketamine'"),            # another drug
    ("dextrose", "the dazzle drugs", "'drugs'"),                 # the home menu's command
    ("lorazepam", "la raza pam", "another drug's name"),         # "pam": 2-PAM, unsigned
])
def test_a_spelling_that_collides_or_is_everyday_speech_is_refused(token, spelling, why):
    got = rules().refuse(token, spelling)
    assert got is not None and why in got, got


def test_a_spelling_another_drug_already_has_is_refused():
    other, token = "acetaminophen", "atropine"
    s = SOUNDS["spellings"][other][0]
    assert "already spells acetaminophen" in rules().refuse(token, s)


def test_the_teach_pages_six_are_safe_by_these_rules():
    for token, spellings in SOUNDS["teach_added"].items():
        for s in spellings:
            r = ts.Rules(VOCAB, lambda w: True, {k: v for k, v in CURRENT.items() if k != s}, BANK)
            assert r.refuse(token, s) is None, (token, s)


def _takes(tmp_path, rows):
    for i, (speaker, word, heard) in enumerate(rows, 1):
        take(tmp_path, speaker, word, i, heard)
    return ts.read_takes(tmp_path)


def test_a_hearing_needs_two_takes_or_a_missed_clip_to_count(tmp_path):
    takes = _takes(tmp_path, [("speaker-4", "lorazepam", "lore as pan cool"),
                              ("speaker-4", "lorazepam", "lore as pan cool"),
                              ("speaker-2", "atropine", "add troy pin cool")])
    kept, refused, _ = ts.propose(takes, VOCAB, rules())
    assert kept == {"lorazepam": ["lore as pan cool"]}
    assert "heard once" in refused["atropine"]["add troy pin cool"]
    kept, _, _ = ts.propose(takes, VOCAB, rules(), rescues={"add troy pin cool"})
    assert kept["atropine"] == ["add troy pin cool"]


def test_a_hearing_heard_for_two_drugs_is_refused_for_both(tmp_path):
    takes = _takes(tmp_path, [("speaker-1", "lorazepam", "rob a pam"), ("speaker-1", "lorazepam", "rob a pam"),
                              ("speaker-4", "propofol", "rob a pam"), ("speaker-4", "propofol", "rob a pam")])
    kept, refused, _ = ts.propose(takes, VOCAB, rules())
    assert not kept
    assert "two names" in refused["lorazepam"]["rob a pam"] and "two names" in refused["propofol"]["rob a pam"]


def test_a_hearing_that_is_already_the_name_adds_nothing(tmp_path):
    takes = _takes(tmp_path, [("speaker-1", "atropine", "atropine"), ("speaker-1", "atropine", "atropine")])
    kept, refused, _ = ts.propose(takes, VOCAB, rules())
    assert kept == {} and refused == {}


# ── before and after, and nothing kept that misleads a clip ────────────────

class Ears:
    """Each clip is heard as given; the text is read with the spellings scored."""

    def __init__(self, heard):
        self.heard = heard                    # wav name -> what the decoder heard

    def known(self, w):
        return True

    def hear_with(self, sounds):
        def hear(wav):
            h = self.heard[pathlib.Path(wav).parent.name + "/" + pathlib.Path(wav).name]
            return h, spoken.normalise(h, sounds)
        return hear


def test_the_gate_is_scored_before_and_after_and_a_misleading_spelling_is_dropped(tmp_path, monkeypatch):
    clips, gate = tmp_path / "clips", tmp_path / "gate"
    gate.mkdir()
    for i, name in enumerate(["lorazepam", "atropine"], 1):
        _wav(gate / f"{i:03d}.wav")
    (gate / "results.jsonl").write_text('{"typed": "lorazepam"}\n{"typed": "atropine"}\n')
    take(clips, "speaker-1", "lorazepam", 1, "lore as pan cool", audio=True)
    take(clips, "speaker-1", "lorazepam", 2, "lore as pan cool", audio=True)
    take(clips, "speaker-4", "propofol", 1, "add troy pin cool")
    take(clips, "speaker-4", "propofol", 2, "add troy pin cool")
    ears = Ears({"gate/001.wav": "lore as pan cool", "gate/002.wav": "add troy pin cool",
                 "drug-lorazepam/take1.wav": "lore as pan cool", "drug-lorazepam/take2.wav": "lorazepam"})
    monkeypatch.setattr(ts, "SOUNDS_LIKE", ROOT / "grammar" / "sounds_like.json")
    r = ts.run(None, clips, gate, ears=ears, out_dir=tmp_path / "out", print=lambda *a: None)
    assert r["before"]["gate"]["heard"] == 0 and r["after"]["gate"]["heard"] == 1      # lorazepam, rescued
    assert r["added"] == {"lorazepam": ["lore as pan cool"]}
    # "add troy pin cool", taught for propofol, would make the atropine gate clip propofol
    assert r["refused"]["propofol"]["add troy pin cool"] == "made a clip heard as another drug"
    assert r["after"]["gate"]["another_drug"] == []
    assert r["teach"]["speaker-1"]["with_audio"] == 2
    assert json.loads((tmp_path / "out" / "report.json").read_text())["added"] == r["added"]
    assert r["applied"] is False


def test_apply_writes_the_spellings_and_keeps_nothing_if_the_dry_run_gets_worse(tmp_path, monkeypatch):
    sounds, grammar, dry = tmp_path / "sounds.json", tmp_path / "grammar.json", tmp_path / "dry.json"
    sounds.write_text(json.dumps({"spellings": {"atropine": ["add true pin"]}}))
    grammar.write_text("{}")
    dry.write_text(json.dumps({"heard": 177, "heard_as_another_drug": 0}))
    monkeypatch.setattr(ts, "SOUNDS_LIKE", sounds)
    monkeypatch.setattr(ts, "GRAMMAR", grammar)
    monkeypatch.setattr(ts, "ROOT", tmp_path)
    (tmp_path / "voice").mkdir()
    dry.rename(tmp_path / "voice" / "dryrun_drugs.json")
    from voice import grammar as vg
    from voice.tools import dryrun_drugs
    monkeypatch.setattr(vg, "generate", lambda model: {"words": ["new"]})
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    (tmp_path / "projects" / "pocket-hearing" / "bench-out" / "dryrun-kokoro").mkdir(parents=True)
    result = {"heard": 177, "heard_as_another_drug": 0}

    def score(model, w):
        (tmp_path / "voice" / "dryrun_drugs.json").write_text(json.dumps(result))
    monkeypatch.setattr(dryrun_drugs, "score", score)
    raw = json.loads(sounds.read_text())
    assert ts._apply(raw, {"atropine": ["add troy pin"]}, {"atropine": {"at the": "everyday words only"}},
                     "model", print=lambda *a: None) is True
    new = json.loads(sounds.read_text())
    assert new["spellings"]["atropine"] == ["add troy pin", "add true pin"]
    assert new["teach_added"] == {"atropine": ["add troy pin"]}
    assert new["teach_refused"] == {"atropine": {"at the": "everyday words only"}}
    assert json.loads(grammar.read_text()) == {"words": ["new"]}
    # the dry run gets worse: nothing is kept
    sounds.write_text(json.dumps({"spellings": {}}))
    grammar.write_text("{}")
    result.update(heard_as_another_drug=1)
    assert ts._apply({"spellings": {}}, {"atropine": ["add troy pin"]}, {}, "model", print=lambda *a: None) is False
    assert json.loads(sounds.read_text()) == {"spellings": {}} and grammar.read_text() == "{}"


# ── what this PR added ──────────────────────────────────────────────────────

def test_each_spelling_from_the_teach_page_is_in_the_grammar_and_is_that_drug_alone():
    added = SOUNDS["teach_added"]
    assert sum(map(len, added.values())) == 5
    for token, spellings in added.items():
        for s in spellings:
            assert s in SOUNDS["spellings"][token] and s in GRAMMAR["words"], s
            p = parse(spoken.normalise(s), VOCAB)
            assert [d.generics for d in p.drugs] == [VOCAB.drug_terms[token]], s
            assert not (p.unknown or p.controls or p.routes or p.weight or p.bare_number), s


def test_the_dry_run_still_hears_no_drug_as_another():
    d = json.loads((ROOT / "voice" / "dryrun_drugs.json").read_text())
    assert d["heard_as_another_drug"] == 0 and d["heard"] >= 177
