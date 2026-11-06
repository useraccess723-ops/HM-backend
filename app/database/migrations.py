"""Database schema synchronization and safe column additions for room_types."""
import logging
from sqlalchemy import text, inspect, select

logger = logging.getLogger("stayflow.db")

NEW_ROOM_TYPE_COLUMNS = [
    ("slug", "VARCHAR(100) DEFAULT ''"),
    ("short_description", "VARCHAR(255) DEFAULT ''"),
    ("weekend_price", "NUMERIC(12, 2)"),
    ("max_adults", "INTEGER DEFAULT 2"),
    ("max_children", "INTEGER DEFAULT 0"),
    ("max_guests", "INTEGER DEFAULT 2"),
    ("number_of_beds", "INTEGER DEFAULT 1"),
    ("bed_type", "VARCHAR(60) DEFAULT 'King-size Bed'"),
    ("room_size_sqft", "INTEGER DEFAULT 250"),
    ("bathroom_type", "VARCHAR(60) DEFAULT 'Private Bathroom'"),
    ("number_of_bathrooms", "INTEGER DEFAULT 1"),
    ("view_type", "VARCHAR(60) DEFAULT 'City View'"),
    ("floor_preference", "VARCHAR(60) DEFAULT 'Any'"),
    ("extra_adult_charge", "NUMERIC(12, 2) DEFAULT 0.0"),
    ("extra_child_charge", "NUMERIC(12, 2) DEFAULT 0.0"),
    ("extra_bed_charge", "NUMERIC(12, 2) DEFAULT 0.0"),
    ("tax_percentage", "NUMERIC(5, 2) DEFAULT 12.0"),
    ("breakfast_included", "BOOLEAN DEFAULT 0"),
    ("free_cancellation", "BOOLEAN DEFAULT 1"),
    ("cancellation_policy", "TEXT DEFAULT 'Free cancellation up to 24 hours before check-in.'"),
    ("check_in_time", "VARCHAR(10) DEFAULT '14:00'"),
    ("check_out_time", "VARCHAR(10) DEFAULT '11:00'"),
    ("minimum_stay_nights", "INTEGER DEFAULT 1"),
    ("maximum_stay_nights", "INTEGER DEFAULT 30"),
    ("refund_policy", "TEXT DEFAULT '100% refund if cancelled at least 24 hours before arrival.'"),
    ("additional_notes", "TEXT DEFAULT ''"),
    ("image_url", "TEXT DEFAULT ''"),
    ("status", "VARCHAR(20) DEFAULT 'Active'"),
    ("created_at", "DATETIME"),
    ("updated_at", "DATETIME"),
]

CHANNEL_COLUMNS = [
    ("base_url", "VARCHAR(255)"),
    ("api_key", "VARCHAR(255)"),
    ("client_id", "VARCHAR(255)"),
    ("client_secret", "VARCHAR(255)"),
    ("affiliate_id", "VARCHAR(255)"),
    ("api_token", "VARCHAR(255)"),
    ("last_sync_at", "DATETIME"),
    ("last_error", "TEXT"),
    ("sync_count", "INTEGER DEFAULT 0"),
]

def _adapt_col_def(col_def: str, dialect_name: str) -> str:
    """Adapt column DDL definitions across database dialects (PostgreSQL, MySQL, SQLite)."""
    if dialect_name == "postgresql":
        col_def = col_def.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
        col_def = col_def.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
        col_def = col_def.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
    elif dialect_name == "sqlite":
        col_def = col_def.replace("DATETIME", "TIMESTAMP")
    return col_def

def ensure_room_type_columns(engine):
    """Ensures existing room_types table has the newly added fields without data loss."""
    try:
        inspector = inspect(engine)
        dialect = engine.dialect.name
        if "room_types" in inspector.get_table_names():
            existing_cols = {col["name"] for col in inspector.get_columns("room_types")}
            for col_name, col_def in NEW_ROOM_TYPE_COLUMNS:
                if col_name not in existing_cols:
                    try:
                        adjusted_def = _adapt_col_def(col_def, dialect)
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE room_types ADD COLUMN {col_name} {adjusted_def}"))
                        logger.info(f"Added column {col_name} to room_types table.")
                    except Exception as col_err:
                        logger.warning(f"Column {col_name} addition notice: {col_err}")
    except Exception as e:
        logger.warning(f"Room types schema check error: {e}")

