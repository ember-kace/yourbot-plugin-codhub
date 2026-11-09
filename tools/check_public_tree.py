"""Reject local secrets, host paths and non-distributable files before publishing."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {'plugin', 'tools', 'tests', 'metadata', 'docs', '.github', '.git', 'dist'}
ALLOWED_FILES = {'README.md', 'requirements-dev.txt', 'THIRD_PARTY_NOTICES.md', '.gitignore', '.gitattributes'}
FORBIDDEN_SUFFIXES = {'.exe', '.dll', '.luac', '.ff', '.fp', '.zone', '.bin', '.pyc', '.har', '.log'}
TEXT_SUFFIXES = {'.py', '.json', '.md', '.txt', '.yml', '.yaml', '.toml', '.ini'}
HOST_PATH = re.compile(r'(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]|/(?:Users|home)/[^\s/]+/')
SECRET = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
PRIVATE_REFERENCE = re.compile(r'research-output[\\/]|\.playwright-cli[\\/]')
PRIVATE_JSON_KEYS = {'user_approval', 'user_approval_quote', 'source_image_sha256', 'reviewed_by', 'received_on'}


def text_issues(text):
    result = []
    if HOST_PATH.search(text):
        result.append('absolute host path')
    if SECRET.search(text):
        result.append('credential/private-key pattern')
    if PRIVATE_REFERENCE.search(text):
        result.append('private development reference')
    return result


def json_issues(value):
    result = []
    if isinstance(value, dict):
        result.extend('private metadata key: ' + key for key in value if key in PRIVATE_JSON_KEYS)
        for child in value.values():
            result.extend(json_issues(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(json_issues(child))
    return result


def scan(root=ROOT):
    root = Path(root).resolve()
    issues, checked = [], 0
    for path in root.iterdir():
        if path.is_dir() and path.name not in ALLOWED_ROOTS:
            issues.append({'path': path.name, 'issue': 'unexpected top-level directory'})
        elif path.is_file() and path.name not in ALLOWED_FILES:
            issues.append({'path': path.name, 'issue': 'unexpected top-level file'})
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if relative.parts[0] in {'.git', 'dist'} or '__pycache__' in relative.parts:
            continue
        if path.is_symlink():
            issues.append({'path': relative.as_posix(), 'issue': 'linked source path'})
            continue
        if not path.is_file():
            continue
        checked += 1
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith('.env'):
            issues.append({'path': relative.as_posix(), 'issue': 'local/proprietary file type'})
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {'.gitignore', '.gitattributes'}:
            text = path.read_text(encoding='utf-8-sig')
            findings = text_issues(text)
            if relative.as_posix() == '.gitignore':
                # Ignore rules name private cache directories to exclude them.
                findings = [item for item in findings if item != 'private development reference']
            if path.suffix == '.json':
                findings += json_issues(json.loads(text))
            issues.extend({'path': relative.as_posix(), 'issue': value} for value in sorted(set(findings)))
    return {'ready': not issues, 'files_checked': checked, 'issues': issues}


def main():
    report = scan()
    print(json.dumps(report, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
