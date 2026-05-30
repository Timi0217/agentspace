"""
Gateway Webhook utilities — payload signing, verification, and delivery.

All agent inbound delivery flows through here so signing stays identical
between the registration-time verification ping and live message delivery.

Recipients verify a request really came from the gateway by recomputing
HMAC-SHA256 over `"{timestamp}.{raw_body}"` with the shared secret and
comparing it to the `X-Chekk-Signature` header.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional, Tuple

import httpx

# Shared secret used to sign webhook payloads. Set GATEWAY_WEBHOOK_SECRET in
# production; a dev default keeps local runs working.
WEBHOOK_SECRET = os.getenv("GATEWAY_WEBHOOK_SECRET", "chekk-dev-webhook-secret")

SIGNATURE_HEADER = "X-Chekk-Signature"
TIMESTAMP_HEADER = "X-Chekk-Timestamp"
DELIVERY_TIMEOUT = 10.0
VERIFY_TIMEOUT = 8.0

# Hosts we refuse to deliver to, to blunt obvious SSRF via registered URLs.
_BLOCKED_HOST_FRAGMENTS = (
    "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "169.254.", ".internal", "metadata.google", "metadata.",
)


def sign_payload(body: bytes, timestamp: str) -> str:
    """Hex HMAC-SHA256 of `"{timestamp}.{body}"` using the shared secret."""
    mac = hmac.new(
        WEBHOOK_SECRET.encode(),
        msg=f"{timestamp}.".encode() + body,
        digestmod=hashlib.sha256,
    )
    return mac.hexdigest()


def signed_headers(body: bytes) -> dict:
    """Headers (content-type + timestamp + signature) for a signed POST."""
    ts = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: ts,
        SIGNATURE_HEADER: f"sha256={sign_payload(body, ts)}",
    }


async def post_signed(
    url: str,
    payload: dict,
    timeout: float = DELIVERY_TIMEOUT,
    client: Optional[httpx.AsyncClient] = None,
) -> httpx.Response:
    """POST a signed JSON payload. Reuses `client` if given, else one-off."""
    body = json.dumps(payload).encode()
    headers = signed_headers(body)
    if client is not None:
        return await client.post(url, content=body, headers=headers)
    async with httpx.AsyncClient(timeout=timeout) as c:
        return await c.post(url, content=body, headers=headers)


def is_valid_webhook_url(url: str) -> bool:
    """True if `url` is an http(s) URL that isn't an obvious internal target."""
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        return False
    lowered = url.lower()
    return not any(frag in lowered for frag in _BLOCKED_HOST_FRAGMENTS)


async def verify_webhook(url: str) -> Tuple[bool, str]:
    """
    Send a signed verification ping. The endpoint must respond 2xx for the
    webhook to be accepted (a permanent agent connector should be live).
    Returns (ok, detail).
    """
    if not is_valid_webhook_url(url):
        return False, "webhook_url must be a public http(s) URL (no internal hosts)"

    challenge = secrets.token_urlsafe(16)
    payload = {"type": "verification", "challenge": challenge}
    try:
        resp = await post_signed(url, payload, timeout=VERIFY_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - report any reachability failure
        return False, f"could not reach webhook_url: {e}"

    if resp.status_code // 100 != 2:
        return False, f"webhook returned HTTP {resp.status_code} (expected 2xx)"
    return True, "verified"
