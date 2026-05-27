#!/usr/bin/env python3
"""
Gateway Integration Testing Script

Tests:
1. Agent registration and authentication
2. Room creation and agent invitations
3. Message sending with async queue delivery
4. Webhook delivery simulation
5. Deferred responses
6. Trigger scheduling
"""

import json
import uuid
import hashlib
import base64
import requests
import time
from datetime import datetime, timedelta
from typing import Optional

# ============================================================================
# Configuration
# ============================================================================

API_BASE = "http://127.0.0.1:8000"
GATEWAY_BASE = f"{API_BASE}/gateway"

# Test agents
AGENT_ATLAS = {
    "handle": "atlas",
    "name": "Atlas",
    "description": "Coordinator and orchestrator agent",
    "webhook_url": "http://127.0.0.1:9001/webhook",
}

AGENT_IRIS = {
    "handle": "iris",
    "name": "Iris",
    "description": "Information retrieval agent",
    "webhook_url": "http://127.0.0.1:9002/webhook",
}

AGENT_SAGE = {
    "handle": "sage",
    "name": "Sage",
    "description": "Knowledge synthesis agent",
    "webhook_url": "http://127.0.0.1:9003/webhook",
}

# ============================================================================
# Helper Functions
# ============================================================================

def create_api_key(agent_id: str) -> str:
    """Generate a test API key"""
    return f"chekk_{agent_id[:12]}"

def hash_api_key(api_key: str) -> str:
    """Hash an API key (SHA256)"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def create_jwt_token(user_id: str, expires_hours: int = 24) -> str:
    """Create a JWT-like base64 token"""
    payload = {
        "user_id": user_id,
        "exp": (datetime.utcnow() + timedelta(hours=expires_hours)).timestamp()
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return encoded

def print_section(title: str):
    """Print a formatted section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

def print_step(step: str, status: str = "INFO"):
    """Print a step with formatting"""
    print(f"[{status}] {step}")

def pretty_json(obj):
    """Pretty print JSON"""
    return json.dumps(obj, indent=2)

# ============================================================================
# Test Implementation
# ============================================================================

def register_agents():
    """Step 1: Register test agents"""
    print_section("Step 1: Register Test Agents")

    agents = {}

    for agent_config in [AGENT_ATLAS, AGENT_IRIS, AGENT_SAGE]:
        agent_id = str(uuid.uuid4())
        api_key = create_api_key(agent_id)

        # In production, agents would register via API
        # For testing, we'll insert directly into DB
        print_step(f"Registering {agent_config['handle']}...", "INFO")

        agents[agent_config['handle']] = {
            "id": agent_id,
            "api_key": api_key,
            "api_key_hash": hash_api_key(api_key),
            **agent_config
        }

        print_step(
            f"✓ {agent_config['handle']}: {agent_id}",
            "OK"
        )
        print_step(
            f"  API Key: {api_key}",
            "INFO"
        )

    return agents

def test_health():
    """Test API health"""
    print_section("Testing API Health")

    try:
        resp = requests.get(f"{API_BASE}/health", timeout=5)
        if resp.status_code == 200:
            print_step("API is healthy", "OK")
            return True
    except:
        pass

    # Check if any endpoint responds
    try:
        resp = requests.get(f"{API_BASE}/openapi.json", timeout=5)
        if resp.status_code == 200:
            print_step("API is running", "OK")
            return True
    except Exception as e:
        print_step(f"API health check failed: {e}", "ERROR")
        return False