def ensure_channel_columns(engine):
    """Ensures booking_channels and reservations have required sync/integration fields."""
    try:
        inspector = inspect(engine)
        dialect = engine.dialect.name
        tables = inspector.get_table_names()
        if "booking_channels" in tables:
            ch_cols = {col["name"] for col in inspector.get_columns("booking_channels")}
            for col_name, col_def in CHANNEL_COLUMNS:
                if col_name not in ch_cols:
                    try:
                        adjusted_def = _adapt_col_def(col_def, dialect)
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE booking_channels ADD COLUMN {col_name} {adjusted_def}"))
                        logger.info(f"Added column {col_name} to booking_channels table.")
                    except Exception as col_err:
                        logger.warning(f"Booking channel column {col_name} notice: {col_err}")

        if "reservations" in tables:
            res_cols = {col["name"] for col in inspector.get_columns("reservations")}
            res_additions = [
                ("channel_ref", "VARCHAR(120) NULL"),
                ("num_guests", "INTEGER DEFAULT 1"),
                ("group_name", "VARCHAR(160) NULL"),
                ("group_ref", "VARCHAR(40) NULL"),
            ]
            for col_name, col_def in res_additions:
                if col_name not in res_cols:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE reservations ADD COLUMN {col_name} {col_def}"))
                        logger.info(f"Added column {col_name} to reservations table.")
                    except Exception as col_err:
                        logger.warning(f"Reservation column {col_name} notice: {col_err}")
    except Exception as e:
        logger.warning(f"Channel/Reservation schema migration error: {e}")

def ensure_guest_columns(engine):
    """Ensures guests table has qr_token and preferences columns."""
    try:
        inspector = inspect(engine)
        if "guests" in inspector.get_table_names():
            guest_cols = {col["name"] for col in inspector.get_columns("guests")}
            if "qr_token" not in guest_cols:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE guests ADD COLUMN qr_token VARCHAR(64) NULL"))
                    logger.info("Added column qr_token to guests table.")
                except Exception as col_err:
                    logger.warning(f"Guest qr_token column notice: {col_err}")
            if "preferences" not in guest_cols:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE guests ADD COLUMN preferences TEXT"))
                    logger.info("Added column preferences to guests table.")
                except Exception as col_err:
                    logger.warning(f"Guest preferences column notice: {col_err}")
    except Exception as e:
        logger.warning(f"Guest schema migration error: {e}")

def ensure_user_and_amenity_columns(engine):
    """Ensures users, amenities and service_requests tables exist with all columns and indexes."""
    try:
        from app.database.connection import Base
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "users" in tables:
            u_cols = {col["name"] for col in inspector.get_columns("users")}
            if "hotel_id" not in u_cols:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TABLE users ADD COLUMN hotel_id INTEGER DEFAULT 1"))
                    logger.info("Added column hotel_id to users table.")
                except Exception as col_err:
                    logger.warning(f"User hotel_id column notice: {col_err}")

        if "amenities" in tables:
            a_cols = {col["name"] for col in inspector.get_columns("amenities")}
            amenity_additions = [
                ("pricing_type", "VARCHAR(40) DEFAULT 'included_in_tariff'"),
                ("price", "NUMERIC(12, 2) DEFAULT 0.0"),
                ("rules", "TEXT"),
                ("image_url", "TEXT"),
            ]
            for col_name, col_def in amenity_additions:
                if col_name not in a_cols:
                    try:
                        adjusted_def = _adapt_col_def(col_def, engine.dialect.name)
                        if engine.dialect.name in ("mysql", "mariadb") and "TEXT" in adjusted_def:
                            adjusted_def = "TEXT"
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE amenities ADD COLUMN {col_name} {adjusted_def}"))
                        logger.info(f"Added column {col_name} to amenities table.")
                    except Exception as col_err:
                        logger.warning(f"Amenity {col_name} column notice: {col_err}")

        logger.info("Service requests and amenities schema checked successfully.")
    except Exception as e:
        logger.warning(f"User/Amenity schema migration error: {e}")

