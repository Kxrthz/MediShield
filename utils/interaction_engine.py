import re

from sqlalchemy import or_

from extensions import db
from models import DrugInteraction


BRAND_TO_SALTS = {
    "crocin": ["paracetamol"], "dolo": ["paracetamol"], "calpol": ["paracetamol"],
    "augmentin": ["amoxicillin", "clavulanic acid"], "azithral": ["azithromycin"],
    "pantop": ["pantoprazole"], "uprise": ["cholecalciferol"], "shelcal": ["calcium carbonate", "cholecalciferol"],
    "montair lc": ["montelukast", "levocetirizine"], "limcee": ["ascorbic acid"],
    "brufen": ["ibuprofen"], "omeZ": ["omeprazole"], "omez": ["omeprazole"],
    "glycomet": ["metformin"], "atorva": ["atorvastatin"], "amlong": ["amlodipine"],
    "ecosprin": ["aspirin"], "telma": ["telmisartan"], "allegra": ["fexofenadine"],
    "meftal spas": ["mefenamic acid", "dicyclomine"], "domstal": ["domperidone"],
    "zincovit": ["multivitamin"], "omeprazole": ["omeprazole"], "cetirizine": ["cetirizine"],
}

ALIASES = {
    "acetaminophen": "paracetamol", "paracetamol": "paracetamol", "amoxycillin": "amoxicillin",
    "amoxicillin trihydrate": "amoxicillin", "clavulanate": "clavulanic acid",
    "clavulanic acid": "clavulanic acid", "pantoprazole sodium": "pantoprazole",
    "cholecalciferol": "cholecalciferol", "vitamin d3": "cholecalciferol",
    "ascorbic acid": "ascorbic acid", "vitamin c": "ascorbic acid",
    "calcium": "calcium carbonate", "calcium carbonate": "calcium carbonate",
    "metformin hydrochloride": "metformin", "ibuprofen": "ibuprofen", "alcohol": "alcohol",
    "ethanol": "alcohol", "aspirin": "aspirin", "acetylsalicylic acid": "aspirin",
    "atorvastatin calcium": "atorvastatin", "sildenafil citrate": "sildenafil",
    "warfarin sodium": "warfarin", "methotrexate sodium": "methotrexate",
    "clopidogrel bisulfate": "clopidogrel", "azithromycin dihydrate": "azithromycin",
    "amoxicillin + clavulanic acid": "amoxicillin + clavulanic acid",
}


def canonical_salt(value):
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    normalized = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|iu|ml)\b", "", normalized).strip()
    normalized = re.sub(r"\s+(?:tablet|tablets|capsule|capsules|syrup|injection)$", "", normalized).strip()
    return ALIASES.get(normalized, normalized)


def ingredients_for(medicine):
    brand = str(getattr(medicine, "brand_name", "") or medicine.get("brand_name", ""))
    generic = str(getattr(medicine, "generic_name", "") or medicine.get("generic_name", ""))
    lowered = brand.casefold()
    for known_brand in sorted(BRAND_TO_SALTS, key=len, reverse=True):
        if lowered.startswith(known_brand.casefold()):
            return list(dict.fromkeys(canonical_salt(s) for s in BRAND_TO_SALTS[known_brand]))
    parts = re.split(r"\s*(?:\+|&|/|\band\b|,)\s*", generic, flags=re.I)
    return list(dict.fromkeys(canonical_salt(s) for s in parts if canonical_salt(s)))


def _medicine_value(medicine, key, fallback=None):
    if isinstance(medicine, dict):
        return medicine.get(key, fallback)
    return getattr(medicine, key, fallback)


def seed_interactions():
    """Idempotently seed the offline screening knowledge base."""
    from utils.interaction_seed import build_interaction_seed

    known = {(r.salt_one.casefold(), r.salt_two.casefold()) for r in DrugInteraction.query.all()}
    for first, second, severity, effect, recommendation, *notes in build_interaction_seed(250):
        a, b = sorted((canonical_salt(first), canonical_salt(second)))
        if (a.casefold(), b.casefold()) in known:
            continue
        db.session.add(DrugInteraction(salt_one=a, salt_two=b, severity=severity, effect=effect,
                                       recommendation=recommendation, notes=notes[0] if notes else "Curated starter interaction."))
        known.add((a.casefold(), b.casefold()))
    db.session.commit()


def check_interactions(medicines):
    """Check selected medicine rows and return warnings plus a bounded 0-100 score.

    Inputs may be Medicine objects or dictionaries; duplicate prescription lines
    remain visible as therapy-duplication warnings but are not compared to themselves.
    """
    rows = []
    for index, medicine in enumerate(medicines):
        rows.append({"index": index, "id": _medicine_value(medicine, "id"),
                     "brand": _medicine_value(medicine, "brand_name", "Medicine"),
                     "generic": _medicine_value(medicine, "generic_name", ""),
                     "salts": ingredients_for(medicine)})

    database = DrugInteraction.query.all()
    lookup = {}
    for item in database:
        lookup[tuple(sorted((canonical_salt(item.salt_one), canonical_salt(item.salt_two))))] = item

    results = {"safe": [], "mild": [], "moderate": [], "severe": [], "duplicate_warnings": [], "unknown_pairs": []}
    seen_pairs = set()
    for i, left in enumerate(rows):
        for right in rows[i + 1:]:
            if left["id"] is not None and left["id"] == right["id"]:
                results["duplicate_warnings"].append({"type": "same_medicine", "medicines": [left["brand"], right["brand"]],
                                                       "message": f"{left['brand']} appears more than once."})
                continue
            left_salts, right_salts = set(left["salts"]), set(right["salts"])
            common = left_salts & right_salts
            if common:
                results["duplicate_warnings"].append({"type": "duplicate_ingredient", "medicines": [left["brand"], right["brand"]],
                                                       "salts": sorted(common), "message": "Duplicate therapy: both products contain " + ", ".join(sorted(common)) + "."})
            for salt_a in left_salts:
                for salt_b in right_salts:
                    if salt_a == salt_b:
                        continue
                    key = tuple(sorted((salt_a, salt_b)))
                    unique_key = (left["index"], right["index"], key)
                    if unique_key in seen_pairs:
                        continue
                    seen_pairs.add(unique_key)
                    record = lookup.get(key)
                    if not record:
                        results["unknown_pairs"].append({"medicine_one": left["brand"], "medicine_two": right["brand"],
                                                          "salt_one": salt_a, "salt_two": salt_b,
                                                          "status": "Not in local knowledge base"})
                        continue
                    severity = record.severity.casefold()
                    entry = {"medicine_one": left["brand"], "medicine_two": right["brand"],
                             "salt_one": record.salt_one, "salt_two": record.salt_two,
                             "severity": record.severity, "effect": record.effect,
                             "recommendation": record.recommendation, "notes": record.notes}
                    results.setdefault(severity, []).append(entry)

    weights = {"mild": 10, "moderate": 30, "severe": 80}
    points = sum(weights.get(level, 0) for level in ("mild", "moderate", "severe") for _ in results[level])
    points += min(20, len(results["duplicate_warnings"]) * 10)
    score = min(100, points)
    label = "Safe" if score <= 25 else "Low Risk" if score <= 50 else "Moderate Risk" if score <= 75 else "High Risk"
    return {**results, "safety_score": score, "safety_label": label,
            "total_interactions": sum(len(results[level]) for level in ("safe", "mild", "moderate", "severe")),
            "unreviewed_pairs": len(results["unknown_pairs"]),
            "has_severe": bool(results["severe"])}
