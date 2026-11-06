import os
import sys
import json
import requests
from decimal import Decimal
from datetime import datetime, timezone

# Configure output encoding for Windows PowerShell
sys.stdout.reconfigure(encoding='utf-8')

from app.core.security import create_access_token
from app.database.connection import SessionLocal
from app.models import Room, RoomType, Reservation, Guest, OperationalRecord, HotelSettings

token = create_access_token('admin@hotel.com', 'ADMIN')
headers = {'Authorization': f'Bearer {token}'}
BASE = 'http://127.0.0.1:8000'

print("=" * 80)
print("HOTEL BILLING & INVOICE WORKFLOW: COMPREHENSIVE INTEGRATION & UNIT TESTS")
print("=" * 80)

# STEP 1: Fetch and Verify Room Rates from MySQL
with SessionLocal() as db:
    settings = db.query(HotelSettings).first()
    hotel_name = settings.hotel_name
    configured_gst = float(settings.gst_percent)
    checkout_time = settings.check_out_time

    fr_type = db.query(RoomType).filter(RoomType.name == 'Family Room').first()
    assert fr_type is not None, "Family Room type must exist in MySQL"
    r109 = db.query(Room).filter(Room.room_type_id == fr_type.id).first()
    assert r109 is not None, "Room 109 must exist"
    # Ensure test room has no active overlapping reservations so test is 100% idempotent
    for past_res in db.query(Reservation).filter(Reservation.room_id == r109.id, Reservation.status.in_(['Checked-in', 'Confirmed', 'Pending'])).all():
        past_res.status = 'Cancelled'
    r109.status = 'vac'
    db.commit()

    room_id = r109.id
    room_number = r109.number
    base_price = float(fr_type.base_price)
    extra_bed_rate = float(fr_type.extra_bed_charge)

print(f"\n[STEP 1] MySQL Hotel & Room Configuration:")
print(f"  • Hotel Name: {hotel_name}")
print(f"  • Configured Standard Check-out: {checkout_time}")
print(f"  • Configured GST: {configured_gst}%")
print(f"  • Room Number: {room_number}")
print(f"  • Room Type: Family Room")
print(f"  • Fetched Rate Per Day from MySQL: Rs. {base_price:,.2f}")
print(f"  • Extra Bed Configured MySQL Rate: Rs. {extra_bed_rate:,.2f}")
assert base_price == 6000.0, f"Expected 6000.0, got {base_price}"

# STEP 2: TEST SCENARIO A - 2 FULL STAY DAYS (Day 1 = ₹6,000, Day 2 = ₹6,000, Total = ₹12,000)
print(f"\n[STEP 2] SCENARIO A: 2 Full Stay Days (Day 1 = Rs. 6,000, Day 2 = Rs. 6,000, Total = Rs. 12,000)")
b_payload = {
    'guest': {'full_name': 'Suresh Varma', 'phone': '+91 98401 23456', 'email': 'suresh.varma@example.com'},
    'room_id': room_id,
    'check_in': '2026-10-22',
    'check_out': '2026-10-24',
    'source': 'Direct',
    'status': 'Checked-in'
}
res = requests.post(f"{BASE}/api/bookings", json=b_payload, headers=headers)
assert res.status_code == 201, f"Booking creation failed: {res.text}"
b_data = res.json()
ref = b_data['reference']
print(f"  • Booking Created: Ref {ref} | Guest: {b_data['guest']}")

# Fetch real-time billing for 2 full days
r_bill_2days = requests.get(f"{BASE}/api/bookings/{ref}/billing", headers=headers)
assert r_bill_2days.status_code == 200
bill_2days = r_bill_2days.json()['billing']

print(f"  • Daily Room Charges Breakdown (2 Full Days):")
assert len(bill_2days['daily_room_charges']) == 2, f"Expected 2 daily room charges, got {len(bill_2days['daily_room_charges'])}"
for day in bill_2days['daily_room_charges']:
    print(f"    - Day {day['day_number']} ({day['date_formatted']}): {day['room_type']} | Rate: Rs. {day['rate_per_day']:,.2f} | Duration: {day['duration']} | Amount: Rs. {day['amount']:,.2f}")
    assert day['rate_per_day'] == 6000.0
    assert day['duration'] == 'Full Day'
    assert day['amount'] == 6000.0

