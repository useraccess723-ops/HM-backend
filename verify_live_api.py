import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

def run_live_verification():
    print(f"=== Starting Live API Verification against {BASE_URL} ===")
    
    # 1. Customer Authentication
    print("\n1. Testing Customer Authentication (customer@hotel.com)...")
    res = requests.post(f"{BASE_URL}/api/auth/token", data={
        "username": "customer@hotel.com",
        "password": "Password@123"
    })
    if res.status_code != 200:
        print(f"FAILED to authenticate customer: {res.status_code} - {res.text}")
        return False
    cust_token = res.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}
    print("   [OK] Customer authenticated successfully.")

    # 2. Customer Amenities Catalog
    print("\n2. Testing Customer Amenities Listing & Security Sanitization...")
    res = requests.get(f"{BASE_URL}/api/customer/amenities", headers=cust_headers)
    assert res.status_code == 200, res.text
    amenities = res.json()
    print(f"   [OK] Retrieved {len(amenities)} available amenities.")
    
    types = [a["amenity_type"] for a in amenities]
    print(f"   [OK] Amenity types found: {', '.join(set(types))}")
    
    wifi = next((a for a in amenities if a["amenity_type"] == "wifi"), None)
    if wifi:
        assert "password" not in wifi["details"], "SECURITY ALERT: Raw Wi-Fi password exposed in customer endpoint!"
        print("   [OK] Wi-Fi sensitive password verified SANITIZED and hidden from customer.")

    # 3. Customer Active Stays
    print("\n3. Testing Customer Active Hotel Reservations...")
    res = requests.get(f"{BASE_URL}/api/customer/active-bookings", headers=cust_headers)
    assert res.status_code == 200, res.text
    bookings = res.json()
    assert len(bookings) > 0, "No active bookings found for customer!"
    active_b = bookings[0]
    print(f"   [OK] Found active stay: Reference {active_b.get('reference')}, Room {active_b.get('room_number')}, Status {active_b.get('status')}")

    # 4. Customer Amenity Booking with Trusted Backend Pricing
    print("\n4. Testing Amenity Booking with Backend Pricing & Auto-Generated ID...")
    pool = next((a for a in amenities if a["amenity_type"] == "pool"), amenities[0])
    pool_price = pool["price"]
    guest_count = 2
    expected_total = round(pool_price * guest_count, 2)

    booking_payload = {
        "amenity_id": pool["id"],
        "booking_reference": active_b.get("reference"),
        "room_number": active_b.get("room_number"),
        "requested_date": "2026-10-22",
        "requested_time": "16:00",
        "guest_count": guest_count,
        "special_instructions": "Provide 2 extra pool towels",
        "amenity_details": {
            "session": "Evening (16:00 - 18:00)",
            "guest_count": guest_count
        },
        "total_price": 0.01 # Tampered price sent by client; backend must ignore and calculate trusted price!
    }

    res = requests.post(f"{BASE_URL}/api/customer/amenity-booking", json=booking_payload, headers=cust_headers)
    assert res.status_code in (200, 201), res.text
    b_data = res.json()
    
    req_id = b_data["request_id"]
    db_id = b_data["id"]
    print(f"   [OK] Booking created! Auto-Generated Request ID: {req_id}")
    assert req_id.startswith("SR-2026-"), f"Unexpected ID format: {req_id}"
    
    charged = b_data["total_charge"]
    print(f"   [OK] Trusted Charge Calculated: INR {charged} (Client submitted INR 0.01 was rejected, calculated {guest_count} x INR {pool_price} = INR {expected_total})")
    assert charged == expected_total or pool["pricing_type"] in ["complimentary", "included_in_tariff"], f"Expected {expected_total}, got {charged}"

    # 5. Customer My Service Requests
    print("\n5. Testing Customer 'My Service Requests' History...")
    res = requests.get(f"{BASE_URL}/api/customer/my-requests", headers=cust_headers)
    assert res.status_code == 200
    my_reqs = res.json()
    assert any(r["request_id"] == req_id for r in my_reqs), f"{req_id} not found in customer history"
    print(f"   [OK] Verified {req_id} appears in customer's request history with status: {b_data['status']}")

    # 6. Admin Management & Status Update
    print("\n6. Testing Hotel Admin View & Management (admin@hotel.com)...")
    res = requests.post(f"{BASE_URL}/api/auth/token", data={
        "username": "admin@hotel.com",
        "password": "Password@123"
    })
    assert res.status_code == 200
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin searches for request
    res = requests.get(f"{BASE_URL}/api/service-requests?search={req_id}", headers=admin_headers)
    assert res.status_code == 200
    found_reqs = res.json()
    assert len(found_reqs) >= 1
    print(f"   [OK] Admin successfully searched and retrieved request {req_id}")

    # Admin updates status to Scheduled & assigns staff
    res = requests.put(f"{BASE_URL}/api/service-requests/{db_id}", json={
        "status": "Scheduled",
        "assigned_to": "Rajesh Kumar (Senior Lifeguard)",
        "admin_notes": "Pool lane 2 reserved for guest party.",
        "payment_status": "paid"
    }, headers=admin_headers)
    assert res.status_code == 200
    updated = res.json()
    print(f"   [OK] Admin updated status to: {updated['status']}, Staff: {updated['assigned_to']}, Payment: {updated['payment_status']}")

    # 7. Customer sees updated status automatically
    print("\n7. Testing Automatic Customer-Facing Status Sync...")
    res = requests.get(f"{BASE_URL}/api/customer/my-requests", headers=cust_headers)
    assert res.status_code == 200
    synced = next(r for r in res.json() if r["request_id"] == req_id)
    assert synced["status"] == "Scheduled", f"Expected Scheduled, got {synced['status']}"
    assert synced["assigned_to"] == "Rajesh Kumar (Senior Lifeguard)"
    assert synced["payment_status"] == "paid"
    print(f"   [OK] Customer dashboard reflects synced live status: {synced['status']} (Staff: {synced['assigned_to']})")

    # 8. Customer Cancellation Rules
    print("\n8. Testing Customer Cancellation Rules...")
    res = requests.post(f"{BASE_URL}/api/service-requests/{db_id}/cancel", json={
        "reason": "Change of travel plans"
    }, headers=cust_headers)
    assert res.status_code == 200
    canc = res.json()
    assert canc["status"] == "Cancelled"
    assert canc["payment_status"] == "refunded" # Was paid, now refunded
    print(f"   [OK] Customer cancelled request. Final status: {canc['status']}, Payment: {canc['payment_status']}")

    print("\n=======================================================")
    print(" ALL LIVE API WORKFLOW TESTS COMPLETED SUCCESSFULLY! ")
    print("=======================================================")
    return True

if __name__ == "__main__":
    success = run_live_verification()
    sys.exit(0 if success else 1)
