import os
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database.connection import Base, get_db
from app.core.config import settings
from app.models import User, RoomType, Room
from app.core.security import hash_password

@pytest.fixture()
def client_and_headers():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    with TestingSession() as db:
        admin = User(
            email="admin@test.com",
            full_name="Admin Tester",
            password_hash=hash_password("adminpassword123"),
            role="ADMIN",
            tenant_id=1
        )
        db.add(admin)
        db.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as c:
        res = c.post("/api/auth/login", json={"email": "admin@test.com", "password": "adminpassword123"})
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        yield c, headers, TestingSession

    app.dependency_overrides.clear()

def test_room_amenities_list(client_and_headers):
    client, headers, _ = client_and_headers
    res = client.get("/api/room-amenities", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "amenities" in data
    assert len(data["amenities"]) >= 35
    assert "Free Wi-Fi" in data["amenities"]
    assert "Air Conditioning" in data["amenities"]

def test_room_types_crud_and_validation(client_and_headers):
    client, headers, Session = client_and_headers

    # 1. Create room type
    payload = {
        "name": "Penthouse Royal",
        "short_description": "Exclusive top floor penthouse with 360 panoramic views.",
        "description": "Ultra luxurious penthouse featuring private elevator, heated pool, and butler service.",
        "base_price": 15000.0,
        "weekend_price": 18000.0,
        "max_adults": 4,
        "max_children": 2,
        "max_guests": 6,
        "number_of_beds": 3,
        "bed_type": "King-size Bed",
        "room_size_sqft": 1200,
        "bathroom_type": "En-suite Jacuzzi",
        "number_of_bathrooms": 3,
        "view_type": "Swimming Pool View",
        "floor_preference": "Floor 5 (Penthouse)",
        "amenities": ["Free Wi-Fi", "Air Conditioning", "Bathtub", "Balcony", "Room Service"],
        "extra_adult_charge": 2000.0,
        "extra_child_charge": 1000.0,
        "extra_bed_charge": 2000.0,
        "tax_percentage": 18.0,
        "breakfast_included": True,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 72 hours before arrival.",
        "check_in_time": "12:00",
        "check_out_time": "12:00",
        "minimum_stay_nights": 2,
        "maximum_stay_nights": 14,
        "refund_policy": "Full refund if cancelled 72 hours before arrival.",
        "additional_notes": "VIP security screening applies.",
        "image_url": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b",
        "status": "Active"
    }
    res = client.post("/api/room-types", json=payload, headers=headers)
    assert res.status_code == 201
    created = res.json()
    created_id = created["id"]
    assert created["name"] == "Penthouse Royal"
    assert created["base_price"] == 15000.0
    assert created["max_guests"] == 6
    assert created["slug"] == "penthouse-royal"

    # 2. Reject duplicate room type name
    dup_res = client.post("/api/room-types", json=payload, headers=headers)
    assert dup_res.status_code == 409

    # 3. Get room type by ID
    get_res = client.get(f"/api/room-types/{created_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Penthouse Royal"

    # 4. Search and filter
    list_res = client.get("/api/room-types?search=penthouse", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 5. Update room type
    update_payload = dict(payload)
    update_payload["base_price"] = 16500.0
    update_payload["short_description"] = "Updated penthouse description."
    put_res = client.put(f"/api/room-types/{created_id}", json=update_payload, headers=headers)
    assert put_res.status_code == 200
    assert put_res.json()["base_price"] == 16500.0
    assert put_res.json()["short_description"] == "Updated penthouse description."

    # 6. Status patch
    patch_res = client.patch(f"/api/room-types/{created_id}/status", json={"status": "Inactive"}, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "Inactive"

    # Verify status filter
    inactive_res = client.get("/api/room-types?status=Inactive", headers=headers)
    assert any(x["id"] == created_id for x in inactive_res.json())

    # 7. Stats endpoint
    stats_res = client.get("/api/room-types/stats", headers=headers)
    assert stats_res.status_code == 200
    assert stats_res.json()["total"] >= 1
    assert stats_res.json()["inactive"] >= 1

    # 8. Restrict deletion when room is assigned
    with Session() as db:
        room = Room(number="PH-501", floor=5, room_type_id=created_id, status="vac")
        db.add(room)
        db.commit()

    del_fail_res = client.delete(f"/api/room-types/{created_id}", headers=headers)
    assert del_fail_res.status_code == 409
    assert "Deactivate this room type instead" in del_fail_res.json()["detail"]

    # Remove room and delete succeeds
    with Session() as db:
        db.query(Room).filter(Room.room_type_id == created_id).delete()
        db.commit()

    del_ok_res = client.delete(f"/api/room-types/{created_id}", headers=headers)
    assert del_ok_res.status_code == 200
