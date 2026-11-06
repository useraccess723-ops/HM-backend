import json
import re
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db, engine
from app.models.entities import Tenant, User, RoomType, Room, Guest, Reservation, Payment, BookingChannel, HotelSettings, AuditLog
from app.core.security import hash_password
from app.core.auth import current_user, require_super_admin

router = APIRouter(prefix="/api/superadmin", tags=["Super Administrator"])

# ── Pydantic Request Models ─────────────────────────────────────────────────

class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=40)
    slug: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: str = "India"
    currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    subscription_plan: str = "Enterprise"
    max_rooms: int = Field(default=100, ge=1, le=5000)
    max_users: int = Field(default=50, ge=1, le=1000)
    admin_name: str = Field(min_length=2, max_length=160)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=128)

class TenantUpdateIn(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    subscription_plan: Optional[str] = None
    max_rooms: Optional[int] = None
    max_users: Optional[int] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None

class AdminCreateIn(BaseModel):
    tenant_id: int
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = "ADMIN"

class AdminResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)

class PlatformSettingsIn(BaseModel):
    platform_name: str = "StayFlow Hotel Management System"
    support_email: EmailStr = "support@stayflow.com"
    default_currency: str = "INR"
    default_timezone: str = "Asia/Kolkata"
    maintenance_mode: bool = False
    system_notice: str = ""

# In-memory platform settings store with safe defaults
_platform_settings = {
    "platform_name": "StayFlow Hotel Management Platform",
    "support_email": "support@stayflow.com",
    "default_currency": "INR",
    "default_timezone": "Asia/Kolkata",
    "maintenance_mode": False,
    "system_notice": "Platform is operating normally. All tenant nodes healthy.",
}

# ── 1. Super Admin Platform Dashboard ──────────────────────────────────────

