from datetime import datetime, timezone, date
from sqlalchemy import String, Integer, Boolean, DateTime, Date, Numeric, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import LONGTEXT
from app.database.connection import Base

def utcnow(): return datetime.now(timezone.utc)

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True) # e.g. HOTEL-001, HOTEL-002
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), default="India")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    subscription_plan: Mapped[str] = mapped_column(String(40), default="Enterprise")
    max_rooms: Mapped[int] = mapped_column(Integer, default=150)
    max_users: Mapped[int] = mapped_column(Integer, default=50)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="Active") # Active, Suspended, Onboarding
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="ADMIN")
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tenant: Mapped["Tenant | None"] = relationship()

class RoomType(Base):
    __tablename__ = "room_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    slug: Mapped[str] = mapped_column(String(100), default="", index=True)
    short_description: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    base_price: Mapped[float] = mapped_column(Numeric(12,2))
    weekend_price: Mapped[float | None] = mapped_column(Numeric(12,2), nullable=True, default=None)
    max_adults: Mapped[int] = mapped_column(Integer, default=2)
    max_children: Mapped[int] = mapped_column(Integer, default=0)
    max_guests: Mapped[int] = mapped_column(Integer, default=2)
    max_occupancy: Mapped[int] = mapped_column(Integer, default=2)
    number_of_beds: Mapped[int] = mapped_column(Integer, default=1)
    bed_type: Mapped[str] = mapped_column(String(60), default="King-size Bed")
    room_size_sqft: Mapped[int] = mapped_column(Integer, default=250)
    bathroom_type: Mapped[str] = mapped_column(String(60), default="Private Bathroom")
    number_of_bathrooms: Mapped[int] = mapped_column(Integer, default=1)
    view_type: Mapped[str] = mapped_column(String(60), default="City View")
    floor_preference: Mapped[str] = mapped_column(String(60), default="Any")
    amenities: Mapped[str] = mapped_column(Text, default="[]")
    extra_adult_charge: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    extra_child_charge: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    extra_bed_charge: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    tax_percentage: Mapped[float] = mapped_column(Numeric(5,2), default=12.0)
    breakfast_included: Mapped[bool] = mapped_column(Boolean, default=False)
    free_cancellation: Mapped[bool] = mapped_column(Boolean, default=True)
    cancellation_policy: Mapped[str] = mapped_column(Text, default="Free cancellation up to 24 hours before check-in.")
    check_in_time: Mapped[str] = mapped_column(String(10), default="14:00")
    check_out_time: Mapped[str] = mapped_column(String(10), default="11:00")
    minimum_stay_nights: Mapped[int] = mapped_column(Integer, default=1)
    maximum_stay_nights: Mapped[int] = mapped_column(Integer, default=30)
    refund_policy: Mapped[str] = mapped_column(Text, default="100% refund if cancelled at least 24 hours before arrival.")
    additional_notes: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT, "mysql"), default="")
    status: Mapped[str] = mapped_column(String(20), default="Active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    tenant: Mapped["Tenant"] = relationship()

class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    number: Mapped[str] = mapped_column(String(20), index=True)
    floor: Mapped[int] = mapped_column(Integer, default=1)
    room_type_id: Mapped[int] = mapped_column(ForeignKey("room_types.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="vac") # vac, occ, res, dirty, ooo
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    room_type: Mapped["RoomType"] = relationship()
    tenant: Mapped["Tenant"] = relationship()

class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    identification_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferences: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str | None] = mapped_column(String(40), default="Silver", nullable=True)
    qr_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tenant: Mapped["Tenant"] = relationship()

class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (Index("ix_reservation_room_dates", "room_id", "check_in", "check_out"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="RESTRICT"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"), index=True)
    source: Mapped[str] = mapped_column(String(80), default="Direct")
    check_in: Mapped[date] = mapped_column(Date, index=True)
    check_out: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), default="Pending", index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(12,2))
    channel_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)  # OTA booking ID for dedup
    num_guests: Mapped[int] = mapped_column(Integer, default=1)
    group_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    group_ref: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    guest: Mapped["Guest"] = relationship()
    room: Mapped["Room"] = relationship()
    tenant: Mapped["Tenant"] = relationship()

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12,2))
    method: Mapped[str] = mapped_column(String(40), default="Cash")
    status: Mapped[str] = mapped_column(String(24), default="Pending", index=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    razorpay_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reservation: Mapped["Reservation"] = relationship()
    tenant: Mapped["Tenant"] = relationship()

class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), index=True)
    discount_type: Mapped[str] = mapped_column(String(12)) # percent or fixed
    discount_value: Mapped[float] = mapped_column(Numeric(12,2))
    starts_on: Mapped[object] = mapped_column(Date)
    ends_on: Mapped[object] = mapped_column(Date)
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tenant: Mapped["Tenant"] = relationship()

