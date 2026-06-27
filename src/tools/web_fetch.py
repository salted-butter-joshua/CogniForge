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

    image_count = _inject_image_descriptions(root, url) if include_images else 0
    body = _clean_text(root.get_text("\n", strip=True))

    if len(body) < MIN_CONTENT_LEN:
        raise ValueError(f"Page content too short or blocked: {url}")

    return {
        "url": url,
        "title": title,
        "content": body,
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
    page_limit = settings.crawl_max_pages if max_pages is None else max_pages
    with_images = settings.crawl_include_images if include_images is None else include_images

    all_chunks: list[dict] = []
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
                    page_urls, cache, discovered_total = collect_scope_urls(
                        seed_norm, page_limit, client
                    )
                else:
                    page_urls, cache, discovered_total = [seed_norm], {}, 1

                manifest.setdefault("discovered_per_seed", {})[seed_norm] = discovered_total
                manifest.setdefault("fetched_per_seed", {})[seed_norm] = len(page_urls)

                for page_url in page_urls:
                    try:
                        html = cache.get(page_url) or fetch_html(page_url, client)
                        page = parse_page_html(
                            html, page_url, include_images=with_images
                        )
                        chunks = chunk_content(page["url"], page["title"], page["content"])
                        all_chunks.extend(chunks)
                        manifest["pages"].append(
                            {
                                "url": page["url"],
                                "title": page["title"],
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
