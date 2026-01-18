#!/usr/bin/env python3
"""FastMCP-based bridge exposing Fiddler real-time inspection tools to MCP clients."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from time import sleep
from typing import Any, Dict, List, Optional, Annotated

import requests
from mcp.server.fastmcp import FastMCP
from pydantic import Field

DEFAULT_BRIDGE_URL = "http://127.0.0.1:8081"
DEFAULT_TIMEOUT = 10.0
DEFAULT_BODY_TIMEOUT = 30.0
ENV_PREFIX = "FMP_FIDDLER_"


class BridgeError(Exception):
    """Base exception for bridge related failures."""


class BridgeConnectionError(BridgeError):
    """Raised when the HTTP bridge cannot be reached."""


class BridgeRequestError(BridgeError):
    """Raised for non-connection related HTTP errors."""


class HttpMethod(str, Enum):
    """Supported HTTP methods for session searching."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"


class TimelineGrouping(str, Enum):
    """Valid grouping keys for the timeline endpoint."""

    MINUTE = "minute"
    HOST = "host"
    STATUS_CODE = "status_code"
    CONTENT_TYPE = "content_type"


@dataclass
class FiddlerBridgeClient:
    """Thin synchronous client for the enhanced Fiddler HTTP bridge."""

    base_url: str = DEFAULT_BRIDGE_URL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = 3

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size to human readable string (KB, MB)"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f}MB"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}{path}"
        import time
        start_time = time.time()
        
        try:
            # CRITICAL: Bypass Fiddler proxy for localhost connections!
            # If Fiddler is running as system proxy, it will intercept localhost
            # requests and cause timeouts. We must bypass it for internal comms.
            response = requests.request(
                method,
                url,
                params=params,
                json=json_payload,
                timeout=timeout or self.timeout,
                proxies={'http': None, 'https': None},  # Bypass all proxies for localhost
            )
            response.raise_for_status()
            
            # Log HTTP timing and response size
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content) if response.content else 0
            logging.info("HTTP %s %s -> %s (%dms, %s)", 
                        method, path, response.status_code, elapsed_ms, self._format_size(response_size))
            
        except requests.exceptions.ConnectionError as exc:  # pragma: no cover - network specific
            elapsed_ms = int((time.time() - start_time) * 1000)
            logging.warning("HTTP %s %s -> ConnectionError (%dms)", method, path, elapsed_ms)
            raise BridgeConnectionError("Cannot connect to Fiddler real-time bridge") from exc
        except requests.exceptions.Timeout as exc:  # pragma: no cover - network specific
            elapsed_ms = int((time.time() - start_time) * 1000)
            logging.warning("HTTP %s %s -> Timeout (%dms)", method, path, elapsed_ms)
            raise BridgeRequestError("Bridge request timed out") from exc
        except requests.exceptions.RequestException as exc:  # pragma: no cover - network specific
            elapsed_ms = int((time.time() - start_time) * 1000)
            logging.warning("HTTP %s %s -> Error: %s (%dms)", method, path, exc, elapsed_ms)
            raise BridgeRequestError(f"HTTP request failed: {exc}") from exc

        if not response.content:
            return {}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except ValueError as exc:  # pragma: no cover - unexpected payload
                raise BridgeRequestError(f"Invalid JSON payload: {exc}") from exc
        try:
            return json.loads(response.text)
        except ValueError:
            return {"raw": response.text}

    def request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        attempt: int = 0,
    ) -> Dict[str, Any]:
        """Wrap request with exponential backoff retries."""

        try:
            return self.request(method, path, params=params, json_payload=json_payload, timeout=timeout)
        except (BridgeConnectionError, BridgeRequestError) as exc:
            if attempt < self.max_retries:
                wait_time = 2 ** attempt
                logging.warning(
                    "Request to %s failed (%s); retrying in %ss (attempt %s/%s)",
                    path,
                    exc,
                    wait_time,
                    attempt + 1,
                    self.max_retries,
                )
                sleep(wait_time)
                return self.request_with_retry(
                    method,
                    path,
                    params=params,
                    json_payload=json_payload,
                    timeout=timeout,
                    attempt=attempt + 1,
                )
            raise

    # Tool implementations -------------------------------------------------

    def get_live_sessions(
        self,
        *,
        limit: int,
        since_minutes: int,
        host_filter: Optional[str],
        status_filter: Optional[str],
        suspicious_only: bool,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        params["limit"] = max(1, min(limit, 500))
        params["since_minutes"] = max(1, min(since_minutes, 360))
        if host_filter:
            params["host"] = host_filter
        if status_filter:
            params["status"] = status_filter
        if suspicious_only:
            params["suspicious_only"] = "true"

        try:
            data = self.request("GET", "/api/sessions", params=params)
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge. Is it running?",
                "bridge_status": "Disconnected",
                "help": "Start the bridge with: python3 realtime-bridge.py",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Session query failed: {exc}",
                "bridge_status": "Error",
            }

        if not isinstance(data, dict) or not data.get("success", True):
            return {
                "success": False,
                "error": data.get("error", "Session query failed") if isinstance(data, dict) else "Unexpected response",
                "bridge_status": data.get("bridge_status", "Unknown") if isinstance(data, dict) else "Unknown",
            }

        raw_sessions: List[Dict[str, Any]] = list(data.get("sessions", []))
        normalized_sessions: List[Dict[str, Any]] = []
        unique_hosts = set()

        for session in raw_sessions:
            host = session.get("host", "") or ""
            unique_hosts.add(host)
            # Check for EKFiddle comments from multiple possible fields
            ekfiddle_comment = (session.get("ekfiddleComments") or 
                               session.get("sessionFlags") or 
                               session.get("ekfiddleFlags") or "").strip()
            
            normalized_sessions.append(
                {
                    "id": session.get("id"),
                    "time": session.get("time"),
                    "received_at": session.get("received_at"),
                    "received_at_iso": session.get("received_at_iso"),
                    "method": session.get("method", "GET"),
                    "status": str(session.get("statusCode", session.get("status", "?"))),
                    "status_code": session.get("statusCode"),
                    "host": host,
                    "url": session.get("url", ""),
                    "content_type": session.get("content_type") or session.get("contentType"),
                    "size": session.get("size", session.get("contentLength", 0)),
                    "content_length": session.get("contentLength"),
                    "is_https": session.get("is_https", (session.get("scheme") or "").lower() == "https"),
                    "risk_flag": session.get("risk_flag"),
                    "risk_score": session.get("risk_score"),
                    "risk_level": session.get("risk_level"),
                    "risk_reasons": session.get("risk_reasons", []),
                    "ekfiddle_comment": ekfiddle_comment if ekfiddle_comment else None,
                }
            )

        statistics = data.get("statistics") or {
            "total_returned": len(normalized_sessions),
            "total_buffered": data.get("total_live", len(raw_sessions)),
            "unique_hosts": sorted([h for h in unique_hosts if h]),
        }

        if not normalized_sessions:
            return {
                "success": True,
                "sessions": [],
                "count": 0,
                "summary": "No live sessions found for the provided filters",
                "statistics": statistics,
                "bridge_status": "Connected",
                "query": data.get("query", params),
                "time_bounds": data.get("time_bounds", {}),
                "query_timestamp": datetime.now().isoformat(),
            }

        return {
            "success": True,
            "sessions": normalized_sessions,
            "count": len(normalized_sessions),
            "matched_count": data.get("matched_count", len(normalized_sessions)),
            "summary": "Use a session ID with fiddler_mcp__session_headers or fiddler_mcp__session_body to inspect content.",
            "statistics": statistics,
            "bridge_status": "Connected",
            "query": data.get("query", params),
            "time_bounds": data.get("time_bounds", {}),
            "query_timestamp": datetime.now().isoformat(),
            "unique_hosts": statistics.get("unique_hosts", sorted([h for h in unique_hosts if h])),
        }

    def search_sessions(
        self,
        *,
        host_pattern: Optional[str],
        url_pattern: Optional[str],
        content_type: Optional[str],
        method: Optional[str],
        status_min: int,
        status_max: int,
        min_size: int,
        max_size: int,
        since_minutes: Optional[int],
        limit: int,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "status_min": status_min,
            "status_max": status_max,
            "min_size": min_size,
            "max_size": max_size,
            "limit": max(1, min(limit, 500)),
        }
        if host_pattern:
            params["host"] = host_pattern
        if url_pattern:
            params["url"] = url_pattern
        if content_type:
            params["content_type"] = content_type
        if method:
            params["method"] = method.upper()
        if since_minutes is not None:
            params["since_minutes"] = max(1, min(since_minutes, 360))

        try:
            data = self.request("GET", "/api/sessions/search", params=params)
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Search failed: {exc}",
            }

        if not isinstance(data, dict) or not data.get("success", True):
            return {
                "success": False,
                "error": data.get("error", "Search failed") if isinstance(data, dict) else "Unexpected response",
                "query": data.get("query", params) if isinstance(data, dict) else params,
            }

        normalized_sessions: List[Dict[str, Any]] = []
        unique_hosts = set()
        for session in data.get("sessions", []):
            unique_hosts.add(session.get("host", ""))
            # Check for EKFiddle comments from multiple possible fields
            ekfiddle_comment = (session.get("ekfiddleComments") or 
                               session.get("sessionFlags") or 
                               session.get("ekfiddleFlags") or "").strip()
            
            normalized_sessions.append(
                {
                    "id": session.get("id"),
                    "time": session.get("time"),
                    "received_at": session.get("received_at"),
                    "received_at_iso": session.get("received_at_iso"),
                    "method": session.get("method", "GET"),
                    "status": str(session.get("statusCode", session.get("status", "?"))),
                    "status_code": session.get("statusCode"),
                    "host": session.get("host", ""),
                    "url": session.get("url", ""),
                    "content_type": session.get("content_type") or session.get("content_type_full"),
                    "size": session.get("size", session.get("contentLength", 0)),
                    "content_length": session.get("contentLength"),
                    "is_https": session.get("is_https", False),
                    "risk_flag": session.get("risk_flag"),
                    "risk_score": session.get("risk_score"),
                    "risk_level": session.get("risk_level"),
                    "risk_reasons": session.get("risk_reasons", []),
                    "ekfiddle_comment": ekfiddle_comment if ekfiddle_comment else None,
                }
            )

        return {
            "success": True,
            "search_type": "advanced",
            "query": data.get("query", params),
            "total_matched": data.get("total_matched", 0),
            "returned": len(normalized_sessions),
            "sessions": normalized_sessions,
            "unique_hosts": sorted(h for h in unique_hosts if h),
        }

    def get_session_headers(self, *, session_id: str) -> Dict[str, Any]:
        try:
            data = self.request("GET", f"/api/sessions/headers/{session_id}")
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Header lookup failed: {exc}",
                "session_id": session_id,
            }

        if not isinstance(data, dict) or not data.get("success", False):
            return {
                "success": False,
                "error": data.get("error", "Headers not available") if isinstance(data, dict) else "Unexpected response",
                "session_id": session_id,
            }

        return {
            "success": True,
            "session_id": session_id,
            "request_headers": data.get("request_headers", {}),
            "response_headers": data.get("response_headers", {}),
            "notes": [
                "Use these headers to reason about authentication, caching, and security controls yourself.",
            ],
        }

    def get_session_body(self, *, session_id: str, include_binary: bool, smart_extract: bool = False) -> Dict[str, Any]:
        # Build params - additive approach preserves existing behavior when smart_extract=False (default)
        params = {}
        if include_binary:
            params["raw"] = "true"
        if smart_extract:
            params["smart_extract"] = "true"
        
        try:
            data = self.request_with_retry(
                "GET",
                f"/api/sessions/body/{session_id}",
                params=params,
                timeout=DEFAULT_BODY_TIMEOUT,
            )
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge after retries",
                "bridge_status": "Disconnected",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Body retrieval failed: {exc}",
                "session_id": session_id,
            }

        if not isinstance(data, dict) or not data.get("success", False):
            error_msg = data.get("error", "Body not available") if isinstance(data, dict) else "Unexpected response"
            
            # Provide helpful hints and prevent tool hallucination
            if "codec" in str(error_msg).lower() or "decode" in str(error_msg).lower():
                error_msg = (
                    f"Session {session_id}: Character encoding error during body retrieval. "
                    f"This has been fixed in the latest version. If you see this error, "
                    f"restart gemini-fiddler-client.py. "
                    f"Available tools: fiddler_mcp__session_body (with include_binary=true for full content). "
                    f"Do NOT use 'session_raw' or 'list_sessions' - these tools don't exist. "
                    f"Technical details: {error_msg}"
                )
            
            return {
                "success": False,
                "error": error_msg,
                "session_id": session_id,
            }

        # Build response - existing fields preserved, new fields added when available
        result = {
            "success": True,
            "analysis_type": "body",
            "id": data.get("id", session_id),
            "session_id": session_id,
            "content_type": data.get("content_type"),
            "content_length": data.get("content_length"),
            "request_body": data.get("request_body", ""),
            "response_body": data.get("response_body", ""),
            "truncated": data.get("truncated", False),
            "response_truncated": data.get("response_truncated", data.get("truncated", False)),
            "request_truncated": data.get("request_truncated", False),
            "full_size": data.get("full_size", {}),
        }
        
        # NEW: Pass through smart extraction data if available (additive - never replaces existing fields)
        if data.get("smart_extraction_available"):
            result["smart_extraction"] = data.get("smart_extraction", {})
            result["smart_extraction_available"] = True
        else:
            result["smart_extraction_available"] = False
            if data.get("smart_extraction_error"):
                result["smart_extraction_error"] = data.get("smart_extraction_error")
        
        return result

    def get_multiple_session_bodies(self, *, session_ids: List[str], include_binary: bool, smart_extract: bool = False) -> Dict[str, Any]:
        """Fetch bodies for multiple sessions efficiently for comparison analysis."""
        if not session_ids:
            return {
                "success": False,
                "error": "No session IDs provided",
                "sessions": [],
                "count": 0,
                "requested": 0,
            }
        
        sessions_data = []
        success_count = 0
        
        for session_id in session_ids:
            # Fetch each session body (pass through smart_extract for large file analysis)
            result = self.get_session_body(session_id=session_id, include_binary=include_binary, smart_extract=smart_extract)
            
            if result.get("success"):
                # Add metadata that's useful for comparison
                session_info = {
                    "session_id": session_id,
                    "success": True,
                    "response_body": result.get("response_body", ""),
                    "request_body": result.get("request_body", ""),
                    "content_type": result.get("content_type", ""),
                    "content_length": result.get("content_length", 0),
                    "truncated": result.get("truncated", False),
                }
                
                # NEW: Include smart extraction data if available
                if result.get("smart_extraction_available"):
                    session_info["smart_extraction"] = result.get("smart_extraction", {})
                    session_info["smart_extraction_available"] = True
                
                # Try to get additional metadata from live_sessions
                try:
                    sessions_list = self.get_live_sessions(limit=500, since_minutes=360)
                    if sessions_list.get("success"):
                        for sess in sessions_list.get("sessions", []):
                            if str(sess.get("id")) == str(session_id):
                                session_info["host"] = sess.get("host", "")
                                session_info["url"] = sess.get("url", "")
                                session_info["method"] = sess.get("method", "")
                                session_info["status"] = sess.get("status", 0)
                                break
                except Exception:
                    pass  # Metadata is optional, don't fail the whole request
                
                sessions_data.append(session_info)
                success_count += 1
            else:
                # Include failed fetch with error info
                sessions_data.append({
                    "session_id": session_id,
                    "success": False,
                    "error": result.get("error", "Failed to fetch session"),
                    "response_body": "",
                    "request_body": "",
                })
        
        return {
            "success": True,
            "sessions": sessions_data,
            "count": success_count,
            "requested": len(session_ids),
            "analysis_type": "comparison",
            "note": f"Successfully fetched {success_count} of {len(session_ids)} sessions for comparison",
        }

    def get_live_stats(self) -> Dict[str, Any]:
        try:
            data = self.request("GET", "/api/stats")
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Real-time bridge is not running",
                "bridge_status": "Disconnected",
                "help": "Start the bridge with: python3 realtime-bridge.py",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Failed to get stats: {exc}",
            }

        uptime_seconds = data.get("uptime_seconds", 0)
        uptime_hours = uptime_seconds / 3600 if isinstance(uptime_seconds, (int, float)) else 0
        capture_rate_minute = data.get("last_minute", 0)
        capture_rate_hour = data.get("last_hour", 0)
        buffered_sessions = data.get("buffered_sessions", data.get("total_sessions", 0))

        memory_usage = data.get("memory_usage", {})
        buffer_capacity = data.get("buffer_capacity", 2000)
        buffer_usage_ratio = data.get("buffer_usage_ratio", 0)

        return {
            "success": True,
            "bridge_status": data.get("bridge_status", "Connected"),
            "total_sessions": data.get("total_sessions", 0),
            "buffered_sessions": buffered_sessions,
            "buffer_capacity": buffer_capacity,
            "buffer_usage_ratio": buffer_usage_ratio,
            "buffer_usage_pct": round(buffer_usage_ratio * 100, 2) if isinstance(buffer_usage_ratio, (int, float)) else None,
            "suspicious_sessions": data.get("suspicious_sessions", 0),
            "last_minute": capture_rate_minute,
            "last_hour": capture_rate_hour,
            "uptime_seconds": uptime_seconds,
            "uptime_hours": round(uptime_hours, 2),
            "monitoring": {
                "total_sessions_captured": data.get("total_sessions", 0),
                "sessions_in_buffer": buffered_sessions,
                "suspicious_sessions": data.get("suspicious_sessions", 0),
                "uptime_hours": round(uptime_hours, 2),
                "capture_rate": {
                    "last_minute": capture_rate_minute,
                    "last_hour": capture_rate_hour,
                    "avg_per_minute": round(capture_rate_hour / 60, 1) if capture_rate_hour else 0,
                },
            },
            "memory_status": memory_usage,
            "health": "Healthy"
            if uptime_seconds and not memory_usage.get("live_buffer_full", False)
            else "Warning",
            "timestamp": datetime.now().isoformat(),
        }

    def get_sessions_timeline(
        self,
        *,
        time_range_minutes: int,
        group_by: TimelineGrouping,
        include_details: bool,
        filter_host: Optional[str],
    ) -> Dict[str, Any]:
        params = {
            "time_range_minutes": max(1, min(time_range_minutes, 180)),
            "group_by": group_by.value,
            "include_details": "true" if include_details else "false",
        }
        if filter_host:
            params["filter_host"] = filter_host

        try:
            data = self.request("GET", "/api/sessions/timeline", params=params)
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Timeline request failed: {exc}",
            }

        return {
            "success": True,
            "analysis_type": "timeline",
            "timeline": data.get("timeline", {}),
            "timeline_entries": data.get("timeline_entries", 0),
            "total_sessions": data.get("total_sessions", 0),
            "group_by": data.get("group_by", params["group_by"]),
            "time_range_minutes": data.get("time_range_minutes", params["time_range_minutes"]),
            "filter_host": data.get("filter_host", params.get("filter_host")),
            "include_details": include_details,
        }

    def clear_sessions(self, *, confirm: bool, clear_suspicious: bool) -> Dict[str, Any]:
        if not confirm:
            return {
                "success": False,
                "error": "Confirmation required to clear sessions",
                "help": "Set confirm=true to permanently delete all buffered session data.",
            }

        payload = {
            "confirm": True,
            "clear_suspicious": bool(clear_suspicious),
        }

        try:
            data = self.request("POST", "/api/clear", json_payload=payload)
        except BridgeConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected",
            }
        except BridgeRequestError as exc:
            return {
                "success": False,
                "error": f"Clear request failed: {exc}",
            }

        if not isinstance(data, dict) or not data.get("success", True):
            return {
                "success": False,
                "error": data.get("error", "Clear request failed") if isinstance(data, dict) else "Unexpected response",
            }

        return {
            "success": True,
            "message": data.get("message", "Sessions cleared"),
            "cleared_counts": {
                "live_sessions": data.get("sessions_cleared", 0),
                "suspicious_sessions": data.get("suspicious_cleared", 0),
            },
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
        }

    def check_bridge_health(self) -> bool:
        """Lightweight reachability probe for the HTTP bridge."""

        try:
            # Bypass Fiddler proxy for localhost health checks
            response = requests.get(
                f"{self.base_url.rstrip('/')}/health",
                timeout=2,
                proxies={'http': None, 'https': None}
            )
        except requests.exceptions.RequestException:
            return False
        return response.status_code == 200


