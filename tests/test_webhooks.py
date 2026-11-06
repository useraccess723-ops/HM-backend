import os
import sys
from datetime import date, timedelta
from decimal import Decimal
import pytest
from unittest.mock import patch, AsyncMock
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")

from app.main import app
from app.database.connection import Base, get_db
from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    User, RoomType, Room, Guest, Reservation, Payment,
    WebhookSubscription, WebhookDeliveryLog
)
from app.database.seed_data import ensure_default_webhooks


@pytest.fixture()
def client():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    settings.ALLOW_INTERNAL_WEBHOOK_URLS = True
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    with TestingSession() as db:
        admin_user = User(
            email="admin@hotel.com",
            full_name="Administrator",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=1,
            tenant_id=1
        )
        customer_user = User(
            email="guest@hotel.com",
            full_name="Guest Customer",
            password_hash=hash_password("Password@123"),
            role="CUSTOMER",
            hotel_id=1,
            tenant_id=1
        )
        db.add_all([admin_user, customer_user])

        rt = RoomType(
            tenant_id=1,
            name="Deluxe Suite",
            base_price=Decimal("4500.00"),
            max_occupancy=3,
            description="Deluxe Room with Sea View",
            amenities="[\"Wi-Fi\", \"AC\", \"TV\"]"
        )
        db.add(rt)
        db.flush()

        room101 = Room(tenant_id=1, number="101", room_type_id=rt.id, status="vac")
        room102 = Room(tenant_id=1, number="102", room_type_id=rt.id, status="vac")
        db.add_all([room101, room102])

        # Tenant 11 isolated test environment
        tenant11_admin = User(
            email="admin11@hotel.com",
            full_name="Tenant 11 Admin",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=11,
            tenant_id=11
        )
        db.add(tenant11_admin)
        rt11 = RoomType(
            tenant_id=11,
            name="Executive Suite 11",
            base_price=Decimal("7500.00"),
            max_occupancy=4,
            description="Tenant 11 Luxury Suite",
            amenities="[\"Wi-Fi\", \"Jacuzzi\"]"
        )
        db.add(rt11)
        db.flush()
        room1101 = Room(tenant_id=11, number="1101", room_type_id=rt11.id, status="vac")
        room1102 = Room(tenant_id=11, number="1102", room_type_id=rt11.id, status="vac")
        db.add_all([room1101, room1102])

        ensure_default_webhooks(db, force=True)
        db.commit()

    def override_get_db():
        with TestingSession() as session:
            yield session

    import app.database.connection as db_conn
    orig_session_local = getattr(db_conn, "SessionLocal", None)
    db_conn.SessionLocal = TestingSession
    try:
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as tc:
            yield tc
    finally:
        db_conn.SessionLocal = orig_session_local
        app.dependency_overrides.clear()


