"""One device session: the pre-gate's questions, then read-back, then "confirm".

The order is EdgeCDSS's pre_gate, adapted to a device that can only ask one thing at a
time: holds first, then the weight questions, then indication, route and which entry.
Stricter than EdgeCDSS in three places, none of them a loosening: a route is asked
whenever more than one is signed, an entry whenever a class holds more than one, and
"estimated" never doses (EdgeCDSS REFERENCE section 9).

Rule 1: every number spoken comes from the bank, or is the weight or age read back.
Rule 2: a dose only after a read-back, on "confirm" alone.
Rule 3: every confirmed dose goes to `log` with a time.

A test bank (POCKET_TEST=1, owner ruling 2026-11-13) says TEST_NOTICE at boot and
before every read-back, logs test:true on every line, and says "Unverified." before
a dose whose entry is check_failed.
"""
import dataclasses
import datetime
import json
import os
import re
import time
from typing import Callable, Optional

from engine import contracts, vials, words
from engine.bank import BANK_DIR, Bank, BankRefused, load_bank
from engine.procedures import Procedure, ProceduresRefused, load_procedures
from grammar.parser import Age, Parsed, parse
from grammar.vocabulary import (CONDITION_PATTERNS, CONFUSABLE_ROUTE_TERMS, CONTROL_OF, MENU_CONTROLS, MENU_OF,
                                PROCEDURE_TITLES, VOLUME_UNITS, build, label_tokens, names_condition)

PEDIATRIC_WEIGHT_CEILING_KG = 40.0  # EdgeCDSS openai_client: not spoken, a gate
ROUTE_ORDER = ("IV", "IM", "IN", "PO", "NEB")
NO_SIGNED_VIAL = "No signed vial, no volume."
CAPPED = "Capped at the signed maximum."
RAISED = "Raised to the signed minimum."
ASK_ADULT = "Adult? Say adult, or give the age or the weight."  # ADULT_CONFIRM_ASK
ASK_ESTIMATE = "I only have an estimate. Say the weight to confirm it."  # WEIGHT_CONFIRM_ASK
NO_CONTRAINDICATIONS = "No contraindications listed."
# The confirm step (owner, 2026-11-16).
SAY_CONFIRM_OR_CANCEL = "Say confirm or cancel."
CANCELLED = "Cancelled."
PENDING_S = 30.0     # a read-back not confirmed within this is cancelled
MISSES_TO_CANCEL = 2
TEST_NOTICE = "Test set. Not for patient use."
# The start-up line and the home menu (owner, 2026-11-21): the set's name, version and
# hash go to the log, not the speaker. The bank names no set, so the kit does.
START_UP_LINE = ("Pocket ready. Research prototype, not for patient care. "
                 "Say drugs, procedures, or help.")
# One drug list, the EMS set (owner, 2026-11-23): no set switching, and the start-up line
# names no set. A procedure step's dose with no signed EMS entry holds.
STEP_HELD = "No signed dose of {name} for this step."
STEP_HELD_AFTER = "No signed dose at this step for {names}."
HOME_LINE = "Pocket ready. Say drugs, procedures, or help."
# Help (the owner's text, 2026-11-21). Shown with the letters; said with the owner's route
# words (2026-11-19) and RSI letter by letter. Each example asks nothing first: the drug one
# goes straight to its read-back (owner, 2026-11-21: agitation, not pain, which asks which one).
# The one drug list, the EMS set (2026-11-23), signs ketamine for agitation IM only: the drug
# example is now fentanyl for pain, IV, which reads straight back in the EMS set.
HELP_WRITTEN = (
    "Pocket gives signed drug doses and procedure steps by voice. Press the button, wait for "
    "the beep, speak, then press again. For a drug, say the drug, what it is for, the route and "
    "the weight. For example: fentanyl for pain, IV, eighty kilos. Pocket repeats what it heard. "
    "Say yes to hear the dose, or no to cancel. For a procedure, say its name and the weight. For "
    "example: RSI, eighty kilos. Then say next, back or repeat. Say new patient to start again. "
    "Say drugs or procedures to hear what Pocket knows. Say what can I say at any time.")
_MENU_LETTERS = {"RSI": "R S I", "PFC": "P F C", "EMS": "E M S"}
# "What can I say": only what works in the state Pocket is in.
CAN_SAY_IDLE = "Say drugs, procedures, help, new patient, or a drug or procedure name."
CAN_SAY_READBACK = "Say yes, no, repeat, or why."
CAN_SAY_STEPS = "Say next, back, repeat, start over, failed airway, or home."
CAN_SAY_WEIGHT = "Say the weight, for example eighty kilos."
SET_NAMES = {"austere-deployment-default": "PFC set", "ems-formulary": "EMS set"}
# Failed airway's question (owner, 2026-11-21): only "yes" or "no" answers it.
SAY_YES_OR_NO = "Say yes or no."
UNVERIFIED = "Unverified."
# An entry that names its vial (kit_vial: a strength, or "none") gets no volume until
# Pocket reads kit_vial: the drug's one signed vial is not necessarily the one the
# entry names (owner, 2026-11-14). null (the vial question stays) and no kit_vial
# (PFC) work the volume out as before.
PINNED_VIAL = "Milligrams only, no volume."
# No dilution in Pocket (owner rule, 2026-11-22): under 0.5 mL, the nearest 0.01 mL and this.
ONE_MIL_SYRINGE = "Use a one mil syringe."
# Signed by the owner, but Pocket cannot say the dose yet (mEq, topical): rule 6, 2026-11-22.
SIGNED_SILENT = "{name} is signed, but Pocket cannot say its dose yet."
# A weight band the formulary gives no dose is a weight floor (owner, 2026-11-22).
NO_DOSE_AT_WEIGHT = "No signed dose at this weight."
# A stated volume ("10 mL", "0.1 mL/kg", "100 cc"); "1 mg/mL" is a concentration, kept.
_VOLUME = re.compile(r"(?i)(?<![a-z/])(ml|cc)(?![a-z])")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
# A contraindication the signed text itself qualifies is spoken, not a gate.
_QUALIFIED = re.compile(r"(?i)\brelative\b|\bunless\b|\bexcept\b|^none\b|\bnot contraindicated\b")


