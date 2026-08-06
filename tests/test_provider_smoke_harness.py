#!/usr/bin/env python3
"""Offline smoke harness across Gemini, DeepSeek, and OpenRouter provider paths."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_module(name: str, filename: str):
    path = os.path.join(ROOT, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if "google" not in sys.modules:
    google_mod = types.ModuleType("google")
    sys.modules["google"] = google_mod
else:
    google_mod = sys.modules["google"]

genai_mod = types.ModuleType("google.generativeai")
genai_mod.configure = MagicMock()
genai_mod.GenerativeModel = MagicMock(return_value=MagicMock())
google_mod.generativeai = genai_mod
sys.modules["google.generativeai"] = genai_mod
types_mod = types.ModuleType("google.generativeai.types")


class _FakeFD:
    def __init__(self, name, description, parameters):
        self.name = name
        self.description = description
        self.parameters = parameters


class _FakeTool:
    def __init__(self, function_declarations):
        self.function_declarations = function_declarations


types_mod.FunctionDeclaration = _FakeFD
types_mod.Tool = _FakeTool
sys.modules["google.generativeai.types"] = types_mod
protos_mod = types.ModuleType("google.generativeai.protos")
protos_mod.Content = MagicMock()
protos_mod.Part = MagicMock()
sys.modules["google.generativeai.protos"] = protos_mod
genai_mod.protos = protos_mod
genai_mod.types = types_mod

gemini = _load_module("gemini_client_smoke_mod", "gemini-fiddler-client.py")

SAMPLE_TOOLS = [
    {
        "name": "fiddler_mcp__live_stats",
        "description": "stats",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class FakeProvider:
    def __init__(self, label: str):
        self.display_label = label
        self._bound = False
        self._tools = []

    def bind_tools(self, mcp_tools, system_instruction):
        self._tools = list(mcp_tools or [])
        self._system_instruction = system_instruction
        self._bound = bool(self._tools)
        return self._bound

    def tools_bound(self):
        return self._bound

    def bound_tool_names(self):
        return [t.get("name") for t in self._tools if t.get("name")]

    def start_conversation(self, user_text):
        return [{"role": "user", "content": user_text}]

    def generate(self, conversation, tool_choice="auto"):
        return {"calls": [], "text": f"{self.display_label} ok"}

    def extract_tool_calls(self, response):
        return list(response.get("calls") or [])

    def extract_text(self, response):
        return response.get("text") or ""

    def append_model_turn(self, conversation, response, calls, text):
        conversation.append({"role": "assistant", "content": text})

    def append_tool_results(self, conversation, executed, nudge):
        pass

    def append_user_text(self, conversation, text):
        conversation.append({"role": "user", "content": text})


class TestProviderSmokeHarness(unittest.TestCase):
    def test_default_gemini_provider(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        self.assertEqual(client.provider_name, "gemini")
        self.assertEqual(client.model_name, "gemini-3-flash-preview")

    def test_switch_deepseek_and_openrouter_and_back(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.deepseek_api_key = "sk-ds"
        client.openrouter_api_key = "sk-or"
        client.available_tools = SAMPLE_TOOLS
        client.log_with_timestamp = MagicMock()

        with patch.object(gemini, "merge_save_config", return_value=Path("gemini-fiddler-config.json")):
            client.change_model("12")
            self.assertEqual(client.provider_name, "deepseek")
            self.assertTrue(client.llm_provider.tools_bound())

            client.change_model("14")
            self.assertEqual(client.provider_name, "openrouter")
            self.assertEqual(client.model_name, "z-ai/glm-5.2")
            self.assertTrue(client.llm_provider.tools_bound())

            client.change_model("1")
            self.assertEqual(client.provider_name, "gemini")

    def test_chat_native_smoke_per_provider_label(self):
        for label, provider_name in (
            ("Gemini", "gemini"),
            ("DeepSeek", "deepseek"),
            ("OpenRouter", "openrouter"),
        ):
            client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
            client.use_native_tools = True
            client._gemini_tool = True
            client.provider_name = provider_name
            client.max_followups = 3
            client.show_progress = False
            client.conversation_history = []
            client._analyzed_session_ids = set()
            client._last_search_args = {}
            client._current_user_query = "hi"
            client._interrupt_requested = False
            client.use_rich = False
            client.console = None
            client.log_with_timestamp = MagicMock()
            client.clear_interrupt = MagicMock()
            client._check_interrupt = MagicMock()
            client._format_recent_history = MagicMock(return_value="")
            client._analyzed_sessions_note = MagicMock(return_value="No sessions")
            client.maybe_persist_ekfiddle_rules = MagicMock(return_value=[])
            client._finalize_assistant_response = lambda t: t
            client.parse_gemini_response = MagicMock(return_value=None)
            client.call_tool = MagicMock(return_value={"success": True})
            client.llm_provider = FakeProvider(label)
            client.llm_provider.bind_tools(SAMPLE_TOOLS, "sys INVESTIGATE CAPTURE EKFIDDLE")
            out = client._chat_native("hi")
            self.assertIn("ok", out)

    def test_investigate_prompt_unchanged(self):
        prompt = gemini.GeminiFiddlerClient.build_investigate_prompt("evil.test")
        self.assertIn("evil.test", prompt)
        self.assertIn("INVESTIGATE CAPTURE", prompt)
        self.assertIn("ekfiddle", prompt.lower())


if __name__ == "__main__":
    unittest.main()
