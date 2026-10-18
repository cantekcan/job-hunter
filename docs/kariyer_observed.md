# Kariyer.net — Raw Observations (2026-10-18, via WebFetch text conversion)

Caveat: WebFetch returns HTML converted to text/markdown. Script tags, attributes and class names are lost. Use this as a guide to the content vocabulary, not the DOM.

## List page: https://www.kariyer.net/is-ilanlari/asp+net+yazilim+muhendisi
- Filter state: "Seçili Filtreler (1)". No results: "Asp.net Yazılım Mühendisi İlanını Bulamadık". Cards shown are "benzer ilanlar".
- Card 1 → https://www.kariyer.net/is-ilani/omuz-omuza-engelsiz-insan-kaynaklari--net-developer-2496842
  text: "Omuz Omuza Engelsiz İnsan Kaynakları .Net Developer … Uzaktan / Remote Tam zamanlı … 2 gün" (plus "accessible" and "update" icon labels)
- Card 2 → https://www.kariyer.net/is-ilani/turkcell-ve-grup-sirketleri--net-lead-developer-4578674
  text: "Turkcell ve Grup Şirketleri .Net Lead Developer Turkcell ve Grup Şirketleri İstanbul (Tümü) Hibrit Tam zamanlı 1 gün"
- Tarih filter options (no hrefs): Tümü · Bugünün ilanları · Son 3 saat · Son 8 saat · Son 3 gün · Son 7 gün · Son 15 gün · İlk kez yayınlananlar
- Other filter groups: Çalışma Tercihi, Sektör, Pozisyon Seviyesi, Departman, Çalışma Şekli, Eğitim Seviyesi, Deneyim Süresi, Engelli İlanı

## List page: https://www.kariyer.net/is-ilanlari/istanbul
- Pagination: /is-ilanlari/istanbul-2 … /is-ilanlari/istanbul-100 ("Sonraki" leads to -2)
- Location sub-slugs: /is-ilanlari/istanbul+avrupa-sisli
- Card hrefs: /is-ilani/vaneda-ayakkabi-san-ve-tic-a-s-magaza-satis-danismani-4580444, /is-ilani/riso-turkey-baski-cozumleri-a-s-bayi-sorumlusu-4580787
- Card prefix "Sponsorlu İlan" on sponsored cards.

## List page: https://www.kariyer.net/is-ilanlari/net+developer (and the root /is-ilanlari)
- Came back as general (unfiltered) listings. Canonical: https://www.kariyer.net/is-ilanlari
- "Şu an 100 sayfa içerisinden 1. sayfadasınız". Pagination on the root list seen as ?cp=2
- Card tail example: "Antalya İş Yerinde Tam zamanlı [update] 1 saat"
- Location suffix example: "+1 il daha". Badge: "Ort. 2 günde dönüyor"

## Detail page: https://www.kariyer.net/is-ilani/turkcell-ve-grup-sirketleri--net-lead-developer-4578674
- H1: ".Net Lead Developer". Company: "Turkcell ve Grup Şirketleri" (linked to /firma-profil/...)
- Location: "İstanbul(Asya), İstanbul(Avr.)". Line: "Hibrit Tam Zamanlı" + "Uzman"
- Department: "Bilgi Teknolojileri / IT". "200+ başvuru". "5 gün önce güncellendi"
- Embedded strings: `lastPublishDate:14.10.2026`, `closingDate:12.11.2026`
- `<title>`/og:title: "Turkcell ve Grup Şirketleri .Net Lead Developer İş İlanı - 14.10.2026"
- Sections: İş İlanı Hakkında · Ne Bekliyoruz? · (role section) · Yan Haklar ve Faydalar · Aday Kriterleri ("5 - 14 yıl arası", "Üniversite(Mezun)") · Şirket Hakkında ("6000+ Çalışan")
- Sidebar: "Bu İlanla Birlikte Görüntülenenler" (related ads; exclude them from parsing)
- No ld+json or __NEXT_DATA__ visible in the converted text.

## Third-party scraper output fields (hints at an internal API)
https://apify.com/powerai/kariyer-jobs-scraper: title, detailPageUrl, company, location, workModel, badge, postedAt, positionId, companyId, jobCode, workType, jobStatus, jobDateStatus, workModelText, workTypeText