@dataclasses.dataclass
class Turn:
    kind: str
    say: str
    after: list = dataclasses.field(default_factory=list)
    data: dict = dataclasses.field(default_factory=dict)
    # The written form, for a screen (owner, 2026-11-19): the same lines with the route
    # letters (IV, IM, IO, IN, PO, NEB). `say`/`after` are the spoken form, for the voice.
    written: str = ""
    written_after: list = dataclasses.field(default_factory=list)

    @property
    def text(self) -> str:
        """What is spoken."""
        return " ".join([self.say, *self.after])

    @property
    def written_text(self) -> str:
        """What is shown."""
        return " ".join([self.written, *self.written_after])


@dataclasses.dataclass
class Patient:
    weight: Optional[object] = None
    estimate_kg: Optional[float] = None
    age: Optional[Age] = None
    child_said: bool = False
    adult_said: bool = False
    conditions: list = dataclasses.field(default_factory=list)

    @property
    def weight_kg(self) -> Optional[float]:
        return self.weight.kg if self.weight else None

    @property
    def is_child(self) -> bool:
        return self.age.years < 18 if self.age else self.child_said

    @property
    def known(self) -> bool:
        return bool(self.weight or self.age or self.child_said or self.adult_said)

    def apply(self, p: Parsed) -> None:
        if p.weight:
            if p.weight.estimated:
                self.estimate_kg = p.weight.kg
            else:
                self.weight, self.estimate_kg = p.weight, None
        if p.age:
            self.age = p.age
        self.child_said = self.child_said or p.child
        self.adult_said = self.adult_said or p.adult
        self.conditions += [c for c in dict.fromkeys(p.conditions) if c not in self.conditions]
        # A hedged weight is not good enough to dose from and is good enough to gate from.
        for kg in (self.weight_kg, self.estimate_kg):
            if kg is not None and kg < PEDIATRIC_WEIGHT_CEILING_KG:
                self.child_said = True

    def said(self) -> list:
        parts = []
        if self.is_child:
            parts.append("child")
        if self.age:
            parts.append(f"{words.num(self.age.value)} {self.age.unit}")
        if self.weight:
            w = self.weight
            parts.append(f"{words.num(w.value)} {w.unit}")
            if w.unit == "pounds":
                parts.append(f"{words.num(w.kg)} kilos")
        elif self.adult_said and not self.age and not self.is_child:
            parts.append("adult")
        return parts + self.conditions


@dataclasses.dataclass
class Request:
    heard: Optional[str] = None
    drug: Optional[str] = None
    options: tuple = ()
    cls: Optional[str] = None
    route: Optional[str] = None
    route_options: tuple = ()     # a confusable route pair heard: "IM or IN?" first
    labels: list = dataclasses.field(default_factory=list)
    stated: list = dataclasses.field(default_factory=list)
    stated_vial: list = dataclasses.field(default_factory=list)
    # A drug said at a procedure step that names it: only the step's signed entries (Q5).
    only: tuple = ()
    step: tuple = ()          # (procedure, step id), for the log
    step_held: str = ""       # a drug the step names with no signed entry: it holds

    @property
    def empty(self) -> bool:
        return not (self.drug or self.options or self.cls or self.route or self.labels
                    or self.stated or self.stated_vial)


def spoken_line(text: str, volume: bool):
    """The spoken form of a signed line: whole when a volume was computed; otherwise
    without what states a volume (owner rulings 2026-11-08). A sentence that states one
    is dropped, unless the volume comes after an em dash: then the sentence is cut there.
    Concentrations stay. None when nothing is left. The signed text is never changed."""
    if volume or not _VOLUME.search(text):
        return text
    kept = []
    for sentence in _SENTENCE.split(text):
        head = []
        for part in sentence.split(" — "):
            if _VOLUME.search(part):
                break
            head.append(part)
        if head:
            cut = " — ".join(head)
            kept.append(cut if cut[-1] in ".!?\"" else cut + ".")
    return " ".join(kept) or None


def holding_conditions(e: dict, conditions) -> list:
    """The stated conditions a signed contraindication of this entry holds on."""
    lines = [c for c in e["contraindications"] if not _QUALIFIED.search(c)]
    return [c for c in conditions
            if any(re.search(CONDITION_PATTERNS[c], line, re.I) for line in lines)]


# The administration time, said with the dose (owner, 2026-11-22). "Slow push" is not one.
_ADMIN_TIME = re.compile(r"(?i)\bover\s+(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*"
                         r"(min(?:ute)?s?|sec(?:ond)?s?|h(?:ou)?rs?|hr)\b")
_TIME_UNITS = {"m": ("minute", "minutes"), "s": ("second", "seconds"), "h": ("hour", "hours")}


