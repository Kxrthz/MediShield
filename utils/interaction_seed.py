"""Local demo DDI seed set. Treat every result as a pharmacist review prompt."""

import itertools


# Ingredient pairs in the examples are explicitly seeded. The remaining starter
# set combines medicines with known QT-prolonging potential and is intentionally
# conservative; it is not a complete or patient-specific clinical reference.
CORE = [
    ("Warfarin", "Aspirin", "Severe", "Both can increase bleeding risk.", "Avoid the combination unless specifically directed; contact the prescriber and monitor for bleeding."),
    ("Warfarin", "Ibuprofen", "Severe", "NSAIDs can increase bleeding risk and affect anticoagulation.", "Avoid unsupervised use; consult the prescriber and monitor for bleeding."),
    ("Azithromycin", "Atorvastatin", "Moderate", "Macrolide antibiotics may increase statin exposure and muscle-injury risk.", "Check the exact product label; consider an alternative or temporary dose plan with the prescriber."),
    ("Metformin", "Alcohol", "Moderate", "Alcohol can increase the risk of metformin-associated lactic acidosis, especially with excess use or illness.", "Avoid excessive alcohol; seek clinician advice for acute illness or dehydration."),
    ("Ibuprofen", "Diclofenac", "Severe", "Using two NSAIDs increases gastrointestinal bleeding and kidney injury risk.", "Do not combine unless specifically directed by a prescriber."),
    ("Paracetamol", "Alcohol", "Moderate", "Regular heavy alcohol use can increase liver-injury risk with paracetamol.", "Check total daily paracetamol from all products and ask a clinician if alcohol use is frequent."),
    ("Amoxicillin", "Methotrexate", "Moderate", "Penicillins may reduce methotrexate clearance and increase toxicity.", "Contact the prescriber; monitor for methotrexate toxicity."),
    ("Pantoprazole", "Clopidogrel", "Mild", "Acid suppression may affect clopidogrel activation; clinical relevance varies by product and patient.", "Review the specific label and consider an alternative acid suppressant if clinically appropriate."),
    ("Cetirizine", "Alcohol", "Moderate", "Alcohol may increase drowsiness and impairment.", "Avoid alcohol and use caution with driving or machinery."),
    ("Amlodipine", "Sildenafil", "Moderate", "Blood-pressure lowering may be additive and cause dizziness or fainting.", "Use only with clinician guidance; monitor for symptomatic low blood pressure."),
    ("Warfarin", "Naproxen", "Severe", "NSAID use with warfarin increases bleeding risk.", "Avoid unless specifically directed; contact the prescriber."),
    ("Warfarin", "Clopidogrel", "Severe", "Combined anticoagulant and antiplatelet effects increase bleeding risk.", "Combination requires prescriber oversight and bleeding monitoring."),
    ("Simvastatin", "Clarithromycin", "Severe", "Clarithromycin can markedly increase simvastatin exposure and myopathy risk.", "Avoid coadministration; contact the prescriber for an alternative."),
    ("Atorvastatin", "Clarithromycin", "Moderate", "Clarithromycin may increase atorvastatin exposure and myopathy risk.", "Review product labeling; the prescriber may pause or adjust therapy."),
    ("Lisinopril", "Spironolactone", "Moderate", "Both can increase potassium and cause hyperkalemia.", "Use only with clinician oversight and potassium/renal monitoring."),
    ("Ramipril", "Potassium", "Moderate", "ACE inhibitors can increase serum potassium.", "Review supplements and monitor potassium with the prescriber."),
    ("Tramadol", "Sertraline", "Severe", "Both affect serotonin; serotonin toxicity and seizures are possible.", "Avoid or use only with close prescriber supervision; seek urgent care for severe symptoms."),
    ("Linezolid", "Fluoxetine", "Severe", "Linezolid has monoamine oxidase activity and may precipitate serotonin toxicity.", "Avoid the combination unless specialist-directed; follow washout guidance."),
    ("Methotrexate", "Ibuprofen", "Moderate", "NSAIDs can reduce methotrexate clearance and increase toxicity, especially at higher doses.", "Contact the prescriber before combining; monitor renal function and toxicity."),
    ("Digoxin", "Amiodarone", "Severe", "Amiodarone can increase digoxin concentrations and toxicity risk.", "Prescriber review, dose adjustment, and digoxin monitoring are needed."),
    ("Lithium", "Ibuprofen", "Moderate", "NSAIDs may increase lithium concentrations and toxicity risk.", "Avoid unsupervised use; monitor lithium levels if prescribed together."),
    ("Theophylline", "Ciprofloxacin", "Severe", "Ciprofloxacin may increase theophylline exposure and toxicity.", "Avoid or closely monitor levels under prescriber direction."),
    ("Gliclazide", "Fluconazole", "Moderate", "Fluconazole may increase sulfonylurea exposure and hypoglycemia risk.", "Monitor glucose and consult the diabetes prescriber."),
    ("Aspirin", "Ibuprofen", "Moderate", "Ibuprofen may interfere with aspirin's antiplatelet effect and both can increase bleeding risk.", "Ask the prescriber or pharmacist about timing and an alternative analgesic."),
    ("Apixaban", "Rifampicin", "Severe", "Rifampicin can reduce apixaban exposure and compromise anticoagulation.", "Avoid coadministration; contact the anticoagulation prescriber."),
    ("Rivaroxaban", "Ketoconazole", "Severe", "Strong CYP3A/P-gp inhibition can increase rivaroxaban exposure and bleeding risk.", "Avoid or use only under specialist direction per current labeling."),
    ("Tadalafil", "Nitroglycerin", "Severe", "Concurrent use can cause a dangerous drop in blood pressure.", "Do not use together; seek urgent medical advice if accidentally combined."),
    ("Levothyroxine", "Calcium carbonate", "Mild", "Calcium can reduce levothyroxine absorption.", "Separate administration by at least four hours and follow prescriber instructions."),
    ("Doxycycline", "Calcium carbonate", "Mild", "Calcium can reduce doxycycline absorption.", "Separate doses as directed by the product label or pharmacist."),
    ("Ciprofloxacin", "Calcium carbonate", "Moderate", "Calcium can reduce ciprofloxacin absorption and treatment effectiveness.", "Separate doses according to the product label; ask a pharmacist."),
    ("Metformin", "Iodinated contrast", "Moderate", "Contrast-associated kidney injury can increase metformin accumulation risk.", "Follow the imaging team's instructions for holding and restarting metformin."),
    ("Digoxin", "Verapamil", "Severe", "Verapamil can increase digoxin exposure and slow heart rate.", "Prescriber review and monitoring are recommended."),
    ("Colchicine", "Clarithromycin", "Severe", "Clarithromycin can substantially increase colchicine exposure and toxicity.", "Avoid coadministration; urgently consult the prescriber."),
    ("Carbamazepine", "Erythromycin", "Severe", "Erythromycin may increase carbamazepine concentrations and toxicity.", "Avoid or monitor levels closely under prescriber direction."),
    ("Rifampicin", "Oral contraceptives", "Moderate", "Rifampicin can reduce hormonal contraceptive effectiveness.", "Use a non-hormonal backup method and consult the prescriber."),
    ("Fluconazole", "Warfarin", "Severe", "Fluconazole can increase anticoagulant effect and bleeding risk.", "Check INR more frequently under anticoagulation-clinic guidance."),
    ("Trimethoprim", "Warfarin", "Severe", "Trimethoprim-sulfamethoxazole may increase INR and bleeding risk.", "Contact the anticoagulation prescriber for INR monitoring and treatment review."),
    ("Prednisolone", "Ibuprofen", "Moderate", "Corticosteroids and NSAIDs together increase gastrointestinal ulcer and bleeding risk.", "Review need for the combination and protective measures with a clinician."),
    ("Insulin", "Propranolol", "Moderate", "Beta blockers may mask some warning symptoms of hypoglycemia.", "Monitor glucose closely and discuss symptom recognition with the clinician."),
    ("Sildenafil", "Nitroglycerin", "Severe", "Concurrent use can cause profound hypotension.", "Do not use together; seek urgent medical advice if accidentally combined."),
]

