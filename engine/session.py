"""One device session: the pre-gate's questions, then read-back, then "confirm".

The order is EdgeCDSS's pre_gate, adapted to a device that can only ask one thing at a
time: holds first, then the weight questions, then indication, route and which entry.
Stricter than EdgeCDSS in three places, none of them a loosening: a route is asked
whenever more than one is signed, an entry whenever a class holds more than one, and
"estimated" never doses (EdgeCDSS REFERENCE section 9).

Rule 1: every number spoken comes from the bank, or is the weight or age read back.
Rule 2: a dose only after a read-back, on "confirm" alone.
Rule 3: every confirmed dose goes to `log` with a time.
"""
import dataclasses
import datetime
import json
import os
from typing import Callable, Optional

from engine import contracts, vials, words
from engine.bank import Bank, BankRefused, load_bank
from grammar.parser import Age, Parsed, parse
from grammar.vocabulary import build, label_tokens

PEDIATRIC_WEIGHT_CEILING_KG = 40.0  # EdgeCDSS openai_client: not spoken, a gate
ROUTE_ORDER = ("IV", "IM", "IN", "PO", "NEB")
NO_SIGNED_VIAL = "No signed vial, no volume."
CAPPED = "Capped at the signed maximum."
RAISED = "Raised to the signed minimum."
ASK_ADULT = "Adult? Say adult, or give the age or the weight."  # ADULT_CONFIRM_ASK
ASK_ESTIMATE = "I only have an estimate. Say the weight to confirm it."  # WEIGHT_CONFIRM_ASK


@dataclasses.dataclass
class Turn:
    kind: str
    say: str
    after: list = dataclasses.field(default_factory=list)
    data: dict = dataclasses.field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join([self.say, *self.after])


@dataclasses.dataclass
class Patient:
    weight: Optional[object] = None
    estimate_kg: Optional[float] = None
    age: Optional[Age] = None
    child_said: bool = False
    adult_said: bool = False

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
        return parts


@dataclasses.dataclass
class Request:
    heard: Optional[str] = None
    drug: Optional[str] = None
    options: tuple = ()
    cls: Optional[str] = None
    route: Optional[str] = None
    labels: list = dataclasses.field(default_factory=list)
    stated: list = dataclasses.field(default_factory=list)
    stated_vial: list = dataclasses.field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.drug or self.options or self.cls or self.route or self.labels
                    or self.stated or self.stated_vial)


def why_text(e: dict) -> str:
    parts = [f"Source: {e['source']}."]
    if e["page"] is not None:
        parts.append(f"Page {words.number_words(str(e['page']))}.")
    if e["quote"]:
        parts.append(f"Quote: {e['quote']}")
    parts.append(f"Signed by {e['signer']}, {e['date']}.")
    return " ".join(parts)


def _choice(items: list, joiner: str = " or ") -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + joiner + items[-1]


def _say_class(cls: str) -> str:
    return cls.replace(" / ", " or ")


def _on_route(entry: dict, route: str) -> bool:
    return entry["route"] == ("IV" if route == "IO" else route)  # A34: one route


