import json
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, abort, jsonify, make_response, request, send_file, session
from flask_login import current_user, login_required
from sqlalchemy import or_

from extensions import db
from models import Bill, BillItem, DrugInteraction, Medicine, Notification, OverrideAudit, Patient, User
from utils.interaction_engine import check_interactions
from utils.pdf_generator import interaction_report_pdf, invoice_pdf
from ai.interaction_service import analyze_interactions, normalize_medicine

billing_bp = Blueprint("billing", __name__)
PAYMENT_METHODS = {"Cash", "UPI", "Card", "Pending"}


def money(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise InvalidOperation("Amount must be finite.")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def remember_failure(message):
    db.session.add(Notification(kind="failed_bill", severity="Warning", title="Billing was not completed", message=message))
    db.session.commit()


def load_cart(payload, validate_stock=True):
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("Add at least one medicine to the bill.")
    today = date.today()
    result, subtotal, reserved = [], Decimal("0.00"), {}
    for line in items:
        if not isinstance(line, dict):
            raise ValueError("Invalid cart item.")
        try:
            medicine_id = int(line.get("medicine_id", line.get("id")))
            quantity = int(line.get("quantity", 0))
        except (TypeError, ValueError):
            raise ValueError("Each cart item must have a valid medicine and quantity.")
        if quantity <= 0:
            raise ValueError("Medicine quantity must be greater than zero.")
        medicine = db.session.get(Medicine, medicine_id)
        if not medicine:
            raise ValueError("A selected medicine is no longer available.")
        if medicine.expiry_date < today:
            raise ValueError(f"{medicine.brand_name} is expired and cannot be billed.")
        already_requested = reserved.get(medicine.id, 0)
        if validate_stock and already_requested + quantity > medicine.stock:
            raise ValueError(f"Only {medicine.stock} unit(s) of {medicine.brand_name} are in stock.")
        reserved[medicine.id] = already_requested + quantity
        line_total = money(money(medicine.price) * quantity)
        result.append((medicine, quantity, line_total))
        subtotal += line_total
    return result, money(subtotal)


def cart_safety(lines):
    return check_interactions([medicine for medicine, _quantity, _total in lines])


def patient_ai_context(patient):
    if not patient:
        return {}
    return {"age": patient.age, "gender": (patient.gender or "")[:40],
            "known_allergies": (patient.allergies or "")[:500],
            "doctor_notes": (patient.notes or "")[:800]}


def analyze_lines(lines, patient):
    medicines = [normalize_medicine(medicine, quantity) for medicine, quantity, _total in lines]
    import secrets
    scope = session.get("ai_cache_scope")
    if not scope:
        scope = secrets.token_urlsafe(16)
        session["ai_cache_scope"] = scope
    return analyze_interactions(medicines, patient_ai_context(patient), cache_scope=scope)


def notify_ai_findings(analysis):
    events = []
    if analysis.get("overall_status") == "SEVERE":
        events.append(("ai_severe", "Danger", "AI Guardian severe warning", analysis.get("summary", "Severe result requires pharmacist review.")))
    if analysis.get("allergy_warnings"):
        details = "; ".join(f"{x['medicine']} · {x['allergen']}" for x in analysis["allergy_warnings"][:5])
        events.append(("ai_allergy", "Danger", "AI Guardian allergy warning", details))
    if not analysis.get("available"):
        events.append(("ai_unavailable", "Warning", "AI Guardian unavailable", analysis.get("summary", "Live analysis could not be completed.")))
    cutoff = datetime.now() - timedelta(hours=1)
    for kind, severity, title, message in events:
        recent = Notification.query.filter_by(kind=kind, title=title, dismissed=False).filter(Notification.created_at >= cutoff).first()
        if not recent:
            db.session.add(Notification(kind=kind, severity=severity, title=title, message=message[:1200]))
    if events:
        db.session.commit()


def ai_summary_snapshot(analysis):
    bucket = {"MILD": "mild", "MODERATE": "moderate", "SEVERE": "severe"}
    groups = {"mild": [], "moderate": [], "severe": [], "safe": []}
    normalized = []
    for item in analysis.get("interactions", []):
        row = {"medicine_one": item["medicine_1"], "medicine_two": item["medicine_2"],
               "severity": item["severity"].title(), "effect": item["reason"],
               "recommendation": item["recommendation"]}
        groups[bucket[item["severity"]]].append(row)
        normalized.append(item)
    status = analysis.get("overall_status", "UNCERTAIN")
    score = {"SAFE": 0, "MILD": 20, "MODERATE": 50, "SEVERE": 90, "UNCERTAIN": 0}.get(status, 0)
    return {**analysis, **groups, "interactions": normalized,
            "total_interactions": len(normalized), "safety_score": score,
            "safety_label": status.title(), "has_severe": status == "SEVERE"}


@billing_bp.post("/api/ai/check-interactions")
@login_required
def ai_check_interactions():
    try:
        payload = request.get_json(silent=True) or {}
        lines, _subtotal = load_cart(payload)
        if len(lines) > 20:
            return jsonify(ok=False, message="AI Guardian supports up to 20 distinct medicines per check."), 400
        patient_id = payload.get("patient_id") or None
        patient = db.session.get(Patient, int(patient_id)) if patient_id else None
        if patient_id and not patient:
            return jsonify(ok=False, message="Selected patient was not found."), 400
        analysis = analyze_lines(lines, patient)
        notify_ai_findings(analysis)
        return jsonify(ok=True, analysis=analysis)
    except (ValueError, TypeError) as exc:
        return jsonify(ok=False, message=str(exc)), 400


@billing_bp.get("/api/billing/medicines")
@login_required
def medicine_search():
    term = request.args.get("q", "").strip()
    query = Medicine.query
    if term:
        match = f"%{term}%"
        query = query.filter(or_(Medicine.brand_name.ilike(match), Medicine.generic_name.ilike(match),
                                 Medicine.barcode.ilike(match), Medicine.category.ilike(match),
                                 Medicine.manufacturer.ilike(match)))
    else:
        query = query.order_by(Medicine.created_at.desc())
    items = query.limit(12).all()
    return jsonify(items=[m.to_dict() for m in items])


@billing_bp.get("/api/billing/patients")
@login_required
def patient_search():
    term = request.args.get("q", "").strip()
    query = Patient.query
    if term:
        match = f"%{term}%"
        query = query.filter(or_(Patient.full_name.ilike(match), Patient.phone.ilike(match),
                                 Patient.email.ilike(match), Patient.id.cast(db.String).ilike(match)))
    return jsonify(items=[{"id":p.id,"full_name":p.full_name,"age":p.age,"gender":p.gender or "",
                           "phone":p.phone or "","allergies":p.allergies or "","notes":(p.notes or "")[:800]}
                          for p in query.order_by(Patient.full_name).limit(10).all()])


@billing_bp.post("/api/billing/interaction-check")
@login_required
def interaction_check():
    try:
        lines, _subtotal = load_cart(request.get_json(silent=True) or {})
        return jsonify(ok=True, safety=cart_safety(lines))
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400


@billing_bp.get("/api/bills")
@login_required
def bill_history():
    query = Bill.query
    term = request.args.get("q", "").strip()
    if term:
        query = query.filter(Bill.invoice_number.ilike(f"%{term}%"))
    patient_id = request.args.get("patient_id", type=int)
    payment_method = request.args.get("payment_method", "").strip()
    status = request.args.get("status", "").strip()
    if payment_method in PAYMENT_METHODS:
        query = query.filter_by(payment_method=payment_method)
    if status in {"Completed", "Pending", "Cancelled", "Refunded"}:
        query = query.filter_by(status=status)
    if request.args.get("patient"):
        query = query.join(Patient).filter(Patient.full_name.ilike(f"%{request.args['patient'].strip()}%"))
    if patient_id:
        query = query.filter_by(patient_id=patient_id)
    start = request.args.get("start")
    end = request.args.get("end")
    try:
        if start:
            query = query.filter(Bill.created_at >= datetime.combine(date.fromisoformat(start), time.min))
        if end:
            query = query.filter(Bill.created_at < datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min))
    except ValueError:
        return jsonify(ok=False, message="Enter a valid date range."), 400
    rows = query.order_by(Bill.created_at.desc()).limit(100).all()
    return jsonify(items=[{"id":b.id,"invoice_number":b.invoice_number,"patient":b.patient.full_name if b.patient else "Walk-in customer",
                          "created_at":b.created_at.isoformat(),"grand_total":b.grand_total,"status":b.status,
                          "payment_method":b.payment_method,"interaction_count":b.interaction_count} for b in rows])