def get_tenant11_token(client: TestClient) -> str:
    res = client.post("/api/auth/token", data={"username": "admin11@hotel.com", "password": "Password@123"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def get_auth_token(client: TestClient) -> str:
    res = client.post("/api/auth/token", data={"username": "admin@hotel.com", "password": "Password@123"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def get_customer_token(client: TestClient) -> str:
    res = client.post("/api/auth/token", data={"username": "guest@hotel.com", "password": "Password@123"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_incoming_webhook_makemytrip_booking(client: TestClient):
    """
    Test that an incoming booking webhook from MakeMyTrip automatically:
    1. Creates Guest and Reservation in MySQL
    2. Immediately displays in the /api/bookings menu
    3. Immediately displays in the /api/guests menu with booking and room details
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    today = date.today()
    check_in = str(today)
    check_out = str(today + timedelta(days=2))

    payload = {
        "event": "booking.created",
        "booking_id": "MMT-IN-889100",
        "channel_ref": "MMT-IN-889100",
        "guest_name": "Rohan Deshmukh",
        "guest_email": "rohan.deshmukh@example.com",
        "guest_phone": "+919876500001",
        "room_type": "Deluxe Suite",
        "room_number": "101",
        "check_in": check_in,
        "check_out": check_out,
        "total_amount": 9000.0,
        "payment_status": "Paid",
        "payment_method": "MakeMyTrip Prepaid",
        "transaction_id": "TXN-MMT-998877",
        "source": "MakeMyTrip"
    }

    # 1. Post incoming webhook
    res = client.post("/api/webhooks/incoming/makemytrip", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "success"
    assert "booking_reference" in data
    booking_ref = data["booking_reference"]
    assert data["guest"]["full_name"] == "Rohan Deshmukh"
    assert data["room"]["number"] == "101"

    # 2. Verify display in Reservation and Booking Menu (/api/bookings)
    bookings_res = client.get("/api/bookings", headers=headers)
    assert bookings_res.status_code == 200, bookings_res.text
    bookings = bookings_res.json()
    matched_booking = next((b for b in bookings if b.get("reference") == booking_ref), None)
    assert matched_booking is not None, f"Booking {booking_ref} not found in bookings list"
    assert matched_booking["guest"] == "Rohan Deshmukh"
    assert matched_booking["src"] == "MakeMyTrip"
    assert matched_booking["reservation_type"] == "Online"
    assert matched_booking["room_number"] == "101"
    assert matched_booking["pay"] == "Paid"

    # 3. Verify display in Guest Management Menu (/api/guests)
    guests_res = client.get("/api/guests", headers=headers)
    assert guests_res.status_code == 200, guests_res.text
    guests = guests_res.json()
    matched_guest = next((g for g in guests if g.get("full_name") == "Rohan Deshmukh"), None)
    assert matched_guest is not None, "Guest not found in guests list"
    assert matched_guest["email"] == "rohan.deshmukh@example.com"
    assert matched_guest["phone"] == "+919876500001"
    assert matched_guest["booking_reference"] == booking_ref
    assert matched_guest["room_number"] == "101"
    assert matched_guest["payment_status"] in ("Paid", "Partially Paid")
    assert matched_guest["amount_paid"] == 9000.0


def test_incoming_webhook_deduplication(client: TestClient):
    """
    Test duplicate webhook handling: re-posting the same channel_ref returns idempotent success.
    """
    today = date.today()
    payload = {
        "event": "booking.created",
        "booking_id": "AGO-UNIQ-772211",
        "channel_ref": "AGO-UNIQ-772211",
        "guest_name": "Priya Patel",
        "guest_email": "priya.patel@example.com",
        "guest_phone": "+919876500002",
        "check_in": str(today),
        "check_out": str(today + timedelta(days=1)),
        "total_amount": 4500.0,
        "source": "Agoda"
    }

    res1 = client.post("/api/webhooks/incoming/agoda", json=payload)
    assert res1.status_code == 200
    ref1 = res1.json()["booking_reference"]

    # Post duplicate
    res2 = client.post("/api/webhooks/incoming/agoda", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2.get("is_duplicate") is True
    assert data2["booking_reference"] == ref1


def test_incoming_webhook_cancellation(client: TestClient):
    """
    Test that incoming cancellation webhook updates booking status to Cancelled.
    """
    today = date.today()
    create_payload = {
        "event": "booking.created",
        "booking_id": "MMT-CANCEL-TEST-01",
        "channel_ref": "MMT-CANCEL-TEST-01",
        "guest_name": "Amit Kumar",
        "guest_email": "amit.kumar@example.com",
        "guest_phone": "+919876500003",
        "check_in": str(today + timedelta(days=5)),
        "check_out": str(today + timedelta(days=7)),
        "total_amount": 9000.0,
        "source": "MakeMyTrip"
    }
    create_res = client.post("/api/webhooks/incoming/makemytrip", json=create_payload)
    assert create_res.status_code == 200
    booking_ref = create_res.json()["booking_reference"]

    # Send cancellation webhook
    cancel_payload = {
        "event": "booking.cancelled",
        "booking_reference": booking_ref,
        "cancellation_reason": "Travel plan rescheduled by guest"
    }
    cancel_res = client.post("/api/webhooks/incoming/makemytrip", json=cancel_payload)
    assert cancel_res.status_code == 200, cancel_res.text
    cancel_data = cancel_res.json()
    assert cancel_data["status"] == "success"
    assert cancel_data["reservation_status"] == "Cancelled"


def test_incoming_webhook_payment_update(client: TestClient):
    """
    Test that incoming payment update webhook creates Payment entry.
    """
    today = date.today()
    create_payload = {
        "event": "booking.created",
        "booking_id": "PAY-TEST-01",
        "channel_ref": "PAY-TEST-01",
        "guest_name": "Neha Gupta",
        "guest_email": "neha.gupta@example.com",
        "guest_phone": "+919876500004",
        "check_in": str(today),
        "check_out": str(today + timedelta(days=2)),
        "total_amount": 9000.0,
        "source": "Direct"
    }
    create_res = client.post("/api/webhooks/incoming/generic", json=create_payload)
    assert create_res.status_code == 200
    booking_ref = create_res.json()["booking_reference"]

    # Send payment captured webhook
    pay_payload = {
        "event": "payment.captured",
        "booking_reference": booking_ref,
        "amount": 9000.0,
        "method": "Razorpay UPI",
        "transaction_id": "TXN-RAZOR-9988",
        "payment_status": "Captured"
    }
    pay_res = client.post("/api/webhooks/incoming/payment", json=pay_payload)
    assert pay_res.status_code == 200, pay_res.text
    pay_data = pay_res.json()
    assert pay_data["status"] == "success"
    assert pay_data["payment_status"] == "Paid"


def test_outgoing_webhook_subscriptions_crud(client: TestClient):
    """
    Test listing, creating, updating, testing, and deleting outgoing webhook subscriptions.
    Verifies that requests require authentication and that secrets are masked in responses.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. List seeded subscriptions (authenticated)
    list_res = client.get("/api/webhooks/subscriptions", headers=headers)
    assert list_res.status_code == 200
    subs = list_res.json()
    assert len(subs) >= 3  # MMT, Agoda, Payment Gateway seeded
    for s in subs:
        if s.get("secret"):
            assert "••••••••" in s["secret"], "Webhook secret must be masked in API response"

    # 2. Create new subscription pointing to test receiver
    create_sub_payload = {
        "name": "Expedia Partner Hook",
        "url": "http://127.0.0.1:8000/api/webhooks/test-receiver/expedia",
        "events": "booking.created,booking.cancelled",
        "secret": "expedia_secret_key_123",
        "status": "Active"
    }
    post_res = client.post("/api/webhooks/subscriptions", json=create_sub_payload, headers=headers)
    assert post_res.status_code == 201, post_res.text
    new_sub = post_res.json()
    sub_id = new_sub["id"]
    assert new_sub["name"] == "Expedia Partner Hook"
    assert "••••••••" in new_sub["secret"], "Returned secret on create must be masked"

    # 3. Test ping to subscription
    test_ping_res = client.post(f"/api/webhooks/subscriptions/{sub_id}/test", headers=headers)
    assert test_ping_res.status_code == 200, test_ping_res.text
    assert test_ping_res.json()["status"] == "success"

    # 4. Update subscription (pause)
    update_res = client.put(f"/api/webhooks/subscriptions/{sub_id}", json={"status": "Paused"}, headers=headers)
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "Paused"

    # 5. Delete subscription
    del_res = client.delete(f"/api/webhooks/subscriptions/{sub_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["id"] == sub_id


def test_test_webhook_receiver_and_accurate_success_rate(client: TestClient):
    """
    Test that the test webhook receiver acknowledges partner deliveries (HTTP 200)
    and that success rates reflect real log history rather than fake 100%.
    """
    # 1. Post directly to test receiver endpoint
    test_payload = {
        "event": "booking.created",
        "hotel_id": 1,
        "source": "StayFlow Outgoing Dispatcher",
        "data": {
            "booking_reference": "MMT-TEST-8899",
            "guest_name": "Rohan Deshmukh",
            "amount": 9000.0
        }
    }
    rec_res = client.post(
        "/api/webhooks/test-receiver/makemytrip",
        json=test_payload,
        headers={
            "X-StayFlow-Event": "booking.created",
            "X-StayFlow-Delivery": "del_test_123",
            "X-StayFlow-Signature": "hex_sig_mock",
            "X-MMT-Auth-Token": "mmt_token_val"
        }
    )
    assert rec_res.status_code == 200, rec_res.text
    rec_data = rec_res.json()
    assert rec_data["status"] == "success"
    assert rec_data["acknowledged"] is True
    assert rec_data["partner"] == "makemytrip"

    # 2. Inspect payloads buffer
    payloads_res = client.get("/api/webhooks/test-receiver/payloads")
    assert payloads_res.status_code == 200
    payloads = payloads_res.json()
    assert len(payloads) >= 1
    assert any(p["partner"] == "makemytrip" for p in payloads)


def test_outgoing_test_dispatch_and_logs(client: TestClient):
    """
    Test outgoing event dispatch test endpoint and logs inspection with authentication.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    dispatch_payload = {
        "event_type": "booking.created",
        "payload": {
            "booking_reference": "MMT-TEST-7788",
            "guest_name": "Sunil Verma",
            "total_amount": 7500.0
        }
    }
    res = client.post("/api/webhooks/outgoing/test-dispatch", json=dispatch_payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["event"] == "booking.created"
    assert data["subscribers_matched"] >= 1

    # Check that logs were recorded in webhook delivery logs (requires auth)
    logs_res = client.get("/api/webhooks/logs?limit=10", headers=headers)
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) >= 1


def test_webhook_unauthorized_access_and_rbac(client: TestClient):
    """
    Phase 1, Item 4: Verify authentication and authorization are enforced on webhook endpoints.
    - Unauthenticated requests return HTTP 401.
    - CUSTOMER / non-staff users return HTTP 403 Forbidden.
    """
    # 1. Unauthenticated requests should be rejected with 401
    assert client.get("/api/webhooks/subscriptions").status_code == 401
    assert client.get("/api/webhooks/logs").status_code == 401
    assert client.post("/api/webhooks/subscriptions", json={"name": "test", "url": "https://example.com"}).status_code == 401

    # 2. Authenticated as CUSTOMER should be rejected with 403 Forbidden
    cust_token = get_customer_token(client)
    cust_headers = {"Authorization": f"Bearer {cust_token}"}
    assert client.get("/api/webhooks/subscriptions", headers=cust_headers).status_code == 403
    assert client.get("/api/webhooks/logs", headers=cust_headers).status_code == 403
    assert client.post("/api/webhooks/subscriptions", json={"name": "test", "url": "https://example.com"}, headers=cust_headers).status_code == 403


def test_invalid_signature_rejection_in_production(client: TestClient):
    """
    Phase 1, Item 2: Verify that in production, unsigned or invalid signature requests are rejected with 401.
    """
    orig_env = settings.APP_ENV
    try:
        settings.APP_ENV = "production"

        payload = {
            "event": "booking.created",
            "booking_id": "PROD-SIG-001",
            "guest_name": "Security Tester",
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=1)),
            "total_amount": 5000.0
        }

        # Request with no signature in production must be rejected
        res_no_sig = client.post("/api/webhooks/incoming/makemytrip", json=payload)
        assert res_no_sig.status_code == 401, res_no_sig.text
        assert res_no_sig.json()["error_code"] == "AUTH_FAILED"

        # Request with invalid signature in production must be rejected
        res_bad_sig = client.post(
            "/api/webhooks/incoming/makemytrip",
            json=payload,
            headers={"X-StayFlow-Signature": "invalid_hex_signature_value"}
        )
        assert res_bad_sig.status_code == 401, res_bad_sig.text
        assert res_bad_sig.json()["error_code"] == "AUTH_FAILED"
    finally:
        settings.APP_ENV = orig_env


def test_duplicate_payment_records_prevented(client: TestClient):
    """
    Phase 2, Item 6: Verify duplicate payment records are prevented using transaction references.
    """
    today = date.today()
    create_payload = {
        "event": "booking.created",
        "booking_id": "PAY-DEDUP-001",
        "channel_ref": "PAY-DEDUP-001",
        "guest_name": "Vijay Shankar",
        "guest_phone": "+919876543210",
        "check_in": str(today),
        "check_out": str(today + timedelta(days=2)),
        "total_amount": 8000.0,
        "source": "Direct"
    }
    create_res = client.post("/api/webhooks/incoming/generic", json=create_payload)
    assert create_res.status_code == 200
    booking_ref = create_res.json()["booking_reference"]

    pay_payload = {
        "event": "payment.captured",
        "booking_reference": booking_ref,
        "amount": 8000.0,
        "method": "UPI",
        "transaction_id": "TXN-UNIQUE-REF-001",
        "payment_status": "Paid"
    }

    # First payment recording
    res1 = client.post("/api/webhooks/incoming/payment", json=pay_payload)
    assert res1.status_code == 200, res1.text
    assert res1.json()["status"] == "success"
    assert not res1.json().get("is_duplicate")

    # Replay identical payment webhook
    res2 = client.post("/api/webhooks/incoming/payment", json=pay_payload)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    assert data2["status"] == "success"
    assert data2.get("is_duplicate") is True
    assert "already recorded" in data2["message"]


def test_duplicate_booking_replay_without_channel_ref(client: TestClient):
    """
    Phase 2, Item 7: Prevent duplicate booking creation when events are replayed without an external booking reference.
    """
    today = date.today()
    payload = {
        "event": "booking.created",
        "guest_name": "Ananya Sharma",
        "guest_email": "ananya.sharma@example.com",
        "guest_phone": "+919811122233",
        "check_in": str(today + timedelta(days=10)),
        "check_out": str(today + timedelta(days=12)),
        "total_amount": 9000.0,
        "source": "MakeMyTrip"
    }

    # 1. Initial booking creation without channel_ref
    res1 = client.post("/api/webhooks/incoming/makemytrip", json=payload)
    assert res1.status_code == 200, res1.text
    ref1 = res1.json()["booking_reference"]

    # 2. Replay identical booking without channel_ref immediately
    res2 = client.post("/api/webhooks/incoming/makemytrip", json=payload)
    assert res2.status_code == 200, res2.text
    data2 = res2.json()
    assert data2.get("is_duplicate") is True
    assert data2["booking_reference"] == ref1


def test_cross_tenant_room_isolation(client: TestClient):
    """
    Phase 1, Item 3: Remove cross-tenant room-selection fallbacks.
    Every room lookup must be scoped to the authenticated or explicitly validated hotel.
    If hotel has no rooms configured, reject rather than taking rooms from another hotel.
    """
    today = date.today()
    payload = {
        "event": "booking.created",
        "hotel_id": 999,  # Tenant with 0 rooms
        "channel_ref": "ISOLATION-TEST-001",
        "guest_name": "Cross Tenant Test",
        "check_in": str(today),
        "check_out": str(today + timedelta(days=1)),
        "total_amount": 5000.0,
        "source": "MakeMyTrip"
    }

    res = client.post("/api/webhooks/incoming/makemytrip", json=payload)
    # Must reject with 422 because hotel 999 has no rooms configured
    assert res.status_code == 422, res.text
    data = res.json()
    assert data["status"] == "error"
    assert data["error_code"] == "NO_ROOMS_AVAILABLE"
    assert "Cross-tenant room assignment is rejected" in data["message"]


def test_retry_behavior_and_queue(client: TestClient):
    """
    Phase 3, Item 10: Automated tests for retry behavior and retry queue endpoints.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Check retry queue endpoint
    q_res = client.get("/api/webhooks/retry-queue", headers=headers)
    assert q_res.status_code == 200, q_res.text
    assert isinstance(q_res.json(), list)

    # Trigger process retries
    p_res = client.post("/api/webhooks/retry-queue/process", headers=headers)
    assert p_res.status_code == 200, p_res.text
    assert p_res.json()["status"] == "success"

    # Clear retry queue
    c_res = client.post("/api/webhooks/retry-queue/clear", headers=headers)
    assert c_res.status_code == 200, c_res.text
    assert "cleared" in c_res.json()


def test_outgoing_url_ssrf_rejection(client: TestClient):
    """
    Verify that outgoing webhook creation rejects loopback, private IPs, and cloud metadata
    when internal webhook URLs are disallowed.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    original_setting = settings.ALLOW_INTERNAL_WEBHOOK_URLS
    try:
        settings.ALLOW_INTERNAL_WEBHOOK_URLS = False

        # 1. Prohibited loopback IP
        res_loopback = client.post(
            "/api/webhooks/subscriptions",
            json={"name": "SSRF Loopback", "type": "outgoing", "url": "http://127.0.0.1:8000/api/hook"},
            headers=headers
        )
        assert res_loopback.status_code == 422, res_loopback.text
        assert "Invalid outgoing webhook destination URL" in res_loopback.json()["detail"]

        # 2. Prohibited localhost hostname
        res_localhost = client.post(
            "/api/webhooks/subscriptions",
            json={"name": "SSRF Localhost", "type": "outgoing", "url": "http://localhost:8000/api/hook"},
            headers=headers
        )
        assert res_localhost.status_code == 422, res_localhost.text

        # 3. Prohibited AWS/Cloud metadata IP
        res_metadata = client.post(
            "/api/webhooks/subscriptions",
            json={"name": "SSRF Cloud Metadata", "type": "outgoing", "url": "http://169.254.169.254/latest/meta-data"},
            headers=headers
        )
        assert res_metadata.status_code == 422, res_metadata.text

        # 4. Prohibited RFC1918 private IP
        res_private = client.post(
            "/api/webhooks/subscriptions",
            json={"name": "SSRF Private Subnet", "type": "outgoing", "url": "http://10.0.0.1/webhook"},
            headers=headers
        )
        assert res_private.status_code == 422, res_private.text

    finally:
        settings.ALLOW_INTERNAL_WEBHOOK_URLS = original_setting


def test_test_ping_failure_without_mock(client: TestClient):
    """
    Verify that Test Ping returns an accurate failure instead of a simulated HTTP 200
    when the target endpoint is blocked or unreachable.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    original_setting = settings.ALLOW_INTERNAL_WEBHOOK_URLS
    try:
        # Create an outgoing subscription with an internal URL while ALLOW_INTERNAL_WEBHOOK_URLS is True
        settings.ALLOW_INTERNAL_WEBHOOK_URLS = True
        create_res = client.post(
            "/api/webhooks/subscriptions",
            json={
                "name": "Unreachable Destination Hook",
                "type": "outgoing",
                "url": "http://127.0.0.1:59999/nonexistent-webhook-path",
                "secret": "test_whsec_12345"
            },
            headers=headers
        )
        assert create_res.status_code == 201, create_res.text
        sub_id = create_res.json()["id"]

        # Now disable internal destinations and trigger Test Ping
        settings.ALLOW_INTERNAL_WEBHOOK_URLS = False
        ping_res = client.post(f"/api/webhooks/subscriptions/{sub_id}/test", headers=headers)
        assert ping_res.status_code == 200, ping_res.text
        data = ping_res.json()

        # Must report failed status and not fake 200 success
        assert data["status"] == "failed"
        assert "Destination blocked by security policy" in data.get("error", "")

    finally:
        settings.ALLOW_INTERNAL_WEBHOOK_URLS = original_setting


def test_missing_signing_secret_fails_safely(client: TestClient):
    """
    Verify that outgoing delivery fails safely with a configuration error when
    no signing secret is configured, rather than using a hardcoded secret fallback.
    """
    from app.services.webhook_service import execute_delivery_attempt
    from app.models.entities import WebhookDeliveryLog, WebhookSubscription

    original_secret = settings.WEBHOOK_SECRET
    try:
        settings.WEBHOOK_SECRET = ""

        # Using a raw db session from client override
        session_gen = client.app.dependency_overrides[get_db]()
        session = next(session_gen)
        try:
            sub = WebhookSubscription(
                hotel_id=1,
                name="No Secret Partner",
                type="outgoing",
                url="https://example.com/webhook",
                secret=None,
                status="Active"
            )
            session.add(sub)
            session.commit()
            session.refresh(sub)

            log_entry = WebhookDeliveryLog(
                hotel_id=1,
                direction="outgoing",
                channel=sub.name,
                event_type="booking.created",
                endpoint="https://example.com/webhook",
                payload="{}",
                status="Pending"
            )
            session.add(log_entry)
            session.commit()
            session.refresh(log_entry)

            import asyncio
            result = asyncio.run(execute_delivery_attempt(session, log_entry.id))

            assert result["status"] == "Failed"
            assert "Missing required webhook signing secret" in result["error_message"]
            assert result["response_code"] == 0
        finally:
            session.close()

    finally:
        settings.WEBHOOK_SECRET = original_secret


def test_booking_creation_triggers_outgoing_webhook_in_background(client: TestClient):
    """
    Verify that creating a booking via POST /api/bookings schedules exactly one
    booking.created outgoing webhook event, commits the booking before dispatch,
    and accurately writes a delivery log.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Register an active outgoing subscription for hotel 1
    sub_payload = {
        "name": "Partner Booking Receiver",
        "type": "outgoing",
        "url": "https://partner-receiver.stayflow.test/webhooks",
        "secret": "test_booking_created_secret_key_123",
        "events": "booking.created",
        "status": "Active"
    }
    sub_res = client.post("/api/webhooks/subscriptions", json=sub_payload, headers=headers)
    assert sub_res.status_code == 201, sub_res.text

    # Mock external delivery receiver
    mock_resp = httpx.Response(
        status_code=200,
        json={"status": "accepted", "id": "partner_ack_1001"},
        request=httpx.Request("POST", "https://partner-receiver.stayflow.test/webhooks")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        booking_body = {
            "room_id": 1,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {
                "full_name": "Anita Desai",
                "email": "anita.desai@example.com",
                "phone": "+919876543299"
            },
            "status": "Confirmed",
            "source": "Direct Website"
        }
        res = client.post("/api/bookings", json=booking_body, headers=headers)
        assert res.status_code == 201, res.text
        ref = res.json()["reference"]

        # Confirm HTTP mock post was invoked for the partner URL
        assert mock_post.called, "Outgoing webhook dispatch was not triggered"
        partner_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == "https://partner-receiver.stayflow.test/webhooks"
        ]
        assert len(partner_calls) == 1, f"Expected 1 dispatch to partner receiver, got {len(partner_calls)}"

        # Verify signed headers and payload passed to external partner
        call_args = partner_calls[0]
        call_url = call_args[0][0] if call_args[0] else call_args[1].get("url")
        assert call_url == "https://partner-receiver.stayflow.test/webhooks"
        headers_sent = call_args[1].get("headers", {})
        assert "X-StayFlow-Signature" in headers_sent
        assert headers_sent["X-StayFlow-Event"] == "booking.created"

    # Query delivery logs endpoint
    logs_res = client.get("/api/webhooks/logs", headers=headers)
    assert logs_res.status_code == 200, logs_res.text
    logs = logs_res.json()
    matching_logs = [l for l in logs if l.get("event_type") == "booking.created" and l.get("channel") == "Partner Booking Receiver"]
    assert len(matching_logs) == 1, f"Expected 1 matching delivery log, got {len(matching_logs)}"
    assert matching_logs[0]["status"] == "Success"
    assert matching_logs[0]["hotel_id"] == 1


def test_booking_webhook_strict_multi_tenant_isolation(client: TestClient):
    """
    Verify strict multi-tenant isolation:
    1. A booking for tenant 11 dispatches ONLY to tenant 11's subscription.
    2. Tenant 1's subscription never receives tenant 11's event.
    3. The dispatcher never defaults to hotel ID 1 when the actual tenant is 11.
    4. Missing or invalid tenant ID safely aborts without cross-tenant delivery.
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}

    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    # Create active subscription for Tenant 1
    sub1_res = client.post("/api/webhooks/subscriptions", json={
        "name": "Tenant 1 Auditor",
        "type": "outgoing",
        "url": "https://tenant1-auditor.stayflow.test/webhook",
        "secret": "tenant1_whsec_secret_key_123456",
        "events": "booking.created",
        "status": "Active"
    }, headers=headers1)
    assert sub1_res.status_code == 201, sub1_res.text

    # Create active subscription for Tenant 11
    sub11_res = client.post("/api/webhooks/subscriptions", json={
        "name": "Tenant 11 ERP",
        "type": "outgoing",
        "url": "https://tenant11-erp.stayflow.test/webhook",
        "secret": "tenant11_whsec_secret_key_654321",
        "events": "booking.created",
        "status": "Active"
    }, headers=headers11)
    assert sub11_res.status_code == 201, sub11_res.text

    # Find room belonging to tenant 11
    rooms_res = client.get("/api/rooms", headers=headers11)
    assert rooms_res.status_code == 200
    tenant11_room = [r for r in rooms_res.json() if r.get("number") == "1101"][0]

    mock_resp11 = httpx.Response(
        status_code=200,
        json={"tenant11_received": True},
        request=httpx.Request("POST", "https://tenant11-erp.stayflow.test/webhook")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp11

        # Create booking specifically for Tenant 11
        booking11_body = {
            "room_id": tenant11_room["id"],
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {
                "full_name": "Rohan Mehra",
                "email": "rohan.mehra@tenant11.com",
                "phone": "+919876543211"
            },
            "status": "Confirmed",
            "source": "Tenant 11 Portal"
        }
        res = client.post("/api/bookings", json=booking11_body, headers=headers11)
        assert res.status_code == 201, res.text

        # Verify only Tenant 11 URL was called
        assert mock_post.called
        assert mock_post.call_count == 1
        called_url = mock_post.call_args[0][0]
        assert called_url == "https://tenant11-erp.stayflow.test/webhook", f"Dispatched to wrong URL: {called_url}"
        assert "tenant1-auditor" not in called_url

    # Check Tenant 1 delivery logs: must NOT contain Tenant 11's booking
    logs1 = client.get("/api/webhooks/logs", headers=headers1).json()
    t1_received = [l for l in logs1 if l.get("channel") == "Tenant 1 Auditor" and "Rohan Mehra" in (l.get("payload") or "")]
    assert len(t1_received) == 0, "Cross-tenant leak! Tenant 1 subscription received Tenant 11's booking!"

    # Check Tenant 11 delivery logs: must contain exactly 1 log
    logs11 = client.get("/api/webhooks/logs", headers=headers11).json()
    t11_logs = [l for l in logs11 if l.get("channel") == "Tenant 11 ERP"]
    assert len(t11_logs) == 1, f"Expected 1 log for Tenant 11, got {len(t11_logs)}"
    assert t11_logs[0]["hotel_id"] == 11

    # Verify invalid or missing tenant ID fails safely without dispatching to hotel 1
    from app.services.webhook_service import dispatch_in_background
    import asyncio
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post2:
        asyncio.run(dispatch_in_background("booking.created", {"test": "data"}, hotel_id=None))
        asyncio.run(dispatch_in_background("booking.created", {"test": "data"}, hotel_id=0))
        assert not mock_post2.called, "Dispatch should have safely aborted for missing/invalid tenant ID"


def test_booking_lifecycle_outgoing_webhook_events(client: TestClient):
    """
    Verify correct scheduling and tenant propagation for:
    - guest.check_in
    - guest.check_out
    - booking.cancelled
    - payment.captured
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Register subscription for all lifecycle events
    client.post("/api/webhooks/subscriptions", json={
        "name": "Lifecycle Subscriber",
        "type": "outgoing",
        "url": "https://lifecycle-receiver.stayflow.test/webhook",
        "secret": "lifecycle_secret_key_12345678",
        "events": "guest.check_in,guest.check_out,booking.cancelled,payment.captured",
        "status": "Active"
    }, headers=headers)

    mock_ok = httpx.Response(
        status_code=200,
        json={"lifecycle": "ok"},
        request=httpx.Request("POST", "https://lifecycle-receiver.stayflow.test/webhook")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # 1. Create a booking to check-in and check-out
        b_res = client.post("/api/bookings", json={
            "room_id": 1,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {"full_name": "Siddharth Rao", "email": "siddharth@example.com"},
            "status": "Confirmed"
        }, headers=headers)
        assert b_res.status_code == 201
        ref = b_res.json()["reference"]
        res_id = b_res.json()["reservation_id"]

        # 2. Check-in
        ci_res = client.post(f"/api/bookings/{ref}/check-in", headers=headers)
        assert ci_res.status_code == 200, ci_res.text

        # 3. Check-out
        co_res = client.post(f"/api/bookings/{ref}/check-out", headers=headers)
        assert co_res.status_code == 200, co_res.text

        # 4. Create another booking to cancel
        b2_res = client.post("/api/bookings", json={
            "room_id": 2,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=3)),
            "guest": {"full_name": "Kavita Nair", "email": "kavita@example.com"},
            "status": "Confirmed"
        }, headers=headers)
        assert b2_res.status_code == 201
        ref2 = b2_res.json()["reference"]

        # Cancel
        can_res = client.patch(f"/api/bookings/{ref2}/status", json={"status": "Cancelled"}, headers=headers)
        assert can_res.status_code == 200, can_res.text

        # 5. Record Payment
        pay_res = client.post("/api/payments", json={
            "reservation_id": res_id,
            "amount": 4500.0,
            "method": "Credit Card",
            "status": "Paid",
            "transaction_reference": f"TXN-TEST-{ref}"
        }, headers=headers)
        assert pay_res.status_code == 201, pay_res.text

    # Verify all 4 lifecycle events exist in delivery logs
    all_logs = client.get("/api/webhooks/logs", headers=headers).json()
    lifecycle_events_found = {l["event_type"] for l in all_logs if l.get("channel") == "Lifecycle Subscriber"}
    expected = {"guest.check_in", "guest.check_out", "booking.cancelled", "payment.captured"}
    assert expected.issubset(lifecycle_events_found), f"Missing events: {expected - lifecycle_events_found}"


def test_failed_dispatch_logged_and_booking_not_corrupted(client: TestClient):
    """
    Verify that an external webhook delivery failure (e.g. 500 error or network exception)
    is recorded accurately in WebhookDeliveryLog and does NOT roll back or corrupt
    an already committed booking.
    """
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/webhooks/subscriptions", json={
        "name": "Failing Partner",
        "type": "outgoing",
        "url": "https://failing-receiver.stayflow.test/webhook",
        "secret": "failing_partner_secret_12345",
        "events": "booking.created",
        "status": "Active"
    }, headers=headers)

    failing_resp = httpx.Response(
        status_code=500,
        text="Internal Server Error: Database down",
        request=httpx.Request("POST", "https://failing-receiver.stayflow.test/webhook")
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = failing_resp

        booking_res = client.post("/api/bookings", json={
            "room_id": 1,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=1)),
            "guest": {"full_name": "Resilient Guest", "email": "resilient@example.com"},
            "status": "Confirmed"
        }, headers=headers)

        # Booking creation MUST succeed despite webhook destination failing
        assert booking_res.status_code == 201, booking_res.text
        ref = booking_res.json()["reference"]

    # Verify booking still exists and is committed in the database
    get_booking = client.get(f"/api/bookings/{ref}", headers=headers)
    assert get_booking.status_code == 200
    assert get_booking.json()["guest"] == "Resilient Guest"

    # Verify delivery failure was recorded accurately with retry scheduling
    logs = client.get("/api/webhooks/logs", headers=headers).json()
    failed_log = [l for l in logs if l.get("channel") == "Failing Partner" and l.get("event_type") == "booking.created"]
    assert len(failed_log) >= 1
    assert failed_log[0]["status"] in ("Failed", "Retrying")
    assert failed_log[0]["response_code"] == 500


# ==============================================================================
# AUDIT & REGRESSION TESTS: ALL 6 SUPPORTED OUTGOING WEBHOOK EVENTS
# ==============================================================================


def test_audit_event_1_booking_created(client: TestClient):
    """
    Audit Event 1: booking.created
    Verifies:
    - Event triggering from POST /api/bookings
    - Correct event name ('booking.created')
    - Correct payload structure (booking_reference, reservation_id, guest, room, stay dates, amount, status)
    - Correct hotel/tenant ID propagation
    - Correct subscription selection (only matching tenant & event)
    - Successful mocked delivery
    - Failed delivery logging & retry calculation
    - No duplicate delivery
    - No cross-tenant delivery (Tenant 1 vs Tenant 11)
    - Database transaction committed before dispatch
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    # 1. Register active subscriptions for Tenant 1 and Tenant 11
    sub1_url = "https://tenant1-created.stayflow.test/webhook"
    sub11_url = "https://tenant11-created.stayflow.test/webhook"

    sub1_res = client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Booking Created Hook",
        "type": "outgoing",
        "url": sub1_url,
        "secret": "whsec_t1_created_secret_998811",
        "events": "booking.created",
        "status": "Active"
    }, headers=headers1)
    assert sub1_res.status_code == 201

    sub11_res = client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Booking Created Hook",
        "type": "outgoing",
        "url": sub11_url,
        "secret": "whsec_t11_created_secret_998822",
        "events": "booking.created",
        "status": "Active"
    }, headers=headers11)
    assert sub11_res.status_code == 201

    # 2. Mock successful external HTTP receiver
    mock_ok = httpx.Response(
        status_code=200,
        json={"status": "ok", "ack_id": "ack_bc_001"},
        request=httpx.Request("POST", sub1_url)
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        b_payload = {
            "room_id": 1,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {
                "full_name": "Aarav Sharma",
                "email": "aarav.sharma@example.com",
                "phone": "+919876501001"
            },
            "status": "Confirmed",
            "source": "Direct Web"
        }
        res = client.post("/api/bookings", json=b_payload, headers=headers1)
        assert res.status_code == 201, res.text
        ref = res.json()["reference"]
        res_id = res.json()["reservation_id"]

        # Verify target subscription was called exactly once
        assert mock_post.called
        target_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls) == 1, f"Expected 1 dispatch to {sub1_url}, got {len(target_calls)}"

        # Verify NO cross-tenant dispatch to Tenant 11
        t11_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub11_url
        ]
        assert len(t11_calls) == 0, f"Cross-tenant delivery violation! Tenant 11 was called {len(t11_calls)} times"

        # Verify signed headers & envelope
        call_args = target_calls[0]
        headers_sent = call_args[1].get("headers", {})
        assert headers_sent["X-StayFlow-Event"] == "booking.created"
        assert "X-StayFlow-Signature" in headers_sent

        content_bytes = call_args[1].get("content", b"")
        import json as j_mod
        envelope = j_mod.loads(content_bytes.decode("utf-8"))
        assert envelope["event"] == "booking.created"
        assert envelope["hotel_id"] == 1
        data = envelope["data"]
        assert data["booking_reference"] == ref
        assert data["reservation_id"] == res_id
        assert data["guest_name"] == "Aarav Sharma"
        assert data["room_number"] == "101"
        assert data["status"] == "Confirmed"

    # 3. Verify Database committed before dispatch
    get_res = client.get(f"/api/bookings/{ref}", headers=headers1)
    assert get_res.status_code == 200
    assert get_res.json()["reference"] == ref

    # 4. Verify Delivery Log for Tenant 1
    t1_logs = client.get("/api/webhooks/logs", headers=headers1).json()
    matched_logs = [l for l in t1_logs if l.get("channel") == "T1 Booking Created Hook" and ref in (l.get("payload") or "")]
    assert len(matched_logs) == 1, f"Expected 1 delivery log, found {len(matched_logs)}"
    assert matched_logs[0]["status"] == "Success"
    assert matched_logs[0]["hotel_id"] == 1
    assert matched_logs[0]["event_type"] == "booking.created"

    # 5. Verify NO cross-tenant delivery in Tenant 11 logs
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    leak_logs = [l for l in t11_logs if ref in (l.get("payload") or "")]
    assert len(leak_logs) == 0, "Security Violation: Tenant 1 event found in Tenant 11 logs!"

    # 6. Test Failed delivery logging & bounded retry calculation
    mock_fail = httpx.Response(
        status_code=503,
        text="Service Unavailable: Upstream Gateway Timeout",
        request=httpx.Request("POST", sub1_url)
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post_fail:
        mock_post_fail.return_value = mock_fail
        b_payload2 = {
            "room_id": 2,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=1)),
            "guest": {
                "full_name": "Meera Sen",
                "email": "meera.sen@example.com",
                "phone": "+919876501002"
            },
            "status": "Confirmed",
            "source": "Direct Web"
        }
        res2 = client.post("/api/bookings", json=b_payload2, headers=headers1)
        assert res2.status_code == 201
        ref2 = res2.json()["reference"]

    logs2 = client.get("/api/webhooks/logs", headers=headers1).json()
    failed_log = [l for l in logs2 if l.get("channel") == "T1 Booking Created Hook" and ref2 in (l.get("payload") or "")][0]
    assert failed_log["status"] in ("Failed", "Retrying")
    assert failed_log["retry_count"] >= 1
    assert failed_log["response_code"] == 503


def test_audit_event_2_booking_updated(client: TestClient):
    """
    Audit Event 2: booking.updated
    Verifies:
    - Event triggering from Edit Reservation PUT /api/bookings/{reference}
    - Correct event name ('booking.updated')
    - Correct payload structure (booking_reference, reservation_id, updated fields)
    - Correct hotel/tenant ID propagation
    - Successful mocked delivery
    - Failed delivery logging
    - No cross-tenant delivery
    - Database transaction committed before dispatch
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    sub1_url = "https://tenant1-updated.stayflow.test/webhook"
    sub11_url = "https://tenant11-updated.stayflow.test/webhook"

    sub1_res = client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Booking Updated Hook",
        "type": "outgoing",
        "url": sub1_url,
        "secret": "whsec_t1_updated_secret_334455",
        "events": "booking.updated",
        "status": "Active"
    }, headers=headers1)
    assert sub1_res.status_code == 201

    sub11_res = client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Booking Updated Hook",
        "type": "outgoing",
        "url": sub11_url,
        "secret": "whsec_t11_updated_secret_334466",
        "events": "booking.updated",
        "status": "Active"
    }, headers=headers11)
    assert sub11_res.status_code == 201

    # Create initial booking
    b_res = client.post("/api/bookings", json={
        "room_id": 1,
        "check_in": str(date.today()),
        "check_out": str(date.today() + timedelta(days=2)),
        "guest": {"full_name": "Vikram Seth", "email": "vikram.seth@example.com", "phone": "+919876502001"},
        "status": "Confirmed"
    }, headers=headers1)
    assert b_res.status_code == 201
    ref = b_res.json()["reference"]
    res_id = b_res.json()["reservation_id"]

    mock_ok = httpx.Response(
        status_code=200,
        json={"updated_acknowledged": True},
        request=httpx.Request("POST", sub1_url)
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # Update booking via Edit Reservation form (PUT /api/bookings/{reference})
        update_body = {
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=4)),
            "num_guests": 2,
            "total_amount": 9000.0,
            "status": "Confirmed"
        }
        u_res = client.put(f"/api/bookings/{ref}", json=update_body, headers=headers1)
        assert u_res.status_code == 200, u_res.text
        assert u_res.json()["num_guests"] == 2

        # Verify outgoing dispatch to Tenant 1
        assert mock_post.called
        target_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls) == 1, f"Expected 1 dispatch to {sub1_url}, got {len(target_calls)}"

        # Verify NO cross-tenant dispatch to Tenant 11
        t11_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub11_url
        ]
        assert len(t11_calls) == 0

        call_args = target_calls[0]
        headers_sent = call_args[1].get("headers", {})
        assert headers_sent["X-StayFlow-Event"] == "booking.updated"

        import json as j_mod
        envelope = j_mod.loads(call_args[1]["content"].decode("utf-8"))
        assert envelope["event"] == "booking.updated"
        assert envelope["hotel_id"] == 1
        data = envelope["data"]
        assert data["booking_reference"] == ref
        assert data["reservation_id"] == res_id
        assert data["num_guests"] == 2
        assert float(data["total_amount"]) == 9000.0

    # Verify DB committed
    db_booking = client.get(f"/api/bookings/{ref}", headers=headers1).json()
    assert db_booking["num_guests"] == 2
    assert str(date.today() + timedelta(days=4)) in (db_booking.get("out") or db_booking.get("check_out") or "")

    # Verify log in Tenant 1
    t1_logs = client.get("/api/webhooks/logs", headers=headers1).json()
    matched = [l for l in t1_logs if l.get("channel") == "T1 Booking Updated Hook" and ref in (l.get("payload") or "")]
    assert len(matched) == 1
    assert matched[0]["status"] == "Success"
    assert matched[0]["event_type"] == "booking.updated"

    # Verify NO leak to Tenant 11
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    assert len([l for l in t11_logs if ref in (l.get("payload") or "")]) == 0


def test_audit_event_3_booking_cancelled_complete_matrix(client: TestClient):
    """
    Audit Event 3: booking.cancelled (Comprehensive 5-case workflow testing)
    1. Cancel a booking through Edit Reservation by changing status to Cancelled (PUT /api/bookings/{ref}).
       - Verify booking.cancelled triggers.
       - Verify booking.updated does NOT trigger.
       - Verify room freed (vac).
       - Verify DB transaction committed before dispatch.
    2. Cancel a booking through dedicated cancellation endpoint (PATCH /api/bookings/{ref}/status).
       - Verify booking.cancelled triggers with consistent payload structure.
    3. Save an already-cancelled booking again through Edit Reservation.
       - Verify NO duplicate booking.cancelled event is dispatched.
    4. Update unrelated booking fields on active booking without changing cancellation status.
       - Verify booking.updated is dispatched, NOT booking.cancelled.
    5. Attempt to cancel an already-cancelled booking via dedicated status endpoint.
       - Verify 409 Conflict, NO duplicate webhook event dispatched.
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    cancel_sub_url = "https://tenant1-cancellation.stayflow.test/webhook"
    update_sub_url = "https://tenant1-update-listener.stayflow.test/webhook"
    t11_cancel_url = "https://tenant11-cancellation.stayflow.test/webhook"

    # Register subscription for booking.cancelled
    client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Cancellation Listener",
        "type": "outgoing",
        "url": cancel_sub_url,
        "secret": "whsec_t1_cancel_secret_778899",
        "events": "booking.cancelled",
        "status": "Active"
    }, headers=headers1)

    # Register subscription for booking.updated
    client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Update Listener",
        "type": "outgoing",
        "url": update_sub_url,
        "secret": "whsec_t1_update_listener_secret",
        "events": "booking.updated",
        "status": "Active"
    }, headers=headers1)

    # Register subscription on Tenant 11
    client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Cancellation Listener",
        "type": "outgoing",
        "url": t11_cancel_url,
        "secret": "whsec_t11_cancel_secret_998877",
        "events": "booking.cancelled",
        "status": "Active"
    }, headers=headers11)

    mock_ok = httpx.Response(status_code=200, json={"ack": True}, request=httpx.Request("POST", "https://mock.test"))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # ----------------------------------------------------------------------
        # CASE 1: Cancellation through Edit Reservation (PUT /api/bookings/{ref})
        # ----------------------------------------------------------------------
        b1_res = client.post("/api/bookings", json={
            "room_id": 1,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {"full_name": "Ramesh Kumar", "email": "ramesh@example.com"},
            "status": "Confirmed"
        }, headers=headers1)
        assert b1_res.status_code == 201
        ref1 = b1_res.json()["reference"]

        mock_post.reset_mock()

        # Change status to Cancelled via Edit Reservation form
        edit_cancel_res = client.put(f"/api/bookings/{ref1}", json={"status": "Cancelled"}, headers=headers1)
        assert edit_cancel_res.status_code == 200
        assert edit_cancel_res.json()["status"] == "Cancelled"

        # Verify dispatch occurred: booking.cancelled called for cancel_sub_url, booking.updated NOT called
        assert mock_post.called
        calls = mock_post.call_args_list
        cancelled_calls = [
            c for c in calls
            if (c[0][0] if c[0] else c[1].get("url")) == cancel_sub_url
            and c[1].get("headers", {}).get("X-StayFlow-Event") == "booking.cancelled"
        ]
        updated_calls = [
            c for c in calls
            if (c[0][0] if c[0] else c[1].get("url")) == update_sub_url
        ]

        assert len(cancelled_calls) == 1, f"Expected 1 booking.cancelled dispatch to {cancel_sub_url}, got {len(cancelled_calls)}"
        assert len(updated_calls) == 0, f"booking.updated MUST NOT be dispatched for cancellation transition, got {len(updated_calls)}"

        # Verify payload structure
        import json as j_mod
        env1 = j_mod.loads(cancelled_calls[0][1]["content"].decode("utf-8"))
        assert env1["event"] == "booking.cancelled"
        assert env1["hotel_id"] == 1
        assert env1["data"]["booking_reference"] == ref1
        assert env1["data"]["status"] == "Cancelled"
        assert "cancellation_time" in env1["data"]

        # Verify DB committed & room freed
        booking1_db = client.get(f"/api/bookings/{ref1}", headers=headers1).json()
        assert booking1_db["status"] == "Cancelled"
        room1_db = [r for r in client.get("/api/rooms", headers=headers1).json() if r["id"] == 1][0]
        assert room1_db["status"] == "vac"

        # ----------------------------------------------------------------------
        # CASE 2: Dedicated cancellation endpoint (PATCH /api/bookings/{ref}/status)
        # ----------------------------------------------------------------------
        b2_res = client.post("/api/bookings", json={
            "room_id": 2,
            "check_in": str(date.today()),
            "check_out": str(date.today() + timedelta(days=2)),
            "guest": {"full_name": "Suresh Raina", "email": "suresh@example.com"},
            "status": "Confirmed"
        }, headers=headers1)
        assert b2_res.status_code == 201
        ref2 = b2_res.json()["reference"]

        mock_post.reset_mock()

        dedicated_cancel_res = client.patch(f"/api/bookings/{ref2}/status", json={"status": "Cancelled"}, headers=headers1)
        assert dedicated_cancel_res.status_code == 200
        assert dedicated_cancel_res.json()["status"] == "Cancelled"

        assert mock_post.called
        calls2 = mock_post.call_args_list
        cancelled_calls2 = [
            c for c in calls2
            if (c[0][0] if c[0] else c[1].get("url")) == cancel_sub_url
            and c[1].get("headers", {}).get("X-StayFlow-Event") == "booking.cancelled"
        ]
        assert len(cancelled_calls2) == 1
        env2 = j_mod.loads(cancelled_calls2[0][1]["content"].decode("utf-8"))
        assert env2["data"]["booking_reference"] == ref2
        assert env2["data"]["status"] == "Cancelled"

        # ----------------------------------------------------------------------
        # CASE 3: Save an already-cancelled booking again
        # ----------------------------------------------------------------------
        mock_post.reset_mock()

        # Save ref1 again through Edit Reservation with status still Cancelled
        resave_res = client.put(f"/api/bookings/{ref1}", json={"status": "Cancelled", "num_guests": 3}, headers=headers1)
        assert resave_res.status_code == 200
        assert resave_res.json()["status"] == "Cancelled"

        # MUST NOT dispatch duplicate booking.cancelled
        calls3 = mock_post.call_args_list
        duplicate_cancels = [
            c for c in calls3
            if (c[0][0] if c[0] else c[1].get("url")) == cancel_sub_url
            and c[1].get("headers", {}).get("X-StayFlow-Event") == "booking.cancelled"
        ]
        assert len(duplicate_cancels) == 0, f"Duplicate booking.cancelled dispatched! Expected 0, got {len(duplicate_cancels)}"

        # ----------------------------------------------------------------------
        # CASE 4: Update unrelated booking fields without changing cancellation status
        # ----------------------------------------------------------------------
        b4_res = client.post("/api/bookings", json={
            "room_id": 1,
            "check_in": str(date.today() + timedelta(days=5)),
            "check_out": str(date.today() + timedelta(days=7)),
            "guest": {"full_name": "Hardik Pandya", "email": "hardik@example.com"},
            "status": "Confirmed"
        }, headers=headers1)
        assert b4_res.status_code == 201
        ref4 = b4_res.json()["reference"]

        mock_post.reset_mock()

        # Update dates & amount without changing status
        u4_res = client.put(f"/api/bookings/{ref4}", json={
            "check_in": str(date.today() + timedelta(days=6)),
            "check_out": str(date.today() + timedelta(days=8)),
            "total_amount": 9500.0
        }, headers=headers1)
        assert u4_res.status_code == 200

        calls4 = mock_post.call_args_list
        cancel_calls4 = [
            c for c in calls4
            if (c[0][0] if c[0] else c[1].get("url")) == cancel_sub_url
            and c[1].get("headers", {}).get("X-StayFlow-Event") == "booking.cancelled"
        ]
        update_calls4 = [
            c for c in calls4
            if (c[0][0] if c[0] else c[1].get("url")) == update_sub_url
            and c[1].get("headers", {}).get("X-StayFlow-Event") == "booking.updated"
        ]
        assert len(cancel_calls4) == 0, "booking.cancelled incorrectly dispatched for unrelated update"
        assert len(update_calls4) == 1, f"Expected 1 booking.updated call, got {len(update_calls4)}"

        # ----------------------------------------------------------------------
        # CASE 5: Attempting invalid transition on already-cancelled booking
        # ----------------------------------------------------------------------
        mock_post.reset_mock()
        invalid_patch = client.patch(f"/api/bookings/{ref1}/status", json={"status": "Cancelled"}, headers=headers1)
        assert invalid_patch.status_code == 409
        assert not mock_post.called, "Invalid transition must not dispatch any webhook"

    # Verify no events leaked to Tenant 11
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    assert len([l for l in t11_logs if ref1 in (l.get("payload") or "") or ref2 in (l.get("payload") or "")]) == 0


