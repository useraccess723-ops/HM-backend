"""Remove the sample/demo data that earlier versions of StayFlow seeded into the database.

Usage (from the backend folder, with the venv active):

    python clear_demo_data.py            # removes only the known demo bookings, guests and payments
    python clear_demo_data.py --all      # ALSO removes every room, room type, channel, offer and
                                         # operational record (administrator accounts are always kept)

The script asks for confirmation before changing anything.
"""
import sys
from sqlalchemy import delete, select
from app.database.connection import SessionLocal
from app.models import (Reservation, Payment, Guest, Room, RoomType, BookingChannel, Offer, OperationalRecord, AuditLog)

DEMO_REFERENCES = [f"BK-{n}" for n in range(10421, 10431)]


def main():
    wipe_all = "--all" in sys.argv[1:]
    scope = ("ALL rooms, room types, channels, offers, reservations, guests, payments, records and audit logs"
             if wipe_all else "the demo reservations (BK-10421..BK-10430), their guests and their payments")
    if input(f"This will permanently delete {scope}. Type YES to continue: ").strip() != "YES":
        raise SystemExit("Cancelled. Nothing was changed.")

    with SessionLocal() as db:
        if wipe_all:
            db.execute(delete(Payment))
            db.execute(delete(Reservation))
            db.execute(delete(Guest))
            db.execute(delete(Room))
            db.execute(delete(RoomType))
            db.execute(delete(BookingChannel))
            db.execute(delete(Offer))
            db.execute(delete(OperationalRecord))
            db.execute(delete(AuditLog))
        else:
            res_ids = db.scalars(select(Reservation.id).where(Reservation.reference.in_(DEMO_REFERENCES))).all()
            guest_ids = db.scalars(select(Guest.id).where(Guest.notes == "Demo record")).all()
            if res_ids:
                db.execute(delete(Payment).where(Payment.reservation_id.in_(res_ids)))
                db.execute(delete(Reservation).where(Reservation.id.in_(res_ids)))
            if guest_ids:
                still_used = set(db.scalars(select(Reservation.guest_id).where(Reservation.guest_id.in_(guest_ids))).all())
                removable = [g for g in guest_ids if g not in still_used]
                if removable:
                    db.execute(delete(Guest).where(Guest.id.in_(removable)))
            db.execute(delete(Payment).where(Payment.transaction_reference.like("DEMO-%")))
            # Rooms that were flagged reserved/occupied only because of demo bookings go back to vacant.
            active = set(db.scalars(select(Reservation.room_id).where(Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"]))).all())
            for room in db.scalars(select(Room).where(Room.status.in_(["res", "occ"]))).all():
                if room.id not in active:
                    room.status = "vac"
        db.commit()
    print("Done. Demo data removed.")


if __name__ == "__main__":
    main()
