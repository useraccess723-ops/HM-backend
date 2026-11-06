# StayFlow Hotel Reservation Backend

FastAPI REST backend added alongside the existing React/Vite frontend. Original frontend files are not edited by this backend package.

## Requirements
- Python 3.10+
- PostgreSQL for production (SQLite is the default local-development database)
- Node.js/npm for the existing frontend

## Windows PowerShell setup

From `HOTEL_RESERVATION\hotel-admin\backend`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated random value into `.env` as `JWT_SECRET_KEY`. Do not commit `.env`.

For PostgreSQL, create a database and dedicated user, then set `DATABASE_URL` in `.env`, for example:
`postgresql+psycopg://hotel_user:YOUR_URL_ENCODED_PASSWORD@localhost:5432/hotel_reservation`

Create the first administrator interactively (no default credentials are provided):
```powershell
python create_admin.py
```

Start the API:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

Run tests:
```powershell
pytest -q
```

## Start the integrated frontend

In a separate PowerShell window, from `HOTEL_RESERVATION\hotel-admin`:

```powershell
Copy-Item .env.example .env
npm ci
npm run dev
```

Vite normally serves `http://localhost:5173`. `VITE_API_BASE_URL` is configured in the frontend `.env`; its default is `http://127.0.0.1:8000`. Restart Vite after changing `.env`. Do not use `VITE_` variables for secrets.

## First local run (complete setup)

From `HOTEL_RESERVATION\hotel-admin\backend` after creating `.env` and installing Python dependencies:

```powershell
alembic upgrade head
python create_admin.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The database starts empty: no sample rooms, bookings, guests or payments are created. Add your real room types, rooms and channels through the app or API. If an earlier version of the project already put demo data into your database, run `python clear_demo_data.py` (or `python clear_demo_data.py --all` to wipe rooms, room types, channels and offers too). The login screen authenticates with the administrator you created; no default password is embedded in the frontend.

## Authentication
Use `POST /api/auth/login` with JSON `{"email":"admin@example.com","password":"..."}` or `POST /api/auth/token` with OAuth2 form fields `username` and `password`. Send the resulting access token as `Authorization: Bearer <token>`. Tokens expire based on `ACCESS_TOKEN_EXPIRE_MINUTES`.

## Implemented API surface
- Authentication: `/api/auth/login`, `/api/auth/token`, `/api/auth/me`, `/api/auth/logout`
- Users: `/api/admin/users`
- Dashboard: `/api/dashboard`
- Room types and rooms: `/api/room-types`, `/api/rooms`
- Guests: `/api/guests`
- Bookings: `/api/bookings`, `/api/bookings/{reference}`, status, check-in, check-out
- Payments: `/api/payments`
- Offers: `/api/offers`
- Channel configuration: `/api/channels`
- Reports: `/api/reports/occupancy`
- Audit: `/api/audit-logs`

All protected endpoints require a bearer token. Admin creation and management actions enforce role checks. A channel can be marked configured, but actual MMT/Agoda/Booking.com/Expedia synchronization is **not** implemented without provider credentials and documented partner APIs. Payment records are ledger entries only; no payment gateway is connected and no real payment is simulated.

## Database migrations
An initial Alembic revision is included. After installing dependencies and configuring `.env`, apply it with:
```powershell
alembic upgrade head
```
To change the schema later, generate a new revision with `alembic revision --autogenerate -m "describe change"`, review the generated migration, and then run `alembic upgrade head`. Startup also calls SQLAlchemy `create_all` as a convenient local bootstrap; it does not replace reviewed migrations for production schema evolution.

## Frontend integration status

The existing dashboard has been connected to the FastAPI backend for login/session validation, dashboard data, rooms, bookings, guest directory, housekeeping room status, channel configuration, payments, offers, reports, staff administration, hotel settings and audit logs. Existing frontend pages and assets are retained; only integration-related source changes and new API/login files were added. See `API_MAPPING.md` for the exact status per module.

The frontend does not silently fall back to mock records once signed in. It loads records from the API/database. Some nested sidebar routes are existing navigation/design placeholders rather than fully implemented workflows. External OTA synchronization and inbound/outbound webhooks are not active without provider credentials and additional event-delivery implementation. Payment records do not charge a real card or UPI account.

## Build and verification notes

Backend automated tests are run with `pytest -q`. Frontend JS/JSX syntax is checked with Babel parser. A Vite production build must be run on the target OS after `npm ci`, because the uploaded `node_modules` folder contains Windows-native optional binaries and cannot be used for a Linux production build. The source `package.json` and lockfile are retained.

## Production checklist
- Configure PostgreSQL and a strong unique `JWT_SECRET_KEY`.
- Restrict `CORS_ORIGINS` to exact trusted origins.
- Use HTTPS and a reverse proxy.
- Configure backups, log retention, database least privilege and monitoring.
- Add rate limiting and refresh/revocation strategy before public exposure.
- Review reservation concurrency guarantees for the chosen production database and deployment topology.