def ensure_webhook_log_columns(engine):
    """Ensures webhook_delivery_logs table exists with retry queue and tracking columns."""
    try:
        from app.database.connection import Base
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        if "webhook_delivery_logs" in inspector.get_table_names():
            w_cols = {col["name"] for col in inspector.get_columns("webhook_delivery_logs")}
            new_columns = [
                ("max_retries", "INTEGER DEFAULT 3"),
                ("next_retry_at", "DATETIME NULL"),
                ("error_message", "TEXT NULL"),
                ("last_attempt_at", "DATETIME NULL"),
            ]
            for col_name, col_def in new_columns:
                if col_name not in w_cols:
                    try:
                        adjusted_def = _adapt_col_def(col_def, engine.dialect.name)
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE webhook_delivery_logs ADD COLUMN {col_name} {adjusted_def}"))
                        logger.info(f"Added column {col_name} to webhook_delivery_logs table.")
                    except Exception as col_err:
                        logger.warning(f"Webhook delivery log {col_name} column notice: {col_err}")
    except Exception as e:
        logger.warning(f"Webhook log schema migration error: {e}")

def ensure_operational_records_columns(engine):
    """Ensures operational_records table has completed_at column."""
    try:
        inspector = inspect(engine)
        if "operational_records" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("operational_records")}
            if "completed_at" not in cols:
                dialect_name = engine.dialect.name.lower()
                col_def = "TIMESTAMP WITH TIME ZONE NULL" if dialect_name == "postgresql" else "DATETIME NULL"
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE operational_records ADD COLUMN completed_at {col_def}"))
                logger.info("Added completed_at column to operational_records table.")
    except Exception as e:
        logger.warning(f"operational_records schema migration notice: {e}")

def ensure_multi_tenancy_columns(engine):
    """Ensures existing tables have tenant_id and is_super_admin columns without raw dialect locks."""
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        dialect_name = engine.dialect.name.lower()

        scoped_tables = [
            ("users", True, True),
            ("rooms", True, False),
            ("room_types", True, False),
            ("guests", True, False),
            ("reservations", True, False),
            ("payments", True, False),
            ("offers", True, False),
            ("booking_channels", True, False),
            ("audit_logs", True, False),
            ("hotel_settings", True, False),
            ("operational_records", True, False),
            ("roles", True, False),
        ]

        with engine.begin() as conn:
            for tbl, need_tid, need_super in scoped_tables:
                if tbl in table_names:
                    cols = {c["name"] for c in inspector.get_columns(tbl)}
                    if need_tid and "tenant_id" not in cols:
                        try:
                            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN tenant_id INTEGER DEFAULT 1"))
                            logger.info(f"Added tenant_id column to {tbl}")
                        except Exception as e:
                            logger.warning(f"Could not add tenant_id to {tbl}: {e}")

                    if need_super and "is_super_admin" not in cols:
                        bool_def = "BOOLEAN DEFAULT FALSE" if dialect_name == "postgresql" else "BOOLEAN DEFAULT 0"
                        try:
                            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN is_super_admin {bool_def}"))
                            logger.info(f"Added is_super_admin column to {tbl}")
                        except Exception as e:
                            logger.warning(f"Could not add is_super_admin to {tbl}: {e}")

            # Ensure roles table allows multi-tenant codes across hotels
            if "roles" in table_names:
                try:
                    idx_map = {i['name']: i for i in inspector.get_indexes('roles')}
                    if dialect_name in ("mysql", "mariadb"):
                        if 'ix_roles_code' in idx_map and idx_map['ix_roles_code'].get('unique'):
                            conn.execute(text("ALTER TABLE roles DROP INDEX ix_roles_code"))
                            conn.execute(text("ALTER TABLE roles ADD INDEX ix_roles_code (code)"))
                            logger.info("Migrated roles.code index to non-unique multi-tenant index")
                        if 'ix_roles_name' in idx_map and idx_map['ix_roles_name'].get('unique'):
                            conn.execute(text("ALTER TABLE roles DROP INDEX ix_roles_name"))
                            conn.execute(text("ALTER TABLE roles ADD INDEX ix_roles_name (name)"))
                            logger.info("Migrated roles.name index to non-unique multi-tenant index")
                    elif dialect_name == "postgresql":
                        if 'ix_roles_code' in idx_map and idx_map['ix_roles_code'].get('unique'):
                            conn.execute(text("DROP INDEX IF EXISTS ix_roles_code"))
                            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_roles_code ON roles (code)"))
                        if 'ix_roles_name' in idx_map and idx_map['ix_roles_name'].get('unique'):
                            conn.execute(text("DROP INDEX IF EXISTS ix_roles_name"))
                            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_roles_name ON roles (name)"))
                except Exception as e:
                    logger.warning(f"Roles index migration notice: {e}")

        # Ensure hotel_settings has auto-incrementing primary key on MySQL
        if dialect_name in ("mysql", "mariadb") and "hotel_settings" in table_names:
            try:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE hotel_settings MODIFY id INT NOT NULL AUTO_INCREMENT"))
            except Exception as e:
                logger.warning(f"hotel_settings auto_increment notice: {e}")

        # Ensure booking_channels allows standard channel names per tenant rather than global uniqueness
        if "booking_channels" in table_names:
            try:
                uqs = inspector.get_unique_constraints("booking_channels")
                has_global_name_uq = any(uq.get("name") == "name" or uq.get("column_names") == ["name"] for uq in uqs)
                if has_global_name_uq:
                    with engine.begin() as conn:
                        try:
                            if dialect_name in ("mysql", "mariadb"):
                                conn.execute(text("ALTER TABLE booking_channels DROP INDEX name"))
                                conn.execute(text("ALTER TABLE booking_channels ADD UNIQUE KEY uq_tenant_channel (tenant_id, name)"))
                            elif dialect_name == "postgresql":
                                conn.execute(text("ALTER TABLE booking_channels DROP CONSTRAINT IF EXISTS booking_channels_name_key"))
                                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_channel ON booking_channels (tenant_id, name)"))
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"booking_channels constraint update notice: {e}")
    except Exception as e:
        logger.warning(f"Multi-tenancy column check notice: {e}")

