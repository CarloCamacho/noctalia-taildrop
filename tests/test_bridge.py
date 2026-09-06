"""Tests for the noctalia-taildrop bridge.

These exercise the helper's validation and the structured request it dispatches
to the Tailscale plugin. A fake `noctalia` shim is placed on PATH so the tests
run without a live Noctalia daemon.

Run from the repo root:  python3 -m pytest tests/  (or python3 -m unittest)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(REPO, "bin", "noctalia-taildrop")


class FakeNoctalia:
    """Fake `noctalia` executable that records its argv to a log file."""

    def __init__(self, log_path):
        self.log_path = log_path
        self.bin_dir = os.path.dirname(log_path)
        os.makedirs(self.bin_dir, exist_ok=True)

    def write_shim(self):
        shim = os.path.join(self.bin_dir, "noctalia")
        log = self.log_path.replace("'", "'\\''")
        # Keep the printf format literal: `%s\n` must not be Python-interpolated.
        body = ("#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > '" + log + "'\n")
        with open(shim, "w") as fh:
            fh.write(body)
        os.chmod(shim, 0o755)
        return shim


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.fake = FakeNoctalia(os.path.join(self.tmp, "noctalia-argv.log"))
        shim = self.fake.write_shim()
        self.env = dict(os.environ)
        # Prepend the fake nohtalia dir so `noctalia` resolves to the shim.
        self.env["PATH"] = self.fake.bin_dir + os.pathsep + self.env.get("PATH", "")
        self.file_path = os.path.join(self.tmp, "a file with spaces.txt")
        with open(self.file_path, "w") as fh:
            fh.write("hello\n")

    def tearDown(self):
        self._td.cleanup()

    def run_helper(self, *args):
        return subprocess.run([sys.executable, HELPER, *args],
                              env=self.env, capture_output=True, text=True)

    def test_no_arg_usage_error(self):
        r = self.run_helper()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", (r.stderr or "").lower())

    def test_rejects_nonexistent(self):
        r = self.run_helper(os.path.join(self.tmp, "nope.bin"))
        self.assertEqual(r.returncode, 1)
        self.assertNotEqual(r.stderr, "")

    def test_rejects_relative_path(self):
        r = self.run_helper("just-a-relative.txt")
        self.assertEqual(r.returncode, 1)
        self.assertIn("absolute", (r.stderr or "").lower())

    def test_rejects_unreadable(self):
        p = os.path.join(self.tmp, "locked.bin")
        with open(p, "w") as fh:
            fh.write("x")
        os.chmod(p, 0)
        r = self.run_helper(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("readable", (r.stderr or "").lower())

    def test_dispatches_valid_file(self):
        r = self.run_helper(self.file_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        # The shim recorded argv: msg plugin <entry> all <event> <json>
        with open(self.fake.log_path) as fh:
            argv = [line.rstrip("\n") for line in fh]
        self.assertEqual(argv[0], "msg")
        self.assertEqual(argv[1], "plugin")
        self.assertEqual(argv[3], "all")
        self.assertEqual(argv[4], "taildrop_send")
        payload = json.loads(argv[5])
        self.assertEqual(payload["v"], 1)
        self.assertEqual(payload["origin"], "hyprfm")
        self.assertEqual(payload["paths"], [self.file_path])
        self.assertTrue(payload["requestId"])
        self.assertRegex(payload["requestId"], r"^[A-Za-z0-9._-]{1,64}$")

    def test_dispatch_runs_no_shell(self):
        # A path with shell metacharacters (no '/' — that's a filename separator)
        # must survive as a single argv element.
        nasty = os.path.join(self.tmp, "x; rm -rf blah \"' $()  unicode-\u00e9.txt")
        with open(nasty, "w") as fh:
            fh.write("s")
        r = self.run_helper(nasty)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.fake.log_path) as fh:
            argv = [line.rstrip("\n") for line in fh]
        payload = json.loads(argv[5])
        self.assertEqual(payload["paths"], [nasty])


if __name__ == "__main__":
    unittest.main()
