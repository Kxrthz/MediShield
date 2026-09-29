import json


SYSTEM_PROMPT = """You are MediShield AI Guardian, a cautious medication compatibility screening assistant for a licensed pharmacist. This is screening support, not a diagnosis or prescribing decision. Analyze only the medicine and limited patient context provided. Do not invent interactions, contraindications, or citations. If evidence is not clear, use UNCERTAIN. Distinguish a known concern from absence of evidence. Do not say a combination is universally safe. Do not give patient-facing dose changes or tell anyone to stop a prescription. Return exactly one JSON object matching the requested schema, with no markdown."""


def build_messages(medicines, patient_context):
    context = {
        "medicines": medicines,
        "patient_context": patient_context or {},
        "required_json_schema": {
            "overall_status": "SAFE|MILD|MODERATE|SEVERE|UNCERTAIN",
            "confidence": "integer from 0 to 100",
            "summary": "short explanation, max 500 characters",
            "interactions": [{
                "medicine_1": "exact input medicine label",
                "medicine_2": "exact input medicine label",
                "severity": "MILD|MODERATE|SEVERE",
                "reason": "brief reason; state uncertainty when applicable",
                "recommendation": "pharmacist review action"
            }],
            "allergy_warnings": [{
                "medicine": "exact input medicine label",
                "allergen": "allergy from patient context",
                "reason": "brief explanation"
            }],
            "recommendations": ["brief pharmacist-facing recommendations"],
            "billing_action": "ALLOW|ACKNOWLEDGEMENT_REQUIRED|BLOCK|ADMIN_OVERRIDE"
        },
        "rules": [
            "Evaluate every unique pair of distinct active ingredients across the selected medicines, including ingredients inside combination products.",
            "Use patient age, gender, known allergies, and notes only when provided; do not infer missing facts.",
            "If a medicine identity or interaction evidence is ambiguous, return UNCERTAIN rather than SAFE.",
            "SAFE means no concern was identified from the information available for this check, not that the combination is guaranteed harmless.",
            "Set status to the highest interaction severity found. Allergy conflicts must be listed separately in allergy_warnings.",
            "Keep explanations concise and suitable for a pharmacist reviewing a prescription."
        ]
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
    ]
