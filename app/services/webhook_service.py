"""
StayFlow Webhook Management Service.
Handles:
1. Incoming Webhooks (MakeMyTrip, Agoda, Payment Gateways, Custom OTAs)
   - Ingests bookings, cancellations, payment updates, and modifications.
   - Automatically saves and associates guests, rooms, reservations, and payments in MySQL.
2. Outgoing Webhooks
   - Dispatches event notifications (booking.created, booking.cancelled, payment.captured, etc.) to registered URLs.
   - Signs payloads with HMAC-SHA256 signature when secret is configured.
   - Logs delivery status, HTTP response codes, latency, and payloads in MySQL database.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from secrets import token_hex, token_urlsafe
from typing import Optional, Any
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, or_

from app.core.config import settings
from app.models.entities import (
    Guest, Reservation, Room, RoomType, Payment, AuditLog,
    WebhookSubscription, WebhookDeliveryLog, OperationalRecord, BookingChannel
)

logger = logging.getLogger("stayflow.webhooks")

PROHIBITED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
    "metadata",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_utc_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    Serializes a database datetime to standard ISO 8601 UTC string with 'Z' suffix.
    Ensures that naive datetimes (e.g. from MySQL DATETIME columns) are explicitly
    marked as UTC so that API clients and browsers can accurately convert to local/hotel time.
    """
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.isoformat()
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s


