"""UI lint: the help layer rules. A disabled kit Button gives a reason (UI011), an icon-only control has a
name and a tip (UI012), and a tip written as a literal stays short (UI013)."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lint"))
import ui_lint  # noqa: E402  # pyright: ignore[reportMissingImports]

KIT = "import { Button, IconButton, IconTrash } from '@example/kit';\n"


def findings(source, name="a.tsx"):
    """The (rule, line) pairs ui_lint reports for one source file."""
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "standards-local").mkdir()
    (root / "src").mkdir()
    (root / "src" / name).write_text(source)
    cfg = root / "standards-local" / "ui-lint.json"
    cfg.write_text(json.dumps({"paths": ["src"]}))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ui_lint.main(["--config", str(cfg), "--json"])
    return [(f["rule"], f["line"]) for f in json.loads(out.getvalue())["findings"]]


def rules(source):
    return [rule for rule, _ in findings(source)]


class DisabledWithoutReason(unittest.TestCase):
    def test_flags_a_disabled_kit_button(self):
        self.assertEqual(
            rules(KIT + "const a = <Button disabled={!ok}>Save</Button>;\n"), ["UI011"]
        )

    def test_flags_a_bare_disabled_attribute(self):
        self.assertEqual(rules(KIT + "const a = <Button disabled>Save</Button>;\n"), ["UI011"])

    def test_flags_a_disabled_icon_button(self):
        src = KIT + 'const a = <IconButton label="Remove" icon={<IconTrash />} disabled />;\n'
        self.assertEqual(rules(src), ["UI011"])

    def test_a_reason_clears_it(self):
        src = (
            KIT
            + 'const a = <Button disabled={!ok} disabledReason="Fill in the name.">Save</Button>;\n'
        )
        self.assertEqual(rules(src), [])

    def test_a_reason_without_disabled_is_fine(self):
        src = (
            KIT
            + "const a = <Button disabledReason={ok ? undefined : 'Fill in the name.'}>Save</Button>;\n"
        )
        self.assertEqual(rules(src), [])

    def test_disabled_false_is_not_disabled(self):
        self.assertEqual(rules(KIT + "const a = <Button disabled={false}>Save</Button>;\n"), [])

    def test_loading_explains_itself(self):
        self.assertEqual(rules(KIT + "const a = <Button disabled loading>Saving</Button>;\n"), [])

    def test_a_spread_may_carry_the_reason(self):
        self.assertEqual(rules(KIT + "const a = <Button {...props} disabled>Save</Button>;\n"), [])

    def test_a_multiline_tag_is_read_whole(self):
        src = (
            KIT
            + "const a = (\n  <Button\n    variant='primary'\n    disabled={busy}\n    onClick={() => go('a>b')}\n  >\n    Go\n  </Button>\n);\n"
        )
        self.assertEqual(rules(src), ["UI011"])

    def test_an_import_with_an_alias_counts(self):
        src = "import { Button as KitButton } from '@example/kit';\nconst a = <KitButton disabled>Save</KitButton>;\n"
        self.assertEqual(rules(src), ["UI011"])

    def test_a_multiline_import_counts(self):
        src = "import {\n  Badge,\n  Button,\n} from '@example/kit';\nconst a = <Button disabled>Save</Button>;\n"
        self.assertEqual(rules(src), ["UI011"])

    def test_a_relative_import_is_not_the_kits_button(self):
        src = "import { Button } from './ui/Button';\nconst a = <Button disabled>Save</Button>;\n"
        self.assertEqual(rules(src), [])

    def test_a_component_the_file_declares_is_not_the_kits_button(self):
        src = "function Button(props: object) { return null; }\nconst a = <Button disabled>Save</Button>;\n"
        self.assertEqual(rules(src), [])

    def test_a_native_button_is_not_a_kit_button(self):
        self.assertEqual(rules("const a = <button disabled>Save</button>;\n"), [])


class IconOnlyWithoutName(unittest.TestCase):
    def test_flags_an_icon_button_with_no_name_and_no_tip(self):
        src = KIT + "const a = <button type='button' onClick={go}><IconTrash /></button>;\n"
        self.assertEqual(rules(src), ["UI012"])

    def test_a_name_without_a_tip_is_flagged(self):
        src = (
            KIT
            + "const a = <button type='button' aria-label='Remove' onClick={go}><IconTrash /></button>;\n"
        )
        self.assertEqual(rules(src), ["UI012"])

    def test_a_tip_without_a_name_is_flagged(self):
        src = (
            KIT
            + "const a = <button type='button' data-tip='Remove' onClick={go}><IconTrash /></button>;\n"
        )
        self.assertEqual(rules(src), ["UI012"])

    def test_a_name_and_a_tip_pass(self):
        src = (
            KIT
            + "const a = <button type='button' aria-label='Remove' data-tip='Remove' onClick={go}><IconTrash /></button>;\n"
        )
        self.assertEqual(rules(src), [])

    def test_a_title_counts_as_the_tip(self):
        src = (
            KIT
            + "const a = <button type='button' aria-label='Remove' title='Remove' onClick={go}><IconTrash /></button>;\n"
        )
        self.assertEqual(rules(src), [])

    def test_an_inline_svg_is_an_icon(self):
        src = "const a = <a href='/x' aria-label='Home'><svg viewBox='0 0 8 8'><path d='M0 0h8v8z' /></svg></a>;\n"
        self.assertEqual(rules(src), ["UI012"])

    def test_text_next_to_the_icon_is_a_name(self):
        src = KIT + "const a = <button type='button'><IconTrash /> Remove</button>;\n"
        self.assertEqual(rules(src), [])

    def test_a_kit_button_with_only_an_icon_is_flagged(self):
        src = KIT + "const a = <Button icon={<IconTrash />} aria-label='Remove' onClick={go} />;\n"
        self.assertEqual(rules(src), ["UI012"])

    def test_a_kit_button_with_children_is_fine(self):
        src = KIT + "const a = <Button icon={<IconTrash />} onClick={go}>Remove</Button>;\n"
        self.assertEqual(rules(src), [])

    def test_a_spread_may_carry_both(self):
        src = KIT + "const a = <button type='button' {...props}><IconTrash /></button>;\n"
        self.assertEqual(rules(src), [])


class TipTooLong(unittest.TestCase):
    LONG = (
        "A host pool is a group of session hosts that share one image and one set of settings. " * 3
    )

    def test_flags_a_long_data_tip(self):
        self.assertEqual(rules(f'const a = <span data-tip="{self.LONG}">Pool</span>;\n'), ["UI013"])

    def test_flags_three_sentences(self):
        src = 'const a = <Badge tip="It is on. It is fine. Leave it.">On</Badge>;\n'
        self.assertEqual(rules(src), ["UI013"])

    def test_flags_a_long_reason(self):
        src = KIT + f'const a = <Button disabledReason="{self.LONG}">Go</Button>;\n'
        self.assertEqual(rules(src), ["UI013"])

    def test_one_or_two_short_sentences_pass(self):
        src = 'const a = <span data-tip="A group of session hosts. They share one image.">Pool</span>;\n'
        self.assertEqual(rules(src), [])

    def test_a_dotted_number_is_not_a_sentence_end(self):
        src = 'const a = <span data-tip="Version 1.2.3 of the agent. Updated daily.">v</span>;\n'
        self.assertEqual(rules(src), [])

    def test_a_template_with_values_is_not_measured(self):
        src = "const a = <span data-tip={`Updated ${ago}. ${note}. ${more}.`}>x</span>;\n"
        self.assertEqual(rules(src), [])

    def test_a_braced_literal_is_measured(self):
        src = "const a = <span data-tip={'" + "x" * 201 + "'}>x</span>;\n"
        self.assertEqual(rules(src), ["UI013"])


class Registered(unittest.TestCase):
    def test_every_new_rule_points_at_a_section_that_exists(self):
        doc = (ROOT / "standards" / "web-ui.md").read_text(encoding="utf8")
        for rule in ("UI011", "UI012", "UI013"):
            ref = ui_lint.RULES[rule][1]
            self.assertTrue(ref.startswith("web-ui.md 27."), ref)
            number = ref.rsplit(".", 1)[1]
            self.assertRegex(doc, rf"(?m)^{number}\. ", ref)

    def test_the_kit_source_is_clean(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ui_lint.main([str(ROOT / "kit" / "src")])
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
