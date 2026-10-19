"""Small helpers shared by the HTML-card scrapers (Secretcv, Yenibiriş, LinkedIn, Indeed)."""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..textutil import fold


def text_of(el: Optional[Tag]) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el is not None else ""


def class_tokens(tag: Tag) -> list[str]:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    extra = [str(tag.get(a)).lower() for a in ("data-test", "data-testid") if tag.get(a)]
    return [c.lower() for c in classes] + extra


def by_hint(card: Tag, hints: Iterable[str], skip: Iterable[str] = ()) -> str:
    """Text of the first descendant whose class / data-test(id) contains one of ``hints``."""
    hints, skip = tuple(hints), tuple(skip)
    for el in card.find_all(True):
        tokens = class_tokens(el)
        if any(s in t for t in tokens for s in skip):
            continue
        if any(h in t for t in tokens for h in hints):
            text = text_of(el)
            if text:
                return text
    return ""


def card_container(anchor: Tag, id_of: Callable[[str], Optional[str]], ext_id: str,
                   link_re: re.Pattern[str], max_up: int = 5) -> Tag:
    """Largest ancestor (bounded) whose job links all point to the same id."""
    card, node = anchor, anchor.parent
    for _ in range(max_up):
        if node is None or node.name in ("body", "html", "[document]", "main"):
            break
        ids = {id_of(a["href"]) for a in node.find_all("a", href=link_re)}
        if ids != {ext_id}:
            break
        card, node = node, node.parent
    return card


def tokens_of(card: Tag) -> list[str]:
    return [t for t in (re.sub(r"\s+", " ", s).strip() for s in card.stripped_strings) if t]


def normalize_url(href: str, base: str, host: str, keep_query: bool = False) -> str:
    """Absolute https URL on ``host`` (subdomains folded), without query/fragment by default."""
    parts = urlsplit(urljoin(base, href))
    netloc = parts.netloc.lower()
    root = host.split(".", 1)[1] if host.startswith("www.") else host
    if netloc == root or netloc.endswith("." + root):
        netloc = host
    return urlunsplit(("https", netloc, parts.path, parts.query if keep_query else "", ""))


def page_text(soup: BeautifulSoup) -> str:
    return fold(soup.get_text(" ", strip=True))
