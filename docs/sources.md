# Job Sources — Analysis

Research date: 2026-10-18. The build container gets a proxy 403 from kariyer.net, so direct `curl`/`requests` could not be tested from here. Facts below were gathered with WebFetch (a server-side fetch that converts HTML to text/markdown) and WebSearch. **Script tags may be stripped in that conversion**, so "no JSON found" is *not* proof that there's no JSON. See `docs/kariyer_observed.md` for raw observations.

## 1. Kariyer.net (primary)

### VERIFIED (observed via WebFetch)

| Fact | Evidence |
|---|---|
| Search/list URL: `https://www.kariyer.net/is-ilanlari/<slug>`, slug words joined with `+` (e.g. `net+developer`, `asp+net+yazilim+muhendisi`, `finans+uzmani`). City/remote also work as path segments: `/is-ilanlari/istanbul`, `/is-ilanlari/ankara`, `/is-ilanlari/remote`, `/is-ilanlari/istanbul+avrupa-sisli` | https://www.kariyer.net/is-ilanlari/asp+net+yazilim+muhendisi, https://www.kariyer.net/is-ilanlari/istanbul |
| Hyphenated slugs exist too (`/is-ilanlari/yazilim-muhendisi`) | Apify example: https://apify.com/unfenced-group/kariyer-net-scraper |
| A keyword slug acts as a **position filter** ("Seçili Filtreler (1)"). If there are no matches the page says "… İlanını Bulamadık" and shows "benzer ilanlar" (similar ads). **Those cards must not be treated as matches.** | asp+net+yazilim+muhendisi page |
| `/is-ilanlari/net+developer` came back as general listings (non-IT ads such as "Finans Asistanı"), so a slug that isn't recognised may fall back to the unfiltered list | https://www.kariyer.net/is-ilanlari/net+developer |
| Pagination: a path suffix `-N` (`/is-ilanlari/istanbul-2` … `-100`, "Sonraki" link). On the root list, `?cp=N` was also seen. Max about 100 pages ("100 sayfa içerisinden 1. sayfadasınız") | istanbul page; root /is-ilanlari |
| Detail URL: `https://www.kariyer.net/is-ilani/<company-slug>-<title-slug>-<numericId>`. The ID is the trailing integer (e.g. `...--net-lead-developer-4578674`). A double hyphen appears when the title starts with "." (".Net"). Subdomains such as `web.`/`akdeniz.`/`docs.kariyer.net` serve the same paths, so **normalise to www and dedupe on the numeric ID** | https://www.kariyer.net/is-ilani/turkcell-ve-grup-sirketleri--net-lead-developer-4578674 |
| Card fields, in order: [optional "Sponsorlu İlan"] · company · title (the company sometimes repeats) · location (may have the suffix "+N il daha", or "İstanbul (Tümü)") · work model ("İş Yerinde" / "Hibrit" / "Uzaktan / Remote") · employment type ("Tam zamanlı" / "Yarı zamanlı") · relative age ("1 saat", "1 gün", "2 gün", behind an update icon) · optional badge "Ort. 2 günde dönüyor" | list pages above |
| Date filter UI "Tarih" options: Tümü, **Bugünün ilanları**, Son 3 saat, Son 8 saat, Son 3 gün, Son 7 gün, Son 15 gün, İlk kez yayınlananlar. "Son 24 saat" does **not** exist. The options appear as JS-driven controls with no `href` | asp+net page |
| Detail page: H1 title, company link, location ("İstanbul(Asya), İstanbul(Avr.)"), "Hibrit Tam Zamanlı", level ("Uzman"), department ("Bilgi Teknolojileri / IT"), "200+ başvuru", "5 gün önce güncellendi", sections "İş İlanı Hakkında", "Ne Bekliyoruz?", "Aday Kriterleri" (experience "5 - 14 yıl arası", education) and "Şirket Hakkında" | Turkcell detail page |
| The detail page contains the strings `lastPublishDate:14.10.2026` and `closingDate:12.11.2026`. These are likely from an embedded JS state object, so **absolute dates are available on the detail page** | Turkcell detail page |
| The `og:title` and `<title>` end with the publish date: "… İş İlanı - 14.10.2026". This is a reliable fallback for the date | Turkcell detail page |
| No `__NEXT_DATA__` and no `application/ld+json` JobPosting appeared in the converted text (but see the caveat above) | all fetched pages |

### ASSUMPTIONS (to verify on first real run from the user's machine)

