#!/usr/bin/env python3
"""Verify the real installed-app picker and import a split APK through the app service."""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/test-apk-desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
PACKAGE = "io.a10vm.miui"
FIXTURE = "io.a10vm.fixture.keyboard"
OUT = ROOT / "artifacts/device-compat/installed-app-import"


def device(command, timeout=20):
    return desktop.device("PATH=/system/bin:/system/xbin " + command, timeout).decode(errors="replace")


def ui():
    for _ in range(3):
        target = "/data/local/tmp/a10vm-import-" + str(time.monotonic_ns()) + ".xml"
        device("uiautomator dump " + target, 25)
        try:
            return ET.fromstring(device("cat " + target))
        except (subprocess.CalledProcessError, ET.ParseError):
            time.sleep(.3)
    raise AssertionError("UI dump did not produce a fresh hierarchy")


def click(text):
    for node in ui().iter("node"):
        if node.get("text", "").replace("\n", " ") == text.replace("\n", " ") and node.get("enabled") == "true":
            left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
            device("input tap %d %d" % ((left + right) // 2, (top + bottom) // 2))
            return
    raise AssertionError("Missing UI control: " + text)


def guest(*args):
    result = subprocess.run(["python3", str(ROOT / "tools/apk-guest-command.py"), "--package", PACKAGE,
                             *args], env=desktop.ENV, text=True, capture_output=True, timeout=140)
    if result.returncode:
        raise AssertionError(result.stdout[-1800:] + result.stderr[-600:])
    return result.stdout


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "fixture": FIXTURE, "steps": []}
    try:
        subprocess.run(["python3", str(ROOT / "tools/build-keyboard-fixture.py")], env=desktop.ENV, check=True)
        created = device("pm install-create -r -t --user 0")
        session = re.search(r"\[(\d+)\]", created).group(1)
        for name in ("base", "split"):
            apk = ROOT / "artifacts/keyboard-fixture" / (name + ".apk")
            result = device("pm install-write -S " + str(apk.stat().st_size) + " " + session + " " +
                            name + ".apk " + shlex.quote(str(apk)))
            assert "Success" in result, result
        assert "Success" in device("pm install-commit " + session)
        assert len(re.findall(r"^package:", device("pm path " + FIXTURE), re.M)) == 2
        device("pm grant " + PACKAGE + " android.permission.POST_NOTIFICATIONS")
        device("am start -W --activity-clear-top -n " + PACKAGE + "/io.a10vm.ui.MainActivity")
        click("导入应用到 Android 10")
        report["steps"].append("source selection")
        click("从手机已安装应用选择")
        deadline = time.monotonic() + 20
        while "正在读取手机上的应用…" in ET.tostring(ui(), encoding="unicode"):
            assert time.monotonic() < deadline, "Installed app list did not load"
            time.sleep(.25)
        click("搜索应用名称或包名")
        report["steps"].append("installed list loaded")
        device("input text " + FIXTURE)
        time.sleep(.4)
        label = "A10VM 输入测试\n" + FIXTURE
        click(label)
        assert any(node.get("text") == "导入（1）" and node.get("enabled") == "true" for node in ui().iter("node"))
        device("input keyevent 4")
        (OUT / "picker.png").write_bytes(desktop.device("PATH=/system/bin:/system/xbin screencap -p"))
        click("导入（1）")
        deadline = time.monotonic() + 90
        state = ""
        while time.monotonic() < deadline:
            state = device("run-as " + PACKAGE + " cat files/guest-runtime/session-state.log")
            if "已导入 1/1" in state:
                break
            if "应用导入失败" in state or "已导入 0/1" in state:
                raise AssertionError(state)
            time.sleep(.5)
        assert "已导入 1/1" in state, state
        paths = guest("package", "path", FIXTURE)
        assert len(re.findall(r"^package:", paths, re.M)) == 2, paths
        report.update(passed=True, search=True, selection=True, splitApks=2, installResult=state.strip(), guestPaths=paths.strip())
        guest("activity", "start", "-n", FIXTURE + "/.EditorActivity")
        device("am start -W -n " + PACKAGE + "/io.a10vm.ui.FullscreenActivity")
    except Exception as error:
        report["error"] = str(error)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
