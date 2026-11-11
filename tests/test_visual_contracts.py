"""Check rendered build identity and clipped labels using actual drawing calls."""
from copy import deepcopy
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from cod_hub import cards, catalog, native_artwork

CODE = "A01-42J19-BU11"


def render_with_text(build):
    calls = []
    original = ImageDraw.ImageDraw.text

    def draw_text(draw, xy, text, *args, **kwargs):
        bounds = draw.textbbox(xy, text, font=kwargs.get("font"))
        calls.append({"xy": xy, "text": text, "bounds": bounds,
                      "width": draw.textlength(text, font=kwargs.get("font"))})
        return original(draw, xy, text, *args, **kwargs)

    with patch.object(ImageDraw.ImageDraw, "text", new=draw_text):
        png = cards.render_build_png(build)
    with Image.open(BytesIO(png)) as image:
        assert image.format == "PNG"
        size = image.size
    return calls, size


class BuildVisualContracts(unittest.TestCase):
    def test_long_custom_title_shows_ellipsis_and_weapon_without_clipping(self):
        build = catalog.resolve_build(CODE)
        build["title"] = "M" * 80
        embed = cards.build_embed(build)
        self.assertEqual(embed["title"], build["title"])
        self.assertIn("Kastov 762", embed["description"])
        self.assertIn(CODE, str(embed))
        self.assertIn("Call of Duty / Activision", embed["description"])
        calls, size = render_with_text(build)
        self.assertEqual(size, (1100, 1134))
        title = next(c for c in calls if c["xy"] == (48, 85))
        self.assertTrue(title["text"].endswith("…"))
        self.assertLess(len(title["text"]), len(build["title"]))
        self.assertLessEqual(title["width"], 1004)
        subtitle = next(c["text"] for c in calls if c["xy"] == (48, 137))
        self.assertIn("Kastov 762", subtitle)
        self.assertIn("5 SELECTED ATTACHMENTS", subtitle)
        self.assertIn(CODE, [c["text"] for c in calls])
        for call in calls:
            with self.subTest(text=call["text"]):
                left, top, right, bottom = call["bounds"]
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, size[0])
                self.assertLessEqual(bottom, size[1])

    def test_default_weapon_title_remains_complete_and_not_repeated(self):
        build = catalog.resolve_build(CODE)
        build["title"] = build["weapon"]["name"]
        embed = cards.build_embed(build)
        self.assertEqual(embed["title"], "Kastov 762")
        self.assertNotIn("Kastov 762", embed["description"])
        calls, _ = render_with_text(build)
        self.assertEqual(next(c["text"] for c in calls if c["xy"] == (48, 85)), "Kastov 762")

    def test_fifteen_cell_stress_wraps_and_marks_two_line_truncation(self):
        build = deepcopy(catalog.resolve_build(CODE))
        build["title"] = "Synthetic renderer stress"
        build["attachments"] = (build["attachments"] * 3)[:15]
        build["attachments"][0] = dict(build["attachments"][0], name=(
            "Long attachment title made of several words that exceeds two visible lines"))
        build["attachments"][1] = dict(build["attachments"][1], name="W" * 180)
        calls, size = render_with_text(build)
        self.assertEqual(size, (1100, 1390))
        first_lines = [c for c in calls if c["xy"][0] == 66 and c["xy"][1] in (683, 708)]
        self.assertEqual(len(first_lines), 2)
        self.assertTrue(first_lines[-1]["text"].endswith("…"))
        cell_width = (1100 - 96 - 32) // 3
        labels = [c for c in calls if c["xy"][1] >= 683 and (c["xy"][1] - 683) % 128 in (0, 25)]
        self.assertTrue(labels)
        for call in labels:
            with self.subTest(text=call["text"]):
                self.assertLessEqual(call["width"], cell_width - 36)

    def test_reviewed_build_image_is_composited_with_credit_and_scope(self):
        build = catalog.resolve_build(CODE)
        art = native_artwork.get_art(build["weapon"], build_code=build["code"])
        self.assertIsNotNone(art)
        self.assertEqual(art["kind"], "native_build")
        calls, size = render_with_text(build)
        rendered_text = "\n".join(call["text"] for call in calls)
        self.assertIn("NATIVE ATTACHMENT PREVIEW", rendered_text)
        self.assertIn("Call of Duty / Activision", rendered_text)
        self.assertIn("camos and charms not shown", rendered_text)
        with Image.open(BytesIO(cards.render_build_png(build))) as image:
            pixels = image.crop((76, 306, 1024, 520)).get_flattened_data()
            # A correctly composited weapon contains many shaded pixels beyond
            # its flat panel background; text is outside this image region.
            self.assertGreater(sum(pixel != (25, 39, 53) for pixel in pixels), 10_000)
            self.assertEqual(image.size, size)

    def test_uncovered_or_missing_bundled_art_keeps_text_export(self):
        build = catalog.resolve_build(CODE)
        for patcher in (patch.object(native_artwork, "get_art", return_value=None),
                        patch.object(native_artwork, "image_bytes", return_value=None),
                        patch.object(native_artwork, "image_bytes", return_value=b"damaged WebP")):
            with patcher:
                calls, size = render_with_text(build)
            self.assertEqual(size, (1100, 794))
            self.assertNotIn("NATIVE ATTACHMENT PREVIEW", [call["text"] for call in calls])
            self.assertIn(CODE, [call["text"] for call in calls])

    def test_modified_build_without_reviewed_layout_uses_clear_base_preview(self):
        build = catalog.resolve_build("A09-43QCD-D4HTW-VI11")
        art = native_artwork.get_art(build["weapon"], build_code=build["code"])
        self.assertIsNotNone(art)
        self.assertEqual(art["kind"], "native_base")
        calls, _ = render_with_text(build)
        self.assertIn("NATIVE BASE-WEAPON PREVIEW", [call["text"] for call in calls])


if __name__ == "__main__":
    unittest.main()
