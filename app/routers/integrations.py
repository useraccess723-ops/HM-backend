"""Dedicated StayFlow AI Receptionist Integration Router.

Provides:
1. Hotel Administration Endpoints (Staff JWT authenticated, strictly tenant-scoped)
   - Connection lifecycle (connect, disconnect, rotate-key, toggle, test-connection)
   - Sanitize activity logs
2. Machine-to-Machine Endpoints (Service Key authenticated via X-Integration-Key)
   - Chat / Q&A knowledge lookups
   - Room definitions & date-range availability checks
   - Concurrency-safe, 2-phase idempotent booking creation
   - Caller verification challenge & OTP verification (keyed HMAC, anti-enumeration)
   - Verified vs Unverified booking retrieval
   - Staff escalation / guest service requests
"""
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.entities import (
    Tenant, User, RoomType, Room, Guest, Reservation,
    HotelSettings, OperationalRecord,
    TenantIntegration, IntegrationLog, IntegrationIdempotencyRecord
)
from app.core.auth import current_user, get_tenant_id
from app.services.integration_crypto import (
    generate_service_key, hash_key, mask_key, encrypt_secret, decrypt_secret
)
from app.services.room_allocation_service import (
    allocate_and_lock_room, get_tenant_availability
)
from app.services.verification_service import (
    request_caller_verification, verify_caller_otp, validate_verification_token
)

logger = logging.getLogger("stayflow.integrations")

router = APIRouter(prefix="/api/integrations/ai-receptionist", tags=["AI Receptionist Integration"])

INTEGRATION_TYPE = "ai_receptionist"
DEFAULT_SCOPES = "knowledge:read,rooms:read,reservations:read,reservations:create,escalations:create"


# ── Dependency: Staff RBAC (ADMIN or GENERAL_MANAGER) ─────────────────────────

def require_integration_admin(
    user: User = Depends(current_user)
) -> User:
    """Requires ADMIN, SUPER_ADMIN, or GENERAL_MANAGER role."""
    role = (user.role or "").upper().strip()
    if user.is_super_admin or role in ("ADMIN", "SUPER_ADMIN", "ADMINISTRATOR", "GENERAL_MANAGER"):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrative permissions required to manage integrations."
    )


def require_admin_strictly(
    user: User = Depends(current_user)
) -> User:
    """Strictly requires ADMIN or SUPER_ADMIN role (e.g. for key rotation)."""
    role = (user.role or "").upper().strip()
    if user.is_super_admin or role in ("ADMIN", "SUPER_ADMIN", "ADMINISTRATOR"):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrator privilege required for credential rotation."
    )


# ── Dependency: Machine-to-Machine Integration Key Auth ────────────────────────

def get_integration_context(required_scope: Optional[str] = None):
    """
    Validates X-Integration-Key header against active tenant integrations.
    Tenant isolation is resolved strictly through the database record mapped to the SHA-256 key hash.
    """
    def dependency(
        request: Request,
        x_integration_key: Optional[str] = Header(None, alias="X-Integration-Key"),
        db: Session = Depends(get_db)
    ) -> Tuple[TenantIntegration, Tenant]:
        if not x_integration_key or not x_integration_key.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Integration-Key authentication header."
            )
        
        raw_key = x_integration_key.strip()
        k_hash = hash_key(raw_key)

        integration = db.scalar(
            select(TenantIntegration)
            .options(joinedload(TenantIntegration.tenant))
            .where(
                TenantIntegration.key_hash == k_hash,
                TenantIntegration.integration_type == INTEGRATION_TYPE
            )
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid integration credentials."
            )

        if not integration.is_enabled or integration.status != "connected":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Integration is disabled or disconnected."
            )

        tenant = integration.tenant
        if not tenant or not tenant.is_active or tenant.status == "Suspended":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hotel property account is suspended or inactive."
            )

        if required_scope:
            scopes = [s.strip() for s in (integration.scopes or "").split(",") if s.strip()]
            if required_scope not in scopes and "*" not in scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Integration credentials lack required scope: {required_scope}."
                )

        # Update last_activity_at timestamp asynchronously
        try:
            integration.last_activity_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()

        return integration, tenant

    return dependency