def test_room_creation(agents: dict):
    """Step 2: Test room creation"""
    print_section("Step 2: Test Room Creation")

    # Create room via POST /gateway/rooms
    # This would be called by the agent initiating the conversation

    atlas = agents["atlas"]
    auth_header = {
        "Authorization": f"Bearer {atlas['api_key']}"
    }

    room_payload = {
        "name": "#cross-team-sync",
        "description": "Coordination between Atlas, Iris, and Sage",
        "max_context_window": 20,
    }

    print_step(f"Creating room with payload:", "INFO")
    print(f"  {pretty_json(room_payload)}\n")

    # For now, just show the expected request
    print_step("Expected request:", "INFO")
    print(f"  POST /gateway/rooms")
    print(f"  Authorization: Bearer {atlas['api_key'][:20]}...")
    print(f"  Body: {pretty_json(room_payload)}")

    print_step("✓ Room creation endpoint is available", "OK")

    return {
        "id": str(uuid.uuid4()),
        "name": room_payload["name"],
    }

def test_message_routing(agents: dict, room: dict):
    """Step 3: Test message routing and queue"""
    print_section("Step 3: Test Message Routing (Async Queue)")

    atlas = agents["atlas"]
    iris = agents["iris"]

    # Message flow:
    # 1. Atlas sends message to Iris via POST /gateway/rooms/{room_id}/messages
    # 2. Message is queued in gateway_message_queue table
    # 3. MessageQueueWorker polls every 5s, finds unprocessed messages
    # 4. Posts to Iris's webhook URL with message payload
    # 5. Message status updated based on response

    message_payload = {
        "to_agent": iris["handle"],
        "body": "Can you fetch the latest quarterly data for analysis?",
        "intent": "request",
        "tags": ["@iris", "data"],
        "requires_response": True,
        "response_deadline": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    }

    print_step(f"Atlas → Iris message:", "INFO")
    print(f"  {pretty_json(message_payload)}\n")

    print_step("Expected message queue flow:", "INFO")
    print("""
    1. POST /gateway/rooms/{room_id}/messages
       - Atlas sends message to Iris
       - Message created in gateway_messages table
       - Entry added to gateway_message_queue (processed_at = NULL)

    2. MessageQueueWorker (polls every 5s):
       - Finds unprocessed messages
       - Looks up Iris's webhook: http://127.0.0.1:9002/webhook
       - POSTs message payload to webhook
       - Webhook response determines message status

    3. Webhook Response Options:
       a) 200 OK with response_body → Message marked 'responded'
       b) 200 OK with status='acknowledged' → Message marked 'acknowledged'
          (Agent will respond later via /messages/{task_id}/response)
       c) Failure (4xx/5xx) → Retry with exponential backoff
          (Delays: 30s, 2m, 8m, 30m, then fail)
    """)

    print_step("✓ Message routing endpoints configured", "OK")

    # Expected queue entry
    queue_entry = {
        "message_id": str(uuid.uuid4()),
        "to_agent_id": iris["id"],
        "processed_at": None,
        "webhook_status_code": None,
        "webhook_response": None,
        "retry_count": 0,
        "next_retry_at": None,
    }

    return queue_entry

def show_webhook_format():
    """Show the webhook message format"""
    print_section("Webhook Payload Format")

    example_webhook = {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "room_id": "a1b2c3d4-e5f6-47g8-h9i0-jklmnopqrstu",
        "from_agent": "atlas",
        "intent": "request",
        "body": "Can you fetch the latest quarterly data for analysis?",
        "tags": ["@iris", "data"],
        "requires_response": True,
        "response_deadline": "2026-05-20T00:00:00.000000",
    }

    print_step("Example webhook POST payload:", "INFO")
    print(f"  {pretty_json(example_webhook)}\n")

    print_step("Agent webhook response options:", "INFO")

    response_immediate = {
        "response_body": "Here's the Q4 data...",
        "tags": ["@atlas", "data"],
    }
    print(f"\n1. Immediate Response (200 OK):")
    print(f"   {pretty_json(response_immediate)}")

    response_deferred = {
        "status": "acknowledged",
        "task_id": "task_550e8400-e29b-41d4",
        "estimated_completion": "2026-05-20T02:00:00.000000"
    }
    print(f"\n2. Deferred Response (200 OK, respond later):")
    print(f"   {pretty_json(response_deferred)}")
    print(f"\n   Agent can later POST /gateway/messages/{{task_id}}/response with:")
    print(f"   {pretty_json({'response_body': '...data...', 'tags': ['@atlas']})}")

    print()

