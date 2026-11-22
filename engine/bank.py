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
# The sets on the device (owner, 2026-11-22): "P F C set", "E M S set".
ROOT = pathlib.Path(__file__).resolve().parents[1]
SET_DIRS = {"PFC": ROOT / "bank", "EMS": ROOT / "bank" / "ems"}
SIGNED_NAMES = {"bank": "bank.json", "kit": "kit.json", "manifest": "manifest.json"}
TEST_NAMES = {"bank": "bank-ems-test.json", "kit": "kit-ems-test.json",
              "manifest": "manifest-ems-test.json"}
NOT_TESTING = "this is a test set; it loads only with POCKET_TEST=1"
# How an EMS entry was signed (owner, 2026-11-22): the record never claims an item was
# individually read when it was not.
READ = "individually read by owner"
BULK = "bulk-signed by owner without item review"
REVIEWS = (READ, BULK)
VIAL_ROUTES = ("IV", "IM", "IN", "PO", "NEB")


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
    kit_id: str = ""
    silent: list = dataclasses.field(default_factory=list)

    @property
    def signed_drugs(self) -> set:
        return {e["drug"] for e in self.entries}

    @property
    def silent_drugs(self) -> set:
        """Signed, but Pocket cannot say any of their doses yet (mEq, topical, ...)."""
        return {s["drug"] for s in self.silent} - self.signed_drugs


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
    if e.get("set") == "EMS" and e.get("review") not in REVIEWS:
        return "it does not say how it was signed"
    return _shape_problem(e)


def _silent_problem(s: dict):
    """A signed entry Pocket does not say: signed like any other, and never a dose."""
    if s.get("signoff") is not True or str(s.get("signer") or "").strip() not in SIGNOFF_AUTHORS:
        return "unsigned"
    if not str(s.get("date") or "").strip():
        return "no signature date"
    if s.get("review") not in REVIEWS:
        return "it does not say how it was signed"
    if "rule" in s or not s.get("silent_because"):
        return "a silent entry with a dose"
    return None


def _shape_problem(e: dict):
    if has_sentinel(e):
        return "an unfinished field"
    floor = e.get("min_weight")
    if floor is not None and not (
            isinstance(floor, dict) and isinstance(floor.get("kg"), (int, float)) and floor["kg"] > 0
            and isinstance(floor.get("exclusive"), bool) and str(floor.get("from") or "").strip()):
        return "a weight floor that is not a weight"
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
    routes = v.get("routes")
    if routes is not None and not (isinstance(routes, list) and routes
                                   and all(r in VIAL_ROUTES for r in routes)):
        return "routes that are not routes"
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

    silent = bank.get("signed_silent") or []
    for sl in silent:
        why = _silent_problem(sl)
        if why:
            raise BankRefused(f"{sl.get('drug')} {sl.get('route')}: {why}")

    vials = {}
    for v in kit.get("vials") or []:
        why = _vial_problem(v)
        if why:
            raise BankRefused(f"{v.get('drug')} vial: {why}")
        vials.setdefault(v["drug"], []).append(v)

    return Bank(entries=entries, kit=vials, no_signed_dose=bank.get("no_signed_dose") or [],
                version=version, hash=sums[names["bank"]], commit=commit, test=test,
                kit_id=str(manifest.get("kit_id") or ""), silent=silent)


def merge_banks(banks) -> Bank:
    """Every set's names in one bank, for the words Pocket hears (owner, 2026-11-22: hearing
    for every drug name in both sets). Never for doses: a session doses from its own set."""
    banks = list(banks)
    entries = [e for b in banks for e in b.entries]
    # A drug one set signs and another only names keeps the names the other set lists
    # ("2-pam", "benadryl"): they are its names, and a spelling must not hold them.
    names = {}
    for b in banks:
        for n in b.no_signed_dose:
            names.setdefault(n["drug"], [])
            names[n["drug"]] += [a for a in n["aliases"] if a not in names[n["drug"]]]
    unsigned = [{"drug": d, "aliases": a} for d, a in names.items()]
    joined = "+".join(b.hash for b in banks)
    return Bank(entries=entries, kit={}, no_signed_dose=unsigned,
                version="+".join(b.version for b in banks),
                hash=hashlib.sha256(joined.encode()).hexdigest(), commit=banks[0].commit,
                silent=[s for b in banks for s in b.silent])


def load_sets(dirs=None) -> dict:
    """{key: Bank} for every set that loads (refused sets left out)."""
    out = {}
    for key, d in (dirs or SET_DIRS).items():
        try:
            out[key] = load_bank(d, test=False)
        except BankRefused:
            continue
    return out
