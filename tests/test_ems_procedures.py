"""RSI and failed airway on the one drug list, the EMS set (owner decision, 2026-11-23):
"RSI and failed airway keep their signed step text. For each dose step, tell me whether a
signed EMS entry exists for that drug and indication, and what dose it gives compared with
the step. Change no doses. Steps with no EMS entry hold; list them for me."

A step's dose links to an EMS entry only when it is the same drug, indication and
population and gives the dose the step states; every other dose holds, with why, until the
owner rules. Pocket never computes a dose that disagrees with the step it has just read.
"""
import copy
import json
import pathlib

import pytest

from engine.bank import BANK_DIR, PFC_RETIRED, load_bank
from engine.procedures import ProceduresRefused, load_procedures
from engine.session import STEP_HELD, STEP_HELD_AFTER, boot

EMS_FILE = BANK_DIR / "procedures.json"
RAW = json.loads(EMS_FILE.read_text())
SIGNED = json.loads((PFC_RETIRED / "procedures.json").read_text())
# (procedure, step, drug) -> the EMS entry it gives, or None: held
LINKS = {("rsi", "6", "ketamine"): None,          # EMS-130: 200 mg fixed; the step: 2 mg/kg
         ("rsi", "6b", "rocuronium"): None,       # EMS-201: 100 mg fixed; the step: 1.2 mg/kg
         ("rsi", "6b", "succinylcholine"): None,  # not in the EMS set
         ("rsi", "P2", "atropine"): None,         # no EMS RSI pre-dose entry
         ("rsi", "P3", "ketamine"): "EMS-135",    # 2 mg/kg, as the step
         ("rsi", "P4", "succinylcholine"): None,  # not in the EMS set (two refs: under 5, 5 and above)
         ("rsi", "P4", "rocuronium"): None}       # no EMS child RSI entry


def _steps(raw):
    return {(p["name"], s["id"]): s for p in raw["procedures"] for s in p["steps"]}


def test_every_step_keeps_its_signed_text_order_and_branch():
    ems, signed = _steps(RAW), _steps(SIGNED)
    assert {k: s["text"] for k, s in ems.items()} == {k: s["text"] for k, s in signed.items()}
    for a, b in zip(RAW["procedures"], SIGNED["procedures"]):
        for key in ("name", "title", "source", "page", "signer", "date", "order", "child_under", "branch"):
            assert a.get(key) == b.get(key), key
    assert RAW["doses_relinked"]["date"] == "2026-11-23"


def test_each_dose_is_linked_or_held_as_ruled_and_remembers_what_it_was():
    seen = {}
    for (proc, sid), s in _steps(RAW).items():
        old = _steps(SIGNED)[(proc, sid)].get("doses") or []
        assert [d["was"] for d in s.get("doses") or []] == old
        for d in s.get("doses") or []:
            seen[(proc, sid, d["drug"])] = d.get("ems_id")
            assert ("held" in d) != ("ems_id" in d)
    assert seen == LINKS


def test_the_one_linked_dose_gives_the_dose_the_step_states():
    bank = load_bank(BANK_DIR)
    e = next(x for x in bank.entries if x.get("ems_id") == "EMS-135")
    assert (e["drug"], e["indication_class"], e["population"]) == ("ketamine", "RSI", "peds")
    assert e["rule"] == {"max": 2.0, "min": 2.0, "per_kg": True, "units": "mg/kg"}
    assert "2mg/kg" in _steps(RAW)[("rsi", "P3")]["text"].replace(" ", "")


def _walk(*said):
    s = boot()
    for line in said:
        t = s.handle(line)
    return t


def test_the_adult_dose_steps_read_their_text_then_say_what_holds():
    t = _walk("rsi eighty kilos", *["next"] * 5)
    assert "Ketamine (First Line): two milligrams per kilogram" in t.say
    assert t.after == [STEP_HELD_AFTER.format(names="ketamine")]
    assert _walk("rsi eighty kilos", *["next"] * 5, "ketamine").say == STEP_HELD.format(name="ketamine")
    t = _walk("rsi eighty kilos", *["next"] * 6)
    assert t.after == ["No signed dose at this step for rocuronium and succinylcholine."]
    for drug in ("rocuronium", "succinylcholine"):
        held = _walk("rsi eighty kilos", *["next"] * 6, drug)
        assert (held.kind, held.say) == ("hold", f"No signed dose of {drug} for this step.")


def test_the_childs_ketamine_step_gives_the_ems_dose_and_the_rest_hold():
    t = _walk("rsi child twenty kilos", *["next"] * 6)
    assert t.after == ["No signed dose at this step for atropine."]
    t = _walk("rsi child twenty kilos", *["next"] * 7)
    assert t.after == ["For the dose, say ketamine."]
    assert _walk("rsi child twenty kilos", *["next"] * 7, "ketamine").say == "Ketamine, RSI, eye vee, child, twenty kilos. Confirm?"
    dose = _walk("rsi child twenty kilos", *["next"] * 7, "ketamine", "confirm")
    assert dose.kind == "dose" and dose.say.startswith("Ketamine forty milligrams.")     # 2 mg/kg x 20 kg
    t = _walk("rsi child twenty kilos", *["next"] * 8)
    assert t.after == ["No signed dose at this step for succinylcholine and rocuronium."]


def test_failed_airway_is_unchanged():
    t = _walk("failed airway")
    assert t.kind == "step" and "Unable to Intubate" in t.say


def _load(tmp_path, mutate):
    import shutil
    d = tmp_path / "b"
    shutil.copytree(BANK_DIR, d)
    raw = copy.deepcopy(RAW)
    mutate(raw)
    (d / "procedures.json").write_text(json.dumps(raw))
    return load_procedures(d)


def _p6(raw):
    return next(s for p in raw["procedures"] for s in p["steps"] if s["id"] == "6")


@pytest.mark.parametrize("mutate, why", [
    (lambda r: _p6(r)["doses"][0].update(held=""), "held dose needs its drug and why"),
    (lambda r: _p6(r)["doses"].__setitem__(0, {"drug": "ketamine", "ems_id": "EMS-201"}), "EMS-201 is not ketamine"),
    (lambda r: _p6(r)["doses"].__setitem__(0, {"drug": "ketamine", "ems_id": "EMS-999"}), "is not one signed entry"),
])
def test_a_dose_that_is_neither_one_signed_entry_nor_held_with_why_refuses_the_file(tmp_path, mutate, why):
    with pytest.raises(ProceduresRefused, match=why):
        _load(tmp_path, mutate)
