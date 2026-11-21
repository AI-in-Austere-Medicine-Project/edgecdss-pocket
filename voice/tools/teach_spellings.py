"""The spelling step from the teach page, as one repeatable command (owner, 2026-11-21).

  python3 -m voice.tools.teach_spellings MODEL_DIR [--clips DIR] [--gate DIR] [--apply]

  1. Reads what the teach page saved (--clips, default ~/pocket-web/owner-clips): every
     take of a drug or medic name, by every speaker. The owner's takes keep the WAV;
     contributors' keep only what Vosk heard (open, its alternatives, and through Pocket's
     grammar).
  2. Each thing heard that is not already the name is a candidate spelling of that name.
     A candidate is refused if it holds a word that means something else to the parser
     (another drug's word, a number, a route, a unit, a command, a condition, a label),
     holds a whole command, is a word the model cannot hear, is an everyday phrase or one
     everyday word for a long name, is already another name's spelling, or was heard for
     two different drugs. What is kept must parse as that drug alone.
  3. Re-scores the gate (--gate, default the owner's 2026-11-11 gate clips) and the owner's
     teach takes with the spellings before and after. A new spelling that makes any clip
     heard as another drug is dropped, and the rest scored again.
  4. With --apply: grammar/sounds_like.json gets the kept spellings ("teach_added") and the
     refusals ("teach_refused"), grammar/vosk_grammar.json is regenerated, and the
     synthetic dry run is scored again; if it hears any drug as another, or fewer, nothing
     is kept. Without --apply nothing in the repo changes.

Run it again after more teach sessions: a spelling already there is not added twice, so a
second run with nothing new changes nothing. The report goes to bench-out/ (the clips and
what contributors said stay out of the repo); the numbers go in the PR.
"""
import argparse
import collections
import os
import dataclasses
import datetime
import difflib
import json
import pathlib
import re
import wave

from engine.bank import load_bank
from grammar.parser import parse
from grammar.vocabulary import CONTROLS, FILLERS, build, menu_only_words
from voice import spoken
from voice.grammar import grammar_words, model_id
from voice.tools.make_spellings import MAX_WORDS, NOT_A_NAME, keep

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOUNDS_LIKE = ROOT / "grammar" / "sounds_like.json"
GRAMMAR = ROOT / "grammar" / "vosk_grammar.json"
CLIPS = pathlib.Path.home() / "pocket-web" / "owner-clips"
GATE = pathlib.Path(os.getenv("POCKET_OWNER_CLIPS", ROOT / "bench-out" / "gate-radxa-usbmic-20261111"))
MAX_CLIP_S = 15.0           # Pocket's own listening limit
NAME_KINDS = ("drug", "medic")


# Words that carry no sound of a name: a spelling made only of these is everyday speech
# ("i don't know", "at the", "he say") and would turn it into a drug request.
FUNCTION_WORDS = frozenset("""a an the and or but if of to in on at by for from with without as
up down out off over under into onto about than then so not no yes yeah oh ah um uh hmm okay ok
i i'm i've i'd i'll me my mine you you're your yours he he's him his she her hers it it's its we
our us they them their there here this that these those what who whom which when where why how
is am are was were be been being do does did don't doesn't didn't have has had having can can't
could would should will won't shall may might must say says said know knew go going get got just
like now well also too very really all any some""".split())
MIN_TAKES = 2               # a contributor's hearing counts when it was heard at least twice
ONE_WORD_LIKE = 0.8         # a one-word spelling must be this close to the name, letter by letter
MIN_LIKE = 0.45             # any spelling at least this close ("first said" for versed is 0.40)


@dataclasses.dataclass
class Take:
    speaker: str
    word_id: str
    say: str
    heard: list             # what Vosk heard: open, its alternatives, through the grammar
    wav: object = None      # the owner's takes only


def read_takes(clips: pathlib.Path) -> list:
    out = []
    for sp in sorted(p for p in pathlib.Path(clips).glob("speaker-*") if p.is_dir()):
        for word in sorted(p for p in sp.iterdir() if p.is_dir()):
            for t in sorted(word.glob("take*.json")):
                r = json.loads(t.read_text())
                if r.get("kind") not in NAME_KINDS:
                    continue
                # What Vosk heard best, open and through Pocket's grammar; not its n-best
                # alternatives, which are guesses it ranked lower.
                heard = [r.get("open") or "", (r.get("pocket") or {}).get("heard") or ""]
                wav = t.with_suffix(".wav")
                out.append(Take(sp.name, r["word_id"], r["say"], [h for h in dict.fromkeys(heard) if h],
                                wav if wav.exists() else None))
    return out


