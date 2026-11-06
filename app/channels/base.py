"""
Base channel adapter contract.
Every OTA integration must subclass ChannelAdapter and implement:
  - test_connection() -> dict
  - fetch_bookings()  -> list[dict]
  - push_availability(rooms, rates) -> dict
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ChannelCredentials:
    base_url: str = ""
    api_key: str = ""
    client_id: str = ""
    client_secret: str = ""
    affiliate_id: str = ""
    api_token: str = ""


class ChannelAdapter(ABC):
    name: str = "unknown"

    def __init__(self, creds: ChannelCredentials):
        self.creds = creds

    @abstractmethod
    async def test_connection(self) -> dict:
        """Ping the partner API. Return {"ok": bool, "message": str}."""

    @abstractmethod
    async def fetch_bookings(self) -> list[dict]:
        """
        Pull new/changed bookings from the partner.
        Each dict must contain at minimum:
          channel_ref, guest_name, guest_email, room_type,
          check_in (YYYY-MM-DD), check_out (YYYY-MM-DD), total_amount
        """

    @abstractmethod
    async def push_availability(self, rooms: list[dict], rates: list[dict]) -> dict:
        """
        Push room availability and rate updates to the channel.
        Return {"ok": bool, "pushed": int, "message": str}
        """
