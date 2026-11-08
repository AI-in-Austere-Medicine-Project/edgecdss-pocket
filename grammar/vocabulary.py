"""Bank -> word list. Phase 2 hands the same list to Vosk as its grammar; here the
typed parser reads it. Nothing outside it is recognised, and it holds no number.

A name close to two drugs never resolves (README, C1). Two ways to be close:
  - a name that is the start of another drug's name: "ket" (ketorolac), "roc" (rocephin);
  - a short form of two names, one letter apart at most: "keto" (keta/keto).
A drug's own full name resolves, unless it is an unsigned stem of signed names: "calcium".
"""
import dataclasses
import re

CONTROLS = ("new patient", "confirm", "cancel", "repeat", "why", "log", "battery")
ROUTES = {"iv": "IV", "i v": "IV", "io": "IO", "i o": "IO", "im": "IM", "i m": "IM",
          "in": "IN", "i n": "IN", "po": "PO", "p o": "PO", "line": "IV", "neb": "NEB"}
PATIENT = ("child", "adult", "estimated")
WEIGHT_UNITS = {"kilos": "kilos", "kilo": "kilos", "kilograms": "kilos", "kg": "kilos",
                "pounds": "pounds", "pound": "pounds", "lbs": "pounds"}
AGE_UNITS = {"years": 1.0, "year": 1.0, "months": 1 / 12, "month": 1 / 12}
DOSE_UNITS = ("milligrams", "milligram", "mg", "micrograms", "microgram", "mcg", "grams", "gram")
VOLUME_UNITS = ("mils", "mil", "ml", "millilitres", "milliliters", "millilitre", "milliliter")
FILLERS = ("for", "give", "dose", "and", "the", "of", "per")
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
           "fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty "
           "sixty seventy eighty ninety hundred thousand point").split()
# Conditions a medic can state for this patient (owner ruling 2026-11-08). A caution or
# contraindication is spoken after the dose only when its signed text names one; the rest
# are in "why". Spoken term -> condition; condition -> what it names in the signed text.
# Left out because the word already means something else to the grammar: shock and seizure
# (indications), TBI and hypotension (label words). Hyperkalaemia is an indication too, so
# it is said as "hyperkalemic" or "high potassium" and read back as "hyperkalaemia".
CONDITION_PATTERNS = {
    "burns": r"\bburns?\b", "crush injury": r"\bcrush", "spinal cord injury": r"spinal cord",
    "denervation": r"denervation", "head injury": r"head (injur|trauma)", "raised icp": r"\bicp\b",
    "hypertension": r"hypertens", "hypovolaemia": r"hypovol|volume.deplet|volume deficit",
    "hypoxia": r"hypox", "asthma": r"asthma", "sleep apnoea": r"sleep apno?ea",
    "respiratory depression": r"respiratory (insufficiency/)?depression", "glaucoma": r"glaucoma",
    "alcohol intoxication": r"alcohol (intoxication|toxicity)", "liver disease": r"hepatic|liver", "renal failure": r"renal|dialysis",
    "elderly": r"elderly", "in labour": r"\blabou?r\b", "hyperkalaemia": r"hyperkal", "egg allergy": r"\beggs?\b",
    "soy allergy": r"\bsoy", "peanut allergy": r"peanut", "penicillin allergy": r"penicillin",
    "cephalosporin allergy": r"cephalosporin", "diabetic coma": r"diabetic coma",
    "hyperglycaemia": r"hyperglyc", "hypercalcaemia": r"hypercalc", "hypokalaemia": r"hypokal",
    "digoxin toxicity": r"digoxin|digitalis", "maoi": r"\bmaoi", "hypothermia": r"hypotherm",
    "eye injury": r"eye injur", "altered mental status": r"altered mental",
    "unable to swallow": r"swallow", "aortic aneurysm": r"aneurysm|dissection",
    "qt prolongation": r"\bqt\b", "ileus": r"ileus",
    "subarachnoid haemorrhage": r"subarachnoid", "intracranial bleed": r"intracranial|intracerebral",
    "thrombosis": r"thromb|\bdvt\b", "enlarged prostate": r"prostat",
    "pyloric stenosis": r"pyloric", "sarcoidosis": r"sarcoid", "brain tumour": r"brain tumou?r",
    "delirium tremens": r"delirium tremens", "intubated": r"\bintubated\b",
}
_CONDITION_VARIANTS = {
    "burn": "burns", "crush": "crush injury", "spinal injury": "spinal cord injury",
    "head trauma": "head injury", "icp": "raised icp", "i c p": "raised icp",
    "hypertensive": "hypertension", "hypovolemia": "hypovolaemia", "hypovolemic": "hypovolaemia",
    "hypovolaemic": "hypovolaemia", "hypoxic": "hypoxia", "asthmatic": "asthma",
    "sleep apnea": "sleep apnoea", "intoxicated": "alcohol intoxication", "drunk": "alcohol intoxication", "liver failure": "liver disease",
    "kidney failure": "renal failure", "dialysis": "renal failure", "in labor": "in labour",
    "hyperkalemic": "hyperkalaemia", "hyperkalaemic": "hyperkalaemia",
    "high potassium": "hyperkalaemia",
    "hyperglycemia": "hyperglycaemia", "hypercalcemia": "hypercalcaemia",
    "hypokalemia": "hypokalaemia", "on digoxin": "digoxin toxicity", "m a o i": "maoi",
    "hypothermic": "hypothermia", "altered": "altered mental status",
    "aneurysm": "aortic aneurysm", "aortic dissection": "aortic aneurysm", "long qt": "qt prolongation",
    "subarachnoid hemorrhage": "subarachnoid haemorrhage", "dvt": "thrombosis",
    "blood clot": "thrombosis", "brain tumor": "brain tumour",
}
_NOT_SAID_AS_ITSELF = {"hyperkalaemia"}
CONDITIONS = {**{c: c for c in CONDITION_PATTERNS if c not in _NOT_SAID_AS_ITSELF},
              **_CONDITION_VARIANTS}


