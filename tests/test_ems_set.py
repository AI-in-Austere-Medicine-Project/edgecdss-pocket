"""The EMS set: every formulary entry, signed by the owner (Andrew Azelton, 2026-11-22).

Owner: "bulk-sign the remaining EMS formulary entries ... Record every one of these as
'bulk-signed by owner without item review' with the date, so the record never claims an
item was individually read. Batch 1 stands as individually read." Rules: 1 the numbers as
read from the page; 2 a weight table against the per-kg dose: the per-kg dose with its
stated maximum; 3 a card that contradicts itself where no rule picks the number: not
signed, left for the owner; 4 a missing or contradicting strength: milligrams only, no
volume, until declared; 5 naloxone (DRAFT watermark): signed, the watermark noted; 6
entries Pocket cannot say yet (mEq, topical): signed, silent; 7 the research-prototype
notice stays on everything. Declared: adenosine 12 mg in 4 mL (3 mg/mL).

bank/ems/ is written by the signing tool kept with the formulary (outside the repo); it
holds the signed entries only (dose, short quote, page).
"""
import hashlib
import json
import pathlib
import shutil

import pytest

from engine.bank import BULK, READ, REVIEWS, BankRefused, load_bank
from engine.session import PINNED_VIAL, SIGNED_SILENT, boot, set_name

EMS = pathlib.Path(__file__).resolve().parents[1] / "bank" / "ems"
RAW = json.loads((EMS / "bank.json").read_text())
KIT = json.loads((EMS / "kit.json").read_text())
MANIFEST = json.loads((EMS / "manifest.json").read_text())
NOTICE = "Research prototype, not for patient care."

# Ruled one by one on 2026-11-12 (22), and signing batch 1 of 2026-11-22 (18).
RULED_2026_11_12 = {"EMS-001", "EMS-002", "EMS-016", "EMS-018", "EMS-019", "EMS-020", "EMS-076", "EMS-077",
                    "EMS-080", "EMS-089", "EMS-126", "EMS-138", "EMS-139", "EMS-142", "EMS-181", "EMS-182",
                    "EMS-187", "EMS-188", "EMS-192", "EMS-210", "EMS-214", "EMS-216"}
BATCH_1 = {"EMS-003", "EMS-004", "EMS-005", "EMS-006", "EMS-007", "EMS-008", "EMS-009", "EMS-010", "EMS-011",
           "EMS-012", "EMS-013", "EMS-014", "EMS-015", "EMS-017", "EMS-021", "EMS-022", "EMS-023", "EMS-024"}
FOR_OWNER = {"EMS-037", "EMS-149", "EMS-150", "EMS-151"}
NO_STRENGTH = {"calcium chloride", "magnesium sulfate", "pralidoxime", "olanzapine"}


def _say(*lines):
    s = boot(EMS)
    t = None
    for line in lines:
        t = s.handle(line)
    return t


def _records():
    return RAW["entries"] + RAW["signed_silent"]


def test_every_formulary_entry_is_signed_or_left_for_the_owner():
    ids = [r["ems_id"] for r in _records()] + [x["ems_id"] for x in RAW["unsigned_left_out"]]
    assert len(ids) == len(set(ids)) == 206
    assert (len(RAW["entries"]), len(RAW["signed_silent"]), len(RAW["unsigned_left_out"])) == (174, 28, 4)
    assert {x["ems_id"] for x in RAW["unsigned_left_out"]} == FOR_OWNER
    assert all(x["why"] for x in RAW["unsigned_left_out"])
    assert set(RAW["unsigned_left_out"][0]) == {"ems_id", "drug", "population", "route", "indication", "why"}  # no dose


def test_the_record_never_claims_an_item_was_individually_read_unless_it_was():
    read = {r["ems_id"] for r in _records() if r["review"] == READ}
    assert read == RULED_2026_11_12 | BATCH_1
    bulk = [r for r in _records() if r["review"] == BULK]
    assert len(bulk) == 162 and BULK == "bulk-signed by owner without item review"
    for r in _records():
        assert r["signoff"] is True and r["signed_by"] == "Andrew Azelton" and r["signer"] == "clinician"
        assert r["date"] == ("2026-11-12" if r["ems_id"] in RULED_2026_11_12 else "2026-11-22")
    assert MANIFEST["counts"]["individually_read"] == 40 and MANIFEST["counts"]["bulk_signed"] == 162


def test_the_bank_refuses_an_ems_entry_that_does_not_say_how_it_was_signed(tmp_path):
    for review in (None, "read", "individually read"):
        d = tmp_path / str(review)
        shutil.copytree(EMS, d)
        bank = json.loads((d / "bank.json").read_text())
        if review is None:
            del bank["entries"][5]["review"]
        else:
            bank["entries"][5]["review"] = review
        _write(d, bank)
        with pytest.raises(BankRefused, match="how it was signed"):
            load_bank(d, test=False)
    assert set(REVIEWS) == {READ, BULK}


