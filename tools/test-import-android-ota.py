#!/usr/bin/env python3
"""Exercise full-OTA sparse placement and reject incomplete/incremental inputs."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("ota", Path(__file__).with_name("import-android-ota.py"))
ota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota)


class FullOtaTest(unittest.TestCase):
    def test_sparse_ranges_and_erase_extent(self):
        commands, limit = ota.parse_transfer("4\n2\n0\n0\nerase 2,3,7\nnew 4,0,1,2,3\n")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system.raw"
            ota.write_partition(io.BytesIO(b"A" * ota.BLOCK + b"B" * ota.BLOCK), target, commands, limit)
            self.assertEqual(target.read_bytes(), b"A" * ota.BLOCK + b"\0" * ota.BLOCK +
                             b"B" * ota.BLOCK + b"\0" * (4 * ota.BLOCK))

    def test_bad_transfer_lists(self):
        for text in ("4\n2\n1\n0\nnew 2,0,2\n", "4\n1\n0\n0\nmove 2,0,1\n",
                     "4\n2\n0\n0\nnew 3,0,1\n", "4\n3\n0\n0\nnew 2,0,2\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                ota.parse_transfer(text)

    def test_truncated_and_trailing_payload(self):
        commands, limit = ota.parse_transfer("4\n1\n0\n0\nnew 2,0,1\n")
        for size in (ota.BLOCK - 1, ota.BLOCK + 1):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                ota.write_partition(io.BytesIO(b"A" * size), Path(directory) / "system.raw", commands, limit)

    def test_zero_after_new_overwrites_written_range(self):
        commands, limit = ota.parse_transfer("4\n3\n0\n0\nnew 2,0,2\nzero 2,1,2\n")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "system.raw"
            ota.write_partition(io.BytesIO(b"A" * ota.BLOCK + b"B" * ota.BLOCK), target, commands, limit)
            self.assertEqual(target.read_bytes(), b"A" * ota.BLOCK + bytes(ota.BLOCK))


if __name__ == "__main__":
    unittest.main()
