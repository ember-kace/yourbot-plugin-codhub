import unittest

from cod_hub.codec import CodecSchema, NativeCodec, Slot, CodeError, UnsupportedVersion


RADICES = [8, 16, 16, 16, 64, 64, 16, 64, 32, 128, 64, 32, 8, 4, 8]
KEYS = ["apex", "barrel", "stock", "magazine", "night_vision_modifier", "muzzle",
        "rear_grip", "underbarrel", "laser", "optic", "launcher", "ammunition",
        "calibration", "dynamic", "other"]


def codec(version=0):
    slots, offset = [], 0
    for key, radix in zip(KEYS, RADICES):
        bits = (radix - 1).bit_length()
        slots.append(Slot(key, radix, bits, offset))
        offset += bits
    return NativeCodec(CodecSchema("mw4", version, "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ", 5, tuple(slots)))


class NativeCodecTests(unittest.TestCase):
    def test_user_controlled_exports(self):
        cases = [
            ("A01-42J19-BU11", [0, 2, 3, 0, 0, 3, 3, 2, 0, 0, 0, 0, 0, 0, 0]),
            ("A01-A11NP-B11", [0, 2, 3, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0]),
            ("A01-9YGBJ-D11", [0, 2, 3, 0, 0, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0]),
            ("A09-43QCD-D4HTW-VI11", [3, 3, 0, 0, 0, 6, 4, 2, 0, 0, 0, 6, 0, 0, 0]),
        ]
        c = codec()
        for code, expected in cases:
            with self.subTest(code=code):
                decoded = c.decode(code)
                self.assertEqual(list(decoded.indexes), expected)
                self.assertEqual(c.encode(decoded.prefix, expected), code)
                self.assertEqual(decoded.unknown_bits, 0)

    def test_64_bit_boundary_and_upper_word(self):
        c = codec()
        ids = [0] * 15
        ids[13] = 2  # bit 64, not a low-word digit or a separate attachment suffix
        self.assertEqual(c.encode("A01", ids), "A01-121")
        ids[13], ids[14] = 0, 1  # bit 65
        self.assertEqual(c.encode("A01", ids), "A01-131")
        ids[13], ids[14] = 3, 7
        result = c.decode(c.encode("A01", ids))
        self.assertEqual(result.low_word, 1 << 63)
        self.assertEqual(result.upper_word, 15)
        self.assertEqual(list(result.indexes), ids)

    def test_last_character_is_version(self):
        with self.assertRaises(UnsupportedVersion):
            codec().decode("A01-42J19-BU12")
        ids = [0] * 15
        self.assertEqual(codec(1).encode("A01", ids), "A01-112")

    def test_unknown_high_bits_preserved_in_inspection(self):
        result = codec().decode("A01-1Z1")
        self.assertEqual(result.upper_word, 33)
        self.assertEqual(result.unknown_bits, 2)
        self.assertEqual(result.canonical_code, "A01-1Z1")

    def test_all_slot_boundaries(self):
        c = codec()
        for n, radix in enumerate(RADICES):
            for value in (0, 1, radix - 1):
                ids = [0] * 15
                ids[n] = value
                with self.subTest(slot=n, value=value):
                    self.assertEqual(list(c.decode(c.encode("A01", ids)).indexes), ids)
        ids = [r - 1 for r in RADICES]
        self.assertEqual(list(c.decode(c.encode("A01", ids)).indexes), ids)

    def test_invalid_inputs_and_overflow(self):
        c = codec()
        for bad in (None, "", "A01---", "A01-111-", "A01-10O", "A01-11_", "A01-11\n1",
                    "A01-ZZZZZZZZZZZZZ11", "AAA-111", "A01-11"):
            with self.subTest(code=bad), self.assertRaises(CodeError):
                c.decode(bad)
        for value in (-1, 8, True, 1.2):
            ids = [0] * 15
            ids[0] = value
            with self.subTest(value=value), self.assertRaises(CodeError):
                c.encode("A01", ids)

    def test_paste_normalization_preserves_meaning(self):
        result = codec().decode("  a01-42j19bu11  ")
        self.assertEqual(result.canonical_code, "A01-42J19-BU11")
        self.assertFalse(result.input_was_canonical)


if __name__ == "__main__":
    unittest.main()
