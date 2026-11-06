import io
from decimal import Decimal
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas

class InvoiceCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Bottom footer line
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(40, 38, 572, 38)
        
        self.drawString(40, 26, "StayFlow Hotel Management System • Official Tax Invoice & GST Receipt")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(572, 26, page_str)
        self.restoreState()

def format_inr(val):
    try:
        f = float(val or 0.0)
        return f"Rs. {f:,.2f}"
    except Exception:
        return "Rs. 0.00"

def generate_invoice_pdf(inv: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=36,
        bottomMargin=46
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    c_primary = colors.HexColor("#0F172A")
    c_accent = colors.HexColor("#0284C7")
    c_sub = colors.HexColor("#475569")
    
    title_style = ParagraphStyle(
        'InvTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=c_primary,
        spaceAfter=2
    )
    
    hotel_sub = ParagraphStyle(
        'HotelSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=c_sub,
    )
    
    sec_title = ParagraphStyle(
        'SecTitle',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=c_accent,
        spaceBefore=6,
        spaceAfter=4
    )
    
    lbl_style = ParagraphStyle(
        'Lbl',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#334155")
    )
    
    val_style = ParagraphStyle(
        'Val',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E293B")
    )

    tbl_header = ParagraphStyle(
        'TblHdr',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white
    )
    
    tbl_cell = ParagraphStyle(
        'TblCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E293B")
    )

    tbl_cell_bold = ParagraphStyle(
        'TblCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0F172A")
    )

    tbl_cell_right = ParagraphStyle(
        'TblCellRight',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        alignment=2, # Right align
        textColor=colors.HexColor("#1E293B")
    )

    tbl_cell_right_bold = ParagraphStyle(
        'TblCellRightBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        alignment=2,
        textColor=colors.HexColor("#0F172A")
    )

    story = []
    
    hotel_name = inv.get("hotel_name") or "StayFlow Hotel & Luxury Suites"
    inv_num = inv.get("invoice_number") or f"INV-{inv.get('booking_reference', '')}"
    issued_at_str = inv.get("issued_at") or inv.get("created_at") or datetime.now().isoformat()
    try:
        dt_obj = datetime.fromisoformat(str(issued_at_str).replace('Z', '+00:00'))
        date_formatted = dt_obj.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        date_formatted = str(issued_at_str)[:19]

    # 1. Header Banner: Hotel details on left, Invoice details on right
    hdr_left = [
        Paragraph(f"<b>{hotel_name}</b>", title_style),
        Paragraph("104 Coastal Boulevard, Hospitality Zone, Bengaluru 560001<br/>"
                  "<b>GSTIN:</b> 29AAACH7409R1ZZ &nbsp;|&nbsp; <b>Email:</b> frontdesk@stayflowhotel.com<br/>"
                  "<b>Phone:</b> +91 80 4567 8900 &nbsp;|&nbsp; <b>Web:</b> stayflowhotel.com", hotel_sub)
    ]
    
    pay_status = str(inv.get("payment_status") or "Paid").upper()
    status_bg = "#16A34A" if "PAID" in pay_status and "PARTIAL" not in pay_status else ("#D97706" if "PARTIAL" in pay_status else "#DC2626")
    
    hdr_right = [
        Paragraph(f"<font size=13 color='#0284C7'><b>TAX INVOICE</b></font>", ParagraphStyle('TI', alignment=2)),
        Paragraph(f"<b>Invoice #:</b> {inv_num}", ParagraphStyle('IH', alignment=2, fontName='Helvetica-Bold', fontSize=9, leading=13)),
        Paragraph(f"<b>Date:</b> {date_formatted}", ParagraphStyle('ID', alignment=2, fontName='Helvetica', fontSize=8, leading=12, textColor=c_sub)),
        Paragraph(f"<b>Booking Ref:</b> {inv.get('booking_reference', '—')}", ParagraphStyle('IB', alignment=2, fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=c_primary)),
        Paragraph(f"<font color='white'><b>&nbsp; {pay_status} &nbsp;</b></font>", ParagraphStyle('IBadge', alignment=2, fontName='Helvetica-Bold', fontSize=8.5, leading=14, backColor=colors.HexColor(status_bg)))
    ]
    
    header_tbl = Table([[hdr_left, hdr_right]], colWidths=[332, 200])
    header_tbl.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceBefore=2, spaceAfter=8))

    # 2. Guest Information & Stay Information 2-Column Card
    guest_details = [
        [Paragraph("Guest Name:", lbl_style), Paragraph(f"<b>{inv.get('guest_name', '—')}</b>", val_style)],
        [Paragraph("Contact Phone:", lbl_style), Paragraph(inv.get('guest_phone') or '—', val_style)],
        [Paragraph("Email Address:", lbl_style), Paragraph(inv.get('guest_email') or '—', val_style)],
        [Paragraph("ID Proof / Verification:", lbl_style), Paragraph(inv.get('id_proof') or 'Verified at Check-in', val_style)],
    ]
    t_guest = Table(guest_details, colWidths=[90, 160])
    t_guest.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))

    check_in_str = inv.get("check_in") or "—"
    check_out_str = inv.get("check_out") or "—"
    nights_num = inv.get("nights", 1)
    room_num = inv.get("room_number") or "—"
    room_type = inv.get("room_type") or "Standard"

    stay_details = [
        [Paragraph("Room Assigned:", lbl_style), Paragraph(f"<b>Room {room_num}</b> ({room_type})", val_style)],
        [Paragraph("Duration of Stay:", lbl_style), Paragraph(f"<b>{nights_num} Night(s)</b>", val_style)],
        [Paragraph("Check-In Date/Time:", lbl_style), Paragraph(f"{check_in_str} (14:00 hrs)", val_style)],
        [Paragraph("Check-Out Date/Time:", lbl_style), Paragraph(f"{check_out_str} (11:00 hrs)", val_style)],
    ]
    t_stay = Table(stay_details, colWidths=[95, 165])
    t_stay.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))

    info_card = Table([
        [
            [Paragraph("<b>GUEST PARTICULARS</b>", sec_title), t_guest],
            [Paragraph("<b>STAY & RESERVATION DETAILS</b>", sec_title), t_stay]
        ]
    ], colWidths=[260, 272])
    info_card.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(info_card)
    story.append(Spacer(1, 10))

    # 3. Itemized Charges Table (Room charges + Additional Services)
    story.append(Paragraph("<b>ITEMIZED CHARGES & SERVICES</b>", sec_title))

    items_data = [
        [
            Paragraph("#", tbl_header),
            Paragraph("Item / Service Description", tbl_header),
            Paragraph("Category", tbl_header),
            Paragraph("Qty", tbl_header),
            Paragraph("Unit Rate", tbl_header),
            Paragraph("Amount", tbl_header),
        ]
    ]

    idx = 0
    daily_room_charges = inv.get("daily_room_charges") or []
    base_rate = float(inv.get("base_rate") or inv.get("price_per_night") or 2500.0)
    room_charges = float(inv.get("room_charges") or (sum(float(d.get("amount", 0.0)) for d in daily_room_charges) if daily_room_charges else (base_rate * float(nights_num))))

    if daily_room_charges:
        for d in daily_room_charges:
            idx += 1
            duration_lbl = d.get("duration", "Full Day")
            day_amt = float(d.get("amount", base_rate))
            day_rate = float(d.get("rate_per_day", base_rate))
            date_display = d.get("date_formatted") or d.get("date") or ""
            day_desc = f"<b>Room Stay: {d.get('room_type', room_type)} ({duration_lbl})</b><br/><font color='#64748B'>Room #{d.get('room_number', room_num)} • Stay Date: {date_display} • {duration_lbl}</font>"
            qty_label = "0.5 Day" if duration_lbl == "Half Day" else "1 Day"
            items_data.append([
                Paragraph(str(idx), tbl_cell),
                Paragraph(day_desc, tbl_cell),
                Paragraph("Accommodation", tbl_cell),
                Paragraph(qty_label, tbl_cell),
                Paragraph(format_inr(day_rate), tbl_cell_right),
                Paragraph(format_inr(day_amt), tbl_cell_right_bold),
            ])
    else:
        # Fallback to single stay row if daily breakdown not provided
        idx += 1
        room_charges = float(inv.get("room_charges") or (base_rate * float(nights_num)))
        items_data.append([
            Paragraph(str(idx), tbl_cell),
            Paragraph(f"<b>Room Stay: {room_type}</b><br/><font color='#64748B'>Room #{room_num} • {nights_num} night(s) @ {format_inr(base_rate)}/night</font>", tbl_cell),
            Paragraph("Accommodation", tbl_cell),
            Paragraph(str(nights_num), tbl_cell),
            Paragraph(format_inr(base_rate), tbl_cell_right),
            Paragraph(format_inr(room_charges), tbl_cell_right_bold),
        ])

    # Additional Services
    services = inv.get("services") or []
    if not isinstance(services, list):
        services = []

    for svc in services:
        idx += 1
        name = svc.get("name") or svc.get("service_name") or "Additional Service"
        cat = svc.get("category") or "Hotel Service"
        qty = svc.get("quantity") or 1
        u_price = float(svc.get("unit_price") or svc.get("rate") or 0.0)
        tot = float(svc.get("total") or (qty * u_price))
        notes = svc.get("notes") or ""
        s_date = svc.get("service_date_formatted") or svc.get("service_date") or ""
        sub_parts = []
        if s_date:
            sub_parts.append(f"Service Date: {s_date}")
        if notes:
            sub_parts.append(notes)
        sub_text = " • ".join(sub_parts)
        desc = f"<b>{name}</b>" + (f"<br/><font color='#64748B'>{sub_text}</font>" if sub_text else "")

        items_data.append([
            Paragraph(str(idx), tbl_cell),
            Paragraph(desc, tbl_cell),
            Paragraph(cat, tbl_cell),
            Paragraph(str(qty), tbl_cell),
            Paragraph(format_inr(u_price), tbl_cell_right),
            Paragraph(format_inr(tot), tbl_cell_right_bold),
        ])

    # If no services were used
    if len(services) == 0:
        idx += 1
        items_data.append([
            Paragraph("—", tbl_cell),
            Paragraph("<font color='#94A3B8'><i>No additional services.</i></font>", tbl_cell),
            Paragraph("—", tbl_cell),
            Paragraph("—", tbl_cell),
            Paragraph("—", tbl_cell_right),
            Paragraph("Rs. 0.00", tbl_cell_right),
        ])

    # If extra charges exist but not itemized as separate services
    unitemized_extra = float(inv.get("additional_charges") or 0.0)
    services_total = sum(float(s.get("total") or 0.0) for s in services)
    remaining_extra = round(unitemized_extra - services_total, 2)
    if remaining_extra > 0.01:
        idx += 1
        items_data.append([
            Paragraph(str(idx), tbl_cell),
            Paragraph("<b>Incidental & Service Charges</b>", tbl_cell),
            Paragraph("Incidental", tbl_cell),
            Paragraph("1", tbl_cell),
            Paragraph(format_inr(remaining_extra), tbl_cell_right),
            Paragraph(format_inr(remaining_extra), tbl_cell_right_bold),
        ])

    t_items = Table(items_data, colWidths=[24, 218, 90, 36, 76, 88])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0F172A")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    story.append(t_items)
    story.append(Spacer(1, 10))

    # 4. Calculation & Summary Box (Subtotal, Taxes, Discounts, Final Total, Paid, Balance)
    subtotal = float(inv.get("subtotal") or (room_charges + unitemized_extra))
    discount = float(inv.get("discount_amount") or inv.get("discount") or 0.0)
    taxable_subtotal = max(0.0, subtotal - discount)
    gst_pct = float(inv.get("gst_percent") or 12.0)
    tax_amt = float(inv.get("tax_amount") or round(taxable_subtotal * (gst_pct / 100.0), 2))
    cgst = round(tax_amt / 2.0, 2)
    sgst = round(tax_amt / 2.0, 2)
    total_bill = float(inv.get("total_bill") or (taxable_subtotal + tax_amt))
    amount_paid = float(inv.get("amount_paid") or 0.0)
    balance_due = float(inv.get("balance_due") or max(0.0, total_bill - amount_paid))

    payment_method = inv.get("payment_method") or "UPI / Card"

    left_note = [
        Paragraph("<b>PAYMENT & SETTLEMENT SUMMARY:</b>", lbl_style),
        Paragraph(f"• <b>Payment Method:</b> {payment_method}<br/>"
                  f"• <b>Payment Status:</b> <font color='{status_bg}'><b>{pay_status}</b></font><br/>"
                  f"• <b>Amount Paid:</b> {format_inr(amount_paid)}<br/>"
                  f"• <b>Balance Outstanding:</b> {format_inr(balance_due)}<br/>"
                  f"• <b>Applicable Tax Slabs:</b> CGST (6.0%) + SGST (6.0%) under HSN/SAC Code 996311.<br/>"
                  f"• <i>This invoice is computer generated and verified against hotel management database records.</i>", hotel_sub)
    ]

    calc_rows = [
        [Paragraph("Room Charges Total:", val_style), Paragraph(format_inr(room_charges), tbl_cell_right)],
        [Paragraph("Additional Services Total:", val_style), Paragraph(format_inr(unitemized_extra if unitemized_extra > 0 else services_total), tbl_cell_right)],
        [Paragraph("Subtotal (Gross):", lbl_style), Paragraph(format_inr(subtotal), tbl_cell_right_bold)],
    ]
    if discount > 0:
        calc_rows.append([
            Paragraph("Discount / Offer Applied:", lbl_style),
            Paragraph(f"-{format_inr(discount)}", ParagraphStyle('D', parent=tbl_cell_right_bold, textColor=colors.HexColor("#16A34A")))
        ])
    calc_rows.extend([
        [Paragraph(f"CGST ({gst_pct/2:.1f}%):", val_style), Paragraph(format_inr(cgst), tbl_cell_right)],
        [Paragraph(f"SGST ({gst_pct/2:.1f}%):", val_style), Paragraph(format_inr(sgst), tbl_cell_right)],
        [Paragraph(f"Total GST ({gst_pct:.1f}%):", val_style), Paragraph(format_inr(tax_amt), tbl_cell_right)],
        [Paragraph("<b>FINAL TOTAL AMOUNT:</b>", ParagraphStyle('FT', fontName='Helvetica-Bold', fontSize=9, textColor=c_primary)), Paragraph(f"<b>{format_inr(total_bill)}</b>", ParagraphStyle('FTR', fontName='Helvetica-Bold', fontSize=10, textColor=c_accent, alignment=2))],
        [Paragraph("Amount Paid:", val_style), Paragraph(format_inr(amount_paid), tbl_cell_right)],
        [Paragraph("<b>OUTSTANDING BALANCE:</b>", ParagraphStyle('OB', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor("#DC2626") if balance_due > 0 else colors.HexColor("#16A34A"))), Paragraph(f"<b>{format_inr(balance_due)}</b>", ParagraphStyle('OBR', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor("#DC2626") if balance_due > 0 else colors.HexColor("#16A34A"), alignment=2))],
    ])

    t_calc = Table(calc_rows, colWidths=[150, 110])
    t_calc.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LINEBELOW', (0,2), (-1,2), 0.5, colors.HexColor("#CBD5E1")),
        ('LINEBELOW', (0,-4), (-1,-4), 0.5, colors.HexColor("#CBD5E1")),
        ('LINEBELOW', (0,-3), (-1,-3), 1, colors.HexColor("#0284C7")),
        ('LINEBELOW', (0,-1), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
    ]))

    summary_table = Table([[left_note, t_calc]], colWidths=[272, 260])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 12))

    # 5. Signatory & Thank You Footer
    sign_table = Table([
        [
            Paragraph("<b>Terms & Conditions:</b><br/>"
                      "1. All disputes are subject to local jurisdiction.<br/>"
                      "2. Standard checkout time is 11:00 AM. Late checkouts may incur charges.<br/>"
                      "3. Thank you for choosing StayFlow Hotel. We look forward to welcoming you back!", hotel_sub),
            Paragraph("<b>For StayFlow Hotel & Luxury Suites</b><br/><br/><br/>"
                      "____________________________<br/>"
                      "<b>Authorized Signatory / Front Desk</b>", ParagraphStyle('Sign', alignment=2, fontName='Helvetica', fontSize=8, leading=11))
        ]
    ], colWidths=[332, 200])
    sign_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(KeepTogether(sign_table))

    doc.build(story, canvasmaker=InvoiceCanvas)
    return buffer.getvalue()