# Configure logging EARLY (before FastMCP initialization)
import sys
_log_level = os.environ.get(f"{ENV_PREFIX}LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
    force=True
)
# Immediate test to verify stderr logging works
print(f"[5ire-bridge] Initializing (log_level={_log_level})", file=sys.stderr, flush=True)
logging.info("Logging configured (level=%s)", _log_level)

client = FiddlerBridgeClient()
# FastMCP log level (controls FastMCP framework logs)
_mcp_log_level = os.environ.get(f"{ENV_PREFIX}LOG_LEVEL", "INFO").upper()
mcp = FastMCP("fiddler-mcp/5ire-bridge", log_level=_mcp_log_level)


@mcp.tool()
def fiddler_mcp__live_sessions(
    limit: Annotated[int, Field(description="Maximum number of sessions to return (1-500).", ge=1, le=500)] = 20,
    since_minutes: Annotated[int, Field(description="Look back this many minutes (1-360).", ge=1, le=360)] = 60,
    host_filter: Annotated[Optional[str], Field(description="Filter by host substring or regex.")] = None,
    status_filter: Annotated[Optional[str], Field(description="Filter by HTTP status code (e.g. '404').")] = None,
    suspicious_only: Annotated[bool, Field(description="Only return sessions previously flagged as suspicious.")] = False,
) -> Dict[str, Any]:
    """Get a list of recent sessions with metadata ONLY (not the actual content).

    **USE THIS TOOL when asked:**
    - "List recent sessions"
    - "Show me the last X sessions"
    - "What sessions were captured?"
    - "List domains/hosts from traffic"
    
    Returns session metadata including: id, method, status, host, url, size, content_type,
    and risk indicators (risk_flag, risk_score, risk_level, risk_reasons).
    
    **This returns METADATA ONLY.** To see actual response content, you must:
    1. Get the session `id` from these results
    2. Call fiddler_mcp__session_body with that `id`
    
    **Session IDs** are opaque strings like "120" or "sid-1758709783214" - always
    pass them back exactly as returned when calling fiddler_mcp__session_body or
    fiddler_mcp__session_headers.

    Examples:
        # Get last 20 sessions
        fiddler_mcp__live_sessions(limit=20, since_minutes=5)

        # Find suspicious sessions from a specific host
        fiddler_mcp__live_sessions(
            host_filter="webdisk.windtech-international.com",
            suspicious_only=True,
            limit=50
        )
        
        # Then inspect content of session 120
        fiddler_mcp__session_body(session_id="120")
    """
    logging.info("Tool called: fiddler_mcp__live_sessions(limit=%s, suspicious_only=%s, since_minutes=%s)", 
                 limit, suspicious_only, since_minutes)

    result = client.get_live_sessions(
        limit=limit,
        since_minutes=since_minutes,
        host_filter=host_filter,
        status_filter=status_filter,
        suspicious_only=suspicious_only,
    )
    
    # Log result summary
    if result.get("success"):
        session_count = result.get("count", 0)
        sessions = result.get("sessions", [])
        suspicious_count = sum(1 for s in sessions if s.get("risk_flag") or s.get("ekfiddle_comment"))
        ekfiddle_count = sum(1 for s in sessions if s.get("ekfiddle_comment"))
        unique_hosts = len(result.get("unique_hosts", []))
        logging.info("Tool result: fiddler_mcp__live_sessions -> %d sessions, %d suspicious, %d ekfiddle, %d hosts", 
                     session_count, suspicious_count, ekfiddle_count, unique_hosts)
    else:
        logging.warning("Tool result: fiddler_mcp__live_sessions -> error: %s", result.get("error", "unknown"))
    
    return result


