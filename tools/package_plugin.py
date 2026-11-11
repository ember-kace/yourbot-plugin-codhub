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
    from .native_artwork_release import evaluate_captured as evaluate_native_artwork
    from .item_catalog_release import evaluate_captured as evaluate_item_catalog, required_files as item_catalog_files
    from .item_artwork_release import evaluate_captured as evaluate_item_artwork
    from .native_guide_release import evaluate_captured as evaluate_native_guide
except ImportError:
    from check_plugin_security import evaluate_sources
    from english_release_gate import evaluate_documents
    from native_artwork_release import evaluate_captured as evaluate_native_artwork
    from item_catalog_release import evaluate_captured as evaluate_item_catalog, required_files as item_catalog_files
    from item_artwork_release import evaluate_captured as evaluate_item_artwork
    from native_guide_release import evaluate_captured as evaluate_native_guide

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "0.10.1"
PLATFORM_PLUGIN_ID = "rmg84ete7r8b"
FILES = (
    "manifest.json", "__main__.py", "requirements.txt", "README.md",
    "cod_hub/__init__.py", "cod_hub/app.py", "cod_hub/cards.py", "cod_hub/catalog.py",
    "cod_hub/codec.py", "cod_hub/meta.py", "cod_hub/reference.py", "cod_hub/store.py",
    "cod_hub/hub.py", "cod_hub/hub_cards.py", "cod_hub/library_ui.py",
    "cod_hub/artwork.py", "cod_hub/native_artwork.py", "cod_hub/urls.py",
    "cod_hub/item_catalog.py", "cod_hub/item_catalog_ui.py", "cod_hub/item_artwork.py",
    "cod_hub/native_guide.py", "cod_hub/native_guide_ui.py",
    "cod_hub/data/native-guide.json", "cod_hub/data/native-guide-sources.json",
    "cod_hub/data/item-artwork.json",
    "cod_hub/comparison.py", "cod_hub/comparison_ui.py", "cod_hub/comparison_charts.py",
    "cod_hub/meta_browser.py", "cod_hub/telemetry.py",
    "cod_hub/fonts/font.ttf", "cod_hub/fonts/LICENSE.txt",
    "cod_hub/data/schema.json", "cod_hub/data/catalog.json",
    "cod_hub/data/facts-sources.json",
    "cod_hub/data/artwork.json",
    "cod_hub/data/native-artwork.json",
    "cod_hub/data/telemetry.json",
    "cod_hub/data/NOTICE-HashIndex.txt",
    "cod_hub/images/native/0978efaa1d1f212fc6f88df4abf3bf846f35b3d322d8fc65a811c5b6ffa521e8.webp",
    "cod_hub/images/native/0dcbfb56e025b637638c6f36a11f7afe641e8b52277f63926290ed198221a9a8.webp",
    "cod_hub/images/native/1fd65403d530169741e4d7131f2d673f75243802e74ac8ec554c2f0538900025.webp",
    "cod_hub/images/native/2f01edbf6a834496d09c7da36c9a85cc897821bef3e4a3640ac95430213c4ca1.webp",
    "cod_hub/images/native/320d185497c0a12cf70cec026ac20a88363c15a23a3948f8512439d963c0277a.webp",
    "cod_hub/images/native/435263f2869641be745ba01c09f241997798cb7e2db89c529bb1272ed779196a.webp",
    "cod_hub/images/native/51c93d7dcdc295ad3ed07d441e4d1b710786b0645d66f0a7a68502af91b85295.webp",
    "cod_hub/images/native/56b214c0e6d96dc3be896a021bcca339c75bfa43217d9e01844340a3f8b87b46.webp",
    "cod_hub/images/native/56ed822e7a560dc9b08f3c7efc3d8384652e731a56a3b910b2fb6ee8ee3ca211.webp",
    "cod_hub/images/native/58b294833861d9152d65b8fa76eddac618cb83f7445e66de6606805879df91c3.webp",
    "cod_hub/images/native/64492959b90e99317cd46545597a3dd435d721388ec4b0ad8ca2b0fc4ba197fb.webp",
    "cod_hub/images/native/6c9728c1b7923242ddef85dd1d210e7f81bbfa93b8ac0ea77a8325667a5a71af.webp",
    "cod_hub/images/native/6ccb90ac10c29a8fda29a10be6477895330c3f6a5c0cc68ebc77f9148edad8a6.webp",
    "cod_hub/images/native/6d3eb81bf5b5b7ef27d5039a8e3a42fe37e5d3c751a9c72ceb49018644ccb7c6.webp",
    "cod_hub/images/native/7a16d298dbb8b5b36cf3d28ceba4f44e7caab0240dc721804e7ad15bb69f7c6c.webp",
    "cod_hub/images/native/83c238a081cb49eae5d40a63ee4f37f4ca6e9516b2887f17cb99fd30ffc5803d.webp",
    "cod_hub/images/native/8460226d213acea03b6c9de8ee601759f65da8b4f9086949f9ff0518c4c40ae7.webp",
    "cod_hub/images/native/870fb4ee16932ef1c737f645e517a22a12f5ff19f11f5faa08401e5276bf2d15.webp",
    "cod_hub/images/native/95ab0b43d11c4ee96a901f9320a1252925bb2f28fe164c39ae363da9156efcb9.webp",
    "cod_hub/images/native/a9e95298d49b81e8d2ddfb1c130e2417b821426c9fc9834a71780a9295335fd6.webp",
    "cod_hub/images/native/b59cf09a211917bd3e1f5400291a69456dc8762d4e29c82f3bc3e365620323a4.webp",
    "cod_hub/images/native/b6a992951221c9240820b8f1f27ba7f6cf5cc6322430f81ad819ab78ecd08962.webp",
    "cod_hub/images/native/b752deca280174780e93a7169062ee070ff5d274fc63107b6bde0335e86c141a.webp",
    "cod_hub/images/native/c3a9f90c3c7d2ecd2fcc6f6485b776bf1ea2248f97e8378bfc5802e1bf71d92a.webp",
    "cod_hub/images/native/c568f0fb21711798793b1b8fee00240cf14edca7cda9b89f3559e5277ed0beac.webp",
    "cod_hub/images/native/c9905b190c6dd0c7bbbdb61121cbe3ca3030c9adaf79d8c256b40c47081ba449.webp",
    "cod_hub/images/native/c9e5ac055033bf54de38c23e1902735226b3ca7ab70802aae82e74041e28e8f1.webp",
    "cod_hub/images/native/ccd54ae9fcd5bd05e82a15777e0434cbbe27f12f80320e8856c45ffe70383a6c.webp",
    "cod_hub/images/native/ce391668130198680dfbe2533f48ff929be2457339e0d72370fbbe8d17f1db88.webp",
    "cod_hub/images/native/ce8b17a020474777c28b1959989ffb0e17802df1f7c36f9ba88984dc6d5f6281.webp",
    "cod_hub/images/native/d086785a7348ebbc6e362971b0144d26da58ad4f3641cbe5f75760f92f51b6fa.webp",
    "cod_hub/images/native/d46f713a29a422b30ae2f31f3779a4a7e384c6a399586cb8394a9a5646ae70bb.webp",
    "cod_hub/images/native/d8132db7a331638cdb7b9f7907180527d4a5d5a068097a32dea92da3c5a4d0f6.webp",
    "cod_hub/images/native/dd5e7dcbef3ea9716555b8b04920478c2deb478327a93606c93d9e411c42fb5e.webp",
    "cod_hub/images/native/e0691d0a3b9a8e28528910fda21fac93921f21fa7bcdb981e506783f629e7400.webp",
    "cod_hub/images/native/e276af45eb84845ded001632d281c472b60390879e54c4b3f412504c61cbae01.webp",
    "cod_hub/images/native/e38320cf8d5a2aba929b78cca16abe4aec0ba1705fff6516dce5d72e71e826e7.webp",
    "cod_hub/images/native/eec3d5dc616ae65954bb3394003bba13859f0f0f97ae357c9c7903eccd580142.webp",
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


def runtime_files(plugin_path):
    root = Path(plugin_path).absolute()
    raw = _member_path(root, "cod_hub/data/item-catalog.json").read_bytes()
    return (*FILES, *item_catalog_files(raw))


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
        for relative in runtime_files(plugin_path):
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
    native_artwork = evaluate_native_artwork(captured)
    item_catalog = evaluate_item_catalog(captured)
    item_artwork = evaluate_item_artwork(captured)
    native_guide = evaluate_native_guide(captured)
    report = {
        "plugin_id": manifest["id"], "version": manifest["version"], "sdk_version": __version__,
        "release_ready": english["ready"] and security["ready"] and native_artwork["ready"] and item_catalog["ready"] and item_artwork["ready"] and native_guide["ready"] and not sdk["errors"] and not sdk["warnings"],
        "english": {key: english[key] for key in ("ready", "required", "total_translated", "total_described", "total_english_covered", "counts")},
        "english_issue_count": len(english["issues"]), "sdk_validation": sdk,
        "artifact_policy": security,
        "native_artwork": native_artwork,
        "item_catalog": item_catalog,
        "item_artwork": item_artwork,
        "native_guide": native_guide,
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
