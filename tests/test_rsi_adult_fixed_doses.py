"""RSI steps 6 and 6b use the formulary's fixed doses (owner, 2026-11-23): "use the formulary
doses ... amend steps 6 and 6b to name the drug without the per-kg number and speak the
formulary's fixed dose. Rocuronium is the only paralytic; succinylcholine is not offered.
Mark both steps "amended by owner" with the date and keep the original JTS wording in the
record." Then: "EMS-130 and EMS-201 individually read. Signed: Andrew Azelton."
"""
import json

from engine.bank import BANK_DIR, PFC_RETIRED, load_bank
from engine.procedures import load_procedures
from engine.session import boot

RAW = json.loads((BANK_DIR / "procedures.json").read_text())
SIGNED = json.loads((PFC_RETIRED / "procedures.json").read_text())   # the JTS text as signed 2026-11-20


def _step(raw, sid):
    rsi = next(p for p in raw["procedures"] if p["name"] == "rsi")
    return next(s for s in rsi["steps"] if s["id"] == sid)


def _walk(*said):
    s = boot()
    for line in said:
        t = s.handle(line)
    return t


def test_both_entries_are_recorded_as_individually_read():
    bank = load_bank(BANK_DIR)
    for eid in ("EMS-130", "EMS-201"):
        e = next(x for x in bank.entries if x.get("ems_id") == eid)
        assert e["review"] == "individually read by owner", eid
        assert "2026-11-23" in e["review_note"] and "RSI 6 and 6b" in e["review_note"]


def test_the_steps_name_the_drug_without_the_per_kg_number():
    assert _step(RAW, "6")["text"] == (
        "Administer medications: Initiate RSI. ALWAYS SEDATE PRIOR TO PARALYZING. Sedative/hypnotic: "
        "Ketamine (First Line) IV/IO. Unstable patients require reduced dosage of induction agent.")
    assert _step(RAW, "6b")["text"] == "Neuromuscular Blockade: Rocuronium IV/IO"
    for sid in ("6", "6b"):
        assert "mg/kg" not in _step(RAW, sid)["text"] and "uccinylcholine" not in _step(RAW, sid)["text"]


def test_both_steps_are_marked_amended_by_owner_and_keep_the_jts_wording():
    for sid in ("6", "6b"):
        s, signed = _step(RAW, sid), _step(SIGNED, sid)
        assert s["signed"] == "amended by owner, 2026-11-23"
        assert s["amended"]["by"] == "owner" and s["amended"]["date"] == "2026-11-23"
        assert s["original_text"] == signed["text"]
        assert s["original_signed"].startswith("amended: unsigned drugs")
        assert [d["was"] for d in s["original_doses"]] == signed["doses"]
    assert "2 mg/kg" in _step(RAW, "6")["original_text"]
    assert "Succinylcholine: 1.5 mg/kg" in _step(RAW, "6b")["original_text"]
    assert any(a["date"] == "2026-11-23" and "6 and 6b" in a["what"] for a in RAW["amended"])


def test_the_steps_link_to_the_two_entries_and_nothing_holds():
    rsi = load_procedures(BANK_DIR, load_bank(BANK_DIR))["rsi"]
    assert [e["ems_id"] for e in rsi.steps["6"].doses] == ["EMS-130"] and not rsi.steps["6"].held
    assert [e["ems_id"] for e in rsi.steps["6b"].doses] == ["EMS-201"] and not rsi.steps["6b"].held


def test_step_six_says_the_fixed_ketamine_dose():
    t = _walk("rsi eighty kilos", *["next"] * 5)
    assert "Ketamine (First Line) eye vee or eye oh." in t.say and "per kilogram" not in t.say
    assert t.after == ["For the dose, say ketamine."]
    assert _walk("rsi eighty kilos", *["next"] * 5, "ketamine").say == "Ketamine, RSI, eye vee, eighty kilos. Confirm?"
    for kg in ("sixty", "eighty", "one hundred twenty"):
        dose = _walk(f"rsi {kg} kilos", *["next"] * 5, "ketamine", "confirm")
        assert dose.kind == "dose" and dose.say.startswith("Ketamine two hundred milligrams. Two mils"), (kg, dose.say)


def test_step_six_b_says_the_fixed_rocuronium_dose_and_offers_no_succinylcholine():
    t = _walk("rsi eighty kilos", *["next"] * 6)
    assert t.say.endswith("Neuromuscular Blockade: Rocuronium eye vee or eye oh.")
    assert t.after == ["For the dose, say rocuronium."]
    for kg in ("sixty", "eighty", "one hundred twenty"):
        dose = _walk(f"rsi {kg} kilos", *["next"] * 6, "rocuronium", "confirm")
        assert dose.kind == "dose" and dose.say.startswith("Rocuronium one hundred milligrams. Ten mils"), (kg, dose.say)
    held = _walk("rsi eighty kilos", *["next"] * 6, "succinylcholine")
    assert held.kind == "hold" and "milligram" not in held.say
