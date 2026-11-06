import json

ALL_PERMS = {"view": True, "create": True, "edit": True, "delete": True, "approve": True, "export": True}
VIEW_EXPORT = {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": True}
VIEW_ONLY = {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": False}
NO_ACCESS = {"view": False, "create": False, "edit": False, "delete": False, "approve": False, "export": False}

MODULES_META = [
    {
        "id": "dashboard",
        "name": "Dashboard & Overview",
        "path": "/",
        "group": "Main Menu",
        "submodules": []
    },
    {
        "id": "bookings",
        "name": "Reservations & Bookings",
        "path": "/bookings",
        "group": "Main Menu",
        "submodules": [
            {"name": "Reservation Details", "path": "/bookings/details"},
            {"name": "Booking Calendar", "path": "/bookings/calendar"},
            {"name": "Group Reservation", "path": "/bookings/group"},
            {"name": "Walk-in Reservation", "path": "/bookings/walk-in"},
            {"name": "Booking History", "path": "/bookings/history"},
            {"name": "Refund Request", "path": "/bookings/refund"},
        ]
    },
    {
        "id": "front-desk",
        "name": "Front Desk",
        "path": "/front-desk",
        "group": "Main Menu",
        "submodules": [
            {"name": "Check-in & Check-out History", "path": "/front-desk/history"},
            {"name": "Pending Check-in", "path": "/front-desk/pending-checkin"},
            {"name": "Check-out", "path": "/front-desk/checkout"},
            {"name": "Room Assignment", "path": "/front-desk/room-assignment"},
            {"name": "Early / Late Check-out", "path": "/front-desk/early-late"},
            {"name": "Guest Identity Verification", "path": "/front-desk/id-verification"},
            {"name": "Key Card Management", "path": "/front-desk/key-card"},
            {"name": "Room Transfer", "path": "/front-desk/transfer"},
            {"name": "Extend Stay", "path": "/front-desk/extend-stay"},
            {"name": "Additional Charges", "path": "/front-desk/additional-charges"},
        ]
    },
    {
        "id": "guests",
        "name": "Guest Management",
        "path": "/guests",
        "group": "Main Menu",
        "submodules": [
            {"name": "Guest Directory", "path": "/guests/directory"},
            {"name": "VIP Guests", "path": "/guests/vip"},
            {"name": "Stay History", "path": "/guests/stay-history"},
            {"name": "Guest Preferences", "path": "/guests/preferences"},
            {"name": "Blacklisted Guests", "path": "/guests/blacklisted"},
            {"name": "Loyalty Members", "path": "/guests/loyalty"},
            {"name": "Corporate Clients", "path": "/guests/corporate"},
            {"name": "Guest Details", "path": "/guests/details"},
        ]
    },
    {
        "id": "guest-services",
        "name": "Guest Services",
        "path": "/guest-services",
        "group": "Main Menu",
        "submodules": [
            {"name": "Concierge Desk", "path": "/guest-services/concierge"},
            {"name": "Luggage & Bell Desk", "path": "/guest-services/bell-desk"},
            {"name": "Valet & Airport Transfers", "path": "/guest-services/valet-transfers"},
            {"name": "Wake-up Calls & Reminders", "path": "/guest-services/wakeup-calls"},
            {"name": "Special Amenities Requests", "path": "/guest-services/amenities-requests"},
            {"name": "Lost & Found Desk", "path": "/guest-services/lost-and-found"},
            {"name": "VIP Butler Service", "path": "/guest-services/butler-service"},
            {"name": "Wi-Fi Management", "path": "/guest-services/wifi"},
            {"name": "Air Conditioning (AC)", "path": "/guest-services/ac"},
            {"name": "Television (TV)", "path": "/guest-services/tv"},
            {"name": "Swimming Pool", "path": "/guest-services/swimming-pool"},
            {"name": "Gym & Fitness", "path": "/guest-services/gym"},
            {"name": "Parking Management", "path": "/guest-services/parking"},
            {"name": "Spa Services", "path": "/guest-services/spa"},
        ]
    },
    {
        "id": "rooms",
        "name": "Room & Room Types",
        "path": "/rooms",
        "group": "Main Menu",
        "submodules": [
            {"name": "Room Availability", "path": "/rooms/availability"},
            {"name": "Room Types & Gallery", "path": "/rooms/types-gallery"},
            {"name": "Floor Management", "path": "/rooms/floor-management"},
            {"name": "Out-of-Order Rooms", "path": "/rooms/out-of-order"},
            {"name": "Seasonal Pricing", "path": "/rooms/seasonal-pricing"},
            {"name": "Taxes and Fees", "path": "/rooms/taxes-fees"},
            {"name": "Rate Plans", "path": "/rooms/rate-plans"},
        ]
    },
    {
        "id": "availability",
        "name": "Availability & Pricing",
        "path": "/availability",
        "group": "Main Menu",
        "submodules": [
            {"name": "Daily Inventory", "path": "/availability/daily-inventory"},
            {"name": "Room Type Availability", "path": "/availability/room-type"},
            {"name": "Min / Max Stay Controls", "path": "/availability/min-max-stay"},
            {"name": "Closed to Arrival / Departure", "path": "/availability/closed"},
            {"name": "Stop Sell", "path": "/availability/stop-sell"},
            {"name": "Seasonal Rates", "path": "/availability/seasonal-rates"},
            {"name": "Weekend Rates", "path": "/availability/weekend-rates"},
            {"name": "Dynamic Rates", "path": "/availability/dynamic-rates"},
        ]
    },
    {
        "id": "revenue-management",
        "name": "Revenue Management",
        "path": "/revenue-management",
        "group": "Main Menu",
        "submodules": [
            {"name": "Rate Strategy & Yield", "path": "/revenue-management/rate-strategy"},
            {"name": "Demand Forecasting", "path": "/revenue-management/demand-forecasting"},
            {"name": "RevPAR & ADR Analytics", "path": "/revenue-management/revpar-adr"},
            {"name": "Competitor Rate Intelligence", "path": "/revenue-management/competitor-rates"},
            {"name": "Length of Stay Controls", "path": "/revenue-management/los-controls"},
            {"name": "Dynamic Pricing Rules", "path": "/revenue-management/dynamic-pricing"},
            {"name": "Channel Yield Management", "path": "/revenue-management/channel-yield"},
        ]
    },
    {
        "id": "finance",
        "name": "Finance & Payments",
        "path": "/finance",
        "group": "Main Menu",
        "submodules": [
            {"name": "Booking Payments", "path": "/finance/booking-payments"},
            {"name": "Payment Requests & Deposits", "path": "/finance/payment-requests"},
            {"name": "Invoice and Receipt", "path": "/finance/invoice-receipt"},
            {"name": "Tax and GST Report", "path": "/finance/tax-gst"},
            {"name": "Revenue Performance", "path": "/finance/revenue"},
            {"name": "Deposit Management", "path": "/finance/deposit-management"},
            {"name": "Commission Booking", "path": "/finance/commission-booking"},
            {"name": "Reconciliation", "path": "/finance/reconciliation"},
            {"name": "Refunds", "path": "/finance/refunds"},
            {"name": "Outstanding Balance", "path": "/finance/outstanding-balance"},
            {"name": "Vendor Payment", "path": "/finance/vendor-payment"},
            {"name": "OTA Commission Booking", "path": "/finance/ota-commission"},
        ]
    },
    {
        "id": "sales-marketing",
        "name": "Sales & Marketing",
        "path": "/sales-marketing",
        "group": "Main Menu",
        "submodules": [
            {"name": "Corporate Accounts", "path": "/sales-marketing/corporate-accounts"},
            {"name": "Group & Event Sales", "path": "/sales-marketing/group-sales"},
            {"name": "Travel Agent Contracts", "path": "/sales-marketing/travel-agents"},
            {"name": "Campaign Management", "path": "/sales-marketing/campaigns"},
            {"name": "Leads & Pipeline", "path": "/sales-marketing/leads"},
            {"name": "Loyalty Program Campaigns", "path": "/sales-marketing/loyalty-campaigns"},
            {"name": "ROI & Channel Performance", "path": "/sales-marketing/marketing-roi"},
        ]
    },
    {
        "id": "offers",
        "name": "Offers & Promotions",
        "path": "/offers",
        "group": "Main Menu",
        "submodules": [
            {"name": "Create New Offers", "path": "/offers/create"},
            {"name": "Fixed Amount Discount", "path": "/offers/fixed-discount"},
            {"name": "Early Booking Offers", "path": "/offers/early-booking"},
            {"name": "Last-Minute Deals", "path": "/offers/last-minute"},
            {"name": "Long Stay Discount", "path": "/offers/long-stay"},
            {"name": "Seasonal Package", "path": "/offers/seasonal"},
            {"name": "Corporate Rates", "path": "/offers/corporate"},
            {"name": "Members Only Offer", "path": "/offers/members-only"},
            {"name": "Booking Restriction", "path": "/offers/booking-restriction"},
            {"name": "Redemption Reports", "path": "/offers/redemption-reports"},
        ]
    },
    {
        "id": "channels",
        "name": "Channel Manager",
        "path": "/channels",
        "group": "Main Menu",
        "submodules": [
            {"name": "Channel Availability", "path": "/channels/availability"},
            {"name": "Channel Rate Mapping", "path": "/channels/rate-mapping"},
            {"name": "Room Type Mapping", "path": "/channels/room-type-mapping"},
            {"name": "Reservation Synchronization", "path": "/channels/reservation-sync"},
            {"name": "Inventory Synchronization", "path": "/channels/inventory-sync"},
            {"name": "Booking Import History", "path": "/channels/import-history"},
            {"name": "Failed Sync Queue", "path": "/channels/failed-sync"},
            {"name": "Channel Commission Settings", "path": "/channels/commission-settings"},
            {"name": "Connection Health", "path": "/channels/connection-health"},
        ]
    },
    {
        "id": "food-beverage",
        "name": "Food & Beverage",
        "path": "/food-beverage",
        "group": "Operations",
        "submodules": [
            {"name": "Restaurant POS & Orders", "path": "/food-beverage/restaurant-pos"},
            {"name": "In-Room Dining", "path": "/food-beverage/in-room-dining"},
            {"name": "Menu and Pricing", "path": "/food-beverage/menu-engineering"},
            {"name": "Bar & Beverage Management", "path": "/food-beverage/bar-management"},
            {"name": "Banquet & Event Catering", "path": "/food-beverage/banquets"},
            {"name": "Kitchen Inventory & Requisitions", "path": "/food-beverage/kitchen-inventory"},
            {"name": "Table Reservations", "path": "/food-beverage/table-reservations"},
        ]
    },
    {
        "id": "housekeeping",
        "name": "Housekeeping",
        "path": "/housekeeping",
        "group": "Operations",
        "submodules": [
            {"name": "Dirty Rooms", "path": "/housekeeping/dirty-rooms"},
            {"name": "Clean Rooms", "path": "/housekeeping/clean-rooms"},
            {"name": "Inspection Pending", "path": "/housekeeping/inspection"},
            {"name": "Staff Assignment", "path": "/housekeeping/staff-assignment"},
            {"name": "Lost & Found", "path": "/housekeeping/lost-found"},
            {"name": "Room Readiness", "path": "/housekeeping/room-readiness"},
        ]
    },
    {
        "id": "engineering",
        "name": "Engineering & Maintenance",
        "path": "/engineering",
        "group": "Operations",
        "submodules": [
            {"name": "Work Orders & Repair Requests", "path": "/engineering/work-orders"},
            {"name": "Preventive Maintenance (PPM)", "path": "/engineering/preventive-maintenance"},
            {"name": "Asset Registry & Equipment", "path": "/engineering/asset-registry"},
            {"name": "Energy & Utility Monitoring", "path": "/engineering/energy-utility"},
            {"name": "Room Inspection Sign-off", "path": "/engineering/room-inspections"},
            {"name": "HVAC & Chillers Control", "path": "/engineering/hvac-controls"},
            {"name": "Safety & Fire Compliance", "path": "/engineering/safety-compliance"},
        ]
    },
    {
        "id": "procurement",
        "name": "Procurement",
        "path": "/procurement",
        "group": "Operations",
        "submodules": [
            {"name": "Purchase Orders (PO)", "path": "/procurement/purchase-orders"},
            {"name": "Vendor Directory", "path": "/procurement/vendors"},
            {"name": "Central Store & Inventory", "path": "/procurement/central-store"},
            {"name": "Goods Receipt Notes (GRN)", "path": "/procurement/goods-receipt"},
            {"name": "Purchase Requisitions", "path": "/procurement/requisitions"},
            {"name": "Vendor Contracts & Tenders", "path": "/procurement/contracts"},
            {"name": "Price Comparison & Bidding", "path": "/procurement/price-comparison"},
        ]
    },
    {
        "id": "security",
        "name": "Security & Loss Prevention",
        "path": "/security",
        "group": "Operations",
        "submodules": [
            {"name": "Incident Reports", "path": "/security/incident-reports"},
            {"name": "CCTV & Surveillance Log", "path": "/security/surveillance-log"},
            {"name": "Visitor & Contractor Passes", "path": "/security/visitor-passes"},
            {"name": "Keycard Audits & Access Logs", "path": "/security/keycard-audits"},
            {"name": "Lost Keycard Deactivation", "path": "/security/lost-keycards"},
            {"name": "Emergency Preparedness", "path": "/security/emergency-protocols"},
            {"name": "Patrol & Guard Dispatch", "path": "/security/patrol-rounds"},
        ]
    },
    {
        "id": "webhooks",
        "name": "Webhooks & APIs",
        "path": "/webhooks",
        "group": "Operations",
        "submodules": [
            {"name": "API Credentials", "path": "/webhooks/api-credentials"},
            {"name": "API Key Management", "path": "/webhooks/api-key-management"},
            {"name": "Incoming Webhook Logs", "path": "/webhooks/incoming-logs"},
            {"name": "Outgoing Webhook Logs", "path": "/webhooks/outgoing-logs"},
            {"name": "Retry Queue", "path": "/webhooks/retry-queue"},
            {"name": "Failed Queue", "path": "/webhooks/failed-queue"},
        ]
    },
    {
        "id": "reports",
        "name": "Reports & Analytics",
        "path": "/reports",
        "group": "Operations",
        "submodules": [
            {"name": "Booking Source Report", "path": "/reports/booking-source"},
            {"name": "Revenue by Room Type", "path": "/reports/revenue-by-room"},
            {"name": "Occupancy Report", "path": "/reports/occupancy"},
            {"name": "Daily / Monthly Revenue", "path": "/reports/revenue-report"},
            {"name": "Feedback & Complaints", "path": "/reports/feedback-complaint"},
            {"name": "Cancellation & Refund Report", "path": "/reports/cancellation-refund"},
            {"name": "Export Dashboard", "path": "/reports/export"},
            {"name": "No Show Reports", "path": "/reports/no-show"},
            {"name": "OTA Commission Reports", "path": "/reports/ota-commission"},
        ]
    },
    {
        "id": "human-resources",
        "name": "Human Resources",
        "path": "/human-resources",
        "group": "Administration",
        "submodules": [
            {"name": "Employee Directory", "path": "/human-resources/employee-directory"},
            {"name": "Attendance & Biometric Logs", "path": "/human-resources/attendance"},
            {"name": "Duty Rosters & Shifts", "path": "/human-resources/shift-rosters"},
            {"name": "Leave Management", "path": "/human-resources/leave-management"},
            {"name": "Payroll & Compensation", "path": "/human-resources/payroll"},
            {"name": "Recruitment & Onboarding", "path": "/human-resources/recruitment"},
            {"name": "Training & Certifications", "path": "/human-resources/training"},
            {"name": "Performance Appraisals", "path": "/human-resources/appraisals"},
        ]
    },
    {
        "id": "staff",
        "name": "Admin & Staff",
        "path": "/staff",
        "group": "Administration",
        "submodules": [
            {"name": "Staff Directory", "path": "/staff/directory"},
            {"name": "Admin Users", "path": "/staff/admin-users"},
            {"name": "Role & Permissions", "path": "/staff/roles"},
            {"name": "Department & Access Control", "path": "/staff/departments"},
            {"name": "Password Reset", "path": "/staff/password-reset"},
        ]
    },
    {
        "id": "notifications",
        "name": "Notifications & Alerts",
        "path": "/notifications",
        "group": "Administration",
        "submodules": []
    },
    {
        "id": "settings",
        "name": "System Settings",
        "path": "/settings",
        "group": "Administration",
        "submodules": []
    },
    {
        "id": "audit-logs",
        "name": "Audit Logs",
        "path": "/audit-logs",
        "group": "Administration",
        "submodules": []
    },
]

def build_all_paths():
    paths = []
    for mod in MODULES_META:
        paths.append(mod["path"])
        for sub in mod.get("submodules", []):
            paths.append(sub["path"])
    return paths

ALL_PATHS = build_all_paths()

def create_full_access():
    return {p: dict(ALL_PERMS) for p in ALL_PATHS}

def create_custom_matrix(allowed_paths, allow_write=False, allow_approve=False, allow_export=True, explicit_overrides=None):
    matrix = {}
    for p in ALL_PATHS:
        # Check if p or its parent is allowed
        parent = "/" + p.split("/")[1] if len(p.split("/")) > 1 else p
        is_allowed = p in allowed_paths or parent in allowed_paths
        if is_allowed:
            matrix[p] = {
                "view": True,
                "create": allow_write,
                "edit": allow_write,
                "delete": False,
                "approve": allow_approve,
                "export": allow_export,
            }
        else:
            matrix[p] = dict(NO_ACCESS)

    if explicit_overrides:
        for p, perms in explicit_overrides.items():
            if p in matrix:
                matrix[p].update(perms)
            else:
                matrix[p] = dict(perms)
    return matrix


def get_default_roles():
    """Generates the 11 default hotel roles with industry-standard RBAC permissions."""

    # 1. Admin
    admin_perms = create_full_access()

    # 2. General Manager (High-level visibility, approval, export, executive changes)
    gm_paths = ALL_PATHS
    gm_explicit = {
        "/": dict(ALL_PERMS),
        "/bookings": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/front-desk": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/revenue-management": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/finance": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/procurement": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/human-resources": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/audit-logs": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": True},
        "/settings": {"view": True, "create": False, "edit": True, "delete": False, "approve": True, "export": False},
        "/staff/roles": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": True},
    }
    gm_perms = create_custom_matrix(gm_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=gm_explicit)

    # 3. Revenue Manager
    rm_paths = [
        "/", "/revenue-management", "/availability", "/rooms", "/channels", "/reports", "/finance", "/bookings"
    ]
    rm_explicit = {
        "/revenue-management": dict(ALL_PERMS),
        "/availability": dict(ALL_PERMS),
        "/rooms": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/channels": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/reports": dict(ALL_PERMS),
        "/finance": VIEW_EXPORT,
        "/bookings": VIEW_EXPORT,
    }
    rm_perms = create_custom_matrix(rm_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=rm_explicit)

    # 4. Reservation Manager
    res_mgr_paths = [
        "/", "/bookings", "/front-desk", "/guests", "/guest-services", "/channels", "/offers", "/rooms", "/reports"
    ]
    res_mgr_explicit = {
        "/bookings": dict(ALL_PERMS),
        "/front-desk": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/guests": dict(ALL_PERMS),
        "/channels": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/offers": dict(ALL_PERMS),
        "/rooms": {"view": True, "create": False, "edit": True, "delete": False, "approve": False, "export": True},
    }
    res_mgr_perms = create_custom_matrix(res_mgr_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=res_mgr_explicit)

    # 5. Front Desk
    fd_paths = [
        "/", "/front-desk", "/bookings", "/guests", "/guest-services", "/rooms/availability"
    ]
    fd_explicit = {
        "/front-desk": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/bookings": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
        "/guests": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
        "/guest-services": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
        "/rooms": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": False},
        "/rooms/availability": VIEW_ONLY,
    }
    fd_perms = create_custom_matrix(fd_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=fd_explicit)

    # 6. Housekeeping
    hk_paths = [
        "/", "/housekeeping", "/rooms/availability", "/guest-services/amenities-requests", "/guest-services/lost-and-found"
    ]
    hk_explicit = {
        "/housekeeping": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/rooms": VIEW_ONLY,
        "/rooms/availability": {"view": True, "create": False, "edit": True, "delete": False, "approve": False, "export": False},
        "/guest-services": VIEW_ONLY,
        "/guest-services/amenities-requests": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": False},
        "/guest-services/lost-and-found": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
    }
    hk_perms = create_custom_matrix(hk_paths, allow_write=True, allow_approve=True, allow_export=False, explicit_overrides=hk_explicit)

    # 7. Finance
    fin_paths = [
        "/", "/finance", "/procurement", "/reports", "/bookings"
    ]
    fin_explicit = {
        "/finance": dict(ALL_PERMS),
        "/procurement": {"view": True, "create": False, "edit": True, "delete": False, "approve": True, "export": True},
        "/reports": dict(ALL_PERMS),
        "/bookings": VIEW_EXPORT,
    }
    fin_perms = create_custom_matrix(fin_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=fin_explicit)

    # 8. Human Resources (HR)
    hr_paths = [
        "/", "/human-resources", "/staff/directory", "/staff/departments", "/notifications"
    ]
    hr_explicit = {
        "/human-resources": dict(ALL_PERMS),
        "/staff": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": True},
        "/staff/directory": dict(ALL_PERMS),
        "/staff/departments": dict(ALL_PERMS),
        "/staff/roles": VIEW_ONLY,
    }
    hr_perms = create_custom_matrix(hr_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=hr_explicit)

    # 9. Food & Beverage (F&B)
    fb_paths = [
        "/", "/food-beverage", "/procurement/requisitions"
    ]
    fb_explicit = {
        "/food-beverage": dict(ALL_PERMS),
        "/procurement": VIEW_ONLY,
        "/procurement/requisitions": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
    }
    fb_perms = create_custom_matrix(fb_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=fb_explicit)

    # 10. Sales & Marketing
    sm_paths = [
        "/", "/sales-marketing", "/offers", "/channels", "/reports", "/bookings"
    ]
    sm_explicit = {
        "/sales-marketing": dict(ALL_PERMS),
        "/offers": dict(ALL_PERMS),
        "/channels": {"view": True, "create": False, "edit": False, "delete": False, "approve": False, "export": True},
        "/reports": VIEW_EXPORT,
        "/bookings": VIEW_EXPORT,
    }
    sm_perms = create_custom_matrix(sm_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=sm_explicit)

    # 11. Engineering & Maintenance
    eng_paths = [
        "/", "/engineering", "/rooms/out-of-order", "/procurement/requisitions"
    ]
    eng_explicit = {
        "/engineering": dict(ALL_PERMS),
        "/rooms": VIEW_ONLY,
        "/rooms/out-of-order": {"view": True, "create": True, "edit": True, "delete": False, "approve": True, "export": False},
        "/procurement": VIEW_ONLY,
        "/procurement/requisitions": {"view": True, "create": True, "edit": False, "delete": False, "approve": False, "export": False},
    }
    eng_perms = create_custom_matrix(eng_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=eng_explicit)

    # 12. Procurement
    proc_paths = [
        "/", "/procurement", "/finance", "/inventory"
    ]
    proc_explicit = {
        "/procurement": dict(ALL_PERMS),
        "/finance": VIEW_ONLY,
    }
    proc_perms = create_custom_matrix(proc_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=proc_explicit)

    # 13. Guest Services
    gs_paths = [
        "/", "/guest-services", "/guests", "/bookings", "/front-desk"
    ]
    gs_explicit = {
        "/guest-services": dict(ALL_PERMS),
        "/guests": {"view": True, "create": True, "edit": True, "delete": False, "approve": False, "export": True},
        "/bookings": VIEW_ONLY,
        "/front-desk": VIEW_ONLY,
    }
    gs_perms = create_custom_matrix(gs_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=gs_explicit)

    # 14. Security
    sec_paths = [
        "/", "/security", "/guests", "/audit-logs"
    ]
    sec_explicit = {
        "/security": dict(ALL_PERMS),
        "/guests": VIEW_ONLY,
        "/audit-logs": VIEW_EXPORT,
    }
    sec_perms = create_custom_matrix(sec_paths, allow_write=True, allow_approve=True, allow_export=True, explicit_overrides=sec_explicit)

    return [
        {
            "name": "Admin",
            "code": "ADMIN",
            "description": "Full access to all hotel operations, system settings, financial controls, and role management.",
            "is_system": True,
            "permissions": json.dumps(admin_perms),
        },
        {
            "name": "General Manager",
            "code": "GENERAL_MANAGER",
            "description": "Executive hotel oversight with view access to all modules, financial approvals, and operational reports.",
            "is_system": True,
            "permissions": json.dumps(gm_perms),
        },
        {
            "name": "Revenue Manager",
            "code": "REVENUE_MANAGER",
            "description": "Oversees pricing strategies, yield management, demand forecasting, RevPAR analytics, and OTA channels.",
            "is_system": True,
            "permissions": json.dumps(rm_perms),
        },
        {
            "name": "Reservation Manager",
            "code": "RESERVATION_MANAGER",
            "description": "Manages reservations, group bookings, guest records, promotions, and room allocation policies.",
            "is_system": True,
            "permissions": json.dumps(res_mgr_perms),
        },
        {
            "name": "Front Desk",
            "code": "FRONT_DESK",
            "description": "Guest check-in/out, keycards, room assignment, walk-ins, and guest services execution.",
            "is_system": True,
            "permissions": json.dumps(fd_perms),
        },
        {
            "name": "Housekeeping",
            "code": "HOUSEKEEPING",
            "description": "Room cleaning management, inspection sign-offs, linen tracking, and lost & found custody.",
            "is_system": True,
            "permissions": json.dumps(hk_perms),
        },
        {
            "name": "Finance",
            "code": "FINANCE",
            "description": "Ledgers, invoices, GST taxation, refunds, payment reconciliation, and procurement accounts.",
            "is_system": True,
            "permissions": json.dumps(fin_perms),
        },
        {
            "name": "Human Resources",
            "code": "HUMAN_RESOURCES",
            "description": "Staff roster, biometric attendance, payroll, leave requests, employee records, and training.",
            "is_system": True,
            "permissions": json.dumps(hr_perms),
        },
        {
            "name": "Food & Beverage",
            "code": "FOOD_BEVERAGE",
            "description": "Restaurant POS, room dining, banquet orders, bar management, and kitchen inventory stores.",
            "is_system": True,
            "permissions": json.dumps(fb_perms),
        },
        {
            "name": "Sales & Marketing",
            "code": "SALES_MARKETING",
            "description": "Corporate accounts, travel agent partnerships, MICE event sales, campaigns, and promotional ROI.",
            "is_system": True,
            "permissions": json.dumps(sm_perms),
        },
        {
            "name": "Engineering",
            "code": "ENGINEERING",
            "description": "Work orders, preventive maintenance, HVAC controls, asset registry, and fire safety compliance.",
            "is_system": True,
            "permissions": json.dumps(eng_perms),
        },
        {
            "name": "Procurement",
            "code": "PROCUREMENT",
            "description": "Purchase requisitions, POs, vendor contracts, goods received notes, store inventory, and cost approvals.",
            "is_system": True,
            "permissions": json.dumps(proc_perms),
        },
        {
            "name": "Guest Services",
            "code": "GUEST_SERVICES",
            "description": "Concierge, bell desk, valet parking, wake-up calls, butler assignments, and lost & found.",
            "is_system": True,
            "permissions": json.dumps(gs_perms),
        },
        {
            "name": "Security",
            "code": "SECURITY",
            "description": "Visitor gate passes, CCTV monitoring, incident reports, key card audits, and emergency procedures.",
            "is_system": True,
            "permissions": json.dumps(sec_perms),
        },
    ]
