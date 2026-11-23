"""Signed procedure steps (owner, 2026-11-20): bank/procedures.json, or nothing.

Only signed entries speak. A procedure loads only when it is wholly signed: a named
signer and a date; every step it orders exists and has text; every dose a step names is
exactly one signed entry in the loaded bank (drug, indication, population). Anything
else refuses the whole file, and every procedure then holds ("No signed steps for ...").
A test bank (POCKET_TEST=1) never loads steps: no RSI step is signed for it (Q9).

Steps are read as signed, one at a time. A step with doses names its signed drugs; the
medic says which, and that one entry is read back and confirmed like any other dose (Q5).

One drug list, the EMS set (owner, 2026-11-23): "RSI and failed airway keep their signed
step text ... Change no doses. Steps with no EMS entry hold." A dose a step names is
either linked to one signed entry ({"ems_id": ...}, or drug, indication and population)
or held ({"drug": ..., "held": why}). A held dose is named after the step ("No signed
dose at this step for ..."), and asking for it at the step holds; it is never computed.

A procedure may end on a question (owner, 2026-11-21: failed airway asks "Can you mask
ventilate?"): `branch` is {"ask", "yes", "no"}. The question must be words of a signed
step; "yes" and "no" each name one signed step, read only on that answer.
"""
import dataclasses
import json
import pathlib

PROCEDURE_SIGNERS = ("Andrew Azelton",)
FILE = "procedures.json"


class ProceduresRefused(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Step:
    id: str
    text: str
    doses: tuple            # bank entries, in the order the step names them
    held: tuple = ()        # (drug, why): doses the step names with no signed entry to give

    @property
    def drugs(self) -> list:
        return list(dict.fromkeys(e["drug"] for e in self.doses))

    @property
    def held_drugs(self) -> list:
        return [d for d in dict.fromkeys(h[0] for h in self.held) if d not in self.drugs]


@dataclasses.dataclass(frozen=True)
class Procedure:
    name: str
    title: str
    source: str
    page: int
    signer: str
    date: str
    order: dict             # "adult" | "child" -> [step id]
    steps: dict             # step id -> Step
    child_under: dict       # {"years", "replace", "with"} or {}
    branch: dict = dataclasses.field(default_factory=dict)   # {"ask", "yes", "no"} or {}
    child_held: str = ""    # said instead of any step for a child (owner, 2026-11-23); "" reads the child order

    @property
    def needs_weight(self) -> bool:
        return any(s.doses or s.held for s in self.steps.values())

    def for_patient(self, child: bool, years) -> list:
        """The steps for this patient, in the signed order. For a child under
        child_under["years"] (or of unknown age), one step is replaced (Q3: P5 replaces
        only the surgical airway line)."""
        return [self.steps[i] for i in self._for(self.order["child" if child else "adult"], child, years)]

    def answer(self, said: str, child: bool, years) -> Step:
        """The branch step for "yes" or "no", with the same child replacement."""
        return self.steps[self._for([self.branch[said]], child, years)[0]]

    def _for(self, ids, child, years) -> list:
        cu = self.child_under
        if cu and child and (years is None or years < cu["years"]):
            return [cu["with"] if i == cu["replace"] else i for i in ids]
        return list(ids)


def _entry(bank, ref: dict, where: str) -> dict:
    if "ems_id" in ref:
        hits = [e for e in bank.entries if e.get("ems_id") == ref["ems_id"]]
        if len(hits) == 1 and ref.get("drug") not in (None, hits[0]["drug"]):
            raise ProceduresRefused(f"{where}: {ref['ems_id']} is not {ref.get('drug')}")
    else:
        hits = [e for e in bank.entries if e["drug"] == ref.get("drug")
                and e["indication"] == ref.get("indication") and e["population"] == ref.get("population")]
    if len(hits) != 1:
        raise ProceduresRefused(f"{where}: {ref.get('ems_id') or ref.get('drug')} is not one signed entry")
    return hits[0]


def _held(ref: dict, where: str) -> tuple:
    drug, why = str(ref.get("drug") or "").strip(), str(ref.get("held") or "").strip()
    if not drug or not why:
        raise ProceduresRefused(f"{where}: a held dose needs its drug and why")
    return (drug, why)


def _procedure(raw: dict, bank) -> Procedure:
    name = str(raw.get("name") or "")
    if str(raw.get("signer") or "").strip() not in PROCEDURE_SIGNERS:
        raise ProceduresRefused(f"{name}: not signed by name")
    if not str(raw.get("date") or "").strip():
        raise ProceduresRefused(f"{name}: no signature date")
    if not str(raw.get("source") or "").strip() or not raw.get("page"):
        raise ProceduresRefused(f"{name}: no source")
    steps = {}
    for s in raw.get("steps") or []:
        text = str(s.get("text") or "").strip()
        if not text:
            raise ProceduresRefused(f"{name} step {s.get('id')}: no text")
        where = f"{name} step {s['id']}"
        refs = s.get("doses") or []
        doses = tuple(_entry(bank, d, where) for d in refs if "held" not in d)
        held = tuple(_held(d, where) for d in refs if "held" in d)
        steps[s["id"]] = Step(s["id"], text, doses, held)
    order = raw.get("order") or {}
    if set(order) != {"adult", "child"}:
        raise ProceduresRefused(f"{name}: no adult and child order")
    cu = raw.get("child_under") or {}
    branch = raw.get("branch") or {}
    if branch:
        if set(branch) != {"ask", "yes", "no"}:
            raise ProceduresRefused(f"{name}: a branch needs a question, yes and no")
        ask = str(branch["ask"]).strip().lower()
        if not ask or not any(ask in s.text.lower() for s in steps.values()):
            raise ProceduresRefused(f"{name}: the question is not signed text")
    used = ([i for ids in order.values() for i in ids] + ([cu["replace"], cu["with"]] if cu else [])
            + ([branch["yes"], branch["no"]] if branch else []))
    for i in used:
        if i not in steps:
            raise ProceduresRefused(f"{name}: step {i} is not signed")
    held = raw.get("child_held")
    if held is not None and not all(str(held.get(k) or "").strip() for k in ("say", "by", "date", "why")):
        raise ProceduresRefused(f"{name}: a child hold needs its line, the owner, a date and why")
    return Procedure(name, str(raw.get("title") or name), raw["source"], raw["page"],
                     raw["signer"], raw["date"], {k: list(v) for k, v in order.items()},
                     steps, dict(cu), dict(branch), str(held["say"]).strip() if held else "")


def load_procedures(bank_dir, bank=None, retired_ok=False) -> dict:
    """{name: Procedure}; raises ProceduresRefused. No file: no procedures."""
    from engine.bank import load_bank
    bank = bank if bank is not None else load_bank(bank_dir, retired_ok=retired_ok)
    path = pathlib.Path(bank_dir) / FILE
    if bank.test or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except ValueError:
        raise ProceduresRefused(f"{FILE} is unreadable") from None
    procs = {}
    for p in raw.get("procedures") or []:
        proc = _procedure(p, bank)
        procs[proc.name] = proc
    return procs
