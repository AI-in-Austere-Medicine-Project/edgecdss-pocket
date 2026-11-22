"""Strengths declared by the owner (Andrew Azelton, 2026-11-22) as the standard product,
each recorded "owner-declared, industry standard, not read from kit", with the date.

Owner: "Liquids now give a volume. Tablets keep saying milligrams only unless you can
state the number of tablets safely; you decide." Tablets keep milligrams only: a count is
safe only for a fixed dose that is a whole number of tablets, and the formulary states no
rule for halving or rounding a range or a per-kg dose.

A vial may name the routes it serves (`routes`): acetaminophen has two liquids, the
1 g / 100 mL bag (IV) and the 160 mg / 5 mL oral liquid (PO), and neither serves the
other's route.
"""
import json
import pathlib

import pytest

from engine import vials as V
from engine.bank import BankRefused, load_bank
from engine.session import PINNED_VIAL, boot

EMS = pathlib.Path(__file__).resolve().parents[1] / "bank" / "ems"
KIT = json.loads((EMS / "kit.json").read_text())
ENTRIES = {e["ems_id"]: e for e in json.loads((EMS / "bank.json").read_text())["entries"]}
SILENT = {s["ems_id"]: s for s in json.loads((EMS / "bank.json").read_text())["signed_silent"]}
STANDARD = "owner-declared, industry standard, not read from kit"


def _vial(drug, label=None):
    vs = [v for v in KIT["vials"] if v["drug"] == drug and (label is None or label in v["label"])]
    assert len(vs) == 1, (drug, vs)
    return vs[0]


def _product(drug):
    ps = [p for p in KIT["declared_products"] if p["drug"] == drug]
    assert len(ps) == 1
    return ps[0]


def _dose(*lines):
    s = boot(EMS)
    for line in lines:
        t = s.handle(line)
    return t.say


def _declared(rec):
    assert rec["review"] == STANDARD and rec["signed_by"] == "Andrew Azelton" and rec["date"] == "2026-11-22"


def _volume(eid, dose_mg):
    kit = load_bank(EMS, test=False).kit
    return V.dose_volume(kit, ENTRIES[eid], dose_mg)["volume_ml"]


def test_nothing_is_left_to_declare():
    assert KIT["strengths_to_declare"] == []


def test_calcium_chloride_100_mg_per_ml_gives_its_volume():
    v = _vial("calcium chloride")
    _declared(v)
    assert v["concentration_mg_ml"] == 100.0 and "misprint" in v["note"]
    assert _dose("calcium chloride for hyperkalemia iv adult", "confirm").startswith(
        "Calcium chloride one gram. Ten mils of one gram per ten.")


def test_magnesium_sulfate_500_mg_per_ml_gives_its_volume():
    v = _vial("magnesium sulfate")
    _declared(v)
    assert v["concentration_mg_ml"] == 500.0 and "misprint" in v["note"]
    assert _volume("EMS-143", 2000.0) == 4.0                         # 2 g, the row's 4 mL
    assert _dose("magnesium sulfate for torsades iv twenty kilos", "confirm") == (
        "Magnesium sulfate one thousand milligrams. Two mils of five hundred per mil. Over five minutes.")


def test_pralidoxime_50_mg_per_ml_gives_the_vials_volume_not_the_auto_injectors():
    v = _vial("pralidoxime")
    _declared(v)
    assert v["concentration_mg_ml"] == 50.0 and "misprint" in v["note"] and v["routes"] == ["IM"]
    assert _volume("EMS-198", 600.0) == 12.0                          # the row's 12 mL
    assert _volume("EMS-199", 300.0) == 6.0                           # 15 mg/kg at 20 kg
    assert ENTRIES["EMS-197"]["kit_vial"] == "none"                   # the 600 mg auto-injector


def test_acetaminophen_oral_liquid_160_mg_in_5_ml_serves_the_childs_po_dose_only():
    v = _vial("acetaminophen", "oral liquid")
    _declared(v)
    assert v["concentration_mg_ml"] == 32.0 and v["routes"] == ["PO"]
    assert _vial("acetaminophen", "100 mL")["routes"] == ["IV"]
    assert _dose("acetaminophen for fever po twenty kilos", "confirm") == (
        "Acetaminophen three hundred milligrams. Nine point four mils of one sixty per five.")
    assert _dose("acetaminophen for fever iv twenty kilos", "confirm").startswith(
        "Acetaminophen three hundred milligrams. Thirty mils of one gram per one hundred.")        # the IV bag, not the liquid
    assert _dose("acetaminophen for fever po adult", "confirm").endswith(PINNED_VIAL)   # tablets


def test_albuterol_inhaler_90_mcg_per_puff_is_recorded_and_the_mdi_entry_stays_silent():
    p = _product("albuterol")
    _declared(p)
    assert p["strength"] == "90 mcg per puff" and "EMS-007" in SILENT


def test_olanzapine_5_mg_tablet_is_recorded_and_its_sl_entries_stay_silent():
    p = _product("olanzapine")
    _declared(p)
    assert (p["product"], p["strength"]) == ("tablet", "5 mg") and {"EMS-184", "EMS-185"} <= set(SILENT)


def test_diphenhydramine_25_mg_tablet_is_recorded_and_the_tablet_says_milligrams_only():
    p = _product("diphenhydramine")
    _declared(p)
    assert (p["product"], p["strength"]) == ("tablet", "25 mg") and "misprint" in p["note"]
    assert ENTRIES["EMS-055"]["kit_vial"] == "none"
    assert _dose("diphenhydramine for hives po adult", "confirm").endswith(PINNED_VIAL)


def test_nitroglycerin_2_percent_ointment_is_recorded_and_stays_silent():
    p = _product("nitroglycerin")
    _declared(p)
    assert (p["product"], p["strength"]) == ("ointment", "2%") and {"EMS-177", "EMS-179"} <= set(SILENT)


def test_a_vial_that_names_its_routes_serves_no_other_route():
    kit = {"x": [{"concentration_mg_ml": 10.0, "routes": ["IV"]}, {"concentration_mg_ml": 32.0, "routes": ["PO"]}]}
    assert V.resolve(kit, "x", "IV") == (V.RESOLVED, 10.0)
    assert V.resolve(kit, "x", "PO") == (V.RESOLVED, 32.0)
    assert V.resolve(kit, "x", "IM") == (V.NONE_DECLARED, None)
    assert V.resolve(kit, "x") == (V.NEEDS_CONFIRMATION, None)         # no route: both, so no volume
    one = {"y": [{"concentration_mg_ml": 5.0}]}                        # no routes: every route, as before
    assert V.resolve(one, "y", "PO") == (V.RESOLVED, 5.0)


def test_a_vial_route_that_is_not_a_route_is_refused(tmp_path):
    import hashlib
    import shutil
    shutil.copytree(EMS, tmp_path / "b")
    kit = json.loads((tmp_path / "b" / "kit.json").read_text())
    kit["vials"][0]["routes"] = "IV"
    blob = json.dumps(kit).encode()
    (tmp_path / "b" / "kit.json").write_bytes(blob)
    man = json.loads((tmp_path / "b" / "manifest.json").read_text())
    man["sha256"]["kit.json"] = hashlib.sha256(blob).hexdigest()
    (tmp_path / "b" / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(BankRefused, match="routes"):
        load_bank(tmp_path / "b", test=False)
