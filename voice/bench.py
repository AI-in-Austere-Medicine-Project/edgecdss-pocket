"""The replay corpus, spoken: python3 -m voice.bench MODEL_DIR [options]

Whole corpus cases, in corpus order, whose words the model can hear, until 50 phrases;
then, with --probes, phrases naming signed drugs the model cannot hear (what does it
hear instead?). Each phrase: wait for the button, record, decode with the bank grammar,
hand the text to the same Session the typed path uses, and score:

  word errors   against the phrase as said (voice.spoken.prompt)
  parse         the slots parsed from what was heard == those from the typed phrase
  turn          the session's (kind, say) == the corpus's expected output
  latency       release -> final text, and release -> turn returned

Everything goes to bench-out/<run>/: results.jsonl (one line per phrase), one WAV per
phrase, next.txt (the phrase now awaited), summary.json at the end. --wavs DIR replays
saved WAVs instead of the microphone (same scoring; "release" is the end of the file).
"""
import argparse
import datetime
import json
import pathlib
import statistics
import time
import wave

from engine.session import boot
from grammar.parser import parse
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "replay_corpus.json"
GRAMMAR = ROOT / "grammar" / "vosk_grammar.json"
RATE = 16000

# The medic forms and spelled names, said in a request (heard through spellings).
PROBES = [
    "rocephin for sepsis eighty kilos",
    "ancef for wound infection prophylaxis eighty kilos",
    "keppra for seizure eighty kilos",
    "cal gluc eighty kilos",
    "atropine for bradycardia child three kilos",
    "levetiracetam for seizure eighty kilos",
]


def can_hear(word, entries) -> bool:
    """In the grammar, or a name the grammar hears through a spelling."""
    return (word in entries or word in spoken.JOINED.values()
            or word in set(spoken.spellings().values()))


def select(corpus, heard, n=50):
    """Whole cases in corpus order, every word hearable, until at least n phrases."""
    out, count, entries = [], 0, set(heard)
    for case in corpus:
        if count >= n:
            break
        if all(can_hear(w, entries) for p, *_ in case["turns"] for w in spoken.normalise(spoken.prompt(p)).split()):
            out.append(case)
            count += len(case["turns"])
    return out


def items(corpus, heard, probes):
    """(case id, turn index, typed phrase, expected kind, expected say) in order."""
    for case in select(corpus, heard):
        for i, (phrase, kind, say, *_) in enumerate(case["turns"]):
            yield case["id"], i, phrase, kind, say
    if probes:
        for i, phrase in enumerate(PROBES):
            yield f"probe-{i}", 0, phrase, None, None


def _wav_write(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def _wav_read(path):
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE), path
        return w.readframes(w.getnframes())


def score(phrase, text, vocab):
    """Word errors on the parser's text against the phrase as said with names whole
    (a spelling heard and mapped back to its name is the name); parse against typed."""
    said = spoken.normalise(spoken.prompt(phrase), {})
    errors, n = spoken.word_errors(said, text)
    return spoken.prompt(phrase), errors, n, parse(text, vocab) == parse(phrase, vocab)


