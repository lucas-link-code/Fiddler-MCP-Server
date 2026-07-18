#!/usr/bin/env python3
"""LLM provider Protocol for Fiddler MCP native tool loops."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple


ToolCall = Dict[str, Any]  # {name, args, id?}


class LLMProvider(Protocol):
    """Provider interface used by the native chat loop."""

    name: str
    display_label: str

    def bind_tools(self, mcp_tools: List[Dict[str, Any]], system_instruction: str) -> bool:
        ...

    def tools_bound(self) -> bool:
        ...

    def start_conversation(self, user_text: str) -> Any:
        ...

    def generate(self, conversation: Any, tool_choice: str = "auto") -> Any:
        """tool_choice: auto | none"""
        ...

    def extract_tool_calls(self, response: Any) -> List[ToolCall]:
        ...

    def extract_text(self, response: Any) -> str:
        ...

    def append_model_turn(
        self,
        conversation: Any,
        response: Any,
        calls: List[ToolCall],
        text: str,
    ) -> None:
        ...

    def append_tool_results(
        self,
        conversation: Any,
        executed: List[Tuple[str, Dict[str, Any], Dict[str, Any], Optional[str]]],
        nudge: str,
    ) -> None:
        """executed items: (name, args, result, tool_call_id)."""
        ...

    def append_user_text(self, conversation: Any, text: str) -> None:
        ...

    def change_model(self, model_name: str) -> None:
        ...
