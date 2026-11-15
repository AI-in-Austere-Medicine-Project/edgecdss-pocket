"""Typed phrase <-> what is said and heard. Vosk returns words from the grammar only;
the parser reads them exactly as it reads typed text. The only rewrite is joining a
spelled name ("t x a") into its token, and only for the names listed here."""
import json
import pathlib
import re

from grammar.parser import tokens
from grammar.vocabulary import CONDITIONS, DOSE_UNITS

# Typed tokens a medic says letter by letter. "in" is the IN route except after an
# amount ("five hundred milligrams in ten mils") or in a condition ("in labour"), as
# the parser reads it.
SPELLED = {"iv": "i v", "io": "i o", "im": "i m", "po": "p o", "rsi": "r s i",
           "icp": "i c p", "maoi": "m a o i", "txa": "t x a", "in": "i n"}
# Spelled forms the parser does not already read letter by letter.
JOINED = {"t x a": "txa", "d d a v p": "ddavp", "r h z e": "rhze"}
SOUNDS_LIKE = pathlib.Path(__file__).resolve().parents[1] / "grammar" / "sounds_like.json"
_SPELLINGS = None


def spellings() -> dict:
    """{spelling: name} from grammar/sounds_like.json (empty if not generated)."""
    global _SPELLINGS
    if _SPELLINGS is None:
        raw = json.loads(SOUNDS_LIKE.read_text())["spellings"] if SOUNDS_LIKE.exists() else {}
        _SPELLINGS = {s: token for token, ss in raw.items() for s in ss}
    return _SPELLINGS


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


def normalise(heard: str, sounds=None) -> str:
    """Vosk text -> parser text: spelled letters joined, phonetic spellings to their
    name, longest first. Nothing else changes."""
    table = {**JOINED, **(spellings() if sounds is None else sounds)}
    longest = max((len(k.split()) for k in table), default=0)
    words, out, i = heard.lower().split(), [], 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            name = table.get(" ".join(words[i:i + n]))
            if name:
                out.append(name)
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


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