def summary(takes: list, clips: pathlib.Path) -> dict:
    """Per speaker: names done, takes, takes with audio, skips."""
    out = {}
    for sp in sorted(p for p in pathlib.Path(clips).glob("speaker-*") if p.is_dir()):
        mine = [t for t in takes if t.speaker == sp.name]
        words = collections.Counter(t.word_id for t in mine)
        log = sp / "session.jsonl"
        skips = sum(json.loads(x).get("event") == "skip" for x in log.read_text().splitlines()) if log.exists() else 0
        out[sp.name] = {"names": len(words), "takes": len(mine), "with_audio": sum(t.wav is not None for t in mine),
                        "takes_per_name": dict(collections.Counter(words.values())), "skips": skips}
    return out


def _like(s: str, token: str) -> float:
    """How close a spelling is to the name, letter by letter, spaces left out."""
    return difflib.SequenceMatcher(None, s.replace(" ", ""), token.replace(" ", "")).ratio()


def target(say: str, vocab):
    """The signed drug term a take was of, or None."""
    t = " ".join(say.lower().replace("-", " ").split())
    return t if t in vocab.signed_terms() else None


class Rules:
    """What a candidate may not be (the rules voice/tests/test_sounds_like.py pins)."""

    def __init__(self, vocab, known, sounds: dict, bank=None):
        self.vocab, self.known, self.sounds = vocab, known, sounds     # sounds: {spelling: token}
        # Every word of every drug's name and alias in the bank, signed or not, sayable or
        # not ("pam" of 2-PAM): an unsigned name's words stay out of the grammar.
        self.names = {w for t in vocab.drug_terms for w in t.split()}
        for e in (bank.entries + bank.no_signed_dose) if bank is not None else ():
            for t in [e["drug"], *e.get("aliases", [])]:
                self.names |= set(re.findall(r"[a-z]+", t.lower()))
        self.meaningful = (((vocab.words() - set(FILLERS)) | {w for c in CONTROLS for w in c.split()})
                           - menu_only_words(vocab))

    def drugs(self, token):
        return self.vocab.drug_terms.get(token) or (token,)

    def refuse(self, token: str, s: str):
        """Why `s` may not spell `token`, or None."""
        words = s.split()
        own = set(token.split()) | set(spoken.SPELLED.get(token, "").split())
        if s == token:
            return "is the name itself"
        if not words or len(words) > MAX_WORDS:
            return "too long"
        if not all(self.known(w) for w in words):
            return "holds a word the model cannot hear"
        bad = sorted((set(words) - own) & self.meaningful)
        if bad:
            return f"holds {', '.join(repr(b) for b in bad)}, which means something else to the parser"
        for c in CONTROLS:
            if f" {c} " in f" {s} ":
                return f"holds the command {c!r}"
        if s in NOT_A_NAME or not keep(token, s):
            return "an everyday word or phrase"
        if all(w in FUNCTION_WORDS for w in words):
            return "everyday words only"
        if len(words) == 1 and _like(s, token) < ONE_WORD_LIKE:
            return "one everyday word, not close to the name"
        if _like(s, token) < MIN_LIKE:
            return f"too unlike the name ({_like(s, token):.2f})"
        if set(words) & (self.names - own):
            return "holds a word of another drug's name"
        other = self.sounds.get(s)
        if other is not None and self.drugs(other) != self.drugs(token):
            return f"already spells {other}"
        p = parse(spoken.normalise(s, {**self.sounds, s: token}), self.vocab)
        alone = not (p.unknown or p.controls or p.routes or p.weight or p.age or p.bare_number
                     or p.bad_number or p.classes or p.labels or p.conditions or p.procedures)
        if [m.generics for m in p.drugs] != [self.drugs(token)] or not alone:
            return "does not parse as that drug alone"
        return None


