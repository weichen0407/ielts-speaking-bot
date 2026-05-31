"""WebSocket server channel: nanobot acts as a WebSocket server and serves connected clients."""

from __future__ import annotations

import asyncio
import base64
import binascii
import email.utils
import hashlib
import hmac
import http
import json
import mimetypes
import re
import secrets
import shutil
import ssl
import time
import uuid
from datetime import datetime
from collections.abc import Callable
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger
from pydantic import Field, field_validator, model_validator
import yaml
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.bus.events import OUTBOUND_META_AGENT_UI, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.command.builtin import builtin_command_palette
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.utils.helpers import safe_filename
from nanobot.utils.media_decode import (
    FileSizeExceeded,
    save_base64_data_url,
)
from nanobot.utils.subagent_channel_display import scrub_subagent_messages_for_channel
from nanobot.utils.webui_thread_disk import delete_webui_thread
from nanobot.utils.webui_transcript import append_transcript_object, build_webui_thread_response
from nanobot.utils.webui_turn_helpers import websocket_turn_wall_started_at

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


def _strip_trailing_slash(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path or "/"


def _normalize_config_path(path: str) -> str:
    return _strip_trailing_slash(path)


class WebSocketConfig(Base):
    """WebSocket server channel configuration.

    Clients connect with URLs like ``ws://{host}:{port}{path}?client_id=...&token=...``.
    - ``client_id``: Used for ``allow_from`` authorization; if omitted, a value is generated and logged.
    - ``token``: If non-empty, the ``token`` query param may match this static secret; short-lived tokens
      from ``token_issue_path`` are also accepted.
    - ``token_issue_path``: If non-empty, **GET** (HTTP/1.1) to this path returns JSON
      ``{"token": "...", "expires_in": <seconds>}``; use ``?token=...`` when opening the WebSocket.
      Must differ from ``path`` (the WS upgrade path). If the client runs in the **same process** as
      nanobot and shares the asyncio loop, use a thread or async HTTP client for GET—do not call
      blocking ``urllib`` or synchronous ``httpx`` from inside a coroutine.
    - ``token_issue_secret``: If non-empty, token requests must send ``Authorization: Bearer <secret>`` or
      ``X-Nanobot-Auth: <secret>``.
    - ``websocket_requires_token``: If True, the handshake must include a valid token (static or issued and not expired).
    - Each connection has its own session: a unique ``chat_id`` maps to the agent session internally.
    - ``media`` field in outbound messages contains local filesystem paths; remote clients need a
      shared filesystem or an HTTP file server to access these files.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/"
    token: str = ""
    token_issue_path: str = ""
    token_issue_secret: str = ""
    token_ttl_s: int = Field(default=300, ge=30, le=86_400)
    websocket_requires_token: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    # Default 36 MB, upper 40 MB: supports up to 4 images at ~6 MB each after
    # client-side Worker normalization (see webui Composer). 4 × 6 MB × 1.37
    # (base64 overhead) + envelope framing stays under 36 MB; the 40 MB ceiling
    # leaves a small margin for sender slop without opening a DoS avenue.
    max_message_bytes: int = Field(default=37_748_736, ge=1024, le=41_943_040)
    ping_interval_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ping_timeout_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    @field_validator("path")
    @classmethod
    def path_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError('path must start with "/"')
        return _normalize_config_path(value)

    @field_validator("token_issue_path")
    @classmethod
    def token_issue_path_format(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.startswith("/"):
            raise ValueError('token_issue_path must start with "/"')
        return _normalize_config_path(value)

    @model_validator(mode="after")
    def token_issue_path_differs_from_ws_path(self) -> Self:
        if not self.token_issue_path:
            return self
        if _normalize_config_path(self.token_issue_path) == _normalize_config_path(self.path):
            raise ValueError("token_issue_path must differ from path (the WebSocket upgrade path)")
        return self

    @model_validator(mode="after")
    def wildcard_host_requires_auth(self) -> Self:
        if self.host not in ("0.0.0.0", "::"):
            return self
        if self.token.strip() or self.token_issue_secret.strip():
            return self
        raise ValueError(
            "host is 0.0.0.0 (all interfaces) but neither token nor "
            "token_issue_secret is set — set one to prevent unauthenticated access"
        )


def _http_json_response(data: dict[str, Any], *, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", "application/json; charset=utf-8"),
        ]
    )
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, headers, body)


def publish_runtime_model_update(
    bus: MessageBus,
    model: str,
    model_preset: str | None,
) -> None:
    """Enqueue a runtime model snapshot for websocket subscribers (fan-out in-channel)."""
    bus.outbound.put_nowait(OutboundMessage(
        channel="websocket",
        chat_id="*",
        content="",
        metadata={
            "_runtime_model_updated": True,
            "model": model,
            "model_preset": model_preset,
        },
    ))


def _default_model_name_from_config() -> str | None:
    """Resolved model string from on-disk config (bootstrap fallback)."""
    try:
        from nanobot.config.loader import load_config

        model = load_config().resolve_preset().model.strip()
        return model or None
    except Exception as e:
        logger.debug("bootstrap model_name could not load from config: {}", e)
        return None


def _resolve_bootstrap_model_name(
    runtime_name: Callable[[], str | None] | None,
) -> str | None:
    """Prefer an in-process resolver (e.g. AgentLoop); else config-derived default."""
    if runtime_name is not None:
        try:
            raw = runtime_name()
        except Exception as e:
            logger.debug("bootstrap runtime model resolver failed: {}", e)
        else:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped:
                    return stripped
    return _default_model_name_from_config()


def _parse_request_path(path_with_query: str) -> tuple[str, dict[str, list[str]]]:
    """Parse normalized path and query parameters in one pass."""
    parsed = urlparse("ws://x" + path_with_query)
    path = _strip_trailing_slash(parsed.path or "/")
    return path, parse_qs(parsed.query, keep_blank_values=True)


def _normalize_http_path(path_with_query: str) -> str:
    """Return the path component (no query string), with trailing slash normalized (root stays ``/``)."""
    return _parse_request_path(path_with_query)[0]


def _parse_query(path_with_query: str) -> dict[str, list[str]]:
    return _parse_request_path(path_with_query)[1]


def _query_first(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key*, or None."""
    values = query.get(key)
    return values[0] if values else None


def _mask_secret_hint(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "••••"
    return f"{secret[:4]}••••{secret[-4:]}"


def _provider_requires_api_key(spec: Any) -> bool:
    if spec.backend == "azure_openai":
        return True
    if spec.is_local or spec.is_direct:
        return False
    return True


def _provider_configured_for_settings(spec: Any, provider_config: Any) -> bool:
    if _provider_requires_api_key(spec):
        return bool(provider_config.api_key)
    return bool(
        provider_config.api_key
        or provider_config.api_base
        or getattr(provider_config, "region", None)
        or getattr(provider_config, "profile", None)
    )


_WEB_SEARCH_PROVIDER_OPTIONS: tuple[dict[str, str], ...] = (
    {"name": "duckduckgo", "label": "DuckDuckGo", "credential": "none"},
    {"name": "brave", "label": "Brave Search", "credential": "api_key"},
    {"name": "tavily", "label": "Tavily", "credential": "api_key"},
    {"name": "searxng", "label": "SearXNG", "credential": "base_url"},
    {"name": "jina", "label": "Jina", "credential": "api_key"},
    {"name": "kagi", "label": "Kagi", "credential": "api_key"},
    {"name": "olostep", "label": "Olostep", "credential": "api_key"},
)
_WEB_SEARCH_PROVIDER_BY_NAME = {
    provider["name"]: provider for provider in _WEB_SEARCH_PROVIDER_OPTIONS
}


def _parse_inbound_payload(raw: str) -> str | None:
    """Parse a client frame into text; return None for empty or unrecognized content."""
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("content", "text", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return None
        return None
    return text


# Accept UUIDs and short scoped keys like "unified:default". Keeps the capability
# namespace small enough to rule out path traversal / quote injection tricks.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def _is_valid_chat_id(value: Any) -> bool:
    return isinstance(value, str) and _CHAT_ID_RE.match(value) is not None


def _parse_envelope(raw: str) -> dict[str, Any] | None:
    """Return a typed envelope dict if the frame is a new-style JSON envelope, else None.

    A frame qualifies when it parses as a JSON object with a string ``type`` field.
    Legacy frames (plain text, or ``{"content": ...}`` without ``type``) return None;
    callers should fall back to :func:`_parse_inbound_payload` for those.
    """
    text = raw.strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    t = data.get("type")
    if not isinstance(t, str):
        return None
    return data


# Per-message media limits. The server-side guard is a touch looser than the
# client's ``Worker`` normalization target (6 MB) — tolerate client slop, but
# still cap total ingress at ``_MAX_IMAGES_PER_MESSAGE * _MAX_IMAGE_BYTES``
# which fits comfortably inside ``max_message_bytes``.
_MAX_IMAGES_PER_MESSAGE = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_VIDEOS_PER_MESSAGE = 1
_MAX_VIDEO_BYTES = 20 * 1024 * 1024

# Image MIME whitelist — matches the Composer's ``accept`` list. SVG is
# explicitly excluded to avoid the XSS surface inside embedded scripts.
_IMAGE_MIME_ALLOWED: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

_VIDEO_MIME_ALLOWED: frozenset[str] = frozenset({
    "video/mp4",
    "video/webm",
    "video/quicktime",
})

_UPLOAD_MIME_ALLOWED: frozenset[str] = _IMAGE_MIME_ALLOWED | _VIDEO_MIME_ALLOWED

_DATA_URL_MIME_RE = re.compile(r"^data:([^;]+);base64,", re.DOTALL)


def _extract_data_url_mime(url: str) -> str | None:
    """Return the MIME type of a ``data:<mime>;base64,...`` URL, else ``None``."""
    if not isinstance(url, str):
        return None
    m = _DATA_URL_MIME_RE.match(url)
    if not m:
        return None
    return m.group(1).strip().lower() or None


_LOCALHOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Matches the legacy chat-id pattern but allows file-system-safe stems too,
# so the API can address sessions whose keys came from non-WebSocket channels.
_API_KEY_RE = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")


def _decode_api_key(raw_key: str) -> str | None:
    """Decode a percent-encoded API path segment, then validate the result."""
    key = unquote(raw_key)
    if _API_KEY_RE.match(key) is None:
        return None
    return key


def _is_localhost(connection: Any) -> bool:
    """Return True if *connection* originated from the loopback interface."""
    addr = getattr(connection, "remote_address", None)
    if not addr:
        return False
    host = addr[0] if isinstance(addr, tuple) else addr
    if not isinstance(host, str):
        return False
    # ``::ffff:127.0.0.1`` is loopback in IPv6-mapped form.
    if host.startswith("::ffff:"):
        host = host[7:]
    return host in _LOCALHOSTS


def _http_response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
    extra_headers: list[tuple[str, str]] | None = None,
) -> Response:
    headers = [
        ("Date", email.utils.formatdate(usegmt=True)),
        ("Connection", "close"),
        ("Content-Length", str(len(body))),
        ("Content-Type", content_type),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, Headers(headers), body)


def _http_error(status: int, message: str | None = None) -> Response:
    body = (message or http.HTTPStatus(status).phrase).encode("utf-8")
    return _http_response(body, status=status)


def _bearer_token(headers: Any) -> str | None:
    """Pull a Bearer token out of standard or query-style headers."""
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _is_websocket_upgrade(request: WsRequest) -> bool:
    """Detect an actual WS upgrade; plain HTTP GETs to the same path should fall through."""
    upgrade = request.headers.get("Upgrade") or request.headers.get("upgrade")
    connection = request.headers.get("Connection") or request.headers.get("connection")
    if not upgrade or "websocket" not in upgrade.lower():
        return False
    if not connection or "upgrade" not in connection.lower():
        return False
    return True


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 without padding — compact + friendly in URL paths."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Reverse of :func:`_b64url_encode`; caller handles ``ValueError``."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# Allowed MIME types we actually serve from the media endpoint. Anything
# outside this set is degraded to ``application/octet-stream`` so an
# attacker who somehow gets a signed URL for an unexpected file type can't
# trick the browser into sniffing executable content.
_MEDIA_ALLOWED_MIMES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "video/quicktime",
})


def _issue_route_secret_matches(headers: Any, configured_secret: str) -> bool:
    """Return True if the token-issue HTTP request carries credentials matching ``token_issue_secret``."""
    if not configured_secret:
        return True
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        return hmac.compare_digest(supplied, configured_secret)
    header_token = headers.get("X-Nanobot-Auth") or headers.get("x-nanobot-auth")
    if not header_token:
        return False
    return hmac.compare_digest(header_token.strip(), configured_secret)


