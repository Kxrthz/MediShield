import os
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for, session, jsonify, flash
from flask_login import current_user, login_required
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from extensions import db, login_manager
from models import Bill, BillItem, DrugInteraction, Medicine, Notification, Patient, User
from routes.auth import auth_bp
from routes.billing import billing_bp
from routes.management import api_bp
from utils.interaction_engine import seed_interactions


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    Config.apply(app)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(billing_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return redirect(url_for("auth.login", expired=1, next=request.full_path))

    @app.context_processor
    def shared_counts():
        if not current_user.is_authenticated:
            return {}
        today = date.today()
        return {"nav_medicine_count": Medicine.query.count(),
                "nav_inventory_alerts": Medicine.query.filter((Medicine.stock <= Medicine.minimum_stock) | (Medicine.expiry_date <= today + timedelta(days=30))).count(),
                "nav_patient_count": Patient.query.count(),
                "nav_alert_count": Notification.query.filter_by(dismissed=False, is_read=False).count()}

    @app.context_processor
    def csrf_context():
        if "csrf_token" not in session:
            import secrets
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    pages = {
        "/": ("landing", "MediShield"), "/dashboard": ("dashboard", "Dashboard"),
        "/billing": ("billing", "Billing"), "/medicines": ("medicines", "Medicines"),
        "/inventory": ("inventory", "Inventory"), "/patients": ("patients", "Patients"),
        "/reports": ("reports", "Reports"), "/settings": ("settings", "Settings"),
        "/alerts": ("alerts", "Alerts center"), "/about": ("about", "About MediShield"), "/help": ("help", "Help center"),
    }

    def render_page(template, title):
        today = date.today()
        data = {"page_title": title}
        if template == "dashboard":
            day_start = datetime.combine(today, datetime.min.time())
            week_start = datetime.combine(today - timedelta(days=6), datetime.min.time())
            month_periods=[]
            for offset in range(11,-1,-1):
                month_index=today.year*12+today.month-1-offset
                year,month0=divmod(month_index,12); month=month0+1
                period_start=datetime(year,month,1)
                next_year,next_month=(year+1,1) if month==12 else (year,month+1)
                month_periods.append((period_start,datetime(next_year,next_month,1)))
            recent_bills = Bill.query.order_by(Bill.created_at.desc()).limit(6).all()
            data.update(total_medicines=Medicine.query.count(),
                        low_stock_count=Medicine.query.filter(Medicine.stock <= Medicine.minimum_stock).count(),
                        total_patients=Patient.query.count(),
                        expiring_count=Medicine.query.filter(Medicine.expiry_date >= today, Medicine.expiry_date <= today + timedelta(days=30)).count(),
                        today_revenue=db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total), 0)).filter(Bill.created_at >= day_start, Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar(),
                        yesterday_revenue=db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total), 0)).filter(Bill.created_at >= datetime.combine(today-timedelta(days=1), datetime.min.time()), Bill.created_at < day_start, Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar(),
                        patients_today=Patient.query.filter(Patient.created_at >= day_start).count(),
                        expired_count=Medicine.query.filter(Medicine.expiry_date < today).count(),
                        interaction_warnings=Notification.query.filter(Notification.kind == "interaction").count(),
                        pending_overrides=Notification.query.filter_by(kind="override_request", dismissed=False).count(),
                        bills_today=Bill.query.filter(Bill.created_at >= day_start).count(),
                        week_revenue=db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total),0)).filter(Bill.created_at >= datetime.combine(today-timedelta(days=today.weekday()), datetime.min.time()), Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar(),
                        month_revenue=db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total),0)).filter(Bill.created_at >= datetime(today.year,today.month,1), Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar(),
                        bills_week=Bill.query.filter(Bill.created_at >= datetime.combine(today-timedelta(days=today.weekday()), datetime.min.time())).count(),
                        bills_month=Bill.query.filter(Bill.created_at >= datetime(today.year,today.month,1)).count(),
                        interaction_alerts_today=Notification.query.filter(Notification.kind == "interaction", Notification.created_at >= day_start).count(),
                        ai_checks_today=Bill.query.filter(Bill.created_at >= day_start, Bill.ai_status.isnot(None)).count(),
                        ai_high_risk_today=Bill.query.filter(Bill.created_at >= day_start, Bill.ai_status == "SEVERE").count(),
                        ai_moderate_today=Bill.query.filter(Bill.created_at >= day_start, Bill.ai_status == "MODERATE").count(),
                        ai_safe_today=Bill.query.filter(Bill.created_at >= day_start, Bill.ai_status == "SAFE").count(),
                        ai_average_confidence=db.session.query(db.func.coalesce(db.func.avg(Bill.ai_confidence),0)).filter(Bill.ai_status.isnot(None)).scalar(),
                        high_risk_bills=Bill.query.filter(Bill.ai_status == "SEVERE").count(),
                        revenue_trend=[(week_start + timedelta(days=i)).strftime("%a") for i in range(7)],
                        revenue_values=[float(db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total), 0)).filter(Bill.created_at >= (week_start + timedelta(days=i)), Bill.created_at < (week_start + timedelta(days=i+1)), Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar()) for i in range(7)],
                        month_labels=[period[0].strftime("%b %y") for period in month_periods],
                        month_values=[float(db.session.query(db.func.coalesce(db.func.sum(Bill.grand_total),0)).filter(Bill.created_at>=start, Bill.created_at<finish, Bill.status.notin_(("Pending", "Cancelled", "Refunded"))).scalar()) for start,finish in month_periods],
                        severity_counts=[(label, Bill.query.filter(Bill.ai_status==label.upper()).count()) for label in ["Mild","Moderate","Severe"]],
                        stock_overview=[("Low stock", Medicine.query.filter(Medicine.stock<=Medicine.minimum_stock).count()),("In stock", Medicine.query.filter(Medicine.stock>Medicine.minimum_stock).count())],
                        top_sellers=[(row[0], int(row[1])) for row in db.session.query(BillItem.medicine_name, db.func.sum(BillItem.quantity)).join(Bill).group_by(BillItem.medicine_name).order_by(db.func.sum(BillItem.quantity).desc()).limit(5).all()],
                        category_counts=[(row[0], row[1]) for row in db.session.query(Medicine.category, db.func.count(Medicine.id)).group_by(Medicine.category).all()],
                        recent_medicines=Medicine.query.order_by(Medicine.created_at.desc()).limit(5).all(),
                        recent_patients=Patient.query.order_by(Patient.created_at.desc()).limit(5).all(),
                        recent_bills=recent_bills,
                        recent_alerts=Notification.query.filter(Notification.kind == "interaction", Notification.dismissed.is_(False)).order_by(Notification.created_at.desc()).limit(5).all(),
                        recent_activity=Notification.query.filter(Notification.dismissed.is_(False)).order_by(Notification.created_at.desc()).limit(8).all())
        elif template == "medicines":
            data["categories"] = [row[0] for row in db.session.query(Medicine.category).distinct().order_by(Medicine.category).all()]
            data["manufacturers"] = [row[0] for row in db.session.query(Medicine.manufacturer).filter(Medicine.manufacturer != "").distinct().order_by(Medicine.manufacturer).all()]
            data["medicines"] = Medicine.query.order_by(Medicine.created_at.desc()).limit(10).all()
        elif template == "patients":
            data["patients"] = Patient.query.order_by(Patient.created_at.desc()).limit(10).all()
        elif template == "inventory":
            data.update(categories=[x[0] for x in db.session.query(Medicine.category).distinct().order_by(Medicine.category).all()], manufacturers=[x[0] for x in db.session.query(Medicine.manufacturer).distinct().order_by(Medicine.manufacturer).all()], suppliers=[x[0] for x in db.session.query(Medicine.supplier).filter(Medicine.supplier != "").distinct().order_by(Medicine.supplier).all()], total_stock=db.session.query(db.func.coalesce(db.func.sum(Medicine.stock), 0)).scalar(),
                        purchase_value=db.session.query(db.func.coalesce(db.func.sum(Medicine.stock * Medicine.cost_price),0)).scalar(),
                        selling_value=db.session.query(db.func.coalesce(db.func.sum(Medicine.stock * Medicine.price),0)).scalar(),
                        low_stock_count=Medicine.query.filter(Medicine.stock <= Medicine.minimum_stock).count(),
                        expired_count=Medicine.query.filter(Medicine.expiry_date < today).count(),
                        expiring_count=Medicine.query.filter(Medicine.expiry_date >= today, Medicine.expiry_date <= today + timedelta(days=30)).count(),
                        medicines=Medicine.query.order_by(Medicine.expiry_date.asc()).all())
        elif template == "alerts":
            alerts_query=Notification.query if request.args.get("history") == "1" else Notification.query.filter_by(dismissed=False)
            data["alerts"] = alerts_query.order_by(Notification.created_at.desc()).limit(100).all()
        elif template == "reports":
            data["categories"] = [x[0] for x in db.session.query(Medicine.category).distinct().order_by(Medicine.category).all()]
            data["manufacturers"] = [x[0] for x in db.session.query(Medicine.manufacturer).filter(Medicine.manufacturer != "").distinct().order_by(Medicine.manufacturer).all()]
        elif template == "billing":
            data["recent_bills"] = Bill.query.order_by(Bill.created_at.desc()).limit(20).all()
            data["recent_medicines"] = Medicine.query.order_by(Medicine.created_at.desc()).limit(5).all()
        return render_template(template + ".html", **data)

    for path, (template, title) in pages.items():
        app.add_url_rule(path, "page_" + template,
                         lambda template=template, title=title: render_page(template, title))

    @app.before_request
    def protect_workspace():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
            if not expected or supplied != expected:
                return (jsonify(ok=False, message="Security token expired. Refresh and try again.") if request.is_json else "Security token expired. Refresh and try again."), 400
        if request.endpoint and request.endpoint.startswith("page_") and request.endpoint not in {"page_landing", "page_about", "page_help"} and not current_user.is_authenticated:
                return login_manager.unauthorized()

    @app.post("/settings/profile")
    @login_required
    def update_profile():
        name = request.form.get("name", "").strip()
        if not name or len(name) > 120:
            flash("Enter a name up to 120 characters.", "error")
        else:
            current_user.name = name
            db.session.commit()
            flash("Profile updated.", "success")
        return redirect(url_for("page_settings"))

    @app.post("/settings/password")
    @login_required
    def update_password():
        old_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        if not current_user.check_password(old_password):
            flash("Current password is incorrect.", "error")
        elif len(new_password) < 12 or not any(c.isalpha() for c in new_password) or not any(c.isdigit() for c in new_password):
            flash("Use at least 12 characters with both letters and numbers.", "error")
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash("Password changed.", "success")
        return redirect(url_for("page_settings"))

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("not_found.html", page_title="Page not found"), 404

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", page_title="Access restricted", code=403, message="Your account does not have access to this page."), 403

    @app.errorhandler(SQLAlchemyError)
    def database_error(_error):
        app.logger.exception("Database request failed")
        db.session.rollback()
        return render_template("db_error.html", page_title="Database temporarily unavailable"), 503

    @app.errorhandler(500)
    def server_error(_error):
        app.logger.exception("Unhandled application error")
        db.session.rollback()
        return render_template("error.html", page_title="Something went wrong", code=500, message="We could not complete that request. Please try again."), 500

    with app.app_context():
        db.create_all()
        columns = {column["name"] for column in inspect(db.engine).get_columns("notification")}
        if "is_read" not in columns:
            db.session.execute(db.text("ALTER TABLE notification ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT 0"))
            db.session.commit()
        medicine_columns = {column["name"] for column in inspect(db.engine).get_columns("medicine")}
        if "cost_price" not in medicine_columns:
            db.session.execute(db.text("ALTER TABLE medicine ADD COLUMN cost_price FLOAT NOT NULL DEFAULT 0"))
            db.session.commit()
        if "supplier" not in medicine_columns:
            db.session.execute(db.text("ALTER TABLE medicine ADD COLUMN supplier VARCHAR(160) NOT NULL DEFAULT ''"))
            db.session.commit()
        bill_columns = {column["name"] for column in inspect(db.engine).get_columns("bill")}
        if "ai_status" not in bill_columns:
            db.session.execute(db.text("ALTER TABLE bill ADD COLUMN ai_status VARCHAR(20)"))
            db.session.commit()
        if "ai_confidence" not in bill_columns:
            db.session.execute(db.text("ALTER TABLE bill ADD COLUMN ai_confidence INTEGER"))
            db.session.commit()
        seed_database()
        from database.seed_medicines import seed_interaction_demo_medicines
        from database.seed_patients import seed_demo_patients
        seed_interaction_demo_medicines()
        seed_demo_patients()
        seed_interactions()
        seed_billing()
        seed_inventory_alerts()
    return app