@billing_bp.get("/api/bills/<int:bill_id>")
@login_required
def bill_detail(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    safety = json.loads(bill.interaction_summary or "{}")
    return jsonify(item={"id":bill.id,"invoice_number":bill.invoice_number,
                         "patient":bill.patient.full_name if bill.patient else "Walk-in customer",
                         "pharmacist":bill.pharmacist.name if bill.pharmacist else "",
                         "created_at":bill.created_at.isoformat(),"subtotal":bill.subtotal,"gst_amount":bill.gst_amount,
                         "discount":bill.discount,"grand_total":bill.grand_total,"status":bill.status,
                         "ai_status":bill.ai_status,"ai_confidence":bill.ai_confidence,
                         "override_reason":bill.override_reason,
                         "payment_method":bill.payment_method,"items":[{"medicine_name":i.medicine_name,
                         "generic_name":i.generic_name,"strength":i.strength,"quantity":i.quantity,
                         "price":i.price,"total":i.total} for i in bill.items],
                         "safety":safety,
                         "pdf_url":f"/bills/{bill.id}/invoice.pdf",
                         "interaction_pdf_url":f"/bills/{bill.id}/interaction-warning.pdf" if safety.get("moderate") or safety.get("severe") or safety.get("allergy_warnings") else None})


@billing_bp.post("/api/bills/<int:bill_id>/cancel")
@login_required
def cancel_bill(bill_id):
    bill=db.get_or_404(Bill,bill_id)
    if bill.status in {"Cancelled", "Refunded"}:
        return jsonify(ok=False,message="This invoice is already cancelled or refunded."),409
    if bill.pharmacist_id != current_user.id and current_user.role != "admin":
        return jsonify(ok=False,message="Only the invoice creator or an administrator can cancel it."),403
    for line in bill.items:
        if line.medicine:
            line.medicine.stock += line.quantity
    bill.status="Cancelled"
    db.session.add(Notification(kind="bill_cancelled",severity="Warning",title="Bill cancelled",message=f"{bill.invoice_number} was cancelled and its stock was restored.",bill=bill))
    db.session.commit()
    return jsonify(ok=True,message="Invoice cancelled and stock restored.")


@billing_bp.post("/api/bills")
@login_required
def create_bill():
    payload = request.get_json(silent=True) or {}
    try:
        lines, subtotal = load_cart(payload)
        patient_id = payload.get("patient_id") or None
        patient = db.session.get(Patient, int(patient_id)) if patient_id else None
        if patient_id and not patient:
            raise ValueError("Select a valid patient or choose walk-in customer.")
        if len(lines) > 20:
            raise ValueError("AI Guardian supports up to 20 distinct medicines per bill.")
        ai_result = analyze_lines(lines, patient)
        notify_ai_findings(ai_result)
        ai_snapshot = ai_summary_snapshot(ai_result)
        if ai_result["overall_status"] == "SEVERE":
            if current_user.role != "admin":
                return jsonify(ok=False, blocked=True, message="Billing blocked due to a severe interaction. Admin override is required.", ai=ai_result), 409
        elif ai_result["billing_action"] == "ACKNOWLEDGEMENT_REQUIRED" and payload.get("patient_acknowledged") is not True:
            return jsonify(ok=False, acknowledgement_required=True,
                           message="Review the AI Guardian warning and acknowledge before billing.", ai=ai_result), 409
        discount = money(payload.get("discount", 0))
        if discount < 0 or discount > subtotal:
            raise ValueError("Discount must be between ₹0 and the subtotal.")
        payment = payload.get("payment_method", "Cash")
        if payment not in PAYMENT_METHODS:
            raise ValueError("Choose a supported payment method.")
        taxable = subtotal - discount
        gst = money(taxable * Decimal("0.12"))
        total = money(taxable + gst)
        safety = ai_snapshot
        override = payload.get("override") or {}
        override_reason = None
        if ai_result["overall_status"] == "SEVERE":
            if current_user.role != "admin":
                db.session.add(Notification(kind="interaction_blocked",severity="Danger",title="Severe interaction blocked",message="Billing was blocked pending administrator review.")); db.session.add(Notification(kind="override_request",severity="Warning",title="New override request",message="An administrator must review the severe interaction before billing can continue.")); db.session.commit()
                return jsonify(ok=False, blocked=True, message="Billing blocked by a severe interaction. An administrator must review and override.", safety=safety), 409
            admin_password = str(override.get("password", ""))
            override_reason = str(override.get("reason", "")).strip()
            if not current_user.check_password(admin_password) or not override_reason:
                remember_failure("Severe interaction override was rejected because administrator verification or reason was missing.")
                return jsonify(ok=False, blocked=True, message="Admin password confirmation and an override reason are required.", safety=safety), 403

        stamp = datetime.now()
        bill = Bill(invoice_number=f"pending-{uuid.uuid4().hex}", patient=patient, pharmacist=current_user,
                    subtotal=float(subtotal), gst_amount=float(gst), discount=float(discount), grand_total=float(total),
                    status="Pending" if payment == "Pending" else "Completed", payment_method=payment,
                    interaction_count=safety["total_interactions"], ai_status=ai_result["overall_status"],
                    ai_confidence=ai_result["confidence"], override_reason=override_reason,
                    interaction_summary=json.dumps(safety, ensure_ascii=False), created_at=stamp)
        db.session.add(bill)
        db.session.flush()
        bill.invoice_number = f"MS-{stamp.year}-{bill.id:06d}"
        for medicine, quantity, line_total in lines:
            db.session.add(BillItem(bill=bill, medicine=medicine, medicine_name=medicine.brand_name,
                                    generic_name=medicine.generic_name, strength=medicine.strength,
                                    quantity=quantity, price=float(money(medicine.price)), total=float(line_total)))
            medicine.stock -= quantity
        if override_reason:
            db.session.add(OverrideAudit(bill=bill, admin_id=current_user.id, reason=override_reason))
            Notification.query.filter_by(kind="override_request", dismissed=False).update({Notification.dismissed: True}, synchronize_session=False)
            db.session.add(Notification(kind="override_approved", severity="Warning", title="Admin override completed", message=f"{bill.invoice_number} was approved with a recorded reason.", bill=bill))
        db.session.add(Notification(kind="successful_bill", severity="Success", title="Bill completed",
                                    message=f"{bill.invoice_number} · ₹{bill.grand_total:,.2f}", bill=bill))
        for alert in ai_snapshot["interactions"]:
            severity=alert["severity"].title()
            db.session.add(Notification(kind="interaction", severity=severity,
                                        title=f"AI Guardian {severity}: {alert['medicine_1']} + {alert['medicine_2']}",
                                        message=alert["reason"], bill=bill))
        for warning in ai_result.get("allergy_warnings", []):
            db.session.add(Notification(kind="ai_allergy", severity="Danger", title="AI Guardian allergy warning",
                                        message=f"{warning['medicine']} · {warning['allergen']}: {warning['reason']}", bill=bill))
        for medicine, _quantity, _line_total in lines:
            if medicine.stock <= medicine.minimum_stock:
                db.session.add(Notification(kind="low_stock", severity="Warning", title=f"Low stock: {medicine.brand_name}",
                                            message=f"{medicine.stock} unit(s) remain after invoice {bill.invoice_number}.", bill=bill))
        db.session.commit()
        return jsonify(ok=True, message="Invoice created and stock updated.", bill={"id":bill.id,"invoice_number":bill.invoice_number,
                       "grand_total":bill.grand_total,"pdf_url":f"/bills/{bill.id}/invoice.pdf",
                       "interaction_pdf_url":f"/bills/{bill.id}/interaction-warning.pdf" if safety["moderate"] or safety["severe"] or safety["allergy_warnings"] else None,
                       "safety":safety,"ai":ai_result}), 201
    except ValueError as exc:
        db.session.rollback()
        remember_failure(str(exc))
        return jsonify(ok=False, message=str(exc)), 400
    except (InvalidOperation, TypeError):
        db.session.rollback()
        remember_failure("The bill contains an invalid amount or quantity.")
        return jsonify(ok=False, message="Enter valid amounts and quantities."), 400
    except Exception:
        db.session.rollback()
        remember_failure("An unexpected error prevented billing. No stock was deducted.")
        return jsonify(ok=False, message="Billing could not be completed. No stock was deducted."), 500


@billing_bp.get("/bills/<int:bill_id>/invoice.pdf")
@login_required
def download_invoice(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    return send_file(__import__("io").BytesIO(invoice_pdf(bill)), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{bill.invoice_number}.pdf")


@billing_bp.get("/bills/<int:bill_id>/interaction-warning.pdf")
@login_required
def download_interaction_report(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    summary = json.loads(bill.interaction_summary or "{}")
    if summary.get("overall_status"):
        warnings = [{"medicine_1":x["medicine_1"],"medicine_2":x["medicine_2"],"severity":x["severity"],"reason":x["reason"],"recommendation":x["recommendation"]} for x in summary.get("interactions", [])]
    else:
        warnings = summary.get("moderate", []) + summary.get("severe", [])
    if not warnings and not summary.get("allergy_warnings"):
        abort(404)
    medicines = [f"{i.medicine_name} ({i.generic_name} {i.strength})" for i in bill.items]
    content = interaction_report_pdf(bill.patient.full_name if bill.patient else None, medicines, warnings, bill.invoice_number,
                                    ai_summary=summary if summary.get("overall_status") else None,
                                    pharmacist=bill.pharmacist.name if bill.pharmacist else "", timestamp=bill.created_at.strftime("%d %b %Y %I:%M %p"))
    return send_file(__import__("io").BytesIO(content), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{bill.invoice_number}-interaction-warning.pdf")


@billing_bp.get("/api/alerts")
@login_required
def alerts_list():
    rows = Notification.query.filter_by(dismissed=False).order_by(Notification.is_read.asc(), Notification.created_at.desc()).limit(100).all()
    return jsonify(items=[{"id":n.id,"kind":n.kind,"severity":n.severity,"title":n.title,"message":n.message,
                          "created_at":n.created_at.isoformat(),"bill_id":n.bill_id,"is_read":n.is_read} for n in rows])


@billing_bp.post("/api/alerts/<int:alert_id>/read")
@login_required
def read_alert(alert_id):
    alert = db.get_or_404(Notification, alert_id)
    alert.is_read = True
    db.session.add(Notification(kind="notification_read", severity="Info", title="Notification read", message=f"{alert.title} was marked as read.", is_read=True))
    db.session.commit()
    return jsonify(ok=True, unread=Notification.query.filter_by(dismissed=False, is_read=False).count())


@billing_bp.post("/api/alerts/<int:alert_id>/delete")
@login_required
def dismiss_alert(alert_id):
    alert = db.get_or_404(Notification, alert_id)
    alert.dismissed = True
    db.session.commit()
    return jsonify(ok=True, message="Notification dismissed.")


@billing_bp.get("/api/reports/<report_type>.<extension>")
@login_required
def export_report(report_type, extension):
    from io import StringIO, BytesIO
    import csv
    from calendar import monthrange
    from sqlalchemy import func
    allowed = {"daily-sales", "weekly-sales", "monthly-sales", "yearly-revenue", "inventory", "low-stock", "expiry", "interactions", "patient-purchases", "top-medicines", "daily-revenue", "monthly-revenue", "dangerous-pairs", "payment-method", "medicine-category", "revenue-by-day"}
    if extension not in {"csv", "pdf"} or report_type not in allowed:
        abort(404)
    today = date.today()
    start_of_day = datetime.combine(today, time.min)
    start_week = datetime.combine(today-timedelta(days=today.weekday()), time.min)
    start_month = datetime(today.year,today.month,1)
    start_year = datetime(today.year,1,1)
    bills = Bill.query.order_by(Bill.created_at.asc()).all()
    if report_type in {"daily-sales", "daily-revenue"}: bills=[b for b in bills if b.created_at>=start_of_day and b.status not in {"Pending", "Cancelled", "Refunded"}]
    elif report_type=="weekly-sales": bills=[b for b in bills if b.created_at>=start_week and b.status not in {"Pending", "Cancelled", "Refunded"}]
    elif report_type in {"monthly-sales", "monthly-revenue"}: bills=[b for b in bills if b.created_at>=start_month and b.status not in {"Pending", "Cancelled", "Refunded"}]
    elif report_type=="yearly-revenue": bills=[b for b in bills if b.created_at>=start_year and b.status not in {"Pending", "Cancelled", "Refunded"}]
    elif report_type=="interactions": bills=[b for b in bills if b.interaction_count]
    if request.args.get("start"):
        try: bills=[b for b in bills if b.created_at.date() >= date.fromisoformat(request.args["start"])]
        except ValueError: abort(400)
    if request.args.get("end"):
        try: bills=[b for b in bills if b.created_at.date() <= date.fromisoformat(request.args["end"])]
        except ValueError: abort(400)
    patient_id=request.args.get("patient_id",type=int)
    if report_type=="patient-purchases" and patient_id: bills=[b for b in bills if b.patient_id==patient_id]
    if request.args.get("patient"):
        term=request.args["patient"].strip().lower(); bills=[b for b in bills if b.patient and term in b.patient.full_name.lower()]
    if request.args.get("payment"):
        bills=[b for b in bills if b.payment_method.lower()==request.args["payment"].strip().lower()]
    if request.args.get("medicine"):
        term=request.args["medicine"].strip().lower(); bills=[b for b in bills if any(term in i.medicine_name.lower() or term in i.generic_name.lower() for i in b.items)]
    if request.args.get("manufacturer"):
        term=request.args["manufacturer"].strip().lower(); bills=[b for b in bills if any(i.medicine and term in i.medicine.manufacturer.lower() for i in b.items)]
    if request.args.get("category"):
        term=request.args["category"].strip().lower(); bills=[b for b in bills if any(i.medicine and i.medicine.category.lower()==term for i in b.items)]
    if request.args.get("severity"):
        severity=request.args["severity"].strip().lower(); bills=[b for b in bills if any(e.get("severity","").lower()==severity for level in ("mild","moderate","severe") for e in json.loads(b.interaction_summary or "{}").get(level,[]))]
    if report_type in {"inventory","low-stock","expiry"}:
        medicine_query=Medicine.query
        if request.args.get("category"): medicine_query=medicine_query.filter(Medicine.category.ilike(request.args["category"].strip()))
        if request.args.get("manufacturer"): medicine_query=medicine_query.filter(Medicine.manufacturer.ilike(f"%{request.args['manufacturer'].strip()}%"))
        if request.args.get("medicine"):
            term=f"%{request.args['medicine'].strip()}%"; medicine_query=medicine_query.filter(or_(Medicine.brand_name.ilike(term),Medicine.generic_name.ilike(term)))
        meds=medicine_query.order_by(Medicine.expiry_date.asc()).all()
        if report_type=="low-stock": meds=[m for m in meds if m.stock<=m.minimum_stock]
        if report_type=="expiry": meds=[m for m in meds if m.expiry_date <= today+timedelta(days=30)]
        if request.args.get("start"):
            try: meds=[m for m in meds if m.expiry_date >= date.fromisoformat(request.args["start"])]
            except ValueError: abort(400)
        if request.args.get("end"):
            try: meds=[m for m in meds if m.expiry_date <= date.fromisoformat(request.args["end"])]
            except ValueError: abort(400)
        rows=[["Medicine","Generic","Category","Manufacturer","Batch","Stock","Minimum","Expiry","Status"]]
        rows += [[m.brand_name,m.generic_name,m.category,m.manufacturer,m.batch_number,m.stock,m.minimum_stock,m.expiry_date.isoformat(),m.stock_status] for m in meds]
    elif report_type in {"top-medicines","dangerous-pairs","medicine-category","payment-method","revenue-by-day"}:
        if report_type=="top-medicines":
            totals=db.session.query(BillItem.medicine_name,func.sum(BillItem.quantity),func.sum(BillItem.total)).join(Bill).group_by(BillItem.medicine_name).order_by(func.sum(BillItem.quantity).desc()).limit(100).all()
            rows=[["Medicine","Quantity sold","Sales total"]]+[[n,q,f"{v:.2f}"] for n,q,v in totals]
        elif report_type=="medicine-category":
            totals={}
            for bill in bills:
                for line in bill.items:
                    category=line.medicine.category if line.medicine else "Uncategorized"
                    quantity,value=totals.get(category,(0,0)); totals[category]=(quantity+line.quantity,value+line.total)
            rows=[["Category","Quantity sold","Sales total"]]+[[n,q,f"{v:.2f}"] for n,(q,v) in sorted(totals.items(),key=lambda pair:pair[1][1],reverse=True)]
        elif report_type=="payment-method":
            totals={}
            for bill in bills:
                if bill.status not in {"Pending", "Cancelled", "Refunded"}:
                    count,value=totals.get(bill.payment_method,(0,0)); totals[bill.payment_method]=(count+1,value+bill.grand_total)
            rows=[["Payment method","Bills","Collected revenue"]]+[[n,c,f"{v:.2f}"] for n,(c,v) in sorted(totals.items(),key=lambda pair:pair[1][1],reverse=True)]
        elif report_type=="revenue-by-day":
            rows=[["Date","Bills","Revenue"]]
            by_day={}
            for b in bills:
                if b.status not in {"Pending", "Cancelled", "Refunded"}:
                    key=b.created_at.date().isoformat(); count,total=by_day.get(key,(0,0)); by_day[key]=(count+1,total+b.grand_total)
            rows += [[day,count,f"{total:.2f}"] for day,(count,total) in sorted(by_day.items())]
        else:
            rows=[["Invoice","Date","Risk","Medicine pair","Effect","Recommendation"]]
            for b in bills:
                for item in (json.loads(b.interaction_summary or "{}").get("moderate",[])+json.loads(b.interaction_summary or "{}").get("severe",[])):
                    rows.append([b.invoice_number,b.created_at.isoformat(),item.get("severity"),f"{item.get('medicine_one')} + {item.get('medicine_two')}",item.get("effect"),item.get("recommendation")])
    elif report_type=="interactions":
        rows=[["Invoice","Date","Patient","Severity","Medicine pair","Effect","Recommendation"]]
        for b in bills:
            summary=json.loads(b.interaction_summary or "{}")
            for item in summary.get("moderate",[])+summary.get("severe",[]): rows.append([b.invoice_number,b.created_at.isoformat(),b.patient.full_name if b.patient else "Walk-in",item.get("severity"),f"{item.get('medicine_one')} + {item.get('medicine_two')}",item.get("effect"),item.get("recommendation")])
    else:
        rows=[["Invoice","Date","Patient","Subtotal","GST","Discount","Total","Payment"]]
        rows += [[b.invoice_number,b.created_at.isoformat(),b.patient.full_name if b.patient else "Walk-in",f"{b.subtotal:.2f}",f"{b.gst_amount:.2f}",f"{b.discount:.2f}",f"{b.grand_total:.2f}",b.payment_method] for b in bills]
    filename=f"medishield-{report_type}"
    if extension=="csv":
        stream=StringIO(); writer=csv.writer(stream); writer.writerows([[ ("'"+str(cell)) if isinstance(cell,str) and cell.startswith(("=","+","-","@","\t","\r")) else cell for cell in row] for row in rows])
        response=make_response("\ufeff"+stream.getvalue()); response.headers["Content-Type"]="text/csv; charset=utf-8"; response.headers["Content-Disposition"]=f"attachment; filename={filename}.csv"; return response
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, LongTable
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    output=BytesIO(); story=[Paragraph(report_type.replace("-"," ").title(),getSampleStyleSheet()["Title"]),Paragraph(f"Generated {today.isoformat()} · MediShield v1.0",getSampleStyleSheet()["Normal"]),LongTable(rows,repeatRows=1)]
    story[2].setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0F172A")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),7),("GRID",(0,0),(-1,-1),.3,colors.grey),("VALIGN",(0,0),(-1,-1),"TOP")]))
    SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=24,leftMargin=24).build(story)
    output.seek(0)
    return send_file(output,mimetype="application/pdf",as_attachment=True,download_name=f"{filename}.pdf")
