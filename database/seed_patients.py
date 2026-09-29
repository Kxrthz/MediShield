"""Fill the demo patient table to its 50-record target without replacing user rows."""
from extensions import db
from models import Patient

NAMES = [
"Aarav Mehta","Anaya Kulkarni","Ishaan Reddy","Diya Chatterjee","Kabir Malhotra","Saanvi Pillai","Reyansh Desai","Aadhya Mukherjee","Vivaan Joshi","Myra Nair",
"Advik Bansal","Kiara Rao","Arnav Sinha","Sara Iyer","Dhruv Kapoor","Ira Menon","Ayaan Shah","Pari Banerjee","Krish Verma","Aarohi Shetty",
"Veer Khanna","Anvi Patil","Rudra Bose","Navya Ghosh","Yuvaan Jain","Tara Das","Atharv Gupta","Ishita Roy","Kian Thomas","Mira Srinivasan",
"Om Prasad","Riya Kaur","Shaurya Mishra","Vanya Anand","Parth Choudhary","Ishani Dutta","Neil Fernandes","Aditi Narayan","Armaan Gill","Lavanya Bhat",
]
def seed_demo_patients(target=50):
    existing={p.phone for p in Patient.query.all() if p.phone}
    missing=max(0,target-Patient.query.count())
    for i,name in enumerate(NAMES):
        if missing<=0: break
        phone=f"98765{20000+i:05d}"
        if phone in existing: continue
        db.session.add(Patient(full_name=name,age=22+(i*7)%58,gender=("Female" if i%2 else "Male"),phone=phone,
            doctor_name="Demo record",allergies="Not recorded",notes="Synthetic MediShield demonstration record."))
        missing-=1
    db.session.commit()
