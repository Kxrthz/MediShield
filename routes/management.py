from datetime import date, timedelta
from urllib.parse import quote
import re
import math
import csv
from io import StringIO

from flask import Blueprint, jsonify, request, send_file, abort, make_response, current_app
from flask_login import current_user, login_required
from sqlalchemy import or_

from extensions import db
from models import Medicine, Patient, Bill, Notification

api_bp = Blueprint("management", __name__, url_prefix="/api")


def error(message, status=400):
    return jsonify(ok=False, message=message), status


def medicine_values(data, medicine=None):
    brand = (data.get("brand_name") or "").strip()
    generic = (data.get("generic_name") or "").strip()
    if not brand or not generic:
        raise ValueError("Brand name and generic name are required.")
    try:
        price = float(data.get("price", ""))
        cost_price = float(data.get("cost_price", 0) or 0)
        stock = int(data.get("stock", 0))
        minimum = int(data.get("minimum_stock", 10))
        expiry = date.fromisoformat(data.get("expiry_date", ""))
    except (TypeError, ValueError):
        raise ValueError("Enter a valid price, stock quantity, and expiry date.")
    if not math.isfinite(price) or price <= 0 or not math.isfinite(cost_price) or cost_price < 0 or cost_price > price:
        raise ValueError("Price must be positive and purchase cost must be between zero and the selling price.")
    if stock < 0 or minimum < 0:
        raise ValueError("Stock values cannot be negative.")
    if expiry < date.today():
        raise ValueError("Expiry date cannot be in the past.")
    image_url=(data.get("image_url") or "").strip() or None
    if image_url and not image_url.startswith(("https://", "http://")):
        raise ValueError("Image URL must use HTTP or HTTPS.")
    barcode = (data.get("barcode") or "").strip() or None
    if barcode and Medicine.query.filter(Medicine.barcode == barcode, Medicine.id != (medicine.id if medicine else 0)).first():
        raise ValueError("That barcode is already assigned to another medicine.")
    return dict(brand_name=brand, generic_name=generic, strength=(data.get("strength") or "").strip(),
                dosage_form=(data.get("dosage_form") or "Tablet").strip(), category=(data.get("category") or "Other").strip(),
                manufacturer=(data.get("manufacturer") or "").strip(), supplier=(data.get("supplier") or "").strip(), barcode=barcode, price=price, cost_price=cost_price, stock=stock,
                minimum_stock=minimum, batch_number=(data.get("batch_number") or "").strip(), expiry_date=expiry,
                image_url=image_url)


@api_bp.get("/medicines")
@login_required
def medicines():
    query = Medicine.query
    term = request.args.get("q", "").strip()
    if term:
        match = f"%{term}%"
        query = query.filter(or_(Medicine.brand_name.ilike(match), Medicine.generic_name.ilike(match),
                                 Medicine.barcode.ilike(match), Medicine.manufacturer.ilike(match)))
    if request.args.get("category"):
        query = query.filter_by(category=request.args["category"])
    if request.args.get("manufacturer"):
        query = query.filter_by(manufacturer=request.args["manufacturer"])
    sort = request.args.get("sort", "newest")
    column = {"name": Medicine.brand_name, "stock": Medicine.stock, "expiry": Medicine.expiry_date,
              "price": Medicine.price, "newest": Medicine.created_at}.get(sort, Medicine.created_at)
    if request.args.get("order") == "desc" or sort == "newest":
        column = column.desc()
    page = max(1, request.args.get("page", 1, type=int))
    result = query.order_by(column).paginate(page=page, per_page=10, error_out=False)
    return jsonify(items=[m.to_dict() for m in result.items], page=page, pages=result.pages, total=result.total,
                   categories=[x[0] for x in db.session.query(Medicine.category).distinct().order_by(Medicine.category).all()],
                   manufacturers=[x[0] for x in db.session.query(Medicine.manufacturer).filter(Medicine.manufacturer != "").distinct().order_by(Medicine.manufacturer).all()])


@api_bp.post("/medicines")
@login_required
def add_medicine():
    if current_user.role not in ("admin", "pharmacist"):
        return error("Your account does not have permission to add medicines.", 403)
    try:
        item = Medicine(**medicine_values(request.get_json(silent=True) or {}))
        db.session.add(item)
        db.session.flush()
        db.session.add(Notification(kind="medicine_added",severity="Success",title="Medicine added",message=f"{item.brand_name} was added to the medicine catalog."))
        db.session.commit()
        return jsonify(ok=True, message="Medicine added.", item=item.to_dict()), 201
    except ValueError as exc:
        db.session.rollback()
        return error(str(exc))
    except Exception:
        db.session.rollback()
        return error("Could not save medicine. Check the barcode and try again.")


