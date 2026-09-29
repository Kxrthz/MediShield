from datetime import date, datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="cashier")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(160), nullable=False, index=True)
    generic_name = db.Column(db.String(160), nullable=False, index=True)
    strength = db.Column(db.String(80), nullable=False, default="")
    dosage_form = db.Column(db.String(80), nullable=False, default="Tablet")
    category = db.Column(db.String(100), nullable=False, default="Other", index=True)
    manufacturer = db.Column(db.String(160), nullable=False, default="")
    supplier = db.Column(db.String(160), nullable=False, default="")
    barcode = db.Column(db.String(100), unique=True, nullable=True, index=True)
    price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    minimum_stock = db.Column(db.Integer, nullable=False, default=10)
    batch_number = db.Column(db.String(100), nullable=False, default="")
    expiry_date = db.Column(db.Date, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    @property
    def stock_status(self):
        if self.expiry_date < date.today():
            return "Expired"
        if self.stock <= self.minimum_stock:
            return "Low stock"
        if (self.expiry_date - date.today()).days <= 30:
            return "Expiring soon"
        return "In stock"

    def to_dict(self):
        return {"id": self.id, "brand_name": self.brand_name, "generic_name": self.generic_name,
                "strength": self.strength, "dosage_form": self.dosage_form, "category": self.category,
                "manufacturer": self.manufacturer, "supplier": self.supplier or "", "barcode": self.barcode or "", "price": self.price, "cost_price": self.cost_price or 0,
                "stock": self.stock, "minimum_stock": self.minimum_stock, "batch_number": self.batch_number,
                "expiry_date": self.expiry_date.isoformat(), "image_url": self.image_url or "",
                "stock_status": self.stock_status}


class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False, index=True)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(40), nullable=False, default="Prefer not to say")
    phone = db.Column(db.String(10), unique=True, nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True)
    blood_group = db.Column(db.String(5), nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    doctor_name = db.Column(db.String(160), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {"id": self.id, "full_name": self.full_name, "age": self.age, "gender": self.gender,
                "phone": self.phone or "", "email": self.email or "", "blood_group": self.blood_group or "",
                "allergies": self.allergies or "", "doctor_name": self.doctor_name or "", "notes": self.notes or "",
                "created_at": self.created_at.isoformat() if self.created_at else ""}


class DrugInteraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    salt_one = db.Column(db.String(160), nullable=False, index=True)
    salt_two = db.Column(db.String(160), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False)
    effect = db.Column(db.Text, nullable=False)
    recommendation = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (db.UniqueConstraint("salt_one", "salt_two", name="uq_interaction_salts"),)


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"), nullable=True)
    pharmacist_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    gst_amount = db.Column(db.Float, nullable=False)
    discount = db.Column(db.Float, nullable=False, default=0)
    grand_total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="Completed")
    payment_method = db.Column(db.String(24), nullable=False, default="Cash")
    interaction_count = db.Column(db.Integer, nullable=False, default=0)
    ai_status = db.Column(db.String(20), nullable=True, index=True)
    ai_confidence = db.Column(db.Integer, nullable=True)
    override_reason = db.Column(db.Text, nullable=True)
    interaction_summary = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    patient = db.relationship("Patient")
    pharmacist = db.relationship("User")
    items = db.relationship("BillItem", back_populates="bill", cascade="all, delete-orphan", order_by="BillItem.id")


class BillItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bill.id"), nullable=False, index=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicine.id", ondelete="SET NULL"), nullable=True)
    medicine_name = db.Column(db.String(160), nullable=False)
    generic_name = db.Column(db.String(200), nullable=False)
    strength = db.Column(db.String(80), nullable=False, default="")
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    bill = db.relationship("Bill", back_populates="items")
    medicine = db.relationship("Medicine")


class OverrideAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bill.id"), nullable=False, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    bill = db.relationship("Bill")
    admin = db.relationship("User")


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False, default="Info")
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey("bill.id"), nullable=True)
    dismissed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    bill = db.relationship("Bill")
