#!/usr/bin/env python3
"""PyPI TLS probe and pip wrapper for FLARE / broken Python CA stores.

Normal machines keep strict SSL. If a short HTTPS probe to pypi.org fails
with a certificate error, pip is retried with --trusted-host (pip-only).
Does not set PYTHONHTTPSVERIFY.
"""
from __future__ import annotations

import os
import ssl
import subprocess
import sys
from typing import List, Optional, Sequence
from urllib.request import Request, urlopen

PROBE_URL = "https://pypi.org/simple/pip/"
PROBE_TIMEOUT = 8.0
TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
)

_ENV_TRUE = {"1", "true", "yes", "on"}
_cached_use_trusted: Optional[bool] = None


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _ENV_TRUE


def trusted_host_args() -> List[str]:
    args: List[str] = []
    for host in TRUSTED_HOSTS:
        args.extend(["--trusted-host", host])
    return args


def _is_ssl_failure(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError):
        return True
    text = str(exc).lower()
    needles = (
        "certificate_verify_failed",
        "certificate verify failed",
        "sslcertverificationerror",
        "ssl: certificate",
        "unable to get local issuer certificate",
    )
    return any(n in text for n in needles)


def probe_pypi_tls(timeout: float = PROBE_TIMEOUT) -> str:
    """Return 'ok', 'ssl', or 'other'."""
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


def run_pip(pip_args: Sequence[str], cwd: Optional[str] = None) -> int:
    trusted = use_trusted_host()
    if trusted:
        print(
            "[!] PyPI TLS verify failed or FIDDLER_PIP_TRUSTED_HOST=1. "
            "Retrying pip with --trusted-host (lab only; pip TLS off for PyPI)."
        )
    cmd = build_pip_command(pip_args, use_trusted=trusted)
    result = subprocess.run(cmd, cwd=cwd)
    return int(result.returncode)


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
        result = probe_pypi_tls()
        print(f"pypi_tls probe: {result}")
        if result == "ok":
            return 0
        if result == "ssl":
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
