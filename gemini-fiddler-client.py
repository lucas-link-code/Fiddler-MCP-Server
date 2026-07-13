#!/usr/bin/env python3
"""
Gemini-Powered Fiddler MCP Client
Natural language interface for analyzing Fiddler traffic using Google Gemini 2.5

Features:
- Natural language queries about Fiddler traffic
- Automatic tool selection and execution
- Conversation history and context
- Easy configuration
- Production-ready error handling
"""
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path

# Suppress gRPC/absl logging noise
os.environ.setdefault("GRPC_VERBOSITY", "NONE")
os.environ.setdefault("GRPC_LOG_SEVERITY_LEVEL", "ERROR")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_TRACE"] = ""

try:
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", message=r"Unrecognized FinishReason enum value", category=UserWarning)
    
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    GENAI_AVAILABLE = False

try:
    from rich.console import Console
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None  # type: ignore
    Markdown = None  # type: ignore

# Package name in requirements -> import module name
_REQ_IMPORT_MAP = {
    "google-generativeai": "google.generativeai",
    "rich": "rich",
    "mcp": "mcp",
    "pydantic": "pydantic",
    "flask": "flask",
    "requests": "requests",
}

REQUIRED_SCRIPTS = (
    "enhanced-bridge.py",
    "5ire-bridge.py",
    "gemini_native_tools.py",
)


def _python_executable() -> str:
    if sys.executable:
        return sys.executable
    import platform
    return "python" if platform.system() == "Windows" else "python3"


def _parse_requirements_packages(req_path: Path) -> List[str]:
    """Return pip requirement lines (non-empty, non-comment)."""
    if not req_path.exists():
        return []
    lines = []
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _requirement_base_name(req_line: str) -> str:
    """Strip version pins / extras: google-generativeai==0.8.5 -> google-generativeai."""
    name = req_line.strip()
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if sep in name:
            name = name.split(sep, 1)[0]
            break
    if "[" in name:
        name = name.split("[", 1)[0]
    return name.strip().lower()


