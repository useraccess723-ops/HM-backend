import os
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-characters-long")
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
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
from app.models import User, RoomType, Room

@pytest.fixture()
def client():
    settings.JWT_SECRET_KEY = "test-secret-key-with-at-least-32-characters-long"
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)
    with TestingSession() as db:
        db.add(User(email="admin@example.com", full_name="Test Admin", password_hash=hash_password("correct horse battery"), role="ADMIN", tenant_id=1))
        db.add(RoomType(tenant_id=1, name="Standard", base_price=Decimal("1500.00"), max_occupancy=2, description="", amenities="[]"))
        db.commit()
        rt=db.query(RoomType).filter_by(name="Standard").one()
        db.add(Room(tenant_id=1, number="101",floor=1,room_type_id=rt.id,status="vac",description=""))
        db.commit()
    def override_db():
        db=TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()

def token(client):
    r=client.post("/api/auth/login",json={"email":"admin@example.com","password":"correct horse battery"})
    assert r.status_code==200, r.text
    return r.json()["access_token"]

def test_health(client):
    assert client.get("/health").json()["status"]=="ok"

def test_login_rejects_wrong_password(client):
    assert client.post("/api/auth/login",json={"email":"admin@example.com","password":"wrong password"}).status_code==401

def test_room_list_and_dashboard_are_database_backed(client):
    headers={"Authorization":"Bearer "+token(client)}
    rooms=client.get("/api/rooms",headers=headers)
    assert rooms.status_code==200 and len(rooms.json())==1
    dashboard=client.get("/api/dashboard",headers=headers).json()
    assert dashboard["total_rooms"]==1
    assert dashboard["available_rooms"]==1

def test_booking_overlap_is_rejected(client):
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Guest Example","email":"guest@example.com","phone":"9000000000"})
    assert guest.status_code==201,guest.text
    payload={"guest_id":guest.json()["id"],"room_id":1,"check_in":(date.today()+timedelta(days=30)).isoformat(),"check_out":(date.today()+timedelta(days=32)).isoformat(),"source":"Direct"}
    first=client.post("/api/bookings",headers=headers,json=payload)
    assert first.status_code==201,first.text
    overlapping={**payload,"check_in":(date.today()+timedelta(days=31)).isoformat(),"check_out":(date.today()+timedelta(days=33)).isoformat()}
    second=client.post("/api/bookings",headers=headers,json=overlapping)
    assert second.status_code==409,second.text

def test_invalid_reservation_dates_rejected(client):
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Guest Example"})
    payload={"guest_id":guest.json()["id"],"room_id":1,"check_in":(date.today()+timedelta(days=40)).isoformat(),"check_out":(date.today()+timedelta(days=40)).isoformat(),"source":"Direct"}
    assert client.post("/api/bookings",headers=headers,json=payload).status_code==422

def test_past_dates_rejected_but_today_and_future_allowed(client):
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Guest Example"}).json()
    today=datetime.now(ZoneInfo("Asia/Kolkata")).date()
    def book(cin,cout): return client.post("/api/bookings",headers=headers,json={"guest_id":guest["id"],"room_id":1,"check_in":cin.isoformat(),"check_out":cout.isoformat(),"source":"Direct"})
    past=book(today-timedelta(days=3),today+timedelta(days=2))
    assert past.status_code==422 and "past" in past.json()["detail"].lower()
    assert book(today-timedelta(days=5),today-timedelta(days=3)).status_code==422
    ok=book(today,today+timedelta(days=1))
    assert ok.status_code==201,ok.text
    ref=ok.json()["id"]
    # moving an existing booking's check-in into the past is rejected; a future move is fine
    assert client.put(f"/api/bookings/{ref}",headers=headers,json={"check_in":(today-timedelta(days=1)).isoformat()}).status_code==422
    assert client.put(f"/api/bookings/{ref}",headers=headers,json={"check_out":(today+timedelta(days=4)).isoformat()}).status_code==200
    assert client.put(f"/api/bookings/{ref}",headers=headers,json={"check_out":today.isoformat()}).status_code==422

def test_booking_with_payment_can_be_deleted(client):
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Guest Example"}).json()
    today=datetime.now(ZoneInfo("Asia/Kolkata")).date()
    b=client.post("/api/bookings",headers=headers,json={"guest_id":guest["id"],"room_id":1,"check_in":today.isoformat(),"check_out":(today+timedelta(days=1)).isoformat(),"source":"Direct"}).json()
    pay=client.post("/api/payments",headers=headers,json={"reservation_id":b["reservation_id"],"amount":100,"method":"UPI","status":"Paid"})
    assert pay.status_code in (200,201),pay.text
    assert client.delete(f"/api/bookings/{b['id']}",headers=headers).status_code==200

