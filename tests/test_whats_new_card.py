"""The What's new / tour card must fit the window: height capped to the viewport, the body scrolling inside it, the
buttons always in view, a sensible width. Source checks on app.css (no browser here: see the PR note)."""
import os
import re
import unittest

CSS = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore",
                        "ui_assets", "app.css")).read()


def rules(selector):
    """Every declaration block whose selector list contains exactly `selector`, joined."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        if selector in [x.strip() for x in m.group(1).split(",")]:
            out.append(m.group(2))
    return " ".join(out)


class TourCardFitsTheWindowTest(unittest.TestCase):
    def test_the_card_is_capped_to_the_viewport_and_lays_out_as_a_column(self):
        card = rules(".tour-card")
        self.assertRegex(card, r"max-height:\s*calc\(100d?vh\s*-\s*\d+px\)")
        self.assertRegex(card, r"display:\s*flex")
        self.assertRegex(card, r"flex-direction:\s*column")

    def test_the_body_scrolls_inside_the_card_and_the_buttons_never_shrink_away(self):
        body = rules(".tour-body")
        self.assertRegex(body, r"overflow-y:\s*auto")
        self.assertRegex(body, r"min-height:\s*0")
        self.assertRegex(rules(".tour-actions"), r"flex:\s*none|flex-shrink:\s*0")

    def test_the_card_is_wide_enough_for_a_long_list_but_never_wider_than_the_window(self):
        m = re.search(r"width:\s*min\((\d+)px,\s*calc\(100vw\s*-\s*(\d+)px\)\)", rules(".tour-card"))
        self.assertTrue(m, rules(".tour-card"))
        self.assertGreaterEqual(int(m.group(1)), 420)
        self.assertLessEqual(int(m.group(1)), 560)

    def test_it_uses_only_theme_variables_so_light_and_dark_both_work(self):
        card = rules(".tour-card")
        self.assertIn("var(--surface)", card)
        self.assertNotRegex(card, r"#[0-9a-fA-F]{3,6}\b")


if __name__ == "__main__":
    unittest.main()
