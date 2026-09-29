import math


STATUSES = {"SAFE", "MILD", "MODERATE", "SEVERE", "UNCERTAIN"}
SEVERITY_RANK = {"SAFE": 0, "MILD": 1, "MODERATE": 2, "SEVERE": 3, "UNCERTAIN": -1}


class SafetyValidationError(ValueError):
    pass


def _text(value, limit=500):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def validate_result(raw, medicines):
    if not isinstance(raw, dict):
        raise SafetyValidationError("AI response is not an object.")
    status = str(raw.get("overall_status", "")).strip().upper()
    if status not in STATUSES:
        raise SafetyValidationError("AI returned an unsupported safety status.")
    confidence_value = raw.get("confidence")
    if isinstance(confidence_value, bool):
        raise SafetyValidationError("AI confidence is invalid.")
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError):
        raise SafetyValidationError("AI confidence is missing.")
    if not math.isfinite(confidence) or confidence < 0 or confidence > 100:
        raise SafetyValidationError("AI confidence must be between 0 and 100.")
    if not 0 <= confidence <= 100:
        raise SafetyValidationError("AI confidence must be between 0 and 100.")
    labels = {m["label"].casefold(): m["label"] for m in medicines}
    aliases = {}
    for medicine in medicines:
        for alias in medicine.get("ingredients", []):
            aliases[alias.casefold()] = medicine["label"]

    interactions = []
    raw_interactions = raw.get("interactions", [])
    if not isinstance(raw_interactions, list):
        raise SafetyValidationError("AI interactions must be a list.")
    if len(raw_interactions) > 40:
        raise SafetyValidationError("AI returned too many interaction entries.")
    max_status = status
    for item in raw_interactions:
        if not isinstance(item, dict):
            raise SafetyValidationError("An interaction entry is invalid.")
        one = _text(item.get("medicine_1"), 160)
        two = _text(item.get("medicine_2"), 160)
        if one.casefold() not in labels and one.casefold() not in aliases:
            raise SafetyValidationError("AI interaction refers to an unselected medicine.")
        if two.casefold() not in labels and two.casefold() not in aliases:
            raise SafetyValidationError("AI interaction refers to an unselected medicine.")
        one = labels.get(one.casefold(), aliases.get(one.casefold(), one))
        two = labels.get(two.casefold(), aliases.get(two.casefold(), two))
        if one.casefold() == two.casefold():
            raise SafetyValidationError("AI returned a medicine paired with itself.")
        severity = _text(item.get("severity"), 20).upper()
        if severity not in {"MILD", "MODERATE", "SEVERE"}:
            raise SafetyValidationError("AI returned an unsupported interaction severity.")
        interactions.append({
            "medicine_1": one, "medicine_2": two, "severity": severity,
            "reason": _text(item.get("reason"), 500) or "The model did not provide a reason.",
            "recommendation": _text(item.get("recommendation"), 500) or "Review this combination using an authoritative clinical reference."
        })
        if SEVERITY_RANK[severity] > SEVERITY_RANK.get(max_status, -1):
            max_status = severity
    if max_status != "UNCERTAIN" and SEVERITY_RANK[max_status] > SEVERITY_RANK.get(status, -1):
        status = max_status
    elif status == "SAFE" and interactions:
        status = max_status
    if confidence < 35 and status in {"SAFE", "MILD"}:
        status = "UNCERTAIN"

    allergy_warnings = []
    raw_allergies = raw.get("allergy_warnings", [])
    if not isinstance(raw_allergies, list) or len(raw_allergies) > 20:
        raise SafetyValidationError("AI allergy warnings are invalid.")
    for warning in raw_allergies:
        if not isinstance(warning, dict):
            raise SafetyValidationError("An allergy warning is invalid.")
        medicine = _text(warning.get("medicine"), 160)
        allergen = _text(warning.get("allergen"), 160)
        if medicine.casefold() not in labels:
            raise SafetyValidationError("AI allergy warning refers to an unselected medicine.")
        if not allergen:
            raise SafetyValidationError("AI allergy warning is missing the allergen.")
        allergy_warnings.append({"medicine": labels[medicine.casefold()], "allergen": allergen,
                                 "reason": _text(warning.get("reason"), 400)})

    recommendations = raw.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise SafetyValidationError("AI recommendations must be a list.")
    recommendations = [_text(x, 400) for x in recommendations if isinstance(x, str) and _text(x, 400)][:8]
    if status == "SEVERE":
        billing_action = "ADMIN_OVERRIDE"
    elif status in {"MODERATE", "UNCERTAIN"} or allergy_warnings:
        billing_action = "ACKNOWLEDGEMENT_REQUIRED"
    else:
        billing_action = "ALLOW"
    return {
        "available": True, "overall_status": status, "confidence": round(confidence),
        "summary": _text(raw.get("summary"), 500) or "Review the listed findings with an authoritative clinical reference.",
        "interactions": interactions, "allergy_warnings": allergy_warnings,
        "recommendations": recommendations, "billing_action": billing_action
    }
