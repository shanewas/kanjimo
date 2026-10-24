"""Media step: puts the Kanji alive recordings the audio stage matched where nginx serves them.

    python3 media.py --zip audio-mp3.zip --www RELEASE/www

The audio stage (audio.py) leaves each word with url "audio/kanjialive/<name>.mp3". This copies
every referenced member out of the archive to www/media/audio/<sha256[:32]>.mp3 (the only shape
nginx serves, behind login) and rewrites the urls in items/ and cards/ to "../media/audio/...",
regenerating the .gz copies gzip_static uses. Run it on a fresh copy of a release. Stdlib only.
"""
import argparse
import gzip
import hashlib
import json
import sys
import zipfile
from pathlib import Path

PREFIX = "audio/kanjialive/"


def rewrite(entries: list, table: dict) -> int:
    n = 0
    for a in entries or []:
        if a.get("url", "").startswith(PREFIX) and a["url"] in table:
            a["url"] = table[a["url"]]
            n += 1
    return n


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--zip", required=True, type=Path)
    p.add_argument("--www", required=True, type=Path)
    a = p.parse_args()
    data, out = a.www / "data", a.www / "media" / "audio"
    files = sorted((data / "items").glob("level-*.json")) + sorted((data / "cards").glob("level-*.json"))
    wanted = set()
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        for rec in doc.get("items") or doc.get("cards") or []:
            wanted |= {x["url"] for x in rec.get("audio") or [] if x.get("url", "").startswith(PREFIX)}
    out.mkdir(parents=True, exist_ok=True)
    table, missing = {}, []
    with zipfile.ZipFile(a.zip) as z:
        members = {Path(m).name: m for m in z.namelist() if m.endswith(".mp3")}
        for url in sorted(wanted):
            m = members.get(url[len(PREFIX):])
            if m is None:
                missing.append(url)
                continue
            body = z.read(m)
            name = hashlib.sha256(body).hexdigest()[:32] + ".mp3"
            (out / name).write_bytes(body)
            table[url] = "../media/audio/" + name
    changed = 0
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        n = sum(rewrite(rec.get("audio"), table) for rec in doc.get("items") or doc.get("cards") or [])
        if n:
            body = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
            f.write_text(body, encoding="utf-8", newline="\n")
            with gzip.GzipFile(f.with_name(f.name + ".gz"), "wb", 9, mtime=0) as gz:
                gz.write(body.encode("utf-8"))
            changed += n
    print(f"{len(wanted)} recordings referenced, {len(table)} copied, {len(missing)} not in the archive, "
          f"{changed} urls rewritten")
    for url in missing[:20]:
        print("missing", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
