"""Web page fetch, scope crawl, and chunking utilities."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString

from src.config import get_settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 6000
MIN_CONTENT_LEN = 200
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; CogniForgeBot/1.0; +https://github.com/loop-engineering)"
)
SKIP_HREF_PREFIXES = ("#", "mailto:", "javascript:", "tel:", "data:")

# Section headings that are navigation/meta, not teachable content.
NOISE_SECTION_HEADINGS = frozenset(
    {
        "章节目录",
        "关于本书",
        "关于本教程",
        "关于本手册",
        "目录",
        "下载 pdf",
        "download pdf",
        "table of contents",
        "about this book",
    }
)

NOISE_CONTENT_SELECTORS = (
    ".homepage-node",
    ".book-toc-grid",
    ".alert-info",
    ".page-meta",
    ".breadcrumb",
    "nav",
    "footer",
    ".docs-sidebar",
    ".pagination",
)


def _clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def scope_prefix(seed_url: str) -> str:
    """Directory scope for same-site child pages (e.g. handbook TOC)."""
    return normalize_url(seed_url)


def is_under_scope(url: str, seed_url: str) -> bool:
    target = normalize_url(url)
    prefix = scope_prefix(seed_url)
    if target == prefix:
        return True
    return target.startswith(prefix + "/")


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, follow_redirects=True)


def _assert_url_allowed(url: str) -> None:
    """SSRF guard: reject non-HTTP(S) schemes and private/loopback/reserved hosts.

    Note: this validates the requested URL. Redirects are still followed by the
    client, so a public host redirecting to an internal one is not covered here.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no host: {url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve host {host}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise ValueError(f"Blocked non-public address for {host}: {ip}")


def fetch_html(url: str, client: httpx.Client | None = None) -> str:
    _assert_url_allowed(url)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if client is None:
        with _http_client() as c:
            resp = c.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text


def _handbook_path_segments(url: str, seed_url: str) -> list[str]:
    """Path segments after the handbook scope prefix (e.g. architecture/etcd)."""
    prefix = scope_prefix(seed_url)
    target = normalize_url(url)
    if target == prefix:
        return []
    marker = prefix.rstrip("/") + "/"
    if not target.startswith(marker):
        return []
    tail = target[len(marker) :].strip("/")
    return [p for p in tail.split("/") if p]


def _is_noise_heading(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in NOISE_SECTION_HEADINGS:
        return True
    if "章节目录" in t or "table of contents" in t:
        return True
    return False


def parse_handbook_curriculum(html: str, seed_url: str) -> list[dict] | None:
    """Parse Part → Chapter → Section tree from handbook index/sidebar.

    Returns None when the page does not look like a structured handbook TOC.
    """
    soup = BeautifulSoup(html, "lxml")
    parts = soup.select(".book-part")
    if not parts:
        return None

    seed = scope_prefix(seed_url)
    entries: list[dict] = []
    order = 0

    for part in parts:
        title_el = part.select_one(".book-part__title")
        part_title = title_el.get_text(strip=True) if title_el else ""

        chapter_slugs: set[str] = set()
        raw_links: list[tuple[str, str, list[str]]] = []

        for anchor in part.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href or href.lower().startswith(SKIP_HREF_PREFIXES):
                continue
            full = normalize_url(urljoin(seed, href))
            if not is_under_scope(full, seed):
                continue
            segs = _handbook_path_segments(full, seed)
            if not segs:
                continue
            label = anchor.get_text(strip=True) or segs[-1]
            raw_links.append((label, full, segs))
            if len(segs) == 1:
                chapter_slugs.add(segs[0])

        chapters_with_leaves: set[str] = {
            segs[0] for _, _, segs in raw_links if len(segs) >= 2
        }

        for label, full, segs in raw_links:
            depth = len(segs)
            if depth == 1 and segs[0] in chapters_with_leaves:
                continue
            if depth >= 3:
                continue

            chapter_slug = segs[0]
            chapter_title = next(
                (lbl for lbl, url, s in raw_links if s == [chapter_slug]),
                chapter_slug.replace("-", " ").title(),
            )
            section_title = label if depth >= 2 else ""
            if depth >= 2:
                display = f"{chapter_title} · {section_title}"
            else:
                display = chapter_title

            order += 1
            entries.append(
                {
                    "url": full,
                    "part_title": part_title,
                    "chapter_slug": chapter_slug,
                    "chapter_title": chapter_title,
                    "section_title": section_title,
                    "display_title": display,
                    "chapter_id": _chapter_key(full, display),
                    "chapter_order": order,
                    "depth": depth,
                }
            )

    return entries or None


def select_curriculum_urls(
    curriculum: list[dict],
    *,
    max_pages: int,
) -> list[dict]:
    """Return ordered curriculum entries to fetch (respect max_pages).

    max_pages <= 0 means fetch all discovered entries.
    """
    if max_pages <= 0:
        return curriculum
    return curriculum[:max_pages]


def probe_crawl_scope(
    seed_url: str,
    *,
    crawl_enabled: bool = True,
) -> dict[str, Any]:
    """Probe how many pages a seed URL exposes (TOC only, no leaf fetch)."""
    seed = scope_prefix(seed_url)
    result: dict[str, Any] = {
        "url": seed,
        "crawl_enabled": crawl_enabled,
        "discovered_total": 1,
        "curriculum_mode": "exact_urls",
        "parts": [],
        "entries_preview": [],
    }
    if not crawl_enabled:
        return result
    try:
        with _http_client() as client:
            html = fetch_html(seed, client)
            curriculum = parse_handbook_curriculum(html, seed)
            if curriculum:
                parts: list[str] = []
                seen: set[str] = set()
                for entry in curriculum:
                    pt = entry.get("part_title", "")
                    if pt and pt not in seen:
                        seen.add(pt)
                        parts.append(pt)
                result.update(
                    {
                        "discovered_total": len(curriculum),
                        "curriculum_mode": "handbook_toc",
                        "parts": parts,
                        "entries_preview": [
                            {
                                "display_title": e.get("display_title", ""),
                                "url": e.get("url", ""),
                                "part_title": e.get("part_title", ""),
                            }
                            for e in curriculum[:15]
                        ],
                    }
                )
                return result
            child_urls = discover_child_urls(html, seed, seed)
            discovered = sorted({seed} | set(child_urls), key=_url_sort_key)
            result.update(
                {
                    "discovered_total": len(discovered),
                    "curriculum_mode": "link_crawl",
                    "entries_preview": [
                        {"display_title": u, "url": u, "part_title": ""}
                        for u in discovered[:15]
                    ],
                }
            )
    except Exception as exc:
        result["error"] = str(exc)
    return result


def probe_crawl_urls(
    urls: list[str],
    *,
    crawl_enabled: bool = True,
) -> dict[str, Any]:
    """Probe all seed URLs; return per-seed stats and aggregate total."""
    seeds: list[dict[str, Any]] = []
    total = 0
    for raw in urls:
        seed = scope_prefix(raw.strip())
        if not seed:
            continue
        info = probe_crawl_scope(seed, crawl_enabled=crawl_enabled)
        seeds.append(info)
        total += int(info.get("discovered_total") or 0)
    return {
        "seeds": seeds,
        "discovered_total": total,
        "crawl_enabled": crawl_enabled,
    }


def collect_handbook_urls(
    seed_url: str,
    max_pages: int,
    client: httpx.Client,
) -> tuple[list[dict], dict[str, str], int, list[dict] | None]:
    """Discover handbook pages via TOC, not blind link crawl."""
    seed = scope_prefix(seed_url)
    html = fetch_html(seed, client)
    cache: dict[str, str] = {seed: html}

    curriculum = parse_handbook_curriculum(html, seed)
    if curriculum:
        selected = select_curriculum_urls(curriculum, max_pages=max_pages)
        for entry in selected:
            url = entry["url"]
            if url not in cache:
                cache[url] = fetch_html(url, client)
        return selected, cache, len(curriculum), curriculum

    page_urls, cache, discovered_total = collect_scope_urls(seed, max_pages, client)
    fallback = [
        {"url": u, "display_title": u, "chapter_id": _chapter_key(u, u), "chapter_order": i + 1}
        for i, u in enumerate(page_urls)
    ]
    return fallback, cache, discovered_total, None


def _strip_noise_elements(root) -> None:
    for selector in NOISE_CONTENT_SELECTORS:
        for node in root.select(selector):
            node.decompose()


def discover_child_urls(html: str, page_url: str, seed_url: str) -> list[str]:
    """Find same-site links under the seed path (sidebar / TOC / in-page links)."""
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.lower().startswith(SKIP_HREF_PREFIXES):
            continue
        full = normalize_url(urljoin(page_url, href))
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != urlparse(seed_url).netloc:
            continue
        if not is_under_scope(full, seed_url):
            continue
        if full in seen:
            continue
        seen.add(full)
        found.append(full)
    return found


def _url_sort_key(url: str) -> tuple:
    path = urlparse(url).path
    return (path.count("/"), path)


def collect_scope_urls(
    seed_url: str,
    max_pages: int,
    client: httpx.Client,
) -> tuple[list[str], dict[str, str], int]:
    """Discover handbook-style child pages from seed; return URLs and HTML cache."""
    seed = scope_prefix(seed_url)
    html = fetch_html(seed, client)
    cache: dict[str, str] = {seed: html}

    discovered = {seed}
    discovered.update(discover_child_urls(html, seed, seed))

    ordered = sorted(discovered, key=_url_sort_key)
    total_discovered = len(ordered)
    if max_pages > 0:
        ordered = ordered[:max_pages]

    return ordered, cache, total_discovered


def _content_root(soup: BeautifulSoup):
    for selector in (
        {"name": "main"},
        {"name": "article"},
        {"attrs": {"role": "main"}},
        {"attrs": {"class": re.compile(r"(markdown|content|doc-content|post-content)", re.I)}},
    ):
        node = soup.find(**selector)
        if node is not None:
            return node
    return soup.body or soup


def _inject_image_descriptions(root, page_url: str) -> int:
    """Replace <img> with text notes so diagrams are not lost."""
    count = 0
    for img in root.find_all("img"):
        alt = (img.get("alt") or img.get("title") or "").strip()
        src = (img.get("src") or "").strip()
        if not alt and not src:
            img.decompose()
            continue
        full_src = urljoin(page_url, src) if src else ""
        label = alt or _filename_hint(src) or "示意图"
        note = f"[图片] {label}"
        if full_src:
            note += f" ({full_src})"
        img.replace_with(NavigableString(f"\n{note}\n"))
        count += 1
    return count


def _filename_hint(src: str) -> str:
    name = urlparse(src).path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.[a-zA-Z0-9]+$", "", name)
    return stem.replace("-", " ").replace("_", " ").strip()


def _extract_sections_from_root(root, page_title: str) -> list[dict]:
    """Split page content into sections by h1–h4 headings."""
    headings = root.find_all(["h1", "h2", "h3", "h4"])
    if not headings:
        body = _clean_text(root.get_text("\n", strip=True))
        if not body or _is_noise_heading(page_title):
            return []
        return [{"heading": page_title, "level": 1, "content": body}]

    sections: list[dict] = []
    for h in headings:
        heading = h.get_text(strip=True) or page_title
        if _is_noise_heading(heading):
            continue
        level = int(h.name[1])
        parts: list[str] = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) in ("h1", "h2", "h3", "h4"):
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text("\n", strip=True)
                if text:
                    parts.append(text)
        content = _clean_text("\n".join(parts))
        if len(content) >= 20:
            sections.append({"heading": heading, "level": level, "content": content})

    if not sections:
        body = _clean_text(root.get_text("\n", strip=True))
        if body and not _is_noise_heading(page_title):
            return [{"heading": page_title, "level": 1, "content": body}]
    return sections


def _chapter_key(url: str, heading: str) -> str:
    raw = f"{url}::{heading}".encode()
    return hashlib.md5(raw).hexdigest()[:12]


def _assign_chapters(
    sections: list[dict],
    url: str,
    page_title: str,
    chapter_order_start: int,
) -> tuple[list[dict], int]:
    """Group sections into chapters (h1 boundaries, else page-level)."""
    enriched: list[dict] = []
    order = chapter_order_start
    current_chapter_id = _chapter_key(url, page_title)
    current_chapter_title = page_title
    min_level = min((s["level"] for s in sections), default=1)

    for sec in sections:
        level = sec["level"]
        heading = sec["heading"]
        if level <= min_level and heading != page_title:
            current_chapter_id = _chapter_key(url, heading)
            current_chapter_title = heading
            if not any(
                e.get("chapter_id") == current_chapter_id for e in enriched
            ):
                order += 1
        enriched.append(
            {
                **sec,
                "chapter_id": current_chapter_id,
                "chapter_title": current_chapter_title,
                "chapter_order": order,
            }
        )
    return enriched, order


def chunk_sections_with_meta(
    url: str,
    page_title: str,
    sections: list[dict],
    *,
    chapter_id: str,
    chapter_title: str,
    chapter_order: int,
    part_title: str = "",
    chunk_size: int = CHUNK_SIZE,
) -> list[dict]:
    """Chunk sections; all chunks share one curriculum chapter (leaf page)."""
    enriched: list[dict] = []
    for sec in sections:
        enriched.append(
            {
                **sec,
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "chapter_order": chapter_order,
                "part_title": part_title,
            }
        )
    return chunk_sections(url, page_title, enriched, chunk_size=chunk_size)


def chunk_sections(
    url: str,
    page_title: str,
    sections: list[dict],
    *,
    chunk_size: int = CHUNK_SIZE,
) -> list[dict]:
    """Chunk section content with chapter metadata."""
    chunks: list[dict] = []
    chunk_idx = 0

    for sec in sections:
        content = sec["content"]
        heading = sec["heading"]
        chapter_id = sec["chapter_id"]
        chapter_title = sec["chapter_title"]
        chapter_order = sec["chapter_order"]
        part_title = sec.get("part_title", "")

        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        buffer: list[str] = []
        buffer_len = 0

        for para in paragraphs:
            if buffer_len + len(para) > chunk_size and buffer:
                chunk_idx += 1
                text = "\n".join(buffer)
                chunk = _make_chunk(url, page_title, chunk_idx, text)
                chunk.update(
                    {
                        "heading": heading,
                        "section_level": sec["level"],
                        "chapter_id": chapter_id,
                        "chapter_title": chapter_title,
                        "chapter_order": chapter_order,
                        "part_title": part_title,
                    }
                )
                chunks.append(chunk)
                buffer, buffer_len = [], 0
            buffer.append(para)
            buffer_len += len(para)

        if buffer:
            chunk_idx += 1
            text = "\n".join(buffer)
            chunk = _make_chunk(url, page_title, chunk_idx, text)
            chunk.update(
                {
                    "heading": heading,
                    "section_level": sec["level"],
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "chapter_order": chapter_order,
                    "part_title": part_title,
                }
            )
            chunks.append(chunk)

    return chunks


def build_chapter_registry(chunks: list[dict]) -> list[dict]:
    """Ordered unique chapters from chunk metadata."""
    seen: dict[str, dict] = {}
    for c in chunks:
        cid = c.get("chapter_id") or ""
        if not cid or cid in seen:
            continue
        seen[cid] = {
            "chapter_id": cid,
            "chapter_title": c.get("chapter_title") or c.get("title", ""),
            "chapter_order": int(c.get("chapter_order", len(seen))),
            "part_title": c.get("part_title", ""),
            "url": c.get("url", ""),
        }
    registry = list(seen.values())
    registry.sort(key=lambda x: x.get("chapter_order", 0))
    return registry


def parse_page_html(
    html: str,
    url: str,
    *,
    include_images: bool = True,
) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.title.string if soup.title and soup.title.string else ""
    title = title_tag.strip() or urlparse(url).path.rsplit("/", 1)[-1] or url

    root = _content_root(soup)
    for tag in root.find_all(["script", "style", "noscript"]):
        tag.decompose()
    _strip_noise_elements(root)

    image_count = _inject_image_descriptions(root, url) if include_images else 0
    sections = _extract_sections_from_root(root, title)
    body = _clean_text(root.get_text("\n", strip=True))

    if len(body) < MIN_CONTENT_LEN:
        raise ValueError(f"Page content too short or blocked: {url}")

    return {
        "url": url,
        "title": title,
        "content": body,
        "sections": sections,
        "image_count": image_count,
    }


def fetch_url(url: str, *, include_images: bool = True) -> dict:
    html = fetch_html(url)
    return parse_page_html(html, normalize_url(url), include_images=include_images)


def chunk_content(url: str, title: str, content: str) -> list[dict]:
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    chunks: list[dict] = []
    buffer: list[str] = []
    buffer_len = 0
    chunk_idx = 0

    for para in paragraphs:
        if buffer_len + len(para) > CHUNK_SIZE and buffer:
            chunk_idx += 1
            text = "\n".join(buffer)
            chunks.append(_make_chunk(url, title, chunk_idx, text))
            buffer, buffer_len = [], 0
        buffer.append(para)
        buffer_len += len(para)

    if buffer:
        chunk_idx += 1
        text = "\n".join(buffer)
        chunks.append(_make_chunk(url, title, chunk_idx, text))

    return chunks


def _make_chunk(url: str, title: str, idx: int, text: str) -> dict:
    chunk_id = hashlib.md5(f"{url}:{idx}:{text[:80]}".encode()).hexdigest()[:12]
    return {
        "id": f"chunk_{idx}_{chunk_id}",
        "url": url,
        "title": title,
        "index": idx,
        "content": text,
        "char_count": len(text),
    }


def fetch_and_chunk_urls(
    urls: list[str],
    *,
    crawl_enabled: bool | None = None,
    max_pages: int | None = None,
    include_images: bool | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    settings = get_settings()
    crawl = settings.crawl_enabled if crawl_enabled is None else crawl_enabled
    raw_limit = settings.crawl_max_pages if max_pages is None else max_pages
    page_limit = raw_limit  # <=0 means fetch all discovered entries
    with_images = settings.crawl_include_images if include_images is None else include_images

    all_chunks: list[dict] = []
    chapter_order = 0
    manifest: dict[str, Any] = {
        "crawl_enabled": crawl,
        "max_pages": page_limit,
        "include_images": with_images,
        "seeds": urls,
        "pages": [],
        "errors": [],
    }

    with _http_client() as client:
        for seed in urls:
            seed_norm = scope_prefix(seed)
            try:
                if crawl:
                    page_entries, cache, discovered_total, curriculum = collect_handbook_urls(
                        seed_norm, page_limit, client
                    )
                else:
                    page_urls, cache, discovered_total = collect_scope_urls(
                        seed_norm, 1, client
                    )
                    page_entries = [
                        {
                            "url": page_urls[0],
                            "display_title": page_urls[0],
                            "chapter_id": _chapter_key(page_urls[0], page_urls[0]),
                            "chapter_order": 1,
                        }
                    ]
                    curriculum = None

                manifest.setdefault("discovered_per_seed", {})[seed_norm] = discovered_total
                manifest.setdefault("fetched_per_seed", {})[seed_norm] = len(page_entries)
                if curriculum:
                    manifest["curriculum_mode"] = "handbook_toc"
                    manifest["curriculum_entries"] = [
                        {
                            "url": e["url"],
                            "part_title": e.get("part_title", ""),
                            "display_title": e.get("display_title", ""),
                            "chapter_order": e.get("chapter_order", 0),
                        }
                        for e in (curriculum[:50] if curriculum else [])
                    ]
                else:
                    manifest["curriculum_mode"] = "link_crawl"

                for entry in page_entries:
                    page_url = entry["url"]
                    try:
                        html = cache.get(page_url) or fetch_html(page_url, client)
                        page = parse_page_html(
                            html, page_url, include_images=with_images
                        )
                        sections = page.get("sections") or []
                        if not sections:
                            sections = [
                                {
                                    "heading": entry.get("display_title", page["title"]),
                                    "level": 1,
                                    "content": page["content"],
                                }
                            ]

                        if entry.get("chapter_id"):
                            chunks = chunk_sections_with_meta(
                                page["url"],
                                page["title"],
                                sections,
                                chapter_id=entry["chapter_id"],
                                chapter_title=entry.get("display_title", page["title"]),
                                chapter_order=int(entry.get("chapter_order", 0)),
                                part_title=entry.get("part_title", ""),
                            )
                        else:
                            enriched, chapter_order = _assign_chapters(
                                sections,
                                page["url"],
                                page["title"],
                                chapter_order,
                            )
                            chunks = chunk_sections(
                                page["url"], page["title"], enriched
                            )
                        if not chunks:
                            chunks = chunk_content(
                                page["url"], page["title"], page["content"]
                            )
                            cid = entry.get("chapter_id") or _chapter_key(
                                page["url"], page["title"]
                            )
                            for c in chunks:
                                c["chapter_id"] = cid
                                c["chapter_title"] = entry.get(
                                    "display_title", page["title"]
                                )
                                c["chapter_order"] = entry.get(
                                    "chapter_order", chapter_order
                                )
                                c["part_title"] = entry.get("part_title", "")
                                c["heading"] = entry.get("display_title", page["title"])
                                c["section_level"] = 1
                            if not entry.get("chapter_id"):
                                chapter_order += 1
                        all_chunks.extend(chunks)
                        manifest["pages"].append(
                            {
                                "url": page["url"],
                                "title": page["title"],
                                "display_title": entry.get("display_title", page["title"]),
                                "part_title": entry.get("part_title", ""),
                                "chars": len(page["content"]),
                                "chunks": len(chunks),
                                "images": page.get("image_count", 0),
                            }
                        )
                    except Exception as exc:
                        logger.warning("Skip page %s: %s", page_url, exc)
                        manifest["errors"].append({"url": page_url, "error": str(exc)})
            except Exception as exc:
                logger.warning("Skip seed %s: %s", seed_norm, exc)
                manifest["errors"].append({"url": seed_norm, "error": str(exc)})

    if not all_chunks:
        raise ValueError("No page content fetched from provided URLs")

    manifest["total_pages"] = len(manifest["pages"])
    manifest["total_chunks"] = len(all_chunks)
    manifest["chapter_registry"] = build_chapter_registry(all_chunks)
    return all_chunks, manifest


def material_context(chunks: list[dict], max_chars: int = 24000) -> str:
    parts: list[str] = []
    total = 0
    for c in chunks:
        block = f"[{c['id']}] ({c['title']}) <{c['url']}>\n{c['content']}\n"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n---\n".join(parts)