def admin_time(e: dict):
    """"Over ten minutes." from the first served caution that states a time ("or" between
    alternatives in it); for an EMS entry, else from its printed row's route cell. None
    when no time is stated."""
    texts = list(e.get("serve_cautions") or [])
    if e.get("set") == "EMS" and e.get("quote"):
        texts.append(e["quote"].split(" | ")[-1])
    for text in texts:
        said = []
        for m in _ADMIN_TIME.finditer(text):
            lo, hi, unit = m.group(1), m.group(2), _TIME_UNITS[m.group(3)[0].lower()]
            how = (f"{words.num(float(lo))} to {words.num(float(hi))} {unit[1]}" if hi
                   else f"{words.num(float(lo))} {unit[0] if float(lo) == 1 else unit[1]}")
            if how not in said:
                said.append(how)
        if said:
            return words.sentence(" or ".join(f"over {h}" for h in said)) + "."
    return None


def _not_said(e: dict, line: str) -> bool:
    """Signed text Pocket keeps in the record and does not say (owner ruling, 2026-11-22):
    the PFC ketamine dilution cautions, since there is no dilution in Pocket."""
    return e.get("drug") == "ketamine" and e.get("set", "PFC") != "EMS" and "dilution" in line.lower()


def caution_lines(e: dict, volume: bool, conditions=None) -> list:
    """Contraindications, then cautions, as spoken lines. With `conditions`, only the
    lines that name one of them; without, every line ("why")."""
    def pick(lines):
        lines = [x for x in lines if conditions is None or names_condition(x, conditions)]
        return [s for s in (spoken_line(x, volume) for x in lines) if s]
    out = []
    ci = pick(e["contraindications"])
    if ci:
        out.append("Contraindicated: " + "; ".join(ci) + ".")
    elif conditions is None:
        out.append(NO_CONTRAINDICATIONS)
    cautions = ["Caution: " + c for c in pick([x for x in e["serve_cautions"] if not _not_said(e, x)])]
    return cautions + out if conditions is None else out + cautions


def why_text(e: dict) -> str:
    parts = [f"Source: {e['source']}."]
    if e["page"] is not None:
        parts.append(f"Page {words.number_words(str(e['page']))}.")
    if e["quote"]:
        parts.append(f"Quote: {e['quote']}")
    parts.append(f"Signed by {e['signer']}, {e['date']}.")
    return " ".join(parts)


def _said(turn: Turn) -> Turn:
    """Both forms of a turn (owner, 2026-11-19): spoken, with routes in words, in `say`
    and `after`; written, with the letters, in `written` and `written_after`. Every turn
    is built in the written form. `data` (the log record) is untouched. A procedure
    step's signed text is also said with its symbols in words (words.say_step)."""
    step = words.say_step if "step" in turn.data else (lambda t: t)
    if turn.kind in ("menu", "boot") or turn.data.get("letters"):
        step = _say_menu
    return dataclasses.replace(turn, say=words.say_as(words.say_routes(step(turn.say))),
                               after=[words.say_as(words.say_routes(a)) for a in turn.after],
                               written=turn.say, written_after=list(turn.after))


def _say_menu(text: str) -> str:
    for letters, said in _MENU_LETTERS.items():
        text = re.sub(rf"\b{letters}\b", said, text)
    return text


HELP_SPOKEN = words.say_routes(_say_menu(HELP_WRITTEN))


@dataclasses.dataclass
class Run:
    """A procedure being read: its steps for this patient (None until the weight is
    known, Q2), and the step being read."""
    proc: Procedure
    steps: Optional[list] = None
    i: int = 0                   # len(steps): at the question; len(steps) + 1: its answer
    answer: Optional[str] = None

    @property
    def asking(self) -> bool:
        return bool(self.proc.branch) and self.steps is not None and self.i == len(self.steps)


def _choice(items: list, joiner: str = " or ") -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + joiner + items[-1]


def _say_class(cls: str) -> str:
    return cls.replace(" / ", " or ")


def _on_route(entry: dict, route: str) -> bool:
    return entry["route"] == ("IV" if route == "IO" else route)  # A34: one route


