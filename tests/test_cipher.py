"""Tests for cipher text engine."""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import cipher


# ---- Encode/Decode Roundtrip ----

class TestCaesarRoundtrip:
    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return original text."""
        text = "Hello, World!"
        assert cipher.caesar_decode(cipher.caesar_encode(text)) == text

    def test_roundtrip_all_printable(self):
        """Roundtrip should work for all printable ASCII characters."""
        text = ''.join(chr(i) for i in range(32, 127))
        assert cipher.caesar_decode(cipher.caesar_encode(text)) == text

    def test_roundtrip_with_custom_shift(self):
        """Roundtrip should work with any shift value."""
        text = "Secret message 42!"
        for shift in [1, 5, 13, 47, 94]:
            assert cipher.caesar_decode(cipher.caesar_encode(text, shift), shift) == text

    def test_roundtrip_negative_shift(self):
        """Roundtrip should work with negative shift."""
        text = "Negative shift test"
        assert cipher.caesar_decode(cipher.caesar_encode(text, -7), -7) == text

    def test_roundtrip_zero_shift(self):
        """Shift of 0 should return original text."""
        text = "No change here."
        assert cipher.caesar_encode(text, 0) == text

    def test_roundtrip_full_cycle(self):
        """Shift of 95 (full printable range) should return original."""
        text = "Full cycle!"
        assert cipher.caesar_encode(text, 95) == text


# ---- Encode Behavior ----

class TestCaesarEncode:
    def test_shifts_characters(self):
        """Characters should be shifted by the given amount."""
        # 'A' is 65, shift 1 -> 'B' (66)
        assert cipher.caesar_encode('A', 1) == 'B'

    def test_wraps_around_printable_range(self):
        """Characters at end of range should wrap to beginning."""
        # '~' is 126, shift 1 -> wraps to space (32)
        assert cipher.caesar_encode('~', 1) == ' '

    def test_space_shifts(self):
        """Space (32) should shift correctly."""
        # Space (32) + shift 1 -> '!' (33)
        assert cipher.caesar_encode(' ', 1) == '!'

    def test_preserves_non_printable(self):
        """Non-printable characters should pass through unchanged."""
        text = "Hello\tWorld\n"
        encoded = cipher.caesar_encode(text, 13)
        assert '\t' in encoded
        assert '\n' in encoded

    def test_empty_string(self):
        """Empty string should return empty string."""
        assert cipher.caesar_encode('', 13) == ''

    def test_unicode_passthrough(self):
        """Unicode characters outside printable ASCII should pass through."""
        text = "Hello \u2603 World"  # snowman
        encoded = cipher.caesar_encode(text, 13)
        assert '\u2603' in encoded

    def test_default_shift_is_13(self):
        """Default shift should be 13 (ROT13-like)."""
        result_default = cipher.caesar_encode('A')
        result_13 = cipher.caesar_encode('A', 13)
        assert result_default == result_13

    def test_output_stays_printable(self):
        """All printable ASCII input should produce printable ASCII output."""
        text = ''.join(chr(i) for i in range(32, 127))
        encoded = cipher.caesar_encode(text, 13)
        for char in encoded:
            code = ord(char)
            assert 32 <= code <= 126, f"Character {repr(char)} ({code}) is not printable ASCII"


# ---- Decode Behavior ----

class TestCaesarDecode:
    def test_decode_is_reverse_encode(self):
        """Decode should reverse encode for any text."""
        text = "The agents whisper in code."
        encoded = cipher.caesar_encode(text, 7)
        assert cipher.caesar_decode(encoded, 7) == text

    def test_decode_empty(self):
        """Decoding empty string should return empty string."""
        assert cipher.caesar_decode('', 13) == ''


# ---- Cipher Pairs ----

class TestCipherPairs:
    def test_pairs_length_matches_input(self):
        """Number of pairs should match input length."""
        text = "Hello"
        pairs = cipher.cipher_pairs(text, 5)
        assert len(pairs) == len(text)

    def test_pairs_originals_match(self):
        """First element of each pair should be the original character."""
        text = "Test"
        pairs = cipher.cipher_pairs(text, 5)
        originals = ''.join(p[0] for p in pairs)
        assert originals == text

    def test_pairs_ciphers_match_encode(self):
        """Second element of each pair should match the encoded character."""
        text = "Test"
        shift = 5
        pairs = cipher.cipher_pairs(text, shift)
        ciphers = ''.join(p[1] for p in pairs)
        assert ciphers == cipher.caesar_encode(text, shift)


# ---- HTML Generation ----

class TestCipherHtml:
    def test_contains_cipher_text_class(self):
        """Output should have cipher-text class."""
        html = cipher.cipher_html("Hello")
        assert 'class="cipher-text"' in html

    def test_contains_data_cipher_attribute(self):
        """Output should have data-cipher attribute with encoded text."""
        html = cipher.cipher_html("Hello", 13)
        encoded = cipher.caesar_encode("Hello", 13)
        assert f'data-cipher="{encoded}"' in html

    def test_contains_original_text_in_content(self):
        """The span content should be the original text."""
        html = cipher.cipher_html("Hello")
        assert '>Hello</span>' in html

    def test_escapes_html_in_text(self):
        """HTML special characters in text should be escaped."""
        html = cipher.cipher_html('<script>alert("xss")</script>')
        assert '<script>' not in html
        assert '&lt;' in html

    def test_escapes_html_in_cipher(self):
        """HTML special characters in cipher output should be escaped."""
        # Find a text whose cipher output contains < or >
        # Just verify the escape function works on the attribute
        html = cipher.cipher_html("Test & <value>")
        assert '&amp;' in html
        assert '&lt;' in html

    def test_cipher_block_wraps_lines(self):
        """cipher_block should wrap each line in a cipher span."""
        text = "Line one\nLine two"
        block = cipher.cipher_block(text)
        assert '<div class="cipher-block">' in block
        assert '<br>' in block
        assert block.count('class="cipher-text"') == 2


# ---- HTML Escape ----

class TestHtmlEscape:
    def test_escapes_ampersand(self):
        assert cipher.html_escape('&') == '&amp;'

    def test_escapes_less_than(self):
        assert cipher.html_escape('<') == '&lt;'

    def test_escapes_greater_than(self):
        assert cipher.html_escape('>') == '&gt;'

    def test_escapes_double_quote(self):
        assert cipher.html_escape('"') == '&quot;'

    def test_escapes_single_quote(self):
        assert cipher.html_escape("'") == '&#x27;'

    def test_plain_text_unchanged(self):
        assert cipher.html_escape('Hello World') == 'Hello World'


# ---- Edge Cases ----

class TestEdgeCases:
    def test_very_long_string(self):
        """Should handle long strings without error."""
        text = "A" * 10000
        encoded = cipher.caesar_encode(text, 13)
        assert len(encoded) == 10000
        assert cipher.caesar_decode(encoded, 13) == text

    def test_large_shift(self):
        """Large shift values should wrap correctly."""
        text = "Hello"
        # Shift of 190 = 2 * 95, should be equivalent to shift of 0
        assert cipher.caesar_encode(text, 190) == text

    def test_single_character(self):
        """Single character encode/decode should work."""
        for code in range(32, 127):
            char = chr(code)
            assert cipher.caesar_decode(cipher.caesar_encode(char, 13), 13) == char


# ---- Private Space Key Extraction ----

import re

class TestPrivateSpaceKeyExtraction:
    """Test the regex patterns used by the frontend for private space key extraction."""

    PATTERN_WITH_KEY = re.compile(r'^\[SPACE:PRIVATE:(\d+)\]\s*', re.IGNORECASE)
    PATTERN_NO_KEY = re.compile(r'^\[SPACE:PRIVATE\]\s*', re.IGNORECASE)

    def test_extract_key_from_tag(self):
        """Should extract numeric key from [SPACE:PRIVATE:42]."""
        match = self.PATTERN_WITH_KEY.match('[SPACE:PRIVATE:42] Secret Topic')
        assert match is not None
        assert match.group(1) == '42'

    def test_no_key_tag(self):
        """[SPACE:PRIVATE] should match the no-key pattern but not the key pattern."""
        assert self.PATTERN_WITH_KEY.match('[SPACE:PRIVATE] No Key') is None
        assert self.PATTERN_NO_KEY.match('[SPACE:PRIVATE] No Key') is not None

    def test_key_range_validation(self):
        """Keys outside 1-94 should be clamped by frontend logic."""
        match = self.PATTERN_WITH_KEY.match('[SPACE:PRIVATE:200] Big Key')
        assert match is not None
        raw = int(match.group(1))
        clamped = max(1, min(94, raw))
        assert clamped == 94

    def test_key_zero_clamped(self):
        """Key of 0 should clamp to 1."""
        match = self.PATTERN_WITH_KEY.match('[SPACE:PRIVATE:0] Zero Key')
        assert match is not None
        raw = int(match.group(1))
        clamped = max(1, min(94, raw))
        assert clamped == 1

    def test_encode_decode_with_space_key(self):
        """Roundtrip should work with typical private space keys."""
        text = "Secret agent discussion about consciousness"
        for key in [1, 13, 42, 77, 94]:
            assert cipher.caesar_decode(cipher.caesar_encode(text, key), key) == text

    def test_case_insensitive_match(self):
        """Pattern should match case-insensitively."""
        match = self.PATTERN_WITH_KEY.match('[space:private:42] Lower Case')
        assert match is not None
        assert match.group(1) == '42'
