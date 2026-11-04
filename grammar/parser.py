"""Typed phrase -> slots, over the generated word list. Stands in for Vosk: a word
outside the list refuses the whole phrase, and nothing is corrected or guessed.

A dose or vial amount that is spoken stays words (B1): this module computes no number
from it and nothing downstream can. Weight and age are the only spoken numbers read.
"""
import dataclasses
import re
from typing import Optional

from grammar.vocabulary import (AGE_UNITS, CONTROLS, DOSE_UNITS, FILLERS, NUMBERS, PATIENT, ROUTES,
                                VOLUME_UNITS, WEIGHT_UNITS, Vocabulary)

_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split())}
_TEENS = {w: i + 10 for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}
_NUMBER_TOKENS = set(NUMBERS)
KG_PER_POUND = 0.453592


@dataclasses.dataclass
class Weight:
    value: float
    unit: str
    estimated: bool = False

    @property
    def kg(self) -> float:
        # EdgeCDSS: round(pounds * 0.453592, 1)
        return self.value if self.unit == "kilos" else round(self.value * KG_PER_POUND, 1)


@dataclasses.dataclass
class Age:
    value: float
    unit: str

    @property
    def years(self) -> float:
        return self.value * AGE_UNITS[self.unit]


@dataclasses.dataclass
class DrugMatch:
    term: str
    generics: tuple


@dataclasses.dataclass
class Parsed:
    controls: list = dataclasses.field(default_factory=list)
    drugs: list = dataclasses.field(default_factory=list)
    classes: list = dataclasses.field(default_factory=list)
    labels: list = dataclasses.field(default_factory=list)
    routes: list = dataclasses.field(default_factory=list)
    weight: Optional[Weight] = None
    age: Optional[Age] = None
    child: bool = False
    adult: bool = False
    stated: list = dataclasses.field(default_factory=list)  # words, never numbers
    stated_vial: list = dataclasses.field(default_factory=list)  # words, never numbers
    bare_number: bool = False
    bad_number: bool = False
    unknown: list = dataclasses.field(default_factory=list)

    def has_slots(self) -> bool:
        return bool(self.drugs or self.classes or self.labels or self.routes or self.weight
                    or self.age or self.child or self.adult or self.stated or self.stated_vial
                    or self.bare_number or self.bad_number)


def _under_100(toks: list):
    if not toks:
        return None, toks
    t = toks[0]
    if t in _TENS:
        if len(toks) > 1 and toks[1] in _ONES and toks[1] != "zero":
            return _TENS[t] + _ONES[toks[1]], toks[2:]
        return _TENS[t], toks[1:]
    if t in _TEENS:
        return _TEENS[t], toks[1:]
    if t in _ONES:
        return _ONES[t], toks[1:]
    return None, toks


def _under_1000(toks: list):
    if len(toks) >= 2 and toks[1] == "hundred" and toks[0] in _ONES and toks[0] != "zero":
        value, rest = _ONES[toks[0]] * 100, toks[2:]
        if rest[:1] == ["and"]:
            rest = rest[1:]
            sub, after = _under_100(rest)
            if sub is None:
                return None, toks
            return value + sub, after
        sub, after = _under_100(rest)
        return (value + sub, after) if sub else (value, rest)
    return _under_100(toks)


def parse_number(toks: list) -> Optional[float]:
    """The value of number words, or None when they do not read as one number."""
    if "point" in toks:
        i = toks.index("point")
        whole, frac = toks[:i], toks[i + 1:]
        if not frac or any(t not in _ONES for t in frac):
            return None
    else:
        whole, frac = toks, []
    value, rest = _under_1000(whole)
    if value is None:
        return None
    if rest[:1] == ["thousand"]:
        value *= 1000
        rest = rest[1:]
        if rest[:1] == ["and"]:
            rest = rest[1:]
        if rest:
            sub, rest = _under_1000(rest)
            if sub is None:
                return None
            value += sub
    if rest:
        return None
    if frac:
        return float(f"{value}." + "".join(str(_ONES[t]) for t in frac))
    return value


