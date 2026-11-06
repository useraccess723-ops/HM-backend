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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ["TESTING"] = "1"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_stayflow2026mock"
os.environ["RAZORPAY_KEY_SECRET"] = "stayflow_rzp_test_secret_mock_2026"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "stayflow_rzp_whsec_mock_2026"
os.environ["RAZORPAY_MODE"] = "test"

from app.main import app
from app.database.connection import Base, get_db
from app.core.config import settings
from app.core.security import hash_password
from app.models import Tenant, User, RoomType, Room, Guest, Reservation, Payment, HotelSettings, OperationalRecord
from app.services.razorpay_service import razorpay_service

@pytest.fixture()
def client(monkeypatch):
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    settings.RAZORPAY_KEY_ID = "rzp_test_stayflow2026mock"
    settings.RAZORPAY_KEY_SECRET = "stayflow_rzp_test_secret_mock_2026"
    settings.RAZORPAY_WEBHOOK_SECRET = "stayflow_rzp_whsec_mock_2026"
    settings.RAZORPAY_MODE = "test"

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr('app.database.connection.SessionLocal', TestingSession)
    monkeypatch.setattr('app.database.connection.engine', test_engine)
    monkeypatch.setattr('app.main.engine', test_engine)
    monkeypatch.setattr('app.main.init_db_with_retry', lambda *args, **kwargs: None)
    Base.metadata.create_all(bind=test_engine)

    with TestingSession() as db:
        # Tenant 1: Grand Meridian Chennai
        t1 = Tenant(id=1, name="Grand Meridian Chennai", slug="grand-meridian", code="HOTEL-001", is_active=True, status="Active")
        # Tenant 10: ABC Hotel
        t10 = Tenant(id=10, name="ABC Hotel", slug="abc-hotel", code="AH-005", is_active=True, status="Active")
        db.add_all([t1, t10])
        db.commit()

        # Hotel Settings
        db.add(HotelSettings(id=1, tenant_id=1, hotel_name="Grand Meridian Chennai", gst_percent=Decimal("12.00")))
        db.add(HotelSettings(id=10, tenant_id=10, hotel_name="ABC Hotel", gst_percent=Decimal("12.00")))

        # Users
        admin1 = User(
            email="admin@meridian.com",
            full_name="Meridian Admin",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=1,
            tenant_id=1
        )
        admin10 = User(
            email="admin@abchotel.com",
            full_name="ABC Admin",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=10,
            tenant_id=10
        )
        staff_unauthorized = User(
            email="cleaner@meridian.com",
            full_name="Cleaner",
            password_hash=hash_password("Password@123"),
            role="HOUSEKEEPING",
            hotel_id=1,
            tenant_id=1
        )
        customer_user = User(
            email="customer@hotel.com",
            full_name="Vikram Malhotra",
            password_hash=hash_password("Password@123"),
            role="CUSTOMER",
            hotel_id=1,
            tenant_id=1
        )
        db.add_all([admin1, admin10, staff_unauthorized, customer_user])
        db.commit()

        # Room Types & Rooms for Hotel 1
        rt1 = RoomType(tenant_id=1, name="Deluxe Room", base_price=Decimal("5000.00"), tax_percentage=Decimal("12.00"), max_occupancy=2, description="", amenities="[]")
        db.add(rt1)
        db.commit()
        rm1 = Room(tenant_id=1, number="101", floor=1, room_type_id=rt1.id, status="vac", description="")
        db.add(rm1)

        # Room Types & Rooms for Hotel 10 (ABC Hotel)
        rt10 = RoomType(tenant_id=10, name="Standard Room", base_price=Decimal("4000.00"), tax_percentage=Decimal("12.00"), max_occupancy=2, description="", amenities="[]")
        db.add(rt10)
        db.commit()
        rm10 = Room(tenant_id=10, number="201", floor=2, room_type_id=rt10.id, status="vac", description="")
        db.add(rm10)
        db.commit()

        # Room type for 10080 total (2 nights x 4500 = 9000 + 12% GST 1080 = 10080)
        rt_sc4 = RoomType(tenant_id=1, name="Executive Suite", base_price=Decimal("4500.00"), tax_percentage=Decimal("12.00"), max_occupancy=2, description="", amenities="[]")
        db.add(rt_sc4)
        db.commit()
        rm_sc4 = Room(tenant_id=1, number="103", floor=1, room_type_id=rt_sc4.id, status="occ", description="")
        db.add(rm_sc4)
        db.commit()

        # Guests
        g1 = Guest(tenant_id=1, full_name="Aarav Patel", email="aarav@example.com", phone="+91 99000 11223")
        g10 = Guest(tenant_id=10, full_name="Koushik Sharma", email="koushik@example.com", phone="+91 99000 44556")
        db.add_all([g1, g10])
        db.commit()

        today = date.today()
        # Booking 1 (Hotel 1): 2 nights @ 5,000 = 10,000 + 12% GST (1,200) = 11,200 total
        res1 = Reservation(
            id=101,
            tenant_id=1,
            reference="BK-MERIDIAN-01",
            guest_id=g1.id,
            room_id=rm1.id,
            check_in=today,
            check_out=today + timedelta(days=2),
            total_amount=Decimal("11200.00"),
            status="Confirmed"
        )
        # Booking 10 (ABC Hotel): 1 night @ 4,000 = 4,000 + 12% GST (480) = 4,480 total
        res10 = Reservation(
            id=102,
            tenant_id=10,
            reference="BK-ABC-01",
            guest_id=g10.id,
            room_id=rm10.id,
            check_in=today,
            check_out=today + timedelta(days=1),
            total_amount=Decimal("4480.00"),
            status="Confirmed"
        )
        gcust = Guest(tenant_id=1, full_name="Vikram Malhotra", email="customer@hotel.com", phone="+91 98765 43210")
        db.add(gcust)
        db.commit()

        res_cust = Reservation(
            id=103,
            tenant_id=1,
            reference="BK-CUST2026",
            guest_id=gcust.id,
            room_id=rm_sc4.id,
            check_in=today,
            check_out=today + timedelta(days=2),
            total_amount=Decimal("10080.00"),
            status="Checked-in"
        )
        db.add_all([res1, res10, res_cust])
        db.commit()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def get_token(client, email, password):
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return r.json()["access_token"]


