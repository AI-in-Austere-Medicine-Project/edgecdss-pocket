"""The RSI step reader (owner, 2026-11-20).

The owner signed the RSI steps from the 2026-11-20 packet (ID39 p.28):
  SIGN: steps 1-5, 7, 8, 9, P2, P4, P5, FA.
  SIGN with amendment: 6, 6b, P3: unsigned drugs (etomidate, vecuronium) are not spoken.
    P1: "Have a dedicated pediatric airway cart, including Broselow tape or equivalent."
    10: text as written, no dose computed.
  STRIKE: PT (pretreat).
  Q2 ask weight once at the start; do not ask access. Q3 P2 before 6, P3/P4 replace 6/6b
  for a child, P5 replaces only the surgical airway line. Q4 (a) as written, no dose.
  Q5 the step names the signed options, the medic says which, it computes that one and
  reads it back. Q6 neither. Q7 its own procedure, called by "failed airway". Q8 no.
  Q9 confirmed (no EMS RSI). Q10 confirmed.
Roadmap section 3: read one step at a time with "next", "back" and "repeat", each dose
computed for the patient at its step.
"""
import json
import pathlib
import shutil

import pytest

from engine.procedures import ProceduresRefused, load_procedures
from engine.session import boot

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = ROOT / "bank"

# The signed text, word for word (the packet, with the owner's amendments).
SIGNED = {
    "1": "Confirm equipment availability and function: Suction, oxygen source, self-inflating bag and mask, oral & nasal airways, ETT with stylet and/or bougie, supraglottic airway, surgical airway kit, drugs, monitors, ventilator, laryngoscope- direct and video, CO2 detector.",
    "2": "Pre-Oxygenate (Denitrogenate) the lungs. Prolongs tolerance of apneic period. Goal is ≈ 3 minutes of tidal volume breathing at 90% FiO2. With standard reservoir facemask set flow rate of oxygen as high as possible. Recommend augmenting with nasal cannula at 15L/min oxygen in preparation for apneic oxygenation, leave in situ throughout procedure. Elevate head of bed if not contraindicated.",
    "3": "Maintain cervical spine stabilization",
    "4": "Remove front of cervical collar",
    "5": "Consider cricoid pressure simultaneous w/ medication administration",
    "6": "Administer medications: Initiate RSI. ALWAYS SEDATE PRIOR TO PARALYZING. Sedative/hypnotic: Ketamine (First Line): 2 mg/kg IV/IO. Unstable patients require reduced dosage of induction agent.",
    "6b": "Neuromuscular Blockade: Rocuronium: 1.2 mg/kg IV/IO or Succinylcholine: 1.5 mg/kg IV/IO",
    "7": "Perform laryngoscopic tracheal intubation. Following onset of neuromuscular blockade. Recommend gum elastic bougie as primary ETT stylet",
    "8": "If laryngoscopic view is poor: Apply external laryngeal manipulation technique(s). Consider alternative visualization method or Supraglottic airway device",
    "9": "Confirm tracheal intubation: Visualize tube passing between the vocal cords. Easy chest rise, equal axillary breath sounds/absence of gastric insufflation, CO2 Calorimeter, and \"fog\" in ETT. Wave form or digital capnography",
    "10": "Provide continuing care IAW JTS Anesthesia for Trauma Patients CPG",
    "P1": "Have a dedicated pediatric airway cart, including Broselow tape or equivalent.",
    "P2": "Pre-dose with atropine IV/IO (0.02mg/kg, minimum dose 0.1mg, maximum dose 0.5mg) in all <1 years old, those <5 who are receiving succinylcholine, and in all who receive a 2nd dose of succinylcholine",
    "P3": "Induction - Ketamine (first line) 2mg/kg IV/IO.",
    "P4": "Neuromuscular blockade - Succinylcholine 1.5mg/kg IV/IO (2mg/kg <5 years old) or Rocuronium 1mg/kg IV/IO",
    "P5": "Avoid surgical airway in <12 years old - use needle cricothyroidotomy (12-14 gauge), tracheostomy preferred over surgical cricothyroidotomy",
}
FA = ("Unable to Intubate: Can You Mask Ventilate? Improve position, video laryngoscope, gum "
      "elastic bougie change blade/operator. More than ≈ 3 attempts at intubation may abolish "
      "your ability to mask ventilate due to edema caused by laryngoscopy. YES → Surgical airway "
      "(Cricothyroidotomy or tracheostomy). NO → Emergency pathway. Seconds matter. Supraglottic "
      "airway or Surgical cricothyroidotomy.")