def test_room_status_update_is_persisted(client):
    headers={"Authorization":"Bearer "+token(client)}
    response=client.patch('/api/rooms/1/status',headers=headers,json={"status":"dirty"})
    assert response.status_code==200, response.text
    assert response.json()['s']=='dirty'
    assert client.get('/api/rooms',headers=headers).json()[0]['s']=='dirty'

def test_hotel_settings_are_database_backed(client):
    headers={"Authorization":"Bearer "+token(client)}
    saved=client.put('/api/settings',headers=headers,json={"hotel_name":"StayFlow Chennai","check_in_time":"14:00","check_out_time":"11:00","currency":"INR","timezone":"Asia/Kolkata","gst_percent":12,"cancellation_hours":48,"no_show_charge":"First night"})
    assert saved.status_code==200, saved.text
    assert client.get('/api/settings',headers=headers).json()['hotel_name']=='StayFlow Chennai'

def test_present_date_booking_allowed(client):
    from datetime import date, timedelta
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Present Guest"})
    today = date.today()
    tomorrow = today + timedelta(days=1)
    payload={"guest_id":guest.json()["id"],"room_id":1,"check_in":today.isoformat(),"check_out":tomorrow.isoformat(),"source":"Direct"}
    r = client.post("/api/bookings",headers=headers,json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["in"] == today.isoformat()
    assert r.json()["out"] == tomorrow.isoformat()

def test_future_date_booking_allowed(client):
    from datetime import date, timedelta
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Future Guest"})
    future_in = date.today() + timedelta(days=10)
    future_out = date.today() + timedelta(days=13)
    payload={"guest_id":guest.json()["id"],"room_id":1,"check_in":future_in.isoformat(),"check_out":future_out.isoformat(),"source":"Direct"}
    r = client.post("/api/bookings",headers=headers,json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["in"] == future_in.isoformat()
    assert r.json()["out"] == future_out.isoformat()

def test_past_date_booking_rejected(client):
    from datetime import date, timedelta
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Past Guest"})
    past_in = date.today() - timedelta(days=3)
    past_out = date.today() + timedelta(days=1)
    payload={"guest_id":guest.json()["id"],"room_id":1,"check_in":past_in.isoformat(),"check_out":past_out.isoformat(),"source":"Direct"}
    r = client.post("/api/bookings",headers=headers,json=payload)
    assert r.status_code == 422, r.text
    assert "Check-in date cannot be in the past" in r.text

def test_checkout_before_or_equal_checkin_rejected(client):
    from datetime import date, timedelta
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Date Guest"})
    today = date.today()
    yesterday = today - timedelta(days=1)
    # Check-out equal to check-in
    r1 = client.post("/api/bookings",headers=headers,json={"guest_id":guest.json()["id"],"room_id":1,"check_in":today.isoformat(),"check_out":today.isoformat(),"source":"Direct"})
    assert r1.status_code == 422, r1.text
    assert "Check-out must be after check-in" in r1.text
    # Check-out before check-in
    future = today + timedelta(days=5)
    r2 = client.post("/api/bookings",headers=headers,json={"guest_id":guest.json()["id"],"room_id":1,"check_in":future.isoformat(),"check_out":(future - timedelta(days=2)).isoformat(),"source":"Direct"})
    assert r2.status_code == 422, r2.text
    assert "Check-out must be after check-in" in r2.text

def test_booking_status_create_and_update(client):
    from datetime import date, timedelta
    headers={"Authorization":"Bearer "+token(client)}
    guest=client.post("/api/guests",headers=headers,json={"full_name":"Status Test Guest"})
    check_in = date.today() + timedelta(days=20)
    check_out = date.today() + timedelta(days=22)
    payload={
        "guest_id": guest.json()["id"],
        "room_id": 1,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "source": "Direct",
        "status": "Confirmed"
    }
    r = client.post("/api/bookings", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    booking = r.json()
    assert booking["st"] == "Confirmed"
    ref = booking["id"]

    # Update status to Cancelled via PUT
    update_res = client.put(f"/api/bookings/{ref}", headers=headers, json={"status": "Cancelled"})
    assert update_res.status_code == 200, update_res.text
    assert update_res.json()["st"] == "Cancelled"

    # Verify persistence by re-fetching
    fetched = client.get(f"/api/bookings/{ref}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["st"] == "Cancelled"

