import os
import sys
import json
from decimal import Decimal
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure UTF-8 stdout for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")

from app.main import app
from app.database.connection import Base, get_db
from app.core.config import settings
from app.core.security import hash_password
from app.models import Tenant, User, RoomType, Room, Guest, Reservation, Payment, HotelSettings, OperationalRecord

@pytest.fixture()
def client():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    with TestingSession() as db:
        # Tenants
        t1 = Tenant(id=1, name="Grand StayFlow Hotel", slug="hotel-1", code="HOTEL-001", is_active=True, status="Active")
        t2 = Tenant(id=2, name="Royal Palace Hotel", slug="hotel-2", code="HOTEL-002", is_active=True, status="Active")
        db.add_all([t1, t2])
        db.commit()

        # Hotel 1 & 2 settings
        db.add(HotelSettings(id=1, tenant_id=1, hotel_name="Grand StayFlow Hotel", gst_percent=Decimal("12.00")))
        db.add(HotelSettings(id=2, tenant_id=2, hotel_name="Royal Palace Hotel", gst_percent=Decimal("12.00")))

        # Users
        admin_h1 = User(
            email="admin@hotel.com",
            full_name="Hotel 1 Admin",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=1,
            tenant_id=1
        )
        admin_h2 = User(
            email="admin@royalpalace.com",
            full_name="Hotel 2 Admin",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=2,
            tenant_id=2
        )
        db.add_all([admin_h1, admin_h2])

        # Room Type and Room for Hotel 1:
        # 2 nights @ 8,000 / night = 16,000 subtotal + 12% GST (1,920) = 17,920.00 exact!
        rt1 = RoomType(
            tenant_id=1,
            name="Executive Suite",
            base_price=Decimal("8000.00"),
            tax_percentage=Decimal("12.00"),
            max_occupancy=2,
            description="",
            amenities="[]"
        )
        db.add(rt1)
        db.commit()

        room101 = Room(tenant_id=1, number="901", floor=1, room_type_id=rt1.id, status="vac", description="")
        db.add(room101)

        # Room Type and Room for Hotel 2 (Multi-tenancy testing)
        rt2 = RoomType(
            tenant_id=2,
            name="Deluxe Room",
            base_price=Decimal("8000.00"),
            tax_percentage=Decimal("12.00"),
            max_occupancy=2,
            description="",
            amenities="[]"
        )
        db.add(rt2)
        db.commit()

        room201 = Room(tenant_id=2, number="902", floor=2, room_type_id=rt2.id, status="vac", description="")
        db.add(room201)
        db.commit()

        # Guests
        guest1 = Guest(tenant_id=1, full_name="Rahul Sharma", email="rahul@example.com", phone="+91 98111 22334")
        guest2 = Guest(tenant_id=2, full_name="Vikram Rathore", email="vikram@example.com", phone="+91 98222 33445")
        db.add_all([guest1, guest2])
        db.commit()

        # Reservation for Hotel 1 (2 nights: 2 * 8000 = 16000 + 12% GST = 17,920.00)
        today = date.today()
        res1 = Reservation(
            tenant_id=1,
            reference="BK-SYNC17920",
            guest_id=guest1.id,
            room_id=room101.id,
            check_in=today,
            check_out=today + timedelta(days=2),
            total_amount=Decimal("17920.00"),
            status="Checked-in"
        )
        db.add(res1)

        # Reservation for Hotel 2 (to test multi-tenant cross-hotel isolation)
        res2 = Reservation(
            tenant_id=2,
            reference="BK-HOTEL2-TEST",
            guest_id=guest2.id,
            room_id=room201.id,
            check_in=today,
            check_out=today + timedelta(days=2),
            total_amount=Decimal("17920.00"),
            status="Checked-in"
        )
        db.add(res2)
        db.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def auth_header(client, email="admin@hotel.com", password="Password@123"):
    res = client.post("/api/auth/token", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}

