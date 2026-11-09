"""Create the allowlisted YourBot artifact only after English and SDK checks pass."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import zipfile

try:
    from .check_plugin_security import evaluate_sources
    from .english_release_gate import evaluate_documents
except ImportError:
    from check_plugin_security import evaluate_sources
    from english_release_gate import evaluate_documents

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "0.10.1"
PLATFORM_PLUGIN_ID = "rmg84ete7r8b"
FILES = (
    "manifest.json", "__main__.py", "requirements.txt", "README.md",
    "cod_hub/__init__.py", "cod_hub/app.py", "cod_hub/cards.py", "cod_hub/catalog.py",
    "cod_hub/codec.py", "cod_hub/meta.py", "cod_hub/reference.py", "cod_hub/store.py",
    "cod_hub/hub.py", "cod_hub/hub_cards.py", "cod_hub/library_ui.py",
    "cod_hub/artwork.py", "cod_hub/urls.py",
    "cod_hub/comparison.py", "cod_hub/comparison_ui.py", "cod_hub/comparison_charts.py",
    "cod_hub/meta_browser.py", "cod_hub/telemetry.py",
    "cod_hub/fonts/font.ttf", "cod_hub/fonts/LICENSE.txt",
    "cod_hub/data/schema.json", "cod_hub/data/catalog.json",
    "cod_hub/data/facts-sources.json",
    "cod_hub/data/artwork.json",
    "cod_hub/data/telemetry.json",
    "cod_hub/data/NOTICE-HashIndex.txt",
)


def _member_path(plugin_path, relative):
    """Check every source component before following or reading a member."""
    current = plugin_path
    for part in (None, *Path(relative).parts):
        if part is not None:
            current = current / part
        metadata = current.lstat()
        if (stat.S_ISLNK(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Linked package path component: " + relative)
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(plugin_path) or not resolved.is_file():
        raise ValueError("Missing or escaping package member: " + relative)
    return resolved


def prepare(plugin_path, *, plugin_id=PLATFORM_PLUGIN_ID, version=None):
    from yourbot_sdk import __version__
    from yourbot_sdk._validation import validate_artifact
    if __version__ != SDK_VERSION:
        raise ValueError(f"Use the reviewed YourBot SDK {SDK_VERSION}; found {__version__}.")
    original_root = Path(plugin_path).absolute()
    # Check the supplied root itself before resolve() can hide a link/junction.
    root_metadata = original_root.lstat()
    if (stat.S_ISLNK(root_metadata.st_mode)
            or getattr(root_metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Linked package source root.")
    plugin_path = original_root.resolve(strict=True)
    buffer = BytesIO()
    members = []
    captured = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in FILES:
            path = _member_path(plugin_path, relative)
            data = path.read_bytes()
            captured[relative] = data
            if path.suffix == ".py":
                compile(data, relative, "exec")  # Compile syntax without executing plugin code.
            info = zipfile.ZipInfo(relative, (2026, 11, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
            members.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    data = buffer.getvalue()
    manifest = json.loads(captured["manifest.json"])
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("id"), str)
            or not isinstance(manifest.get("version"), str)):
        raise ValueError("Manifest must contain string id and version fields.")
    sdk = validate_artifact(plugin_id=plugin_id, version=version or manifest["version"], artifact_bytes=data).to_payload()
    security = evaluate_sources(captured)
    # The gate must approve the bytes in this archive, even if an import changes
    # the source folder concurrently after capture.
    english = evaluate_documents(json.loads(captured["cod_hub/data/catalog.json"]),
                                 json.loads(captured["cod_hub/data/facts-sources.json"]))
    report = {
        "plugin_id": manifest["id"], "version": manifest["version"], "sdk_version": __version__,
        "release_ready": english["ready"] and security["ready"] and not sdk["errors"] and not sdk["warnings"],
        "english": {key: english[key] for key in ("ready", "required", "total_translated", "total_described", "total_english_covered", "counts")},
        "english_issue_count": len(english["issues"]), "sdk_validation": sdk,
        "artifact_policy": security,
        "archive_bytes": len(data), "uncompressed_bytes": sum(m["bytes"] for m in members),
        "archive_sha256": hashlib.sha256(data).hexdigest(), "members": members,
    }
    return data, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=ROOT / "plugin")
    parser.add_argument("--plugin-id", default=PLATFORM_PLUGIN_ID,
                        help="Assigned platform plugin ID to validate against (defaults to COD Hub).")
    parser.add_argument("--version", help="Expected version on the platform, when known.")
    parser.add_argument("--output", type=Path, help="Write a release ZIP; omitted for read-only validation.")
    parser.add_argument("--report", type=Path, help="Optional local validation report.")
    args = parser.parse_args(argv)
    try:
        data, report = prepare(args.plugin, plugin_id=args.plugin_id, version=args.version)
    except (ValueError, OSError, ImportError, SyntaxError) as error:
        print(json.dumps({"release_ready": False, "error": str(error)})); return 1
    if args.output and report["release_ready"]:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        written = args.output.resolve()
        report["written"] = written.relative_to(ROOT).as_posix() if written.is_relative_to(ROOT) else written.name
    elif args.output:
        report["written"] = None
        report["reason"] = "Release blocked; no ZIP written."
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps({key: value for key, value in report.items() if key != "members"}, indent=2))
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
