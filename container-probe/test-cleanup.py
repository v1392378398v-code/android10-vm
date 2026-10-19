#!/usr/bin/env python3
"""Exercise the installer cleanup with a fake ADB, without touching any device."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


FAKE_TOOL = r'''
import os
from pathlib import Path
import sys

state = Path(os.environ["PROBE_TEST_STATE"])
scenario = os.environ["PROBE_TEST_SCENARIO"]
args = sys.argv[1:]
with state.with_suffix(".trace").open("a") as trace:
    trace.write(" ".join(args) + "\n")
if Path(sys.argv[0]).name == "aapt2":
    print("package: name='io.a10vm.containerprobe' versionCode='1'")
elif args == ["get-state"]:
    print("device")
elif args and args[0] == "install":
    if scenario == "no-side-effect":
        sys.exit(1)
    state.write_text("installed")
    sys.exit(124)
elif args and args[0] == "shell":
    if args[1].startswith("pm path "):
        if not state.exists():
            sys.exit(1)
        print("package:/fixture/probe.apk")
    elif args[1].startswith("pm uninstall "):
        if not state.exists() or scenario == "uninstall-fails":
            print("Failure")
            sys.exit(1)
        state.unlink()
        print("Success")
    else:
        sys.exit(99)
else:
    sys.exit(99)
'''


class CleanupTest(unittest.TestCase):
    def run_case(self, scenario, expected_exit, remains, uninstall, graphics=False, surface=False,
                 dynamic=False, companion=False, binder=False, filesystem=False):
        with tempfile.TemporaryDirectory(prefix="a10vm-cleanup-") as temporary:
            root = Path(temporary)
            module = root / "container-probe"
            module.mkdir()
            script = module / "test-device.sh"
            shutil.copyfile(Path(__file__).with_name("test-device.sh"), script)
            apk = root / "fixture.apk"
            apk.write_bytes(b"temporary test fixture")
            binaries = root / "bin"
            binaries.mkdir()
            stub = binaries / "fake-tool"
            stub.write_text("#!" + sys.executable + "\n" + FAKE_TOOL, encoding="utf-8")
            stub.chmod(0o755)
            for name in ("adb", "aapt2"):
                (binaries / name).symlink_to(stub)
            state = root / "installed"
            if scenario == "existing":
                state.write_text("previous installation", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(PATH=str(binaries) + os.pathsep + environment["PATH"],
                               PROBE_TEST_STATE=str(state), PROBE_TEST_SCENARIO=scenario)
            mode = ["--filesystem"] if filesystem else ["--binder"] if binder else ["--companion"] if companion else ["--dynamic"] if dynamic else ["--surface"] if surface else ["--graphics"] if graphics else []
            command = ["sh", str(script)] + mode + [str(apk)]
            result = subprocess.run(command, env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
            self.assertEqual(state.exists(), remains)
            trace = state.with_suffix(".trace").read_text(encoding="utf-8")
            self.assertEqual("pm uninstall " in trace, uninstall)
            if scenario == "existing":
                self.assertNotIn("install -r", trace)
                self.assertEqual(state.read_text(), "previous installation")

    def test_install_side_effect_then_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True)

    def test_failed_install_without_side_effect(self):
        self.run_case("no-side-effect", 1, False, False)

    def test_existing_installation_is_preserved(self):
        self.run_case("existing", 2, True, False)

    def test_uninstall_failure_is_reported(self):
        self.run_case("uninstall-fails", 1, True, True)

    def test_graphics_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, graphics=True)

    def test_surface_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, surface=True)

    def test_dynamic_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, dynamic=True)

    def test_companion_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, companion=True)

    def test_binder_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, binder=True)

    def test_filesystem_install_timeout_is_cleaned(self):
        self.run_case("timeout", 124, False, True, filesystem=True)


if __name__ == "__main__":
    unittest.main()