- **Date filter query parameter: UNKNOWN.** No href exposed it. Candidates to test in DevTools: click "Bugünün ilanları" and read the resulting URL or XHR. The site may call an internal JSON search API. Third-party scrapers output fields such as `positionId`, `companyId`, `jobCode`, `workType`, `workModel`, `jobStatus`, `jobDateStatus` and `postedAt` (https://apify.com/powerai/kariyer-jobs-scraper), which strongly suggests a JSON API behind the list. **Do not depend on a date param.** Instead, sort/scan the first 1–3 pages and filter client-side on relative age ("N saat" / "1 gün" / "Bugün" / "Yeni") plus dedupe in SQLite.
- The page is probably a Nuxt/Vue or Next app with state in a `<script>` (e.g. `window.__NUXT__`). `lastPublishDate:` without quotes resembles a serialized JS object, not JSON.
- Plain `requests` with a browser User-Agent probably returns server-rendered HTML (WebFetch got full card text without JS). Cloudflare/bot protection may still block it, so plan a fallback to Playwright.
- The keyword search may also work as `https://www.kariyer.net/is-ilanlari?kw=<q>` (unverified; don't use until tested).

### Recommended parsing strategy

1. **Fetch the list:** `https://www.kariyer.net/is-ilanlari/<query-slug>` (slugify: lowercase, transliterate TR characters, spaces become `+`), plus `-2`, `-3` for pages 2–3. Stop early when every card on a page is older than 1 day or is already in the DB.
2. **Extract cards in layers:**
   a. Look for embedded JSON first: `<script type="application/ld+json">`, `__NEXT_DATA__`, `window.__NUXT__`, or any `<script>` containing `"jobId"`/`positionId`/`lastPublishDate`.
   b. Fallback: select all `a[href*="/is-ilani/"]`, take the ID from the href with the regex `-(\d+)(?:[/?#]|$)`, and parse the anchor's text nodes (title, company, location, work model, age). Avoid brittle generated class names. Anchor on the href pattern and the text vocabulary ("İş Yerinde|Hibrit|Uzaktan", "Tam zamanlı|Yarı zamanlı", the age regex `(\d+)\s*(saat|gün|dakika)` or `Bugün|Dün|Yeni`).
   c. Skip "Sponsorlu İlan" duplicates (dedupe by ID handles this) and the "benzer ilanlar" (similar ads) section on no-result pages.
3. **Detail page (only for new IDs that pass the title filter):** parse H1, the description sections and "Aday Kriterleri". Get the date from `lastPublishDate`/`closingDate`, falling back to the date suffix in `og:title`.
4. **Pre-filter before the LLM:** apply the `exclude_title_keywords` and `include_locations` lists from `profile/preferences.md` (`java` must match as a whole word only). This saves free-tier LLM quota.
5. **Selector health check:** if a page returns 0 cards and doesn't say "Bulamadık", alert via Telegram (layout change or block).

### Polite crawling

- Use a real desktop browser User-Agent with `Accept-Language: tr-TR`. One session, keep-alive.
- Wait a random **2–5 s** between requests, never run in parallel, and back off on 429/403 (stop the run and notify).
- **At most 1–2 runs per day.** Roughly 10–15 queries × 1–3 pages plus detail pages for new IDs only.
- Respect `robots.txt` (not checked from here; check on first run). No login. Personal use only. Don't redistribute the data.

## 2. Later sources (brief)

### LinkedIn (guest job search)
- Public guest search: `https://www.linkedin.com/jobs/search?keywords=.net%20developer&location=Istanbul&f_TPR=r86400` (`f_TPR=r86400` means the past 24 h. `f_WT=2` means remote, `f_WT=3` hybrid; these are well-known parameters but were not verified here). The guest HTML fragment endpoint `jobs-guest/jobs/api/seeMoreJobPostings/search?...&start=N` is commonly used (assumption).
- **NEVER scrape while logged in. Never use the user's cookies or account.** Account bans and ToS violations are a real risk. Use guest pages only, at low volume (1 run/day, under 50 requests). If 429 or an authwall appears, skip LinkedIn for that day.
- The other option is LinkedIn job alert emails, which are safer.

### Indeed TR (tr.indeed.com)
- `https://tr.indeed.com/jobs?q=.net+developer&l=İstanbul&fromage=1` (`fromage=1` means the last day; assumption based on the global Indeed URL scheme). Heavy Cloudflare protection, so a headless browser is probably needed. Lower priority.

### Secretcv (secretcv.com) and Yenibiris (yenibiris.com)
- Turkish boards, smaller IT volume. Both have URL-based search (not verified here). Add them after Kariyer.net is stable, with the same pattern: list page, then ID, dedupe, detail page.

## Open risks
1. The date filter parameter is unknown, so we rely on parsing relative age and dedupe.
2. A keyword slug that isn't recognised returns the general list or "similar ads", which creates noise. Validate that card titles contain query terms, or tune the slugs on the first run.
3. Bot protection or 403 from residential IPs is untested.
4. Embedded JSON is unconfirmed, so CSS/text fallback must exist from day one.


## Gerçek çalıştırmadan öğrenilenler (2026-10-19)
- `/is-ilanlari/<serbest metin>` (ör. `net+developer`) filtrelemez; genel ilan listesine düşer. Sadece
  Kariyer.net'in pozisyon adları çalışır: `yazilim+gelistirme+uzmani`, `yazilim+uzmani`,
  `yazilim+muhendisi`, `asp+net+yazilim+uzmani` (doğrulandı, sayfalar `-2`, `-3`).
- Filtreli liste bitince "…İlanlarının Hepsini İnceledin" + "Benzer pozisyondaki ilanlar" gelir.
- Kartta logo yerine şirketin baş harfi (ör. "F") olan bir öğe var; class ipuçları bunu şirket, bütün
  kartı sarmalayan öğeyi başlık sanıyordu. Artık alanlar ilan URL'sindeki `<şirket>-<başlık>-<id>`
  slug'ıyla doğrulanıyor.