class Session:
    def __init__(self, bank: Optional[Bank], refused: Optional[str] = None,
                 log: Optional[Callable] = None, now: Optional[Callable] = None):
        self.bank, self.refused = bank, refused
        self.records = []
        self._log = log if log is not None else self.records.append
        self._now = now or (lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
        self._logged = 0
        self.vocab = build(bank) if bank else None
        self.patient, self.req = Patient(), Request()
        self._pending = None   # the entry a read-back is waiting on
        self._last_entry = None
        self._last_say = None
        self.announce = self._boot_turn()

    def _boot_turn(self) -> Turn:
        if self.refused:
            return Turn("refused", f"Bank refused: {self.refused}. No doses.")
        short = self.bank.hash[:8]
        return Turn("boot",
                    f"Bank version {words.say_chars(self.bank.version)}. "
                    f"Hash {words.say_chars(short)}. "
                    f"{words.num(len(self.bank.entries))} signed entries, "
                    f"{words.num(sum(len(v) for v in self.bank.kit.values()))} signed vials.",
                    data={"bank_version": self.bank.version, "hash": short})

    def parse(self, text: str) -> Parsed:
        return parse(text, self.vocab)

    # ── one phrase ──────────────────────────────────────────────────────────

    def handle(self, text: str) -> Turn:
        if self.refused:
            return self.announce
        p = self.parse(text)
        if p.unknown or not (p.controls or p.has_slots()):
            return Turn("unrecognised", "Not recognised.")
        turn = self._handle(p)
        if turn.kind != "repeat":
            self._last_say = turn
        return turn

    def _handle(self, p: Parsed) -> Turn:
        lead = ""
        controls = list(p.controls)
        if "new patient" in controls:
            controls.remove("new patient")
            self.patient, self.req = Patient(), Request()
            self._pending = self._last_entry = None
            lead = "New patient. Weight and age cleared."
            if not controls and not p.has_slots():
                return Turn("control", lead)
        if controls:
            if len(controls) > 1 or p.has_slots():
                return Turn("control", "One command at a time.")
            return self._control(controls[0])
        turn = self._slots(p)
        if lead:
            turn.say = f"{lead} {turn.say}"
        return turn

    def _control(self, word: str) -> Turn:
        if word == "confirm":
            return self._dose() if self._pending else Turn("control", "Nothing to confirm.")
        if word == "cancel":
            self.req, self._pending = Request(), None
            return Turn("control", "Cancelled.")
        if word == "repeat":
            last = self._last_say
            if last is None:
                return Turn("control", "Nothing to repeat.")
            return Turn("repeat", last.say, list(last.after), dict(last.data))
        if word == "why":
            entry = self._pending or self._last_entry
            return Turn("why", why_text(entry)) if entry else Turn("control", "No dose to explain.")
        if word == "log":
            return Turn("control", f"{words.num(self._logged)} doses logged.")
        return Turn("control", "Battery is not read on the bench.")

    def _slots(self, p: Parsed) -> Turn:
        self.patient.apply(p)
        self._pending = None
        if len({d.generics for d in p.drugs}) > 1:
            self.req = Request()
            return Turn("ask", "One drug at a time.")
        if p.drugs:
            self._name_drug(p.drugs[0])
        if len(set(p.classes)) > 1:
            return Turn("ask", "One indication at a time.")
        req = self.req
        if p.classes:
            req.cls = p.classes[0]
        if p.routes:
            req.route = p.routes[-1]
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
        self.req = Request(cls=req.cls if not (req.drug or req.options) else None,
                           route=req.route if not (req.drug or req.options) else None,
                           drug=generic, heard=match.term)

    # ── the gate ───────────────────────────────────────────────────────────

    def _hold(self, say: str) -> Turn:
        self.req, self._pending, self._last_entry = Request(), None, None
        return Turn("hold", say)

    def _next(self) -> Turn:
        req, patient = self.req, self.patient
        if req.options:
            names = [words.say_name(o) for o in req.options]
            return Turn("ask", words.sentence(_choice(names)) + "?")
        drug = req.drug
        if drug not in self.bank.signed_drugs:
            return self._hold(f"No signed dose for {req.heard}.")

        name = words.say_name(drug)
        cands = [e for e in self.bank.entries if e["drug"] == drug]
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
            cands = [e for e in cands if set(req.labels) <= label_tokens(e["indication"])]
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
        return self._read_back(entry[0], name, cls, several > 1, route_said)

    def _read_back(self, entry, name, cls, name_label, route_said) -> Turn:
        self._pending = entry
        what = words.say_name(entry["indication"]) if name_label else _say_class(cls)
        parts = [words.sentence(name), what, route_said, *self.patient.said()]
        say = ", ".join(parts) + "."
        stated = self.req.stated + self.req.stated_vial
        if stated:
            say += f" You said {_choice(stated, ', ')}."
        return Turn("readback", say + " Confirm?")

    # ── the dose ───────────────────────────────────────────────────────────

    def _dose(self) -> Turn:
        entry, req = self._pending, self.req
        self._pending = None
        self._last_entry = entry
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
            if r["capped"] and not r["floor_applied"]:
                parts.append(CAPPED)
            if r["floor_applied"]:
                parts.append(RAISED)
            vol = vials.dose_volume(self.bank.kit, entry, round(r["dose_mg"], 4))
            parts.append(_volume_words(vol, bool(req.stated_vial)))
            if rule["min"] != rule["max"]:
                parts.append(f"Signed range {words.span(rule['min'], rule['max'], rule['units'])}.")
            say = " ".join(parts)
            record["dose"] = f"{r['display_value']:g} {r['display_units']}"
            if not req.stated_vial:
                record.update(volume_ml=vol["volume_ml"], diluted=vol["diluted"],
                              concentration_mg_ml=vol["concentration_mg_ml"])

        record.update(time=self._now(), drug=entry["drug"], indication=entry["indication"],
                      route=req.route or entry["route"], population=entry["population"],
                      weight_kg=weight, stated=req.stated + req.stated_vial,
                      bank_version=self.bank.version, bank_hash=self.bank.hash[:8])
        self._log(record)
        self._logged += 1
        self.req = Request()
        after = []
        if entry["serve_cautions"]:
            after.append("Caution: " + entry["serve_cautions"][0])
        if entry["contraindications"]:
            after.append("Contraindicated: " + "; ".join(entry["contraindications"]) + ".")
        else:
            after.append("No contraindications listed.")
        return Turn("dose", say, after, data={"record": record})


def _class_labels(bank, drug, cls, route, patient, years) -> int:
    """How many signed labels this patient has in this class on this route: when more
    than one, the read-back names the label, not the class."""
    pool = [e for e in bank.entries if e["drug"] == drug and e["indication_class"] == cls
            and e["route"] == route and contracts.fits_population(e, patient.is_child)]
    pool = contracts.prefer_population_specific(pool)
    pool = [e for e in pool if not contracts.age_band(e) or years is None
            or contracts.age_band(e)[0] <= years < contracts.age_band(e)[1]]
    return len({e["indication"] for e in pool})


def _volume_words(vol: dict, stated_vial: bool) -> str:
    if stated_vial:
        return "Stated vial not used, no volume."   # K1: never computed on
    if vol["diluted"]:
        return (f"{_recipe(vol['recipe'])} {words.sentence(words.mils(vol['volume_ml']))} "
                f"of the dilution, {words.num(vol['concentration_mg_ml'])} per mil.")
    if vol["volume_ml"] is not None:
        return (f"{words.sentence(words.mils(vol['volume_ml']))} of "
                f"{words.num(vol['concentration_mg_ml'])}.")
    if vol["refusal"] == vials.TOO_SMALL:
        if vol["recipe"]:
            return f"Too small to draw from the vial. {_recipe(vol['recipe'])} No volume."
        return "Too small to draw. No volume."
    if vol["refusal"] == vials.TOO_LARGE:
        return "Over sixty mils, an infusion. No volume."
    if vol["status"] == vials.NEEDS_CONFIRMATION:
        return "More than one signed vial, no volume."
    return NO_SIGNED_VIAL


def _recipe(d: dict) -> str:
    return (f"Dilute {words.mils(d['drug_ml'])} of {words.num(d['from_concentration_mg_ml'])} "
            f"in {words.mils(d['diluent_ml'])} of {d['diluent']}.")


def boot(bank_dir, log: Optional[Callable] = None, now: Optional[Callable] = None) -> Session:
    """A session, refused if the bank is. A refused session answers nothing else."""
    try:
        return Session(load_bank(bank_dir), log=log, now=now)
    except BankRefused as e:
        return Session(None, refused=str(e))


def jsonl_log(path) -> Callable:
    """Append-only JSON lines, flushed to disk per dose (rule 3)."""
    def write(record: dict) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return write