def ensure_default_tenants(db):
    """Seed default multi-tenant organizations if not present."""
    from app.models.entities import Tenant
    try:
        t1 = db.scalar(select(Tenant).where(Tenant.id == 1))
        if not t1:
            t1 = Tenant(
                id=1,
                name="Grand Meridian Chennai",
                slug="grand-meridian",
                code="HOTEL-001",
                contact_email="contact@grandmeridian.com",
                contact_phone="+91 44 2811 0000",
                address="100 GST Road, Guindy",
                city="Chennai",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Enterprise",
                max_rooms=150,
                max_users=50,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t1)
            logger.info("Seeded primary tenant: Grand Meridian Chennai (HOTEL-001)")

        t2 = db.scalar(select(Tenant).where(Tenant.id == 2))
        if not t2:
            t2 = Tenant(
                id=2,
                name="Royal Palace New Delhi",
                slug="royal-palace",
                code="HOTEL-002",
                contact_email="concierge@royalpalacedelhi.com",
                contact_phone="+91 11 4155 0000",
                address="12 Barakhamba Road, Connaught Place",
                city="New Delhi",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Professional",
                max_rooms=80,
                max_users=25,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t2)
            logger.info("Seeded secondary demo tenant: Royal Palace New Delhi (HOTEL-002)")

        t8 = db.scalar(select(Tenant).where(Tenant.id == 8))
        if not t8:
            t8 = Tenant(
                id=8,
                name="The Palm Luxury Resort",
                slug="the-palm-luxury-resort",
                code="TPL-003",
                contact_email="contact@thepalm.com",
                contact_phone="+91 832 270 0000",
                address="Candolim Beach Road",
                city="Goa",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Enterprise",
                max_rooms=120,
                max_users=40,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t8)

        t9 = db.scalar(select(Tenant).where(Tenant.id == 9))
        if not t9:
            t9 = Tenant(
                id=9,
                name="Azure Sands Kovalam",
                slug="azure-sands-kovalam",
                code="ASK-004",
                contact_email="contact@azuresands.com",
                contact_phone="+91 471 248 0000",
                address="Lighthouse Beach Road",
                city="Kovalam",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Professional",
                max_rooms=60,
                max_users=20,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t9)

        t10 = db.scalar(select(Tenant).where(Tenant.id == 10))
        if not t10:
            t10 = Tenant(
                id=10,
                name="ABC Hotel",
                slug="abc-hotel",
                code="AH-005",
                contact_email="abc@hotel.com",
                contact_phone="+91 98765 43210",
                address="Main Avenue",
                city="Chennai",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Enterprise",
                max_rooms=100,
                max_users=30,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t10)

        t11 = db.scalar(select(Tenant).where(Tenant.id == 11))
        if not t11:
            t11 = Tenant(
                id=11,
                name="MM Residency",
                slug="mm-residency",
                code="MMR-006",
                contact_email="contact@mmresidency.com",
                contact_phone="+91 98765 43211",
                address="Mount Road",
                city="Chennai",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Enterprise",
                max_rooms=100,
                max_users=30,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t11)

        t12 = db.scalar(select(Tenant).where(Tenant.id == 12))
        if not t12:
            t12 = Tenant(
                id=12,
                name="Bala Hotel",
                slug="bala-hotel",
                code="BH-007",
                contact_email="contact@balahotel.com",
                contact_phone="+91 98765 43212",
                address="OMR IT Corridor",
                city="Chennai",
                country="India",
                currency="INR",
                timezone="Asia/Kolkata",
                subscription_plan="Professional",
                max_rooms=50,
                max_users=20,
                is_active=True,
                status="Active",
                settings_json="{}"
            )
            db.add(t12)

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Tenant seeding notice: {e}")

