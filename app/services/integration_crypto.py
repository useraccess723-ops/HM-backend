"""Cryptographic helpers for AI Receptionist integration service keys and secrets."""
import base64
import hashlib
import os
import secrets
from cryptography.fernet import Fernet
from app.core.config import Settings

KEY_PREFIX = "sf_live_"

def generate_service_key() -> tuple[str, str, str, str]:
    """
    Generates a secure, high-entropy 72-character API key for M2M integrations.
    Format: sf_live_ (8 chars) + secrets.token_urlsafe(48) (64 chars) = 72 chars.
    Entropy: 48 raw bytes = 384 bits.
    Zero tenant identifiers or sequence numbers are contained in the key.
    
    Returns:
        (raw_key, key_hash, prefix, last4)
    """
    random_part = secrets.token_urlsafe(48)
    raw_key = f"{KEY_PREFIX}{random_part}"
    key_hash = hash_key(raw_key)
    prefix = raw_key[:12]
    last4 = raw_key[-4:]
    return raw_key, key_hash, prefix, last4

def hash_key(raw_key: str) -> str:
    """Returns the raw SHA-256 hex digest of the raw key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

def mask_key(prefix: str | None, last4: str | None) -> str:
    """Formats a masked display string for service credentials."""
    p = prefix or KEY_PREFIX
    l = last4 or "••••"
    return f"{p}••••••••••••••••••••••••••••••••{l}"

def _get_fernet() -> Fernet:
    secret_bytes = (Settings.JWT_SECRET_KEY or "stayflow_integration_fallback_secret_32b!").encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(secret_bytes).digest())
    return Fernet(derived_key)

def encrypt_secret(plaintext: str) -> str:
    """Encrypts sensitive integration strings (e.g., webhook signing secrets)."""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")

def decrypt_secret(ciphertext: str) -> str:
    """Decrypts ciphertext using authenticated symmetric encryption."""
    if not ciphertext:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""

