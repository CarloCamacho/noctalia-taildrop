"""Tests for the noctalia-taildrop bridge.

These exercise the helper's validation and the structured requests it dispatches
to the Taildrop plugin (a `msg plugin ... taildrop_send` request, then a
`msg panel-open` to bring the dialog forward). A fake `noctalia` shim is placed
on PATH so the tests run without a live Noctalia daemon.

Run from the repo root:  python3 -m unittest -v tests.test_bridge
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(REPO, "bin", "noctalia-taildrop")

SENTINEL = "---CALL---"


class FakeNoctalia:
    """Fake `noctalia` executable that records each invocation's argv."""

    def __init__(self, log_path):
        self.log_path = log_path
        self.bin_dir = os.path.dirname(log_path)
        os.makedirs(self.bin_dir, exist_ok=True)

    def write_shim(self):
        shim = os.path.join(self.bin_dir, "noctalia")
        log = self.log_path.replace("'", "'\\''")
        # Append a sentinel then one line per argv element (shell-quoted safely).
        # The sentinel lets tests distinguish successive `noctalia` calls.
        body = ("#!/usr/bin/env bash\n"
                "printf '\\n---CALL---\\n' >> '" + log + "'\n"
                "printf '%s\\n' \"$@\" >> '" + log + "'\n")
        with open(shim, "w") as fh:
            fh.write(body)
        os.chmod(shim, 0o755)
        return shim

    def read_calls(self):
        """Return a list of argv lists, one per `noctalia` invocation."""
        with open(self.log_path) as fh:
            content = fh.read()
        calls = []
        for block in content.split(SENTINEL):
            args = [ln.rstrip("\n") for ln in block.splitlines()]
            # Drop the empty leading line produced by the sentinel's newline.
            args = [a for a in args if a != ""]
            if args:
                calls.append(args)
        return calls


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.fake = FakeNoctalia(os.path.join(self.tmp, "noctalia-argv.log"))
        shim = self.fake.write_shim()
        self.env = dict(os.environ)
        # Prepend the fake noctalia dir so `noctalia` resolves to the shim.
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
        calls = self.fake.read_calls()
        # Call 0: msg plugin <entry> all <event> <json>
        argv = calls[0]
        self.assertEqual(argv[0], "msg")
        self.assertEqual(argv[1], "plugin")
        self.assertEqual(argv[2], "carlocamacho/taildrop:service")
        self.assertEqual(argv[3], "all")
        self.assertEqual(argv[4], "taildrop_send")
        payload = json.loads(argv[5])
        self.assertEqual(payload["v"], 1)
        self.assertEqual(payload["origin"], "file_manager")
        self.assertEqual(payload["paths"], [self.file_path])
        self.assertTrue(payload["requestId"])
        self.assertRegex(payload["requestId"], r"^[A-Za-z0-9._-]{1,64}$")

    def test_opens_panel_after_dispatch(self):
        self.run_helper(self.file_path)
        calls = self.fake.read_calls()
        self.assertEqual(len(calls), 2)
        # Call 1: msg panel-open <panel-id>
        self.assertEqual(calls[1][0], "msg")
        self.assertEqual(calls[1][1], "panel-open")
        self.assertEqual(calls[1][2], "carlocamacho/taildrop:send")

    def test_dispatches_multiple_files_one_request(self):
        second = os.path.join(self.tmp, "second file.txt")
        with open(second, "w") as fh:
            fh.write("two\n")
        r = self.run_helper(self.file_path, second)
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(self.fake.read_calls()[0][5])
        self.assertEqual(payload["paths"], [self.file_path, second])
        self.assertEqual(len(payload["paths"]), 2)

    def test_rejects_too_many_paths(self):
        too_many = [os.path.join(self.tmp, f"f{i}.txt") for i in range(33)]
        for p in too_many:
            with open(p, "w") as fh:
                fh.write("x")
        r = self.run_helper(*too_many)
        self.assertEqual(r.returncode, 1)
        self.assertIn("too many", (r.stderr or "").lower())

    def test_dispatch_runs_no_shell(self):
        # A path with shell metacharacters (no '/' — that's a filename separator)
        # must survive as a single argv element.
        nasty = os.path.join(self.tmp, "x; rm -rf blah \"' $()  unicode-\u00e9.txt")
        with open(nasty, "w") as fh:
            fh.write("s")
        r = self.run_helper(nasty)
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(self.fake.read_calls()[0][5])
        self.assertEqual(payload["paths"], [nasty])


if __name__ == "__main__":
    unittest.main()
