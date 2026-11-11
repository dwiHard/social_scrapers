import unittest

from cdp_scraper import EXISTS, F, FieldMapper, const, get_path, register_transform
from cdp_scraper.parsing.paths import MISSING, resolve
from cdp_scraper.parsing.transforms import get_transform

DATA = {"a": {"b": [{"k": 1, "v": "x"}, {"k": 2, "v": "y"}, {"k": 1, "v": "z"}]}, "t": True}


class PathTests(unittest.TestCase):
    def test_dotted_and_index(self):
        self.assertEqual(get_path(DATA, "a.b[0].v"), "x")
        self.assertEqual(get_path(DATA, "a.b[-1].v"), "z")
        self.assertIsNone(get_path(DATA, "a.zzz.v"))
        self.assertIs(resolve(DATA, "a.zzz"), MISSING)

    def test_wildcard_and_filter(self):
        self.assertEqual(get_path(DATA, "a.b[].v"), ["x", "y", "z"])
        self.assertEqual(get_path(DATA, "a.b[k=1].v"), ["x", "z"])
        self.assertEqual(get_path(DATA, "nope[k=1].v"), [])

    def test_typed_filter(self):
        data = {"x": [{"t": 1, "v": "a"}, {"t": "1", "v": "b"}, {"t": True, "v": "c"}, {"t": "abc", "v": "d"}]}
        self.assertEqual(get_path(data, "x[t=1].v"), ["a", "c"])
        self.assertEqual(get_path(data, 'x[t="1"].v'), ["b"])
        self.assertEqual(get_path(data, "x[t=abc].v"), ["d"])
        self.assertEqual(get_path({"x": [{"t": None, "v": ""}, {"t": None}]}, "x[].v"), [])

    def test_invalid_token(self):
        with self.assertRaises(ValueError):
            resolve(DATA, "a.b[abc]")


class TransformTests(unittest.TestCase):
    def test_builtin(self):
        self.assertEqual(get_transform("int")("12"), 12)
        self.assertEqual(get_transform("iso_utc")(1700000000), "2023-11-14T22:13:20Z")
        self.assertEqual(get_transform("date_id")(1700000000000), "2023-11-14")
        self.assertIsNone(get_transform("iso_utc")(0))
        self.assertEqual(get_transform("iso_utc:%a %b %d %H:%M:%S %z %Y")("Wed Oct 10 20:19:24 +0000 2018"),
                         "2018-10-10T20:19:24Z")
        self.assertEqual(get_transform("each:url")(["https://a", "x", "http://b"]), ["https://a", "http://b"])
        self.assertEqual(get_transform(["str", "upper"])(5), "5")

    def test_custom_and_unknown(self):
        register_transform("shout", lambda v: str(v).upper() + "!")
        self.assertEqual(get_transform("shout")("hi"), "HI!")
        with self.assertRaises(ValueError):
            get_transform("tidak_ada")


class MapperTests(unittest.TestCase):
    def test_fields_defaults_required_where(self):
        mapper = FieldMapper(
            items="rows", where={"type": 1}, item_path="item", record_where={"id": EXISTS},
            fields={
                "id": F("id", transform="str", required=True),
                "n": ("stats.n", "int", 0),
                "name": F(any_of=["user.nick", "user.name"], default="?"),
                "link": F(template="https://s/{user.name}/{id}"),
                "tags": "tags[].t",
                "flag": const(True),
                "calc": F(fn=lambda r: r["id"] * 2),
            })
        data = {"rows": [
            {"type": 1, "item": {"id": 5, "stats": {"n": "7"}, "user": {"name": "u"}, "tags": [{"t": "a"}, {"t": "b"}]}},
            {"type": 2, "item": {"id": 6}},
            {"type": 1, "item": {"stats": {}}},
            {"type": 1, "item": {}},
            {"type": 1, "item": None},
        ]}
        self.assertEqual(mapper(data), [{"id": "5", "n": 7, "name": "u", "link": "https://s/u/5",
                                         "tags": ["a", "b"], "flag": True, "calc": 10}])

    def test_robust_input_and_item_errors(self):
        mapper = FieldMapper(items="rows", fields={"x": F(fn=lambda r: r["wajib"])})
        self.assertEqual(mapper(None), [])
        self.assertEqual(mapper([1, 2]), [])
        self.assertEqual(mapper({"rows": [{"a": 1}]}), [])

    def test_callable_items_and_unwrap(self):
        mapper = FieldMapper(items=lambda d: d["x"], unwrap=lambda r: r.get("inner"), fields={"v": "v"})
        self.assertEqual(mapper({"x": [{"inner": {"v": 1}}, {"inner": None}]}), [{"v": 1}])


if __name__ == "__main__":
    unittest.main()
