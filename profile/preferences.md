# İş Arama Tercihleri — Can Tekcan

Bu dosya, ilanları CV'ye göre puanlayan LLM için yazılmıştır. Her ilanı aşağıdaki kurallara göre değerlendir. CV: `profile/cv.md`.

## Aday Özeti

- 10+ yıl deneyimli Senior Backend Developer (C# / .NET, mikroservis).
- Son rol: Odeabank'ta Expert Software Developer & Scrum Master (kurumsal internet bankacılığı, fraud, işlem imzalama).
- Öncesi: Turkcell Technology (.NET Core, MS SQL, MongoDB), Omerd Business Solutions (C#, Dynamics CRM).
- İstanbul, Ataşehir'de (Anadolu yakası) yaşıyor.

## Hedef Roller

Ana hedefler:
- .NET Developer / Senior .NET Developer
- Backend Developer / Senior Backend Developer
- Software Developer / Software Engineer (.NET/C# odaklı)
- Expert / Lead / Principal Software Developer, Tech Lead (.NET)

Kariyer geçişi bonusu:
- AI / LLM / GenAI Developer, AI Engineer, RAG / Agent geliştirici rolleri; **yalnızca** .NET/C# veya Python kullanıyorsa ve backend ağırlığı varsa. Saf araştırma / data scientist / ML research (PhD beklentili) rolleri hedef değildir.

## Anahtar Kelimeler

Güçlü eşleşme: C#, .NET, .NET Core, .NET 6/7/8+, ASP.NET Core, Web API, REST, Entity Framework, LINQ, SQL, MS SQL, PostgreSQL, MongoDB, mikroservis / microservices, dağıtık sistemler, DDD, CQRS, Clean Architecture, Redis, RabbitMQ, Kafka, Elasticsearch, Docker, Kubernetes, CI/CD, GitLab.

Bonus eşleşme: RAG, LLM, GenAI, Semantic Kernel, OpenAI/Azure OpenAI, vektör veritabanı, Python; bankacılık, fintech, ödeme sistemleri, fraud / dolandırıcılık önleme.

## Lokasyon

- **İstanbul:** onsite, hibrit ve remote kabul. Anadolu yakası (Ataşehir, Kadıköy, Ümraniye, Kozyatağı, Üsküdar, Kartal, Maltepe vb.) hafif artı.
- **Remote (tam uzaktan):** her şehir / yurt dışı şirket kabul.
- **Hibrit:** İstanbul içinde kabul.
- **Diğer şehirler:** yalnızca tam remote ise kabul; onsite veya hibrit ise ele.
- Lokasyon belirtilmemişse ele alma, nötr değerlendir.

## Kıdem

- Hedef: Senior / Expert / Uzman / Lead / Kıdemli (10+ yıl deneyim).
- Mid-level (3-5 yıl) ilanlar: elenmez ama puan düşer.
- Deneyim aralığı adayın 10+ yılını kapsıyorsa (ör. "5-14 yıl") uygundur.

## Elenecekler (Kesin Eleme → puan 0-20)

- Junior, Jr., Stajyer, Intern, Yeni mezun, Entry level, Trainee ilanları.
- Java-only veya Java-ağırlıklı roller (Java, Spring, Spring Boot ana teknoloji ise). **Not:** "JavaScript" Java değildir.
- Saf frontend rolleri (React/Angular/Vue developer, UI developer; backend sorumluluğu yoksa).
- Saf mobil roller (iOS, Android, Swift, Kotlin, Flutter, React Native).
- Lokasyon kuralına uymayan ilanlar (İstanbul dışı ve remote değil).
- C#/.NET dışı tek-dil backend roller (yalnızca PHP, Go, Ruby, Node.js vb.) belirgin şekilde düşük puan alır; AI/Python geçiş rolleri istisnadır.

## Artı Puan

- Fintech / bankacılık / ödeme / sigorta sektörü.
- AI / LLM / RAG geçiş fırsatı (.NET veya Python ile).
- Mikroservis, dağıtık sistem, DDD/CQRS mimarisi.
- Remote veya hibrit çalışma modeli.
- Anadolu yakası ofis.
- Lead / mimari sorumluluk, Scrum / ekip liderliği deneyiminin değer göreceği roller.

## Maaş Beklentisi

(doldurulacak)

## Puanlama Kuralları

- Puan aralığı **0-100** (tam sayı).
- **< 50:** bildirme.
- **50-69:** sadece Telegram bildirimi gönder.
- **70+:** bildir ve ön yazı (cover letter) yaz.
- Kesin eleme kriterlerinden biri varsa puan en fazla 20 olur.
- Kısa gerekçe ver: eşleşen anahtar kelimeler, eksikler, lokasyon/çalışma modeli değerlendirmesi.

Önerilen ağırlıklar (rehber niteliğinde):
- Teknoloji eşleşmesi (C#/.NET, SQL, mikroservis vb.): %40
- Rol ve kıdem uyumu: %25
- Lokasyon / çalışma modeli: %15
- Sektör ve bonuslar (fintech, AI/LLM): %20

## Makine Okunabilir Yapılandırma

```yaml
# name: config
search_queries:
  - ".net developer"
  - "senior .net developer"
  - "c# developer"
  - "asp.net core developer"
  - ".net core developer"
  - "backend developer"
  - "senior backend developer"
  - "software engineer .net"
  - "software developer c#"
  - "yazılım uzmanı .net"
  - "kıdemli yazılım geliştirici"
  - "lead software developer"
  - "ai engineer"
  - "llm developer"

# Title matching is lowercase, Turkish-aware (use casefold / tr locale: "I" -> "ı", "İ" -> "i").
# "java" must match as a whole word only: \bjava\b (so "javascript" does NOT match).
# Recommended regex for java: (?<![a-z])java(?![a-z]) — still allow "java/spring".
exclude_title_keywords:
  - "junior"
  - "jr."
  - "jr "
  - "stajyer"
  - "staj"
  - "intern"
  - "internship"
  - "yeni mezun"
  - "entry level"
  - "trainee"
  - "java"        # whole-word only; must NOT match "javascript"
  - "spring boot"
  - "frontend"
  - "front-end"
  - "front end"
  - "ios"
  - "android"
  - "flutter"
  - "react native"
  - "mobile developer"
  - "mobil"

include_locations:
  - "istanbul"
  - "istanbul(asya)"
  - "istanbul(avr.)"
  - "remote"
  - "uzaktan"
  - "uzaktan / remote"
  - "hibrit"       # only valid together with istanbul, unless remote
  - "türkiye"

min_score_notify: 50
min_score_cover_letter: 70
```
