#!/usr/bin/env python3
"""Unit tests for OpenRouter OpenAI-compatible native tool provider and client wiring."""
from __future__ import annotations

import importlib.util
import json
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
genai_mod.GenerativeModel = MagicMock()
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

gemini = _load_module("gemini_client_or_mod", "gemini-fiddler-client.py")

ALL_TEN_TOOLS = [
    {
        "name": "fiddler_mcp__live_sessions",
        "description": "List live sessions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "host_filter": {"type": "string"},
                "suspicious_only": {"type": "boolean"},
            },
        },
    },
    {
        "name": "fiddler_mcp__sessions_search",
        "description": "Search sessions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_pattern": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "fiddler_mcp__session_headers",
        "description": "Session headers",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "fiddler_mcp__session_body",
        "description": "Session body",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "smart_extract": {"type": "boolean"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "fiddler_mcp__compare_sessions",
        "description": "Compare sessions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["session_ids"],
        },
    },
    {
        "name": "fiddler_mcp__live_stats",
        "description": "Bridge stats",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fiddler_mcp__sessions_timeline",
        "description": "Timeline",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_by": {"type": "string", "enum": ["minute", "host", "status"]},
            },
        },
    },
    {
        "name": "fiddler_mcp__sessions_clear",
        "description": "Clear buffer",
        "inputSchema": {
            "type": "object",
            "properties": {"confirm": {"type": "boolean"}},
            "required": ["confirm"],
        },
    },
    {
        "name": "fiddler_mcp__ekfiddle_sessions",
        "description": "EKFiddle sessions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threat_level": {
                    "type": "string",
                    "enum": ["all", "critical", "high", "medium", "low"],
                },
            },
        },
    },
    {
        "name": "fiddler_mcp__ekfiddle_threats",
        "description": "EKFiddle threats",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_risk_score": {"type": "number"},
                "time_range_minutes": {"type": "integer"},
            },
        },
    },
]


class TestOpenAIToolSchema(unittest.TestCase):
    def test_all_ten_tools_convert(self):
        from llm_tool_schema import mcp_tools_to_openai_tools

        tools = mcp_tools_to_openai_tools(ALL_TEN_TOOLS)
        self.assertEqual(len(tools), 10)
        body = next(t for t in tools if t["function"]["name"] == "fiddler_mcp__session_body")
        self.assertIn("session_id", body["function"]["parameters"]["required"])


class TestOpenRouterProviderParse(unittest.TestCase):
    def test_extract_tool_calls_json_string_args(self):
        with patch("openai.OpenAI") as OpenAI, patch("httpx.Client"):
            OpenAI.return_value = MagicMock()
            from llm_providers.openrouter_provider import OpenRouterProvider

            provider = OpenRouterProvider(api_key="sk-or-test", model_name="z-ai/glm-5.2")
            fn = types.SimpleNamespace(
                name="fiddler_mcp__ekfiddle_threats",
                arguments='{"min_risk_score": 0.7, "time_range_minutes": 60}',
            )
            tc = types.SimpleNamespace(id="call_abc", function=fn)
            msg = types.SimpleNamespace(tool_calls=[tc], content=None)
            resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
            calls = provider.extract_tool_calls(resp)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["name"], "fiddler_mcp__ekfiddle_threats")
            self.assertEqual(calls[0]["args"]["min_risk_score"], 0.7)

    def test_tool_choice_none_omits_tools(self):
        with patch("openai.OpenAI") as OpenAI, patch("httpx.Client"):
            client = MagicMock()
            OpenAI.return_value = client
            from llm_providers.openrouter_provider import OpenRouterProvider

            provider = OpenRouterProvider(api_key="sk-or-test")
            provider.bind_tools(ALL_TEN_TOOLS, "sys")
            provider.generate([{"role": "user", "content": "hi"}], tool_choice="none")
            kwargs = client.chat.completions.create.call_args.kwargs
            self.assertNotIn("tools", kwargs)
            provider.generate([{"role": "user", "content": "hi"}], tool_choice="auto")
            kwargs2 = client.chat.completions.create.call_args.kwargs
            self.assertIn("tools", kwargs2)
            self.assertEqual(len(kwargs2["tools"]), 10)


