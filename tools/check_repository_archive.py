"""Keep GitHub repository imports below 50 MB without changing hosted artwork."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 50_000_000
HOSTED_ARTWORK = "docs/artwork/items/v1/"


def blob_id(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def inspect_archive(path, tracked):
    """Verify every retained file against its Git blob, including all plugin data."""
    compressed = Path(path).stat().st_size
    if compressed >= LIMIT_BYTES:
        raise ValueError("Repository ZIP must be smaller than 50,000,000 bytes.")
    expected = {name: digest for name, digest in tracked.items() if not name.startswith(HOSTED_ARTWORK)}
    with zipfile.ZipFile(path) as archive:
        members = [entry for entry in archive.infolist() if not entry.is_dir()]
        expanded = sum(entry.file_size for entry in members)
        if expanded >= LIMIT_BYTES:
            raise ValueError("Expanded repository archive must be smaller than 50,000,000 bytes.")
        names = [entry.filename for entry in members]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("Archive must omit only the externally hosted item-image library.")
        for entry in members:
            if blob_id(archive.read(entry)) != expected[entry.filename]:
                raise ValueError("An archived file differs from its committed bytes: " + entry.filename)
    return {"ready": True, "compressed_bytes": compressed, "expanded_bytes": expanded,
            "limit_bytes": LIMIT_BYTES, "files_verified": len(expected),
            "plugin_files_verified": sum(name.startswith("plugin/") for name in expected),
            "hosted_artwork_files_omitted": len(tracked) - len(expected),
            "all_retained_files_byte_identical": True}


def check(root=ROOT, *, output=None):
    root = Path(root)
    listing = subprocess.run(["git", "ls-tree", "-rz", "--full-tree", "HEAD"], cwd=root,
                             check=True, stdout=subprocess.PIPE).stdout
    tracked = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, digest = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Repository archive requires ordinary tracked files.")
        tracked[name.decode("utf8")] = digest.decode("ascii")
    with tempfile.TemporaryDirectory(prefix="cod-hub-repository-archive-") as temporary:
        path = Path(temporary) / "repository.zip"
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=zip", "--worktree-attributes", "--output=" + str(path), "HEAD"],
                       cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        report = inspect_archive(path, tracked)
        if output is not None:
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(path.read_bytes())
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optionally retain the checked repository ZIP.")
    args = parser.parse_args()
    try:
        print(json.dumps(check(output=args.output), indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(json.dumps({"ready": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