def seed_database():
    admin_email=os.environ.get("ADMIN_EMAIL", "admin@medishield.com")
    pharmacist_email=os.environ.get("PHARMACIST_EMAIL", "pharmacist@medishield.com")
    if not User.query.filter_by(email=admin_email).first():
        for name, email, password, role in [
            ("MediShield Admin", admin_email, os.environ.get("ADMIN_PASSWORD", "Admin@123"), "admin"),
            ("MediShield Pharmacist", pharmacist_email, os.environ.get("PHARMACIST_PASSWORD", "Pharma@123"), "pharmacist"),
        ]:
            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
    if Medicine.query.count() == 0:
        samples = [
            ("Crocin 650", "Paracetamol", "650 mg", "Tablet", "Pain relief", "GSK", 28, 120, 20),
            ("Dolo 650", "Paracetamol", "650 mg", "Tablet", "Pain relief", "Micro Labs", 25, 90, 20),
            ("Augmentin 625", "Amoxicillin + Clavulanic acid", "625 mg", "Tablet", "Antibiotics", "GSK", 212, 34, 10),
            ("Azithral 500", "Azithromycin", "500 mg", "Tablet", "Antibiotics", "Alembic", 116, 28, 10),
            ("Pantop 40", "Pantoprazole", "40 mg", "Tablet", "Digestive care", "Aristo", 82, 44, 10),
            ("Cetirizine 10 mg", "Cetirizine", "10 mg", "Tablet", "Allergy care", "Cipla", 32, 5, 10),
            ("ORS Orange", "Oral rehydration salts", "21 g", "Sachet", "Rehydration", "FDC", 22, 76, 15),
            ("Paracetamol 500", "Paracetamol", "500 mg", "Tablet", "Pain relief", "IPCA", 18, 130, 20),
            ("Amoxicillin 500", "Amoxicillin", "500 mg", "Capsule", "Antibiotics", "Mankind", 95, 12, 10),
            ("Glycomet 500", "Metformin", "500 mg", "Tablet", "Diabetes care", "USV", 28, 86, 15),
            ("Brufen 400", "Ibuprofen", "400 mg", "Tablet", "Pain relief", "Abbott", 32, 61, 10),
            ("Omez 20", "Omeprazole", "20 mg", "Capsule", "Digestive care", "Dr. Reddy's", 56, 73, 10),
            ("Atorva 10", "Atorvastatin", "10 mg", "Tablet", "Cardiac care", "Zydus", 44, 52, 10),
            ("Amlong 5", "Amlodipine", "5 mg", "Tablet", "Cardiac care", "Micro Labs", 36, 67, 10),
            ("Uprise D3 60K", "Cholecalciferol", "60000 IU", "Capsule", "Vitamins", "Alkem", 104, 42, 10),
            ("Limcee 500", "Ascorbic acid", "500 mg", "Tablet", "Vitamins", "Abbott", 29, 80, 15),
            ("Shelcal 500", "Calcium + Vitamin D3", "500 mg", "Tablet", "Vitamins", "Torrent", 136, 39, 10),
            ("Montair LC", "Montelukast + Levocetirizine", "10 mg", "Tablet", "Allergy care", "Cipla", 164, 32, 8),
            ("Cipcal 500", "Calcium carbonate", "500 mg", "Tablet", "Vitamins", "Cipla", 76, 55, 10),
            ("Ecosprin 75", "Aspirin", "75 mg", "Tablet", "Cardiac care", "USV", 12, 93, 15),
            ("Glimestar 1", "Glimepiride", "1 mg", "Tablet", "Diabetes care", "Mankind", 52, 48, 10),
            ("Telma 40", "Telmisartan", "40 mg", "Tablet", "Cardiac care", "Glenmark", 89, 40, 10),
            ("Allegra 120", "Fexofenadine", "120 mg", "Tablet", "Allergy care", "Sanofi", 138, 31, 10),
            ("Betadine Ointment", "Povidone iodine", "5%", "Ointment", "First aid", "Win-Medicare", 74, 25, 5),
            ("Cough Syrup", "Dextromethorphan combination", "100 ml", "Syrup", "Cough and cold", "Piramal", 96, 19, 5),
            ("Zincovit", "Multivitamin combination", "Tablet", "Tablet", "Vitamins", "Apex", 112, 37, 10),
            ("Meftal Spas", "Mefenamic acid + Dicyclomine", "Tablet", "Tablet", "Pain relief", "Blue Cross", 64, 29, 8),
            ("Rantac 150", "Ranitidine", "150 mg", "Tablet", "Digestive care", "J.B. Chemicals", 21, 21, 8),
            ("Domstal 10", "Domperidone", "10 mg", "Tablet", "Digestive care", "Torrent", 38, 46, 10),
            ("Azithromycin 250", "Azithromycin", "250 mg", "Tablet", "Antibiotics", "Cipla", 78, 26, 8),
        ]
        for i, (brand, generic, strength, form, category, maker, price, stock, minimum) in enumerate(samples, 1):
            expiry = date.today() + timedelta(days=18 if i == 6 else 180 + (i * 17) % 540)
            db.session.add(Medicine(brand_name=brand, generic_name=generic, strength=strength, dosage_form=form,
                                    category=category, manufacturer=maker, price=price, stock=stock,
                                    minimum_stock=minimum, batch_number=f"MS-{date.today().year}-{i:04d}",
                                    barcode=f"890100000{i:04d}", expiry_date=expiry))
    if Patient.query.count() == 0:
        for name, age, gender, phone in [
            ("Meera Sharma", 42, "Female", "9876501001"), ("Rohan Iyer", 36, "Male", "9876501002"),
            ("Kavita Nair", 58, "Female", "9876501003"), ("Arjun Das", 29, "Male", "9876501004"),
            ("Asha Menon", 67, "Female", "9876501005"), ("Vikram Patel", 51, "Male", "9876501006"),
            ("Neha Kapoor", 33, "Female", "9876501007"), ("Sanjay Rao", 73, "Male", "9876501008"),
            ("Fatima Khan", 24, "Female", "9876501009"), ("Devika Bose", 46, "Female", "9876501010"),
        ]:
            db.session.add(Patient(full_name=name, age=age, gender=gender, phone=phone,
                                   doctor_name="Dr. Priya Shah", allergies="Not recorded"))
    db.session.commit()