# ===========================================================================
# 1. ADMIN PAYMENT TESTS (Order, Verify, Signature, Status, Balance)
# ===========================================================================

def test_admin_create_order_and_verify_success(client):
    """Scenario 1 & 5: Admin creates Razorpay order, verifies signature, captures payment in full."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    # 1. Create order for full balance
    order_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01"},
        headers=h1
    )
    assert order_res.status_code == 200, order_res.text
    data = order_res.json()
    assert data["status"] == "success"
    order_id = data["order_id"]
    assert order_id.startswith("order_")
    assert data["amount_inr"] == 11200.0
    assert data["amount"] == 1120000  # in paise
    assert data["currency"] == "INR"
    assert data["key_id"].startswith("rzp_test_")

    # 2. Verify with valid HMAC signature
    payment_id = "pay_test_meridian_01"
    valid_sig = razorpay_service.create_mock_signature(order_id, payment_id)

    verify_res = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": valid_sig,
            "booking_reference": "BK-MERIDIAN-01"
        },
        headers=h1
    )
    assert verify_res.status_code == 200, verify_res.text
    v_data = verify_res.json()
    assert v_data["status"] == "success"
    assert v_data["transaction_id"] == payment_id
    assert v_data["invoice"]["payment_status"] == "Paid"
    assert v_data["invoice"]["balance_due"] == 0.0
    assert v_data["invoice"]["amount_paid"] == 11200.0

    # 3. Check /api/payments ledger shows status="Paid", method="Razorpay"
    ledger_res = client.get("/api/payments", headers=h1)
    assert ledger_res.status_code == 200
    payments = ledger_res.json()
    matched = [p for p in payments if p["transaction_reference"] == payment_id]
    assert len(matched) == 1
    assert matched[0]["status"] == "Paid"
    assert matched[0]["method"] == "Razorpay"


def test_invalid_signature_rejection(client):
    """Scenario 12: Invalid payment signature is rejected with HTTP 400."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    order_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01", "amount": 2000.0},
        headers=h1
    )
    assert order_res.status_code == 200
    order_id = order_res.json()["order_id"]

    verify_res = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_test_tampered",
            "razorpay_signature": "invalid_forged_signature_hex",
            "booking_reference": "BK-MERIDIAN-01"
        },
        headers=h1
    )
    assert verify_res.status_code == 400
    assert "Invalid Razorpay payment signature" in verify_res.json()["detail"]


def test_partial_payment_and_subsequent_balance_settlement(client):
    """Scenario 6 & 7: Partial invoice payment followed by remaining balance settlement."""
    tok10 = get_token(client, "admin@abchotel.com", "Password@123")
    h10 = {"Authorization": f"Bearer {tok10}", "X-Hotel-ID": "10"}

    # Total bill is 4,480. Pay 2,000 partial.
    order1 = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 2000.0},
        headers=h10
    ).json()
    pay_id1 = "pay_test_part1"
    sig1 = razorpay_service.create_mock_signature(order1["order_id"], pay_id1)

    v1 = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": order1["order_id"],
            "razorpay_payment_id": pay_id1,
            "razorpay_signature": sig1
        },
        headers=h10
    ).json()

    assert v1["invoice"]["payment_status"] == "Partially Paid"
    assert v1["invoice"]["amount_paid"] == 2000.0
    assert v1["invoice"]["balance_due"] == 2480.0

    # Attempt to pay more than remaining balance (e.g. 3,000 > 2,480) -> REJECTED
    exceed_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 3000.0},
        headers=h10
    )
    assert exceed_res.status_code == 400
    assert "cannot exceed outstanding balance" in exceed_res.json()["detail"]

    # Settle remaining 2,480
    order2 = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 2480.0},
        headers=h10
    ).json()
    pay_id2 = "pay_test_part2"
    sig2 = razorpay_service.create_mock_signature(order2["order_id"], pay_id2)

    v2 = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": order2["order_id"],
            "razorpay_payment_id": pay_id2,
            "razorpay_signature": sig2
        },
        headers=h10
    ).json()

    assert v2["invoice"]["payment_status"] == "Paid"
    assert v2["invoice"]["amount_paid"] == 4480.0
    assert v2["invoice"]["balance_due"] == 0.0


