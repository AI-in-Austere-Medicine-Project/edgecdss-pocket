"""Dev tool: is every route, procedure and command heard? (owner, 2026-11-23) The same
check as dryrun_drugs.py, for the words that are not drug names.

  python3 -m voice.tools.dryrun_words jobs JOBS.json
  ~/pi-cloud-cdss/.venv/bin/python voice/tools/synth_kokoro.py JOBS.json WAVDIR
  python3 -m voice.tools.dryrun_words score MODEL_DIR WAVDIR     -> voice/dryrun_words.json

Each route (letters and words), procedure name and command, said alone in the three
held-out voices, is decoded with grammar/vosk_grammar.json and read by the parser. A clip is
heard when the parser reads the word's own meaning (its route, command, procedure or
class) and nothing more. Synthetic speech: a gate before the medic's own voice, not a
measurement of it.
"""
import hashlib
import json
import pathlib
import sys
import wave

from engine.bank import BANK_DIR, load_bank
from grammar.parser import parse
from grammar.vocabulary import CONTROLS, PROCEDURE_TERMS, ROUTES, build
from voice import spoken
from voice.tools.dryrun_drugs import VOICES, clip_id

ROOT = pathlib.Path(__file__).resolve().parents[2]


def words() -> list:
    """[{"word", "kind"}]: Pocket's routes ("i v" and "iv" once, as "iv"), procedures and
    commands, in its own order."""
    out, seen = [], set()

    def add(word, kind):
        if word not in seen:
            seen.add(word)
            out.append({"word": word, "kind": kind})
    for r in ROUTES:
        add(r.replace(" ", "") if len(r) == 3 and r[1] == " " else r, "route")
    for p in ("rsi", *PROCEDURE_TERMS):
        add(p, "procedure")
    for c in CONTROLS:
        add(c, "command")
    return out


def prompt(word: str) -> str:
    """What the voice says: a word of letters as its letters ("i v", "r s i"); a phrase as
    its words, so "in the vein" keeps its "in"."""
    return spoken.SPELLED.get(word, word) if " " not in word else word


def meaning(text: str, vocab) -> dict:
    p = parse(spoken.normalise(text), vocab)
    return {"routes": sorted(p.routes), "controls": list(p.controls),
            "procedures": list(p.procedures), "classes": list(p.classes),
            "drugs": sorted(g for d in p.drugs for g in d.generics)}


def jobs(path):
    js = [[clip_id(w["word"], v), prompt(w["word"]), v, 1.0] for w in words() for v in VOICES]
    pathlib.Path(path).write_text(json.dumps(js))
    print(len(js) // len(VOICES), "words,", len(js), "clips")


def score(model_dir, wavdir):
    import vosk
    from voice.hear import Hearing
    vosk.SetLogLevel(-1)
    gpath = ROOT / "grammar" / "vosk_grammar.json"
    vocab = build(load_bank(BANK_DIR))
    hearing = Hearing(vosk.Model(str(model_dir)), json.loads(gpath.read_text()), vocab)
    rows = []
    for w in words():
        want = meaning(w["word"], vocab)
        for v in VOICES:
            u = hearing.start()
            with wave.open(str(pathlib.Path(wavdir) / f"{clip_id(w['word'], v)}.wav")) as f:
                u.feed(f.readframes(f.getnframes()))
            heard, text, _ = u.finish()
            got = meaning(text, vocab)
            rows.append({**w, "voice": v, "heard": heard, "want": want, "got": got,
                         "ok": got == want and any(want.values())})
    report = {"grammar_sha256": hashlib.sha256(gpath.read_bytes()).hexdigest(), "voices": list(VOICES),
              "words": len(rows) // len(VOICES), "clips": len(rows), "heard": sum(r["ok"] for r in rows),
              "rows": rows}
    (ROOT / "voice" / "dryrun_words.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"{report['heard']}/{len(rows)} clips heard as their word")
    for r in rows:
        if not r["ok"]:
            print(f"  {r['kind']:10} {r['word']!r:24} {r['voice']:10} heard {r['heard']!r}")


if __name__ == "__main__":
    {"jobs": lambda: jobs(sys.argv[2]), "score": lambda: score(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
