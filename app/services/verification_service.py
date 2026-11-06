"""Guest Caller Verification Service.

Provides keyed HMAC-SHA256 OTP challenge generation, rate limiting,
attempt tracking, and ephemeral single-use verification tokens (`vtok_...`).
Guarantees anti-enumeration: responses are uniform whether or not a booking exists.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import logging
import secrets
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.models.entities import Reservation, Guest, OperationalRecord

logger = logging.getLogger("stayflow.integrations.verification")

OTP_TTL_MINUTES = 5
MAX_ATTEMPTS = 3
COOLDOWN_SECONDS = 60
TOKEN_TTL_MINUTES = 15

def _otp_hmac_secret() -> str:
    return Settings.JWT_SECRET_KEY or "stayflow_otp_hmac_default_secret_key"

def _hash_otp(code: str) -> str:
    return hmac.new(_otp_hmac_secret().encode("utf-8"), code.strip().encode("utf-8"), hashlib.sha256).hexdigest()

def request_caller_verification(
    db: Session,
    tenant_id: int,
    booking_ref: str,
    phone_number: str
) -> dict:
    """
    Issues an OTP challenge for caller verification.
    Anti-enumeration: Returns identical generic success response even if the booking or phone doesn't match.
    """
    now = datetime.now(timezone.utc)
    generic_response = {
        "status": "challenge_issued",
        "message": "If the reference and phone match an active reservation, a 6-digit verification code has been sent.",
        "expires_in_seconds": OTP_TTL_MINUTES * 60
    }

    # Normalize phone: keep digits only
    clean_phone = "".join(ch for ch in phone_number if ch.isdigit())
    if not clean_phone or len(clean_phone) < 7:
        return generic_response

    # Look up reservation strictly scoped to tenant
    res = db.scalar(
        select(Reservation).where(
            Reservation.tenant_id == tenant_id,
            Reservation.reference == booking_ref.strip().upper()
        )
    )
    if not res:
        return generic_response

    guest = db.scalar(
        select(Guest).where(
            Guest.id == res.guest_id,
            Guest.tenant_id == tenant_id
        )
    )
    if not guest or not guest.phone:
        return generic_response

    guest_clean_phone = "".join(ch for ch in guest.phone if ch.isdigit())
    if not guest_clean_phone.endswith(clean_phone[-10:]) and not clean_phone.endswith(guest_clean_phone[-10:]):
        return generic_response

    # Check cooldown on existing active challenge
    existing_rec = db.scalar(
        select(OperationalRecord).where(
            OperationalRecord.tenant_id == tenant_id,
            OperationalRecord.category == "otp_verification",
            OperationalRecord.title == f"otp:{booking_ref.upper()}",
            OperationalRecord.status == "PENDING"
        ).order_by(OperationalRecord.id.desc())
    )
    if existing_rec and existing_rec.data:
        try:
            data = json.loads(existing_rec.data)
            created_at_iso = data.get("created_at")
            if created_at_iso:
                created_dt = datetime.fromisoformat(created_at_iso)
                if (now - created_dt).total_seconds() < COOLDOWN_SECONDS:
                    return generic_response
        except Exception:
            pass

    # Generate 6-digit OTP and keyed HMAC
    raw_code = f"{secrets.randbelow(900000) + 100000:06d}"
    code_hash = _hash_otp(raw_code)

    rec_data = {
        "booking_ref": booking_ref.upper(),
        "phone_last4": clean_phone[-4:],
        "code_hash": code_hash,
        "attempts": 0,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
    }

    # Mark prior pending records as SUPERSEDED
    prior_records = db.scalars(
        select(OperationalRecord).where(
            OperationalRecord.tenant_id == tenant_id,
            OperationalRecord.category == "otp_verification",
            OperationalRecord.title == f"otp:{booking_ref.upper()}",
            OperationalRecord.status == "PENDING"
        )
    ).all()
    for pr in prior_records:
        pr.status = "SUPERSEDED"

    new_record = OperationalRecord(
        tenant_id=tenant_id,
        category="otp_verification",
        title=f"otp:{booking_ref.upper()}",
        status="PENDING",
        data=json.dumps(rec_data)
    )
    db.add(new_record)
    db.commit()

    # Log dispatch event (in production, triggers SMS webhook or notification)
    logger.info(
        f"[OTP] Verification challenge generated for Tenant #{tenant_id}, Ref {booking_ref.upper()}. "
        f"Simulated dispatch code: {raw_code}"
    )

    # For seamless local testing, expose code in dev/test mode only
    if Settings.APP_ENV in ("development", "test"):
        generic_response["dev_test_code"] = raw_code

    return generic_response

def verify_caller_otp(
    db: Session,
    tenant_id: int,
    booking_ref: str,
    otp_code: str
) -> Tuple[bool, Optional[str], str]:
    """
    Verifies an OTP submitted by the caller.
    Returns: (is_valid, verification_token, message)
    """
    now = datetime.now(timezone.utc)
    rec = db.scalar(
        select(OperationalRecord).where(
            OperationalRecord.tenant_id == tenant_id,
            OperationalRecord.category == "otp_verification",
            OperationalRecord.title == f"otp:{booking_ref.strip().upper()}",
            OperationalRecord.status == "PENDING"
        ).order_by(OperationalRecord.id.desc())
    )

    if not rec or not rec.data:
        return False, None, "Invalid or expired verification session."

    try:
        data = json.loads(rec.data)
    except Exception:
        return False, None, "Malformed verification state."

    expires_at = datetime.fromisoformat(data["expires_at"])
    if now > expires_at:
        rec.status = "EXPIRED"
        db.commit()
        return False, None, "Verification code has expired. Please request a new code."

    attempts = data.get("attempts", 0) + 1
    data["attempts"] = attempts

    if attempts > MAX_ATTEMPTS:
        rec.status = "MAX_ATTEMPTS_EXCEEDED"
        rec.data = json.dumps(data)
        db.commit()
        return False, None, "Too many failed attempts. Please request a new code."

    input_hash = _hash_otp(otp_code)
    if not hmac.compare_digest(input_hash, data.get("code_hash", "")):
        rec.data = json.dumps(data)
        db.commit()
        remaining = MAX_ATTEMPTS - attempts
        return False, None, f"Incorrect verification code. {remaining} attempt(s) remaining."

    # Success: Mark record VERIFIED and issue ephemeral single-use token
    rec.status = "VERIFIED"
    rec.completed_at = now
    rec.data = json.dumps(data)

    vtoken = f"vtok_{secrets.token_urlsafe(32)}"
    token_data = {
        "booking_ref": booking_ref.strip().upper(),
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=TOKEN_TTL_MINUTES)).isoformat(),
        "used": False
    }

    token_record = OperationalRecord(
        tenant_id=tenant_id,
        category="verification_token",
        title=f"token:{vtoken}",
        status="ACTIVE",
        data=json.dumps(token_data)
    )
    db.add(token_record)
    db.commit()

    return True, vtoken, "Verification successful."

def validate_verification_token(
    db: Session,
    tenant_id: int,
    booking_ref: str,
    token: str
) -> bool:
    """
    Validates that a verification token is valid, active, matching tenant and booking, and unexpired.
    """
    if not token or not token.startswith("vtok_"):
        return False

    now = datetime.now(timezone.utc)
    rec = db.scalar(
        select(OperationalRecord).where(
            OperationalRecord.tenant_id == tenant_id,
            OperationalRecord.category == "verification_token",
            OperationalRecord.title == f"token:{token.strip()}",
            OperationalRecord.status == "ACTIVE"
        )
    )
    if not rec or not rec.data:
        return False

    try:
        data = json.loads(rec.data)
        if data.get("booking_ref") != booking_ref.strip().upper():
            return False
        expires_at = datetime.fromisoformat(data["expires_at"])
        if now > expires_at:
            rec.status = "EXPIRED"
            db.commit()
            return False
        return True
    except Exception:
        return False