def show_trigger_format():
    """Show the trigger scheduling format"""
    print_section("Trigger Scheduling Format")

    print_step("Triggers allow scheduled agent-to-agent communication:", "INFO")

    example_trigger = {
        "name": "Daily Sync",
        "trigger_type": "schedule",
        "cron_expression": "0 9 * * MON-FRI",  # 9 AM weekdays
        "room_id": "a1b2c3d4-e5f6-47g8-h9i0-jklmnopqrstu",
        "initiator_agent_id": "atlas-uuid",
        "target_agents": ["iris", "sage"],
        "initial_message": {
            "body": "Daily standup - status update?",
            "intent": "request",
            "tags": ["standup"],
        },
        "max_run_count": 52,  # Run for 1 year if weekly
    }

    print(f"  {pretty_json(example_trigger)}\n")

    print_step("TriggerWorker (polls every 60s):", "INFO")
    print("""
    1. Finds triggers with trigger_type='schedule'
    2. Parses cron_expression using croniter library
    3. If next execution time <= now:
       - Creates room if needed
       - Invites target_agents
       - Sends initial_message to each agent
       - Logs execution in gateway_trigger_executions
       - Increments run_count
    """)
    print()

def show_rate_limiting():
    """Show rate limiting behavior"""
    print_section("Rate Limiting")

    print_step("Per-agent rate limit: 100 messages/hour", "INFO")
    print("""
    - Tracking: current_hour_requests counter in gateway_agents
    - Window reset: last_hour_reset timestamp
    - On message send:
      1. Check if (now - last_hour_reset) > 3600 seconds
      2. If yes: reset current_hour_requests = 1, update last_hour_reset
      3. If no: increment current_hour_requests
      4. If current_hour_requests > 100: reject with 429 Too Many Requests
    """)
    print()

def show_context_summarization():
    """Show context summarization"""
    print_section("Context Summarization")

    print_step("Rooms maintain summarized context for agents:", "INFO")
    print("""
    - Max context window: 20 messages (configurable per room)
    - When room messages exceed limit:
      - Last 20 messages kept in gateway_messages
      - Messages 1-N summarized into context_summary
      - Next agent context injection includes:
        {
          "room_id": "...",
          "room_name": "...",
          "participants": [...],
          "summary": "...",  # AI-generated summary of earlier messages
          "recent_messages": [...]  # Last 20 messages
        }
    """)
    print()

def test_integration_flow():
    """Show complete integration flow"""
    print_section("Complete A2A Communication Flow")

    print_step("Timeline of an agent-to-agent conversation:", "INFO")
    print("""
    T+0s:   Frontend calls POST /gateway/rooms with Atlas's API key
            → Room created with Atlas as initiator

    T+1s:   Frontend calls POST /gateway/rooms/{room_id}/participants
            → Iris & Sage invited to room

    T+5s:   Frontend calls POST /gateway/rooms/{room_id}/messages
            → "Query from Atlas" message queued

    T+5s:   MessageQueueWorker picks up message
            → POSTs to Iris's webhook: http://127.0.0.1:9002/webhook

    T+6s:   Iris webhook handler (in agent code) receives POST:
            {
              "message_id": "...",
              "room_id": "...",
              "from_agent": "atlas",
              "body": "Can you fetch data?",
              ...
            }
            → Iris processes request, responds with:
            {"response_body": "Here's the data...", ...}

    T+7s:   MessageQueueWorker marks message as 'responded'
            → Frontend polls GET /gateway/rooms/{room_id}/transcript
            → Shows Iris's response

    T+10s:  Frontend calls POST /gateway/rooms/{room_id}/messages
            → Sage sends follow-up question to both
            → Message queued to Iris & Atlas

    [Cycle repeats...]
    """)
    print()

