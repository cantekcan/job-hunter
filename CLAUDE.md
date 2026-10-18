# Job Hunter — Claude Code Proje Kuralları

Bu proje, iş ilanlarını tarayıp adayın CV'sine göre LLM ile puanlayan, uygun ilanlar için ön yazı
hazırlayan ve Telegram'dan bildiren bir Python 3.11+ aracıdır. Bu dosyadaki kurallar her oturumda geçerlidir.

## Proje yapısı

- `profile/cv.md`, `profile/preferences.md` — adayın CV'si ve tercihleri (puanlamanın kaynağı).
  `preferences.md` sonundaki ```yaml bloğu makine tarafından okunur (`src/config.py`); bozma.
- `src/` — kod (`main.py` pipeline, `scrapers/`, `ai/providers.py`, `scorer.py`, `cover_letter.py`,
  `filter.py`, `notify.py`, `report.py`). `tests/` — pytest testleri.
- `data/jobs.db` — görülen ilanlar (SQLite). `output/YYYY-MM-DD/` — rapor, ön yazılar, dry-run çıktıları.

## Tarih kuralı (en önemli kural)

Yalnızca **son 24 saatte** (bugün ve dün) yayınlanan ilanlar işlenir. Üç katmanlı kontrol:

1. **URL tarih filtresi (scraper):** Sitenin "son 24 saat" parametresi arama URL'ine eklenir.
2. **Göreli tarih ayrıştırma:** "Bugün", "Dün", "3 saat önce", "2 gün önce" gibi metinler
   `src/dateparse.py` ile tarihe çevrilir; dünden eski ilanlar elenir. Tarihi anlaşılamayan ilan
   elenmez, `date_unknown` olarak işaretlenir.
3. **first_seen DB dedupe:** Her ilan `kaynak:id` anahtarıyla `data/jobs.db`'ye yazılır; daha önce
   görülen ilan bir daha işlenmez/bildirilmez.

## Puan eşikleri

- Puan 0-100 tam sayı. Eşikler `preferences.md` yaml bloğundan gelir:
  - `< 50` (`min_score_notify`): bildirme, sadece rapora yaz.
  - `50-69`: yalnızca Telegram bildirimi (🟡).
  - `>= 70` (`min_score_cover_letter`): bildirim (🟢) + ön yazı.
- Kesin eleme kriteri (junior, Java-ağırlıklı, saf frontend/mobil, uygun olmayan lokasyon) → en fazla 20.
- Başlıkta hariç tutulan kelimeler LLM'e gitmeden elenir; eşleşme tam kelimedir ("java" ≠ "JavaScript").

## Ön yazı dil kuralı

- Ön yazı **ilanın dilinde** yazılır: Türkçe ilan → Türkçe, İngilizce ilan → İngilizce.
- 200-280 kelime; güçlü (strong) model kullanılır.
- **CV'de olmayan deneyim, rakam, sertifika veya teknoloji asla uydurulmaz.**
- Her dosyanın başında "Göndermeden önce oku ve kendi cümlelerinle düzelt." uyarısı bulunur.
  Ön yazılar otomatik gönderilmez; aday okuyup düzeltir.

## Zamanlama (GitHub Actions)

- `.github/workflows/daily.yml`: her gün 08:30 (İstanbul) çalışır, elle `dry_run` ile tetiklenebilir.
- Secrets: `GROQ_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CV_MD`.
  Variables: `TELEGRAM_ENABLED` (varsayılan false), `AI_PROVIDERS`.
- `data/jobs.db` çalıştırmalar arasında `actions/cache` ile taşınır; `output/` 14 gün artifact olarak saklanır.

## Kaynaklar

- Birincil kaynak: **kariyer.net** (`src/scrapers/kariyernet.py`). Tarih URL parametresi henüz bilinmiyor:
  tarayıcıdan bulununca `DATE_PARAMS` sözlüğüne ekle (katman 1). Detay sayfası yalnızca yeni ve AI
  açıkken, en fazla `max_details` (40) ilan için çekilir. Yeni kaynak eklemek için
  `BaseScraper`'dan türet ve `src/scrapers/__init__.py` içindeki `SCRAPERS`'a kaydet.
- **LinkedIn'e giriş yapılmış (logged-in) hesapla scraping YAPILMAZ.** Hesap kapatılma riski ve
  kullanım koşulları nedeniyle; yalnızca herkese açık sayfalar/RSS/resmi API düşünülebilir.

## Gizli bilgiler

- API anahtarları ve Telegram token'ı yalnızca `.env` dosyasındadır (`.env.example` şablondur).
- `.env`, `data/jobs.db`, `output/` asla commit edilmez; anahtarlar koda, loglara veya teste yazılmaz.
- **CV gizliliği:** `CV_MD` (düz metin) veya `CV_MD_B64` (base64) ortam değişkeni ayarlıysa CV
  `profile/cv.md` yerine oradan okunur (`Config.read_cv()`). Repo public olacaksa `cv.md`'yi repodan
  çıkar ve GitHub Actions'ta `CV_MD` secret'ını kullan. Yerelde `profile/cv.md` kullanılmaya devam eder.
- LLM sağlayıcıları: `AI_PROVIDERS` sırasıyla denenir (Groq → Gemini; opsiyonel xAI Grok). Biri hata
  verirse (HTTP hata, timeout, 429) sıradakine geçilir. SDK yok, düz `requests` kullanılır.

## Nazik tarama (polite crawling)

- Gerçekçi User-Agent, `Accept-Language: tr-TR`; istekler arasında rastgele 2-5 sn bekleme.
- Timeout ve sınırlı yeniden deneme; 429/5xx'te geri çekil. Sayfa sayısını düşük tut (`max_pages`).
- robots.txt ve sitenin kullanım koşullarına saygı göster; gereksiz tekrar istek atma.

## Çalışma şekli (adım adım)

1. Değişikliğe başlamadan önce ilgili modülü ve testlerini oku; küçük, odaklı adımlarla ilerle.
2. Her adımda testleri yaz/güncelle ve çalıştır: `python3 -m pytest -q` (yeşil olmadan ilerleme).
3. Testler ağa çıkmaz: HTTP çağrıları mock'lanır, veritabanı/çıktı için `tmp_path` kullanılır;
   gerçek `data/` ve `output/` klasörlerine test yazmaz.
4. Uçtan uca deneme: `python3 -m src.main --dry-run --no-ai` (Telegram'a gönderim yok, DB'ye kalıcı yazma yok).
   Kaydedilmiş HTML ile çevrimdışı: `--sample-html tests/fixtures/kariyernet_list.html --print 5`
   (ilk 5 ilanı ekrana tablo olarak basar). Gerçek çalıştırma: `python3 -m src.main`.
   `tests/fixtures/kariyernet_*.html` SENTETİKTİR; gerçek sayfa kaydedilince onunla değiştir.
5. `profile/` dosyalarını kullanıcı onayı olmadan değiştirme. Yeni bağımlılık eklemeden önce sor
   (izinli: requests, beautifulsoup4, lxml, python-dotenv, pytest + standart kütüphane).
6. Bitirince kısa özet: ne değişti, test sonucu, açık kalan konular.
