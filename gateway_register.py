#!/usr/bin/env python3
"""
Chekk Gateway Auto-Registration Module for Hermes

Copy this file into your Hermes agent and use:

    from gateway_register import ensure_registered

    # On startup:
    credentials = ensure_registered()

    # Use credentials for gateway API calls:
    # headers = {"Authorization": f"Bearer {credentials['api_key']}"}

No config needed. Just import and call!
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, Optional
import hashlib


GATEWAY_URL = "https://chekk.dev"
CREDENTIALS_DIR = Path.home() / ".hermes" / "credentials"


def _ensure_credentials_dir():
    """Create credentials directory with proper permissions."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    # Set secure permissions on credentials directory
    os.chmod(CREDENTIALS_DIR, 0o700)


def _load_existing_credentials(handle: str) -> Optional[Dict]:
    """Load existing credentials if already registered."""
    cred_file = CREDENTIALS_DIR / f"{handle}.json"
    if cred_file.exists():
        try:
            with open(cred_file, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save_credentials(handle: str, credentials: Dict) -> None:
    """Save credentials to disk with secure permissions."""
    _ensure_credentials_dir()
    cred_file = CREDENTIALS_DIR / f"{handle}.json"

    with open(cred_file, "w") as f:
        json.dump(credentials, f, indent=2)

    # Set secure permissions on credentials file
    os.chmod(cred_file, 0o600)


def _generate_registration_token(handle: str, name: Optional[str] = None) -> str:
    """Generate registration token from gateway."""
    try:
        import requests
    except ImportError:
        print("Error: requests module required. Install with: pip install requests")
        sys.exit(1)

    if not name:
        name = handle.replace("_", " ").replace("-", " ").title()

    try:
        response = requests.post(
            f"{GATEWAY_URL}/api/v1/gateway/agents/registration-token",
            json={
                "handle": handle,
                "name": name
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data["token"]
    except Exception as e:
        raise RuntimeError(f"Failed to generate registration token: {e}")


def _redeem_registration_token(handle: str, token: str) -> Dict:
    """Redeem registration token for API key."""
    try:
        import requests
    except ImportError:
        print("Error: requests module required. Install with: pip install requests")
        sys.exit(1)

    try:
        response = requests.post(
            f"{GATEWAY_URL}/api/v1/gateway/agents/redeem-token",
            json={
                "handle": handle,
                "token": token
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise RuntimeError(f"Failed to redeem registration token: {e}")


def _generate_default_handle() -> str:
    """Generate a default handle from hostname + hash."""
    import socket
    try:
        hostname = socket.gethostname().lower()
        # Keep only alphanumeric and hyphens
        hostname = "".join(c if c.isalnum() or c == "-" else "-" for c in hostname)
        hostname = hostname.strip("-")

        # Add random suffix
        pid_hash = hashlib.md5(str(os.getpid()).encode()).hexdigest()[:6]
        handle = f"{hostname}-{pid_hash}"

        # Ensure it's valid length
        if len(handle) > 64:
            handle = handle[:64]
        if len(handle) < 3:
            handle = f"agent-{pid_hash}"

        return handle.lower()
    except Exception:
        # Fallback
        pid_hash = hashlib.md5(str(os.getpid()).encode()).hexdigest()[:8]
        return f"agent-{pid_hash}"


def register_agent_interactive() -> Dict:
    """
    Interactive agent registration - prompts user for handle and name.

    Perfect for calling from Hermes when user asks "Register yourself".
    Prompts for input, handles validation, and completes registration.

    Returns:
        Dict with keys: handle, agent_id, api_key, gateway_url

    Usage:
        # Call when user asks Hermes to register
        credentials = register_agent_interactive()
    """
    print("\n" + "=" * 60)
    print("🔐 Chekk Gateway - Agent Registration")
    print("=" * 60)

    # Prompt for handle
    while True:
        handle = input("\nEnter your agent handle (e.g., 'my-hermes', 'atlas', 'jarvis'): ").strip()

        if not handle:
            print("Handle cannot be empty.")
            continue

        # Validate
        if len(handle) < 3:
            print(f"❌ Handle too short. Must be at least 3 characters. Got: {len(handle)}")
            continue

        if len(handle) > 64:
            print(f"❌ Handle too long. Maximum 64 characters. Got: {len(handle)}")
            continue

        handle = handle.lower()

        if not all(c.isalnum() or c in "-_" for c in handle):
            print("❌ Handle can only contain letters, numbers, hyphens, and underscores.")
            continue

        # Check if already registered
        existing = _load_existing_credentials(handle)
        if existing:
            print(f"❌ Agent '{handle}' is already registered!")
            print(f"   Agent ID: {existing['agent_id']}")
            use_existing = input("\nUse existing credentials? (y/n): ").strip().lower()
            if use_existing == "y":
                return existing
            else:
                print("Please choose a different handle.")
                continue

        break

    # Prompt for name
    name = input(f"Enter agent name (or press Enter for '{handle}'): ").strip()
    if not name:
        name = handle.replace("-", " ").replace("_", " ").title()

    # Register
    print(f"\n🔐 Registering '{handle}' with Chekk gateway...")

    try:
        # Generate token
        token = _generate_registration_token(handle, name)
        print(f"✓ Generated registration token (expires in 10 minutes)")

        # Redeem token
        credentials = _redeem_registration_token(handle, token)
        print(f"✓ Exchanged token for API key")

        # Ensure gateway_url is in credentials
        if "gateway_url" not in credentials:
            credentials["gateway_url"] = GATEWAY_URL

        # Save credentials
        _save_credentials(handle, credentials)
        print(f"✓ Saved credentials to ~/.hermes/credentials/{handle}.json")

        print(f"\n" + "=" * 60)
        print(f"✓ Agent '{handle}' registered successfully!")
        print(f"=" * 60)
        print(f"  Handle:    {credentials['handle']}")
        print(f"  Agent ID:  {credentials['agent_id']}")
        print(f"  API Key:   {credentials['api_key'][:20]}...")
        print(f"  Gateway:   {credentials['gateway_url']}")
        print("=" * 60 + "\n")

        return credentials

    except Exception as e:
        print(f"\n❌ Registration failed: {e}\n")
        raise


def ensure_registered(
    handle: Optional[str] = None,
    name: Optional[str] = None,
    auto_register: bool = True
) -> Dict:
    """
    Ensure this agent is registered with Chekk gateway.

    If already registered, returns existing credentials.
    If not registered and auto_register=True, registers automatically.
    If not registered and auto_register=False, prompts for handle.

    Args:
        handle: Agent handle (defaults to auto-generated)
        name: Agent display name (defaults to handle)
        auto_register: Auto-register if not found (True) or prompt (False)

    Returns:
        Dict with keys: handle, agent_id, api_key, gateway_url

    Usage:
        # Automatic registration on first run
        credentials = ensure_registered()

        # Or with specific handle
        credentials = ensure_registered(handle="my-agent", name="My Agent")

        # Use the API key
        api_key = credentials["api_key"]
    """

    # Determine handle
    if not handle:
        if auto_register:
            handle = _generate_default_handle()
        else:
            # Prompt user
            handle = input("Enter agent handle (or press Enter for auto-generated): ").strip()
            if not handle:
                handle = _generate_default_handle()
                print(f"Generated handle: {handle}")

    # Validate handle
    if not isinstance(handle, str) or len(handle) < 3 or len(handle) > 64:
        raise ValueError("Handle must be 3-64 characters")

    handle = handle.lower().strip()
    # Only allow alphanumeric, hyphens, underscores
    if not all(c.isalnum() or c in "-_" for c in handle):
        raise ValueError("Handle can only contain alphanumeric characters, hyphens, and underscores")

    # Check if already registered
    existing = _load_existing_credentials(handle)
    if existing:
        print(f"✓ Agent '{handle}' already registered")
        return existing

    # Register
    print(f"🔐 Registering agent '{handle}' with Chekk gateway...")

    try:
        # Generate token
        token = _generate_registration_token(handle, name)
        print(f"✓ Generated registration token (expires in 10 minutes)")

        # Redeem token
        credentials = _redeem_registration_token(handle, token)
        print(f"✓ Exchanged token for API key")

        # Ensure gateway_url is in credentials
        if "gateway_url" not in credentials:
            credentials["gateway_url"] = GATEWAY_URL

        # Save credentials
        _save_credentials(handle, credentials)
        print(f"✓ Saved credentials to ~/.hermes/credentials/{handle}.json")

        print(f"✓ Agent '{handle}' registered successfully!")
        print(f"  Agent ID: {credentials['agent_id']}")
        print(f"  API Key: {credentials['api_key'][:20]}...")

        return credentials

    except Exception as e:
        print(f"❌ Registration failed: {e}")
        raise


def get_credentials(handle: Optional[str] = None) -> Optional[Dict]:
    """
    Get stored credentials for an agent.

    If handle not provided, returns the first registered agent.
    Returns None if not found.

    Usage:
        creds = get_credentials("my-agent")
        if creds:
            api_key = creds["api_key"]
    """
    if handle:
        return _load_existing_credentials(handle)

    # Return first registered agent
    _ensure_credentials_dir()
    creds_files = list(CREDENTIALS_DIR.glob("*.json"))
    if creds_files:
        try:
            with open(creds_files[0], "r") as f:
                return json.load(f)
        except Exception:
            return None

    return None


def list_registered_agents() -> list:
    """List all registered agent handles."""
    _ensure_credentials_dir()
    agents = []
    for cred_file in CREDENTIALS_DIR.glob("*.json"):
        try:
            with open(cred_file, "r") as f:
                data = json.load(f)
                agents.append(data.get("handle", cred_file.stem))
        except Exception:
            pass
    return agents


if __name__ == "__main__":
    # Can be run directly for interactive registration
    credentials = register_agent_interactive()
    print("\nStored as:")
    print(json.dumps(credentials, indent=2))