@api_bp.route("/medicines/<int:item_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def medicine_detail(item_id):
    item = db.get_or_404(Medicine, item_id)
    if request.method == "GET":
        return jsonify(item=item.to_dict())
    if request.method == "DELETE":
        if current_user.role != "admin":
            return error("Only an administrator can delete medicines.", 403)
        db.session.delete(item)
        db.session.commit()
        return jsonify(ok=True, message="Medicine deleted successfully.")
    if current_user.role not in ("admin", "pharmacist"):
        return error("Your account does not have permission to update medicines.", 403)
    try:
        for key, value in medicine_values(request.get_json(silent=True) or {}, item).items():
            setattr(item, key, value)
        db.session.add(Notification(kind="medicine_updated", severity="Info", title="Medicine updated", message=f"{item.brand_name} was updated in the medicine catalog."))
        db.session.commit()
        return jsonify(ok=True, message="Medicine updated.", item=item.to_dict())
    except ValueError as exc:
        db.session.rollback()
        return error(str(exc))
    except Exception:
        db.session.rollback()
        return error("Could not update medicine. Check the barcode and try again.")


def patient_values(data, patient=None):
    name = (data.get("full_name") or "").strip()
    if not name:
        raise ValueError("Patient name is required.")
    try:
        age = int(data.get("age", ""))
    except (TypeError, ValueError):
        raise ValueError("Enter a valid age between 0 and 120.")
    if not 0 <= age <= 120:
        raise ValueError("Age must be between 0 and 120.")
    phone = (data.get("phone") or "").strip()
    if phone and not re.fullmatch(r"\d{10}", phone):
        raise ValueError("Phone number must contain exactly 10 digits.")
    if phone and Patient.query.filter(Patient.phone == phone, Patient.id != (patient.id if patient else 0)).first():
        raise ValueError("That phone number is already assigned to another patient.")
    email = (data.get("email") or "").strip().lower()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    return dict(full_name=name, age=age, gender=(data.get("gender") or "Prefer not to say").strip(), phone=phone or None,
                email=email or None, blood_group=(data.get("blood_group") or "").strip() or None,
                allergies=(data.get("allergies") or "").strip() or None, doctor_name=(data.get("doctor_name") or "").strip() or None,
                notes=(data.get("notes") or "").strip() or None)


@api_bp.get("/patients")
@login_required
def patient_list():
    query = Patient.query
    term = request.args.get("q", "").strip()
    if term:
        match = f"%{term}%"
        query = query.filter(or_(Patient.full_name.ilike(match), Patient.phone.ilike(match), Patient.email.ilike(match)))
    result = query.order_by(Patient.created_at.desc()).paginate(page=max(1, request.args.get("page", 1, type=int)), per_page=10, error_out=False)
    return jsonify(items=[p.to_dict() for p in result.items], page=result.page, pages=result.pages, total=result.total)


@api_bp.post("/patients")
@login_required
def add_patient():
    if current_user.role not in ("admin", "pharmacist"):
        return error("Your account does not have permission to add patients.", 403)
    try:
        item = Patient(**patient_values(request.get_json(silent=True) or {}))
        db.session.add(item)
        db.session.flush()
        db.session.add(Notification(kind="patient_added",severity="Success",title="Patient added",message=f"Patient record created for {item.full_name}."))
        db.session.commit()
        return jsonify(ok=True, message="Patient added.", item=item.to_dict()), 201
    except ValueError as exc:
        db.session.rollback()
        return error(str(exc))


@api_bp.route("/patients/<int:item_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def patient_detail(item_id):
    item = db.get_or_404(Patient, item_id)
    if request.method == "GET":
        return jsonify(item=item.to_dict())
    if request.method == "DELETE":
        if current_user.role != "admin":
            return error("Only an administrator can delete patient records.", 403)
        db.session.delete(item)
        db.session.commit()
        return jsonify(ok=True, message="Patient deleted successfully.")
    if current_user.role not in ("admin", "pharmacist"):
        return error("Your account does not have permission to update patient records.", 403)
    try:
        for key, value in patient_values(request.get_json(silent=True) or {}, item).items():
            setattr(item, key, value)
        db.session.commit()
        return jsonify(ok=True, message="Patient updated.", item=item.to_dict())
    except ValueError as exc:
        db.session.rollback()
        return error(str(exc))


@api_bp.post("/inventory/<int:item_id>/stock")
@login_required
def adjust_stock(item_id):
    if current_user.role not in ("admin", "pharmacist"):
        return error("Your account does not have permission to change stock.", 403)
    item = db.get_or_404(Medicine, item_id)
    data = request.get_json(silent=True) or {}
    amount = data.get("amount", 0)
    if not isinstance(amount, int) or amount == 0:
        return error("Enter a whole-number stock adjustment.")
    if item.stock + amount < 0:
        return error("Stock cannot be reduced below zero.")
    item.stock += amount
    db.session.add(Notification(kind="inventory_updated", severity="Info", title="Inventory updated", message=f"{item.brand_name}: stock adjusted by {amount:+d} unit(s)."))
    db.session.commit()
    return jsonify(ok=True, message="Stock updated.", item=item.to_dict())


@api_bp.get("/search")
@login_required
def global_search():
    term = request.args.get("q", "").strip()
    if len(term) < 2:
        return jsonify(medicines=[], patients=[], invoices=[], inventory=[], reports=[], notifications=[])
    match = f"%{term}%"
    meds = Medicine.query.filter(or_(Medicine.brand_name.ilike(match), Medicine.generic_name.ilike(match))).limit(5).all()
    patients = Patient.query.filter(or_(Patient.full_name.ilike(match), Patient.phone.ilike(match))).limit(5).all()
    bills=Bill.query.filter(Bill.invoice_number.ilike(match)).order_by(Bill.created_at.desc()).limit(5).all()
    inventory=Medicine.query.filter(or_(Medicine.batch_number.ilike(match), Medicine.manufacturer.ilike(match))).limit(5).all()
    reports=[{"label": label, "meta": "Report", "url": "/reports"} for label in ["Daily sales", "Weekly sales", "Monthly sales", "Yearly revenue", "Inventory report", "Interaction report"] if term.lower() in label.lower()][:5]
    notifications=Notification.query.filter(or_(Notification.title.ilike(match), Notification.message.ilike(match)), Notification.dismissed.is_(False)).order_by(Notification.created_at.desc()).limit(5).all()
    return jsonify(medicines=[{"id":m.id,"label":m.brand_name,"meta":m.generic_name,"url":f"/medicines?q={quote(m.brand_name)}"} for m in meds],
                   patients=[{"id":p.id,"label":p.full_name,"meta":p.phone or "Patient","url":f"/patients?patient={quote(p.full_name)}"} for p in patients],
                   invoices=[{"id":b.id,"label":b.invoice_number,"meta":f"{b.patient.full_name if b.patient else 'Walk-in'} · ₹{b.grand_total:,.2f}","url":f"/billing?invoice={b.invoice_number}"} for b in bills], inventory=[{"id":m.id,"label":m.brand_name,"meta":f"Batch {m.batch_number or '—'} · {m.manufacturer}","url":"/inventory"} for m in inventory], reports=reports, notifications=[{"id":n.id,"label":n.title,"meta":n.severity,"url":"/alerts"} for n in notifications])


@api_bp.get("/patients/<int:item_id>/history")
@login_required
def patient_history(item_id):
    from models import BillItem
    patient=Patient.query.get_or_404(item_id)
    bills=Bill.query.filter_by(patient_id=patient.id).order_by(Bill.created_at.desc()).all()
    purchases=[]; interactions=[]
    import json
    for b in bills:
        purchases.append({"invoice":b.invoice_number,"date":b.created_at.isoformat(),"total":b.grand_total,"items":[i.medicine_name for i in b.items],"interaction_count":b.interaction_count})
        summary=json.loads(b.interaction_summary or "{}")
        for level in ("mild","moderate","severe"):
            for event in summary.get(level,[]): interactions.append({"date":b.created_at.isoformat(),"invoice":b.invoice_number,"severity":event.get("severity"),"pair":f"{event.get('medicine_one')} + {event.get('medicine_two')}","recommendation":event.get("recommendation")})
    from collections import Counter
    most_purchased=Counter(i.medicine_name for b in bills for i in b.items).most_common(1)
    return jsonify(patient=patient.to_dict(),total_purchases=round(sum(b.grand_total for b in bills),2),total_bills=len(bills),most_purchased=most_purchased[0][0] if most_purchased else None,last_purchase=bills[0].created_at.isoformat() if bills else None,last_visit=bills[0].created_at.isoformat() if bills else None,bills=purchases,interactions=interactions,doctor_notes=patient.notes or "")


@api_bp.post("/alerts/read-all")
@login_required
def read_all_alerts():
    Notification.query.filter_by(dismissed=False, is_read=False).update({Notification.is_read: True}, synchronize_session=False)
    db.session.add(Notification(kind="notification_read", severity="Info", title="Notifications marked read", message="All active notifications were marked as read.", is_read=True))
    db.session.commit()
    return jsonify(ok=True)


@api_bp.get("/backup/<kind>.csv")
@login_required
def export_backup_csv(kind):
    output=StringIO(); writer=csv.writer(output)
    if kind == "medicines":
        writer.writerow(["brand_name","generic_name","strength","dosage_form","category","manufacturer","supplier","barcode","price","cost_price","stock","minimum_stock","batch_number","expiry_date"])
        for m in Medicine.query.order_by(Medicine.id).yield_per(500): writer.writerow([m.brand_name,m.generic_name,m.strength,m.dosage_form,m.category,m.manufacturer,m.supplier or "",m.barcode or "",m.price,m.cost_price or 0,m.stock,m.minimum_stock,m.batch_number,m.expiry_date.isoformat()])
    elif kind == "patients":
        writer.writerow(["full_name","age","gender","phone","email","blood_group","allergies","doctor_name","notes"])
        for p in Patient.query.order_by(Patient.id).yield_per(500): writer.writerow([p.full_name,p.age,p.gender,p.phone or "",p.email or "",p.blood_group or "",p.allergies or "",p.doctor_name or "",p.notes or ""])
    elif kind == "bills":
        writer.writerow(["invoice_number","created_at","patient","subtotal","gst_amount","discount","grand_total","payment_method","status"])
        for b in Bill.query.order_by(Bill.created_at).yield_per(500): writer.writerow([b.invoice_number,b.created_at.isoformat(),b.patient.full_name if b.patient else "Walk-in",b.subtotal,b.gst_amount,b.discount,b.grand_total,b.payment_method,b.status])
    else: abort(404)
    response=make_response("\ufeff"+output.getvalue()); response.headers["Content-Type"]="text/csv; charset=utf-8"; response.headers["Content-Disposition"]=f"attachment; filename=medishield-{kind}-backup.csv"; return response


@api_bp.get("/backup/database")
@login_required
def backup_database():
    import os
    import sqlite3
    if not db.engine.dialect.name == "sqlite": abort(501)
    path=db.engine.url.database
    if not path or path == ":memory:": abort(501)
    if not os.path.isabs(path): path=os.path.join(current_app.root_path,path)
    if not os.path.isfile(path): abort(404)
    from io import BytesIO
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
        with sqlite3.connect(":memory:") as snapshot:
            source.backup(snapshot)
            content=snapshot.serialize()
    return send_file(BytesIO(content),as_attachment=True,download_name="medishield-backup.db",mimetype="application/octet-stream")


@api_bp.post("/backup/import/<kind>")
@login_required
def import_backup_csv(kind):
    if current_user.role not in ("admin", "pharmacist"): return error("Only an administrator or pharmacist can import records.",403)
    upload=request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".csv"): return error("Choose a CSV file.")
    if upload.content_length and upload.content_length > 5_000_000: return error("CSV file must be smaller than 5 MB.",413)
    try:
        reader=csv.DictReader(upload.stream.read().decode("utf-8-sig").splitlines())
        count=0
        for row in reader:
            if count >= 1000: raise ValueError("Import is limited to 1,000 rows per file.")
            if kind=="medicines": db.session.add(Medicine(**medicine_values(row)))
            elif kind=="patients": db.session.add(Patient(**patient_values(row)))
            else: abort(404)
            count+=1
        db.session.commit()
        return jsonify(ok=True,message=f"Imported {count} {kind} record(s).",count=count)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        db.session.rollback(); return error(str(exc))
    except Exception:
        db.session.rollback(); return error("Import could not be completed. Check required columns and duplicate values.")