def _is_importable(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def ensure_python_dependencies(script_dir: Optional[Path] = None, auto_install: bool = True) -> bool:
    """Check requirements-gemini.txt packages; pip install missing ones if allowed.

    Returns True if all required imports are available after the check/install.
    """
    root = Path(script_dir) if script_dir else Path(__file__).resolve().parent
    req_path = root / "requirements-gemini.txt"
    print("\n[*] Checking Python dependencies...")

    if not req_path.exists():
        print(f"[!] {req_path.name} not found; checking core imports only")
        req_lines = [
            "google-generativeai==0.8.5",
            "rich>=13.0.0",
            "mcp>=1.0.0",
            "pydantic>=2.0.0",
            "Flask>=2.0.0",
            "requests>=2.28.0",
        ]
    else:
        req_lines = _parse_requirements_packages(req_path)
        print(f"[+] Using {req_path.name}")

    missing_reqs: List[str] = []
    present: List[str] = []
    for req in req_lines:
        base = _requirement_base_name(req)
        mod = _REQ_IMPORT_MAP.get(base, base.replace("-", "_"))
        if _is_importable(mod):
            present.append(base)
        else:
            missing_reqs.append(req)

    if present:
        print(f"[+] Installed: {', '.join(present)}")
    if not missing_reqs:
        print("[+] All required Python packages are available")
        return True

    print(f"[!] Missing packages: {', '.join(_requirement_base_name(r) for r in missing_reqs)}")
    if not auto_install:
        print("[!] Auto-install disabled. Run: pip install -r requirements-gemini.txt")
        return False

    py = _python_executable()
    cmd = [py, "-m", "pip", "install", "--upgrade"]
    if req_path.exists():
        cmd.extend(["-r", str(req_path)])
        print(f"[*] Installing from {req_path.name} ...")
    else:
        cmd.extend(missing_reqs)
        print(f"[*] Installing: {' '.join(missing_reqs)}")

    try:
        result = subprocess.run(cmd, cwd=str(root), check=False)
        if result.returncode != 0:
            print(f"[X] pip install failed with exit code {result.returncode}")
            return False
    except Exception as exc:
        print(f"[X] pip install failed: {exc}")
        return False

    # Re-check
    still_missing = []
    for req in req_lines:
        base = _requirement_base_name(req)
        mod = _REQ_IMPORT_MAP.get(base, base.replace("-", "_"))
        if not _is_importable(mod):
            still_missing.append(base)
    if still_missing:
        print(f"[X] Still missing after install: {', '.join(still_missing)}")
        print("[!] Try manually: python -m pip install -r requirements-gemini.txt")
        return False

    print("[+] Dependencies installed successfully")
    # Reload genai into this process if it was missing at import time
    global genai, GENAI_AVAILABLE, RICH_AVAILABLE, Console, Markdown
    try:
        import google.generativeai as _genai
        genai = _genai
        GENAI_AVAILABLE = True
    except ImportError:
        GENAI_AVAILABLE = False
        return False
    if not RICH_AVAILABLE:
        try:
            from rich.console import Console as _Console
            from rich.markdown import Markdown as _Markdown
            Console = _Console
            Markdown = _Markdown
            RICH_AVAILABLE = True
        except ImportError:
            pass
    return True


def ensure_required_scripts(script_dir: Optional[Path] = None) -> bool:
    """Verify companion scripts exist next to the client."""
    root = Path(script_dir) if script_dir else Path(__file__).resolve().parent
    print("\n[*] Checking required scripts...")
    ok = True
    for name in REQUIRED_SCRIPTS:
        path = root / name
        if path.exists():
            print(f"[+] Found {name}")
        else:
            print(f"[X] Missing {name} (expected at {path})")
            ok = False
    return ok


def bootstrap_runtime(auto_install: bool = True) -> bool:
    """Install deps and verify scripts before starting bridges/client."""
    root = Path(__file__).resolve().parent
    skip_install = os.environ.get("GEMINI_SKIP_DEP_INSTALL", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not ensure_python_dependencies(root, auto_install=auto_install and not skip_install):
        return False
    if not GENAI_AVAILABLE:
        print("[X] google.generativeai still unavailable after dependency check")
        return False
    if not ensure_required_scripts(root):
        return False
    return True

# Available Gemini models for selection (centralized for consistency)
# Model IDs from https://ai.google.dev/gemini-api/docs/models (Gemini 3 / 2.5)
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
AVAILABLE_MODELS = {
    "1": "gemini-3-flash-preview",
    "2": "gemini-3.1-flash-lite",
    "3": "gemini-3.1-pro-preview",
    "4": "gemini-3.5-flash",
    "5": "gemini-2.5-flash",
    "6": "gemini-2.5-pro",
    "7": "gemini-2.5-flash-lite",
    "8": "gemini-2.0-flash",
    "9": "gemini-2.0-flash-lite",
    "10": "gemini-1.5-flash",
    "11": "gemini-1.5-pro",
}


class GeminiFiddlerClient:
    """Gemini-powered MCP client for Fiddler traffic analysis"""

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_GEMINI_MODEL,
        auto_save_full_bodies: bool = False,
    ):
        """Initialize client with Gemini API key"""
        self.api_key = api_key
        self.model_name = model_name
        self.mcp_process = None
        self.mcp_stderr_file = None
        self.request_id = 0
        self.conversation_history = []
        self.available_tools = []
        self.session_start = datetime.now()
        self.auto_save_full_bodies = auto_save_full_bodies
        self.verbose_logging = os.environ.get("GEMINI_FIDDLER_VERBOSE_LOG", "0") == "1"
        
        # Performance settings
        self.tool_timeout = int(os.environ.get("GEMINI_TOOL_TIMEOUT", "30"))  # seconds
        self.gemini_timeout = int(os.environ.get("GEMINI_API_TIMEOUT", "60"))  # seconds
        self.show_progress = os.environ.get("GEMINI_HIDE_PROGRESS", "").strip() != "1"
        self.max_followups = int(os.environ.get("GEMINI_MAX_TOOL_CALLS", "20"))  # Maximum tool calls per query
        self._analyzed_session_ids: set = set()
        self._last_search_args: Dict[str, Any] = {}
        self._interrupt_requested = False
        self._bridge_process = None  # optional handle if we spawned enhanced-bridge ourselves
        self.script_dir = Path(__file__).resolve().parent
        self.bridge_url = os.environ.get("FIDDLER_BRIDGE_URL", "http://127.0.0.1:8081").rstrip("/")
        self._current_user_query = ""
        self._mcp_server_command: Optional[List[str]] = None
        # Native Gemini function calling (default on). Set GEMINI_NATIVE_TOOLS=0 for legacy text JSON loop.
        self.use_native_tools = os.environ.get("GEMINI_NATIVE_TOOLS", "1").strip().lower() not in {
            "0", "false", "no", "off",
        }
        self._gemini_tool = None
        self._system_instruction = ""
        
        if RICH_AVAILABLE:
            self.console = Console()
            self.use_rich = True
        else:
            self.console = None
            self.use_rich = False
        
        if not GENAI_AVAILABLE or genai is None:
            raise RuntimeError(
                "google-generativeai is not installed. "
                "Run: python -m pip install -r requirements-gemini.txt"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        
        print(f"Initialized Gemini {model_name}")
        if self.use_native_tools:
            print("[*] Native tool schema binding enabled (GEMINI_NATIVE_TOOLS=1)")
        if not RICH_AVAILABLE:
            print("[!] Tip: Install 'rich' library for better formatting: pip install rich")

    # Valid argument keys per tool (used by sanitizer)
    _TOOL_ARG_KEYS = {
        "fiddler_mcp__live_sessions": {"limit", "since_minutes", "host_filter", "status_filter", "suspicious_only"},
        "fiddler_mcp__sessions_search": {
            "host_pattern", "url_pattern", "content_type", "method",
            "status_min", "status_max", "min_size", "max_size", "since_minutes", "limit",
        },
        "fiddler_mcp__session_headers": {"session_id"},
        "fiddler_mcp__session_body": {"session_id", "include_binary", "smart_extract"},
        "fiddler_mcp__compare_sessions": {"session_ids", "include_binary", "smart_extract"},
        "fiddler_mcp__live_stats": set(),
        "fiddler_mcp__sessions_timeline": {
            "time_range_minutes", "group_by", "include_details", "filter_host", "since_minutes",
        },
        "fiddler_mcp__sessions_clear": {"confirm", "clear_suspicious"},
        "fiddler_mcp__ekfiddle_sessions": {"limit", "time_range_minutes", "threat_level"},
        "fiddler_mcp__ekfiddle_threats": {"time_range_minutes", "min_risk_score", "categories"},
    }

    @staticmethod
    def _flatten_session_id_value(value: Any) -> Optional[str]:
        """Coerce nested/object session_id values to a plain string."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("session_id", "id", "value"):
                if key in value and value[key] is not None:
                    return GeminiFiddlerClient._flatten_session_id_value(value[key])
            if len(value) == 1:
                return GeminiFiddlerClient._flatten_session_id_value(next(iter(value.values())))
        if isinstance(value, list) and len(value) == 1:
            return GeminiFiddlerClient._flatten_session_id_value(value[0])
        return str(value).strip() or None

    def _sanitize_tool_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common LLM argument mistakes before calling MCP tools.

        Returns either sanitized args, or an error dict with success=False and
        a correction hint (caller must not send that to MCP).
        """
        if not isinstance(arguments, dict):
            return {
                "success": False,
                "error": "Tool arguments must be a JSON object",
                "hint": 'Use format: {"tool": "fiddler_mcp__session_body", "arguments": {"session_id": "142"}}',
                "_sanitize_error": True,
            }

        args = dict(arguments)

        # Map id -> session_id for body/headers tools
        if tool_name in ("fiddler_mcp__session_body", "fiddler_mcp__session_headers"):
            if "session_id" not in args and "id" in args:
                args["session_id"] = args.pop("id")
            if "session_id" in args:
                flat = self._flatten_session_id_value(args["session_id"])
                if not flat:
                    return {
                        "success": False,
                        "error": "session_id must be a string or number",
                        "hint": 'Correct example: {"session_id": "262"}',
                        "received": arguments,
                        "_sanitize_error": True,
                    }
                args["session_id"] = flat

        if tool_name == "fiddler_mcp__compare_sessions" and "session_ids" in args:
            raw_ids = args["session_ids"]
            if isinstance(raw_ids, (str, int)):
                raw_ids = [raw_ids]
            elif not isinstance(raw_ids, list):
                # Gemini may pass protobuf RepeatedComposite; coerce to a plain list
                try:
                    raw_ids = list(raw_ids)
                except TypeError:
                    raw_ids = [raw_ids]
            if isinstance(raw_ids, list):
                flattened = []
                for item in raw_ids:
                    flat = self._flatten_session_id_value(item)
                    if flat:
                        flattened.append(flat)
                args["session_ids"] = flattened

        # Lucene-ish query: "content_type:javascript" / "host:cdn.apigateway.co"
        if tool_name == "fiddler_mcp__sessions_search" and "query" in args:
            query_val = args.pop("query")
            if isinstance(query_val, str) and query_val.strip():
                q = query_val.strip()
                mapped = False
                for field, target in (
                    ("content_type:", "content_type"),
                    ("host:", "host_pattern"),
                    ("host_pattern:", "host_pattern"),
                    ("url:", "url_pattern"),
                    ("url_pattern:", "url_pattern"),
                    ("method:", "method"),
                ):
                    if q.lower().startswith(field):
                        args.setdefault(target, q[len(field):].strip().strip('"').strip("'"))
                        mapped = True
                        break
                if not mapped:
                    # Bare domain-like string -> host_pattern
                    if "." in q and " " not in q and ":" not in q:
                        args.setdefault("host_pattern", q)
                    elif q.lower() in ("javascript", "html", "json", "css", "plain"):
                        args.setdefault("content_type", q.lower())
                    else:
                        return {
                            "success": False,
                            "error": f"Unknown query form: {query_val!r}. sessions_search has no 'query' parameter.",
                            "hint": 'Use host_pattern, url_pattern, or content_type. Example: {"host_pattern": "cdn.apigateway.co"} or {"content_type": "javascript"}',
                            "received": arguments,
                            "_sanitize_error": True,
                        }

        # host -> host_pattern alias
        if tool_name == "fiddler_mcp__sessions_search" and "host" in args and "host_pattern" not in args:
            args["host_pattern"] = args.pop("host")
        if tool_name == "fiddler_mcp__sessions_search" and "url" in args and "url_pattern" not in args:
            args["url_pattern"] = args.pop("url")

        # filter / host_filter aliases often hallucinated by the model
        if tool_name == "fiddler_mcp__sessions_search":
            for alias in ("filter", "host_filter"):
                if alias in args and "host_pattern" not in args:
                    val = args.pop(alias)
                    if isinstance(val, str) and val.strip():
                        args["host_pattern"] = val.strip()
                elif alias in args:
                    args.pop(alias, None)

            # Strip leading/trailing * before bridge call
            for key in ("host_pattern", "url_pattern"):
                if key in args and isinstance(args[key], str):
                    pat = args[key].strip()
                    while pat.startswith("*"):
                        pat = pat[1:]
                    while pat.endswith("*") and not pat.endswith(r"\*"):
                        pat = pat[:-1]
                    args[key] = pat.strip()

        # Timeline: map legacy since_minutes -> time_range_minutes
        if tool_name == "fiddler_mcp__sessions_timeline":
            if "time_range_minutes" not in args and "since_minutes" in args:
                args["time_range_minutes"] = args.pop("since_minutes")
            elif "since_minutes" in args:
                args.pop("since_minutes", None)

        allowed = self._TOOL_ARG_KEYS.get(tool_name)
        if allowed is not None:
            unknown = [k for k in list(args.keys()) if k not in allowed]
            for k in unknown:
                args.pop(k, None)
            if unknown and not args and allowed:
                hint = f"Valid keys for {tool_name}: {sorted(allowed)}"
                if tool_name == "fiddler_mcp__sessions_search":
                    hint += '. Example: {"host_pattern": "cdn.apigateway.co"} or {"content_type": "javascript"}'
                return {
                    "success": False,
                    "error": f"No valid arguments after removing unknown keys: {unknown}",
                    "hint": hint,
                    "received": arguments,
                    "_sanitize_error": True,
                }

        return args

    @staticmethod
    def _user_allows_body_refetch(user_query: str) -> bool:
        """True only when the user explicitly asks to refresh/re-analyze a body."""
        q = (user_query or "").lower()
        triggers = (
            "refresh",
            "fetch again",
            "re-fetch",
            "refetch",
            "re-analyze",
            "reanalyze",
            "re-analyse",
            "analyse again",
            "analyze again",
            "get the body again",
            "pull the body again",
        )
        return any(t in q for t in triggers)

    def _validate_ekfiddle_rule_line(self, line: str) -> bool:
        """Validate one tab-separated EKFiddle CustomRegexes line."""
        if not line or "\t" not in line:
            return False
        if line.lstrip().startswith("#") or line.lstrip().startswith("##"):
            return False
        parts = line.split("\t")
        if len(parts) < 3:
            return False
        rule_type = parts[0].strip()
        severity_name = parts[1].strip()
        regex = parts[2].strip()
        if rule_type not in ("IP", "URI", "SourceCode", "Headers", "Hash"):
            return False
        # Accept Med: or common LLM slip Medium: (normalized on save)
        if not any(
            severity_name.startswith(s) for s in ("High:", "Med:", "Medium:", "Low:")
        ):
            return False
        if len(regex) < 3:
            return False
        # Reject slash-wrapped /regex/i pseudo-format and Name/Regex table leftovers
        if regex.startswith("/") and regex.rstrip().endswith(("/i", "/")):
            return False
        if severity_name.lower() in ("name", "regex", "comment", "color"):
            return False
        return True

    def _extract_ekfiddle_rules_from_text(self, text: str) -> List[str]:
        """Pull valid tab-separated EKFiddle rule lines from mixed assistant prose."""
        if not text:
            return []
        rules: List[str] = []
        seen = set()
        # Prefer fenced blocks first, then whole text
        chunks = [text]
        import re
        fences = re.findall(r"```(?:text|ekfiddle|rules)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fences:
            chunks = fences + [text]
        for chunk in chunks:
            for raw in chunk.splitlines():
                line = raw.rstrip("\n").strip()
                if not line or line in seen:
                    continue
                # Normalize common LLM severity slip Medium: → Med:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip().startswith("Medium:"):
                    parts[1] = "Med:" + parts[1].strip()[len("Medium:") :]
                    line = "\t".join(parts)
                if self._validate_ekfiddle_rule_line(line):
                    seen.add(line)
                    rules.append(line)
        return rules

    def _save_ekfiddle_rules(self, rules: List[str], output_path: Optional[Path] = None) -> Optional[Path]:
        """Append validated rules to generated_ekfiddle_rules.txt with a timestamp header."""
        if not rules:
            return None
        path = Path(output_path) if output_path else (self.script_dir / "generated_ekfiddle_rules.txt")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n# Generated {stamp}\n")
                for rule in rules:
                    fh.write(rule + "\n")
            return path
        except Exception as exc:
            self.log_with_timestamp(f"Failed to save EKFiddle rules: {exc}", to_console=True, prefix="[!] ")
            return None

    def maybe_persist_ekfiddle_rules(self, assistant_text: str) -> List[str]:
        """Extract and save EKFiddle rules from an assistant response. Returns saved lines."""
        rules = self._extract_ekfiddle_rules_from_text(assistant_text)
        if not rules:
            return []
        # Skip auto-save of Low: FP monitors when verdict is Benign unless user asked for rules
        q = (getattr(self, "_current_user_query", None) or "").lower()
        asked_for_rules = any(
            token in q for token in ("ekfiddle", "customregex", "signature", " rule", "rules")
        )
        text_l = (assistant_text or "").lower()
        benign_verdict = any(
            token in text_l
            for token in ("benign", "false positive", "false positives", "is a false positive")
        )
        if benign_verdict and not asked_for_rules:
            filtered = []
            for rule in rules:
                parts = rule.split("\t")
                sev = parts[1].strip() if len(parts) > 1 else ""
                if sev.startswith("Low:"):
                    continue
                filtered.append(rule)
            rules = filtered
            if not rules:
                return []
        path = self._save_ekfiddle_rules(rules)
        if path:
            print(f"[+] Saved {len(rules)} EKFiddle rules to {path.name}")
        return rules

    def _finalize_assistant_response(self, text: str) -> str:
        """Persist any EKFiddle rules found in the assistant text, then return it."""
        if text:
            self.maybe_persist_ekfiddle_rules(text)
        return text

    def _track_analyzed_session(self, tool_name: str, arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Record session IDs whose bodies were fetched in this query."""
        if not isinstance(result, dict) or result.get("success") is False:
            return
        if tool_name == "fiddler_mcp__session_body":
            sid = arguments.get("session_id") or result.get("session_id") or result.get("id")
            if sid:
                self._analyzed_session_ids.add(str(sid))
        elif tool_name == "fiddler_mcp__compare_sessions":
            for sid in arguments.get("session_ids") or []:
                self._analyzed_session_ids.add(str(sid))
            for item in result.get("sessions") or []:
                if isinstance(item, dict) and item.get("session_id"):
                    self._analyzed_session_ids.add(str(item["session_id"]))

    def _analyzed_sessions_note(self) -> str:
        if not self._analyzed_session_ids:
            return "No session bodies analyzed yet in this query."
        ids = ", ".join(sorted(self._analyzed_session_ids, key=lambda x: int(x) if str(x).isdigit() else str(x)))
        return f"Already analyzed session bodies this query (DO NOT re-fetch): {ids}"

    def _strip_tool_json_from_text(self, text: str) -> str:
        """Remove trailing/embedded tool-call JSON so unfinished calls are not shown as answers."""
        if not text:
            return text
        explanatory = self._extract_text_before_tool_call(text)
        return explanatory.strip() if explanatory and explanatory.strip() else text.strip()

    def _should_auto_fetch_body(self, search_result: Dict[str, Any], search_args: Optional[Dict[str, Any]] = None) -> bool:
        """Decide whether auto body fetch is appropriate for this search."""
        args = search_args if search_args is not None else self._last_search_args
        if not args:
            return False
        host_pat = (args.get("host_pattern") or "").strip()
        url_pat = (args.get("url_pattern") or "").strip()
        if not host_pat and not url_pat:
            return False
        sessions = search_result.get("sessions") or []
        if not sessions or len(sessions) > 10:
            return False
        return True

    @staticmethod
    def _is_text_or_js_session(session: Dict[str, Any]) -> bool:
        ctype = (session.get("content_type") or session.get("contentType") or "").lower()
        url = (session.get("url") or "").lower()
        if any(x in ctype for x in ("javascript", "ecmascript", "text/html", "application/json", "text/plain")):
            return True
        if any(x in ctype for x in ("video/", "audio/", "image/", "octet-stream", "mp4", "mpeg")):
            return False
        if url.endswith((".mp4", ".webm", ".mp3", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf")):
            return False
        size = session.get("size") or session.get("content_length") or session.get("contentLength") or 0
        try:
            if int(size) > 5_000_000:
                return False
        except (TypeError, ValueError):
            pass
        return "javascript" in url or url.endswith(".js") or "/html" in ctype

    def _pick_auto_fetch_session(self, sessions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Prefer Critical/High EKFiddle JS/HTML, else first text/JS hit; skip media and already-analyzed."""
        def severity_rank(s: Dict[str, Any]) -> int:
            comment = (s.get("ekfiddle_comment") or "") + " " + " ".join(s.get("risk_reasons") or [])
            c = comment.lower()
            if "critical" in c[:40] or c.strip().startswith("critical"):
                return 0
            if "high:" in c[:40] or " high " in f" {c[:40]}":
                return 1
            if s.get("risk_level") == "CRITICAL":
                return 0
            if s.get("risk_level") == "HIGH":
                return 1
            return 5

        analyzed = getattr(self, "_analyzed_session_ids", set()) or set()
        candidates = []
        for s in sessions:
            if not self._is_text_or_js_session(s):
                continue
            sid = str(s.get("id") or s.get("session_id") or "").strip()
            if sid and sid in analyzed:
                continue
            candidates.append(s)
        if not candidates:
            return None
        candidates.sort(key=severity_rank)
        return candidates[0]

    @staticmethod
    def _is_media_content_type(content_type: str) -> bool:
        ctype = (content_type or "").lower()
        return any(
            x in ctype
            for x in (
                "image/",
                "video/",
                "audio/",
                "font/",
                "application/octet-stream",
                "application/pdf",
            )
        )

    @staticmethod
    def _brief_tool_status(tool_name: str, args: Optional[Dict[str, Any]] = None) -> str:
        """One-line investigation breadcrumb for the native tool loop."""
        args = args or {}
        short = (tool_name or "").replace("fiddler_mcp__", "")
        if short == "session_body":
            return f"  -> session_body {args.get('session_id', '?')}"
        if short == "session_headers":
            return f"  -> headers {args.get('session_id', '?')}"
        if short == "sessions_search":
            host = args.get("host_pattern") or args.get("url_pattern") or ""
            return f"  -> search {host}".rstrip() if host else "  -> search"
        if short == "compare_sessions":
            ids = args.get("session_ids") or []
            if isinstance(ids, list) and ids:
                shown = ",".join(str(x) for x in ids[:4])
                extra = f"+{len(ids) - 4}" if len(ids) > 4 else ""
                return f"  -> compare {shown}{extra}"
            return "  -> compare"
        if short == "ekfiddle_threats":
            return "  -> ekfiddle threats"
        if short == "ekfiddle_sessions":
            return "  -> ekfiddle sessions"
        if short == "live_sessions":
            return "  -> live sessions"
        if short == "live_stats":
            return "  -> stats"
        if short == "sessions_timeline":
            return "  -> timeline"
        if short == "sessions_clear":
            return "  -> clear buffer"
        return f"  -> {short}"

    @staticmethod
    def build_investigate_prompt(host: Optional[str] = None) -> str:
        """Canned malicious-traffic investigation prompt for /investigate."""
        scope = ""
        if host:
            host = host.strip().rstrip("/")
            if "://" in host:
                # keep hostname only when a full URL was pasted
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(host if "://" in host else f"https://{host}")
                    host = parsed.hostname or host
                except Exception:
                    pass
            scope = (
                f" Prioritize host {host}: search that host first, then follow "
                "any loader/C2/RPC pivots found in its bodies."
            )
        return (
            "Investigate the current capture buffer for any signs of malicious traffic. "
            "Follow the INVESTIGATE CAPTURE playbook: triage with live_stats and "
            "ekfiddle_threats/ekfiddle_sessions, fetch a few highest-severity JS/HTML bodies, "
            "pivot on hosts found in those bodies, trace the infection chain, then give a "
            "structured summary with Infection chain, hosts/IOCs, and verdict. "
            "Emit EKFiddle CustomRegexes only if malicious high-signal evidence exists. "
            "Do not author rules for confirmed FP or benign libraries."
            f"{scope}"
        )

    def log_with_timestamp(self, message: str, to_console: bool = True, prefix: str = "") -> None:
        """Log a message with timestamp to both console and log file"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted_message = f"[{timestamp}] {prefix}{message}"
        
        # Always log to file if available
        if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
            try:
                self.mcp_stderr_file.write(formatted_message + "\n")
                self.mcp_stderr_file.flush()
            except Exception:
                pass  # Silently fail if file is closed
        
        # Optionally log to console
        if to_console:
            print(formatted_message)

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size to human readable string (KB, MB)"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f}MB"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation: ~4 chars per token for English)"""
        return len(text) // 4

    def _extract_finish_reason(self, response) -> str:
        """Extract finish_reason from Gemini response"""
        try:
            candidates = getattr(response, "candidates", []) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
                if finish_reason is not None:
                    return str(finish_reason).replace("FinishReason.", "")
        except Exception:
            pass
        return "UNKNOWN"

    def _count_candidates(self, response) -> int:
        """Count number of candidates in Gemini response"""
        try:
            candidates = getattr(response, "candidates", []) or []
            return len(candidates)
        except Exception:
            return 0

    def request_interrupt(self) -> None:
        """Soft-interrupt the current tool/analysis chain without exiting the client."""
        self._interrupt_requested = True

    def clear_interrupt(self) -> None:
        self._interrupt_requested = False

    def _check_interrupt(self) -> None:
        """Raise KeyboardInterrupt if a soft interrupt was requested mid-chain."""
        if self._interrupt_requested:
            self._interrupt_requested = False
            raise KeyboardInterrupt()

    def is_enhanced_bridge_healthy(self, timeout: float = 2.0) -> bool:
        """Return True if enhanced-bridge HTTP API on bridge_url is reachable."""
        try:
            import urllib.request
            url = f"{self.bridge_url}/health"
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception:
            try:
                import urllib.request
                url = f"{self.bridge_url}/api/stats"
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    return 200 <= getattr(resp, "status", 200) < 300
            except Exception:
                return False

    def _python_executable(self) -> str:
        import platform
        # Prefer the same interpreter running this client
        if sys.executable:
            return sys.executable
        return "python" if platform.system() == "Windows" else "python3"

    def _launch_script_in_new_console(self, script_name: str, title: str) -> bool:
        """Open script_name in a new visible terminal window. Returns True on launch attempt."""
        import platform
        script_path = self.script_dir / script_name
        if not script_path.exists():
            print(f"[X] Cannot start {script_name}: not found at {script_path}")
            return False

        python_exe = self._python_executable()
        system = platform.system()
        try:
            if system == "Windows":
                # Visible CMD window, same pattern as deploy-mcp.bat
                cmd = f'start "{title}" cmd /k "cd /d "{self.script_dir}" && "{python_exe}" "{script_path}""'
                subprocess.Popen(cmd, shell=True, cwd=str(self.script_dir))
            elif system == "Darwin":
                # macOS: open a new Terminal window running the bridge
                apple_script = (
                    f'tell application "Terminal"\n'
                    f'  do script "cd {self.script_dir} && {python_exe} {script_path}"\n'
                    f'  activate\n'
                    f'end tell'
                )
                subprocess.Popen(["osascript", "-e", apple_script])
            else:
                # Linux: try common terminal emulators, else background process
                launched = False
                for term in (
                    ["gnome-terminal", "--", "bash", "-lc", f"cd '{self.script_dir}' && '{python_exe}' '{script_path}'; exec bash"],
                    ["xterm", "-T", title, "-e", f"cd '{self.script_dir}' && '{python_exe}' '{script_path}'; bash"],
                    ["konsole", "-e", f"bash -lc \"cd '{self.script_dir}' && '{python_exe}' '{script_path}'; exec bash\""],
                ):
                    try:
                        subprocess.Popen(term)
                        launched = True
                        break
                    except FileNotFoundError:
                        continue
                if not launched:
                    log_path = self.script_dir / f"{script_name}.autostart.log"
                    log_f = open(log_path, "a", encoding="utf-8", errors="replace")
                    self._bridge_process = subprocess.Popen(
                        [python_exe, str(script_path)],
                        cwd=str(self.script_dir),
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    print(f"[*] No GUI terminal found; started {script_name} in background (log: {log_path})")
            print(f"[+] Launched {script_name} in a new window ({title})")
            return True
        except Exception as exc:
            print(f"[X] Failed to launch {script_name}: {exc}")
            return False

    def ensure_enhanced_bridge_running(self, wait_seconds: float = 25.0) -> bool:
        """Start enhanced-bridge.py if the HTTP bridge is not already healthy."""
        if self.is_enhanced_bridge_healthy():
            print(f"[+] Enhanced bridge already running at {self.bridge_url}")
            return True

        print(f"[!] Enhanced bridge not reachable at {self.bridge_url}")
        print("[*] Starting enhanced-bridge.py automatically...")
        if not self._launch_script_in_new_console("enhanced-bridge.py", "Fiddler MCP Bridge (Port 8081)"):
            return False

        deadline = time.time() + wait_seconds
        dots = 0
        while time.time() < deadline:
            if self.is_enhanced_bridge_healthy(timeout=1.5):
                print(f"\n[+] Enhanced bridge is healthy at {self.bridge_url}")
                return True
            dots = (dots + 1) % 4
            sys.stdout.write(f"\r  Waiting for enhanced-bridge{'.' * dots}{' ' * (3 - dots)}")
            sys.stdout.flush()
            time.sleep(0.8)

        print(f"\n[X] Timed out waiting for enhanced-bridge at {self.bridge_url}")
        print("[!] Start it manually: python enhanced-bridge.py")
        return False

    def ensure_dependencies_running(self, mcp_server_command: Optional[List[str]] = None) -> bool:
        """Ensure enhanced-bridge (HTTP) is up, then start 5ire-bridge as MCP child if needed.

        5ire-bridge speaks MCP over stdin/stdout and must be this client's subprocess.
        enhanced-bridge is a separate HTTP server and is opened in its own console when missing.
        """
        if not self.ensure_enhanced_bridge_running():
            return False

        # 5ire-bridge: start as MCP subprocess if not already running
        if self.mcp_process is not None and self.mcp_process.poll() is None:
            print("[+] MCP bridge (5ire-bridge.py) already attached")
            return True

        import platform
        python_cmd = self._python_executable()
        if mcp_server_command:
            server_command = list(mcp_server_command)
        else:
            server_command = [python_cmd, str(self.script_dir / "5ire-bridge.py")]
        # Resolve relative script path against script_dir
        if len(server_command) >= 2 and not os.path.isabs(server_command[1]):
            candidate = self.script_dir / server_command[1]
            if candidate.exists():
                server_command[1] = str(candidate)

        self._mcp_server_command = server_command
        self.start_mcp_server(server_command)
        return True

    def is_mcp_alive(self) -> bool:
        proc = getattr(self, "mcp_process", None)
        return proc is not None and proc.poll() is None

    def ensure_mcp_alive(self) -> bool:
        """Restart MCP child if it died (common after Windows Ctrl+C process-group signal)."""
        if self.is_mcp_alive():
            return True
        # Unit tests / partial clients may lack a process handle; do not crash call_tool
        if not hasattr(self, "mcp_process") and not getattr(self, "_mcp_server_command", None):
            return True
        print("[!] MCP server process is not running. Restarting 5ire-bridge...")
        cmd = self._mcp_server_command
        if not cmd:
            cmd = [self._python_executable(), str(self.script_dir / "5ire-bridge.py")]
        try:
            # Clear dead handle before restart
            self.mcp_process = None
            self.start_mcp_server(cmd)
            if self.is_mcp_alive():
                print("[+] MCP server restarted")
                # Re-bind tools if native mode (list_tools refreshes schemas)
                try:
                    tools = self.list_tools()
                    if tools:
                        print(f"[+] Re-discovered {len(tools)} tools after MCP restart")
                except Exception as exc:
                    print(f"[!] Tool rediscovery after restart failed: {exc}")
                return True
        except Exception as exc:
            print(f"[X] Failed to restart MCP server: {exc}")
        return False

    def start_mcp_server(self, server_command: List[str]):
        """Start the MCP server (5ire-bridge.py) as subprocess"""
        print(f"\n[*] Starting MCP server: {' '.join(server_command)}")
        try:
            self._mcp_server_command = list(server_command)
            log_dir = Path(__file__).parent
            err_path = log_dir / "mcp_server.err.log"
            
            if self.verbose_logging:
                print(f"[*] Opening log file: {err_path}")
            
            try:
                err_file = open(err_path, "w", buffering=1, encoding="utf-8", errors="replace")
                self.mcp_stderr_file = err_file
                if self.verbose_logging:
                    print(f"[+] Log file opened (fd={err_file.fileno()})")
            except Exception as e:
                print(f"[!] Failed to open log file: {e}")
                self.mcp_stderr_file = None
                raise

            log_mode = "VERBOSE" if self.verbose_logging else "OPTIMIZED"
            try:
                self.mcp_stderr_file.write(f"=== MCP Server Log Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                self.mcp_stderr_file.write(f"Command: {' '.join(server_command)}\n")
                self.mcp_stderr_file.write(f"Log Mode: {log_mode} (set GEMINI_FIDDLER_VERBOSE_LOG=1 for full JSON)\n")
                self.mcp_stderr_file.write("=" * 70 + "\n\n")
                self.mcp_stderr_file.flush()
            except Exception as e:
                print(f"[!] Error writing log file header: {e}")
                raise

            popen_kwargs: Dict[str, Any] = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 0,
            }
            # Isolate child from Ctrl+C so soft-interrupt does not kill MCP
            if sys.platform == "win32":
                # CREATE_NEW_PROCESS_GROUP prevents console Ctrl+C broadcast to child
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            self.mcp_process = subprocess.Popen(server_command, **popen_kwargs)
            
            import threading
            def log_server_stderr():
                try:
                    while True:
                        line = self.mcp_process.stderr.readline()
                        if not line:
                            break
                        if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            self.mcp_stderr_file.write(f"[{timestamp}] Server: {line}")
                            self.mcp_stderr_file.flush()
                except Exception as e:
                    if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        self.mcp_stderr_file.write(f"[{timestamp}] Stderr thread error: {e}\n")
                        self.mcp_stderr_file.flush()
            
            stderr_thread = threading.Thread(target=log_server_stderr, daemon=True)
            stderr_thread.start()
            
            self.mcp_stderr_file.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Client: Starting stderr capture thread\n")
            self.mcp_stderr_file.flush()
            
            time.sleep(0.5)
            print("[+] MCP server started")
            print(f"[*] Logging to: {err_path}")
            
            if self.verbose_logging:
                try:
                    self.mcp_stderr_file.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Client: Log file test successful\n")
                    self.mcp_stderr_file.flush()
                    print(f"[+] Log file test successful")
                except Exception as e:
                    print(f"[!] Log file test failed: {e}")
            
            try:
                print("[*] Initializing connection...")
                self.initialize_mcp()
            except Exception as e:
                print(f"[X] Initialize failed: {e}")
                print("[!] This usually means the MCP server isn't ready yet")
                raise
        except Exception as e:
            print(f"[X] Failed to start MCP server: {e}")
            if hasattr(self, 'mcp_process') and self.mcp_process:
                try:
                    print("[*] Terminating MCP server subprocess...")
                    self.mcp_process.terminate()
                    self.mcp_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("[!] Force killing MCP server subprocess...")
                    self.mcp_process.kill()
                except Exception as cleanup_error:
                    print(f"[!] Error during cleanup: {cleanup_error}")
            if self.mcp_stderr_file:
                try:
                    self.mcp_stderr_file.close()
                finally:
                    self.mcp_stderr_file = None
            sys.exit(1)

    def send_mcp_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server with timeout"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        request_start = time.time()
        
        try:
            if self.mcp_process.poll() is not None:
                return {"error": "MCP server process has terminated"}
            
            request_json = json.dumps(request)
            request_size = len(request_json)
            
            # Log MCP request with details
            if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if method == "tools/call":
                    tool_name = params.get("name", "unknown") if params else "unknown"
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Request: method={method}, tool={tool_name}, size={self._format_size(request_size)}\n")
                else:
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Request: method={method}, size={self._format_size(request_size)}\n")
                self.mcp_stderr_file.flush()
            self.mcp_process.stdin.write(request_json + "\n")
            self.mcp_process.stdin.flush()

            import select
            import sys
            
            if sys.platform == "win32":
                import threading
                response_line = []
                error = []
                
                def read_with_timeout():
                    try:
                        line = self.mcp_process.stdout.readline()
                        response_line.append(line)
                    except Exception as e:
                        error.append(str(e))
                
                thread = threading.Thread(target=read_with_timeout, daemon=True)
                thread.start()
                thread.join(timeout=30.0)
                
                if not response_line:
                    if error:
                        raise RuntimeError(f"Read error: {error[0]}")
                    raise RuntimeError("MCP server response timeout (30s) - server may not be responding")
                
                response_line = response_line[0]
            else:
                ready = select.select([self.mcp_process.stdout], [], [], 30.0)
                if not ready[0]:
                    raise RuntimeError("MCP server response timeout (30s)")
                response_line = self.mcp_process.stdout.readline()
            
            if not response_line:
                raise RuntimeError("MCP server closed connection")

            response = json.loads(response_line)
            response_size = len(response_line)
            elapsed_ms = int((time.time() - request_start) * 1000)
            
            # Log MCP response with timing and size
            if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                
                if self.verbose_logging:
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, size={self._format_size(response_size)}\n")
                    self.mcp_stderr_file.write(f"[{timestamp}] Response: {json.dumps(response)}\n")
                else:
                    if "error" in response:
                        self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, ERROR: {json.dumps(response.get('error', {}))}\n")
                    elif method == "tools/call":
                        tool_name = params.get("name", "unknown") if params else "unknown"
                        if "result" in response:
                            result = response.get("result", {})
                            content = result.get("content", [])
                            item_count = len(content) if isinstance(content, list) else 0
                            self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, tool='{tool_name}', items={item_count}, size={self._format_size(response_size)}\n")
                        else:
                            self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, tool='{tool_name}', no result\n")
                    else:
                        self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, method='{method}', size={self._format_size(response_size)}\n")
                
                self.mcp_stderr_file.flush()
            return response
        except json.JSONDecodeError as e:
            elapsed_ms = int((time.time() - request_start) * 1000)
            self.log_with_timestamp(f"MCP Response: {elapsed_ms}ms, JSON decode error: {e}", to_console=False)
            return {"error": f"Invalid JSON response: {e}"}
        except Exception as e:
            elapsed_ms = int((time.time() - request_start) * 1000)
            self.log_with_timestamp(f"MCP Response: {elapsed_ms}ms, error: {e}", to_console=False)
            return {"error": f"MCP request failed: {e}"}

    def send_mcp_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Send JSON-RPC notification (no response expected)."""
        try:
            if self.mcp_process.poll() is not None:
                return "MCP server process has terminated"

            notification = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }

            self.mcp_process.stdin.write(json.dumps(notification) + "\n")
            self.mcp_process.stdin.flush()
        except Exception as exc:
            return f"Failed to send notification: {exc}"
        return None

    def initialize_mcp(self):
        """Initialize MCP connection"""
        response = self.send_mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gemini-fiddler-client", "version": "1.0.0"},
            },
        )
        
        if "result" in response:
            server_info = response["result"].get("serverInfo", {})
            print(f"[+] Connected to {server_info.get('name', 'MCP server')}")

            # MCP spec requires clients to notify once initialization completes.
            error = self.send_mcp_notification("notifications/initialized")
            if error and self.verbose_logging:
                print(f"[!] Warning: {error}")
        else:
            print(f"[X] Initialization failed: {response.get('error', 'Unknown error')}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available MCP tools"""
        response = self.send_mcp_request("tools/list")
        
        if "error" in response:
            print(f"\n[X] Error listing tools: {response['error']}")
            print("\n[!] Diagnostics:")
            print(f"    - Process alive: {self.mcp_process.poll() is None}")
            print(f"    - Process PID: {self.mcp_process.pid if self.mcp_process else 'N/A'}")
            print("\n[!] This usually means:")
            print("    1. The 5ire-bridge.py failed to start properly")
            print("    2. The enhanced-bridge.py is not running (needed on port 8081)")
            print("    3. There's a port conflict or network issue")
            print("\n[!] Try:")
            print("    1. Start enhanced-bridge.py first: python enhanced-bridge.py")
            print("    2. Check if port 8081 is available: netstat -an | findstr 8081")
            print("    3. Kill stuck processes: taskkill /F /IM python.exe")
            return []
        
        tools = response.get("result", {}).get("tools", [])
        self.available_tools = tools
        if self.use_native_tools:
            self.bind_gemini_tools()
        return tools

    def bind_gemini_tools(self) -> bool:
        """Convert MCP tools to Gemini FunctionDeclarations and rebuild the model."""
        import gemini_native_tools as native

        self._system_instruction = native.investigation_system_instruction(self.max_followups)
        tool, errors = native.build_gemini_tool(self.available_tools)
        if errors:
            for err in errors:
                self.log_with_timestamp(f"Tool bind skip: {err}", to_console=True, prefix="[!] ")
        if not tool:
            self.log_with_timestamp("No Gemini tools bound; falling back to text tool loop", to_console=True, prefix="[!] ")
            self._gemini_tool = None
            self.use_native_tools = False
            self.model = genai.GenerativeModel(self.model_name)
            return False

        self._gemini_tool = tool
        self.model = genai.GenerativeModel(
            self.model_name,
            tools=[tool],
            system_instruction=self._system_instruction,
        )
        n = len(getattr(tool, "function_declarations", []) or [])
        names = [d.name for d in (tool.function_declarations or [])]
        print(f"[+] Bound {n} Gemini FunctionDeclarations: {', '.join(names)}")
        self.log_with_timestamp(f"Bound Gemini tools: {names}", to_console=False)
        return True

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific MCP tool with progress indicator"""

        if not self.ensure_mcp_alive():
            return {
                "success": False,
                "error": "MCP server process is not running and restart failed",
                "hint": "Restart gemini-fiddler-client.py or start 5ire-bridge.py manually",
            }
        
        # Handle non-prefixed tool names (LLM sometimes omits fiddler_mcp__ prefix)
        NON_PREFIXED_ALIASES = {
            # Common non-prefixed hallucinations
            "get_sessions": "fiddler_mcp__live_sessions",
            "live_sessions": "fiddler_mcp__live_sessions",
            "list_sessions": "fiddler_mcp__live_sessions",
            "session_body": "fiddler_mcp__session_body",
            "get_body": "fiddler_mcp__session_body",
            "session_headers": "fiddler_mcp__session_headers",
            "get_headers": "fiddler_mcp__session_headers",
            "compare_sessions": "fiddler_mcp__compare_sessions",
            "sessions_search": "fiddler_mcp__sessions_search",
            "search_sessions": "fiddler_mcp__sessions_search",
            "live_stats": "fiddler_mcp__live_stats",
            "get_stats": "fiddler_mcp__live_stats",
            "sessions_timeline": "fiddler_mcp__sessions_timeline",
            "sessions_clear": "fiddler_mcp__sessions_clear",
            "ekfiddle_sessions": "fiddler_mcp__ekfiddle_sessions",
            "ekfiddle_threats": "fiddler_mcp__ekfiddle_threats",
        }
        
        # Handle dot notation (fiddler_mcp.tool_name -> fiddler_mcp__tool_name)
        if "." in tool_name and not tool_name.startswith("fiddler_mcp__"):
            parts = tool_name.split(".")
            if len(parts) == 2:
                possible_name = f"fiddler_mcp__{parts[1]}"
                self.log_with_timestamp(f"Auto-corrected dot notation: {tool_name} -> {possible_name}", to_console=True, prefix="[!] ")
                tool_name = possible_name
        
        # Check non-prefixed aliases first
        if tool_name in NON_PREFIXED_ALIASES:
            corrected = NON_PREFIXED_ALIASES[tool_name]
            self.log_with_timestamp(f"Auto-corrected non-prefixed tool: {tool_name} -> {corrected}", to_console=True, prefix="[!] ")
            tool_name = corrected
        
        # Correct common tool name hallucinations from LLM (prefixed versions)
        TOOL_ALIASES = {
            # Session body aliases
            "fiddler_mcp__session_details": "fiddler_mcp__session_body",
            "fiddler_mcp__sessions_details": "fiddler_mcp__session_body",
            "fiddler_mcp__get_session": "fiddler_mcp__session_body",
            "fiddler_mcp__get_body": "fiddler_mcp__session_body",
            "fiddler_mcp__body": "fiddler_mcp__session_body",
            # Live sessions aliases
            "fiddler_mcp__list_sessions": "fiddler_mcp__live_sessions",
            "fiddler_mcp__sessions_list": "fiddler_mcp__live_sessions",
            "fiddler_mcp__get_sessions": "fiddler_mcp__live_sessions",
            "fiddler_mcp__sessions": "fiddler_mcp__live_sessions",
            # Headers aliases
            "fiddler_mcp__get_headers": "fiddler_mcp__session_headers",
            "fiddler_mcp__headers": "fiddler_mcp__session_headers",
            # Stats aliases
            "fiddler_mcp__stats": "fiddler_mcp__live_stats",
            "fiddler_mcp__get_stats": "fiddler_mcp__live_stats",
            # Search aliases
            "fiddler_mcp__search": "fiddler_mcp__sessions_search",
            "fiddler_mcp__search_sessions": "fiddler_mcp__sessions_search",
            # Compare aliases
            "fiddler_mcp__compare": "fiddler_mcp__compare_sessions",
            # Clear aliases
            "fiddler_mcp__clear": "fiddler_mcp__sessions_clear",
            # Timeline aliases
            "fiddler_mcp__timeline": "fiddler_mcp__sessions_timeline",
        }
        if tool_name in TOOL_ALIASES:
            corrected = TOOL_ALIASES[tool_name]
            self.log_with_timestamp(f"Auto-corrected tool: {tool_name} -> {corrected}", to_console=True, prefix="[!] ")
            tool_name = corrected
        
        # Client-side validation: check if tool exists before calling server
        valid_tools = [t.get("name") for t in self.available_tools if t.get("name")]
        if tool_name not in valid_tools:
            tool_list = "\n- ".join(valid_tools) if valid_tools else "No tools available"
            self.log_with_timestamp(f"Invalid tool name: {tool_name}", to_console=True, prefix="[!] ")
            return {
                "error": f"Unknown tool: '{tool_name}'",
                "message": f"This tool does not exist. Use ONLY these exact tool names:\n- {tool_list}",
                "hint": "Check the tool name spelling and try again with one from the list above.",
                "available_tools": valid_tools,
            }

        sanitized = self._sanitize_tool_arguments(tool_name, arguments or {})
        if isinstance(sanitized, dict) and sanitized.get("_sanitize_error"):
            self.log_with_timestamp(
                f"Argument sanitize rejected for {tool_name}: {sanitized.get('error')}",
                to_console=True,
                prefix="[!] ",
            )
            return sanitized
        arguments = sanitized

        # Re-fetch lock: do not pull the same session body twice in one query
        if tool_name == "fiddler_mcp__session_body":
            sid = str(arguments.get("session_id", "")).strip()
            if sid and sid in self._analyzed_session_ids:
                if not self._user_allows_body_refetch(self._current_user_query):
                    msg = (
                        f"Session {sid} already analyzed this query. "
                        "Use prior body findings. Do not re-fetch."
                    )
                    self.log_with_timestamp(msg, to_console=True, prefix="[!] ")
                    return {
                        "success": False,
                        "error": msg,
                        "session_id": sid,
                        "already_analyzed": True,
                        "hint": "Create EKFiddle rules or continue from prior findings. "
                                "Only re-fetch if the user explicitly asks to refresh/re-analyze.",
                    }
        
        # Enhanced bridge call logging
        args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
        self.log_with_timestamp(f"Bridge Call: {tool_name}({args_str})", to_console=False)
        
        if self.verbose_logging:
            self.log_with_timestamp(f"  Arguments: {json.dumps(arguments, indent=2)}", to_console=False, prefix="Client: ")
        
        # Progress indicator
        spinner = ['|', '/', '-', '\\']
        spinner_idx = 0
        start_time = time.time()
        
        # Show initial progress - specify it's the Fiddler HTTP bridge
        sys.stdout.write(f"\r  {spinner[spinner_idx]} Waiting for Fiddler HTTP bridge... (0s)")
        sys.stdout.flush()
        
        response = self.send_mcp_request("tools/call", {"name": tool_name, "arguments": arguments})
        
        # Stop progress and show completion with descriptive info
        elapsed_ms = int((time.time() - start_time) * 1000)
        elapsed_s = elapsed_ms / 1000
        
        result = self._parse_tool_response(response)

        # Short-circuit media bodies: no malware signal, waste tokens
        if (
            tool_name == "fiddler_mcp__session_body"
            and isinstance(result, dict)
            and not result.get("error")
        ):
            ctype = result.get("content_type") or result.get("contentType") or ""
            if self._is_media_content_type(ctype):
                sid = arguments.get("session_id") or result.get("session_id") or result.get("id")
                msg = (
                    f"Session {sid} is media content ({ctype}). "
                    "Skip media bodies; analyze JS/HTML/JSON sessions instead."
                )
                self.log_with_timestamp(msg, to_console=True, prefix="[!] ")
                sys.stdout.write(f"\r  [Fiddler Bridge] Skipped media body ({elapsed_s:.1f}s)                    \n")
                sys.stdout.flush()
                return {
                    "success": False,
                    "error": msg,
                    "session_id": sid,
                    "content_type": ctype,
                    "media_skipped": True,
                    "hint": "Pick a text/html or application/javascript session for malware analysis.",
                }
        
        # Enhanced result logging with session metadata
        try:
            if isinstance(result, dict):
                if result.get("error"):
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, error={result.get('error')}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Error ({elapsed_s:.1f}s)                    \n")
                elif 'sessions' in result:
                    sessions = result.get('sessions', [])
                    count = len(sessions)
                    suspicious = sum(1 for s in sessions if s.get('risk_flag') or s.get('ekfiddle_comment'))
                    ekfiddle = sum(1 for s in sessions if s.get('ekfiddle_comment'))
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, sessions={count}, suspicious={suspicious}, ekfiddle={ekfiddle}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Received {count} sessions ({elapsed_s:.1f}s)                    \n")
                elif 'response_body' in result or 'responseBody' in result:
                    body = result.get('response_body', '') or result.get('responseBody', '') or ''
                    body_len = len(body)
                    content_type = result.get('content_type', 'unknown')
                    # Try to get host from result or infer from session data
                    host = result.get('host', '')
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, content_type={content_type}, response_body={self._format_size(body_len)}", to_console=False)
                    if host:
                        self.log_with_timestamp(f"Bridge Result: host={host}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Received session body: {self._format_size(body_len)} ({elapsed_s:.1f}s)                    \n")
                else:
                    result_size = len(json.dumps(result))
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, result_size={self._format_size(result_size)}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
            else:
                self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, unexpected_type={type(result)}", to_console=False)
                sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
        except Exception as e:
            # Fallback if we can't parse the response
            self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, parse_error={e}", to_console=False)
            sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
        
        sys.stdout.flush()

        if tool_name == "fiddler_mcp__sessions_search":
            self._last_search_args = dict(arguments or {})
            if result.get("success") and self._should_auto_fetch_body(result, arguments):
                follow_up = self._auto_fetch_session_body(result)
                if follow_up:
                    result.setdefault("_follow_up", {})["session_body_preview"] = follow_up
                    metadata = follow_up.get("_auto_fetch_metadata", {})
                    follow_id = follow_up.get("session_id") or follow_up.get("id")
                    if follow_id:
                        status_msg = f"[+] Auto body fetch for session {follow_id}"
                        if metadata.get("has_duplicate_ids"):
                            status_msg += f" at {metadata.get('fetched_timestamp', 'unknown time')}"
                        print(status_msg)
                        self._analyzed_session_ids.add(str(follow_id))
                    else:
                        print("[+] Auto body fetch complete")
            elif result.get("success"):
                print("[*] Auto body fetch skipped (broad search, media-only hits, or no host/url filter)")

        self._track_analyzed_session(tool_name, arguments or {}, result if isinstance(result, dict) else {})
        return result

    def _parse_tool_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if "result" not in response:
            return {"error": response.get("error", "Tool call failed")}

        result = response["result"]

        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list) and content:
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and "text" in item:
                            text_data = item["text"]
                            if isinstance(text_data, str) and (text_data.strip().startswith('{') or text_data.strip().startswith('[')):
                                try:
                                    return json.loads(text_data)
                                except json.JSONDecodeError:
                                    return {"text": text_data}
                            return {"text": text_data}
                        return item

            if any(key in result for key in ("success", "error", "sessions", "bridge_status")):
                return result

            response_envelope = result.get("response")
            if isinstance(response_envelope, dict):
                data = response_envelope.get("data")
                if data is not None:
                    return data if isinstance(data, dict) else {"data": data}
                return response_envelope

        return result if isinstance(result, dict) else {"result": result}

    def _auto_fetch_session_body(self, search_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Auto-retrieve body for a host/url-filtered text or JS hit; never media."""
        sessions = search_result.get("sessions") or []
        if not sessions:
            return None

        first = self._pick_auto_fetch_session(sessions)
        if not first:
            print("[*] Auto body fetch skipped: no text/html or javascript candidate in results")
            return None

        session_id = str(first.get("id", "")).strip()
        if not session_id:
            return None

        # Extract timestamp info for disambiguation
        received_at = first.get("received_at")
        received_at_iso = first.get("received_at_iso") or first.get("time")
        
        # Check if there are duplicate session IDs with different timestamps
        duplicate_ids = [s for s in sessions if str(s.get("id", "")) == session_id]
        has_duplicates = len(duplicate_ids) > 1
        
        # Build informative log message
        log_msg = f"[*] Auto-fetching body for session {session_id}"
        if received_at_iso:
            log_msg += f" (timestamp: {received_at_iso})"
        if has_duplicates:
            log_msg += f" [WARNING: {len(duplicate_ids)} sessions share this ID]"
        print(log_msg)
        
        response = self.send_mcp_request(
            "tools/call",
            {"name": "fiddler_mcp__session_body", "arguments": {"session_id": session_id}},
        )
        body_data = self._parse_tool_response(response)

        if not isinstance(body_data, dict) or body_data.get("success") is False:
            if isinstance(body_data, dict):
                body_data.setdefault("note", "Automatic session body lookup failed or returned no content.")
            return body_data

        # Add disambiguation metadata to help AI understand which session was fetched
        body_data["_auto_fetch_metadata"] = {
            "fetched_session_id": session_id,
            "fetched_timestamp": received_at_iso,
            "fetched_received_at": received_at,
            "has_duplicate_ids": has_duplicates,
            "note": f"This is session {session_id} from the search results (first match)" 
                    + (f" - WARNING: {len(duplicate_ids)} sessions share this ID with different timestamps" if has_duplicates else "")
        }

        truncated_flag = body_data.get("response_truncated") or body_data.get("truncated")
        size_bytes = body_data.get("content_length")

        # If preview is truncated, request the raw body and persist it to disk.
        # NEW: For large JavaScript files, also request smart extraction for better LLM analysis
        if truncated_flag:
            content_type = body_data.get("content_type", "") or ""
            is_javascript = "javascript" in content_type.lower()
            
            # Determine if we should use smart extraction (large JS files benefit most)
            # Default threshold: 50KB - matches enhanced-bridge MAX_BODY_PREVIEW_BYTES
            use_smart_extract = is_javascript and size_bytes and size_bytes > 50000
            
            if use_smart_extract:
                print(f"[*] Large JavaScript detected ({size_bytes:,} bytes); using smart extraction for session {session_id}...")
            else:
                print(f"[*] Preview for session {session_id} was truncated; requesting full body...")
            
            raw_response = self.send_mcp_request(
                "tools/call",
                {
                    "name": "fiddler_mcp__session_body",
                    "arguments": {
                        "session_id": session_id, 
                        "include_binary": True,
                        "smart_extract": use_smart_extract,  # NEW: Request intelligent extraction
                    },
                },
            )
            raw_data = self._parse_tool_response(raw_response)
            if isinstance(raw_data, dict) and raw_data.get("success"):
                body_data = raw_data
                truncated_flag = body_data.get("response_truncated") or body_data.get("truncated")
                size_bytes = body_data.get("content_length", size_bytes)
            else:
                body_data.setdefault(
                    "auto_note",
                    "Body preview was truncated and full fetch failed; inspect manually via fiddler_mcp__session_body",
                )
                return body_data

        # Check if smart extraction is available (from the bridge response)
        smart_extraction = body_data.get("smart_extraction")
        smart_extraction_available = body_data.get("smart_extraction_available", False)
        
        response_text = body_data.get("response_body") or ""
        
        # NEW: If smart extraction is available, use it for better LLM analysis
        if smart_extraction_available and smart_extraction:
            # Format the smart extraction for LLM consumption
            formatted_extraction = self._format_smart_extraction(smart_extraction)
            
            if formatted_extraction:
                # Use larger snippet limit for curated smart extraction content
                snippet_limit = 24000  # ~24KB of curated, security-relevant content
                
                if len(formatted_extraction) > snippet_limit:
                    body_data["response_body_analyzed"] = (
                        formatted_extraction[:snippet_limit]
                        + "\n\n...[smart extraction shortened for conversation output]"
                    )
                else:
                    body_data["response_body_analyzed"] = formatted_extraction
                
                # Add the analyzed content as the primary response for LLM
                body_data["response_body"] = body_data["response_body_analyzed"]
                body_data["response_body_preview"] = body_data["response_body_analyzed"]
                body_data["analysis_method"] = "smart_extraction"
                
                # Log what was extracted
                metadata = smart_extraction.get("metadata", {})
                patterns_found = metadata.get("patterns_found", [])
                if patterns_found:
                    print(f"[+] Smart extraction found {len(patterns_found)} suspicious patterns: {', '.join(patterns_found[:5])}")
                
                # Still save the full body to disk if enabled
                saved_path = self._save_body_to_file(session_id, response_text)
                if saved_path:
                    body_data["saved_response_path"] = saved_path
                    body_data.setdefault(
                        "auto_note_details",
                        f"Smart extraction from {size_bytes:,} byte file; full response saved to {saved_path}"
                    )
                    body_data["auto_note"] = f"Smart extraction applied; full body saved to {saved_path}"
                else:
                    body_data["auto_note"] = "Smart extraction applied for enhanced analysis"
        
        # FALLBACK: Existing behavior for non-JavaScript or when smart extraction not available
        elif response_text:
            snippet_limit = 8000  # Original limit preserved
            if len(response_text) > snippet_limit:
                body_data["response_body_preview"] = (
                    response_text[:snippet_limit]
                    + "\n\n...[preview shortened for conversation output]"
                )
                body_data["response_body"] = body_data["response_body_preview"]
            else:
                body_data["response_body_preview"] = response_text

            saved_path = self._save_body_to_file(session_id, response_text)
            if saved_path:
                body_data["saved_response_path"] = saved_path
                body_data.setdefault(
                    "auto_note_details",
                    f"Body length reported as {size_bytes} bytes; full response saved to {saved_path}"
                    if size_bytes is not None
                    else f"Full response saved to {saved_path}",
                )
                if not truncated_flag:
                    body_data["auto_note"] = f"Full body retrieved and saved to {saved_path}"
                else:
                    body_data["auto_note"] = f"Body preview truncated; full response saved to {saved_path}"

        request_text = body_data.get("request_body") or ""
        if request_text:
            snippet_limit = 4000
            if len(request_text) > snippet_limit:
                body_data["request_body_preview"] = (
                    request_text[:snippet_limit]
                    + "\n\n...[preview shortened for conversation output]"
                )
                body_data["request_body"] = body_data["request_body_preview"]
            else:
                body_data["request_body_preview"] = request_text

            saved_req_path = self._save_body_to_file(session_id, request_text, kind="request")
            if saved_req_path:
                body_data["saved_request_path"] = saved_req_path

        # Build auto_note with disambiguation info
        base_note = "Full body retrieved" if not truncated_flag else "Body preview truncated; saved full payload to disk"
        if has_duplicates:
            base_note += f" [Session {session_id} at {received_at_iso} - {len(duplicate_ids)} total with this ID]"
        
        body_data.setdefault("auto_note", base_note)
        
        if size_bytes is not None:
            body_data.setdefault("auto_note_details", f"Body length reported as {size_bytes} bytes")

        return body_data

    def _save_body_to_file(self, session_id: str, body_text: str, kind: str = "response") -> Optional[str]:
        if not self.auto_save_full_bodies:
            return None

        try:
            dump_dir = Path(__file__).parent / "session_dumps"
            dump_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_id = str(session_id).replace(os.sep, "_")
            file_path = dump_dir / f"session_{safe_id}_{kind}_{timestamp}.txt"
            file_path.write_text(body_text, encoding="utf-8", errors="replace")
            return str(file_path)
        except Exception as exc:
            print(f"[!] Failed to persist {kind} body for session {session_id}: {exc}")
            return None

    def _format_smart_extraction(self, extraction: dict) -> str:
        """
        Format intelligent extraction data for LLM consumption.
        
        This method takes the smart_extraction dict from the bridge and formats it
        into a structured string that helps the LLM understand the content layout.
        
        Args:
            extraction: Dict with keys: head, tail, suspicious_patterns, metadata
        
        Returns:
            Formatted string combining head, patterns, and tail sections
        """
        if not extraction or not isinstance(extraction, dict):
            return ""
        
        parts = []
        metadata = extraction.get("metadata", {})
        original_size = metadata.get("original_size", 0)
        patterns_found = metadata.get("patterns_found", [])
        
        # Add header with context
        if original_size > 0:
            parts.append(f"[INTELLIGENT EXTRACTION from {original_size:,} byte file]")
            if patterns_found:
                parts.append(f"[Suspicious patterns detected: {', '.join(patterns_found[:10])}]")
            parts.append("")
        
        # Add head section (first 8KB - variable declarations, imports, configs)
        head = extraction.get("head", "")
        if head:
            parts.append("=" * 60)
            parts.append("=== FILE START (first 8KB) ===")
            parts.append("=" * 60)
            parts.append(head)
        
        # Add suspicious patterns section (security-relevant code from middle)
        suspicious = extraction.get("suspicious_patterns", "")
        if suspicious:
            parts.append("")
            parts.append("=" * 60)
            parts.append("=== DETECTED SUSPICIOUS PATTERNS (from middle section) ===")
            parts.append("=" * 60)
            parts.append(suspicious)
        
        # Add tail section (last 4KB - execution logic, callbacks)
        tail = extraction.get("tail", "")
        if tail:
            parts.append("")
            parts.append("=" * 60)
            parts.append("=== FILE END (last 4KB) ===")
            parts.append("=" * 60)
            parts.append(tail)
        
        # Add extraction summary
        if metadata:
            parts.append("")
            parts.append("-" * 40)
            total_extracted = metadata.get("total_extracted", 0)
            patterns_count = metadata.get("patterns_count", 0)
            parts.append(f"[Extraction summary: {total_extracted:,} bytes extracted from {original_size:,} bytes original]")
            if patterns_count > 0:
                parts.append(f"[{patterns_count} suspicious code patterns identified]")
        
        return "\n".join(parts)

    def create_tool_descriptions(self) -> str:
        """Create formatted tool descriptions for Gemini with security focus"""
        if not self.available_tools:
            return "No tools available."
        
        descriptions = ["Available Fiddler MCP Tools:\n"]
        for i, tool in enumerate(self.available_tools, 1):
            name = tool.get("name", "")
            desc = tool.get("description", "No description")
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})
            
            descriptions.append(f"{i}. {name}")
            descriptions.append(f"   Description: {desc}")
            
            # Add security guidance for session_body tool
            if "session_body" in name:
                descriptions.append("   SECURITY NOTE: Use this tool to analyze script behavior, not just content.")
                descriptions.append("   Focus on: DOM manipulation, redirects, iframe injection, anti-analysis patterns.")
            
            if props:
                descriptions.append("   Parameters:")
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required = "required" if param_name in schema.get("required", []) else "optional"
                    descriptions.append(f"     - {param_name} ({param_type}, {required}): {param_desc}")
            descriptions.append("")
        
        # Add note about multiple tool calls
        descriptions.append("\n" + "="*80)
        descriptions.append("IMPORTANT: YOU CAN CALL ANY TOOL MULTIPLE TIMES!")
        descriptions.append("="*80)
        descriptions.append("")
        descriptions.append("You are NOT limited to one tool call per user request.")
        descriptions.append(f"You can call tools up to {self.max_followups} times to gather all necessary information.")
        descriptions.append("")
        descriptions.append("Common multi-call scenarios:")
        descriptions.append("  - List sessions, then analyze multiple session bodies")
        descriptions.append("  - Search for pattern, then examine each matching session")
        descriptions.append("  - Get suspicious sessions, then investigate top 5 in detail")
        descriptions.append("  - Discover attack chain, then trace each stage")
        descriptions.append("")
        descriptions.append("After EACH tool result, you can either:")
        descriptions.append("  a) Make ANOTHER tool call (no permission needed)")
        descriptions.append("  b) Provide your final analysis")
        descriptions.append("")
        descriptions.append("Make calls as needed to provide thorough, complete analysis!")
        descriptions.append("="*80 + "\n")
        
        return "\n".join(descriptions)

    def _get_tool_names_list(self) -> str:
        """Get compact list of available tool names for prompt reinforcement.
        
        This prevents LLM from inventing tool names by reminding it of exact valid names.
        """
        if not self.available_tools:
            return ""
        names = [t.get("name", "") for t in self.available_tools if t.get("name")]
        if not names:
            return ""
        return "AVAILABLE TOOLS (use ONLY these exact names):\n- " + "\n- ".join(names)

    def build_gemini_prompt(self, user_query: str) -> str:
        """Build comprehensive prompt for Gemini"""
        tool_descriptions = self.create_tool_descriptions()
        
        prompt = f"""You are an expert security analyst helping analyze web traffic captured by Fiddler.

{tool_descriptions}

SECURITY ANALYSIS MANDATE - CRITICAL FOR OBFUSCATED CODE:
When encountering obfuscated JavaScript (code with string arrays, hex encoding, complex control flow, or anti-debugging patterns), your primary objective is to perform a SECURITY ANALYSIS. Assume malicious intent until the code's behavior is proven to be benign. Do not accept embedded strings at face value without cross-validating them against the script's executable logic.

ANALYTICAL HIERARCHY - BEHAVIOR OVER CONTENT:
When analyzing a script, you MUST prioritize evidence in the following order:
1. EXECUTABLE ACTIONS: Identify and prioritize analysis of actions that modify the browser environment or user experience. This includes:
   - DOM manipulation (e.g., creating iframe, div, script elements)
   - Style changes (e.g., creating overlays with position:fixed, z-index:99999)
   - Redirection (window.location, document.location)
2. CONTROL FLOW & LOGIC: Analyze conditional checks (if/else), loops, and timers (setTimeout). Pay close attention to conditions that trigger actions, such as checks against:
   - document.referrer
   - localStorage
   - Counters or view limits
3. DATA AND API INTERACTION: Examine how the script interacts with:
   - localStorage
   - document.cookie
   - Network requests
4. STATIC CONTENT (STRINGS): Only after analyzing the behavior should you use embedded strings for context. Be highly skeptical of familiar-looking strings within obfuscated code, as they may be included as decoys to mislead analysis.

MANDATORY MALICIOUS PATTERN CHECKLIST:
For any obfuscated script, you MUST verify the presence or absence of the following patterns:
[ ] Iframe/Script Injection: Does the code dynamically create and append <iframe> or <script> elements to the DOM?
[ ] Redirection: Does the code manipulate window.location or document.location?
[ ] Anti-Analysis Techniques:
    [ ] Does it check document.referrer to alter its behavior?
    [ ] Does it use localStorage or cookies to implement view counters or persistent flags?
    [ ] Does it contain anti-debugging patterns (e.g., debugger; statements inside a loop)?
[ ] Overlay/UI Hijacking: Does the script apply CSS to create full-screen overlays (e.g., position:fixed, z-index:99999, width:100%)?
[ ] Dynamic Code Execution: Is eval() or new Function() used to execute strings as code?

HOLISTIC SYNTHESIS REQUIREMENT:
Your final conclusion MUST synthesize all evidence. If conflicting evidence is found (e.g., telemetry-like strings alongside ad-injection logic), you MUST address the discrepancy. Do not base your conclusion on a single piece of evidence if other behavioral indicators contradict it. State the script's most probable primary purpose based on the weight of the behavioral evidence.

HOW TO ANALYZE OBFUSCATED CODE:
When asked to "explain" or "analyze" a session, follow this structured approach:
1. Request the session body using fiddler_mcp__session_body
2. Identify if the code is obfuscated (string arrays, hex encoding, etc.)
3. If obfuscated, ASSUME MALICIOUS until proven otherwise
4. Analyze BEHAVIOR first:
   - What does the code DO (not what strings it contains)?
   - What DOM elements does it create?
   - What APIs does it call?
   - What conditions trigger its actions?
5. Check against the malicious pattern checklist
6. Only then consider static strings for context
7. Provide a holistic synthesis that reconciles all findings

IMPROVED REQUEST PHRASING EXAMPLES:
Instead of: "explain 265"
Use: "Analyze the behavior of the script in session 265. What actions does it perform on the webpage?"

Instead of: "what is this script doing"
Use: "Analyze session X for any malicious behavior, such as ad injection, redirects, or anti-analysis techniques."

Instead of: "show me the code"
Use: "Attempt to deobfuscate the script in session X and explain its primary function or purpose."

UNDERSTANDING SUSPICIOUS SESSIONS - CRITICAL DISTINCTION:
There are TWO types of suspicious sessions you may encounter:

1. FIDDLER-FLAGGED SUSPICIOUS SESSIONS:
   - Marked by Fiddler's internal risk assessment
   - May have various risk_reasons (large response, suspicious patterns, etc.)
   - Accessed via suspicious_only: true parameter
   - These are based on heuristics, not specific threat intelligence

2. EKFIDDLE-FLAGGED SESSIONS:
   - Have ekfiddle_comment field with SPECIFIC threat intelligence
   - This is AUTHORITATIVE intelligence from the EKFiddle extension
   - These are a SUBSET of suspicious sessions
   - Much higher confidence of actual threats

CRITICAL: Not all suspicious sessions have EKFiddle comments! Be VERY CLEAR about which type you're reporting to avoid confusion.

IOC-FIRST INVESTIGATION RULE (HIGHEST PRIORITY):
If the user names specific domains, hosts, URLs, or IOCs (e.g. cdn.apigateway.co, polygon.rpc.subquery.network):
1. IMMEDIATELY search those hosts with fiddler_mcp__sessions_search using host_pattern (substring, no leading *).
   Example: {{"tool": "fiddler_mcp__sessions_search", "arguments": {{"host_pattern": "cdn.apigateway.co", "limit": 50}}}}
2. Do this BEFORE analyzing Low EKFiddle HTML pages on the landing site.
3. Inspect session_body for matching IOC hosts (JS/HTML) before WordPress theme/plugin noise.
4. ZERO-HIT PROTOCOL: if exact host returns 0 matches:
   a) Search parent apex (e.g. subquery.network, drpc.org, apigateway.co)
   b) Then url_pattern with the IOC string
   c) Then live_sessions / timeline for unique hosts
   d) Do NOT declare CLEAN after a single exact miss
5. Do NOT invent a "query" parameter. Use host_pattern, url_pattern, or content_type only.

EKFIDDLE SEVERITY GATE:
- Critical / High: investigate NOW with session_body
- Medium: investigate after user IOCs and Critical/High
- Low (especially "External Script Monitor [HTML/JS]"): BACKGROUND only unless it matches user IOCs or references external loader hosts named by the user
- Do NOT treat Low External Script Monitor as primary evidence of clickfix / EtherHiding / ErrTraffic

NO REANALYSIS:
- Never re-fetch session_body for a session ID already analyzed in this query
- Prefer new IOC hosts and unexamined Critical/High sessions

WHEN ASKED ABOUT SUSPICIOUS OR EKFIDDLE SESSIONS:

1. IF USER NAMED IOCs: search those hosts first (see IOC-FIRST rule). Otherwise call:
   {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true, "limit": 100, "since_minutes": 360}}}}

2. ANALYZE AND REPORT CLEARLY:
   First, state the TOTALS:
   - "Found X suspicious sessions (Fiddler risk assessment)"
   - "Of these, Y have EKFiddle threat intelligence"
   
   If Y = 0, state clearly: "None of the suspicious sessions have EKFiddle threat intelligence comments."
   
3. CREATE APPROPRIATE LISTS:
   Format output as a table or structured list showing ONLY:
   - Session ID
   - Domain/Host (extract subdomain if present)
   - EKFiddle Comment/Alert Message
   
   Example format when EKFiddle sessions exist:
   ```
   SUMMARY: Found 62 suspicious sessions (Fiddler risk assessment).
   Of these, 3 have EKFiddle threat intelligence:
   
   EKFIDDLE-FLAGGED SESSIONS:
   Session 142 | cdn.malicious-ads.com | High: JavaScript obfuscation with eval()
   Session 158 | tracking.adnetwork.io | Medium: Suspicious redirect chain detected
   Session 201 | evil.example.org      | Critical: Known malware distribution site
   ```
   
   Example format when NO EKFiddle sessions exist:
   ```
   SUMMARY: Found 62 suspicious sessions (Fiddler risk assessment).
   None of these have EKFiddle threat intelligence comments.
   
   The suspicious sessions are based on Fiddler's heuristics (large responses, unusual patterns, etc.)
   but lack specific threat intelligence from EKFiddle.
   ```

3. PRIORITIZE BY SEVERITY:
   - List Critical/High severity first
   - Then Medium
   - Then Low (if present) — do not deep-dive Low External Script Monitor before user IOCs
   - Extract severity from EKFiddle comment (Critical, High, Medium, Low)

4. EXTRACT KEY DOMAINS:
   After the list, summarize unique domains/subdomains that were flagged:
   ```
   FLAGGED DOMAINS TO INVESTIGATE:
   1. cdn.malicious-ads.com (1 session, High severity)
   2. evil.example.org (1 session, Critical severity)
   3. tracking.adnetwork.io (1 session, Medium severity)
   ```

5. SET INVESTIGATION FOCUS:
   If user named IOCs, those hosts remain PRIMARY. Otherwise:
   End with: "Critical/High EKFiddle sessions should be the PRIMARY focus.
   To analyze the code, use: fiddler_mcp__session_body with the session ID."

WHEN ASKED ABOUT MALICIOUS/SUSPICIOUS SESSIONS IN FOLLOW-UP:
If user asks "are there any malicious sessions?" or "show me suspicious traffic" AFTER you've listed EKFiddle flags:

1. If user previously named IOC hosts still unsearched, search those first
2. Otherwise AUTOMATICALLY FETCH CODE from the HIGHEST SEVERITY (Critical/High) EKFiddle session:
   {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "<highest_severity_id>"}}}}
3. Skip Low External Script Monitor unless it is the only signal and no user IOCs remain

2. APPLY SECURITY ANALYSIS FRAMEWORK to that code
3. CORRELATE your analysis with the EKFiddle comment
4. If EKFiddle says "JavaScript obfuscation", LOOK FOR obfuscation patterns
5. If EKFiddle says "redirect chain", LOOK FOR window.location manipulation
6. If EKFiddle says "eval()", LOOK FOR dynamic code execution

EKFIDDLE COMMENT INTERPRETATION:
Common EKFiddle patterns and what to look for:
- "JavaScript obfuscation" → Check for string arrays, hex encoding, packed code
- "eval()" or "Function constructor" → Dynamic code execution pattern
- "redirect" → window.location, document.location manipulation
- "suspicious domain" → Check domain reputation, TLD
- "known malware" → Treat as HIGH PRIORITY threat
- "exploit kit" → Advanced threat, check for CVE references
- "External Script Monitor" (Low) → Often WP performance lazy-load; confirm against user IOCs before deep dive

TRUST HIERARCHY for THREAT ASSESSMENT:
1. HIGHEST: User-supplied IOC hosts/URLs (search these first)
2. HIGH: EKFiddle Critical/High comments
3. MEDIUM: Behavioral analysis (malicious pattern checklist)
4. LOWER: EKFiddle Low / heuristics
5. LOWEST: String content (easily manipulated)

If EKFiddle Critical/High flagged something, focus on CONFIRMING the threat type. Low flags need IOC correlation.

EKFIDDLE RULE AUTHORING (when user asks for EKFiddle rules / CustomRegexes / signatures):
This is a HARD TASK MODE. Follow the EKFiddle CustomRegexes skill bar exactly:

1. If the user names a session ID, call fiddler_mcp__session_body for that session ONCE only if it is not already analyzed this query.
2. Extract ONLY high-signal malicious patterns actually present in the tool results:
   - Compound JSON-RPC: method:'eth_call' with jsonrpc:'2.0' and eth_call params shape, not bare eth_call alone
   - Overlay UI hijack: z-index:2147483647 with position:fixed and iframe or clipboard-write
   - Distinctive hex decode loops when unique enough; prefer technique over one hex function name
   - Distinctive cookies or sendBeacon telemetry strings that are campaign-specific
   - Domains / URIs / IPs that appear in the body, captured traffic, or the user query
3. Emit rules in EXACT tab-separated CustomRegexes schema (TABS not spaces):
   [Type]	[Severity]: [Rule Name]	[Regex]	[Optional Comment]
   Types: SourceCode | URI | IP | Headers | Hash
   Severity MUST be High: or Med: or Low: including the colon. Never write Medium:
   Rule names: title case with spaces, threat-specific. No snake_case. No vague Potential X names.
4. Write a short explanation per rule that includes The crucial pattern or The key pattern.
5. End the answer with a plain block of ONLY the tab-separated rule lines so they can be copied into CustomRegexes.txt.
6. STOP after delivering rules. Do NOT chase Low External Script Monitor siblings. Do NOT invent hosts not present in tool results.
7. Do NOT refuse defensive CustomRegex generation when the user asks. Provide the rules.
8. Do NOT emit Name/Regex/Comment/Color tables, slash-wrapped /regex/i, or markdown tables as the rule format.
9. Prefer SourceCode rules for unique malicious JS. Use URI/IP only for IOCs observed in data or supplied by the user.
10. Keep regexes bounded and specific: use {{0,120}} / [^}}]{{1,200}}, escape \\. \\( \\), non-capturing (?:...), avoid unbounded .*. Prefer 2 to 6 strong rules.
11. FORBIDDEN unless user explicitly asks: bare \\beth_call\\b, _\\w{{7,8}}\\(\\), NitroPack / ___mnag / text/lazyload MutationObserver, createElement alone, appendChild alone.
12. If improving a prior rule for false positives, tighten with compound tokens. Do not replace it with an unrelated or broken regex.

Example correct rule lines:
SourceCode	High: ErrTraffic eth_call RPC	method\\s*:\\s*['\"]eth_call['\"].{{0,80}}jsonrpc\\s*:\\s*['\"]2\\.0['\"]
SourceCode	High: EtherHiding Fullscreen Overlay	z-index\\s*:\\s*2147483647.{{0,120}}position\\s*:\\s*fixed
URI	High: ErrTraffic Delivery Host	cdn\\.apigateway\\.co

ZERO-HIT AND INFECTION CHAIN:
- If the user lists many IOC hosts and the first search returns 0, do not serially hunt every host. Report missing hosts, then use landing-page session bodies and prior findings.
- When asked for the infection chain, explain stages from evidence even if RPC hosts are not currently in the buffer.
- Low External Script Monitor is not a clean bill of health when eth_call or etherhiding patterns are present.
- Prefer session_body over session_headers. Treat headers 404 as non-fatal.
- Do not emit Low: CustomRegexes for confirmed Benign or False Positive libraries unless the user asks for FP monitors.

INVESTIGATE CAPTURE (when user asks to investigate the buffer / malicious traffic / /investigate):
1. live_stats then ekfiddle_threats or ekfiddle_sessions; Critical/High first
2. Fetch a few highest-severity JS/HTML bodies; skip Low External Script Monitor unless IOCs demand it
3. Pivot sessions_search on hosts found in those bodies; keep zero-hit budget tight
4. Trace landing to loader to C2/RPC to payload/overlay
5. Structured summary: Infection chain, hosts/IOCs, verdict; EKFiddle rules only for malicious high-signal evidence

NO INVENTED IOCs:
- Never invent domains, IPs, cookies, or function names that did not appear in tool results or the user query.
- If a host search returns 0, say so. Do not fabricate related infrastructure.

CRITICAL INSTRUCTIONS FOR TOOL CALLING (legacy text path only):
NOTE: Prefer native Gemini FunctionDeclarations when GEMINI_NATIVE_TOOLS=1.
If you must emit a text tool call, use JSON-ONLY with the tool LAST:
{{"tool": "tool_name", "arguments": {{"param": "value"}}}}

RULES:
1. Use ONLY MCP tools from the list above. Do not invent names.
2. MAKE ONE TOOL CALL AT A TIME
3. session_id must be a plain string like "262", never an object
4. sessions_search has NO "query" field — use host_pattern / url_pattern / content_type
5. Do not use leading * in host_pattern (use "drpc.org" not "*drpc.org")
6. Prefer fiddler_mcp__ekfiddle_threats / ekfiddle_sessions for triage before bodies

MULTI-SESSION COMPARISON:
When user asks to COMPARE 2-10 sessions, use fiddler_mcp__compare_sessions.
When asking about ONE session, use fiddler_mcp__session_body.

MULTIPLE TOOL CALLS - YOU CAN CALL TOOLS REPEATEDLY:

IMPORTANT: You are ALLOWED and ENCOURAGED to call tools multiple times to provide complete analysis!

YOU CAN MAKE UP TO {self.max_followups} TOOL CALLS in a single user request if needed to:
- Analyze multiple sessions sequentially (e.g., top 5 EKFiddle sessions)
- Fetch additional context after initial analysis
- Investigate related sessions discovered during analysis
- Gather comprehensive information for thorough security assessment
- Follow investigation leads as they emerge

HOW MULTIPLE TOOL CALLS WORK:

1. Make Initial Tool Call:
   {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true, "limit": 100}}}}

2. After Receiving Results, You Can:
   a) Provide final analysis (if you have enough information)
   b) Make ANOTHER tool call to get more data (you don't need permission!)

3. Example Multi-Call Flow:
   First call:  List suspicious sessions
   Second call: Get body of highest risk session
   Third call:  Get body of another related session
   Fourth call: Search for similar patterns
   [Continue until you have complete picture, up to {self.max_followups} calls total]

4. When to Make Additional Calls:
   - You found suspicious sessions and need to examine their code
   - Initial session reveals references to other sessions
   - User asks for "comprehensive" or "detailed" analysis
   - You need to verify findings across multiple sessions
   - Investigation uncovers new leads
   - You need more context to provide confident assessment

5. When to Stop Making Calls:
   - You have sufficient information to answer the user's question
   - You've examined the most critical sessions
   - You've reached {self.max_followups} tool calls (system limit)
   - User explicitly asks for summary/conclusion

EXAMPLE WORKFLOWS WITH MULTIPLE CALLS:

Example 1: Analyzing EKFiddle Sessions
Query: "Analyze EKFiddle sessions in detail"

Call 1: {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true}}}}
Result: Found 5 EKFiddle-flagged sessions

Call 2: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "312"}}}}
Analysis: Session 312 has eval() - HIGH RISK

Call 3: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "287"}}}}
Analysis: Session 287 has redirect chain - MEDIUM RISK

Call 4: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "156"}}}}
Analysis: Session 156 is benign false positive

Final Response: Comprehensive threat assessment of all 3 sessions

Example 2: Investigating Attack Chain
Query: "Investigate suspicious sessions"

Call 1: {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true}}}}
Result: Found suspicious iframe injection in session 100

Call 2: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "100"}}}}
Analysis: Session 100 loads external script from session 105

Call 3: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "105"}}}}
Analysis: Session 105 is the malicious payload

Final Response: Explains the 2-stage attack chain

IMPORTANT: Don't announce "I will make X calls" - just make them as needed!
Between each call, provide brief progress: "Analyzing session X..." then continue.

IMPORTANT WORKFLOW RULES:
- When user asks for EKFiddle rules / CustomRegexes / signatures for a named session → fetch that body once if needed, emit tab-separated rules, STOP
- When user names IOC domains → search those hosts FIRST with host_pattern before any Low EKFiddle HTML body analysis
- When user explicitly requests COMPARISON of multiple sessions → Use fiddler_mcp__compare_sessions (efficient, one call)
- When analyzing EKFiddle or suspicious sessions sequentially → Fetch ONE at a time with fiddler_mcp__session_body, make multiple calls
- DO NOT list "I will call session X, Y, Z..." - just make the calls as you analyze
- After each call, provide brief NEW findings THEN decide if another call is needed
- DO NOT repeat previous summaries - each response should ADD NEW information only
- Focus on user IOCs and Critical/High first; skip Low External Script Monitor until IOCs are covered
- Never re-fetch a session body already analyzed in this query
- Never invent hosts or IOCs not present in tool results
- You have a limit of {self.max_followups} tool calls per user query - use them wisely

PERFORMANCE OPTIMIZATION INSTRUCTIONS:
1. Be CONCISE in your initial responses - acknowledge the request in 1 sentence
2. For tool calls, don't provide lengthy explanations beforehand
3. After getting results, provide analysis WITHOUT repeating all raw data
4. If listing items, show only ESSENTIAL information (ID, domain, key finding)
5. Keep responses focused and actionable
6. Offer to provide more detail if needed, don't dump everything at once

RESPONSE SPEED PRIORITY:
- Make tool calls immediately without preamble
- Analyze results efficiently  
- Keep initial responses under 10 lines unless specifically asked for detail
- Focus on answering the specific question asked
- Prefer JSON-only tool calls; put any short analysis BEFORE the JSON, not after

CONVERSATION CONTEXT:
{self._format_recent_history(5)}

USER QUERY: {user_query}

YOUR RESPONSE (if tool needed, use JSON format above; otherwise natural language):"""
        return prompt

    def _format_recent_history(self, limit: int = 5) -> str:
        """Format recent conversation history"""
        if not self.conversation_history:
            return "No previous conversation."
        
        recent = self.conversation_history[-limit:]
        formatted = []
        for entry in recent:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            formatted.append(f"[{role}] {content}")
        
        return "\n".join(formatted)

    def parse_gemini_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse Gemini response for tool calls - handles multiple formats"""
        import re
        
        response_text = response_text.strip()
        
        if not response_text:
            return None
        
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]).strip()
        
        try:
            data = json.loads(response_text)
            return self._process_tool_call_data(data)
        except json.JSONDecodeError:
            pass
        
        json_patterns = [
            r'\{(?:[^{}]|\{[^{}]*\})*"tool(?:_code)?"(?:[^{}]|\{[^{}]*\})*\}',
            r'\[(?:[^\[\]]|\[[^\[\]]*\])*"tool(?:_code)?"(?:[^\[\]]|\[[^\[\]]*\])*\]',
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    result = self._process_tool_call_data(data)
                    if result:
                        print("  Extracted tool call from mixed text/JSON response")
                        return result
                except json.JSONDecodeError:
                    continue
        
        plain_text_pattern = r'(fiddler_mcp__\w+)\((.*?)\)'
        match = re.search(plain_text_pattern, response_text)
        if match:
            tool_name = match.group(1)
            args_str = match.group(2)
            
            arguments = {}
            arg_matches = re.findall(r'(\w+)=(["\']?)([^,\'"]+)\2', args_str)
            for key, quote, value in arg_matches:
                if not quote and value.isdigit():
                    arguments[key] = int(value)
                else:
                    arguments[key] = value
            
            print(f"  Gemini used plain text format instead of JSON")
            print(f"    Extracted: {tool_name} with arguments {arguments}")
            return {"tool": tool_name, "arguments": arguments}
        
        return None
    
    def _extract_text_before_tool_call(self, response_text: str) -> str:
        """Extract text before tool call"""
        import re
        
        response_text = response_text.strip()
        
        json_patterns = [
            r'\{(?:[^{}]|\{[^{}]*\})*"tool(?:_code)?"(?:[^{}]|\{[^{}]*\})*\}',
            r'\[(?:[^\[\]]|\[[^\[\]]*\])*"tool(?:_code)?"(?:[^\[\]]|\[[^\[\]]*\])*\]',
        ]
        
        earliest_pos = len(response_text)
        
        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                earliest_pos = min(earliest_pos, match.start())
        
        plain_text_pattern = r'(fiddler_mcp__\w+)\('
        plain_match = re.search(plain_text_pattern, response_text)
        if plain_match:
            earliest_pos = min(earliest_pos, plain_match.start())
        
        if earliest_pos < len(response_text):
            explanatory_text = response_text[:earliest_pos].strip()
            explanatory_text = re.sub(r'(Tool Call|Next):\s*$', '', explanatory_text, flags=re.IGNORECASE).strip()
            return explanatory_text
        
        return response_text
    
    def _process_tool_call_data(self, data: Any) -> Optional[Dict[str, Any]]:
        """Process parsed JSON to extract tool call"""
        import re
        
        if isinstance(data, list):
            print(f"  Gemini returned multiple tool calls ({len(data)} calls)")
            print("   Processing first call only (will chain the rest)")
            if data:
                data = data[0]
            else:
                return None
        
        if not isinstance(data, dict):
            return None
        
        if "tool" in data and "arguments" in data:
            return data
        
        if "tool_code" in data:
            print("  Gemini used incorrect tool_code format instead of MCP tool calling")
            print("   Attempting to extract tool call from code...")
            
            code = data.get("tool_code", "")
            tool_name = None
            args_str = None
            
            match = re.search(r'(fiddler_mcp__\w+)\((.*?)\)', code)
            if match:
                tool_name = match.group(1)
                args_str = match.group(2)
            else:
                match = re.search(r'fiddler_mcp\.(\w+)\((.*?)\)', code)
                if match:
                    tool_suffix = match.group(1)
                    tool_name = f"fiddler_mcp__{tool_suffix}"
                    args_str = match.group(2)
            
            if tool_name and args_str is not None:
                arguments = {}
                arg_matches = re.findall(r'(\w+)=[\'"]([^\'"]+)[\'"]', args_str)
                for key, value in arg_matches:
                    arguments[key] = value
                
                print(f"    Extracted: {tool_name} with arguments {arguments}")
                return {"tool": tool_name, "arguments": arguments}
        
        return None
    
    def _looks_like_markdown(self, text: str) -> bool:
        """Detect if text contains markdown"""
        if not text or len(text) < 3:
            return False
        
        markdown_indicators = ['**', '__', '`', '# ', '## ', '### ', '* ', '- ', '+ ', '[', '|']
        return any(indicator in text for indicator in markdown_indicators)

    def _chat_native(self, user_query: str) -> str:
        """Native Gemini function-calling loop with MCP call_tool as execution gate."""
        import gemini_native_tools as native
        from google.generativeai import protos

        query_start_time = time.time()
        total_gemini_time = 0.0
        total_bridge_time = 0.0
        tool_call_count = 0
        max_calls = self.max_followups

        history_snip = self._format_recent_history()
        user_text = (
            f"Analyst question: {user_query}\n\n"
            f"{self._analyzed_sessions_note()}\n\n"
            f"Recent conversation:\n{history_snip}\n\n"
            "Use tools as needed. Prefer ekfiddle_threats/ekfiddle_sessions for triage, "
            "sessions_search for host hunts, session_body for deep analysis, "
            "compare_sessions when asked to compare. "
            "ZERO-HIT: after one missed host on a user IOC list, stop serial hunting; "
            "report missing hosts and continue from bodies or prior findings. "
            "EKFiddle rules: High:/Med:/Low: only, title-case names, compound high-signal "
            "regexes with bounded quantifiers, The crucial/key pattern explanations, then "
            "plain tab-separated rule lines and STOP. No bare eth_call, no _\\w{{7,8}}\\(\\), "
            "no NitroPack/lazyload unless asked. Answer infection-chain questions from "
            "prior evidence when bodies were already analyzed."
        )
        contents: List[Any] = [
            protos.Content(role="user", parts=[protos.Part(text=user_text)])
        ]

        try:
            if self.show_progress:
                print(f"  (Native tools: up to {max_calls} calls. Ctrl+C stops this chain)")

            while tool_call_count < max_calls:
                self._check_interrupt()
                sys.stdout.write("\r  Waiting for Gemini LLM (native tools)...")
                sys.stdout.flush()
                gemini_start = time.time()
                response = self.model.generate_content(
                    contents,
                    tool_config=native.tool_config("AUTO"),
                )
                self._check_interrupt()
                gemini_elapsed = time.time() - gemini_start
                total_gemini_time += gemini_elapsed
                sys.stdout.write(f"\r  [Gemini LLM] Response ({gemini_elapsed:.1f}s)                    \n")
                sys.stdout.flush()

                calls = native.extract_function_calls(response)
                text = native.extract_text_parts(response)

                # Fallback: legacy text JSON tool call if no native function_call parts
                if not calls and text:
                    legacy = self.parse_gemini_response(text)
                    if legacy:
                        calls = [{"name": legacy["tool"], "args": legacy.get("arguments") or {}}]

                if not calls:
                    final = text or "No response from model."
                    self.conversation_history.append({"role": "assistant", "content": final})
                    self.log_with_timestamp(
                        f"Query Summary: native_tools, gemini={total_gemini_time:.1f}s, "
                        f"bridge={total_bridge_time:.1f}s, tool_calls={tool_call_count}",
                        to_console=False,
                    )
                    return self._finalize_assistant_response(final)

                model_content = native.model_content_from_response(response)
                if model_content is not None:
                    contents.append(model_content)
                else:
                    # Reconstruct model turn from extracted calls
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
                    contents.append(protos.Content(role="model", parts=parts))

                if text and text.strip():
                    # Show interim analyst notes
                    if self.use_rich and self.console:
                        self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                        self.console.print(text)
                    else:
                        print(f"\n< Gemini: {text}")
                    self.maybe_persist_ekfiddle_rules(text)

                response_parts = []
                for call in calls:
                    self._check_interrupt()
                    name = call["name"]
                    args = call.get("args") or {}
                    if self.show_progress:
                        print(self._brief_tool_status(name, args))
                    bridge_start = time.time()
                    result = self.call_tool(name, args)
                    bridge_elapsed = time.time() - bridge_start
                    total_bridge_time += bridge_elapsed
                    tool_call_count += 1
                    self.log_with_timestamp(
                        f"Tool Chain: call #{tool_call_count} -> {name} ({bridge_elapsed*1000:.0f}ms)",
                        to_console=False,
                    )
                    self.conversation_history.append({
                        "role": "tool",
                        "tool": name,
                        "content": json.dumps(result, indent=2, default=str)[:8000],
                    })
                    response_parts.append(native.build_function_response_part(name, result))

                nudge = (
                    f"{self._analyzed_sessions_note()}\n"
                    "Continue investigation or give the final answer. "
                    "If user asked for EKFiddle rules and you have malicious SourceCode evidence, "
                    "emit tab-separated rules now and stop calling tools."
                )
                response_parts.append(protos.Part(text=nudge))
                contents.append(protos.Content(role="user", parts=response_parts))

            # Budget exhausted — force text-only synthesis
            self.log_with_timestamp(
                f"Native tools: budget exhausted after {tool_call_count} calls",
                to_console=False,
            )
            synth_prompt = (
                f"Tool call budget exhausted ({max_calls}). Do NOT call tools.\n"
                f"User question: {user_query}\n"
                f"{self._analyzed_sessions_note()}\n"
                "Provide FINAL SYNTHESIS. If EKFiddle rules were requested, emit best "
                "tab-separated CustomRegexes from evidence already gathered. Do not invent IOCs."
            )
            contents.append(protos.Content(role="user", parts=[protos.Part(text=synth_prompt)]))
            sys.stdout.write("\r  Waiting for Gemini LLM final synthesis...")
            sys.stdout.flush()
            synth_start = time.time()
            synth_resp = self.model.generate_content(
                contents,
                tool_config=native.tool_config("NONE"),
            )
            total_gemini_time += time.time() - synth_start
            sys.stdout.write(f"\r  [Gemini LLM] Final synthesis complete                    \n")
            sys.stdout.flush()
            final = native.extract_text_parts(synth_resp) or "Tool budget reached."
            self.conversation_history.append({"role": "assistant", "content": final})
            self.log_with_timestamp(
                f"Query Summary: native_tools budget, gemini={total_gemini_time:.1f}s, "
                f"bridge={total_bridge_time:.1f}s, total={time.time()-query_start_time:.1f}s, "
                f"tool_calls={tool_call_count}",
                to_console=False,
            )
            return self._finalize_assistant_response(final)

        except KeyboardInterrupt:
            self.clear_interrupt()
            # Ctrl+C can still kill an unprotected child on some hosts; recover immediately
            if not self.is_mcp_alive():
                print("[!] MCP child died during interrupt; attempting restart...")
                self.ensure_mcp_alive()
            interrupt_msg = (
                "\n\n[INTERRUPTED] Stopped the current tool chain. "
                "Conversation context is preserved. Ask a follow-up or type /quit to exit."
            )
            print(interrupt_msg)
            self.conversation_history.append({"role": "system", "content": "[User interrupted the response]"})
            return interrupt_msg
        except Exception as e:
            error_msg = f"Error processing query (native tools): {e}"
            self.conversation_history.append({"role": "error", "content": error_msg})
            return error_msg

    def chat(self, user_query: str) -> str:
        """Process user query with Gemini and execute tools as needed
        
        User can press Ctrl+C at any time to interrupt the model's response chain.
        """
        # Log the new query (log file only)
        self.log_with_timestamp(f"User query: {user_query[:100]}{'...' if len(user_query) > 100 else ''}", to_console=False, prefix="Client: ")
        
        # Reset per-query investigation state
        self._analyzed_session_ids = set()
        self._last_search_args = {}
        self.clear_interrupt()
        self._current_user_query = user_query

        # Recover MCP if a prior Ctrl+C killed the child process group
        if not self.ensure_mcp_alive():
            err = (
                "MCP server is not running and restart failed. "
                "Restart gemini-fiddler-client.py or start 5ire-bridge.py manually."
            )
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append({"role": "error", "content": err})
            return err
        
        # Add user query to history
        self.conversation_history.append({"role": "user", "content": user_query})

        if self.use_native_tools and self._gemini_tool is not None:
            return self._chat_native(user_query)
        
        # Build prompt
        self.log_with_timestamp("Building comprehensive prompt for Gemini...", to_console=False, prefix="Client: ")
        prompt = self.build_gemini_prompt(user_query)
        
        def extract_text_safe(resp) -> str:
            """Safely extract text from Gemini response, even if no Parts were returned."""
            try:
                return resp.text  # fast path
            except Exception:
                pass
            try:
                # Fallback: manual extraction
                candidates = getattr(resp, "candidates", []) or []
                if not candidates:
                    return ""
                first = candidates[0]
                # Log finish_reason if present
                finish_reason = getattr(first, "finish_reason", None)
                if finish_reason is not None and self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    self.mcp_stderr_file.write(f"[{ts}] Gemini finish_reason: {finish_reason}\n")
                    self.mcp_stderr_file.flush()
                content = getattr(first, "content", None)
                parts = getattr(content, "parts", []) if content else []
                # Concatenate any text parts
                texts = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if isinstance(t, str) and t:
                        texts.append(t)
                return "\n".join(texts)
            except Exception:
                return ""

        # Track timing for query summary
        query_start_time = time.time()
        total_gemini_time = 0.0
        total_bridge_time = 0.0
        tool_call_count = 0
        
        try:
            # Get Gemini response with progress indicator (user can interrupt with Ctrl+C)
            prompt_length = len(prompt)
            estimated_tokens = self._estimate_tokens(prompt)
            
            # Enhanced Gemini request logging
            self.log_with_timestamp(f"Gemini Request: model={self.model_name}, type=initial_query", to_console=False)
            self.log_with_timestamp(f"Gemini Request: prompt_length={prompt_length} chars (~{estimated_tokens} tokens)", to_console=False)
            self.log_with_timestamp(f"Gemini Request: user_query=\"{user_query[:80]}{'...' if len(user_query) > 80 else ''}\"", to_console=False)
            
            # Show console feedback while waiting for Gemini
            sys.stdout.write("\r  Waiting for Gemini LLM response...")
            sys.stdout.flush()
            
            start_time = time.time()
            self._check_interrupt()
            response = self.model.generate_content(prompt)
            self._check_interrupt()
            elapsed_ms = int((time.time() - start_time) * 1000)
            elapsed_s = elapsed_ms / 1000
            total_gemini_time += elapsed_s
            
            # Clear the waiting message and show completion
            sys.stdout.write(f"\r  [Gemini LLM] Response received ({elapsed_s:.1f}s)                    \n")
            sys.stdout.flush()
            
            gemini_text = extract_text_safe(response)
            finish_reason = self._extract_finish_reason(response)
            candidates_count = self._count_candidates(response)
            
            # Enhanced Gemini response logging
            self.log_with_timestamp(f"Gemini Response: {elapsed_ms}ms, response_length={len(gemini_text)} chars", to_console=False)
            self.log_with_timestamp(f"Gemini Response: finish_reason={finish_reason}, candidates={candidates_count}", to_console=False)
            
            # If model produced no text (e.g., finish_reason blocked), retry once with stricter prompt
            if not gemini_text:
                self.log_with_timestamp(f"Gemini Warning: finish_reason={finish_reason}, response blocked/empty", to_console=False)
                self.log_with_timestamp("Gemini Warning: retrying with stricter prompt (temperature=0)", to_console=False)
                retry_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with the JSON tool call format if a tool is needed, or a concise sentence otherwise."
                # Low temperature to reduce safety blocks/hallucinations
                start_retry = time.time()
                response = self.model.generate_content(retry_prompt, generation_config={"temperature": 0})
                retry_elapsed_ms = int((time.time() - start_retry) * 1000)
                total_gemini_time += retry_elapsed_ms / 1000
                retry_finish_reason = self._extract_finish_reason(response)
                self.log_with_timestamp(f"Gemini Retry: {retry_elapsed_ms}ms, finish_reason={retry_finish_reason}", to_console=False)
                gemini_text = extract_text_safe(response)
            
            # Check if Gemini wants to call a tool
            tool_call = self.parse_gemini_response(gemini_text)
            
            # Log tool detection result
            if tool_call:
                tool_name = tool_call["tool"]
                arguments = tool_call["arguments"]
                args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
                self.log_with_timestamp(f"Gemini Response: tool_call detected: {tool_name}({args_str})", to_console=False)
                self.log_with_timestamp(f"Tool Chain: starting (max_followups={self.max_followups})", to_console=False)
                
                # Execute the tool with timing
                bridge_start = time.time()
                tool_result = self.call_tool(tool_name, arguments)
                bridge_elapsed = time.time() - bridge_start
                total_bridge_time += bridge_elapsed
                tool_call_count += 1
                self.log_with_timestamp(f"Tool Chain: call #{tool_call_count} -> {tool_name} ({bridge_elapsed*1000:.0f}ms)", to_console=False)
                
                # Add tool result to history
                self.conversation_history.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps(tool_result, indent=2)
                })
                
                # Ask Gemini to analyze the tool result with security framework
                self.log_with_timestamp("Preparing analysis prompt for tool results...", to_console=False, prefix="Client: ")
                
                analysis_prompt = f"""The tool '{tool_name}' returned this result:

{json.dumps(tool_result, indent=2)}

CRITICAL: Apply the SECURITY ANALYSIS FRAMEWORK to analyze this result.

User's original question: "{user_query}"

{self._analyzed_sessions_note()}

ANALYSIS REQUIREMENTS:
1. If the user asked for EKFiddle rules / CustomRegexes / signatures:
   - Use this tool result to extract high-signal malicious patterns only
   - Emit tab-separated rules NOW: Type	Severity: Name	Regex	Comment
   - Types: SourceCode URI IP Headers Hash. Severity: High: Med: Low:
   - End with a plain block of ONLY rule lines. Then STOP. No more tool calls.
   - Do NOT invent IOCs. Do NOT write NitroPack/___mnag rules unless asked.
2. Otherwise IOC-FIRST: search user-named hosts with host_pattern BEFORE Low EKFiddle HTML.
3. Distinguish suspicious vs EKFiddle-flagged; Critical/High first; Low External Script Monitor last.
4. ZERO-HIT: if a host search returned 0 matches, search parent apex / url_pattern next. Do not invent hosts.
5. Do NOT re-fetch session bodies already listed above.
6. If response_body contains JavaScript, focus on BEHAVIOR over strings.

{self._get_tool_names_list()}

IMPORTANT: Do NOT invent tool names. Use ONLY the tools listed above.
session_id must be a plain string. sessions_search has no "query" field — use host_pattern / content_type.
If you need to call another tool, put brief findings then JSON: {{"tool": "tool_name", "arguments": {{...}}}}

Otherwise, provide your security-focused analysis or EKFiddle rules."""
                
                # Log tool result size for context
                tool_result_str = json.dumps(tool_result, indent=2)
                tool_result_size = len(tool_result_str)
                analysis_prompt_len = len(analysis_prompt)
                self.log_with_timestamp(f"Gemini Request: type=tool_analysis, tool_result_size={self._format_size(tool_result_size)}", to_console=False)
                self.log_with_timestamp(f"Gemini Request: analysis_prompt_length={analysis_prompt_len} chars (~{self._estimate_tokens(analysis_prompt)} tokens)", to_console=False)
                
                # Show console feedback
                sys.stdout.write("\r  Waiting for Gemini LLM analysis...")
                sys.stdout.flush()
                
                analysis_start = time.time()
                self._check_interrupt()
                analysis_response = self.model.generate_content(analysis_prompt)
                self._check_interrupt()
                analysis_elapsed_ms = int((time.time() - analysis_start) * 1000)
                analysis_elapsed_s = analysis_elapsed_ms / 1000
                total_gemini_time += analysis_elapsed_s
                
                # Show completion
                sys.stdout.write(f"\r  [Gemini LLM] Analysis complete ({analysis_elapsed_s:.1f}s)                    \n")
                sys.stdout.flush()
                
                final_text = extract_text_safe(analysis_response)
                analysis_finish_reason = self._extract_finish_reason(analysis_response)
                
                # Enhanced analysis response logging
                self.log_with_timestamp(f"Gemini Response: {analysis_elapsed_ms}ms, response_length={len(final_text)} chars", to_console=False)
                self.log_with_timestamp(f"Gemini Response: finish_reason={analysis_finish_reason}", to_console=False)
                
                # If blocked, provide helpful error message
                if not final_text:
                    self.log_with_timestamp(f"Gemini Warning: finish_reason={analysis_finish_reason}, analysis blocked", to_console=False)
                    final_text = "Analysis blocked by safety filters. This may indicate the content contains potentially harmful code. Try: 'Analyze session X for malicious patterns' with a fresh request."
                
                current_text = final_text
                max_followups = self.max_followups
                followup_count = 0
                
                # Inform user they can interrupt if needed
                if self.show_progress:
                    print(f"  (Model can make up to {max_followups} tool calls. Press Ctrl+C to stop this chain and keep chatting)")
                
                while followup_count < max_followups:
                    self._check_interrupt()
                    next_tool_call = self.parse_gemini_response(current_text)
                    
                    if not next_tool_call:
                        # Log completion with query summary
                        total_time = time.time() - query_start_time
                        self.log_with_timestamp(f"Gemini Response: no further tool calls, providing analysis", to_console=False)
                        self.log_with_timestamp(f"Tool Chain: completed after {tool_call_count} tool calls", to_console=False)
                        self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                        self.log_with_timestamp(f"Query Summary: tool_calls={tool_call_count}, follow_ups={followup_count}", to_console=False)
                        self.conversation_history.append({"role": "assistant", "content": current_text})
                        return self._finalize_assistant_response(current_text)
                    
                    explanatory_text = self._extract_text_before_tool_call(current_text)
                    
                    if explanatory_text.strip():
                        self.maybe_persist_ekfiddle_rules(explanatory_text)
                        self.conversation_history.append({"role": "assistant", "content": explanatory_text})
                        if self.use_rich and self.console:
                            self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                            if self._looks_like_markdown(explanatory_text):
                                from rich.markdown import Markdown
                                md = Markdown(explanatory_text)
                                self.console.print(md)
                            else:
                                self.console.print(explanatory_text)
                        else:
                            print(f"\n< Gemini: {explanatory_text}")
                    
                    next_tool_name = next_tool_call["tool"]
                    next_arguments = next_tool_call["arguments"]
                    next_args_str = ", ".join(f"{k}={v}" for k, v in next_arguments.items())
                    self.log_with_timestamp(f"Gemini Response: tool_call detected: {next_tool_name}({next_args_str})", to_console=False)
                    
                    # Execute follow-up tool with timing
                    self._check_interrupt()
                    bridge_start = time.time()
                    next_tool_result = self.call_tool(next_tool_name, next_arguments)
                    self._check_interrupt()
                    bridge_elapsed = time.time() - bridge_start
                    total_bridge_time += bridge_elapsed
                    tool_call_count += 1
                    self.log_with_timestamp(f"Tool Chain: call #{tool_call_count} -> {next_tool_name} ({bridge_elapsed*1000:.0f}ms)", to_console=False)
                    
                    self.conversation_history.append({
                        "role": "tool",
                        "tool": next_tool_name,
                        "content": json.dumps(next_tool_result, indent=2)
                    })
                    
                    followup_prompt = f"""The tool '{next_tool_name}' returned this result:

{json.dumps(next_tool_result, indent=2)}

CRITICAL: Apply SECURITY ANALYSIS FRAMEWORK. Analyze ONLY this new data. DO NOT repeat previous summary.

User's original question: "{user_query}"

{self._analyzed_sessions_note()}

ANALYSIS REQUIREMENTS:
1. If the user asked for EKFiddle rules / CustomRegexes / signatures and you have malicious SourceCode evidence:
   - Emit final tab-separated rules NOW and STOP. No more session hopping.
   - Format: Type	Severity: Name	Regex	OptionalComment
   - Do NOT invent IOCs. Do NOT target NitroPack/___mnag unless asked.
2. Otherwise continue the IOC hunt only for user-named hosts still unsearched or 0-hit parent apex / url_pattern.
3. Be clear on ekfiddle_comment severity; Critical/High first; Low External Script Monitor last.
4. If obfuscated JavaScript OR Critical/High EKFiddle, run MALICIOUS PATTERN CHECKLIST:
   [ ] Iframe/Script Injection
   [ ] Redirection (window.location)
   [ ] Anti-Analysis (referrer checks, localStorage counters)
   [ ] Overlay/UI Hijacking (position:fixed, z-index)
   [ ] Dynamic Code Execution (eval, Function constructor)
5. Focus on BEHAVIOR over string content. Correlate with EKFiddle when present.
6. Do NOT re-fetch already analyzed session IDs listed above.
7. Provide NEW findings only, then either call another tool OR give the final answer.

{self._get_tool_names_list()}

IMPORTANT: Do NOT invent tool names. session_id must be a plain string. No "query" param on sessions_search.
If calling a tool: brief note then {{"tool": "tool_name", "arguments": {{...}}}}"""
                    
                    # Log follow-up prompt details
                    followup_result_str = json.dumps(next_tool_result, indent=2)
                    followup_result_size = len(followup_result_str)
                    self.log_with_timestamp(f"Gemini Request: type=followup_analysis, tool_result_size={self._format_size(followup_result_size)}", to_console=False)
                    self.log_with_timestamp(f"Gemini Request: followup_prompt_length={len(followup_prompt)} chars (~{self._estimate_tokens(followup_prompt)} tokens)", to_console=False)
                    
                    # Show console feedback
                    sys.stdout.write(f"\r  Waiting for Gemini LLM follow-up #{followup_count}...")
                    sys.stdout.flush()
                    
                    followup_start = time.time()
                    self._check_interrupt()
                    followup_response = self.model.generate_content(followup_prompt)
                    self._check_interrupt()
                    followup_elapsed_ms = int((time.time() - followup_start) * 1000)
                    followup_elapsed_s = followup_elapsed_ms / 1000
                    total_gemini_time += followup_elapsed_s
                    
                    # Show completion
                    sys.stdout.write(f"\r  [Gemini LLM] Follow-up #{followup_count} complete ({followup_elapsed_s:.1f}s)                    \n")
                    sys.stdout.flush()
                    
                    current_text = extract_text_safe(followup_response)
                    followup_finish_reason = self._extract_finish_reason(followup_response)
                    
                    # Enhanced follow-up response logging
                    self.log_with_timestamp(f"Gemini Response: {followup_elapsed_ms}ms, response_length={len(current_text)} chars", to_console=False)
                    self.log_with_timestamp(f"Gemini Response: finish_reason={followup_finish_reason}", to_console=False)
                    
                    # Handle blocked responses
                    if not current_text:
                        self.log_with_timestamp(f"Gemini Warning: finish_reason={followup_finish_reason}, follow-up blocked", to_console=False)
                        current_text = "Follow-up analysis blocked by safety filters. The content may contain malicious code patterns."
                        # Log query summary even on blocked response
                        total_time = time.time() - query_start_time
                        self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                        self.conversation_history.append({"role": "assistant", "content": current_text})
                        return self._finalize_assistant_response(current_text)
                    followup_count += 1
                
                # Reached max follow-ups — force synthesis without dangling tool JSON
                total_time = time.time() - query_start_time
                self.log_with_timestamp(f"Gemini Warning: reached max follow-up limit ({max_followups})", to_console=False)
                self.log_with_timestamp(f"Tool Chain: completed after {tool_call_count} tool calls (limit reached)", to_console=False)

                pending_call = self.parse_gemini_response(current_text)
                evidence_text = self._strip_tool_json_from_text(current_text)
                if pending_call or (current_text and current_text != evidence_text):
                    self.log_with_timestamp("Forcing final synthesis after tool budget exhausted", to_console=False)
                    synthesis_prompt = f"""Tool call budget exhausted ({max_followups} calls). Do NOT request another tool.

User's original question: "{user_query}"

{self._analyzed_sessions_note()}

Latest unfinished analysis text (tool JSON removed):
{evidence_text[:8000]}

Provide a FINAL SYNTHESIS only:
- If the user asked for EKFiddle rules, emit the best tab-separated CustomRegexes you can from evidence already gathered (Type	Severity: Name	Regex	Comment). Do not invent IOCs.
- What was confirmed about user-named IOCs / hosts
- What remains unsearched or unverified
- Key security findings from sessions already analyzed
- Clear next manual steps if evidence is incomplete
Do not emit any tool JSON."""
                    try:
                        sys.stdout.write("\r  Waiting for Gemini LLM final synthesis...")
                        sys.stdout.flush()
                        synth_start = time.time()
                        synth_resp = self.model.generate_content(synthesis_prompt)
                        synth_elapsed = time.time() - synth_start
                        total_gemini_time += synth_elapsed
                        sys.stdout.write(f"\r  [Gemini LLM] Final synthesis complete ({synth_elapsed:.1f}s)                    \n")
                        sys.stdout.flush()
                        synth_text = extract_text_safe(synth_resp)
                        if synth_text:
                            current_text = self._strip_tool_json_from_text(synth_text)
                        else:
                            current_text = evidence_text or "Tool budget reached. Unable to complete further automated investigation."
                    except Exception as synth_err:
                        self.log_with_timestamp(f"Final synthesis failed: {synth_err}", to_console=False)
                        current_text = evidence_text or current_text
                else:
                    current_text = evidence_text or current_text

                self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                self.log_with_timestamp(f"Query Summary: tool_calls={tool_call_count}, follow_ups={followup_count}", to_console=False)
                self.conversation_history.append({"role": "assistant", "content": current_text})
                return self._finalize_assistant_response(current_text)
            else:
                # Direct response from Gemini (no tool needed)
                total_time = time.time() - query_start_time
                self.log_with_timestamp(f"Gemini Response: no tool call, direct response", to_console=False)
                self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge=0.0s, total={total_time:.1f}s", to_console=False)
                self.log_with_timestamp(f"Query Summary: tool_calls=0, follow_ups=0", to_console=False)
                self.conversation_history.append({"role": "assistant", "content": gemini_text})
                return self._finalize_assistant_response(gemini_text)
                
        except KeyboardInterrupt:
            # Soft interrupt: stop this tool chain only; keep client + conversation
            self.clear_interrupt()
            if not self.is_mcp_alive():
                print("[!] MCP child died during interrupt; attempting restart...")
                self.ensure_mcp_alive()
            interrupt_msg = (
                "\n\n[INTERRUPTED] Stopped the current tool chain. "
                "Conversation context is preserved. Ask a follow-up or type /quit to exit."
            )
            print(interrupt_msg)
            self.log_with_timestamp("User interrupted tool chain with Ctrl+C (client kept alive)", to_console=False, prefix="Client: ")
            self.conversation_history.append({"role": "system", "content": "[User interrupted the response]"})
            return interrupt_msg
                
        except Exception as e:
            error_msg = f"Error processing query: {e}"
            self.conversation_history.append({"role": "error", "content": error_msg})
            return error_msg

    def clear_bridge_buffer(self) -> Dict[str, Any]:
        """Clear enhanced-bridge live + suspicious buffers via MCP (no Gemini)."""
        result = self.call_tool(
            "fiddler_mcp__sessions_clear",
            {"confirm": True, "clear_suspicious": True},
        )
        self._analyzed_session_ids = set()
        return result if isinstance(result, dict) else {"success": False, "error": str(result)}

    def clear_chat_history(self) -> None:
        """Clear only the local conversation history."""
        self.conversation_history.clear()

    def interactive_mode(self):
        """Run interactive chat session"""
        print("\n" + "=" * 70)
        print("Gemini-Powered Fiddler Traffic Analyzer")
        print("=" * 70)
        print("\nAsk questions about your Fiddler traffic in natural language!")
        print("Examples:")
        print("  - Show me recent sessions from the last 5 minutes")
        print("  - What hosts are in the captured traffic?")
        print("  - Show me the body of session 240")
        print("  - Are there any suspicious sessions?")
        print("  - Search for JavaScript files from example.com")
        self.show_commands_menu()
        print("\nTip: During a tool chain, Ctrl+C stops that answer only and returns to the prompt.")
        print("=" * 70)
        
        while True:
            try:
                user_input = input("\n> You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.startswith("/"):
                    if user_input == "/quit":
                        print("\nGoodbye!")
                        break
                    elif user_input == "/help":
                        self.show_help()
                    elif user_input == "/stats":
                        self.show_stats()
                    elif user_input == "/tools":
                        self.show_tools()
                    elif user_input == "/history":
                        self.show_history()
                    elif user_input == "/clear":
                        print("\n[*] Clearing bridge capture buffers...")
                        result = self.clear_bridge_buffer()
                        if result.get("success") is False or result.get("error"):
                            print(f"[X] Clear failed: {result.get('error') or result}")
                        else:
                            counts = result.get("cleared_counts") or {}
                            live_n = counts.get("live_sessions", result.get("sessions_cleared", "?"))
                            sus_n = counts.get(
                                "suspicious_sessions",
                                result.get("suspicious_cleared", "?"),
                            )
                            print(
                                f"[+] Bridge buffers cleared "
                                f"(live={live_n}, suspicious={sus_n})"
                            )
                    elif user_input == "/clearchat":
                        self.clear_chat_history()
                        print("[+] Conversation history cleared")
                    elif user_input == "/investigate" or user_input.startswith("/investigate "):
                        host_arg = ""
                        if user_input.startswith("/investigate "):
                            host_arg = user_input[len("/investigate ") :].strip()
                        prompt = self.build_investigate_prompt(host_arg or None)
                        print(f"\n[*] Running investigate playbook{' for ' + host_arg if host_arg else ''}...")
                        response = self.chat(prompt)
                        if self.use_rich and self.console:
                            self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                            if self._looks_like_markdown(response):
                                md = Markdown(response)
                                self.console.print(md)
                            else:
                                self.console.print(response)
                        else:
                            print("\n< Gemini: ", end="", flush=True)
                            print(response)
                    elif user_input == "/model":
                        self.show_models()
                    elif user_input.startswith("/model "):
                        model_arg = user_input[7:].strip()
                        self.change_model(model_arg)
                    else:
                        print(f"Unknown command: {user_input}")
                    continue
                
                # Process natural language query
                response = self.chat(user_input)
                
                # Render response with rich formatting if available
                if self.use_rich and self.console:
                    self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                    # Detect if response is markdown and render accordingly
                    if self._looks_like_markdown(response):
                        md = Markdown(response)
                        self.console.print(md)
                    else:
                        self.console.print(response)
                else:
                    print("\n< Gemini: ", end="", flush=True)
                    print(response)
                
            except KeyboardInterrupt:
                # Idle prompt Ctrl+C: soft interrupt flag + stay in loop
                self.request_interrupt()
                self.clear_interrupt()
                print("\n\n[!] Interrupted. Conversation kept. Type a new question or /quit to exit.")
            except Exception as e:
                print(f"\n[X] Error: {e}")

    def show_commands_menu(self):
        """Print the slash-command menu (same list as startup)."""
        print("\nCommands:")
        print("  /help         - Show this menu and example queries")
        print("  /stats        - Show bridge statistics")
        print("  /tools        - List available tools")
        print("  /model        - Show/change Gemini model")
        print("  /history      - Show conversation history")
        print("  /clear        - Clear bridge capture buffers (live + suspicious)")
        print("  /clearchat    - Clear conversation history")
        print("  /investigate  - Hunt malicious traffic in the current buffer")
        print("  /investigate <host> - Same playbook, prioritize a host")
        print("  /quit         - Exit")

    def show_help(self):
        """Show slash-command menu and example queries."""
        print("\n" + "=" * 70)
        print("Fiddler Traffic Analyzer - Commands and Examples")
        print("=" * 70)
        self.show_commands_menu()
        print("\nTip: During a tool chain, Ctrl+C stops that answer only and returns to the prompt.")
        print("\n[*] OVERVIEW QUERIES:")
        print("  - Show me statistics about the captured traffic")
        print("  - How many sessions are in the buffer?")
        print("  - What's the status of the Fiddler bridge?")
        print("\n[*] SESSION QUERIES:")
        print("  - Show me the last 20 sessions")
        print("  - Get sessions from the last 10 minutes")
        print("  - Show me only suspicious sessions")
        print("  - Find all sessions from example.com")
        print("\n[*] DETAILED ANALYSIS:")
        print("  - Show me the headers for session 189")
        print("  - Get the response body for session 240")
        print("  - Analyze session 191 for threats")
        print("\n[*] ADVANCED SEARCHES:")
        print("  - Search for POST requests with status 404")
        print("  - Find all JavaScript files from cdn.example.com")
        print("  - Show me sessions larger than 1MB")
        print("  - Get all failed requests (status >= 400)")
        print("\n[*] INVESTIGATE:")
        print("  - /investigate")
        print("  - /investigate example.com")
        print("  - Investigate the capture buffer for malicious traffic")
        print("\n[*] BUFFER:")
        print("  - /clear        Clear bridge live + suspicious buffers between cases")
        print("  - /clearchat    Clear conversation history only")
        print("=" * 70)

    def show_stats(self):
        """Show current bridge statistics"""
        print("\n[*] Fetching bridge statistics...")
        result = self.call_tool("fiddler_mcp__live_stats", {})
        if "error" not in result:
            print(f"\n[+] Bridge Status: {result.get('bridge_status', 'Unknown')}")
            print(f"  Total Sessions: {result.get('total_sessions', 0)}")
            print(f"  Buffered: {result.get('buffered_sessions', 0)}")
            print(f"  Suspicious: {result.get('suspicious_sessions', 0)}")
            print(f"  Uptime: {result.get('uptime_hours', 0):.1f} hours")
            print(f"  Last Minute: {result.get('last_minute', 0)} sessions")
            print(f"  Last Hour: {result.get('last_hour', 0)} sessions")
        else:
            print(f"\n[X] Error: {result.get('error')}")

    def show_tools(self):
        """Show available MCP tools"""
        print("\n" + "=" * 70)
        print("Available Fiddler MCP Tools")
        print("=" * 70)
        for i, tool in enumerate(self.available_tools, 1):
            name = tool.get("name", "")
            desc = tool.get("description", "")
            print(f"\n{i}. {name}")
            print(f"   {desc}")
        print("=" * 70)

    def show_history(self):
        """Show conversation history"""
        print("\n" + "=" * 70)
        print("Conversation History")
        print("=" * 70)
        if not self.conversation_history:
            print("No conversation history yet.")
        else:
            for i, entry in enumerate(self.conversation_history, 1):
                role = entry.get("role", "unknown").upper()
                content = entry.get("content", "")
                tool = entry.get("tool", "")
                
                # Truncate long content
                if len(content) > 300:
                    content = content[:300] + "... [truncated]"
                
                if tool:
                    print(f"\n[{i}] {role} ({tool}):")
                else:
                    print(f"\n[{i}] {role}:")
                print(f"  {content}")
        print("=" * 70)

    def show_models(self):
        """Show available Gemini models and current selection"""
        print("\n" + "=" * 70)
        print("Available Gemini Models")
        print("=" * 70)
        print(f"\nCurrent model: {self.model_name}")
        print("\nAvailable models:")
        for num, name in AVAILABLE_MODELS.items():
            marker = " <-- CURRENT" if name == self.model_name else ""
            print(f"  {num}. {name}{marker}")
        print("\nTo switch: /model <number> or /model <name>")
        print(f"Example: /model 1  or  /model {DEFAULT_GEMINI_MODEL}")
        print("=" * 70)

    def change_model(self, model_identifier: str):
        """Switch to a different Gemini model at runtime"""
        model_identifier = model_identifier.strip()
        
        # Resolve number to model name
        if model_identifier in AVAILABLE_MODELS:
            new_model = AVAILABLE_MODELS[model_identifier]
        elif model_identifier in AVAILABLE_MODELS.values():
            new_model = model_identifier
        else:
            print(f"[X] Unknown model: {model_identifier}")
            print("    Use /model to see available options")
            return
        
        if new_model == self.model_name:
            print(f"[*] Already using {new_model}")
            return
        
        old_model = self.model_name
        try:
            self.model_name = new_model
            if self.use_native_tools and self.available_tools:
                if not self.bind_gemini_tools():
                    self.model = genai.GenerativeModel(new_model)
            else:
                self.model = genai.GenerativeModel(new_model)
            print(f"[+] Switched from {old_model} to {new_model}")
        except Exception as e:
            self.model_name = old_model
            print(f"[X] Failed to switch model: {e}")

    def close(self):
        """Clean up resources"""
        if self.mcp_process:
            self.mcp_process.stdin.close()
            self.mcp_process.terminate()
            self.mcp_process.wait(timeout=5)
        if self.mcp_stderr_file:
            try:
                self.mcp_stderr_file.close()
            finally:
                self.mcp_stderr_file = None
        
        # Print session summary
        duration = (datetime.now() - self.session_start).total_seconds()
        print(f"\nSession duration: {duration:.1f} seconds")
        print(f"Queries processed: {len([h for h in self.conversation_history if h.get('role') == 'user'])}")


def load_config() -> Dict[str, str]:
    """Load configuration from file or environment"""
    config_file = Path(__file__).parent / "gemini-fiddler-config.json"
    
    # Try to load from config file
    if config_file.exists():
        try:
            with open(config_file) as f:
                config = json.load(f)
                if config.get("api_key"):
                    config.setdefault("auto_save_full_bodies", False)
                    return config
        except Exception:
            pass
    
    # Try environment variable
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return {
            "api_key": api_key,
            "model": os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "auto_save_full_bodies": os.getenv("GEMINI_AUTO_SAVE_FULL_BODIES", "false").lower() in {"1", "true", "yes", "on"},
        }
    
    return {}


def create_config_file():
    """Interactive config file creation"""
    print("\n" + "=" * 70)
    print("Gemini Fiddler Client - Configuration Setup")
    print("=" * 70)
    print("\nNo configuration found. Let's set it up!")
    print("\n1. Get your Gemini API key:")
    print("   https://makersuite.google.com/app/apikey")
    print("\n2. Enter your API key below:")
    
    api_key = input("\nGemini API Key: ").strip()
    
    if not api_key:
        print("[X] No API key provided. Exiting.")
        sys.exit(1)
    
    print("\n3. Select Gemini model:")
    print("\n   DEFAULT / RECOMMENDED (Gemini 3):")
    print("   1. gemini-3-flash-preview (DEFAULT)")
    print("   2. gemini-3.1-flash-lite (fast, cost efficient)")
    print("   3. gemini-3.1-pro-preview (most capable Gemini 3)")
    print("   4. gemini-3.5-flash (stable Gemini 3.5)")
    print("\n   GEMINI 2.5:")
    print("   5. gemini-2.5-flash")
    print("   6. gemini-2.5-pro")
    print("   7. gemini-2.5-flash-lite")
    print("\n   LEGACY (may be deprecated):")
    print("   8. gemini-2.0-flash")
    print("   9. gemini-2.0-flash-lite")
    print("   10. gemini-1.5-flash")
    print("   11. gemini-1.5-pro")
    print("\n   Enter number (1-11) or full model name")
    
    model_choice = input(f"\nModel [1 for {DEFAULT_GEMINI_MODEL}]: ").strip() or "1"
    
    # Get model name from choice (uses centralized AVAILABLE_MODELS constant)
    if model_choice in AVAILABLE_MODELS:
        model = AVAILABLE_MODELS[model_choice]
    elif model_choice in AVAILABLE_MODELS.values():
        # User entered a model name directly
        model = model_choice
    else:
        # Unknown model name, use as-is (user may know a newer model)
        model = model_choice
    
    print(f"\n[+] Selected model: {model}")
    
    # Detect OS and use appropriate Python command
    import platform
    python_cmd = "python" if platform.system() == "Windows" else "python3"
    
    auto_save_prompt = input("\nSave full response bodies to disk automatically? [y/N]: ").strip().lower()
    auto_save_full_bodies = auto_save_prompt in {"y", "yes"}

    config = {
        "api_key": api_key,
        "model": model,
        "auto_save_full_bodies": auto_save_full_bodies,
        "mcp_server_command": [python_cmd, "5ire-bridge.py"],
        "bridge_url": "http://127.0.0.1:8081"
    }
    
    config_file = Path(__file__).parent / "gemini-fiddler-config.json"
    try:
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n[+] Configuration saved to {config_file}")
        return config
    except Exception as e:
        print(f"\n[X] Failed to save config: {e}")
        print("You can set the GEMINI_API_KEY environment variable instead.")
        return config


def main():
    """Main entry point"""
    import platform
    import signal

    print("\nGemini-Powered Fiddler Traffic Analyzer")
    print("=" * 70)

    # 1) Check / install Python deps and verify companion scripts
    if not bootstrap_runtime(auto_install=True):
        print("\n[X] Startup dependency check failed.")
        print("[!] Fix missing packages/scripts, then re-run gemini-fiddler-client.py")
        sys.exit(1)
    
    client = None
    _state = {"interactive": False, "in_chat": False}

    def signal_handler(sig, frame):
        """Ctrl+C during chat/tool chain: soft interrupt. Idle at prompt: stay alive.
        Only exit the process if we are still in startup (before interactive mode).
        """
        if client is not None and _state["interactive"]:
            client.request_interrupt()
            # Raise so blocking generate_content / input() abort immediately
            raise KeyboardInterrupt
        print("\n\n[!] Interrupted by user (Ctrl+C)")
        if client:
            print("[*] Cleaning up...")
            try:
                client.close()
            except Exception:
                pass
        print("[+] Goodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Load or create configuration
        config = load_config()
        if not config.get("api_key"):
            config = create_config_file()
        
        api_key = config.get("api_key")
        model = config.get("model", DEFAULT_GEMINI_MODEL)
        
        # Initialize client
        auto_save_bodies = config.get("auto_save_full_bodies", False)

        client = GeminiFiddlerClient(
            api_key=api_key,
            model_name=model,
            auto_save_full_bodies=auto_save_bodies,
        )
        if config.get("bridge_url"):
            client.bridge_url = str(config["bridge_url"]).rstrip("/")

        # 2) Ensure enhanced-bridge (HTTP) + 5ire-bridge (MCP) are running
        python_cmd = "python" if platform.system() == "Windows" else "python3"
        server_command = config.get("mcp_server_command", [python_cmd, "5ire-bridge.py"])
        print("\n[*] Checking / starting bridges...")
        if not client.ensure_dependencies_running(server_command):
            print("[X] Required bridges are not available. Cannot continue.")
            print("[!] Start enhanced-bridge.py manually, then re-run this client.")
            sys.exit(1)
        
        # List available tools with timeout
        print("[*] Discovering tools...")
        tools = client.list_tools()
        
        if not tools:
            print("[X] Failed to discover tools. Cannot continue.")
            print("[!] Make sure enhanced-bridge.py is running and healthy on port 8081.")
            sys.exit(1)
        
        print(f"[+] Ready with {len(tools)} tools:")
        for tool in tools:
            tool_name = tool.get("name", "unknown").replace("fiddler_mcp__", "")
            print(f"    - {tool_name}")
        
        try:
            original_chat = client.chat

            def chat_with_flag(user_query: str) -> str:
                _state["in_chat"] = True
                try:
                    return original_chat(user_query)
                finally:
                    _state["in_chat"] = False

            client.chat = chat_with_flag  # type: ignore[method-assign]
            _state["interactive"] = True
            client.interactive_mode()
        finally:
            _state["interactive"] = False
            if client:
                client.close()
    
    except KeyboardInterrupt:
        # Should be rare here (startup); interactive catches its own interrupts
        print("\n\n[!] Interrupted by user")
        if client:
            try:
                client.close()
            except Exception:
                pass
        sys.exit(0)
    except Exception as e:
        print(f"\n[X] Fatal error: {e}")
        if client:
            try:
                client.close()
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
