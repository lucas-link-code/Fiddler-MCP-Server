#!/usr/bin/env python3
"""PyPI TLS probe and pip wrapper for FLARE / broken Python CA stores.

Normal machines keep strict SSL. Probe pip's own cert stack first; urllib on
Windows can pass via the OS store while pip's certifi still fails. If a probe
or a pip run hits a certificate error, retry with --trusted-host (pip-only).
Does not set PYTHONHTTPSVERIFY.
"""
from __future__ import annotations

import os
import ssl
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

PROBE_URL = "https://pypi.org/simple/pip/"
PROBE_TIMEOUT = 8.0
TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
)

_ENV_TRUE = {"1", "true", "yes", "on"}
_SSL_NEEDLES = (
    "certificate_verify_failed",
    "certificate verify failed",
    "sslcertverificationerror",
    "ssl: certificate",
    "unable to get local issuer certificate",
)
_cached_use_trusted: Optional[bool] = None
_LAB_WARN = (
    "[!] PyPI TLS verify failed or FIDDLER_PIP_TRUSTED_HOST=1. "
    "Retrying pip with --trusted-host (lab only; pip TLS off for PyPI)."
)
_PIP_SSL_WARN = (
    "[!] pip reported a certificate verify failure. "
    "Windows urllib can pass while pip certifi fails. "
    "Retrying pip with --trusted-host."
)


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _ENV_TRUE


def trusted_host_args() -> List[str]:
    args: List[str] = []
    for host in TRUSTED_HOSTS:
        args.extend(["--trusted-host", host])
    return args


def ssl_in_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(n in lowered for n in _SSL_NEEDLES)


def _is_ssl_failure(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError):
        return True
    chain = [exc, reason, getattr(exc, "__cause__", None)]
    return any(x is not None and ssl_in_text(str(x)) for x in chain)


def probe_urllib_tls(timeout: float = PROBE_TIMEOUT) -> str:
    """Return 'ok', 'ssl', or 'other' using stdlib urlopen (Windows CA store)."""
    req = Request(PROBE_URL, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            resp.read(64)
        return "ok"
    except Exception as exc:
        chain = [exc, getattr(exc, "reason", None), getattr(exc, "__cause__", None)]
        if any(x is not None and _is_ssl_failure(x) for x in chain):
            return "ssl"
        return "other"


def probe_pip_stack_tls(timeout: float = PROBE_TIMEOUT) -> str:
    """Return 'ok', 'ssl', or 'other' using pip's vendored requests/certifi."""
    try:
        from pip._vendor import requests as pip_requests
    except Exception:
        return "other"
    try:
        resp = pip_requests.get(PROBE_URL, timeout=timeout)
        try:
            resp.close()
        except Exception:
            pass
        return "ok"
    except Exception as exc:
        if _is_ssl_failure(exc):
            return "ssl"
        return "other"


def probe_layers(timeout: float = PROBE_TIMEOUT) -> Tuple[str, str, str]:
    """Combined result, pip_stack result, urllib result."""
    pip_r = probe_pip_stack_tls(timeout)
    if pip_r in ("ssl", "ok"):
        return pip_r, pip_r, "skipped"
    url_r = probe_urllib_tls(timeout)
    if url_r == "ssl":
        return "ssl", pip_r, url_r
    return "other", pip_r, url_r


def probe_pypi_tls(timeout: float = PROBE_TIMEOUT) -> str:
    """Return 'ok', 'ssl', or 'other'. Prefers pip's TLS stack over urllib."""
    combined, _, _ = probe_layers(timeout)
    return combined


def use_trusted_host(force_probe: bool = False) -> bool:
    """Decide whether pip should pass --trusted-host. Cached per process."""
    global _cached_use_trusted
    if _env_flag("FIDDLER_PIP_STRICT_SSL"):
        return False
    if _env_flag("FIDDLER_PIP_TRUSTED_HOST"):
        return True
    if _cached_use_trusted is not None and not force_probe:
        return _cached_use_trusted
    result = probe_pypi_tls()
    _cached_use_trusted = result == "ssl"
    return _cached_use_trusted


def reset_probe_cache() -> None:
    global _cached_use_trusted
    _cached_use_trusted = None


def build_pip_command(pip_args: Sequence[str], use_trusted: Optional[bool] = None) -> List[str]:
    """sys.executable -m pip [trusted-host...] <pip_args>."""
    if use_trusted is None:
        use_trusted = use_trusted_host()
    cmd = [sys.executable, "-m", "pip"]
    if use_trusted:
        cmd.extend(trusted_host_args())
    cmd.extend(list(pip_args))
    return cmd


def _invoke_pip(cmd: List[str], cwd: Optional[str], capture: bool) -> subprocess.CompletedProcess:
    if not capture:
        return subprocess.run(cmd, cwd=cwd)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    chunks: List[str] = []
    if proc.stdout is not None:
        for line in proc.stdout:
            chunks.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
    rc = proc.wait()
    return subprocess.CompletedProcess(cmd, int(rc), stdout="".join(chunks), stderr="")


def run_pip(pip_args: Sequence[str], cwd: Optional[str] = None) -> int:
    global _cached_use_trusted
    trusted = use_trusted_host()
    if trusted:
        print(_LAB_WARN)
        result = _invoke_pip(build_pip_command(pip_args, use_trusted=True), cwd, capture=False)
        return int(result.returncode)

    first = _invoke_pip(build_pip_command(pip_args, use_trusted=False), cwd, capture=True)
    if _env_flag("FIDDLER_PIP_STRICT_SSL"):
        return int(first.returncode)
    if not ssl_in_text(first.stdout or ""):
        return int(first.returncode)

    print(_PIP_SSL_WARN)
    _cached_use_trusted = True
    second = _invoke_pip(build_pip_command(pip_args, use_trusted=True), cwd, capture=False)
    return int(second.returncode)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  python pypi_tls.py probe\n"
            "  python pypi_tls.py install --upgrade pip\n"
            "  python pypi_tls.py install -r requirements-gemini.txt\n"
            "  python pypi_tls.py pip <pip-args...>\n"
        )
        return 0
    cmd = args[0]
    if cmd == "probe":
        combined, pip_r, url_r = probe_layers()
        print(f"pypi_tls probe: {combined}")
        print(f"pypi_tls detail: pip_stack={pip_r} urllib={url_r}")
        if combined == "ok":
            return 0
        if combined == "ssl":
            return 2
        return 1
    if cmd == "install":
        return run_pip(args)
    if cmd == "pip":
        return run_pip(args[1:])
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
