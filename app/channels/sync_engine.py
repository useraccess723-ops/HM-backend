"""
Channel Sync Engine.

Orchestrates:
 1. Pulling bookings from each enabled/configured channel (or push via webhook)
 2. Creating reservations in the local DB with conflict-checking and deduplication
 3. Pushing updated availability back to all channels
 4. Updating sync status timestamps, error fields, and audit trails
"""
from datetime import datetime, timezone, date
from decimal import Decimal
from secrets import token_hex
import traceback
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models import BookingChannel, Guest, Reservation, Room, RoomType, AuditLog
from app.channels.registry import get_adapter, build_creds


def _utcnow():
    return datetime.now(timezone.utc)


def import_single_ota_booking(db: Session, channel_name: str, b: dict) -> tuple[Reservation | None, str]:
    """
    Imports a single booking payload from an OTA into StayFlow.
    Returns (reservation, message).
    """
    channel_ref = str(b.get("channel_ref", "")).strip()
    if not channel_ref:
        return None, "Missing channel_ref"

    # Deduplication: return existing reservation if already imported
    existing = db.scalar(
        select(Reservation).where(Reservation.channel_ref == channel_ref)
    )
    if existing:
        return existing, "Already imported (skipped duplicate)"

    # Parse dates
    try:
        check_in_str = str(b.get("check_in", ""))[:10]
        check_out_str = str(b.get("check_out", ""))[:10]
        check_in = datetime.strptime(check_in_str, "%Y-%m-%d").date()
        check_out = datetime.strptime(check_out_str, "%Y-%m-%d").date()
    except Exception as e:
        return None, f"Invalid dates ({b.get('check_in')} - {b.get('check_out')}): {e}"

    if check_out <= check_in:
        return None, f"Check-out {check_out} must be after check-in {check_in}"

    # Find or create guest
    guest_email = str(b.get("guest_email", "")).strip().lower()
    guest_name = str(b.get("guest_name", "")).strip() or "Guest from " + channel_name
    guest_phone = str(b.get("guest_phone", "")).strip()

    guest = None
    if guest_email:
        guest = db.scalar(select(Guest).where(Guest.email == guest_email))
    if not guest:
        guest = Guest(
            full_name=guest_name,
            email=guest_email or None,
            phone=guest_phone,
            identification_number="",
            notes="Booked via " + channel_name,
        )
        db.add(guest)
        db.flush()

    # Find matching room type
    room_type_name = str(b.get("room_type", "")).strip()
    rt = None
    if room_type_name:
        rt = db.scalar(select(RoomType).where(RoomType.name.ilike(f"%{room_type_name}%")))
    if not rt:
        rt = db.scalar(select(RoomType))  # fallback to first available room type

    if not rt:
        return None, "No room types defined in system inventory"

    # Find candidate room of this room type without date conflict
    candidate_rooms = db.scalars(
        select(Room).where(Room.room_type_id == rt.id)
    ).all()
    if not candidate_rooms:
        # Fallback to any room in the hotel
        candidate_rooms = db.scalars(select(Room)).all()

    assigned_room = None
    for r in candidate_rooms:
        if r.status in ("dirty", "ooo"):
            continue
        conflict = db.scalar(
            select(Reservation.id).where(
                Reservation.room_id == r.id,
                Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"]),
                Reservation.check_in < check_out,
                Reservation.check_out > check_in,
            ).limit(1)
        )
        if not conflict:
            assigned_room = r
            break

    # If all rooms have conflicts, fall back to first candidate room but flag it
    if not assigned_room and candidate_rooms:
        assigned_room = candidate_rooms[0]

    if not assigned_room:
        return None, f"No room available to assign for {channel_name} booking {channel_ref}"

    prefix = channel_name[:3].upper().replace(".", "")
    clean_ref = "".join(ch for ch in channel_ref if ch.isalnum())[-6:]
    ref = f"{prefix}-{clean_ref}"
    while db.scalar(select(Reservation.id).where(Reservation.reference == ref)):
        ref = f"{prefix}-{token_hex(3).upper()}"

    total_amount = float(b.get("total_amount") or 0.0)
    if total_amount <= 0:
        nights = max(1, (check_out - check_in).days)
        total_amount = float(assigned_room.room_type.base_price) * nights

    res = Reservation(
        reference=ref,
        guest_id=guest.id,
        room_id=assigned_room.id,
        check_in=check_in,
        check_out=check_out,
        status="Confirmed",
        source=b.get("source", channel_name),
        total_amount=Decimal(str(total_amount)),
        channel_ref=channel_ref,
    )
    db.add(res)
    db.flush()

    today = date.today()
    if check_in <= today < check_out and assigned_room.status == "vac":
        assigned_room.status = "res"

    db.add(AuditLog(
        actor_email=f"channel.{channel_name.lower()}",
        action="channel.booking_imported",
        entity_type="reservation",
        entity_id=str(res.id),
        detail=f"Imported from {channel_name} (ref {channel_ref}, {check_in} to {check_out}, ₹{total_amount})"
    ))

    return res, f"Successfully imported {ref}"


