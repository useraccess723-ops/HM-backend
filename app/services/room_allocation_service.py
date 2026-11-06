"""Concurrency-safe room allocation and availability service.

Provides row-locking current reads (`with_for_update`) during allocation
to prevent double-booking race conditions between concurrent Front Desk,
OTA, and AI Receptionist operations.
"""
from datetime import date
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, case
from sqlalchemy.orm import Session, joinedload
from app.models.entities import Room, RoomType, Reservation

ACTIVE_BOOKING_STATUSES = ["Pending", "Confirmed", "Modified", "Checked-in"]

def check_room_conflict(
    db: Session,
    room_id: int,
    check_in: date,
    check_out: date,
    ignore_res_id: Optional[int] = None
) -> Optional[Reservation]:
    """
    Checks if a reservation conflict exists for the given room and dates.
    Uses standard half-open interval overlap: existing.check_in < req_out AND existing.check_out > req_in.
    """
    q = select(Reservation).where(
        Reservation.room_id == room_id,
        Reservation.status.in_(ACTIVE_BOOKING_STATUSES),
        Reservation.check_in < check_out,
        Reservation.check_out > check_in
    )
    if ignore_res_id:
        q = q.where(Reservation.id != ignore_res_id)
    return db.scalar(q)

def allocate_and_lock_room(
    db: Session,
    tenant_id: int,
    check_in: date,
    check_out: date,
    room_id: Optional[int] = None,
    room_type_id: Optional[int] = None,
    ignore_res_id: Optional[int] = None
) -> Optional[Room]:
    """
    Allocates and row-locks an available room for a tenant.
    
    IMPORTANT: This function NEVER calls db.commit() or db.rollback().
    The caller owns the transaction boundary and commits upon successful booking creation.
    
    Locks candidate rooms deterministically in Room.id ASC order to avoid deadlocks.
    """
    if room_id:
        stmt = (
            select(Room)
            .options(joinedload(Room.room_type))
            .where(Room.id == room_id, Room.tenant_id == tenant_id)
            .with_for_update()
        )
        room = db.scalar(stmt)
        if not room:
            return None
        if room_type_id and room.room_type_id != room_type_id:
            return None
        conflict = check_room_conflict(db, room.id, check_in, check_out, ignore_res_id)
        if conflict:
            return None
        return room

    if room_type_id:
        # Deterministic ordering by Room.id ASC ensures consistent locking order across threads
        stmt = (
            select(Room)
            .options(joinedload(Room.room_type))
            .where(
                Room.tenant_id == tenant_id,
                Room.room_type_id == room_type_id,
                Room.status.notin_(["dirty", "ooo"])
            )
            .order_by(
                case((Room.status == "vac", 1), else_=2),
                Room.id.asc()
            )
            .with_for_update()
        )
        candidates = db.scalars(stmt).unique().all()
        for cand in candidates:
            if not check_room_conflict(db, cand.id, check_in, check_out, ignore_res_id):
                return cand
        return None

    return None

def get_tenant_availability(
    db: Session,
    tenant_id: int,
    check_in: date,
    check_out: date,
    room_type_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Read-only availability check for date ranges.
    Returns list of room types with total rooms, booked rooms, and available count.
    """
    rt_query = select(RoomType).where(RoomType.tenant_id == tenant_id)
    if room_type_id:
        rt_query = rt_query.where(RoomType.id == room_type_id)
    room_types = db.scalars(rt_query).all()

    results = []
    for rt in room_types:
        rooms = db.scalars(
            select(Room).where(
                Room.tenant_id == tenant_id,
                Room.room_type_id == rt.id,
                Room.status.notin_(["ooo"])
            )
        ).all()
        total_rooms = len(rooms)
        available_rooms = []
        for r in rooms:
            if not check_room_conflict(db, r.id, check_in, check_out):
                available_rooms.append({
                    "id": r.id,
                    "number": r.number,
                    "floor": r.floor,
                    "status": r.status
                })
        
        results.append({
            "room_type_id": rt.id,
            "room_type_name": rt.name,
            "base_price": float(rt.weekend_price or 0.0) if hasattr(rt, "weekend_price") and rt.weekend_price else 0.0,
            "max_occupancy": getattr(rt, "max_guests", 2),
            "total_inventory": total_rooms,
            "available_count": len(available_rooms),
            "is_available": len(available_rooms) > 0,
            "sample_rooms": available_rooms[:5]
        })
    return results

