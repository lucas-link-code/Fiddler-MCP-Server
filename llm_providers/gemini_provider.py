#!/usr/bin/env python3
"""Gemini native tool provider wrapping gemini_native_tools helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import gemini_native_tools as native


class GeminiProvider:
    name = "gemini"
    display_label = "Gemini"

    def __init__(self, api_key: str, model_name: str):
        import google.generativeai as genai

        self._genai = genai
        self.api_key = api_key
        self.model_name = model_name
        self._tool = None
        self._system_instruction = ""
        self.model = None
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def bind_tools(self, mcp_tools: List[Dict[str, Any]], system_instruction: str) -> bool:
        self._system_instruction = system_instruction
        tool, errors = native.build_gemini_tool(mcp_tools)
        self._bind_errors = errors
        if not tool:
            self._tool = None
            self.model = self._genai.GenerativeModel(self.model_name)
            return False
        self._tool = tool
        self.model = self._genai.GenerativeModel(
            self.model_name,
            tools=[tool],
            system_instruction=system_instruction,
        )
        return True

    @property
    def bind_errors(self) -> List[str]:
        return getattr(self, "_bind_errors", []) or []

    def tools_bound(self) -> bool:
        return self._tool is not None

    def bound_tool_names(self) -> List[str]:
        if not self._tool:
            return []
        return [d.name for d in (self._tool.function_declarations or [])]

    def start_conversation(self, user_text: str) -> Any:
        from google.generativeai import protos

        return [protos.Content(role="user", parts=[protos.Part(text=user_text)])]

    def generate(self, conversation: Any, tool_choice: str = "auto") -> Any:
        mode = "NONE" if str(tool_choice).lower() == "none" else "AUTO"
        return self.model.generate_content(
            conversation,
            tool_config=native.tool_config(mode),
        )

    def extract_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        return native.extract_function_calls(response)

    def extract_text(self, response: Any) -> str:
        return native.extract_text_parts(response)

    def append_model_turn(
        self,
        conversation: Any,
        response: Any,
        calls: List[Dict[str, Any]],
        text: str,
    ) -> None:
        from google.generativeai import protos

        model_content = native.model_content_from_response(response)
        if model_content is not None:
            conversation.append(model_content)
            return
        parts = []
        for c in calls:
            parts.append(
                protos.Part(
                    function_call=protos.FunctionCall(
                        name=c["name"],
                        args=c.get("args") or {},
                    )
                )
            )
        if text:
            parts.insert(0, protos.Part(text=text))
        conversation.append(protos.Content(role="model", parts=parts))

    def append_tool_results(
        self,
        conversation: Any,
        executed: List[Tuple[str, Dict[str, Any], Dict[str, Any], Optional[str]]],
        nudge: str,
    ) -> None:
        from google.generativeai import protos

        response_parts = []
        for name, _args, result, _tid in executed:
            response_parts.append(native.build_function_response_part(name, result))
        response_parts.append(protos.Part(text=nudge))
        conversation.append(protos.Content(role="user", parts=response_parts))

    def append_user_text(self, conversation: Any, text: str) -> None:
        from google.generativeai import protos

        conversation.append(protos.Content(role="user", parts=[protos.Part(text=text)]))

    def change_model(self, model_name: str) -> None:
        self.model_name = model_name
        if self._tool and self._system_instruction:
            self.model = self._genai.GenerativeModel(
                model_name,
                tools=[self._tool],
                system_instruction=self._system_instruction,
            )
        else:
            self.model = self._genai.GenerativeModel(model_name)
