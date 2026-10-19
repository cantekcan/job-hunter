"""Kariyer.net scraper.

Facts and assumptions about the site are in docs/sources.md and docs/kariyer_observed.md.

- List URL: https://www.kariyer.net/is-ilanlari/<words+joined+with+plus>, page N as "<slug>-N".
- Detail URL: https://www.kariyer.net/is-ilani/<company>-<title>-<numericId>. The numeric id is the uid.
- Parsing order: (a) embedded JSON (ld+json JobPosting, __NEXT_DATA__, window.__*STATE__ blobs
  with positionId/jobDateStatus), (b) HTML fallback that anchors on /is-ilani/...-<id> links and
  reads each card by class-name hints, then by the text order the site uses.
- No-results pages ("... İlanını Bulamadık" + "benzer ilanlar") return []. Related-ad blocks
  ("Bu İlanla Birlikte Görüntülenenler") are ignored.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..cover_letter import detect_language
from ..dateparse import parse_relative_date
from ..models import Job
from ..textutil import fold
from .base import BaseScraper

log = logging.getLogger(__name__)

BASE_URL = "https://www.kariyer.net"

# Layer 1 of the date rule (URL date filter). The real query parameter for "Bugünün ilanları" is
# NOT known yet (the filter is JS-driven, no href was observed). Find it once in a browser
# (DevTools -> click "Tarih: Bugünün ilanları" -> copy the URL/XHR params) and put it here,
# e.g. DATE_PARAMS = {"<param>": "<value>"}. While empty, layers 2 and 3 do the work.
DATE_PARAMS: dict[str, str] = {}

ID_RE = re.compile(r"/is-ilani/[^?#\s\"']*?-(\d+)(?=[/?#]|$)")
_WORK_MODELS = {
    "is yerinde": "iş yerinde", "ofiste": "iş yerinde", "hibrit": "hibrit",
    "uzaktan / remote": "uzaktan", "uzaktan/remote": "uzaktan", "uzaktan": "uzaktan", "remote": "uzaktan",
}
_EMPLOYMENT_RE = re.compile(r"^(tam|yari) ?zamanli$|^(full|part)[ -]?time$|^donemsel$|^proje bazli$")
_AGE_RE = re.compile(r"^(\d+\+?\s*(dakika|dk|saat|gun|hafta|ay)(\s*once)?|bugun|dun|yeni|az once)$")
_MORE_CITIES_RE = re.compile(r"^\+\s*\d+\s*(il|sehir)\s*daha$")
_NOISE_RE = re.compile(
    r"^(sponsorlu( ilan)?|accessible|update|engelli ilani|kaydet|basvur|hemen basvur|yeni ilan|"
    r"ort\. .*donuyor|.*basvuru|favorilere ekle|paylas)$"
)
_RELATED_RE = re.compile(r"bu ilanla birlikte goruntulenenler|benzer ilanlar|ilgini cekebilecek ilanlar")
_NO_RESULTS_RE = re.compile(r"bulamadik")
_DETAIL_SECTIONS = ("is ilani hakkinda", "ne bekliyoruz", "aday kriterleri", "is tanimi",
                    "genel nitelikler", "yan haklar")
_DETAIL_STOP = ("sirket hakkinda", "bu ilanla birlikte goruntulenenler", "benzer ilanlar")
_LAST_PUBLISH_RE = re.compile(r"lastPublishDate\"?\s*[:=]\s*\"?(\d{2}\.\d{2}\.\d{4})")
_TITLE_DATE_RE = re.compile(r"-\s*(\d{2}\.\d{2}\.\d{4})\s*$")

# class-name hints for the HTML fallback (matched against each class token, lowercase)
_HINTS: dict[str, tuple[str, ...]] = {
    "title": ("title", "position-name", "job-name"),
    "company": ("company", "firm"),
    "location": ("location", "city"),
    "work_model": ("work-model", "workmodel", "working-model", "work_model"),
    "age": ("date", "posted", "ago", "publish", "time-info", "update-time"),
}


# ---------------------------------------------------------------- helpers

def query_slug(query: str) -> str:
    """".NET Developer" -> "net+developer", "Yazılım Uzmanı .NET" -> "yazilim+uzmani+net"."""
    return "+".join(re.findall(r"[a-z0-9]+", fold(query)))


def search_url(query: str, page: int = 1, date_params: Optional[dict[str, str]] = None) -> str:
    url = f"{BASE_URL}/is-ilanlari/{query_slug(query)}"
    if page > 1:
        url += f"-{page}"
    params = DATE_PARAMS if date_params is None else date_params
    return f"{url}?{urlencode(params)}" if params else url


def extract_id(href: str) -> Optional[str]:
    m = ID_RE.search(urlsplit(href).path if "://" in href else href.split("?")[0].split("#")[0])
    return m.group(1) if m else None


def normalize_url(href: str) -> str:
    """Absolute https://www.kariyer.net/is-ilani/... without query/fragment (subdomains -> www)."""
    parts = urlsplit(urljoin(BASE_URL + "/", href))
    host = parts.netloc.lower()
    if host == "kariyer.net" or host.endswith(".kariyer.net"):
        host = "www.kariyer.net"
    return urlunsplit(("https", host, parts.path, "", ""))


