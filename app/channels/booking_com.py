"""
Booking.com Demand API v3.3 Channel Adapter.

Real Booking.com API:
  - Sandbox: https://demandapi-sandbox.booking.com/3.3
  - Prod:    https://demandapi.booking.com/3.3
  - Auth:    Bearer token (api_token) + affiliate_id in header
  - Docs:    https://developers.booking.com/demand-api/content/reference

Fields used: base_url, affiliate_id, api_token
"""
import httpx
from datetime import date, timedelta

from app.channels.base import ChannelAdapter, ChannelCredentials


class BookingComAdapter(ChannelAdapter):
    name = "Booking.com"

    def _base(self) -> str:
        return (self.creds.base_url or "https://demandapi-sandbox.booking.com/3.3").rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.creds.api_token}",
            "X-Affiliate-Id": self.creds.affiliate_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def test_connection(self) -> dict:
        """Test Booking.com connection via accommodations listing endpoint."""
        url = self._base() + "/accommodations"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url, headers=self._headers(), params={"rows": 1})
            if r.status_code == 200:
                return {"ok": True, "message": "Booking.com connection successful", "http_status": 200}
            elif r.status_code == 401:
                return {"ok": False, "message": "Booking.com: Invalid API token (401) — check api_token", "http_status": 401}
            elif r.status_code == 403:
                return {"ok": False, "message": "Booking.com: Forbidden (403) — check Affiliate ID permissions", "http_status": 403}
            else:
                return {"ok": False, "message": f"Booking.com API responded with HTTP {r.status_code}: {r.text[:200]}", "http_status": r.status_code}
        except httpx.ConnectError:
            return {"ok": False, "message": "Cannot reach Booking.com API — check Base URL and network", "http_status": 0}
        except Exception as e:
            return {"ok": False, "message": f"Booking.com error: {str(e)}", "http_status": 0}

    async def fetch_bookings(self) -> list[dict]:
        """Fetch reservations from Booking.com Demand API."""
        url = self._base() + "/reservations"
        params = {
            "arrival_date_from": date.today().isoformat(),
            "arrival_date_to": (date.today() + timedelta(days=90)).isoformat(),
            "rows": 100,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            data = r.json()
            reservations = data.get("data", data if isinstance(data, list) else [])
            return [
                {
                    "channel_ref": str(b.get("id") or b.get("reservation_id") or ""),
                    "guest_name": (b.get("booker") or {}).get("name") or b.get("guest_name") or "Booking.com Guest",
                    "guest_email": (b.get("booker") or {}).get("email") or b.get("guest_email") or "",
                    "room_type": (b.get("room_details") or [{}])[0].get("room_name") or "Standard",
                    "check_in": b.get("arrival_date") or b.get("check_in") or "",
                    "check_out": b.get("departure_date") or b.get("check_out") or "",
                    "total_amount": float(b.get("price", {}).get("total") or b.get("total_amount") or 0),
                    "source": "Booking.com",
                }
                for b in reservations
            ]
        except Exception:
            return []

    async def push_availability(self, rooms: list[dict], rates: list[dict]) -> dict:
        """Push availability and rates to Booking.com."""
        url = self._base() + "/availability"
        try:
            payload = {
                "roomTypes": [
                    {
                        "id": r.get("room_type_id"),
                        "available": r.get("available", 1),
                        "rate": {"amount": r.get("price"), "currency": "INR"},
                    }
                    for r in rates
                ]
            }
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(url, json=payload, headers=self._headers())
            if r.status_code in (200, 201, 202, 204):
                return {"ok": True, "pushed": len(rates), "message": "Availability pushed to Booking.com"}
            return {"ok": False, "pushed": 0, "message": f"Booking.com push failed: HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "pushed": 0, "message": str(e)}
