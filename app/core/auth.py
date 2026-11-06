from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.database.connection import get_db
from app.models.entities import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
    except (PyJWTError, RuntimeError):
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")
    
    user = db.scalar(select(User).options(joinedload(User.tenant)).where(User.email == email, User.is_active.is_(True)))
    if not user:
        raise HTTPException(status_code=401, detail="User is inactive or does not exist")
    
    # If regular tenant user, verify user has a valid tenant and tenant is active
    if not user.is_super_admin:
        if not user.tenant_id and getattr(user, "hotel_id", None):
            user.tenant_id = user.hotel_id
        if not user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="User account is not associated with any active hotel tenant."
            )
        if user.tenant and (not user.tenant.is_active or user.tenant.status == "Suspended"):
            raise HTTPException(
                status_code=403,
                detail="Hotel property account is suspended or inactive. Please contact platform administration."
            )
    return user

def require_super_admin(user: User = Depends(current_user)) -> User:
    if not user.is_super_admin and (user.role or "").upper() != "SUPER_ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Platform Super Administrator privileges required."
        )
    return user

def get_tenant_id(request: Request, user: User = Depends(current_user)) -> Optional[int]:
    """
    Returns the effective tenant ID for the current request.
    If the user is Super Admin:
      - Can view/inspect a specific tenant by passing 'X-Tenant-Id' header or 'tenant_id' query param.
      - If no specific tenant is targeted, returns None (platform-wide mode).
    If regular tenant user:
      - Always strictly returns user.tenant_id (never trusts frontend header/query and NEVER falls back to Tenant 1).
    """
    if user.is_super_admin:
        tid = request.headers.get("X-Tenant-Id") or request.query_params.get("tenant_id")
        if tid and str(tid).isdigit():
            return int(tid)
        return None
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="User account is not associated with any active hotel tenant.")
    return user.tenant_id

import logging

logger = logging.getLogger("stayflow")

def check_tenant_access(entity, user: User, entity_name: str | None = None, required_tenant_id: Optional[int] = None):
    """
    Guarantees strict hotel data isolation.
    - Inspects both 'tenant_id' and 'hotel_id' attributes.
    - Super Admin can access all entities unless required_tenant_id is explicitly set.
    - Regular tenant users are strictly constrained to user.tenant_id.
    - Raises 404 if the entity does not belong to the user's tenant or has no tenant assigned.
    """
    if user.is_super_admin:
        if required_tenant_id is not None:
            entity_tid = getattr(entity, "tenant_id", None)
            if entity_tid is None:
                entity_tid = getattr(entity, "hotel_id", None)
            if entity_tid is not None and entity_tid != required_tenant_id:
                name = entity_name or getattr(entity, "__class__", type(entity)).__name__
                raise HTTPException(status_code=404, detail=f"{name} not found")
        return

    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="User account is not associated with any active hotel tenant.")

    entity_tid = getattr(entity, "tenant_id", None)
    if entity_tid is None:
        entity_tid = getattr(entity, "hotel_id", None)

    name = entity_name or getattr(entity, "__class__", type(entity)).__name__

    if entity_tid is None:
        logger.warning("Tenant isolation check: %s record has no tenant_id/hotel_id set", name)
        raise HTTPException(status_code=404, detail=f"{name} not found")

    if entity_tid != user.tenant_id:
        logger.warning(
            "Tenant isolation mismatch for %s: entity_tid=%s, user_tid=%s, user_email=%s",
            name, entity_tid, user.tenant_id, user.email
        )
        raise HTTPException(status_code=404, detail=f"{name} not found")