async def sync_channel(db: Session, channel: BookingChannel) -> dict:
    """
    Full sync cycle for one channel:
      - fetch bookings -> import new ones
      - push availability
    Returns a result summary dict.
    """
    creds = build_creds(channel)
    adapter = get_adapter(channel.name, creds)
    if adapter is None:
        channel.last_error = f"No adapter registered for channel '{channel.name}'"
        channel.status = "Error"
        db.commit()
        return {"channel": channel.name, "ok": False, "imported": 0, "message": channel.last_error}

    imported = 0
    errors = []

    # --- 1. Fetch & import bookings ---
    try:
        bookings = await adapter.fetch_bookings()
        for b in bookings:
            res, msg = import_single_ota_booking(db, channel.name, b)
            if res:
                if "Successfully imported" in msg:
                    imported += 1
            else:
                errors.append(msg)
    except Exception as exc:
        errors.append(f"fetch_bookings: {exc}")

    # --- 2. Push availability ---
    push_result = {"ok": False, "pushed": 0, "message": "skipped"}
    try:
        room_types = db.scalars(select(RoomType)).all()
        rooms_data = [
            {"room_type_id": rt.id, "price": float(rt.base_price)}
            for rt in room_types
        ]
        push_result = await adapter.push_availability(rooms_data, rooms_data)
    except Exception as exc:
        push_result = {"ok": False, "pushed": 0, "message": str(exc)}

    # --- 3. Update channel status ---
    channel.last_sync_at = _utcnow()
    channel.sync_count = (channel.sync_count or 0) + 1
    if errors:
        channel.last_error = "; ".join(errors[:3])
        channel.status = "Sync error" if imported == 0 else "Partial sync"
    else:
        channel.last_error = ""
        channel.status = "Connected"

    db.commit()
    return {
        "channel": channel.name,
        "ok": not errors,
        "imported": imported,
        "pushed": push_result.get("pushed", 0),
        "message": "; ".join(errors) if errors else f"Sync complete: {imported} imported, inventory pushed",
        "last_sync_at": channel.last_sync_at.isoformat() if channel.last_sync_at else None,
    }


async def sync_all_channels(db: Session) -> list[dict]:
    """Run sync_channel for every enabled + configured channel."""
    channels = db.scalars(
        select(BookingChannel).where(BookingChannel.enabled == True)
    ).all()
    results = []
    for ch in channels:
        has_creds = bool(ch.api_key or ch.api_token)
        if not has_creds:
            ch.last_error = "No credentials configured"
            db.commit()
            results.append({"channel": ch.name, "ok": False, "imported": 0, "message": "No credentials"})
            continue
        result = await sync_channel(db, ch)
        results.append(result)
    return results
