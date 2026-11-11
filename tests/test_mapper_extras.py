import json
import os
import tempfile
import unittest

from cdp_scraper import (F, FieldMapper, const, get_mapper, list_mappers, load_mappers,
                         register_mapper, register_transform)
from cdp_scraper.parsing.registry import unregister_mapper

DATA = {"rows": [{"id": 1, "kind": "a", "n": "5", "tags": [{"t": "x"}, {"t": ""}]},
                 {"id": 2, "kind": "b", "n": 7, "tags": []}]}


def base():
    return FieldMapper(items="rows", where={"kind": "a"}, name="t.base",
                       fields={"id": ("id", "str", ""), "n": ("n", "int", 0), "tags": "tags[].t"})


class ExtendTests(unittest.TestCase):
    def test_extend_adds_overrides_removes(self):
        child = base().extend(fields={"n": F("n", transform="float"), "extra": const(1)}, remove=["tags"], name="t.child")
        self.assertEqual(child(DATA), [{"id": "1", "n": 5.0, "extra": 1}])
        self.assertEqual(base()(DATA), [{"id": "1", "n": 5, "tags": ["x"]}])
        self.assertEqual(child.name, "t.child")

    def test_extend_options(self):
        child = base().extend(where={"kind": "b"})
        self.assertEqual([r["id"] for r in child(DATA)], ["2"])
        self.assertEqual(list(base().fields), ["id", "n", "tags"])


class ConfigTests(unittest.TestCase):
    def test_all_spec_shapes(self):
        mapper = FieldMapper.from_config({
            "name": "t.cfg", "items": "rows", "where": {"id": "$exists"},
            "fields": {
                "a": "id", "b": ["n", "int", 0], "c": {"path": "kind", "transform": "upper"},
                "d": {"template": "k-{kind}"}, "e": {"const": True},
                "f": {"any_of": ["zzz", "kind"], "default": "?"}, "g": {"fn": "json:dumps"},
            }})
        first = mapper(DATA)[0]
        self.assertEqual({k: first[k] for k in "abcdef"}, {"a": 1, "b": 5, "c": "A", "d": "k-a", "e": True, "f": "a"})
        self.assertTrue(first["g"].startswith("{"))

    def test_extends_from_registry_and_register(self):
        register_mapper("t.base", base(), replace=True)
        try:
            mapper = FieldMapper.from_config({"name": "t.ext", "extends": "t.base", "remove": ["tags"],
                                              "fields": {"k": "kind"}}, register=True)
            self.assertEqual(mapper(DATA), [{"id": "1", "n": 5, "k": "a"}])
            self.assertIn("t.ext", list_mappers())
            self.assertIs(get_mapper("t.ext"), mapper)
        finally:
            unregister_mapper("t.base"); unregister_mapper("t.ext")

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            FieldMapper.from_config({"items": "rows", "fields": {}, "typo": 1})
        with self.assertRaises(ValueError):
            FieldMapper.from_config({"fields": {"a": "id"}})
        with self.assertRaises(ValueError):
            FieldMapper.from_config({"items": "rows", "fields": {"a": ["id", "transform_tidak_ada"]}})
        with self.assertRaises(KeyError):
            FieldMapper.from_config({"extends": "tidak.ada"})

    def test_from_json_text_file_and_load_mappers(self):
        text = json.dumps({"name": "t.j", "items": "rows", "fields": {"id": "id"}})
        self.assertEqual(FieldMapper.from_json(text)(DATA), [{"id": 1}, {"id": 2}])
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "1_base.json"), "w") as f:
                f.write(json.dumps({"name": "t.l1", "items": "rows", "fields": {"id": "id"}}))
            with open(os.path.join(d, "2_child.json"), "w") as f:
                f.write(json.dumps({"name": "t.l2", "extends": "t.l1", "fields": {"k": "kind"}}))
            with open(os.path.join(d, "catatan.txt"), "w") as f:
                f.write("bukan json")
            try:
                m1, m2 = load_mappers(d)
                self.assertEqual(m2(DATA)[0], {"id": 1, "k": "a"})
                self.assertEqual(sorted(n for n in list_mappers() if n.startswith("t.l")), ["t.l1", "t.l2"])
            finally:
                unregister_mapper("t.l1"); unregister_mapper("t.l2")


class ReportTests(unittest.TestCase):
    def test_report_flags_wrong_paths(self):
        mapper = FieldMapper(items="rows", name="t.rep", fields={"id": ("id", "str", ""), "salah": ("tidak_ada", "str", "")})
        rep = mapper.report(DATA)
        self.assertEqual(rep["items"], 2)
        self.assertEqual(rep["empty_fields"], ["salah"])
        self.assertEqual(rep["fields"]["id"], {"filled": 2, "empty": 0, "example": "1"})
        text = mapper.explain(DATA)
        self.assertIn("KOSONG salah", text)
        self.assertIn("OK     id", text)


class CustomTransformAndEndpointTests(unittest.TestCase):
    def test_custom_transform_in_json(self):
        register_transform("kali2", lambda v: int(v) * 2)
        mapper = FieldMapper.from_config({"items": "rows", "fields": {"d": ["n", "kali2"]}})
        self.assertEqual(mapper(DATA), [{"d": 10}, {"d": 14}])

    def test_endpoint_parser_by_registered_name(self):
        from cdp_scraper import Endpoint, Platform, Scraper
        from tests.fakes import FAST, FakeContext, FakePage, fake_engine, run, scroll_emit
        from cdp_scraper import CDPConfig, CDPSessionManager
        register_mapper("t.byname", FieldMapper(items="items", fields={"id": "id"}), replace=True)
        try:
            platform = Platform("byname", endpoints=[Endpoint(
                "list", url="https://s.test/{q}", api_match="api/list", parser="t.byname", params=("q",),
                initial_sleep=0, max_scrolls=1, stall_limit=1, scroll=scroll_emit, capture_options=FAST)])

            class Ctx(FakeContext):
                async def new_page(self):
                    return FakePage([{"items": [{"id": "z"}]}], api_url="https://s.test/api/list")
            manager = CDPSessionManager(CDPConfig(), engine_factory=fake_engine(Ctx()))
            res = run(Scraper(platform, manager=manager).run("list", {"q": "a"}))
            self.assertEqual([i["id"] for i in res.items], ["z"])
        finally:
            unregister_mapper("t.byname")


if __name__ == "__main__":
    unittest.main()
