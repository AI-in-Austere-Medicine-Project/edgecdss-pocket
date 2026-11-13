"""EMS-TEST bench bank (owner ruling 2026-11-13).

Owner: "Pocket loads a test bank only when started with POCKET_TEST=1, and
refuses it otherwise. It says "Test set. Not for patient use." on boot and at
the start of every read-back. Every log line carries test:true. Entries that
failed check (a) or (b), or contradict their own card, are included but marked
check_failed with the reason; Pocket says "unverified" before those doses."

The fixture is this repo's own signed bank relabelled the way EdgeCDSS's
exporter writes a test bank (bank-ems-test.json, test:true, every entry status
"test", unsigned): the real EMS-TEST bank reproduces the agency's formulary and
never enters this repo.
"""
import hashlib
import json
import pathlib

import pytest

from engine.bank import BankRefused, load_bank
from engine.session import TEST_NOTICE, boot, jsonl_log

BANK = pathlib.Path(__file__).resolve().parents[1] / "bank"
NAMES = {"bank": "bank-ems-test.json", "kit": "kit-ems-test.json",
         "manifest": "manifest-ems-test.json"}
KETAMINE = ("ketamine for agitation iv eighty kilos",)  # a read-back on the PFC bank


def _as_test(entry: dict, check_failed=()):
    return dict(entry, set="EMS-TEST", status="test", signoff=False, signer=None, date=None,
                check_failed=list(check_failed))


def _write(d: pathlib.Path, bank: dict, kit: bytes, manifest: dict, names=NAMES):
    d.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(bank).encode()
    (d / names["bank"]).write_bytes(blob)
    (d / names["kit"]).write_bytes(kit)
    manifest = dict(manifest, sha256={names["bank"]: hashlib.sha256(blob).hexdigest(),
                                      names["kit"]: hashlib.sha256(kit).hexdigest()})
    (d / names["manifest"]).write_text(json.dumps(manifest))
    return d


def make_test_bank(tmp_path, failed=None, edit=None, names=NAMES, manifest_test=True):
    """failed: {drug: [reason, ...]} marks that drug's entries check_failed."""
    failed = failed or {}
    bank = json.loads((BANK / "bank.json").read_text())
    man = json.loads((BANK / "manifest.json").read_text())
    bank["entries"] = [_as_test(e, failed.get(e["drug"], ())) for e in bank["entries"]]
    bank.update(set="EMS-TEST", test=True)
    if edit:
        edit(bank)
    man.update(set="EMS-TEST")
    if manifest_test:
        man["test"] = True
    return _write(tmp_path / "bank", bank, (BANK / "kit.json").read_bytes(), man, names)


@pytest.fixture
def testing(monkeypatch):
    monkeypatch.setenv("POCKET_TEST", "1")


@pytest.fixture
def not_testing(monkeypatch):
    monkeypatch.delenv("POCKET_TEST", raising=False)


def _dose(s, *phrases):
    turns = [s.handle(p) for p in (*phrases, "confirm")]
    return turns[-2], turns[-1]


# ── loaded only with POCKET_TEST=1 ──────────────────────────────────────────

def test_without_pocket_test_a_test_bank_is_refused(tmp_path, not_testing):
    s = boot(make_test_bank(tmp_path))
    assert s.announce.kind == "refused"
    assert "POCKET_TEST=1" in s.announce.say
    for phrase in (*KETAMINE, "confirm"):
        assert s.handle(phrase).kind == "refused"


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2"])
def test_only_the_value_1_loads_it(tmp_path, monkeypatch, value):
    monkeypatch.setenv("POCKET_TEST", value)
    assert boot(make_test_bank(tmp_path)).announce.kind == "refused"


def test_a_test_bank_under_the_signed_names_is_still_refused(tmp_path, not_testing):
    """Renaming the files does not make it a signed bank: the manifest says test."""
    plain = {"bank": "bank.json", "kit": "kit.json", "manifest": "manifest.json"}
    with pytest.raises(BankRefused, match="POCKET_TEST=1"):
        load_bank(make_test_bank(tmp_path, names=plain))


