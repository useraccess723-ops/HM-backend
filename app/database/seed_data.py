"""Default seed data for automatic database initialization on server startup."""
import json
from decimal import Decimal
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.models import User, Role, RoomType, Room, BookingChannel, HotelSettings, Amenity, Guest, Reservation
from app.core.security import hash_password, verify_password
from app.core.rbac_defaults import get_default_roles

DEFAULT_USERS_DATA = [
    {"email": "superadmin@stayflow.com", "full_name": "Platform Super Administrator", "role": "SUPER_ADMIN", "password": "SuperAdmin@2026!", "title": "Platform Super Administrator", "is_super_admin": True, "tenant_id": None},
    {"email": "admin@hotel.com", "full_name": "Administrator", "role": "ADMIN", "password": "Password@123", "title": "System Administrator", "is_super_admin": False, "tenant_id": 1},
    {"email": "admin@stayflow.com", "full_name": "StayFlow Administrator", "role": "ADMIN", "password": "Password@123", "title": "StayFlow Administrator", "is_super_admin": False, "tenant_id": 1},
    {"email": "admin@royalpalace.com", "full_name": "Royal Palace Administrator", "role": "ADMIN", "password": "Password@123", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 2},
    {"email": "manager2@hotel.com", "full_name": "Royal Palace Manager", "role": "MANAGER", "password": "Password@123", "title": "Hotel Manager", "is_super_admin": False, "tenant_id": 2},
    {"email": "gm@hotel.com", "full_name": "Vikramaditya Rathore", "role": "GENERAL_MANAGER", "password": "Password@123", "title": "General Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "revenue@hotel.com", "full_name": "Radhika Sen", "role": "REVENUE_MANAGER", "password": "Password@123", "title": "Revenue & Yield Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "reservations@hotel.com", "full_name": "Amit Verma", "role": "RESERVATION_MANAGER", "password": "Password@123", "title": "Central Reservations Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "frontdesk@hotel.com", "full_name": "Priya Sharma", "role": "FRONT_DESK", "password": "Password@123", "title": "Front Desk Lead Officer", "is_super_admin": False, "tenant_id": 1},
    {"email": "housekeeping@hotel.com", "full_name": "Meenakshi Sundaram", "role": "HOUSEKEEPING", "password": "Password@123", "title": "Executive Housekeeper", "is_super_admin": False, "tenant_id": 1},
    {"email": "finance@hotel.com", "full_name": "Rajesh Iyer", "role": "FINANCE", "password": "Password@123", "title": "Chief Financial Controller", "is_super_admin": False, "tenant_id": 1},
    {"email": "hr@hotel.com", "full_name": "Ananya Roy", "role": "HUMAN_RESOURCES", "password": "Password@123", "title": "Director of Human Resources", "is_super_admin": False, "tenant_id": 1},
    {"email": "fb@hotel.com", "full_name": "Chef Sanjeev Malhotra", "role": "FOOD_BEVERAGE", "password": "Password@123", "title": "Food & Beverage Director", "is_super_admin": False, "tenant_id": 1},
    {"email": "sales@hotel.com", "full_name": "Rohini Deshmukh", "role": "SALES_MARKETING", "password": "Password@123", "title": "Head of Sales & Partnerships", "is_super_admin": False, "tenant_id": 1},
    {"email": "engineering@hotel.com", "full_name": "Naresh Kumar", "role": "ENGINEERING", "password": "Password@123", "title": "Chief Facility Engineer", "is_super_admin": False, "tenant_id": 1},
    {"email": "procurement@hotel.com", "full_name": "Suresh Nair", "role": "PROCUREMENT", "password": "Password@123", "title": "Procurement Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "guestservices@hotel.com", "full_name": "Lalitha Menon", "role": "GUEST_SERVICES", "password": "Password@123", "title": "Guest Services Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "security@hotel.com", "full_name": "Rajan Pillai", "role": "SECURITY", "password": "Password@123", "title": "Chief Security Officer", "is_super_admin": False, "tenant_id": 1},
    {"email": "nightauditor@hotel.com", "full_name": "Tanya Bhatia", "role": "NIGHT_AUDITOR", "password": "Password@123", "title": "Night Auditor", "is_super_admin": False, "tenant_id": 1},
    {"email": "customer@hotel.com", "full_name": "Vikram Malhotra", "role": "CUSTOMER", "password": "Password@123", "title": "Valued Resident Guest", "is_super_admin": False, "tenant_id": 1},
    {"email": "meena@hotel.com", "full_name": "Meena R", "role": "MANAGER", "password": "Password@123", "title": "Hotel Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "suresh@hotel.com", "full_name": "Suresh K", "role": "FRONT_DESK", "password": "Password@123", "title": "Front Desk Officer", "is_super_admin": False, "tenant_id": 1},
    {"email": "divya@hotel.com", "full_name": "Divya S", "role": "FINANCE", "password": "Password@123", "title": "Finance Manager", "is_super_admin": False, "tenant_id": 1},
    {"email": "rajan@hotel.com", "full_name": "Rajan P", "role": "HOUSEKEEPING", "password": "Password@123", "title": "Housekeeping Supervisor", "is_super_admin": False, "tenant_id": 1},
    {"email": "valichettykoushik@gmail.com", "full_name": "Balaji V", "role": "ADMIN", "password": "12345678", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 10},
    {"email": "admin@thepalm.com", "full_name": "The Palm Administrator", "role": "ADMIN", "password": "Password@123", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 8},
    {"email": "admin@azuresands.com", "full_name": "Azure Sands Administrator", "role": "ADMIN", "password": "Password@123", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 9},
    {"email": "ram@gmail.com", "full_name": "Ram", "role": "REVENUE_MANAGER", "password": "Password@123", "title": "Revenue Manager", "is_super_admin": False, "tenant_id": 10},
    {"email": "shiva@gmail.com", "full_name": "Shiva Kesavan", "role": "ENGINEERING", "password": "Password@123", "title": "Chief Facility Engineer", "is_super_admin": False, "tenant_id": 10},
    {"email": "koushikbala@gmail.com", "full_name": "Koushik Bala", "role": "RESERVATION_MANAGER", "password": "Password@123", "title": "Central Reservations Manager", "is_super_admin": False, "tenant_id": 10},
    {"email": "receptionist.test@hotel.com", "full_name": "Test Receptionist", "role": "FRONT_DESK", "password": "Password@123", "title": "Front Desk Receptionist", "is_super_admin": False, "tenant_id": 10},
    {"email": "priya.ramesh@hotel.com", "full_name": "Priya Ramesh", "role": "FRONT_DESK", "password": "Password@123", "title": "Front Desk Officer", "is_super_admin": False, "tenant_id": 10},
    {"email": "geetha_clean@hotel.com", "full_name": "Geetha Raman", "role": "HOUSEKEEPING", "password": "Password@123", "title": "Housekeeping Staff", "is_super_admin": False, "tenant_id": 10},
    {"email": "mukilan@gmail.com", "full_name": "Mukilan M", "role": "ADMIN", "password": "Password@123", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 11},
    {"email": "ravi@gmail.com", "full_name": "Ravi K", "role": "HOUSEKEEPING", "password": "Password@123", "title": "Housekeeping Supervisor", "is_super_admin": False, "tenant_id": 11},
    {"email": "koushik@gmail.com", "full_name": "Koushik S", "role": "FRONT_DESK", "password": "Password@123", "title": "Front Desk Officer", "is_super_admin": False, "tenant_id": 11},
    {"email": "karthik@gmail.com", "full_name": "Karthik P", "role": "FOOD_BEVERAGE", "password": "Password@123", "title": "F&B Manager", "is_super_admin": False, "tenant_id": 11},
    {"email": "bala@gmail.com", "full_name": "Bala R", "role": "ADMIN", "password": "Password@123", "title": "Hotel Administrator", "is_super_admin": False, "tenant_id": 12},
]

DEFAULT_ROOM_TYPES = [
    {
        "name": "Standard Room",
        "slug": "standard-room",
        "short_description": "A comfortable and affordable room for solo travellers and couples.",
        "description": "A comfortable and affordable room for solo travellers and couples, offering essential amenities for a relaxing stay.",
        "base_price": Decimal("2000.00"),
        "weekend_price": Decimal("2300.00"),
        "max_adults": 2,
        "max_children": 1,
        "max_guests": 2,
        "max_occupancy": 2,
        "number_of_beds": 1,
        "bed_type": "Queen-size Bed",
        "room_size_sqft": 220,
        "bathroom_type": "Private Bathroom",
        "number_of_bathrooms": 1,
        "view_type": "City View",
        "floor_preference": "Floors 1-2",
        "extra_adult_charge": Decimal("500.00"),
        "extra_child_charge": Decimal("300.00"),
        "extra_bed_charge": Decimal("600.00"),
        "tax_percentage": Decimal("12.00"),
        "breakfast_included": False,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 24 hours before check-in.",
        "check_in_time": "14:00",
        "check_out_time": "11:00",
        "minimum_stay_nights": 1,
        "maximum_stay_nights": 30,
        "refund_policy": "100% refund if cancelled at least 24 hours before arrival.",
        "additional_notes": "Ideal for short business trips and solo leisure travel.",
        "image_url": "https://images.unsplash.com/photo-1618773928121-c32242e63f39?auto=format&fit=crop&w=800&q=80",
        "status": "Active",
        "amenities": json.dumps(["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "Wardrobe", "Work Desk", "Private Bathroom", "Hot and Cold Water", "Daily Housekeeping", "Fresh Towels", "Toiletries", "Complimentary Bottled Water"])
    },
    {
        "name": "Deluxe Room",
        "slug": "deluxe-room",
        "short_description": "Spacious and upgraded room with enhanced comfort and city views.",
        "description": "A spacious and upgraded room with enhanced comfort, quality furnishings, and additional in-room facilities.",
        "base_price": Decimal("3500.00"),
        "weekend_price": Decimal("4000.00"),
        "max_adults": 2,
        "max_children": 1,
        "max_guests": 2,
        "max_occupancy": 2,
        "number_of_beds": 1,
        "bed_type": "King-size Bed",
        "room_size_sqft": 320,
        "bathroom_type": "Private Bathroom",
        "number_of_bathrooms": 1,
        "view_type": "City View",
        "floor_preference": "Floors 2-3",
        "extra_adult_charge": Decimal("800.00"),
        "extra_child_charge": Decimal("400.00"),
        "extra_bed_charge": Decimal("900.00"),
        "tax_percentage": Decimal("12.00"),
        "breakfast_included": False,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 24 hours before check-in.",
        "check_in_time": "14:00",
        "check_out_time": "11:00",
        "minimum_stay_nights": 1,
        "maximum_stay_nights": 30,
        "refund_policy": "100% refund if cancelled at least 24 hours before arrival.",
        "additional_notes": "Features plush bedding and high-speed dedicated Wi-Fi.",
        "image_url": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=800&q=80",
        "status": "Active",
        "amenities": json.dumps(["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "Wardrobe", "Work Desk", "Private Bathroom", "Hot and Cold Water", "Shower", "Daily Housekeeping", "Fresh Towels", "Toiletries", "Complimentary Bottled Water", "Tea and Coffee Maker", "Mini Refrigerator", "In-room Safe", "Hair Dryer", "Premium Bedding", "City View", "Room Service"])
    },
    {
        "name": "Premium Room",
        "slug": "premium-room",
        "short_description": "Elegant room featuring superior bedding, balcony, and lounge access.",
        "description": "An elegant room featuring premium furnishings, superior bedding, enhanced facilities, and a refined guest experience.",
        "base_price": Decimal("5000.00"),
        "weekend_price": Decimal("5800.00"),
        "max_adults": 2,
        "max_children": 1,
        "max_guests": 2,
        "max_occupancy": 2,
        "number_of_beds": 1,
        "bed_type": "King-size Bed",
        "room_size_sqft": 420,
        "bathroom_type": "Private Bathroom",
        "number_of_bathrooms": 1,
        "view_type": "Garden View",
        "floor_preference": "Floors 3-4",
        "extra_adult_charge": Decimal("1000.00"),
        "extra_child_charge": Decimal("500.00"),
        "extra_bed_charge": Decimal("1200.00"),
        "tax_percentage": Decimal("18.00"),
        "breakfast_included": True,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 48 hours before check-in.",
        "check_in_time": "14:00",
        "check_out_time": "12:00",
        "minimum_stay_nights": 1,
        "maximum_stay_nights": 30,
        "refund_policy": "100% refund if cancelled at least 48 hours before arrival.",
        "additional_notes": "Complimentary gourmet breakfast included at The Palms Restaurant.",
        "image_url": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=800&q=80",
        "status": "Active",
        "amenities": json.dumps(["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "Wardrobe", "Work Desk", "Telephone", "Private Bathroom", "Hot and Cold Water", "Shower", "Daily Housekeeping", "Fresh Towels", "Toiletries", "Complimentary Bottled Water", "Tea and Coffee Maker", "Mini Refrigerator", "In-room Safe", "Hair Dryer", "Premium Bedding", "King-size Bed", "Balcony", "Garden View", "Room Service", "Breakfast Included", "Iron and Ironing Board"])
    },
    {
        "name": "Suite Room",
        "slug": "suite-room",
        "short_description": "Luxury suite with private living room, deep soak bathtub, and pool view.",
        "description": "A spacious premium accommodation with a separate living area, upgraded amenities, and additional privacy for guests seeking an elevated stay.",
        "base_price": Decimal("8000.00"),
        "weekend_price": Decimal("9500.00"),
        "max_adults": 3,
        "max_children": 2,
        "max_guests": 3,
        "max_occupancy": 3,
        "number_of_beds": 2,
        "bed_type": "King-size Bed",
        "room_size_sqft": 650,
        "bathroom_type": "Private Bathroom",
        "number_of_bathrooms": 2,
        "view_type": "Swimming Pool View",
        "floor_preference": "Floor 4 (Top Floor)",
        "extra_adult_charge": Decimal("1500.00"),
        "extra_child_charge": Decimal("800.00"),
        "extra_bed_charge": Decimal("1500.00"),
        "tax_percentage": Decimal("18.00"),
        "breakfast_included": True,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 48 hours before check-in.",
        "check_in_time": "13:00",
        "check_out_time": "12:00",
        "minimum_stay_nights": 1,
        "maximum_stay_nights": 30,
        "refund_policy": "100% refund if cancelled at least 48 hours before arrival.",
        "additional_notes": "Includes VIP check-in, welcome champagne, and butler service on request.",
        "image_url": "https://images.unsplash.com/photo-1631049307264-da0ec9d70304?auto=format&fit=crop&w=800&q=80",
        "status": "Active",
        "amenities": json.dumps(["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "Wardrobe", "Work Desk", "Telephone", "Private Bathroom", "Hot and Cold Water", "Shower", "Bathtub", "Hair Dryer", "Toiletries", "Fresh Towels", "Premium Bedding", "King-size Bed", "Balcony", "Swimming Pool View", "Room Service", "Breakfast Included", "Complimentary Breakfast", "Dining Area", "Sofa / Seating Area", "Living Room", "Separate Bedroom", "Mini Refrigerator", "In-room Safe", "Tea and Coffee Maker", "Iron and Ironing Board", "Laundry Service"])
    },
    {
        "name": "Family Room",
        "slug": "family-room",
        "short_description": "Family-friendly accommodation designed to comfortably host parents and children.",
        "description": "A family-friendly accommodation designed to comfortably host parents and children with additional sleeping capacity and practical amenities.",
        "base_price": Decimal("6000.00"),
        "weekend_price": Decimal("7000.00"),
        "max_adults": 4,
        "max_children": 2,
        "max_guests": 4,
        "max_occupancy": 4,
        "number_of_beds": 3,
        "bed_type": "Twin Beds",
        "room_size_sqft": 550,
        "bathroom_type": "Private Bathroom",
        "number_of_bathrooms": 2,
        "view_type": "Garden View",
        "floor_preference": "Floors 1-2",
        "extra_adult_charge": Decimal("1000.00"),
        "extra_child_charge": Decimal("500.00"),
        "extra_bed_charge": Decimal("1000.00"),
        "tax_percentage": Decimal("12.00"),
        "breakfast_included": False,
        "free_cancellation": True,
        "cancellation_policy": "Free cancellation up to 24 hours before check-in.",
        "check_in_time": "14:00",
        "check_out_time": "11:00",
        "minimum_stay_nights": 1,
        "maximum_stay_nights": 30,
        "refund_policy": "100% refund if cancelled at least 24 hours before arrival.",
        "additional_notes": "Baby cots and kid-friendly entertainment amenities available on request.",
        "image_url": "https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=800&q=80",
        "status": "Active",
        "amenities": json.dumps(["Free Wi-Fi", "Air Conditioning", "Television / Smart TV", "Wardrobe", "Work Desk", "Private Bathroom", "Hot and Cold Water", "Shower", "Daily Housekeeping", "Fresh Towels", "Toiletries", "Complimentary Bottled Water", "Tea and Coffee Maker", "Mini Refrigerator", "In-room Safe", "Hair Dryer", "Twin Beds", "Dining Area", "Sofa / Seating Area", "Dining Table", "Extra Bed Available", "Baby Cot Available", "Room Service"])
    }
]

def ensure_default_roles(db: Session):
    try:
        defaults = get_default_roles()
        existing_codes = set(db.scalars(select(Role.code)).all())
        added = False
        for r_data in defaults:
            if r_data["code"] not in existing_codes:
                role = Role(
                    name=r_data["name"],
                    code=r_data["code"],
                    description=r_data["description"],
                    is_system=r_data["is_system"],
                    permissions=r_data["permissions"]
                )
                db.add(role)
                added = True
        if added:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Role initialization notice: {e}")

def ensure_default_users(db: Session):
    try:
        from app.models.entities import Tenant
        valid_tenant_ids = set(db.scalars(select(Tenant.id)).all())
        existing_users = {u.email.lower(): u for u in db.scalars(select(User)).all()}
        added_or_updated = False
        for u_data in DEFAULT_USERS_DATA:
            email_lower = u_data["email"].lower()
            is_super = u_data.get("is_super_admin", False)
            tid = u_data.get("tenant_id", None if is_super else 1)
            if tid is not None and tid not in valid_tenant_ids:
                tid = 1 if 1 in valid_tenant_ids else (min(valid_tenant_ids) if valid_tenant_ids else None)

            if email_lower not in existing_users:
                new_user = User(
                    email=email_lower,
                    full_name=u_data["full_name"],
                    password_hash=hash_password(u_data["password"]),
                    role=u_data["role"],
                    is_active=True,
                    is_super_admin=is_super,
                    tenant_id=tid,
                    hotel_id=tid
                )
                db.add(new_user)
                added_or_updated = True
            else:
                user = existing_users[email_lower]
                if user.role != u_data["role"]:
                    user.role = u_data["role"]
                    added_or_updated = True
                if user.is_super_admin != is_super:
                    user.is_super_admin = is_super
                    added_or_updated = True
                if is_super:
                    if user.tenant_id is not None:
                        user.tenant_id = None
                        added_or_updated = True
                    if getattr(user, "hotel_id", None) is not None:
                        user.hotel_id = None
                        added_or_updated = True
                else:
                    if user.tenant_id != tid:
                        user.tenant_id = tid
                        added_or_updated = True
                    if getattr(user, "hotel_id", None) != tid:
                        user.hotel_id = tid
                        added_or_updated = True
                if not verify_password(u_data["password"], user.password_hash):
                    user.password_hash = hash_password(u_data["password"])
                    added_or_updated = True
        if added_or_updated:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"User initialization notice: {e}")

def ensure_default_room_types(db: Session):
    try:
        from app.models.entities import Tenant
        tenant_ids = [t.id for t in db.scalars(select(Tenant)).all()]
        if not tenant_ids:
            tenant_ids = [1]

        added = False
        for tid in tenant_ids:
            for item in DEFAULT_ROOM_TYPES:
                base_name = item["name"].replace(" Room", "").strip()
                existing = db.scalar(
                    select(RoomType).where(
                        RoomType.tenant_id == tid,
                        or_(
                            RoomType.name == item["name"],
                            RoomType.name == base_name,
                            RoomType.slug == item["slug"],
                        )
                    )
                )
                if not existing:
                    item_data = dict(item)
                    item_data["tenant_id"] = tid
                    db.add(RoomType(**item_data))
                    added = True
                else:
                    updated = False
                    if not existing.slug:
                        existing.slug = item["slug"]; updated = True
                    if not existing.short_description:
                        existing.short_description = item["short_description"]; updated = True
                    if not existing.image_url:
                        existing.image_url = item["image_url"]; updated = True
                    if updated:
                        added = True
        if added:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Room types initialization notice: {e}")

def ensure_default_rooms(db: Session):
    try:
        from app.models.entities import Tenant
        tenant_ids = [t.id for t in db.scalars(select(Tenant)).all()]
        if not tenant_ids:
            tenant_ids = [1]

        sample_rooms = [
            ("101", 1, "Standard Room", "vac", "Standard ground-floor room near lobby"),
            ("102", 1, "Standard Room", "vac", "Standard room with courtyard view"),
            ("103", 1, "Standard Room", "vac", "Standard room with twin beds"),
            ("201", 2, "Deluxe Room", "vac", "Deluxe king room with private balcony"),
            ("202", 2, "Deluxe Room", "vac", "Deluxe double room overlooking garden"),
            ("301", 3, "Premium Room", "vac", "Premium king room with club lounge access"),
            ("302", 3, "Premium Room", "vac", "Premium suite-style corner room"),
            ("401", 4, "Suite Room", "vac", "Luxury executive suite with panoramic city skyline"),
            ("501", 5, "Family Room", "vac", "Spacious family suite with kitchenette and twin beds"),
        ]

        added = False
        for tid in tenant_ids:
            room_count = db.scalar(select(func.count(Room.id)).where(Room.tenant_id == tid)) or 0
            if room_count == 0:
                room_types = {rt.name: rt.id for rt in db.scalars(select(RoomType).where(RoomType.tenant_id == tid)).all()}
                for rt in db.scalars(select(RoomType).where(RoomType.tenant_id == tid)).all():
                    room_types[rt.name.replace(" Room", "").strip()] = rt.id

                for num, floor, type_name, st, desc in sample_rooms:
                    rt_id = room_types.get(type_name) or room_types.get(type_name.replace(" Room", "").strip())
                    if not rt_id and room_types:
                        rt_id = list(room_types.values())[0]
                    if rt_id:
                        db.add(Room(number=num, floor=floor, room_type_id=rt_id, status=st, description=desc, tenant_id=tid))
                        added = True
        if added:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Default rooms initialization notice: {e}")

def ensure_default_channels(db: Session):
    try:
        from app.models.entities import Tenant
        tenant_ids = [t.id for t in db.scalars(select(Tenant)).all()]
        if not tenant_ids:
            tenant_ids = [1]
        defaults = [
            {"name": "Direct Website", "enabled": True, "status": "Connected"},
            {"name": "Booking.com", "enabled": True, "status": "Connected"},
            {"name": "Agoda", "enabled": True, "status": "Connected"},
            {"name": "MakeMyTrip", "enabled": True, "status": "Connected"},
            {"name": "Expedia", "enabled": False, "status": "Not connected"},
        ]
        added = False
        for tid in tenant_ids:
            channels_count = db.scalar(select(func.count(BookingChannel.id)).where(BookingChannel.tenant_id == tid)) or 0
            if channels_count == 0:
                for c in defaults:
                    db.add(BookingChannel(tenant_id=tid, name=c["name"], enabled=c["enabled"], status=c["status"]))
                    added = True
        if added:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Default channels initialization notice: {e}")

def ensure_default_hotel_settings(db: Session):
    try:
        row = db.get(HotelSettings, 1)
        if not row:
            db.add(HotelSettings(id=1, hotel_name="StayFlow Luxury Resort & Hotel"))
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Hotel settings initialization notice: {e}")

def ensure_default_amenities(db: Session):
    """Seed and backfill operational records for all 7 hotel amenities with pricing, rules, and images."""
    try:
        existing_count = db.scalar(select(func.count(Amenity.id))) or 0
        if existing_count > 0:
            # Backfill pricing, rules, and images for existing amenities if not set
            amenities = db.scalars(select(Amenity)).all()
            updated_any = False
            for a in amenities:
                atype = (a.amenity_type or "").lower().strip()
                if not a.rules:
                    if atype == "wifi":
                        a.rules = "High-speed guest Wi-Fi. 24/7 technical assistance. Fair usage policy applies."
                    elif atype == "ac":
                        a.rules = "In-room temperature adjustment 18°C-28°C. Report any cooling or remote issues for immediate maintenance."
                    elif atype == "tv":
                        a.rules = "Complimentary HD satellite & OTT channels. Casting enabled. Respect quiet hours 22:00 - 07:00."
                    elif atype == "swimming_pool":
                        a.rules = "Proper nylon/lycra swimwear mandatory. Children under 12 must be accompanied by an adult. Shower before entering."
                    elif atype == "gym":
                        a.rules = "Athletic footwear & gym attire required at all times. Wipe machines after use. Personal lockers available."
                    elif atype == "parking":
                        a.rules = "Valid parking pass required. Please park within designated bay markers. 24/7 CCTV surveillance."
                    elif atype == "spa":
                        a.rules = "Arrive 10 minutes prior to booked slot. Advance notice of 2 hours required for cancellation. Organic essential oils used."
                    updated_any = True

                if not a.image_url:
                    if atype == "wifi":
                        a.image_url = "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=600&q=80"
                    elif atype == "ac":
                        a.image_url = "/split_ac_unit.jpg"
                    elif atype == "tv":
                        a.image_url = "https://images.unsplash.com/photo-1593784991095-a205069470b6?auto=format&fit=crop&w=600&q=80"
                    elif atype == "swimming_pool":
                        a.image_url = "https://images.unsplash.com/photo-1576013551627-0cc20b96c2a7?auto=format&fit=crop&w=600&q=80"
                    elif atype == "gym":
                        a.image_url = "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=600&q=80"
                    elif atype == "parking":
                        a.image_url = "https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=600&q=80"
                    elif atype == "spa":
                        a.image_url = "https://images.unsplash.com/photo-1540555700478-4be289fbecef?auto=format&fit=crop&w=600&q=80"
                    updated_any = True

                if not a.pricing_type or a.pricing_type == "included_in_tariff" and float(a.price or 0) == 0.0:
                    if atype == "swimming_pool" and "Azure" in a.name:
                        a.pricing_type = "per_guest"
                        a.price = Decimal("350.00")
                        updated_any = True
                    elif atype == "gym":
                        a.pricing_type = "per_day"
                        a.price = Decimal("250.00")
                        updated_any = True
                    elif atype == "parking" and "EV" in a.name:
                        a.pricing_type = "per_vehicle"
                        a.price = Decimal("200.00")
                        updated_any = True
                    elif atype == "spa":
                        a.pricing_type = "per_session"
                        if "Swedish" in a.name:
                            a.price = Decimal("3500.00")
                        elif "Ayurvedic" in a.name:
                            a.price = Decimal("4800.00")
                        elif "Jasmine" in a.name:
                            a.price = Decimal("4200.00")
                        elif "Express" in a.name:
                            a.price = Decimal("2200.00")
                        else:
                            a.price = Decimal("2500.00")
                        updated_any = True

            if updated_any:
                db.commit()

            # Ensure customer@hotel.com has an active Checked-in reservation
            from app.models.entities import Tenant as _Tenant
            _tid = db.scalar(select(_Tenant.id).order_by(_Tenant.id)) or 1

            cust_guest = db.scalar(select(Guest).where(func.lower(Guest.email) == "customer@hotel.com"))
            if not cust_guest:
                cust_guest = Guest(
                    tenant_id=_tid,
                    full_name="Vikram Malhotra",
                    email="customer@hotel.com",
                    phone="+91 98765 43210",
                    identification_number="AADH-8821-9923",
                    notes="VIP Resident Customer"
                )
                db.add(cust_guest)
                db.flush()
            elif not cust_guest.tenant_id:
                cust_guest.tenant_id = _tid
                db.flush()

            # Idempotency: check by the hardcoded reference first to avoid duplicate
            # key errors on subsequent server startups against a live database.
            cust_res = db.scalar(select(Reservation).where(
                Reservation.reference == "BK-CUST2026"
            ))
            if cust_res:
                updated_res = False
                if not cust_res.tenant_id:
                    cust_res.tenant_id = _tid
                    updated_res = True
                if cust_res.guest_id != cust_guest.id:
                    cust_res.guest_id = cust_guest.id
                    updated_res = True
                if cust_res.status != "Checked-in":
                    cust_res.status = "Checked-in"
                    updated_res = True
                if updated_res:
                    db.commit()
            else:
                # Also check if this guest already has any active Checked-in reservation
                cust_res = db.scalar(select(Reservation).where(
                    Reservation.guest_id == cust_guest.id,
                    Reservation.status == "Checked-in"
                ))
                if not cust_res:
                    room_101 = db.scalar(select(Room).where(Room.number == "101"))
                    from datetime import date, timedelta
                    today = date.today()
                    cust_res = Reservation(
                        tenant_id=_tid,
                        reference="BK-CUST2026",
                        guest_id=cust_guest.id,
                        room_id=room_101.id if room_101 else None,
                        check_in=today,
                        check_out=today + timedelta(days=3),
                        source="customer@hotel.com",
                        status="Checked-in",
                        num_guests=2,
                        total_amount=Decimal("6000.00")
                    )
                    db.add(cust_res)
                    db.commit()

            if cust_res:
                try:
                    from app.main import sync_invoice_for_reservation
                    sync_invoice_for_reservation(db, cust_res)
                    db.commit()
                except Exception:
                    pass

            return

        rooms_map = {r.number: r.id for r in db.scalars(select(Room)).all()}

        default_amenities = [
            # 1. Wi-Fi
            {
                "hotel_id": 1,
                "amenity_type": "wifi",
                "name": "StayFlow-Lobby-HighSpeed",
                "room_id": None,
                "status": "Available",
                "pricing_type": "included_in_tariff",
                "price": Decimal("0.00"),
                "rules": "High-speed guest Wi-Fi. 24/7 technical assistance. Fair usage policy applies.",
                "image_url": "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=600&q=80",
                "details": json.dumps({
                    "network_name": "StayFlow-Lobby-HighSpeed",
                    "coverage_area": "Ground Floor Lobby & Reception",
                    "password": "Guest@StayFlow2025",
                    "speed": "300 Mbps",
                    "availability_status": "Available",
                    "notes": "Dual-band Wi-Fi 6 enterprise access point."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "wifi",
                "name": "StayFlow-Club-Lounge",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "network_name": "StayFlow-Club-Lounge",
                    "coverage_area": "4th Floor Club Lounge & Boardroom",
                    "password": "Lounge@VIPAccess!",
                    "speed": "500 Mbps",
                    "availability_status": "Available",
                    "notes": "Dedicated gigabit optical fiber uplink with low latency."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "wifi",
                "name": "StayFlow-Guest-Rooms",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "network_name": "StayFlow-Guest-Rooms",
                    "coverage_area": "All Guest Rooms (Floors 1-5)",
                    "password": "RoomGuestAccess#24",
                    "speed": "200 Mbps",
                    "availability_status": "Available",
                    "notes": "Seamless captive portal roaming across all floors."
                })
            },

            # 2. Air Conditioning (AC) - Room specific
            {
                "hotel_id": 1,
                "amenity_type": "ac",
                "name": "Room 101 AC",
                "room_id": rooms_map.get("101"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "101",
                    "ac_type": "Daikin Inverter Split AC",
                    "temperature_setting": "22°C",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Filter cleaned on 15th of current month."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "ac",
                "name": "Room 201 AC",
                "room_id": rooms_map.get("201"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "201",
                    "ac_type": "Mitsubishi Smart VRV",
                    "temperature_setting": "21°C",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Whisper-quiet eco mode enabled."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "ac",
                "name": "Room 301 AC",
                "room_id": rooms_map.get("301"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "301",
                    "ac_type": "Carrier Central Climate",
                    "temperature_setting": "20°C",
                    "maintenance_status": "Servicing Scheduled",
                    "availability_status": "Operational",
                    "notes": "Annual coil inspection due next week."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "ac",
                "name": "Room 401 AC",
                "room_id": rooms_map.get("401"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "401",
                    "ac_type": "Daikin Luxury Multi-Zone VRV",
                    "temperature_setting": "19°C",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Executive suite dual thermostat control."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "ac",
                "name": "Room 501 AC",
                "room_id": rooms_map.get("501"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "501",
                    "ac_type": "Samsung WindFree Inverter AC",
                    "temperature_setting": "22°C",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Multi-room cooling configured for family suite."
                })
            },

            # 3. Television (TV) - Room specific
            {
                "hotel_id": 1,
                "amenity_type": "tv",
                "name": "Room 101 TV",
                "room_id": rooms_map.get("101"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "101",
                    "tv_type": "Samsung Crystal 4K UHD 50\"",
                    "channels_services": "Tata Sky HD, Netflix, Prime Video, YouTube",
                    "remote_status": "Operational",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "HDMI 1 connected to hotel IPTV set-top box."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "tv",
                "name": "Room 201 TV",
                "room_id": rooms_map.get("201"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "201",
                    "tv_type": "LG OLED Cinema 55\"",
                    "channels_services": "All Sports, International News, Disney+, Apple TV",
                    "remote_status": "Operational",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Magic Remote with voice navigation paired."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "tv",
                "name": "Room 301 TV",
                "room_id": rooms_map.get("301"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "301",
                    "tv_type": "Sony Bravia XR 65\"",
                    "channels_services": "Premium Entertainment Suite, HBO, Live Sports, Spotify",
                    "remote_status": "Operational",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Bluetooth soundbar integration enabled."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "tv",
                "name": "Room 401 TV",
                "room_id": rooms_map.get("401"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "401",
                    "tv_type": "Samsung The Frame 75\"",
                    "channels_services": "VIP Presidential Cable Suite, 4K Streaming Hub",
                    "remote_status": "Operational",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Art mode standby with private concierge portal."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "tv",
                "name": "Room 501 TV",
                "room_id": rooms_map.get("501"),
                "status": "Operational",
                "details": json.dumps({
                    "room_number": "501",
                    "tv_type": "LG Smart LED 55\"",
                    "channels_services": "Kids Entertainment, Disney, Cartoon Network, Sony Sports",
                    "remote_status": "Operational",
                    "maintenance_status": "Good",
                    "availability_status": "Operational",
                    "notes": "Family-friendly content filtering enabled."
                })
            },

            # 4. Swimming Pool
            {
                "hotel_id": 1,
                "amenity_type": "swimming_pool",
                "name": "Azure Rooftop Infinity Pool",
                "room_id": None,
                "status": "Open",
                "details": json.dumps({
                    "pool_name": "Azure Rooftop Infinity Pool",
                    "pool_type": "Heated Rooftop Infinity Pool",
                    "opening_time": "06:00 AM",
                    "closing_time": "10:00 PM",
                    "capacity": "35",
                    "safety_status": "Lifeguard on Duty, Automated Chlorination & UV Active",
                    "availability_status": "Open",
                    "maintenance_notes": "Daily morning vacuuming & pH balance test passed at 05:30 AM."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "swimming_pool",
                "name": "Palm Garden Oasis Pool",
                "room_id": None,
                "status": "Open",
                "details": json.dumps({
                    "pool_name": "Palm Garden Oasis Pool",
                    "pool_type": "Outdoor Tropical Lagoon & Kids Pool",
                    "opening_time": "07:00 AM",
                    "closing_time": "08:00 PM",
                    "capacity": "50",
                    "safety_status": "Depth Markers Displayed (1.2m - 1.8m), First Aid Station",
                    "availability_status": "Open",
                    "maintenance_notes": "Water temperature regulated to comfortable 27°C."
                })
            },

            # 5. Gym
            {
                "hotel_id": 1,
                "amenity_type": "gym",
                "name": "StayFlow Fitness & High-Performance Gym",
                "room_id": None,
                "status": "Open",
                "details": json.dumps({
                    "gym_name": "StayFlow Fitness & High-Performance Gym",
                    "available_equipment": "Technogym Treadmills, Olympic Barbells & Bumper Plates, Dumbbells (2.5 - 50 kg), Cable Crossovers, Rowers & Spin Bikes",
                    "opening_time": "05:00 AM",
                    "closing_time": "11:00 PM",
                    "capacity": "30",
                    "availability_status": "Open",
                    "maintenance_notes": "Certified fitness trainer available 06:00 - 10:00 and 17:00 - 21:00. Sanitized thrice daily."
                })
            },

            # 6. Parking
            {
                "hotel_id": 1,
                "amenity_type": "parking",
                "name": "Basement Valet Parking (Bay A)",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "parking_type": "Underground Covered Valet",
                    "total_spaces": "60",
                    "available_spaces": "28",
                    "parking_location": "Basement Level 1 - Ramp A",
                    "parking_charges": "Complimentary for In-house Guests",
                    "availability_status": "Available",
                    "notes": "24/7 CCTV surveillance, biometric security barrier and valet ticket desk."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "parking",
                "name": "East Wing Surface & EV Fast Charging",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "parking_type": "Surface EV Charging Bay",
                    "total_spaces": "20",
                    "available_spaces": "11",
                    "parking_location": "East Wing Ground Gate 2",
                    "parking_charges": "₹15 / kWh for 60kW DC Fast Charging",
                    "availability_status": "Available",
                    "notes": "Supports CCS2 & Type-2 EV connectors. Pre-booking available at Concierge."
                })
            },

            # 7. Spa
            {
                "hotel_id": 1,
                "amenity_type": "spa",
                "name": "Deep Tissue Swedish Revitalizing Massage",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "service_name": "Deep Tissue Swedish Revitalizing Massage",
                    "service_description": "Full-body stress relief therapeutic massage using organic warm almond and lavender essential oils.",
                    "duration": "60 Mins",
                    "price": "3500.00",
                    "available_time_slots": "10:00 AM - 08:00 PM",
                    "booking_status": "Available",
                    "notes": "Includes 15-minute steam bath & herbal green tea relaxation."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "spa",
                "name": "Ayurvedic Herbal Abhyanga Therapy",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "service_name": "Ayurvedic Herbal Abhyanga Therapy",
                    "service_description": "Traditional Indian warm medicated oil massage promoting lymphatic drainage and cellular rejuvenation.",
                    "duration": "90 Mins",
                    "price": "4800.00",
                    "available_time_slots": "09:00 AM - 07:00 PM",
                    "booking_status": "Available",
                    "notes": "Conducted by certified Ayurvedic wellness therapists."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "spa",
                "name": "Royal Jasmine Aroma Detox & Body Scrub",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "service_name": "Royal Jasmine Aroma Detox & Body Scrub",
                    "service_description": "Exfoliating Himalayan sea salt scrub blended with cold-pressed jasmine and sandalwood nectar.",
                    "duration": "75 Mins",
                    "price": "4200.00",
                    "available_time_slots": "11:00 AM - 08:30 PM",
                    "booking_status": "Available",
                    "notes": "Deep skin hydration with private hydrotherapy shower."
                })
            },
            {
                "hotel_id": 1,
                "amenity_type": "spa",
                "name": "Express Facial & Scalp Revitalization",
                "room_id": None,
                "status": "Available",
                "details": json.dumps({
                    "service_name": "Express Facial & Scalp Revitalization",
                    "service_description": "Quick refreshing treatment focused on facial hydration, pressure point massage and scalp revitalization.",
                    "duration": "45 Mins",
                    "price": "2200.00",
                    "available_time_slots": "10:00 AM - 09:00 PM",
                    "booking_status": "Available",
                    "notes": "Popular choice for business travellers prior to check-out."
                })
            },
        ]

        for item in default_amenities:
            db.add(Amenity(**item))
        db.commit()
        print(f"Default amenities seeded: {len(default_amenities)} records created.")
    except Exception as e:
        db.rollback()
        print(f"Amenities initialization notice: {e}")

def ensure_default_webhooks(db: Session, force: bool = False):
    """
    Webhook subscriptions and delivery logs are managed by user/system integrations
    and not pre-populated with test records unless explicitly forced for testing.
    """
    if not force:
        return
    try:
        from secrets import token_hex
        from app.models.entities import WebhookSubscription
        count = db.scalar(select(func.count(WebhookSubscription.id))) or 0
        if count == 0:
            defaults = [
                {
                    "hotel_id": 1,
                    "name": "MakeMyTrip (MMT) Webhook",
                    "url": "http://127.0.0.1:8000/api/webhooks/test-receiver/makemytrip",
                    "events": "booking.created, booking.updated, booking.cancelled, booking.modified, payment.updated, guest.check_in, guest.check_out",
                    "secret": f"whsec_{token_hex(16)}",
                    "status": "Active",
                    "success_rate": "—",
                },
                {
                    "hotel_id": 1,
                    "name": "Agoda Partner Connect",
                    "url": "http://127.0.0.1:8000/api/webhooks/test-receiver/agoda",
                    "events": "booking.created, booking.updated, booking.cancelled, booking.modified, payment.updated, guest.check_in, guest.check_out",
                    "secret": f"whsec_{token_hex(16)}",
                    "status": "Active",
                    "success_rate": "—",
                },
                {
                    "hotel_id": 1,
                    "name": "Payment Gateway (Razorpay/Stripe)",
                    "url": "http://127.0.0.1:8000/api/webhooks/test-receiver/payment_gateway",
                    "events": "payment.captured, payment.refunded, payment.failed",
                    "secret": f"whsec_{token_hex(16)}",
                    "status": "Active",
                    "success_rate": "—",
                },
            ]
            for d in defaults:
                db.add(WebhookSubscription(**d))
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"Webhook subscription seed notice: {e}")



