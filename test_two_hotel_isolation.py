import os
import sys
import json
from decimal import Decimal
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database.connection import SessionLocal
from app.models.entities import Tenant, User, Room, RoomType, Guest, Reservation, Payment, Amenity, ServiceRequest, DocumentChunk, KnowledgeDocument

client = TestClient(app)

print("=" * 80)
print("STARTING TWO-HOTEL MULTI-TENANCY DATA ISOLATION VERIFICATION SUITE")
print("=" * 80)

# Helper to log in and get token
def login(email, password="Password@123"):
    res = client.post("/api/auth/token", data={"username": email, "password": password})
    if res.status_code != 200:
        res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

headers_a = login("valichettykoushik@gmail.com")
headers_b = login("mukilan@gmail.com")
headers_sa = login("superadmin@stayflow.com", "SuperAdmin@2026!")

print("[1] Authentication & Token Claims Verified:")
me_a = client.get("/api/auth/me", headers=headers_a).json()
me_b = client.get("/api/auth/me", headers=headers_b).json()
me_sa = client.get("/api/auth/me", headers=headers_sa).json()

print(f"  Hotel A User: {me_a['email']} -> tenant_id: {me_a['tenant_id']} ({me_a.get('tenant', {}).get('name')})")
print(f"  Hotel B User: {me_b['email']} -> tenant_id: {me_b['tenant_id']} ({me_b.get('tenant', {}).get('name')})")
print(f"  Super Admin:  {me_sa['email']} -> is_super_admin: {me_sa['is_super_admin']}, tenant_id: {me_sa['tenant_id']}")

assert me_a['tenant_id'] == 10, f"Expected tenant 10 for Hotel A, got {me_a['tenant_id']}"
assert me_b['tenant_id'] == 11, f"Expected tenant 11 for Hotel B, got {me_b['tenant_id']}"
assert me_sa['is_super_admin'] is True, "Expected Super Admin privileges"

# Test 2: Data Isolation in Listing APIs
print("\n[2] Verifying Isolation across Listing APIs (Hotel A vs Hotel B):")
endpoints_to_check = [
    ("/api/rooms", "Rooms"),
    ("/api/room-types", "Room Types"),
    ("/api/bookings?limit=100", "Bookings"),
    ("/api/guests?limit=100", "Guests"),
    ("/api/payments", "Payments"),
    ("/api/amenities", "Amenities"),
    ("/api/service-requests", "Service Requests"),
    ("/api/webhooks/subscriptions", "Webhook Subscriptions"),
    ("/api/records", "Operational Records")
]

db = SessionLocal()

# Ensure at least one room and room type exist for both hotels for testing
rt_a = db.query(RoomType).filter(RoomType.tenant_id == 10).first()
if not rt_a:
    rt_a = RoomType(tenant_id=10, name="Hotel A Deluxe", base_price=Decimal("3500.00"), max_occupancy=2, description="Hotel A room")
    db.add(rt_a)
    db.commit()

room_a = db.query(Room).filter(Room.tenant_id == 10).first()
if not room_a:
    room_a = Room(tenant_id=10, number="101A", floor=1, room_type_id=rt_a.id, status="vac", description="Hotel A 101")
    db.add(room_a)
    db.commit()

guest_a = db.query(Guest).filter(Guest.tenant_id == 10).first()
if not guest_a:
    guest_a = Guest(tenant_id=10, full_name="Hotel A Guest", email="guestA@example.com", phone="+919111111111")
    db.add(guest_a)
    db.commit()

res_a = db.query(Reservation).filter(Reservation.tenant_id == 10).first()
if not res_a:
    res_a = Reservation(tenant_id=10, reference="HTA-BOOK-101", guest_id=guest_a.id, room_id=room_a.id, check_in=date.today(), check_out=date.today() + timedelta(days=2), total_amount=Decimal("7000.00"), status="Confirmed", source="Direct")
    db.add(res_a)
    db.commit()

amenity_a = db.query(Amenity).filter(Amenity.hotel_id == 10).first()
if not amenity_a:
    amenity_a = Amenity(hotel_id=10, amenity_type="wifi", name="Hotel A Wi-Fi", status="Available", pricing_type="complimentary", price=Decimal("0.00"), details="{}")
    db.add(amenity_a)
    db.commit()

# Hotel B test data
rt_b = db.query(RoomType).filter(RoomType.tenant_id == 11).first()
if not rt_b:
    rt_b = RoomType(tenant_id=11, name="Hotel B Suite", base_price=Decimal("4500.00"), max_occupancy=3, description="Hotel B room")
    db.add(rt_b)
    db.commit()