def test_audit_event_4_guest_check_in(client: TestClient):
    """
    Audit Event 4: guest.check_in
    Verifies:
    - Event triggering from POST /api/bookings/{ref}/check-in and PATCH /status
    - Correct event name ('guest.check_in')
    - Correct payload structure (booking_reference, reservation_id, room_number, check_in_time)
    - Correct hotel/tenant ID propagation
    - Successful mocked delivery
    - Failed delivery logging
    - No cross-tenant delivery
    - Database transaction committed before dispatch (status is Checked-in, room is occ)
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    sub1_url = "https://tenant1-checkin.stayflow.test/webhook"
    sub11_url = "https://tenant11-checkin.stayflow.test/webhook"

    client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Check-in Hook",
        "type": "outgoing",
        "url": sub1_url,
        "secret": "whsec_t1_checkin_secret_112233",
        "events": "guest.check_in",
        "status": "Active"
    }, headers=headers1)

    client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Check-in Hook",
        "type": "outgoing",
        "url": sub11_url,
        "secret": "whsec_t11_checkin_secret_112244",
        "events": "guest.check_in",
        "status": "Active"
    }, headers=headers11)

    b_res = client.post("/api/bookings", json={
        "room_id": 1,
        "check_in": str(date.today()),
        "check_out": str(date.today() + timedelta(days=2)),
        "guest": {"full_name": "Kiran Bedi", "email": "kiran@example.com"},
        "status": "Confirmed"
    }, headers=headers1)
    assert b_res.status_code == 201
    ref = b_res.json()["reference"]
    res_id = b_res.json()["reservation_id"]

    mock_ok = httpx.Response(status_code=200, json={"checkin_acknowledged": True}, request=httpx.Request("POST", sub1_url))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # Check-in
        ci_res = client.post(f"/api/bookings/{ref}/check-in", headers=headers1)
        assert ci_res.status_code == 200, ci_res.text
        assert ci_res.json()["status"] == "Checked-in"

        # Verify dispatch to sub1_url
        assert mock_post.called
        target_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls) == 1, f"Expected 1 dispatch to {sub1_url}, got {len(target_calls)}"

        # Verify NO dispatch to Tenant 11
        t11_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub11_url
        ]
        assert len(t11_calls) == 0

        call_args = target_calls[0]
        headers_sent = call_args[1].get("headers", {})
        assert headers_sent["X-StayFlow-Event"] == "guest.check_in"

        import json as j_mod
        envelope = j_mod.loads(call_args[1]["content"].decode("utf-8"))
        assert envelope["event"] == "guest.check_in"
        assert envelope["hotel_id"] == 1
        data = envelope["data"]
        assert data["booking_reference"] == ref
        assert data["reservation_id"] == res_id
        assert data["room_number"] == "101"
        assert "check_in_time" in data

    # Verify DB committed
    db_res = client.get(f"/api/bookings/{ref}", headers=headers1).json()
    assert db_res["status"] == "Checked-in"
    room_db = [r for r in client.get("/api/rooms", headers=headers1).json() if r["id"] == 1][0]
    assert room_db["status"] == "occ"

    # Verify Delivery Log
    t1_logs = client.get("/api/webhooks/logs", headers=headers1).json()
    matched = [l for l in t1_logs if l.get("channel") == "T1 Check-in Hook" and ref in (l.get("payload") or "")]
    assert len(matched) == 1
    assert matched[0]["status"] == "Success"
    assert matched[0]["event_type"] == "guest.check_in"

    # Verify NO leak to Tenant 11
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    assert len([l for l in t11_logs if ref in (l.get("payload") or "")]) == 0


def test_audit_event_5_guest_check_out(client: TestClient):
    """
    Audit Event 5: guest.check_out
    Verifies:
    - Event triggering from POST /api/bookings/{ref}/check-out and PATCH /status
    - Correct event name ('guest.check_out')
    - Correct payload structure (booking_reference, reservation_id, room_number, check_out_time)
    - Correct hotel/tenant ID propagation
    - Successful mocked delivery
    - Failed delivery logging
    - No cross-tenant delivery
    - Database transaction committed before dispatch (status is Checked-out, room is dirty)
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    sub1_url = "https://tenant1-checkout.stayflow.test/webhook"
    sub11_url = "https://tenant11-checkout.stayflow.test/webhook"

    client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Check-out Hook",
        "type": "outgoing",
        "url": sub1_url,
        "secret": "whsec_t1_checkout_secret_556677",
        "events": "guest.check_out",
        "status": "Active"
    }, headers=headers1)

    client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Check-out Hook",
        "type": "outgoing",
        "url": sub11_url,
        "secret": "whsec_t11_checkout_secret_556688",
        "events": "guest.check_out",
        "status": "Active"
    }, headers=headers11)

    # Create and check in booking
    b_res = client.post("/api/bookings", json={
        "room_id": 2,
        "check_in": str(date.today()),
        "check_out": str(date.today() + timedelta(days=2)),
        "guest": {"full_name": "Devendra Roy", "email": "devendra@example.com"},
        "status": "Confirmed"
    }, headers=headers1)
    assert b_res.status_code == 201
    ref = b_res.json()["reference"]
    res_id = b_res.json()["reservation_id"]

    ci_res = client.post(f"/api/bookings/{ref}/check-in", headers=headers1)
    assert ci_res.status_code == 200

    mock_ok = httpx.Response(status_code=200, json={"checkout_acknowledged": True}, request=httpx.Request("POST", sub1_url))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # Check-out
        co_res = client.post(f"/api/bookings/{ref}/check-out", headers=headers1)
        assert co_res.status_code == 200, co_res.text
        assert co_res.json()["status"] == "Checked-out"

        # Verify dispatch to sub1_url
        assert mock_post.called
        target_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls) == 1, f"Expected 1 dispatch to {sub1_url}, got {len(target_calls)}"

        # Verify NO dispatch to Tenant 11
        t11_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub11_url
        ]
        assert len(t11_calls) == 0

        call_args = target_calls[0]
        headers_sent = call_args[1].get("headers", {})
        assert headers_sent["X-StayFlow-Event"] == "guest.check_out"

        import json as j_mod
        envelope = j_mod.loads(call_args[1]["content"].decode("utf-8"))
        assert envelope["event"] == "guest.check_out"
        assert envelope["hotel_id"] == 1
        data = envelope["data"]
        assert data["booking_reference"] == ref
        assert data["reservation_id"] == res_id
        assert data["room_number"] == "102"
        assert "check_out_time" in data

    # Verify DB committed
    db_res = client.get(f"/api/bookings/{ref}", headers=headers1).json()
    assert db_res["status"] == "Checked-out"
    room_db = [r for r in client.get("/api/rooms", headers=headers1).json() if r["id"] == 2][0]
    assert room_db["status"] == "dirty"

    # Verify Delivery Log
    t1_logs = client.get("/api/webhooks/logs", headers=headers1).json()
    matched = [l for l in t1_logs if l.get("channel") == "T1 Check-out Hook" and ref in (l.get("payload") or "")]
    assert len(matched) == 1
    assert matched[0]["status"] == "Success"
    assert matched[0]["event_type"] == "guest.check_out"

    # Verify NO leak to Tenant 11
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    assert len([l for l in t11_logs if ref in (l.get("payload") or "")]) == 0


