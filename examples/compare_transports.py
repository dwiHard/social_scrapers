"""Bandingkan dua koneksi browser pada endpoint yang sama: kenapa yang satu dapat data lebih sedikit?

Contoh (dari folder proyek tiktok_api):
  python compare_transports.py tiktok_platform:tiktok comments '{"username":"x","aweme_id":"123"}' \
      --a playwright@http://chrome:9222 --b raw@http://anoa:9225 --limit 50

Setiap sisi: <transport>@<cdp_url>. Dicetak: kondisi browser (UA, ukuran viewport, fokus/visible),
jumlah item, statistik jaringan (seen/matched/parse_errors), jumlah scroll dan 8 request pertama.
"""
import argparse
import asyncio
import importlib
import json
import sys

from cdp_scraper import CDPConfig, CDPSessionManager, Scraper

PROBE = """() => ({
    ua: navigator.userAgent, webdriver: navigator.webdriver, lang: navigator.language,
    viewport: [innerWidth, innerHeight], screen: [screen.width, screen.height], dpr: devicePixelRatio,
    visibility: document.visibilityState, hasFocus: document.hasFocus(), url: location.href,
})"""


async def run_side(name, spec, platform, endpoint, params, limit):
    transport, _, cdp_url = spec.partition("@")
    base = platform.cdp or CDPConfig()
    cfg = CDPConfig(**{**base.__dict__, "cdp_url": cdp_url, "transport": transport, "max_sessions": 1})
    manager = CDPSessionManager(cfg)
    out = {"side": name, "spec": spec}
    try:
        async with manager.session() as page:
            out["probe"] = await page.evaluate(PROBE)
    except Exception as e:
        out["probe"] = {"error": str(e)[:200]}
    result = await Scraper(platform, manager=manager).run(endpoint, params, limit=limit)
    net = result.diagnostics.get("network", {})
    out.update(items=result.count, status=result.status, error=result.error, stopped_by=result.stopped_by,
               scrolls=result.diagnostics.get("scrolls"), engine=result.diagnostics.get("engine"),
               network={k: net.get(k) for k in ("seen", "matched", "bad_status", "parse_errors")},
               requests=net.get("requests", [])[:8])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", help="module:attribute, mis. tiktok_platform:tiktok")
    ap.add_argument("endpoint")
    ap.add_argument("params", nargs="?", default="{}")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    sys.path.insert(0, ".")
    module, _, attr = args.platform.partition(":")
    platform = getattr(importlib.import_module(module), attr)
    params = json.loads(args.params)

    async def go():
        return [await run_side(n, s, platform, args.endpoint, params, args.limit)
                for n, s in (("A", args.a), ("B", args.b))]
    for r in asyncio.run(go()):
        print(f"\n=== {r['side']}  {r['spec']} ===")
        print(json.dumps({k: v for k, v in r.items() if k not in ("side", "spec", "requests")},
                         indent=2, ensure_ascii=False))
        for q in r["requests"]:
            print("  ", q)


if __name__ == "__main__":
    main()
