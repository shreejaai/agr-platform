"""AGR on-prem license validation — Ed25519 signed license keys.

License format:
  base64url(json_payload) . base64url(ed25519_signature)

Payload fields:
  org       — organization name (string)
  expiry    — ISO date string YYYY-MM-DD
  evals     — max evaluations allowed (int, 0 = unlimited)
  issued_at — ISO date string YYYY-MM-DD

The public key is baked into this binary. The matching private key
is held exclusively by Shreeja AI and never distributed.

To generate a key pair (run once, store private key in vault):
  python tools/generate_keypair.py

To issue a license:
  python tools/generate_license.py --private-key <b64> --org "Acme" --expiry 2027-01-01
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

# ── Public key (baked into binary) ────────────────────────────────────────────
# Generated with: python tools/generate_keypair.py
# Replace this placeholder with your real public key before distributing.
# The private key must NEVER be committed or included in any build artifact.
AGR_PUBLIC_KEY_B64 = "m3HWC3YbeihSPYQ84JfzjpF03krhI0B3GOKNwHle2/M="


def validate_license(license_key: str) -> dict:
    """Validate a license key. Returns the decoded payload dict.

    Raises RuntimeError with a human-readable message if:
    - The key is missing or empty
    - The format is invalid
    - The Ed25519 signature does not verify
    - The license has expired
    """
    if not license_key:
        raise RuntimeError(
            "AGR_LICENSE_KEY is not set. " "Contact support@agr.dev to obtain an on-prem license."
        )

    if AGR_PUBLIC_KEY_B64.startswith("REPLACE_WITH"):
        raise RuntimeError(
            "AGR public key is not configured. "
            "Run tools/generate_keypair.py and set AGR_PUBLIC_KEY_B64 in license.py "
            "before building the on-prem image."
        )

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package is required for license validation. "
            "Add it to requirements.txt."
        ) from exc

    try:
        parts = license_key.strip().split(".")
        if len(parts) != 2:
            raise ValueError("expected exactly one '.' separator")

        payload_b64, sig_b64 = parts

        # Restore padding stripped during encoding
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
        sig_bytes = base64.urlsafe_b64decode(sig_b64 + "==")

        # Verify signature against raw payload bytes
        pub_key_bytes = base64.b64decode(AGR_PUBLIC_KEY_B64)
        public_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
        try:
            public_key.verify(sig_bytes, payload_bytes)
        except InvalidSignature as exc:
            raise ValueError("signature verification failed") from exc

        payload: dict = json.loads(payload_bytes)

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Invalid AGR license key: {exc}") from exc

    # Check expiry
    expiry_str: str = payload.get("expiry", "")
    try:
        expiry = date.fromisoformat(expiry_str)
    except ValueError as exc:
        raise RuntimeError(f"License has invalid expiry date: '{expiry_str}'") from exc

    if date.today() > expiry:
        raise RuntimeError(
            f"AGR license expired on {expiry_str}. "
            "Contact support@agr.dev to renew your license."
        )

    logger.info(
        "AGR on-prem license valid — org=%s expiry=%s evals=%s",
        payload.get("org"),
        expiry_str,
        payload.get("evals"),
    )
    return payload