room_b = db.query(Room).filter(Room.tenant_id == 11).first()
if not room_b:
    room_b = Room(tenant_id=11, number="201B", floor=2, room_type_id=rt_b.id, status="vac", description="Hotel B 201")
    db.add(room_b)
    db.commit()

guest_b = db.query(Guest).filter(Guest.tenant_id == 11).first()
if not guest_b:
    guest_b = Guest(tenant_id=11, full_name="Hotel B Guest", email="guestB@example.com", phone="+919222222222")
    db.add(guest_b)
    db.commit()

res_b = db.query(Reservation).filter(Reservation.tenant_id == 11).first()
if not res_b:
    res_b = Reservation(tenant_id=11, reference="HTB-BOOK-201", guest_id=guest_b.id, room_id=room_b.id, check_in=date.today(), check_out=date.today() + timedelta(days=3), total_amount=Decimal("13500.00"), status="Confirmed", source="Direct")
    db.add(res_b)
    db.commit()

amenity_b = db.query(Amenity).filter(Amenity.hotel_id == 11).first()
if not amenity_b:
    amenity_b = Amenity(hotel_id=11, amenity_type="wifi", name="Hotel B Wi-Fi", status="Available", pricing_type="complimentary", price=Decimal("0.00"), details="{}")
    db.add(amenity_b)
    db.commit()

db.close()

# Now test listings
for path, label in endpoints_to_check:
    res_a_data = client.get(path, headers=headers_a).json()
    res_b_data = client.get(path, headers=headers_b).json()
    if isinstance(res_a_data, dict) and "data" in res_a_data:
        items_a = res_a_data["data"]
    elif isinstance(res_a_data, list):
        items_a = res_a_data
    else:
        items_a = []

    if isinstance(res_b_data, dict) and "data" in res_b_data:
        items_b = res_b_data["data"]
    elif isinstance(res_b_data, list):
        items_b = res_b_data
    else:
        items_b = []

    # Check that none of A's items are in B and vice-versa
    ids_a = {str(item.get("id") or item.get("reference") or item.get("request_id")) for item in items_a if (item.get("id") or item.get("reference") or item.get("request_id"))}
    ids_b = {str(item.get("id") or item.get("reference") or item.get("request_id")) for item in items_b if (item.get("id") or item.get("reference") or item.get("request_id"))}
    overlap = ids_a.intersection(ids_b)
    assert len(overlap) == 0, f"LEAK DETECTED in {label}: Overlapping IDs {overlap} between Hotel A and Hotel B!"
    print(f"  [PASS] {label:22}: Hotel A has {len(items_a):2} items, Hotel B has {len(items_b):2} items. Overlap = 0. PASSED.")

# Test 3: Cross-Tenant Read/Update/Delete Block Test
print("\n[3] Verifying Cross-Tenant Read/Update/Delete Attempts are BLOCKED:")

# 3a. Hotel A attempts to read Hotel B's Room
r_get = client.get(f"/api/rooms/{room_b.id}", headers=headers_a)
assert r_get.status_code in (403, 404), f"Cross-tenant room read should be blocked! Got {r_get.status_code}"
print(f"  [PASS] Hotel A GET Hotel B Room ({room_b.id}) -> Blocked ({r_get.status_code}).")

# 3b. Hotel A attempts to update Hotel B's Room
r_put = client.put(f"/api/rooms/{room_b.id}", json={"number": "HACKED", "floor": 1, "room_type_id": rt_b.id, "status": "vac", "description": ""}, headers=headers_a)
assert r_put.status_code in (403, 404), f"Cross-tenant room update should be blocked! Got {r_put.status_code}"
print(f"  [PASS] Hotel A PUT Hotel B Room ({room_b.id}) -> Blocked ({r_put.status_code}).")

# 3c. Hotel A attempts to delete Hotel B's Room
r_del = client.delete(f"/api/rooms/{room_b.id}", headers=headers_a)
assert r_del.status_code in (403, 404), f"Cross-tenant room delete should be blocked! Got {r_del.status_code}"
print(f"  [PASS] Hotel A DELETE Hotel B Room ({room_b.id}) -> Blocked ({r_del.status_code}).")

# 3d. Hotel A attempts to read Hotel B's Reservation
r_res_get = client.get(f"/api/bookings/{res_b.reference}", headers=headers_a)
assert r_res_get.status_code in (403, 404), f"Cross-tenant booking read should be blocked! Got {r_res_get.status_code}"
print(f"  [PASS] Hotel A GET Hotel B Booking ({res_b.reference}) -> Blocked ({r_res_get.status_code}).")