class Session:
    def __init__(self, bank: Optional[Bank], refused: Optional[str] = None,
                 log: Optional[Callable] = None, now: Optional[Callable] = None,
                 clock: Optional[Callable] = None, procedures: Optional[dict] = None):
        self.bank, self.refused = bank, refused
        self.procedures = procedures or {}
        self._run = None
        self.records = []
        self._log = log if log is not None else self.records.append
        self._now = now or (lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
        self._logged = 0
        self.vocab = build(bank) if bank else None
        self.patient, self.req = Patient(), Request()
        self._pending = None   # the entry a read-back is waiting on
        self._clock = clock or time.monotonic
        self._pending_at = 0.0
        self._misses = 0
        self._readback_turn = None
        self._last_entry = None
        self._last_volume = False
        self._last_say = None
        self._spoken = False
        self.announce = _said(self._boot_turn())

    def _boot_turn(self) -> Turn:
        """"Pocket ready." and the prototype sentence, spoken (owner, 2026-11-21); the set's
        name, the full version and the full hash, logged."""
        if self.refused:
            return Turn("refused", f"Bank refused: {self.refused}. No doses.")
        bank, short = self.bank, self.bank.hash[:8]
        name = set_name(bank.kit_id)
        say = START_UP_LINE
        if bank.test:
            say = f"{TEST_NOTICE} {say}"
        self._log({"event": "boot", "time": self._now(), "set": name, "bank_version": bank.version,
                   "bank_hash": bank.hash, "kit_id": bank.kit_id, "test": bank.test})
        return Turn("boot", say, data={"bank_version": bank.version, "hash": short,
                                       "test": bank.test})

    def parse(self, text: str) -> Parsed:
        return parse(text, self.vocab)

    # ── one phrase ──────────────────────────────────────────────────────────

    def handle(self, text: str, spoken: bool = False) -> Turn:
        """spoken: the text is what Vosk heard. Only then does a pair the clips or the
        sound-alike checks confuse ask "X or Y?" first: typed text cannot be misheard.
        Every line comes back with routes as they are said (words.say_routes)."""
        return _said(self._turn(text, spoken))

    def _turn(self, text: str, spoken: bool) -> Turn:
        self._spoken = spoken
        if self.refused:
            return self.announce
        self._expired()
        menu = self._menu_word(self.parse(text))
        if menu:
            turn = self._menu(menu)
            self._last_say = turn
            return turn
        if self._pending is not None:
            turn = self._confirm_step(self.parse(text))
            if turn.kind != "repeat":
                self._last_say = turn
            return turn
        p = self.parse(text)
        if p.unknown or not (p.controls or p.has_slots()):
            return Turn("unrecognised", "Not recognised.")
        turn = self._handle(p)
        if turn.kind != "repeat":
            self._last_say = turn
        return turn

    # ── the home menu, help and command lists (owner, 2026-11-21) ──────────

    @staticmethod
    def _menu_word(p: Parsed) -> Optional[str]:
        """A menu command said alone. Names and instructions only: none of these ever
        speaks a dose, and only "home" changes anything."""
        if len(p.controls) == 1 and p.controls[0] in MENU_CONTROLS and not (p.unknown or p.has_slots()):
            return MENU_OF.get(p.controls[0], p.controls[0])
        return None

    @property
    def set_name(self) -> str:
        return set_name(self.bank.kit_id) if self.bank else ""

    def _menu(self, word: str) -> Turn:
        if word == "home":                    # from anywhere; the patient stays
            self.req, self._pending, self._misses, self._run = Request(), None, 0, None
            return Turn("menu", HOME_LINE)
        if word == "drugs":
            names = sorted({self.vocab.listed_name(d) for d in self.bank.signed_drugs})
            if not names:
                return Turn("menu", "No signed drugs.")
            return Turn("menu", f"Signed drugs: {', '.join(names)}. Say a drug name to begin.")
        if word == "procedures":
            titles = [p.title for p in self.procedures.values()]
            if not titles:
                return Turn("menu", "No signed procedures.")
            return Turn("menu", f"Signed procedures: {', '.join(titles)}. Say a procedure name to begin.")
        if word == "help":
            return Turn("menu", HELP_WRITTEN)
        return Turn("menu", self._can_say())

    def _can_say(self) -> str:
        run, req = self._run, self.req
        if self._pending is not None:
            return CAN_SAY_READBACK
        if run is not None and run.asking:
            return SAY_YES_OR_NO
        if run is not None and run.steps is None:
            return CAN_SAY_WEIGHT
        if run is not None:
            return CAN_SAY_STEPS
        if req.options:
            return f"Say {_choice([words.say_name(o) for o in req.options])}."
        return CAN_SAY_IDLE

    # ── the confirm step ───────────────────────────────────────────────────

    def _expired(self) -> bool:
        if self._pending is not None and self._clock() - self._pending_at > PENDING_S:
            self._cancel()
            return True
        return False

    def expire_pending(self) -> Optional[Turn]:
        """For the device loop: "Cancelled." once, when a read-back has waited over
        PENDING_S, so a later "yes" can never confirm an old dose."""
        return _said(Turn("control", CANCELLED)) if self._expired() else None

    def _cancel(self) -> None:
        """Clears the request and the pending dose; the patient (weight, age) stays."""
        self.req, self._pending, self._misses = Request(), None, 0

    def _confirm_step(self, p: Parsed) -> Turn:
        """A read-back is waiting (owner rulings, 2026-11-16):
          - one confirm word doses; one cancel word cancels (weight and age kept);
          - "why" and "repeat" (the read-back again) answer and are not misses;
          - "new patient" clears the patient and drops the pending dose (A1);
          - anything said about the patient or the request (weight, age, child or adult,
            a condition, drug, route, indication) runs the normal flow: a fresh full
            read-back (a fresh miss count and 30 s), a hold or a question, never the old dose;
          - anything else: "Say confirm or cancel."; the second miss cancels."""
        words_said = [CONTROL_OF.get(c, c) for c in p.controls]
        if not p.unknown and not p.has_slots() and len(words_said) == 1:
            if words_said[0] == "confirm":
                return self._dose()
            if words_said[0] == "cancel":
                self._cancel()
                return Turn("control", CANCELLED)
            if words_said[0] == "why":
                return self._control("why")
            if words_said[0] == "repeat":                # the read-back itself, again
                rb = self._readback_turn
                return Turn("repeat", rb.say, list(rb.after), dict(rb.data))
            if words_said[0] == "new patient":           # A1: drops the pending dose too
                return self._handle(p)
        if not p.unknown and p.has_slots():
            # New information about the patient or the request (weight, age, child or adult,
            # a condition, drug, route, indication): the read-back no longer stands, so the
            # normal flow runs on it: a fresh read-back, a hold or a question, never the old
            # dose. A confirm or cancel word said with it is set aside: the new information
            # wins, and it is read back.
            return self._handle(dataclasses.replace(p, controls=[]))
        self._misses += 1
        if self._misses >= MISSES_TO_CANCEL:
            self._cancel()
            return Turn("control", CANCELLED)
        return Turn("ask", SAY_CONFIRM_OR_CANCEL)

    def _handle(self, p: Parsed) -> Turn:
        lead = ""
        controls = [CONTROL_OF.get(c, c) for c in p.controls]
        if "new patient" in controls:
            controls.remove("new patient")
            self.patient, self.req = Patient(), Request()
            self._pending = self._last_entry = None
            self._last_volume = False
            self._run = None
            lead = "New patient. Weight and age cleared."
            if not controls and not p.has_slots():
                return Turn("control", lead)
        if self._run is not None and self._run.asking:
            return self._at_question(p)
        if controls:
            if len(controls) > 1 or p.has_slots():
                return Turn("control", "One command at a time.")
            return self._control(controls[0])
        name = self._procedure_named(p)
        if name:
            turn = self._start(name, p)
        elif self._run is not None and self._run.steps is None and p.weight and not p.drugs:
            self.patient.apply(p)
            turn = self._begin()
        else:
            turn = self._slots(p)
        if lead:
            turn.say = f"{lead} {turn.say}"
        return turn

    def _control(self, word: str) -> Turn:
        if word == "confirm":
            return self._dose() if self._pending else Turn("control", "Nothing to confirm.")
        if word == "cancel":
            self.req, self._pending, self._run = Request(), None, None
            return Turn("control", "Cancelled.")
        if word in ("next", "back"):
            return self._move(1 if word == "next" else -1)
        if word == "start over":
            return self._start_over()
        if word == "repeat":
            run = self._run
            if run is not None and run.steps is not None and self.req.empty:
                step = self._step_turn()            # the current step, not the last line
                return Turn("repeat", step.say, list(step.after), dict(step.data))
            last = self._last_say
            if last is None:
                return Turn("control", "Nothing to repeat.")
            return Turn("repeat", last.say, list(last.after), dict(last.data))
        if word == "why":
            entry = self._pending or self._last_entry
            if not entry:
                return Turn("control", "No dose to explain.")
            volume = self._last_volume and not self._pending
            return Turn("why", why_text(entry), caution_lines(entry, volume))
        if word == "log":
            return Turn("control", f"{words.sentence(words.num(self._logged))} doses logged.")
        return Turn("control", "Battery is not read on the bench.")

    def _slots(self, p: Parsed) -> Turn:
        self.patient.apply(p)
        self._pending = None
        if len({d.generics for d in p.drugs}) > 1:
            self.req = Request()
            return Turn("ask", "One drug at a time.")
        if p.drugs:
            self._name_drug(p.drugs[0])
            self._at_step()
        if len(set(p.classes)) > 1:
            return Turn("ask", "One indication at a time.")
        req = self.req
        if p.classes:
            req.cls = p.classes[0]
        if p.routes:
            route, term = p.routes[-1], p.route_terms[-1]
            if req.route_options and route in req.route_options:
                req.route, req.route_options = route, ()        # the answer
            elif self._spoken and term in CONFUSABLE_ROUTE_TERMS:
                req.route, req.route_options = None, CONFUSABLE_ROUTE_TERMS[term]
            else:
                req.route, req.route_options = route, ()
        req.labels += p.labels
        new_stated = p.stated + p.stated_vial
        req.stated += p.stated
        req.stated_vial += p.stated_vial
        if p.bad_number:
            return Turn("ask", "Say the number again.")
        if p.bare_number and not p.weight:
            return Turn("ask", "Kilos or pounds?")
        if req.empty:
            said = self.patient.said() or ["estimate"]
            return Turn("noted", "Noted: " + ", ".join(said) + ".")
        turn = self._next() if (req.drug or req.options) else Turn("ask", "Which drug?")
        if new_stated and turn.kind == "ask" and req.heard:
            turn.say = f"Heard {req.heard} {_choice(new_stated, ', ')}. {turn.say}"
        return turn

    def _name_drug(self, match) -> None:
        req = self.req
        if len(match.generics) > 1:
            kept = req.options and set(match.generics) <= set(req.options)
            if not kept:
                self.req = req = Request(cls=req.cls if req.empty else None)
            req.options, req.heard, req.drug = match.generics, match.term, None
            return
        generic = match.generics[0]
        if generic in req.options or generic == req.drug:
            req.options, req.drug, req.heard = (), generic, match.term
            return
        fresh = not (req.drug or req.options)
        keep = dict(cls=req.cls if fresh else None, route=req.route if fresh else None,
                    route_options=req.route_options if fresh else ())
        pair = self.vocab.confusable.get(generic) if self._spoken else None
        if pair:
            # A pair the clips or the sound-alike checks confuse: always "X or Y?" first.
            self.req = Request(options=pair, heard=match.term, **keep)
            return
        self.req = Request(drug=generic, heard=match.term, **keep)

    # ── procedures (owner, 2026-11-20) ─────────────────────────────────────

    def _procedure_named(self, p: Parsed) -> Optional[str]:
        """"failed airway"; or the RSI class said with nothing about a drug: "rsi",
        "rsi eighty kilos". "Rocuronium for RSI" stays a dose request."""
        if p.procedures:
            return p.procedures[0]
        if (p.classes and set(p.classes) == {"RSI"} and not (p.drugs or p.routes or p.labels
                                                             or p.stated or p.stated_vial)):
            return "rsi"
        return None

    def _start(self, name: str, p: Parsed) -> Turn:
        self.patient.apply(p)
        self.req, self._pending, self._run = Request(), None, None
        proc = self.procedures.get(name)
        if proc is None:
            return self._hold(f"No signed steps for {PROCEDURE_TITLES[name]}.")
        self._run = Run(proc)
        return self._begin()

    def _begin(self) -> Turn:
        """The weight, once, at the start (Q2); access is never asked."""
        run, patient = self._run, self.patient
        if run.proc.needs_weight:
            if patient.estimate_kg is not None and patient.weight is None:
                return Turn("ask", ASK_ESTIMATE)
            if patient.weight is None:
                return Turn("ask", "Weight?")
        years = patient.age.years if patient.age else None
        run.steps, run.i, run.answer = run.proc.for_patient(patient.is_child, years), 0, None
        who = []
        if patient.known:
            who = ["child" if patient.is_child else "adult"] + [x for x in patient.said() if x != "child"]
        lead = words.sentence(", ".join([run.proc.title, *who])) + ". "
        return self._step_turn(lead)

    def _step_turn(self, lead: str = "") -> Turn:
        """The step at run.i; at the question, the question; after it, the answer's step,
        numbered last."""
        run, n = self._run, len(self._run.steps)
        total = n + (1 if run.proc.branch else 0)
        if run.asking:
            return Turn("ask", f"{words.sentence(run.proc.branch['ask'])} {SAY_YES_OR_NO}")
        if run.i > n:
            years = self.patient.age.years if self.patient.age else None
            step = run.proc.answer(run.answer, self.patient.is_child, years)
        else:
            step = run.steps[run.i]
        say = (f"{lead}Step {words.num(min(run.i, n) + 1)} of {words.num(total)}. {step.text}")
        after = []
        if step.doses:
            after.append(f"For the dose, say {_choice([words.say_name(d) for d in step.drugs])}.")
        if step.held_drugs:
            after.append(STEP_HELD_AFTER.format(names=_choice([words.say_name(d) for d in step.held_drugs], " and ")))
        return Turn("step", say, after, data={"step": step.id, "procedure": run.proc.name})

    def _move(self, by: int) -> Turn:
        run = self._run
        if run is None:
            return Turn("control", "No steps running.")
        if run.steps is None:
            return Turn("ask", "Weight?")
        self.req = Request()
        n, branch = len(run.steps), bool(run.proc.branch)
        if run.i + by < 0:
            return Turn("step", "First step.")
        if run.asking and by > 0:
            return Turn("ask", SAY_YES_OR_NO)
        if run.i + by >= n + (2 if branch else 0):
            self._run = None
            return Turn("step", f"End of {run.proc.title} steps.")
        run.i += by
        if run.asking:
            run.answer = None
        return self._step_turn()

    def _at_question(self, p: Parsed) -> Turn:
        """Only "yes" or "no" answers (owner, 2026-11-21). "repeat", "back", "start over"
        and "cancel" work as always; anything else asks again."""
        said = p.controls[0] if len(p.controls) == 1 and not p.has_slots() else None
        if said in ("yes", "no"):
            run = self._run
            run.answer, run.i = said, len(run.steps) + 1
            return self._step_turn()
        if said in ("repeat", "back", "start over", "cancel"):
            return self._control(said)
        return Turn("ask", SAY_YES_OR_NO)

    def _start_over(self) -> Turn:
        """The current procedure from step one; the patient stays, the request does not."""
        run = self._run
        if run is None:
            return Turn("control", "No steps running.")
        self.req, self._pending = Request(), None
        return self._begin()

    def _at_step(self) -> None:
        """A drug the current step names: only that step's signed entries (Q5). Any
        other drug is asked for as usual."""
        run, req = self._run, self.req
        if run is None or run.steps is None or not req.drug:
            return
        step = run.steps[run.i]
        if req.drug in step.drugs:
            req.only = tuple(_key(e) for e in step.doses if e["drug"] == req.drug)
            req.step = (run.proc.name, step.id)
        elif req.drug in step.held_drugs:
            req.step_held, req.step = req.drug, (run.proc.name, step.id)

    # ── the gate ───────────────────────────────────────────────────────────

    def _hold(self, say: str) -> Turn:
        self.req, self._pending, self._last_entry = Request(), None, None
        self._last_volume = False
        return Turn("hold", say)

    def _next(self) -> Turn:
        req, patient = self.req, self.patient
        if req.options:
            names = [words.say_name(o) for o in req.options]
            return Turn("ask", words.sentence(_choice(names)) + "?")
        drug = req.drug
        if req.step_held:
            return self._hold(STEP_HELD.format(name=words.say_name(req.step_held)))
        if drug not in self.bank.signed_drugs:
            if drug in self.bank.silent_drugs:
                return self._hold(SIGNED_SILENT.format(name=words.say_name(drug).capitalize()))
            return self._hold(f"No signed dose for {req.heard}.")
        if req.route_options:
            return Turn("ask", _choice(list(req.route_options)) + "?")

        name = words.say_name(drug)
        cands = [e for e in self.bank.entries if e["drug"] == drug]
        if req.only:
            cands = [e for e in cands if _key(e) in req.only]
        for_cls = f" for {_say_class(req.cls)}" if req.cls else ""
        if req.cls:
            cands = [e for e in cands if e["indication_class"] == req.cls]
            if not cands:
                return self._hold(f"No signed dose of {name}{for_cls}.")
        if req.route:
            cands = [e for e in cands if _on_route(e, req.route)]
            if not cands:
                return self._hold(f"No signed {req.route} dose of {name}{for_cls}.")
        if req.labels:
            printed = [e for e in cands if set(req.labels) <= label_tokens(e["indication"])]
            # none: the class's words too ("calcium channel blocker overdose", label "... OD")
            cands = printed or [e for e in cands if set(req.labels) <= label_tokens(e["indication"])
                                | label_tokens(e["indication_class"])]
            if not cands:
                return self._hold(f"No signed dose of {name} for that.")

        # Weight, in the pre-gate's order. Only a confirmed weight doses (F-1).
        per_kg = any((e["rule"] or {}).get("per_kg") for e in cands)
        if patient.estimate_kg is not None and patient.weight is None:
            return Turn("ask", ASK_ESTIMATE)
        if not patient.known:
            return Turn("ask", "Weight?" if per_kg else ASK_ADULT)
        if patient.is_child and patient.weight is None:
            return Turn("ask", "Weight?")

        fit = [e for e in cands if contracts.fits_population(e, patient.is_child)]
        if not fit:
            who = "a child" if patient.is_child else "an adult"
            return self._hold(f"No signed dose of {name} for {who}.")
        fit = contracts.prefer_population_specific(fit)
        years = patient.age.years if patient.age else None
        fit = [e for e in fit if contracts.age_exclusion(e, years) is None]
        if not fit:
            return self._hold(f"No signed dose of {name} for this age.")
        if patient.weight is None and any((e["rule"] or {}).get("per_kg") for e in fit):
            return Turn("ask", "Weight?")

        classes = list(dict.fromkeys(e["indication_class"] for e in fit))
        if len(classes) > 1:
            return Turn("ask", f"Which indication: {_choice([_say_class(c) for c in classes])}?")
        cls = classes[0]

        routes = [r for r in ROUTE_ORDER if any(e["route"] == r for e in fit)]
        if len(routes) > 1:
            return Turn("ask", f"Which route: {_choice(routes)}?")
        route_said = req.route or routes[0]

        if any(contracts.age_band(e) for e in fit):
            if years is None:
                return Turn("ask", "Age in years?")
            fit = [e for e in fit if not contracts.age_band(e)
                   or contracts.age_band(e)[0] <= years < contracts.age_band(e)[1]]
            if not fit:
                return self._hold(f"No signed dose of {name} for this age.")

        labels = list(dict.fromkeys(e["indication"] for e in fit))
        several = _class_labels(self.bank, drug, cls, routes[0], patient, years)
        if len(labels) > 1:
            said = set(req.labels) | {w for w in label_tokens(cls)}
            exact = [lb for lb in labels if label_tokens(lb) == said]
            if len(exact) != 1:
                return Turn("ask", "Which one: "
                            + _choice([words.say_name(lb) for lb in labels], ", or ") + "?")
            labels = exact
        entry = [e for e in fit if e["indication"] == labels[0]]
        if len(entry) != 1:
            return self._hold(f"No single signed dose of {name}.")
        if contracts.below_weight_floor(entry[0], patient.weight_kg):
            return self._hold(NO_DOSE_AT_WEIGHT)
        held = holding_conditions(entry[0], patient.conditions)
        if held:
            return self._contraindicated(entry[0], name, held, years)
        return self._read_back(entry[0], name, cls, several > 1, route_said)

    def _contraindicated(self, entry, name, held, years) -> Turn:
        """A gate, as EdgeCDSS's A12: no read-back, no dose. Names the other signed drugs
        for the same indication that this patient's conditions do not hold."""
        base = entry["indication"].split(" — ")[0]
        alts = []
        for e in self.bank.entries:
            if (e["drug"] == entry["drug"] or e["indication_class"] != entry["indication_class"]
                    or e["indication"].split(" — ")[0] != base
                    or not contracts.fits_population(e, self.patient.is_child)
                    or contracts.age_exclusion(e, years) is not None
                    or holding_conditions(e, self.patient.conditions)):
                continue
            alt = words.sentence(words.say_name(e["drug"]))
            if alt not in alts:
                alts.append(alt)
        say = f"Held. {words.sentence(name)} is contraindicated with {_choice(held, ' and ')}."
        if len(alts) == 1:
            say += f" {alts[0]} is the signed alternative."
        elif alts:
            say += f" Signed alternatives: {', '.join(alts)}."
        return self._hold(say)

    def _read_back(self, entry, name, cls, name_label, route_said) -> Turn:
        self._pending = entry
        self._pending_at, self._misses = self._clock(), 0
        what = words.say_name(entry["indication"]) if name_label else _say_class(cls)
        parts = [words.sentence(name), what, route_said, *self.patient.said()]
        say = ", ".join(parts) + "."
        if self.bank.test:
            say = f"{TEST_NOTICE} {say}"
        stated = self.req.stated + self.req.stated_vial
        if stated:
            say += f" You said {_choice(stated, ', ')}."
        self._readback_turn = Turn("readback", say + " Confirm?")
        return self._readback_turn

    # ── the dose ───────────────────────────────────────────────────────────

    def _dose(self) -> Turn:
        entry, req = self._pending, self.req
        self._pending = None
        self._last_entry = entry
        self._last_volume = False
        weight = self.patient.weight_kg
        r = contracts.resolve_dose(entry, weight)
        name = words.sentence(words.say_name(entry["drug"]))
        rule = entry["rule"]
        record = {"volume_ml": None, "concentration_mg_ml": None, "diluted": False}

        if r["kind"] == contracts.RATE:
            units = rule["units"]
            rate = (words.amount(rule["min"], units) if rule["min"] == rule["max"]
                    else words.span(rule["min"], rule["max"], units))
            say = f"{name} {rate}. Infusion, no single volume."
            record["dose"] = contracts.range_text(entry)
        elif r["dose_mg"] is None:
            return self._hold(f"No signed dose of {words.say_name(entry['drug'])} can be worked out.")
        else:
            parts = [f"{name} {words.amount(r['display_value'], r['display_units'])}."]
            signed = "test-set" if self.bank.test else "signed"
            if r["capped"] and not r["floor_applied"]:
                parts.append(CAPPED.replace("signed", signed))
            if r["floor_applied"]:
                parts.append(RAISED.replace("signed", signed))
            pinned = entry.get("kit_vial") is not None
            vol = vials.dose_volume(self.bank.kit, entry, round(r["dose_mg"], 4),
                                    contracts.signed_max_mg(entry, weight))
            withheld = pinned or not self._stated_vial_is_signed(entry["drug"])
            parts.append(PINNED_VIAL if pinned else _volume_words(vol, withheld))
            timed = admin_time(entry)
            if timed:
                parts.append(timed)
            if rule["min"] != rule["max"]:
                parts.append(f"{'Test range' if self.bank.test else 'Signed range'} {words.span(rule['min'], rule['max'], rule['units'])}.")
            say = " ".join(parts)
            record["dose"] = f"{r['display_value']:g} {r['display_units']}"
            if not withheld:
                record.update(volume_ml=vol["volume_ml"], diluted=vol["diluted"],
                              concentration_mg_ml=vol["concentration_mg_ml"])

        if self.bank.test:
            if entry["check_failed"]:
                say = f"{UNVERIFIED} {say}"
            record.update(test=True, check_failed=list(entry["check_failed"]))
        if req.step:
            record.update(procedure=req.step[0], step=req.step[1])
        record.update(time=self._now(), drug=entry["drug"], indication=entry["indication"],
                      route=req.route or entry["route"], population=entry["population"],
                      weight_kg=weight, stated=req.stated + req.stated_vial,
                      bank_version=self.bank.version, bank_hash=self.bank.hash[:8])
        self._log(record)
        self._logged += 1
        self.req = Request()
        # Dose first. After it, only the lines that name a condition stated for this
        # patient; the rest are in "why" (owner ruling 2026-11-08).
        self._last_volume = record["volume_ml"] is not None
        after = caution_lines(entry, self._last_volume, self.patient.conditions)
        return Turn("dose", say, after, data={"record": record})

    def _stated_vial_is_signed(self, drug: str) -> bool:
        """True when no vial was stated, or every stated one is, word for word, a signed
        kit vial of this drug. The words are compared; nothing is computed from them."""
        stated = self.req.stated_vial
        if not stated:
            return True
        signed = {p for v in self.bank.kit.get(drug) or [] for p in _vial_phrasings(v)}
        return all(_vial_words(s) in signed for s in stated)


def set_name(kit_id: str) -> str:
    for prefix, name in SET_NAMES.items():
        if kit_id.startswith(prefix):
            return name
    return "Drug set"


def _key(e: dict) -> tuple:
    return (e["drug"], e["indication"], e["population"])


def _class_labels(bank, drug, cls, route, patient, years) -> int:
    """How many signed labels this patient has in this class on this route: when more
    than one, the read-back names the label, not the class."""
    pool = [e for e in bank.entries if e["drug"] == drug and e["indication_class"] == cls
            and e["route"] == route and contracts.fits_population(e, patient.is_child)]
    pool = contracts.prefer_population_specific(pool)
    pool = [e for e in pool if not contracts.age_band(e) or years is None
            or contracts.age_band(e)[0] <= years < contracts.age_band(e)[1]]
    return len({e["indication"] for e in pool})


_MG = {"milligrams", "milligram", "mg"}


def _vial_words(text: str) -> str:
    """Stated vial words, normalised for comparison only: unit spellings, "and", hyphens,
    and a leading "zero" before "point"."""
    toks = text.lower().replace("-", " ").split()
    out = []
    for i, w in enumerate(toks):
        if w == "and" or (w == "zero" and toks[i + 1:i + 2] == ["point"] and not out):
            continue
        out.append("mg" if w in _MG else "ml" if w in VOLUME_UNITS else w)
    return " ".join(out)


def _vial_phrasings(v: dict) -> set:
    """How a signed vial can be said: its strength per mil, or its mass in its volume."""
    conc, mass, vol = (words.num(v[k]) for k in ("concentration_mg_ml", "mass_mg", "volume_ml"))
    said = [f"{conc} mg per ml", f"{conc} mg per one ml", f"{conc} mg in one ml"]
    if v.get("mass_mg") and v.get("volume_ml"):
        said += [f"{mass} mg in {vol} ml", f"{mass} mg per {vol} ml"]
    return {_vial_words(s) for s in said}


def _volume_words(vol: dict, withheld: bool) -> str:
    if withheld:
        return "Stated vial not used, no volume."   # K1: not the signed vial
    if vol["volume_ml"] is not None:
        said = (f"{words.sentence(words.mils(vol['volume_ml']))} of "
                f"{vol['strength'] or words.num(vol['concentration_mg_ml'])}.")   # as the label reads
        return f"{said} {ONE_MIL_SYRINGE}" if vol["volume_ml"] < vials.ONE_MIL_BELOW_ML else said
    if vol["refusal"] == vials.TOO_SMALL:
        return "Too small to draw. No volume."
    if vol["refusal"] == vials.TOO_LARGE:
        return "Over sixty mils, an infusion. No volume."
    if vol["status"] == vials.NEEDS_CONFIRMATION:
        return "More than one signed vial, no volume."
    return NO_SIGNED_VIAL


def boot(bank_dir=BANK_DIR, log: Optional[Callable] = None, now: Optional[Callable] = None,
         clock: Optional[Callable] = None, retired_ok: bool = False) -> Session:
    """A session, refused if the bank is. A refused session answers nothing else."""
    try:
        bank = load_bank(bank_dir, retired_ok=retired_ok)
    except BankRefused as e:
        return Session(None, refused=str(e))
    try:
        procedures = load_procedures(bank_dir, bank)
    except ProceduresRefused:
        procedures = {}            # every procedure holds; the doses are unaffected
    return Session(bank, log=log, now=now, clock=clock, procedures=procedures)


def jsonl_log(path) -> Callable:
    """Append-only JSON lines, flushed to disk per dose (rule 3). The first line also
    fsyncs the directory, so a new log file's name survives a power cut too (owner,
    2026-11-21: power can be cut at any time)."""
    path = os.fspath(path)
    synced = []

    def write(record: dict) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if not synced:
            fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            synced.append(True)
    return write
