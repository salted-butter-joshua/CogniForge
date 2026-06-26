"""JSON extraction and retry helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

_THINKING_TYPES = frozenset({"thinking", "reasoning", "thought"})
_PAYLOAD_LIST_KEYS = ("questions", "results", "answers", "responses", "scores", "items", "data")


def llm_content_to_str(content: Any) -> str:
    """Normalize LangChain AIMessage.content (str or block list) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in _THINKING_TYPES:
                    continue
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                elif "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(content)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_thinking_obj(obj: Any) -> bool:
    return isinstance(obj, dict) and obj.get("type") in _THINKING_TYPES


def _unwrap_payload(obj: Any) -> Any:
    if isinstance(obj, dict):
        for key in _PAYLOAD_LIST_KEYS:
            if isinstance(obj.get(key), list):
                return obj[key]
    return obj


def _score_json_candidate(obj: Any) -> int:
    if _is_thinking_obj(obj):
        return -100
    obj = _unwrap_payload(obj)
    if isinstance(obj, list):
        return 50 + len(obj)
    if isinstance(obj, dict):
        return 10
    return 0


def _collect_json_candidates(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    candidates: list[Any] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx] not in "[{":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            candidates.append(obj)
            idx = max(end, idx + 1)
        except json.JSONDecodeError:
            idx += 1
    return candidates


def _extract_fenced_json(text: str) -> Any | None:
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        block = match.group(1).strip()
        if not block:
            continue
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if _is_thinking_obj(obj):
            continue
        return _unwrap_payload(obj)
    return None


def extract_json(content: Any) -> Any:
    """Parse JSON from LLM output; tolerates fences, prose, thinking blocks."""
    text = _strip_code_fence(llm_content_to_str(content))
    if not text:
        raise ValueError("Empty LLM response")

    fenced = _extract_fenced_json(text)
    if fenced is not None:
        return fenced

    try:
        whole = json.loads(text)
        if not _is_thinking_obj(whole):
            return _unwrap_payload(whole)
    except json.JSONDecodeError:
        pass

    candidates = _collect_json_candidates(text)
    if candidates:
        best = max(candidates, key=_score_json_candidate)
        if _score_json_candidate(best) >= 0:
            return _unwrap_payload(best)

    block_match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if block_match:
        parsed = json.loads(block_match.group(1))
        if not _is_thinking_obj(parsed):
            return _unwrap_payload(parsed)

    raise ValueError(f"Could not parse JSON from LLM output: {text[:200]}...")


def llm_retry():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
