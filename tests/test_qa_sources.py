"""QA: multi-source scraping (Kariyer.net, LinkedIn guest, Indeed TR, Secretcv, Yenibiriş).

All HTTP goes through a fake ``requests.Session.get`` router; sleeps are no-ops; nothing hits the network.
"""
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests
import time_machine

from src import main as M
from src.config import DEFAULT_PREFS, load_config, load_preferences
from src.dateparse import parse_relative_date
from src.filter import JobStore
from src.scrapers import SCRAPERS
from src.scrapers import indeed as IND
from src.scrapers import linkedin as LI
from src.scrapers import secretcv as SCV

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "tests" / "fixtures"
RUN_DAY = date(2026, 10, 19)
ALL = ["kariyernet", "linkedin", "indeed", "secretcv", "yenibiris"]


def fx(name):
    return (FX / name).read_text(encoding="utf-8")


def resp(status=200, text="", url="https://x/"):
    r = requests.Response()
    r.status_code, r._content, r.url, r.encoding, r.reason = status, text.encode("utf-8"), url, "utf-8", "X"
    return r


GOOD = {
    "kariyer.net": lambda url: fx("kariyernet_detail.html") if "/is-ilani/" in url else fx("kariyernet_list.html"),
    "linkedin.com": lambda url: fx("linkedin_detail.html") if "/jobPosting/" in url else fx("linkedin_list.html"),
    "indeed.com": lambda url: "<html><div id='jobDescriptionText'>C# .NET</div></html>" if "viewjob" in url
    else fx("indeed_list.html"),
    "secretcv.com": lambda url: fx("secretcv_list.html") if "/is-ilanlari/" in url else fx("secretcv_detail.html"),
    "yenibiris.com": lambda url: fx("yenibiris_detail.html") if "/is-ilani/" in url else fx("yenibiris_list.html"),
}


class Router:
    """Fake Session.get. ``bad`` maps a host key to a callable(url) returning a Response or raising."""

    def __init__(self, bad=None):
        self.bad = bad or {}
        self.calls = []

    def __call__(self, session, url, params=None, **kw):
        self.calls.append((url, dict(session.headers), dict(session.cookies)))
        host = next(h for h in GOOD if h in url)
        if host in self.bad:
            return self.bad[host](url)
        return resp(200, GOOD[host](url), url)

    def count(self, host):
        return sum(host in u for u, _, _ in self.calls)


@pytest.fixture
def env(tmp_path, monkeypatch):
    sleeps = []
    orig = M.build_scrapers

    def build(sources):
        scrapers = orig(sources)
        for s in scrapers.values():
            s._sleep = sleeps.append
        return scrapers
    monkeypatch.setattr(M, "build_scrapers", build)
    cfg = load_config(root=tmp_path, env={}, prefs_path=ROOT / "profile" / "preferences.md")

    def install(router):
        monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: router(self, url, **kw))
        monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("unexpected POST"))
        return router
    return SimpleEnv(tmp_path, cfg, sleeps, install)


class SimpleEnv:
    def __init__(self, tmp, cfg, sleeps, install):
        self.tmp, self.cfg, self.sleeps, self.install = tmp, cfg, sleeps, install

    def collect(self, sources=ALL):
        return M.collect_jobs(self.cfg, sources, None, M.build_scrapers(sources), RUN_DAY)

    def report(self):
        return (self.tmp / "output" / RUN_DAY.isoformat() / "report.md").read_text("utf-8")


def _raise(exc):
    def f(url):
        raise exc
    return f


# ---------------- (1) blocked / crashing sources never stop the others ----------------

BAD_CASES = {
    "linkedin-999": ("linkedin.com", lambda u: resp(999, "", u)),
    "linkedin-429": ("linkedin.com", lambda u: resp(429, "", u)),
    "linkedin-authwall": ("linkedin.com", lambda u: resp(200, fx("linkedin_authwall.html"), u)),
    "linkedin-redirect": ("linkedin.com", lambda u: resp(200, "<html></html>", "https://www.linkedin.com/authwall?x=1")),
    "indeed-403": ("indeed.com", lambda u: resp(403, "Forbidden", u)),
    "indeed-cloudflare": ("indeed.com", lambda u: resp(200, fx("indeed_challenge.html"), u)),
    "indeed-conn": ("indeed.com", _raise(requests.ConnectionError("reset"))),
    "secretcv-429": ("secretcv.com", lambda u: resp(429, "slow down", u)),
    "secretcv-500": ("secretcv.com", lambda u: resp(500, "boom", u)),
    "yenibiris-timeout": ("yenibiris.com", _raise(requests.Timeout("read timeout"))),
    "yenibiris-garbage": ("yenibiris.com", lambda u: resp(200, "\x00<<<>>>not html", u)),
    "kariyer-403": ("kariyer.net", lambda u: resp(403, "", u)),
    "kariyer-crash": ("kariyer.net", _raise(RuntimeError("weird"))),
}