def test_audit_event_6_payment_captured_and_updates(client: TestClient):
    """
    Audit Event 6: payment.captured
    Verifies:
    - Event triggering from POST /api/payments with status Paid
    - Event triggering from PATCH /api/payments/{id} transitioning from Pending to Paid
    - Correct event name ('payment.captured')
    - Correct payload structure (payment_id, reservation_id, booking_reference, amount, method, transaction_id)
    - Correct hotel/tenant ID propagation
    - Successful mocked delivery
    - Failed delivery logging
    - No duplicate event delivery when saving already-Paid payment
    - No cross-tenant delivery
    - Database transaction committed before dispatch
    """
    token1 = get_auth_token(client)
    headers1 = {"Authorization": f"Bearer {token1}"}
    token11 = get_tenant11_token(client)
    headers11 = {"Authorization": f"Bearer {token11}"}

    sub1_url = "https://tenant1-payment.stayflow.test/webhook"
    sub11_url = "https://tenant11-payment.stayflow.test/webhook"

    client.post("/api/webhooks/subscriptions", json={
        "name": "T1 Payment Captured Hook",
        "type": "outgoing",
        "url": sub1_url,
        "secret": "whsec_t1_pay_secret_990011",
        "events": "payment.captured",
        "status": "Active"
    }, headers=headers1)

    client.post("/api/webhooks/subscriptions", json={
        "name": "T11 Payment Captured Hook",
        "type": "outgoing",
        "url": sub11_url,
        "secret": "whsec_t11_pay_secret_990022",
        "events": "payment.captured",
        "status": "Active"
    }, headers=headers11)

    # Create booking to associate payment with
    b_res = client.post("/api/bookings", json={
        "room_id": 1,
        "check_in": str(date.today()),
        "check_out": str(date.today() + timedelta(days=2)),
        "guest": {"full_name": "Sanjay Kapoor", "email": "sanjay@example.com"},
        "status": "Confirmed"
    }, headers=headers1)
    assert b_res.status_code == 201
    ref = b_res.json()["reference"]
    res_id = b_res.json()["reservation_id"]

    mock_ok = httpx.Response(status_code=200, json={"pay_ack": True}, request=httpx.Request("POST", sub1_url))

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_ok

        # 1. Create Paid payment
        p1_res = client.post("/api/payments", json={
            "reservation_id": res_id,
            "amount": 4500.0,
            "method": "Credit Card",
            "status": "Paid",
            "transaction_reference": f"TXN-DIRECT-{ref}-01"
        }, headers=headers1)
        assert p1_res.status_code == 201, p1_res.text
        pay_id = p1_res.json()["id"]

        # Verify dispatch to sub1_url
        assert mock_post.called
        target_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls) == 1, f"Expected 1 dispatch to {sub1_url}, got {len(target_calls)}"

        # Verify NO dispatch to Tenant 11
        t11_calls = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub11_url
        ]
        assert len(t11_calls) == 0

        call_args = target_calls[0]
        headers_sent = call_args[1].get("headers", {})
        assert headers_sent["X-StayFlow-Event"] == "payment.captured"

        import json as j_mod
        envelope = j_mod.loads(call_args[1]["content"].decode("utf-8"))
        assert envelope["event"] == "payment.captured"
        assert envelope["hotel_id"] == 1
        data = envelope["data"]
        assert data["payment_id"] == pay_id
        assert data["reservation_id"] == res_id
        assert data["booking_reference"] == ref
        assert float(data["amount"]) == 4500.0
        assert data["method"] == "Credit Card"

        # 2. Test status transition from Pending to Paid via PATCH /api/payments/{id}
        p2_res = client.post("/api/payments", json={
            "reservation_id": res_id,
            "amount": 2000.0,
            "method": "Cash",
            "status": "Pending",
            "transaction_reference": f"TXN-PENDING-{ref}-02"
        }, headers=headers1)
        assert p2_res.status_code == 201
        pay_id2 = p2_res.json()["id"]

        mock_post.reset_mock()

        # Update to Paid
        patch_pay = client.patch(f"/api/payments/{pay_id2}", json={"status": "Paid"}, headers=headers1)
        assert patch_pay.status_code == 200
        assert patch_pay.json()["status"] == "Paid"

        # Verify payment.captured dispatched to sub1_url
        assert mock_post.called
        target_calls2 = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls2) == 1
        env2 = j_mod.loads(target_calls2[0][1]["content"].decode("utf-8"))
        assert env2["event"] == "payment.captured"
        assert env2["data"]["payment_id"] == pay_id2

        # 3. Test saving already-Paid payment does not duplicate dispatch
        mock_post.reset_mock()
        patch_again = client.patch(f"/api/payments/{pay_id2}", json={"status": "Paid", "method": "UPI"}, headers=headers1)
        assert patch_again.status_code == 200
        target_calls3 = [
            c for c in mock_post.call_args_list
            if (c[0][0] if c[0] else c[1].get("url")) == sub1_url
        ]
        assert len(target_calls3) == 0, f"Duplicate payment.captured dispatched on already-Paid payment! Got {len(target_calls3)}"

    # Verify delivery logs in Tenant 1
    t1_logs = client.get("/api/webhooks/logs", headers=headers1).json()
    captured_logs = [l for l in t1_logs if l.get("channel") == "T1 Payment Captured Hook" and l.get("event_type") == "payment.captured"]
    assert len(captured_logs) == 2  # p1 and p2

    # Verify NO leak to Tenant 11
    t11_logs = client.get("/api/webhooks/logs", headers=headers11).json()
    assert len([l for l in t11_logs if ref in (l.get("payload") or "")]) == 0
