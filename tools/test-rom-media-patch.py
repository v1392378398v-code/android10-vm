#!/usr/bin/env python3
"""Run the ARM64 renderer guard and verify the original non-null operation."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('rom_media_patch', ROOT / 'tools/patch-rom-media.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
env = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD')}
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    original, patched, runner = (directory / name for name in ('original.so', 'patched.so', 'runner'))
    subprocess.run(['clang', '-shared', '-fPIC', '-nostdlib', '-Wl,-z,separate-code',
                    str(ROOT / 'tools/fixtures/rom/MediaResetFixture.S'),
                    '-o', str(original)], env=env, check=True)
    subprocess.run(['clang++', str(ROOT / 'tools/fixtures/rom/MediaResetFixture.cpp'), '-ldl', '-o', str(runner)],
                   env=env, check=True)
    before = subprocess.run([str(runner), str(original)], env=env, capture_output=True, timeout=5)
    assert before.returncode == -signal.SIGSEGV, (before.returncode, before.stderr)
    report = module.patch(original, patched)
    after = subprocess.run([str(runner), str(patched)], env=env, capture_output=True, timeout=5)
    assert after.returncode == 0 and b'media_renderer_guard=1\n' in after.stdout, (after.returncode, after.stderr)
    assert report['cfiBodyPreserved']
    print('media_null_renderer_before=SIGSEGV\nmedia_null_renderer_after=return\nmedia_nonnull_renderer_preserved=1')