@pytest.mark.parametrize("case", list(BAD_CASES))
def test_bad_source_does_not_stop_others(env, case):
    host, behavior = BAD_CASES[case]
    env.install(Router({host: behavior}))
    jobs = env.collect()
    sources = {j.source for j in jobs}
    bad_name = {"linkedin.com": "linkedin", "indeed.com": "indeed", "secretcv.com": "secretcv",
                "yenibiris.com": "yenibiris", "kariyer.net": "kariyernet"}[host]
    assert sources == set(ALL) - {bad_name}, case


@pytest.mark.parametrize("case", ["linkedin-999", "indeed-cloudflare", "kariyer-crash", "yenibiris-timeout"])
def test_bad_source_full_run_succeeds(env, case):
    host, behavior = BAD_CASES[case]
    env.install(Router({host: behavior}))
    assert M.run(M.parse_args(["--dry-run", "--no-ai"]), env.cfg, RUN_DAY) == 0
    assert "Senior .NET Developer" in env.report() or ".Net Lead Developer" in env.report()


def test_blocked_source_stops_after_first_block(env):
    r = env.install(Router({"linkedin.com": lambda u: resp(429, "", u), "indeed.com": lambda u: resp(403, "", u)}))
    env.collect()
    assert r.count("linkedin.com") == 1 and r.count("indeed.com") == 1


def test_parser_exception_isolated(env, monkeypatch):
    env.install(Router())
    monkeypatch.setattr(SCV, "parse_cards", lambda html, today: (_ for _ in ()).throw(ValueError("layout")))
    assert {j.source for j in env.collect()} == set(ALL) - {"secretcv"}


def test_detail_blocked_does_not_fail_run(env, monkeypatch):
    def li(url):
        return resp(999, "", url) if "/jobPosting/" in url else resp(200, fx("linkedin_list.html"), url)
    env.install(Router({"linkedin.com": li, "indeed.com": lambda u: resp(200, fx("indeed_challenge.html"), u)
                        if "viewjob" in u else resp(200, fx("indeed_list.html"), u)}))

    class Chain:
        def __bool__(self):
            return True

        def complete(self, system, user, json_mode=False, strong=False):
            return "Merhaba" if strong else json.dumps({"score": 40})
    monkeypatch.setattr(M, "build_chain", lambda cfg: Chain())
    assert M.run(M.parse_args(["--dry-run"]), env.cfg, RUN_DAY) == 0


# ---------------- (2) LinkedIn: no cookies / auth, request cap, delays ----------------

def _li_full_page(start):
    cards = "".join(
        f'<li><div class="base-search-card" data-entity-urn="urn:li:jobPosting:{9000 + start + i}">'
        f'<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/x-{9000 + start + i}"></a>'
        f'<h3 class="base-search-card__title">.NET Developer {start + i}</h3>'
        f'<time datetime="2026-10-19">1 hour ago</time></div></li>' for i in range(10))
    return cards


def test_linkedin_request_cap_and_delays(env, monkeypatch):
    def li(url):
        start = int(re.search(r"start=(\d+)", url).group(1)) if "start=" in url else 0
        return resp(200, _li_full_page(start), url)
    r = env.install(Router({"linkedin.com": li}))
    env.cfg.max_pages = 50
    s = M.build_scrapers(["linkedin"])["linkedin"]
    jobs = s.fetch_all(env.cfg)
    for j in jobs[:5]:
        s.fetch_detail(j)
    assert r.count("linkedin.com") == LI.MAX_REQUESTS == 30
    assert len(env.sleeps) == 29 and all(3.0 <= x <= 7.0 for x in env.sleeps)
    for url, headers, cookies in r.calls:
        assert "authorization" not in {k.lower() for k in headers} and "cookie" not in {k.lower() for k in headers}
        assert "f_TPR=r86400" in url or "/jobPosting/" in url


