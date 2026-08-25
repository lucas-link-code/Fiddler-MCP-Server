#!/usr/bin/env python3
"""DeepSeek OpenAI-compatible native tool provider."""
from __future__ import annotations

import json
import os
import ssl
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from llm_tool_schema import mcp_tools_to_openai_tools
from gemini_native_tools import truncate_tool_result_for_model

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}
_SHARED_CA_ENVS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)
SslVerify = Union[bool, ssl.SSLContext]


def _config_disables_verify(config_flag: Optional[Any]) -> bool:
    if isinstance(config_flag, bool) and config_flag is False:
        return True
    if isinstance(config_flag, (int, float)) and int(config_flag) == 0:
        return True
    if isinstance(config_flag, str) and config_flag.strip().lower() in _FALSE:
        return True
    return False


def _ca_files(*extra_envs: str) -> List[str]:
    ordered = tuple(extra_envs) + _SHARED_CA_ENVS
    out: List[str] = []
    seen = set()
    for env in ordered:
        path = (os.environ.get(env) or "").strip()
        if not path or not os.path.isfile(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def ssl_verify_label(verify: SslVerify) -> str:
    if verify is False:
        return "disabled"
    if verify is True:
        return "system defaults"
    label = getattr(verify, "_fiddler_ca_label", None)
    return str(label or "SSLContext")


def build_merged_ssl_context(extra_cert_envs: Sequence[str] = ()) -> ssl.SSLContext:
    """OS trust store plus certifi plus extra PEM files.

    FLARE often sets SSL_CERT_FILE to a single lab root such as
    C:/ProgramData/Rep/rootCA.crt. Using that path as the only httpx verify
    store drops public CAs, so api.deepseek.com fails even when the file exists.
    """
    ctx = ssl.create_default_context()
    parts = ["OS trust store"]
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
        parts.append("certifi")
    except Exception:
        pass
    for path in _ca_files(*extra_cert_envs):
        try:
            ctx.load_verify_locations(cafile=path)
            parts.append(path)
        except Exception as exc:
            print(f"[!] Skipping extra CA {path}: {exc}")
    ctx._fiddler_ca_label = " + ".join(parts)  # type: ignore[attr-defined]
    return ctx


def resolve_ssl_verify(
    config_flag: Optional[Any] = None,
    *,
    disable_env: str = "DEEPSEEK_SSL_VERIFY",
    extra_cert_envs: Sequence[str] = ("DEEPSEEK_SSL_CERT_FILE",),
) -> SslVerify:
    """httpx verify value: False, or an SSLContext that merges lab CA files.

    disable_env=0/false disables verify. A lab CA env file is appended to the
    default store; it is never used as the sole bundle.
    """
    env_flag = (os.environ.get(disable_env) or "").strip().lower()
    if env_flag in _FALSE:
        return False
    if env_flag not in _TRUE and _config_disables_verify(config_flag):
        return False
    return build_merged_ssl_context(extra_cert_envs)


class DeepSeekProvider:
    name = "deepseek"
    display_label = "DeepSeek"

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        ssl_verify: Optional[Any] = None,
    ):
        from openai import OpenAI
        import httpx

        self.api_key = api_key
        self.model_name = model_name
        # Official OpenAI-compatible base URL per https://api-docs.deepseek.com/
        self.base_url = (base_url or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
        self._tools: List[Dict[str, Any]] = []
        self._system_instruction = ""
        self._ssl_verify = resolve_ssl_verify(ssl_verify)
        if self._ssl_verify is False:
            print(
                "[!] DeepSeek TLS verify disabled (DEEPSEEK_SSL_VERIFY=0 or "
                "deepseek_ssl_verify=false). Lab use only."
            )
        else:
            print(f"[*] DeepSeek TLS verify: {ssl_verify_label(self._ssl_verify)}")
        timeout = float(os.environ.get("DEEPSEEK_HTTP_TIMEOUT", "90"))
        self._http_client = httpx.Client(verify=self._ssl_verify, timeout=timeout)
        self._client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            http_client=self._http_client,
        )

    def bind_tools(self, mcp_tools: List[Dict[str, Any]], system_instruction: str) -> bool:
        self._system_instruction = system_instruction
        self._tools = mcp_tools_to_openai_tools(mcp_tools)
        return bool(self._tools)

    def tools_bound(self) -> bool:
        return bool(self._tools)

    def bound_tool_names(self) -> List[str]:
        names = []
        for t in self._tools:
            fn = (t.get("function") or {}).get("name")
            if fn:
                names.append(fn)
        return names

    def start_conversation(self, user_text: str) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        if self._system_instruction:
            messages.append({"role": "system", "content": self._system_instruction})
        messages.append({"role": "user", "content": user_text})
        return messages

    def generate(self, conversation: Any, tool_choice: str = "auto") -> Any:
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": conversation,
        }
        if self._tools and str(tool_choice).lower() != "none":
            kwargs["tools"] = self._tools
            kwargs["tool_choice"] = "auto"
        elif self._tools and str(tool_choice).lower() == "none":
            # Omit tools so the model cannot call them
            pass
        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(self._format_api_error(exc)) from exc

    def _format_api_error(self, exc: BaseException) -> str:
        """Turn opaque SDK Connection error into an actionable message."""
        name = type(exc).__name__
        msg = str(exc).strip() or name
        cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
        cause_txt = ""
        if cause is not None:
            cause_txt = f" | cause={type(cause).__name__}: {cause}"

        lower = (msg + cause_txt).lower()
        hints: List[str] = []
        if "certificate" in lower or "ssl" in lower or "certifi" in lower:
            hints.append("URL is correct: https://api.deepseek.com (official DeepSeek OpenAI base_url)")
            hints.append("This is a TLS trust problem on the VM, not a wrong API URL")
            hints.append("Fix 1: restart this client. Lab SSL_CERT_FILE is merged into the OS/certifi store, not used as the only CA file")
            hints.append("Fix 2: extra intercept CA: set DEEPSEEK_SSL_CERT_FILE to a PEM path")
            hints.append("Fix 3 lab only: set DEEPSEEK_SSL_VERIFY=0 then restart (disables cert checks; insecure)")
            hints.append(f"Current verify setting: {ssl_verify_label(self._ssl_verify)}")
        elif "connection" in lower or "connect" in lower or "timeout" in lower or "name resolution" in lower:
            hints.append(f"Cannot reach DeepSeek API at {self.base_url}")
            hints.append("Official base URL is https://api.deepseek.com (also accepts /v1)")
            hints.append("On the analysis VM run: curl -I https://api.deepseek.com")
            hints.append("If you need a corporate proxy, set HTTPS_PROXY / HTTP_PROXY then restart the client")
        if "401" in lower or "unauthorized" in lower or "invalid api key" in lower or "authentication" in lower:
            hints.append("API key rejected. Re-enter with /model deepseek-v4-flash and paste a fresh key from https://platform.deepseek.com/")
        if "403" in lower or "forbidden" in lower or "country" in lower or "region" in lower:
            hints.append("DeepSeek may be blocking this network or region")

        detail = f"DeepSeek API error ({name}): {msg}{cause_txt}"
        if hints:
            detail += "\n  Hints:\n  - " + "\n  - ".join(hints)
        return detail

    def extract_tool_calls(self, response: Any) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        try:
            message = response.choices[0].message
        except Exception:
            return calls
        tool_calls = getattr(message, "tool_calls", None) or []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if not fn:
                continue
            name = getattr(fn, "name", "") or ""
            raw_args = getattr(fn, "arguments", "") or "{}"
            args: Dict[str, Any]
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            calls.append({
                "name": str(name),
                "args": args,
                "id": getattr(tc, "id", None),
            })
        return calls

    def extract_text(self, response: Any) -> str:
        try:
            message = response.choices[0].message
            content = getattr(message, "content", None)
            return content if isinstance(content, str) else (content or "")
        except Exception:
            return ""

    def append_model_turn(
        self,
        conversation: Any,
        response: Any,
        calls: List[Dict[str, Any]],
        text: str,
    ) -> None:
        try:
            message = response.choices[0].message
            # Prefer SDK message object serialized into dict for history
            entry: Dict[str, Any] = {
                "role": "assistant",
                "content": text or getattr(message, "content", None),
            }
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c.get("id") or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c.get("args") or {}),
                        },
                    }
                    for i, c in enumerate(calls)
                ]
            conversation.append(entry)
        except Exception:
            entry = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c.get("id") or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c.get("args") or {}),
                        },
                    }
                    for i, c in enumerate(calls)
                ]
            conversation.append(entry)

    def append_tool_results(
        self,
        conversation: Any,
        executed: List[Tuple[str, Dict[str, Any], Dict[str, Any], Optional[str]]],
        nudge: str,
    ) -> None:
        for i, (name, _args, result, tid) in enumerate(executed):
            safe = truncate_tool_result_for_model(result)
            conversation.append({
                "role": "tool",
                "tool_call_id": tid or f"call_{i}",
                "content": json.dumps(safe, default=str),
            })
        if nudge:
            conversation.append({"role": "user", "content": nudge})

    def append_user_text(self, conversation: Any, text: str) -> None:
        conversation.append({"role": "user", "content": text})

    def change_model(self, model_name: str) -> None:
        self.model_name = model_name