def names_condition(text: str, conditions) -> bool:
    return any(re.search(CONDITION_PATTERNS[c], text, re.I) for c in conditions)


STOPWORDS = frozenset("and the for with without not dose doses patient incl no of or to in".split())
MIN_STEM = 3


def label_tokens(label: str) -> set:
    """The words a signed label can be asked for by."""
    return {w for w in re.findall(r"[a-z]+", label.lower())
            if len(w) >= MIN_STEM and w not in STOPWORDS}


def _say_term(term: str):
    """A name as it can be said, or None: "solu-cortef" can; "d50", "3% saline" cannot yet."""
    t = term.strip().lower().replace("-", " ")
    return t if re.fullmatch(r"[a-z]+(?: [a-z]+)*", t) else None


@dataclasses.dataclass
class Vocabulary:
    drug_terms: dict      # term -> tuple of generics; more than one means it must ask
    class_terms: dict     # term -> class
    label_words: set
    unspeakable: set
    signed: set

    def words(self) -> set:
        out = set(NUMBERS) | set(PATIENT) | set(WEIGHT_UNITS) | set(AGE_UNITS)
        out |= set(DOSE_UNITS) | set(VOLUME_UNITS) | set(FILLERS) | self.label_words
        for group in (CONTROLS, ROUTES, CONDITIONS, self.drug_terms, self.class_terms):
            for term in group:
                out.update(term.split())
        return out

    def named(self, generic: str) -> list:
        return [t for t, g in self.drug_terms.items() if g == (generic,)]

    def class_terms_for(self, cls: str) -> list:
        return [t for t, c in self.class_terms.items() if c == cls]


def _reserved() -> set:
    out = set(CONTROLS) | set(ROUTES) | set(PATIENT) | set(WEIGHT_UNITS) | set(AGE_UNITS)
    return out | set(DOSE_UNITS) | set(VOLUME_UNITS) | set(FILLERS) | set(NUMBERS)


def _class_terms(classes) -> dict:
    out = {}
    for cls in classes:
        for part in cls.split(" / "):
            term = part.strip().lower()
            out[term] = cls
            if "aem" in term:                       # hemorrhage, hypoglycemia
                out[term.replace("aem", "em")] = cls
            if term == "rsi":
                out["r s i"] = cls
    return out


def _close(token: str, name: str) -> bool:
    n = len(token)
    if len(name) < n or name[:2] != token[:2]:
        return False
    return sum(a != b for a, b in zip(token, name)) <= 1


def build(bank) -> Vocabulary:
    names, unspeakable = {}, set()   # said name -> generic
    signed = {e["drug"] for e in bank.entries}
    groups = {}
    for e in bank.entries:
        groups.setdefault(e["drug"], set()).update(e["aliases"])
    for n in bank.no_signed_dose:
        groups.setdefault(n["drug"], set()).update(n["aliases"])
    for generic, aliases in sorted(groups.items(), key=lambda kv: kv[0] not in signed):
        for term in [generic, *sorted(aliases)]:
            said = _say_term(term)
            if said is None:
                unspeakable.add(term)
            else:
                names.setdefault(said, generic)

    terms = {}
    for term, generic in names.items():
        others = {g for other, g in names.items()
                  if g != generic and other != term and other.startswith(term)}
        if len(term) < MIN_STEM or not others:
            terms[term] = (generic,)
        elif term == generic:
            live = {g for g in others if g in signed}
            if generic in signed or not live:
                terms[term] = (generic,)
            else:
                terms[term] = tuple(sorted(others))
        else:
            terms[term] = tuple(sorted(others | {generic}))

    # Short forms close to two names, where at least one of them is signed.
    single = [(n, g) for n, g in names.items() if " " not in n]
    reserved = _reserved()
    stems = {}
    for i, (a, ga) in enumerate(single):
        for b, gb in single[i + 1:]:
            if ga == gb or (ga not in signed and gb not in signed):
                continue
            common = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                common += 1
            if common < MIN_STEM:
                continue
            for n in range(MIN_STEM, common + 2):
                for name in (a, b):
                    if len(name) > n:
                        stems[name[:n]] = None
    for stem in stems:
        if stem in terms or stem in reserved:
            continue
        close = {g for n, g in single if _close(stem, n)}
        if len(close) >= 2:
            terms[stem] = tuple(sorted(close))

    class_terms = _class_terms(dict.fromkeys(e["indication_class"] for e in bank.entries))
    labels = set()
    for e in bank.entries:
        labels |= label_tokens(e["indication"])
    labels -= set(class_terms) | reserved | set(terms)
    return Vocabulary(drug_terms=terms, class_terms=class_terms, label_words=labels,
                      unspeakable=unspeakable, signed=signed)
