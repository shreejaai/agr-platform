#!/usr/bin/env python3
"""Generate an Ed25519 key pair for AGR on-prem license signing.

Run this ONCE. Store the private key in a secrets vault (1Password, AWS Secrets
Manager, etc.) — never commit it to git or include it in any build artifact.

The public key goes into services/agr-api/app/license.py as AGR_PUBLIC_KEY_B64.

Usage:
  pip install cryptography
  python tools/generate_keypair.py
"""

import base64
import sys


def main() -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("ERROR: cryptography package is required.")
        print("       pip install cryptography")
        sys.exit(1)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_b64 = base64.b64encode(private_key.private_bytes_raw()).decode()
    pub_b64 = base64.b64encode(public_key.public_bytes_raw()).decode()

    print()
    print("=" * 64)
    print("AGR LICENSE KEY PAIR — generated", flush=True)
    print("=" * 64)
    print()
    print("PRIVATE KEY — store in 1Password / AWS Secrets Manager / vault")
    print("NEVER commit this to git or include in Docker images.")
    print()
    print(priv_b64)
    print()
    print("PUBLIC KEY — paste into services/agr-api/app/license.py")
    print("Replace the AGR_PUBLIC_KEY_B64 = '...' line with:")
    print()
    print(f'AGR_PUBLIC_KEY_B64 = "{pub_b64}"')
    print()
    print("=" * 64)


if __name__ == "__main__":
    main()