def ensure_default_settings(db):
    """Seed default HotelSettings for tenants if not present."""
    from app.models.entities import HotelSettings
    try:
        tenant_ids = [1, 2, 8, 9, 10, 11, 12]
        tenant_names = {
            1: "Grand Meridian Chennai",
            2: "Royal Palace New Delhi",
            8: "The Palm Luxury Resort",
            9: "Azure Sands Kovalam",
            10: "ABC Hotel",
            11: "MM Residency",
            12: "Bala Hotel"
        }
        for tid in tenant_ids:
            s = db.scalar(select(HotelSettings).where(HotelSettings.tenant_id == tid))
            if not s:
                s = HotelSettings(
                    tenant_id=tid,
                    hotel_name=tenant_names.get(tid, f"Hotel {tid}"),
                    check_in_time="14:00",
                    check_out_time="11:00",
                    currency="INR",
                    timezone="Asia/Kolkata",
                    gst_percent=12.00,
                    cancellation_hours=24,
                    no_show_charge="First night"
                )
                db.add(s)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"HotelSettings seeding notice: {e}")

def ensure_starter_inventory(db):
    """Starter inventory auto-seeding disabled to prevent automatic recreation of test data."""
    pass

def ensure_starter_channels(db):
    """Seed default booking channels for active hotels if missing."""
    from app.models.entities import BookingChannel
    default_channels = ["Direct Website", "Booking.com", "Agoda", "Expedia", "MakeMyTrip"]
    try:
        for tid in [1, 2]:
            existing = set(db.scalars(select(BookingChannel.name).where(BookingChannel.tenant_id == tid)).all())
            added = False
            for name in default_channels:
                if name not in existing:
                    try:
                        db.add(BookingChannel(tenant_id=tid, name=name, enabled=(name in ["Direct Website", "Booking.com"]), status="Connected" if name == "Direct Website" else "Not connected"))
                        db.flush()
                        added = True
                    except Exception as ch_err:
                        db.rollback()
                        logger.warning(f"Notice seeding channel {name} for tenant {tid}: {ch_err}")
            if added:
                db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Booking channels seeding notice: {e}")

def ensure_multi_tenancy(engine):
    """Backward compatibility wrapper."""
    ensure_multi_tenancy_columns(engine)

