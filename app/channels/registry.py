"""
Channel Registry — maps channel names to their adapter implementations.
"""
from app.channels.base import ChannelAdapter, ChannelCredentials
from app.channels.agoda import AgodaAdapter
from app.channels.booking_com import BookingComAdapter
from app.channels.makemytrip import MakeMyTripAdapter
from app.channels.expedia import ExpediaAdapter


def _normalise(name: str) -> str:
    return name.lower().replace(" ", "").replace(".", "").replace("-", "").replace("/", "")


_REGISTRY: dict[str, type[ChannelAdapter]] = {
    "agoda": AgodaAdapter,
    "bookingcom": BookingComAdapter,
    "makemytrip": MakeMyTripAdapter,
    "bookmytrip": MakeMyTripAdapter,
    "expedia": ExpediaAdapter,
}


def get_adapter(channel_name: str, creds: ChannelCredentials) -> ChannelAdapter | None:
    """
    Return an instantiated adapter for the given channel name, or None if unknown.
    """
    key = _normalise(channel_name)
    cls = _REGISTRY.get(key)
    if cls is None:
        return None
    return cls(creds)


def build_creds(channel) -> ChannelCredentials:
    """Build a ChannelCredentials from a BookingChannel ORM object."""
    return ChannelCredentials(
        base_url=channel.base_url or "",
        api_key=channel.api_key or "",
        client_id=channel.client_id or "",
        client_secret=channel.client_secret or "",
        affiliate_id=channel.affiliate_id or "",
        api_token=channel.api_token or "",
    )
