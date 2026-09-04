#!/usr/bin/env python3
"""Regression tests for IOC-driven investigation hardening.

Covers failures from supremeboxer / ErrTraffic agent logs:
- wildcard host search (*drpc.org)
- Low EKFiddle stays LOW with ekfiddle_comment on overview
- argument sanitizer (id, nested session_id, query forms)
- auto-fetch skips MP4 / broad searches
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
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


# Stub google.generativeai before loading gemini client
if "google" not in sys.modules:
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.generativeai")
    genai_mod.configure = MagicMock()
    genai_mod.GenerativeModel = MagicMock()
    google_mod.generativeai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.generativeai"] = genai_mod

# Stub flask / requests / mcp deps lightly if missing for enhanced-bridge / 5ire
for pkg in ("flask", "requests"):
    if pkg not in sys.modules:
        try:
            __import__(pkg)
        except ImportError:
            sys.modules[pkg] = MagicMock()

enhanced = _load_module("enhanced_bridge_mod", "enhanced-bridge.py")
fiveire = _load_module("fiveire_bridge_mod", "5ire-bridge.py")
gemini = _load_module("gemini_client_mod", "gemini-fiddler-client.py")


class TestWildcardSearch(unittest.TestCase):
    def setUp(self):
        self.bridge = enhanced.EnhancedFiddlerRealtimeBridge.__new__(
            enhanced.EnhancedFiddlerRealtimeBridge
        )

    def test_star_drpc_compiles_and_matches(self):
        rx, norm, warn = self.bridge._compile_search_pattern("*drpc.org")
        self.assertEqual(norm, "drpc.org")
        self.assertIsNotNone(rx)
        self.assertTrue(rx.search("polygon.drpc.org"))
        self.assertTrue(rx.search("drpc.org"))
        self.assertIsNotNone(warn)

    def test_plain_drpc_matches(self):
        rx, norm, warn = self.bridge._compile_search_pattern("drpc.org")
        self.assertEqual(norm, "drpc.org")
        self.assertIsNotNone(rx)
        self.assertTrue(rx.search("polygon.drpc.org"))
        self.assertIsNone(warn)

    def test_star_only_reduces_to_empty(self):
        rx, norm, warn = self.bridge._compile_search_pattern("*")
        self.assertEqual(norm, "")
        self.assertIsNone(rx)


class TestEkfiddleOverview(unittest.TestCase):
    def setUp(self):
        self.bridge = enhanced.EnhancedFiddlerRealtimeBridge.__new__(
            enhanced.EnhancedFiddlerRealtimeBridge
        )

    def test_low_severity_stays_low(self):
        session = {
            "id": "262",
            "host": "supremeboxer.com",
            "url": "https://supremeboxer.com/membership/",
            "method": "GET",
            "statusCode": 200,
            "contentType": "text/html",
            "contentLength": 50000,
            "ekfiddleComments": "Low: External Script Monitor [HTML/JS]",
            "received_at": 0,
        }
        assessment = self.bridge._quick_risk_assessment(session)
        self.assertEqual(assessment["level"], "LOW")
        self.assertEqual(assessment["flag"], "ekfiddle_alert")
        self.assertLess(assessment["score"], 0.4)

    def test_overview_includes_ekfiddle_comment(self):
        session = {
            "id": "262",
            "host": "supremeboxer.com",
            "url": "https://supremeboxer.com/membership/",
            "method": "GET",
            "statusCode": 200,
            "contentType": "text/html",
            "contentLength": 50000,
            "ekfiddleComments": "Low: External Script Monitor [HTML/JS]",
            "received_at": 0,
        }
        overview = self.bridge._format_session_overview(session)
        self.assertEqual(overview["ekfiddle_comment"], "Low: External Script Monitor [HTML/JS]")
        self.assertEqual(overview["risk_level"], "LOW")
        self.assertTrue(any("EKFiddle:" in r for r in overview["risk_reasons"]))


class TestFiveireEkfiddleFallback(unittest.TestCase):
    def test_from_explicit_field(self):
        comment = fiveire.FiddlerBridgeClient._extract_ekfiddle_comment(
            {"ekfiddle_comment": "High: eval()"}
        )
        self.assertEqual(comment, "High: eval()")

    def test_from_risk_reasons_when_comment_null(self):
        comment = fiveire.FiddlerBridgeClient._extract_ekfiddle_comment(
            {
                "ekfiddle_comment": None,
                "ekfiddleComments": "",
                "risk_reasons": ["EKFiddle: Low: External Script Monitor [HTML/JS]"],
            }
        )
        self.assertEqual(comment, "Low: External Script Monitor [HTML/JS]")


class TestArgSanitizer(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client._analyzed_session_ids = set()
        self.client._last_search_args = {}

    def test_id_maps_to_session_id(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__session_body", {"id": "262"}
        )
        self.assertEqual(out.get("session_id"), "262")
        self.assertNotIn("id", out)

    def test_nested_session_id_object(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__session_body",
            {"session_id": {"session_id": "262"}},
        )
        self.assertEqual(out.get("session_id"), "262")

    def test_query_content_type(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_search",
            {"query": "content_type:javascript"},
        )
        self.assertEqual(out.get("content_type"), "javascript")
        self.assertNotIn("query", out)

    def test_query_host(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_search",
            {"query": "host:cdn.apigateway.co"},
        )
        self.assertEqual(out.get("host_pattern"), "cdn.apigateway.co")

    def test_filter_alias_maps_to_host_pattern(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_search",
            {"filter": "apigateway.co"},
        )
        self.assertEqual(out.get("host_pattern"), "apigateway.co")
        self.assertNotIn("filter", out)

    def test_strips_leading_star_from_host_pattern(self):
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__sessions_search",
            {"host_pattern": "*apigateway.co"},
        )
        self.assertEqual(out.get("host_pattern"), "apigateway.co")


class TestRefetchLock(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client._analyzed_session_ids = {"256"}
        self.client._current_user_query = "create ekfiddle rules for session 256"
        self.client._last_search_args = {}
        self.client.available_tools = [{"name": "fiddler_mcp__session_body"}]
        self.client.verbose_logging = False
        self.client.show_progress = False
        self.client.log_with_timestamp = MagicMock()

    def test_blocks_already_analyzed_session(self):
        result = self.client.call_tool(
            "fiddler_mcp__session_body", {"session_id": "256"}
        )
        self.assertFalse(result.get("success", True))
        self.assertTrue(result.get("already_analyzed"))
        self.assertIn("already analyzed this query", result.get("error", ""))

    def test_allows_refetch_when_user_asks_refresh(self):
        self.client._current_user_query = "refresh session 256 body"
        # Sanitizer + lock pass; MCP path will fail without process — stub send
        self.client.send_mcp_request = MagicMock(
            return_value={
                "result": {
                    "content": [{"type": "text", "text": '{"success": true, "session_id": "256"}'}]
                }
            }
        )
        # Prefer testing allow flag directly; call_tool MCP path varies
        self.assertTrue(
            self.client._user_allows_body_refetch(self.client._current_user_query)
        )


class TestEkfiddleRuleHelpers(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client.script_dir = Path(ROOT)
        self.client.log_with_timestamp = MagicMock()

    def test_validator_accepts_eth_call_rule(self):
        line = (
            "SourceCode\tHigh: ErrTraffic eth_call\t"
            "method\\s*:\\s*['\\\"]eth_call['\\\"]"
        )
        self.assertTrue(self.client._validate_ekfiddle_rule_line(line))

    def test_validator_rejects_name_regex_table(self):
        bad_lines = [
            "Name\tRegex\tComment\tColor",
            "EtherHiding\t/eth_call/i\tcomment\tred",
            "| Name | Regex | Comment |",
        ]
        for line in bad_lines:
            self.assertFalse(
                self.client._validate_ekfiddle_rule_line(line),
                msg=f"should reject: {line!r}",
            )

    def test_extractor_pulls_tab_lines_from_prose(self):
        text = (
            "Here are the rules for session 256.\n\n"
            "SourceCode\tHigh: EtherHiding eth_call\tmethod\\s*:\\s*['\\\"]eth_call['\\\"]\n"
            "SourceCode\tHigh: Overlay max z-index\tz-index\\s*:\\s*2147483647\n"
            "\n"
            "Do not invent hosts.\n"
        )
        rules = self.client._extract_ekfiddle_rules_from_text(text)
        self.assertEqual(len(rules), 2)
        self.assertTrue(rules[0].startswith("SourceCode\tHigh:"))

    def test_extractor_normalizes_medium_to_med(self):
        text = (
            "SourceCode\tMedium: Dynamic iframe loading\t"
            "document\\.createElement\\(['\\\"]iframe['\\\"]\\)"
        )
        rules = self.client._extract_ekfiddle_rules_from_text(text)
        self.assertEqual(len(rules), 1)
        self.assertTrue(rules[0].startswith("SourceCode\tMed:"))
        self.assertNotIn("Medium:", rules[0])

    def test_save_helper_appends_under_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "generated_ekfiddle_rules.txt"
            rules = [
                "SourceCode\tHigh: EtherHiding eth_call\tmethod\\s*:\\s*['\\\"]eth_call['\\\"]",
                "URI\tMed: ErrTraffic RPC host\tapigateway\\.co",
            ]
            path = self.client._save_ekfiddle_rules(rules, output_path=out)
            self.assertIsNotNone(path)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("# Generated ", content)
            self.assertIn("EtherHiding eth_call", content)
            # Append again
            self.client._save_ekfiddle_rules(
                ["Headers\tLow: Cookie marker\t_cf_verified"],
                output_path=out,
            )
            content2 = out.read_text(encoding="utf-8")
            self.assertEqual(content2.count("# Generated "), 2)
            self.assertIn("_cf_verified", content2)


class TestAutoFetchPolicy(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client._analyzed_session_ids = set()
        self.client._last_search_args = {}

    def test_skips_without_host_filter(self):
        result = {"sessions": [{"id": "1", "content_type": "text/html"}]}
        self.assertFalse(
            self.client._should_auto_fetch_body(result, {"content_type": "javascript"})
        )

    def test_allows_host_filtered_small_set(self):
        result = {"sessions": [{"id": "1", "content_type": "application/javascript"}]}
        self.assertTrue(
            self.client._should_auto_fetch_body(
                result, {"host_pattern": "cdn.apigateway.co"}
            )
        )

    def test_pick_skips_mp4(self):
        sessions = [
            {
                "id": "334",
                "content_type": "video/mp4",
                "url": "https://supremeboxer.com/supreme-01.mp4",
                "size": 85_000_000,
            },
            {
                "id": "262",
                "content_type": "text/html",
                "url": "https://supremeboxer.com/membership/",
                "size": 50000,
                "ekfiddle_comment": "Low: External Script Monitor [HTML/JS]",
            },
        ]
        picked = self.client._pick_auto_fetch_session(sessions)
        self.assertIsNotNone(picked)
        self.assertEqual(str(picked["id"]), "262")

    def test_pick_skips_already_analyzed(self):
        self.client._analyzed_session_ids = {"262"}
        sessions = [
            {
                "id": "262",
                "content_type": "text/html",
                "url": "https://example.com/",
                "size": 50000,
                "ekfiddle_comment": "High: SocGholish Loader",
            },
            {
                "id": "250",
                "content_type": "application/javascript",
                "url": "https://evil.example/loader.js",
                "size": 12000,
            },
        ]
        picked = self.client._pick_auto_fetch_session(sessions)
        self.assertIsNotNone(picked)
        self.assertEqual(str(picked["id"]), "250")

    def test_is_text_or_js_rejects_mp4(self):
        self.assertFalse(
            self.client._is_text_or_js_session(
                {
                    "content_type": "video/mp4",
                    "url": "https://x/a.mp4",
                    "size": 85_000_000,
                }
            )
        )


class TestCompareSanitizeAndStatus(unittest.TestCase):
    def setUp(self):
        self.client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        self.client._analyzed_session_ids = set()
        self.client._last_search_args = {}
        self.client.conversation_history = []
        self.client._current_user_query = ""
        self.client.log_with_timestamp = MagicMock()

    def test_compare_coerces_repeated_like_session_ids(self):
        class FakeRepeated:
            def __init__(self, items):
                self._items = list(items)

            def __iter__(self):
                return iter(self._items)

        FakeRepeated.__name__ = "RepeatedComposite"
        out = self.client._sanitize_tool_arguments(
            "fiddler_mcp__compare_sessions",
            {"session_ids": FakeRepeated(["250", "231", "41"]), "smart_extract": True},
        )
        self.assertEqual(out["session_ids"], ["250", "231", "41"])
        import json

        json.dumps(out)

    def test_brief_tool_status_formats(self):
        self.assertEqual(
            self.client._brief_tool_status(
                "fiddler_mcp__session_body", {"session_id": "250"}
            ),
            "  -> session_body 250",
        )
        self.assertIn(
            "auth-code-check.info",
            self.client._brief_tool_status(
                "fiddler_mcp__sessions_search",
                {"host_pattern": "auth-code-check.info"},
            ),
        )
        self.assertIn(
            "compare",
            self.client._brief_tool_status(
                "fiddler_mcp__compare_sessions",
                {"session_ids": ["1", "2", "3"]},
            ),
        )

    def test_is_media_content_type(self):
        self.assertTrue(self.client._is_media_content_type("image/png"))
        self.assertTrue(self.client._is_media_content_type("video/mp4"))
        self.assertFalse(self.client._is_media_content_type("text/html"))
        self.assertFalse(self.client._is_media_content_type("application/javascript"))

    def test_build_investigate_prompt_with_host(self):
        prompt = self.client.build_investigate_prompt("https://www.mgc.es/")
        self.assertIn("INVESTIGATE CAPTURE", prompt)
        self.assertIn("mgc.es", prompt)

    def test_clear_bridge_buffer_calls_mcp(self):
        self.client.call_tool = MagicMock(
            return_value={
                "success": True,
                "cleared_counts": {"live_sessions": 10, "suspicious_sessions": 2},
            }
        )
        self.client._analyzed_session_ids = {"1", "2"}
        result = self.client.clear_bridge_buffer()
        self.client.call_tool.assert_called_once_with(
            "fiddler_mcp__sessions_clear",
            {"confirm": True, "clear_suspicious": True},
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(self.client._analyzed_session_ids, set())

    def test_persist_skips_low_rules_on_benign_verdict(self):
        self.client._current_user_query = "anything malicious in this traffic?"
        self.client.script_dir = Path(tempfile.mkdtemp())
        text = (
            "The traffic is Benign. False Positive from dns-prefetch.\n"
            "SourceCode\tLow: Mautic Marketing\tMauticTrackingObject\n"
            "SourceCode\tHigh: SocGholish atob Loader\tatob\\(['\\\"]QgwfBAke\n"
        )
        # High should not appear together with Benign in real answers, but filter only drops Low:
        saved = self.client.maybe_persist_ekfiddle_rules(text)
        # Benign + not asked for rules => Low dropped; High still saved if present
        self.assertTrue(all(not r.split("\t")[1].startswith("Low:") for r in saved))
        self.assertTrue(any("SocGholish" in r for r in saved))


class TestRequestRetryPolicy(unittest.TestCase):
    def test_does_not_retry_timeout(self):
        client = fiveire.FiddlerBridgeClient()
        client.request = MagicMock(
            side_effect=fiveire.BridgeRequestError("Bridge request timed out")
        )
        with self.assertRaises(fiveire.BridgeRequestError):
            client.request_with_retry("GET", "/api/stats")
        self.assertEqual(client.request.call_count, 1)

    def test_retries_connection_error(self):
        client = fiveire.FiddlerBridgeClient()
        client.max_retries = 2
        client.request = MagicMock(
            side_effect=[fiveire.BridgeConnectionError("down"), {"ok": True}]
        )
        with patch.object(fiveire, "sleep"):
            out = client.request_with_retry("GET", "/api/stats")
        self.assertEqual(out, {"ok": True})
        self.assertEqual(client.request.call_count, 2)


class TestBridgeHangFixes(unittest.TestCase):
    def _client(self):
        client = gemini.GeminiFiddlerClient.__new__(gemini.GeminiFiddlerClient)
        client._analyzed_session_ids = set()
        client._current_user_query = "investigate"
        client._last_search_args = {}
        client.available_tools = [{"name": "fiddler_mcp__live_stats"}]
        client.verbose_logging = False
        client.show_progress = False
        client.log_with_timestamp = MagicMock()
        client.mcp_stderr_file = None
        client.tool_timeout = 30
        client._reset_bridge_circuit()
        client.is_enhanced_bridge_healthy = MagicMock(return_value=False)
        client.clear_interrupt = MagicMock()
        client.conversation_history = []
        return client

    def test_classify_http_timeout_vs_mcp_stdio(self):
        self.assertEqual(
            gemini.GeminiFiddlerClient._classify_bridge_error(
                result={"error": "Failed to get stats: Bridge request timed out"}
            ),
            "http_timeout",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._classify_bridge_error(
                result={"error": "MCP child did not reply in 30s (no console; it is this client's python.exe child). HTTP 8081 may still be the cause."}
            ),
            "mcp_stdio",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._classify_bridge_error(
                exc=RuntimeError("MCP server response timeout (30s) - server may not be responding")
            ),
            "mcp_stdio",
        )
        self.assertIsNone(
            gemini.GeminiFiddlerClient._classify_bridge_error(
                result={"error": "Maximum 10 sessions per comparison (to prevent timeout)"}
            )
        )

    def test_status_formatter_strings(self):
        self.assertEqual(
            gemini.GeminiFiddlerClient._status_line_wait("LLM thinking", 12),
            "LLM thinking 12s",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._status_line_done("HTTP 8081 ok", 0.4),
            "HTTP 8081 ok (0.4s)",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._status_line_done("HTTP 8081 timeout", 10.0),
            "HTTP 8081 timeout (10.0s)",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._status_line_done("MCP child timeout", 30.0),
            "MCP child timeout (30.0s)",
        )
        self.assertEqual(
            gemini.GeminiFiddlerClient._status_line_done("LLM report", 8.1),
            "LLM report (8.1s)",
        )

    def test_streak_opens_on_second_timeout_success_resets(self):
        client = self._client()
        timeout = {"success": False, "error": "Search failed: Bridge request timed out"}
        client._note_tool_outcome(timeout)
        self.assertFalse(client._http_circuit_open)
        self.assertEqual(client._http_timeout_streak, 1)
        client._note_tool_outcome(timeout)
        self.assertTrue(client._http_circuit_open)
        client._reset_bridge_circuit()
        client._note_tool_outcome(timeout)
        client._note_tool_outcome({"success": True, "sessions": []})
        self.assertEqual(client._http_timeout_streak, 0)
        self.assertFalse(client._http_circuit_open)
        self.assertEqual(client._successful_tools_this_query, 1)

    def test_chat_resets_circuit(self):
        client = self._client()
        client._http_timeout_streak = 5
        client._http_circuit_open = True
        client.ensure_mcp_alive = MagicMock(return_value=False)
        out = client.chat("try now")
        self.assertIn("MCP server is not running", out)
        self.assertFalse(client._http_circuit_open)
        self.assertEqual(client._http_timeout_streak, 0)

    def test_call_tool_skips_http_when_circuit_open(self):
        client = self._client()
        client._http_circuit_open = True
        client._http_circuit_error = "HTTP 8081 not answering. Stopping tools."
        client.send_mcp_request = MagicMock()
        result = client.call_tool("fiddler_mcp__live_stats", {})
        client.send_mcp_request.assert_not_called()
        self.assertTrue(result.get("circuit_open"))
        self.assertIn("8081", result.get("error", ""))

    def test_call_tool_catches_mcp_stdio_timeout(self):
        client = self._client()
        client.send_mcp_request = MagicMock(
            side_effect=RuntimeError("MCP server response timeout (30s) - server may not be responding")
        )
        result = client.call_tool("fiddler_mcp__live_stats", {})
        self.assertEqual(result.get("error_class"), "mcp_stdio")
        self.assertIn("MCP child did not reply", result.get("error", ""))
        self.assertIn("no console", result.get("error", ""))

    def test_native_loop_stops_after_two_timeouts(self):
        client = self._client()
        client.use_native_tools = True
        client._gemini_tool = True
        client.provider_name = "deepseek"
        client.max_followups = 20
        client._interrupt_requested = False
        client.use_rich = False
        client.console = None
        client._format_recent_history = MagicMock(return_value="")
        client._analyzed_sessions_note = MagicMock(return_value="No sessions")
        client.maybe_persist_ekfiddle_rules = MagicMock(return_value=[])
        client._finalize_assistant_response = lambda t: t
        client.parse_gemini_response = MagicMock(return_value=None)
        order = []

        def fake_call(name, args):
            order.append(name)
            result = {"success": False, "error": "Failed to get stats: Bridge request timed out"}
            client._note_tool_outcome(result)
            return result

        client.call_tool = fake_call

        class FakeDeepSeek:
            display_label = "DeepSeek"

            def tools_bound(self):
                return True

            def start_conversation(self, user_text):
                return [{"role": "user", "content": user_text}]

            def generate(self, conversation, tool_choice="auto"):
                self.generate_calls += 1
                return {
                    "calls": [
                        {"name": "fiddler_mcp__live_stats", "args": {}, "id": "1"},
                        {"name": "fiddler_mcp__ekfiddle_threats", "args": {}, "id": "2"},
                        {"name": "fiddler_mcp__sessions_search", "args": {}, "id": "3"},
                    ],
                    "text": "",
                }

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
        provider.generate_calls = 0
        client.llm_provider = provider
        out = client._chat_native("investigate")
        self.assertEqual(len(order), 2)
        self.assertEqual(provider.generate_calls, 1)
        self.assertIn("8081", out)

    def test_disable_quick_edit_does_not_raise(self):
        gemini._disable_quick_edit()
        enhanced._disable_quick_edit()


if __name__ == "__main__":
    unittest.main()
