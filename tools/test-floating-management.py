#!/usr/bin/env python3
"""Exercise floating management dragging, docking, navigation and saved position."""
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

ENV = {key: value for key, value in os.environ.items() if key not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}
PACKAGE = "io.a10vm.miui"
DESCRIPTION = "打开管理页，可拖动贴边"


def device(command):
    return subprocess.check_output(["su", "-c", "PATH=/system/bin:/system/xbin " + command],
                                   env=ENV, timeout=20).decode()


def screen():
    output = device("/system/bin/uiautomator dump /data/local/tmp/a10vm-floating-ui.xml")
    assert "UI hierchary dumped to:" in output, "UI capture failed: " + output
    return ET.fromstring(device("/system/bin/cat /data/local/tmp/a10vm-floating-ui.xml"))


def bounds(tree, description):
    node = next((node for node in tree.iter("node") if node.get("content-desc") == description), None)
    assert node is not None, "Missing control: " + description
    return tuple(map(int, re.findall(r"\d+", node.get("bounds"))))


def open_display():
    device("/system/bin/am start -W -n " + PACKAGE + "/io.a10vm.ui.FullscreenActivity")
    deadline = time.monotonic() + 8
    while True:
        tree = screen()
        if any(node.get("content-desc") == DESCRIPTION for node in tree.iter("node")):
            return tree
        assert time.monotonic() < deadline, "Fullscreen management control did not appear"
        time.sleep(.2)


def main():
    report = {"passed": False}
    try:
        tree = open_display()
        left, top, right, bottom = bounds(tree, "Android 10 桌面")
        previous = bounds(tree, DESCRIPTION)
        report["initialBounds"] = previous
        report["displayBounds"] = [left, top, right, bottom]
        width = previous[2] - previous[0]
        assert width == previous[3] - previous[1] and width > 0, "Expected a circular touch target"
        targets = ((left + (right - left) // 4, top + (bottom - top) // 3, "left"),
                   (left + 3 * (right - left) // 4, top + 2 * (bottom - top) // 3, "right"))
        report["docking"] = []
        for target_x, target_y, side in targets:
            cx, cy = (previous[0] + previous[2]) // 2, (previous[1] + previous[3]) // 2
            device("/system/bin/input swipe %d %d %d %d 500" % (cx, cy, target_x, target_y))
            time.sleep(.25)
            current = bounds(screen(), DESCRIPTION)
            report["docking"].append({"side": side, "bounds": current})
            edge = current[0] if side == "left" else current[2]
            assert abs(edge - (left if side == "left" else right)) <= 2, (side, current)
            assert top <= current[1] < current[3] <= bottom, current
            assert abs((current[1] + current[3]) // 2 - target_y) <= 3, "Vertical drag was lost"
            previous = current
        device("/system/bin/input tap %d %d" % ((previous[0] + previous[2]) // 2,
                                                (previous[1] + previous[3]) // 2))
        manager = screen()
        assert any(node.get("text") == "进入 Android 10 桌面" for node in manager.iter("node")), \
            "Floating button did not return to management"
        report["clickOpenedManagement"] = True
        restored = bounds(open_display(), DESCRIPTION)
        assert all(abs(a - b) <= 2 for a, b in zip(previous, restored)), (previous, restored)
        report["positionRestored"] = True
        report["passed"] = True
    except (AssertionError, subprocess.SubprocessError, ValueError) as error:
        report["error"] = str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
