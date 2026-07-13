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
    if not schema or not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        out: Dict[str, Any] = {}
        typ = node.get("type")
        if typ:
            out["type"] = typ
        if "description" in node and isinstance(node["description"], str):
            out["description"] = node["description"]
        if "enum" in node and isinstance(node["enum"], list):
            out["enum"] = node["enum"]
        if "properties" in node and isinstance(node["properties"], dict):
            out["properties"] = {k: walk(v) for k, v in node["properties"].items()}
        if "required" in node and isinstance(node["required"], list):
            out["required"] = [str(x) for x in node["required"]]
        if "items" in node:
            out["items"] = walk(node["items"])
        # Drop unsupported keywords: anyOf, oneOf, allOf, $ref, additionalProperties, etc.
        return out

    cleaned = walk(schema)
    if cleaned.get("type") != "object":
        cleaned = {"type": "object", "properties": cleaned.get("properties") or {}, "required": cleaned.get("required", [])}
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    return cleaned


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
                    args_dict = {k: _proto_value_to_python(v) for k, v in args.items()}
                except Exception:
                    args_dict = dict(args)
            elif isinstance(args, dict):
                args_dict = args
            else:
                args_dict = {}
            if name:
                calls.append({"name": str(name), "args": args_dict, "raw_part": part})
    except Exception:
        return calls
    return calls


def _proto_value_to_python(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_proto_value_to_python(v) for v in value]
    if hasattr(value, "items"):
        try:
            return {k: _proto_value_to_python(v) for k, v in value.items()}
        except Exception:
            pass
    return value


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
    return f"""You are a senior malware analyst investigating live Fiddler HTTP captures via MCP tools.

You have native function calling for Fiddler tools. Call tools when you need traffic data. Do not invent tool names or arguments outside the declared schemas.

SECURITY ANALYSIS FRAMEWORK:
- IOC-FIRST: when the user names hosts, search those hosts with host_pattern before Low EKFiddle HTML
- Critical/High EKFiddle first; Low External Script Monitor last unless the user asks for it
- ZERO-HIT BUDGET: if the user lists many IOC hosts, search at most 1 or 2 missing hosts. After the first zero-hit, STOP serial host hunting. Report which hosts are absent from the buffer and continue from session bodies or prior findings already in this conversation
- Never invent domains, IPs, cookies, or function names absent from tool results or the user query
- Do not re-fetch session bodies already analyzed in this query unless the user explicitly asks to re-fetch
- Prefer fiddler_mcp__compare_sessions when the user asks to compare 2 to 10 sessions
- Focus on BEHAVIOR in JavaScript bodies over string dumps
- If MCP tools fail or the server is down, answer from prior conversation evidence. Do not claim you cannot explain an infection chain when bodies were already analyzed earlier in this chat
- Low External Script Monitor does not mean benign. Elevate when SourceCode shows eth_call, RPC C2, clipboard hijack, fullscreen overlay, or etherhiding patterns

EKFIDDLE RULE AUTHORING HARD MODE when user asks for EKFiddle rules, CustomRegexes, or signatures:

FORMAT exact tab-separated CustomRegexes lines, TABS not spaces:
Type	Severity: Rule Name	Regex	Optional Comment
Types: SourceCode | URI | IP | Headers | Hash
Severity MUST be High: or Med: or Low: including the colon. Never write Medium:

NAMING: threat-specific title case with spaces. Include family or actor when known.
Good: High: ErrTraffic Polygon eth_call RPC
Good: High: EtherHiding Fullscreen Overlay
Bad: High: Potential Ethereum eth_call
Bad: Medium: Obfuscated Function Names
Bad: High: ErrTraffic_Clickfix_EthCall_Function  underscore snake_case names

QUALITY BAR for regexes:
- Compound high-signal tokens. Prefer method:'eth_call' with jsonrpc nearby, not bare \\beth_call\\b
- Bounded quantifiers like {{0,120}} or [^}}]{{1,200}}. Avoid unbounded .* and .+
- Escape literals: \\. \\( \\) \\[ \\] \\/
- Use non-capturing groups (?:...) and word boundaries \\b where needed so eval does not match reveal
- Prefer distinctive literals from the body: eth_call JSON-RPC shape, AbortSignal.timeout near POST fetch, z-index:2147483647 with position:fixed, clipboard-write allow, distinctive cookies, distinctive URI paths
- FORBIDDEN generic FP bait unless user explicitly asks: bare eth_call alone, _\\w{{7,8}}\\(\\), MutationObserver lazyload NitroPack ___mnag text/lazyload, createElement alone, appendChild alone, Function alone
- Do not overfit to one hex function name like _128a8a20 unless you also emit a generalized sibling rule for the same technique
- URI rules only for domains or paths observed in tool results or explicitly supplied by the user. Escape dots
- Keep 2 to 6 strong rules. Prefer fewer precise rules over many weak ones

EXPLANATIONS: for each rule write a short paragraph that includes The crucial pattern or The key pattern. Then end with a plain block of ONLY the tab-separated rule lines for copy into CustomRegexes.txt. Then STOP. No more tool calls. No markdown tables. No Name/Regex/Comment/Color. No slash-wrapped /regex/i.

INFECTION CHAIN REQUESTS: when the user asks for the infection flow, explain stages from evidence: landing or infected page, injected SourceCode behavior, RPC or C2 discovery, payload or redirect hosts, overlay or clickfix delivery. Use prior body findings if present. Do not burn the tool budget re-searching every IOC domain that already returned 0.

WORKFLOW:
- Prefer fiddler_mcp__ekfiddle_threats or fiddler_mcp__ekfiddle_sessions for triage
- Use fiddler_mcp__sessions_search for host/url/content_type hunts
- Use fiddler_mcp__session_body for deep analysis
- Use fiddler_mcp__compare_sessions when user asks to compare 2 to 10 sessions
- You may make up to {max_followups} tool calls per user query; stop early when you can answer
- When finished, answer in clear analyst prose without emitting tool JSON text
"""
