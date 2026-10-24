"""Builds one release tree for Navi: server/ (the API package) and www/ (app + open content).

    py -I tools/release.py --content BUILD/open --out BUILD/release/<sha>

www/data takes only the files nginx serves, each JSON/SVG/JS/CSS also gzipped for gzip_static.
Refuses content from the repo's scraped data/ directory and any served file naming the scraped
course. Stdlib only.
"""
import argparse
import gzip
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = b"wanikani"
DATA_FILES = ("search-index.json", "ATTRIBUTION.json")
DATA_DIRS = ("cards", "items", "own", "images")
GZIP_SUFFIXES = {".json", ".svg", ".js", ".css", ".html"}


class ReleaseError(Exception):
    pass


def copy_content(content: Path, data: Path) -> None:
    for name in DATA_FILES:
        shutil.copy2(content / name, data / name)
    for name in DATA_DIRS:
        if (content / name).is_dir():
            shutil.copytree(content / name, data / name)
    for path in data.rglob("*"):
        if path.is_file() and FORBIDDEN in path.read_bytes().lower():
            raise ReleaseError(f"refusing {path}: it mentions the scraped course")


def gzip_tree(root: Path) -> None:
    for path in list(root.rglob("*")):
        if path.is_file() and path.suffix in GZIP_SUFFIXES:
            with open(path, "rb") as src, gzip.GzipFile(path.with_name(path.name + ".gz"), "wb", 9, mtime=0) as dst:
                shutil.copyfileobj(src, dst)


def build(content: Path, out: Path, version: str) -> None:
    content, out = content.resolve(), out.resolve()
    if content.is_relative_to(REPO / "data"):
        raise ReleaseError("refusing the repo's data/ directory: it holds the scraped course")
    if not (content / "search-index.json").is_file():
        raise ReleaseError(f"{content} has no search-index.json")
    if out.exists():
        raise ReleaseError(f"{out} already exists")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "tests")
    server = out / "server"
    shutil.copytree(REPO / "server" / "jstudy", server / "jstudy", ignore=ignore)
    for name in ("requirements.txt", "requirements.lock", "pyproject.toml"):
        if (REPO / "server" / name).is_file():
            shutil.copy2(REPO / "server" / name, server / name)
    www = out / "www"
    shutil.copytree(REPO / "app", www / "app", ignore=ignore)
    (www / "app" / "version.txt").write_text(version + "\n", encoding="utf-8", newline="\n")
    shutil.copytree(REPO / "legal", www / "legal")
    shutil.copytree(REPO / "site", www, dirs_exist_ok=True)  # public pages such as /about/
    (www / "data").mkdir(parents=True)
    copy_content(content, www / "data")
    gzip_tree(www)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    version = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"], check=True,
                             capture_output=True, encoding="utf-8", errors="replace").stdout.strip()
    try:
        build(args.content, args.out, version)
    except (ReleaseError, OSError) as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    print(f"release {version} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
