"""Prevent a return of network imports that local SDK validation alone permits."""
import unittest

from tools.check_plugin_security import evaluate_sources


class PluginSecurityTests(unittest.TestCase):
    def test_network_imports_are_rejected_including_url_only_submodules(self):
        for source in ("from urllib.parse import quote", "import urllib.parse as urls",
                       "import requests", "from http.client import HTTPSConnection",
                       "import socket", "import httpx"):
            with self.subTest(source=source):
                report = evaluate_sources({"cod_hub/example.py": source})
                self.assertFalse(report["ready"])
                self.assertEqual(report["findings"][0]["line"], 1)
                self.assertEqual(report["findings"][0]["path"], "cod_hub/example.py")

    def test_process_and_dynamic_imports_are_rejected(self):
        for source in ("import subprocess", "import ctypes", "import multiprocessing",
                       "import importlib", "__import__('urllib.parse')", "eval('1')",
                       "exec('pass')", "from builtins import __import__ as load",
                       "import os; os.system('example')", "import pty; pty.spawn('example')",
                       "import pickle; pickle.loads(b'')", "import marshal; marshal.loads(b'')",
                       "import builtins; builtins.eval('1')", "import runpy"):
            with self.subTest(source=source):
                self.assertFalse(evaluate_sources({"example.py": source})["ready"])

    def test_proxy_calls_local_helpers_and_module_docstrings_are_allowed(self):
        source = ('"""Do not use urllib.request here."""\n'
                  'from yourbot_sdk import Plugin\n'
                  'from .urls import quote\n'
                  'def fetch(ctx):\n'
                  '    return ctx.http.get("https://metaradar.gg/api/v1/meta/modernwarfare4")\n')
        report = evaluate_sources({"cod_hub/example.py": source, "data.json": b"{}"})
        self.assertTrue(report["ready"])
        self.assertEqual(report["python_files_checked"], 1)


if __name__ == "__main__":
    unittest.main()
