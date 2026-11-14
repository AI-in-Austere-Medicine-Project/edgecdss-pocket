"""Entries pinned to a vial speak milligrams only, until Pocket reads kit_vial
(owner, 2026-11-14: "Before I merge ems-test-bank it must include the fix that
entries pinned to a vial speak milligrams only until Pocket reads kit_vial").

EdgeCDSS's EMS entries name their vial in `kit_vial`: a strength (mg/mL), "none"
(no kit vial: a tablet, a tube, a rate), or null (the vial question stays). Pocket
works a volume out from the drug's one signed vial, which is not necessarily the
vial the entry names (epinephrine 1:10,000 rows against the 1 mg/mL vial). So any
entry with a kit_vial set gets no volume at all; null, and PFC entries, which
carry no kit_vial, are unchanged.
"""
import hashlib
import json
import pathlib
import shutil

import pytest

from engine.session import PINNED_VIAL, boot

BANK = pathlib.Path(__file__).resolve().parents[1] / "bank"
KETAMINE = "ketamine for agitation iv eighty kilos"


def _bank_with(tmp_path, kit_vial, present=True):
    d = tmp_path / "bank"
    shutil.copytree(BANK, d)
    bank = json.loads((d / "bank.json").read_text())
    for e in bank["entries"]:
        if e["drug"] == "ketamine" and present:
            e["kit_vial"] = kit_vial
    (d / "bank.json").write_text(json.dumps(bank))
    man = json.loads((d / "manifest.json").read_text())
    man["sha256"]["bank.json"] = hashlib.sha256((d / "bank.json").read_bytes()).hexdigest()
    (d / "manifest.json").write_text(json.dumps(man))
    return d


def _dose(s):
    s.handle(KETAMINE)
    return s.handle("confirm")


@pytest.mark.parametrize("pin", [50.0, 100.0, "none"])
def test_an_entry_pinned_to_a_vial_speaks_milligrams_only(tmp_path, pin, monkeypatch):
    monkeypatch.delenv("POCKET_TEST", raising=False)
    dose = _dose(boot(_bank_with(tmp_path, pin)))
    assert dose.kind == "dose", dose.text
    assert "milligrams" in dose.say
    assert "mil" not in dose.say.replace("milligram", ""), dose.say
    assert PINNED_VIAL in dose.say
    rec = dose.data["record"]
    assert rec["volume_ml"] is None and rec["concentration_mg_ml"] is None
    assert rec["diluted"] is False


def test_a_null_kit_vial_keeps_the_volume(tmp_path, monkeypatch):
    monkeypatch.delenv("POCKET_TEST", raising=False)
    dose = _dose(boot(_bank_with(tmp_path, None)))
    assert "mils of fifty" in dose.say, dose.say
    assert PINNED_VIAL not in dose.say


def test_an_entry_with_no_kit_vial_keeps_the_volume(monkeypatch):
    monkeypatch.delenv("POCKET_TEST", raising=False)
    dose = _dose(boot(BANK))
    assert "Three point two mils of fifty" in dose.say, dose.say
    assert dose.data["record"]["volume_ml"] == 3.2
