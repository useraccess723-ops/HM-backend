import sys, os
sys.path.insert(0, os.path.abspath('hotelmanageemnt-backend'))
import pytest
import os
import json
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///./test_new_features.db"

from app.main import app
from app.database.connection import Base, engine, SessionLocal
from app.models.entities import Tenant, User, Role, OperationalRecord
from app.core.security import hash_password, create_access_token
from app.database.seed_data import ensure_default_roles, ensure_default_users, DEFAULT_USERS_DATA
from app.database.migrations import ensure_default_tenants

@pytest.fixture(scope="module")
def setup_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_default_tenants(db)
        ensure_default_roles(db)
        ensure_default_users(db)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test_new_features.db"):
        try:
            os.remove("./test_new_features.db")
        except Exception:
            pass

@pytest.fixture
def client(setup_db):
    return TestClient(app)

@pytest.fixture
def admin_token(setup_db):
    with SessionLocal() as db:
        user = db.scalar(Base.metadata.tables["users"].select().where(Base.metadata.tables["users"].c.email == "admin@hotel.com"))
        token = create_access_token(subject="admin@hotel.com", role="ADMIN", tenant_id=1)
        return token

def test_login_modal_removes_create_guest_account():
    """Verify that Login.jsx does not include 'Create Guest Account' but preserves 'Register Hotel'."""
    with open("hotelmanagement-frontend/src/pages/Login.jsx", "r", encoding="utf-8") as f:
        content = f.read()
    assert "Create Guest Account" not in content, "Create Guest Account link should be removed from Login modal"
    assert "Register Hotel" in content, "Register Hotel button must be preserved in Login modal"

def test_payslip_validation_rejects_empty(client, admin_token):
    """Verify that saving a completely empty payslip record returns HTTP 400."""
    headers = {"Authorization": f"Bearer {admin_token}", "X-Tenant-Id": "1"}
    payload = {
        "category": "human-resources_payroll",
        "title": "Generate Payslip",
        "data": {},
        "status": "Active"
    }
    resp = client.post("/api/records", json=payload, headers=headers)
    assert resp.status_code == 400, f"Expected 400 for empty payslip, got {resp.status_code}: {resp.text}"
    assert "empty" in resp.text.lower() or "mandatory" in resp.text.lower()

def test_payslip_validation_rejects_missing_mandatory_fields(client, admin_token):
    """Verify missing Employee Name or Month is rejected with HTTP 400."""
    headers = {"Authorization": f"Bearer {admin_token}", "X-Tenant-Id": "1"}
    
    # Missing employee name
    p1 = {
        "category": "human-resources_payroll",
        "title": "Generate Payslip",
        "data": {"Month": "October 2026", "Basic Salary (₹)": 50000},
    }
    r1 = client.post("/api/records", json=p1, headers=headers)
    assert r1.status_code == 400
    assert "Employee Name" in r1.text

    # Missing month
    p2 = {
        "category": "human-resources_payroll",
        "title": "Generate Payslip",
        "data": {"Employee Name": "Rahul Sharma", "Basic Salary (₹)": 50000},
    }
    r2 = client.post("/api/records", json=p2, headers=headers)
    assert r2.status_code == 400
    assert "Month" in r2.text

def test_payslip_validation_rejects_negative_salary(client, admin_token):
    """Verify negative basic salary or allowances are rejected with HTTP 400."""
    headers = {"Authorization": f"Bearer {admin_token}", "X-Tenant-Id": "1"}
    p = {
        "category": "human-resources_payroll",
        "title": "Generate Payslip",
        "data": {
            "Employee Name": "Rahul Sharma",
            "Month": "October 2026",
            "Basic Salary (₹)": -5000,
        },
    }
    r = client.post("/api/records", json=p, headers=headers)
    assert r.status_code == 400
    assert "non-negative" in r.text or "valid" in r.text

def test_payslip_successful_save_and_duplicate_prevention(client, admin_token):
    """Verify valid payslip saves with HTTP 201 and duplicate payslip for same employee + month returns HTTP 409."""
    headers = {"Authorization": f"Bearer {admin_token}", "X-Tenant-Id": "1"}
    p = {
        "category": "human-resources_payroll",
        "title": "Generate Payslip",
        "data": {
            "Employee Name": "Ramesh Kumar",
            "Employee ID": "EMP-101",
            "Department": "Front Desk",
            "Month": "November 2026",
            "Basic Salary (₹)": 45000,
            "Allowances (₹)": 5000,
            "Deductions (₹)": 2000,
            "Net Salary (₹)": 48000,
            "Payment Method": "Direct Bank Transfer",
            "Payment Status": "Processed"
        },
        "status": "Active"
    }
    r = client.post("/api/records", json=p, headers=headers)
    assert r.status_code == 201, f"Failed to save valid payslip: {r.text}"
    data = r.json()
    assert "Payslip: Ramesh Kumar (November 2026)" in data["title"]

    # Attempt duplicate save for same employee + period in tenant 1
    r_dup = client.post("/api/records", json=p, headers=headers)
    assert r_dup.status_code == 409, f"Expected 409 for duplicate payslip, got {r_dup.status_code}: {r_dup.text}"
    assert "already exists" in r_dup.text

def test_default_users_seeded(setup_db):
    """Verify that default logins are properly stored in the database."""
    with SessionLocal() as db:
        superadmin = db.scalar(Base.metadata.tables["users"].select().where(Base.metadata.tables["users"].c.email == "superadmin@stayflow.com"))
        admin = db.scalar(Base.metadata.tables["users"].select().where(Base.metadata.tables["users"].c.email == "admin@hotel.com"))
        customer = db.scalar(Base.metadata.tables["users"].select().where(Base.metadata.tables["users"].c.email == "customer@hotel.com"))
        frontdesk = db.scalar(Base.metadata.tables["users"].select().where(Base.metadata.tables["users"].c.email == "frontdesk@hotel.com"))

        assert superadmin is not None, "superadmin@stayflow.com must be seeded"
        assert admin is not None, "admin@hotel.com must be seeded"
        assert customer is not None, "customer@hotel.com must be seeded"
        assert frontdesk is not None, "frontdesk@hotel.com must be seeded"
