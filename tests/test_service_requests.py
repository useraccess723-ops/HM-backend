import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")

from app.main import app, generate_unique_service_request_id, calculate_amenity_charge
from app.database.connection import Base, get_db
from app.core.config import settings
from app.core.security import hash_password
from app.models import User, RoomType, Room, Amenity, Reservation, Guest
from app.models.entities import ServiceRequest

@pytest.fixture()
def client():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    with TestingSession() as db:
        # Hotel 1 Admin
        admin_user = User(
            email="admin@hotel.com",
            full_name="Hotel Administrator",
            password_hash=hash_password("Password@123"),
            role="ADMIN",
            hotel_id=1,
            tenant_id=1
        )
        # Hotel 1 Customer
        customer_user = User(
            email="customer@hotel.com",
            full_name="Vikram Malhotra",
            password_hash=hash_password("Password@123"),
            role="CUSTOMER",
            hotel_id=1,
            tenant_id=1
        )
        # Hotel 2 Manager (for multi-tenant isolation testing)
        hotel2_user = User(
            email="manager2@hotel.com",
            full_name="Hotel 2 Manager",
            password_hash=hash_password("Password@123"),
            role="MANAGER",
            hotel_id=2,
            tenant_id=2
        )
        db.add_all([admin_user, customer_user, hotel2_user])

        # Room Type & Room for Hotel 1
        rt = RoomType(tenant_id=1, name="Deluxe Suite", base_price=Decimal("4500.00"), max_occupancy=2, description="", amenities="[]")
        db.add(rt)
        db.commit()

        room101 = Room(tenant_id=1, number="101", floor=1, room_type_id=rt.id, status="occ", description="")
        db.add(room101)
        db.commit()

        # Active Reservation for Vikram Malhotra
        guest_vm = Guest(tenant_id=1, full_name="Vikram Malhotra", email="customer@hotel.com", phone="+91 9876543210")
        db.add(guest_vm)
        db.commit()

        today = date.today()
        res_vm = Reservation(
            tenant_id=1,
            reference="BK-CUST2026",
            guest_id=guest_vm.id,
            room_id=room101.id,
            check_in=today - timedelta(days=1),
            check_out=today + timedelta(days=3),
            total_amount=Decimal("13500.00"),
            status="Checked-in"
        )
        db.add(res_vm)

        # Amenities for Hotel 1
        amenity_wifi = Amenity(
            hotel_id=1,
            amenity_type="wifi",
            name="StayFlow-Ultra-5G",
            status="Available",
            pricing_type="complimentary",
            price=Decimal("0.00"),
            rules="Fair usage policy applies. Device limit: 4 devices per room.",
            details=json.dumps({
                "network_name": "StayFlow-Ultra-5G",
                "coverage_area": "All Guest Rooms, Lobby, Pool & Suites",
                "password": "SecretSuperPassword123",
                "access_instructions": "Select StayFlow-Ultra-5G and enter room number on captive portal",
                "speed": "300 Mbps"
            })
        )
        amenity_pool = Amenity(
            hotel_id=1,
            amenity_type="pool",
            name="Infinity Sky Pool",
            status="Available",
            pricing_type="per_guest",
            price=Decimal("350.00"),
            rules="Appropriate swimwear required. Children under 12 must be accompanied by an adult.",
            details=json.dumps({
                "opening_time": "06:00",
                "closing_time": "22:00",
                "capacity": 30
            })
        )
        amenity_spa = Amenity(
            hotel_id=1,
            amenity_type="spa",
            name="Ayurvedic Wellness Spa",
            status="Available",
            pricing_type="per_session",
            price=Decimal("1500.00"),
            rules="Please arrive 15 minutes before scheduled slot. 4 hours notice required for free cancellation.",
            details=json.dumps({
                "service_types": ["Full Body Massage", "Deep Tissue", "Facial"],
                "opening_time": "08:00",
                "closing_time": "21:00"
            })
        )
        amenity_parking = Amenity(
            hotel_id=1,
            amenity_type="parking",
            name="Secure Valet Parking",
            status="Available",
            pricing_type="per_vehicle",
            price=Decimal("200.00"),
            rules="Standard height clearance 2.2m. Valet ticket must be presented at departure.",
            details=json.dumps({
                "vehicle_types": ["Sedan", "SUV", "EV", "Motorcycle"],
                "capacity": 100
            })
        )
        db.add_all([amenity_wifi, amenity_pool, amenity_spa, amenity_parking])
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

