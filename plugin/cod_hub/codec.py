"""Independently implemented native attachment-index codec.

Format facts were verified against MW4 sharing settings and static native
encode/decode routines. No game code, binary or third-party codec is required.
"""
from dataclasses import dataclass
import re


UINT64_MAX = (1 << 64) - 1
PREFIX_PATTERN = re.compile(r"[A-Z][0-9]{2}\Z")


class CodeError(ValueError):
    """A code cannot be interpreted by the selected format snapshot."""


class UnsupportedVersion(CodeError):
    def __init__(self, actual, expected):
        self.actual = actual
        self.expected = expected
        super().__init__(
            f"This code uses format version {actual}; this catalog supports version {expected}."
        )


@dataclass(frozen=True)
class Slot:
    key: str
    radix: int
    bits: int
    offset: int


@dataclass(frozen=True)
class DecodedCode:
    prefix: str
    indexes: tuple
    low_word: int
    upper_word: int
    version: int
    unknown_bits: int
    canonical_code: str
    input_was_canonical: bool


@dataclass(frozen=True)
class CodecSchema:
    game: str
    version: int
    alphabet: str
    chunk_size: int
    slots: tuple

    def __post_init__(self):
        if (not self.game or not 2 <= len(self.alphabet) <= 256
                or len(set(self.alphabet)) != len(self.alphabet)
                or not self.alphabet.isascii() or not self.alphabet.isalnum()
                or self.alphabet != self.alphabet.upper()):
            raise ValueError("Invalid codec alphabet or game.")
        if type(self.version) is not int or not 0 <= self.version < len(self.alphabet):
            raise ValueError("Invalid format version.")
        if type(self.chunk_size) is not int or not 1 <= self.chunk_size <= 20:
            raise ValueError("Invalid code grouping length.")
        if not 1 <= len(self.slots) <= 17 or len({s.key for s in self.slots}) != len(self.slots):
            raise ValueError("Invalid slot configuration.")
        offset = 0
        for slot in self.slots:
            if (type(slot.radix) is not int or slot.radix <= 0
                    or slot.bits != max(1, (slot.radix - 1).bit_length())
                    or slot.offset != offset):
                raise ValueError("Invalid slot width or offset.")
            offset += slot.bits
        if offset > 127:
            raise ValueError("The native format supports at most 127 packed bits.")

    @classmethod
    def from_dict(cls, data):
        return cls(
            game=data["game"], version=data["native_version"],
            alphabet=data["alphabet"], chunk_size=data["chunk_size"],
            slots=tuple(Slot(s["key"], s["radix"], s["bits"], s["offset"])
                        for s in data["slots"]),
        )

    @property
    def packed_bits(self):
        return sum(slot.bits for slot in self.slots)


class NativeCodec:
    def __init__(self, schema):
        self.schema = schema
        self.digits = {char: value for value, char in enumerate(schema.alphabet)}

    def _encode_word(self, number):
        if number == 0:
            return self.schema.alphabet[0]
        chars = []
        while number:
            number, digit = divmod(number, len(self.schema.alphabet))
            chars.append(self.schema.alphabet[digit])
        return "".join(reversed(chars))

    def _decode_word(self, text):
        number = 0
        for char in text:
            number = number * len(self.schema.alphabet) + self.digits[char]
            if number > UINT64_MAX:
                raise CodeError("The code's packed value exceeds the native 64-bit word.")
        return number

    def _format(self, prefix, low, high, version):
        body = self._encode_word(low) + self.schema.alphabet[high] + self.schema.alphabet[version]
        size = self.schema.chunk_size
        return prefix + "-" + "-".join(body[i:i + size] for i in range(0, len(body), size))

    def decode(self, code):
        if not isinstance(code, str):
            raise CodeError("Paste a native build code as text.")
        text = code.strip().upper()
        if not text.isascii() or len(text) > 160 or len(text) < 6:
            raise CodeError("Paste a native build code such as A01-42J19-BU11.")
        prefix, tail = text[:3], text[3:]
        if not PREFIX_PATTERN.fullmatch(prefix):
            raise CodeError("The code must start with a weapon prefix such as A01.")
        if tail.startswith("-"):
            tail = tail[1:]
        pieces = tail.split("-")
        if any(not piece for piece in pieces):
            raise CodeError("The code contains an empty segment or trailing hyphen.")
        body = "".join(pieces)
        if not 3 <= len(body) <= 127:
            raise CodeError("The encoded body must contain between 3 and 127 characters.")
        if any(char not in self.digits for char in body):
            raise CodeError("The code contains an unsupported character; 0 and O are not used in this catalog.")
        version = self.digits[body[-1]]
        if version != self.schema.version:
            raise UnsupportedVersion(version, self.schema.version)
        low, high = self._decode_word(body[:-2]), self.digits[body[-2]]
        packed = low | (high << 64)
        indexes = tuple((packed >> slot.offset) & ((1 << slot.bits) - 1)
                        for slot in self.schema.slots)
        for slot, index in zip(self.schema.slots, indexes):
            if index >= slot.radix:
                raise CodeError(f"The {slot.key.replace('_', ' ')} index exceeds its configured range.")
        canonical = self._format(prefix, low, high, version)
        return DecodedCode(
            prefix, indexes, low, high, version, packed >> self.schema.packed_bits,
            canonical, text == canonical,
        )

    def encode(self, prefix, indexes):
        if not isinstance(prefix, str) or not PREFIX_PATTERN.fullmatch(prefix.upper()):
            raise CodeError("Choose a weapon prefix such as A01.")
        if len(indexes) != len(self.schema.slots):
            raise CodeError("The attachment selection does not match this catalog's slot layout.")
        packed = 0
        for slot, value in zip(self.schema.slots, indexes):
            if type(value) is not int or not 0 <= value < slot.radix:
                raise CodeError(f"The {slot.key.replace('_', ' ')} index must be between 0 and {slot.radix - 1}.")
            packed |= value << slot.offset
        low, high = packed & UINT64_MAX, packed >> 64
        if high >= len(self.schema.alphabet):
            raise CodeError("The upper word cannot be represented by the native one-character suffix.")
        return self._format(prefix.upper(), low, high, self.schema.version)
