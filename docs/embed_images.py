"""Embed local PNG images as base64 data URIs for Markdown preview."""

from __future__ import annotations

import base64
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent
IMAGES = DOCS / "images"
MD_SRC = DOCS / "blog-langgraph-subgraph-subagent-selection.md"
MD_EMBED = DOCS / "blog-langgraph-subgraph-subagent-selection.preview.md"
HTML_OUT = DOCS / "blog-langgraph-subgraph-subagent-selection.html"

IMG_PATTERN = re.compile(
    r"!\[([^\]]*)\]\(\./images/([^)]+)\)"
)


def to_data_uri(filename: str) -> str:
    path = IMAGES / filename
    if not path.exists():
        raise FileNotFoundError(path)
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def embed_markdown(text: str) -> str:
    def repl(match: re.Match) -> str:
        alt, fname = match.group(1), match.group(2)
        return f"![{alt}]({to_data_uri(fname)})"

    return IMG_PATTERN.sub(repl, text)


def markdown_to_html(md_body: str) -> str:
    """Minimal markdown to HTML for blog preview (headings, images, tables, code, lists)."""
    lines = md_body.splitlines()
    html: list[str] = []
    in_code = False
    in_table = False
    in_blockquote = False
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            html.append("</ul>")
            list_open = False

    for line in lines:
        if line.strip() == "---":
            close_list()
            if in_table:
                html.append("</tbody></table>")
                in_table = False
            if in_blockquote:
                html.append("</blockquote>")
                in_blockquote = False
            html.append("<hr/>")
            continue

        if line.startswith("```"):
            close_list()
            if in_code:
                html.append("</code></pre>")
                in_code = False
            else:
                lang = line.strip("`").strip() or "text"
                html.append(f'<pre><code class="language-{lang}">')
                in_code = True
            continue

        if in_code:
            html.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue

        if line.startswith("!["):
            close_list()
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line)
            if m:
                alt, src = m.group(1), m.group(2)
                html.append(
                    f'<figure class="fig"><img src="{src}" alt="{alt}"/>'
                    f'<figcaption>{alt}</figcaption></figure>'
                )
            continue

        if line.startswith("# "):
            close_list()
            html.append(f"<h1>{line[2:]}</h1>")
            continue
        if line.startswith("## "):
            close_list()
            html.append(f"<h2>{line[3:]}</h2>")
            continue
        if line.startswith("### "):
            close_list()
            html.append(f"<h3>{line[4:]}</h3>")
            continue

        if line.startswith("> "):
            if not in_blockquote:
                html.append("<blockquote>")
                in_blockquote = True
            html.append(f"<p>{inline_md(line[2:])}</p>")
            continue
        elif in_blockquote and not line.strip():
            html.append("</blockquote>")
            in_blockquote = False

        if "|" in line and line.strip().startswith("|"):
            close_list()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_table:
                html.append('<table><thead><tr>')
                for c in cells:
                    html.append(f"<th>{inline_md(c)}</th>")
                html.append("</tr></thead><tbody>")
                in_table = True
            else:
                html.append("<tr>")
                for c in cells:
                    html.append(f"<td>{inline_md(c)}</td>")
                html.append("</tr>")
            continue
        elif in_table:
            html.append("</tbody></table>")
            in_table = False

        if line.startswith("- "):
            if not list_open:
                html.append("<ul>")
                list_open = True
            html.append(f"<li>{inline_md(line[2:])}</li>")
            continue

        if re.match(r"^\d+\.\s", line):
            if not list_open:
                html.append("<ul>")
                list_open = True
            text = re.sub(r"^\d+\.\s", "", line)
            html.append(f"<li>{inline_md(text)}</li>")
            continue

        close_list()
        if line.strip():
            html.append(f"<p>{inline_md(line)}</p>")
        else:
            html.append("")

    close_list()
    if in_table:
        html.append("</tbody></table>")
    if in_code:
        html.append("</code></pre>")

    return "\n".join(html)


def inline_md(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def main() -> None:
    src = MD_SRC.read_text(encoding="utf-8")
    # strip YAML front matter for HTML body
    body = src
    if src.startswith("---"):
        parts = src.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")

    embedded = embed_markdown(body)
    MD_EMBED.write_text(
        "<!-- 本文件由 embed_images.py 自动生成，图片已内嵌 base64，供 Cursor/VS Code 预览 -->\n\n"
        + embedded,
        encoding="utf-8",
    )

    html_content = markdown_to_html(embedded)
    HTML_OUT.write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>LangGraph 选型指南：Subgraph 还是 Subagent？</title>
  <style>
    body {{ max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.7; color: #1a1a1a; }}
    h1, h2, h3 {{ line-height: 1.3; }}
    h1 {{ font-size: 1.9rem; border-bottom: 2px solid #2e7d32; padding-bottom: .4rem; }}
    h2 {{ margin-top: 2.2rem; font-size: 1.45rem; color: #1565c0; }}
    h3 {{ margin-top: 1.5rem; font-size: 1.15rem; }}
    figure.fig {{ margin: 1.5rem 0; text-align: center; }}
    figure.fig img {{ max-width: 100%; height: auto; border: 1px solid #e0e0e0; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
    figcaption {{ margin-top: .6rem; font-size: .9rem; color: #555; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92rem; }}
    th, td {{ border: 1px solid #ddd; padding: .55rem .7rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
    blockquote {{ border-left: 4px solid #2e7d32; margin: 1rem 0; padding: .5rem 1rem; background: #f1f8e9; color: #333; }}
    pre {{ background: #f6f8fa; padding: 1rem; overflow-x: auto; border-radius: 6px; font-size: .88rem; }}
    code {{ font-family: Consolas, Monaco, monospace; }}
    hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 2rem 0; }}
    a {{ color: #1565c0; }}
  </style>
</head>
<body>
{html_content}
</body>
</html>""",
        encoding="utf-8",
    )

    print(f"Wrote: {MD_EMBED}")
    print(f"Wrote: {HTML_OUT}")
    print(f"Embedded images: {len(IMG_PATTERN.findall(body))}")


if __name__ == "__main__":
    main()
