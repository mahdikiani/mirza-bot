"""Extract plain text from .docx files without extra dependencies."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_text(data: bytes) -> str:
    """Return paragraph text from a .docx file."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    parts: list[str] = []
    for node in root.iter(f"{_W_NS}t"):
        if node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return "".join(parts).strip()
