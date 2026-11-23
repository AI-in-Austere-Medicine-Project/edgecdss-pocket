"""Owner rule, 2026-11-23, the whole EMS list: "Pocket ignores provider levels (PL) and
online medical control (OLMC). It never gates a dose on them and never says them. If a
drug is in the formulary, it is in the system. Record this as an owner rule with the
date, and remove any hold or spoken text that comes from a PL or OLMC note. Weight floors
from the dose tables stay."

The signed text keeps every PL and OLMC note, for the record; Pocket does not say them.
"""
import json
import pathlib
import re

import pytest

from engine.bank import BANK_DIR, load_bank
from engine.session import boot, caution_lines, why_text, without_pl_olmc

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = load_bank(BANK_DIR)
PL_OLMC = re.compile(r"\bPL\s?\d|\bPLs?\b|OLMC|provider level|medical control|integrated services|ALS providers", re.I)
ITEMS = json.loads((BANK_DIR / "bank.json").read_text())


def test_pocket_never_says_a_provider_level_or_olmc():
    for e in BANK.entries:
        for volume in (True, False):
            for line in caution_lines(e, volume) + [why_text(e)]:
                assert not PL_OLMC.search(line), (e["ems_id"], line)


def test_the_conditions_path_says_none_either():
    for e in BANK.entries:
        for line in caution_lines(e, True, conditions=["hypovolaemia", "burns", "asthma", "head injury", "hypertension"]):
            assert not PL_OLMC.search(line), (e["ems_id"], line)


@pytest.mark.parametrize("signed,said", [
    ("Provider level: PL5–PL6.", None),
    ("Provider level: PL6; PL5 if advanced airway established.", None),
    ("Provider level: ≥PL7 only.", None),
    ("Provider level: ALS providers.", None),
    ("OLMC required.", None),
    ("OLMC for higher dosing.", None),
    ("OLMC for higher dosing if synthetics suspected (10–20 mg per dose).", None),
    ("Repeat: OLMC for repeat doses.", None),
    ("Repeat: OLMC for repeat IM doses.", None),
    ("Infusion over 10 min; OLMC required.", "Infusion over 10 min."),
    ("Slow IV/IO over 3 min; OLMC required.", "Slow IV/IO over 3 min."),
    ("In 100 cc over 20 min at 150 gtt/min; Consult OLMC.", "In 100 cc over 20 min at 150 gtt/min."),
    ("Repeat: 15 min after the 1st, OLMC required.", "Repeat: 15 min after the 1st."),
    ("Repeat: x1 with 0.63 mg (0.25 mL) at 10 min; OLMC for further doses.",
     "Repeat: x1 with 0.63 mg (0.25 mL) at 10 min."),
    ("OLMC required; ≥3 months.", "≥3 months."),
    ("hypovolemic shock from hemorrhage except for OLMC approval", "hypovolemic shock from hemorrhage"),
    ("Repeat: IM every 30 min, to pain relief or nystagmus.", "Repeat: IM every 30 min, to pain relief or nystagmus."),
    ("Anaphylaxis ALS PROVIDERS", "Anaphylaxis"),
])
def test_only_the_pl_or_olmc_part_of_a_line_is_left_out(signed, said):
    assert without_pl_olmc(signed) == said


def test_the_signed_text_still_carries_the_notes():
    texts = [c for e in ITEMS["entries"] for c in e["serve_cautions"] + e["contraindications"]]
    assert sum(bool(PL_OLMC.search(t)) for t in texts) > 150


def test_no_entry_is_held_or_left_out_for_a_pl_or_olmc_note():
    """Every formulary entry is in the bank (206). The one signed-silent entry that names
    OLMC is silent because its row prints no dose ("Contact OLMC"), not because of OLMC."""
    ids = {e["ems_id"] for e in ITEMS["entries"]} | {s["ems_id"] for s in ITEMS["signed_silent"]}
    assert len(ids) == 206
    for s in ITEMS["signed_silent"]:
        for why in s["silent_because"]:
            if PL_OLMC.search(why):
                assert s["ems_id"] == "EMS-183" and "is not one amount" in why, (s["ems_id"], why)


def test_norepinephrine_is_still_contraindicated_in_hemorrhagic_shock_without_the_olmc_exception():
    e = next(x for x in BANK.entries if x["ems_id"] == "EMS-181")
    lines = caution_lines(e, True)
    assert any("hypovolemic shock from hemorrhage" in l and l.startswith("Contraindicated:") for l in lines), lines
    assert not any("OLMC" in l or "except" in l for l in lines)


def test_an_indication_is_said_without_its_provider_group():
    s = boot()
    s.handle("epinephrine for anaphylaxis im child twenty kilos")
    t = s.handle("why")
    assert "PROVIDERS" not in t.say.upper() and "Quote: Anaphylaxis | 0.01 mg/kg" in t.say
    from engine.session import said_indication
    assert said_indication("Anaphylaxis — ALS providers (infusion)") == "Anaphylaxis (infusion)"
    assert said_indication("Anaphylaxis — BLS providers") == "Anaphylaxis"


def test_the_weight_floors_from_the_dose_tables_stay():
    assert sorted(e["ems_id"] for e in BANK.entries if e.get("min_weight")) == [
        "EMS-004", "EMS-062", "EMS-063", "EMS-064", "EMS-065", "EMS-086", "EMS-131", "EMS-134",
        "EMS-165", "EMS-166", "EMS-167", "EMS-168", "EMS-190", "EMS-191"]


def test_the_rule_is_recorded_with_its_date():
    rules = (ROOT / "docs" / "WORK_ORDER.md").read_text().split("## Log")[0]
    assert "(owner, 2026-11-23)" in rules and "provider levels (PL)" in rules
    assert "online medical control (OLMC)" in rules
