"""WeRead (微信读书) book ID encoder."""

from __future__ import annotations

import hashlib
import re

from whats_hot_api.utils.logger import logger


def get_weread_id(book_id: str) -> str | None:
    """
    Encode a WeRead book ID.

    Thanks to @MCBBC and ChatGPT for the original algorithm.
    """
    try:
        # MD5 hash of the book ID
        md5_hex = hashlib.md5(book_id.encode(), usedforsecurity=False).hexdigest()

        # Take the first 3 characters as the initial value
        str_sub = md5_hex[:3]

        # Determine the type of the book ID and convert accordingly
        if re.fullmatch(r"\d*", book_id):
            # Numeric-only ID: split into chunks of 9 and convert to hex
            chunks: list[str] = []
            for i in range(0, len(book_id), 9):
                chunk = book_id[i : i + 9]
                chunks.append(format(int(chunk), "x"))
            fa_type = "3"
            fa_parts = chunks
        else:
            # Mixed ID: convert each character's Unicode code point to hex
            hex_str = "".join(format(ord(c), "x") for c in book_id)
            fa_type = "4"
            fa_parts = [hex_str]

        # Append the type indicator
        str_sub += fa_type

        # Append "2" and the last 2 characters of the hash
        str_sub += "2" + md5_hex[-2:]

        # Process the converted sub-string array
        for i, sub in enumerate(fa_parts):
            sub_length_hex = format(len(sub), "x")
            # Pad to 2 characters if needed
            sub_length_padded = sub_length_hex.zfill(2)
            str_sub += sub_length_padded + sub
            # Add separator 'g' between chunks (not after the last one)
            if i < len(fa_parts) - 1:
                str_sub += "g"

        # Pad to at least 20 characters using hash characters
        if len(str_sub) < 20:
            str_sub += md5_hex[: 20 - len(str_sub)]

        # Final MD5 hash, take first 3 characters
        final_hex = hashlib.md5(str_sub.encode(), usedforsecurity=False).hexdigest()
        str_sub += final_hex[:3]

        return str_sub
    except Exception as exc:
        logger.error(f"Error processing WeRead ID: {exc}")
        return None
