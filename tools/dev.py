"""Portable development commands for COD Hub; no game installation required."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('test', 'validate', 'package', 'preview'))
    args = parser.parse_args(argv)
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    environment['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'plugin'), str(ROOT), environment.get('PYTHONPATH', '')])
    commands = {
        'test': [['-m', 'unittest', 'discover', '-s', 'tests', '-q']],
        'validate': [['tools/check_public_tree.py'], ['tools/validate_catalog.py'], ['tools/package_plugin.py']],
        'package': [['tools/package_plugin.py', '--output', 'dist/COD-Hub-0.1.2.zip', '--report', 'dist/package.json']],
        'preview': [['tools/render_readme_previews.py', '--output', 'docs/images']],
    }
    for command in commands[args.command]:
        result = subprocess.run([sys.executable, *command], cwd=ROOT, env=environment, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
