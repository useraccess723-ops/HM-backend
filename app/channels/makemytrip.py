"""
MakeMyTrip / BookMyTrip B2B Hotel API Channel Adapter.

Real MMT API:
  - Requires commercial partnership with MakeMyTrip / GoIbibo.
  - Auth: OAuth2 client_credentials flow using client_id + client_secret
  - Docs: Available only after signing the MMT partner agreement.

Fields used: base_url, api_key, client_id, client_secret
"""
import httpx
from datetime import date, timedelta

from app.channels.base import ChannelAdapter, ChannelCredentials


class MakeMyTripAdapter(ChannelAdapter):
    name = "MakeMyTrip"

    def _base(self) -> str:
        return (self.creds.base_url or "https://api.makemytrip.com").rstrip("/")

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        """Obtain OAuth2 bearer token via client_credentials grant."""
        r = await client.post(
            self._base() + "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.creds.client_id,
                "client_secret": self.creds.client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("access_token", "")

    async def test_connection(self) -> dict:
        """Test by attempting the OAuth token exchange."""
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                token = await self._get_token(client)
            if token:
                return {"ok": True, "message": "MakeMyTrip OAuth token obtained successfully", "http_status": 200}
            return {"ok": False, "message": "MakeMyTrip: Token exchange succeeded but returned empty token", "http_status": 200}
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            if sc == 401:
                return {"ok": False, "message": "MakeMyTrip: Invalid client_id or client_secret (401)", "http_status": sc}
            return {"ok": False, "message": f"MakeMyTrip: HTTP {sc}", "http_status": sc}
        except httpx.ConnectError:
            return {"ok": False, "message": "Cannot reach MakeMyTrip API — check Base URL and network", "http_status": 0}
        except Exception as e:
            return {"ok": False, "message": f"MakeMyTrip error: {str(e)}", "http_status": 0}

    async def fetch_bookings(self) -> list[dict]:
        """Fetch bookings from MMT partner portal."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                token = await self._get_token(client)
                r = await client.get(
                    self._base() + "/hotel/reservations",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Api-Key": self.creds.api_key,
                        "Accept": "application/json",
                    },
                    params={
                        "fromDate": date.today().isoformat(),
                        "toDate": (date.today() + timedelta(days=90)).isoformat(),
                    },
                )
            r.raise_for_status()
            data = r.json()
            bookings = data.get("reservations", data if isinstance(data, list) else [])
            return [
                {
                    "channel_ref": str(b.get("bookingId") or b.get("id") or ""),
                    "guest_name": b.get("guestName") or "MMT Guest",
                    "guest_email": b.get("guestEmail") or "",
                    "room_type": b.get("roomType") or "Standard",
                    "check_in": b.get("checkIn") or b.get("arrivalDate") or "",
                    "check_out": b.get("checkOut") or b.get("departureDate") or "",
                    "total_amount": float(b.get("totalAmount") or b.get("netAmount") or 0),
                    "source": "MakeMyTrip",
                }
                for b in bookings
            ]
        except Exception:
            return []

    async def push_availability(self, rooms: list[dict], rates: list[dict]) -> dict:
        """Push rates and availability to MakeMyTrip."""
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token = await self._get_token(client)
                payload = {
                    "roomRates": [
                        {"roomTypeId": r.get("room_type_id"), "rate": r.get("price"), "currency": "INR"}
                        for r in rates
                    ]
                }
                r = await client.post(
                    self._base() + "/hotel/rates",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "X-Api-Key": self.creds.api_key, "Accept": "application/json"},
                )
            if r.status_code in (200, 201, 202, 204):
                return {"ok": True, "pushed": len(rates), "message": "Rates pushed to MakeMyTrip"}
            return {"ok": False, "pushed": 0, "message": f"MakeMyTrip push failed: HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "pushed": 0, "message": str(e)}
