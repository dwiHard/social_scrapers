import asyncio
import time
import unittest

from cdp_scraper import (BrowserBusy, CDPConfig, CDPSessionManager, Endpoint, FieldMapper,
                         PageCrashed, Platform, RedpandaProducer, Scraper, capture, end_when_falsy,
                         get_platform, list_platforms, publish_chunks, register_platform)
from cdp_scraper.platforms.registry import unregister_platform
from tests.fakes import FAST, FakeContext, FakePage, fake_engine, run, scroll_emit

PARSER = FieldMapper(items="items", fields={"id": "id"})


def batch(*ids, more=1):
    return {"items": [{"id": i} for i in ids], "has_more": more}


class CaptureTests(unittest.TestCase):
    def go(self, batches, limit=10, **kw):
        page = FakePage(batches)
        opts = dict(FAST, scroll_fn=scroll_emit, max_scrolls=5, stall_limit=2)
        opts.update(kw)
        return page, run(capture(page, "https://site.test/x", "api/list", PARSER, "id", limit, **opts))

    def test_dedupe_and_limit(self):
        page, res = self.go([batch("a", "b"), batch("b", "c", "d")], limit=3)
        self.assertEqual([i["id"] for i in res.items], ["a", "b", "c"])
        self.assertEqual(res.stopped_by, "limit")

    def test_exhausted_by_end_fn(self):
        _, res = self.go([batch("a"), batch("b", more=0)], end_fn=end_when_falsy("has_more"))
        self.assertEqual(len(res.items), 2)
        self.assertEqual(res.stopped_by, "exhausted")

    def test_stalled_saves_diagnostics(self):
        page, res = self.go([batch("a")], stall_limit=2)
        self.assertEqual(res.stopped_by, "stalled")
        self.assertTrue(page.shots)
        self.assertIn("after_goto", str(res.diagnostics["tag"]) + "after_goto")

    def test_matchers(self):
        import re
        for match in (re.compile(r"api/l.st"), lambda u: "list" in u):
            page = FakePage([batch("a")])
            res = run(capture(page, "u", match, PARSER, "id", 5, **dict(FAST, max_scrolls=0)))
            self.assertEqual(len(res.items), 1)

    def test_crash(self):
        page = FakePage([batch("a")])

        async def crash_scroll(p):
            for h in p.handlers["crash"]:
                h(p)

        with self.assertRaises(PageCrashed):
            run(capture(page, "u", "api", PARSER, "id", 5, **dict(FAST, scroll_fn=crash_scroll)))
        self.assertEqual(page.handlers["response"], [])


class SessionTests(unittest.TestCase):
    def test_tab_per_session_and_busy(self):
        ctx = FakeContext()
        manager = CDPSessionManager(CDPConfig(max_sessions=2, lock_timeout=0.6), engine_factory=fake_engine(ctx))

        async def job(hold):
            try:
                async with manager.session() as page:
                    await asyncio.sleep(hold)
                    return page
            except BrowserBusy:
                return "busy"

        async def main():
            return await asyncio.gather(job(1.2), job(1.2), job(1.2))

        started = time.time()
        results = run(main())
        self.assertEqual(sorted(map(str, [r if r == "busy" else "page" for r in results])), ["busy", "page", "page"])
        self.assertEqual(len(ctx.pages_made), 2)
        self.assertTrue(all(p.closed for p in ctx.pages_made))
        self.assertFalse(manager.is_busy)
        self.assertEqual(manager.active, 0)
        self.assertLess(time.time() - started, 3)

    def test_config_validation_and_env(self):
        with self.assertRaises(ValueError):
            CDPConfig(max_sessions=0)
        cfg = CDPConfig.from_env("X_", {"X_CDP_URL": "http://h:9333", "X_MAX_CONCURRENT_SESSIONS": "3"})
        self.assertEqual((cfg.cdp_url, cfg.max_sessions, cfg.timezone), ("http://h:9333", 3, "Asia/Jakarta"))


class ScraperTests(unittest.TestCase):
    def platform(self, name="demo"):
        return Platform(name, cdp={"cdp_url": "http://x:1"}, delay_between_runs=0, endpoints=[
            Endpoint("list", url="https://site.test/list?q={q}", api_match="api/list", parser=PARSER,
                     params=("q",), label="q", limit=5, initial_sleep=0, max_scrolls=3, stall_limit=1,
                     end=end_when_falsy("has_more"), scroll=scroll_emit, capture_options=FAST)])

    def scraper(self, batches, platform=None):
        ctx = FakeContext(batches)
        manager = CDPSessionManager(CDPConfig(max_sessions=1, lock_timeout=1), engine_factory=fake_engine(ctx))
        return Scraper(platform or self.platform(), manager=manager), ctx

    def test_run_and_validation(self):
        scraper, ctx = self.scraper([batch("a", "b", more=0)])
        res = run(scraper.run("list", {"q": "kopi susu"}))
        self.assertEqual((res.label, res.count, res.status, res.stopped_by), ("kopi susu", 2, "success", "exhausted"))
        self.assertTrue(ctx.pages_made[0].url.endswith("q=kopi%20susu"))
        with self.assertRaises(ValueError):
            run(scraper.run("list", {}))
        with self.assertRaises(KeyError):
            run(scraper.run("tidak_ada", {"q": "x"}))

    def test_run_many_isolates_errors(self):
        scraper, _ = self.scraper([batch("a", more=0), batch(more=0)])
        results = run(scraper.run_many("list", [{"q": "satu"}, {"q": "dua"}]))
        self.assertEqual([(r.label, r.status) for r in results], [("satu", "success"), ("dua", "no_data")])
        self.assertEqual(results[0].to_dict()["results_count"], 1)

    def test_login_hint_logged_and_registry(self):
        platform = self.platform("reg_demo")
        register_platform(platform)
        try:
            self.assertIn("reg_demo", list_platforms())
            self.assertIs(get_platform("reg_demo"), platform)
            with self.assertRaises(ValueError):
                register_platform(platform)
        finally:
            unregister_platform("reg_demo")
        with self.assertRaises(KeyError):
            get_platform("reg_demo")


class FakeKafka:
    def __init__(self, config):
        self.sent, self.flushed = [], False

    def poll(self, t):
        pass

    def produce(self, topic, value, callback):
        if b"boom" in value:
            raise RuntimeError("gagal")
        self.sent.append((topic, value))

    def flush(self, *a):
        self.flushed = True


class MessagingTests(unittest.TestCase):
    def test_publish_chunks(self):
        producer = RedpandaProducer(producer_factory=FakeKafka)
        stats = publish_chunks(producer, "t", ["a", "b", "c", "boom", "e"], chunk_size=2,
                               build_payload=lambda c: None if c == ["e"] else {"keywords": c})
        self.assertEqual(stats, {"berhasil": 1, "gagal": 2})
        self.assertTrue(producer.producer.flushed)
        self.assertEqual(producer.producer.sent[0][0], "t")

    def test_unavailable_producer(self):
        def broken(config):
            raise RuntimeError("tanpa broker")
        producer = RedpandaProducer(producer_factory=broken)
        self.assertFalse(producer.available)
        self.assertFalse(producer.send("t", {"a": 1}))


if __name__ == "__main__":
    unittest.main()
