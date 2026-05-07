#!/usr/bin/env python3
"""
Kai Agent Chat Server — HTTP server for E2B sandbox.

Handles /chat and /chat/stream endpoints with session management,
cron scheduling, and event processing.

Security hardening (2026-05-07):
  - Cryptographic thread IDs (secrets.token_urlsafe) replace guessable timestamps
  - User-bound sessions (JWT user_id scoped keys)
  - Session eviction (MAX_SESSIONS with LRU cleanup)
  - Content-Length limits and safe JSON parsing
"""

import json
import logging
import os
import secrets
import sys
import time
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PORT = int(os.environ.get("CHAT_SERVER_PORT", "8080"))
_HOST = os.environ.get("CHAT_SERVER_HOST", "0.0.0.0")

# Auth secrets
_JWT_SECRET = os.environ.get("CHAT_JWT_SECRET", "")
_SANDBOX_AUTH_SECRET = os.environ.get("SANDBOX_AUTH_SECRET", "")

# ---------------------------------------------------------------------------
# Session store with eviction
# ---------------------------------------------------------------------------

_sessions_history = {}  # composite_key → list of message dicts
MAX_SESSIONS = 10000    # Maximum concurrent sessions before eviction


def _evict_oldest_sessions():
    """Evict the oldest 10% of sessions when we hit the limit."""
    if len(_sessions_history) < MAX_SESSIONS:
        return
    evict_count = max(1, len(_sessions_history) // 10)
    keys_to_evict = list(_sessions_history.keys())[:evict_count]
    for key in keys_to_evict:
        del _sessions_history[key]
    logger.info("Evicted %d sessions (total was %d)", evict_count, len(_sessions_history) + evict_count)


# ---------------------------------------------------------------------------
# Body size limit
# ---------------------------------------------------------------------------

_MAX_BODY_SIZE = 1_048_576  # 1 MB


# ---------------------------------------------------------------------------
# Cron state
# ---------------------------------------------------------------------------

_cron_thread = None
_cron_stop_event = threading.Event()


def _start_cron_scheduler():
    """Start the cron scheduler in a background thread."""
    global _cron_thread
    if _cron_thread and _cron_thread.is_alive():
        return

    def _run_cron():
        try:
            from cron.scheduler import run_scheduler
            run_scheduler(_cron_stop_event)
        except Exception as e:
            logger.exception("Cron scheduler crashed: %s", e)

    _cron_thread = threading.Thread(target=_run_cron, daemon=True, name="cron-scheduler")
    _cron_thread.start()
    logger.info("Cron scheduler started")


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def _create_agent(model=None, session_id=None, system_prompt=None):
    """Create an AIAgent instance with current configuration."""
    from run_agent import AIAgent

    model = model or os.environ.get("DASH_MODEL") or os.environ.get("KAI_MODEL") or "anthropic/claude-sonnet-4.6"
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    return AIAgent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        provider="openrouter",
        max_iterations=25,
        quiet_mode=True,
        platform="web",
        session_id=session_id,
        ephemeral_system_prompt=system_prompt,
    )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _verify_backend_auth(headers) -> bool:
    """Verify the sandbox auth secret for internal endpoints."""
    if not _SANDBOX_AUTH_SECRET:
        return True
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return auth[7:] == _SANDBOX_AUTH_SECRET


def _verify_chat_token(headers) -> tuple:
    """Verify Bearer JWT token for direct client-to-sandbox chat requests.

    Returns:
        (True, user_id) on success -- user_id extracted from JWT sub/user_id claim
        (False, None) on failure
    """
    if not _JWT_SECRET:
        return (True, "anonymous")  # No secret configured — skip auth (dev mode)
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return (False, None)
    token = auth[7:]
    try:
        import jwt
        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "iss"]})
        if payload.get("iss") != "chat-session":
            return (False, None)
        # Extract user identity from JWT claims
        user_id = payload.get("sub") or payload.get("user_id") or "anonymous"
        return (True, str(user_id))
    except Exception:
        return (False, None)


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def _read_request_body(handler) -> bytes | None:
    """Read request body with Content-Length limit.

    Returns the body bytes, or None if the request should be rejected
    (handler will have already sent the error response).
    """
    content_length = handler.headers.get("Content-Length")
    if content_length is not None:
        try:
            length = int(content_length)
        except (TypeError, ValueError):
            handler._json_response(400, {"error": "Invalid Content-Length"})
            return None
        if length > _MAX_BODY_SIZE:
            handler._json_response(413, {"error": f"Request body too large (max {_MAX_BODY_SIZE} bytes)"})
            return None
        return handler.rfile.read(length)
    else:
        # No Content-Length -- read up to limit
        return handler.rfile.read(_MAX_BODY_SIZE)


