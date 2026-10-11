import math


class CostValidationError(ValueError):
    pass


COST_FIELDS = (
    "material_per_sheet",
    "click_per_side",
    "setup",
    "finishing_per_unit",
    "labour_per_hour",
    "machine_per_hour",
    "waste_percent",
    "outsourcing",
    "sell_price_per_unit",
)


def cost_profile(payload):
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 100:
        raise CostValidationError("Cost profile name must be between 1 and 100 characters.")
    values = {}
    for field in COST_FIELDS:
        try:
            value = float(payload.get(field))
        except (TypeError, ValueError) as error:
            raise CostValidationError(f"{field} is required and must be numeric.") from error
        if not math.isfinite(value) or value < 0:
            raise CostValidationError(f"{field} must be a finite non-negative number.")
        values[field] = value
    if values["waste_percent"] > 100:
        raise CostValidationError("waste_percent must not exceed 100.")
    return {"name": name, **values, "enabled": bool(payload.get("enabled", True))}


def estimate(plan, profile, quantity):
    sheets = float(plan["sheets"]) + float(plan["waste_sheets"])
    clicks = float(plan["clicks"])
    machine_hours = float(plan["machine_minutes"]) / 60
    labour_hours = float(plan["operator_minutes"]) / 60
    material = sheets * float(profile["material_per_sheet"])
    waste = material * float(profile["waste_percent"]) / 100
    breakdown = {
        "paper_material": round(material, 2),
        "expected_waste": round(waste, 2),
        "ink_toner_clicks": round(clicks * float(profile["click_per_side"]), 2),
        "setup": round(float(profile["setup"]), 2),
        "finishing_binding": round(quantity * float(profile["finishing_per_unit"]), 2),
        "labour": round(labour_hours * float(profile["labour_per_hour"]), 2),
        "machine_running": round(machine_hours * float(profile["machine_per_hour"]), 2),
        "outsourcing": round(float(profile["outsourcing"]), 2),
    }
    total = round(sum(breakdown.values()), 2)
    revenue = round(quantity * float(profile["sell_price_per_unit"]), 2)
    margin = round(((revenue - total) / revenue) * 100, 2) if revenue else None
    return {"breakdown": breakdown, "total": total, "revenue": revenue, "profit_margin_percent": margin}