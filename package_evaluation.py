"""Create a minimal, deterministic local archive from the staged Git file set."""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parent
PREFIX = "kimura-boundary-proof"


def git_bytes(*arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True,
                          capture_output=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("write the package outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = [entry for entry in git_bytes("ls-files", "--stage", "-z").split(b"\0")
               if entry]
    if not entries:
        raise RuntimeError("no staged or committed files found")

    with output.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
                for entry in entries:
                    metadata, raw_name = entry.split(b"\t", 1)
                    mode, _, stage = metadata.decode().split()
                    name = raw_name.decode()
                    path = PurePosixPath(name)
                    if (stage != "0" or mode not in {"100644", "100755"} or
                            path.is_absolute() or ".." in path.parts or ".git" in path.parts):
                        raise ValueError(f"unsafe index entry: {name}")
                    data = git_bytes("show", f":{name}")
                    member = tarfile.TarInfo(f"{PREFIX}/{name}")
                    member.size = len(data)
                    member.mode = 0o755 if mode == "100755" else 0o644
                    member.uid = member.gid = member.mtime = 0
                    member.uname = member.gname = ""
                    archive.addfile(member, io.BytesIO(data))
    print(json.dumps({"path": str(output), "files": len(entries),
                      "sha256": sha256(output.read_bytes()).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