def propose(takes: list, vocab, rules: Rules, rescues=frozenset()) -> tuple:
    """({token: [spellings]}, {token: {spelling: why}}, {spelling: speakers}). A spelling
    needs evidence: heard in MIN_TAKES takes, or how a missed clip of the owner's was
    heard (`rescues`)."""
    seen = collections.defaultdict(set)              # spelling -> tokens heard for
    by = collections.defaultdict(set)                # spelling -> speakers
    count = collections.Counter()
    for t in takes:
        token = target(t.say, vocab)
        if token is None:
            continue
        for h in t.heard:
            h = " ".join(h.lower().split())
            if spoken.normalise(h) == token:          # already heard as the name
                continue
            seen[h].add(token)
            by[h].add(t.speaker)
            count[h] += 1
    kept, refused = collections.defaultdict(list), collections.defaultdict(dict)
    for s, tokens in sorted(seen.items()):
        if len({rules.drugs(x) for x in tokens}) > 1:
            for x in tokens:
                refused[x][s] = f"heard for two names: {', '.join(sorted(tokens))}"
            continue
        token = min(tokens)
        if rules.sounds.get(s) is not None and rules.drugs(rules.sounds[s]) == rules.drugs(token):
            continue                                  # already there
        why = rules.refuse(token, s)
        if not why and count[s] < MIN_TAKES and s not in rescues:
            why = f"heard once, not for a missed clip of the owner's"
        if why:
            refused[token][s] = why
        else:
            kept[token].append(s)
    return dict(kept), dict(refused), {s: sorted(v) for s, v in by.items()}


# ── scoring ─────────────────────────────────────────────────────────────────

def gate_clips(gate: pathlib.Path, vocab) -> list:
    """(label, wav, the drug it is of) for the owner's gate clips."""
    rows = []
    res = pathlib.Path(gate) / "results.jsonl"
    if not res.exists():
        return rows
    for i, line in enumerate(res.read_text().splitlines(), 1):
        name = json.loads(line)["typed"]
        wav = pathlib.Path(gate) / f"{i:03d}.wav"
        want = {g for d in parse(name, vocab).drugs for g in d.generics}
        if wav.exists() and want and _seconds(wav) <= MAX_CLIP_S:
            rows.append((f"gate {i:03d} {name}", wav, frozenset(want)))
    return rows


def teach_clips(takes: list, vocab) -> list:
    rows = []
    for t in takes:
        token = target(t.say, vocab)
        if t.wav is not None and token and _seconds(t.wav) <= MAX_CLIP_S:
            rows.append((f"teach {t.speaker} {t.word_id} {t.wav.stem}", t.wav, frozenset(vocab.drug_terms[token])))
    return rows


def _seconds(wav) -> float:
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def score(rows: list, hear, vocab) -> dict:
    """hear(wav) -> the parser's text. Heard as its drug, as another drug, or missed."""
    out = {"clips": len(rows), "heard": 0, "another_drug": [], "missed": []}
    for label, wav, want in rows:
        heard, text = hear(wav)
        got = {g for d in parse(text, vocab).drugs for g in d.generics}
        allowed = set(want) | {x for g in want for x in vocab.confusable.get(g, ())}
        if got and got <= allowed:
            out["heard"] += 1
        elif got:
            out["another_drug"].append({"clip": label, "heard": heard, "as": sorted(got)})
        else:
            out["missed"].append({"clip": label, "heard": heard})
    return out


class Ears:
    """Pocket's two decoders (voice/hear.py) over a given grammar and spellings."""

    def __init__(self, model, vocab):
        self.model, self.vocab = model, vocab

    def known(self, w) -> bool:
        return self.model.vosk_model_find_word(w) >= 0

    def hear_with(self, sounds: dict):
        from voice.hear import Hearing
        words, _ = grammar_words(self.vocab, self.known, sounds)
        base, _ = grammar_words(self.vocab, self.known, sounds={})
        hearing = Hearing(self.model, {"words": words, "base_words": base}, self.vocab, sounds=sounds)

        def hear(wav):
            u = hearing.start()
            with wave.open(str(wav)) as w:
                u.feed(w.readframes(w.getnframes()))
            heard, text, _ = u.finish()
            return heard, text
        return hear


