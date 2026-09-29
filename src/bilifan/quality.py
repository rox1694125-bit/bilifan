"""Local, explainable quality checks shared by reading and export surfaces.

These checks identify reasons to compare an edited transcript with its source.
They do not establish factual accuracy, semantic equivalence or human approval.
"""
from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from .transcript_quality import check_transcript_quality
from .transcription_routing import COMMAND_RE

QUALITY_RULE_VERSION = "transcript-quality-v2.2"
QUALITY_LABELS = {
    "clean": "自动检查未发现明显异常",
    "needs_review": "需复查",
    "unusable": "不可用",
    "unknown": "未检查",
}
_MESSAGES = {
    "too_little_text": "视频较长但转录文字过少，或原稿为空，不能作为可用逐字稿。",
    "high_repetition": "转录存在大量重复片段，请核对是否发生识别异常。",
    "very_low_text_density": "转录文字与视频时长明显不相称，请核对是否漏录。",
    "expected_zh_but_low_cjk": "预期中文，但结果主要为英文，请核对识别语言。",
    "expected_en_but_low_ascii_words": "预期英文，但结果主要为中文，请核对识别语言。",
    "expected_zh_low_confidence": "中文识别结果的语言证据不足，请对照原视频。",
    "expected_en_low_confidence": "英文识别结果的语言证据不足，请对照原视频。",
    "metadata_language_conflict": "中文标题与英文转录存在冲突；输出像英文不能证明语言选择正确，请核对原视频。",
}
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[+-]?\d+(?:,\d{3})*(?:\.\d+)?")
_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9_])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(人民币|美元|万元|亿元|毫秒|分钟|小时|千米|厘米|毫米|公斤|千克|毫克|"
    r"元|秒|分|米|克|吨|年|月|天|日|次|个|倍|度|%|％|‰|℃|°C|"
    r"USD|CNY|RMB|GB|MB|KB|ms|cm|mm|km|kg|mg|s|h|m|g)(?![A-Za-z])", re.IGNORECASE,
)
_UNIT_ALIASES = {
    "人民币": "CNY", "元": "CNY", "cny": "CNY", "rmb": "CNY", "美元": "USD", "usd": "USD",
    "秒": "s", "毫秒": "ms", "分": "min", "分钟": "min", "小时": "h",
    "米": "m", "厘米": "cm", "毫米": "mm", "千米": "km", "公斤": "kg", "千克": "kg",
    "克": "g", "毫克": "mg", "％": "%", "℃": "celsius", "°c": "celsius",
}
# Only number/unit spellings are folded for quantity comparison. This is not a
# general Traditional-to-Simplified text conversion and never rewrites sources.
_QUANTITY_SPELLING_FOLD = str.maketrans({
    "兩": "两", "萬": "万", "億": "亿", "個": "个", "鐘": "钟",
    "時": "时", "噸": "吨", "幣": "币", "釐": "厘",
})
_CHINESE_QUANTITY_RE = re.compile(
    r"([零〇一二两三四五六七八九十百千万亿]+)(?=\s*(?:人民币|美元|万元|亿元|毫秒|分钟|小时|千米|厘米|毫米|公斤|千克|毫克|元|秒|分|米|克|吨|年|月|天|日|次|个|倍|度))"
)
_FILLERS_RE = re.compile(r"嗯+|呃+|额+|那个|这个嘛|就是说|就是|其实|然后然后|\b(?:um+|uh+|you know)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")
_CODE_RE = re.compile(r"```(?:[A-Za-z]+\n)?(.*?)```|`([^`\n]+)`", re.DOTALL)


def quality_label(status: str | dict[str, Any]) -> str:
    if isinstance(status, dict):
        status = str(status.get("status", "unknown"))
    return QUALITY_LABELS.get(status, QUALITY_LABELS["unknown"])


def quality_text(quality: dict[str, Any]) -> str:
    lines = [f"质量状态：{quality_label(quality)}", "自动检查仅提示异常，不代表内容已经人工核实。"]
    for reason in quality.get("reasons", []):
        if not isinstance(reason, dict):
            continue
        message = reason.get("message")
        if not isinstance(message, str) or not message:
            continue
        location = ""
        if isinstance(reason.get("start"), (int, float)):
            location = f"（原稿 {float(reason['start']):g} 秒起）"
        lines.append(f"- {message}{location}")
    return "\n".join(lines)


