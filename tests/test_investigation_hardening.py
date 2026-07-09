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
import types
import unittest
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