def is_prohibited_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Returns True if the IP address belongs to loopback, private, link-local, reserved, or cloud metadata."""
    if (
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    ):
        return True
    ip_str = str(ip_obj)
    if ip_str in ("169.254.169.254", "100.100.100.200", "fd00:ec2::254"):
        return True
    return False


def validate_outgoing_url(url: str, allow_local: Optional[bool] = None) -> tuple[bool, Optional[str]]:
    """
    Validates an outgoing webhook destination URL to prevent SSRF and unsafe requests.
    Enforces scheme (HTTPS required in production), checks host against prohibited names,
    and performs DNS resolution to block private/loopback/cloud metadata IP addresses.
    """
    if not url or not isinstance(url, str):
        return False, "Destination URL is required"

    url = url.strip()
    if allow_local is None:
        allow_local = getattr(settings, "ALLOW_INTERNAL_WEBHOOK_URLS", False)

    # In local test mode or when allow_local is True, allow relative paths (e.g. /api/webhooks/...)
    if url.startswith("/"):
        if allow_local:
            return True, None
        return False, "Relative URL paths are not permitted as external webhook destinations"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, "URL scheme must be HTTP or HTTPS"

    if not parsed.hostname:
        return False, "URL must contain a valid hostname"

    if parsed.username or parsed.password:
        return False, "User credentials are not permitted in webhook destination URLs"

    hostname = parsed.hostname.lower().strip()

    is_prod = getattr(settings, "APP_ENV", "production").lower() in ("production", "prod")
    if is_prod and not allow_local and parsed.scheme != "https":
        return False, "Outgoing webhook URLs must use HTTPS in production"

    if hostname in PROHIBITED_HOSTNAMES or hostname.endswith(".localhost"):
        if not allow_local:
            return False, f"Destination hostname '{hostname}' is prohibited (internal/loopback target)"

    # Check if hostname is an IP address literal
    try:
        ip_direct = ipaddress.ip_address(hostname.strip("[]"))
        if is_prohibited_ip(ip_direct) and not allow_local:
            return False, f"Prohibited destination IP ({ip_direct}): Loopback, private, or cloud metadata addresses are not allowed"
        return True, None
    except ValueError:
        pass

    # Resolve hostname via DNS to prevent DNS rebinding to internal addresses
    try:
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addr_info = socket.getaddrinfo(hostname, target_port, proto=socket.IPPROTO_TCP)
        if not addr_info:
            return False, f"Could not resolve hostname '{hostname}'"

        for item in addr_info:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if is_prohibited_ip(ip_obj) and not allow_local:
                    return False, f"Resolved destination IP ({ip_str}) for '{hostname}' is a prohibited internal/loopback address"
            except ValueError:
                return False, f"Invalid resolved IP '{ip_str}'"
    except socket.gaierror as e:
        if not allow_local:
            return False, f"DNS resolution failed for '{hostname}': {e}"
    except Exception as e:
        if not allow_local:
            return False, f"Host validation failed: {e}"

    return True, None


def compute_signature(secret: str, payload_bytes: bytes) -> str:
    """Generate HMAC-SHA256 hex signature for outgoing webhook payload verification."""
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def calculate_subscription_success_rate(db: Session, channel_name: str, hotel_id: Optional[int] = None) -> str:
    """
    Calculates actual historical delivery success rate percentage for a webhook subscription
    scoped to a specific hotel_id based on real WebhookDeliveryLog entries in MySQL.
    Never returns fake or hardcoded values.
    """
    try:
        stmt_total = select(func.count(WebhookDeliveryLog.id)).where(
            WebhookDeliveryLog.channel == channel_name,
            WebhookDeliveryLog.direction == "outgoing"
        )
        if hotel_id is not None:
            stmt_total = stmt_total.where(WebhookDeliveryLog.hotel_id == hotel_id)
        total = db.scalar(stmt_total) or 0
        if total == 0:
            return "—"
        stmt_success = select(func.count(WebhookDeliveryLog.id)).where(
            WebhookDeliveryLog.channel == channel_name,
            WebhookDeliveryLog.direction == "outgoing",
            WebhookDeliveryLog.status == "Success"
        )
        if hotel_id is not None:
            stmt_success = stmt_success.where(WebhookDeliveryLog.hotel_id == hotel_id)
        success = db.scalar(stmt_success) or 0
        rate = (success / total) * 100.0
        return f"{rate:.1f}%"
    except Exception as e:
        logger.warning(f"Error calculating success rate for {channel_name} (hotel {hotel_id}): {e}")
        return "—"


async def execute_delivery_attempt(
    db: Session,
    log_id: int,
    is_manual_retry: bool = False
) -> dict:
    """
    Executes a signed HTTP POST delivery attempt for a queued WebhookDeliveryLog entry.
    Updates attempt counts, records real response status/latency/body, and implements
    bounded exponential retry calculation.
    """
    log_entry = db.get(WebhookDeliveryLog, log_id)
    if not log_entry:
        return {"id": log_id, "status": "Failed", "error": f"Log #{log_id} not found"}

    target_url = (log_entry.endpoint or "").strip()
    port = getattr(settings, "PORT", 8000) or 8000
    allow_internal = getattr(settings, "ALLOW_INTERNAL_WEBHOOK_URLS", False)

    if target_url.startswith("/"):
        if allow_internal:
            target_url = f"http://127.0.0.1:{port}{target_url}"
        else:
            log_entry.status = "Failed"
            log_entry.error_message = "SSRF_BLOCKED: Relative path not allowed in production without internal permissions"
            log_entry.response_code = 0
            log_entry.response_body = "Delivery blocked: Relative path prohibited"
            db.commit()
            return {"id": log_id, "status": "Failed", "error": log_entry.error_message, "response_code": 0}

    # SSRF Protection: Validate target destination URL
    is_safe, ssrf_err = validate_outgoing_url(target_url, allow_local=allow_internal)
    if not is_safe:
        logger.warning("SSRF blocked outgoing webhook delivery #%s to '%s': %s", log_id, target_url, ssrf_err)
        log_entry.status = "Failed"
        log_entry.error_message = f"SSRF_BLOCKED: {ssrf_err}"
        log_entry.response_code = 0
        log_entry.response_body = f"Delivery blocked by security policy: {ssrf_err}"
        db.commit()
        return {
            "id": log_id,
            "status": "Failed",
            "response_code": 0,
            "error": log_entry.error_message,
            "error_message": log_entry.error_message,
            "url": target_url,
        }

    raw_payload = log_entry.payload or "{}"
    payload_bytes = raw_payload.encode("utf-8")

    # Find subscription secret if available, fallback to settings.WEBHOOK_SECRET
    sub = db.scalar(
        select(WebhookSubscription).where(
            WebhookSubscription.name == log_entry.channel,
            WebhookSubscription.hotel_id == log_entry.hotel_id
        )
    )
    if sub and sub.url:
        sub_target = sub.url.strip()
        if sub_target.startswith("/") and allow_internal:
            sub_target = f"http://127.0.0.1:{port}{sub_target}"
        target_url = sub_target
        log_entry.endpoint = target_url

    # Secret handling: strictly require configured secret, never use hardcoded fallback
    secret = (sub.secret if sub and sub.secret else None) or getattr(settings, "WEBHOOK_SECRET", None) or None
    if not secret:
        logger.error(
            "Outgoing webhook delivery skipped: No signing secret configured for subscription '%s' (ID %s). Configure WEBHOOK_SECRET or subscription secret.",
            log_entry.channel,
            sub.id if sub else "N/A",
        )
        log_entry.status = "Failed"
        log_entry.error_message = "Configuration error: Missing required webhook signing secret"
        log_entry.response_code = 0
        log_entry.response_body = "Delivery aborted: Webhook signing secret is required but not configured"
        db.commit()
        return {
            "id": log_entry.id,
            "subscription_id": sub.id if sub else None,
            "name": log_entry.channel,
            "status": "Failed",
            "response_code": 0,
            "error": log_entry.error_message,
            "error_message": log_entry.error_message,
            "latency_ms": 0,
        }

    ts = str(int(time.time()))
    delivery_id = f"del_{token_hex(6)}"
    signature = compute_signature(secret, payload_bytes)

    # Build fresh signed headers
    try:
        existing_headers = json.loads(log_entry.request_headers) if log_entry.request_headers else {}
    except Exception:
        existing_headers = {}

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "StayFlow-Webhook-Dispatcher/2.0",
        "X-StayFlow-Event": log_entry.event_type,
        "X-StayFlow-Delivery": delivery_id,
        "X-StayFlow-Timestamp": ts,
        "X-StayFlow-Signature": f"sha256={signature}",
    }

    sub_name_lower = (log_entry.channel or "").lower()
    if "makemytrip" in sub_name_lower or "mmt" in sub_name_lower:
        headers["X-MMT-Auth-Token"] = secret
        headers["X-Partner-Id"] = "stayflow-pms"
        headers["Authorization"] = f"Bearer {secret}"
    elif "agoda" in sub_name_lower:
        headers["X-Agoda-Webhook-Token"] = secret
        headers["Authorization"] = f"Bearer {secret}"
    elif "payment" in sub_name_lower or "razorpay" in sub_name_lower or "stripe" in sub_name_lower:
        headers["X-Razorpay-Signature"] = signature
        headers["Stripe-Signature"] = f"t={ts},v1={signature}"
        headers["Authorization"] = f"Bearer {secret}"

    log_entry.request_headers = json.dumps(headers)
    log_entry.last_attempt_at = _utcnow()

    start_t = time.perf_counter()
    resp_code = 0
    resp_text = ""
    error_msg = None

    # follow_redirects=False prevents open redirect SSRF attacks
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        try:
            response = await client.post(target_url, content=payload_bytes, headers=headers)
            resp_code = response.status_code
            resp_text = response.text[:2000]
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            if 200 <= resp_code < 300:
                status_label = "Success"
                error_msg = None
            elif 300 <= resp_code < 400:
                status_label = "Failed"
                red_loc = response.headers.get("location") or "unknown"
                error_msg = f"HTTP {resp_code}: Automatic redirects are disabled for security. Target: {red_loc[:120]}"
            else:
                status_label = "Failed"
                error_msg = f"HTTP {resp_code}: {resp_text[:200]}"
        except (httpx.ConnectError, ConnectionRefusedError) as conn_exc:
            # When running in-process (e.g. pytest TestClient), port 8000 socket may not be listening;
            # route to internal ASGI app if targeting localhost
            if allow_internal and any(host in target_url for host in ("127.0.0.1", "localhost")):
                try:
                    from app.main import app as fastapi_app
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as in_proc_client:
                        parsed_path = target_url.replace(f"http://127.0.0.1:{port}", "").replace(f"http://localhost:{port}", "")
                        if not parsed_path.startswith("/"):
                            parsed_path = "/" + parsed_path
                        response = await in_proc_client.post(parsed_path, content=payload_bytes, headers=headers)
                        resp_code = response.status_code
                        resp_text = response.text[:2000]
                        latency_ms = int((time.perf_counter() - start_t) * 1000)
                        if 200 <= resp_code < 300:
                            status_label = "Success"
                            error_msg = None
                        else:
                            status_label = "Failed"
                            error_msg = f"HTTP {resp_code}: {resp_text[:200]}"
                except Exception as in_err:
                    latency_ms = int((time.perf_counter() - start_t) * 1000)
                    resp_code = 0
                    resp_text = f"Connection error: {str(conn_exc)[:400]}"
                    status_label = "Failed"
                    error_msg = f"Network connection error: {str(conn_exc)[:200]}"
            else:
                latency_ms = int((time.perf_counter() - start_t) * 1000)
                resp_code = 0
                resp_text = f"Connection error: {str(conn_exc)[:400]}"
                status_label = "Failed"
                error_msg = f"Network connection error: {str(conn_exc)[:200]}"
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_t) * 1000)
            resp_code = 0
            resp_text = f"Connection error: {str(exc)[:400]}"
            status_label = "Failed"
            error_msg = f"Network connection error: {str(exc)[:200]}"

    log_entry.latency_ms = latency_ms
    log_entry.response_code = resp_code
    log_entry.response_body = resp_text
    log_entry.error_message = error_msg

    if status_label == "Success":
        log_entry.status = "Success"
        log_entry.next_retry_at = None
    else:
        log_entry.retry_count += 1
        if log_entry.retry_count < log_entry.max_retries:
            log_entry.status = "Retrying"
            # Bounded exponential backoff: 30s * 2^(retry_count - 1)
            backoff_seconds = 30 * (2 ** (log_entry.retry_count - 1))
            log_entry.next_retry_at = _utcnow() + timedelta(seconds=backoff_seconds)
        else:
            log_entry.status = "Failed"
            log_entry.next_retry_at = None

    db.commit()

    if sub:
        sub.last_delivery = _utcnow()
        sub.success_rate = calculate_subscription_success_rate(db, sub.name, hotel_id=sub.hotel_id)
        db.commit()

    return {
        "id": log_entry.id,
        "subscription_id": sub.id if sub else None,
        "name": log_entry.channel,
        "channel": log_entry.channel,
        "url": log_entry.endpoint,
        "target_endpoint": target_url,
        "status": log_entry.status,
        "response_code": log_entry.response_code,
        "latency_ms": log_entry.latency_ms,
        "retry_count": log_entry.retry_count,
        "max_retries": log_entry.max_retries,
        "created_at": serialize_utc_datetime(log_entry.created_at),
        "last_attempt_at": serialize_utc_datetime(log_entry.last_attempt_at),
        "next_retry_at": serialize_utc_datetime(log_entry.next_retry_at),
        "error_message": log_entry.error_message,
        "success_rate": sub.success_rate if sub else "—",
        "response_body": log_entry.response_body[:200]
    }


async def process_pending_retries(db: Session, hotel_id: Optional[int] = None) -> list[dict]:
    """
    Finds queued outgoing webhook deliveries ready for automatic bounded retry
    and executes them.
    """
    now = _utcnow()
    stmt = select(WebhookDeliveryLog).where(
        WebhookDeliveryLog.direction == "outgoing",
        WebhookDeliveryLog.status.in_(["Retrying", "Failed"]),
        WebhookDeliveryLog.retry_count < WebhookDeliveryLog.max_retries,
        or_(WebhookDeliveryLog.next_retry_at <= now, WebhookDeliveryLog.next_retry_at.is_(None))
    )
    if hotel_id is not None:
        stmt = stmt.where(WebhookDeliveryLog.hotel_id == hotel_id)

    pending = db.scalars(stmt.order_by(WebhookDeliveryLog.id.asc())).all()

    results = []
    for log in pending:
        try:
            res = await execute_delivery_attempt(db, log.id)
            results.append(res)
        except Exception as exc:
            logger.warning("Error processing retry for log #%s: %s", log.id, exc)
    return results


async def dispatch_single_test_ping(db: Session, subscription_id: int) -> dict:
    """
    Dispatches an authentic test ping to a single webhook subscription.
    Verifies subscription validity, checks URL against SSRF policy, enqueues a delivery log,
    executes real HTTP delivery, and records actual outcomes without faking HTTP 200.
    """
    sub = db.get(WebhookSubscription, subscription_id)
    if not sub:
        return {
            "status": "failed",
            "subscription_id": subscription_id,
            "error": "Webhook subscription not found",
            "response_code": 404,
            "message": "Webhook subscription not found",
        }

    if getattr(sub, "type", "outgoing") == "incoming":
        return {
            "status": "info",
            "subscription_id": sub.id,
            "name": sub.name,
            "type": "incoming",
            "url": sub.url,
            "message": f"'{sub.name}' is an Inbound Receiver endpoint designed to receive external events sent to StayFlow. It does not dispatch outgoing test pings.",
        }

    target_url = (sub.url or "").strip()
    if not target_url:
        return {
            "status": "failed",
            "subscription_id": sub.id,
            "name": sub.name,
            "url": "",
            "error": "No destination URL configured for this webhook subscription",
            "response_code": 0,
            "message": "No destination URL configured for this webhook subscription",
        }

    allow_internal = getattr(settings, "ALLOW_INTERNAL_WEBHOOK_URLS", False)
    is_safe, ssrf_err = validate_outgoing_url(target_url, allow_local=allow_internal)
    if not is_safe:
        return {
            "status": "failed",
            "subscription_id": sub.id,
            "name": sub.name,
            "url": target_url,
            "error": f"Destination blocked by security policy: {ssrf_err}",
            "response_code": 0,
            "latency_ms": 0,
            "message": f"Test ping blocked by SSRF policy: {ssrf_err}",
        }

    test_payload = {
        "event": "ping.test",
        "timestamp": _utcnow().isoformat(),
        "subscription_id": sub.id,
        "subscription_name": sub.name,
        "hotel_id": sub.hotel_id,
        "message": "StayFlow test ping notification - connectivity verification",
    }

    log_entry = WebhookDeliveryLog(
        hotel_id=sub.hotel_id,
        direction="outgoing",
        channel=sub.name,
        event_type="ping.test",
        endpoint=target_url,
        payload=json.dumps(test_payload),
        status="Pending",
        retry_count=0,
        max_retries=1,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)

    result = await execute_delivery_attempt(db, log_entry.id)
    is_success = result.get("status") == "Success"

    return {
        "status": "success" if is_success else "failed",
        "subscription": sub.name,
        "subscription_id": sub.id,
        "url": sub.url,
        "response_code": result.get("response_code", 0),
        "latency_ms": result.get("latency_ms", 0),
        "error": result.get("error_message"),
        "result": result,
        "message": (
            f"Test ping delivered successfully to {sub.name} (HTTP {result.get('response_code')}, {result.get('latency_ms')}ms)"
            if is_success
            else f"Test ping delivery failed for {sub.name}: {result.get('error_message') or 'HTTP ' + str(result.get('response_code'))}"
        ),
    }


async def dispatch_outgoing_webhooks(
    db: Session,
    event_type: str,
    payload: dict,
    hotel_id: Optional[int] = None,
    origin_channel: str = "StayFlow PMS"
) -> list[dict]:
    """
    Finds active outgoing webhook subscriptions for this hotel and event_type,
    enqueues persistent delivery records in MySQL, dispatches real HTTP POST requests
    signed with HMAC-SHA256, and records response/status logging with bounded retries.
    """
    if not hotel_id:
        logger.warning(
            "Outgoing webhook dispatch for event '%s' aborted: missing or invalid hotel/tenant ID (%r)",
            event_type, hotel_id
        )
        return []

    clean_event = event_type.strip().lower()

    # Query active subscriptions for this hotel
    subscriptions = db.scalars(
        select(WebhookSubscription).where(
            WebhookSubscription.hotel_id == hotel_id,
            WebhookSubscription.status == "Active"
        )
    ).all()

    matching_subs = []
    for sub in subscriptions:
        sub_events = [ev.strip().lower() for ev in (sub.events or "").split(",") if ev.strip()]
        if (
            "*" in sub_events
            or "all" in sub_events
            or clean_event in sub_events
            or (clean_event == "booking.updated" and ("booking.modified" in sub_events or "booking.update" in sub_events))
            or (clean_event == "booking.modified" and ("booking.updated" in sub_events or "booking.update" in sub_events))
            or (clean_event == "payment.captured" and ("payment.updated" in sub_events or "payment.success" in sub_events))
        ):
            matching_subs.append(sub)

    if not matching_subs:
        return []

    results = []
    event_envelope = {
        "event": clean_event,
        "timestamp": _utcnow().isoformat(),
        "hotel_id": hotel_id,
        "source": origin_channel,
        "data": payload
    }
    raw_json = json.dumps(event_envelope, default=str)

    for sub in matching_subs:
        target_url = (sub.url or "").strip()
        port = getattr(settings, "PORT", 8000) or 8000
        if target_url.startswith("/"):
            target_url = f"http://127.0.0.1:{port}{target_url}"

        # 1. Enqueue persistent delivery log in MySQL (Status: Pending)
        log_entry = WebhookDeliveryLog(
            hotel_id=hotel_id,
            direction="outgoing",
            channel=sub.name,
            event_type=clean_event,
            endpoint=target_url,
            request_headers="{}",
            payload=raw_json,
            response_code=0,
            response_body="",
            status="Pending",
            latency_ms=0,
            retry_count=0,
            max_retries=3,
            last_attempt_at=_utcnow(),
            created_at=_utcnow()
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)

        # 2. Execute first signed delivery attempt
        attempt_res = await execute_delivery_attempt(db, log_entry.id)
        results.append(attempt_res)

    return results



def verify_incoming_webhook_auth(
    channel_name: str,
    raw_body: bytes,
    headers: dict,
    db: Session,
    secret_override: Optional[str] = None,
    hotel_id: Optional[int] = None
) -> tuple[bool, str, str]:
    """
    Verifies HMAC-SHA256 signature or authentication token for incoming webhook requests.
    Supports standard partner headers:
    - HMAC: X-StayFlow-Signature, X-Razorpay-Signature, Stripe-Signature, X-Hub-Signature-256, X-Signature
    - Token: X-MMT-Auth-Token, X-Agoda-Webhook-Token, X-Api-Key, Authorization
    Enforces strict signature verification in production environments.
    """
    h_lower = {str(k).lower(): str(v).strip() for k, v in headers.items()}

    # 1. Extract provided signature
    sig = (
        h_lower.get("x-stayflow-signature") or
        h_lower.get("x-signature") or
        h_lower.get("x-hub-signature-256") or
        h_lower.get("x-webhook-signature") or
        h_lower.get("x-razorpay-signature") or
        ""
    )
    if not sig and "stripe-signature" in h_lower:
        parts = dict(item.split("=", 1) for item in h_lower["stripe-signature"].split(",") if "=" in item)
        sig = parts.get("v1", "")

    if sig.startswith("sha256="):
        sig = sig[7:].strip()

    # 2. Extract provided token
    token = (
        h_lower.get("x-mmt-auth-token") or
        h_lower.get("x-agoda-webhook-token") or
        h_lower.get("x-api-key") or
        h_lower.get("authorization") or
        ""
    )
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    # 3. Collect authorized secrets dynamically from settings and database (NO hardcoded secrets)
    candidate_secrets = set()
    if secret_override and secret_override.strip():
        candidate_secrets.add(secret_override.strip())

    # Environment variables
    for env_secret in (
        getattr(settings, "WEBHOOK_SECRET", None),
        getattr(settings, "OUTGOING_WEBHOOK_SECRET", None),
        getattr(settings, "MAKEMYTRIP_API_KEY", None),
        getattr(settings, "MAKEMYTRIP_CLIENT_SECRET", None),
        getattr(settings, "AGODA_API_KEY", None),
        getattr(settings, "AGODA_CLIENT_SECRET", None),
        getattr(settings, "BOOKING_COM_API_TOKEN", None),
    ):
        if env_secret and str(env_secret).strip():
            candidate_secrets.add(str(env_secret).strip())

    try:
        from app.models.entities import WebhookSubscription, BookingChannel
        sub_stmt = select(WebhookSubscription).where(WebhookSubscription.secret.is_not(None))
        if hotel_id:
            sub_stmt = sub_stmt.where(WebhookSubscription.hotel_id == hotel_id)
        subs = db.scalars(sub_stmt).all()
        for s in subs:
            if s.secret and s.secret.strip():
                candidate_secrets.add(s.secret.strip())

        ch_stmt = select(BookingChannel)
        if hotel_id:
            ch_stmt = ch_stmt.where(BookingChannel.tenant_id == hotel_id)
        channels = db.scalars(ch_stmt).all()
        for ch in channels:
            for val in (ch.api_key, ch.api_token, ch.client_secret):
                if val and str(val).strip():
                    candidate_secrets.add(str(val).strip())
    except Exception as e:
        logger.warning(f"Error loading subscription secrets for webhook verification: {e}")

    # 4. If signature is provided, verify HMAC
    if sig:
        if not candidate_secrets:
            return False, "No webhook verification secret configured on server", sig
        for secret in candidate_secrets:
            if not secret:
                continue
            computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(computed.lower(), sig.lower()):
                return True, "HMAC-SHA256 signature verified successfully", sig
        return False, "Invalid signature: HMAC-SHA256 does not match authorized keys", sig

    # 5. If auth token is provided, verify token
    if token:
        if not candidate_secrets:
            return False, "No webhook authorization token configured on server", token
        for secret in candidate_secrets:
            if not secret:
                continue
            if hmac.compare_digest(secret, token):
                return True, f"Authentication token verified for {channel_name}", token
        return False, "Invalid authentication token: token does not match authorized keys", token

    # 6. Reject unsigned requests in production
    is_prod = getattr(settings, "APP_ENV", "production").lower() in ("production", "prod")
    if is_prod:
        return False, "Unauthorized: Valid webhook signature or authentication token required in production", "missing"

    # Allow unsigned webhooks ONLY in non-production (development / test)
    return True, "Unsigned request accepted (development/sandbox mode only - rejected in production)", "none"



def validate_incoming_payload(event_type: str, payload: dict, channel: str) -> tuple[bool, Optional[str], int]:
    """
    Validates inbound webhook payload schema and data constraints.
    Returns (is_valid, error_message, http_status_code).
    """
    if not isinstance(payload, dict) or not payload:
        return False, "Payload must be a non-empty JSON object", 400

    clean_ev = (event_type or "").lower().strip()

    if "cancel" in clean_ev:
        ref = (
            payload.get("booking_reference") or
            payload.get("reference") or
            payload.get("booking_id") or
            payload.get("channel_ref") or
            payload.get("channel_reference") or
            payload.get("id") or
            ""
        )
        if not str(ref).strip():
            return False, "Missing required booking identifier ('booking_reference' or 'reference') for cancellation", 400
        return True, None, 200

    elif "payment" in clean_ev:
        ref = (
            payload.get("booking_reference") or
            payload.get("reference") or
            payload.get("booking_id") or
            payload.get("channel_ref") or
            ""
        )
        if not str(ref).strip():
            return False, "Missing required booking identifier ('booking_reference' or 'reference') for payment update", 400
        amt = payload.get("amount") or payload.get("paid_amount")
        if amt is not None:
            try:
                if float(amt) < 0:
                    return False, "Payment amount cannot be negative", 400
            except (ValueError, TypeError):
                return False, f"Invalid payment amount: '{amt}' is not a numeric value", 400
        return True, None, 200

    elif "modifi" in clean_ev or "update" in clean_ev:
        ref = (payload.get("booking_reference") or payload.get("reference") or payload.get("channel_ref") or "")
        if not str(ref).strip():
            return False, "Missing required booking identifier ('booking_reference' or 'reference') for modification", 400
        cin = payload.get("check_in")
        cout = payload.get("check_out")
        if cin and cout:
            try:
                d_in = datetime.strptime(str(cin)[:10], "%Y-%m-%d").date()
                d_out = datetime.strptime(str(cout)[:10], "%Y-%m-%d").date()
                if d_out <= d_in:
                    return False, "Check-out date must be strictly after check-in date", 400
            except Exception as e:
                return False, f"Invalid stay date format: {e}", 400
        return True, None, 200

    else:
        # Default / booking.created
        cin = payload.get("check_in") or payload.get("arrival_date") or payload.get("start_date")
        cout = payload.get("check_out") or payload.get("departure_date") or payload.get("end_date")
        if not cin or not cout:
            return False, "Missing required stay dates: 'check_in' and 'check_out' (YYYY-MM-DD) are required", 400
        try:
            d_in = datetime.strptime(str(cin)[:10], "%Y-%m-%d").date()
            d_out = datetime.strptime(str(cout)[:10], "%Y-%m-%d").date()
        except Exception as e:
            return False, f"Invalid date format for stay dates (expected YYYY-MM-DD): {e}", 400

        if d_out <= d_in:
            return False, f"Check-out date ({d_out}) must be strictly after check-in date ({d_in})", 400

        guest_field = payload.get("guest")
        if isinstance(guest_field, dict):
            guest_name = guest_field.get("full_name") or guest_field.get("name") or (f"{guest_field.get('first_name', '')} {guest_field.get('last_name', '')}".strip() if (guest_field.get('first_name') or guest_field.get('last_name')) else None)
        elif isinstance(guest_field, str):
            guest_name = guest_field.strip()
        else:
            guest_name = (
                payload.get("guest_name") or
                payload.get("customer_name") or
                (f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip() if (payload.get('first_name') or payload.get('last_name')) else None)
            )

        if guest_name is not None and not str(guest_name).strip():
            return False, "Guest name cannot be empty when provided", 400

        guests_cnt = payload.get("num_guests") or payload.get("guests") or payload.get("guest_count")
        if guests_cnt is not None:
            try:
                if int(guests_cnt) < 1:
                    return False, "Number of guests must be at least 1", 400
            except (ValueError, TypeError):
                return False, f"Invalid number of guests: '{guests_cnt}' is not an integer", 400

        amt = payload.get("total_amount") or payload.get("amount") or payload.get("price")
        if amt is not None:
            try:
                if float(amt) < 0:
                    return False, "Total amount cannot be negative", 400
            except (ValueError, TypeError):
                return False, f"Invalid total amount: '{amt}' is not a numeric value", 400

        return True, None, 200


def process_incoming_webhook(
    db: Session,
    channel_name: str,
    payload: dict,
    headers: Optional[dict] = None,
    hotel_id: int = 1,
    raw_body: Optional[bytes] = None
) -> dict:
    """
    Validates and executes incoming webhook actions:
    1. Signature & Authentication Verification
    2. Payload Validation & Event Routing
    3. Tenant & Channel Mapping
    4. MySQL Transaction (Guest, Room, Reservation, Payment, Audit Log, Delivery Log)
    5. Returns result structure updating Reservations & Bookings
    """
    start_time = time.perf_counter()
    headers = headers or {}
    raw_json = json.dumps(payload, default=str)
    raw_bytes = raw_body if raw_body is not None else raw_json.encode("utf-8")

    # 1. Tenant & Channel Mapping
    tenant_hotel_id = int(
        payload.get("hotel_id") or
        payload.get("property_id") or
        headers.get("x-hotel-id") or
        headers.get("x-property-id") or
        hotel_id or 1
    )

    clean_channel = (channel_name or payload.get("source") or payload.get("channel") or "MakeMyTrip").strip()
    c_lower = clean_channel.lower()
    if c_lower in ("mmt", "makemytrip"):
        clean_channel = "MakeMyTrip"
    elif c_lower in ("agoda", "agoda_connect"):
        clean_channel = "Agoda"
    elif c_lower in ("booking", "booking.com", "booking_com"):
        clean_channel = "Booking.com"
    elif c_lower in ("expedia", "expedia_group"):
        clean_channel = "Expedia"
    elif c_lower in ("payment", "razorpay"):
        clean_channel = "Razorpay"
    elif c_lower in ("stripe",):
        clean_channel = "Stripe"
    elif c_lower in ("paymentgateway", "payment_gateway"):
        clean_channel = "PaymentGateway"

    # 2. Determine Event Type
    event_type = (
        payload.get("event") or
        payload.get("event_type") or
        payload.get("action") or
        headers.get("x-event-type") or
        headers.get("x-stayflow-event") or
        ""
    ).lower().strip()

    if not event_type:
        if payload.get("status") in ("cancelled", "canceled") or payload.get("cancellation_reason"):
            event_type = "booking.cancelled"
        elif payload.get("payment_status") and not payload.get("check_in"):
            event_type = "payment.updated"
        elif payload.get("modification") or ("check_in" in payload and payload.get("booking_reference")):
            event_type = "booking.modified"
        else:
            event_type = "booking.created"

    # 3. Signature & Authentication Verification
    auth_valid, auth_reason, sig_used = verify_incoming_webhook_auth(
        channel_name=clean_channel,
        raw_body=raw_bytes,
        headers=headers,
        db=db
    )
    if not auth_valid:
        latency = int((time.perf_counter() - start_time) * 1000)
        log_incoming_event(
            db=db,
            hotel_id=tenant_hotel_id,
            channel=clean_channel,
            event_type=event_type or "unauthorized",
            payload=payload,
            code=401,
            message=f"Authentication failed: {auth_reason}",
            status="Failed",
            headers=headers,
            latency_ms=latency
        )
        return {
            "status": "error",
            "http_code": 401,
            "error_code": "AUTH_FAILED",
            "message": f"Webhook signature or authentication verification failed: {auth_reason}",
            "channel": clean_channel,
            "event": event_type
        }

    # 4. Payload Validation
    val_valid, val_err, val_code = validate_incoming_payload(event_type, payload, clean_channel)
    if not val_valid:
        latency = int((time.perf_counter() - start_time) * 1000)
        log_incoming_event(
            db=db,
            hotel_id=tenant_hotel_id,
            channel=clean_channel,
            event_type=event_type,
            payload=payload,
            code=val_code,
            message=f"Payload validation failed: {val_err}",
            status="Failed",
            headers=headers,
            latency_ms=latency
        )
        return {
            "status": "error",
            "http_code": val_code,
            "error_code": "VALIDATION_FAILED",
            "message": val_err,
            "channel": clean_channel,
            "event": event_type
        }

    # --- ROUTE BY EVENT TYPE (WITH TRANSACTION SAFETY) ---
    try:
        # ──────────────────────────────────────────────────────────────────────────
        # CASE 1: CANCELLATION
        # ──────────────────────────────────────────────────────────────────────────
        if "cancel" in event_type:
            ref = (
                payload.get("booking_reference") or
                payload.get("reference") or
                payload.get("booking_id") or
                payload.get("channel_ref") or
                payload.get("channel_reference") or
                payload.get("id") or
                ""
            ).strip()

            res = None
            if ref:
                res = db.scalar(
                    select(Reservation).where(
                        or_(
                            Reservation.reference == ref,
                            Reservation.channel_ref == ref
                        ),
                        Reservation.tenant_id == tenant_hotel_id
                    )
                )

            if not res:
                log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 404, f"Reservation '{ref}' not found for cancellation in hotel {tenant_hotel_id}", "Failed", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))
                return {
                    "status": "error",
                    "http_code": 404,
                    "message": f"Reservation '{ref}' not found for cancellation",
                    "channel": clean_channel,
                    "event": event_type
                }

            res.status = "Cancelled"
            if res.room and res.room.status == "res":
                res.room.status = "vac"

            # Update payment status if paid
            for p in db.scalars(select(Payment).where(Payment.reservation_id == res.id)).all():
                if p.status in ("Paid", "Completed"):
                    p.status = "Refunded"

            db.add(AuditLog(
                tenant_id=tenant_hotel_id,
                actor_email=f"webhook.{clean_channel.lower()}",
                action="booking.webhook_cancelled",
                entity_type="reservation",
                entity_id=str(res.id),
                detail=f"Reservation {res.reference} cancelled via {clean_channel} webhook"
            ))
            db.commit()

            log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 200, f"Reservation {res.reference} successfully cancelled", "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))

            return {
                "status": "success",
                "message": f"Reservation {res.reference} has been cancelled successfully",
                "booking_reference": res.reference,
                "guest_name": res.guest.full_name if res.guest else "",
                "reservation_status": "Cancelled",
                "hotel_id": tenant_hotel_id
            }

        # ──────────────────────────────────────────────────────────────────────────
        # CASE 2: PAYMENT UPDATE
        # ──────────────────────────────────────────────────────────────────────────
        elif "payment" in event_type:
            ref = (
                payload.get("booking_reference") or
                payload.get("reference") or
                payload.get("booking_id") or
                payload.get("channel_ref") or
                ""
            ).strip()

            res = db.scalar(select(Reservation).where(
                or_(Reservation.reference == ref, Reservation.channel_ref == ref),
                Reservation.tenant_id == tenant_hotel_id
            ))
            if not res:
                log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 404, f"Reservation '{ref}' not found for payment in hotel {tenant_hotel_id}", "Failed", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))
                return {"status": "error", "http_code": 404, "message": f"Reservation '{ref}' not found"}

            amt = Decimal(str(payload.get("amount") or payload.get("paid_amount") or res.total_amount or "0.00"))
            method = str(payload.get("method") or payload.get("payment_method") or "UPI")
            txn_ref = str(payload.get("transaction_id") or payload.get("txn_id") or payload.get("transaction_reference") or f"TXN-{token_hex(4).upper()}")
            pay_st = "Paid" if str(payload.get("payment_status", "Paid")).lower() in ("paid", "completed", "captured", "success") else "Pending"

            # Deduplication check: prevent duplicate payment records using transaction reference
            existing_payment = db.scalar(select(Payment).where(Payment.transaction_reference == txn_ref))
            if existing_payment:
                log_incoming_event(
                    db, tenant_hotel_id, clean_channel, event_type, payload, 200,
                    f"Duplicate payment transaction {txn_ref} skipped (already recorded for {res.reference})",
                    "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000)
                )
                return {
                    "status": "success",
                    "message": f"Payment transaction {txn_ref} already recorded for booking {res.reference}",
                    "booking_reference": res.reference,
                    "transaction_reference": txn_ref,
                    "payment_status": existing_payment.status,
                    "is_duplicate": True,
                    "hotel_id": tenant_hotel_id
                }

            payment = Payment(
                tenant_id=tenant_hotel_id,
                reservation_id=res.id,
                amount=amt,
                method=method,
                status=pay_st,
                transaction_reference=txn_ref
            )
            db.add(payment)
            db.commit()

            log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 200, f"Recorded payment ₹{amt} ({txn_ref}) for {res.reference}", "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))

            return {
                "status": "success",
                "message": f"Payment of ₹{amt:.2f} recorded for booking {res.reference}",
                "booking_reference": res.reference,
                "transaction_reference": txn_ref,
                "payment_status": pay_st,
                "hotel_id": tenant_hotel_id
            }

        # ──────────────────────────────────────────────────────────────────────────
        # CASE 3: RESERVATION MODIFICATION
        # ──────────────────────────────────────────────────────────────────────────
        elif "modifi" in event_type or "update" in event_type:
            ref = (payload.get("booking_reference") or payload.get("reference") or payload.get("channel_ref") or "").strip()
            res = db.scalar(select(Reservation).where(
                or_(Reservation.reference == ref, Reservation.channel_ref == ref),
                Reservation.tenant_id == tenant_hotel_id
            ))
            if not res:
                log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 404, f"Reservation '{ref}' not found for update in hotel {tenant_hotel_id}", "Failed", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))
                return {"status": "error", "http_code": 404, "message": f"Reservation '{ref}' not found"}

            if payload.get("check_in"):
                res.check_in = datetime.strptime(str(payload["check_in"])[:10], "%Y-%m-%d").date()
            if payload.get("check_out"):
                res.check_out = datetime.strptime(str(payload["check_out"])[:10], "%Y-%m-%d").date()
            if payload.get("total_amount"):
                res.total_amount = Decimal(str(payload["total_amount"]))

            res.status = "Modified"
            db.commit()

            log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 200, f"Reservation {res.reference} modified via webhook", "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000))
            return {
                "status": "success",
                "message": f"Reservation {res.reference} updated",
                "booking_reference": res.reference,
                "check_in": str(res.check_in),
                "check_out": str(res.check_out),
                "status": res.status,
                "hotel_id": tenant_hotel_id
            }

        # ──────────────────────────────────────────────────────────────────────────
        # CASE 4: NEW BOOKING (Default / booking.created)
        # ──────────────────────────────────────────────────────────────────────────
        channel_ref = str(
            payload.get("channel_ref") or
            payload.get("channel_reference") or
            payload.get("booking_id") or
            payload.get("reservation_id") or
            payload.get("id") or
            ""
        ).strip()

        idempotency_key = (
            headers.get("x-idempotency-key") or
            headers.get("idempotency-key") or
            headers.get("x-delivery-id") or
            headers.get("x-event-id") or
            payload.get("idempotency_key") or
            payload.get("delivery_id") or
            payload.get("event_id") or
            ""
        )
        if isinstance(idempotency_key, (int, str)):
            idempotency_key = str(idempotency_key).strip()
        else:
            idempotency_key = ""

        effective_ref = channel_ref or idempotency_key

        # Deduplication check via external channel reference or idempotency token
        if effective_ref:
            existing = db.scalar(select(Reservation).where(
                Reservation.channel_ref == effective_ref,
                Reservation.tenant_id == tenant_hotel_id
            ))
            if existing:
                log_incoming_event(
                    db, tenant_hotel_id, clean_channel, event_type, payload, 200,
                    f"Duplicate booking {effective_ref} skipped (already exists as {existing.reference})",
                    "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000)
                )
                return {
                    "status": "success",
                    "message": f"Booking already processed ({existing.reference})",
                    "booking_reference": existing.reference,
                    "reservation_id": existing.id,
                    "guest_name": existing.guest.full_name if existing.guest else "",
                    "room_number": existing.room.number if existing.room else "",
                    "check_in": str(existing.check_in),
                    "check_out": str(existing.check_out),
                    "source": existing.source,
                    "is_duplicate": True,
                    "hotel_id": tenant_hotel_id
                }

        # Parse dates
        cin_raw = payload.get("check_in") or payload.get("arrival_date") or payload.get("start_date") or str(date.today())
        cout_raw = payload.get("check_out") or payload.get("departure_date") or payload.get("end_date") or str(date.today() + datetime.resolution * 2)
        try:
            check_in = datetime.strptime(str(cin_raw)[:10], "%Y-%m-%d").date()
            check_out = datetime.strptime(str(cout_raw)[:10], "%Y-%m-%d").date()
        except Exception as e:
            log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 400, f"Invalid stay dates: {e}", "Failed", headers=headers)
            return {"status": "error", "http_code": 400, "message": f"Invalid date format: {e}"}

        if check_out <= check_in:
            log_incoming_event(db, tenant_hotel_id, clean_channel, event_type, payload, 400, "Check-out must be after check-in", "Failed", headers=headers)
            return {"status": "error", "http_code": 400, "message": "Check-out date must be strictly after check-in date"}

        guest_field = payload.get("guest")
        if isinstance(guest_field, dict):
            guest_name = (
                guest_field.get("full_name") or
                guest_field.get("name") or
                f"{guest_field.get('first_name', '')} {guest_field.get('last_name', '')}".strip() or
                f"Guest from {clean_channel}"
            ).strip()
            guest_email = (guest_field.get("email") or payload.get("guest_email") or payload.get("email") or "").strip().lower()
            guest_phone = (guest_field.get("phone") or guest_field.get("mobile") or payload.get("guest_phone") or payload.get("phone") or payload.get("mobile") or "").strip()
        else:
            guest_name = (
                payload.get("guest_name") or
                payload.get("customer_name") or
                (f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip() if (payload.get('first_name') or payload.get('last_name')) else "") or
                (str(guest_field).strip() if isinstance(guest_field, str) else "") or
                f"Guest from {clean_channel}"
            ).strip()
            guest_email = (payload.get("guest_email") or payload.get("email") or "").strip().lower()
            guest_phone = (payload.get("guest_phone") or payload.get("phone") or payload.get("mobile") or "").strip()

        # Scoped guest lookup strictly by hotel tenant ID (prevent cross-tenant data leakage)
        guest = None
        if guest_phone:
            guest = db.scalar(select(Guest).where(Guest.phone == guest_phone, Guest.tenant_id == tenant_hotel_id))
        if not guest and guest_email:
            guest = db.scalar(select(Guest).where(Guest.email == guest_email, Guest.tenant_id == tenant_hotel_id))

        if not guest:
            guest = Guest(
                tenant_id=tenant_hotel_id,
                full_name=guest_name,
                email=guest_email or None,
                phone=guest_phone or "",
                identification_number=str(payload.get("id_proof", "")),
                notes=f"Created automatically via {clean_channel} webhook",
                qr_token=token_urlsafe(16)
            )
            db.add(guest)
            db.flush()
        else:
            # Keep guest info updated with latest contact details
            if guest_name and guest.full_name.startswith("Guest from"):
                guest.full_name = guest_name
            if guest_phone and not guest.phone:
                guest.phone = guest_phone
            if guest_email and not guest.email:
                guest.email = guest_email

        # Deduplication check for replayed events without external booking reference:
        # Check if identical reservation was created for this guest and dates within the last 15 minutes
        time_threshold = _utcnow() - timedelta(minutes=15)
        existing_recent = db.scalar(
            select(Reservation).where(
                Reservation.tenant_id == tenant_hotel_id,
                Reservation.guest_id == guest.id,
                Reservation.check_in == check_in,
                Reservation.check_out == check_out,
                Reservation.source == clean_channel,
                Reservation.created_at >= time_threshold
            ).order_by(Reservation.id.desc())
        )
        if existing_recent:
            log_incoming_event(
                db, tenant_hotel_id, clean_channel, event_type, payload, 200,
                f"Duplicate booking event without external reference skipped (matches {existing_recent.reference})",
                "Success", headers=headers, latency_ms=int((time.perf_counter() - start_time) * 1000)
            )
            return {
                "status": "success",
                "message": f"Duplicate booking event replayed and skipped ({existing_recent.reference})",
                "booking_reference": existing_recent.reference,
                "reservation_id": existing_recent.id,
                "guest_name": guest.full_name,
                "room_number": existing_recent.room.number if existing_recent.room else "",
                "check_in": str(existing_recent.check_in),
                "check_out": str(existing_recent.check_out),
                "source": existing_recent.source,
                "is_duplicate": True
            }

        # 2. Find matching Room & RoomType strictly within this hotel tenant
        room_type_name = str(payload.get("room_type") or payload.get("room_name") or "").strip()
        rt = None
        if room_type_name:
            rt = db.scalar(select(RoomType).where(RoomType.name.ilike(f"%{room_type_name}%"), RoomType.tenant_id == tenant_hotel_id))
        if not rt:
            rt = db.scalar(select(RoomType).where(RoomType.tenant_id == tenant_hotel_id))

        # Room selection without date conflict (strictly scoped to tenant_hotel_id)
        assigned_room = None
        requested_room_num = str(payload.get("room_number") or "").strip()
        if requested_room_num:
            r_cand = db.scalar(select(Room).where(Room.number == requested_room_num, Room.tenant_id == tenant_hotel_id))
            if r_cand:
                conflict = db.scalar(select(Reservation.id).where(
                    Reservation.room_id == r_cand.id,
                    Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"]),
                    Reservation.check_in < check_out,
                    Reservation.check_out > check_in,
                ).limit(1))
                if not conflict:
                    assigned_room = r_cand

        if not assigned_room and rt:
            candidate_rooms = db.scalars(select(Room).where(Room.room_type_id == rt.id, Room.tenant_id == tenant_hotel_id)).all()
            for r in candidate_rooms:
                if r.status in ("dirty", "ooo"):
                    continue
                conflict = db.scalar(select(Reservation.id).where(
                    Reservation.room_id == r.id,
                    Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"]),
                    Reservation.check_in < check_out,
                    Reservation.check_out > check_in,
                ).limit(1))
                if not conflict:
                    assigned_room = r
                    break

            if not assigned_room and candidate_rooms:
                assigned_room = candidate_rooms[0]

        if not assigned_room:
            # Fallback only to rooms strictly within the validated hotel tenant
            all_hotel_rooms = db.scalars(select(Room).where(Room.tenant_id == tenant_hotel_id)).all()
            for r in all_hotel_rooms:
                if r.status in ("dirty", "ooo"):
                    continue
                conflict = db.scalar(select(Reservation.id).where(
                    Reservation.room_id == r.id,
                    Reservation.status.in_(["Pending", "Confirmed", "Modified", "Checked-in"]),
                    Reservation.check_in < check_out,
                    Reservation.check_out > check_in,
                ).limit(1))
                if not conflict:
                    assigned_room = r
                    break
            if not assigned_room and all_hotel_rooms:
                assigned_room = all_hotel_rooms[0]

        # Enforce multi-tenant isolation: reject if no rooms exist for this hotel
        if not assigned_room:
            db.rollback()
            latency = int((time.perf_counter() - start_time) * 1000)
            log_incoming_event(
                db, tenant_hotel_id, clean_channel, event_type, payload, 422,
                f"No rooms configured or available for hotel ID {tenant_hotel_id}",
                "Failed", headers=headers, latency_ms=latency
            )
            return {
                "status": "error",
                "http_code": 422,
                "error_code": "NO_ROOMS_AVAILABLE",
                "message": f"No rooms configured or available for hotel ID {tenant_hotel_id}. Cross-tenant room assignment is rejected."
            }

        # 3. Generate Unique Booking Reference
        prefix = clean_channel[:3].upper().replace(".", "")
        if prefix in ("MAK", "MMT"):
            prefix = "MMT"
        elif prefix in ("AGO", "AGODA"):
            prefix = "AGO"
        
        unique_suffix = "".join(ch for ch in (channel_ref or token_hex(3)) if ch.isalnum())[-6:].upper()
        ref = f"{prefix}-{unique_suffix}"
        while db.scalar(select(Reservation.id).where(Reservation.reference == ref)):
            ref = f"{prefix}-{token_hex(3).upper()}"

        # Calculate Total Price
        raw_amount = float(payload.get("total_amount") or payload.get("amount") or payload.get("price") or 0.0)
        if raw_amount <= 0.0 and assigned_room and assigned_room.room_type:
            nights = max(1, (check_out - check_in).days)
            raw_amount = float(assigned_room.room_type.base_price) * nights

        num_guests = int(payload.get("num_guests") or payload.get("guests") or payload.get("guest_count") or 1)

        # 4. Create Reservation in MySQL Database
        reservation = Reservation(
            tenant_id=tenant_hotel_id,
            reference=ref,
            guest_id=guest.id,
            room_id=assigned_room.id,
            check_in=check_in,
            check_out=check_out,
            status="Confirmed",
            source=clean_channel,
            total_amount=Decimal(str(raw_amount)),
            channel_ref=channel_ref or idempotency_key or ref,
            num_guests=num_guests
        )
        db.add(reservation)
        db.flush()

        # Update Room Status
        today = date.today()
        if check_in <= today < check_out and assigned_room and assigned_room.status == "vac":
            assigned_room.status = "res"

        # 5. Record Payment if provided (with transaction_reference uniqueness check)
        pay_status = str(payload.get("payment_status") or "").lower()
        is_prepaid = pay_status in ("paid", "completed", "captured", "success") or "payment" in payload
        payment_rec = None
        if is_prepaid or payload.get("transaction_id") or payload.get("txn_id"):
            pay_method = str(payload.get("payment_method") or payload.get("method") or f"{clean_channel} Direct")
            txn_id = str(payload.get("transaction_id") or payload.get("txn_id") or f"TXN-{ref}-{token_hex(2).upper()}")
            
            existing_pay = db.scalar(select(Payment).where(Payment.transaction_reference == txn_id))
            if not existing_pay:
                payment_rec = Payment(
                    tenant_id=tenant_hotel_id,
                    reservation_id=reservation.id,
                    amount=Decimal(str(raw_amount)),
                    method=pay_method,
                    status="Paid",
                    transaction_reference=txn_id
                )
                db.add(payment_rec)
                db.flush()
            else:
                payment_rec = existing_pay

        # 6. Audit Trail
        db.add(AuditLog(
            tenant_id=tenant_hotel_id,
            actor_email=f"webhook.{clean_channel.lower()}",
            action="channel.booking_imported",
            entity_type="reservation",
            entity_id=str(reservation.id),
            detail=f"Imported from {clean_channel} (ref {ref}, channel_ref {channel_ref or idempotency_key}, ₹{raw_amount})"
        ))
        db.commit()

        # 7. Log incoming webhook
        log_incoming_event(
            db, tenant_hotel_id, clean_channel, event_type, payload, 201,
            f"Booking {ref} created successfully for {guest.full_name} in Room {assigned_room.number if assigned_room else 'TBD'}",
            "Success",
            headers=headers,
            latency_ms=int((time.perf_counter() - start_time) * 1000)
        )

        return {
            "status": "success",
            "message": f"Booking successfully imported from {clean_channel}",
            "booking_reference": reservation.reference,
            "reservation_id": reservation.id,
            "hotel_id": tenant_hotel_id,
            "guest": {
                "id": guest.id,
                "full_name": guest.full_name,
                "email": guest.email,
                "phone": guest.phone
            },
            "room": {
                "id": assigned_room.id if assigned_room else None,
                "number": assigned_room.number if assigned_room else "Unassigned",
                "type": assigned_room.room_type.name if (assigned_room and assigned_room.room_type) else "Standard"
            },
            "stay": {
                "check_in": str(reservation.check_in),
                "check_out": str(reservation.check_out),
                "nights": (reservation.check_out - reservation.check_in).days
            },
            "source": clean_channel,
            "total_amount": float(reservation.total_amount),
            "payment_status": "Paid" if payment_rec else "Pending"
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error processing incoming webhook: %s", exc)
        latency = int((time.perf_counter() - start_time) * 1000)
        log_incoming_event(
            db,
            tenant_hotel_id,
            clean_channel,
            event_type or "error",
            payload,
            500,
            f"Internal processing error: {str(exc)}",
            "Failed",
            headers=headers,
            latency_ms=latency
        )
        return {
            "status": "error",
            "http_code": 500,
            "error_code": "INTERNAL_ERROR",
            "message": f"Webhook processing encountered a database or runtime error: {str(exc)}",
            "channel": clean_channel,
            "event": event_type
        }


def log_incoming_event(
    db: Session,
    hotel_id: int,
    channel: str,
    event_type: str,
    payload: dict,
    code: int,
    message: str,
    status: str,
    headers: Optional[dict] = None,
    latency_ms: int = 15
):
    """Helper to record incoming webhook execution in webhook_delivery_logs."""
    try:
        clean_headers = {str(k): str(v) for k, v in (headers or {}).items() if not str(k).lower().startswith("cookie")}
        log_entry = WebhookDeliveryLog(
            hotel_id=hotel_id,
            direction="incoming",
            channel=channel,
            event_type=event_type,
            endpoint=f"/api/webhooks/incoming/{channel.lower().replace(' ', '_')}",
            request_headers=json.dumps(clean_headers, default=str),
            payload=json.dumps(payload, default=str),
            response_code=code,
            response_body=message,
            error_message=message if code >= 400 else None,
            status=status,
            latency_ms=latency_ms
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to write webhook log: {e}")


async def dispatch_in_background(
    event_type: str,
    payload: dict,
    hotel_id: Optional[int] = None,
    origin_channel: str = "StayFlow PMS"
):
    """Runs outgoing webhook dispatch safely in background task with dedicated session."""
    if not hotel_id:
        logger.warning(
            "Background webhook dispatch for event '%s' aborted: missing or invalid hotel/tenant ID (%r)",
            event_type, hotel_id
        )
        return

    try:
        from app.database import connection
        session_factory = getattr(connection, "SessionLocal", None)
        if not session_factory:
            from app.database.connection import SessionLocal as session_factory

        with session_factory() as session:
            await dispatch_outgoing_webhooks(session, event_type, payload, hotel_id, origin_channel)
    except Exception as e:
        logger.warning(f"Background webhook dispatch notice: {e}")
