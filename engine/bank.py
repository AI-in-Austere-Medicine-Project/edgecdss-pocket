"""Load the exported bank, or refuse. EdgeCDSS already gated every entry at export;
this is the device's own check that what it holds is what was signed (rule 1, E1)."""
import dataclasses
import hashlib
import json
import pathlib
import re

from engine.contracts import (SIGNOFF_AUTHORS, UNKNOWN, VALID_POPULATIONS, has_sentinel,
                              resolve_dose)
from engine.words import UNIT_WORDS

_REQUIRED = ("drug", "aliases", "indication", "indication_class", "population", "route",
             "rule", "cap", "repeat", "cautions", "serve_cautions", "contraindications",
             "dilution", "source", "page", "quote", "sources", "signoff", "signer", "date")


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

    @property
    def signed_drugs(self) -> set:
        return {e["drug"] for e in self.entries}


def entry_problem(e: dict):
    missing = [f for f in _REQUIRED if f not in e]
    if missing:
        return f"missing {', '.join(missing)}"
    if e["signoff"] is not True:
        return "unsigned"
    if str(e["signer"]).strip() not in SIGNOFF_AUTHORS:
        return f"signer {e['signer']} is not authorised"
    if not str(e["date"]).strip():
        return "no signature date"
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


def load_bank(directory) -> Bank:
    d = pathlib.Path(directory)
    manifest = _json(_read(d / "manifest.json"), "manifest")
    bank_blob, kit_blob = _read(d / "bank.json"), _read(d / "kit.json")
    sums = manifest.get("sha256") or {}
    for name, blob in (("bank.json", bank_blob), ("kit.json", kit_blob)):
        if sums.get(name) != hashlib.sha256(blob).hexdigest():
            raise BankRefused(f"{name} does not match its hash")
    bank, kit = _json(bank_blob, "bank"), _json(kit_blob, "kit")

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
        raise BankRefused("no signed entries")
    for e in entries:
        why = entry_problem(e)
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
                version=version, hash=sums["bank.json"], commit=commit)
