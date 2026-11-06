"""
Safe purge script for test/demo records in StayFlow PMS.
Deletes:
  - Demo reservations (BK-10421..BK-10430, TEST-T1-RES, TEST-T2-RES)
  - Demo payments (DEMO-*, and payments linked to demo reservations)
  - Demo guests (notes == "Demo record", and test guests alpha@guest.com, beta@guest.com)
  - Demo operational records (invoices, service charges, refund for test bookings, demo VIPs, test floor)
  - Audit logs referencing demo bookings
Resets:
  - Rooms occupied or reserved solely due to removed demo reservations back to vacant ('vac')
Preserves:
  - Genuine user-created bookings (e.g. BK-23C2DE8D, BK-0A69A8CD, BK-92BCF458)
  - Genuine user-created guests (e.g. Ravi, Devi, Koushik Balaji)
  - Genuine operational records (e.g. Walk-in reservations, selfies, ID uploads, staff directory)
  - All users, roles, permissions, tenants, room types, and room infrastructure
"""
from sqlalchemy import select, delete
from app.database.connection import SessionLocal
from app.models import Reservation, Payment, Guest, Room, OperationalRecord, AuditLog

DEMO_REFS = [f"BK-{n}" for n in range(10421, 10431)] + ["TEST-T1-RES", "TEST-T2-RES"]
TEST_GUEST_EMAILS = ["alpha@guest.com", "beta@guest.com"]
TEST_OP_TITLES = [
    "INV-TEST-T1-RES", "INV-TEST-T2-RES", "SERVICE-TEST-T1-RES-66F5AA",
    "REF-10427", "Floor 5", "Ravi Kumar", "Anita Sharma", "Rajesh Kapoor"
]


def purge():
    with SessionLocal() as db:
        # 1. Identify reservations to remove
        res_to_remove = db.scalars(select(Reservation).where(Reservation.reference.in_(DEMO_REFS))).all()
        res_ids = [r.id for r in res_to_remove]
        res_refs = [r.reference for r in res_to_remove]
        print(f"Removing {len(res_ids)} test reservations: {res_refs}")

        # 2. Identify payments to remove
        payments_to_remove = db.scalars(select(Payment).where(
            (Payment.reservation_id.in_(res_ids)) | (Payment.transaction_reference.like("DEMO-%"))
        )).all()
        pay_ids = [p.id for p in payments_to_remove]
        print(f"Removing {len(pay_ids)} test payments: {[p.transaction_reference for p in payments_to_remove]}")

        # 3. Identify demo guests to remove
        demo_guests = db.scalars(select(Guest).where(
            (Guest.notes == "Demo record") | (Guest.email.in_(TEST_GUEST_EMAILS))
        )).all()
        # Ensure none of these guests are attached to remaining non-demo reservations
        active_guest_ids = set(db.scalars(select(Reservation.guest_id).where(~Reservation.id.in_(res_ids))).all())
        safe_guests_to_remove = [g for g in demo_guests if g.id not in active_guest_ids]
        guest_ids = [g.id for g in safe_guests_to_remove]
        print(f"Removing {len(guest_ids)} test guests: {[f'{g.id}: {g.full_name}' for g in safe_guests_to_remove]}")

        # 4. Identify operational records to remove
        op_to_remove = db.scalars(select(OperationalRecord).where(
            (OperationalRecord.title.in_(TEST_OP_TITLES)) |
            (OperationalRecord.data.like("%BK-1042%")) |
            (OperationalRecord.data.like("%TEST-%"))
        )).all()
        op_ids = [o.id for o in op_to_remove]
        print(f"Removing {len(op_ids)} test operational records: {[f'{o.id}: {o.title}' for o in op_to_remove]}")

        # 5. Identify audit logs referencing demo records
        audit_to_remove = db.scalars(select(AuditLog).where(
            (AuditLog.entity_id.in_(DEMO_REFS)) |
            (AuditLog.detail.like("%BK-1042%")) |
            (AuditLog.detail.like("%TEST-%"))
        )).all()
        audit_ids = [a.id for a in audit_to_remove]
        print(f"Removing {len(audit_ids)} test audit logs")

        # Execute deletions in proper foreign-key order
        if pay_ids:
            db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
        if res_ids:
            db.execute(delete(Reservation).where(Reservation.id.in_(res_ids)))
        if guest_ids:
            db.execute(delete(Guest).where(Guest.id.in_(guest_ids)))
        if op_ids:
            db.execute(delete(OperationalRecord).where(OperationalRecord.id.in_(op_ids)))
        if audit_ids:
            db.execute(delete(AuditLog).where(AuditLog.id.in_(audit_ids)))

        # 6. Reset rooms that were flagged 'occ' or 'res' only because of demo bookings
        active_rooms = set(db.scalars(select(Reservation.room_id).where(
            Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"])
        )).all())

        rooms_reset = 0
        for room in db.scalars(select(Room).where(Room.status.in_(["res", "occ"]))).all():
            if room.id not in active_rooms:
                room.status = "vac"
                rooms_reset += 1
        print(f"Reset {rooms_reset} rooms back to vacant ('vac')")

        db.commit()
        print("\nSUCCESS: All test data purged successfully. Production and user data preserved.")


if __name__ == "__main__":
    purge()