class BookingChannel(Base):
    __tablename__ = "booking_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(80), default="Not connected")
    # Per-channel API credentials (stored encrypted in production; plaintext for dev)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affiliate_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Sync tracking
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    sync_count: Mapped[int] = mapped_column(Integer, default=0)
    tenant: Mapped["Tenant"] = relationship()

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="system")
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tenant: Mapped["Tenant | None"] = relationship()

class HotelSettings(Base):
    __tablename__ = "hotel_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    hotel_name: Mapped[str] = mapped_column(String(160), default="StayFlow Hotel")
    check_in_time: Mapped[str] = mapped_column(String(5), default="14:00")
    check_out_time: Mapped[str] = mapped_column(String(5), default="11:00")
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    gst_percent: Mapped[float] = mapped_column(Numeric(5,2), default=12)
    cancellation_hours: Mapped[int] = mapped_column(Integer, default=48)
    no_show_charge: Mapped[str] = mapped_column(String(40), default="First night")
    tenant: Mapped["Tenant"] = relationship()

class OperationalRecord(Base):
    __tablename__ = "operational_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(40), default="Active")
    data: Mapped[str] = mapped_column(Text, default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    tenant: Mapped["Tenant"] = relationship()

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    code: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    tenant: Mapped["Tenant | None"] = relationship()

class Amenity(Base):
    __tablename__ = "amenities"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    amenity_type: Mapped[str] = mapped_column(String(40), index=True)  # wifi, ac, tv, swimming_pool, gym, parking, spa
    name: Mapped[str] = mapped_column(String(160), index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="Available")
    pricing_type: Mapped[str] = mapped_column(String(40), default="included_in_tariff") # complimentary, per_guest, per_session, per_day, per_vehicle, included_in_tariff
    price: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    rules: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    room: Mapped["Room | None"] = relationship()

class ServiceRequest(Base):
    __tablename__ = "service_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), unique=True, index=True) # e.g. SR-2026-00001
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True)
    booking_reference: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    guest_name: Mapped[str] = mapped_column(String(160), index=True)
    guest_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guest_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    room_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    amenity_id: Mapped[int | None] = mapped_column(ForeignKey("amenities.id", ondelete="SET NULL"), nullable=True, index=True)
    amenity_type: Mapped[str] = mapped_column(String(40), index=True, default="general")
    service_type: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="Pending", index=True) # Pending, Approved, Scheduled, In Progress, Completed, Cancelled, Rejected
    priority: Mapped[str] = mapped_column(String(20), default="Normal") # Normal, High, Urgent
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Pricing fields (captured at time of booking)
    pricing_type: Mapped[str] = mapped_column(String(40), default="included_in_tariff") # complimentary, per_guest, per_session, per_day, per_vehicle, included_in_tariff
    unit_price: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_charge: Mapped[float] = mapped_column(Numeric(12,2), default=0.0)
    payment_status: Mapped[str] = mapped_column(String(40), default="included in room tariff") # unpaid, paid, refunded, included in room tariff
    details: Mapped[str] = mapped_column(Text, default="{}") # JSON details for amenity-specific inputs
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    amenity: Mapped["Amenity | None"] = relationship()
    reservation: Mapped["Reservation | None"] = relationship()
    guest: Mapped["Guest | None"] = relationship()
    customer: Mapped["User | None"] = relationship()

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    type: Mapped[str] = mapped_column(String(30), default="outgoing", index=True) # outgoing, incoming
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[str] = mapped_column(Text, default="booking.created, booking.cancelled, booking.modified, payment.updated")
    secret: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Active", index=True) # Active, Paused, Inactive
    last_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success_rate: Mapped[str] = mapped_column(String(20), default="100%")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class WebhookDeliveryLog(Base):
    __tablename__ = "webhook_delivery_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(20), default="incoming", index=True) # incoming, outgoing
    channel: Mapped[str] = mapped_column(String(60), default="MakeMyTrip", index=True) # MakeMyTrip, Agoda, Razorpay, Stripe, etc.
    event_type: Mapped[str] = mapped_column(String(60), index=True) # booking.created, booking.cancelled, payment.captured, etc.
    endpoint: Mapped[str] = mapped_column(String(500))
    request_headers: Mapped[str] = mapped_column(Text, default="{}")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    response_code: Mapped[int] = mapped_column(Integer, default=200)
    response_body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="Success", index=True) # Success, Failed, Retrying
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)  # unique string ID e.g. DOC-..., UUID
    title: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(60), default="text")  # text, file, policy, faq, SOP, menu, room_info
    content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    content_hash: Mapped[str] = mapped_column(String(64), default="")  # sha256 of content
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunking_config_json: Mapped[str] = mapped_column(Text, default="{}")  # splitter, chunk_size, chunk_overlap
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="Processed")  # Pending, Processed, Failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant: Mapped["Tenant | None"] = relationship()
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", name="uq_tenant_document_id"),
        Index("ix_knowledge_documents_tenant_doc", "tenant_id", "document_id"),
    )

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    document_ref_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_id: Mapped[str] = mapped_column(String(100), index=True)  # e.g. DOC-001-CHK-000
    chunk_index: Mapped[int] = mapped_column(Integer, index=True)  # 0, 1, 2, ...
    chunk_text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    embedding_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)  # Persistent vector embedding
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant: Mapped["Tenant | None"] = relationship()
    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("tenant_id", "chunk_id", name="uq_tenant_chunk_id"),
        UniqueConstraint("document_ref_id", "chunk_index", name="uq_doc_chunk_index"),
        Index("ix_document_chunks_tenant_doc", "tenant_id", "document_id"),
    )


