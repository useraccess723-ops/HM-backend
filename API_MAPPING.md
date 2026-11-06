# StayFlow frontend ↔ backend API mapping

The frontend calls the API through `src/services/api.js`; the base URL is `VITE_API_BASE_URL` (default `http://127.0.0.1:8000`). All data endpoints below require a bearer JWT unless marked health/public.

| Frontend module/action | Endpoint | Method | Database entities | State |
|---|---|---|---|---|
| Login | `/api/auth/login` | POST | `users` | Integrated |
| Session validation | `/api/auth/me` | GET | `users` | Integrated |
| Logout | `/api/auth/logout` | POST | JWT client-side discard | Integrated |
| Dashboard summary | `/api/dashboard` | GET | rooms, reservations, payments | Integrated |
| Room inventory | `/api/rooms` | GET | rooms, room_types | Integrated |
| Create room | `/api/rooms` | POST | rooms, room_types, audit_logs | Integrated |
| Housekeeping mark clean | `/api/rooms/{id}/status` | PATCH | rooms, reservations, audit_logs | Integrated |
| Room types | `/api/room-types` | GET/POST | room_types | API available; read integrated |
| Bookings list/search | `/api/bookings` | GET | reservations, guests, rooms, payments | Integrated |
| Create reservation | `/api/bookings` | POST | reservations, guests, rooms, offers | Integrated |
| Confirm/cancel/check-in/check-out | `/api/bookings/{reference}/status` | PATCH | reservations, rooms, audit_logs | Integrated |
| Guest directory | `/api/guests` | GET | guests | Integrated |
| Create guest | `/api/guests` | POST | guests, audit_logs | API available |
| Payment ledger | `/api/payments` | GET/POST | payments, reservations | Integrated |
| Offers list/create | `/api/offers` | GET/POST | offers | Integrated |
| Channel configuration | `/api/channels` | GET/POST/PATCH | booking_channels | Integrated as configuration only |
| Hotel settings | `/api/settings` | GET/PUT | hotel_settings | Integrated |
| Staff list/create | `/api/admin/users` | GET/POST | users, audit_logs | Integrated for admins |
| Occupancy report | `/api/reports/occupancy` | GET | reservations, rooms | Integrated |
| Audit logs | `/api/audit-logs` | GET | audit_logs | Integrated for admins |
| Provider webhooks | Not implemented | — | — | Placeholder only; provider credentials and event contracts required |
| Many nested sidebar sub-pages | Existing frontend routes | — | — | Existing UI retained; several are design/navigation placeholders, not standalone CRUD workflows |

## Security and data behavior
- Passwords are hashed; protected APIs require a JWT.
- PostgreSQL is the production database option; SQLite is for local development.
- Payment records are a ledger only. No real gateway transaction is simulated.
- MMT/Agoda/Booking.com/Expedia switches save local configuration only; they do not connect to the provider.
- No demo seed script is shipped. Use `python clear_demo_data.py` to remove sample data left behind by earlier versions.