def build_quality(
    transcript: dict[str, Any],
    article: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recheck available evidence, preserving warnings and unknown coverage.

    Missing historical checks are not a passing check. Text-based checks can be
    rerun from raw segments, while missing duration/coverage evidence stays
    unknown. `article=None` means this is the raw-transcript stage.
    """
    transcript = transcript if isinstance(transcript, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    if article is not None and not isinstance(article, dict):
        article = {"sections": []}
    raw_segments = transcript.get("segments")
    segments = [s for s in raw_segments if isinstance(s, dict)] if isinstance(raw_segments, list) else []
    original_check = transcript.get("transcript_check")
    original_check = original_check if isinstance(original_check, dict) else {}
    duration = _positive_number(original_check.get("audio_seconds")) or _positive_number(metadata.get("duration")) or _positive_number(metadata.get("duration_seconds"))
    language = str(transcript.get("language") or "unknown").lower()
    expected_language = "zh" if language.startswith("zh") else "en" if language.startswith("en") else "unknown"
    local = check_transcript_quality(segments, expected_language=expected_language, metadata=metadata, audio_seconds=duration)
    saved = transcript.get("transcript_quality_check")
    saved = saved if isinstance(saved, dict) else {}
    saved_warnings = saved.get("warnings")
    saved_warnings = [code for code in saved_warnings if isinstance(code, str)] if isinstance(saved_warnings, list) else []
    codes = list(dict.fromkeys([*local.get("warnings", []), *saved_warnings]))
    reasons = [{"code": code, "message": _MESSAGES.get(code, f"已有转录检查提示：{code}，请核对原稿。")} for code in codes if isinstance(code, str)]
    transcript_status = _transcript_status(local.get("status"))
    saved_status = _transcript_status(saved.get("status")) if saved else "clean"
    transcript_status = _combine([transcript_status, saved_status])
    if transcript_status == "needs_review" and not reasons:
        reasons.append({"code": "transcript_previous_warning", "message": "已有转录检查提示需复查，请核对原稿。"})
    completeness, completeness_reasons = _completeness(segments, original_check, duration)
    reasons.extend(completeness_reasons)
    article_check, article_reasons = _article_fidelity(segments, article)
    reasons.extend(article_reasons)
    checks = {
        "transcript_quality": {"status": transcript_status, "observed_language": local["observed_language"], "metrics": local["metrics"]},
        "completeness": completeness,
        "article_fidelity": article_check,
    }
    status = _combine([c["status"] for c in checks.values()])
    return {
        "schema_version": 1,
        "rule_version": QUALITY_RULE_VERSION,
        "status": status,
        "review_required": status in {"needs_review", "unusable"},
        "checks": checks,
        "reasons": reasons,
    }


def _transcript_status(status: Any) -> str:
    if not isinstance(status, str):
        return "unknown"
    return {"ok": "clean", "unusable": "unusable", "low_confidence": "needs_review", "suspect_wrong_route": "needs_review"}.get(status, "unknown")


def _combine(statuses: list[str]) -> str:
    for status in ("unusable", "needs_review", "unknown"):
        if status in statuses:
            return status
    return "clean"


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _completeness(segments: list[dict[str, Any]], saved: dict[str, Any], duration: float | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not segments:
        return {"status": "unusable"}, [{"code": "transcript_empty", "message": "没有可供核对的原始转录片段。"}]
    status = saved.get("status")
    status = status if isinstance(status, str) else None
    if status in {"empty", "transcript_incomplete"}:
        return {"status": "needs_review"}, [{"code": "transcript_incomplete", "message": "原始转录的时间覆盖不完整，请核对缺失部分。"}]
    if duration:
        ends = [_positive_number(s.get("end")) for s in segments]
        last_end = max((end for end in ends if end is not None), default=0)
        if abs(duration - last_end) > max(10, duration * 0.05):
            return {"status": "needs_review"}, [{"code": "transcript_incomplete", "message": "原始转录结尾与视频时长不符，请核对缺失部分。", "start": last_end}]
        return {"status": "clean"}, []
    if status == "ok":
        return {"status": "clean", "evidence": "saved_completeness_check"}, []
    return {"status": "unknown"}, [{"code": "completeness_not_checked", "message": "缺少完整性检查或视频时长，时间覆盖尚未检查。"}]


def _article_fidelity(segments: list[dict[str, Any]], article: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if article is None:
        return {"status": "not_applicable"}, []
    sections = article.get("sections")
    if not isinstance(sections, list) or not sections:
        return {"status": "unusable"}, [{"code": "article_missing_sections", "message": "整理稿没有有效章节。", **_locator(segments, 0, max(0, len(segments) - 1))}]
    reasons: list[dict[str, Any]] = []
    covered: set[int] = set()
    unknown = False
    for position, section in enumerate(sections, 1):
        if not isinstance(section, dict):
            unknown = True
            continue
        start, end = section.get("source_segment_start_index"), section.get("source_segment_end_index")
        section_id = str(section.get("id") or section.get("section_index") or position)
        if (type(start) is not int or type(end) is not int or start < 0 or end < start or end >= len(segments)):
            unknown = True
            reasons.append({"code": "article_source_unavailable", "message": "整理章节缺少有效原稿位置，无法完成来源对照。", "section_id": section_id, **_locator(segments, 0, max(0, len(segments) - 1))})
            continue
        covered.update(range(start, end + 1))
        locator = {"section_id": section_id, **_locator(segments, start, end)}
        raw = "\n".join(str(s.get("text") or "") for s in segments[start:end + 1])
        paragraphs = section.get("paragraphs")
        paragraphs = paragraphs if isinstance(paragraphs, list) else []
        edited = "\n".join(str(p.get("text") or "") for p in paragraphs if isinstance(p, dict))
        if not edited.strip():
            reasons.append({"code": "article_substantive_omission", "message": "整理章节没有正文，请核对是否遗漏原稿内容。", **locator})
            continue
        for code, message, before, after in (
            ("article_numbers_changed", "整理稿中的数字与原稿不同，请对照核对，不能仅凭整理结果判定正确。", _numbers(raw), _numbers(edited)),
            ("article_units_changed", "整理稿中的数值单位与原稿不同，请对照核对。", _units(raw), _units(edited)),
        ):
            if before != after:
                reasons.append({"code": code, "message": message, **locator})
        if _code_changed(raw, edited):
            reasons.append({"code": "article_code_changed", "message": "整理稿中的命令或代码与原稿不同，请对照核对。", **locator})
        original_tokens, edited_tokens = _tokens(raw), _tokens(edited)
        matcher = SequenceMatcher(None, original_tokens, edited_tokens, autojunk=False)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        if _substantive_delta(original_tokens, len(original_tokens) - matched):
            reasons.append({"code": "article_substantive_omission", "message": "这一章节有较多原稿内容未在整理稿中匹配到，请核对是否漏掉实质内容。", **locator})
        if _substantive_delta(edited_tokens, len(edited_tokens) - matched):
            reasons.append({"code": "article_substantive_addition", "message": "这一章节有较多整理内容无法直接匹配原稿，请核对是否新增了解读或推断。", **locator})
    missing = [i for i, s in enumerate(segments) if i not in covered and (_substantial_text(str(s.get("text") or "")) or _numbers(str(s.get("text") or "")))]
    for group in _consecutive_groups(missing):
        reasons.append({"code": "article_uncovered_segments", "message": "这一段原稿没有对应整理章节，请核对是否遗漏。", **_locator(segments, group[0], group[-1])})
    warnings = any(r["code"] != "article_source_unavailable" for r in reasons)
    status = "needs_review" if warnings else "unknown" if unknown else "clean"
    return {"status": status, "covered_segments": len(covered), "total_segments": len(segments)}, reasons


def _locator(segments: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    result: dict[str, Any] = {"segment_start_index": start, "segment_end_index": end}
    if 0 <= start < len(segments):
        value = segments[start].get("start")
        if isinstance(value, (int, float)) and math.isfinite(value):
            result["start"] = value
    if 0 <= end < len(segments):
        value = segments[end].get("end")
        if isinstance(value, (int, float)) and math.isfinite(value):
            result["end"] = value
    return result


def _canonical_number(text: str) -> str:
    try:
        return str(Decimal(text.replace(",", "")).normalize())
    except InvalidOperation:
        return text


def _numbers(text: str) -> set[str]:
    return {_canonical_number(m.group()) for m in _NUMBER_RE.finditer(_number_forms(text))}


def _units(text: str) -> set[tuple[str, str]]:
    return {(_canonical_number(m[1]), _UNIT_ALIASES.get(m[2].lower(), m[2].lower())) for m in _UNIT_RE.finditer(_number_forms(text))}


def _number_forms(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUANTITY_SPELLING_FOLD)
    return _CHINESE_QUANTITY_RE.sub(lambda m: str(_chinese_integer(m[1])), text)


def _chinese_integer(text: str) -> int:
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    if all(char in digits for char in text):
        return int("".join(str(digits[char]) for char in text))
    for unit, scale in (("亿", 100000000), ("万", 10000)):
        if unit in text:
            left, right = text.split(unit, 1)
            return _chinese_integer(left or "一") * scale + (_chinese_integer(right) if right else 0)
    units = {"十": 10, "百": 100, "千": 1000}
    section = digit = 0
    for char in text:
        if char in digits:
            digit = digits[char]
        else:
            section += (digit or 1) * units[char]
            digit = 0
    return section + digit


def _tokens(text: str) -> list[str]:
    text = _FILLERS_RE.sub(" ", unicodedata.normalize("NFKC", text).lower())
    return _TOKEN_RE.findall(text)


def _substantive_delta(tokens: list[str], missing: int) -> bool:
    cjk = sum(1 for t in tokens if len(t) == 1 and "\u4e00" <= t <= "\u9fff")
    minimum = 18 if cjk > len(tokens) / 2 else 7
    return missing >= minimum and missing / max(1, len(tokens)) >= 0.4


def _substantial_text(text: str) -> bool:
    tokens = _tokens(text)
    return _substantive_delta(tokens, len(tokens))


def _code_changed(before: str, after: str) -> bool:
    # Formatting backticks may be added or removed; compare their contents, not
    # the markup. A bare product name like `Git` is not a code change.
    for text, other in ((before, after), (after, before)):
        candidates = [m[1] or m[2] for m in _CODE_RE.finditer(text)]
        candidates.extend(m.group() for m in COMMAND_RE.finditer(text))
        for fragment in candidates:
            fragment = fragment.strip().strip("`。；;,.")
            if not re.search(r"[\s._()=:/-]", fragment):
                continue
            compact = re.sub(r"\s+", "", fragment.replace("`", ""))
            if compact and compact not in re.sub(r"\s+", "", other.replace("`", "")):
                return True
    return False


def _consecutive_groups(indices: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in indices:
        if groups and groups[-1][-1] + 1 == index:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups
