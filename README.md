<div align="center">
  <img src="https://raw.githubusercontent.com/dwiHard/social_scrapers/main/assets/logo.png" alt="Browser Execution Observer Logo" width="600" />
  
  <br />
  
  [![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
  [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
  
  <h1>Browser Execution Observer</h1>
</div>

> **⚠️ PERINGATAN & PENAFIAN (DISCLAIMER):**  
> Library dan kode di dalam repositori ini dibuat semata-mata untuk **tujuan edukasi dan penelitian**. Pengembang (author) **tidak bertanggung jawab** atas segala bentuk penyalahgunaan, kerusakan, pelanggaran *Terms of Service* (ToS) dari platform target, maupun konsekuensi hukum apa pun yang timbul akibat penggunaan kode ini. Gunakan dengan bijak dan patuhi aturan yang berlaku di masing-masing platform.

Library *core* untuk ekstraksi data lewat browser Chrome (CDP). Satu mesin yang sama dipakai untuk banyak sosial media: platform baru cukup **dideskripsikan** (URL, pola API, mapping field), tanpa menulis ulang sesi browser, scroll, capture, maupun parser.

---

## 🚀 Quick Start `cdp_scraper`

Alurnya sangat sederhana: jalankan Chrome yang bisa dikendalikan, login sekali, lalu panggil Scraper dari Python. 

*(Catatan: Kode langkah 3 dan 5 sudah dijalankan dengan browser tiruan dan hasilnya benar, tapi pastikan untuk mengujinya dengan Chrome dan situs sungguhan.)*

### 1. Instalasi

```bash
pip install "beo-mcdp"  # nama paket di requirements kamu; tambah [kafka] kalau pakai Kafka
```

Nama import-nya adalah `cdp_scraper`. Library ini hanya terhubung ke Chrome yang sudah berjalan, jadi **tidak perlu** melakukan `playwright install`.

### 2. Jalankan Chrome dengan remote debugging, lalu login

Jalankan perintah berikut di terminal/command prompt sesuai sistem operasi kamu:

**Linux:**
```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-scraper
```

**macOS:**
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir=$HOME/chrome-scraper
```

**Windows:**
```cmd
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-scraper
```

> **Penting:** Flag `--user-data-dir` wajib digunakan. Chrome versi 136 ke atas mengabaikan `--remote-debugging-port` kalau memakai profil bawaan.

Setelah Chrome terbuka, **login manual** ke situs yang mau di-scrape (TikTok, X, dan seterusnya) sekali saja. Cek koneksinya dengan menjalankan perintah: 
```bash
curl http://localhost:9222/json/version
```

### 3. Scrape pertama

```python
import asyncio
from cdp_scraper import Endpoint, Platform, Scraper, make_scroller, setup_logging
from cdp_scraper.presets import tiktok as _presets   # mendaftarkan mapper tiktok.search, dst

tiktok = Platform("tiktok", endpoints=[Endpoint(
    "search", url="https://www.tiktok.com/search?q={keyword}", api_match="search/general/full",
    parser="tiktok.search", params=("keyword",), label="keyword", limit=20,
    scroll=make_scroller(containers=True, click_pattern="load more"))])

async def main():
    setup_logging()                                    # log berformat: [tiktok] Success message: ...
    results = await Scraper(tiktok).run_many(
        "search", [{"keyword": "kopi"}, {"keyword": "teh"}], limit=20)
    
    for r in results:
        print(r.label, r.status, r.count)              # Output: kopi success 20
    
    print(results[0].items[0])                         # satu dict hasil parsing

asyncio.run(main())
```

Satu `Endpoint` menjelaskan tiga hal: halaman yang dibuka (`url`), response API yang ditangkap (`api_match`), dan cara mengubah JSON jadi data (`parser`).

Tiap `ScrapeResult` berisi field berikut:

| Field | Isi |
| :--- | :--- |
| `status` | `success`, `no_data`, atau `error` |
| `items` dan `count` | List dict hasil parsing dan jumlah itemnya |
| `stopped_by` | Alasan scroll berhenti: `limit`, `exhausted`, `stalled`, atau `max_scrolls` |
| `diagnostics` | Info halaman, berguna kalau hasil kosong |
| `error` | Pesan kalau status error |

*Catatan: `run_many` memakai satu tab untuk beberapa query. Kalau cuma satu query, pakai `Scraper(tiktok).run("search", {"keyword": "kopi"})`. Bedanya, `run` melempar exception sedangkan `run_many` menjadikannya `status="error"` per query.*

### 4. Pakai di Flask

```python
# butuh: pip install "flask[async]"

@app.post("/search")
async def search():                                    
    keywords = (request.get_json() or {}).get("keywords", [])
    results = await asyncio.wait_for(
        Scraper(tiktok).run_many("search", [{"keyword": k} for k in keywords]), timeout=240)
    return jsonify([{"query": r.label, "status": r.status, "data": r.items} for r in results])
```
*Versi lengkapnya (route dinamis untuk semua platform, 404, 400, 429, dan 504) ada di `flask_example.py`.*

### 5. Parsing sendiri (tanpa menulis parser)

```python
from cdp_scraper import F, FieldMapper, const

mapper = FieldMapper(items="result.posts", name="situs.feed", fields={
    "id": ("post_id", "str", ""),                           # format: (path, transform, default)
    "likes": F("metrics.likes", transform="int", default=0),
    "tags": "tags[].label",                                 # semua elemen list
    "platform": const("situs"),
})
print(mapper.explain(sample_json))   # tandai field KOSONG = kemungkinan path salah
```
Lalu pasang sebagai `Endpoint(..., parser=mapper)`. Cara lain (turunan lewat `extend`, mapper dari JSON, transform custom) ada di dokumentasi bagian "Menambah FieldMapper sendiri".

### 6. Konfigurasi

```python
from cdp_scraper import CDPConfig, set_default_config, setup_cdp

setup_cdp(cdp_url="http://localhost:9222", max_sessions=2, lock_timeout=120)
set_default_config(CDPConfig.from_env())   # atau dari env: CDP_URL, MAX_CONCURRENT_SESSIONS, LOCK_WAIT_TIMEOUT, BROWSER_TIMEZONE
```
*Platform yang butuh Chrome sendiri (misalnya X di port lain) cukup diberi parameter `cdp` spesifik: `Platform(..., cdp={"cdp_url": "http://localhost:9223"})`.*

### 7. Kalau Bermasalah (Troubleshooting)

| Gejala | Penyebab dan Solusi |
| :--- | :--- |
| **Gagal terhubung ke CDP** | Chrome belum berjalan dengan `--remote-debugging-port`, atau lupa `--user-data-dir`. Cek cepat dengan `check_cdp('http://localhost:9222')` atau `Scraper(...).health()`. |
| **`no_data`** | Belum login atau terkena captcha, `api_match` tidak cocok, atau path mapping salah. Lihat log `API:`, `diagnostics`, dan screenshot `debug_last.png`. |
| **`BrowserBusy`** | Semua slot terpakai. Naikkan `max_sessions` atau `lock_timeout`. |
| **`cannot import name 'BrowserBusy'`** | Versi lama masih terpasang di venv. Pasang ulang dengan `pip install --force-reinstall --no-cache-dir`. |
| **Hasil error** | Cari baris `[job] Error message: ...` di log. |

*Contoh lengkap ada di folder `examples/` (TikTok, X, mapper custom), dan tesnya jalan dengan `python -m unittest discover -s tests -t .` tanpa butuh Chrome.*

---

## ⚙️ Cara Kerja (How it Works)

Library `beo-mcdp` menggunakan pendekatan **CDP (Chrome DevTools Protocol) Network Interception**. Pendekatan ini membuatnya lebih cepat, bersih, dan tangguh (*anti-break*) dibandingkan teknik *web scraping* berbasis HTML tradisional. 

Berikut adalah alur kerjanya:

1. **Navigasi Halaman (`Endpoint.url`)**  
   Mesin (menggunakan Playwright atau Patchright) akan membuka URL target secara otomatis di latar belakang.
2. **Intersepsi Jalur API (`Endpoint.api_match`)**  
   Alih-alih mencari elemen visual atau membaca kode HTML di layar, library ini bertindak sebagai "penyadap" jaringan. Ia secara diam-diam memonitor lalu lintas data (*network traffic*) dan **mencegat respons API spesifik** yang cocok dengan aturan `api_match` (contoh: `/api/search/item`). Dengan ini, kita mendapatkan data JSON mentah langsung dari sumbernya sebelum halaman web sempat merendernya.
3. **Parsing, Deduplikasi, dan Paginasi (Auto-Scroll)**  
   Setelah data JSON mentah berhasil ditangkap, sistem akan melakukan tiga hal secara otomatis:
   * **Parsing (FieldMapper):** Menyaring data JSON yang rumit dan mengekstrak intisarinya menjadi daftar *dictionary* yang rapi.
   * **Deduplikasi Data:** Memeriksa ID unik (*key*) dari setiap *item*. Data yang terkirim berulang oleh server saat *scroll* akan otomatis dibuang.
   * **Auto-Scroll:** Menggulir halaman ke bawah secara otomatis untuk memicu server memuat data baru. Proses siklus ini terus berjalan sampai target jumlah data (`limit`) terpenuhi atau data di server sudah habis.

---

## 🛠️ Menambah platform baru

```python
from cdp_scraper import (Endpoint, F, FieldMapper, Platform, Scraper,
                         const, make_scroller, register_platform, end_when_falsy)

parser = FieldMapper(
    items="data.posts",                      # path ke list item
    fields={
        "id":    ("id", "str", ""),          # (path, transform, default)
        "url":   F(template="https://site.com/{author.handle}/{id}"),
        "likes": ("stats.likes", "int", 0),
        "tags":  "tags[].name",              # semua elemen
        "posted": F("created", transform="iso_utc"),
        "platform": const("site"),
    },
)

site = Platform(
    name="site",                              # juga jadi label log: [site] ...
    cdp={"cdp_url": "http://localhost:9223"}, # opsional: Chrome/slot terpisah per platform
    overlay_selectors=('div.popup-close',),   # popup yang ditutup otomatis
    login_url_hints=("/login",),              # deteksi browser belum login
    endpoints=[Endpoint(
        "search", url="https://site.com/search?q={keyword}", api_match="api/search",
        parser=parser, params=("keyword",), label="keyword", limit=20, max_limit=50,
        end=end_when_falsy("has_more"),
        scroll=make_scroller(wheel=2500, click_pattern="load more"),
    )],
)
register_platform(site)

result = await Scraper("site").run("search", {"keyword": "kopi"}, limit=30)     # satu query
results = await Scraper("site").run_many("search", [{"keyword": "a"}, {"keyword": "b"}])
```

* `run()` melempar exception (`PageCrashed`, `BrowserBusy`, `ValueError` untuk parameter salah).
* `run_many()` memakai satu tab untuk banyak query dan menjadikan error per-item `status="error"`.

Contoh lengkap TikTok dan X/Twitter ada di `examples/`.

---

## 🗺️ Mapping parsing (`FieldMapper`)

| Sintaks path | Arti |
|---|---|
| `a.b.c` | nilai bersarang |
| `a[0].b`, `a[-1]` | indeks |
| `a[].b` | semua elemen (hasil list) |
| `a[type=1].b` | elemen yang cocok filter (hasil list) |

**Bentuk spec field:** `"path"` · `("path", "transform", default)` · `F(path | any_of=[...] | template=... | fn=..., default=, transform=, required=)` · `const(x)` · `callable(record)`.

**Opsi `FieldMapper`:** `item_path` (sub-path record di tiap item), `where` / `record_where` (`{path: nilai | EXISTS | callable}` atau callable), `unwrap` (membuka pembungkus), `items` boleh list path atau callable.

**Transform bawaan:** `int`, `float`, `str`, `bool`, `url`, `lower`, `upper`, `strip`, `clean_text`, `username`, `hashtag`, `iso_utc`, `date_id`, `join`, `first`, `count`, `unique`, `drop_empty` dan `each:<transform>` untuk list. 
* Argumen format tanggal: `iso_utc:%a %b %d %H:%M:%S %z %Y`. 
* Tambah sendiri: `register_transform("nama", fn)`.

Jika logika terlalu rumit untuk mapping, gunakan `F(fn=...)` atau parser Python biasa (`parser=` menerima callable apa pun yang mengembalikan list dict).

---

## 🧩 Preset siap pakai

Mengimpor modulnya otomatis mendaftarkan mapper dengan nama di bawah, sehingga bisa dipakai sebagai
`Endpoint(parser="nama")`. Semuanya setara dengan parser lama yang dibandingkan lewat tes acak (`tests/test_*parity.py`).

| Modul | Mapper terdaftar |
|---|---|
| `cdp_scraper.presets.tiktok` | `tiktok.search`, `tiktok.user_videos`, `tiktok.comments` |
| `cdp_scraper.presets.twitter` | `twitter.search` |
| `cdp_scraper.presets.instagram` | `instagram.search`, `instagram.comments`, `instagram.user_profile`, `instagram.user_posts`, `instagram.user_timeline` |

**Instagram** memakai satu URL GraphQL untuk banyak query, jadi parsernya berbasis struktur (response yang bukan
miliknya menghasilkan list kosong). Tiga hal yang perlu diatur di `Endpoint`:

```python
from cdp_scraper import Endpoint, Platform
from cdp_scraper.presets import instagram as ig

instagram = Platform("instagram", endpoints=[
    Endpoint("comments", url="https://www.instagram.com/p/{code}/", api_match="graphql/query",
             parser="instagram.comments", key="id", params=("code", "media_id"), label="code",
             end=ig.comments_exhausted,                    # berhenti saat has_next_page=False
             attach_params={"media_id": "media_id"}),      # media_id tidak ada di response, ditempel dari parameter
    Endpoint("user", url="https://www.instagram.com/{username}/", api_match="graphql/query",
             parser="instagram.user_timeline",             # item profil + semua post dalam satu list
             key=ig.item_key, params=("username",), label="username"),   # item profil tidak punya `id`
])
```

Contoh di atas hanyalah kerangka: URL halaman, `api_match`, dan hook scroll untuk Instagram perlu kamu sesuaikan
dan uji pada akun sungguhan. Helper lain: `ig.comments_page_info(data)` (setara return kedua parser lama),
`ig.to_iso` / `ig.to_date`, dan `ig.loads_response_text` (membuang prefix `for (;;);`).
Perbedaan dengan `MediaParser` lama: tidak ada item `{"error": ...}` (hasil kosong = `[]`), serta record kosong
atau post tanpa caption tidak lagi menggagalkan seluruh response.

`Endpoint.attach_params={"field": "nama_param"}` menempelkan nilai parameter ke setiap item hasil; berguna untuk
data konteks yang tidak ada di response API (seperti `media_id` di atas).

## ⚓ Hook & aksi halaman

`prepare` (setelah halaman terbuka) dan `scroll` (tiap putaran) adalah fungsi `async def (page)`.
* Bawaan: `make_scroller(...)`, `make_wait_for(selector)`, `close_overlays(page, selectors)`.
* `Endpoint.capture_options` meneruskan kwargs tambahan ke `capture` (`poll_interval`, `settle`, dst).

---

## ⚙️ Konfigurasi browser

```python
from cdp_scraper import CDPConfig, setup_cdp
setup_cdp(cdp_url="http://localhost:9222", max_sessions=2, lock_timeout=60)   # default global
cfg = CDPConfig.from_env("TWITTER_")   # TWITTER_CDP_URL, TWITTER_MAX_CONCURRENT_SESSIONS, ...
```

Setiap request memakai **tab baru sendiri** (ditutup saat selesai) dan dibatasi `max_sessions` bersamaan per konfigurasi. Konfigurasi yang sama berbagi slot; `cdp_url` berbeda = slot berbeda. Screenshot debug disimpan di `CDPConfig.debug_dir` (default folder kerja); matikan dengan `debug_screenshots=False`.

---

## 🩺 Health check koneksi CDP

Cek apakah sudah terhubung ke server CDP (Chrome remote debugging), tanpa membuka tab:

```python
from cdp_scraper import Scraper, check_cdp

check_cdp("http://localhost:9222")            # sinkron, hanya stdlib: GET /json/version
await Scraper(platform).health()              # + status slot sesi, tidak memblokir event loop
await Scraper(platform).health(deep=True)     # + mencoba koneksi Playwright sungguhan (tanpa tab)
manager.health_sync()                         # versi sinkron untuk route Flask biasa
```

```json
{"connected": true, "cdp_url": "http://localhost:9222", "browser": "Chrome/140.0.7339.0",
 "protocol_version": "1.3", "latency_ms": 4.2, "error": null, "engine": "playwright",
 "sessions": {"active": 1, "max": 2, "busy": false}}
```

`engine` bernilai `null` sampai scraping pertama dijalankan. Kalau gagal: `connected: false` dan `error` berisi alasannya (`Connection refused`, `timeout setelah 3 detik`,
`HTTP 500: Host header ...`, `respons bukan JSON CDP`). Argumen: `timeout` (default 3 detik) dan `tabs=True`
untuk menambahkan jumlah tab terbuka. Pada `deep=True`, kegagalan koneksi Playwright juga membuat
`connected` bernilai `false`. Contoh route health:

```python
@app.get("/health")
async def health():
    report = await Scraper(platform).health()
    return jsonify({"status": "healthy" if report["connected"] else "unhealthy", "cdp": report}), \
        200 if report["connected"] else 503
```

## 📝 Logging

Format seragam `[job] Status message: detail`, job = nama platform:

```text
[2026-11-10 08:19:38] [INFO] [site] Success message: Capture api/search selesai: 20 data
```

Library hanya memakai logger `cdp_scraper` (tanpa handler). Aktifkan dengan `setup_logging()` atau injeksi logger sendiri: `setup_cdp(custom_logger=...)`. `get_logger("kafka").error("...")` untuk log aplikasi dengan format yang sama.

---

## 🐘 Kafka / Redpanda

```python
from cdp_scraper import RedpandaProducer, publish_chunks
producer = RedpandaProducer()            # KAFKA_BOOTSTRAP_SERVERS; koneksi dibuat saat dipakai
if producer.available:
    stats = publish_chunks(producer, "topic-x", keywords, chunk_size=2,
                           build_payload=lambda chunk: {"keywords": chunk})
    # {"berhasil": n, "gagal": n}
```
Kontrak sumber data (keyword/akun) ada di `cdp_scraper.utils.database` (`KeywordSource`, `AccountSource`); implementasinya milik aplikasi.

---

## 🧪 Pengujian

```bash
python -m unittest discover -s tests -t .
```
*(Tes memakai browser palsu, jadi tidak butuh Chrome/Kafka).*
