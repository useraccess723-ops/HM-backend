import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database.connection import Base, get_db
from app.core.config import settings
from app.core.security import hash_password
from app.models import User, RoomType, Room, Amenity

@pytest.fixture()
def client():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        hotel2_user = User(
            email="manager2@hotel.com",
            full_name="Hotel 2 Manager",
            password_hash=hash_password("Password@123"),
            role="MANAGER",
            hotel_id=2,
            tenant_id=2
        )
        db.add_all([admin_user, hotel2_user])
        rt = RoomType(tenant_id=1, name="Standard", base_price=Decimal("2000.00"), max_occupancy=2, description="", amenities="[]")
        db.add(rt)
        db.commit()
        db.add(Room(tenant_id=1, number="101", floor=1, room_type_id=rt.id, status="vac", description=""))
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

def test_amenities_crud_and_validation(client):
    headers = auth_header(client)

    # 1. Create Wi-Fi amenity
    wifi_data = {
        "amenity_type": "wifi",
        "name": "StayFlow-Lobby-5G",
        "details": {
            "network_name": "StayFlow-Lobby-5G",
            "coverage_area": "Lobby & Lounge",
            "password": "SecretPassword123",
            "speed": "300 Mbps",
            "notes": "Fast guest access"
        }
    }
    r = client.post("/api/amenities", json=wifi_data, headers=headers)
    assert r.status_code == 201, r.text
    wifi_id = r.json()["id"]
    assert r.json()["name"] == "StayFlow-Lobby-5G"
    assert r.json()["amenity_type"] == "wifi"
    assert r.json()["details"]["speed"] == "300 Mbps"

    # 2. Create AC amenity associated with room 101
    ac_data = {
        "amenity_type": "ac",
        "name": "Room 101 AC Unit",
        "room_number": "101",
        "status": "Operational",
        "details": {
            "room_number": "101",
            "ac_type": "Daikin Inverter Split",
            "temperature_setting": "22°C",
            "maintenance_status": "Good",
            "notes": "Recently serviced"
        }
    }
    r = client.post("/api/amenities", json=ac_data, headers=headers)
    assert r.status_code == 201, r.text
    ac_id = r.json()["id"]
    assert r.json()["room_number"] == "101"
    assert r.json()["room_id"] is not None

    # 3. Create TV amenity associated with room 101
    tv_data = {
        "amenity_type": "tv",
        "name": "Room 101 Smart TV",
        "room_number": "101",
        "status": "Operational",
        "details": {
            "room_number": "101",
            "tv_type": "Samsung 4K UHD 50\"",
            "channels_services": "Netflix, DTH, YouTube",
            "remote_status": "Operational",
            "maintenance_status": "Good",
            "notes": "HDMI 1 connected"
        }
    }
    r = client.post("/api/amenities", json=tv_data, headers=headers)
    assert r.status_code == 201, r.text

    # 4. Create Swimming Pool amenity
    pool_data = {
        "amenity_type": "swimming_pool",
        "name": "Rooftop Heated Pool",
        "status": "Open",
        "details": {
            "pool_name": "Rooftop Heated Pool",
            "pool_type": "Infinity Rooftop",
            "opening_time": "06:00 AM",
            "closing_time": "10:00 PM",
            "capacity": "30",
            "safety_status": "Lifeguard on duty",
            "maintenance_notes": "Cleaned daily"
        }
    }
    r = client.post("/api/amenities", json=pool_data, headers=headers)
    assert r.status_code == 201, r.text

    # 5. List with filter by type
    r_list = client.get("/api/amenities?type=wifi", headers=headers)
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1
    assert r_list.json()[0]["amenity_type"] == "wifi"

    # 6. Summary endpoint
    r_summary = client.get("/api/amenities/summary", headers=headers)
    assert r_summary.status_code == 200
    assert r_summary.json()["wifi"]["total"] == 1
    assert r_summary.json()["ac"]["total"] == 1
    assert r_summary.json()["tv"]["total"] == 1
    assert r_summary.json()["swimming_pool"]["total"] == 1

    # 7. Update AC temperature setting
    r_update = client.put(f"/api/amenities/{ac_id}", json={
        "status": "Maintenance",
        "details": {"temperature_setting": "20°C", "maintenance_status": "Filter Clean Required"}
    }, headers=headers)
    assert r_update.status_code == 200
    assert r_update.json()["status"] == "Maintenance"
    assert r_update.json()["details"]["temperature_setting"] == "20°C"

    # 8. Workflow integration: Create guest service ticket for amenity
    r_ticket = client.post(f"/api/amenities/{ac_id}/request", json={
        "guest_name": "Priya Sharma",
        "room_number": "101",
        "service_type": "AC Temperature Adjustment",
        "priority": "High",
        "request_details": "Guest requested cooling inspection and remote battery check."
    }, headers=headers)
    assert r_ticket.status_code == 201
    assert "request_id" in r_ticket.json()
    assert r_ticket.json()["status"] == "In Progress"

    # 9. Test Gym, Parking, and Spa creation
    gym_data = {
        "amenity_type": "gym",
        "name": "StayFlow Performance Gym",
        "details": {
            "gym_name": "StayFlow Performance Gym",
            "available_equipment": "Treadmills, Dumbbells, Cable Machines",
            "opening_time": "05:00 AM",
            "closing_time": "11:00 PM",
            "capacity": "25",
            "maintenance_notes": "Sanitized daily"
        }
    }
    r = client.post("/api/amenities", json=gym_data, headers=headers)
    assert r.status_code == 201

    parking_data = {
        "amenity_type": "parking",
        "name": "Basement Valet Bay",
        "details": {
            "parking_type": "Valet Covered",
            "total_spaces": "50",
            "available_spaces": "20",
            "parking_location": "Basement 1",
            "parking_charges": "Complimentary"
        }
    }
    r = client.post("/api/amenities", json=parking_data, headers=headers)
    assert r.status_code == 201

    spa_data = {
        "amenity_type": "spa",
        "name": "Aromatherapy Massage",
        "details": {
            "service_name": "Aromatherapy Massage",
            "duration": "60 Mins",
            "price": "3000",
            "available_time_slots": "10:00 - 20:00",
            "booking_status": "Available"
        }
    }
    r = client.post("/api/amenities", json=spa_data, headers=headers)
    assert r.status_code == 201

    # 10. Room validation error test for AC with non-existent room
    invalid_ac = {
        "amenity_type": "ac",
        "name": "Invalid Room AC",
        "room_number": "9999",
        "details": {"room_number": "9999"}
    }
    r_bad = client.post("/api/amenities", json=invalid_ac, headers=headers)
    assert r_bad.status_code == 422
    assert "does not exist" in r_bad.json()["detail"]

    # 11. Multi-tenancy isolation test
    hotel2_headers = auth_header(client, "manager2@hotel.com", "Password@123")
    r_hotel2_list = client.get("/api/amenities", headers=hotel2_headers)
    assert r_hotel2_list.status_code == 200
    # Hotel 2 should not see Hotel 1's records
    assert len(r_hotel2_list.json()) == 0

    # 12. Delete Wi-Fi amenity
    r_del = client.delete(f"/api/amenities/{wifi_id}", headers=headers)
    assert r_del.status_code == 200

    r_check = client.get(f"/api/amenities/{wifi_id}", headers=headers)
    assert r_check.status_code == 404
