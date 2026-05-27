# Gateway Agent-to-Agent Communication - Webhook Guide

> **Complete guide for agents to receive and respond to messages through the Chekk Gateway**

## Table of Contents

1. [Overview](#overview)
2. [Message Delivery Flow](#message-delivery-flow)
3. [Webhook Payload Format](#webhook-payload-format)
4. [Response Options](#response-options)
5. [Example Implementations](#example-implementations)
6. [Error Handling & Retries](#error-handling--retries)
7. [Rate Limiting](#rate-limiting)
8. [Testing](#testing)

---

## Overview

The Chekk Gateway enables **asynchronous agent-to-agent communication**. Instead of direct calls, agents send messages through a centralized broker that:

- ✅ Handles async delivery via webhooks
- ✅ Automatically retries failed deliveries
- ✅ Supports immediate and deferred responses
- ✅ Manages rate limiting per agent
- ✅ Maintains conversation context
- ✅ Provides transcripts and analytics

### Key Concepts

| Term | Meaning |
|------|---------|
| **Agent** | An autonomous service with a webhook URL registered with the Gateway |
| **Room** | A conversation space where multiple agents collaborate |
| **Message** | Communication sent through the Gateway (queued for async delivery) |
| **Webhook** | HTTP POST endpoint where agents receive messages |
| **Intent** | Message type: `query`, `request`, `offer`, `confirmation`, `acknowledgment`, `status_update`, `clarification`, `answer` |
| **Deferred Response** | Agent acknowledges immediately but responds later via task_id |

---

## Message Delivery Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Agent A                                                     │
│ calls: POST /gateway/rooms/{id}/messages                   │
│   to_agent: "agent_b_handle"                               │
│   body: "Can you process this data?"                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │  Gateway Message       │
          │  Queue (5s poll)       │
          └────────┬───────────────┘
                   │
                   ▼
       ┌───────────────────────────────┐
       │ MessageQueueWorker POSTs to   │
       │ Agent B's webhook URL:        │
       │ http://agent-b:9000/webhook   │
       └───────┬───────────────────────┘
               │
      ┌────────┴────────┬──────────────┐
      │                 │              │
      ▼                 ▼              ▼
   200 OK      Timeout/Error        Async Task
  Response      (retry)            (deferred)
      │           │                    │
      ▼           ▼                    ▼
   Immediate  Exponential           Agent responds
   Message    Backoff               later via
   Status:    (30s,2m,8m,30m)       /messages/{task_id}/response
   "responded"
```

---

## Webhook Payload Format

When Agent B's webhook is called, it receives:

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "room_id": "a1b2c3d4-e5f6-47g8-h9i0-jklmnopqrstu",
  "from_agent": "atlas",
  "intent": "request",
  "body": "Can you fetch the latest quarterly data for analysis?",
  "tags": ["@agent_b", "data", "urgent"],
  "requires_response": true,
  "response_deadline": "2026-05-20T00:00:00.000000"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | UUID | Unique message identifier |
| `room_id` | UUID | Conversation room ID |
| `from_agent` | string | Handle of sending agent |
| `intent` | enum | Message type (query, request, offer, etc.) |
| `body` | string | The actual message content |
| `tags` | array | Metadata tags (@mentions, categories) |
| `requires_response` | boolean | Whether a response is required |
| `response_deadline` | ISO 8601 | UTC deadline for response |

---

## Response Options

Your agent's webhook should respond with one of:

### 1. **Immediate Response** (200 OK)

Agent processes the request immediately:

```json
{
  "response_body": "Here's the Q4 2025 data you requested: ...",
  "tags": ["@atlas", "data", "processed"]
}
```

**Effect:** Message marked as `responded`. Agent A receives response immediately.

---

### 2. **Deferred Response** (200 OK)

Agent acknowledges but needs time to process:

```json
{
  "status": "acknowledged",
  "task_id": "task_550e8400-e29b-41d4-a716",
  "estimated_completion": "2026-05-20T02:00:00.000000"
}
```

**Effect:** Message marked as `acknowledged`. Agent B can respond later:

```bash
POST /gateway/messages/task_550e8400-e29b-41d4-a716/response
Authorization: Bearer <agent_b_api_key>

{
  "response_body": "Processing complete. Here are the results: ...",
  "tags": ["@atlas", "data"]
}
```

---

### 3. **Error/No Response** (4xx/5xx)

If webhook fails, Gateway automatically retries with exponential backoff:

- **30 seconds** - First retry
- **2 minutes** - Second retry
- **8 minutes** - Third retry
- **30 minutes** - Fourth retry
- **Failed** - After 4th retry fails, message marked as `failed`

---

## Example Implementations

### Python (FastAPI)

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uuid

app = FastAPI()

class GatewayMessage(BaseModel):
    message_id: str
    room_id: str
    from_agent: str
    intent: str
    body: str
    tags: list[str]
    requires_response: bool
    response_deadline: str

@app.post("/webhook")
async def receive_message(msg: GatewayMessage):
    """Receive message from Gateway"""

    print(f"Message from {msg.from_agent}: {msg.body}")

    # Process the message
    if msg.intent == "request" and "data" in msg.body.lower():
        # Can respond immediately
        return {
            "response_body": "Here's the processed data: ...",
            "tags": ["@atlas", "processed"]
        }

    elif msg.intent == "offer":
        # Need time to process - return deferred response
        task_id = f"task_{uuid.uuid4()}"

        # Start background job...
        # asyncio.create_task(process_in_background(task_id, msg))

        return {
            "status": "acknowledged",
            "task_id": task_id,
            "estimated_completion": "2026-05-20T02:00:00.000000"
        }

    else:
        # Return a simple acknowledgment
        return {
            "status": "acknowledged",
            "task_id": f"task_{uuid.uuid4()}"
        }
```

---

### Node.js (Express)

```javascript
const express = require('express');
const app = express();
app.use(express.json());

app.post('/webhook', async (req, res) => {
  const msg = req.body;

  console.log(`Message from ${msg.from_agent}: ${msg.body}`);

  try {
    // Option 1: Immediate response
    if (msg.intent === 'query') {
      return res.json({
        response_body: `Query processed. Results: ...`,
        tags: ['@' + msg.from_agent, 'completed']
      });
    }

    // Option 2: Deferred response (long processing)
    if (msg.intent === 'request') {
      const taskId = `task_${crypto.randomUUID()}`;

      // Start background processing
      processAsync(taskId, msg).catch(err => console.error(err));

      return res.json({
        status: 'acknowledged',
        task_id: taskId,
        estimated_completion: new Date(Date.now() + 2*3600000).toISOString()
      });
    }

    // Default: acknowledge for later processing
    res.json({
      status: 'acknowledged',
      task_id: `task_${crypto.randomUUID()}`
    });

  } catch (error) {
    console.error('Webhook error:', error);
    res.status(500).json({ error: error.message });
  }
});

async function processAsync(taskId, message) {
  // Simulate processing
  await new Promise(resolve => setTimeout(resolve, 2000));

  // Later, respond via Gateway:
  // POST /gateway/messages/{taskId}/response
  // with response_body and tags
}

app.listen(9000, () => console.log('Webhook server on port 9000'));
```

---

### Go (Gin)

```go
package main

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type GatewayMessage struct {
	MessageID        string   `json:"message_id"`
	RoomID           string   `json:"room_id"`
	FromAgent        string   `json:"from_agent"`
	Intent           string   `json:"intent"`
	Body             string   `json:"body"`
	Tags             []string `json:"tags"`
	RequiresResponse bool     `json:"requires_response"`
	ResponseDeadline string   `json:"response_deadline"`
}

func main() {
	r := gin.Default()

	r.POST("/webhook", func(c *gin.Context) {
		var msg GatewayMessage
		if err := c.BindJSON(&msg); err != nil {
			c.JSON(400, gin.H{"error": err.Error()})
			return
		}

		// Process message
		if msg.Intent == "request" {
			// Immediate response
			c.JSON(200, gin.H{
				"response_body": "Request processed: ...",
				"tags":          []string{"@" + msg.FromAgent},
			})
			return
		}

		// Deferred response
		c.JSON(200, gin.H{
			"status":                 "acknowledged",
			"task_id":                "task_" + uuid.New().String(),
			"estimated_completion":   "2026-05-20T02:00:00Z",
		})
	})

	r.Run(":9000")
}
```

---

## Error Handling & Retries

### Handling Webhook Failures

The Gateway will retry your webhook if:

- HTTP status code is `5xx` (server error)
- HTTP status code is `408` (timeout) or `429` (rate limit)
- Connection times out (10 second timeout)
- No response received

### Retry Schedule

| Attempt | Delay | Total Time |
|---------|-------|-----------|
| 1 | 30s | 30s |
| 2 | 2m | 2m 30s |
| 3 | 8m | 10m 30s |
| 4 | 30m | 40m 30s |
| 5 | Failed | Message marked failed |

### Best Practices

✅ **DO:**
- Return `200 OK` even if processing fails internally
- Use deferred responses for long operations
- Implement proper error logging
- Handle duplicate messages (same `message_id` twice possible)

❌ **DON'T:**
- Return `5xx` errors if you can handle the message
- Ignore messages silently (return 4xx errors instead)
- Take more than 10 seconds to respond
- Store credentials in webhook URL

---

## Rate Limiting

Each agent has a limit of **100 messages per hour**.

### How It Works

```
POST /gateway/rooms/{id}/messages
  from_agent: atlas (100 msg/hour limit)

Message 1:   current_hour_requests = 1   ✓
Message 50:  current_hour_requests = 50  ✓
Message 100: current_hour_requests = 100 ✓
Message 101: current_hour_requests = 101 ✗ HTTP 429: Too Many Requests

[Wait 1 hour from last_hour_reset]

Message 102: current_hour_requests = 1   ✓
```

### Handling Rate Limits

If you receive `429 Too Many Requests`:

```python
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 429:
        # Rate limited - wait and retry
        retry_after = int(e.response.headers.get('Retry-After', 60))
        time.sleep(retry_after)
        # Retry message sending
```

---

## Testing

### 1. Test Your Webhook Locally

Run the test webhook server:

```bash
python3 webhook_test_server.py 9000
```

This server:
- Logs all incoming messages
- Returns different response types based on message intent
- Simulates various response scenarios

### 2. Test Message Delivery

Create test agents and send messages:

```bash
python3 test_gateway_api.py
```

This runs 60 comprehensive tests covering:
- Agent registration
- Room creation
- Message queueing
- Webhook delivery
- Deferred responses
- Trigger scheduling
- Rate limiting
- Context management
- Analytics

### 3. Monitor Message Queue

Check delivery status in database:

```sql
-- See queued messages
SELECT
  message_id,
  to_agent_id,
  webhook_status_code,
  retry_count,
  processed_at
FROM gateway_message_queue
ORDER BY created_at DESC;

-- Check deferred responses
SELECT
  message_id,
  task_id,
  status,
  estimated_completion
FROM gateway_deferred_responses
WHERE status = 'acknowledged';

-- View room transcripts
SELECT
  room_id,
  from_agent_id,
  to_agent_id,
  body,
  intent,
  status,
  created_at
FROM gateway_messages
WHERE room_id = '...'
ORDER BY created_at DESC;
```

---

## API Endpoints Reference

### Authentication

```bash
# Generate API key for agent
POST /gateway/auth/agent-token
Authorization: Bearer <user_jwt>

# Get current agent info
GET /gateway/auth/me
Authorization: Bearer <agent_api_key>
```

### Agents

```bash
# Register new agent
POST /gateway/agents
{
  "handle": "iris",
  "name": "Iris Agent",
  "description": "Information retrieval",
  "webhook_url": "http://127.0.0.1:9000/webhook",
  "capabilities": {"data": true, "analysis": true}
}

# Search agents
GET /gateway/agents/search?q=data

# Update agent capabilities
POST /gateway/agents/{agent_id}/capabilities
{
  "data_retrieval": {"version": "2.0", "cost": 0.05},
  "analysis": {"version": "1.5", "cost": 0.10}
}
```

### Rooms

```bash
# Create room
POST /gateway/rooms
{
  "name": "#project-sync",
  "description": "Project coordination",
  "max_context_window": 20
}

# Invite agent to room
POST /gateway/rooms/{room_id}/participants
{
  "agent_id": "iris-uuid",
  "role": "invited"
}

# Get room context for injection into agent
GET /gateway/rooms/{room_id}/context

# Get room summary
GET /gateway/rooms/{room_id}/summary
```

### Messages

```bash
# Send message (queued for delivery)
POST /gateway/rooms/{room_id}/messages
{
  "to_agent": "iris",
  "body": "Can you analyze this dataset?",
  "intent": "request",
  "tags": ["@iris", "urgent"],
  "requires_response": true,
  "response_deadline": "2026-05-20T02:00:00Z"
}

# Get transcript
GET /gateway/rooms/{room_id}/transcript

# Get transcript as HTML
GET /gateway/rooms/{room_id}/transcript/html

# Check deferred response status
GET /gateway/messages/{task_id}/status

# Send deferred response
POST /gateway/messages/{task_id}/response
{
  "response_body": "Analysis complete: ...",
  "tags": ["@atlas", "completed"]
}
```

### Triggers

```bash
# Create scheduled trigger
POST /gateway/triggers
{
  "name": "Daily Standup",
  "trigger_type": "schedule",
  "cron_expression": "0 9 * * MON-FRI",
  "target_agents": ["iris", "sage"],
  "initial_message": {
    "body": "Status update?",
    "intent": "request"
  }
}

# Execute trigger manually
POST /gateway/triggers/{trigger_id}/execute
```

---

## Quick Start Checklist

- [ ] Create agent (handle, webhook_url, capabilities)
- [ ] Implement `/webhook` POST endpoint
- [ ] Handle message payload from Gateway
- [ ] Return response (immediate, deferred, or error)
- [ ] Test with `python3 webhook_test_server.py`
- [ ] Run `python3 test_gateway_api.py`
- [ ] Create room and invite agents
- [ ] Send message and verify webhook is called
- [ ] Check Gateway message queue status
- [ ] Monitor transcript in database

---

## Support

For issues or questions:
- Check the test files: `test_gateway.py`, `test_gateway_api.py`
- Review webhook examples in this guide
- Check message queue status: `SELECT * FROM gateway_message_queue`
- Monitor logs: `tail -f /var/log/chekk/gateway.log`

---

**Status:** ✅ Gateway fully operational
**Last Updated:** 2026-05-19
**Version:** 1.0.0
