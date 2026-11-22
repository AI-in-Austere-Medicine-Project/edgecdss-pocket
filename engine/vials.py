"""Vial to mL, ported from EdgeCDSS server/drug_concentrations.py and
openai_client.resolve_dose_volume. A volume comes only from a signed vial in kit.json.
kit is {drug: [vial, ...]}.

No dilution in Pocket (owner rule, 2026-11-22): a volume under 0.5 mL is said to the
nearest 0.01 mL, with "Use a one mil syringe."; under 0.05 mL it is too small to draw.
A signed dilution in an entry is not used (it replaced K3, owner 2026-10-28).
"""
import re
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Optional

from engine import words

RESOLVED = "RESOLVED"
NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
NONE_DECLARED = "NONE_DECLARED"

TOO_SMALL = "TOO_SMALL"
TOO_LARGE = "TOO_LARGE"

MIN_DRAWABLE_ML = 0.05
MAX_BOLUS_ML = 60.0
ONE_MIL_BELOW_ML = 0.5  # owner rule 2026-11-22: nearest 0.01 mL, a one mil syringe


def resolve(kit: dict, drug: str, route: Optional[str] = None) -> tuple:
    """(status, concentration). Pocket's grammar has no vial question, so two signed
    vials, or confirm_required, stay unresolved: milligrams only. A vial that names its
    routes serves only those (acetaminophen's IV bag and oral liquid, 2026-11-22)."""
    vials = [v for v in kit.get(drug) or []
             if route is None or v.get("routes") is None or route in v["routes"]]
    if not vials:
        return NONE_DECLARED, None
    if len(vials) == 1 and not vials[0].get("confirm_required"):
        return RESOLVED, vials[0]["concentration_mg_ml"]
    return NEEDS_CONFIRMATION, None


def draw_precision(true_volume_ml: float) -> int:
    """Decimal places a syringe can be read to: two at a mL and above, three below."""
    start = 3 if true_volume_ml < 1.0 else 2
    for places in (start, start + 1, 4):
        rounded = round(true_volume_ml, places)
        if rounded > 0 and abs(rounded - true_volume_ml) <= true_volume_ml * 0.05:
            return places
    return 4


def drawable(volume_ml_value: float) -> tuple:
    """(ok, TOO_SMALL | TOO_LARGE | "")."""
    if volume_ml_value < MIN_DRAWABLE_ML:
        return False, TOO_SMALL
    if volume_ml_value > MAX_BOLUS_ML:
        return False, TOO_LARGE
    return True, ""


def _round(value: float, step: str, down: bool = False) -> float:
    rounding = ROUND_FLOOR if down else ROUND_HALF_UP          # half up, as a medic rounds
    return float((Decimal(repr(value)) / Decimal(step)).quantize(Decimal("1"), rounding=rounding)
                 * Decimal(step))


def round_volume(true_vol: float, conc: float, max_mg: Optional[float] = None) -> float:
    """The volume as said (owner rulings, 2026-11-22): under 1 mL to 0.01 mL, 1 to 10 mL to
    0.1 mL, 10 mL and over to 1 mL. Safeguards: never above the signed maximum (rounded down
    instead); from 0.5 mL, a rounding that moves the dose more than 5 % takes one more place
    (under 0.5 mL the owner's rule is the nearest 0.01 mL as given)."""
    steps = ["0.01", "0.001"] if true_vol < 1 else ["0.1", "0.01"] if true_vol < 10 else ["1", "0.1"]
    for i, step in enumerate(steps):
        vol = _round(true_vol, step)
        if max_mg is not None and vol * conc > max_mg * (1 + 1e-9):
            vol = _round(true_vol, step, down=True)
        last = i == len(steps) - 1 or true_vol < ONE_MIL_BELOW_ML
        if last or (vol > 0 and abs(vol - true_vol) / true_vol <= 0.05):
            return vol
    return vol


def volume_ml(kit: dict, drug: str, dose_mg: float, route: Optional[str] = None,
              max_mg: Optional[float] = None) -> tuple:
    """(volume_ml, concentration) or (None, None)."""
    status, conc = resolve(kit, drug, route)
    if status != RESOLVED or not conc:
        return None, None
    true_vol = dose_mg / conc
    if not drawable(true_vol)[0]:
        return None, None
    return round_volume(true_vol, conc, max_mg), conc


_LABEL = re.compile(r"^(?:D\d+W\s+)?(\d+(?:\.\d+)?)\s*(mg|g|mcg)\s*/\s*(\d+(?:\.\d+)?)?\s*mL\b", re.I)


def _label_number(text: str) -> str:
    """As a label is read: 160 is "one sixty", 250 "two fifty", 105 "one oh five"."""
    x = float(text)
    if x.is_integer() and 100 < x < 1000 and x % 100:
        hundreds, rest = divmod(int(x), 100)
        return f"{words.num(hundreds)} {'oh ' + words.num(rest) if rest < 10 else words.num(rest)}"
    return words.num(x)


def label_words(vial: dict) -> str:
    """The strength as the vial's label reads it (owner ruling, 2026-11-22): "one sixty per
    five", "fifty micrograms per mil", "one gram per ten"; milligrams unsaid. A label that
    states no strength: the milligrams per mil, as before."""
    m = _LABEL.match(str(vial.get("label") or "").strip())
    if not m:
        return words.num(vial["concentration_mg_ml"])
    amount, unit, per = m.group(1), m.group(2).lower(), m.group(3) or "1"
    unit_said = {"mg": "", "g": " gram" if float(amount) == 1 else " grams", "mcg": " micrograms"}[unit]
    per_said = "per mil" if float(per) == 1 else f"per {_label_number(per)}"
    return f"{_label_number(amount)}{unit_said} {per_said}"


def dose_volume(kit: dict, entry: dict, dose_mg: float, max_mg: Optional[float] = None) -> dict:
    """{status, volume_ml, concentration_mg_ml, diluted, recipe, refusal}. diluted is
    always False and recipe always None: no dilution in Pocket (owner rule, 2026-11-22)."""
    drug = entry.get("drug")
    status, resolved = resolve(kit, drug, entry.get("route"))
    out = {"status": status, "volume_ml": None, "concentration_mg_ml": None,
           "diluted": False, "recipe": None, "refusal": None, "strength": None}
    vol, conc = volume_ml(kit, drug, dose_mg, entry.get("route"), max_mg)
    if vol is None:
        if status == RESOLVED:
            _ok, out["refusal"] = drawable(dose_mg / resolved)
        return out
    vial = [v for v in kit.get(drug) or []
            if v.get("routes") is None or entry.get("route") in v["routes"]][0]
    out.update(volume_ml=vol, concentration_mg_ml=conc, strength=label_words(vial))
    return out
