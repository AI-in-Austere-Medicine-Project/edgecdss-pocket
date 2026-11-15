"""Dev tool: are all 25 signed drugs heard? Synthetic held-out voices, the real grammar.

  python3 -m voice.tools.dryrun_drugs jobs JOBS.json
  ~/pi-cloud-cdss/.venv/bin/python voice/tools/synth_kokoro.py JOBS.json WAVDIR
  python3 -m voice.tools.dryrun_drugs score MODEL_DIR WAVDIR     -> voice/dryrun_drugs.json

Every sayable name of every signed drug (bank name, aliases, medic forms), said alone in
voices not used to make the spellings. Each is decoded with grammar/vosk_grammar.json,
normalised, and handed to a fresh Session; the row records which drug the session then
holds (or the drugs it asks between). Synthetic speech: a gate before the spoken replay,
not a measurement of it.
"""
import hashlib
import json
import pathlib
import sys
import wave

from engine.bank import load_bank
from engine.session import boot
from grammar.vocabulary import MEDIC_NAMES, _say_term, build
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[2]
VOICES = ("af_nicole", "am_liam", "bf_lily")


def names():
    bank = load_bank(ROOT / "bank")
    vocab = build(bank)
    groups = {}
    for e in bank.entries:
        groups.setdefault(e["drug"], [e["drug"]])
        groups[e["drug"]] += [a for a in e["aliases"] if a not in groups[e["drug"]]]
    for said, generic in MEDIC_NAMES.items():
        groups[generic].append(said)
    out = []
    for drug, raw in sorted(groups.items()):
        said = [s for s in dict.fromkeys(_say_term(n) for n in raw) if s]
        for name in said:
            options = vocab.drug_terms.get(name, ())
            out.append({"drug": drug, "name": name, "primary": said[0],
                        "asks": list(options) if len(options) > 1 else []})
    return out


def jobs(path):
    rows = names()
    js = [[f"{i:03d}__{v}", spoken.prompt(r["name"]), v, 1.0] for i, r in enumerate(rows) for v in VOICES]
    pathlib.Path(path).write_text(json.dumps(js))
    print(len(rows), "names,", len(js), "clips")


def score(model_dir, wavdir):
    import vosk
    vosk.SetLogLevel(-1)
    gpath = ROOT / "grammar" / "vosk_grammar.json"
    g = json.loads(gpath.read_text())
    from voice.hear import Hearing
    hearing = Hearing(vosk.Model(str(model_dir)), g, build(load_bank(ROOT / "bank")))
    out = []
    for i, r in enumerate(names()):
        for v in VOICES:
            u = hearing.start()
            with wave.open(str(pathlib.Path(wavdir) / f"{i:03d}__{v}.wav")) as w:
                u.feed(w.readframes(w.getnframes()))
            heard, text, which = u.finish()
            s = boot(ROOT / "bank")
            turn = s.handle(text)
            heard_as = [s.req.drug] if s.req.drug else list(s.req.options)
            out.append({**r, "voice": v, "heard": heard, "decoder": which, "heard_as": heard_as,
                        "turn": turn.say})
    ok = [r for r in out if r["heard_as"] == [r["drug"]] or (r["asks"] and r["heard_as"] == r["asks"])]
    wrong = [r for r in out if set(r["heard_as"]) - {r["drug"]} - set(r["asks"])]
    report = {"grammar_sha256": hashlib.sha256(gpath.read_bytes()).hexdigest(), "voices": list(VOICES),
              "names": len(out) // len(VOICES), "clips": len(out), "heard": len(ok),
              "heard_as_another_drug": len(wrong), "rows": out}
    (ROOT / "voice" / "dryrun_drugs.json").write_text(json.dumps(report, indent=1) + "\n")
    drugs = {r["drug"] for r in out}
    primary_ok = {d for d in drugs if all(r["heard_as"] == [d] for r in out if r["drug"] == d and r["name"] == r["primary"])}
    print(f"{len(ok)}/{len(out)} clips heard as their drug; {len(wrong)} as another drug; "
          f"primary name heard in every voice: {len(primary_ok)}/{len(drugs)} drugs")
    for r in out:
        if r not in ok:
            print(f"  {r['drug']:20} {r['name']!r:24} {r['voice']:10} heard {r['heard']!r} -> {r['heard_as']}")


if __name__ == "__main__":
    {"jobs": lambda: jobs(sys.argv[2]), "score": lambda: score(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
