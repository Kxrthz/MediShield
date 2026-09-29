from io import BytesIO
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BLUE = colors.HexColor("#2563EB")
NAVY = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")


def _document():
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=17 * mm, bottomMargin=17 * mm, title="MediShield invoice")
    return output, doc


def _header(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.roundRect(18 * mm, A4[1] - 26 * mm, 11 * mm, 11 * mm, 3 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawCentredString(23.5 * mm, A4[1] - 22 * mm, "+")
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(33 * mm, A4[1] - 20 * mm, "MediShield")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(33 * mm, A4[1] - 25 * mm, "Safe Pharmacy Billing & Drug Interaction Checker")
    canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
    canvas.line(18 * mm, A4[1] - 31 * mm, A4[0] - 18 * mm, A4[1] - 31 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(A4[0] / 2, 10 * mm, "MediShield · Please retain this invoice for your records")
    canvas.restoreState()


def invoice_pdf(bill):
    output, doc = _document()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("InvoiceTitle", parent=styles["Heading1"], textColor=NAVY, fontSize=20, spaceAfter=6)
    small = ParagraphStyle("MutedSmall", parent=styles["BodyText"], textColor=MUTED, fontSize=9, leading=13)
    story = [Spacer(1, 19 * mm), Paragraph("Tax invoice", title),
             Paragraph(f"Invoice <b>{bill.invoice_number}</b> &nbsp; · &nbsp; {bill.created_at.strftime('%d %b %Y, %I:%M %p')}", small),
             Spacer(1, 8 * mm)]
    patient = bill.patient.full_name if bill.patient else "Walk-in customer"
    story.append(Paragraph(f"<b>Patient</b><br/>{escape(patient)}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Pharmacist</b><br/>{escape(bill.pharmacist.name if bill.pharmacist else 'MediShield pharmacy team')}", small))
    story.append(Spacer(1, 7 * mm))
    rows = [["Medicine", "Qty", "Unit price", "Amount"]]
    for item in bill.items:
        rows.append([f"{escape(item.medicine_name)}<br/><font size='8' color='#64748B'>{escape(item.generic_name)} · {escape(item.strength)}</font>",
                     str(item.quantity), f"INR {item.price:,.2f}", f"INR {item.total:,.2f}"])
    table = Table(rows, colWidths=[93 * mm, 18 * mm, 32 * mm, 32 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                               ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                               ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#E2E8F0")),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.extend([table, Spacer(1, 7 * mm)])
    totals = [["Subtotal", f"INR {bill.subtotal:,.2f}"], ["GST (12%)", f"INR {bill.gst_amount:,.2f}"],
              ["Discount", f"− INR {bill.discount:,.2f}"], ["Grand total", f"INR {bill.grand_total:,.2f}"]]
    total_table = Table(totals, colWidths=[145 * mm, 32 * mm], hAlign="RIGHT")
    total_table.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
                                     ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                                     ("FONTSIZE", (0, -1), (-1, -1), 13),
                                     ("LINEABOVE", (0, -1), (-1, -1), 1, BLUE),
                                     ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    summary = json.loads(bill.interaction_summary or "{}")
    ai_status = summary.get("overall_status")
    interaction_count = len(summary.get("interactions", [])) if "interactions" in summary else sum(len(summary.get(level, [])) for level in ("mild", "moderate", "severe"))
    status_text = f"AI Guardian: {ai_status} · confidence {summary.get('confidence', 0)}% · {interaction_count} interaction(s)" if ai_status else f"Local screening: {summary.get('safety_label', 'Not scored')} · {interaction_count} interaction(s)"
    story.extend([total_table, Spacer(1, 7 * mm),
                  Paragraph(f"<b>Payment method:</b> {escape(bill.payment_method)} &nbsp; · &nbsp; <b>Status:</b> {escape(bill.status)}", small),
                  Paragraph(f"<b>Prescription safety:</b> {escape(status_text)}", small)])
    if ai_status:
        for alert in summary.get("interactions", []):
            story.append(Paragraph(f"{escape(alert['severity'])}: {escape(alert['medicine_1'])} + {escape(alert['medicine_2'])} — {escape(alert['reason'])} Recommendation: {escape(alert['recommendation'])}", small))
        for warning in summary.get("allergy_warnings", []):
            story.append(Paragraph(f"<b>Allergy warning:</b> {escape(warning['medicine'])} · {escape(warning['allergen'])} — {escape(warning.get('reason', ''))}", small))
        for recommendation in summary.get("recommendations", []):
            story.append(Paragraph(f"<b>Pharmacist review:</b> {escape(recommendation)}", small))
        story.append(Paragraph("AI Guardian is an assistive screening tool. Review the underlying clinical evidence and use professional judgment; an AI result cannot guarantee that a combination is safe.", small))
    else:
        for alert in summary.get("severe", []) + summary.get("moderate", []):
            story.append(Paragraph(f"{escape(alert['severity'])}: {escape(alert['medicine_one'])} + {escape(alert['medicine_two'])} — {escape(alert['recommendation'])}", small))
    if bill.override_reason:
        story.extend([Spacer(1, 4 * mm), Paragraph(f"<b>Admin override reason:</b> {escape(bill.override_reason)}", small)])
    doc.build(story, onFirstPage=_header, onLaterPages=_header)
    return output.getvalue()


def interaction_report_pdf(patient_name, medicines, interactions, invoice_number=None, ai_summary=None, pharmacist=None, timestamp=None):
    output, doc = _document()
    styles = getSampleStyleSheet()
    story = [Spacer(1, 18 * mm), Paragraph("AI Prescription Safety Report" if ai_summary else "Drug Interaction Warning Report", styles["Title"]),
             Paragraph(f"Patient: <b>{patient_name or 'Walk-in customer'}</b>", styles["BodyText"]),
             Paragraph(f"Related invoice: <b>{invoice_number or 'Prescription review'}</b>", styles["BodyText"]),
             Paragraph(f"Pharmacist: <b>{pharmacist or 'Not recorded'}</b> &nbsp; · &nbsp; Time: <b>{timestamp or 'Not recorded'}</b>", styles["BodyText"]), Spacer(1, 6 * mm),
             Paragraph("Medicines reviewed", styles["Heading2"])]
    story.append(Paragraph(", ".join(escape(m) for m in medicines), styles["BodyText"]))
    if ai_summary:
        story.extend([Spacer(1, 4 * mm), Paragraph(f"<b>Overall status:</b> {escape(str(ai_summary.get('overall_status', 'UNCERTAIN')))} &nbsp; · &nbsp; <b>Confidence:</b> {ai_summary.get('confidence', 0)}%", styles["BodyText"]), Paragraph(escape(str(ai_summary.get("summary", ""))), styles["BodyText"])])
    story.extend([Spacer(1, 5 * mm), Paragraph("Detected interactions", styles["Heading2"])])
    rows = [["Pair", "Severity", "Potential effect", "Suggested action"]]
    for item in interactions:
        rows.append([f"{escape(item.get('medicine_1', item.get('medicine_one', '')))} + {escape(item.get('medicine_2', item.get('medicine_two', ''))) }", escape(item["severity"]), escape(item.get("reason", item.get("effect", ""))), escape(item["recommendation"])])
    table = Table(rows, colWidths=[38 * mm, 20 * mm, 58 * mm, 59 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                               ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#CBD5E1")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    allergy_warnings = (ai_summary or {}).get("allergy_warnings", [])
    if allergy_warnings:
        story.extend([Spacer(1, 5 * mm), Paragraph("Allergy warnings", styles["Heading2"])] )
        for warning in allergy_warnings:
            story.append(Paragraph(f"{escape(warning['medicine'])} · {escape(warning['allergen'])}: {escape(warning.get('reason', ''))}", styles["BodyText"]))
    story.extend([table, Spacer(1, 7 * mm), Paragraph("This report is a screening aid, not a substitute for clinical judgment. A model confidence score is not a clinical probability. Confirm findings against current product labeling and patient-specific information.", styles["Italic"])])
    doc.build(story, onFirstPage=_header, onLaterPages=_header)
    return output.getvalue()