def test_a_silent_entry_must_be_signed_too(tmp_path):
    shutil.copytree(EMS, tmp_path / "b")
    bank = json.loads((tmp_path / "b" / "bank.json").read_text())
    bank["signed_silent"][0]["signoff"] = False
    _write(tmp_path / "b", bank)
    with pytest.raises(BankRefused, match="unsigned"):
        load_bank(tmp_path / "b", test=False)


def test_a_signed_but_silent_drug_is_named_and_says_no_dose():
    b = load_bank(EMS, test=False)
    assert b.silent_drugs == {"nitroglycerin", "olanzapine", "sodium bicarbonate"}
    assert not {s["drug"] for s in b.silent} & {"nitroglycerin", "olanzapine", "sodium bicarbonate"} - b.silent_drugs
    for said, name in (("sodium bicarbonate", "Sodium bicarbonate"), ("nitroglycerin", "Nitroglycerin")):
        t = _say(said)
        assert t.kind == "hold" and t.say == SIGNED_SILENT.format(name=name)
        assert "milligram" not in t.say and "gram" not in t.say


def test_silent_entries_carry_no_dose_pocket_could_serve():
    b = load_bank(EMS, test=False)
    keys = {(e["drug"], e["population"], e["route"], e["indication"]) for e in b.entries}
    for s in b.silent:
        assert s["silent_because"]
        assert "rule" not in s and "cap" not in s
        assert (s["drug"], s["population"], s["route"], s["indication"]) not in keys


def test_the_declared_adenosine_vial_gives_its_volume():
    t = _say("adenosine for svt iv adult", "confirm")
    assert t.say == "Adenosine twelve milligrams. Four mils of three."
    v = [v for v in KIT["vials"] if v["drug"] == "adenosine"]
    assert len(v) == 1 and v[0]["concentration_mg_ml"] == 3.0 and v[0]["owner_declared"] is True


def test_a_drug_whose_strength_is_missing_or_contradicted_says_milligrams_only():
    declared = {x["drug"] for x in KIT["strengths_to_declare"]}
    assert NO_STRENGTH <= declared and "adenosine" not in declared
    assert not NO_STRENGTH & {v["drug"] for v in KIT["vials"]}
    for e in RAW["entries"]:
        if e["drug"] in NO_STRENGTH:
            assert e["kit_vial"] == "none"
    t = _say("calcium chloride for hyperkalemia iv adult", "confirm")
    assert t.say == f"Calcium chloride one gram. {PINNED_VIAL}"


def test_a_tablet_or_a_second_strength_never_gives_a_volume():
    """Rule 4: a volume only where the route uses the card's one printed liquid strength."""
    for e in RAW["entries"]:
        if e["date"] == "2026-11-22" and (e["route"] == "PO" or e["drug"] in {"epinephrine", "norepinephrine"}):
            assert e["kit_vial"] == "none", e["ems_id"]
    t = _say("acetaminophen for fever po twenty kilos", "confirm")
    assert t.say.endswith(PINNED_VIAL)


def test_every_unpinned_entry_has_exactly_one_signed_vial():
    vials = [v["drug"] for v in KIT["vials"]]
    for e in RAW["entries"]:
        if e["kit_vial"] is None and e["date"] == "2026-11-22":
            assert vials.count(e["drug"]) == 1, e["ems_id"]


def test_naloxone_is_signed_with_its_draft_watermark_noted():
    nal = [r for r in _records() if r["drug"] == "naloxone"]
    assert len(nal) == 7
    for r in nal:
        assert r["watermark"] == "DRAFT"
    for e in RAW["entries"]:
        if e["drug"] == "naloxone":
            assert any("watermarked DRAFT" in c["text"] for c in e["cautions"])


def test_the_research_prototype_notice_stays_on_everything():
    assert RAW["notice"] == MANIFEST["notice"] == NOTICE
    assert all(r["notice"] == NOTICE for r in _records())


def test_the_ems_bank_is_its_hash_and_loads_as_the_ems_set():
    for name in ("bank.json", "kit.json"):
        assert hashlib.sha256((EMS / name).read_bytes()).hexdigest() == MANIFEST["sha256"][name]
    b = load_bank(EMS, test=False)
    assert b.kit_id.startswith("ems-formulary") and len(b.entries) == 174
    assert set_name(b.kit_id) == "EMS set"


def _write(d, bank):
    blob = json.dumps(bank).encode()
    (d / "bank.json").write_bytes(blob)
    man = json.loads((d / "manifest.json").read_text())
    man["sha256"]["bank.json"] = hashlib.sha256(blob).hexdigest()
    (d / "manifest.json").write_text(json.dumps(man))