# ── 1. Unit Tests for ID Generator & Pricing Calculator ──

def test_service_request_id_generator(client):
    """Test unique collision-resistant ID generation format SR-YYYY-XXXXX."""
    from app.database.connection import get_db
    db = next(app.dependency_overrides[get_db]())
    current_year = date.today().year

    id1 = generate_unique_service_request_id(db, hotel_id=1)
    assert id1.startswith(f"SR-{current_year}-")
    assert len(id1) == 13  # e.g. SR-2026-00001

    # Simulate inserting id1
    sr1 = ServiceRequest(
        hotel_id=1,
        request_id=id1,
        guest_name="Test User",
        service_type="wifi",
        status="Pending"
    )
    db.add(sr1)
    db.commit()

    id2 = generate_unique_service_request_id(db, hotel_id=1)
    assert id2 != id1
    assert id2.startswith(f"SR-{current_year}-")
    db.close()

def test_pricing_calculator():
    """Test calculation of trusted backend pricing for various models."""
    # Complimentary
    tot, p_type, pay_status = calculate_amenity_charge(None, "complimentary", 0.0, quantity=5)
    assert tot == 0.0
    assert p_type == "included_in_tariff"
    assert pay_status == "included in room tariff"

    # Per Guest
    tot, p_type, pay_status = calculate_amenity_charge(None, "per_guest", 350.0, quantity=3)
    assert tot == 1050.0
    assert p_type == "per_guest"
    assert pay_status == "unpaid"

    # Per Session
    tot, p_type, pay_status = calculate_amenity_charge(None, "per_session", 1500.0, quantity=2)
    assert tot == 3000.0
    assert p_type == "per_session"
    assert pay_status == "unpaid"

    # Per Vehicle
    tot, p_type, pay_status = calculate_amenity_charge(None, "per_vehicle", 200.0, quantity=1)
    assert tot == 200.0
    assert p_type == "per_vehicle"
    assert pay_status == "unpaid"

    # Included in tariff
    tot, p_type, pay_status = calculate_amenity_charge(None, "included_in_tariff", 500.0, quantity=2)
    assert tot == 0.0
    assert pay_status == "included in room tariff"

# ── 2. Customer Amenities & Booking Flow ──

def test_customer_amenities_list_masks_credentials(client):
    """Customer endpoint must display amenities, pricing and rules, but NEVER expose raw wifi passwords."""
    headers = auth_header(client, "customer@hotel.com", "Password@123")
    res = client.get("/api/customer/amenities", headers=headers)
    assert res.status_code == 200, res.text
    items = res.json()
    assert len(items) >= 4

    wifi = next(a for a in items if a["amenity_type"] == "wifi")
    assert wifi["pricing_type"] == "complimentary"
    assert "rules" in wifi
    assert "details" in wifi
    # Security: password should NOT be present in customer output
    assert "password" not in wifi["details"]
    assert wifi["details"]["access_instructions"] != ""

def test_customer_active_bookings(client):
    """Customer can fetch their active reservation for room 101."""
    headers = auth_header(client, "customer@hotel.com", "Password@123")
    res = client.get("/api/customer/active-bookings", headers=headers)
    assert res.status_code == 200, res.text
    bookings = res.json()
    assert len(bookings) == 1
    b = bookings[0]
    assert b["confirmation_code"] == "BK-CUST2026"
    assert b["room_number"] == "101"

