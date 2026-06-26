"""RAG retrieval over injected chunk snapshots."""

from __future__ import annotations

import re
from typing import Iterable


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(t) > 1}


def retrieve_chunks(
    chunks: list[dict],
    weak_topics: list[str],
    persona_style: str = "",
    top_k: int = 8,
) -> list[dict]:
    if not chunks:
        return []

    query_terms = _tokenize(" ".join(weak_topics) + " " + persona_style)
    if not query_terms:
        return chunks[:top_k]

    scored: list[tuple[float, dict]] = []
    for chunk in chunks:
        text = chunk.get("content", "")
        terms = _tokenize(text)
        if not terms:
            continue
        overlap = len(query_terms & terms) / max(len(query_terms), 1)
        scored.append((overlap, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [c for s, c in scored[:top_k] if s > 0]
    return selected or chunks[:top_k]


def search_corpus(
    chunks: list[dict],
    queries: list[str],
    top_k: int = 5,
) -> list[dict]:
    """Lightweight 'online search' fallback: keyword retrieval over full corpus."""
    if not queries:
        return []

    query_terms = _tokenize(" ".join(queries))
    if not query_terms:
        return []

    scored: list[tuple[float, dict]] = []
    for chunk in chunks:
        terms = _tokenize(chunk.get("content", ""))
        if not terms:
            continue
        overlap = len(query_terms & terms) / max(len(query_terms), 1)
        if overlap > 0:
            scored.append((overlap, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    results: list[dict] = []
    for score, chunk in scored[:top_k]:
        results.append(
            {
                "source": "corpus_search",
                "chunk_id": chunk.get("id"),
                "title": chunk.get("title"),
                "snippet": chunk.get("content", "")[:500],
                "score": round(score, 3),
            }
        )
    return results


def valid_evidence_refs(refs: Iterable[str], chunks: list[dict]) -> bool:
    valid_ids = {c.get("id") for c in chunks}
    return bool(refs) and all(r in valid_ids for r in refs)
