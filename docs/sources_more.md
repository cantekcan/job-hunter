# More sources: LinkedIn guest, Indeed TR, Secretcv, Yenibiriş

Researched 2026-10-19 using WebFetch (HTML is converted to text, so classes and scripts are lost), WebSearch and open-source scraper code. The container itself gets a 403. **V** = verified by a fetch (the URL is given). **A** = assumption or second-hand.

## 1. LinkedIn guest (no login, ever)
WebFetch refused `linkedin.com/jobs-guest` with ROBOTS_DISALLOWED, so **nothing on this site was fetched**. The facts below come from JobSpy's source (raw.githubusercontent.com/speedyapply/JobSpy/main/jobspy/linkedin/__init__.py) and browse.sh/skills/linkedin.com/search-linkedin-jobs-3v1wu7. The two sources agree.
- **Template (A):** `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={q}&location={loc}&f_TPR=r86400&sortBy=DD&start={0,10}`
  - `f_TPR=r{seconds}`.
  - `f_WT=2` is remote (JobSpy uses it). `f_WT=3` is hybrid (A).
  - Optional: `geoId`, `distance`.
  - Keyword filtering is done server-side and is **unverified here**. Check it on the first run.
- **geoId (A, not verified):** Turkey is `102105699`. For İstanbul, use `location=Istanbul, Türkiye`, or resolve the id once via `/jobs-guest/api/typeaheadHits?query=Istanbul&typeaheadType=GEO`. For remote, use `location=Türkiye&f_WT=2`.
- **Paging:** 10 cards per page; `count` is ignored. Stop when a page has fewer than 10 cards.
- **Selectors:**
  - Card: `div.base-search-card`
  - ID: `data-entity-urn="urn:li:jobPosting:(\d+)"`, or the trailing `-(\d+)` of the href
  - Title: `h3.base-search-card__title`
  - Company: `h4.base-search-card__subtitle a`
  - Location: `span.job-search-card__location`
  - Date: `time.job-search-card__listdate`, which can also be `...__listdate--new`
  - URL: `a.base-card__full-link`, cut at `?`
- **Date:** read the `datetime` attribute as `%Y-%m-%d`. It has no time part, so `f_TPR` does the 24 h cut. Dedupe on the ID.
- **Detail:** `/jobs-guest/jobs/api/jobPosting/{id}` (A) or `/jobs/view/{id}` (JobSpy).
  - Description: `div.show-more-less-html__markup`.
  - Criteria: `span.description__job-criteria-text`.
  - If the URL ends up at `linkedin.com/signup`, it is an authwall.
- **Risk: MEDIUM.** JobSpy waits 3–7 s between pages and stops on 429. GitHub Actions runs from datacenter IPs. Plan:
  - Cap a run at about 30 requests.
  - On 429 or an authwall, skip LinkedIn for the day and keep the partial results.
- **Sample cards:** none (could not fetch).

## 2. Indeed TR
- **V:**
  - tr.indeed.com/jobs?q=.net+developer&l=%C4%B0stanbul&sort=date returned a **real page with no challenge**. The meta says "42 açık .NET Developer iş ilanı".
  - Pagination is `start=10` and `start=20`.
- **V, keyword filter works:** `/jobs?q=c%23&l=T%C3%BCrkiye` returned "87 açık C# iş ilanı" (.NET and ASP.NET cards).
- **V, `fromage` works:** adding `&fromage=14` cut it to 4. `fromage=1` and `fromage=7` gave **0** for both `.net developer` and `yazılım geliştirici` in İstanbul. **Daily volume is very low.**
- **Template:** `https://tr.indeed.com/jobs?q={q}&l={İstanbul|Türkiye}&fromage=1&sort=date&start={0,10}`. `fromage=3` plus dedupe is a safer alternative.
- **ID:** `data-jk`, or `jk=` in hrefs (`/rc/clk?jk=`, `/viewjob?jk=`). Canonical URL: `https://tr.indeed.com/viewjob?jk={jk}`.
- **Selectors (A, not visible via WebFetch):**
  - Title: `h2.jobTitle span[title]`
  - Company: `[data-testid=company-name]`
  - Location: `[data-testid=text-location]`
  - Date: `[data-testid=myJobsStateDate]` or `span.date`. Text looks like "Bugün", "Şimdi", "1 gün önce".
  - Preferred JSON: `window.mosaic.providerData["mosaic-provider-jobcards"]` → `metaData.mosaicProviderJobCardsModel.results[]` with `jobkey`, `title`, `company`, `formattedLocation`, `pubDate` (ms), `formattedRelativeTime`. This is unverified because WebFetch strips scripts.