def run(args):
    g = json.loads(GRAMMAR.read_text())
    corpus = json.loads(CORPUS.read_text())
    todo = list(items(corpus, g["words"], args.probes))
    out = pathlib.Path(args.out or ROOT / "bench-out" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    import vosk
    from voice.hear import Hearing
    vosk.SetLogLevel(-1)
    hearing = Hearing(vosk.Model(str(args.model)), g, boot(ROOT / "bank").vocab)

    mic = button = None
    if not args.wavs:
        from voice import listen
        mic = listen.Mic(listen.capture_command(args.source))
        if args.enter:
            button = listen.EnterKey()
        else:
            path, name = listen.find_button(args.button)
            if not path:
                raise SystemExit("No headset button found in /proc/bus/input/devices.")
            print(f"button: {name} ({path}), mode {args.mode}", flush=True)
            button = listen.Button(path, args.mode)

    session, case_now = None, None
    results = out / "results.jsonl"
    for k, (cid, ti, phrase, kind, say) in enumerate(todo):
        if cid != case_now:
            session, case_now = boot(ROOT / "bank"), cid
        if k < args.start:
            if kind is not None:
                session.handle(phrase)        # replay the typed turn to keep the session's state
            continue
        said = spoken.prompt(phrase)
        (out / "next.txt").write_text(f"{k + 1}/{len(todo)} {cid}: {said}\n")
        print(f"[{k + 1}/{len(todo)}] say: {said}", flush=True)
        u = hearing.start()
        pcm = bytearray()
        if args.wavs:
            data = _wav_read(pathlib.Path(args.wavs) / f"{k + 1:03d}.wav")
            for i in range(0, len(data), 640):
                u.feed(data[i:i + 640])
            pcm += data
            t_release = time.monotonic()
        else:
            button.drain()
            button.press()

            def sink(d):
                pcm.extend(d)
                u.feed(d)
            mic.start(sink)
            t_release, _ = button.release()
            mic.stop()
        heard, text, which = u.finish()
        t_text = time.monotonic()
        said, errors, n, parse_ok = score(phrase, text, session.vocab)
        turn = session.handle(text) if text else None
        t_turn = time.monotonic()
        if not args.wavs:
            _wav_write(out / f"{k + 1:03d}.wav", bytes(pcm))
        got = (turn.kind, turn.say) if turn else (None, None)
        r = {"n": k + 1, "case": cid, "turn": ti, "typed": phrase, "said": said, "heard": heard,
             "decoder": which, "parsed_from": text, "errors": errors, "words": n, "parse_ok": parse_ok,
             "expected": [kind, say], "got": list(got),
             "turn_ok": None if kind is None else list(got) == [kind, say],
             "audio_s": round(len(pcm) / 2 / RATE, 2),
             "release_to_text_ms": round((t_text - t_release) * 1000, 1),
             "release_to_turn_ms": round((t_turn - t_release) * 1000, 1)}
        with results.open("a") as f:
            f.write(json.dumps(r) + "\n")
        print(f"  heard: {heard!r}  errors {errors}/{n}  turn {'ok' if r['turn_ok'] else r['turn_ok']}"
              f"  {r['release_to_turn_ms']} ms", flush=True)
    (out / "next.txt").write_text("done\n")
    summary = summarise([json.loads(x) for x in results.read_text().splitlines()])
    summary.update(model=g["model"], bank_hash=g["bank_hash"][:8])
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    if mic:
        mic.close()


def summarise(rows):
    def stats(xs):
        xs = sorted(xs)
        if not xs:
            return None
        return {"median": statistics.median(xs), "p95": xs[min(len(xs) - 1, int(0.95 * len(xs)))],
                "max": xs[-1], "n": len(xs)}
    replay = [r for r in rows if r["turn_ok"] is not None]
    probes = [r for r in rows if r["turn_ok"] is None]
    e, n = sum(r["errors"] for r in replay), sum(r["words"] for r in replay)
    return {
        "phrases": len(replay), "words": n, "word_errors": e,
        "wer": round(e / n, 4) if n else None,
        "phrases_exact": sum(r["errors"] == 0 for r in replay),
        "parse_ok": sum(r["parse_ok"] for r in replay),
        "turn_ok": sum(r["turn_ok"] for r in replay),
        "release_to_text_ms": stats([r["release_to_text_ms"] for r in replay]),
        "release_to_turn_ms": stats([r["release_to_turn_ms"] for r in replay]),
        "probes": [{"said": r["said"], "heard": r["heard"], "got": r["got"]} for r in probes],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--out")
    ap.add_argument("--wavs", help="replay saved WAVs (001.wav ...) instead of the mic")
    ap.add_argument("--start", type=int, default=0, help="resume: skip the first N phrases")
    ap.add_argument("--probes", action="store_true")
    ap.add_argument("--source", help="capture source (parec --device)")
    ap.add_argument("--button", help="input device name to use as push-to-talk")
    ap.add_argument("--mode", choices=("hold", "toggle"), default="hold")
    ap.add_argument("--enter", action="store_true", help="Enter key as push-to-talk")
    run(ap.parse_args())