def ensure_knowledge_document_tables(engine):
    """Ensure knowledge_documents and document_chunks tables exist in database."""
    from app.database.connection import Base
    from app.models.entities import KnowledgeDocument, DocumentChunk
    try:
        Base.metadata.create_all(bind=engine, tables=[KnowledgeDocument.__table__, DocumentChunk.__table__])
        logger.info("[DB] Knowledge documents and document chunks tables verified/created.")
    except Exception as e:
        logger.warning(f"[DB] Notice ensuring knowledge document tables: {e}")

def sync_postgres_sequences(engine):
    """Synchronize PostgreSQL serial/identity sequences with current MAX(id) across all tables."""
    try:
        if engine.dialect.name != "postgresql":
            return
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        with engine.begin() as conn:
            for tbl in table_names:
                cols = {c["name"] for c in inspector.get_columns(tbl)}
                if "id" in cols:
                    try:
                        conn.execute(text(f"""
                            SELECT setval(
                                pg_get_serial_sequence('"{tbl}"', 'id'),
                                COALESCE((SELECT MAX(id) FROM "{tbl}"), 1),
                                (SELECT MAX(id) IS NOT NULL FROM "{tbl}")
                            );
                        """))
                    except Exception:
                        pass
        logger.info("[DB] PostgreSQL sequences synchronized successfully.")
    except Exception as e:
        logger.warning(f"[DB] PostgreSQL sequence sync notice: {e}")


def ensure_razorpay_payment_columns(engine):
    """Ensure payments table has razorpay_order_id, razorpay_payment_id, and razorpay_signature columns safely."""
    try:
        inspector = inspect(engine)
        if "payments" in inspector.get_table_names():
            existing_cols = {col["name"] for col in inspector.get_columns("payments")}
            cols_to_add = [
                ("razorpay_order_id", "VARCHAR(100) NULL"),
                ("razorpay_payment_id", "VARCHAR(100) NULL"),
                ("razorpay_signature", "VARCHAR(255) NULL"),
            ]
            for col_name, col_type in cols_to_add:
                if col_name not in existing_cols:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE payments ADD COLUMN {col_name} {col_type}"))
                        logger.info(f"Added column {col_name} to payments table.")
                    except Exception as col_err:
                        logger.warning(f"Notice adding column {col_name} to payments: {col_err}")
    except Exception as e:
        logger.warning(f"Payments schema check notice: {e}")

def ensure_tenant_sequences_table(engine):
    """Ensure tenant_sequences table exists and pre-seeds sequences for existing tenants."""
    from app.database.connection import Base
    from app.models.entities import TenantSequence, Tenant
    from app.services.sequence_service import get_highest_existing_beo
    from sqlalchemy.orm import Session
    try:
        Base.metadata.create_all(bind=engine, tables=[TenantSequence.__table__])
        logger.info("[DB] Tenant sequences table verified/created.")

        with Session(bind=engine) as db:
            try:
                tenants = db.query(Tenant).all()
                for t in tenants:
                    existing_seq = db.query(TenantSequence).filter(
                        TenantSequence.tenant_id == t.id,
                        TenantSequence.sequence_key == "banquet_beo"
                    ).first()
                    if not existing_seq:
                        highest = get_highest_existing_beo(db, t.id, baseline_default=512)
                        new_seq = TenantSequence(
                            tenant_id=t.id,
                            sequence_key="banquet_beo",
                            current_value=highest
                        )
                        db.add(new_seq)
                db.commit()
            except Exception as seed_err:
                db.rollback()
                logger.warning(f"[DB] Notice pre-seeding tenant sequences: {seed_err}")
    except Exception as e:
        logger.warning(f"[DB] Notice ensuring tenant sequences table: {e}")

def ensure_ai_receptionist_tables(engine):
    """Ensure tenant_integrations, integration_logs, and integration_idempotency_records tables exist."""
    from app.database.connection import Base
    from app.models.entities import TenantIntegration, IntegrationLog, IntegrationIdempotencyRecord
    try:
        Base.metadata.create_all(
            bind=engine,
            tables=[
                TenantIntegration.__table__,
                IntegrationLog.__table__,
                IntegrationIdempotencyRecord.__table__,
            ]
        )
        logger.info("[DB] AI Receptionist integration tables verified/created successfully.")
    except Exception as e:
        logger.warning(f"[DB] Notice ensuring AI Receptionist tables: {e}")

