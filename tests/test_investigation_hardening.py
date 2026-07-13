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
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