- **Date:** no per-card date appeared in the converted text. Rely on `fromage`, plus `pubDate >= now-24h` when the JSON is present.
- **Risk: HIGH from GitHub Actions** (Cloudflare 403 or a "Doğrulama" page). If the page has no `data-jk` and no "eşleşmedi" text, treat it as **blocked**: log it, skip the source, and don't fail the run. Max 2–3 pages per run.
- (A) JobSpy's mobile GraphQL API (apis.indeed.com/graphql with the app's api key) is fragile and a ToS grey area. Not recommended.
- **Copied data** (c#/Türkiye page; jk values as the converter reported them):
  1. .NET Developer | ISCOM | İstanbul | no date | https://tr.indeed.com/viewjob?jk=ad8cbce77652e9c0
  2. Software ASP.NET Developer | MagiClick Digital Solutions | İstanbul | no date | https://tr.indeed.com/viewjob?jk=ddd15c91e2bd2ba8
  3. Mid-Level .Net Developer (CR-MNDE02) | CRENNO | Kağıthane | no date | https://tr.indeed.com/viewjob?jk=74baf3f22ce04a2e

## 3. Secretcv
- **V:**
  - www.secretcv.com/is-ilanlari shows "19.227" listings, paged as `?sf=2` … `?sf=323`.
  - /is-ilanlari/istanbul shows "2.479 İş İlanı Listelendi", paged as `/is-ilanlari/istanbul-is-ilanlari/?sf=N`.
- **V, position slugs all return 0:**
  - `/is-ilanlari/istanbul/yazilim-muhendisi-is-ilanlari`, `/is-ilanlari/yazilim-uzmani-is-ilanlari` and `/is-ilanlari/c-yazilim-gelistirme-uzmani-is-ilanlari`, plus the istanbul-avrupa/anadolu variants, all show "Arama kriterlerinize ait ilan bulunamadı!".
  - The sector page `/is-ilanlari/bilgisayar-bt-internet-is-ilanlari` has 34 listings, almost none of them software.
  - **No free-text keyword URL found.** `?kw=` returned an error.
- **Card text (V):** title · company ("Firma Adı Gizli" when hidden) · location ("İstanbul Anadolu/Avrupa") · "İlan Tarihi: 3 gün önce". Sponsored cards have no date.
- **Detail (V):**
  - URL: `https://www.secretcv.com/{company-slug}/{title-slug}-is-ilanlari-{id}`. Get the ID with `-(\d+)$`; it also appears as `ilanId=` in apply links.
  - The page has an absolute date, "İlan Tarihi 16-10-2026" (`%d-%m-%Y`).
  - Sections: "İş Açıklaması" and "İstenen Yetenek ve Uzmanlıklar".
- **Date filter (V, labels only, no params):** Bugünün İlanları, Son 3 Günün, Bu Haftanın, …. There is a "Tarihe Göre Sırala" sort option.
- **Recommendation:** **low value; deprioritise.** If you build it anyway:
  - Scan `/is-ilanlari/istanbul-is-ilanlari` pages 1–3.
  - Accept "Bugün", "N saat" or "1 gün".
  - Filter titles locally.
  - Dedupe on the ID.
- **Risk: LOW** (server-rendered HTML).
- **Copied data** (/is-ilanlari/istanbul):
  1. Boyner İstanbul Neomarin AVM - Kasiyer Full Time | Boyner Büyük Mağazacılık | İstanbul Anadolu | 3 gün önce | https://www.secretcv.com/boyner-buyuk-magazacilik/boyner-istanbul-neomarin-avm-kasiyer-full-time-is-ilanlari-1882116
  2. Mağaza Müdürü - İstanbul Torium Avm | English Home | İstanbul Avrupa | 3 gün önce | https://www.secretcv.com/english-home/magaza-muduru-istanbul-torium-avm-is-ilanlari-1882160
  3. Mağaza Yönetici Yardımcısı (İstanbul Maltepepark) | Porland | İstanbul Anadolu | 3 gün önce | https://www.secretcv.com/porland/magaza-yonetici-yardimcisi-istanbul-maltepepark-is-ilanlari-1882140

## 4. Yenibiriş
- **V:**
  - www.yenibiris.com/is-ilanlari shows "5313 iş ilanı", paged as `?sayfa=N`.
  - The category page /is-ilanlari/yazilim shows "10 Yazılım iş ilanı listelendi", so **the category filter works**.
  - /is-ilanlari/yazilim-uzmani returns 4 listings.
  - Filters combine with `+` (`istanbul-anadolu-yakasi+yazilim-uzmani` shows its "Seçili Filtreler" and 0 results).
  - Free-text keyword parameter: not found.
- **Volume:** about 10 software ads nationwide, many of them weeks old.
- **Template:** `https://www.yenibiris.com/is-ilanlari/yazilim` (page 1). Filter titles locally.
- **Detail (V):** `https://www.yenibiris.com/is-ilani/{title-slug}/{id}`. Get the ID with `/(\d+)$`. The page shows "Güncelleme Tarihi" as `dd.mm.yyyy` (seen on /is-ilani/net-developer/926914).
- **Card text (V):** title | company | "City - District" | a date in `d.mm.yyyy` form, or "Son 1 Hafta" for new ads. "Son 1 Hafta" is too coarse, so rely on first-seen dedupe. The date filter labels ("Bugün/Dün yayına girenler") expose no params.
- **Risk: LOW.**
- **Copied data** (/is-ilanlari/yazilim):
  1. Yazılım Geliştirme Uzmanı | Beş Yıldız Eğitim Kurumları | İstanbul Avrupa Yakası - Başakşehir | 17.09.2026 | https://www.yenibiris.com/is-ilani/yazilim-gelistirme-uzmani/1220282
  2. Bulut Yazılım Uzmanı | Akınsoft | Konya - Karatay | 11.09.2026 | https://www.yenibiris.com/is-ilani/bulut-yazilim-uzmani/1220921
  3. Part Time Web Sitesi Sorumlusu / İnternet Reklam Personeli | Genç Akademi | İstanbul Anadolu Yakası - Pendik | Son 1 Hafta | https://www.yenibiris.com/is-ilani/part-time-web-sitesi-sorumlusu-internet-reklam-personeli/1222191

## Priority
LinkedIn (most relevant volume) > Indeed (filters verified, low volume, high block risk) > Yenibiriş and Secretcv (optional, almost no .NET ads). Every scraper must fail soft: log the error, send a "source X skipped" note, and continue the run.
