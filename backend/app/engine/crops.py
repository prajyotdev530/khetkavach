"""Crop stage lookup: turns a crop and sowing date into a growth stage and its heat threshold (BUILD_SPEC §7).

The stage tables themselves live in `risk.yaml` so every agronomic number is in one reviewable file.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.config import risk_rules
from app.models import StageInfo

CROP_LABELS = {"wheat": "Wheat", "mustard": "Mustard", "gram": "Gram (chickpea)", "unknown": "Not sure"}


def stage_for(crop: str, sowing_date: Optional[date], today: date) -> StageInfo:
    """Return the growth stage for a crop sown on `sowing_date`, or an 'unknown' stage without one."""
    crops = risk_rules()["crops"]
    if crop not in crops or sowing_date is None:
        return StageInfo(key="unknown", label="Stage unknown")
    das = (today - sowing_date).days
    for stage in crops[crop]["stages"]:
        end = stage["end"]
        if das >= stage["start"] and (end is None or das <= end):
            return StageInfo(key=stage["key"], label=stage["label"], days_after_sowing=das,
                             sensitive=bool(stage["sensitive"]))
    return StageInfo(key="unknown", label="Stage unknown", days_after_sowing=das)


def heat_threshold(crop: str, stage: StageInfo) -> float:
    """Max-temperature limit for heat stress: lower at sensitive stages; 35 °C when the crop is 'Not sure'."""
    rules = risk_rules()
    if crop not in rules["crops"]:
        return float(rules["unknown_crop_heat_c"])
    limits = rules["crops"][crop]["heat_c"]
    return float(limits["sensitive"] if stage.sensitive else limits["other"])


def is_sensitive_for(hazard: str, crop: str, stage_key: str) -> bool:
    """True if this stage gets the drought (×1.15) or excess-rain (×1.3) multiplier for this crop."""
    stages = risk_rules()[hazard].get("sensitive_stages", {}).get(crop, [])
    return stage_key in stages
