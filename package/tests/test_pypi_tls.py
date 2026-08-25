#!/usr/bin/env python3
"""Unit tests for pypi_tls probe and pip argv construction."""
from __future__ import annotations

import os
import ssl
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pypi_tls  # noqa: E402


class TestTrustedHostArgs(unittest.TestCase):
    def test_three_hosts(self):
        args = pypi_tls.trusted_host_args()
        self.assertEqual(
            args,
            [
                "--trusted-host",
                "pypi.org",
                "--trusted-host",
                "files.pythonhosted.org",
                "--trusted-host",
                "pypi.python.org",
            ],
        )


class TestProbeClassification(unittest.TestCase):
    def tearDown(self):
        pypi_tls.reset_probe_cache()

    def test_probe_ok(self):
        cm = MagicMock()
        cm.__enter__.return_value.read.return_value = b"ok"
        cm.__exit__.return_value = False
        with patch("pypi_tls.urlopen", return_value=cm):
            self.assertEqual(pypi_tls.probe_pypi_tls(), "ok")

    def test_probe_ssl_cert_error(self):
        err = ssl.SSLCertVerificationError("unable to get local issuer certificate")
        with patch("pypi_tls.urlopen", side_effect=URLError(err)):
            self.assertEqual(pypi_tls.probe_pypi_tls(), "ssl")

    def test_probe_other_network(self):
        with patch("pypi_tls.urlopen", side_effect=URLError(OSError("timed out"))):
            self.assertEqual(pypi_tls.probe_pypi_tls(), "other")


class TestBuildPipCommand(unittest.TestCase):
    def tearDown(self):
        pypi_tls.reset_probe_cache()
        for key in ("FIDDLER_PIP_STRICT_SSL", "FIDDLER_PIP_TRUSTED_HOST"):
            os.environ.pop(key, None)

    def test_probe_ok_no_trusted_host(self):
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ok"):
            pypi_tls.reset_probe_cache()
            cmd = pypi_tls.build_pip_command(["install", "--upgrade", "pip"])
        self.assertEqual(cmd[:3], [sys.executable, "-m", "pip"])
        self.assertNotIn("--trusted-host", cmd)
        self.assertEqual(cmd[-3:], ["install", "--upgrade", "pip"])

    def test_probe_ssl_adds_trusted_hosts(self):
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ssl"):
            pypi_tls.reset_probe_cache()
            cmd = pypi_tls.build_pip_command(["install", "-r", "requirements-gemini.txt"])
        self.assertIn("--trusted-host", cmd)
        self.assertIn("pypi.org", cmd)
        self.assertIn("files.pythonhosted.org", cmd)
        self.assertIn("pypi.python.org", cmd)
        self.assertEqual(cmd[-3:], ["install", "-r", "requirements-gemini.txt"])

    def test_strict_ssl_skips_fallback(self):
        os.environ["FIDDLER_PIP_STRICT_SSL"] = "1"
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ssl") as probe:
            cmd = pypi_tls.build_pip_command(["install", "rich"])
        probe.assert_not_called()
        self.assertNotIn("--trusted-host", cmd)

    def test_force_trusted_host_skips_probe(self):
        os.environ["FIDDLER_PIP_TRUSTED_HOST"] = "1"
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ok") as probe:
            cmd = pypi_tls.build_pip_command(["install", "rich"])
        probe.assert_not_called()
        self.assertIn("--trusted-host", cmd)


class TestRunPipAndCli(unittest.TestCase):
    def tearDown(self):
        pypi_tls.reset_probe_cache()
        os.environ.pop("FIDDLER_PIP_TRUSTED_HOST", None)
        os.environ.pop("FIDDLER_PIP_STRICT_SSL", None)

    def test_run_pip_forwards_args(self):
        os.environ["FIDDLER_PIP_TRUSTED_HOST"] = "1"
        completed = MagicMock(returncode=0)
        with patch("pypi_tls.subprocess.run", return_value=completed) as run:
            rc = pypi_tls.run_pip(["install", "--upgrade", "pip"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:3], [sys.executable, "-m", "pip"])
        self.assertIn("--trusted-host", cmd)
        self.assertEqual(cmd[-3:], ["install", "--upgrade", "pip"])

    def test_cli_install_invokes_pip(self):
        completed = MagicMock(returncode=0)
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ok"):
            pypi_tls.reset_probe_cache()
            with patch("pypi_tls.subprocess.run", return_value=completed) as run:
                rc = pypi_tls.main(["install", "-r", "requirements-gemini.txt"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[-3:], ["install", "-r", "requirements-gemini.txt"])
        self.assertNotIn("--trusted-host", cmd)

    def test_cli_probe_ssl_exit_2(self):
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ssl"):
            self.assertEqual(pypi_tls.main(["probe"]), 2)

    def test_cli_probe_ok_exit_0(self):
        with patch.object(pypi_tls, "probe_pypi_tls", return_value="ok"):
            self.assertEqual(pypi_tls.main(["probe"]), 0)


if __name__ == "__main__":
    unittest.main()
