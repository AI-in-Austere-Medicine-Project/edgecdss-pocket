"""Signed dose arithmetic, ported from EdgeCDSS server/drug_contracts.py.

classify_units, _limit_mg, resolve_dose, range_text, age_exclusion, age band and
population preference keep their EdgeCDSS logic, and tests/test_golden.py compares
every entry with EdgeCDSS's own output. Only the field names differ: dose_range is
`rule`, max_single is `cap.max_single`, min_single is `floor`. This module holds no
dose: every value comes from the exported bank. `capped` is new: a device with no
screen says so.
"""
import re
from typing import Optional

PENDING = "PENDING_CLINICAL_SIGNOFF"
NEEDS_MANUAL = "NEEDS_MANUAL_ENTRY"
SENTINELS = (PENDING, NEEDS_MANUAL)
SIGNOFF_AUTHORS = ("clinician", "AI-AIM")
VALID_POPULATIONS = ("adult", "peds", "weight-based", "adult|peds")

_MASS_TO_MG = {"g": 1000.0, "mg": 1.0, "mcg": 0.001}
_RATE_MARKERS = ("/min", "/h", "/hr", "/hour", "/minute")

MASS = "MASS"
MASS_PER_KG = "MASS_PER_KG"
RATE = "RATE"
UNKNOWN = "UNKNOWN"


def classify_units(units, per_kg: bool) -> tuple:
    """(kind, mass_unit, reason). UNKNOWN means do not serve: there is no default."""
    if not isinstance(units, str) or not units.strip():
        return UNKNOWN, None, "dose_range has no units"
    u = units.strip().lower().replace("µ", "mc")

    if any(m in u for m in _RATE_MARKERS):
        head = u.split("/")[0]
        if head not in _MASS_TO_MG:
            return UNKNOWN, None, f"unrecognised rate unit {units!r}"
        if not per_kg and "/kg" in u:
            return UNKNOWN, None, f"units {units!r} are weight-based but per_kg is false"
        return RATE, head, ""

    if u.endswith("/kg"):
        head = u[:-3]
        if head not in _MASS_TO_MG:
            return UNKNOWN, None, f"unrecognised mass unit in {units!r}"
        if not per_kg:
            return UNKNOWN, None, f"units {units!r} are per-kilogram but per_kg is false"
        return MASS_PER_KG, head, ""

    if u in _MASS_TO_MG:
        if per_kg:
            return UNKNOWN, None, f"units {units!r} are a flat mass but per_kg is true"
        return MASS, u, ""

    return UNKNOWN, None, f"unrecognised dose unit {units!r}"


def to_mg(value: float, mass_unit: str) -> float:
    return value * _MASS_TO_MG[mass_unit]


def _limit_mg(limit, weight_kg: Optional[float]) -> tuple:
    """(milligrams, why_unusable). (None, "") means no such limit; (None, why) means
    one this module will not guess at, and the whole dose is refused."""
    if not isinstance(limit, dict) or not isinstance(limit.get("value"), (int, float)):
        return None, ""
    units = limit.get("units")
    kind, mass_unit, why = classify_units(units, str(units or "").endswith("/kg"))
    if kind == MASS:
        return to_mg(limit["value"], mass_unit), ""
    if kind == MASS_PER_KG:
        if weight_kg is None:
            return None, ""
        return to_mg(limit["value"] * weight_kg, mass_unit), ""
    return None, why or f"{units!r} is not a mass"


