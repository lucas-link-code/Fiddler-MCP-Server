#!/usr/bin/env python3
"""Gemini native FunctionDeclaration helpers for Fiddler MCP tools.

Converts MCP tools/list schemas into google.generativeai FunctionDeclarations
and extracts function_call parts from model responses.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Gemini function name: letter/underscore start; a-zA-Z0-9_.; max 64
_FUNC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

# Caps for FunctionResponse payload size
DEFAULT_MAX_RESPONSE_CHARS = 48_000
BODY_FIELD_MAX_CHARS = 24_000


def is_valid_gemini_function_name(name: str) -> bool:
    return bool(name and _FUNC_NAME_RE.match(name))


def _normalize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce MCP JSON Schema to the subset Gemini FunctionDeclaration accepts."""
    from llm_tool_schema import normalize_json_schema
    return normalize_json_schema(schema)


def mcp_tool_to_function_declaration(tool: Dict[str, Any]):
    """Convert one MCP tool dict into a Gemini FunctionDeclaration."""
    from google.generativeai.types import FunctionDeclaration

    name = str(tool.get("name") or "").strip()
    if not is_valid_gemini_function_name(name):
        raise ValueError(f"Invalid Gemini function name: {name!r}")

    description = (tool.get("description") or "").strip()
    if len(description) > 1024:
        description = description[:1000].rstrip() + "..."

    raw_schema = tool.get("inputSchema") or tool.get("input_schema") or {
        "type": "object",
        "properties": {},
    }
    parameters = _normalize_json_schema(raw_schema if isinstance(raw_schema, dict) else {})

    return FunctionDeclaration(
        name=name,
        description=description or f"MCP tool {name}",
        parameters=parameters,
    )


def build_gemini_tool(available_tools: List[Dict[str, Any]]):
    """Build a single Gemini Tool from MCP tools/list entries."""
    from google.generativeai.types import Tool

    decls = []
    errors = []
    for tool in available_tools or []:
        try:
            decls.append(mcp_tool_to_function_declaration(tool))
        except Exception as exc:
            errors.append(f"{tool.get('name')}: {exc}")
    if not decls:
        return None, errors
    return Tool(function_declarations=decls), errors


def extract_function_calls(response: Any) -> List[Dict[str, Any]]:
    """Extract ordered function_call parts from a Gemini response."""
    calls: List[Dict[str, Any]] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return calls
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if not fc:
                continue
            name = getattr(fc, "name", None) or ""
            args = getattr(fc, "args", None)
            if hasattr(args, "items"):
                # MapComposite / protobuf Struct-like
                try:
                    args_dict = {str(k): _proto_value_to_python(v) for k, v in args.items()}
                except Exception:
                    try:
                        args_dict = {str(k): _proto_value_to_python(v) for k, v in dict(args).items()}
                    except Exception:
                        args_dict = {}
            elif isinstance(args, dict):
                args_dict = {str(k): _proto_value_to_python(v) for k, v in args.items()}
            else:
                args_dict = {}
            # Final pass: ensure nested values are JSON-serializable
            args_dict = _proto_value_to_python(args_dict)
            if not isinstance(args_dict, dict):
                args_dict = {}
            if name:
                calls.append({"name": str(name), "args": args_dict, "raw_part": part})
    except Exception:
        return calls
    return calls