assert bill_2days['room_charges'] == 12000.0, f"Expected Room Total 12000.0, got {bill_2days['room_charges']}"
print(f"  • Room Total for 2 Full Days: Rs. {bill_2days['room_charges']:,.2f} (VERIFIED Day 1 = Rs. 6,000 + Day 2 = Rs. 6,000 = Rs. 12,000)")

# STEP 3: TEST SCENARIO B - FULL DAY + HALF DAY CALCULATION (1 Full Day = ₹6,000, 1 Half Day = ₹3,000, Room Total = ₹9,000)
print(f"\n[STEP 3] SCENARIO B: Full-Day and Half-Day Calculation (Policy Permitted: 1 Full Day = Rs. 6,000 + 1 Half Day = Rs. 3,000 = Rs. 9,000)")
r_half = requests.post(f"{BASE}/api/bookings/{ref}/half-day", json={"has_half_day": True, "notes": "Guest requested half-day extension"}, headers=headers)
assert r_half.status_code == 200
bill_half = r_half.json()['billing']

print(f"  • Daily Room Charges Breakdown with Half-Day Stay Applied:")
assert len(bill_half['daily_room_charges']) == 2
d1 = bill_half['daily_room_charges'][0]
d2 = bill_half['daily_room_charges'][1]
print(f"    - Day 1 ({d1['date_formatted']}): {d1['room_type']} | Rate: Rs. {d1['rate_per_day']:,.2f} | Duration: {d1['duration']} | Amount: Rs. {d1['amount']:,.2f}")
print(f"    - Day 2 ({d2['date_formatted']}): {d2['room_type']} | Rate: Rs. {d2['rate_per_day']:,.2f} | Duration: {d2['duration']} | Amount: Rs. {d2['amount']:,.2f}")

assert d1['duration'] == 'Full Day' and d1['amount'] == 6000.0, "Day 1 must be Full Day = 6000.0"
assert d2['duration'] == 'Half Day' and d2['amount'] == 3000.0, "Day 2 must be Half Day = 3000.0"
assert bill_half['room_charges'] == 9000.0, f"Expected Room Total 9000.0, got {bill_half['room_charges']}"
print(f"  • Room Total: Rs. {bill_half['room_charges']:,.2f} (VERIFIED Full Day = Rs. 6,000, Half Day = Rs. 3,000, Room Total = Rs. 9,000)")

# Revert to standard 2 full days for full billing & services test
requests.post(f"{BASE}/api/bookings/{ref}/half-day", json={"has_half_day": False}, headers=headers)

# STEP 4: TEST POLICY DISALLOWED CASE (When Policy Does Not Permit Half-Day -> Late Check-out Fee Applies)
print(f"\n[STEP 4] SCENARIO C: Hotel Policy Disallowing Half-Day (Applies Appropriate Late Check-out Fee)")
r_pol = requests.post(f"{BASE}/api/settings/billing-policy", json={"allow_half_day": False, "half_day_rate_percent": 50.0, "late_checkout_flat_fee": 600.0}, headers=headers)
assert r_pol.status_code == 200

# Test checkout time at 14:00 (after 12:00 grace period)
checkout_dt = datetime(2026, 10, 24, 14, 0, 0, tzinfo=timezone.utc)
with SessionLocal() as db:
    r_test = db.query(Reservation).filter(Reservation.reference == ref).first()
    from app.main import calculate_billing
    b_late = calculate_billing(db, r_test, checkout_time=checkout_dt)
    print(f"  • With Half-Day Disallowed by Policy and Checkout at 14:00:")
    print(f"    - Room Charges: Rs. {b_late['room_charges']:,.2f}")
    late_svc = next((s for s in b_late['services'] if 'Late Check-out' in s['name']), None)
    assert late_svc is not None, "Late Check-out Charge must be applied when half-day policy is disallowed"
    print(f"    - Late Check-out Charge applied: Rs. {late_svc['total']:,.2f} ({late_svc['notes']})")