class TenantSequence(Base):
    __tablename__ = "tenant_sequences"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    current_value: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant: Mapped["Tenant"] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "sequence_key", name="uq_tenant_sequence"),
        Index("ix_tenant_sequences_lookup", "tenant_id", "sequence_key"),
    )


class TenantIntegration(Base):
    __tablename__ = "tenant_integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_type: Mapped[str] = mapped_column(String(50), default="ai_receptionist", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="disconnected", nullable=False) # "connected", "disconnected", "error"
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    key_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(String(255), default="knowledge:read,rooms:read,reservations:read,reservations:create,escalations:create", nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant: Mapped["Tenant"] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "integration_type", name="uq_tenant_integration_type"),
        Index("ix_tenant_integrations_tenant_type", "tenant_id", "integration_type"),
    )


class IntegrationLog(Base):
    __tablename__ = "integration_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("tenant_integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), default="inbound", nullable=False) # inbound, outbound
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True) # chat, check_availability, create_booking, escalation, ping, etc.
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False) # success, error, warning
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    tenant: Mapped["Tenant"] = relationship()
    integration: Mapped["TenantIntegration"] = relationship()

    __table_args__ = (
        Index("ix_integration_logs_tenant_created", "tenant_id", "created_at"),
    )


class IntegrationIdempotencyRecord(Base):
    __tablename__ = "integration_idempotency_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("tenant_integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING", nullable=False) # PROCESSING, COMPLETED, FAILED
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship()
    integration: Mapped["TenantIntegration"] = relationship()

    __table_args__ = (
        UniqueConstraint("tenant_id", "integration_id", "idempotency_key", name="uq_tenant_int_idempotency"),
        Index("ix_idempotency_lookup", "tenant_id", "integration_id", "idempotency_key"),
    )