QT_RISK_DRUGS = [
    "Amiodarone", "Sotalol", "Quinidine", "Dofetilide", "Dronedarone", "Procainamide",
    "Azithromycin", "Clarithromycin", "Erythromycin", "Levofloxacin", "Moxifloxacin",
    "Ciprofloxacin", "Fluconazole", "Ketoconazole", "Ondansetron", "Domperidone",
    "Haloperidol", "Citalopram", "Escitalopram", "Amitriptyline", "Methadone",
    "Quetiapine", "Chlorpromazine", "Ziprasidone", "Hydroxychloroquine", "Trazodone",
    "Venlafaxine", "Risperidone", "Fluphenazine", "Disopyramide",
]


def build_interaction_seed(target=250):
    rows = list(CORE)
    seen = {frozenset((a.casefold(), b.casefold())) for a, b, *_ in rows}
    for first, second in itertools.combinations(QT_RISK_DRUGS, 2):
        key = frozenset((first.casefold(), second.casefold()))
        if key in seen:
            continue
        rows.append((first, second, "Moderate",
                     "Potential additive QT-interval prolongation may increase the risk of serious heart-rhythm changes.",
                     "Review the exact products and patient risk factors; consider ECG and electrolyte monitoring with the prescriber.",
                     "Starter screening pair based on QT-risk medicines; confirm against current product labeling."))
        seen.add(key)
        if len(rows) >= target:
            break
    return [(*row[:5], row[5] if len(row) > 5 else "Curated starter interaction; confirm against current product labeling.") for row in rows]
