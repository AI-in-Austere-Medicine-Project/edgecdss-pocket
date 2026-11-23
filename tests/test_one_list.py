"""One drug list, the EMS set (owner decision, 2026-11-23): "Pocket carries one drug list,
the EMS set only. Load only the EMS set. Remove set switching ("E M S set", "P F C set")
and the other-set messages. Start-up line no longer names a set. Retire the PFC bank: keep
the file in the repo, unloaded and marked retired with the date. Do not delete signed work."

This replaces the set choice of 2026-11-22 (#32).
"""
import hashlib
import json
import pathlib
import subprocess

import pytest

from engine.bank import BANK_DIR, PFC_RETIRED, RETIRED_FILE, BankRefused, load_bank
from engine.session import START_UP_LINE, boot
from grammar.vocabulary import CONTROLS
from voice import spoken

ROOT = pathlib.Path(__file__).resolve().parents[1]
RETIRED_DRUGS = ["artesunate", "calcium gluconate", "cefazolin", "ceftriaxone", "ertapenem",
                 "levetiracetam", "lorazepam", "morphine", "moxifloxacin", "phytomenadione",
                 "propofol", "sodium chloride 3%", "succinylcholine"]


def test_pocket_loads_the_ems_set_and_nothing_else():
    assert BANK_DIR == ROOT / "bank" / "ems"
    s = boot()
    assert s.bank.kit_id.startswith("ems-formulary") and len(s.bank.entries) == 178
    assert s.set_name == "EMS set" and sorted(s.procedures) == ["failed airway", "rsi"]
    assert not (ROOT / "bank" / "bank.json").exists()          # nothing left where the PFC set was


def test_the_start_up_line_names_no_set():
    s = boot()
    assert s.announce.say == s.announce.written == START_UP_LINE == (
        "Pocket ready. Research prototype, not for patient care. Say drugs, procedures, or help.")
    assert s.records[0]["set"] == "EMS set"                    # the set is logged, not said


@pytest.mark.parametrize("said", ["e m s set", "p f c set", "ems set", "pfc set"])
def test_the_set_words_are_gone(said):
    assert "ems set" not in CONTROLS and "pfc set" not in CONTROLS
    s = boot()
    t = s.handle(spoken.normalise(said), spoken=True)
    assert t.kind == "unrecognised" and s.set_name == "EMS set"


@pytest.mark.parametrize("name", ["artesunate", "keppra", "succinylcholine", "sux", "lorazepam"])
def test_a_drug_only_the_retired_set_signed_holds_and_names_no_other_set(name):
    """No other-set message. Typed, the name is one the EMS formulary lists without a signed
    dose, so it holds; spoken, it is not in the grammar (tests/test_hearing_ems.py)."""
    t = boot().handle(name)
    assert t.kind in ("hold", "unrecognised") and "set" not in t.say, t.say
    assert t.say in (f"No signed dose for {name}.", "Not recognised."), t.say


def test_the_pfc_bank_is_retired_unchanged_and_never_loaded():
    mark = json.loads((PFC_RETIRED / RETIRED_FILE).read_text())
    assert mark["date"] == "2026-11-23" and mark["set"] == "PFC" and "Do not delete signed work" in mark["decision"]
    man = json.loads((PFC_RETIRED / "manifest.json").read_text())
    for name in ("bank.json", "kit.json"):                     # the signed files, byte for byte
        assert hashlib.sha256((PFC_RETIRED / name).read_bytes()).hexdigest() == man["sha256"][name]
    assert man["sha256"]["bank.json"].startswith("934ca9b6")
    with pytest.raises(BankRefused, match="retired on 2026-11-23"):
        load_bank(PFC_RETIRED)
    assert boot(PFC_RETIRED).refused == "this bank was retired on 2026-11-23"
    pfc = load_bank(PFC_RETIRED, retired_ok=True)              # the tests' fixture, by name only
    assert sorted((pfc.signed_drugs | pfc.silent_drugs) - (boot().bank.signed_drugs | boot().bank.silent_drugs)) == RETIRED_DRUGS


def test_no_code_on_the_device_loads_a_retired_bank():
    code = subprocess.run(["git", "grep", "-l", "-e", "retired_ok=True", "-e", "PFC_RETIRED", "--",
                           "*.py", "*.sh", ":!tests", ":!voice/tests", ":!engine/tests"],
                          cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert code == ["engine/bank.py"]


def test_the_device_and_power_up_load_the_ems_set():
    import argparse

    from voice import autostart, device
    assert device._boot(argparse.Namespace(bank=None), None).bank.kit_id.startswith("ems-formulary")
    for gone in ("SETS", "SET_FILE", "saved_set", "save_set"):
        assert not hasattr(autostart, gone)
    with pytest.raises(SystemExit):
        device.main(["--set", "EMS", "--typed"])