def to_iso(d: Any) -> Optional[str]:
    """Safely converts date or datetime to ISO string without direct method indexing."""
    if d is None:
        return None
    iso_fn = getattr(d, "isoformat", None)
    if callable(iso_fn):
        try:
            return str(iso_fn())
        except Exception:
            pass
    return str(d)

def log_integration_event(
    db: Session,
    tenant_id: int,
    integration_id: int,
    event_type: str,
    status_str: str = "success",
    direction: str = "inbound",
    status_code: Optional[int] = 200,
    payload_summary: Optional[str] = None,
    error_details: Optional[str] = None,
    duration_ms: Optional[int] = None,
    ip_address: Optional[str] = None
):
    """Safely records an activity log entry without raising exceptions."""
    try:
        log_entry = IntegrationLog(
            tenant_id=tenant_id,
            integration_id=integration_id,
            direction=direction,
            event_type=event_type,
            status=status_str,
            status_code=status_code,
            payload_summary=(payload_summary or "")[:250],
            error_details=error_details,
            duration_ms=duration_ms,
            ip_address=ip_address
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to record integration log: {e}")


# ── Pydantic Request & Response Schemas ────────────────────────────────────────

class ConnectIntegrationIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    api_base_url: Optional[str] = None
    webhook_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None

class UpdateIntegrationConfigIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    api_base_url: Optional[str] = None
    webhook_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    is_enabled: Optional[bool] = None

class ToggleIntegrationIn(BaseModel):
    enabled: bool

class ChatQueryIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    guest_phone: Optional[str] = None
    session_id: Optional[str] = None

class BookingCreateIn(BaseModel):
    guest_name: str = Field(min_length=2, max_length=120)
    guest_phone: str = Field(min_length=7, max_length=30)
    guest_email: Optional[EmailStr] = None
    check_in: date
    check_out: date
    room_type_id: int
    room_id: Optional[int] = None
    num_guests: int = Field(default=1, ge=1, le=10)
    external_intent_id: Optional[str] = None
    special_requests: Optional[str] = None

class RequestVerificationIn(BaseModel):
    phone_number: str = Field(min_length=7, max_length=30)

class VerifyOtpIn(BaseModel):
    otp_code: str = Field(min_length=4, max_length=10)

class ServiceRequestIn(BaseModel):
    guest_name: str = Field(min_length=2, max_length=120)
    caller_phone: Optional[str] = None
    room_number: Optional[str] = None
    category: str = Field(default="front_desk", description="front_desk, room_service, maintenance, complaint")
    priority: str = Field(default="medium", description="low, medium, high, urgent")
    description: str = Field(min_length=5, max_length=1000)

class LogActivityIn(BaseModel):
    event_type: str = Field(min_length=2, max_length=80)
    status: str = Field(default="success")
    summary: str = Field(max_length=250)
    details: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# 1. HOTEL ADMINISTRATION ENDPOINTS (Staff JWT Protected)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("", summary="Get AI Receptionist Integration Status")
def get_integration_status(
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Returns current connection status, settings, masked key, and metrics for the hotel."""
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    tenant = db.scalar(select(Tenant).where(Tenant.id == tid))
    default_name = f"{tenant.name} - AI Receptionist" if tenant else "AI Receptionist Voice Agent"

    if not integration:
        return {
            "name": default_name,
            "description": "Connect your external AI Receptionist voice agent to live StayFlow reservation engine.",
            "api_base_url": "",
            "auth_method": "Header: X-Integration-Key (SHA-256 M2M Key)",
            "status": "disconnected",
            "is_enabled": False,
            "masked_key": None,
            "key_prefix": None,
            "key_last4": None,
            "webhook_url": None,
            "scopes": DEFAULT_SCOPES.split(","),
            "last_connected_at": None,
            "last_activity_at": None,
            "last_error_message": None,
            "total_logs": 0
        }

    cfg = json.loads(integration.config_json or "{}")
    name = cfg.get("name") or cfg.get("label") or default_name
    description = cfg.get("description") or "Dedicated AI Voice Receptionist Connector"
    api_base_url = cfg.get("api_base_url") or ""

    total_logs = db.scalar(
        select(func.count(IntegrationLog.id)).where(IntegrationLog.tenant_id == tid)
    ) or 0

    return {
        "id": integration.id,
        "name": name,
        "description": description,
        "api_base_url": api_base_url,
        "auth_method": "Header: X-Integration-Key (SHA-256 M2M Key)",
        "status": integration.status,
        "is_enabled": integration.is_enabled,
        "masked_key": mask_key(integration.key_prefix, integration.key_last4) if integration.key_hash else None,
        "key_prefix": integration.key_prefix,
        "key_last4": integration.key_last4,
        "webhook_url": integration.webhook_url,
        "scopes": [s.strip() for s in (integration.scopes or "").split(",") if s.strip()],
        "last_connected_at": to_iso(integration.last_connected_at),
        "last_activity_at": to_iso(integration.last_activity_at),
        "last_error_message": integration.last_error_message,
        "total_logs": total_logs
    }


@router.post("/connect", summary="Connect AI Receptionist & Generate Service Key")
def connect_integration(
    payload: ConnectIntegrationIn,
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """
    Connects the AI Receptionist integration and issues a high-entropy 72-character API key.
    The raw plaintext key is returned ONCE and never stored in the database.
    """
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    now = datetime.now(timezone.utc)
    raw_key, k_hash, prefix, last4 = generate_service_key()

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    cfg = payload.config or {}
    if payload.name:
        cfg["name"] = payload.name
    if payload.description:
        cfg["description"] = payload.description
    if payload.api_base_url:
        cfg["api_base_url"] = payload.api_base_url

    selected_scopes = DEFAULT_SCOPES
    if payload.scopes:
        clean_scopes = [s.strip() for s in payload.scopes if s.strip()]
        if clean_scopes:
            selected_scopes = ",".join(clean_scopes)

    if not integration:
        integration = TenantIntegration(
            tenant_id=tid,
            integration_type=INTEGRATION_TYPE,
            status="connected",
            is_enabled=True,
            key_hash=k_hash,
            key_prefix=prefix,
            key_last4=last4,
            webhook_url=payload.webhook_url,
            scopes=selected_scopes,
            config_json=json.dumps(cfg),
            last_connected_at=now,
            last_activity_at=now
        )
        db.add(integration)
    else:
        integration.status = "connected"
        integration.is_enabled = True
        integration.key_hash = k_hash
        integration.key_prefix = prefix
        integration.key_last4 = last4
        if payload.scopes:
            integration.scopes = selected_scopes
        if payload.webhook_url is not None:
            integration.webhook_url = payload.webhook_url
        integration.config_json = json.dumps(cfg)
        integration.last_connected_at = now
        integration.last_error_message = None

    db.commit()
    db.refresh(integration)

    log_integration_event(
        db=db,
        tenant_id=tid,
        integration_id=integration.id,
        event_type="connect",
        status_str="success",
        payload_summary=f"Connected by {user.email}. Key issued: {prefix}...{last4}"
    )

    return {
        "status": "connected",
        "service_key": raw_key,
        "masked_key": mask_key(prefix, last4),
        "key_prefix": prefix,
        "key_last4": last4,
        "message": "AI Receptionist connected successfully. Copy your API service key now; it will not be displayed again."
    }


@router.post("/rotate-key", summary="Rotate AI Receptionist Service Key")
def rotate_integration_key(
    request: Request,
    user: User = Depends(require_admin_strictly),
    db: Session = Depends(get_db)
):
    """
    Rotates the service key for the AI Receptionist.
    Immediately invalidates the prior key and returns the new 72-character key.
    """
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    if not integration or integration.status != "connected":
        raise HTTPException(status_code=404, detail="Active integration not found to rotate.")

    raw_key, k_hash, prefix, last4 = generate_service_key()

    integration.key_hash = k_hash
    integration.key_prefix = prefix
    integration.key_last4 = last4
    integration.updated_at = datetime.now(timezone.utc)
    db.commit()

    log_integration_event(
        db=db,
        tenant_id=tid,
        integration_id=integration.id,
        event_type="rotate_key",
        status_str="success",
        payload_summary=f"Key rotated by {user.email}. New key: {prefix}...{last4}"
    )

    return {
        "status": "connected",
        "service_key": raw_key,
        "masked_key": mask_key(prefix, last4),
        "key_prefix": prefix,
        "key_last4": last4,
        "message": "Key rotated successfully. Update your AI Receptionist application with the new key."
    }


@router.post("/disconnect", summary="Disconnect AI Receptionist")
def disconnect_integration(
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Disconnects the AI Receptionist and revokes active credentials immediately."""
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    if not integration:
        return {"status": "disconnected", "message": "Integration is already disconnected."}

    integration.status = "disconnected"
    integration.is_enabled = False
    integration.key_hash = None
    integration.key_prefix = None
    integration.key_last4 = None
    integration.updated_at = datetime.now(timezone.utc)
    db.commit()

    log_integration_event(
        db=db,
        tenant_id=tid,
        integration_id=integration.id,
        event_type="disconnect",
        status_str="success",
        payload_summary=f"Disconnected by {user.email}"
    )

    return {"status": "disconnected", "message": "AI Receptionist disconnected successfully."}


@router.post("/toggle", summary="Enable / Disable Integration")
def toggle_integration(
    payload: ToggleIntegrationIn,
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Temporarily enables or disables inbound AI Receptionist calls without revoking credentials."""
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found.")

    integration.is_enabled = payload.enabled
    db.commit()

    return {
        "status": integration.status,
        "is_enabled": integration.is_enabled,
        "message": f"Integration {'enabled' if payload.enabled else 'paused'} successfully."
    }


@router.put("/config", summary="Update Integration Configuration")
def update_integration_config(
    payload: UpdateIntegrationConfigIn,
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Updates display name, description, API base URL, webhook, and scopes without key revocation."""
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration record not found.")

    cfg = json.loads(integration.config_json or "{}")
    if payload.name is not None:
        cfg["name"] = payload.name
    if payload.description is not None:
        cfg["description"] = payload.description
    if payload.api_base_url is not None:
        cfg["api_base_url"] = payload.api_base_url
    integration.config_json = json.dumps(cfg)

    if payload.webhook_url is not None:
        integration.webhook_url = payload.webhook_url
    if payload.scopes is not None:
        clean_scopes = [s.strip() for s in payload.scopes if s.strip()]
        if clean_scopes:
            integration.scopes = ",".join(clean_scopes)
    if payload.is_enabled is not None:
        integration.is_enabled = payload.is_enabled

    integration.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(integration)

    log_integration_event(
        db=db,
        tenant_id=tid,
        integration_id=integration.id,
        event_type="config_update",
        status_str="success",
        payload_summary="Integration configuration updated successfully."
    )

    return {"status": "ok", "message": "Integration configuration updated successfully."}


@router.post("/test-connection", summary="Test Connection Health & Latency")
def test_connection(
    request: Request,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Performs a self-check on the integration state, verifying tenant isolation and database readiness."""
    start_time = time.perf_counter()
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tid,
            TenantIntegration.integration_type == INTEGRATION_TYPE
        )
    )

    if not integration or integration.status != "connected":
        return {
            "status": "error",
            "message": "AI Receptionist is not connected for this hotel.",
            "latency_ms": int((time.perf_counter() - start_time) * 1000)
        }

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    log_integration_event(
        db=db,
        tenant_id=tid,
        integration_id=integration.id,
        event_type="ping",
        status_str="success",
        duration_ms=duration_ms,
        payload_summary="Test connection handshake successful."
    )

    return {
        "status": "ok",
        "integration_id": integration.id,
        "latency_ms": duration_ms,
        "message": "Connection active. StayFlow integration endpoints are ready to receive AI Receptionist calls."
    }


@router.get("/logs", summary="Get Integration Activity Logs")
def get_integration_logs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    user: User = Depends(require_integration_admin),
    db: Session = Depends(get_db)
):
    """Retrieves sanitized activity logs strictly scoped to the authenticated tenant."""
    tid = get_tenant_id(request, user)
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant context required.")

    query = select(IntegrationLog).where(IntegrationLog.tenant_id == tid)
    if event_type:
        query = query.where(IntegrationLog.event_type == event_type)
    if status_filter:
        if status_filter == "success":
            query = query.where(IntegrationLog.status == "success")
        elif status_filter in ("failed", "error"):
            query = query.where(IntegrationLog.status.in_(["error", "failed"]))
    if category:
        if category == "connection":
            query = query.where(IntegrationLog.event_type.in_(["connect", "disconnect", "rotate_key", "toggle", "ping", "config_update"]))
        elif category == "booking":
            query = query.where(IntegrationLog.event_type.in_(["booking_create", "check_availability"]))
        elif category == "auth":
            query = query.where(IntegrationLog.event_type.in_(["auth_failure", "verify_caller", "verify_otp"]))
        elif category == "escalation":
            query = query.where(IntegrationLog.event_type == "escalation")

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    logs = db.scalars(query.order_by(desc(IntegrationLog.created_at)).offset(offset).limit(limit)).all()

    items = []
    for l in logs:
        items.append({
            "id": l.id,
            "direction": l.direction,
            "event_type": l.event_type,
            "status": l.status,
            "status_code": l.status_code,
            "payload_summary": l.payload_summary,
            "error_details": l.error_details,
            "duration_ms": l.duration_ms,
            "created_at": to_iso(l.created_at)
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": items
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. MACHINE-TO-MACHINE (M2M) ENDPOINTS FOR EXTERNAL AI RECEPTIONIST
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/chat", summary="AI Knowledge Inquiry & Hotel FAQs")
def integration_chat(
    payload: ChatQueryIn,
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("knowledge:read")),
    db: Session = Depends(get_db)
):
    """
    Hotel Knowledge inquiry for guest calls.
    Returns property rules, check-in policies, amenities, and dining hours strictly for this tenant.
    """
    integration, tenant = context
    start_time = time.perf_counter()

    settings_row = db.scalar(select(HotelSettings).where(HotelSettings.tenant_id == tenant.id))
    room_types = db.scalars(select(RoomType).where(RoomType.tenant_id == tenant.id)).all()

    rt_summary = [f"{rt.name} (Capacity: {getattr(rt, 'max_guests', 2)} guests)" for rt in room_types]

    info = {
        "hotel_name": tenant.name,
        "city": tenant.city,
        "address": tenant.address,
        "contact_phone": tenant.contact_phone,
        "contact_email": tenant.contact_email,
        "currency": tenant.currency,
        "check_in_time": settings_row.check_in_time if settings_row and hasattr(settings_row, "check_in_time") else "14:00",
        "check_out_time": settings_row.check_out_time if settings_row and hasattr(settings_row, "check_out_time") else "11:00",
        "available_room_types": rt_summary
    }

    answer = (
        f"Welcome to {tenant.name}. Our check-in time is {info['check_in_time']} and check-out is {info['check_out_time']}. "
        f"We offer the following room options: {', '.join(rt_summary) if rt_summary else 'Standard Rooms'}. "
        f"Please let me know your desired check-in dates and number of guests to check live availability."
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="chat",
        status_str="success",
        duration_ms=duration_ms,
        payload_summary=f"Q: {payload.query[:60]}"
    )

    return {
        "answer": answer,
        "hotel_info": info,
        "session_id": payload.session_id
    }


@router.get("/rooms", summary="List Hotel Room Types & Configurations")
def list_rooms(
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("rooms:read")),
    db: Session = Depends(get_db)
):
    """Returns room types and standard occupancies for the authenticated hotel."""
    integration, tenant = context
    room_types = db.scalars(select(RoomType).where(RoomType.tenant_id == tenant.id)).all()

    results = []
    for rt in room_types:
        total_rooms = db.scalar(
            select(func.count(Room.id)).where(
                Room.tenant_id == tenant.id,
                Room.room_type_id == rt.id
            )
        ) or 0

        results.append({
            "id": rt.id,
            "name": rt.name,
            "description": getattr(rt, "short_description", "") or getattr(rt, "name", ""),
            "max_occupancy": getattr(rt, "max_guests", 2),
            "bed_type": getattr(rt, "bed_type", "King-size Bed"),
            "base_price": float(rt.weekend_price or 0.0) if hasattr(rt, "weekend_price") and rt.weekend_price else 0.0,
            "total_inventory": total_rooms
        })

    return {
        "tenant_id": tenant.id,
        "hotel_name": tenant.name,
        "room_types": results
    }


@router.get("/availability", summary="Check Date-Range Room Availability")
def check_availability(
    check_in: date = Query(..., description="Target check-in date (YYYY-MM-DD)"),
    check_out: date = Query(..., description="Target check-out date (YYYY-MM-DD)"),
    room_type_id: Optional[int] = Query(None, description="Optional specific room type ID"),
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("rooms:read")),
    db: Session = Depends(get_db)
):
    """
    Checks real date-range availability against reservations.
    A vacant room status alone is NOT treated as confirmation of availability.
    """
    integration, tenant = context

    if check_out <= check_in:
        raise HTTPException(
            status_code=400,
            detail="Check-out date must be after check-in date."
        )

    avail = get_tenant_availability(
        db=db,
        tenant_id=tenant.id,
        check_in=check_in,
        check_out=check_out,
        room_type_id=room_type_id
    )

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="check_availability",
        status_str="success",
        payload_summary=f"Dates: {check_in} to {check_out}. Results: {len(avail)} types checked."
    )

    return {
        "check_in": to_iso(check_in),
        "check_out": to_iso(check_out),
        "availability": avail
    }


@router.post("/bookings", status_code=status.HTTP_201_CREATED, summary="Create Reservation (Concurrency-Safe & Idempotent)")
def create_integration_booking(
    payload: BookingCreateIn,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("reservations:create")),
    db: Session = Depends(get_db)
):
    """
    Dedicated AI Receptionist booking creation endpoint.
    Guarantees:
    1. Row-level concurrency locking via allocate_and_lock_room() (prevents double-booking).
    2. 2-phase idempotency storage (prevents duplicate charging/reservations).
    3. Multi-year duplicate prevention via channel_ref = ext:{integration_id}:{external_intent_id}.
    """
    integration, tenant = context

    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required for reservation creation."
        )

    ikey = idempotency_key.strip()
    if payload.check_out <= payload.check_in:
        raise HTTPException(status_code=400, detail="Check-out date must be after check-in date.")

    # 1. Payload Hash for Idempotency
    raw_payload_str = json.dumps(payload.model_dump(), default=str, sort_keys=True)
    payload_hash = hashlib.sha256(raw_payload_str.encode("utf-8")).hexdigest()

    # 2. Check Existing Idempotency Record
    existing_rec = db.scalar(
        select(IntegrationIdempotencyRecord).where(
            IntegrationIdempotencyRecord.tenant_id == tenant.id,
            IntegrationIdempotencyRecord.integration_id == integration.id,
            IntegrationIdempotencyRecord.idempotency_key == ikey
        )
    )

    if existing_rec:
        if existing_rec.status == "COMPLETED" and existing_rec.response_body:
            if existing_rec.payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with different request payload."
                )
            return json.loads(existing_rec.response_body)
        elif existing_rec.status == "PROCESSING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A concurrent reservation request with this idempotency key is already in progress."
            )

    # 3. Multi-Year Duplicate Check via channel_ref
    if payload.external_intent_id:
        expected_channel_ref = f"ext:{integration.id}:{payload.external_intent_id}"
        prior_res = db.scalar(
            select(Reservation).where(
                Reservation.tenant_id == tenant.id,
                Reservation.channel_ref == expected_channel_ref
            )
        )
        if prior_res:
            res_dict = {
                "id": prior_res.id,
                "reference": prior_res.reference,
                "status": prior_res.status,
                "room_id": prior_res.room_id,
                "check_in": to_iso(prior_res.check_in),
                "check_out": to_iso(prior_res.check_out),
                "total_amount": float(prior_res.total_amount or 0.0),
                "is_cached": True
            }
            return res_dict

    # 4. Insert PROCESSING Idempotency Record in a savepoint
    idemp_rec = IntegrationIdempotencyRecord(
        tenant_id=tenant.id,
        integration_id=integration.id,
        idempotency_key=ikey,
        payload_hash=payload_hash,
        status="PROCESSING"
    )
    try:
        with db.begin_nested():
            db.add(idemp_rec)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent request already registered with this Idempotency-Key."
        )

    # 5. Lock and Allocate Available Room
    room = allocate_and_lock_room(
        db=db,
        tenant_id=tenant.id,
        check_in=payload.check_in,
        check_out=payload.check_out,
        room_id=payload.room_id,
        room_type_id=payload.room_type_id
    )

    if not room:
        idemp_rec.status = "FAILED"
        db.commit()
        log_integration_event(
            db=db,
            tenant_id=tenant.id,
            integration_id=integration.id,
            event_type="create_booking",
            status_str="conflict",
            status_code=409,
            payload_summary=f"No available room for room_type #{payload.room_type_id} between {payload.check_in} and {payload.check_out}"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No operational room is available for the selected room type and dates."
        )

    # 6. Find or Create Guest
    clean_phone = "".join(ch for ch in payload.guest_phone if ch.isdigit())
    guest = db.scalar(
        select(Guest).where(
            Guest.tenant_id == tenant.id,
            Guest.phone.like(f"%{clean_phone[-10:]}%")
        )
    )
    if not guest:
        guest = Guest(
            tenant_id=tenant.id,
            full_name=payload.guest_name,
            phone=payload.guest_phone,
            email=payload.guest_email or "",
            tier="Standard"
        )
        db.add(guest)
        db.flush()

    # 7. Pricing calculation
    nights = max(1, (payload.check_out - payload.check_in).days)
    rt = db.scalar(select(RoomType).where(RoomType.id == room.room_type_id))
    rate = Decimal(str(rt.weekend_price or 1500.00)) if rt and getattr(rt, "weekend_price", None) else Decimal("1500.00")
    total_amount = rate * nights

    # 8. Unique Reference & Create Reservation
    rand_suffix = secrets.token_hex(4).upper()
    booking_ref = f"BK-AI-{tenant.id}-{rand_suffix}"
    durable_channel_ref = f"ext:{integration.id}:{payload.external_intent_id or ikey}"

    reservation = Reservation(
        tenant_id=tenant.id,
        reference=booking_ref,
        guest_id=guest.id,
        room_id=room.id,
        source="AI Receptionist",
        channel_ref=durable_channel_ref,
        check_in=payload.check_in,
        check_out=payload.check_out,
        status="Confirmed",
        total_amount=total_amount,
        num_guests=payload.num_guests
    )
    db.add(reservation)
    db.flush()

    # 9. Complete Idempotency Record
    guest_display_name = getattr(guest, "full_name", None) or getattr(guest, "name", "")
    res_dict = {
        "id": reservation.id,
        "reference": reservation.reference,
        "guest_id": guest.id,
        "guest_name": guest_display_name,
        "room_id": room.id,
        "room_number": room.number,
        "room_type_id": room.room_type_id,
        "check_in": to_iso(reservation.check_in),
        "check_out": to_iso(reservation.check_out),
        "nights": nights,
        "total_amount": float(reservation.total_amount),
        "status": reservation.status,
        "source": reservation.source,
        "channel_ref": reservation.channel_ref
    }

    idemp_rec.status = "COMPLETED"
    idemp_rec.reservation_id = reservation.id
    idemp_rec.response_body = json.dumps(res_dict)
    idemp_rec.status_code = 201

    # Atomic Commit: commits the reservation and idempotency record together
    db.commit()

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="create_booking",
        status_str="success",
        status_code=201,
        payload_summary=f"Booking created: {booking_ref} (Room #{room.number}, Nights: {nights})"
    )

    return res_dict


@router.get("/bookings/{ref}", summary="Retrieve Booking by Reference (Caller Verified or Sanitized)")
def get_integration_booking(
    ref: str,
    x_verification_token: Optional[str] = Header(None, alias="X-Verification-Token"),
    verification_token: Optional[str] = Query(None),
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("reservations:read")),
    db: Session = Depends(get_db)
):
    """
    Retrieves booking details.
    Caller Verification Rule:
    - If verified with valid ephemeral token: returns full booking & guest details.
    - If unverified: returns strictly sanitized status without leaking PII or exact dates.
    """
    integration, tenant = context
    token = x_verification_token or verification_token

    res = db.scalar(
        select(Reservation)
        .options(joinedload(Reservation.guest), joinedload(Reservation.room))
        .where(
            Reservation.tenant_id == tenant.id,
            Reservation.reference == ref.strip().upper()
        )
    )

    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found.")

    is_verified = False
    if token:
        is_verified = validate_verification_token(db, tenant.id, ref, token)

    if is_verified:
        return {
            "is_caller_verified": True,
            "reference": res.reference,
            "status": res.status,
            "guest": {
                "name": getattr(res.guest, "full_name", None) or getattr(res.guest, "name", "Unknown") if res.guest else "Unknown",
                "phone": res.guest.phone if res.guest else "",
                "email": res.guest.email if res.guest else ""
            },
            "room_number": res.room.number if res.room else "",
            "check_in": to_iso(res.check_in),
            "check_out": to_iso(res.check_out),
            "total_amount": float(res.total_amount or 0.0),
            "created_at": to_iso(res.created_at)
        }

    # Sanitized unverified response
    guest_name = (getattr(res.guest, "full_name", None) or getattr(res.guest, "name", "Guest")) if res.guest else "Guest"
    masked_name = f"{guest_name[:1]}*** {guest_name.split()[-1][:1]}***" if " " in guest_name else f"{guest_name[:1]}***"

    return {
        "is_caller_verified": False,
        "reference": res.reference,
        "status": res.status,
        "guest_name_masked": masked_name,
        "message": "Caller is unverified. To receive reservation dates, room details, or make modifications, complete OTP caller verification."
    }


@router.post("/bookings/{ref}/request-verification", summary="Request Caller Verification Challenge")
def request_verification(
    ref: str,
    payload: RequestVerificationIn,
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("reservations:read")),
    db: Session = Depends(get_db)
):
    """
    Issues an OTP verification challenge to the registered guest phone.
    Anti-enumeration: Uniform generic response returned whether or not details match.
    """
    integration, tenant = context

    result = request_caller_verification(
        db=db,
        tenant_id=tenant.id,
        booking_ref=ref,
        phone_number=payload.phone_number
    )

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="request_verification",
        status_str="success",
        payload_summary=f"Verification challenge requested for Ref {ref}"
    )

    return result


@router.post("/bookings/{ref}/verify-otp", summary="Verify OTP & Obtain Caller Token")
def verify_otp(
    ref: str,
    payload: VerifyOtpIn,
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("reservations:read")),
    db: Session = Depends(get_db)
):
    """Verifies OTP code and returns an ephemeral verification token."""
    integration, tenant = context

    is_valid, token, message = verify_caller_otp(
        db=db,
        tenant_id=tenant.id,
        booking_ref=ref,
        otp_code=payload.otp_code
    )

    if not is_valid:
        log_integration_event(
            db=db,
            tenant_id=tenant.id,
            integration_id=integration.id,
            event_type="verify_otp",
            status_str="failed",
            status_code=400,
            payload_summary=f"Failed verification attempt for Ref {ref}"
        )
        raise HTTPException(status_code=400, detail=message)

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="verify_otp",
        status_str="success",
        status_code=200,
        payload_summary=f"Caller successfully verified for Ref {ref}"
    )

    return {
        "verified": True,
        "verification_token": token,
        "message": message,
        "expires_in_minutes": 15
    }


@router.post("/service-requests", status_code=status.HTTP_201_CREATED, summary="Create Guest Service Request / Staff Escalation")
def create_service_request(
    payload: ServiceRequestIn,
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context("escalations:create")),
    db: Session = Depends(get_db)
):
    """Creates a human staff escalation or service request from the AI Receptionist."""
    integration, tenant = context

    task_data = {
        "guest_name": payload.guest_name,
        "caller_phone": payload.caller_phone or "",
        "room_number": payload.room_number or "",
        "category": payload.category,
        "priority": payload.priority,
        "description": payload.description,
        "source": "AI Receptionist",
        "created_at": to_iso(datetime.now(timezone.utc))
    }

    record = OperationalRecord(
        tenant_id=tenant.id,
        category="guest_service",
        title=f"AI Request: {payload.category.title()} - Room {payload.room_number or 'Front Desk'}",
        status="PENDING",
        data=json.dumps(task_data)
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type="service_request",
        status_str="success",
        status_code=201,
        payload_summary=f"Escalation ticket #{record.id} created: {payload.category} ({payload.priority})"
    )

    return {
        "id": record.id,
        "status": record.status,
        "title": record.title,
        "message": "Service request dispatched to hotel staff successfully."
    }


@router.post("/log-activity", summary="Log AI Receptionist Call Activity")
def log_activity(
    payload: LogActivityIn,
    context: Tuple[TenantIntegration, Tenant] = Depends(get_integration_context()),
    db: Session = Depends(get_db)
):
    """Allows the AI Receptionist to record call transcripts and audit summaries into StayFlow."""
    integration, tenant = context

    log_integration_event(
        db=db,
        tenant_id=tenant.id,
        integration_id=integration.id,
        event_type=payload.event_type,
        status_str=payload.status,
        payload_summary=payload.summary,
        error_details=payload.details
    )

    return {"status": "logged"}