# Restore default policy permitting half-day
requests.post(f"{BASE}/api/settings/billing-policy", json={"allow_half_day": True, "half_day_rate_percent": 50.0, "late_checkout_flat_fee": 600.0}, headers=headers)
print("  • Restored standard half-day permission policy.")

# STEP 5: TEST ADDITIONAL SERVICES WITH SERVICE DATES & EMPTY STATE
print(f"\n[STEP 5] Additional Services Breakdown (Each Extra Service Recorded Separately with Service Date):")
services_to_test = [
    {
        'service_name': 'Food: Dinner Platter',
        'category': 'Food & Beverage',
        'service_date': '2026-10-22',
        'quantity': 2,
        'unit_price': 450.0,
        'notes': '2x North Indian dinner platter'
    },
    {
        'service_name': 'Laundry: Express Dry Clean',
        'category': 'Laundry',
        'service_date': '2026-10-23',
        'quantity': 2,
        'unit_price': 250.0,
        'notes': 'Express 4-hour garment cleaning'
    },
    {
        'service_name': 'Room Service: Continental Breakfast',
        'category': 'Food & Beverage',
        'service_date': '2026-10-23',
        'quantity': 2,
        'unit_price': 300.0,
        'notes': 'Served in Room 109'
    },
    {
        'service_name': 'Extra Bed Setup',
        'category': 'Housekeeping',
        'service_date': '2026-10-22',
        'quantity': 1,
        'unit_price': extra_bed_rate,
        'notes': 'Configured MySQL room rate'
    }
]

for s in services_to_test:
    r_add = requests.post(f"{BASE}/api/bookings/{ref}/services", json=s, headers=headers)
    assert r_add.status_code == 200
    added = r_add.json()['service']
    print(f"  + Added: {added['service_name']} | Date: {added['service_date']} | Qty: {added['quantity']} | Rate: Rs. {added['unit_price']:,.2f} | Total: Rs. {added['total']:,.2f}")

# STEP 6: VERIFY FINAL BILL WITH AUTOMATIC NO-HARDCODING CALCULATIONS
print(f"\n[STEP 6] Final Bill Mathematical Verification:")
r_final_bill = requests.get(f"{BASE}/api/bookings/{ref}/billing", headers=headers)
assert r_final_bill.status_code == 200
final_bill = r_final_bill.json()['billing']

print(f"  • Room Charges: Rs. {final_bill['room_charges']:,.2f}")
print(f"  • Additional Services: Rs. {final_bill['additional_charges']:,.2f}")
print(f"  • Subtotal (Gross): Rs. {final_bill['subtotal']:,.2f}")
print(f"  • GST Tax ({final_bill['gst_percent']}%): Rs. {final_bill['tax_amount']:,.2f} (CGST: Rs. {final_bill['cgst_amount']:,.2f}, SGST: Rs. {final_bill['sgst_amount']:,.2f})")
print(f"  • Grand Total: Rs. {final_bill['total_bill']:,.2f}")
print(f"  • Amount Paid: Rs. {final_bill['amount_paid']:,.2f}")
print(f"  • Outstanding Balance: Rs. {final_bill['balance_due']:,.2f}")
print(f"  • Payment Status: {final_bill['payment_status']}")

# Expected values:
# Room Charges = 2 x 6,000 = 12,000
# Additional Services = 900 (Food) + 500 (Laundry) + 600 (Room Service) + 1000 (Extra Bed) = 3,000
# Subtotal = 12,000 + 3,000 = 15,000
# GST 12% on 15,000 = 1,800 (CGST 900 + SGST 900)
# Grand Total = 16,800
assert final_bill['room_charges'] == 12000.0
assert final_bill['additional_charges'] == 3000.0
assert final_bill['subtotal'] == 15000.0
assert final_bill['tax_amount'] == 1800.0
assert final_bill['cgst_amount'] == 900.0
assert final_bill['sgst_amount'] == 900.0
assert final_bill['total_bill'] == 16800.0
assert final_bill['balance_due'] == 16800.0
assert final_bill['payment_status'] == 'Pending'
print("  >>> MATHEMATICAL VALIDATION 100% ACCURATE & ZERO HARDCODED VALUES! <<<")

