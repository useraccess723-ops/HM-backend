import re

# 1. Update entities.py
with open("app/models/entities.py", "r", encoding="utf-8") as f:
    ent = f.read()

# Change Mapped[int] to Mapped[int | None] with nullable=True for tenant_id and hotel_id
ent = re.sub(
    r'tenant_id:\s*Mapped\[int\]\s*=\s*mapped_column\(ForeignKey\("tenants\.id",\s*ondelete="CASCADE"\),\s*index=True\)',
    r'tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)',
    ent
)
ent = re.sub(
    r'hotel_id:\s*Mapped\[int\]\s*=\s*mapped_column\(Integer,\s*index=True\)',
    r'hotel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)',
    ent
)

with open("app/models/entities.py", "w", encoding="utf-8") as f:
    f.write(ent)
print("Updated entities.py")

# 2. Update auth.py
with open("app/core/auth.py", "r", encoding="utf-8") as f:
    auth = f.read()

old_auth_check = """    if not user.is_super_admin and (user.role or "").upper() != "SUPER_ADMIN":
        if not user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="User account is not associated with any active hotel tenant."
            )"""

new_auth_check = """    if not user.is_super_admin and (user.role or "").upper() != "SUPER_ADMIN":
        if not user.tenant_id and getattr(user, "hotel_id", None):
            user.tenant_id = user.hotel_id
        if not user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="User account is not associated with any active hotel tenant."
            )"""

if old_auth_check in auth:
    auth = auth.replace(old_auth_check, new_auth_check)
    with open("app/core/auth.py", "w", encoding="utf-8") as f:
        f.write(auth)
    print("Updated auth.py")

# 3. Update main.py
with open("app/main.py", "r", encoding="utf-8") as f:
    main_py = f.read()

old_main_check = """    if not user.is_super_admin and (user.role or "").upper() != "SUPER_ADMIN":
        if not user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="User account is not associated with any active hotel tenant."
            )"""

new_main_check = """    if not user.is_super_admin and (user.role or "").upper() != "SUPER_ADMIN":
        if not user.tenant_id and getattr(user, "hotel_id", None):
            user.tenant_id = user.hotel_id
        if not user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="User account is not associated with any active hotel tenant."
            )"""

if old_main_check in main_py:
    main_py = main_py.replace(old_main_check, new_main_check)
    with open("app/main.py", "w", encoding="utf-8") as f:
        f.write(main_py)
    print("Updated main.py")