def _number_run(toks: list, i: int) -> int:
    """Index past the run of number words at i. "and" only joins two number words."""
    j = i
    while j < len(toks):
        if toks[j] in _NUMBER_TOKENS:
            j += 1
        elif toks[j] == "and" and j > i and j + 1 < len(toks) and toks[j + 1] in _NUMBER_TOKENS:
            j += 2
        else:
            break
    return j


def _match(toks: list, i: int, table, longest: int = 5):
    for n in range(min(longest, len(toks) - i), 0, -1):
        term = " ".join(toks[i:i + n])
        if term in table:
            return term, n
    return None, 0


def tokens(text: str) -> list:
    return re.sub(r"[,.;:?!]", " ", text.lower()).replace("-", " ").split()


def parse(text: str, vocab: Vocabulary) -> Parsed:
    p, toks, i = Parsed(), tokens(text), 0
    estimated = False
    while i < len(toks):
        t = toks[i]
        term, n = _match(toks, i, CONTROLS, 2)
        if term:
            p.controls.append(term)
            i += n
            continue
        if t in _NUMBER_TOKENS:
            i = _read_number(toks, i, p)
            continue
        if t in WEIGHT_UNITS or t in AGE_UNITS or t in DOSE_UNITS or t in VOLUME_UNITS:
            p.bare_number = True       # a unit with no number
            i += 1
            continue
        if t in PATIENT:
            p.child = p.child or t == "child"
            p.adult = p.adult or t == "adult"
            estimated = estimated or t == "estimated"
            i += 1
            continue
        term, n = _match(toks, i, vocab.drug_terms)
        if term:
            p.drugs.append(DrugMatch(term, vocab.drug_terms[term]))
            i += n
            continue
        term, n = _match(toks, i, ROUTES, 2)
        if term:
            p.routes.append(ROUTES[term])
            i += n
            continue
        term, n = _match(toks, i, vocab.class_terms, 4)
        if term:
            p.classes.append(vocab.class_terms[term])
            i += n
            continue
        if t in vocab.label_words:
            p.labels.append(t)
        elif t not in FILLERS:
            p.unknown.append(t)
        i += 1
    if p.unknown:
        return Parsed(unknown=p.unknown)
    if p.weight is not None:
        p.weight.estimated = estimated
    return p


def _read_number(toks: list, i: int, p: Parsed) -> int:
    end = _number_run(toks, i)
    words, unit = toks[i:end], toks[end] if end < len(toks) else None
    value = parse_number(words)
    if unit in DOSE_UNITS:
        said = " ".join(words + [unit])
        return _read_strength(toks, end + 1, p, said, i)
    if unit in VOLUME_UNITS:
        p.stated_vial.append(" ".join(words + [unit]))
        return end + 1
    if unit in WEIGHT_UNITS:
        if value is None or value <= 0:
            p.bad_number = True
        else:
            p.weight = Weight(value, WEIGHT_UNITS[unit])
        return end + 1
    if unit in AGE_UNITS:
        if value is None:
            p.bad_number = True
        else:
            p.age = Age(value, unit if unit.endswith("s") else unit + "s")
        return end + 1
    if value is None:
        p.bad_number = True
    else:
        p.bare_number = True
    return end


def _read_strength(toks: list, j: int, p: Parsed, said: str, _start: int) -> int:
    """After a stated amount: "per mil" or "in ten mils" makes it a claim about a vial."""
    if j < len(toks) and toks[j] in ("per", "in"):
        k = _number_run(toks, j + 1)
        if k < len(toks) and toks[k] in VOLUME_UNITS:
            p.stated_vial.append(" ".join([said, *toks[j:k + 1]]))
            return k + 1
    p.stated.append(said)
    return j
