"""Build metadata, audit portable bundles, and create release ZIP/checksum pairs."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thaum_nexus.version import VERSION

# Keep individual files comfortably below GitHub's 100 MiB repository limit.
MAX_FILE_BYTES = 95 * 1024 * 1024
REQUIRED = (
    "ThaumcraftNexus.exe", "LICENSE", "THIRD_PARTY_NOTICES.md", "README_CN.txt",
    "_internal/build-info.json", "_internal/java-agent/thaum-nexus-agent.jar",
    "_internal/data/aspects.json", "_internal/data/adjacency.json",
    "_internal/data/combinations.json", "_internal/data/manifest.json",
    "_internal/image/icons8-github-50.png",
    "_internal/image/thaumonomicon_bg_clean.png",
)


def validate_environment(requirements: Path, installed: dict[str, str] | None = None) -> None:
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    expected = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = line.split("==")
            expected[normalize(name)] = version
    if installed is None:
        installed = {dist.metadata["Name"]: dist.version for dist in metadata.distributions()}
    actual = {normalize(k): v for k, v in installed.items() if normalize(k) != "pip"}
    if actual != expected:
        raise ValueError(f"Build environment differs from pinned requirements. Expected {expected}, found {actual}. Run without -SkipPyInstallerInstall to recreate it.")


def build_metadata(project: Path, version: str | None = None) -> dict:
    version = version.removeprefix("v") if version else VERSION
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[.-][A-Za-z0-9.-]+)?", version):
        raise ValueError("Version must be a version number such as v1.2.3")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(project), *args], text=True).strip()
    commit = git("rev-parse", "HEAD")
    # Source status excludes the checked-in generated package and local agent state.
    # Dependency pins constrain build inputs; this does not claim byte-identical output.
    return {"version": version, "commit": commit,
            "dirty": bool(git("status", "--porcelain", "--untracked-files=normal", "--", ".", ":(exclude)dist", ":(exclude).omx")),
            "python": sys.version.split()[0]}


def verify_package(root: Path, max_file_bytes: int = MAX_FILE_BYTES) -> dict:
    root = root.resolve()
    for name in REQUIRED:
        if not (root / name).is_file():
            raise ValueError(f"Missing required file: {name}")
    info = json.loads((root / "_internal/build-info.json").read_text(encoding="utf-8"))
    if not isinstance(info, dict) or not isinstance(info.get("version"), str) or not re.fullmatch(r"[0-9a-f]{40}", str(info.get("commit", ""))):
        raise ValueError("Invalid build metadata")
    total = count = 0
    unwanted = {"runtime", "debug", ".git", "__pycache__", "numpy", "numpy.libs", "cv2", "scipy", "matplotlib"}
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if path.is_symlink():
            raise ValueError(f"Unwanted symbolic link: {path}")
        if any(p.lower() in unwanted for p in parts):
            raise ValueError(f"Unwanted package content: {path}")
        if path.is_file():
            size = path.stat().st_size
            if size >= max_file_bytes:
                raise ValueError(f"File exceeds size limit: {path} ({size} bytes)")
            total += size
            count += 1
    return {"files": count, "bytes": total, "build": info}


def package_release(root: Path, archive: Path) -> Path:
    verify_package(root)
    root, archive = root.resolve(), archive.resolve()
    if archive.is_relative_to(root):
        raise ValueError("Archive must be outside the portable folder")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zipped.write(path, str(Path(root.name) / path.relative_to(root)))
    if archive.stat().st_size >= 2 * 1024**3:
        raise ValueError("ZIP exceeds GitHub Release asset size limit")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest.hexdigest()}  {archive.name}\n", encoding="utf-8")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    metadata = commands.add_parser("metadata")
    metadata.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    metadata.add_argument("--version")
    metadata.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("folder", type=Path)
    package = commands.add_parser("package")
    package.add_argument("folder", type=Path)
    package.add_argument("archive", type=Path)
    environment = commands.add_parser("check-environment")
    environment.add_argument("requirements", type=Path)
    args = parser.parse_args()
    if args.command == "metadata":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(build_metadata(args.project, args.version), indent=2) + "\n", encoding="utf-8")
    elif args.command == "verify":
        print(json.dumps(verify_package(args.folder), indent=2))
    elif args.command == "check-environment":
        validate_environment(args.requirements)
    else:
        print(package_release(args.folder, args.archive))


if __name__ == "__main__":
    main()