@mcp.tool()
def fiddler_mcp__sessions_search(
    host_pattern: Annotated[Optional[str], Field(description="Substring or regex to match host names.")] = None,
    url_pattern: Annotated[Optional[str], Field(description="Substring or regex to match URLs.")] = None,
    content_type: Annotated[Optional[str], Field(description="Filter by MIME hint (e.g. 'javascript', 'text/html').")] = None,
    method: Annotated[Optional[HttpMethod], Field(description="Restrict to a specific HTTP method.")] = None,
    status_min: Annotated[int, Field(description="Minimum HTTP status code.", ge=0, le=999)] = 0,
    status_max: Annotated[int, Field(description="Maximum HTTP status code.", ge=0, le=999)] = 999,
    min_size: Annotated[int, Field(description="Minimum response size in bytes.", ge=0)] = 0,
    max_size: Annotated[int, Field(description="Maximum response size in bytes.")] = 1_000_000_000,
    since_minutes: Annotated[Optional[int], Field(description="Only include sessions captured in the last N minutes.", ge=1, le=360)] = None,
    limit: Annotated[int, Field(description="Maximum matches to return (1-500).", ge=1, le=500)] = 50,
) -> Dict[str, Any]:
    """Search for specific sessions using filters, then use the returned session IDs
    with fiddler_mcp__session_body or fiddler_mcp__session_headers for detailed inspection.

    **WORKFLOW:**
    1. Use this tool to FIND sessions matching your criteria
    2. Get the session `id` from the results
    3. Use that `id` with fiddler_mcp__session_body to see the actual content
    
    **This tool returns metadata ONLY** (not the actual response content).
    Each result includes: id, host, url, method, status, size, content_type.
    
    The `content_type` parameter accepts shortcuts: "javascript", "html", "json", 
    or full MIME strings like "application/json".

    **Common use cases:**
    - Find POST requests to a specific domain: host_pattern="sentry.io", method="POST"
    - Find JavaScript files: content_type="javascript"
    - Find failed requests: status_min=400
    - Find large responses: min_size=100000

    **REMEMBER:** After finding sessions, you MUST use fiddler_mcp__session_body
    with the returned session ID to see what's actually inside!

    Examples:
        # Step 1: Find JavaScript from a host
        results = fiddler_mcp__sessions_search(
            host_pattern="webdisk.windtech-international.com",
            content_type="javascript",
            since_minutes=10
        )
        
        # Step 2: Inspect the content (use the 'id' from results)
        fiddler_mcp__session_body(session_id=results['sessions'][0]['id'])
        
        # Find POST requests that failed
        fiddler_mcp__sessions_search(
            method=HttpMethod.POST,
            status_min=400,
            min_size=10 * 1024,
            limit=200
        )
    """
    logging.info("Tool called: fiddler_mcp__sessions_search(host=%s, content_type=%s, method=%s, limit=%s)", 
                 host_pattern, content_type, method.value if method else None, limit)

    result = client.search_sessions(
        host_pattern=host_pattern,
        url_pattern=url_pattern,
        content_type=content_type,
        method=method.value if method else None,
        status_min=status_min,
        status_max=status_max,
        min_size=min_size,
        max_size=max_size,
        since_minutes=since_minutes,
        limit=limit,
    )
    
    # Log result summary
    if result.get("success"):
        matched = result.get("total_matched", 0)
        returned = result.get("returned", 0)
        unique_hosts = len(result.get("unique_hosts", []))
        logging.info("Tool result: fiddler_mcp__sessions_search -> matched=%d, returned=%d, hosts=%d", 
                     matched, returned, unique_hosts)
    else:
        logging.warning("Tool result: fiddler_mcp__sessions_search -> error: %s", result.get("error", "unknown"))
    
    return result


