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


# Routes as they sound (owner's choices by ear, 2026-11-19). Bare letters are misread
# ("IV" as "Roman four", "IM" as "imm"). Applied to every spoken line, signed text
# included; the bank, the log and anything shown as text keep the letters.
ROUTE_WORDS = {"IV": "eye vee", "IM": "eye em", "IO": "eye oh", "IN": "intranasal",
               "PO": "pee oh", "NEB": "nebuliser"}
_ROUTE = "|".join(ROUTE_WORDS)
# "IV/IO", "IV/IM/SC/IN": a slash between routes is "or".
_ROUTE_CHAIN = re.compile(r"(?<![A-Za-z/])[A-Z]{2,3}(?:/[A-Z]{2,3})+(?![A-Za-z/])")
_ROUTE_ONE = re.compile(rf"(?<![A-Za-z])({_ROUTE})(?![A-Za-z])")


def say_routes(text: str) -> str:
    """Route letters written the way they are said. Only whole upper-case tokens
    change: "in", "IVP", "INR" and "nebulised" do not."""
    def chain(m):
        parts = m.group(0).split("/")
        if not any(p in ROUTE_WORDS for p in parts):
            return m.group(0)
        return " or ".join(ROUTE_WORDS.get(p, p) for p in parts)
    starts = bool(text[:1].isupper())
    text = _ROUTE_CHAIN.sub(chain, text)
    text = _ROUTE_ONE.sub(lambda m: ROUTE_WORDS[m.group(1)], text)
    return sentence(text) if starts else text


# Names said another way so the voice gets them right (owner, by ear, from the numbered
# list of voice/tools/say_all.py): the spoken form only; the screen and the log keep the
# name. Name (lower case) -> how to say it.
SAY_AS: dict = {}


def say_as(text: str) -> str:
    """Each SAY_AS name, as a whole word in any case, said its way."""
    for name, said in sorted(SAY_AS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?i)(?<![a-z]){re.escape(name)}(?![a-z])", said, text)
    return text


def say_chars(text: str) -> str:
    """Read character by character: a version or a hash."""
    names = {".": "point", "+": "plus", "-": "dash"}
    out = []
    for c in text:
        out.append(_ONES[int(c)] if c.isdigit() else names.get(c, c))
    return " ".join(out)


# A signed procedure step said aloud (owner, 2026-11-20): the text is read as signed; only
# its symbols, units and numbers are written out, in this order. The written form keeps it.
_STEP_SAY = [
    (r"≈\s*", "about "), (r"\s*→\s*", ", then "), (r"\bw/\s", "with "), (r"\s*&\s*", " and "),
    (r"<\s*", "under "), (r"(\d)\s*-\s*(\d)", r"\1 to \2"), (r"\b2nd\b", "second"),
    (r"(\d)\s*L/min\b", r"\1 litres per minute"), (r"(\d)\s*mg/kg\b", r"\1 milligrams per kilogram"),
    (r"(\d)\s*mg\b", r"\1 milligrams"), (r"(\d)\s*%", r"\1 percent"),
    (r"\bIAW\b", "in accordance with"),
]


def say_step(text: str) -> str:
    for pattern, repl in _STEP_SAY:
        text = re.sub(pattern, repl, text)
    # Numbers alone are written out; one inside a name ("CO2", "FiO2") is left to the voice.
    text = re.sub(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?(?![A-Za-z\d])", lambda m: number_words(m.group(0)), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text[-1:] in ".?!\"" else text + "."    # a pause before what follows
