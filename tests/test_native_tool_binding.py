#!/usr/bin/env python3
"""Tests for native Gemini tool schema binding and Phase 0 bridge/schema fixes."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
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

# Stub nested types used by gemini_native_tools
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

class _Mode:
    AUTO = 1
    NONE = 2
    ANY = 3

class _FCC:
    Mode = _Mode
    def __init__(self, mode=None):
        self.mode = mode
        self.allowed_function_names = []

class _ToolConfig:
    def __init__(self, function_calling_config=None):
        self.function_calling_config = function_calling_config

class _Part:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class _FR:
    def __init__(self, name=None, response=None):
        self.name = name
        self.response = response

class _FC:
    def __init__(self, name=None, args=None):
        self.name = name
        self.args = args or {}

class _Content:
    def __init__(self, role=None, parts=None):
        self.role = role
        self.parts = parts or []

protos_mod.FunctionCallingConfig = _FCC
protos_mod.ToolConfig = _ToolConfig
protos_mod.Part = _Part
protos_mod.FunctionResponse = _FR
protos_mod.FunctionCall = _FC
protos_mod.Content = _Content
sys.modules["google.generativeai.protos"] = protos_mod
genai_mod.protos = protos_mod
genai_mod.types = types_mod

for pkg in ("flask", "requests"):
    if pkg not in sys.modules:
        try:
            __import__(pkg)
        except ImportError:
            sys.modules[pkg] = MagicMock()

native = _load_module("gemini_native_tools_mod", "gemini_native_tools.py")
enhanced = _load_module("enhanced_bridge_mod", "enhanced-bridge.py")
fiveire = _load_module("fiveire_bridge_mod", "5ire-bridge.py")
gemini = _load_module("gemini_client_mod", "gemini-fiddler-client.py")


SAMPLE_TOOLS = [
    {
        "name": "fiddler_mcp__live_stats",
        "description": "Bridge health",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fiddler_mcp__session_body",
        "description": "Fetch body",
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
        "name": "fiddler_mcp__sessions_search",
        "description": "Search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_pattern": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST"]},
            },
        },
    },
    {
        "name": "fiddler_mcp__sessions_timeline",
        "description": "Timeline",
        "inputSchema": {
            "type": "object",
            "properties": {
                "time_range_minutes": {"type": "integer"},
                "group_by": {"type": "string", "enum": ["minute", "host"]},
                "include_details": {"type": "boolean"},
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


class TestSchemaConverter(unittest.TestCase):
    def test_valid_names(self):
        self.assertTrue(native.is_valid_gemini_function_name("fiddler_mcp__session_body"))
        self.assertFalse(native.is_valid_gemini_function_name("bad name"))
        self.assertFalse(native.is_valid_gemini_function_name(""))

    def test_converter_required_and_enum(self):
        decl = native.mcp_tool_to_function_declaration(SAMPLE_TOOLS[1])
        self.assertEqual(decl.name, "fiddler_mcp__session_body")
        self.assertIn("session_id", decl.parameters.get("required", []))
        search = native.mcp_tool_to_function_declaration(SAMPLE_TOOLS[2])
        method = search.parameters["properties"]["method"]
        self.assertEqual(method.get("enum"), ["GET", "POST"])

    def test_no_params_tool(self):
        decl = native.mcp_tool_to_function_declaration(SAMPLE_TOOLS[0])
        self.assertEqual(decl.parameters.get("type"), "object")

    def test_strips_unsupported_schema_keys(self):
        tool = {
            "name": "fiddler_mcp__live_stats",
            "description": "x",
            "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
                "anyOf": [{"type": "object"}],
            },
        }
        decl = native.mcp_tool_to_function_declaration(tool)
        self.assertNotIn("anyOf", decl.parameters)
        self.assertNotIn("additionalProperties", decl.parameters)

    def test_build_tool(self):
        tool, errors = native.build_gemini_tool(SAMPLE_TOOLS)
        self.assertIsNotNone(tool)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(tool.function_declarations), len(SAMPLE_TOOLS))


class TestExtractFunctionCalls(unittest.TestCase):
    def test_extract_ordered_calls(self):
        part1 = types.SimpleNamespace(function_call=types.SimpleNamespace(name="fiddler_mcp__live_stats", args={}), text=None)
        part2 = types.SimpleNamespace(
            function_call=types.SimpleNamespace(name="fiddler_mcp__session_body", args={"session_id": "256"}),
            text=None,
        )
        content = types.SimpleNamespace(parts=[part1, part2])
        cand = types.SimpleNamespace(content=content)
        resp = types.SimpleNamespace(candidates=[cand], text=None)
        calls = native.extract_function_calls(resp)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["name"], "fiddler_mcp__live_stats")
        self.assertEqual(calls[1]["args"]["session_id"], "256")


class TestTruncate(unittest.TestCase):
    def test_truncates_large_body(self):
        big = "x" * 50_000
        out = native.truncate_tool_result_for_model(
            {"success": True, "response_body": big, "session_id": "1"}
        )
        self.assertTrue(out.get("truncated"))
        self.assertLess(len(out["response_body"]), len(big))


class TestTimelineFilter(unittest.TestCase):
    def test_filter_sessions_time_window(self):
        import time as time_mod
        bridge = enhanced.EnhancedFiddlerRealtimeBridge.__new__(
            enhanced.EnhancedFiddlerRealtimeBridge
        )
        now = time_mod.time()
        sessions = [
            {"id": "old", "host": "a.com", "received_at": now - 7200},
            {"id": "new", "host": "b.com", "received_at": now - 60},
        ]
        filtered = bridge._filter_sessions(sessions, since_minutes=30)
        ids = [s["id"] for s in filtered]
        self.assertIn("new", ids)
        self.assertNotIn("old", ids)


class TestArgKeysAligned(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client._analyzed_session_ids = set()
        self.client._last_search_args = {}

    def test_timeline_maps_since_minutes(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_timeline",
            {"since_minutes": 45, "group_by": "minute"},
        )
        self.assertEqual(out.get("time_range_minutes"), 45)
        self.assertNotIn("since_minutes", out)

    def test_timeline_keeps_include_details(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_timeline",
            {"time_range_minutes": 30, "include_details": True, "filter_host": "x.com"},
        )
        self.assertTrue(out.get("include_details"))
        self.assertEqual(out.get("filter_host"), "x.com")

    def test_clear_keeps_clear_suspicious(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_clear",
            {"confirm": True, "clear_suspicious": True},
        )
        self.assertTrue(out.get("clear_suspicious"))
        self.assertTrue(out.get("confirm"))

    def test_ekfiddle_tool_keys_allowed(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__ekfiddle_threats",
            {"min_risk_score": 0.65, "time_range_minutes": 60},
        )
        self.assertEqual(out.get("min_risk_score"), 0.65)


class TestEkfiddleClientMethods(unittest.TestCase):
    def test_get_ekfiddle_sessions_normalizes(self):
        client = fiveire.FiddlerBridgeClient.__new__(fiveire.FiddlerBridgeClient)
        client.request = MagicMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "id": "99",
                        "host": "evil.test",
                        "url": "https://evil.test/",
                        "ekfiddleComments": "High: eval()",
                        "method": "GET",
                        "statusCode": 200,
                        "contentType": "text/html",
                    }
                ],
                "threats_found": 1,
                "time_range_minutes": 60,
                "threat_level_filter": "all",
            }
        )
        out = client.get_ekfiddle_sessions(limit=10, time_range_minutes=60, threat_level="all")
        self.assertTrue(out["success"])
        self.assertEqual(out["sessions"][0]["id"], "99")
        self.assertIn("High:", out["sessions"][0]["ekfiddle_comment"])

    def test_get_ekfiddle_threats(self):
        client = fiveire.FiddlerBridgeClient.__new__(fiveire.FiddlerBridgeClient)
        client.request = MagicMock(
            return_value={
                "success": True,
                "threats": [{"session_id": "1", "risk_score": 0.9}],
                "total_count": 1,
                "critical_sessions": [],
                "critical_count": 0,
                "time_range_minutes": 120,
                "min_risk_score": 0.7,
                "categories_searched": [],
            }
        )
        out = client.get_ekfiddle_threats(time_range_minutes=120, min_risk_score=0.7)
        self.assertTrue(out["success"])
        self.assertEqual(out["total_count"], 1)


class TestNativeChatHelpers(unittest.TestCase):
    def test_bind_rebuilds_model(self):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client.model_name = "gemini-3-flash-preview"
        client.max_followups = 20
        client.available_tools = SAMPLE_TOOLS
        client.use_native_tools = True
        client.log_with_timestamp = MagicMock()
        with patch.object(gemini.genai, "GenerativeModel", return_value=MagicMock()) as gm:
            ok = client.bind_gemini_tools()
            self.assertTrue(ok)
            self.assertIsNotNone(client._gemini_tool)
            gm.assert_called()
            kwargs = gm.call_args.kwargs
            self.assertIn("tools", kwargs)
            self.assertIn("system_instruction", kwargs)

    def test_system_instruction_has_ekfiddle(self):
        text = native.investigation_system_instruction(10)
        self.assertIn("EKFIDDLE RULE AUTHORING", text)
        self.assertIn("tab-separated", text)
        self.assertIn("Med:", text)
        self.assertIn("ZERO-HIT", text)
        self.assertIn("The crucial pattern", text)
        self.assertIn("Never write Medium:", text)


class TestNativeChatLoop(unittest.TestCase):
    def test_sequential_tool_execution_order(self):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client.use_native_tools = True
        client._gemini_tool = object()
        client.max_followups = 5
        client.show_progress = False
        client.conversation_history = []
        client._analyzed_session_ids = set()
        client._last_search_args = {}
        client._current_user_query = "stats then body"
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
        order = []

        def fake_call(name, args):
            order.append(name)
            return {"success": True, "tool": name}

        client.call_tool = fake_call

        # First response: two function calls; second: final text only
        call_parts = [
            types.SimpleNamespace(function_call=types.SimpleNamespace(name="fiddler_mcp__live_stats", args={}), text=None),
            types.SimpleNamespace(function_call=types.SimpleNamespace(name="fiddler_mcp__session_body", args={"session_id": "1"}), text=None),
        ]
        resp1 = types.SimpleNamespace(
            candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=call_parts))],
            text=None,
        )
        resp2 = types.SimpleNamespace(
            candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[types.SimpleNamespace(text="done", function_call=None)]))],
            text="done",
        )
        client.model = MagicMock()
        client.model.generate_content = MagicMock(side_effect=[resp1, resp2])

        out = client._chat_native("get stats then body of 1")
        self.assertEqual(order, ["fiddler_mcp__live_stats", "fiddler_mcp__session_body"])
        self.assertIn("done", out)
    def test_legacy_prompt_notes_native_preference(self):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client.available_tools = SAMPLE_TOOLS
        client.max_followups = 20
        client.conversation_history = []
        prompt = client.build_gemini_prompt("show sessions")
        self.assertIn("GEMINI_NATIVE_TOOLS", prompt)
        # Old verbose JSON examples removed
        self.assertNotIn('arguments": {{"limit": 50}}', prompt)


if __name__ == "__main__":
    unittest.main()