def test_a_bank_of_test_entries_is_refused_even_if_its_manifest_omits_test(tmp_path, not_testing):
    plain = {"bank": "bank.json", "kit": "kit.json", "manifest": "manifest.json"}
    with pytest.raises(BankRefused):
        load_bank(make_test_bank(tmp_path, names=plain, manifest_test=False))


def test_with_pocket_test_it_loads(tmp_path, testing):
    b = load_bank(make_test_bank(tmp_path))
    assert b.test is True and len(b.entries) > 0


def test_with_pocket_test_a_signed_bank_is_not_loaded_as_a_test_bank(testing):
    """POCKET_TEST=1 loads a test bank only: a signed bank never boots announced as test."""
    with pytest.raises(BankRefused, match="test"):
        load_bank(BANK)


def test_the_signed_bank_still_loads_without_pocket_test(not_testing):
    b = load_bank(BANK)
    assert b.test is False


@pytest.mark.parametrize("field, value", [
    ("status", None), ("set", "EMS"), ("signoff", True), ("check_failed", "check (a)")])
def test_a_test_bank_holds_test_entries_only(tmp_path, testing, field, value):
    def edit(bank):
        bank["entries"][0][field] = value
    with pytest.raises(BankRefused):
        load_bank(make_test_bank(tmp_path, edit=edit))


def test_a_test_bank_is_still_hash_checked(tmp_path, testing):
    d = make_test_bank(tmp_path)
    (d / NAMES["bank"]).write_bytes((d / NAMES["bank"]).read_bytes() + b" ")
    with pytest.raises(BankRefused, match="hash"):
        load_bank(d)


# ── what it says ────────────────────────────────────────────────────────────

def test_boot_says_test_set_not_for_patient_use(tmp_path, testing):
    assert TEST_NOTICE == "Test set. Not for patient use."
    s = boot(make_test_bank(tmp_path))
    assert s.announce.kind == "boot"
    assert s.announce.say.startswith(TEST_NOTICE)
    assert "signed entries" not in s.announce.say  # they are test entries, unsigned


def test_every_read_back_starts_with_it(tmp_path, testing):
    s = boot(make_test_bank(tmp_path))
    for _ in range(2):
        readback, dose = _dose(s, *KETAMINE)
        assert readback.kind == "readback", readback.text
        assert readback.say.startswith(TEST_NOTICE), readback.say
        assert dose.kind == "dose"


def test_the_signed_bank_says_neither(not_testing):
    s = boot(BANK)
    assert TEST_NOTICE not in s.announce.text
    readback, dose = _dose(s, *KETAMINE)
    assert TEST_NOTICE not in readback.text
    assert "nverified" not in dose.text
    assert "test" not in dose.data["record"]


def test_a_check_failed_dose_says_unverified_first(tmp_path, testing):
    s = boot(make_test_bank(tmp_path, failed={"ketamine": ["check (a): dose not in the row"]}))
    _, dose = _dose(s, *KETAMINE)
    assert dose.kind == "dose"
    assert dose.say.startswith("Unverified."), dose.say
    assert "milligrams" in dose.say
    assert dose.data["record"]["check_failed"] == ["check (a): dose not in the row"]


def test_a_dose_that_passed_its_checks_is_not_called_unverified(tmp_path, testing):
    s = boot(make_test_bank(tmp_path))
    _, dose = _dose(s, *KETAMINE)
    assert "nverified" not in dose.text
    assert dose.data["record"]["check_failed"] == []


# ── every log line carries test:true ────────────────────────────────────────

def test_every_log_line_carries_test_true(tmp_path, testing):
    log = tmp_path / "doses.jsonl"
    s = boot(make_test_bank(tmp_path, failed={"ketamine": ["x"]}), log=jsonl_log(log))
    for _ in range(3):
        _dose(s, *KETAMINE)
    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(lines) == 3
    assert all(l["test"] is True for l in lines)