ADULT = ["1", "2", "3", "4", "5", "6", "6b", "7", "8", "9", "10"]
CHILD = ["1", "P1", "2", "3", "4", "5", "P2", "P3", "P4", "7", "8", "9", "10"]


def _file():
    return json.loads((BANK / "procedures.json").read_text())


def _steps(name):
    proc = next(p for p in _file()["procedures"] if p["name"] == name)
    return proc, {s["id"]: s for s in proc["steps"]}


def play(s, *phrases):
    return [s.handle(p) for p in phrases]


def _to_step(s, step_id, order, start="rsi eighty kilos"):
    turn = s.handle(start)
    for _ in range(order.index(step_id)):
        turn = s.handle("next")
    return turn


# ── the signed file ─────────────────────────────────────────────────────────

def test_the_signed_rsi_text_is_word_for_word_what_the_owner_signed():
    proc, steps = _steps("rsi")
    assert {k: v["text"] for k, v in steps.items()} == {k: SIGNED[k] for k in ADULT + ["P1", "P2", "P3", "P4"]}
    assert proc["order"] == {"adult": ADULT, "child": CHILD}
    assert (proc["signer"], proc["date"], proc["page"]) == ("Andrew Azelton", "2026-11-20", 28)


def test_the_failed_airway_lines_are_the_signed_fa_text_and_p5():
    proc, steps = _steps("failed airway")
    assert " ".join(steps[i]["text"] for i in proc["order"]["adult"]) == FA
    assert steps["P5"]["text"] == SIGNED["P5"]
    assert proc["child_under"] == {"years": 12, "replace": "FA3", "with": "P5"}
    assert steps["FA3"]["text"].startswith("YES → Surgical airway")


def test_unsigned_drugs_and_the_struck_pretreat_step_are_never_spoken():
    text = json.dumps([s["text"] for p in _file()["procedures"] for s in p["steps"]]).lower()
    for word in ("etomidate", "vecuronium", "fentanyl", "pretreat"):
        assert word not in text
    assert all(s["id"] != "PT" for p in _file()["procedures"] for s in p["steps"])


def test_only_steps_6_6b_p2_p3_p4_compute_a_dose_and_step_10_does_not():
    _, steps = _steps("rsi")
    assert {k for k, v in steps.items() if v.get("doses")} == {"6", "6b", "P2", "P3", "P4"}


def test_every_dose_a_step_names_is_one_signed_bank_entry():
    procs = load_procedures(BANK)
    bank = json.loads((BANK / "bank.json").read_text())["entries"]
    for proc in procs.values():
        for step in proc.steps.values():
            for d in step.doses:
                assert d in bank and d["signoff"] is True


# ── refusals: an unsigned procedure holds ───────────────────────────────────

def _copy_bank(tmp_path, edit):
    d = tmp_path / "bank"
    shutil.copytree(BANK, d)
    data = json.loads((d / "procedures.json").read_text())
    edit(data)
    (d / "procedures.json").write_text(json.dumps(data))
    return d


@pytest.mark.parametrize("edit", [
    lambda d: d["procedures"][0].update(signer="clinician"),
    lambda d: d["procedures"][0].update(date=""),
    lambda d: d["procedures"][0]["steps"][5]["doses"][0].update(indication="RSI induction (second line)"),
    lambda d: d["procedures"][0]["steps"][5]["doses"][0].update(drug="etomidate"),
    lambda d: d["procedures"][0]["order"]["adult"].append("11"),
    lambda d: d["procedures"][0]["steps"][2].update(text=""),
], ids=["role-not-a-name", "no-date", "entry-not-in-bank", "unsigned-drug", "unknown-step", "empty-step"])
def test_a_procedure_that_is_not_wholly_signed_is_refused_and_rsi_holds(tmp_path, edit):
    d = _copy_bank(tmp_path, edit)
    with pytest.raises(ProceduresRefused):
        load_procedures(d)
    s = boot(d)
    turn = s.handle("rsi eighty kilos")
    assert turn.kind == "hold" and turn.text == "No signed steps for rapid sequence intubation."


def test_with_no_step_file_rsi_holds(tmp_path):
    d = tmp_path / "bank"
    shutil.copytree(BANK, d)
    (d / "procedures.json").unlink()
    assert boot(d).handle("rsi eighty kilos").kind == "hold"


def test_the_ems_test_bank_has_no_rsi_steps(tmp_path, monkeypatch):
    from tests.test_test_bank import make_test_bank
    d = make_test_bank(tmp_path)
    shutil.copy(BANK / "procedures.json", d / "procedures.json")
    monkeypatch.setenv("POCKET_TEST", "1")
    s = boot(d)
    assert s.handle("rsi eighty kilos").text == "No signed steps for rapid sequence intubation."


