"""Dev tool: phonetic spellings from the model itself.

  python3 -m voice.tools.make_spellings MODEL_DIR WAVDIR

WAVDIR holds <name>__<voice>.wav ("+" for a space in the name): a drug name, or a word
of one the model's word list lacks, said by a synthetic voice (voice/tools/synth_kokoro.py).

Pass 1 decodes each with the model's full language model: what it hears, in words it
holds, is a spelling. Pass 2 decodes each again through the grammar those spellings make
(Vosk hears grammar words in any order), and what it hears there is a spelling too,
unless it already reads as the name. Existing spellings in grammar/sounds_like.json are
kept. A spelling is dropped if it holds a word that means something else to the parser
(the name's own words excepted), if it is an everyday phrase (NOT_A_NAME), if a long name
would be one everyday word, or if two names were heard the same way. Decodes are cached
in WAVDIR/decodes.json.
"""
import collections
import difflib
import json
import pathlib
import sys
import wave

from engine.bank import load_bank
from grammar.vocabulary import CONTROLS, build
from voice import spoken
from voice.grammar import grammar_words, model_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "grammar" / "sounds_like.json"
MAX_WORDS = 6
# Heard as a name, these would turn something a medic says for real into a drug request.
NOT_A_NAME = {"can't breathe", "can't breath", "answer", "black"}


def keep(target: str, spelling: str) -> bool:
    """A listed phrase never spells. A long name is spelled by one word only when that
    word is a variant of it ("adrenalin"), never by an unrelated everyday word."""
    if spelling in NOT_A_NAME:
        return False
    if len(spelling.split()) > 1 or len(target) <= 6:
        return True
    return difflib.SequenceMatcher(None, spelling, target).ratio() >= 0.8


def _decode(model, path, grammar=None):
    import vosk
    rec = (vosk.KaldiRecognizer(model, 16000, json.dumps(grammar)) if grammar
           else vosk.KaldiRecognizer(model, 16000))
    with wave.open(str(path)) as w:
        rec.AcceptWaveform(w.readframes(w.getnframes()))
    return json.loads(rec.FinalResult())["text"]


def main(model_dir, wavdir):
    import vosk
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_dir))
    vocab = build(load_bank(ROOT / "bank"))
    meaningful = vocab.words() | {w for c in CONTROLS for w in c.split()}
    wavs = sorted(pathlib.Path(wavdir).glob("*__*.wav"))
    cache_path = pathlib.Path(wavdir) / "decodes.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def target_of(wav):
        return wav.stem.split("__")[0].replace("+", " ")

    def ok(target, text):
        words = text.split()
        own = set(target.split())
        return bool(words and len(words) <= MAX_WORDS and not (set(words) - own) & meaningful
                    and text != target and keep(target, text))

    heard = collections.defaultdict(collections.Counter)
    if OUT.exists():
        for t, ss in json.loads(OUT.read_text())["spellings"].items():
            for s in ss:
                heard[t][s] += 1
    for wav in wavs:                                    # pass 1: free
        key = f"free:{wav.name}"
        if key not in cache:
            cache[key] = _decode(model, wav)
        if ok(target_of(wav), cache[key]):
            heard[target_of(wav)][cache[key]] += 1
    cache_path.write_text(json.dumps(cache))

    sounds = {s: t for t, c in heard.items() for s in c}
    entries, _ = grammar_words(vocab, lambda w: model.vosk_model_find_word(w) >= 0, sounds)
    for wav in wavs:                                    # pass 2: through the grammar
        text = _decode(model, wav, entries)
        target = target_of(wav)
        if spoken.normalise(text, sounds) != target and ok(target, text):
            heard[target][text] += 1

    # A spelling heard for two names is kept only when both name the same drug(s), and
    # then for the first name only.
    def drugs(target):
        return vocab.drug_terms.get(target) or (target,)
    owners = collections.defaultdict(set)
    for target, c in heard.items():
        for s in c:
            owners[s].add(target)
    spellings, dropped = {}, {}
    for target in sorted(heard):
        def mine(s):
            others = owners[s]
            return len({drugs(t) for t in others}) == 1 and min(others) == target
        kept = sorted(s for s in heard[target] if keep(target, s) and mine(s))
        clash = sorted(s for s in heard[target] if len({drugs(t) for t in owners[s]}) > 1)
        if kept:
            spellings[target] = kept
        if clash:
            dropped[target] = clash
    voices = sorted({w.stem.split("__")[1] for w in wavs})
    targets = {target_of(w) for w in wavs}
    out = {**model_id(model_dir), "voices": voices, "spellings": spellings,
           "shared_spellings_dropped": dropped,
           "no_spelling": sorted(t for t in targets - set(spellings)
                                 if any(model.vosk_model_find_word(w) < 0 for w in t.split()))}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"{len(spellings)} names spelled, {sum(map(len, spellings.values()))} spellings; "
          f"no spelling: {', '.join(out['no_spelling']) or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
