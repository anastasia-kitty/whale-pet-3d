# -*- coding: utf-8 -*-
"""
把模型输出的 Markdown 转成 QTextDocument 能渲染的 HTML。

只实现聊天里最常用的一小撮语法：标题、粗体、斜体、删除线、行内代码、
代码块、列表、引用、分隔线、链接、简单表格。没有第三方 Markdown 依赖。
"""

from __future__ import annotations

import html
import re
from typing import List

MAX_INPUT_CHARS = 30000

_FENCE_RE = re.compile(r"^\s{0,3}```([\w+#.\-]*)\s*$")
_FENCE_END_RE = re.compile(r"^\s{0,3}```\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_BULLET_RE = re.compile(r"^\s{0,6}[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s{0,6}(\d{1,3})[.)]\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")

_CODE_STYLE = (
    "font-family:'Cascadia Mono','Consolas','Courier New',monospace;"
    "font-size:11px;color:#4B5480;background-color:#F1F4FF;"
)
_LINK_STYLE = "color:#5460FF;text-decoration:none;"


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def _split_cells(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _strip_url_tail(url: str) -> str:
    while url and url[-1] in ".,;:!?)]}>，。；：！？）】」":
        url = url[:-1]
    return url


def _inline(text: str) -> str:
    """行内语法。先用占位符保护行内代码，再转义，避免二次转义。"""
    codes = []  # type: List[str]

    def stash_code(match: "re.Match[str]") -> str:
        codes.append(match.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    text = re.sub(r"`([^`\n]+)`", stash_code, text)
    escaped = escape_html(text)

    def link(match: "re.Match[str]") -> str:
        label, url = match.group(1), match.group(2)
        return '<a href="%s" style="%s">%s</a>' % (url, _LINK_STYLE, label)

    escaped = re.sub(
        r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", link, escaped
    )

    def bare_link(match: "re.Match[str]") -> str:
        url = _strip_url_tail(match.group(1))
        if not url or url.lower().startswith("javascript"):
            return match.group(1)
        return '<a href="%s" style="%s">%s</a>' % (url, _LINK_STYLE, url)

    escaped = re.sub(r"(?<![\"'=])(https?://[^\s<]+)", bare_link, escaped)

    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r'<span style="text-decoration:line-through">\1</span>', escaped)
    escaped = re.sub(r"(?<![\*\w])\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", escaped)

    for index, code in enumerate(codes):
        escaped = escaped.replace(
            "\x00%d\x00" % index,
            '<span style="%s">%s</span>' % (_CODE_STYLE, escape_html(code)),
        )
    return escaped


def _code_block(code: str, language: str = "") -> str:
    caption = ""
    if language:
        caption = (
            '<div style="font-size:10px;color:#8A94B8;padding:0 0 3px 2px;">%s</div>'
            % escape_html(language)
        )
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" '
        'style="margin-top:4px;margin-bottom:6px;">'
        '<tr><td style="background-color:#F3F6FF;padding:7px 9px;">'
        + caption
        + '<pre style="margin:0;white-space:pre-wrap;word-wrap:break-word;'
        "font-family:'Cascadia Mono','Consolas',"
        '\'Courier New\',monospace;font-size:10px;color:#2E3657;">'
        + escape_html(code)
        + "</pre></td></tr></table>"
    )


def _table(rows: List[str]) -> str:
    if not rows:
        return ""
    header = _split_cells(rows[0])
    body = [_split_cells(row) for row in rows[1:] if row.strip()]
    parts = [
        '<table width="100%" cellspacing="0" cellpadding="5" '
        'style="margin-top:4px;margin-bottom:6px;">'
    ]
    cells = "".join(
        '<td style="background-color:#F3F6FF;font-weight:600;color:#3B4668;">%s</td>'
        % _inline(cell)
        for cell in header
    )
    parts.append("<tr>%s</tr>" % cells)
    for row in body:
        cells = "".join(
            '<td style="color:#4A5478;">%s</td>' % _inline(cell) for cell in row
        )
        parts.append("<tr>%s</tr>" % cells)
    parts.append("</table>")
    return "".join(parts)


def _is_table_sep(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line))