def test_duplicate_verification_idempotency(client):
    """Scenario 9: Submitting verification twice does not create duplicate payment records or counts."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    order = client.post("/api/payments/razorpay/create-order", json={"booking_reference": "BK-MERIDIAN-01", "amount": 1000.0}, headers=h1).json()
    pay_id = "pay_test_idem_01"
    sig = razorpay_service.create_mock_signature(order["order_id"], pay_id)

    # First verify
    r1 = client.post("/api/payments/razorpay/verify", json={"razorpay_order_id": order["order_id"], "razorpay_payment_id": pay_id, "razorpay_signature": sig}, headers=h1)
    assert r1.status_code == 200

    # Second verify with exact same details -> Idempotent success
    r2 = client.post("/api/payments/razorpay/verify", json={"razorpay_order_id": order["order_id"], "razorpay_payment_id": pay_id, "razorpay_signature": sig}, headers=h1)
    assert r2.status_code == 200
    assert r2.json()["status"] == "success"

    # Ledger check: exactly ONE payment with this payment_id exists
    ledger = client.get("/api/payments", headers=h1).json()
    matching = [p for p in ledger if p["transaction_reference"] == pay_id]
    assert len(matching) == 1


def test_failed_checkout_handling(client):
    """Scenario 2 & 3: Failed / cancelled checkout records status as Failed without corrupting invoices."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    order = client.post("/api/payments/razorpay/create-order", json={"booking_reference": "BK-MERIDIAN-01", "amount": 1500.0}, headers=h1).json()
    fail_res = client.post(
        "/api/payments/razorpay/failed",
        json={"razorpay_order_id": order["order_id"], "error_code": "BAD_REQUEST_ERROR", "error_description": "Payment was cancelled by user"},
        headers=h1
    )
    assert fail_res.status_code == 200

    # Verify that the payment status is Failed and not counted in invoice
    ledger = client.get("/api/payments", headers=h1).json()
    failed_pays = [p for p in ledger if p["transaction_reference"] == order["order_id"]]
    assert len(failed_pays) == 1
    assert failed_pays[0]["status"] == "Failed"


def test_unauthorized_user_cannot_initiate_payment(client):
    """Admin scenario 2: Housekeeping / unauthorized role cannot create Razorpay orders."""
    cleaner_tok = get_token(client, "cleaner@meridian.com", "Password@123")
    h_cleaner = {"Authorization": f"Bearer {cleaner_tok}", "X-Hotel-ID": "1"}

    res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01"},
        headers=h_cleaner
    )
    assert res.status_code == 403


# ===========================================================================
# 2. GUEST PUBLIC PORTAL TESTS
# ===========================================================================