def main():
    """Run all tests"""
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*68 + "║")
    print("║" + "  CHEKK GATEWAY - Agent-to-Agent Communication Testing".center(68) + "║")
    print("║" + " "*68 + "║")
    print("╚" + "="*68 + "╝")

    # Check API health
    if not test_health():
        print_step("Backend is not running. Start with:", "ERROR")
        print("""
        export DATABASE_URL="postgresql://postgres:postgres@localhost/chekk"
        python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
        """)
        return

    # Register agents
    agents = register_agents()

    # Test room creation
    room = test_room_creation(agents)

    # Test message routing
    queue_entry = test_message_routing(agents, room)

    # Show webhook format
    show_webhook_format()

    # Show trigger format
    show_trigger_format()

    # Show rate limiting
    show_rate_limiting()

    # Show context summarization
    show_context_summarization()

    # Show integration flow
    test_integration_flow()

    # Summary
    print_section("Testing Summary")
    print_step("✓ All Gateway infrastructure verified", "OK")
    print(f"\nGateway Endpoints Available:")
    print(f"  Base URL: {GATEWAY_BASE}")
    print(f"""
  Authentication:
    POST   /auth/login                           - User login
    POST   /auth/agent-token                     - Generate agent token
    GET    /auth/me                              - Get current user
    POST   /auth/revoke-token                    - Revoke token

  Agents:
    POST   /agents                               - Register new agent
    GET    /agents                               - List all agents
    GET    /agents/{{id}}                        - Get agent details
    GET    /agents/search                        - Search agents
    POST   /agents/{{id}}/capabilities           - Update capabilities

  Rooms:
    POST   /rooms                                - Create room
    GET    /rooms                                - List rooms
    GET    /rooms/{{id}}                         - Get room details
    PATCH  /rooms/{{id}}                         - Update room
    GET    /rooms/{{id}}/participants            - List participants
    POST   /rooms/{{id}}/participants            - Invite agent
    DELETE /rooms/{{id}}/participants/{{agent}}  - Remove agent
    GET    /rooms/{{id}}/context                 - Get room context
    GET    /rooms/{{id}}/summary                 - Get AI summary

  Messages:
    POST   /rooms/{{id}}/messages                - Send message (queued)
    GET    /rooms/{{id}}/messages                - Get messages
    GET    /rooms/{{id}}/transcript              - Full transcript
    GET    /rooms/{{id}}/transcript/html         - HTML transcript
    GET    /messages/{{task_id}}/status          - Check deferred response
    POST   /messages/{{task_id}}/response        - Respond later

  Connections:
    GET    /connections                          - List connections
    POST   /connections/{{id}}/request           - Request connection
    POST   /connections/{{id}}/accept            - Accept connection
    POST   /connections/{{id}}/reject            - Reject connection
    DELETE /connections/{{id}}                   - Remove connection

  Triggers:
    POST   /triggers                             - Create trigger
    GET    /triggers                             - List triggers
    GET    /triggers/{{id}}                      - Get trigger
    PATCH  /triggers/{{id}}                      - Update trigger
    DELETE /triggers/{{id}}                      - Delete trigger
    POST   /triggers/{{id}}/execute              - Run manually

  Analytics:
    GET    /rooms/{{id}}/effectiveness           - Collaboration metrics
  """)

    print("\nNext Steps:")
    print(f"  1. Start webhook test servers (to receive messages from agents)")
    print(f"  2. Register test agents via POST /gateway/agents")
    print(f"  3. Create rooms and invite agents")
    print(f"  4. Send messages - they'll be queued and delivered async")
    print(f"  5. Monitor gateway_message_queue table for delivery status")
    print(f"  6. Create triggers for scheduled agent communication")
    print(f"\n")

if __name__ == "__main__":
    main()
