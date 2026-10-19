#!/usr/bin/env python3
"""Exercise ROM trial cleanup with real short-lived subprocesses."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("rom_trial", Path(__file__).with_name("try-android-rom.py"))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialCleanupTest(unittest.TestCase):
    def run_case(self, *, setup_error=False, keep_runtime=False, keep_diagnostics=False):
        with tempfile.TemporaryDirectory(prefix="rom-cleanup-check-") as temporary:
            root = Path(temporary)
            (root / "artifacts").mkdir()
            prepared = root / "prepared"
            prepared.mkdir()
            installed_data = root / "installed-app-data"
            installed_data.write_bytes(b"preserve existing application data")
            output = root / "results"

            def fixture(directory, *, prepared):
                rootfs = directory / "rootfs"
                rootfs.mkdir()
                (rootfs / "trial-cache").write_bytes(b"temporary runtime")
                (output / "desktop.ppm").write_bytes(b"temporary frame")
                (output / "tap-1.ppm").write_bytes(b"temporary tap frame")
                (output / "setup.log").write_text("setup diagnostics\n", encoding="utf-8")
                if setup_error:
                    raise RuntimeError("fixture setup failed")
                return SimpleNamespace(rootfs=rootfs, inputs={"sourceImageSha256": "fixture"},
                    environment={"A10VM_STATE_ROOT": str(directory)},
                    native=lambda logical: "",
                    art_command=lambda name: [sys.executable, "-c", "print('art_runtime_ready=1')"])

            with patch.object(trial, "ROOT", root), patch.object(trial, "RuntimeInstance", fixture):
                report = trial.run_trial(prepared, output, "art", 3,
                                         keep_runtime=keep_runtime, keep_diagnostics=keep_diagnostics)
            self.assertEqual(report["passed"], not setup_error, report)
            self.assertEqual(Path(report["runtimeDirectory"]).exists(), keep_runtime)
            self.assertEqual((output / "runtime").is_symlink(), keep_runtime)
            self.assertEqual(report["runtimeRetained"], keep_runtime)
            self.assertEqual(report["diagnosticsRetained"], keep_diagnostics)
            self.assertEqual((output / "setup.log").exists(), keep_diagnostics)
            self.assertEqual((output / "desktop.ppm").exists(), keep_diagnostics)
            self.assertEqual((output / "tap-1.ppm").exists(), keep_diagnostics)
            self.assertEqual(installed_data.read_bytes(), b"preserve existing application data")
            self.assertEqual(json.loads((output / "report.json").read_text()), report)
            if not setup_error:
                self.assertEqual(report["processes"], {"art": 0})
                self.assertIn("art_runtime_ready=1", report["evidence"])
                self.assertEqual((output / "art.log").exists(), keep_diagnostics)

    def test_success_keeps_report_without_runtime_or_diagnostics(self):
        self.run_case()

    def test_setup_failure_removes_partial_runtime_and_diagnostics(self):
        self.run_case(setup_error=True)

    def test_diagnostics_can_be_kept_without_runtime(self):
        self.run_case(keep_diagnostics=True)

    def test_runtime_can_be_kept_without_diagnostics(self):
        self.run_case(keep_runtime=True)

    def test_both_can_be_kept_explicitly(self):
        self.run_case(keep_runtime=True, keep_diagnostics=True)


if __name__ == "__main__":
    unittest.main()