def resolve_dose(entry: dict, weight_kg: Optional[float]) -> dict:
    """{kind, dose_mg, display_value, display_units, reason, floor_applied, floor_note,
    capped}. dose_mg is None for a rate or an unusable unit. A range serves its minimum,
    as in EdgeCDSS; range_text says the rest."""
    out = {"kind": UNKNOWN, "dose_mg": None, "display_value": None,
           "display_units": None, "reason": "",
           "floor_applied": False, "floor_note": "", "capped": False}
    rng = entry.get("rule")
    if not isinstance(rng, dict):
        out["reason"] = "dose_range is not authored"
        return out

    kind, mass_unit, why = classify_units(rng.get("units"), bool(rng.get("per_kg")))
    out["kind"], out["display_units"] = kind, rng.get("units")
    if kind == UNKNOWN:
        out["reason"] = why
        return out
    if kind == RATE:
        out["reason"] = ("this is an infusion RATE, not a bolus — no single "
                         "volume can be derived from it")
        out["display_value"] = rng.get("min")
        return out

    base = rng.get("min")
    if base is None:
        out["kind"] = UNKNOWN
        out["reason"] = "dose_range has no minimum"
        return out

    if kind == MASS_PER_KG:
        if weight_kg is None:
            out["kind"] = UNKNOWN
            out["reason"] = "weight-based dose with no confirmed weight"
            return out
        value = base * weight_kg
    else:
        value = base

    dose_mg = to_mg(value, mass_unit)

    cap_mg, why = _limit_mg((entry.get("cap") or {}).get("max_single"), weight_kg)
    if why:
        out["kind"] = UNKNOWN
        out["reason"] = f"max_single unit is unusable: {why}"
        return out
    if cap_mg is not None:
        out["capped"] = dose_mg > cap_mg
        dose_mg = min(dose_mg, cap_mg)

    floor = entry.get("floor")
    floor_mg, why = _limit_mg(floor, weight_kg)
    if why:
        out["kind"] = UNKNOWN
        out["reason"] = f"min_single unit is unusable: {why}"
        return out
    if floor_mg is not None and dose_mg < floor_mg:
        out["floor_applied"] = True
        out["floor_note"] = (
            f"MINIMUM DOSE {floor['value']:g} {floor['units']}: the weight-based "
            f"dose is below the minimum this source states, so the minimum is "
            f"what is given"
            + (f" — {floor['rule']}" if str(floor.get("rule") or "").strip() else ""))
        dose_mg = floor_mg

    out["dose_mg"] = dose_mg
    out["display_value"] = round(dose_mg / _MASS_TO_MG[mass_unit], 4)
    out["display_units"] = mass_unit
    return out


def range_values(entry: dict) -> list:
    rng = entry.get("rule")
    if not isinstance(rng, dict):
        return []
    return [v for v in (rng.get("min"), rng.get("max")) if isinstance(v, (int, float))]


def range_text(entry: dict) -> Optional[str]:
    """The rule as the source wrote it: "10-20 mcg", "0.25 mg/kg"."""
    vals = range_values(entry)
    rng = entry.get("rule") or {}
    units = rng.get("units")
    kind, _, _ = classify_units(units, bool(rng.get("per_kg")))
    if not vals or kind == UNKNOWN:
        return None
    lo, hi = vals[0], vals[-1]
    head = f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}"
    return f"{head} {units}"


def age_exclusion(entry: dict, age_years: Optional[float]) -> Optional[str]:
    """Why a STATED age rules this entry out, or None. An unknown age blocks nothing."""
    floor = (entry or {}).get("min_age_months")
    if age_years is None or not isinstance(floor, (int, float)):
        return None
    if age_years * 12.0 < floor - 1e-9:
        return (f"contraindicated under {floor:g} months of age "
                f"(stated age {age_years * 12.0:.3g} months)")
    return None


def age_band(entry: dict):
    """(low, high) years this entry is banded to, or None."""
    ind = (entry.get("indication") or "").lower()
    m = re.search(r"under (\d+(?:\.\d+)?) year", ind)
    if m:
        return (0.0, float(m.group(1)))
    m = re.search(r"(\d+(?:\.\d+)?) years? and above", ind)
    if m:
        return (float(m.group(1)), 200.0)
    return None


def fits_population(entry: dict, child: bool) -> bool:
    pop = entry.get("population")
    return not ((child and pop == "adult") or (not child and pop == "peds"))


def prefer_population_specific(entries: list) -> list:
    """Drop a shared adult|peds entry where a population-specific one covers the same
    drug, indication and route (owner ruling 2026-09-18, #65)."""
    specific = {(e.get("drug"), e.get("indication"), e.get("route"))
                for e in entries if e.get("population") in ("adult", "peds")}
    return [e for e in entries
            if not (e.get("population") == "adult|peds"
                    and (e.get("drug"), e.get("indication"), e.get("route")) in specific)]


def has_sentinel(value) -> bool:
    if isinstance(value, str):
        return value.strip() in SENTINELS
    if isinstance(value, dict):
        return any(has_sentinel(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_sentinel(v) for v in value)
    return False
