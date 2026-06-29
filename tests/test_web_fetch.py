"""Tests for handbook-aware web fetch."""

from src.tools.web_fetch import (
    _handbook_path_segments,
    _is_noise_heading,
    build_chapter_registry,
    parse_handbook_curriculum,
    select_curriculum_urls,
)

HANDBOOK_INDEX_SNIPPET = """
<html><body>
<div class="book-part">
  <div class="book-part__title">Part I · 基础</div>
  <a href="/zh/book/kubernetes-handbook/architecture/">Kubernetes 架构</a>
  <a href="/zh/book/kubernetes-handbook/architecture/overview/">概述</a>
  <a href="/zh/book/kubernetes-handbook/architecture/etcd/">Etcd 解析</a>
</div>
<div class="book-part">
  <div class="book-part__title">Part II · 进阶</div>
  <a href="/zh/book/kubernetes-handbook/security/">安全</a>
</div>
</body></html>
"""

SEED = "https://jimmysong.io/zh/book/kubernetes-handbook/"


def test_handbook_path_segments():
    assert _handbook_path_segments(
        "https://jimmysong.io/zh/book/kubernetes-handbook/architecture/etcd",
        SEED,
    ) == ["architecture", "etcd"]


def test_parse_handbook_curriculum_skips_chapter_index_when_leaves_exist():
    curriculum = parse_handbook_curriculum(HANDBOOK_INDEX_SNIPPET, SEED)
    assert curriculum is not None
    urls = [e["url"] for e in curriculum]
    assert any("architecture/overview" in u for u in urls)
    assert any("architecture/etcd" in u for u in urls)
    assert not any(u.endswith("/architecture") for u in urls)
    assert not any("/kubernetes-handbook" == u.rstrip("/").split("/")[-1] and "architecture" not in u for u in urls)


def test_curriculum_display_titles():
    curriculum = parse_handbook_curriculum(HANDBOOK_INDEX_SNIPPET, SEED)
    etcd = next(e for e in curriculum if "etcd" in e["url"])
    assert "Kubernetes 架构" in etcd["display_title"]
    assert "Etcd 解析" in etcd["display_title"]
    assert etcd["part_title"].startswith("Part I")


def test_noise_headings():
    assert _is_noise_heading("章节目录")
    assert not _is_noise_heading("Etcd 解析")


def test_registry_one_entry_per_leaf():
    chunks = [
        {
            "chapter_id": "a",
            "chapter_title": "Kubernetes 架构 · 概述",
            "chapter_order": 1,
            "part_title": "Part I",
            "url": "https://x/overview",
        },
        {
            "chapter_id": "a",
            "chapter_title": "Kubernetes 架构 · 概述",
            "chapter_order": 1,
            "part_title": "Part I",
            "url": "https://x/overview",
        },
        {
            "chapter_id": "b",
            "chapter_title": "Kubernetes 架构 · Etcd 解析",
            "chapter_order": 2,
            "part_title": "Part I",
            "url": "https://x/etcd",
        },
    ]
    reg = build_chapter_registry(chunks)
    assert len(reg) == 2
    assert reg[0]["part_title"] == "Part I"


def test_select_curriculum_urls_respects_limit():
    curriculum = parse_handbook_curriculum(HANDBOOK_INDEX_SNIPPET, SEED) or []
    picked = select_curriculum_urls(curriculum, max_pages=2)
    assert len(picked) == 2
    all_picked = select_curriculum_urls(curriculum, max_pages=0)
    assert len(all_picked) == len(curriculum)


def test_probe_handbook_curriculum_from_snippet():
    from src.tools.web_fetch import probe_crawl_scope

    # probe needs live fetch; test parse path via curriculum count logic
    curriculum = parse_handbook_curriculum(HANDBOOK_INDEX_SNIPPET, SEED)
    assert curriculum is not None
    assert len(curriculum) == 3