def _parse_json_body(handler, raw_body: bytes) -> dict | None:
    """Parse JSON body safely.

    Returns the parsed dict, or None if parsing failed
    (handler will have already sent the error response).
    """
    try:
        return json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        handler._json_response(400, {"error": f"Invalid JSON: {e}"})
        return None


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class ChatHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the chat server."""

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass

    def _json_response(self, status_code, data):
        """Send a JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _stream_response(self, generator):
        """Send a streaming response."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        try:
            for chunk in generator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._json_response(200, {
                "status": "ok",
                "server": "kai-chat",
                "timestamp": time.time(),
            })
            return

        self._json_response(404, {"error": "Not found"})

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # --- Internal endpoints (backend auth) ---

        if path == "/secrets-updated":
            if not _verify_backend_auth(self.headers):
                self._json_response(401, {"error": "Unauthorized"})
                return
            # Reload environment from any updated secrets
            self._json_response(200, {"ok": True})
            return

        if path == "/event":
            if not _verify_backend_auth(self.headers):
                self._json_response(401, {"error": "Unauthorized"})
                return
            raw = _read_request_body(self)
            if raw is None:
                return
            body = _parse_json_body(self, raw)
            if body is None:
                return
            event_type = body.get("type", "")
            logger.info("Event received: %s", event_type)
            self._json_response(200, {"ok": True})
            return

        # --- Chat endpoints (JWT auth) ---

        if path == "/chat":
            auth_result, user_id = _verify_chat_token(self.headers)
            if not auth_result:
                self._json_response(401, {"error": "Invalid or expired chat session token"})
                return

            raw = _read_request_body(self)
            if raw is None:
                return
            body = _parse_json_body(self, raw)
            if body is None:
                return

            message = body.get("message", "").strip()
            if not message:
                self._json_response(400, {"error": "message required"})
                return

            thread_id = body.get("threadId", "")
            session_key = thread_id or f"web_{secrets.token_urlsafe(16)}"

            # Composite key: user_id:session_key -- prevents cross-user access
            composite_key = f"{user_id}:{session_key}"

            _evict_oldest_sessions()
            if composite_key not in _sessions_history:
                _sessions_history[composite_key] = []
            history = _sessions_history[composite_key]

            try:
                agent = _create_agent(session_id=session_key)
                result = agent.run_conversation(message, conversation_history=history)

                _sessions_history[composite_key] = result.get("messages", [])

                self._json_response(200, {
                    "response": result.get("response", ""),
                    "threadId": session_key,
                    "messages": result.get("messages", []),
                })
            except Exception as e:
                logger.exception("Chat error: %s", e)
                self._json_response(500, {"error": str(e)})
            return

        if path == "/chat/stream":
            auth_result, user_id = _verify_chat_token(self.headers)
            if not auth_result:
                self._json_response(401, {"error": "Invalid or expired chat session token"})
                return

            raw = _read_request_body(self)
            if raw is None:
                return
            body = _parse_json_body(self, raw)
            if body is None:
                return

            message = body.get("message", "").strip()
            if not message:
                self._json_response(400, {"error": "message required"})
                return

            thread_id = body.get("threadId", "")
            session_key = thread_id or f"web_{secrets.token_urlsafe(16)}"

            # Composite key: user_id:session_key -- prevents cross-user access
            composite_key = f"{user_id}:{session_key}"

            _evict_oldest_sessions()
            if composite_key not in _sessions_history:
                _sessions_history[composite_key] = []
            history = _sessions_history[composite_key]

            try:
                agent = _create_agent(session_id=session_key)

                def _stream():
                    try:
                        result = agent.run_conversation(
                            message,
                            conversation_history=history,
                            stream=True,
                        )

                        if hasattr(result, "__iter__") and not isinstance(result, (str, dict)):
                            final_result = None
                            for chunk in result:
                                if isinstance(chunk, dict):
                                    if chunk.get("type") == "final":
                                        final_result = chunk
                                        continue
                                    yield f"data: {json.dumps(chunk)}\n\n"
                                elif isinstance(chunk, str):
                                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                            if final_result:
                                _sessions_history[composite_key] = final_result.get("messages", [])
                                yield f"data: {json.dumps({'type': 'done', 'threadId': session_key})}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'done', 'threadId': session_key})}\n\n"
                        else:
                            # Non-streaming fallback
                            if isinstance(result, dict):
                                _sessions_history[composite_key] = result.get("messages", [])
                                response_text = result.get("response", "")
                            else:
                                response_text = str(result)
                            yield f"data: {json.dumps({'type': 'token', 'content': response_text})}\n\n"
                            yield f"data: {json.dumps({'type': 'done', 'threadId': session_key})}\n\n"

                    except Exception as e:
                        logger.exception("Stream error: %s", e)
                        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

                self._stream_response(_stream())
            except Exception as e:
                logger.exception("Chat stream setup error: %s", e)
                self._json_response(500, {"error": str(e)})
            return

        self._json_response(404, {"error": "Not found"})


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

def main():
    """Start the chat server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Start cron scheduler
    _start_cron_scheduler()

    port = _PORT
    server = HTTPServer((_HOST, port), ChatHandler)
    logger.info("Kai chat server (real agent) on port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
