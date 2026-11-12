<div align="center">
  <img src="assets/logo.png" alt="Browser Execution Observer Logo" width="600" />
  
  <br />
  
  [![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
  [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
  
  <h1>Browser Execution Observer</h1>
</div>

Library *core* untuk ekstraksi data lewat browser Chrome (CDP). Satu mesin yang sama dipakai untuk
banyak sosial media: platform baru cukup **dideskripsikan** (URL, pola API, mapping field), tanpa
menulis ulang sesi browser, scroll, capture, maupun parser.

## Instalasi

```bash
pip install beo-mcdp
# opsional: pip install "beo-mcdp[kafka]"  /  "beo-mcdp[patchright]"
```

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

## Menambah platform baru

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

`run()` melempar exception (`PageCrashed`, `BrowserBusy`, `ValueError` untuk parameter salah).
`run_many()` memakai satu tab untuk banyak query dan menjadikan error per-item `status="error"`.
Contoh lengkap TikTok dan X/Twitter ada di `examples/`.

## Mapping parsing (`FieldMapper`)

| Sintaks path | Arti |
|---|---|
| `a.b.c` | nilai bersarang |
| `a[0].b`, `a[-1]` | indeks |
| `a[].b` | semua elemen (hasil list) |
| `a[type=1].b` | elemen yang cocok filter (hasil list) |

Bentuk spec field: `"path"` · `("path", "transform", default)` · `F(path | any_of=[...] | template=... | fn=...,
default=, transform=, required=)` · `const(x)` · `callable(record)`.

Opsi `FieldMapper`: `item_path` (sub-path record di tiap item), `where` / `record_where`
(`{path: nilai | EXISTS | callable}` atau callable), `unwrap` (membuka pembungkus), `items` boleh
list path atau callable.

Transform bawaan: `int float str bool url lower upper strip clean_text username hashtag iso_utc
date_id join first count unique drop_empty` dan `each:<transform>` untuk list. Argumen format tanggal:
`iso_utc:%a %b %d %H:%M:%S %z %Y`. Tambah sendiri: `register_transform("nama", fn)`.

Jika logika terlalu rumit untuk mapping, gunakan `F(fn=...)` atau parser Python biasa
(`parser=` menerima callable apa pun yang mengembalikan list dict).

## Hook & aksi halaman

`prepare` (setelah halaman terbuka) dan `scroll` (tiap putaran) adalah fungsi `async def (page)`.
Bawaan: `make_scroller(...)`, `make_wait_for(selector)`, `close_overlays(page, selectors)`.
`Endpoint.capture_options` meneruskan kwargs tambahan ke `capture` (`poll_interval`, `settle`, dst).

## Konfigurasi browser

```python
from cdp_scraper import CDPConfig, setup_cdp
setup_cdp(cdp_url="http://localhost:9222", max_sessions=2, lock_timeout=60)   # default global
cfg = CDPConfig.from_env("TWITTER_")   # TWITTER_CDP_URL, TWITTER_MAX_CONCURRENT_SESSIONS, ...
```

Setiap request memakai **tab baru sendiri** (ditutup saat selesai) dan dibatasi `max_sessions`
bersamaan per konfigurasi. Konfigurasi yang sama berbagi slot; `cdp_url` berbeda = slot berbeda.
Screenshot debug disimpan di `CDPConfig.debug_dir` (default folder kerja); matikan dengan
`debug_screenshots=False`.

## Logging

Format seragam `[job] Status message: detail`, job = nama platform:

```
[2026-11-10 08:19:38] [INFO] [site] Success message: Capture api/search selesai: 20 data
```

Library hanya memakai logger `cdp_scraper` (tanpa handler). Aktifkan dengan `setup_logging()`
atau injeksi logger sendiri: `setup_cdp(custom_logger=...)`. `get_logger("kafka").error("...")`
untuk log aplikasi dengan format yang sama.

## Kafka / Redpanda

```python
from cdp_scraper import RedpandaProducer, publish_chunks
producer = RedpandaProducer()            # KAFKA_BOOTSTRAP_SERVERS; koneksi dibuat saat dipakai
if producer.available:
    stats = publish_chunks(producer, "topic-x", keywords, chunk_size=2,
                           build_payload=lambda chunk: {"keywords": chunk})
    # {"berhasil": n, "gagal": n}
```
Kontrak sumber data (keyword/akun) ada di `cdp_scraper.utils.database` (`KeywordSource`,
`AccountSource`); implementasinya milik aplikasi.

## Pengujian

```bash
python -m unittest discover -s tests -t .
```
Tes memakai browser palsu, jadi tidak butuh Chrome/Kafka.

## Perubahan dari 0.1.x (breaking)

- Konfigurasi sekarang `CDPConfig` (immutable, per platform); `setup_cdp(...)` tetap ada. Variabel modul `config.CDP_URL` dst dihapus.
- `get_session_slots` dan `PW_ENGINE` dihapus; pakai `CDPSessionManager` / `manager.engine`.
- `BrowserBusy` (subclass `TimeoutError`) menggantikan `TimeoutError` polos.
- `helpers.close_login_modal(page, selectors)` kini wajib diberi selector (tidak ada lagi selector TikTok bawaan).
- `utils`: tidak lagi mengimpor Flask; `extract_challenges` (khusus TikTok) dihapus; `calculate_engagement_rate` menerima `interaction_keys` / `view_key` (default sama dengan perilaku lama).
- `utils.database` kini berupa Protocol; `utils.redpanda_client` tidak lagi membuat producer saat import (gunakan `cdp_scraper.messaging`).
