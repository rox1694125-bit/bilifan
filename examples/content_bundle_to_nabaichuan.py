from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from bilifan.exports import ExportError, build_nabaichuan_records
except ModuleNotFoundError as exc:
    if exc.name != "bilifan":
        raise
    src_dir = Path(__file__).resolve().parents[1] / "src"
    if src_dir.is_dir():
        sys.path.insert(0, str(src_dir))
    from bilifan.exports import ExportError, build_nabaichuan_records


def convert_bundle(
    bundle: dict[str, Any],
    *,
    include_transcript: bool = True,
) -> list[dict[str, Any]]:
    return build_nabaichuan_records(
        bundle,
        include_transcript=include_transcript,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Bilifan content_bundle.json to Nabaichuan-style JSONL."
    )
    parser.add_argument("bundle")
    parser.add_argument("--out", required=True)
    transcript_group = parser.add_mutually_exclusive_group()
    transcript_group.add_argument(
        "--include-transcript",
        dest="include_transcript",
        action="store_true",
        default=True,
        help="Include transcript segment records. This is the default.",
    )
    transcript_group.add_argument(
        "--no-transcript",
        dest="include_transcript",
        action="store_false",
        help="Omit transcript segment records.",
    )
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        parser.error("bundle must be a JSON object")

    try:
        rows = convert_bundle(bundle, include_transcript=args.include_transcript)
    except ExportError as exc:
        parser.error(str(exc))
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
