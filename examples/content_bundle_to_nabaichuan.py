from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def convert_bundle(
    bundle: dict[str, Any],
    *,
    include_transcript: bool = False,
) -> list[dict[str, Any]]:
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    bundle_id = str(bundle.get("bundle_id") or "")
    rows: list[dict[str, Any]] = [
        {
            "type": "video",
            "source_id": bundle_id,
            "platform": source.get("platform"),
            "title": source.get("title"),
            "author": source.get("author"),
            "source_url": source.get("canonical_url"),
        }
    ]

    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    chapters = summary.get("chapters") if isinstance(summary.get("chapters"), list) else []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        index = chapter.get("chapter_index")
        rows.append(
            {
                "type": "chapter",
                "source_id": f"{bundle_id}#chapter-{index}",
                "parent_source_id": bundle_id,
                "title": chapter.get("title"),
                "summary": chapter.get("summary"),
                "key_points": chapter.get("key_points") or [],
                "source_url": chapter.get("timestamp_url"),
            }
        )

    if include_transcript:
        transcript = (
            bundle.get("transcript")
            if isinstance(bundle.get("transcript"), dict)
            else {}
        )
        segments = (
            transcript.get("segments")
            if isinstance(transcript.get("segments"), list)
            else []
        )
        for index, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict):
                continue
            rows.append(
                {
                    "type": "transcript_segment",
                    "source_id": f"{bundle_id}#segment-{index}",
                    "parent_source_id": bundle_id,
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": segment.get("text"),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Bilifan content_bundle.json to Nabaichuan-style JSONL."
    )
    parser.add_argument("bundle")
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-transcript", action="store_true")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        parser.error("bundle must be a JSON object")

    rows = convert_bundle(bundle, include_transcript=args.include_transcript)
    Path(args.out).write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