def run(model_dir, clips=CLIPS, gate=GATE, apply=False, ears=None, out_dir=None, print=print) -> dict:
    bank = load_bank(ROOT / "bank")
    vocab = build(bank)
    if ears is None:
        import vosk
        vosk.SetLogLevel(-1)
        ears = Ears(vosk.Model(str(model_dir)), vocab)
    raw = json.loads(SOUNDS_LIKE.read_text())
    sounds = {s: t for t, ss in raw["spellings"].items() for s in ss}
    takes = read_takes(clips)
    rules = Rules(vocab, ears.known, sounds, bank)
    rows = {"gate": gate_clips(gate, vocab), "teach (in-sample)": teach_clips(takes, vocab)}
    before_hear = ears.hear_with(sounds)
    before = {k: score(r, before_hear, vocab) for k, r in rows.items()}
    rescues = {" ".join(m["heard"].split()) for b in before.values() for m in b["missed"] if m["heard"]}
    kept, refused, speakers = propose(takes, vocab, rules, rescues)
    while True:                                       # drop any spelling that misleads a clip
        new = {s: t for t, ss in kept.items() for s in ss}
        after = {k: score(r, ears.hear_with({**sounds, **new}), vocab) for k, r in rows.items()}
        worse = [w for a in after.values() for w in a["another_drug"]]
        worse = [w for w in worse if w not in [x for b in before.values() for x in b["another_drug"]]]
        culprits = {s for w in worse for s in new if f" {s} " in f" {w['heard']} "}
        if not culprits:
            break
        for s in culprits:
            t = new[s]
            kept[t].remove(s)
            refused.setdefault(t, {})[s] = "made a clip heard as another drug"
        kept = {t: ss for t, ss in kept.items() if ss}

    report = {"date": datetime.date.today().isoformat(), "model": model_id(model_dir)["model"] if model_dir else "",
              "teach": summary(takes, clips), "added": kept, "refused": refused,
              "heard_by": {s: speakers.get(s, []) for ss in kept.values() for s in ss},
              "before": before, "after": after, "applied": False}
    if apply and kept:
        report["applied"] = _apply(raw, kept, refused, model_dir, print)
    out_dir = pathlib.Path(out_dir or ROOT / "bench-out" / f"teach-spellings-{report['date']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    _print(report, print)
    return report


def _apply(raw, kept, refused, model_dir, print) -> bool:
    """Writes the spellings and the grammar; scores the synthetic dry run; keeps nothing
    if it got worse."""
    old_sounds, old_grammar = SOUNDS_LIKE.read_text(), GRAMMAR.read_text()
    dry_path = ROOT / "voice" / "dryrun_drugs.json"
    old_dry = json.loads(dry_path.read_text())
    new = json.loads(old_sounds)
    for t, ss in kept.items():
        new["spellings"][t] = sorted(set(new["spellings"].get(t, [])) | set(ss))
        new.setdefault("teach_added", {})[t] = sorted(set(new.get("teach_added", {}).get(t, [])) | set(ss))
    for t, rs in refused.items():
        new.setdefault("teach_refused", {}).setdefault(t, {}).update(rs)
    new["teach_note"] = ("spellings from the teach page (voice/tools/teach_spellings.py): what Vosk heard "
                         "for each name, owner and contributors, kept when safe; teach_refused says why not")
    SOUNDS_LIKE.write_text(json.dumps(new, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    spoken._SPELLINGS = None
    from voice import grammar as vg
    g = vg.generate(model_dir)
    GRAMMAR.write_text(json.dumps(g, indent=1, sort_keys=True) + "\n")
    from voice.tools import dryrun_drugs
    wavs = pathlib.Path.home() / "projects" / "pocket-hearing" / "bench-out" / "dryrun-kokoro"
    if not wavs.exists():
        print(f"dry run not scored: no clips at {wavs}")
        return True
    dryrun_drugs.score(model_dir, wavs)
    dry = json.loads(dry_path.read_text())
    if dry["heard_as_another_drug"] > old_dry["heard_as_another_drug"] or dry["heard"] < old_dry["heard"]:
        SOUNDS_LIKE.write_text(old_sounds)
        GRAMMAR.write_text(old_grammar)
        dry_path.write_text(json.dumps(old_dry, indent=1) + "\n")
        print(f"NOT APPLIED: the dry run got worse ({dry['heard']} heard, {dry['heard_as_another_drug']} as another drug)")
        return False
    return True


def _print(r, print) -> None:
    print("teach page:")
    for sp, s in r["teach"].items():
        print(f"  {sp}: {s['names']} names, {s['takes']} takes ({s['with_audio']} with audio), {s['skips']} skips")
    print(f"added: {sum(map(len, r['added'].values()))} spellings for {len(r['added'])} names")
    for t, ss in sorted(r["added"].items()):
        print(f"  {t}: {', '.join(ss)}")
    print(f"refused: {sum(map(len, r['refused'].values()))}")
    for k in r["before"]:
        b, a = r["before"][k], r["after"][k]
        print(f"{k}: heard {b['heard']}/{b['clips']} -> {a['heard']}/{a['clips']}; "
              f"as another drug {len(b['another_drug'])} -> {len(a['another_drug'])}")
    print("applied" if r["applied"] else "not applied (run with --apply)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("model")
    ap.add_argument("--clips", default=str(CLIPS))
    ap.add_argument("--gate", default=str(GATE))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    run(a.model, pathlib.Path(a.clips), pathlib.Path(a.gate), a.apply)


if __name__ == "__main__":
    main()
