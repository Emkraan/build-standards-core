"""web-shell-manifest.md: standards/schemas/console.module.schema.json accepts the manifest shape a
multi-module shell reads and rejects what its validator rejects. CI has no jsonschema package, so this
file carries a small validator for the keywords the schema uses, and fails on a keyword it does not know."""

import json
import re
import unittest

from support import ROOT

SCHEMA = ROOT / "standards/schemas/console.module.schema.json"
FIXTURES = ROOT / "tests/fixtures/console-module"
HANDLED = {
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "title",
    "description",
    "default",
    "type",
    "required",
    "properties",
    "items",
    "enum",
    "const",
    "pattern",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "dependentSchemas",
    "if",
    "then",
    "else",
    "not",
}


def check(schema, value, root, path="$"):
    """Return a list of problem strings; empty when value satisfies schema."""
    out = []
    unknown = set(schema) - HANDLED
    if unknown:
        raise AssertionError(f"{path}: schema keyword not handled by this test: {sorted(unknown)}")
    if "$ref" in schema:
        out += check(resolve(root, schema["$ref"]), value, root, path)
    if "type" in schema:
        t = schema["type"]
        ok = {
            "string": isinstance(value, str),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "integer": isinstance(value, int) and not isinstance(value, bool),
        }[t]
        if not ok:
            return out + [f"{path}: not a {t}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: not one of {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: not {schema['const']!r}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: does not match {schema['pattern']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                out += check(schema["items"], v, root, f"{path}[{i}]")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                out.append(f"{path}: missing {k}")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                out += check(sub, value[k], root, f"{path}.{k}")
        for k, sub in schema.get("dependentSchemas", {}).items():
            if k in value:
                out += check(sub, value, root, path)
        if "if" in schema:
            branch = "then" if not check(schema["if"], value, root, path) else "else"
            if branch in schema:
                out += check(schema[branch], value, root, path)
    if "not" in schema and not check(schema["not"], value, root, path):
        out.append(f"{path}: matches a forbidden form")
    return out


def resolve(root, ref):
    node = root
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


class ConsoleModuleSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA.read_text())

    def problems(self, manifest):
        return check(self.schema, manifest, self.schema)

    def load(self, name):
        return json.loads((FIXTURES / name).read_text())

    def test_schema_is_ascii_and_declares_the_dialect(self):
        text = SCHEMA.read_text()
        text.encode("ascii")
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertNotIn(
            "additionalProperties", json.dumps(self.schema), "unknown keys must be allowed"
        )

    def test_the_fixtures_are_valid(self):
        files = sorted(FIXTURES.glob("*.module.json"))
        self.assertEqual(len(files), 3)
        for f in files:
            with self.subTest(f.name):
                self.assertEqual(self.problems(json.loads(f.read_text())), [])

    def test_every_description_pattern_compiles(self):
        def walk(o):
            if isinstance(o, dict):
                if "pattern" in o:
                    re.compile(o["pattern"])
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(self.schema)

    def test_unknown_keys_pass_at_every_level(self):
        m = self.load("alerts.module.json")
        m["x-other"] = 1
        m["api"]["x-api"] = True
        m["pages"][0]["x-page"] = "a"
        m["home"]["x-home"] = []
        self.assertEqual(self.problems(m), [])

    def test_required_keys(self):
        for key in self.schema["required"]:
            with self.subTest(key):
                m = self.load("alerts.module.json")
                del m[key]
                self.assertTrue(self.problems(m))

    def test_rejected_mutations(self):
        def edit(fn):
            m = self.load("alerts.module.json")
            fn(m)
            return m

        cases = {
            "bad id": lambda m: m.update(id="Alerts"),
            "short id": lambda m: m.update(id="a"),
            "bad accent": lambda m: m.update(accent="pink"),
            "bad icon": lambda m: m.update(icon="megaphone"),
            "negative order": lambda m: m.update(order=-1),
            "wrong client": lambda m: m.update(client="packages/x"),
            "non ASCII name": lambda m: m.update(name="Caf" + chr(0xE9)),
            "angle bracket in description": lambda m: m.update(description="a <b> c"),
            "padded description": lambda m: m.update(description=" lead"),
            "empty requires": lambda m: m["pages"][0].update(requires=[]),
            "bad hue": lambda m: m["pages"][0].update(hue="pink"),
            "bad permission id": lambda m: m["pages"][0].update(requires=["alerts"]),
            "http link": lambda m: m["links"][0].update(href="http://status.example.com/"),
            "rail link without group": lambda m: m["links"][0].update(slot="rail"),
            "link with no slot and no group": lambda m: m["links"][0].pop("slot"),
            "bad feed block": lambda m: m["home"]["feeds"][0].update(block="side"),
            "five home actions": lambda m: m["home"].update(actions=m["home"]["actions"] * 5),
            "long action label": lambda m: m["home"]["actions"][0].update(label="x" * 41),
            "double slash feed path": lambda m: m["home"]["feeds"][0].update(path="/a//b"),
            "http changelog": lambda m: m.update(
                whatsnew={"path": "/w", "changelog": "http://x.example.com"}
            ),
            "peer id on a tile": lambda m: m.update(
                tiles=[
                    {
                        "key": "t",
                        "dashboard": "home",
                        "label": "T",
                        "permission": "fleet/tab:x",
                        "order": 1,
                    }
                ]
            ),
            "permissionSource on another shape": lambda m: m["rbac"].update(
                permissionSource="console"
            ),
            "missing groups": lambda m: m.pop("groups"),
            "bad rbac shape": lambda m: m["rbac"].update(shape="other"),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertTrue(self.problems(edit(fn)), f"{name} must be rejected")

    def test_permission_source_needs_console_shape(self):
        m = self.load("fleet.module.json")
        self.assertEqual(self.problems(m), [])
        m["rbac"]["shape"] = "hub"
        self.assertTrue(self.problems(m))

    def test_description_is_optional(self):
        m = self.load("alerts.module.json")
        self.assertNotIn("description", m)
        self.assertEqual(self.problems(m), [])


if __name__ == "__main__":
    unittest.main()
