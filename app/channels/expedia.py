"""
Expedia Group EQC (Expedia QuickConnect) / EPS (Expedia Partner Solutions) Adapter.

Real Expedia API:
  - EQC API: https://services.expediapartnercentral.com
  - Auth:    Basic Auth (client_id as username, api_key as password)
  - Docs:    https://developers.expediagroup.com

Fields used: base_url, api_key, client_id, client_secret
"""
import httpx
from datetime import date, timedelta
import base64

from app.channels.base import ChannelAdapter, ChannelCredentials


class ExpediaAdapter(ChannelAdapter):
    name = "Expedia"

    def _base(self) -> str:
        return (self.creds.base_url or "https://services.expediapartnercentral.com").rstrip("/")

    def _auth_header(self) -> str:
        raw = f"{self.creds.client_id}:{self.creds.api_key}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def test_connection(self) -> dict:
        """Test via Expedia EQC ping / property endpoint."""
        url = self._base() + "/lodging/properties"
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url, headers=self._headers(), params={"offset": 0, "limit": 1})
            if r.status_code == 200:
                return {"ok": True, "message": "Expedia connection successful", "http_status": 200}
            elif r.status_code == 401:
                return {"ok": False, "message": "Expedia: Invalid credentials — check client_id and api_key (401)", "http_status": 401}
            elif r.status_code == 403:
                return {"ok": False, "message": "Expedia: Forbidden — your account may lack API access (403)", "http_status": 403}
            else:
                return {"ok": False, "message": f"Expedia API responded with HTTP {r.status_code}", "http_status": r.status_code}
        except httpx.ConnectError:
            return {"ok": False, "message": "Cannot reach Expedia API — check Base URL and network", "http_status": 0}
        except Exception as e:
            return {"ok": False, "message": f"Expedia error: {str(e)}", "http_status": 0}

    async def fetch_bookings(self) -> list[dict]:
        """Fetch reservations from Expedia EQC."""
        url = self._base() + "/lodging/reservations"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    url,
                    headers=self._headers(),
                    params={
                        "checkInDateFrom": date.today().isoformat(),
                        "checkInDateTo": (date.today() + timedelta(days=90)).isoformat(),
                    },
                )
            r.raise_for_status()
            data = r.json()
            reservations = data.get("entity", data if isinstance(data, list) else [])
            return [
                {
                    "channel_ref": str(b.get("id") or b.get("reservationId") or ""),
                    "guest_name": (b.get("primaryGuest") or {}).get("firstName", "") + " " + (b.get("primaryGuest") or {}).get("lastName", ""),
                    "guest_email": (b.get("primaryGuest") or {}).get("email") or "",
                    "room_type": b.get("roomTypeName") or "Standard",
                    "check_in": b.get("checkInDate") or "",
                    "check_out": b.get("checkOutDate") or "",
                    "total_amount": float((b.get("pricing") or {}).get("totalGuestAmount") or b.get("totalAmount") or 0),
                    "source": "Expedia",
                }
                for b in reservations
            ]
        except Exception:
            return []

    async def push_availability(self, rooms: list[dict], rates: list[dict]) -> dict:
        """Push rate/availability updates to Expedia EQC."""
        url = self._base() + "/lodging/properties/rates"
        try:
            payload = {
                "rates": [
                    {"roomTypeId": r.get("room_type_id"), "rateAmount": r.get("price"), "currency": "INR"}
                    for r in rates
                ]
            }
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(url, json=payload, headers=self._headers())
            if r.status_code in (200, 201, 202, 204):
                return {"ok": True, "pushed": len(rates), "message": "Rates pushed to Expedia"}
            return {"ok": False, "pushed": 0, "message": f"Expedia push failed: HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "pushed": 0, "message": str(e)}