def _proto_value_to_python(value: Any) -> Any:
    """Coerce Gemini protobuf / MapComposite / RepeatedComposite values to JSON-safe Python."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _proto_value_to_python(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_proto_value_to_python(v) for v in value]
    if hasattr(value, "items"):
        try:
            return {str(k): _proto_value_to_python(v) for k, v in value.items()}
        except Exception:
            pass
    type_name = type(value).__name__
    # protobuf RepeatedComposite / RepeatedScalarContainer / MapComposite
    if "Repeated" in type_name or type_name == "MapComposite":
        try:
            if hasattr(value, "items") and "Map" in type_name:
                return {str(k): _proto_value_to_python(v) for k, v in value.items()}
            return [_proto_value_to_python(v) for v in value]
        except Exception:
            pass
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return [_proto_value_to_python(v) for v in value]
        except Exception:
            pass
    # Scalar proto wrappers / leftover opaque objects
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def extract_text_parts(response: Any) -> str:
    """Concatenate text parts from a Gemini response (ignore function_call parts)."""
    texts: List[str] = []
    try:
        # Fast path may raise when only function_call parts exist
        try:
            t = response.text
            if isinstance(t, str) and t.strip():
                return t
        except Exception:
            pass
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            t = getattr(part, "text", None)
            if isinstance(t, str) and t:
                texts.append(t)
    except Exception:
        return ""
    return "\n".join(texts)


def model_content_from_response(response: Any):
    """Return the model Content from the first candidate, or None."""
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        return getattr(candidates[0], "content", None)
    except Exception:
        return None


def truncate_tool_result_for_model(
    result: Any,
    *,
    max_chars: int = DEFAULT_MAX_RESPONSE_CHARS,
    body_field_max: int = BODY_FIELD_MAX_CHARS,
) -> Dict[str, Any]:
    """Shrink tool results before embedding in FunctionResponse."""
    if not isinstance(result, dict):
        text = str(result)
        if len(text) > max_chars:
            return {"success": False, "truncated": True, "preview": text[:max_chars]}
        try:
            return json.loads(text) if text.strip().startswith("{") else {"result": text}
        except Exception:
            return {"result": text[:max_chars]}

    out = dict(result)
    for key in ("response_body", "request_body", "responseBody", "requestBody"):
        if key in out and isinstance(out[key], str) and len(out[key]) > body_field_max:
            out[key] = out[key][:body_field_max] + f"\n...[truncated {len(result[key]) - body_field_max} chars]"
            out["truncated"] = True

    # Truncate compare_sessions nested bodies
    sessions = out.get("sessions")
    if isinstance(sessions, list):
        trimmed = []
        for item in sessions:
            if isinstance(item, dict):
                trimmed.append(
                    truncate_tool_result_for_model(item, max_chars=max_chars // 2, body_field_max=body_field_max // 2)
                )
            else:
                trimmed.append(item)
        out["sessions"] = trimmed

    # Drop huge auto-fetch previews if present as nested full copies
    follow = out.get("_follow_up")
    if isinstance(follow, dict) and "session_body_preview" in follow:
        preview = follow["session_body_preview"]
        if isinstance(preview, dict):
            follow = dict(follow)
            follow["session_body_preview"] = truncate_tool_result_for_model(
                preview, max_chars=max_chars // 2, body_field_max=body_field_max // 2
            )
            out["_follow_up"] = follow

    encoded = json.dumps(out, default=str)
    if len(encoded) > max_chars:
        return {
            "success": out.get("success", True),
            "truncated": True,
            "session_id": out.get("session_id") or out.get("id"),
            "host": out.get("host"),
            "ekfiddle_comment": out.get("ekfiddle_comment"),
            "content_type": out.get("content_type"),
            "message": f"Result truncated from {len(encoded)} chars for model context",
            "preview": encoded[: max_chars // 2],
        }
    return out


def build_function_response_part(name: str, result: Dict[str, Any]):
    """Build a Gemini Part carrying a FunctionResponse."""
    from google.generativeai import protos

    safe = truncate_tool_result_for_model(result)
    # FunctionResponse.response must be a Struct-compatible mapping
    return protos.Part(
        function_response=protos.FunctionResponse(
            name=name,
            response=safe if isinstance(safe, dict) else {"result": safe},
        )
    )


def tool_config(mode: str = "AUTO", allowed_function_names: Optional[List[str]] = None):
    """Build ToolConfig for AUTO / NONE / ANY function calling modes."""
    from google.generativeai import protos

    mode_map = {
        "AUTO": protos.FunctionCallingConfig.Mode.AUTO,
        "NONE": protos.FunctionCallingConfig.Mode.NONE,
        "ANY": protos.FunctionCallingConfig.Mode.ANY,
    }
    fc = protos.FunctionCallingConfig(mode=mode_map.get(mode.upper(), protos.FunctionCallingConfig.Mode.AUTO))
    if allowed_function_names and mode.upper() == "ANY":
        fc.allowed_function_names.extend(allowed_function_names)
    return protos.ToolConfig(function_calling_config=fc)


def investigation_system_instruction(max_followups: int = 20) -> str:
    """Stable system instruction for native tool-calling investigations."""
    from llm_prompts import investigation_system_instruction as _shared
    return _shared(max_followups)
