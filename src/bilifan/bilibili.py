from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class BilibiliPartRef:
    bvid: str
    part_index: int
    sanitized_url: str

    @property
    def output_id(self) -> str:
        return f"{self.bvid}_p{self.part_index}"

    def timestamp_url(self, seconds: float) -> str:
        timestamp = max(0, int(seconds))
        return f"https://www.bilibili.com/video/{self.bvid}?p={self.part_index}&t={timestamp}"


def parse_bilibili_url(url: str) -> BilibiliPartRef:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Expected a supported Bilibili video URL.")
    if parsed.netloc not in {"www.bilibili.com", "bilibili.com"}:
        raise ValueError("Expected a supported Bilibili video URL.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "video" or not parts[1].startswith("BV"):
        raise ValueError("Expected a supported Bilibili video URL.")

    bvid = parts[1]
    query = parse_qs(parsed.query)
    raw_part = query.get("p", ["1"])[0]

    try:
        part_index = int(raw_part)
    except ValueError as exc:
        raise ValueError("Bilibili part index must be a positive integer.") from exc

    if part_index < 1:
        raise ValueError("Bilibili part index must be a positive integer.")

    sanitized_url = f"https://www.bilibili.com/video/{bvid}?p={part_index}"
    return BilibiliPartRef(
        bvid=bvid,
        part_index=part_index,
        sanitized_url=sanitized_url,
    )