class TestOpenRouterNativeLoop(unittest.TestCase):
    def _make_client(self, max_followups=5):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client.use_native_tools = True
        client._gemini_tool = True
        client.provider_name = "openrouter"
        client.max_followups = max_followups
        client.show_progress = False
        client.conversation_history = []
        client._analyzed_session_ids = set()
        client._last_search_args = {}
        client._current_user_query = "investigate"
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
        return client

    def test_sequential_and_budget_synthesis(self):
        client = self._make_client(max_followups=1)
        order = []

        def fake_call(name, args):
            order.append(name)
            return {"success": True, "tool": name}

        client.call_tool = fake_call
        tool_choices = []

        class FakeOpenRouter:
            display_label = "OpenRouter"

            def tools_bound(self):
                return True

            def start_conversation(self, user_text):
                return [{"role": "system", "content": "sys"}, {"role": "user", "content": user_text}]

            def generate(self, conversation, tool_choice="auto"):
                tool_choices.append(tool_choice)
                return self._queue.pop(0)

            def extract_tool_calls(self, response):
                return list(response.get("calls") or [])

            def extract_text(self, response):
                return response.get("text") or ""

            def append_model_turn(self, conversation, response, calls, text):
                conversation.append({"role": "assistant"})

            def append_tool_results(self, conversation, executed, nudge):
                conversation.append({"role": "tool"})

            def append_user_text(self, conversation, text):
                conversation.append({"role": "user", "content": text})

        provider = FakeOpenRouter()
        provider._queue = [
            {
                "calls": [
                    {"name": "fiddler_mcp__ekfiddle_threats", "args": {}, "id": "1"},
                ],
                "text": "",
            },
            {"calls": [], "text": "final after budget"},
        ]
        client.llm_provider = provider
        out = client._chat_native("investigate buffer")
        self.assertEqual(order, ["fiddler_mcp__ekfiddle_threats"])
        self.assertIn("final after budget", out)
        self.assertEqual(tool_choices, ["auto", "none"])


