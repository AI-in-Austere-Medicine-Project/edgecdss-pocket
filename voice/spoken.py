"""Typed phrase <-> what is said and heard. Vosk returns words from the grammar only;
the parser reads them exactly as it reads typed text. The only rewrite is joining a
spelled name ("t x a") into its token, and only for the names listed here."""
import re

from grammar.parser import tokens
from grammar.vocabulary import CONDITIONS, DOSE_UNITS

# Typed tokens a medic says letter by letter. "in" is the IN route except after an
# amount ("five hundred milligrams in ten mils") or in a condition ("in labour"), as
# the parser reads it.
SPELLED = {"iv": "i v", "io": "i o", "im": "i m", "po": "p o", "rsi": "r s i",
           "icp": "i c p", "maoi": "m a o i", "txa": "t x a", "in": "i n"}
# Spelled forms the parser does not already read letter by letter.
JOINED = {"t x a": "txa"}


def prompt(typed: str) -> str:
    toks = tokens(typed)
    out = []
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        prev = toks[i - 1] if i else None
        if t == "in" and (prev in DOSE_UNITS or f"in {nxt}" in CONDITIONS):
            out.append(t)
        else:
            out.append(SPELLED.get(t, t))
    return " ".join(out)


def normalise(heard: str) -> str:
    text = " ".join(heard.lower().split())
    for said, token in JOINED.items():
        text = f" {text} ".replace(f" {said} ", f" {token} ").strip()
    return text


def same_word(w: str) -> str:
    """One spelling for scoring: haemorrhage/hemorrhage, apnoea/apnea. Sounds that are
    different words ("four", "for") stay different."""
    return re.sub(r"ae|oe", "e", w) if len(w) > 4 else w


def word_errors(ref: str, hyp: str) -> tuple:
    """(substitutions + deletions + insertions, words in ref)."""
    r, h = [same_word(w) for w in ref.split()], [same_word(w) for w in hyp.split()]
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1], len(r)