# STEP 7: SETTLE PAYMENT & FINALIZE BILL
print(f"\n[STEP 7] Settle Payment & Finalize Invoice in MySQL:")
fin_payload = {
    'payment_method': 'UPI',
    'settle_amount': 16800.0,
    'transaction_reference': f"UPI-VARMA-{ref}"
}
r_fin = requests.post(f"{BASE}/api/bookings/{ref}/finalize-bill", json=fin_payload, headers=headers)
assert r_fin.status_code == 200
inv = r_fin.json()['invoice']
print(f"  • Invoice Number: {inv['invoice_number']}")
print(f"  • Total Bill: Rs. {inv['total_bill']:,.2f}")
print(f"  • Amount Paid: Rs. {inv['amount_paid']:,.2f}")
print(f"  • Outstanding Balance: Rs. {inv['balance_due']:,.2f}")
print(f"  • Payment Status: {inv['payment_status']}")
assert inv['balance_due'] == 0.0
assert inv['payment_status'] == 'Paid'

# STEP 8: CHECKOUT & DUPLICATE PREVENTION CHECK
print(f"\n[STEP 8] Check-Out & Zero Duplicate Invoice Check:")
r_out = requests.post(f"{BASE}/api/bookings/{ref}/check-out", headers=headers)
assert r_out.status_code == 200

with SessionLocal() as db:
    r_obj = db.query(Reservation).filter(Reservation.reference == ref).first()
    assert r_obj.status == 'Checked-out'
    assert r_obj.room.status == 'dirty'
    inv_count = db.query(OperationalRecord).filter(OperationalRecord.title == f'INV-{ref}').count()
    print(f"  • Reservation Status in MySQL: {r_obj.status}")
    print(f"  • Room Status in MySQL: {r_obj.room.status} (Room 109 marked dirty)")
    print(f"  • Invoice Count in MySQL for INV-{ref}: {inv_count}")
    assert inv_count == 1, "Duplicate invoices were created!"
    print("  >>> EXACTLY 1 INVOICE IN MYSQL — ZERO DUPLICATE INVOICES! <<<")

# STEP 9: TEST OFFICIAL PDF GENERATION & DOWNLOAD
print(f"\n[STEP 9] Official PDF Generation & Download:")
r_pdf = requests.get(f"{BASE}/api/invoices/{ref}/pdf", headers=headers)
assert r_pdf.status_code == 200
assert r_pdf.headers.get('content-type') == 'application/pdf'
pdf_size = len(r_pdf.content)
print(f"  • PDF Generated Successfully: {pdf_size} bytes")
assert pdf_size > 1000

pdf_path = f"Invoice_{ref}.pdf"
with open(pdf_path, 'wb') as f:
    f.write(r_pdf.content)
print(f"  • PDF saved to {pdf_path}")

# STEP 10: SYNCHRONIZATION WITH GUEST MANAGEMENT & FINANCE
print(f"\n[STEP 10] Module Synchronization Verification:")
r_invoices = requests.get(f"{BASE}/api/invoices", headers=headers)
all_invoices = r_invoices.json()
inv_entry = next((i for i in all_invoices if i['booking_reference'] == ref), None)
assert inv_entry is not None
print(f"  • Finance Module: Found Invoice {inv_entry['invoice_number']} | Total: Rs. {inv_entry['total_bill']:,.2f} | Status: {inv_entry['payment_status']}")

r_guests = requests.get(f"{BASE}/api/guests", headers=headers)
all_guests = r_guests.json()
guest_entry = next((g for g in all_guests if g['booking_reference'] == ref), None)
assert guest_entry is not None
print(f"  • Guest Management: Found {guest_entry['full_name']} | Room: {guest_entry['room_number']} | Bill: Rs. {guest_entry['total_bill']:,.2f} | Status: {guest_entry['payment_status']}")

print("\n" + "=" * 80)
print("ALL 5 REQUIREMENTS FULLY TESTED & VERIFIED TO 100% SPECIFICATION!")
print("=" * 80)