def test_customer_amenity_booking_and_pricing(client):
    """Customer submits amenity booking. Pricing is calculated securely on backend."""
    headers = auth_header(client, "customer@hotel.com", "Password@123")

    # Fetch pool amenity id
    amenities = client.get("/api/customer/amenities", headers=headers).json()
    pool = next(a for a in amenities if a["amenity_type"] == "pool")

    # 1. Book Pool with 3 guests (Price in DB is 350.00 -> Total should be 1050.00)
    # Notice we intentionally try sending client total_price = 1.00 to verify backend calculates trusted price!
    booking_payload = {
        "amenity_id": pool["id"],
        "booking_reference": "BK-CUST2026",
        "room_number": "101",
        "requested_date": str(date.today()),
        "requested_time": "16:00",
        "guest_count": 3,
        "special_instructions": "Provide 3 fresh pool towels",
        "amenity_details": {
            "session_time": "16:00 - 18:00",
            "guest_count": 3
        },
        "total_price": 1.00  # Attempted override should be ignored
    }

    res = client.post("/api/customer/amenity-booking", json=booking_payload, headers=headers)
    assert res.status_code in (200, 201), res.text
    data = res.json()

    assert data["request_id"].startswith("SR-")
    assert data["customer_name"] == "Vikram Malhotra"
    assert data["room"] == "101"
    assert data["pricing_type"] == "per_guest"
    assert float(data["unit_price"]) == 350.00
    assert float(data["total_price"]) == 1050.00  # Trusted calculation: 3 * 350
    assert data["payment_status"] == "unpaid"
    assert data["status"] == "Pending"

    req_id = data["id"]
    code_id = data["request_id"]

    # 2. Check My Requests
    my_reqs_res = client.get("/api/customer/my-requests", headers=headers)
    assert my_reqs_res.status_code == 200
    my_reqs = my_reqs_res.json()
    assert any(r["request_id"] == code_id for r in my_reqs)

    # 3. Customer can cancel their pending request
    cancel_res = client.post(f"/api/service-requests/{req_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200, cancel_res.text
    cancelled_data = cancel_res.json()
    assert cancelled_data["status"] == "Cancelled"
    assert cancelled_data["payment_status"] == "unpaid"

def test_complimentary_amenity_charges(client):
    """Complimentary or tariff-included amenity sets total_price 0 and payment_status 'included in room tariff'."""
    headers = auth_header(client, "customer@hotel.com", "Password@123")
    amenities = client.get("/api/customer/amenities", headers=headers).json()
    wifi = next(a for a in amenities if a["amenity_type"] == "wifi")

    booking_payload = {
        "amenity_id": wifi["id"],
        "booking_reference": "BK-CUST2026",
        "room_number": "101",
        "requested_date": str(date.today()),
        "requested_time": "10:00",
        "guest_count": 1,
        "special_instructions": "Need high speed connection for conference call",
        "amenity_details": {
            "device_count": 2,
            "device_types": ["Laptop", "Smartphone"]
        }
    }

    res = client.post("/api/customer/amenity-booking", json=booking_payload, headers=headers)
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert float(data["total_price"]) == 0.00
    assert data["payment_status"] == "included in room tariff"
    assert data["status"] == "Pending"

def test_invalid_booking_or_unauthorized_customer_prevention(client):
    """Only valid bookings belonging to the customer in the correct hotel are allowed."""
    headers = auth_header(client, "customer@hotel.com", "Password@123")
    amenities = client.get("/api/customer/amenities", headers=headers).json()
    pool = next(a for a in amenities if a["amenity_type"] == "pool")

    # Invalid non-existent booking code
    fake_payload = {
        "amenity_id": pool["id"],
        "booking_reference": "NON-EXISTENT-BOOKING",
        "room_number": "999",
        "requested_date": str(date.today()),
        "requested_time": "15:00"
    }
    res = client.post("/api/customer/amenity-booking", json=fake_payload, headers=headers)
    assert res.status_code in (400, 404)

# ── 3. Admin Management & Multi-Tenancy Isolation ──

def test_admin_service_request_lifecycle(client):
    """Admin views, searches, updates status (Approved, Scheduled, Completed), assigns staff and notes."""
    # First create a request as customer
    cust_headers = auth_header(client, "customer@hotel.com", "Password@123")
    amenities = client.get("/api/customer/amenities", headers=cust_headers).json()
    spa = next(a for a in amenities if a["amenity_type"] == "spa")

    res = client.post("/api/customer/amenity-booking", json={
        "amenity_id": spa["id"],
        "booking_reference": "BK-CUST2026",
        "room_number": "101",
        "requested_date": str(date.today()),
        "requested_time": "11:00",
        "guest_count": 1,
        "amenity_details": {"service": "Deep Tissue", "therapist_gender": "Female"}
    }, headers=cust_headers)
    assert res.status_code in (200, 201), res.text
    sr = res.json()
    sr_id = sr["id"]
    code_id = sr["request_id"]

    # Admin Login
    admin_headers = auth_header(client, "admin@hotel.com", "Password@123")

    # 1. Admin GET list and filter
    list_res = client.get(f"/api/service-requests?query={code_id}", headers=admin_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 2. Admin updates status to Approved and assigns staff
    update_res = client.put(f"/api/service-requests/{sr_id}", json={
        "status": "Approved",
        "assigned_to": "Kavita Nair (Senior Therapist)",
        "admin_notes": "Confirmed appointment for 11:00 AM slot. Room notified.",
        "payment_status": "paid"
    }, headers=admin_headers)
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["status"] == "Approved"
    assert updated["assigned_to"] == "Kavita Nair (Senior Therapist)"
    assert updated["payment_status"] == "paid"

    # 3. Customer immediately sees the updated status
    cust_view_res = client.get("/api/customer/my-requests", headers=cust_headers)
    assert cust_view_res.status_code == 200
    my_sr = next(r for r in cust_view_res.json() if r["id"] == sr_id)
    assert my_sr["status"] == "Approved"
    assert my_sr["assigned_to"] == "Kavita Nair (Senior Therapist)"
    assert my_sr["payment_status"] == "paid"

    # 4. Admin marks as Completed
    comp_res = client.put(f"/api/service-requests/{sr_id}", json={
        "status": "Completed",
        "admin_notes": "Treatment successfully delivered."
    }, headers=admin_headers)
    assert comp_res.status_code == 200
    assert comp_res.json()["status"] == "Completed"

    # 5. Customer cannot cancel an already completed service
    cant_cancel_res = client.post(f"/api/service-requests/{sr_id}/cancel", headers=cust_headers)
    assert cant_cancel_res.status_code == 400

def test_admin_manual_create_auto_generates_id(client):
    """When Admin creates a service request manually without ID, backend assigns SR-YYYY-XXXXX."""
    admin_headers = auth_header(client, "admin@hotel.com", "Password@123")
    res = client.post("/api/service-requests", json={
        "guest_name": "Walk-in Guest",
        "room": "101",
        "service_type": "Housekeeping & Linen",
        "priority": "High",
        "assigned_to": "Ravi Kumar",
        "status": "Active"
    }, headers=admin_headers)
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert data["request_id"].startswith("SR-")
    assert data["guest_name"] == "Walk-in Guest"

def test_multi_tenancy_isolation(client):
    """Hotel 2 Manager cannot view or modify Hotel 1 service requests."""
    # Create request in Hotel 1
    admin1_headers = auth_header(client, "admin@hotel.com", "Password@123")
    h1_sr = client.post("/api/service-requests", json={
        "guest_name": "Hotel 1 Guest",
        "room": "101",
        "service_type": "Concierge",
        "status": "Active"
    }, headers=admin1_headers).json()
    sr1_id = h1_sr["id"]

    # Login as Hotel 2 Manager
    h2_headers = auth_header(client, "manager2@hotel.com", "Password@123")

    # Hotel 2 list should NOT include Hotel 1 request
    h2_list = client.get("/api/service-requests", headers=h2_headers).json()
    assert all(r["id"] != sr1_id for r in h2_list)

    # Hotel 2 direct access should return 403 or 404
    h2_get = client.get(f"/api/service-requests/{sr1_id}", headers=h2_headers)
    assert h2_get.status_code in (403, 404)