def test_payment_synchronization_all_scenarios(client):
    headers_h1 = auth_header(client, "admin@hotel.com", "Password@123")
    headers_h2 = auth_header(client, "admin@royalpalace.com", "Password@123")

    # Fetch booking ID for BK-SYNC17920
    res_list = client.get("/api/bookings", headers=headers_h1).json()
    b1 = next(b for b in res_list if b["reference"] == "BK-SYNC17920")
    b1_id = b1["reservation_id"]

    # -------------------------------------------------------------------------
    # SCENARIO 1: Rs. 17,920 invoice with no payment -> Pending
    # -------------------------------------------------------------------------
    inv_res = client.get("/api/public/booking/invoice/BK-SYNC17920?hotel=HOTEL-001")
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert inv_data["total_bill"] == 17920.0, f"Expected 17920.0, got {inv_data['total_bill']}"
    assert inv_data["amount_paid"] == 0.0
    assert inv_data["balance_due"] == 17920.0
    assert inv_data["payment_status"] == "Pending"

    # Verify that list_all_invoices returns Pending
    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    assert inv_record["total_bill"] == 17920.0
    assert inv_record["amount_paid"] == 0.0
    assert inv_record["balance_due"] == 17920.0
    assert inv_record["payment_status"] == "Pending"
    print("\n[PASS] Scenario 1: Rs. 17,920 invoice with no payment -> Pending (Paid: Rs. 0, Balance: Rs. 17,920)")

    # -------------------------------------------------------------------------
    # SCENARIO 2: Rs. 17,920 invoice with Rs. 5,000 payment -> Partially Paid
    # -------------------------------------------------------------------------
    pay_res = client.post("/api/payments", json={
        "reservation_id": b1_id,
        "amount": 5000.0,
        "method": "UPI",
        "status": "Paid",
        "transaction_reference": "TXN-5000-TEST"
    }, headers=headers_h1)
    assert pay_res.status_code == 201
    pay1_id = pay_res.json()["id"]

    # Invoices list must immediately reflect the update
    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    assert inv_record["amount_paid"] == 5000.0, f"Expected 5000.0, got {inv_record['amount_paid']}"
    assert inv_record["balance_due"] == 12920.0, f"Expected 12920.0, got {inv_record['balance_due']}"
    assert inv_record["payment_status"] == "Partially Paid"

    # Public invoice must also be synchronized
    pub_inv = client.get("/api/public/booking/invoice/BK-SYNC17920?hotel=HOTEL-001").json()
    assert pub_inv["amount_paid"] == 5000.0
    assert pub_inv["balance_due"] == 12920.0
    assert pub_inv["payment_status"] == "Partially Paid"
    print("[PASS] Scenario 2: Rs. 17,920 invoice with Rs. 5,000 payment -> Partially Paid (Paid: Rs. 5,000, Balance: Rs. 12,920)")

    # -------------------------------------------------------------------------
    # SCENARIO 3: Rs. 17,920 invoice with full balance cleared (adding Rs. 12,920) -> Paid
    # -------------------------------------------------------------------------
    pay_res2 = client.post("/api/payments", json={
        "reservation_id": b1_id,
        "amount": 12920.0,
        "method": "Credit Card",
        "status": "Paid",
        "transaction_reference": "TXN-12920-TEST"
    }, headers=headers_h1)
    assert pay_res2.status_code == 201
    pay2_id = pay_res2.json()["id"]

    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    assert inv_record["amount_paid"] == 17920.0
    assert inv_record["balance_due"] == 0.0
    assert inv_record["payment_status"] == "Paid"
    print("[PASS] Scenario 3: Rs. 17,920 invoice with full payment -> Paid (Paid: Rs. 17,920, Balance: Rs. 0)")

    # -------------------------------------------------------------------------
    # SCENARIO 4: Reset & test Rs. 10,000 + Rs. 7,920 payments -> Paid
    # Delete previous two payments to reset
    # -------------------------------------------------------------------------
    client.delete(f"/api/payments/{pay1_id}", headers=headers_h1)
    client.delete(f"/api/payments/{pay2_id}", headers=headers_h1)

    # After deleting, invoice must revert to Pending
    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    assert inv_record["amount_paid"] == 0.0
    assert inv_record["balance_due"] == 17920.0
    assert inv_record["payment_status"] == "Pending"

    # Add Payment 1: Rs. 10,000
    p_a = client.post("/api/payments", json={
        "reservation_id": b1_id,
        "amount": 10000.0,
        "method": "Bank Transfer",
        "status": "Paid",
        "transaction_reference": "TXN-10000-TEST"
    }, headers=headers_h1).json()

    # Add Payment 2: Rs. 7,920
    p_b = client.post("/api/payments", json={
        "reservation_id": b1_id,
        "amount": 7920.0,
        "method": "UPI",
        "status": "Paid",
        "transaction_reference": "TXN-7920-TEST"
    }, headers=headers_h1).json()

    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    assert inv_record["amount_paid"] == 17920.0
    assert inv_record["balance_due"] == 0.0
    assert inv_record["payment_status"] == "Paid"
    print("[PASS] Scenario 4: Rs. 17,920 invoice with Rs. 10,000 + Rs. 7,920 payments -> Paid (Paid: Rs. 17,920, Balance: Rs. 0)")

    # -------------------------------------------------------------------------
    # SCENARIO 5: Refund a payment -> Recalculate balance and status correctly
    # Refund the Rs. 7,920 payment (p_b)
    # -------------------------------------------------------------------------
    patch_res = client.patch(f"/api/payments/{p_b['id']}", json={"status": "Refunded"}, headers=headers_h1)
    assert patch_res.status_code == 200

    invoices = client.get("/api/invoices", headers=headers_h1).json()
    inv_record = next(i for i in invoices if i["booking_reference"] == "BK-SYNC17920")
    # Only the Rs. 10,000 payment should remain Paid
    assert inv_record["amount_paid"] == 10000.0, f"Expected 10000.0, got {inv_record['amount_paid']}"
    assert inv_record["balance_due"] == 7920.0, f"Expected 7920.0, got {inv_record['balance_due']}"
    assert inv_record["payment_status"] == "Partially Paid"
    print("[PASS] Scenario 5: Refunded Rs. 7,920 payment -> Recalculated (Paid: Rs. 10,000, Balance: Rs. 7,920, Status: Partially Paid)")

    # -------------------------------------------------------------------------
    # SCENARIO 6: Multi-tenant Isolation: payments from another hotel are never included
    # -------------------------------------------------------------------------
    # Get Hotel 2 booking
    res_list_h2 = client.get("/api/bookings", headers=headers_h2).json()
    b2 = next(b for b in res_list_h2 if b["reference"] == "BK-HOTEL2-TEST")
    b2_id = b2["reservation_id"]

    # Record a Rs. 17,920 payment for Hotel 2's booking
    client.post("/api/payments", json={
        "reservation_id": b2_id,
        "amount": 17920.0,
        "method": "Cash",
        "status": "Paid",
        "transaction_reference": "TXN-HOTEL2-17920"
    }, headers=headers_h2)

    # Hotel 1's invoice must NOT be affected by Hotel 2's payment!
    invoices_h1 = client.get("/api/invoices", headers=headers_h1).json()
    inv_h1 = next(i for i in invoices_h1 if i["booking_reference"] == "BK-SYNC17920")
    assert inv_h1["amount_paid"] == 10000.0, f"Cross-tenant leak! Expected 10000.0, got {inv_h1['amount_paid']}"
    assert inv_h1["balance_due"] == 7920.0
    assert inv_h1["payment_status"] == "Partially Paid"

    # Hotel 2's invoice must show Paid: Rs. 17,920, Balance: Rs. 0, Status: Paid
    invoices_h2 = client.get("/api/invoices", headers=headers_h2).json()
    inv_h2 = next(i for i in invoices_h2 if i["booking_reference"] == "BK-HOTEL2-TEST")
    assert inv_h2["amount_paid"] == 17920.0
    assert inv_h2["balance_due"] == 0.0
    assert inv_h2["payment_status"] == "Paid"

    # Hotel 1 must never see Hotel 2's invoice
    assert not any(i["booking_reference"] == "BK-HOTEL2-TEST" for i in invoices_h1)
    # Hotel 2 must never see Hotel 1's invoice
    assert not any(i["booking_reference"] == "BK-SYNC17920" for i in invoices_h2)
    print("[PASS] Scenario 6: Multi-tenant isolation verified - zero cross-hotel payment leakage")