@mcp.tool()
def fiddler_mcp__session_headers(
    session_id: Annotated[str, Field(description="Session ID from live_sessions or sessions_search.")],
) -> Dict[str, Any]:
    """Fetch ONLY the HTTP headers (NOT the body content) for a captured session.

    USE THIS TOOL ONLY when specifically asked about headers, caching directives,
    authentication headers, cookies, or HTTP metadata. 
    
    DO NOT use this for analyzing response content, JSON data, JavaScript code,
    or message bodies - use fiddler_mcp__session_body instead.

    Returns a dictionary with `request_headers` and `response_headers` mappings
    exactly as captured by Fiddler.

    Example use cases:
        - "Show me the headers for session 120"
        - "Check caching directives for session sid-1758709783214"
        - "What authentication headers are in session 50?"
        
    When asked to "explain session X" or "analyze session X content" - use
    fiddler_mcp__session_body instead!
    """

    return client.get_session_headers(session_id=session_id)


@mcp.tool()
def fiddler_mcp__session_body(
    session_id: Annotated[str, Field(description="Session ID from live_sessions or sessions_search.")],
    include_binary: Annotated[bool, Field(description="Return base64-encoded payloads for binary content.")] = False,
    smart_extract: Annotated[bool, Field(description="For large files (>50KB), extract head/tail/suspicious patterns instead of just first 50KB. Recommended for JavaScript analysis.")] = False,
) -> Dict[str, Any]:
    """Retrieve the actual content/payload from request and response bodies.

    **USE THIS TOOL when asked to:**
    - "Explain the response from session X"
    - "What does session X contain?"
    - "Analyze the content of session X"
    - "Show me the body of session X"
    - "What data is sent in session X?"
    - "Inspect the JavaScript/JSON/HTML in session X"
    - "What's the payload of session X?"
    
    The response includes:
    - `request_body`: What was sent TO the server
    - `response_body`: What the server sent BACK (this is usually what you want)
    - `content_type`: MIME type (e.g., application/json, text/javascript)
    - `content_length`: Size in bytes
    - `truncated`: True if response was too large (>50KB) and was cut off

    Set `include_binary=true` to request the entire payload (useful for large
    text responses or binary data). When enabled, the client saves the full
    response/request bodies to disk and returns a shortened preview along with
    file paths.

    Set `smart_extract=true` for large JavaScript files (>50KB) to get intelligent
    content extraction instead of simple truncation. This extracts:
    - First 8KB (variable declarations, imports, configs)
    - Last 4KB (execution logic, callbacks)  
    - Suspicious patterns from middle section (eval, Function, redirects, etc.)
    This provides better security analysis coverage for obfuscated scripts.

    **IMPORTANT**: When a user says "explain session X" or "analyze session X",
    they want the BODY (content), not just headers. Use THIS tool, not session_headers!

    Examples:
        # Analyze JSON response content
        fiddler_mcp__session_body(session_id="28")
        
        # Get JavaScript code from session
        fiddler_mcp__session_body(session_id="159")
        
        # Inspect POST request data
        fiddler_mcp__session_body(session_id="17")
        
        # Analyze large obfuscated JavaScript with smart extraction
        fiddler_mcp__session_body(session_id="265", smart_extract=True)
    """
    logging.info("Tool called: fiddler_mcp__session_body(session_id=%s, smart_extract=%s, include_binary=%s)", 
                 session_id, smart_extract, include_binary)

    result = client.get_session_body(session_id=session_id, include_binary=include_binary, smart_extract=smart_extract)
    
    # Log result summary with session metadata
    if result.get("success"):
        content_type = result.get("content_type", "unknown")
        content_length = result.get("content_length", 0)
        response_body_len = len(result.get("response_body", "") or "")
        truncated = result.get("truncated", False)
        smart_avail = result.get("smart_extraction_available", False)
        logging.info("Tool result: fiddler_mcp__session_body -> session=%s, content_type=%s, size=%s, truncated=%s, smart_extract=%s", 
                     session_id, content_type, client._format_size(content_length or response_body_len), truncated, smart_avail)
    else:
        logging.warning("Tool result: fiddler_mcp__session_body -> session=%s, error: %s", session_id, result.get("error", "unknown"))
    
    return result


