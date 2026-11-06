import getpass
from sqlalchemy import select
from app.database.connection import Base, engine, SessionLocal
from app.models import User
from app.core.security import hash_password

def main():
    Base.metadata.create_all(bind=engine)
    email=input("Administrator email: ").strip().lower()
    full_name=input("Administrator full name: ").strip()
    password=getpass.getpass("Password (minimum 12 characters): ")
    confirm=getpass.getpass("Confirm password: ")
    if len(password)<12 or password!=confirm:
        raise SystemExit("Password must be at least 12 characters and both entries must match.")
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email==email)):
            raise SystemExit("That email already exists.")
        db.add(User(email=email,full_name=full_name,password_hash=hash_password(password),role="ADMIN"))
        db.commit()
    print("Administrator created successfully.")
if __name__=="__main__": main()
