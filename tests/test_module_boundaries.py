"""Protect the dependency boundaries introduced by the viewer extraction."""
from pathlib import Path
import subprocess
import sys
import unittest


class ModuleBoundaryTests(unittest.TestCase):
    def test_data_modules_and_worker_import_without_qt_or_caiman(self):
        # A separate interpreter prevents earlier Qt tests masking an eager import.
        script = """
import importlib.abc
import sys

class BlockUIAndEngine(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PySide6', 'pyqtgraph', 'caiman'}:
            raise AssertionError('Unexpected import: ' + fullname)

sys.meta_path.insert(0, BlockUIAndEngine())
import cali
assert 'cali.viewer' not in sys.modules
import cali.timing
import cali.tracking
import cali.readers
import cali.video_exports
import cali.calcium_pipeline
assert 'cali.viewer' not in sys.modules
"""
        result = subprocess.run([sys.executable, "-B", "-c", script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