@mcp.tool()
def fiddler_mcp__compare_sessions(
    session_ids: Annotated[List[str], Field(description="List of session IDs to compare (2-10 sessions).")],
    include_binary: Annotated[bool, Field(description="Return base64-encoded payloads for binary content.")] = False,
    smart_extract: Annotated[bool, Field(description="For large files (>50KB), extract head/tail/suspicious patterns. Recommended for JavaScript comparison.")] = False,
) -> Dict[str, Any]:
    """Fetch and compare code/content from multiple sessions at once.

    **USE THIS TOOL when asked to:**
    - "Compare sessions 134, 148, 192, 194"
    - "What are the differences between sessions X, Y, and Z?"
    - "Analyze and compare sessions A, B, C"
    - "Show me code from sessions X and Y and compare them"
    - "How do sessions X, Y, Z fit together?"
    - "Compare the code in sessions 10, 20, 30"
    
    This tool efficiently fetches content from multiple sessions in one call,
    making it ideal for comparative analysis.
    
    **Returns**:
    - `success`: Boolean indicating if fetch was successful
    - `sessions`: Array of session data, each containing:
        - `session_id`: The session ID
        - `success`: Whether this specific session was retrieved
        - `response_body`: The response content (if available)
        - `request_body`: The request content (if available)
        - `content_type`: MIME type
        - `content_length`: Size in bytes
        - `host`: Domain/host
        - `url`: Full URL
        - `smart_extraction`: Intelligent extraction data (if smart_extract=True and file >50KB)
        - `error`: Error message (if fetch failed)
    - `count`: Number of sessions successfully fetched
    - `requested`: Number of sessions requested
    
    **Limits**: 
    - Minimum 2 sessions (use fiddler_mcp__session_body for single session)
    - Maximum 10 sessions per call (to prevent timeout)
    
    **Analysis Tips**:
    After fetching, you should:
    1. Compare code structure and patterns across sessions
    2. Identify common functions, variables, or patterns
    3. Note differences in behavior or implementation
    4. Explain how they fit together (e.g., multi-stage attack, related scripts)
    5. Provide a comprehensive summary of findings
    
    Examples:
        # Compare 3 sessions
        fiddler_mcp__compare_sessions(session_ids=["134", "148", "192"])
        
        # Compare 4 sessions with full content
        fiddler_mcp__compare_sessions(session_ids=["10", "20", "30", "40"], include_binary=True)
        
        # Compare large JavaScript files with smart extraction
        fiddler_mcp__compare_sessions(session_ids=["265", "270"], smart_extract=True)
    """
    if not isinstance(session_ids, list) or len(session_ids) < 2:
        return {
            "success": False,
            "error": "Must provide at least 2 session IDs in a list",
            "requested": len(session_ids) if isinstance(session_ids, list) else 0,
        }
    
    if len(session_ids) > 10:
        return {
            "success": False,
            "error": "Maximum 10 sessions per comparison (to prevent timeout)",
            "requested": len(session_ids),
        }
    
    logging.info("Tool called: fiddler_mcp__compare_sessions(session_ids=%s, count=%d, smart_extract=%s)", 
                 session_ids, len(session_ids), smart_extract)
    
    result = client.get_multiple_session_bodies(session_ids=session_ids, include_binary=include_binary, smart_extract=smart_extract)
    
    # Log result summary
    if result.get("success"):
        requested = result.get("requested", 0)
        fetched = result.get("count", 0)
        sessions = result.get("sessions", [])
        total_size = sum(len(s.get("response_body", "") or "") for s in sessions)
        logging.info("Tool result: fiddler_mcp__compare_sessions -> fetched %d/%d sessions, total_size=%s", 
                     fetched, requested, client._format_size(total_size))
    else:
        logging.warning("Tool result: fiddler_mcp__compare_sessions -> error: %s", result.get("error", "unknown"))
    
    return result


