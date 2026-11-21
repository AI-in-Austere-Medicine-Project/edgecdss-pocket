"""Signed procedure steps (owner, 2026-11-20): bank/procedures.json, or nothing.

Only signed entries speak. A procedure loads only when it is wholly signed: a named
signer and a date; every step it orders exists and has text; every dose a step names is
exactly one signed entry in the loaded bank (drug, indication, population). Anything
else refuses the whole file, and every procedure then holds ("No signed steps for ...").
A test bank (POCKET_TEST=1) never loads steps: no RSI step is signed for it (Q9).

Steps are read as signed, one at a time. A step with doses names its signed drugs; the
medic says which, and that one entry is read back and confirmed like any other dose (Q5).

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

    @property
    def drugs(self) -> list:
        return list(dict.fromkeys(e["drug"] for e in self.doses))


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

    @property
    def needs_weight(self) -> bool:
        return any(s.doses for s in self.steps.values())

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
    hits = [e for e in bank.entries if e["drug"] == ref.get("drug")
            and e["indication"] == ref.get("indication") and e["population"] == ref.get("population")]
    if len(hits) != 1:
        raise ProceduresRefused(f"{where}: {ref.get('drug')} is not one signed entry")
    return hits[0]


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
        doses = tuple(_entry(bank, d, f"{name} step {s['id']}") for d in s.get("doses") or [])
        steps[s["id"]] = Step(s["id"], text, doses)
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
    return Procedure(name, str(raw.get("title") or name), raw["source"], raw["page"],
                     raw["signer"], raw["date"], {k: list(v) for k, v in order.items()},
                     steps, dict(cu), dict(branch))


def load_procedures(bank_dir, bank=None) -> dict:
    """{name: Procedure}; raises ProceduresRefused. No file: no procedures."""
    from engine.bank import load_bank
    bank = bank if bank is not None else load_bank(bank_dir)
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
