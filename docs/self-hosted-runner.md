# Türk sitelerini kendi bilgisayarından taramak (self-hosted runner)

Kariyer.net, Indeed TR ve Yenibiriş, GitHub'ın sunucularından gelen istekleri bot koruması ile
engelliyor (2026-10-19 denemeleri: "Access to this page has been denied", Cloudflare "Just a moment").
Ev internetinden gelen istekler engellenmez. Bu yüzden aynı günlük iş iki parçaya bölünür:

| Parça | Nerede çalışır | Kaynaklar |
|---|---|---|
| `hunt (cloud)` | GitHub sunucusu | LinkedIn |
| `hunt (local)` | Senin bilgisayarın (runner) | Kariyer.net, Indeed TR, Yenibiriş, Secretcv |

Bilgisayar 10:23'te kapalıysa `local` iş kuyrukta bekler (en fazla 24 saat) ve bilgisayar açılıp
runner bağlanınca çalışır.

## Kurulum (Windows, ~5 dakika)

1. GitHub'da repo → **Settings → Actions → Runners → New self-hosted runner** → **Windows**, **x64**.
2. Sayfadaki komutları **PowerShell**'de sırayla çalıştır (klasör `C:\actions-runner` önerilir).
   `config.cmd` soruları için Enter ile varsayılanları kabul edebilirsin.
3. "Run the runner as a service?" sorusuna **Y** de. Böylece bilgisayar açılınca runner kendiliğinden
   başlar, terminal açık tutman gerekmez.
4. Bilgisayarda **Git for Windows** kurulu olmalı (iş adımları Git Bash ile çalışır):
   <https://git-scm.com/download/win>. Python'u runner kendisi indirir.
5. Repo → **Settings → Secrets and variables → Actions → Variables** → `SELF_HOSTED_RUNNER` = `true`.

## Test

**Actions → Daily job hunt → Run workflow**, `mode` = `dry_run`. İki iş görünür:
`hunt (cloud)` ve `hunt (local)`. `local` işin sayfasındaki **Kaynaklar** notunda Kariyer.net için
`bulunan` sayısı 0'dan büyükse kurulum tamamdır.

## Geri almak

`SELF_HOSTED_RUNNER` değişkenini silince her şey yine sadece GitHub'da çalışır. Runner'ı kaldırmak için
`C:\actions-runner` içinde `config.cmd remove` çalıştır.

## Güvenlik notu

GitHub, public repolarda self-hosted runner için dikkatli olmayı önerir: başkasının açtığı bir pull
request senin bilgisayarında kod çalıştırabilir. Bu workflow sadece zamanlanmış ve elle başlatılan
çalıştırmalarda tetiklenir (`schedule`, `workflow_dispatch`), pull request'lerde çalışmaz; bu yüzden
risk düşük. Bu workflow'a **asla `pull_request` tetikleyicisi ekleme**. Ek güvenlik için
Settings → Actions → General → "Fork pull request workflows" ayarında onay zorunlu kalsın.