@mcp.tool()
def fiddler_mcp__live_stats() -> Dict[str, Any]:
    """Summarise bridge health: buffer depth, capture rates, uptime, and utilisation.

    Returns top-level fields such as `total_sessions`, `buffered_sessions`,
    `suspicious_sessions`, `last_minute`, `last_hour`, `uptime_seconds`, and
    `buffer_usage_pct` so the analyst can gauge how fresh the buffer is.

    Example:
        stats = fiddler_mcp__live_stats()
        if stats["buffer_usage_pct"] > 75:
            print("Buffer almost full; consider clearing or exporting sessions")
    """

    return client.get_live_stats()


@mcp.tool()
def fiddler_mcp__sessions_timeline(
    time_range_minutes: Annotated[int, Field(description="Look back this many minutes (1-180).", ge=1, le=180)] = 60,
    group_by: Annotated[TimelineGrouping, Field(description="Group timeline buckets by minute, host, status_code, or content_type.")] = TimelineGrouping.MINUTE,
    include_details: Annotated[bool, Field(description="Include representative session IDs for each bucket.")] = True,
    filter_host: Annotated[Optional[str], Field(description="Restrict results to hosts matching this substring.")] = None,
) -> Dict[str, Any]:
    """Visualise activity bursts by time, host, status, or MIME type.

    The response contains `timeline` buckets keyed by the chosen grouping and
    includes counts plus optional representative session IDs for quick follow-up.

    Example:
        fiddler_mcp__sessions_timeline(time_range_minutes=30,
                                       group_by=TimelineGrouping.STATUS_CODE)
    """

    return client.get_sessions_timeline(
        time_range_minutes=time_range_minutes,
        group_by=group_by,
        include_details=include_details,
        filter_host=filter_host,
    )