# 3e. Hotel A attempts to cancel/modify Hotel B's Reservation
r_res_patch = client.patch(f"/api/bookings/{res_b.reference}/status", json={"status": "Cancelled"}, headers=headers_a)
assert r_res_patch.status_code in (403, 404), f"Cross-tenant booking status change should be blocked! Got {r_res_patch.status_code}"
print(f"  [PASS] Hotel A PATCH Hotel B Booking Status -> Blocked ({r_res_patch.status_code}).")

# 3f. Hotel A attempts to read Hotel B's Guest
r_guest_get = client.get(f"/api/guests/{guest_b.id}", headers=headers_a)
assert r_guest_get.status_code in (403, 404), f"Cross-tenant guest read should be blocked! Got {r_guest_get.status_code}"
print(f"  [PASS] Hotel A GET Hotel B Guest ({guest_b.id}) -> Blocked ({r_guest_get.status_code}).")

# 3g. Hotel A attempts to delete Hotel B's Guest
r_guest_del = client.delete(f"/api/guests/{guest_b.id}", headers=headers_a)
assert r_guest_del.status_code in (403, 404), f"Cross-tenant guest delete should be blocked! Got {r_guest_del.status_code}"
print(f"  [PASS] Hotel A DELETE Hotel B Guest ({guest_b.id}) -> Blocked ({r_guest_del.status_code}).")

# 3h. Hotel A attempts to read Hotel B's Amenity
r_amenity_get = client.get(f"/api/amenities/{amenity_b.id}", headers=headers_a)
assert r_amenity_get.status_code in (403, 404), f"Cross-tenant amenity read should be blocked! Got {r_amenity_get.status_code}"
print(f"  [PASS] Hotel A GET Hotel B Amenity ({amenity_b.id}) -> Blocked ({r_amenity_get.status_code}).")

# 3i. Hotel A attempts to update Hotel B's Amenity
r_amenity_put = client.put(f"/api/amenities/{amenity_b.id}", json={"name": "Hacked Wi-Fi"}, headers=headers_a)
assert r_amenity_put.status_code in (403, 404), f"Cross-tenant amenity update should be blocked! Got {r_amenity_put.status_code}"
print(f"  [PASS] Hotel A PUT Hotel B Amenity ({amenity_b.id}) -> Blocked ({r_amenity_put.status_code}).")

# 3j. Hotel A attempts to delete Hotel B's Amenity
r_amenity_del = client.delete(f"/api/amenities/{amenity_b.id}", headers=headers_a)
assert r_amenity_del.status_code in (403, 404), f"Cross-tenant amenity delete should be blocked! Got {r_amenity_del.status_code}"
print(f"  [PASS] Hotel A DELETE Hotel B Amenity ({amenity_b.id}) -> Blocked ({r_amenity_del.status_code}).")

# Test 4: Cross-Tenant Foreign Key Relationship Rejection
print("\n[4] Verifying Cross-Tenant Foreign-Key Relationship Prevention:")

# 4a. Hotel A creates Room referencing Hotel B's RoomType
fk_room = client.post("/api/rooms", json={"number": "999A", "floor": 9, "room_type_id": rt_b.id, "status": "vac", "description": "Invalid FK"}, headers=headers_a)
assert fk_room.status_code in (400, 403, 404), f"Should reject room with cross-tenant room_type_id! Got {fk_room.status_code}"
print(f"  [PASS] Hotel A Room with Hotel B RoomType ({rt_b.id}) -> Rejected ({fk_room.status_code}).")

# 4b. Hotel A creates Booking referencing Hotel B's Room
fk_book_room = client.post("/api/bookings", json={
    "guest_id": guest_a.id,
    "room_id": room_b.id,
    "room_type_id": rt_a.id,
    "check_in": str(date.today() + timedelta(days=5)),
    "check_out": str(date.today() + timedelta(days=7)),
    "total_amount": 5000.0,
    "status": "Confirmed",
    "source": "Direct"
}, headers=headers_a)
assert fk_book_room.status_code in (400, 403, 404), f"Should reject booking with cross-tenant room_id! Got {fk_book_room.status_code}"
print(f"  [PASS] Hotel A Booking with Hotel B Room ({room_b.id}) -> Rejected ({fk_book_room.status_code}).")

