"""Local artifact checks supplement SDK validation; the portal assigns risk scores."""
from __future__ import annotations

import ast

# All HTTP belongs in ctx.http. URL formatting must not import a network package.
# Process/native loaders and dynamic code are unnecessary in this plugin too.
FORBIDDEN_IMPORTS = frozenset({
    "urllib", "requests", "http", "httpx", "aiohttp", "socket", "socketserver",
    "ssl", "websocket", "websockets", "ftplib", "smtplib", "imaplib", "poplib",
    "telnetlib", "xmlrpc", "subprocess", "ctypes", "multiprocessing", "importlib",
    "os", "pty", "pickle", "marshal", "builtins", "imp", "runpy",
})
FORBIDDEN_CALLS = frozenset({"__import__", "eval", "exec", "compile"})


def evaluate_sources(sources):
    """Inspect the captured Python members that will actually enter the ZIP."""
    findings = []
    checked = 0
    for filename, source in sources.items():
        if not filename.endswith(".py"):
            continue
        checked += 1
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    modules = [node.module or ""]
                    if node.module == "builtins":
                        modules += [alias.name for alias in node.names if alias.name in FORBIDDEN_CALLS]
            for module in modules:
                if module.partition(".")[0] in FORBIDDEN_IMPORTS | FORBIDDEN_CALLS:
                    findings.append({"path": filename, "line": node.lineno,
                                     "rule": "disallowed_import", "symbol": module})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                findings.append({"path": filename, "line": node.lineno,
                                 "rule": "dynamic_code", "symbol": node.func.id})
    return {"ready": not findings, "python_files_checked": checked, "findings": findings}