@router.get("/dashboard")
def get_superadmin_dashboard(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    total_tenants = db.scalar(select(func.count(Tenant.id))) or 0
    active_tenants = db.scalar(select(func.count(Tenant.id)).where(Tenant.is_active == True, Tenant.status == "Active")) or 0
    total_rooms = db.scalar(select(func.count(Room.id))) or 0
    total_bookings = db.scalar(select(func.count(Reservation.id))) or 0
    total_revenue = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.status.in_(["Paid", "Completed"]))) or 0
    total_staff = db.scalar(select(func.count(User.id)).where(User.is_super_admin == False, User.is_active == True)) or 0

    recent_tenants_raw = db.scalars(select(Tenant).order_by(Tenant.id.desc()).limit(5)).all()
    recent_tenants = []
    for t in recent_tenants_raw:
        r_cnt = db.scalar(select(func.count(Room.id)).where(Room.tenant_id == t.id)) or 0
        u_cnt = db.scalar(select(func.count(User.id)).where(User.tenant_id == t.id)) or 0
        recent_tenants.append({
            "id": t.id,
            "name": t.name,
            "code": t.code,
            "slug": t.slug,
            "city": t.city or "—",
            "plan": t.subscription_plan,
            "status": t.status,
            "is_active": t.is_active,
            "rooms_count": r_cnt,
            "users_count": u_cnt,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {
        "metrics": {
            "total_tenants": total_tenants,
            "active_tenants": active_tenants,
            "total_rooms": total_rooms,
            "total_bookings": total_bookings,
            "total_revenue": float(total_revenue),
            "total_staff": total_staff,
        },
        "recent_tenants": recent_tenants,
        "system_health": {
            "api_status": "Healthy & Operational",
            "database_connection": "Connected (MySQL)",
            "channel_sync_engine": "Active (Real-time polling)",
            "active_sessions": total_staff + 1,
            "platform_version": "v2.5 Multi-Tenant",
        }
    }

# ── 2. Tenant Management Endpoints ─────────────────────────────────────────

@router.get("/tenants")
def list_tenants(
    search: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin)
):
    q = select(Tenant).order_by(Tenant.id.asc())
    if search:
        s = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Tenant.name).like(s), func.lower(Tenant.code).like(s), func.lower(Tenant.city).like(s)))
    if status_filter and status_filter.lower() != "all":
        q = q.where(Tenant.status == status_filter)

    tenants = db.scalars(q).all()
    results = []
    for t in tenants:
        rooms_cnt = db.scalar(select(func.count(Room.id)).where(Room.tenant_id == t.id)) or 0
        users_cnt = db.scalar(select(func.count(User.id)).where(User.tenant_id == t.id)) or 0
        res_cnt = db.scalar(select(func.count(Reservation.id)).where(Reservation.tenant_id == t.id)) or 0
        rev = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Reservation)
            .where(Reservation.tenant_id == t.id, Payment.status.in_(["Paid", "Completed"]))
        ) or 0

        # Load primary admin email
        primary_admin = db.scalar(select(User).where(User.tenant_id == t.id, User.role == "ADMIN").order_by(User.id.asc()).limit(1))

        results.append({
            "id": t.id,
            "name": t.name,
            "code": t.code,
            "slug": t.slug,
            "contact_email": t.contact_email,
            "contact_phone": t.contact_phone,
            "address": t.address,
            "city": t.city,
            "country": t.country,
            "currency": t.currency,
            "timezone": t.timezone,
            "subscription_plan": t.subscription_plan,
            "max_rooms": t.max_rooms,
            "max_users": t.max_users,
            "is_active": t.is_active,
            "status": t.status,
            "rooms_count": rooms_cnt,
            "users_count": users_cnt,
            "bookings_count": res_cnt,
            "revenue": float(rev),
            "admin_email": primary_admin.email if primary_admin else "—",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return results

@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreateIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    code_clean = body.code.strip().upper()
    name_clean = body.name.strip()
    slug_clean = body.slug.strip() if body.slug else re.sub(r'[^a-z0-9]+', '-', name_clean.lower()).strip('-')

    if db.scalar(select(Tenant.id).where(Tenant.code == code_clean)):
        raise HTTPException(status_code=409, detail=f"Tenant code '{code_clean}' already exists")
    if db.scalar(select(Tenant.id).where(Tenant.slug == slug_clean)):
        slug_clean = f"{slug_clean}-{code_clean.lower()}"

    admin_email_lower = body.admin_email.lower().strip()
    if db.scalar(select(User.id).where(User.email == admin_email_lower)):
        raise HTTPException(status_code=409, detail=f"User email '{admin_email_lower}' is already registered")

    # 1. Create Tenant
    tenant = Tenant(
        name=name_clean,
        code=code_clean,
        slug=slug_clean,
        contact_email=body.contact_email or admin_email_lower,
        contact_phone=body.contact_phone,
        address=body.address,
        city=body.city,
        country=body.country,
        currency=body.currency,
        timezone=body.timezone,
        subscription_plan=body.subscription_plan,
        max_rooms=body.max_rooms,
        max_users=body.max_users,
        is_active=True,
        status="Active",
        settings_json=json.dumps({
            "guest_portal_enabled": True,
            "qr_checkin_enabled": True,
            "online_channels_enabled": True,
        })
    )
    db.add(tenant)
    db.flush()

    # 2. Create Hotel Settings
    settings_obj = HotelSettings(
        tenant_id=tenant.id,
        hotel_name=tenant.name,
        currency=tenant.currency,
        timezone=tenant.timezone,
        check_in_time="14:00",
        check_out_time="11:00",
        gst_percent=12.0,
        cancellation_hours=24,
        no_show_charge="First night"
    )
    db.add(settings_obj)

    # 3. Create Primary Hotel Administrator
    admin_user = User(
        tenant_id=tenant.id,
        email=admin_email_lower,
        full_name=body.admin_name.strip(),
        password_hash=hash_password(body.admin_password),
        role="ADMIN",
        is_active=True,
        is_super_admin=False
    )
    db.add(admin_user)
    db.flush()

    # 4. Create Starter Room Types and Rooms for the new Hotel
    rt1 = RoomType(
        tenant_id=tenant.id,
        name="Deluxe Room",
        slug="deluxe-room",
        short_description=f"Standard Deluxe Room at {tenant.name}.",
        description="Comfortable modern hotel room with private bathroom, high-speed Wi-Fi, and city views.",
        base_price=3500.0,
        weekend_price=4200.0,
        max_adults=2,
        max_children=1,
        max_guests=2,
        max_occupancy=2,
        bed_type="King-size Bed",
        room_size_sqft=320,
        amenities='["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "In-room Safe", "Private Bathroom"]',
        status="Active"
    )
    rt2 = RoomType(
        tenant_id=tenant.id,
        name="Executive Suite",
        slug="executive-suite",
        short_description=f"Spacious luxury suite at {tenant.name}.",
        description="Spacious suite featuring separate living area, upgraded amenities, and luxury bath.",
        base_price=7500.0,
        weekend_price=8500.0,
        max_adults=3,
        max_children=2,
        max_guests=4,
        max_occupancy=4,
        bed_type="King & Twin Beds",
        room_size_sqft=600,
        amenities='["Free Wi-Fi", "Air Conditioning", "Living Room", "Bathtub", "Smart TV"]',
        status="Active"
    )
    db.add_all([rt1, rt2])
    db.flush()

    r101 = Room(tenant_id=tenant.id, number="101", floor=1, room_type_id=rt1.id, status="vac", description="Deluxe Room floor 1")
    r102 = Room(tenant_id=tenant.id, number="102", floor=1, room_type_id=rt1.id, status="vac", description="Deluxe Room floor 1")
    r201 = Room(tenant_id=tenant.id, number="201", floor=2, room_type_id=rt2.id, status="vac", description="Executive Suite floor 2")
    db.add_all([r101, r102, r201])

    db.commit()
    db.refresh(tenant)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "code": tenant.code,
        "slug": tenant.slug,
        "plan": tenant.subscription_plan,
        "status": tenant.status,
        "admin_email": admin_user.email,
        "message": f"Tenant '{tenant.name}' and administrator created successfully."
    }

@router.get("/tenants/{tenant_id}")
def get_tenant_detail(tenant_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    rooms_cnt = db.scalar(select(func.count(Room.id)).where(Room.tenant_id == t.id)) or 0
    users_cnt = db.scalar(select(func.count(User.id)).where(User.tenant_id == t.id)) or 0
    res_cnt = db.scalar(select(func.count(Reservation.id)).where(Reservation.tenant_id == t.id)) or 0
    admins = db.scalars(select(User).where(User.tenant_id == t.id)).all()
    settings_obj = db.scalar(select(HotelSettings).where(HotelSettings.tenant_id == t.id))

    return {
        "id": t.id,
        "name": t.name,
        "code": t.code,
        "slug": t.slug,
        "contact_email": t.contact_email,
        "contact_phone": t.contact_phone,
        "address": t.address,
        "city": t.city,
        "country": t.country,
        "currency": t.currency,
        "timezone": t.timezone,
        "subscription_plan": t.subscription_plan,
        "max_rooms": t.max_rooms,
        "max_users": t.max_users,
        "is_active": t.is_active,
        "status": t.status,
        "rooms_count": rooms_cnt,
        "users_count": users_cnt,
        "bookings_count": res_cnt,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "settings": {
            "check_in_time": settings_obj.check_in_time if settings_obj else "14:00",
            "check_out_time": settings_obj.check_out_time if settings_obj else "11:00",
            "gst_percent": float(settings_obj.gst_percent) if settings_obj else 12.0,
        },
        "administrators": [
            {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active}
            for u in admins
        ]
    }

@router.patch("/tenants/{tenant_id}")
def update_tenant(tenant_id: int, body: TenantUpdateIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    for field, val in body.model_dump(exclude_unset=True).items():
        if val is not None:
            setattr(t, field, val)
    
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    return {
        "id": t.id,
        "name": t.name,
        "code": t.code,
        "status": t.status,
        "is_active": t.is_active,
        "subscription_plan": t.subscription_plan,
        "message": f"Tenant '{t.name}' updated successfully."
    }

@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: int, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    if tenant_id == 1:
        raise HTTPException(status_code=400, detail="Cannot delete the primary platform tenant")
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    t.status = "Suspended"
    t.is_active = False
    db.commit()
    return {"message": f"Tenant '{t.name}' has been suspended/deactivated", "id": tenant_id}

# ── 3. Tenant Administrators Management ────────────────────────────────────

@router.get("/administrators")
def list_tenant_administrators(
    tenant_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_super_admin)
):
    q = select(User).options(joinedload(User.tenant)).where(User.is_super_admin == False).order_by(User.tenant_id.asc(), User.id.asc())
    if tenant_id:
        q = q.where(User.tenant_id == tenant_id)
    
    users = db.scalars(q).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "tenant_id": u.tenant_id,
            "tenant_name": u.tenant.name if u.tenant else "—",
            "tenant_code": u.tenant.code if u.tenant else "—",
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]

@router.post("/administrators", status_code=201)
def create_tenant_administrator(body: AdminCreateIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    tenant = db.get(Tenant, body.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Target tenant does not exist")
    
    email_clean = body.email.lower().strip()
    if db.scalar(select(User.id).where(User.email == email_clean)):
        raise HTTPException(status_code=409, detail=f"Email '{email_clean}' is already registered")
    
    new_user = User(
        tenant_id=tenant.id,
        email=email_clean,
        full_name=body.full_name.strip(),
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
        is_super_admin=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "id": new_user.id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "message": f"Administrator created for {tenant.name}"
    }

@router.patch("/administrators/{admin_id}/status")
def toggle_administrator_status(admin_id: int, body: dict, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u = db.get(User, admin_id)
    if not u or u.is_super_admin:
        raise HTTPException(status_code=404, detail="Administrator not found")
    
    if "is_active" in body:
        u.is_active = bool(body["is_active"])
    db.commit()
    return {"id": u.id, "email": u.email, "is_active": u.is_active}

@router.post("/administrators/{admin_id}/reset-password")
def reset_administrator_password(admin_id: int, body: AdminResetPasswordIn, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    u = db.get(User, admin_id)
    if not u or u.is_super_admin:
        raise HTTPException(status_code=404, detail="Administrator not found")
    
    u.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": f"Password reset successfully for {u.email}", "id": u.id}

# ── 4. Tenant Configurations Matrix ────────────────────────────────────────

@router.get("/configurations")
def get_tenant_configurations(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    tenants = db.scalars(select(Tenant).order_by(Tenant.id.asc())).all()
    configs = []
    for t in tenants:
        settings_dict = {}
        if t.settings_json:
            try:
                settings_dict = json.loads(t.settings_json)
            except Exception:
                settings_dict = {}
        
        channels_cnt = db.scalar(select(func.count(BookingChannel.id)).where(BookingChannel.tenant_id == t.id, BookingChannel.enabled == True)) or 0
        rooms_cnt = db.scalar(select(func.count(Room.id)).where(Room.tenant_id == t.id)) or 0

        configs.append({
            "tenant_id": t.id,
            "tenant_name": t.name,
            "tenant_code": t.code,
            "plan": t.subscription_plan,
            "max_rooms": t.max_rooms,
            "current_rooms": rooms_cnt,
            "max_users": t.max_users,
            "active_channels_count": channels_cnt,
            "guest_portal": settings_dict.get("guest_portal_enabled", True),
            "qr_checkin": settings_dict.get("qr_checkin_enabled", True),
            "ota_sync": settings_dict.get("online_channels_enabled", True),
            "custom_domain": settings_dict.get("custom_domain", ""),
        })
    return configs

@router.patch("/configurations/{tenant_id}")
def update_tenant_configuration(tenant_id: int, body: dict, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    current_conf = {}
    if t.settings_json:
        try:
            current_conf = json.loads(t.settings_json)
        except Exception:
            current_conf = {}
    
    for k, v in body.items():
        if k in {"max_rooms", "max_users"}:
            setattr(t, k, int(v))
        else:
            current_conf[k] = v
    
    t.settings_json = json.dumps(current_conf)
    db.commit()
    return {"tenant_id": t.id, "message": f"Configuration updated for {t.name}", "config": current_conf}

# ── 5. Platform Settings & Monitoring ──────────────────────────────────────

@router.get("/settings")
def get_platform_settings(admin: User = Depends(require_super_admin)):
    return _platform_settings

@router.patch("/settings")
def update_platform_settings(body: PlatformSettingsIn, admin: User = Depends(require_super_admin)):
    global _platform_settings
    _platform_settings.update(body.model_dump())
    return {"message": "Platform settings updated successfully", "settings": _platform_settings}

@router.get("/monitoring")
def get_platform_monitoring(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    pool = engine.pool
    total_logs = db.scalar(select(func.count(AuditLog.id))) or 0
    total_channels = db.scalar(select(func.count(BookingChannel.id))) or 0
    active_channels = db.scalar(select(func.count(BookingChannel.id)).where(BookingChannel.enabled == True)) or 0
    total_tenants = db.scalar(select(func.count(Tenant.id))) or 0

    recent_logs = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(10)).all()

    return {
        "status": "Healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_pool": {
            "pool_size": pool.size() if hasattr(pool, "size") else 5,
            "checked_in": pool.checkedin() if hasattr(pool, "checkedin") else 0,
            "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else 0,
            "overflow": pool.overflow() if hasattr(pool, "overflow") else 0,
        },
        "network": {
            "total_tenants": total_tenants,
            "total_channels": total_channels,
            "active_channels": active_channels,
            "audit_trail_events": total_logs,
        },
        "recent_audit_events": [
            {
                "id": l.id,
                "actor": l.actor_email,
                "action": l.action,
                "entity": l.entity_type,
                "tenant_id": l.tenant_id,
                "time": l.created_at.isoformat() if l.created_at else None
            }
            for l in recent_logs
        ]
    }