# 4c. Hotel A creates Booking referencing Hotel B's Guest
fk_book_guest = client.post("/api/bookings", json={
    "guest_id": guest_b.id,
    "room_id": room_a.id,
    "room_type_id": rt_a.id,
    "check_in": str(date.today() + timedelta(days=10)),
    "check_out": str(date.today() + timedelta(days=12)),
    "total_amount": 5000.0,
    "status": "Confirmed",
    "source": "Direct"
}, headers=headers_a)
assert fk_book_guest.status_code in (400, 403, 404), f"Should reject booking with cross-tenant guest_id! Got {fk_book_guest.status_code}"
print(f"  [PASS] Hotel A Booking with Hotel B Guest ({guest_b.id}) -> Rejected ({fk_book_guest.status_code}).")

# 4d. Hotel A records Payment referencing Hotel B's Reservation
fk_pay = client.post("/api/payments", json={
    "reservation_id": res_b.id,
    "amount": 1000.0,
    "method": "Cash",
    "status": "Paid",
    "transaction_reference": "TXN-CROSS-TENANT-TEST"
}, headers=headers_a)
assert fk_pay.status_code in (400, 403, 404), f"Should reject payment for cross-tenant reservation! Got {fk_pay.status_code}"
print(f"  [PASS] Hotel A Payment on Hotel B Reservation ({res_b.id}) -> Rejected ({fk_pay.status_code}).")

# Test 5: Header Spoofing Block
print("\n[5] Verifying Frontend Header Spoofing is BLOCKED:")
# Hotel A sends X-Tenant-Id: 11 header attempting to access Hotel B data
spoofed = client.get("/api/rooms", headers={**headers_a, "X-Tenant-Id": "11"}).json()
for r in spoofed:
    assert r["n"] != room_b.number, f"Header spoofing succeeded! Hotel A saw Hotel B room {room_b.number}!"
print(f"  [PASS] Hotel A sent 'X-Tenant-Id: 11': Backend ignored header and returned Hotel A data ({len(spoofed)} rooms). Spoofing BLOCKED.")

# Test 6: Platform-Level Super Admin Scoping
print("\n[6] Verifying Platform-Level Super Admin Scoping via explicit X-Tenant-Id:")
sa_rooms_a = client.get("/api/rooms", headers={**headers_sa, "X-Tenant-Id": "10"}).json()
sa_rooms_b = client.get("/api/rooms", headers={**headers_sa, "X-Tenant-Id": "11"}).json()
print(f"  [PASS] Super Admin scoped to Tenant 10: {len(sa_rooms_a)} rooms.")
print(f"  [PASS] Super Admin scoped to Tenant 11: {len(sa_rooms_b)} rooms.")
assert any(str(r.get("number")) == str(room_a.number) for r in sa_rooms_a), f"Super Admin should see Hotel A room {room_a.number} when scoped to 10. Got {[r.get('number') for r in sa_rooms_a]}"
assert any(str(r.get("number")) == str(room_b.number) for r in sa_rooms_b), f"Super Admin should see Hotel B room {room_b.number} when scoped to 11. Got {[r.get('number') for r in sa_rooms_b]}"

# Test 7: RAG Vector Search Isolation
print("\n[7] Verifying RAG & Knowledge Base Tenant Isolation:")
db = SessionLocal()
# Create knowledge chunk for Hotel A
chunk_a = db.query(DocumentChunk).filter(DocumentChunk.tenant_id == 10).first()
if not chunk_a:
    chunk_a = DocumentChunk(
        tenant_id=10,
        hotel_id=10,
        document_id="DOC-HTA-POLICY",
        chunk_index=0,
        content="Hotel A Executive Lounge offers complimentary high tea between 4 PM and 6 PM exclusively for Hotel A guests.",
        metadata_json=json.dumps({"hotel": "Hotel A", "type": "policy"})
    )
    db.add(chunk_a)
    db.commit()

# Query from Hotel B
rag_search_b = client.get("/api/knowledge-base/search?query=Executive%20Lounge", headers=headers_b).json()
chunks_b = rag_search_b if isinstance(rag_search_b, list) else rag_search_b.get("results", [])
for c in chunks_b:
    assert c.get("tenant_id") != 10, "Cross-tenant RAG chunk leaked to Hotel B!"
    assert "Hotel A" not in c.get("content", ""), "Hotel A secret content leaked in Hotel B search!"

print(f"  [PASS] Hotel B searched 'Executive Lounge': Hotel A chunk was NEVER returned ({len(chunks_b)} results). RAG isolation PASSED.")
db.close()

print("\n" + "=" * 80)
print("ALL TWO-HOTEL DATA ISOLATION TESTS PASSED WITHOUT ERRORS!")
print("=" * 80)