def test_guest_public_order_create_and_verify(client):
    """Guest test 1: Public guest initiates order with hotel code, verifies signature, checks invoice."""
    # 1. Public order creation for ABC Hotel (tenant code AH-005)
    pub_order = client.post(
        "/api/public/payments/razorpay/create-order",
        json={
            "booking_reference": "BK-ABC-01",
            "hotel": "AH-005",
            "amount": 1000.0,
            "phone": "+91 99000 44556"
        }
    )
    assert pub_order.status_code == 200, pub_order.text
    order_data = pub_order.json()
    assert order_data["status"] == "success"
    assert order_data["amount"] == 100000

    # 2. Public verification
    pay_id = "pay_test_guest_abc_01"
    sig = razorpay_service.create_mock_signature(order_data["order_id"], pay_id)

    pub_verify = client.post(
        "/api/public/payments/razorpay/verify",
        json={
            "razorpay_order_id": order_data["order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "hotel": "AH-005"
        }
    )
    assert pub_verify.status_code == 200
    v_json = pub_verify.json()
    assert v_json["status"] == "success"
    assert v_json["invoice"]["amount_paid"] >= 1000.0


def test_guest_phone_mismatch_rejected(client):
    """Guest test 5: Mismatched guest phone number is rejected."""
    res = client.post(
        "/api/public/payments/razorpay/create-order",
        json={
            "booking_reference": "BK-ABC-01",
            "hotel": "AH-005",
            "amount": 500.0,
            "phone": "9999999999"  # Does not match registered guest
        }
    )
    assert res.status_code == 403


# ===========================================================================
# 3. RAZORPAY WEBHOOK INTEGRATION TESTS
# ===========================================================================

def test_razorpay_webhook_payment_captured(client):
    """Scenario 10: Razorpay webhook payment.captured marks payment as Paid idempotently."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    order = client.post("/api/payments/razorpay/create-order", json={"booking_reference": "BK-MERIDIAN-01", "amount": 2500.0}, headers=h1).json()
    order_id = order["order_id"]
    payment_id = "pay_webhook_captured_01"

    webhook_payload = {
        "entity": "event",
        "id": "evt_test_captured_01",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": 250000,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        },
        "created_at": 1730370100
    }
    raw_body = json.dumps(webhook_payload).encode("utf-8")
    sig = razorpay_service.create_mock_webhook_signature(raw_body)

    # Send webhook
    res = client.post(
        "/api/webhooks/razorpay",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig}
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "success"

    # Verify payment in DB
    ledger = client.get("/api/payments", headers=h1).json()
    p = [x for x in ledger if x["transaction_reference"] == payment_id]
    assert len(p) == 1
    assert p[0]["status"] == "Paid"

    # Send duplicate webhook -> Handled idempotently
    dup_res = client.post(
        "/api/webhooks/razorpay",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig}
    )
    assert dup_res.status_code == 200
    assert dup_res.json()["status"] == "already_processed"


def test_razorpay_webhook_invalid_signature_rejected(client):
    """Scenario 12: Webhook with invalid signature is rejected with HTTP 400."""
    body = b'{"event":"payment.captured"}'
    res = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "invalid_sig"}
    )
    assert res.status_code == 400


def test_razorpay_webhook_refund_processed(client):
    """Scenario 11: Webhook refund.processed marks payment as Refunded and adjusts invoice balance."""
    tok1 = get_token(client, "admin@meridian.com", "Password@123")
    h1 = {"Authorization": f"Bearer {tok1}", "X-Hotel-ID": "1"}

    order = client.post("/api/payments/razorpay/create-order", json={"booking_reference": "BK-MERIDIAN-01", "amount": 3000.0}, headers=h1).json()
    pay_id = "pay_to_be_refunded_01"
    sig = razorpay_service.create_mock_signature(order["order_id"], pay_id)
    client.post("/api/payments/razorpay/verify", json={"razorpay_order_id": order["order_id"], "razorpay_payment_id": pay_id, "razorpay_signature": sig}, headers=h1)

    # Webhook refund.processed
    webhook_payload = {
        "entity": "event",
        "id": "evt_test_refund_01",
        "event": "refund.processed",
        "contains": ["refund"],
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_test_123",
                    "payment_id": pay_id,
                    "amount": 300000,
                    "currency": "INR",
                    "status": "processed"
                }
            }
        },
        "created_at": 1730370200
    }
    raw_body = json.dumps(webhook_payload).encode("utf-8")
    wh_sig = razorpay_service.create_mock_webhook_signature(raw_body)

    wh_res = client.post(
        "/api/webhooks/razorpay",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": wh_sig}
    )
    assert wh_res.status_code == 200

    # Check that payment is now Refunded
    ledger = client.get("/api/payments", headers=h1).json()
    p = [x for x in ledger if x["transaction_reference"] == pay_id][0]
    assert p["status"] == "Refunded"


# ===========================================================================
# 4. STRICT MULTI-TENANT ISOLATION TESTS
# ===========================================================================

def test_strict_multi_tenant_isolation(client):
    """
    Multi-tenant scenarios 1-7:
    - ABC Hotel (tenant 10) cannot create or verify payments for Grand Meridian (tenant 1).
    - Grand Meridian (tenant 1) cannot create or verify payments for ABC Hotel (tenant 10).
    - Payment records from one hotel are completely invisible to the other hotel.
    """
    tok_meridian = get_token(client, "admin@meridian.com", "Password@123")
    tok_abc = get_token(client, "admin@abchotel.com", "Password@123")

    h_meridian = {"Authorization": f"Bearer {tok_meridian}", "X-Hotel-ID": "1"}
    h_abc = {"Authorization": f"Bearer {tok_abc}", "X-Hotel-ID": "10"}

    # 1. ABC Hotel admin attempts to create Razorpay order for Grand Meridian booking -> 404/403
    cross_order = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01", "amount": 1000.0},
        headers=h_abc
    )
    assert cross_order.status_code in (403, 404)

    # 2. Grand Meridian admin attempts to create Razorpay order for ABC Hotel booking -> 404/403
    cross_order2 = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 1000.0},
        headers=h_meridian
    )
    assert cross_order2.status_code in (403, 404)

    # 3. Create legitimate payment for ABC Hotel
    abc_order = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 500.0},
        headers=h_abc
    ).json()
    abc_pay_id = "pay_iso_abc_999"
    abc_sig = razorpay_service.create_mock_signature(abc_order["order_id"], abc_pay_id)
    client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": abc_order["order_id"],
            "razorpay_payment_id": abc_pay_id,
            "razorpay_signature": abc_sig
        },
        headers=h_abc
    )

    # 4. Grand Meridian queries /api/payments -> Must NOT see ABC Hotel payment
    meridian_ledger = client.get("/api/payments", headers=h_meridian).json()
    abc_leaks = [p for p in meridian_ledger if p["transaction_reference"] == abc_pay_id]
    assert len(abc_leaks) == 0, "Security Violation: ABC Hotel payment leaked into Grand Meridian ledger!"

    # 5. Cross-tenant public verification attempt: Public request with Hotel 1 header/code for Hotel 10 order -> 403
    cross_pub_verify = client.post(
        "/api/public/payments/razorpay/verify",
        json={
            "razorpay_order_id": abc_order["order_id"],
            "razorpay_payment_id": abc_pay_id,
            "razorpay_signature": abc_sig,
            "hotel": "HOTEL-001"  # Grand Meridian code for ABC payment
        }
    )
    assert cross_pub_verify.status_code == 403



# ===========================================================================
# 5. FULL BALANCE SETTLEMENT (SCENARIO 4) & CUSTOMER PORTAL WORKFLOW
# ===========================================================================

def test_full_balance_settlement_scenario_4(client):
    """
    Test Case 4: Full balance settlement scenario:
    - Invoice with Total ₹10,080.00 (Room ₹9,000 + GST ₹1,080).
    - Initial payment: ₹7,000.00 recorded.
    - Initial balance due: ₹3,080.00. Payment status: Partially Paid.
    - Razorpay order created for remaining balance (omit amount or pass 3080.0).
    - Assert order amount in paise is exactly 308,000 paise (₹3,080.00).
    - Verify payment with valid Razorpay HMAC-SHA256 signature.
    - Assert invoice transitions to status: 'Paid' (Fully Paid).
    - Assert amount_paid == 10,080.00, balance_due == 0.00.
    - Assert payment ledger contains both initial ₹7,000 and settlement ₹3,080.
    """
    tok_admin = get_token(client, "admin@meridian.com", "Password@123")
    h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Hotel-ID": "1"}

    # 1. Record initial partial payment of 7,000.00 via standard payment or Razorpay
    init_order = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-CUST2026", "amount": 7000.0},
        headers=h_admin
    ).json()
    assert init_order["amount"] == 700000  # 700,000 paise

    init_pay_id = "pay_sc4_initial_7000"
    init_sig = razorpay_service.create_mock_signature(init_order["order_id"], init_pay_id)
    verify_init = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": init_order["order_id"],
            "razorpay_payment_id": init_pay_id,
            "razorpay_signature": init_sig
        },
        headers=h_admin
    )
    assert verify_init.status_code == 200
    inv1 = verify_init.json()["invoice"]
    assert inv1["total_bill"] == 10080.0
    assert inv1["amount_paid"] == 7000.0
    assert inv1["balance_due"] == 3080.0
    assert inv1["payment_status"] == "Partially Paid"

    # 2. Settle remaining balance: Call create-order WITHOUT explicit amount (defaults to balance_due)
    settle_order_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-CUST2026"},
        headers=h_admin
    )
    assert settle_order_res.status_code == 200
    settle_order = settle_order_res.json()
    # Check exact paise: 3,080 * 100 = 308,000 paise
    assert settle_order["amount"] == 308000
    assert settle_order["currency"] == "INR"

    # 3. Complete Razorpay checkout with valid signature
    settle_pay_id = "pay_sc4_settle_3080"
    settle_sig = razorpay_service.create_mock_signature(settle_order["order_id"], settle_pay_id)
    verify_settle = client.post(
        "/api/payments/razorpay/verify",
        json={
            "razorpay_order_id": settle_order["order_id"],
            "razorpay_payment_id": settle_pay_id,
            "razorpay_signature": settle_sig
        },
        headers=h_admin
    )
    assert verify_settle.status_code == 200
    inv2 = verify_settle.json()["invoice"]
    assert inv2["total_bill"] == 10080.0
    assert inv2["amount_paid"] == 10080.0
    assert inv2["balance_due"] == 0.0
    assert inv2["payment_status"] == "Paid"  # Fully Paid

    # 4. Attempt further payment on fully settled booking -> REJECTED (Balance is 0)
    zero_bal_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-CUST2026", "amount": 100.0},
        headers=h_admin
    )
    assert zero_bal_res.status_code == 400
    assert "already fully paid" in zero_bal_res.json()["detail"].lower() or "outstanding balance" in zero_bal_res.json()["detail"].lower()


def test_customer_portal_login_billing_and_payment_flow(client):
    """
    FLOW B: Guest / Customer Account Login Flow:
    - Login as authenticated customer (customer@hotel.com, Password@123).
    - Query /api/customer/bookings/BK-CUST2026/billing.
    - Verify customer sees their own reservation, total bill, paid amount, and remaining balance.
    - Customer creates Razorpay order via /api/customer/payments/razorpay/create-order.
    - Customer completes checkout and verifies via /api/customer/payments/razorpay/verify.
    - Multi-Tenant & Cross-Customer Isolation:
      * Customer cannot view or pay for another customer's booking.
      * Customer cannot access bookings belonging to ABC Hotel (tenant 10).
    """
    tok_cust = get_token(client, "customer@hotel.com", "Password@123")
    h_cust = {"Authorization": f"Bearer {tok_cust}"}

    # 1. Customer retrieves billing for their own booking
    billing_res = client.get("/api/customer/bookings/BK-CUST2026/billing", headers=h_cust)
    assert billing_res.status_code == 200
    b_data = billing_res.json()
    assert b_data["booking_reference"] == "BK-CUST2026"
    assert b_data["status"] == "Checked-in"
    assert b_data["billing"]["total_bill"] == 10080.0

    # 2. Customer creates Razorpay order for partial payment of 2,000
    cust_order_res = client.post(
        "/api/customer/payments/razorpay/create-order",
        json={"booking_reference": "BK-CUST2026", "amount": 2000.0},
        headers=h_cust
    )
    assert cust_order_res.status_code == 200
    cust_order = cust_order_res.json()
    assert cust_order["amount"] == 200000

    # 3. Customer verifies payment
    c_pay_id = "pay_cust_test_2000"
    c_sig = razorpay_service.create_mock_signature(cust_order["order_id"], c_pay_id)
    c_verify_res = client.post(
        "/api/customer/payments/razorpay/verify",
        json={
            "razorpay_order_id": cust_order["order_id"],
            "razorpay_payment_id": c_pay_id,
            "razorpay_signature": c_sig,
            "booking_reference": "BK-CUST2026"
        },
        headers=h_cust
    )
    assert c_verify_res.status_code == 200
    c_vdata = c_verify_res.json()
    assert c_vdata["invoice"]["amount_paid"] == 2000.0
    assert c_vdata["invoice"]["balance_due"] == 8080.0
    assert c_vdata["invoice"]["payment_status"] == "Partially Paid"

    # 4. Multi-Tenant & Cross-Customer Isolation:
    # Customer attempts to access ABC Hotel booking BK-ABC-01 -> HTTP 403 / 404
    cross_tenant_res = client.get("/api/customer/bookings/BK-ABC-01/billing", headers=h_cust)
    assert cross_tenant_res.status_code in (403, 404)

    cross_tenant_pay = client.post(
        "/api/customer/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 1000.0},
        headers=h_cust
    )
    assert cross_tenant_pay.status_code in (403, 404)

    # Customer attempts to access another guest's booking in Grand Meridian BK-MERIDIAN-01 -> HTTP 403
    cross_cust_res = client.get("/api/customer/bookings/BK-MERIDIAN-01/billing", headers=h_cust)
    assert cross_cust_res.status_code in (403, 404)


def test_customer_vs_admin_roles_and_api_guarding(client):
    """
    Verifies role detection, assigned dashboard selection, and backend route guards:
    1. Customer login returns role='CUSTOMER' and assigned_dashboard='customer' (never 'admin').
    2. Admin login returns role='ADMIN' and assigned_dashboard='admin'.
    3. Customer calling /api/dashboard is blocked with HTTP 403.
    4. Customer calling /api/guests is blocked with HTTP 403.
    5. Customer calling POST /api/bookings is blocked with HTTP 403.
    6. Customer calling GET /api/bookings only receives their own reservation(s).
    7. Admin calling /api/dashboard and /api/guests succeeds with HTTP 200.
    """
    # 1. Customer Login Response Inspection
    cust_login = client.post("/api/auth/login", json={"email": "customer@hotel.com", "password": "Password@123"})
    assert cust_login.status_code == 200
    cust_data = cust_login.json()
    assert cust_data["user"]["role"] == "CUSTOMER"
    assert cust_data["user"]["assigned_dashboard"] == "customer"

    # 2. Admin Login Response Inspection
    admin_login = client.post("/api/auth/login", json={"email": "admin@meridian.com", "password": "Password@123"})
    assert admin_login.status_code == 200
    admin_data = admin_login.json()
    assert admin_data["user"]["role"] == "ADMIN"
    assert admin_data["user"]["assigned_dashboard"] == "admin"

    tok_cust = cust_data["access_token"]
    tok_admin = admin_data["access_token"]
    h_cust = {"Authorization": f"Bearer {tok_cust}"}
    h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Hotel-ID": "1"}

    # 3. Customer calling administrative dashboard -> 403
    cust_dash = client.get("/api/dashboard", headers=h_cust)
    assert cust_dash.status_code == 403
    assert "Customers cannot access administrative dashboards" in cust_dash.json()["detail"]

    # 4. Customer calling guest directory -> 403
    cust_guests = client.get("/api/guests", headers=h_cust)
    assert cust_guests.status_code == 403
    assert "Guest directory is restricted to hotel staff" in cust_guests.json()["detail"]

    # 5. Customer calling administrative booking creation -> 403
    cust_create_bk = client.post("/api/bookings", json={"check_in": "2026-11-01", "check_out": "2026-11-03", "room_id": 1}, headers=h_cust)
    assert cust_create_bk.status_code == 403

    # 6. Customer calling list bookings -> only sees own booking
    cust_bookings = client.get("/api/bookings", headers=h_cust)
    assert cust_bookings.status_code == 200
    bks = cust_bookings.json()
    assert len(bks) >= 1
    for b in bks:
        assert b["reference"] == "BK-CUST2026"

    # 7. Admin calling administrative endpoints -> 200 OK
    admin_dash = client.get("/api/dashboard", headers=h_admin)
    assert admin_dash.status_code == 200
    admin_guests = client.get("/api/guests", headers=h_admin)
    assert admin_guests.status_code == 200


def test_customer_registration_workflow_and_isolation(client):
    """
    Verify Customer Registration:
    1. Validation: requires name, email, phone, matching passwords, and hotel context.
    2. Tenant resolution: verifies tenant exists and associates account strictly to that tenant.
    3. Exclusively assigns ROLE=CUSTOMER (cannot escalate to privileged role).
    4. Prevents duplicate accounts without modifying existing passwords.
    5. Newly registered customer logs in, receives role=CUSTOMER and assigned_dashboard=customer.
    """
    # 1. Missing hotel context -> 400
    res_no_hotel = client.post(
        "/api/public/customer-registration",
        json={
            "full_name": "Aditya Verma",
            "email": "aditya.verma@example.com",
            "phone": "+91 98765 00111",
            "password": "Customer@2026",
            "confirm_password": "Customer@2026"
        }
    )
    assert res_no_hotel.status_code == 400
    assert "Hotel property context is required" in res_no_hotel.json()["detail"]

    # 2. Password mismatch -> 422
    res_mismatch = client.post(
        "/api/public/customer-registration?hotel=HOTEL-001",
        json={
            "full_name": "Aditya Verma",
            "email": "aditya.verma@example.com",
            "phone": "+91 98765 00111",
            "password": "Password1",
            "confirm_password": "Password2"
        }
    )
    assert res_mismatch.status_code == 422
    assert "Passwords do not match" in res_mismatch.json()["detail"]

    # 3. Successful customer registration under Hotel 1 (Grand Meridian)
    reg_payload = {
        "full_name": "Aditya Verma",
        "email": "aditya.verma@example.com",
        "phone": "+91 98765 00111",
        "password": "CustomerPassword@2026",
        "confirm_password": "CustomerPassword@2026",
        "preferences": "Quiet high-floor corner room",
        "hotel": "HOTEL-001"
    }
    res_reg = client.post("/api/public/customer-registration", json=reg_payload)
    assert res_reg.status_code == 201, res_reg.text
    reg_data = res_reg.json()
    assert reg_data["status"] == "success"
    assert reg_data["data"]["role"] == "CUSTOMER"
    assert reg_data["data"]["tenant_id"] == 1
    assert reg_data["data"]["hotel_name"] == "Grand Meridian Chennai"
    assert reg_data["data"]["email"] == "aditya.verma@example.com"
    assert reg_data["data"]["full_name"] == "Aditya Verma"
    assert "guest_id" in reg_data["data"]

    # 4. Attempting duplicate registration -> 409 Conflict
    res_dup = client.post("/api/public/customer-registration?hotel=HOTEL-001", json=reg_payload)
    assert res_dup.status_code == 409
    assert "already registered" in res_dup.json()["detail"]

    # 5. Customer Login with registered credentials -> returns CUSTOMER role & dashboard
    login_res = client.post(
        "/api/auth/login",
        json={"email": "aditya.verma@example.com", "password": "CustomerPassword@2026"}
    )
    assert login_res.status_code == 200, login_res.text
    l_data = login_res.json()
    assert l_data["user"]["role"] == "CUSTOMER"
    assert l_data["user"]["assigned_dashboard"] == "customer"
    assert l_data["user"]["tenant_id"] == 1
    assert "access_token" in l_data


def test_hotel_level_guest_registration_and_multi_tenant_isolation(client):
    """
    Comprehensive verification of the 4 strict hotel-level guest isolation scenarios:
    - Scenario A: Grand Meridian Registration (?hotel=HOTEL-001) -> associated strictly to Tenant 1
    - Scenario B: ABC Hotel Registration (?hotel=AH-005) -> associated strictly to Tenant 10
    - Scenario C: Cross-Tenant Security -> Customer 10 accessing Tenant 1 resources gets 403 Forbidden, and vice versa
    - Scenario D: Missing or Invalid Hotel Context -> 400 Bad Request / 404 Not Found
    """
    # -------------------------------------------------------------
    # Scenario D: Missing or Invalid Hotel Context
    # -------------------------------------------------------------
    # 1. No hotel query param or body field
    res_no_ctx = client.post(
        "/api/public/customer-registration",
        json={
            "full_name": "No Hotel User",
            "email": "nohotel@example.com",
            "phone": "+91 99999 11111",
            "password": "Password@123",
            "confirm_password": "Password@123"
        }
    )
    assert res_no_ctx.status_code == 400
    assert "Hotel property context is required" in res_no_ctx.json()["detail"]

    # 2. Invalid / Non-existent hotel code
    res_invalid_hotel = client.post(
        "/api/public/customer-registration?hotel=INVALID_HOTEL_999",
        json={
            "full_name": "Invalid Hotel User",
            "email": "invalid@example.com",
            "phone": "+91 99999 22222",
            "password": "Password@123",
            "confirm_password": "Password@123"
        }
    )
    assert res_invalid_hotel.status_code == 404
    assert "Hotel not found or currently inactive" in res_invalid_hotel.json()["detail"]

    # -------------------------------------------------------------
    # Scenario A: Grand Meridian Registration (hotel=HOTEL-001)
    # -------------------------------------------------------------
    res_meridian_reg = client.post(
        "/api/public/customer-registration?hotel=HOTEL-001",
        json={
            "full_name": "Meridian Guest",
            "email": "meridian.guest@example.com",
            "phone": "+91 98111 22334",
            "password": "GuestPassword@2026",
            "confirm_password": "GuestPassword@2026",
            "preferences": "Near elevator"
        }
    )
    assert res_meridian_reg.status_code == 201
    m_data = res_meridian_reg.json()["data"]
    assert m_data["tenant_id"] == 1
    assert m_data["role"] == "CUSTOMER"
    assert m_data["hotel_name"] == "Grand Meridian Chennai"
    assert m_data["email"] == "meridian.guest@example.com"

    # Login as Meridian Customer
    tok_meridian = get_token(client, "meridian.guest@example.com", "GuestPassword@2026")
    h_meridian = {"Authorization": f"Bearer {tok_meridian}"}

    # -------------------------------------------------------------
    # Scenario B: ABC Hotel Registration (hotel=AH-005)
    # -------------------------------------------------------------
    res_abc_reg = client.post(
        "/api/public/customer-registration?hotel=AH-005",
        json={
            "full_name": "ABC Guest",
            "email": "abc.guest@example.com",
            "phone": "+91 98222 33445",
            "password": "AbcPassword@2026",
            "confirm_password": "AbcPassword@2026"
        }
    )
    assert res_abc_reg.status_code == 201
    abc_data = res_abc_reg.json()["data"]
    assert abc_data["tenant_id"] == 10
    assert abc_data["role"] == "CUSTOMER"
    assert abc_data["hotel_name"] == "ABC Hotel"
    assert abc_data["email"] == "abc.guest@example.com"

    # Login as ABC Hotel Customer
    tok_abc = get_token(client, "abc.guest@example.com", "AbcPassword@2026")
    h_abc = {"Authorization": f"Bearer {tok_abc}"}

    # -------------------------------------------------------------
    # Scenario C: Cross-Tenant Security & Isolation
    # -------------------------------------------------------------
    # 1. ABC Hotel customer (Tenant 10) attempts to access Grand Meridian booking (Tenant 1)
    res_cross_billing = client.get("/api/customer/bookings/BK-MERIDIAN-01/billing", headers=h_abc)
    assert res_cross_billing.status_code == 403, f"Expected 403, got {res_cross_billing.status_code}"
    assert "Access forbidden: Reservation does not belong to your hotel property" in res_cross_billing.json()["detail"]

    # ABC Customer attempts to create Razorpay payment order for Grand Meridian booking
    res_cross_pay = client.post(
        "/api/customer/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01", "amount": 1000.0},
        headers=h_abc
    )
    assert res_cross_pay.status_code == 403
    assert "Access forbidden: Reservation does not belong to your hotel property" in res_cross_pay.json()["detail"]

    # Meridian Admin creates an order for BK-MERIDIAN-01
    tok_meridian_admin = get_token(client, "admin@meridian.com", "Password@123")
    h_m_admin = {"Authorization": f"Bearer {tok_meridian_admin}", "X-Hotel-ID": "1"}
    order_res = client.post(
        "/api/payments/razorpay/create-order",
        json={"booking_reference": "BK-MERIDIAN-01", "amount": 1000.0},
        headers=h_m_admin
    )
    assert order_res.status_code == 200
    m_order_id = order_res.json()["order_id"]
    m_payment_id = "pay_cross_tenant_test_1"
    m_sig = razorpay_service.create_mock_signature(m_order_id, m_payment_id)

    # ABC Customer attempts to call verify payment for Grand Meridian booking
    res_cross_verify = client.post(
        "/api/customer/payments/razorpay/verify",
        json={
            "booking_reference": "BK-MERIDIAN-01",
            "razorpay_order_id": m_order_id,
            "razorpay_payment_id": m_payment_id,
            "razorpay_signature": m_sig
        },
        headers=h_abc
    )
    assert res_cross_verify.status_code == 403
    assert "Access forbidden: Reservation does not belong to your hotel property" in res_cross_verify.json()["detail"]

    # 2. Meridian Customer (Tenant 1) attempts to access ABC Hotel booking (Tenant 10)
    res_meridian_cross_billing = client.get("/api/customer/bookings/BK-ABC-01/billing", headers=h_meridian)
    assert res_meridian_cross_billing.status_code == 403
    assert "Access forbidden: Reservation does not belong to your hotel property" in res_meridian_cross_billing.json()["detail"]

    res_meridian_cross_pay = client.post(
        "/api/customer/payments/razorpay/create-order",
        json={"booking_reference": "BK-ABC-01", "amount": 500.0},
        headers=h_meridian
    )
    assert res_meridian_cross_pay.status_code == 403
    assert "Access forbidden: Reservation does not belong to your hotel property" in res_meridian_cross_pay.json()["detail"]

    # 3. Cross-Tenant Registration Conflict:
    # Attempting to register the same email across different hotels does NOT compromise existing accounts
    res_dup_cross = client.post(
        "/api/public/customer-registration?hotel=HOTEL-001",
        json={
            "full_name": "ABC Imposter",
            "email": "abc.guest@example.com",  # Already registered under ABC Hotel (Tenant 10)
            "phone": "+91 99999 88888",
            "password": "HackedPassword@2026",
            "confirm_password": "HackedPassword@2026"
        }
    )
    assert res_dup_cross.status_code == 409
    assert "already exists in the system under another property" in res_dup_cross.json()["detail"]

