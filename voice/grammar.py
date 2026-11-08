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
from voice.spoken import prompt

ROOT = pathlib.Path(__file__).resolve().parents[1]
LETTERS = set("abcdefghijklmnopqrstuvwxyz")


def grammar_words(vocab, known) -> tuple:
    """(sorted grammar words, sorted bank words the model does not know)."""
    words = vocab.words()
    missing = sorted(w for w in words if not known(w))
    letters = {w for term in words for w in term.split() if len(w) == 1} | LETTERS
    heard = {w for w in words if known(w)} | {x for x in letters if known(x)}
    return sorted(heard | {"[unk]"}), missing


def model_id(model_dir) -> dict:
    d = pathlib.Path(model_dir)
    h = hashlib.sha256((d / "am" / "final.mdl").read_bytes()).hexdigest()
    return {"model": d.name, "model_am_sha256": h}


def unsayable_drugs(vocab, known) -> list:
    """Signed drugs none of whose names the model can hear."""
    out = []
    for drug in sorted(vocab.signed):
        if not any(all(known(w) for w in prompt(t).split()) for t in vocab.named(drug)):
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
    return {**model_id(model_dir), "bank_version": bank.version, "bank_hash": bank.hash,
            "words": words, "not_in_model": missing,
            "signed_drugs_not_sayable": unsayable_drugs(vocab, known)}


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "grammar" / "vosk_grammar.json"
    g = generate(sys.argv[1])
    out.write_text(json.dumps(g, indent=1, sort_keys=True) + "\n")
    print(f"{len(g['words'])} words; {len(g['not_in_model'])} bank words not in the model; "
          f"signed drugs that cannot be said: {', '.join(g['signed_drugs_not_sayable']) or 'none'}")