def _list_match(line: str):
    ordered = _ORDERED_RE.match(line)
    if ordered:
        return "ol", ordered.group(2)
    bullet = _BULLET_RE.match(line)
    if bullet:
        return "ul", bullet.group(1)
    return None


def _starts_block(line: str, lines: List[str], index: int) -> bool:
    if not line.strip():
        return True
    if _FENCE_RE.match(line) or _HEADING_RE.match(line) or _HR_RE.match(line):
        return True
    if _QUOTE_RE.match(line) or _list_match(line):
        return True
    if "|" in line and index + 1 < len(lines) and _is_table_sep(lines[index + 1]):
        return True
    return False


def _render_list(kind: str, items: List[str]) -> str:
    tag = "ol" if kind == "ol" else "ul"
    body = "".join("<li>%s</li>" % item for item in items)
    return (
        '<%s style="margin-top:2px;margin-bottom:2px;margin-left:14px;">%s</%s>'
        % (tag, body, tag)
    )


def render_markdown(text: str) -> str:
    """返回 Qt 富文本 HTML。空字符串返回空串。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS] + "\n\n……（内容太长，后面省略啦）"

    lines = text.split("\n")
    out = []  # type: List[str]
    i = 0
    total = len(lines)

    while i < total:
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            i += 1
            code = []  # type: List[str]
            while i < total and not _FENCE_END_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(_code_block("\n".join(code), fence.group(1)))
            continue

        if "|" in line and i + 1 < total and _is_table_sep(lines[i + 1]):
            rows = [line]
            i += 2
            while i < total and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            size = {1: 17, 2: 15, 3: 14}.get(level, 13)
            out.append(
                '<div style="margin-top:6px;margin-bottom:3px;">'
                '<span style="font-size:%dpx;font-weight:600;color:#2B3357;">%s</span>'
                "</div>" % (size, _inline(heading.group(2).strip()))
            )
            i += 1
            continue

        if _HR_RE.match(line):
            out.append(
                '<table width="100%" cellspacing="0" cellpadding="0" '
                'style="margin-top:7px;margin-bottom:7px;">'
                '<tr><td style="background-color:#E6ECFF;height:1px;"></td></tr>'
                "</table>"
            )
            i += 1
            continue

        if _QUOTE_RE.match(line):
            quoted = []  # type: List[str]
            while i < total and _QUOTE_RE.match(lines[i]):
                quoted.append(_inline(_QUOTE_RE.sub("", lines[i], count=1)))
                i += 1
            out.append(
                '<div style="margin:4px 0 4px 8px;color:#6B7599;">▎ '
                + "<br/>".join(quoted)
                + "</div>"
            )
            continue

        list_item = _list_match(line)
        if list_item:
            kind = list_item[0]
            items = []  # type: List[str]
            while i < total:
                current = _list_match(lines[i])
                if current is None or current[0] != kind:
                    break
                items.append(_inline(current[1]))
                i += 1
            out.append(_render_list(kind, items))
            continue

        if not line.strip():
            out.append('<div style="height:5px;"></div>')
            i += 1
            continue

        paragraph = [line]
        i += 1
        while i < total and not _starts_block(lines[i], lines, i):
            paragraph.append(lines[i])
            i += 1
        out.append(
            '<div style="margin-bottom:2px;">'
            + "<br/>".join(_inline(part) for part in paragraph)
            + "</div>"
        )

    return "".join(out)


def plain_excerpt(text: str, limit: int = 48) -> str:
    """给桌宠气泡用的一行摘要：去掉 Markdown 符号和多余空白。"""
    cleaned = re.sub(r"```.*?```", "代码", text or "", flags=re.S)
    cleaned = re.sub(r"[`*_>#~|]", "", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "…"
    return cleaned


__all__ = ["escape_html", "plain_excerpt", "render_markdown"]
