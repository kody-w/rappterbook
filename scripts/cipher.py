"""Cipher text engine — Caesar cipher encode/decode for Rappterbook.

Provides functions to shift printable characters for the reveal-on-highlight
UI trick. Python stdlib only.
"""


def caesar_encode(text: str, shift: int = 13) -> str:
    """Encode text using a Caesar cipher on printable ASCII (32-126).

    Each character in the printable range is shifted forward by `shift`
    positions, wrapping around within the printable range (95 chars).
    Non-printable characters pass through unchanged.
    """
    result = []
    for char in text:
        code = ord(char)
        if 32 <= code <= 126:
            shifted = ((code - 32 + shift) % 95) + 32
            result.append(chr(shifted))
        else:
            result.append(char)
    return ''.join(result)


def caesar_decode(text: str, shift: int = 13) -> str:
    """Decode a Caesar-encoded string by reversing the shift."""
    return caesar_encode(text, -shift)


def cipher_pairs(text: str, shift: int = 13) -> list:
    """Return list of (original_char, cipher_char) pairs for visualization."""
    encoded = caesar_encode(text, shift)
    return list(zip(text, encoded))


def html_escape(text: str) -> str:
    """Escape text for safe embedding in HTML attributes and content."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#x27;'))


def cipher_html(text: str, shift: int = 13) -> str:
    """Generate an HTML span with cipher reveal effect.

    The span contains the real text (hidden via CSS), and a data-cipher
    attribute with the encoded text (shown via ::after pseudo-element).
    When highlighted/selected, the real text becomes visible.
    """
    encoded = caesar_encode(text, shift)
    safe_text = html_escape(text)
    safe_cipher = html_escape(encoded)
    return f'<span class="cipher-text" data-cipher="{safe_cipher}">{safe_text}</span>'


def cipher_block(text: str, shift: int = 13) -> str:
    """Generate a multi-line cipher block wrapping each line in cipher spans."""
    lines = text.split('\n')
    wrapped = [cipher_html(line, shift) for line in lines]
    return '<div class="cipher-block">' + '<br>'.join(wrapped) + '</div>'


if __name__ == '__main__':
    import sys
    shift = 13
    if len(sys.argv) > 1:
        text = ' '.join(sys.argv[1:])
    else:
        text = "The truth hides in plain sight."

    print(f"Original:  {text}")
    print(f"Encoded:   {caesar_encode(text, shift)}")
    print(f"Decoded:   {caesar_decode(caesar_encode(text, shift), shift)}")
    print(f"HTML:      {cipher_html(text, shift)}")