class WebSocketChannel(BaseChannel):
    """Run a local WebSocket server; forward text/JSON messages to the message bus."""

    name = "websocket"
    display_name = "WebSocket"

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        *,
        session_manager: "SessionManager | None" = None,
        static_dist_path: Path | None = None,
        runtime_model_name: Callable[[], str | None] | None = None,
    ):
        if isinstance(config, dict):
            config = WebSocketConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebSocketConfig = config
        # chat_id -> connections subscribed to it (fan-out target).
        self._subs: dict[str, set[Any]] = {}
        # connection -> chat_ids it is subscribed to (O(1) cleanup on disconnect).
        self._conn_chats: dict[Any, set[str]] = {}
        # connection -> default chat_id for legacy frames that omit routing.
        self._conn_default: dict[Any, str] = {}
        # Single-use tokens consumed at WebSocket handshake.
        self._issued_tokens: dict[str, float] = {}
        # Multi-use tokens for HTTP routes served beside WS; checked but not consumed.
        self._api_tokens: dict[str, float] = {}
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._session_manager = session_manager
        self._static_dist_path: Path | None = (
            static_dist_path.resolve() if static_dist_path is not None else None
        )
        self._runtime_model_name = runtime_model_name
        self._subagent_status_history: list[dict[str, Any]] = []
        # Process-local secret used to HMAC-sign media URLs. The signed URL is
        # the capability — anyone who holds a valid URL can fetch that one
        # file, nothing else. The secret regenerates on restart so links
        # become self-expiring (callers just refresh the session list).
        self._media_secret: bytes = secrets.token_bytes(32)

    # -- Subscription bookkeeping -------------------------------------------

    def _attach(self, connection: Any, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _cleanup_connection(self, connection: Any) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        chat_ids = self._conn_chats.pop(connection, set())
        for cid in chat_ids:
            subs = self._subs.get(cid)
            if subs is None:
                continue
            subs.discard(connection)
            if not subs:
                self._subs.pop(cid, None)
        self._conn_default.pop(connection, None)

    async def _maybe_push_active_goal_state(self, chat_id: str) -> None:
        """Replay an active sustained goal from session metadata after *chat_id* is subscribed.

        Goal metadata lives on the session JSONL and survives gateway restarts, but
        connected clients normally see it via ``goal_state`` / ``turn_end`` frames.
        Pushing here makes refresh + reconnect restore the strip without a new model turn.
        """
        if self._session_manager is None:
            return
        row = self._session_manager.read_session_file(f"websocket:{chat_id}")
        meta = row.get("metadata", {}) if isinstance(row, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        blob = goal_state_ws_blob(meta)
        if not blob.get("active"):
            return
        await self.send_goal_state(chat_id, blob)

    async def _maybe_push_turn_run_wall_clock(self, chat_id: str) -> None:
        """Replay ``goal_status: running`` when a turn is still active (same-process refresh)."""
        t0 = websocket_turn_wall_started_at(chat_id)
        if t0 is None:
            return
        await self.send_goal_status(chat_id, "running", started_at=t0)

    async def _hydrate_after_subscribe(self, chat_id: str) -> None:
        """Replay goal/run strip state after subscribe (same-process refresh)."""
        await self._maybe_push_active_goal_state(chat_id)
        await self._maybe_push_turn_run_wall_clock(chat_id)

    async def _send_event(self, connection: Any, event: str, **fields: Any) -> None:
        """Send a control event (attached, error, ...) to a single connection."""
        payload: dict[str, Any] = {"event": event}
        payload.update(fields)
        raw = json.dumps(payload, ensure_ascii=False)
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
        except Exception as e:
            self.logger.warning("failed to send {} event: {}", event, e)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebSocketConfig().model_dump(by_alias=True)

    def _expected_path(self) -> str:
        return _normalize_config_path(self.config.path)

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        cert = self.config.ssl_certfile.strip()
        key = self.config.ssl_keyfile.strip()
        if not cert and not key:
            return None
        if not cert or not key:
            raise ValueError(
                "ssl_certfile and ssl_keyfile must both be set for WSS, or both left empty"
            )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    _MAX_ISSUED_TOKENS = 10_000

    def _purge_expired_issued_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._issued_tokens.items()):
            if now > expiry:
                self._issued_tokens.pop(token_key, None)

    def _take_issued_token_if_valid(self, token_value: str | None) -> bool:
        """Validate and consume one issued token (single use per connection attempt).

        Uses single-step pop to minimize the window between lookup and removal;
        safe under asyncio's single-threaded cooperative model.
        """
        if not token_value:
            return False
        self._purge_expired_issued_tokens()
        expiry = self._issued_tokens.pop(token_value, None)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            return False
        return True

    def _handle_token_issue_http(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self.logger.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        self._purge_expired_issued_tokens()
        if len(self._issued_tokens) >= self._MAX_ISSUED_TOKENS:
            self.logger.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self._issued_tokens),
            )
            return _http_json_response({"error": "too many outstanding tokens"}, status=429)
        token_value = f"nbwt_{secrets.token_urlsafe(32)}"
        self._issued_tokens[token_value] = time.monotonic() + float(self.config.token_ttl_s)

        return _http_json_response(
            {"token": token_value, "expires_in": self.config.token_ttl_s}
        )

    # -- HTTP dispatch ------------------------------------------------------

    async def _dispatch_http(self, connection: Any, request: WsRequest) -> Any:
        """Route an inbound HTTP request to a handler or to the WS upgrade path."""
        got, query = _parse_request_path(request.path)

        # 1. Token issue endpoint (legacy, optional, gated by configured secret).
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue_http(connection, request)

        # 2. Bootstrap (`/webui/bootstrap`): mint WS/API tokens + shared session metadata.
        if got == "/webui/bootstrap":
            return self._handle_bootstrap(connection, request)

        # 3. REST handlers co-located with this channel (sessions, settings, …).
        if got == "/api/sessions":
            return self._handle_sessions_list(request)

        if got == "/api/settings":
            return self._handle_settings(request)

        if got == "/api/commands":
            return self._handle_commands(request)

        if got == "/api/settings/update":
            return self._handle_settings_update(request)

        if got == "/api/settings/provider/update":
            return self._handle_settings_provider_update(request)

        if got == "/api/settings/web-search/update":
            return self._handle_settings_web_search_update(request)

        if got == "/api/settings/voice/update":
            return self._handle_settings_voice_update(request)

        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return self._handle_session_messages(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/webui-thread$", got)
        if m:
            return self._handle_webui_thread_get(request, m.group(1))

        # NOTE: websockets' HTTP parser only accepts GET, so we cannot expose a
        # true ``DELETE`` verb. The action is folded into the path instead.
        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return self._handle_session_delete(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/notes$", got)
        if m:
            return self._handle_session_notes(request, m.group(1))

        # Global notes (cross-session user notebook)
        m = re.match(r"^/api/notes$", got)
        if m:
            return self._handle_global_notes(request)

        # Notes AI Assistant endpoints
        m = re.match(r"^/api/notes/ai-reply$", got)
        if m:
            return self._handle_notes_ai_reply_request(request)

        m = re.match(r"^/api/notes/ai-reply/status$", got)
        if m:
            return self._handle_notes_ai_reply_status(request)

        m = re.match(r"^/api/notes/ai-replies$", got)
        if m:
            return self._handle_notes_ai_replies_list(request)

        # Benative endpoints
        m = re.match(r"^/api/sessions/([^/]+)/benative$", got)
        if m:
            return self._handle_session_benative(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/benative/article$", got)
        if m:
            return self._handle_session_benative_article(request, m.group(1))

        m = re.match(r"^/api/sessions/([^/]+)/benative/responses$", got)
        if m:
            return self._handle_session_benative_responses(request, m.group(1))

        # /api/benative/articles - list available articles
        if got == "/api/benative/articles":
            return self._handle_benative_articles(request)

        # IELTS Exam API
        m = re.match(r"^/api/ielts/exam/start$", got)
        if m:
            return self._handle_ielts_exam_start(request)

        m = re.match(r"^/api/ielts/exam/answer$", got)
        if m:
            return self._handle_ielts_exam_answer(request)

        m = re.match(r"^/api/ielts/exam/next$", got)
        if m:
            return self._handle_ielts_exam_next(request)

        m = re.match(r"^/api/ielts/exam/end$", got)
        if m:
            return self._handle_ielts_exam_end(request)

        m = re.match(r"^/api/ielts/exam/list$", got)
        if m:
            return self._handle_ielts_exam_list(request)

        # Wiki API
        m = re.match(r"^/api/wiki/search$", got)
        if m:
            return self._handle_wiki_search(request)
        m = re.match(r"^/api/wiki/page$", got)
        if m:
            return self._handle_wiki_page(request)
        m = re.match(r"^/api/wiki/graph$", got)
        if m:
            return self._handle_wiki_graph(request)
        m = re.match(r"^/api/wiki/patch$", got)
        if m:
            return self._handle_wiki_patch(request)
        m = re.match(r"^/api/wiki/rebuild-index$", got)
        if m:
            return self._handle_wiki_rebuild_index(request)
        m = re.match(r"^/api/wiki/lint$", got)
        if m:
            return self._handle_wiki_lint(request)
        m = re.match(r"^/api/wiki/sync-log$", got)
        if m:
            return self._handle_wiki_sync_log(request)

        # Admin / monitor API
        if got == "/api/admin/monitor":
            return self._handle_admin_monitor(request)
        if got == "/api/admin/triggers":
            return self._handle_admin_trigger_update(request)

        # Signed media fetch: ``<sig>`` is an HMAC over ``<payload>``; the
        # payload decodes to a path inside :func:`get_media_dir`. See
        # :meth:`_sign_media_path` for the inverse direction used to build
        # these URLs when replaying a session.
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2))

        # 4. WebSocket upgrade (the channel's primary purpose). Only run the
        # handshake gate on requests that actually ask to upgrade; otherwise
        # a bare ``GET /`` from the browser would be rejected as an
        # unauthorized WS handshake instead of serving the SPA's index.html.
        expected_ws = self._expected_path()
        if got == expected_ws and _is_websocket_upgrade(request):
            client_id = _query_first(query, "client_id") or ""
            if len(client_id) > 128:
                client_id = client_id[:128]
            if not self.is_allowed(client_id):
                return connection.respond(403, "Forbidden")
            return self._authorize_websocket_handshake(connection, query)

        # 5. Static SPA serving (only if a build directory was wired in).
        if self._static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    # -- HTTP route handlers ------------------------------------------------

    def _check_api_token(self, request: WsRequest) -> bool:
        """Validate a request against the API token pool (multi-use, TTL-bound)."""
        self._purge_expired_api_tokens()
        token = _bearer_token(request.headers) or _query_first(
            _parse_query(request.path), "token"
        )
        if not token:
            return False
        expiry = self._api_tokens.get(token)
        if expiry is None or time.monotonic() > expiry:
            self._api_tokens.pop(token, None)
            return False
        return True

    def _purge_expired_api_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._api_tokens.items()):
            if now > expiry:
                self._api_tokens.pop(token_key, None)

    def _handle_bootstrap(self, connection: Any, request: Any) -> Response:
        # When a secret is configured (token_issue_secret or static token),
        # validate it regardless of source IP.  This secures deployments
        # behind a reverse proxy where all connections appear as localhost.
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return _http_error(401, "Unauthorized")
        elif not _is_localhost(connection):
            # No secret configured: only allow localhost (local dev mode).
            return _http_error(403, "bootstrap is localhost-only")
        # Cap outstanding tokens to avoid runaway growth from a misbehaving client.
        self._purge_expired_issued_tokens()
        self._purge_expired_api_tokens()
        if (
            len(self._issued_tokens) >= self._MAX_ISSUED_TOKENS
            or len(self._api_tokens) >= self._MAX_ISSUED_TOKENS
        ):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
            )
        token = f"nbwt_{secrets.token_urlsafe(32)}"
        expiry = time.monotonic() + float(self.config.token_ttl_s)
        # Same string registered in both pools: the WS handshake consumes one copy
        # while the REST surface keeps validating the other until TTL expiry.
        self._issued_tokens[token] = expiry
        self._api_tokens[token] = expiry
        return _http_json_response(
            {
                "token": token,
                "ws_path": self._expected_path(),
                "expires_in": self.config.token_ttl_s,
                "model_name": _resolve_bootstrap_model_name(self._runtime_model_name),
            }
        )

    def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        sessions = self._session_manager.list_sessions()
        # Sidebar/chat listing for WS-backed sessions only — CLI / Slack / etc.
        # keys are not intended for resume over this HTTP surface.
        cleaned = [
            {k: v for k, v in s.items() if k != "path"}
            for s in sessions
            if isinstance(s.get("key"), str) and s["key"].startswith("websocket:")
        ]
        return _http_json_response({"sessions": cleaned})

    def _settings_payload(self, *, requires_restart: bool = False) -> dict[str, Any]:
        from nanobot.config.loader import get_config_path, load_config
        from nanobot.providers.registry import PROVIDERS, find_by_name

        config = load_config()
        defaults = config.agents.defaults
        provider_name = config.get_provider_name(defaults.model) or defaults.provider
        provider = config.get_provider(defaults.model)
        selected_provider = provider_name
        if defaults.provider != "auto":
            spec = find_by_name(defaults.provider)
            selected_provider = spec.name if spec else provider_name
        providers = []
        for spec in PROVIDERS:
            provider_config = getattr(config.providers, spec.name, None)
            if provider_config is None or spec.is_oauth:
                continue
            providers.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "configured": _provider_configured_for_settings(spec, provider_config),
                    "api_key_required": _provider_requires_api_key(spec),
                    "api_key_hint": _mask_secret_hint(provider_config.api_key),
                    "api_base": provider_config.api_base,
                    "default_api_base": spec.default_api_base or None,
                }
            )
        search_config = config.tools.web.search
        search_provider = (
            search_config.provider
            if search_config.provider in _WEB_SEARCH_PROVIDER_BY_NAME
            else "duckduckgo"
        )
        channels_config = config.channels
        return {
            "agent": {
                "model": defaults.model,
                "provider": selected_provider,
                "resolved_provider": provider_name,
                "has_api_key": bool(provider and provider.api_key),
            },
            "providers": providers,
            "web_search": {
                "provider": search_provider,
                "api_key_hint": _mask_secret_hint(search_config.api_key),
                "base_url": search_config.base_url or None,
                "providers": list(_WEB_SEARCH_PROVIDER_OPTIONS),
            },
            "voice": {
                "provider": channels_config.voice_provider,
                "whisperlivekit_autostart": channels_config.whisperlivekit_autostart,
                "whisperlivekit_url": channels_config.whisperlivekit_url,
                "whisperlivekit_language": channels_config.whisperlivekit_language,
                "whisperlivekit_backend": channels_config.whisperlivekit_backend,
                "whisperlivekit_model": channels_config.whisperlivekit_model,
            },
            "runtime": {
                "config_path": str(get_config_path().expanduser()),
            },
            "requires_restart": requires_restart,
        }

    def _handle_settings(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(self._settings_payload())

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_settings_update(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.config.loader import load_config, save_config
        from nanobot.providers.registry import find_by_name

        query = _parse_query(request.path)
        config = load_config()
        defaults = config.agents.defaults
        changed = False

        model = _query_first(query, "model")
        if model is not None:
            model = model.strip()
            if not model:
                return _http_error(400, "model is required")
            if defaults.model != model:
                defaults.model = model
                changed = True

        provider = _query_first(query, "provider")
        if provider is not None:
            provider = provider.strip()
            if not provider:
                return _http_error(400, "provider is required")
            if find_by_name(provider) is None:
                return _http_error(400, "unknown provider")
            provider_config = getattr(config.providers, provider, None)
            spec = find_by_name(provider)
            if (
                provider_config is None
                or spec is None
                or not _provider_configured_for_settings(spec, provider_config)
            ):
                return _http_error(400, "provider is not configured")
            if defaults.provider != provider:
                defaults.provider = provider
                changed = True

        if changed:
            save_config(config)
        # LLM provider/model changes are hot-reloaded by AgentLoop before each
        # new turn via the provider snapshot loader, so a restart is unnecessary.
        return _http_json_response(self._settings_payload(requires_restart=False))

    def _handle_settings_provider_update(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.config.loader import load_config, save_config
        from nanobot.providers.registry import find_by_name

        query = _parse_query(request.path)
        provider_name = (_query_first(query, "provider") or "").strip()
        if not provider_name:
            return _http_error(400, "provider is required")
        spec = find_by_name(provider_name)
        if spec is None or spec.is_oauth:
            return _http_error(400, "unknown provider")

        config = load_config()
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config is None:
            return _http_error(400, "unknown provider")

        changed = False
        if "api_key" in query or "apiKey" in query:
            api_key = _query_first(query, "api_key")
            if api_key is None:
                api_key = _query_first(query, "apiKey")
            api_key = (api_key or "").strip() or None
            if provider_config.api_key != api_key:
                provider_config.api_key = api_key
                changed = True

        if "api_base" in query or "apiBase" in query:
            api_base = _query_first(query, "api_base")
            if api_base is None:
                api_base = _query_first(query, "apiBase")
            api_base = (api_base or "").strip() or None
            if provider_config.api_base != api_base:
                provider_config.api_base = api_base
                changed = True

        if changed:
            save_config(config)
        # API key/base changes are picked up by the next provider snapshot refresh.
        return _http_json_response(self._settings_payload(requires_restart=False))

    def _handle_settings_web_search_update(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.config.loader import load_config, save_config

        query = _parse_query(request.path)
        provider_name = (_query_first(query, "provider") or "").strip().lower()
        provider_option = _WEB_SEARCH_PROVIDER_BY_NAME.get(provider_name)
        if provider_option is None:
            return _http_error(400, "unknown web search provider")

        config = load_config()
        search_config = config.tools.web.search
        previous_provider = search_config.provider
        changed = False

        def set_value(attr: str, value: str | None) -> None:
            nonlocal changed
            if getattr(search_config, attr) != value:
                setattr(search_config, attr, value)
                changed = True

        if search_config.provider != provider_name:
            search_config.provider = provider_name
            changed = True

        credential = provider_option["credential"]
        if credential == "none":
            set_value("api_key", "")
            set_value("base_url", "")
        elif credential == "base_url":
            base_url = _query_first(query, "base_url")
            if base_url is None:
                base_url = _query_first(query, "baseUrl")
            base_url = base_url.strip() if base_url is not None else None
            if not base_url and previous_provider == provider_name and search_config.base_url:
                base_url = search_config.base_url
            if not base_url:
                return _http_error(400, "base_url is required")
            set_value("base_url", base_url)
            set_value("api_key", "")
        else:
            api_key = _query_first(query, "api_key")
            if api_key is None:
                api_key = _query_first(query, "apiKey")
            api_key = api_key.strip() if api_key is not None else None
            if not api_key and previous_provider == provider_name and search_config.api_key:
                api_key = search_config.api_key
            if not api_key:
                return _http_error(400, "api_key is required")
            set_value("api_key", api_key)
            set_value("base_url", "")

        if changed:
            save_config(config)
        return _http_json_response(self._settings_payload(requires_restart=False))

    def _handle_settings_voice_update(self, request: WsRequest) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        from nanobot.config.loader import load_config, save_config

        query = _parse_query(request.path)
        config = load_config()
        channels_config = config.channels
        changed = False
        previous = {
            "voice_provider": channels_config.voice_provider,
            "whisperlivekit_autostart": channels_config.whisperlivekit_autostart,
            "whisperkit_url": channels_config.whisperlivekit_url,
            "whisperlivekit_language": channels_config.whisperlivekit_language,
            "whisperlivekit_backend": channels_config.whisperlivekit_backend,
            "whisperlivekit_model": channels_config.whisperlivekit_model,
        }

        voice_provider = _query_first(query, "voice_provider")
        if voice_provider is not None:
            voice_provider = voice_provider.strip().lower()
            if voice_provider not in ("deepgram", "whisperlivekit"):
                return _http_error(400, "invalid voice_provider: must be 'deepgram' or 'whisperlivekit'")
            if channels_config.voice_provider != voice_provider:
                channels_config.voice_provider = voice_provider
                changed = True

        whisperlivekit_autostart = _query_first(query, "whisperlivekit_autostart")
        if whisperlivekit_autostart is not None:
            autostart = whisperlivekit_autostart.lower() in ("true", "1", "yes")
            if channels_config.whisperlivekit_autostart != autostart:
                channels_config.whisperlivekit_autostart = autostart
                changed = True

        whisperlivekit_url = _query_first(query, "whisperlivekit_url")
        if whisperlivekit_url is not None:
            whisperlivekit_url = whisperlivekit_url.strip()
            parsed = urlparse(whisperlivekit_url)
            if parsed.scheme not in ("ws", "wss") or not parsed.netloc:
                return _http_error(400, "invalid whisperlivekit_url: must be a ws:// or wss:// URL")
            if _strip_trailing_slash(parsed.path or "/asr") != "/asr":
                return _http_error(400, "invalid whisperlivekit_url: path must be /asr")
            host = (parsed.hostname or "").lower()
            if channels_config.whisperlivekit_autostart and host not in ("localhost", "127.0.0.1", "::1"):
                return _http_error(
                    400,
                    "invalid whisperlivekit_url: autostart requires localhost, 127.0.0.1, or ::1",
                )
            if channels_config.whisperlivekit_url != whisperlivekit_url:
                channels_config.whisperlivekit_url = whisperlivekit_url
                changed = True

        whisperlivekit_language = _query_first(query, "whisperlivekit_language")
        if whisperlivekit_language is not None:
            whisperlivekit_language = whisperlivekit_language.strip()
            if channels_config.whisperlivekit_language != whisperlivekit_language:
                channels_config.whisperlivekit_language = whisperlivekit_language
                changed = True

        whisperlivekit_backend = _query_first(query, "whisperlivekit_backend")
        if whisperlivekit_backend is not None:
            whisperlivekit_backend = whisperlivekit_backend.strip().lower()
            if whisperlivekit_backend not in ("mlx-whisper", "faster-whisper", "whisper"):
                return _http_error(400, "invalid whisperlivekit_backend: must be 'mlx-whisper', 'faster-whisper', or 'whisper'")
            if channels_config.whisperlivekit_backend != whisperlivekit_backend:
                channels_config.whisperlivekit_backend = whisperlivekit_backend
                changed = True

        whisperlivekit_model = _query_first(query, "whisperlivekit_model")
        if whisperlivekit_model is not None:
            whisperlivekit_model = whisperlivekit_model.strip().lower()
            valid_models = ("base", "small", "medium", "large", "large-v3", "large-v3-turbo", "turbo")
            if whisperlivekit_model not in valid_models:
                return _http_error(400, f"invalid whisperlivekit_model: must be one of {valid_models}")
            if channels_config.whisperlivekit_model != whisperlivekit_model:
                channels_config.whisperlivekit_model = whisperlivekit_model
                changed = True

        if changed:
            save_config(config)

        previous_url = urlparse(previous["whisperlivekit_url"] or "ws://localhost:8000/asr")
        current_url = urlparse(channels_config.whisperlivekit_url or "ws://localhost:8000/asr")
        restart_required = any(
            previous[key] != getattr(channels_config, key)
            for key in (
                "voice_provider",
                "whisperlivekit_autostart",
                "whisperlivekit_language",
                "whisperlivekit_backend",
                "whisperlivekit_model",
            )
        ) or (
            previous_url.hostname,
            previous_url.port,
            _strip_trailing_slash(previous_url.path or "/asr"),
        ) != (
            current_url.hostname,
            current_url.port,
            _strip_trailing_slash(current_url.path or "/asr"),
        )
        return _http_json_response(self._settings_payload(requires_restart=restart_required))

    @staticmethod
    def _is_websocket_channel_session_key(key: str) -> bool:
        """True when *key* is a ``websocket:…`` session exposed on this HTTP surface."""
        return key.startswith("websocket:")

    def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        # Only ``websocket:…`` sessions are listed/served here — same boundary as
        # ``/api/sessions``. Block handcrafted URLs from probing CLI / Slack / etc.
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = self._session_manager.read_session_file(decoded_key)
        if data is None:
            return _http_error(404, "session not found")
        messages = data.get("messages")
        if isinstance(messages, list):
            scrub_subagent_messages_for_channel(messages)
        # Decorate persisted user messages with signed media URLs so the
        # client can render previews. The raw on-disk ``media`` paths are
        # stripped on the way out — they leak server filesystem layout and
        # the client never needs them once it has the signed fetch URL.
        self._augment_media_urls(data)
        return _http_json_response(data)

    def _handle_webui_thread_get(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        data = build_webui_thread_response(
            decoded_key,
            augment_user_media=self._augment_transcript_user_media,
        )
        if data is None:
            return _http_error(404, "webui thread not found")
        return _http_json_response(data)

    def _try_append_webui_transcript(self, chat_id: str, wire: dict[str, Any]) -> None:
        sk = f"websocket:{chat_id}"
        try:
            dup = json.loads(json.dumps(wire, ensure_ascii=False))
            append_transcript_object(sk, dup)
        except (ValueError, TypeError) as e:
            self.logger.warning("webui transcript append failed: {}", e)

    def _augment_transcript_user_media(self, paths: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pstr in paths:
            path = Path(pstr)
            att = self._sign_or_stage_media_path(path)
            if att is None:
                continue
            mime, _ = mimetypes.guess_type(path.name)
            kind = "video" if mime and mime.startswith("video/") else "image"
            out.append(
                {"kind": kind, "url": att["url"], "name": att.get("name", path.name)},
            )
        return out

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        is_dm: bool = False,
    ) -> None:
        meta = metadata or {}
        if meta.get("webui"):
            user_obj: dict[str, Any] = {
                "event": "user",
                "chat_id": chat_id,
                "text": content,
            }
            if media:
                user_obj["media_paths"] = list(media)
            self._try_append_webui_transcript(chat_id, user_obj)
        await super()._handle_message(
            sender_id,
            chat_id,
            content,
            media,
            metadata,
            session_key,
            is_dm,
        )

    def _augment_media_urls(self, payload: dict[str, Any]) -> None:
        """Mutate *payload* in place: each message's ``media`` path list is
        replaced by a parallel ``media_urls`` list of signed fetch URLs.

        Messages without media or with non-string path entries are left
        untouched. Paths that no longer live inside ``media_dir`` (e.g. the
        file was deleted, or the dir was relocated) are silently skipped;
        the client falls back to the historical-replay placeholder tile.
        """
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            media = msg.get("media")
            if not isinstance(media, list) or not media:
                continue
            urls: list[dict[str, str]] = []
            for entry in media:
                if not isinstance(entry, str) or not entry:
                    continue
                signed = self._sign_media_path(Path(entry))
                if signed is None:
                    continue
                urls.append({"url": signed, "name": Path(entry).name})
            if urls:
                msg["media_urls"] = urls
            # Always drop the raw paths from the wire payload.
            msg.pop("media", None)

    def _sign_media_path(self, abs_path: Path) -> str | None:
        """Return a ``/api/media/<sig>/<payload>`` URL for *abs_path*, or
        ``None`` when the path does not resolve inside the media root.

        The URL is self-authenticating: the signature binds the payload to
        this process's ``_media_secret``, so only paths we chose to sign can
        be fetched. The returned path is relative to the server origin; the
        client joins it against this server's HTTP origin (same host as WS).
        """
        try:
            media_root = get_media_dir().resolve()
            rel = abs_path.resolve().relative_to(media_root)
        except (OSError, ValueError):
            return None
        payload = _b64url_encode(rel.as_posix().encode("utf-8"))
        mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        return f"/api/media/{_b64url_encode(mac)}/{payload}"

    def _sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        """Return a signed media URL payload for *path*.

        Persisted inbound media already lives under ``get_media_dir`` and can
        be signed directly. Outbound bot-generated files may live anywhere on
        disk; copy those into the websocket media bucket first so the browser
        can fetch them through the existing signed media route without
        exposing arbitrary filesystem paths.
        """
        signed = self._sign_media_path(path)
        if signed is not None:
            return {"url": signed, "name": path.name}
        try:
            if not path.is_file():
                return None
            media_dir = get_media_dir("websocket")
            safe_name = safe_filename(path.name) or "attachment"
            staged = media_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
            shutil.copyfile(path, staged)
        except OSError as exc:
            self.logger.warning("failed to stage outbound media {}: {}", path, exc)
            return None
        signed = self._sign_media_path(staged)
        if signed is None:
            return None
        return {"url": signed, "name": path.name}

    def _handle_media_fetch(self, sig: str, payload: str) -> Response:
        """Serve a single media file previously signed via
        :meth:`_sign_media_path`. Validates the signature, decodes the
        payload to a relative path, and streams the file bytes with a
        long-lived immutable cache header (the URL already encodes the
        file identity, so caches can be aggressive)."""
        try:
            provided_mac = _b64url_decode(sig)
        except (ValueError, binascii.Error):
            return _http_error(401, "invalid signature")
        expected_mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        if not hmac.compare_digest(expected_mac, provided_mac):
            return _http_error(401, "invalid signature")
        try:
            rel_bytes = _b64url_decode(payload)
            rel_str = rel_bytes.decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            return _http_error(400, "invalid payload")
        # An attacker who somehow bypassed the HMAC check would still need
        # the resolved path to escape the media root; guard defensively.
        try:
            media_root = get_media_dir().resolve()
            candidate = (media_root / rel_str).resolve()
            candidate.relative_to(media_root)
        except (OSError, ValueError):
            return _http_error(404, "not found")
        if not candidate.is_file():
            return _http_error(404, "not found")
        try:
            body = candidate.read_bytes()
        except OSError:
            return _http_error(500, "read error")
        mime, _ = mimetypes.guess_type(candidate.name)
        if mime not in _MEDIA_ALLOWED_MIMES:
            mime = "application/octet-stream"
        return _http_response(
            body,
            content_type=mime,
            extra_headers=[
                ("Cache-Control", "private, max-age=31536000, immutable"),
                # Paired with the MIME whitelist above: prevents browsers from
                # MIME-sniffing an octet-stream fallback into executable HTML.
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        # Same boundary as ``_handle_session_messages``: mutations apply only to
        # websocket-channel sessions; deletion unlinks local JSONL — keep scope narrow.
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        deleted = self._session_manager.delete_session(decoded_key)
        delete_webui_thread(decoded_key)
        return _http_json_response({"deleted": bool(deleted)})

    def _handle_session_notes(self, request: WsRequest, key: str) -> Response:
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        notes = self._session_manager.get_session_notes(decoded_key)
        # Return empty if no notes found (session might not exist or have no notes yet)
        return _http_json_response(notes)

    def _handle_global_notes(self, request: WsRequest) -> Response:
        """Get or save global user notes.

        GET /api/notes?date=YYYY-MM-DD - Returns notes for the specified date
        POST /api/notes?date=YYYY-MM-DD&data=<urlencoded json> - Save notes

        Storage structure (under ielts-speaking-bot/user-notes/):
        - notes.json: Raw data (source of truth)
        - by-date/YYYY-MM-DD.md: Notes grouped by date
        - by-session/{session-key}.md: Notes grouped by session
        """
        from urllib.parse import parse_qs, unquote
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        # Get project root directory (ielts-speaking-bot/, not bot/)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        user_notes_dir = project_root / "user-notes"
        by_date_dir = user_notes_dir / "by-date"
        by_session_dir = user_notes_dir / "by-session"

        # Debug logging
        logger.info(f"[GlobalNotes] request.path: {request.path}")

        query_string = request.path[request.path.find('?')+1:] if '?' in request.path else ''
        query_params = parse_qs(query_string)
        date_str = query_params.get("date", [""])[0]
        has_data = "data=" in request.path

        logger.info(f"[GlobalNotes] date_str: {date_str}, has_data: {has_data}")

        if not has_data:
            # GET request - return markdown for the date
            all_dates = query_params.get("all_dates", [""])[0]

            if all_dates.lower() == "true":
                # Return all dates with their content
                dates = []
                if by_date_dir.exists():
                    for f in sorted(by_date_dir.iterdir(), reverse=True):
                        if f.suffix == ".md" and f.stem.startswith("user-note-"):
                            date_key = f.stem.replace("user-note-", "")
                            content = f.read_text(encoding="utf-8")
                            dates.append({"date": date_key, "content": content})
                return _http_json_response({"dates": dates})

            if not date_str:
                date_str = datetime.now().strftime("%Y-%m-%d")

            notes_file = by_date_dir / f"user-note-{date_str}.md"
            if notes_file.exists():
                content = notes_file.read_text(encoding="utf-8")
                return _http_json_response({"date": date_str, "content": content})
            return _http_json_response({"date": date_str, "content": ""})

        # POST request - save notes
        try:
            import json

            logger.info(f"[GlobalNotes] POST section reached, date_str={date_str}")

            if not date_str:
                date_str = datetime.now().strftime("%Y-%m-%d")

            data_param = query_params.get("data", [""])[0]
            if not data_param:
                logger.warning(f"[GlobalNotes] missing data_param")
                return _http_error(400, "missing data parameter")

            # Parse full entries but only store key fields
            full_entries = json.loads(unquote(data_param))
            logger.info(f"[GlobalNotes] parsed {len(full_entries)} entries")

            # Simplify entries - only keep key fields
            entries = []
            for entry in full_entries:
                simplified = {
                    "id": entry.get("id"),
                    "timestamp": entry.get("timestamp"),
                    "sessionTitle": entry.get("sessionTitle") or entry.get("sessionKey"),
                    "content": entry.get("content", ""),
                    "quotedContent": entry.get("quotedContent"),
                }
                entries.append(simplified)

            logger.info(f"[GlobalNotes] simplified to {len(entries)} entries")
            logger.info(f"[GlobalNotes] writing to dirs: user_notes={user_notes_dir}, by_date={by_date_dir}, by_session={by_session_dir}")

            # Create directories
            user_notes_dir.mkdir(parents=True, exist_ok=True)
            by_date_dir.mkdir(parents=True, exist_ok=True)
            by_session_dir.mkdir(parents=True, exist_ok=True)

            # 1. Save raw JSON
            notes_json_file = user_notes_dir / "notes.json"
            notes_json_file.write_text(json.dumps({
                "date": date_str,
                "entries": entries
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[GlobalNotes] wrote notes.json")

            # 2. Generate by-date markdown
            date_md = self._generate_notes_markdown(entries, date_str, "date")
            date_md_file = by_date_dir / f"user-note-{date_str}.md"
            date_md_file.write_text(date_md, encoding="utf-8")

            # 3. Generate by-session markdowns
            session_entries: dict[str, list] = {}
            for entry in entries:
                session_key = entry.get("sessionTitle") or "unknown"
                if session_key not in session_entries:
                    session_entries[session_key] = []
                session_entries[session_key].append(entry)

            for session_key, sess_entries in session_entries.items():
                safe_key = session_key.replace("/", "_").replace(":", "_").replace(" ", "_")
                session_md = self._generate_notes_markdown(sess_entries, date_str, "session", session_key)
                session_md_file = by_session_dir / f"{safe_key}.md"
                session_md_file.write_text(session_md, encoding="utf-8")

            return _http_json_response({"date": date_str, "saved": True})
        except json.JSONDecodeError:
            return _http_error(400, "invalid JSON")
        except Exception as e:
            logger.warning("Failed to save global notes: {}", e)
            return _http_error(500, f"failed to save notes: {e}")

    def _handle_notes_ai_reply_request(self, request: WsRequest) -> Response:
        """Trigger AI reply generation for a note.

        GET /api/notes/ai-reply?note_id=xxx&date=YYYY-MM-DD&reply_type=encouragement&note_content=xxx&quoted_content=xxx
        """
        from datetime import datetime
        import json
        import uuid

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find('?')+1:] if '?' in request.path else ''
        query_params = parse_qs(query_string)

        note_id = query_params.get("note_id", [""])[0]
        date = query_params.get("date", [""])[0]
        reply_type = query_params.get("reply_type", ["encouragement"])[0]
        note_content = query_params.get("note_content", [""])[0]
        quoted_content = query_params.get("quoted_content", [None])[0]

        if not note_id or not date:
            return _http_error(400, "note_id and date are required")

        # Generate a task_id for tracking
        task_id = f"notes-ai-{uuid.uuid4().hex[:8]}"

        # Write task to queue file for AgentLoop to process
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        queue_file = project_root / "user-notes" / ".notes_ai_queue.json"
        queue_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            queue_data = {}
            if queue_file.exists():
                try:
                    queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    queue_data = {}
        except Exception:
            queue_data = {}

        if "tasks" not in queue_data:
            queue_data["tasks"] = []

        queue_data["tasks"].append({
            "task_id": task_id,
            "note_id": note_id,
            "date": date,
            "reply_type": reply_type,
            "note_content": note_content,
            "quoted_content": quoted_content,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        })

        queue_file.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(f"[NotesAI] Reply request queued: note_id={note_id}, date={date}, task_id={task_id}")

        return _http_json_response({
            "task_id": task_id,
            "status": "started",
            "message": "AI reply generation started"
        })

    def _handle_notes_ai_reply_status(self, request: WsRequest) -> Response:
        """Query AI reply generation status.

        GET /api/notes/ai-reply/status?task_id=xxx
        """
        import json

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find('?')+1:] if '?' in request.path else ''
        query_params = parse_qs(query_string)

        task_id = query_params.get("task_id", [""])[0]

        if not task_id:
            return _http_error(400, "task_id is required")

        # Read task status from queue file
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        queue_file = project_root / "user-notes" / ".notes_ai_queue.json"

        task_status = "running"
        task_data = None

        if queue_file.exists():
            try:
                queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
                for task in queue_data.get("tasks", []):
                    if task.get("task_id") == task_id:
                        task_status = task.get("status", "running")
                        if task_status == "done":
                            task_data = task.get("result")
                        break
            except (json.JSONDecodeError, IOError):
                pass

        return _http_json_response({
            "task_id": task_id,
            "status": task_status,
            "reply": task_data,
            "error": None
        })

    def _handle_notes_ai_replies_list(self, request: WsRequest) -> Response:
        """Get all AI replies for a date.

        GET /api/notes/ai-replies?date=YYYY-MM-DD
        """
        from datetime import datetime

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find('?')+1:] if '?' in request.path else ''
        query_params = parse_qs(query_string)

        date = query_params.get("date", [""])[0]

        project_root = Path(__file__).resolve().parent.parent.parent.parent
        index_file = project_root / "user-notes" / "ai-replies" / "index.json"

        logger.info(f"[NotesAI] _handle_notes_ai_replies_list: date={date}, query_params={dict(query_params)}")

        replies = []

        # Read from index file if exists
        logger.info(f"[NotesAI] index_file path: {index_file}")
        logger.info(f"[NotesAI] index_file exists: {index_file.exists()}")
        # Read raw file content for debugging
        if index_file.exists():
            raw_content = index_file.read_text(encoding="utf-8")
            logger.info(f"[NotesAI] index_file raw content length: {len(raw_content)}")
            logger.info(f"[NotesAI] index_file raw content: {raw_content[:500]}")
            import json
            try:
                index_data = json.loads(index_file.read_text(encoding="utf-8"))
                raw_replies = [dict(r) for r in index_data.get("replies", {}).values()]
                logger.info(f"[NotesAI] Raw replies from index: {len(raw_replies)} items")
                # Transform to match frontend's AiReplyEntry interface
                from datetime import datetime
                for r in raw_replies:
                    # Map 'id' (noteId) to 'noteId' for frontend compatibility
                    note_id = r.pop("id", r.get("noteId", ""))
                    r["noteId"] = note_id
                    logger.info(f"[NotesAI] Transformed noteId: {note_id}")
                    # Convert ISO timestamp string to milliseconds
                    ts = r.get("timestamp", "")
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts.replace("+08:00", "").replace("Z", ""))
                            r["timestamp"] = int(dt.timestamp() * 1000)
                        except Exception:
                            r["timestamp"] = 0
                    if not r.get("date") and ts:
                        try:
                            dt = datetime.fromisoformat(ts.replace("+08:00", "").replace("Z", ""))
                            r["date"] = dt.strftime("%Y-%m-%d")
                        except Exception:
                            r["date"] = ""

                replies = raw_replies
                logger.info(f"[NotesAI] Transformed replies: {len(replies)} items, first noteId={replies[0].get('noteId') if replies else 'none'}")
            except json.JSONDecodeError:
                pass

        # Filter by date if requested
        if date:
            replies = [r for r in replies if r.get("date") == date]
            logger.info(f"[NotesAI] After date filter ({date}): {len(replies)} items")

        logger.info(f"[NotesAI] Final response: {len(replies)} replies")
        return _http_json_response({"date": date, "replies": replies})

    def _generate_notes_markdown(self, entries: list, date_str: str, mode: str = "date", session_key: str | None = None) -> str:
        """Generate markdown content from entries.

        Only includes key fields: sessionTitle, content, quotedContent
        """
        from datetime import datetime

        lines = []

        if mode == "date":
            lines.append(f"# Notes - {date_str}")
            lines.append("")
        else:
            lines.append(f"# Notes - {session_key}")
            lines.append(f"*Date: {date_str}*")
            lines.append("")

        for entry in entries:
            entry_id = entry.get("id", "unknown")
            timestamp = entry.get("timestamp")
            if timestamp:
                if isinstance(timestamp, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            session_title = entry.get("sessionTitle") or session_key or "Unknown"
            content = entry.get("content", "")
            quoted = entry.get("quotedContent")

            lines.append("---")
            lines.append(f"**[{timestamp}]** | {session_title} **[id:{entry_id}]**")

            if quoted:
                lines.append("")
                for ql in str(quoted).split('\n'):
                    lines.append(f"> {ql}")

            if content:
                lines.append("")
                lines.append(content)

            lines.append("")

        return "\n".join(lines)

    def _handle_benative_articles(self, request: WsRequest) -> Response:
        """List available benative articles."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        articles_dir = self._session_manager.sessions_dir.parent / "benative" / "articles"
        article_list = []

        if articles_dir.exists():
            for article_file in articles_dir.glob("*.json"):
                try:
                    import json
                    article_data = json.loads(article_file.read_text(encoding="utf-8"))
                    pairs_file = articles_dir.parent / "pairs" / f"{article_file.stem}.jsonl"
                    sentence_count = 0
                    if pairs_file.exists():
                        sentence_count = sum(1 for _ in pairs_file.read_text(encoding="utf-8").strip().split("\n") if _.strip())
                    article_list.append({
                        "id": article_data.get("id", article_file.stem),
                        "title": article_data.get("title", "Untitled"),
                        "source": article_data.get("source", "Unknown"),
                        "topic": article_data.get("topic", "general"),
                        "sentence_count": sentence_count,
                    })
                except Exception:
                    continue

        return _http_json_response({"articles": article_list})

    def _handle_ielts_exam_start(self, request: WsRequest) -> Response:
        """Start a new IELTS exam."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        import json
        from nanobot.ielts_exam import IeltsExamManager

        # Get query parameters
        _, query = _parse_request_path(request.path)
        topic_param = _query_first(query, "topic")
        random_param = _query_first(query, "random")

        workspace = self._session_manager.workspace
        topic_bank = workspace / "topic-bank"
        topics = sorted(topic_bank.glob("*.md"))

        if not topics:
            return _http_json_response({"error": "No topics found"}, status=404)

        # Select topic
        if random_param == "true" or not topic_param:
            import random
            selected = random.choice(topics)
        else:
            # Find topic by number
            selected = None
            for t in topics:
                if t.stem.startswith(topic_param) or t.stem == topic_param:
                    selected = t
                    break
            if not selected:
                return _http_json_response({"error": f"Topic {topic_param} not found"}, status=404)

        # Initialize exam manager and load topic
        exam_manager = IeltsExamManager(workspace)
        exam = exam_manager.load_topic(selected)

        # Get current question
        current_q = exam_manager.get_current_question()

        return _http_json_response({
            "exam": {
                "examId": exam.exam_id,
                "topic": selected.stem,
                "topicTitle": selected.read_text(encoding="utf-8").split("\n")[0].replace("# ", "").strip(),
                "state": exam.state.value,
                "currentPart": exam.current_part.value,
                "currentQuestionIndex": exam.current_question_index,
                "parts": {
                    "part1": {
                        "questions": [
                            {
                                "number": q.number,
                                "question": q.question,
                                "depth": q.depth,
                                "asked": q.asked,
                            }
                            for q in exam.parts.get("part1", {}).questions or []
                        ]
                    },
                    "part2": {
                        "cueCard": {
                            "topic": exam.parts.get("part2", {}).cue_card.topic if exam.parts.get("part2", {}).cue_card else "",
                            "bulletPoints": exam.parts.get("part2", {}).cue_card.bullet_points if exam.parts.get("part2", {}).cue_card else [],
                            "asked": exam.parts.get("part2", {}).cue_card.asked if exam.parts.get("part2", {}).cue_card else False,
                        }
                    },
                    "part3": {
                        "questions": [
                            {
                                "number": q.number,
                                "question": q.question,
                                "depth": q.depth,
                                "asked": q.asked,
                            }
                            for q in exam.parts.get("part3", {}).questions or []
                        ]
                    },
                },
            },
            "currentQuestion": {
                "number": current_q.number if current_q else None,
                "question": current_q.question if current_q and hasattr(current_q, 'question') else None,
            } if current_q else None,
        })

    def _handle_ielts_exam_answer(self, request: WsRequest) -> Response:
        """Record an answer to the current exam question."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        import json
        from nanobot.ielts_exam import IeltsExamManager

        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _http_json_response({"error": "Invalid JSON"}, status=400)

        exam_id = body.get("examId")
        answer = body.get("answer", "")
        time_spent = body.get("timeSpent", 0)

        if not exam_id:
            return _http_json_response({"error": "examId required"}, status=400)

        workspace = self._session_manager.workspace
        exam_manager = IeltsExamManager(workspace)

        # Load exam from disk
        exam = exam_manager.get_exam_by_id(exam_id)
        if not exam:
            return _http_json_response({"error": "Exam not found"}, status=404)

        exam_manager.set_active_exam(exam)

        # Record answer
        exam_manager.record_answer(answer, time_spent)

        return _http_json_response({"success": True})

    def _handle_ielts_exam_next(self, request: WsRequest) -> Response:
        """Advance to the next step in the exam."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        import json
        from nanobot.ielts_exam import IeltsExamManager

        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _http_json_response({"error": "Invalid JSON"}, status=400)

        exam_id = body.get("examId")

        if not exam_id:
            return _http_json_response({"error": "examId required"}, status=400)

        workspace = self._session_manager.workspace
        exam_manager = IeltsExamManager(workspace)

        # Load exam from disk
        exam = exam_manager.get_exam_by_id(exam_id)
        if not exam:
            return _http_json_response({"error": "Exam not found"}, status=404)

        exam_manager.set_active_exam(exam)

        # Advance to next step
        new_state = exam_manager.next_step()

        if new_state.value == "completed":
            return _http_json_response({"completed": True})

        # Get current question for new state
        current_q = exam_manager.get_current_question()

        return _http_json_response({
            "exam": {
                "examId": exam.exam_id,
                "state": exam.state.value,
                "currentPart": exam.current_part.value,
                "currentQuestionIndex": exam.current_question_index,
            },
            "currentQuestion": {
                "number": current_q.number if current_q else None,
                "question": current_q.question if current_q and hasattr(current_q, 'question') else None,
            } if current_q and hasattr(current_q, 'question') else None,
            "cueCard": {
                "topic": current_q.topic if current_q and hasattr(current_q, 'topic') else None,
                "bulletPoints": current_q.bullet_points if current_q and hasattr(current_q, 'bullet_points') else None,
            } if current_q and hasattr(current_q, 'topic') else None,
        })

    def _handle_ielts_exam_end(self, request: WsRequest) -> Response:
        """End the current exam early."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        import json
        from nanobot.ielts_exam import IeltsExamManager

        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _http_json_response({"error": "Invalid JSON"}, status=400)

        workspace = self._session_manager.workspace
        exam_manager = IeltsExamManager(workspace)

        exam_manager.end_exam()

        return _http_json_response({"success": True})

    def _handle_ielts_exam_list(self, request: WsRequest) -> Response:
        """List all saved exam records."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")

        from nanobot.ielts_exam import IeltsExamManager

        workspace = self._session_manager.workspace
        exam_manager = IeltsExamManager(workspace)
        exams = exam_manager.list_exams()

        return _http_json_response({
            "exams": [
                {
                    "examId": e.exam_id,
                    "topic": e.topic,
                    "startedAt": e.started_at,
                    "endedAt": e.ended_at,
                    "finalScore": e.final_score,
                }
                for e in exams
            ]
        })

    def _handle_session_benative(self, request: WsRequest, key: str) -> Response:
        """Get benative progress for a session."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        session = self._session_manager._cache.get(decoded_key)
        if not session:
            return _http_json_response({})

        session_dir = self._session_manager._get_session_dir(decoded_key)
        progress_file = session_dir / "notes" / "benative_progress.json"

        progress = {}
        if progress_file.exists():
            import json
            progress = json.loads(progress_file.read_text(encoding="utf-8"))

        return _http_json_response(progress)

    def _handle_session_benative_article(self, request: WsRequest, key: str) -> Response:
        """Get current benative article content for a session."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        session_dir = self._session_manager._get_session_dir(decoded_key)
        progress_file = session_dir / "notes" / "benative_progress.json"

        if not progress_file.exists():
            return _http_json_response({"error": "No article selected"})

        import json
        progress = json.loads(progress_file.read_text(encoding="utf-8"))
        article_id = progress.get("article_id")

        if not article_id:
            return _http_json_response({"error": "No article selected"})

        articles_dir = self._session_manager.sessions_dir.parent / "benative" / "articles"
        article_file = articles_dir / f"{article_id}.json"
        pairs_file = self._session_manager.sessions_dir.parent / "benative" / "pairs" / f"{article_id}.jsonl"

        if not article_file.exists():
            return _http_json_response({"error": "Article not found"})

        article_data = json.loads(article_file.read_text(encoding="utf-8"))

        pairs = []
        if pairs_file.exists():
            for line in pairs_file.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    pairs.append(json.loads(line))

        return _http_json_response({
            "article": article_data,
            "pairs": pairs,
            "current_sentence": progress.get("current_sentence", 0),
            "total_sentences": len(pairs),
        })

    def _handle_session_benative_responses(self, request: WsRequest, key: str) -> Response:
        """Get benative user responses for a session."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self._session_manager is None:
            return _http_error(503, "session manager unavailable")
        decoded_key = _decode_api_key(key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not self._is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")

        session = self._session_manager._cache.get(decoded_key)
        if not session:
            return _http_json_response({"responses": []})

        session_uuid = session.session_uuid
        responses_file = self._session_manager.sessions_dir.parent / "benative" / "sessions" / session_uuid / "responses.jsonl"

        responses = []
        if responses_file.exists():
            import json
            for line in responses_file.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    responses.append(json.loads(line))

        return _http_json_response({"responses": responses})

    # -- Wiki API handlers ----------------------------------------------------

    def _wiki_root(self) -> Path:
        """Get the wiki root path (project_root/persona/wiki)."""
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        return project_root / "persona" / "wiki"

    def _ensure_subagent_importable(self) -> None:
        """Ensure the repo-root subagent package is on sys.path for wiki handlers."""
        repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

    def _handle_wiki_search(self, request: WsRequest) -> Response:
        """GET /api/wiki/search?q=...&mode=...&topic=...&type=...&tags=...&limit=..."""
        from urllib.parse import parse_qs

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find("?") + 1 :] if "?" in request.path else ""
        params = parse_qs(query_string)

        try:
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.wiki_query import WikiQueryEngine

            searcher = WikiQueryEngine(wiki_root=self._wiki_root())
            tags_str = params.get("tags", [None])[0]
            tags = tags_str.split(",") if tags_str else None
            results = searcher.query(
                query=params.get("q", [""])[0],
                mode=params.get("mode", [None])[0] or None,
                topic=params.get("topic", [None])[0] or None,
                page_type=params.get("type", [None])[0] or None,
                tags=tags,
                limit=int(params.get("limit", [10])[0]),
            )
            return _http_json_response({"results": [r.model_dump() for r in results]})
        except Exception as e:
            logger.exception("[Wiki] search error: %s", e)
            return _http_json_response({"results": [], "error": str(e)})

    def _handle_wiki_page(self, request: WsRequest) -> Response:
        """GET /api/wiki/page?slug=..."""
        from urllib.parse import parse_qs

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find("?") + 1 :] if "?" in request.path else ""
        params = parse_qs(query_string)
        slug = params.get("slug", [None])[0]

        if not slug:
            return _http_error(400, "missing slug parameter")

        try:
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.wiki_store import WikiStore

            store = WikiStore(workspace=self._wiki_root().parent, wiki_root=self._wiki_root())
            page = store.read_page(slug)
            if page is None:
                return _http_error(404, "page not found")
            meta, body = page
            return _http_json_response({"meta": meta.model_dump(), "content": body})
        except Exception as e:
            logger.exception("[Wiki] page error: %s", e)
            return _http_error(500, str(e))

    def _handle_wiki_graph(self, request: WsRequest) -> Response:
        """GET /api/wiki/graph?mode=...&topic=...&type=...&tags=..."""
        from urllib.parse import parse_qs

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find("?") + 1 :] if "?" in request.path else ""
        params = parse_qs(query_string)

        try:
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.wiki_graph import build_wiki_graph

            tags_str = params.get("tags", [None])[0]
            tags = tags_str.split(",") if tags_str else None

            graph = build_wiki_graph(
                wiki_root=self._wiki_root(),
                mode=params.get("mode", [None])[0] or None,
                topic=params.get("topic", [None])[0] or None,
                page_type=params.get("type", [None])[0] or None,
                tags=tags,
            )
            return _http_json_response(graph)
        except Exception as e:
            logger.exception("[Wiki] graph error: %s", e)
            return _http_json_response({"nodes": [], "edges": [], "error": str(e)})

    def _handle_wiki_patch(self, request: WsRequest) -> Response:
        """GET /api/wiki/patch?data=<urlencoded JSON>"""
        from urllib.parse import parse_qs, unquote

        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query_string = request.path[request.path.find("?") + 1 :] if "?" in request.path else ""
        params = parse_qs(query_string)
        data_param = params.get("data", [""])[0]

        if not data_param:
            return _http_error(400, "missing data parameter")

        try:
            import json

            patch_data = json.loads(unquote(data_param))
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.schema import WikiPatch
            from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
            from subagent.cross_session.wiki.processor.wiki_store import WikiStore

            patch = WikiPatch(**patch_data)
            store = WikiStore(workspace=self._wiki_root().parent, wiki_root=self._wiki_root())
            ok = store.apply_patch(patch)
            if ok:
                index = WikiIndex(wiki_root=self._wiki_root())
                index.index_page(patch.slug)
                return _http_json_response({"ok": True, "slug": patch.slug})
            else:
                return _http_json_response({"ok": False, "slug": patch.slug}, status=422)
        except Exception as e:
            logger.exception("[Wiki] patch error: %s", e)
            return _http_error(400, str(e))

    def _handle_wiki_rebuild_index(self, request: WsRequest) -> Response:
        """GET /api/wiki/rebuild-index"""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        try:
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.wiki_index import WikiIndex

            index = WikiIndex(wiki_root=self._wiki_root())
            count = index.rebuild()
            return _http_json_response({"ok": True, "chunks_indexed": count})
        except Exception as e:
            logger.exception("[Wiki] rebuild error: %s", e)
            return _http_error(500, str(e))

    def _handle_wiki_lint(self, request: WsRequest) -> Response:
        """GET /api/wiki/lint"""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        try:
            self._ensure_subagent_importable()
            from subagent.cross_session.wiki.processor.wiki_lint import WikiLinter

            findings = WikiLinter(wiki_root=self._wiki_root()).lint()
            return _http_json_response({
                "findings": [finding.__dict__ for finding in findings],
                "count": len(findings),
                "errors": len([f for f in findings if f.severity == "error"]),
                "warnings": len([f for f in findings if f.severity == "warning"]),
            })
        except Exception as e:
            logger.exception("[Wiki] lint error: %s", e)
            return _http_error(500, str(e))

    def _handle_wiki_sync_log(self, request: WsRequest) -> Response:
        """GET /api/wiki/sync-log?limit=..."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")

        query = _parse_query(request.path)
        try:
            limit = int(_query_first(query, "limit") or 100)
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 500))
        try:
            records = self._wiki_sync_runs(self._project_root(), limit=limit)
            return _http_json_response({"runs": records})
        except Exception as e:
            logger.exception("[Wiki] sync log error: %s", e)
            return _http_error(500, str(e))

    # -- Admin / monitor API ----------------------------------------------------

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent.parent

    def _safe_read_text(self, path: Path, *, max_chars: int = 20_000) -> tuple[str, bool]:
        text = path.read_text(encoding="utf-8")
        truncated = len(text) > max_chars
        return text[:max_chars], truncated

    def _read_config_file(self, path: Path) -> Any:
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {}

    def _monitor_trigger_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for mode_dir in sorted((root / "mode").glob("*")):
            trigger_dir = mode_dir / "trigger"
            if not trigger_dir.exists():
                continue
            for rel in ("triggers.json", "cron/cron.yaml"):
                candidate = trigger_dir / rel
                if candidate.exists():
                    files.append(candidate)
        return files

    def _monitor_context_prompt_files(self, root: Path) -> list[Path]:
        files = sorted(root.glob("subagent/*/*/context/*.md"))
        files.extend(sorted(root.glob("mode/*/context/*.md")))
        return files

    def _normalize_prompt_path(self, root: Path, raw: str | None) -> Path | None:
        if not raw:
            return None
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate if candidate.is_relative_to(root) else None
        direct = root / candidate
        if direct.exists():
            return direct
        # Some older YAML configs use "subagents/session/..." while the repo now
        # stores canonical prompts under subagent/{scope}/{name}/context.
        name = candidate.name
        matches = sorted(root.glob(f"subagent/**/context/{name}"))
        return matches[0] if matches else direct

    def _monitor_triggers(self, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        triggers: list[dict[str, Any]] = []
        prompt_refs: dict[str, dict[str, Any]] = {}
        for path in self._monitor_trigger_files(root):
            try:
                config = self._read_config_file(path)
            except Exception as e:
                triggers.append({
                    "id": path.stem,
                    "mode": path.parts[-4] if len(path.parts) >= 4 else "",
                    "source": str(path.relative_to(root)),
                    "enabled": False,
                    "error": str(e),
                })
                continue

            mode = path.relative_to(root).parts[1] if len(path.relative_to(root).parts) > 1 else ""
            raw_items = config.get("triggers") or config.get("cron_jobs") or []
            if not isinstance(raw_items, list):
                raw_items = []
            for idx, item in enumerate(raw_items):
                if not isinstance(item, dict):
                    continue
                target = item.get("target") if isinstance(item.get("target"), dict) else {}
                condition = item.get("condition") if isinstance(item.get("condition"), dict) else {}
                prompt_file = target.get("prompt_file") if isinstance(target, dict) else None
                prompt_path = self._normalize_prompt_path(root, prompt_file)
                prompt_id = str(prompt_path.relative_to(root)) if prompt_path and prompt_path.exists() else (prompt_file or "")
                if prompt_path and prompt_path.exists() and prompt_id not in prompt_refs:
                    try:
                        content, truncated = self._safe_read_text(prompt_path)
                        prompt_refs[prompt_id] = {
                            "id": prompt_id,
                            "path": prompt_id,
                            "title": prompt_path.stem,
                            "content": content,
                            "truncated": truncated,
                        }
                    except OSError as e:
                        prompt_refs[prompt_id] = {
                            "id": prompt_id,
                            "path": prompt_id,
                            "title": prompt_path.stem,
                            "content": "",
                            "truncated": False,
                            "error": str(e),
                        }
                triggers.append({
                    "id": str(item.get("id") or f"{path.stem}-{idx + 1}"),
                    "name": item.get("name") or item.get("id") or f"Trigger {idx + 1}",
                    "mode": mode,
                    "source": str(path.relative_to(root)),
                    "enabled": item.get("enabled", True),
                    "condition": condition,
                    "subagent": target.get("subagent") if isinstance(target, dict) else None,
                    "model": target.get("model") if isinstance(target, dict) else None,
                    "prompt_file": prompt_file,
                    "prompt_id": prompt_id,
                    "task_template": target.get("task_template") if isinstance(target, dict) else None,
                    "cursor": item.get("cursor") if isinstance(item.get("cursor"), dict) else None,
                    "error": None,
                })
        return triggers, list(prompt_refs.values())

    def _monitor_recent_activity(self, root: Path, *, limit: int = 80) -> list[dict[str, Any]]:
        activity: list[dict[str, Any]] = []
        sessions_root = root / "persona" / "sessions"
        if not sessions_root.exists():
            return activity
        thread_files = sorted(
            sessions_root.glob("*/thread.jsonl"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )[:25]
        for thread_path in thread_files:
            session_id = thread_path.parent.name
            try:
                lines = thread_path.read_text(encoding="utf-8").splitlines()[-120:]
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                metadata = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
                timestamp = msg.get("timestamp") or metadata.get("timestamp")
                if metadata.get("injected_event") == "subagent_result":
                    activity.append({
                        "kind": "subagent_result",
                        "session_id": session_id,
                        "timestamp": timestamp,
                        "label": "subagent result",
                        "detail": (msg.get("content") or "")[:600],
                        "status": "ok",
                    })
                for event in metadata.get("_tool_events") or []:
                    if not isinstance(event, dict):
                        continue
                    activity.append({
                        "kind": "tool",
                        "session_id": session_id,
                        "timestamp": timestamp,
                        "label": event.get("name") or "tool",
                        "detail": str(event.get("detail") or event.get("status") or "")[:600],
                        "status": event.get("status") or "",
                    })
        return sorted(activity, key=lambda x: x.get("timestamp") or "", reverse=True)[:limit]

    def _monitor_subagent_runs(self, root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        paths = [
            root / "persona" / "monitor" / "subagent_runs.jsonl",
            root / "monitor" / "subagent_runs.jsonl",
        ]
        for path in paths:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    runs.append(item)
        runs.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return runs[:limit]

    def _monitor_trigger_decisions(self, root: Path, *, limit: int = 200) -> list[dict[str, Any]]:
        path = root / "monitor" / "trigger_decisions.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit * 2:]
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        records.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return records[:limit]

    def _estimate_llm_cost_usd(self, *, model: str | None, usage: dict[str, Any] | None) -> dict[str, Any]:
        """Estimate DeepSeek API cost from normalized usage fields.

        Prices are per 1M tokens from DeepSeek's public pricing page. This is
        intentionally an estimate because provider invoices may apply discounts,
        balance rules, and model aliases outside this local process.
        """
        if not usage:
            return {
                "model": model or "",
                "estimated_usd": 0.0,
                "known_price": False,
            }

        normalized_model = self._normalize_cost_model(model)
        rates = {
            "deepseek-v4-flash": {
                "input_cache_hit": 0.0028,
                "input_cache_miss": 0.14,
                "output": 0.28,
            },
            "deepseek-v4-pro": {
                "input_cache_hit": 0.003625,
                "input_cache_miss": 0.435,
                "output": 0.87,
            },
        }.get(normalized_model)

        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int(usage.get("cached_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        uncached = max(prompt - cached, 0)

        if rates is None:
            return {
                "model": model or "",
                "normalized_model": normalized_model,
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "completion_tokens": completion,
                "estimated_usd": 0.0,
                "known_price": False,
            }

        estimated = (
            (cached / 1_000_000) * rates["input_cache_hit"]
            + (uncached / 1_000_000) * rates["input_cache_miss"]
            + (completion / 1_000_000) * rates["output"]
        )
        return {
            "model": model or "",
            "normalized_model": normalized_model,
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "uncached_prompt_tokens": uncached,
            "completion_tokens": completion,
            "estimated_usd": round(estimated, 8),
            "known_price": True,
        }

    def _normalize_cost_model(self, model: str | None) -> str:
        value = (model or "").strip().lower()
        if value in {"deepseek-chat", "deepseek/deepseek-chat"}:
            return "deepseek-v4-flash"
        if value in {"deepseek-reasoner", "deepseek/deepseek-reasoner"}:
            return "deepseek-v4-flash"
        if value.endswith("deepseek-v4-flash"):
            return "deepseek-v4-flash"
        if value.endswith("deepseek-v4-pro"):
            return "deepseek-v4-pro"
        return value

    def _monitor_cost_summary(self, runs: list[dict[str, Any]]) -> dict[str, Any]:
        by_model: dict[str, dict[str, Any]] = {}
        total = 0.0
        prompt = 0
        cached = 0
        completion = 0

        for run in runs:
            usage = run.get("usage") if isinstance(run.get("usage"), dict) else {}
            estimate = self._estimate_llm_cost_usd(
                model=str(run.get("model") or ""),
                usage=usage,
            )
            run["cost_estimate"] = estimate
            normalized = estimate.get("normalized_model") or estimate.get("model") or "unknown"
            row = by_model.setdefault(
                str(normalized),
                {
                    "model": normalized,
                    "prompt_tokens": 0,
                    "cached_tokens": 0,
                    "completion_tokens": 0,
                    "estimated_usd": 0.0,
                    "runs": 0,
                    "known_price": bool(estimate.get("known_price")),
                },
            )
            row["runs"] += 1
            row["prompt_tokens"] += int(estimate.get("prompt_tokens") or 0)
            row["cached_tokens"] += int(estimate.get("cached_tokens") or 0)
            row["completion_tokens"] += int(estimate.get("completion_tokens") or 0)
            row["estimated_usd"] += float(estimate.get("estimated_usd") or 0.0)
            row["known_price"] = row["known_price"] or bool(estimate.get("known_price"))
            total += float(estimate.get("estimated_usd") or 0.0)
            prompt += int(estimate.get("prompt_tokens") or 0)
            cached += int(estimate.get("cached_tokens") or 0)
            completion += int(estimate.get("completion_tokens") or 0)

        models = []
        for row in by_model.values():
            row["estimated_usd"] = round(float(row["estimated_usd"]), 8)
            models.append(row)
        models.sort(key=lambda row: float(row.get("estimated_usd") or 0), reverse=True)
        last_turn = self._estimate_llm_cost_usd(
            model=getattr(self, "model", ""),
            usage=getattr(self, "_last_usage", None),
        )
        return {
            "currency": "USD",
            "estimated_usd": round(total, 8),
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "completion_tokens": completion,
            "models": models,
            "last_turn": last_turn,
            "price_source": "https://api-docs.deepseek.com/quick_start/pricing",
            "note": "Local estimate from logged usage; official invoice is authoritative.",
        }

    def _wiki_sync_runs(self, root: Path, *, limit: int = 100) -> list[dict[str, Any]]:
        path = root / "persona" / "wiki" / "state" / "sync_log.jsonl"
        if not path.exists():
            return []
        runs: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                runs.append(item)
        runs.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return runs[:limit]

    def _handle_admin_monitor(self, request: WsRequest) -> Response:
        """GET /api/admin/monitor - trigger, prompt, and recent execution overview."""
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        try:
            root = self._project_root()
            triggers, trigger_prompts = self._monitor_triggers(root)
            subagent_runs = self._monitor_subagent_runs(root)
            trigger_decisions = self._monitor_trigger_decisions(root)
            known_prompt_ids = {p["id"] for p in trigger_prompts}
            extra_prompts: list[dict[str, Any]] = []
            for path in self._monitor_context_prompt_files(root):
                prompt_id = str(path.relative_to(root))
                if prompt_id in known_prompt_ids:
                    continue
                try:
                    content, truncated = self._safe_read_text(path)
                    extra_prompts.append({
                        "id": prompt_id,
                        "path": prompt_id,
                        "title": path.stem,
                        "content": content,
                        "truncated": truncated,
                    })
                except OSError as e:
                    extra_prompts.append({
                        "id": prompt_id,
                        "path": prompt_id,
                        "title": path.stem,
                        "content": "",
                        "truncated": False,
                        "error": str(e),
                    })

            return _http_json_response({
                "generated_at": datetime.now().isoformat(),
                "workspace": str(root),
                "triggers": triggers,
                "prompts": trigger_prompts + extra_prompts,
                "subagent_statuses": list(reversed(self._subagent_status_history[-100:])),
                "subagent_runs": subagent_runs,
                "trigger_decisions": trigger_decisions,
                "cost_summary": self._monitor_cost_summary(subagent_runs),
                "wiki_sync_runs": self._wiki_sync_runs(root),
                "recent_activity": self._monitor_recent_activity(root),
            })
        except Exception as e:
            logger.exception("[Admin] monitor error: %s", e)
            return _http_error(500, str(e))

    def _handle_admin_trigger_update(self, request: WsRequest) -> Response:
        """GET /api/admin/triggers - update trigger enabled/count fields.

        This gateway is served by websockets' lightweight HTTP parser, which is
        GET-oriented. Keep mutations query-string based like the settings routes.
        """
        if not self._check_api_token(request):
            return _http_error(401, "Unauthorized")
        query = _parse_query(request.path)

        source = str(_query_first(query, "source") or "").strip()
        trigger_id = str(_query_first(query, "id") or "").strip()
        if not source or not trigger_id:
            return _http_json_response({"error": "source and id are required"}, status=400)

        root = self._project_root()
        path = (root / source).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not path.exists() or path not in self._monitor_trigger_files(root):
            return _http_json_response({"error": "unknown trigger source"}, status=404)

        try:
            config = self._read_config_file(path)
        except Exception as e:
            return _http_json_response({"error": f"failed to read config: {e}"}, status=400)
        items = config.get("triggers") or config.get("cron_jobs") or []
        if not isinstance(items, list):
            return _http_json_response({"error": "config does not contain trigger list"}, status=400)

        target_item: dict[str, Any] | None = None
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "") == trigger_id:
                target_item = item
                break
        if target_item is None:
            return _http_json_response({"error": "trigger not found"}, status=404)

        if "enabled" in query:
            target_item["enabled"] = (_query_first(query, "enabled") or "").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }

        if "count" in query:
            try:
                count = int(_query_first(query, "count") or "")
            except (TypeError, ValueError):
                return _http_json_response({"error": "count must be an integer"}, status=400)
            if count < 1:
                return _http_json_response({"error": "count must be >= 1"}, status=400)
            condition = target_item.setdefault("condition", {})
            if not isinstance(condition, dict):
                condition = {}
                target_item["condition"] = condition
            condition["count"] = count
            condition.pop("every", None)
            condition.pop("threshold", None)

        try:
            if path.suffix.lower() == ".json":
                path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            elif path.suffix.lower() in {".yaml", ".yml"}:
                path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
            else:
                return _http_json_response({"error": "unsupported trigger file type"}, status=400)
        except OSError as e:
            return _http_json_response({"error": f"failed to write config: {e}"}, status=500)

        return _http_json_response({"ok": True, "trigger": target_item})

    def _serve_static(self, request_path: str) -> Response | None:
        """Resolve *request_path* against the built SPA directory; SPA fallback to index.html."""
        assert self._static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        # Reject path-traversal attempts and absolute targets.
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self._static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self._static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            # SPA history-mode fallback: unknown routes serve index.html so the
            # client-side router can render them.
            index = self._static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            self.logger.warning("static: failed to read {}: {}", candidate, e)
            return _http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        # Hash-named build assets are cache-friendly; index.html must stay fresh.
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )

    def _authorize_websocket_handshake(self, connection: Any, query: dict[str, list[str]]) -> Any:
        supplied = _query_first(query, "token")
        static_token = self.config.token.strip()

        if static_token:
            if supplied and hmac.compare_digest(supplied, static_token):
                return None
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if self.config.websocket_requires_token:
            if supplied and self._take_issued_token_if_valid(supplied):
                return None
            return connection.respond(401, "Unauthorized")

        if supplied:
            self._take_issued_token_if_valid(supplied)
        return None

    async def start(self) -> None:
        from nanobot.utils.logging_bridge import redirect_lib_logging

        redirect_lib_logging("websockets", level="WARNING")

        self._running = True
        self._stop_event = asyncio.Event()

        ssl_context = self._build_ssl_context()
        scheme = "wss" if ssl_context else "ws"

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            return await self._dispatch_http(connection, request)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        self.logger.info(
            "WebSocket server listening on {}://{}:{}{}",
            scheme,
            self.config.host,
            self.config.port,
            self.config.path,
        )
        if self.config.token_issue_path:
            self.logger.info(
                "WebSocket token issue route: {}://{}:{}{}",
                scheme,
                self.config.host,
                self.config.port,
                _normalize_config_path(self.config.token_issue_path),
            )

        async def runner() -> None:
            async with serve(
                handler,
                self.config.host,
                self.config.port,
                process_request=process_request,
                max_size=self.config.max_message_bytes,
                ping_interval=self.config.ping_interval_s,
                ping_timeout=self.config.ping_timeout_s,
                ssl=ssl_context,
            ):
                assert self._stop_event is not None
                await self._stop_event.wait()

        self._server_task = asyncio.create_task(runner())
        await self._server_task

    async def _connection_loop(self, connection: Any) -> None:
        request = connection.request
        path_part = request.path if request else "/"
        _, query = _parse_request_path(path_part)
        client_id_raw = _query_first(query, "client_id")
        client_id = client_id_raw.strip() if client_id_raw else ""
        if not client_id:
            client_id = f"anon-{uuid.uuid4().hex[:12]}"
        elif len(client_id) > 128:
            self.logger.warning("client_id too long ({} chars), truncating", len(client_id))
            client_id = client_id[:128]

        default_chat_id = str(uuid.uuid4())

        try:
            await connection.send(
                json.dumps(
                    {
                        "event": "ready",
                        "chat_id": default_chat_id,
                        "client_id": client_id,
                    },
                    ensure_ascii=False,
                )
            )
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._conn_default[connection] = default_chat_id
            self._attach(connection, default_chat_id)
            await self._hydrate_after_subscribe(default_chat_id)

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        self.logger.warning("ignoring non-utf8 binary frame")
                        continue

                envelope = _parse_envelope(raw)
                if envelope is not None:
                    await self._dispatch_envelope(connection, client_id, envelope)
                    continue

                content = _parse_inbound_payload(raw)
                if content is None:
                    continue
                # WebSocket already authenticates at handshake time (token),
                # so pairing is not applicable. Treat as non-DM to avoid
                # sending pairing codes to an already-authenticated client.
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=default_chat_id,
                    content=content,
                    metadata={"remote": getattr(connection, "remote_address", None)},
                    is_dm=False,
                )
        except Exception as e:
            self.logger.debug("connection ended: {}", e)
        finally:
            self._cleanup_connection(connection)

    def _save_envelope_media(
        self,
        media: list[Any],
    ) -> tuple[list[str], str | None]:
        """Decode and persist ``media`` items from a ``message`` envelope.

        Returns ``(paths, None)`` on success or ``([], reason)`` on the first
        failure — the caller is expected to surface ``reason`` to the client
        and skip publishing so no half-formed message ever reaches the agent.
        On failure, any files already written to disk earlier in the same
        call are unlinked so partial ingress doesn't leak orphan files.
        ``reason`` is a short, stable token suitable for UI localization.

        Shape: ``list[{"data_url": str, "name"?: str | None}]``.
        """
        image_count = 0
        video_count = 0
        for item in media:
            mime = _extract_data_url_mime(item.get("data_url", "")) if isinstance(item, dict) else None
            if mime in _VIDEO_MIME_ALLOWED:
                video_count += 1
            elif mime in _IMAGE_MIME_ALLOWED:
                image_count += 1
        if image_count > _MAX_IMAGES_PER_MESSAGE:
            return [], "too_many_images"
        if video_count > _MAX_VIDEOS_PER_MESSAGE:
            return [], "too_many_videos"

        media_dir = get_media_dir("websocket")
        paths: list[str] = []

        def _abort(reason: str) -> tuple[list[str], str]:
            for p in paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError as exc:
                    self.logger.warning(
                        "failed to unlink partial media {}: {}", p, exc
                    )
            return [], reason

        for item in media:
            if not isinstance(item, dict):
                return _abort("malformed")
            data_url = item.get("data_url")
            if not isinstance(data_url, str) or not data_url:
                return _abort("malformed")
            mime = _extract_data_url_mime(data_url)
            if mime is None:
                return _abort("decode")
            if mime not in _UPLOAD_MIME_ALLOWED:
                return _abort("mime")
            is_video = mime in _VIDEO_MIME_ALLOWED
            max_bytes = _MAX_VIDEO_BYTES if is_video else _MAX_IMAGE_BYTES
            try:
                saved = save_base64_data_url(
                    data_url, media_dir, max_bytes=max_bytes,
                )
            except FileSizeExceeded:
                return _abort("size")
            except Exception as exc:
                self.logger.warning("media decode failed: {}", exc)
                return _abort("decode")
            if saved is None:
                return _abort("decode")
            paths.append(saved)
        return paths, None

    async def _dispatch_envelope(
        self,
        connection: Any,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        """Route one typed inbound envelope (``new_chat`` / ``attach`` / ``message``)."""
        t = envelope.get("type")
        if t == "new_chat":
            new_id = str(uuid.uuid4())
            self._attach(connection, new_id)
            await self._send_event(connection, "attached", chat_id=new_id)
            await self._hydrate_after_subscribe(new_id)
            return
        if t == "attach":
            cid = envelope.get("chat_id")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            self._attach(connection, cid)
            await self._send_event(connection, "attached", chat_id=cid)
            await self._hydrate_after_subscribe(cid)
            return
        if t == "message":
            cid = envelope.get("chat_id")
            content = envelope.get("content")
            if not _is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            if not isinstance(content, str):
                await self._send_event(connection, "error", detail="missing content")
                return

            raw_media = envelope.get("media")
            media_paths: list[str] = []
            if raw_media is not None:
                if not isinstance(raw_media, list):
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason="malformed",
                    )
                    return
                media_paths, reason = self._save_envelope_media(raw_media)
                if reason is not None:
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason=reason,
                    )
                    return

            # Allow image-only turns (content may be empty when media is attached).
            if not content.strip() and not media_paths:
                await self._send_event(connection, "error", detail="missing content")
                return

            # Auto-attach on first use so clients can one-shot without a separate attach.
            self._attach(connection, cid)
            await self._hydrate_after_subscribe(cid)
            metadata: dict[str, Any] = {"remote": getattr(connection, "remote_address", None)}
            if envelope.get("webui") is True:
                metadata["webui"] = True
            image_generation = envelope.get("image_generation")
            if isinstance(image_generation, dict) and image_generation.get("enabled") is True:
                aspect_ratio = image_generation.get("aspect_ratio")
                metadata["image_generation"] = {
                    "enabled": True,
                    "aspect_ratio": aspect_ratio if isinstance(aspect_ratio, str) else None,
                }
            await self._handle_message(
                sender_id=client_id,
                chat_id=cid,
                content=content,
                media=media_paths or None,
                metadata=metadata,
                is_dm=False,
            )
            return
        await self._send_event(connection, "error", detail=f"unknown type: {t!r}")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except Exception as e:
                self.logger.warning("server task error during shutdown: {}", e)
            self._server_task = None
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()
        self._issued_tokens.clear()
        self._api_tokens.clear()

    async def _safe_send_to(self, connection: Any, raw: str, *, label: str = "") -> None:
        """Send a raw frame to one connection, cleaning up on ConnectionClosed."""
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
            self.logger.warning("connection gone{}", label)
        except Exception:
            self.logger.exception("send failed{}", label)
            raise

    async def send(self, msg: OutboundMessage) -> None:
        if msg.metadata.get("_runtime_model_updated"):
            await self.send_runtime_model_updated(
                model_name=msg.metadata.get("model"),
                model_preset=msg.metadata.get("model_preset"),
            )
            return

        # Snapshot the subscriber set so ConnectionClosed cleanups mid-iteration are safe.
        conns = list(self._subs.get(msg.chat_id, ()))
        if not conns:
            if (
                msg.metadata.get("_progress")
                or msg.metadata.get("_file_edit_events")
                or msg.metadata.get("_turn_end")
                or msg.metadata.get("_session_updated")
                or msg.metadata.get("_goal_status")
                or msg.metadata.get("_goal_state_sync")
                or msg.metadata.get("_subagent_status")
            ):
                self.logger.debug("no active subscribers for chat_id={}", msg.chat_id)
            else:
                self.logger.warning("no active subscribers for chat_id={}", msg.chat_id)
            return
        if msg.metadata.get("_goal_state_sync"):
            blob = msg.metadata.get("goal_state")
            await self.send_goal_state(msg.chat_id, blob if isinstance(blob, dict) else {"active": False})
            return
        if msg.metadata.get("_subagent_status"):
            await self.send_subagent_status(
                msg.chat_id,
                task_id=msg.metadata.get("task_id", ""),
                label=msg.metadata.get("label", ""),
                phase=msg.metadata.get("phase", ""),
                error=msg.metadata.get("error"),
            )
            return
        if msg.metadata.get("_goal_status"):
            status = msg.metadata.get("goal_status")
            if status in ("running", "idle"):
                started_raw = msg.metadata.get("started_at", msg.metadata.get("goal_started_at"))
                await self.send_goal_status(
                    msg.chat_id,
                    status,
                    started_at=float(started_raw) if isinstance(started_raw, int | float) else None,
                )
            return
        # Signal that the agent has fully finished processing the current turn.
        if msg.metadata.get("_turn_end"):
            lat = msg.metadata.get("latency_ms")
            lat_i = int(lat) if isinstance(lat, (int, float)) else None
            gs = msg.metadata.get("goal_state")
            gs_blob = gs if isinstance(gs, dict) else None
            await self.send_turn_end(msg.chat_id, latency_ms=lat_i, goal_state=gs_blob)
            return
        if msg.metadata.get("_session_updated"):
            scope = msg.metadata.get("_session_update_scope")
            await self.send_session_updated(
                msg.chat_id,
                scope=scope if isinstance(scope, str) else None,
            )
            return
        if msg.metadata.get("_file_edit_events"):
            payload: dict[str, Any] = {
                "event": "file_edit",
                "chat_id": msg.chat_id,
                "edits": msg.metadata["_file_edit_events"],
            }
            self._try_append_webui_transcript(msg.chat_id, payload)
            raw = json.dumps(payload, ensure_ascii=False)
            for connection in conns:
                await self._safe_send_to(connection, raw, label=" ")
            return
        text = msg.content
        payload: dict[str, Any] = {
            "event": "message",
            "chat_id": msg.chat_id,
            "text": text,
        }
        if msg.media:
            payload["media"] = msg.media
            urls: list[dict[str, str]] = []
            for entry in msg.media:
                signed = self._sign_or_stage_media_path(Path(entry))
                if signed is not None:
                    urls.append(signed)
            if urls:
                payload["media_urls"] = urls
        if msg.reply_to:
            payload["reply_to"] = msg.reply_to
        lat = msg.metadata.get("latency_ms")
        if isinstance(lat, (int, float)):
            payload["latency_ms"] = int(lat)
        if msg.metadata.get("_tool_events"):
            payload["tool_events"] = msg.metadata["_tool_events"]
        agent_ui = msg.metadata.get(OUTBOUND_META_AGENT_UI)
        if agent_ui is not None:
            payload["agent_ui"] = agent_ui
        # Mark intermediate agent breadcrumbs (tool-call hints, generic
        # progress strings) so WS clients can render them as subordinate
        # trace rows rather than conversational replies.
        if msg.metadata.get("_tool_hint"):
            payload["kind"] = "tool_hint"
        elif msg.metadata.get("_progress"):
            payload["kind"] = "progress"
        self._try_append_webui_transcript(msg.chat_id, payload)
        raw = json.dumps(payload, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" ")

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Push one chunk of model reasoning. Mirrors ``send_delta`` shape so
        clients receive a stream that opens, updates in place, and closes —
        rendered above the active assistant bubble with a shimmer header
        until the matching ``reasoning_end`` arrives.
        """
        conns = list(self._subs.get(chat_id, ()))
        if not conns or not delta:
            return
        meta = metadata or {}
        body: dict[str, Any] = {
            "event": "reasoning_delta",
            "chat_id": chat_id,
            "text": delta,
        }
        stream_id = meta.get("_stream_id")
        if stream_id is not None:
            body["stream_id"] = stream_id
        self._try_append_webui_transcript(chat_id, body)
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" reasoning ")

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Close the current reasoning stream segment for in-place renderers."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        meta = metadata or {}
        body: dict[str, Any] = {
            "event": "reasoning_end",
            "chat_id": chat_id,
        }
        stream_id = meta.get("_stream_id")
        if stream_id is not None:
            body["stream_id"] = stream_id
        self._try_append_webui_transcript(chat_id, body)
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" reasoning_end ")

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        meta = metadata or {}
        if meta.get("_stream_end"):
            body: dict[str, Any] = {"event": "stream_end", "chat_id": chat_id}
        else:
            body = {
                "event": "delta",
                "chat_id": chat_id,
                "text": delta,
            }
        if meta.get("_stream_id") is not None:
            body["stream_id"] = meta["_stream_id"]
        self._try_append_webui_transcript(chat_id, body)
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" stream ")

    async def send_turn_end(
        self,
        chat_id: str,
        latency_ms: int | None = None,
        *,
        goal_state: dict[str, Any] | None = None,
    ) -> None:
        """Signal that the agent has fully finished processing the current turn."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "turn_end", "chat_id": chat_id}
        if latency_ms is not None:
            body["latency_ms"] = int(latency_ms)
        if goal_state is not None:
            body["goal_state"] = goal_state
        self._try_append_webui_transcript(chat_id, body)
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_end ")

    async def send_goal_state(self, chat_id: str, blob: dict[str, Any]) -> None:
        """Push persisted goal-state snapshot for *chat_id* (multi-chat isolation)."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body = {"event": "goal_state", "chat_id": chat_id, "goal_state": blob}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" goal_state ")

    async def send_goal_status(
        self,
        chat_id: str,
        status: str,
        *,
        started_at: float | None = None,
    ) -> None:
        """Notify subscribed clients that a turn started or finished (wall-clock hint)."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {
            "event": "goal_status",
            "chat_id": chat_id,
            "status": status,
        }
        if status == "running" and started_at is not None:
            body["started_at"] = started_at
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" goal_status ")

    async def send_session_updated(self, chat_id: str, *, scope: str | None = None) -> None:
        """Notify clients that session metadata changed outside the main turn."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "session_updated", "chat_id": chat_id}
        if scope:
            body["scope"] = scope
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" session_updated ")

    async def send_subagent_status(
        self,
        chat_id: str,
        *,
        task_id: str,
        label: str,
        phase: str,
        error: str | None = None,
    ) -> None:
        """Notify clients that a subagent started or completed."""
        body: dict[str, Any] = {
            "event": "subagent_status",
            "chat_id": chat_id,
            "task_id": task_id,
            "label": label,
            "phase": phase,
        }
        if error:
            body["error"] = error
        self._subagent_status_history.append({
            "timestamp": datetime.now().isoformat(),
            "chat_id": chat_id,
            "task_id": task_id,
            "label": label,
            "phase": phase,
            "error": error,
        })
        if len(self._subagent_status_history) > 200:
            del self._subagent_status_history[:-200]
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" subagent_status ")

    async def send_runtime_model_updated(
        self,
        *,
        model_name: Any,
        model_preset: Any = None,
    ) -> None:
        """Broadcast runtime model changes to every open websocket connection."""
        conns = list(self._conn_chats)
        if not conns or not isinstance(model_name, str) or not model_name.strip():
            return
        body: dict[str, Any] = {
            "event": "runtime_model_updated",
            "model_name": model_name.strip(),
        }
        if isinstance(model_preset, str) and model_preset.strip():
            body["model_preset"] = model_preset.strip()
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" runtime_model_updated ")
