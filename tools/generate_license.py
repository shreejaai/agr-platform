#!/usr/bin/env python3
"""Issue an AGR on-prem license key.

Each license is an Ed25519-signed JSON payload encoding the customer's
org name, evaluation limit, and expiry date. The key is delivered to
the client who sets it as AGR_LICENSE_KEY in their .env file.

Usage:
  pip install cryptography
  python tools/generate_license.py \\
    --private-key <base64_private_key> \\
    --org "Acme Corp" \\
    --expiry 2027-03-20 \\
    --evals 1000000

Options:
  --private-key   Base64-encoded Ed25519 private key (from generate_keypair.py)
  --org           Customer organization name (embedded in license, shown in logs)
  --expiry        License expiry date in YYYY-MM-DD format
  --evals         Maximum evaluations allowed (0 = unlimited, default: 1 000 000)

Output:
  Prints the license key to stdout. Send it to the client.
"""

import argparse
import base64
import json
import sys
from datetime import date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue an AGR on-prem license key.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--private-key", required=True, help="Base64 Ed25519 private key")
    parser.add_argument("--org", required=True, help="Customer organization name")
    parser.add_argument("--expiry", required=True, help="Expiry date YYYY-MM-DD")
    parser.add_argument(
        "--evals",
        type=int,
        default=1_000_000,
        help="Max evaluations (0 = unlimited, default: 1 000 000)",
    )
    args = parser.parse_args()

    # Validate expiry
    try:
        expiry = date.fromisoformat(args.expiry)
    except ValueError:
        print(f"ERROR: --expiry must be YYYY-MM-DD, got '{args.expiry}'")
        sys.exit(1)

    if expiry <= date.today():
        print(f"WARNING: expiry date {args.expiry} is in the past or today.")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("ERROR: cryptography package is required.")
        print("       pip install cryptography")
        sys.exit(1)

    # Build payload
    payload = {
        "org": args.org,
        "expiry": args.expiry,
        "evals": args.evals,
        "issued_at": date.today().isoformat(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()

    # Sign
    try:
        priv_bytes = base64.b64decode(args.private_key)
        private_key = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    except Exception as exc:
        print(f"ERROR: Could not load private key: {exc}")
        sys.exit(1)

    sig_bytes = private_key.sign(payload_bytes)
    sig_b64 = base64.urlsafe_b64encode(sig_bytes).rstrip(b"=").decode()

    license_key = f"{payload_b64}.{sig_b64}"

    print()
    print("=" * 64)
    print("AGR LICENSE KEY ISSUED")
    print("=" * 64)
    print(f"  Organization : {args.org}")
    print(f"  Expiry       : {args.expiry}")
    print(f"  Evaluations  : {'unlimited' if args.evals == 0 else f'{args.evals:,}'}")
    print(f"  Issued       : {date.today().isoformat()}")
    print()
    print("LICENSE KEY (send to client):")
    print()
    print(license_key)
    print()
    print("Client adds to .env.onprem:")
    print(f"  AGR_LICENSE_KEY={license_key}")
    print("=" * 64)


if __name__ == "__main__":
    main()
