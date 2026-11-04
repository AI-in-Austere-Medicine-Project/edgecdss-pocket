"""Vial and dilution to mL, ported from EdgeCDSS server/drug_concentrations.py and
openai_client.resolve_dose_volume. A volume comes only from a signed vial in kit.json
or a signed dilution made from it. kit is {drug: [vial, ...]}.
"""
from typing import Optional

RESOLVED = "RESOLVED"
NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
NONE_DECLARED = "NONE_DECLARED"

TOO_SMALL = "TOO_SMALL"
TOO_LARGE = "TOO_LARGE"

MIN_DRAWABLE_ML = 0.05
MAX_BOLUS_ML = 60.0
DILUTE_BELOW_ML = 0.5  # K3, owner 2026-10-28


def resolve(kit: dict, drug: str) -> tuple:
    """(status, concentration). Pocket's grammar has no vial question, so two signed
    vials, or confirm_required, stay unresolved: milligrams only."""
    vials = kit.get(drug) or []
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


def volume_ml(kit: dict, drug: str, dose_mg: float) -> tuple:
    """(volume_ml, concentration) or (None, None)."""
    status, conc = resolve(kit, drug)
    if status != RESOLVED or not conc:
        return None, None
    true_vol = dose_mg / conc
    if not drawable(true_vol)[0]:
        return None, None
    return round(true_vol, draw_precision(true_vol)), conc


def _dilution_for(dilution: Optional[dict], conc: Optional[float]) -> Optional[dict]:
    """The dilution, only if its recipe starts from the vial `conc` is."""
    if not dilution or not conc:
        return None
    return dilution if abs(dilution["from_concentration_mg_ml"] - conc) < 1e-9 else None


def dose_volume(kit: dict, entry: dict, dose_mg: float) -> dict:
    """{status, volume_ml, concentration_mg_ml, diluted, recipe, refusal}."""
    drug, dilution = entry.get("drug"), entry.get("dilution")
    status, resolved = resolve(kit, drug)
    out = {"status": status, "volume_ml": None, "concentration_mg_ml": None,
           "diluted": False, "recipe": None, "refusal": None}
    vol, conc = volume_ml(kit, drug, dose_mg)
    if vol is None:
        if status == RESOLVED:
            _ok, out["refusal"] = drawable(dose_mg / resolved)
            if out["refusal"] == TOO_SMALL:
                out["recipe"] = _dilution_for(dilution, resolved)
        return out
    dil = _dilution_for(dilution, conc)
    if dil and vol < DILUTE_BELOW_ML:
        dil_conc = float(dil["concentration_mg_ml"])
        true_vol = dose_mg / dil_conc
        if drawable(true_vol)[0]:
            out.update(volume_ml=round(true_vol, draw_precision(true_vol)),
                       concentration_mg_ml=dil_conc, diluted=True, recipe=dil)
            return out
    out.update(volume_ml=vol, concentration_mg_ml=conc)
    return out