def normalize_work_model(text: str) -> str:
    f = re.sub(r"\s+", " ", fold(text)).strip()
    return _WORK_MODELS.get(f, "")


def is_no_results(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all(["h1", "h2", "h3", "p", "div", "span"], string=True):
        if _NO_RESULTS_RE.search(fold(tag.get_text(" ", strip=True))):
            return True
    return False


def _class_tokens(tag: Tag) -> list[str]:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    return [c.lower() for c in classes] + ([str(tag.get("data-test", "")).lower()] if tag.get("data-test") else [])


def _remove_related_blocks(soup: BeautifulSoup) -> None:
    """Drop "Bu İlanla Birlikte Görüntülenenler" / "Benzer İlanlar" sections."""
    for node in list(soup.find_all(string=lambda s: bool(s) and _RELATED_RE.search(fold(s)))):
        if node.parent is None or getattr(node.parent, "decomposed", False):
            continue
        total = len(soup.find_all("a", href=ID_RE))
        container: Optional[Tag] = node.parent
        while container is not None and container.name not in ("body", "html", "[document]", "main"):
            explicit = container.name in ("section", "aside") or any(
                h in c for c in _class_tokens(container) for h in ("related", "similar", "benzer", "recommend")
            )
            n_links = len(container.find_all("a", href=ID_RE))
            if explicit or n_links:
                # never drop a non-explicit block that holds every job link on the page (the main list)
                if explicit or n_links < total:
                    container.decompose()
                break
            container = container.parent


# ---------------------------------------------------------------- embedded JSON (layer a)

_ID_KEYS = ("positionId", "jobId", "advertId", "ilanId")
_TITLE_KEYS = ("title", "positionName", "positionTitle", "jobTitle", "name")


def _walk(obj: Any) -> Iterator[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _name(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or v.get("title") or v.get("text") or "")
    if isinstance(v, list):
        return ", ".join(filter(None, (_name(x) for x in v)))
    return str(v or "")


def _ld_location(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(filter(None, (_ld_location(x) for x in v)))
    if isinstance(v, dict):
        addr = v.get("address", v)
        if isinstance(addr, dict):
            return str(addr.get("addressLocality") or addr.get("addressRegion") or "")
        return str(addr)
    return str(v or "")


def _html_to_text(value: str) -> str:
    return BeautifulSoup(html_lib.unescape(value), "lxml").get_text("\n", strip=True) if value else ""


def _job_from_json(d: dict[str, Any], today: date) -> Optional[Job]:
    is_ld = str(d.get("@type", "")).lower() == "jobposting"
    url = str(_first(d, ("detailPageUrl", "url", "jobUrl", "seoUrl", "link")) or "")
    ext_id = _first(d, _ID_KEYS)
    if ext_id is None and isinstance(d.get("identifier"), dict):
        ext_id = d["identifier"].get("value")
    if ext_id is None and url:
        ext_id = extract_id(url)
    title = _first(d, ("title", "positionName", "positionTitle", "jobTitle"))
    if ext_id is None or not str(ext_id).isdigit() or not title or not (is_ld or _first(d, _ID_KEYS) or url):
        return None
    if url and not url.startswith("http") and "/is-ilani/" not in url:
        url = f"/is-ilani/{url.lstrip('/')}"
    company = _name(_first(d, ("companyName", "company", "hiringOrganization", "firmName")))
    location = _ld_location(d.get("jobLocation")) if is_ld else _name(
        _first(d, ("locationText", "location", "cityName", "city", "locations")))
    work_model = normalize_work_model(_name(_first(d, ("workModelText", "workModel")))) or (
        "uzaktan" if str(d.get("jobLocationType", "")).upper() == "TELECOMMUTE" else "")
    posted_text = str(_first(d, ("postedAt", "jobDateStatus", "datePosted", "postedDate", "date")) or "")
    description = _html_to_text(str(d.get("description") or "")) if is_ld or d.get("description") else ""
    job = Job(
        source=KariyerNetScraper.name, external_id=str(ext_id), title=str(title).strip(),
        company=company.strip(), location=location.strip(), work_model=work_model,
        url=normalize_url(url) if url else f"{BASE_URL}/is-ilani/{ext_id}",
        posted_text=posted_text, posted_date=parse_relative_date(posted_text, today) if posted_text else None,
        description=description,
    )
    if description:
        job.language = detect_language(f"{job.title}\n{description}")
    return job


def _json_blobs(soup: BeautifulSoup) -> Iterator[Any]:
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        stype = (script.get("type") or "").lower()
        if stype == "application/ld+json" or script.get("id") == "__NEXT_DATA__":
            try:
                yield json.loads(text)
            except json.JSONDecodeError:
                log.debug("Unparseable JSON script %s", script.get("id") or stype)
            continue
        if not re.search(r"positionId|jobDateStatus|lastPublishDate", text):
            continue
        m = re.search(r"window\.__[A-Za-z0-9_]+__\s*=\s*", text)
        payload = text[m.end():] if m else text
        payload = payload.strip().rstrip(";").strip()
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:  # e.g. Nuxt's (function(a,b){...}) state -> not JSON
            log.debug("Script with job keys is not plain JSON; skipping")


def parse_embedded_json(soup: BeautifulSoup, today: date) -> list[Job]:
    jobs: list[Job] = []
    for blob in _json_blobs(soup):
        for d in _walk(blob):
            job = _job_from_json(d, today)
            if job:
                jobs.append(job)
    return jobs


# ---------------------------------------------------------------- HTML cards (layer b)

def _card_container(anchor: Tag, ext_id: str, max_up: int = 5) -> Tag:
    """Largest ancestor (bounded) whose /is-ilani/ links all point to the same id."""
    card = anchor
    node = anchor.parent
    for _ in range(max_up):
        if node is None or node.name in ("body", "html", "[document]"):
            break
        ids = {extract_id(a["href"]) for a in node.find_all("a", href=ID_RE)}
        if ids != {ext_id}:
            break
        card = node
        node = node.parent
    return card


def _slug(text: str) -> str:
    """Kariyer.net-style slug for cross-checking: "Fiba Faktoring A.Ş." -> "fiba-faktoring-a-s"."""
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def url_slug_body(href: str) -> str:
    """"/is-ilani/fiba-faktoring-a-s-portfoy-yoneticisi-kayseri-4578859" -> "fiba-...-kayseri"."""
    path = urlsplit(href).path if "://" in href else href.split("?")[0]
    m = re.search(r"/is-ilani/(.+?)-\d+/?$", path)
    return re.sub(r"-+", "-", m.group(1)).strip("-") if m else ""


def _is_title_of(text: str, body: str) -> bool:
    """The ad URL is "<company>-<title>-<id>", so the title's slug is a suffix of the body."""
    s = _slug(text)
    return bool(s) and len(s) >= 3 and (body == s or body.endswith("-" + s))


def _is_company_of(text: str, body: str, title: str) -> bool:
    """Company slug is the prefix; Kariyer truncates long company slugs, so allow either direction."""
    s, t = _slug(text), _slug(title)
    prefix = body[: -len(t)].strip("-") if t and body.endswith(t) else body
    if len(s) < 3 or not prefix:
        return False
    return prefix == s or prefix.startswith(s + "-") or (len(prefix) >= 8 and s.startswith(prefix))


def _by_hint(card: Tag, field: str) -> str:
    hints = _HINTS[field]
    for el in card.find_all(True):
        tokens = _class_tokens(el)
        if field == "title" and any("subtitle" in t for t in tokens):
            continue
        if any(h in t for t in tokens for h in hints):
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _parse_card(card: Tag, anchor: Tag, ext_id: str, today: date) -> Optional[Job]:
    tokens = [re.sub(r"\s+", " ", s).strip() for s in card.stripped_strings]
    tokens = [t for t in tokens if t]
    sponsored = any(fold(t).startswith("sponsorlu") for t in tokens)

    title = _by_hint(card, "title") or (anchor.get("title") or "").strip()
    company = _by_hint(card, "company")
    location = _by_hint(card, "location")
    work_model = normalize_work_model(_by_hint(card, "work_model"))
    age = _by_hint(card, "age")
    if age and not _AGE_RE.match(fold(age)):
        m = re.search(r"\d+\s*(saat|gün|dakika|hafta|ay)|bugün|dün", age, re.IGNORECASE)
        age = m.group(0) if m else age

    # Text-order fallback: [Sponsorlu İlan] company, title, [company], location, model, type, age
    rest: list[str] = []
    model_idx: Optional[int] = None
    more_cities = ""
    for t in tokens:
        f = fold(t)
        if _NOISE_RE.match(f) or _EMPLOYMENT_RE.match(f):
            continue
        if normalize_work_model(t):
            work_model = work_model or normalize_work_model(t)
            model_idx = len(rest) if model_idx is None else model_idx
            continue
        if _AGE_RE.match(f):
            age = age or t
            continue
        if _MORE_CITIES_RE.match(f):
            more_cities = t
            continue
        rest.append(t)
    known = {x for x in (title, company, location) if x}
    if not company and rest:
        company = next((t for t in rest if t != title), "")
    if not title:
        title = next((t for t in rest if t != company), "")
    if not location:
        candidates = rest[:model_idx] if model_idx is not None else rest
        tail = [t for t in candidates if t not in known | {title, company}]
        location = tail[-1] if tail else ""
    if more_cities and more_cities not in location:
        location = f"{location} {more_cities}".strip()

    # Cross-check against the URL slug (<company>-<title>-<id>): on the live site the class hints
    # picked the whole card as "title" and the logo initial ("F") as "company".
    body = url_slug_body(anchor["href"])
    if body:
        clean = [t for t in rest if len(t) > 2 and not fold(t).startswith("sponsorlu")]
        if not _is_title_of(title, body):
            matches = [t for t in clean if _is_title_of(t, body)]
            if matches:
                title = max(matches, key=len)
        if not _is_company_of(company, body, title):
            comp = [t for t in clean if t != title and _is_company_of(t, body, title)]
            if comp:
                company = comp[0]
            elif len(company) <= 2 or company == title:
                company = ""
        if location in (title, company) or len(location) <= 2:
            tail = [t for t in clean if t not in (title, company)]
            location = tail[0] if tail else ""
            if more_cities and more_cities not in location:
                location = f"{location} {more_cities}".strip()
    if fold(title).startswith("sponsorlu"):
        title = ""

    if not title:
        return None
    job = Job(
        source=KariyerNetScraper.name, external_id=ext_id, title=title, company=company,
        location=location, work_model=work_model, url=normalize_url(anchor["href"]),
        posted_text=age, posted_date=parse_relative_date(age, today) if age else None,
    )
    if sponsored:
        job.flags.append("sponsored")
    return job


def parse_cards(soup: BeautifulSoup, today: date) -> list[Job]:
    jobs: list[Job] = []
    seen_cards: set[int] = set()
    for anchor in soup.find_all("a", href=ID_RE):
        ext_id = extract_id(anchor["href"])
        if not ext_id:
            continue
        card = _card_container(anchor, ext_id)
        if id(card) in seen_cards:
            continue
        seen_cards.add(id(card))
        job = _parse_card(card, anchor, ext_id, today)
        if job:
            jobs.append(job)
    return jobs


def dedupe(jobs: Iterable[Job]) -> list[Job]:
    """One job per id; a non-sponsored copy wins over a sponsored duplicate. Order is kept."""
    by_id: dict[str, Job] = {}
    for job in jobs:
        prev = by_id.get(job.external_id)
        if prev is None:
            by_id[job.external_id] = job
        elif "sponsored" in prev.flags and "sponsored" not in job.flags:
            by_id[job.external_id] = job
    return list(by_id.values())


# ---------------------------------------------------------------- detail page

def parse_detail(html: str, job: Job) -> Job:
    """Fill description (and the absolute publish date) from a detail page."""
    soup = BeautifulSoup(html, "lxml")
    raw = soup.decode()
    m = _LAST_PUBLISH_RE.search(raw)
    if not m:
        title_tag = soup.find("meta", property="og:title")
        title_text = (title_tag.get("content") if title_tag else None) or (soup.title.string if soup.title else "")
        m = _TITLE_DATE_RE.search(title_text or "")
    if m:
        parsed = parse_relative_date(m.group(1))
        if parsed:
            job.posted_date = parsed

    _remove_related_blocks(soup)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    lines = [re.sub(r"\s+", " ", s).strip() for s in soup.stripped_strings]
    lines = [ln for ln in lines if ln]
    start = next((i for i, ln in enumerate(lines) if fold(ln).rstrip("?:").strip() in _DETAIL_SECTIONS), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if any(fold(lines[i]).startswith(s) for s in _DETAIL_STOP)), len(lines))
        job.description = "\n".join(lines[start:end])[:8000]
    else:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if meta and meta.get("content"):
            job.description = meta["content"].strip()
    if job.description:
        job.language = detect_language(f"{job.title}\n{job.description}")
    return job


# ---------------------------------------------------------------- scraper

class KariyerNetScraper(BaseScraper):
    name = "kariyernet"
    max_age_days = 1

    def parse_html(self, html: str, today: Optional[date] = None) -> list[Job]:
        today = today or self.today or date.today()
        soup = BeautifulSoup(html, "lxml")
        if is_no_results(soup):
            log.info("[kariyernet] no-results page (similar ads ignored)")
            return []
        _remove_related_blocks(soup)
        jobs = parse_embedded_json(soup, today)
        if not jobs:
            jobs = parse_cards(soup, today)
        if not jobs:
            log.warning("[kariyernet] 0 cards on a page without 'Bulamadık' - layout change or block?")
        return dedupe(jobs)

    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        today = self.today or date.today()
        cutoff = today - timedelta(days=self.max_age_days)
        jobs: list[Job] = []
        for page in range(1, max(max_pages, 1) + 1):
            url = search_url(query, page)
            html = self.get(url).text
            if self.raw_dir is not None:
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                (self.raw_dir / f"{query_slug(query).replace('+', '_')}-p{page}.html").write_text(html, encoding="utf-8")
            page_jobs = self.parse_html(html, today)
            log.info("[kariyernet] %r page %d: %d cards", query, page, len(page_jobs))
            if not page_jobs:
                break
            jobs.extend(page_jobs)
            dated = [j.posted_date for j in page_jobs if j.posted_date]
            if dated and len(dated) == len(page_jobs) and max(dated) < cutoff:
                break  # whole page is older than the date window
        return dedupe(jobs)

    def fetch_detail(self, job: Job) -> Job:
        return parse_detail(self.get(job.url).text, job)