def seed_billing():
    if Bill.query.count() or not Medicine.query.first():
        return
    medicines = Medicine.query.order_by(Medicine.id).limit(12).all()
    patients = Patient.query.order_by(Patient.id).all()
    users = User.query.filter(User.role.in_(["admin", "pharmacist"])).order_by(User.id).all()
    now = datetime.now()
    methods = ["Cash", "UPI", "Card", "Pending"]
    for index in range(20):
        medicine = medicines[index % len(medicines)]
        quantity = index % 3 + 1
        subtotal = round(medicine.price * quantity, 2)
        gst = round(subtotal * 0.12, 2)
        created = now - timedelta(days=index, hours=index % 9)
        payment_method = methods[index % len(methods)]
        bill = Bill(invoice_number=f"MS-{created.year}-{index + 1:06d}",
                    patient=patients[index % len(patients)] if patients else None,
                    pharmacist=users[index % len(users)], subtotal=subtotal, gst_amount=gst,
                    discount=0, grand_total=round(subtotal + gst, 2), status="Pending" if payment_method == "Pending" else "Completed",
                    payment_method=payment_method, interaction_count=0,
                    interaction_summary="{}", created_at=created)
        db.session.add(bill)
        db.session.flush()
        db.session.add(BillItem(bill_id=bill.id, medicine_id=medicine.id, medicine_name=medicine.brand_name,
                                generic_name=medicine.generic_name, strength=medicine.strength,
                                quantity=quantity, price=medicine.price, total=subtotal))
    db.session.commit()


def seed_inventory_alerts():
    today = date.today()
    for medicine in Medicine.query.all():
        if medicine.expiry_date < today:
            kind, severity, title = "expired", "Severe", f"Expired medicine: {medicine.brand_name}"
            message = f"Batch {medicine.batch_number or 'not recorded'} expired on {medicine.expiry_date:%d %b %Y}. Quarantine and review this stock."
        elif medicine.stock <= medicine.minimum_stock:
            kind, severity, title = "low_stock", "Warning", f"Low stock: {medicine.brand_name}"
            message = f"{medicine.stock} unit(s) remain; minimum stock is {medicine.minimum_stock}."
        elif medicine.expiry_date <= today + timedelta(days=30):
            kind, severity, title = "expiry", "Warning", f"Expiring soon: {medicine.brand_name}"
            message = f"Batch {medicine.batch_number or 'not recorded'} expires on {medicine.expiry_date:%d %b %Y}."
        else:
            continue
        if not Notification.query.filter_by(title=title).first():
            db.session.add(Notification(kind=kind, severity=severity, title=title, message=message))
    db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
