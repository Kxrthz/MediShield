"""Incremental demo products that make the documented interaction scenarios testable."""
from datetime import date, timedelta
from extensions import db
from models import Medicine

INTERACTION_DEMO_MEDICINES = [
    ("Warfarin 5 mg", "Warfarin", "5 mg", "Tablet", "Cardiac care", 18),
    ("Sildenafil 50 mg", "Sildenafil", "50 mg", "Tablet", "Other", 24),
    ("Nitroglycerin 0.5 mg", "Nitroglycerin", "0.5 mg", "Tablet", "Cardiac care", 16),
    ("Diclofenac 50 mg", "Diclofenac", "50 mg", "Tablet", "Pain relief", 12),
    ("Clopidogrel 75 mg", "Clopidogrel", "75 mg", "Tablet", "Cardiac care", 28),
    ("Methotrexate 2.5 mg", "Methotrexate", "2.5 mg", "Tablet", "Other", 42),
    ("Naproxen 250 mg", "Naproxen", "250 mg", "Tablet", "Pain relief", 18),
    ("Simvastatin 10 mg", "Simvastatin", "10 mg", "Tablet", "Cardiac care", 22),
]

def seed_interaction_demo_medicines():
    existing={m.brand_name.casefold() for m in Medicine.query.all()}
    for i,(brand,generic,strength,form,category,price) in enumerate(INTERACTION_DEMO_MEDICINES,1):
        if brand.casefold() in existing: continue
        db.session.add(Medicine(brand_name=brand,generic_name=generic,strength=strength,dosage_form=form,
            category=category,manufacturer="MediShield demo catalog",price=price,stock=25,minimum_stock=5,
            batch_number=f"DEMO-{date.today().year}-{i:04d}",barcode=f"890199990{i:03d}",
            expiry_date=date.today()+timedelta(days=365)))
    db.session.commit()
