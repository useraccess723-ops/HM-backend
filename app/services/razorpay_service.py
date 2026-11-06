"""
StayFlow Razorpay Payment Gateway Integration Service (Strictly TEST MODE).
Handles order creation, payment signature verification, webhook signature verification,
and payment status queries using standard HMAC-SHA256 and httpx.
"""
import hmac
import hashlib
import json
import logging
import secrets
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger("stayflow.razorpay")

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

class RazorpayServiceError(Exception):
    """Base exception for Razorpay gateway errors."""
    pass

class RazorpayService:
    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        self.mode = settings.RAZORPAY_MODE
        self._validate_mode()

    def _validate_mode(self):
        """Enforce strict TEST MODE operation."""
        if self.mode != "test":
            raise RazorpayServiceError(
                f"StayFlow is strictly configured for Razorpay TEST MODE. Current mode: '{self.mode}'."
            )
        if self.key_id.startswith("rzp_live_"):
            raise RazorpayServiceError(
                "Live Razorpay credentials (rzp_live_*) detected! Only test keys (rzp_test_*) are permitted."
            )

    def create_order(
        self,
        amount_in_paise: int,
        currency: str = "INR",
        receipt: str = "",
        notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay order via Razorpay REST API or mock generator in test environments.
        amount_in_paise: Integer amount in paise (1 INR = 100 paise). Minimum 100 paise (₹1).
        """
        self._validate_mode()
        if amount_in_paise < 100:
            raise RazorpayServiceError(f"Minimum transaction amount is 100 paise (₹1.00). Given: {amount_in_paise}")
        if currency.upper() != "INR":
            raise RazorpayServiceError(f"Only INR currency is supported for domestic payments. Given: {currency}")

        receipt = (receipt or f"rcpt_{secrets.token_hex(6)}")[:40]
        payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {}
        }

        # Attempt API call if live internet & real test keys are available
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.post(
                    f"{RAZORPAY_API_BASE}/orders",
                    auth=(self.key_id, self.key_secret),
                    json=payload
                )
                if res.status_code in (200, 201):
                    order_data = res.json()
                    logger.info("Created Razorpay test order: %s", order_data.get("id"))
                    return order_data
                else:
                    logger.warning(
                        "Razorpay API returned HTTP %s: %s (falling back to mock test order)",
                        res.status_code,
                        res.text[:120]
                    )
        except Exception as net_err:
            logger.info("Razorpay API offline or unreachable (%s); using mock test order", net_err)

        # Standalone Test Mode order for local development / automated tests
        order_id = f"order_test_{secrets.token_hex(8)}"
        return {
            "id": order_id,
            "entity": "order",
            "amount": amount_in_paise,
            "amount_paid": 0,
            "amount_due": amount_in_paise,
            "currency": "INR",
            "receipt": receipt,
            "status": "created",
            "attempts": 0,
            "notes": notes or {},
            "created_at": 1730370000
        }

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str
    ) -> bool:
        """
        Verifies Razorpay payment signature using HMAC-SHA256.
        Formula: HMAC-SHA256(order_id + "|" + payment_id, secret) == signature
        """
        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            return False

        message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        secret = self.key_secret.encode("utf-8")
        generated_signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(generated_signature, razorpay_signature.strip())

    def create_mock_signature(self, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        """Helper to generate a valid HMAC-SHA256 signature for automated tests."""
        message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        return hmac.new(self.key_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Verifies Razorpay webhook signature using HMAC-SHA256.
        Formula: HMAC-SHA256(raw_body, webhook_secret) == signature
        """
        if not raw_body or not signature_header:
            return False

        secret = (self.webhook_secret or self.key_secret).encode("utf-8")
        expected_signature = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_signature, signature_header.strip())

    def create_mock_webhook_signature(self, raw_body: bytes) -> str:
        """Helper to generate a valid webhook signature for tests."""
        secret = (self.webhook_secret or self.key_secret).encode("utf-8")
        return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

    def fetch_payment(self, razorpay_payment_id: str) -> Dict[str, Any]:
        """Queries Razorpay API or mock details for a captured payment."""
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.get(
                    f"{RAZORPAY_API_BASE}/payments/{razorpay_payment_id}",
                    auth=(self.key_id, self.key_secret)
                )
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass

        # Standalone Test Mode mock response
        return {
            "id": razorpay_payment_id,
            "entity": "payment",
            "amount": 0,
            "currency": "INR",
            "status": "captured",
            "method": "upi",
            "captured": True
        }

razorpay_service = RazorpayService()