@mcp.tool()
def fiddler_mcp__sessions_clear(
    confirm: Annotated[bool, Field(description="REQUIRED: Set to true to permanently clear the live buffer.")] = False,
    clear_suspicious: Annotated[bool, Field(description="Also clear the dedicated suspicious-session buffer.")] = False,
) -> Dict[str, Any]:
    """Clear the rolling buffers once evidence has been exported.

    Returns `cleared_counts` detailing how many live and suspicious sessions were
    removed, along with a timestamp acknowledgement.

    Example:
        result = fiddler_mcp__sessions_clear(confirm=True)
        assert result["cleared_counts"]["live_sessions"] == 0
    """

    return client.clear_sessions(confirm=confirm, clear_suspicious=clear_suspicious)


def _env(name: str, default: str) -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def main() -> None:
    # Force UTF-8 encoding for stdin/stdout/stderr on Windows
    import sys
    if sys.platform == "win32":
        import io
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
    
    # Logging already configured at module level
    log_level = _env("LOG_LEVEL", "INFO").upper()
    
    logging.info("5ire-bridge MCP server starting (log_level=%s)", log_level)
    logging.info("Bridge URL: %s", _env("BRIDGE_URL", DEFAULT_BRIDGE_URL))
    
    client.base_url = _env("BRIDGE_URL", DEFAULT_BRIDGE_URL).rstrip("/")
    try:
        client.timeout = max(1e-3, float(_env("TIMEOUT", str(DEFAULT_TIMEOUT))))
    except ValueError:
        client.timeout = DEFAULT_TIMEOUT

    transport = _env("TRANSPORT", "stdio").lower()
    logging.info("Using transport: %s", transport)

    try:
        if transport == "sse":
            host = _env("HOST", "127.0.0.1")
            try:
                port = int(_env("PORT", "8765"))
            except ValueError:
                port = 8765
            mcp.settings.host = host
            mcp.settings.port = port
            logging.info("MCP server available at http://%s:%s/sse", host, port)
            mcp.run(transport="sse")
        else:
            logging.info("MCP server ready on stdio")
            mcp.run(transport="stdio")
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        pass


if __name__ == "__main__":
    main()