# ── reading the steps ───────────────────────────────────────────────────────

def test_rsi_asks_the_weight_once_at_the_start_and_never_the_access():
    s = boot(BANK)
    first = s.handle("rsi")
    assert (first.kind, first.text) == ("ask", "Weight?")
    turns = [s.handle("eighty kilos")] + play(s, *["next"] * 5, "ketamine", "confirm",
                                               "next", "rocuronium", "confirm", *["next"] * 4)
    assert all(t.text != "Weight?" for t in turns)
    assert not any("access" in t.text.lower() for t in [first, *turns])


def test_the_adult_steps_are_read_in_the_signed_order_written_as_signed():
    s = boot(BANK)
    turn = s.handle("rsi eighty kilos")
    assert turn.kind == "step"
    assert turn.written.startswith("Rapid sequence intubation, adult, eighty kilos. Step one of eleven.")
    seen = [turn]
    for _ in ADULT[1:]:
        seen.append(s.handle("next"))
    for step_id, t in zip(ADULT, seen):
        assert t.kind == "step" and SIGNED[step_id] in t.written, step_id
    end = s.handle("next")
    assert end.kind == "step" and end.text == "End of rapid sequence intubation steps."
    assert s.handle("next").text == "No steps running."


def test_the_child_steps_replace_6_and_6b_and_put_p1_and_p2_in_place():
    s = boot(BANK)
    turn = s.handle("rsi child twenty kilos")
    assert turn.written.startswith("Rapid sequence intubation, child, twenty kilos. Step one of thirteen.")
    seen = [turn] + [s.handle("next") for _ in CHILD[1:]]
    for step_id, t in zip(CHILD, seen):
        assert SIGNED[step_id] in t.written, step_id
    assert not any(SIGNED["6"] in t.written or SIGNED["6b"] in t.written for t in seen)


def test_next_back_and_repeat_move_and_repeat_one_step():
    s = boot(BANK)
    s.handle("rsi eighty kilos")
    two = s.handle("next")
    assert SIGNED["2"] in two.written
    assert s.handle("repeat").written == two.written
    back = s.handle("back")
    assert SIGNED["1"] in back.written and "Step one of eleven." in back.written
    assert s.handle("back").text == "First step."
    assert SIGNED["2"] in s.handle("next").written


def test_the_spoken_form_says_the_symbols_and_routes_and_the_written_keeps_them():
    s = boot(BANK)
    s.handle("rsi eighty kilos")
    two = s.handle("next")
    assert "≈ 3 minutes" in two.written and "about three minutes" in two.text and "≈" not in two.text
    six = _to_step(boot(BANK), "6", ADULT)
    assert "2 mg/kg IV/IO" in six.written
    assert "eye vee or eye oh" in six.text and "IV/IO" not in six.text


# ── a dose at its step (Q5) ─────────────────────────────────────────────────

def test_step_6_names_ketamine_and_computes_only_the_signed_id39_dose():
    s = boot(BANK)
    six = _to_step(s, "6", ADULT)
    assert six.after == ["For the dose, say ketamine."]
    rb = s.handle("ketamine")
    assert rb.kind == "readback" and rb.text.startswith("Ketamine, RSI induction, eye vee, eighty kilos.")
    dose = s.handle("confirm")
    assert dose.kind == "dose" and dose.text.startswith("Ketamine one hundred and sixty milligrams.")
    assert dose.data["record"]["indication"] == "RSI induction"


@pytest.mark.parametrize("drug,said", [("rocuronium", "Rocuronium ninety-six milligrams."),
                                       ("succinylcholine", "Succinylcholine one hundred and twenty milligrams.")])
def test_step_6b_names_both_signed_paralytics_and_computes_the_one_said(drug, said):
    s = boot(BANK)
    sixb = _to_step(s, "6b", ADULT)
    assert sixb.after == ["For the dose, say rocuronium or succinylcholine."]
    assert s.handle(drug).kind == "readback"
    dose = s.handle("confirm")
    assert dose.text.startswith(said)
    assert dose.data["record"]["indication"] == "RSI paralytic"


def test_a_dose_is_never_spoken_without_its_read_back_and_confirm():
    s = boot(BANK)
    _to_step(s, "6", ADULT)
    assert s.handle("ketamine").kind == "readback"
    assert s.handle("next").kind == "ask"          # a miss, not the next step
    assert s.handle("next").text == "Cancelled."
    assert s.records == []


