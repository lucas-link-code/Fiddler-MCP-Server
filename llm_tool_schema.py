#!/usr/bin/env python3
"""Shared MCP JSON Schema normalization for Gemini and OpenAI-compatible tool bindings."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def normalize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reduce MCP JSON Schema to a subset accepted by Gemini and OpenAI tools."""
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
        return out

    cleaned = walk(schema)
    if cleaned.get("type") != "object":
        cleaned = {
            "type": "object",
            "properties": cleaned.get("properties") or {},
            "required": cleaned.get("required", []),
        }
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    return cleaned


def mcp_tools_to_openai_tools(available_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tools/list entries to OpenAI/DeepSeek tools array."""
    tools: List[Dict[str, Any]] = []
    for tool in available_tools or []:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        description = (tool.get("description") or "").strip()
        if len(description) > 1024:
            description = description[:1000].rstrip() + "..."
        raw = tool.get("inputSchema") or tool.get("input_schema") or {
            "type": "object",
            "properties": {},
        }
        parameters = normalize_json_schema(raw if isinstance(raw, dict) else {})
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description or f"MCP tool {name}",
                    "parameters": parameters,
                },
            }
        )
    return tools
