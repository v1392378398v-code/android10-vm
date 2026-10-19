#!/usr/bin/env python3
"""Exercise the guest's real EGL loader, GLES driver, shaders and GPU buffers."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from guest_runtime_fixture import RuntimeInstance
from test_framework_support import wait_marker, stop_children

OUT = ROOT / "artifacts/container/graphics/desktop"


def main():
    assert os.getuid() >= 10000
    report = {"passed": False, "uid": os.getuid(), "rootRequired": False, "desktopVerified": False}
    children, handles = [], []
    with tempfile.TemporaryDirectory(prefix="egl-", dir=OUT) as temporary:
        runtime = RuntimeInstance(temporary, {
            **{path.name: path for path in (OUT / "lib").glob("*.so")},
            "desktop-egl-check": OUT / "bin/desktop-egl-check",
            "desktop-hal-check": OUT / "bin/desktop-hal-check",
        })
        for path in (OUT / "lib").glob("*emulation.so"):
            target = runtime.rootfs / "vendor/lib64/egl" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            target.symlink_to(runtime.native(path.name))
        environment = runtime.framework_environment()
        environment["A10VM_GPU_SOCKET"] = str(runtime.directory / "gpu.sock")

        def start(role, command, env):
            log = OUT / ("egl-" + role + ".log")
            handle = log.open("w")
            if role == "hal" and os.environ.get("A10VM_DEBUG_DESKTOP_HAL"):
                command = [shutil.which("gdb"), "-q", "-nx", "-batch", "-ex", "set pagination off",
                    "-ex", "set exec-wrapper env LD_PRELOAD=" + env["LD_PRELOAD"], "-ex", "run",
                    "-ex", "thread apply all bt 16", "--args"] + command
                env = {key: value for key, value in env.items() if key != "LD_PRELOAD"}
            child = subprocess.Popen(list(map(str, command)), env=env,
                                     stdout=handle, stderr=subprocess.STDOUT)
            children.append(child)
            handles.append(handle)
            return child, log

        try:
            host, host_log = start("host", [OUT / "bin/desktop-gpu-host", environment["A10VM_GPU_SOCKET"]],
                                   {"PATH": "/system/bin", "TMPDIR": temporary})
            wait_marker(host, host_log, "desktop_gpu_ready=1", 3)
            hal, hal_log = start("hal", [runtime.native("ld-android.so"),
                                runtime.native("desktop-hal-check")], environment)
            hal_text = wait_marker(hal, hal_log, "desktop_hal_complete=1", 5)
            assert hal.wait(timeout=2) == 0, hal_text
            assert "desktop_hal_software_yuv=1\n" in hal_text
            assert "desktop_hal_yuv_readback=1\n" in hal_text
            report.update(grallocVerified=True, softwareYuvVerified=True, yuvReadbackVerified=True,
                          composerModuleVerified=True, hal=hal_text)
            guest, guest_log = start("guest", [runtime.native("ld-android.so"),
                                     runtime.native("desktop-egl-check")], environment)
            text = wait_marker(guest, guest_log, "desktop_egl_complete=1", 5)
            assert guest.wait(timeout=2) == 0 and host.poll() is None
            assert "desktop_egl_shader_pixel=1\n" in text and "desktop_egl_rgba8_target=1\n" in text
            assert "desktop_egl_large_texture_upload=1\n" in text
            assert "desktop_egl_interleaved_pixel=1\n" in text
            assert "desktop_egl_multiline_readback=1\n" in text
            assert "desktop_egl_readback_alignment=1\n" in text
            assert "desktop_egl_vertex_attribute_bounds=1\n" in text
            assert "desktop_egl_config_non_null_handles=1\n" in text
            assert "desktop_egl_config_capabilities=1\n" in text
            assert "desktop_egl_native_buffer_video_pixels=1\n" in text
            assert "desktop_egl_native_image_lifetime=1\n" in text
            assert "desktop_egl_threaded_texture_mailbox=1\n" in text
            assert "desktop_egl_shared_glyph_atlas=1\n" in text
            assert "desktop_egl_shared_glyph_first_frame=1\n" in text
            assert "desktop_egl_shared_glyph_without_query=1\n" in text
            assert "desktop_egl_danmaku_transparency=1\n" in text
            assert "desktop_gpu_error=" not in host_log.read_text()
            report.update(passed=True, shaderPixelVerified=True, interleavedPixelVerified=True,
                          largeTextureUploadVerified=True,
                          rgba8TargetVerified=True, multilineReadbackVerified=True,
                          readbackAlignmentVerified=True, vertexAttributeBoundsVerified=True, eglDriverLoaded=True,
                          nativeBufferVideoPixelsVerified=True,
                          nativeImageLifetimeVerified=True,
                          threadedTextureMailboxVerified=True,
                          sharedGlyphAtlasVerified=True, sharedGlyphFirstFrameVerified=True,
                          sharedGlyphWithoutQueryVerified=True, danmakuTransparencyVerified=True,
                          nonNullConfigHandlesVerified=True, configCapabilitiesVerified=True,
                          host=host_log.read_text(), guest=text)
        except Exception as error:
            report["error"] = str(error)
        finally:
            stop_children(children, handles)
            report["processCleanupPassed"] = all(child.poll() is not None for child in children)
    (OUT / "egl-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