def test_after_a_dose_next_goes_on_to_the_next_step():
    s = boot(BANK)
    _to_step(s, "6", ADULT)
    play(s, "ketamine", "confirm")
    assert SIGNED["6b"] in s.handle("next").written


def test_step_10_and_the_other_steps_offer_no_dose():
    s = boot(BANK)
    turns = [s.handle("rsi eighty kilos")] + [s.handle("next") for _ in ADULT[1:]]
    for step_id, t in zip(ADULT, turns):
        if step_id not in ("6", "6b"):
            assert t.after == [], step_id


def test_child_atropine_ketamine_and_succinylcholine_by_age_band():
    s = boot(BANK)
    p2 = _to_step(s, "P2", CHILD, "rsi child twenty kilos")
    assert p2.after == ["For the dose, say atropine."]
    play(s, "atropine")
    assert s.handle("confirm").text.startswith("Atropine zero point four milligrams.")
    p3 = s.handle("next")
    assert p3.after == ["For the dose, say ketamine."]
    play(s, "ketamine")
    assert s.handle("confirm").text.startswith("Ketamine forty milligrams.")
    p4 = s.handle("next")
    assert p4.after == ["For the dose, say succinylcholine or rocuronium."]
    assert s.handle("succinylcholine").text == "Age in years?"
    assert s.handle("three years").kind == "readback"
    dose = s.handle("confirm")
    assert dose.text.startswith("Succinylcholine forty milligrams.")
    assert dose.data["record"]["indication"] == "RSI paralytic — under 5 years"


def test_a_stated_contraindication_still_holds_the_dose_at_its_step():
    s = boot(BANK)
    _to_step(s, "6b", ADULT, "rsi eighty kilos burns")
    turn = s.handle("succinylcholine")
    assert turn.kind == "hold" and "contraindicated with burns" in turn.text


def test_cancel_ends_the_steps():
    s = boot(BANK)
    s.handle("rsi eighty kilos")
    assert s.handle("cancel").text == "Cancelled."
    assert s.handle("next").text == "No steps running."


def test_new_patient_ends_the_steps_and_clears_the_weight():
    s = boot(BANK)
    s.handle("rsi eighty kilos")
    s.handle("new patient")
    assert s.handle("next").text == "No steps running."
    assert s.handle("rsi").text == "Weight?"


def test_a_dose_asked_for_by_drug_and_indication_is_unchanged():
    s = boot(BANK)
    turn = s.handle("rocuronium for rsi eighty kilos")
    assert turn.kind == "readback"


# ── failed airway (Q7) ──────────────────────────────────────────────────────

def test_failed_airway_is_its_own_procedure_and_asks_no_weight():
    s = boot(BANK)
    turn = s.handle("failed airway")
    assert turn.kind == "step" and turn.written.startswith("Failed airway. Step one of four.")
    lines = [turn] + [s.handle("next") for _ in range(3)]
    proc, steps = _steps("failed airway")
    for t, step_id in zip(lines, proc["order"]["adult"]):
        assert t.written.endswith(steps[step_id]["text"]), step_id


@pytest.mark.parametrize("start,p5", [("failed airway child six years", True),
                                      ("failed airway child twenty kilos", True),
                                      ("failed airway child fourteen years", False),
                                      ("failed airway eighty kilos", False)])
def test_p5_replaces_only_the_surgical_airway_line_for_a_child_under_12(start, p5):
    s = boot(BANK)
    lines = [s.handle(start)] + [s.handle("next") for _ in range(3)]
    text = " ".join(t.written for t in lines)
    assert (SIGNED["P5"] in text) is p5
    assert ("YES → Surgical airway (Cricothyroidotomy or tracheostomy)." in text) is not p5
    assert "NO → Emergency pathway. Seconds matter." in text


# ── hearing the words ───────────────────────────────────────────────────────

def test_the_step_words_are_in_the_grammar():
    words = set(json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())["words"])
    for w in ("next", "back", "repeat", "failed", "airway", "r", "s", "i"):
        assert w in words, w


def test_say_step_writes_out_symbols_units_and_lone_numbers_only():
    from engine.words import say_step
    assert say_step("CO2 detector, 90% FiO2") == "CO2 detector, ninety percent FiO2."
    assert say_step("(12-14 gauge)") == "(twelve to fourteen gauge)."
    assert say_step("0.02mg/kg, <1 years, a 2nd dose") == ("zero point zero two milligrams per kilogram, "
                                                          "under one years, a second dose.")
    assert say_step("YES → Surgical airway.") == "YES, then Surgical airway."
