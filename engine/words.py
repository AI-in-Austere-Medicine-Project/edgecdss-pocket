"""Numbers and units written out. number_words is EdgeCDSS server/spoken.py's."""
import re

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _int_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + _int_words(rest))
    if n < 1_000_000:
        rest = n % 1000
        joiner = "" if rest == 0 else (" and " if rest < 100 else " ")
        return _int_words(n // 1000) + " thousand" + ("" if rest == 0 else joiner + _int_words(rest))
    raise ValueError(n)


def number_words(text: str) -> str:
    """'0.18' -> 'zero point one eight'. Digits after the point are read one by one."""
    whole, _, frac = text.replace(",", "").partition(".")
    out = _int_words(int(whole or "0"))
    if frac:
        out += " point " + " ".join(_ONES[int(d)] for d in frac)
    return out


def num(value: float) -> str:
    return number_words(f"{value:g}")


# Every unit in the bank has a line here; a unit that does not is not spoken
# (tests/test_vocabulary.py walks the bank).
UNIT_WORDS = {
    "mg": ("milligram", "milligrams"), "mcg": ("microgram", "micrograms"), "g": ("gram", "grams"),
    "mg/kg": ("milligram per kilogram", "milligrams per kilogram"),
    "mcg/kg": ("microgram per kilogram", "micrograms per kilogram"),
    "g/kg": ("gram per kilogram", "grams per kilogram"),
    "mg/kg/hr": ("milligram per kilogram per hour", "milligrams per kilogram per hour"),
    "mcg/kg/min": ("microgram per kilogram per minute", "micrograms per kilogram per minute"),
    "mcg/kg/hr": ("microgram per kilogram per hour", "micrograms per kilogram per hour"),
    "mcg/min": ("microgram per minute", "micrograms per minute"),
    "mcg/hr": ("microgram per hour", "micrograms per hour"),
    "mg/hr": ("milligram per hour", "milligrams per hour"),
    "mg/min": ("milligram per minute", "milligrams per minute"),
}


def amount(value: float, unit: str) -> str:
    one, many = UNIT_WORDS[unit]
    return f"{num(value)} {one if value == 1 else many}"


def span(lo: float, hi: float, unit: str) -> str:
    return f"{num(lo)} to {num(hi)} {UNIT_WORDS[unit][1]}"


def mils(value: float) -> str:
    return f"{num(value)} {'mil' if value == 1 else 'mils'}"


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def say_name(name: str) -> str:
    """A drug or label as speech: digits and symbols written out, punctuation gone.
    "<" is "under" because dropping it would reverse "SBP < 90"."""
    t = name.replace("<", " under ").replace(">", " over ").replace("%", " percent ")
    t = re.sub(r"\d+(?:\.\d+)?", lambda m: " " + number_words(m.group(0)) + " ", t)
    t = re.sub(r"[/—–(),.:;+]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def say_chars(text: str) -> str:
    """Read character by character: a version or a hash."""
    names = {".": "point", "+": "plus", "-": "dash"}
    out = []
    for c in text:
        out.append(_ONES[int(c)] if c.isdigit() else names.get(c, c))
    return " ".join(out)
