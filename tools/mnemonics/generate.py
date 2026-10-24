"""Runs the mnemonic requests from prepare.py through the Claude API.

    python generate.py pilot   DIR CUSTOM_ID...   # synchronous, a few chunks, for review
    python generate.py submit  DIR [--only IDS_FILE]
    python generate.py collect DIR                # waits for the batch, appends results.jsonl

The API key comes from the environment (ANTHROPIC_API_KEY); nothing here prints it.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

client = anthropic.Anthropic()


def requests(d: Path) -> dict:
    return {r["custom_id"]: r for r in map(json.loads, open(d / "requests.jsonl", encoding="utf-8"))}


def text_of(msg) -> str | None:
    if msg.stop_reason == "refusal":
        return None
    return next((b.text for b in msg.content if b.type == "text"), None)


def save(d: Path, custom_id: str, text: str | None, usage) -> None:
    rec = {"custom_id": custom_id, "ok": text is not None, "usage": usage.model_dump() if usage else None}
    if text is not None:
        rec["items"] = json.loads(text)["items"]
    with open(d / "results.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def pilot(d: Path, ids: list[str]) -> None:
    reqs = requests(d)
    for cid in ids:
        msg = client.messages.create(**reqs[cid]["params"])
        save(d, cid, text_of(msg), msg.usage)
        print(cid, msg.stop_reason, msg.usage.input_tokens, msg.usage.output_tokens)


def submit(d: Path, only: Path | None) -> None:
    reqs = requests(d)
    keep = set(only.read_text(encoding="utf-8").split()) if only else set(reqs)
    batch = client.messages.batches.create(requests=[
        Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**r["params"]))
        for cid, r in reqs.items() if cid in keep])
    (d / "batch_id.txt").write_text(batch.id, encoding="utf-8")
    print("batch", batch.id, len(keep), "requests")


def collect(d: Path) -> None:
    bid = (d / "batch_id.txt").read_text(encoding="utf-8").strip()
    while True:
        b = client.messages.batches.retrieve(bid)
        if b.processing_status == "ended":
            break
        print(time.strftime("%H:%M"), b.request_counts.processing, "processing", flush=True)
        time.sleep(120)
    bad = 0
    for res in client.messages.batches.results(bid):
        if res.result.type == "succeeded":
            save(d, res.custom_id, text_of(res.result.message), res.result.message.usage)
        else:
            bad += 1
            save(d, res.custom_id, None, None)
    print("done", b.request_counts.succeeded, "succeeded", bad, "not")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["pilot", "submit", "collect"])
    p.add_argument("dir", type=Path)
    p.add_argument("ids", nargs="*")
    p.add_argument("--only", type=Path)
    a = p.parse_args()
    try:
        if a.cmd == "pilot":
            pilot(a.dir, a.ids)
        elif a.cmd == "submit":
            submit(a.dir, a.only)
        else:
            collect(a.dir)
    except anthropic.RateLimitError as exc:
        print("rate limited:", exc, file=sys.stderr)
        return 2
    except anthropic.APIStatusError as exc:
        print("API error", exc.status_code, exc.message, file=sys.stderr)
        return 1
    except anthropic.APIConnectionError as exc:
        print("connection error:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