class TestProviderResolution(unittest.TestCase):
    def test_provider_for_model_routing(self):
        self.assertEqual(gemini.provider_for_model("gemini-3-flash-preview"), "gemini")
        self.assertEqual(gemini.provider_for_model("deepseek-v4-pro"), "deepseek")
        self.assertEqual(gemini.provider_for_model("deepseek-v4-flash"), "deepseek")
        self.assertEqual(gemini.provider_for_model("deepseek/deepseek-v4-pro"), "openrouter")
        self.assertEqual(gemini.provider_for_model("deepseek/deepseek-v4-flash"), "openrouter")
        self.assertEqual(gemini.provider_for_model("z-ai/glm-5.2"), "openrouter")
        self.assertEqual(gemini.provider_for_model("qwen/qwen3.8-max"), "openrouter")
        self.assertEqual(gemini.provider_for_model("moonshotai/kimi-k3"), "openrouter")

    def test_resolve_model_identifier(self):
        self.assertEqual(gemini.resolve_model_identifier("14"), "z-ai/glm-5.2")
        self.assertEqual(gemini.resolve_model_identifier("16"), "deepseek/deepseek-v4-pro")
        self.assertEqual(gemini.resolve_model_identifier("12"), "deepseek-v4-flash")
        self.assertEqual(gemini.resolve_model_identifier("z-ai/glm-5.2"), "z-ai/glm-5.2")
        self.assertEqual(
            gemini.resolve_model_identifier("anthropic/claude-sonnet-4"),
            "anthropic/claude-sonnet-4",
        )
        self.assertIsNone(gemini.resolve_model_identifier("nope"))

    def test_openrouter_init_requires_key(self):
        with self.assertRaises(RuntimeError):
            gemini.GeminiFiddlerClient(
                api_key="",
                model_name="z-ai/glm-5.2",
                provider="openrouter",
                openrouter_api_key="",
            )

    def test_openrouter_forces_native_even_when_env_off(self):
        with patch.dict(os.environ, {"GEMINI_NATIVE_TOOLS": "0"}, clear=False):
            client = gemini.GeminiFiddlerClient(
                api_key="gk",
                provider="openrouter",
                openrouter_api_key="sk-or",
                model_name="z-ai/glm-5.2",
            )
        self.assertEqual(client.provider_name, "openrouter")
        self.assertTrue(client.use_native_tools)

    def test_change_model_to_openrouter_without_key_cancels(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.openrouter_api_key = ""
        client.available_tools = ALL_TEN_TOOLS
        with patch.object(client, "prompt_and_save_openrouter_api_key", return_value=False):
            client.change_model("14")
        self.assertEqual(client.provider_name, "gemini")
        self.assertEqual(client.model_name, "gemini-3-flash-preview")

    def test_change_model_prompts_and_saves_openrouter_key(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.openrouter_api_key = ""
        client.available_tools = ALL_TEN_TOOLS[:1]
        client.log_with_timestamp = MagicMock()

        def fake_prompt():
            client.openrouter_api_key = "sk-or-test"
            return True

        with patch.object(client, "prompt_and_save_openrouter_api_key", side_effect=fake_prompt):
            with patch.object(gemini, "merge_save_config", return_value=Path("gemini-fiddler-config.json")):
                client.change_model("14")
        self.assertEqual(client.provider_name, "openrouter")
        self.assertEqual(client.model_name, "z-ai/glm-5.2")
        self.assertEqual(client.openrouter_api_key, "sk-or-test")

    def test_direct_deepseek_still_distinct_from_openrouter(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.deepseek_api_key = "sk-ds"
        client.openrouter_api_key = "sk-or"
        client.available_tools = ALL_TEN_TOOLS[:1]
        client.log_with_timestamp = MagicMock()
        with patch.object(gemini, "merge_save_config", return_value=Path("gemini-fiddler-config.json")):
            client.change_model("12")
            self.assertEqual(client.provider_name, "deepseek")
            self.assertEqual(client.model_name, "deepseek-v4-flash")
            client.change_model("15")
            self.assertEqual(client.provider_name, "openrouter")
            self.assertEqual(client.model_name, "deepseek/deepseek-v4-flash")

    def test_openrouter_system_has_investigate_sections(self):
        import llm_prompts

        text = llm_prompts.investigation_system_instruction(20)
        self.assertIn("INVESTIGATE CAPTURE", text)
        self.assertIn("EKFIDDLE RULE AUTHORING", text)
        with patch("openai.OpenAI") as OpenAI, patch("httpx.Client"):
            OpenAI.return_value = MagicMock()
            from llm_providers.openrouter_provider import OpenRouterProvider

            p = OpenRouterProvider(api_key="sk-or")
            ok = p.bind_tools(ALL_TEN_TOOLS, text)
            self.assertTrue(ok)
            messages = p.start_conversation("go")
            self.assertEqual(messages[0]["role"], "system")
            self.assertIn("INVESTIGATE CAPTURE", messages[0]["content"])

    def test_load_config_openrouter_env(self):
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "sk-or",
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_MODEL": "qwen/qwen3.8-max",
            },
            clear=False,
        ):
            with patch("pathlib.Path.exists", return_value=False):
                cfg = gemini.load_config()
        self.assertEqual(cfg.get("openrouter_api_key"), "sk-or")
        self.assertEqual(cfg.get("provider"), "openrouter")
        self.assertEqual(cfg.get("model"), "qwen/qwen3.8-max")


if __name__ == "__main__":
    unittest.main()
