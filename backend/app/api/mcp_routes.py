"""MCP (Model Context Protocol) Routes for Agent Registration and Discovery"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: Optional[Dict[str, Any]] = None


@router.post("/mcp")
async def handle_mcp(request: MCPRequest) -> Dict[str, Any]:
    """Handle MCP protocol requests for agent registration and tool discovery"""

    method = request.method
    params = request.params or {}
    request_id = request.id

    try:
        # Handle tools/list request
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "discover_server",
                            "description": "Discover the Chekk MCP server and available tools",
                        },
                        {
                            "name": "register_agent",
                            "description": "Register a new agent and get a registration token",
                        },
                        {
                            "name": "redeem_token",
                            "description": "Redeem a registration token for an API key",
                        },
                    ]
                },
            }

        # Handle tools/call request
        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if tool_name == "discover_server":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "status": "success",
                        "server": {
                            "name": "chekk-gateway",
                            "type": "http",
                            "url": "https://chekk-production.up.railway.app/api/v1/mcp",
                            "description": "Chekk Gateway MCP Server for agent registration and coordination",
                        },
                        "tools": [
                            {"name": "discover_server", "description": "Discover the Chekk MCP server and available tools"},
                            {"name": "register_agent", "description": "Register a new agent and get a registration token"},
                            {"name": "redeem_token", "description": "Redeem registration token for API key"},
                        ],
                    },
                }

            if tool_name == "register_agent":
                handle = tool_args.get("handle")
                name = tool_args.get("name")

                if not handle or not name:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32602, "message": "Missing handle or name"},
                    }

                # For now, return a dummy token
                # In production, this would call the actual registration endpoint
                import secrets
                token = f"chekk_reg_{secrets.token_urlsafe(24)}"

                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "status": "success",
                        "handle": handle,
                        "name": name,
                        "token": token,
                        "expires_in": 3600,
                    },
                }

            if tool_name == "redeem_token":
                handle = tool_args.get("handle")
                token = tool_args.get("token")

                if not handle or not token:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32602, "message": "Missing handle or token"},
                    }

                # Validate token against database
                try:
                    from sqlalchemy.orm import Session
                    from app.db.base import SessionLocal
                    from app.models.registration_token import RegistrationToken
                    import secrets
                    from uuid import uuid4
                    from datetime import datetime

                    db: Session = SessionLocal()

                    # Find the token
                    reg_token = db.query(RegistrationToken).filter(
                        RegistrationToken.token == token,
                        RegistrationToken.handle == handle
                    ).first()

                    if not reg_token:
                        return {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "Invalid token or handle mismatch"},
                        }

                    # Check if token is expired
                    if reg_token.is_expired:
                        return {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "Token has expired"},
                        }

                    # Check if token is already redeemed
                    if reg_token.redeemed:
                        return {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "Token has already been redeemed"},
                        }

                    # Generate API key and agent ID
                    api_key = f"sk_{secrets.token_urlsafe(24)}"
                    agent_id = str(uuid4())

                    # Mark token as redeemed and save credentials
                    reg_token.redeemed = 1
                    reg_token.redeemed_at = datetime.utcnow()
                    reg_token.api_key = api_key
                    reg_token.agent_id = agent_id
                    db.commit()
                    db.close()

                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "status": "success",
                            "handle": handle,
                            "agent_id": agent_id,
                            "api_key": api_key,
                            "credentials_location": f"~/.hermes/credentials/{handle}.json",
                        },
                    }
                except Exception as e:
                    logger.error(f"Token validation error: {e}")
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32603, "message": f"Token validation failed: {str(e)}"},
                    }

            # Unknown tool
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }

    except Exception as e:
        logger.error(f"MCP error: {e}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
        }


@router.get("/gateway")
async def get_gateway_info() -> Dict[str, Any]:
    """Get gateway information"""
    return {
        "status": "ok",
        "name": "Chekk Agent Gateway",
        "version": "1.0.0",
        "mcp_endpoint": "/api/mcp",
    }