class _CookieAdapter(requests.adapters.HTTPAdapter):
    """Real Session plumbing: responses set cookies like LinkedIn does (bcookie, JSESSIONID, lidc)."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, request, **kw):
        import io
        from urllib3 import HTTPResponse
        self.sent.append(dict(request.headers))
        raw = HTTPResponse(body=io.BytesIO(_li_full_page(0).encode()), status=200, preload_content=False,
                           headers={"Set-Cookie": "JSESSIONID=ajax:123; Path=/; Domain=.linkedin.com",
                                    "Content-Type": "text/html"})
        import email
        from types import SimpleNamespace
        msg = email.message_from_string("Set-Cookie: JSESSIONID=ajax123; Path=/; Domain=.linkedin.com\r\n\r\n",
                                        _class=__import__("http.client").client.HTTPMessage)
        raw._original_response = SimpleNamespace(msg=msg)
        return self.build_response(request, raw)


def test_linkedin_never_sends_cookies():
    adapter = _CookieAdapter()
    s = LI.LinkedInScraper(sleep=lambda x: None)
    s.session.mount("https://", adapter)
    s.configure(type("C", (), {"linkedin_queries": ["a", "b"], "linkedin_locations": ["Türkiye"], "max_pages": 1})())
    s.fetch_all()
    assert len(adapter.sent) == 2
    assert all("Cookie" not in h for h in adapter.sent), adapter.sent[-1]


# ---------------- (3) uids / dedupe ----------------

def test_uids_unique_and_prefixed(env):
    env.install(Router())
    jobs = env.collect()
    uids = [j.uid for j in jobs]
    assert len(uids) == len(set(uids))
    assert all(j.uid.startswith(j.source + ":") and j.source in ALL for j in jobs)


def test_same_external_id_on_two_sources_does_not_collide(tmp_path):
    from src.models import Job
    with JobStore(tmp_path / "j.db") as st:
        a, b = Job("secretcv", "1882116", "X"), Job("yenibiris", "1882116", "X")
        assert len(st.filter_new([a, b], RUN_DAY)) == 2


def test_kariyer_ad_found_twice_is_deduped(env):
    r = env.install(Router())
    env.cfg.search_queries = [".net developer", "c# developer", "backend developer"]
    jobs = M.collect_jobs(env.cfg, ["kariyernet"], None, M.build_scrapers(["kariyernet"]), RUN_DAY)
    assert r.count("kariyer.net") >= 3
    assert len([j for j in jobs if j.uid == "kariyernet:4578674"]) == 1
    prepared = M.prepare(jobs + jobs, RUN_DAY)
    assert len(prepared) == len({j.uid for j in jobs})


def test_second_run_same_db_finds_nothing_new(env):
    env.install(Router())
    M.run(M.parse_args(["--no-ai"]), env.cfg, RUN_DAY)
    M.run(M.parse_args(["--no-ai"]), env.cfg, RUN_DAY)
    assert "**Yeni:** 0" in env.report() or "Yeni:** 0" in env.report()


# ---------------- (4) dates per source, run's today vs. wall clock ----------------

@pytest.mark.parametrize("text,expected", [
    ("16-10-2026", date(2026, 10, 16)), ("1.09.2026", date(2026, 9, 1)), ("9.10.2026", date(2026, 10, 9)),
    ("İlan Tarihi: 16-10-2026", date(2026, 10, 16)), ("Son 1 Hafta", None), ("Son 3 Gün", None),
    ("SON 24 SAAT", None), ("32-10-2026", None), ("16-10/2026", None),
])
def test_new_date_formats(text, expected):
    assert parse_relative_date(text, RUN_DAY) == expected


def test_indeed_epoch_ms_is_turkey_day():
    # 2026-10-18 22:30 UTC == 2026-10-19 01:30 Istanbul
    ms = int(datetime(2026, 10, 18, 22, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert IND._from_epoch_ms(ms) == date(2026, 10, 19)
    assert IND._from_epoch_ms("garbage") is None and IND._from_epoch_ms(10 ** 30) is None


EXPECTED_DATES = {
    "kariyernet:4578674": date(2026, 10, 19), "kariyernet:4581001": date(2026, 10, 18),
    "kariyernet:4579304": date(2026, 10, 17), "linkedin:4012345678": date(2026, 10, 19),
    "linkedin:4012345681": date(2026, 10, 16), "indeed:ad8cbce77652e9c0": date(2026, 10, 19),
    "indeed:ddd15c91e2bd2ba8": date(2026, 10, 18), "secretcv:1883002": date(2026, 10, 19),
    "secretcv:1882116": date(2026, 10, 16), "yenibiris:926914": date(2026, 10, 9),
    "yenibiris:1222191": None,
}


def test_run_today_used_not_wall_clock(env):
    env.install(Router())
    with time_machine.travel(datetime(2031, 3, 3, 12, tzinfo=timezone.utc), tick=False):
        assert date.today() == date(2031, 3, 3)
        jobs = {j.uid: j for j in M.prepare(env.collect(), RUN_DAY)}
        for uid, d in EXPECTED_DATES.items():
            assert jobs[uid].posted_date == d, uid
        assert M.run(M.parse_args(["--dry-run", "--no-ai"]), env.cfg, RUN_DAY) == 0
    rep = env.report()
    for keep in (".Net Lead Developer", "Backend Engineer (C#, .NET 8)", "Software ASP.NET Developer"):
        assert keep in rep, keep
    for drop in ("Senior Software Engineer (.NET)", "Software Engineer (.NET) - Hybrid", "Mid-Level .Net Developer"):
        assert drop not in rep, drop


def _ai_chain(score=85):
    class Chain:
        last_ai = None

        def __bool__(self):
            return True

        def complete(self, system, user, json_mode=False, strong=False):
            return "Merhaba,\nmetin" if strong else json.dumps({"score": score, "eslesen": ["C#"], "dil": "tr"})
    return Chain()


def test_detail_date_older_than_window_is_not_notified(env, monkeypatch):
    env.install(Router())
    monkeypatch.setattr(M, "build_chain", lambda cfg: _ai_chain())
    M.run(M.parse_args(["--dry-run", "--sources", "secretcv"]), env.cfg, RUN_DAY)
    dry = (env.tmp / "output" / RUN_DAY.isoformat() / "telegram_dryrun.txt").read_text("utf-8")
    assert "Kıdemli .NET Yazılım Uzmanı" not in dry  # detail says 16-10-2026


# ---------------- (5) title pre-filter + exclude for every source ----------------

def test_prefilter_and_exclude_apply_to_all_sources(env):
    env.install(Router())
    assert M.run(M.parse_args(["--dry-run", "--no-ai"]), env.cfg, RUN_DAY) == 0
    rep = env.report()
    for gone in ("Java Developer", "Junior .NET Developer", "Kasiyer", "Mağaza Müdürü", "Part Time Web Sitesi"):
        assert gone not in rep, gone
    for src_title in (".Net Lead Developer", "Senior .NET Developer", "Backend Developer (C#) - Uzaktan",
                      "Backend Developer (C#)"):
        assert src_title in rep, src_title


# ---------------- (6) config ----------------

def test_real_preferences_source_keys():
    p = load_preferences(ROOT / "profile" / "preferences.md")
    assert p["sources"] == ALL
    assert p["linkedin_queries"] == [".NET Developer", "C# Developer", "Backend Developer .NET", "Senior Software Engineer C#"]
    assert p["linkedin_locations"] == ["Istanbul, Türkiye", "Türkiye|f_WT=2"]
    assert p["indeed_queries"] == ["c#", ".net", "backend developer"]
    assert p["indeed_locations"] == ["İstanbul", "Türkiye"]
    assert p["secretcv_paths"] == ["istanbul-is-ilanlari"] and p["yenibiris_paths"] == ["yazilim", "yazilim-uzmani"]
    assert set(SCRAPERS) == set(ALL)


def test_defaults_when_keys_missing(tmp_path):
    prefs = tmp_path / "p.md"
    prefs.write_text("# x\n```yaml\nmin_score_notify: 55\nsources: \"linkedin\"\n```\n", encoding="utf-8")
    c = load_config(root=tmp_path, env={}, prefs_path=prefs)
    assert c.min_score_notify == 55 and c.sources == ["linkedin"]
    for key in ("linkedin_queries", "linkedin_locations", "indeed_queries", "indeed_locations",
                "secretcv_paths", "yenibiris_paths", "max_pages", "max_details"):
        assert getattr(c, key) == DEFAULT_PREFS[key], key
    c2 = load_config(root=tmp_path, env={}, prefs_path=tmp_path / "missing.md")
    assert c2.sources == DEFAULT_PREFS["sources"]


def test_unknown_source_in_prefs_ignored(env):
    env.cfg.sources = ["linkedin", "bogus"]
    assert M.default_sources(env.cfg) == ["linkedin"]


# ---------------- (7) worst-case request budget ----------------

def test_request_budget_all_pages_full(env):
    """Every list page 'full' -> upper bound of list requests from the real config."""
    def full_kariyer(url):
        return resp(200, fx("kariyernet_list.html").replace("4578674", str(abs(hash(url)) % 10 ** 7)), url)
    r = env.install(Router({"linkedin.com": lambda u: resp(200, _li_full_page(int(re.search(r"start=(\d+)", u).group(1))), u),
                            "kariyer.net": full_kariyer}))
    env.collect()
    c = env.cfg
    assert r.count("kariyer.net") <= len(c.search_queries) * c.max_pages
    assert r.count("linkedin.com") <= LI.MAX_REQUESTS
    assert r.count("indeed.com") <= len(c.indeed_queries) * len(c.indeed_locations) * IND.MAX_PAGES
    assert len(r.calls) <= 100


def test_dead_source_gives_up_quickly(env):
    r = env.install(Router({"kariyer.net": _raise(requests.Timeout("read timeout"))}))
    env.collect(["kariyernet"])
    assert r.count("kariyer.net") <= 6
