"""Bank -> Vosk grammar: python3 -m voice.grammar MODEL_DIR [OUT]

The grammar is every word in the bank's word list that the model's lexicon holds, the
letters spelled names use, and "[unk]", so speech outside it comes back as "[unk]" and
the parser refuses the phrase rather than taking the nearest word. Words the model does
not hold cannot be heard at all; they are listed in the output.
"""
import hashlib
import json
import pathlib
import sys

from engine.bank import load_bank
from grammar.vocabulary import build
from voice.spoken import JOINED, prompt, spellings

ROOT = pathlib.Path(__file__).resolve().parents[1]
LETTERS = set("abcdefghijklmnopqrstuvwxyz")


def grammar_words(vocab, known, sounds=None) -> tuple:
    """(sorted grammar entries, sorted bank words the model does not know). Entries are
    the bank words it knows, the letters, every phonetic spelling as one phrase, and
    "[unk]"."""
    words = vocab.words()
    missing = sorted(w for w in words if not known(w))
    heard = {w for w in words if known(w)} | {x for x in LETTERS if known(x)}
    sounds = spellings() if sounds is None else sounds
    phrases = {s for s in sounds if all(known(w) for w in s.split())}
    return sorted(heard | phrases | {"[unk]"}), missing


def hearable(word, known, sounds) -> bool:
    """The model can hear it: in its word list, spelled by letters, or spelled phonetically."""
    return known(word) or word in JOINED.values() or word in set(sounds.values())


def model_id(model_dir) -> dict:
    d = pathlib.Path(model_dir)
    h = hashlib.sha256((d / "am" / "final.mdl").read_bytes()).hexdigest()
    return {"model": d.name, "model_am_sha256": h}


def unsayable_drugs(vocab, known) -> list:
    """Signed drugs none of whose names the model can hear."""
    out = []
    for drug in sorted(vocab.signed):
        sounds = spellings()
        if not any(all(hearable(w, known, sounds) for w in t.split()) for t in vocab.named(drug)):
            out.append(drug)
    return out


def generate(model_dir, bank_dir=ROOT / "bank") -> dict:
    import vosk
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_dir))
    bank = load_bank(bank_dir)
    vocab = build(bank)

    def known(w):
        return model.vosk_model_find_word(w) >= 0
    words, missing = grammar_words(vocab, known)
    base, _ = grammar_words(vocab, known, sounds={})
    return {**model_id(model_dir), "bank_version": bank.version, "bank_hash": bank.hash,
            "base_words": base, "words": words, "not_in_model": missing,
            "signed_drugs_not_sayable": unsayable_drugs(vocab, known)}


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "grammar" / "vosk_grammar.json"
    g = generate(sys.argv[1])
    out.write_text(json.dumps(g, indent=1, sort_keys=True) + "\n")
    print(f"{len(g['words'])} words; {len(g['not_in_model'])} bank words not in the model; "
          f"signed drugs that cannot be said: {', '.join(g['signed_drugs_not_sayable']) or 'none'}")
