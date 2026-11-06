"""
Agoda YCS (Yield Control System) Channel Adapter.

Real Agoda API:
  - Base URL: https://sandbox-api.agoda.com  (sandbox)
                https://api.agoda.com         (production)
  - Auth: HMAC-SHA256 signed requests using api_key + client_secret
  - Docs: https://ycs.agoda.com/en-us/

Fields used: base_url, api_key, client_id, client_secret
"""
import hashlib
import hmac
import time
import httpx
from datetime import date, timedelta

from app.channels.base import ChannelAdapter, ChannelCredentials


def _agoda_headers(creds: ChannelCredentials, method: str, path: str) -> dict:
    """Build HMAC-signed Agoda YCS request headers."""
    timestamp = str(int(time.time()))
    string_to_sign = f"{creds.client_id}\n{timestamp}\n{method.upper()}\n{path}"
    signature = hmac.new(
        creds.client_secret.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "AgodaApiKey": creds.api_key,
        "AgodaClientId": creds.client_id,
        "AgodaTimestamp": timestamp,
        "AgodaSignature": signature,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class AgodaAdapter(ChannelAdapter):
    name = "Agoda"

    def _base(self) -> str:
        return (self.creds.base_url or "https://sandbox-api.agoda.com").rstrip("/")

    async def test_connection(self) -> dict:
        """Ping the Agoda YCS property info endpoint."""
        path = "/api/v2/property/info"
        url = self._base() + path
        try:
            headers = _agoda_headers(self.creds, "GET", path)
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return {"ok": True, "message": "Agoda connection successful", "http_status": 200}
            elif r.status_code == 401:
                return {"ok": False, "message": "Agoda: Invalid API key or signature (401)", "http_status": 401}
            elif r.status_code == 403:
                return {"ok": False, "message": "Agoda: Access forbidden — check Client ID permissions (403)", "http_status": 403}
            elif r.status_code == 404:
                return {"ok": False, "message": "Agoda: Property not found — verify your Client ID (404)", "http_status": 404}
            else:
                return {"ok": False, "message": f"Agoda API responded with HTTP {r.status_code}", "http_status": r.status_code}
        except httpx.ConnectError:
            return {"ok": False, "message": "Cannot reach Agoda API — check Base URL and network", "http_status": 0}
        except Exception as e:
            return {"ok": False, "message": f"Agoda error: {str(e)}", "http_status": 0}

    async def fetch_bookings(self) -> list[dict]:
        """Fetch reservations from Agoda for the next 90 days."""
        path = "/api/v2/reservations"
        url = self._base() + path
        params = {
            "fromDate": date.today().isoformat(),
            "toDate": (date.today() + timedelta(days=90)).isoformat(),
            "status": "Confirmed",
        }
        try:
            headers = _agoda_headers(self.creds, "GET", path)
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
            bookings = data.get("reservations", data if isinstance(data, list) else [])
            return [
                {
                    "channel_ref": str(b.get("reservationId") or b.get("bookingId") or ""),
                    "guest_name": b.get("guestName") or b.get("customerName") or "Agoda Guest",
                    "guest_email": b.get("guestEmail") or b.get("customerEmail") or "",
                    "room_type": b.get("roomTypeName") or b.get("roomType") or "Standard",
                    "check_in": b.get("checkInDate") or b.get("arrivalDate") or "",
                    "check_out": b.get("checkOutDate") or b.get("departureDate") or "",
                    "total_amount": float(b.get("totalPrice") or b.get("totalAmount") or 0),
                    "source": "Agoda",
                }
                for b in bookings
            ]
        except Exception:
            return []

    async def push_availability(self, rooms: list[dict], rates: list[dict]) -> dict:
        """Push rate and availability updates to Agoda YCS."""
        path = "/api/v2/rates"
        url = self._base() + path
        try:
            payload = {
                "rateUpdates": [
                    {"roomTypeId": r.get("room_type_id"), "rate": r.get("price"), "currency": "INR"}
                    for r in rates
                ]
            }
            headers = _agoda_headers(self.creds, "POST", path)
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(url, json=payload, headers=headers)
            if r.status_code in (200, 201, 202, 204):
                return {"ok": True, "pushed": len(rates), "message": "Rates pushed to Agoda"}
            return {"ok": False, "pushed": 0, "message": f"Agoda push failed: HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "pushed": 0, "message": str(e)}
