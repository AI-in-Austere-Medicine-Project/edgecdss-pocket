"""Load the exported bank, or refuse. EdgeCDSS already gated every entry at export;
this is the device's own check that what it holds is what was signed (rule 1, E1).

A test bank (EMS-TEST, owner ruling 2026-11-13) is bench testing only: unsigned
entries, status "test", in bank-ems-test.json with test:true in its manifest. It
loads only when Pocket is started with POCKET_TEST=1, and then nothing else does;
without it, anything marked test is refused, under any file name."""
import dataclasses
import hashlib
import json
import os
import pathlib
import re

from engine.contracts import (SIGNOFF_AUTHORS, UNKNOWN, VALID_POPULATIONS, has_sentinel,
                              resolve_dose)
from engine.words import UNIT_WORDS

_REQUIRED = ("drug", "aliases", "indication", "indication_class", "population", "route",
             "rule", "cap", "repeat", "cautions", "serve_cautions", "contraindications",
             "dilution", "source", "page", "quote", "sources", "signoff", "signer", "date")


TEST_SET = "EMS-TEST"
SIGNED_NAMES = {"bank": "bank.json", "kit": "kit.json", "manifest": "manifest.json"}
TEST_NAMES = {"bank": "bank-ems-test.json", "kit": "kit-ems-test.json",
              "manifest": "manifest-ems-test.json"}
NOT_TESTING = "this is a test set; it loads only with POCKET_TEST=1"


def testing() -> bool:
    """POCKET_TEST=1 exactly: any other value is not a request for the test bank."""
    return os.environ.get("POCKET_TEST") == "1"


class BankRefused(Exception):
    """The reason is short enough to be spoken at boot."""


@dataclasses.dataclass(frozen=True)
class Bank:
    entries: list
    kit: dict
    no_signed_dose: list
    version: str
    hash: str
    commit: str
    test: bool = False

    @property
    def signed_drugs(self) -> set:
        return {e["drug"] for e in self.entries}


def _test_entry_problem(e: dict):
    if e.get("status") != "test" or e.get("set") != TEST_SET:
        return "not a test entry"
    if e.get("signoff") is True:
        return "a test entry marked signed"
    cf = e.get("check_failed")
    if not isinstance(cf, list) or not all(isinstance(x, str) and x.strip() for x in cf):
        return "check_failed is not a list of reasons"
    return None


def entry_problem(e: dict, test: bool = False):
    missing = [f for f in _REQUIRED if f not in e]
    if missing:
        return f"missing {', '.join(missing)}"
    if test:
        why = _test_entry_problem(e)
        if why:
            return why
        return _shape_problem(e)
    if e.get("status") == "test" or e.get("set") == TEST_SET:
        return NOT_TESTING
    if e["signoff"] is not True:
        return "unsigned"
    if str(e["signer"]).strip() not in SIGNOFF_AUTHORS:
        return f"signer {e['signer']} is not authorised"
    if not str(e["date"]).strip():
        return "no signature date"
    return _shape_problem(e)


def _shape_problem(e: dict):
    if has_sentinel(e):
        return "an unfinished field"
    if e["population"] not in VALID_POPULATIONS:
        return f"population {e['population']}"
    if not e["sources"] or not str(e["source"]).strip():
        return "no source"
    if resolve_dose(e, 70.0)["kind"] == UNKNOWN:
        return "an unusable dose"
    if (e["rule"] or {}).get("units") not in UNIT_WORDS:
        return "a unit it cannot say"
    return None


def _vial_problem(v: dict):
    if str(v.get("signer") or "").strip() not in SIGNOFF_AUTHORS:
        return "unsigned"
    if not str(v.get("date") or "").strip() or has_sentinel(v):
        return "unsigned"
    conc = v.get("concentration_mg_ml")
    if not isinstance(conc, (int, float)) or conc <= 0:
        return "no strength"
    return None


def _read(path: pathlib.Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise BankRefused(f"{path.name} is missing") from None


def _json(blob: bytes, name: str):
    try:
        return json.loads(blob)
    except ValueError:
        raise BankRefused(f"{name} is unreadable") from None


def load_bank(directory, test=None) -> Bank:
    """test: None reads POCKET_TEST. True loads the test bank and nothing else."""
    test = testing() if test is None else test
    d = pathlib.Path(directory)
    names = TEST_NAMES if test else SIGNED_NAMES
    if not test and not (d / "manifest.json").exists() and (d / TEST_NAMES["manifest"]).exists():
        raise BankRefused(NOT_TESTING)
    if test and not (d / TEST_NAMES["manifest"]).exists():
        raise BankRefused(f"POCKET_TEST=1 loads a test set only, and "
                          f"{TEST_NAMES['manifest']} is missing")
    manifest = _json(_read(d / names["manifest"]), "manifest")
    bank_blob, kit_blob = _read(d / names["bank"]), _read(d / names["kit"])
    sums = manifest.get("sha256") or {}
    for name, blob in ((names["bank"], bank_blob), (names["kit"], kit_blob)):
        if sums.get(name) != hashlib.sha256(blob).hexdigest():
            raise BankRefused(f"{name} does not match its hash")
    bank, kit = _json(bank_blob, "bank"), _json(kit_blob, "kit")
    marked_test = (manifest.get("test") is True or bank.get("test") is True
                   or TEST_SET in (manifest.get("set"), bank.get("set")))
    if marked_test and not test:
        raise BankRefused(NOT_TESTING)
    if test and not (manifest.get("test") is True and bank.get("test") is True
                     and manifest.get("set") == bank.get("set") == TEST_SET):
        raise BankRefused("POCKET_TEST=1 loads a test set only; this one is not marked test")

    version = str(manifest.get("bank_version") or "")
    if not version or bank.get("bank_version") != version:
        raise BankRefused("no bank version")
    for label in (version, str(manifest.get("kit_id")), str(kit.get("kit_id"))):
        if "example" in label.lower():
            raise BankRefused("this is an EXAMPLE bank")
    commit = str(manifest.get("edgecdss_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BankRefused("no EdgeCDSS commit")

    entries = bank.get("entries") or []
    if not entries:
        raise BankRefused("no test entries" if test else "no signed entries")
    for e in entries:
        why = entry_problem(e, test)
        if why:
            raise BankRefused(f"{e.get('drug')} {e.get('route')}: {why}")
    for name in bank.get("no_signed_dose") or []:
        if set(name) - {"drug", "aliases"}:
            raise BankRefused(f"unsigned {name.get('drug')} carries more than its name")

    vials = {}
    for v in kit.get("vials") or []:
        why = _vial_problem(v)
        if why:
            raise BankRefused(f"{v.get('drug')} vial: {why}")
        vials.setdefault(v["drug"], []).append(v)

    return Bank(entries=entries, kit=vials, no_signed_dose=bank.get("no_signed_dose") or [],
                version=version, hash=sums[names["bank"]], commit=commit, test=test)
