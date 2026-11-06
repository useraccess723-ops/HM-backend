import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8000"

def post(url, data, token=None, tenant_id=None):
    req = urllib.request.Request(
        f"{BASE}{url}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if tenant_id:
        req.add_header("X-Tenant-Id", str(tenant_id))
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def get(url, token=None, tenant_id=None):
    req = urllib.request.Request(f"{BASE}{url}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if tenant_id:
        req.add_header("X-Tenant-Id", str(tenant_id))
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def patch(url, data, token=None):
    req = urllib.request.Request(
        f"{BASE}{url}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH"
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

print("=" * 60)
print("TEST 1: SUPER ADMIN AUTHENTICATION & PORTAL ENDPOINTS")
print("=" * 60)
status, res = post("/api/auth/login", {"email": "superadmin@stayflow.com", "password": "SuperAdmin@2026!"})
assert status == 200, f"SuperAdmin login failed: {res}"
super_token = res["access_token"]
print("✓ SuperAdmin logged in successfully.")
print(f"  User: {res['user']['email']}, is_super_admin: {res['user']['is_super_admin']}, role: {res['user']['role']}")

# Superadmin dashboard
st, data = get("/api/superadmin/dashboard", super_token)
assert st == 200, f"Dashboard failed: {data}"
print(f"✓ SuperAdmin Dashboard loaded: total_tenants={data['metrics']['total_tenants']}, total_rooms={data['metrics']['total_rooms']}")

# Superadmin tenants
st, data = get("/api/superadmin/tenants", super_token)
assert st == 200, f"Tenants list failed: {data}"
print(f"✓ SuperAdmin Tenants: found {len(data)} tenants:")
for t in data:
    plan = t.get('subscription_plan') or t.get('plan') or 'Standard'
    print(f"    - Tenant #{t['id']}: {t['name']} ({t['code']}) [{plan}] status={t['status']}")

# Superadmin administrators
st, data = get("/api/superadmin/administrators", super_token)
assert st == 200, f"Administrators failed: {data}"
print(f"✓ SuperAdmin Administrators: {len(data)} admins found across tenants")

# Superadmin configurations
st, data = get("/api/superadmin/configurations", super_token)
assert st == 200, f"Configurations failed: {data}"
print(f"✓ SuperAdmin Configurations: {len(data)} tenant configs found")

# Superadmin settings
st, data = get("/api/superadmin/settings", super_token)
assert st == 200, f"Platform Settings failed: {data}"
print(f"✓ SuperAdmin Platform Settings: platform_name={data['platform_name']}, maintenance_mode={data['maintenance_mode']}")

# Superadmin monitoring
st, data = get("/api/superadmin/monitoring", super_token)
assert st == 200, f"Monitoring failed: {data}"
print(f"✓ SuperAdmin Monitoring: status={data['status']}, pool_size={data['database_pool']['pool_size']}, events={data['network']['audit_trail_events']}")

print("\n" + "=" * 60)
print("TEST 2: TENANT 1 (Grand Meridian Chennai) ISOLATION")
print("=" * 60)
status, res = post("/api/auth/login", {"email": "admin@hotel.com", "password": "Password@123"})
assert status == 200, f"Tenant 1 login failed: {res}"
t1_token = res["access_token"]
print(f"✓ Tenant 1 logged in: tenant_id={res['user']['tenant_id']}, hotel={res['tenant']['name']}")

# Check rooms for Tenant 1
st, rooms1 = get("/api/rooms", t1_token)
assert st == 200
print(f"✓ Tenant 1 sees {len(rooms1)} rooms (scoped to Grand Meridian)")

# Tenant 1 attempts to access Super Admin API
st, forbidden_res = get("/api/superadmin/dashboard", t1_token)
print(f"✓ Tenant 1 accessing /api/superadmin/dashboard: status={st} (Expected: 403 Forbidden)")
assert st == 403

# Tenant 1 attempts to tamper with Tenant 2 header
st, spoofed_rooms = get("/api/rooms", t1_token, tenant_id=2)
assert st == 200
assert len(spoofed_rooms) == len(rooms1), "Tenant 1 bypassed isolation via header!"
print(f"✓ Tenant 1 passing spoofed 'X-Tenant-Id: 2' correctly ignored: still receives {len(spoofed_rooms)} rooms")

print("\n" + "=" * 60)
print("TEST 3: TENANT 2 (Royal Palace New Delhi) ISOLATION")
print("=" * 60)
status, res = post("/api/auth/login", {"email": "admin@royalpalace.com", "password": "Password@123"})
assert status == 200, f"Tenant 2 login failed: {res}"
t2_token = res["access_token"]
print(f"✓ Tenant 2 logged in: tenant_id={res['user']['tenant_id']}, hotel={res['tenant']['name']}")

# Check rooms for Tenant 2
st, rooms2 = get("/api/rooms", t2_token)
assert st == 200
print(f"✓ Tenant 2 sees {len(rooms2)} rooms (scoped to Royal Palace)")
assert len(rooms2) != len(rooms1), "Rooms should be isolated per tenant!"

# Tenant 2 attempts to view / modify Tenant 1's room
t1_first_room_id = rooms1[0]["id"]
st, tamper_res = get(f"/api/rooms/{t1_first_room_id}", t2_token)
print(f"✓ Tenant 2 querying Tenant 1 room #{t1_first_room_id}: status={st} (Expected: 404 Item not found)")
assert st == 404

print("\n" + "=" * 60)
print("TEST 4: SUPER ADMIN SCOPED INSPECTION")
print("=" * 60)
# Super Admin without header -> all rooms
st, all_rooms = get("/api/rooms", super_token)
print(f"✓ Super Admin without header sees all {len(all_rooms)} rooms across all tenants")

# Super Admin with header for Tenant 2 -> exactly Tenant 2's rooms
st, sa_t2_rooms = get("/api/rooms", super_token, tenant_id=2)
print(f"✓ Super Admin with 'X-Tenant-Id: 2' inspects exactly Tenant 2's {len(sa_t2_rooms)} rooms")
assert len(sa_t2_rooms) == len(rooms2)

print("\n" + "=" * 60)
print("ALL MULTI-TENANCY TESTS PASSED SUCCESSFULLY! 👑🏨")
print("=" * 60)
