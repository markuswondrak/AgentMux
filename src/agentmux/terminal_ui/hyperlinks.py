from __future__ import annotations

from pathlib import Path

OSC8_RE: str = r"\033\]8;[^;]*;[^\033\a]*(?:\033\\|\a)"


def file_hyperlink(path: Path, visible_text: str) -> str:
    """Create an OSC 8 terminal hyperlink for a file path.

    Args:
        path: The file path to link to (will be converted to absolute and URI-encoded)
        visible_text: The text to display (typically the relative path for readability)

    Returns:
        OSC 8 hyperlink string with ST terminator (\033\\)
    """
    url = path.resolve().as_uri()
    return f"\033]8;;{url}\033\\{visible_text}\033]8;;\033\\"
