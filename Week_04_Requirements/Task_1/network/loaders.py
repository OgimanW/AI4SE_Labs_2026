"""Deterministic file loaders and chunking."""
import email
import re
from email import policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from . import config


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(p.strip() for p in parser.parts if p.strip())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_eml(path: Path) -> tuple[str, str | None]:
    """Return text of an email file (headers + plain bodies) and its date (ISO)."""
    raw = path.read_bytes()
    # A file may hold a whole thread of concatenated messages; the parser reads the
    # first header block, the rest stays in the body, which is what we want.
    msg = email.message_from_bytes(raw, policy=policy.default)
    date = None
    if msg["Date"]:
        try:
            date = parsedate_to_datetime(str(msg["Date"])).date().isoformat()
        except (TypeError, ValueError):
            date = None
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Subject", "Date") if msg[h])
    bodies: list[str] = []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        try:
            content = part.get_content()
        except (LookupError, KeyError):
            content = part.get_payload(decode=True).decode("utf-8", errors="replace")
        if ctype == "text/plain":
            bodies.append(content)
        elif ctype == "text/html" and not bodies:
            bodies.append(_html_to_text(content))
    return f"{header}\n\n" + "\n\n".join(bodies), date


def _load_pdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _load_docx(path: Path) -> str:
    import docx
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def load_file(path: Path) -> tuple[str, str | None]:
    """Load any supported file into (text, date-or-None)."""
    ext = path.suffix.lower()
    date = None
    if ext == ".eml":
        text, date = _load_eml(path)
    elif ext == ".pdf":
        text = _load_pdf(path)
    elif ext == ".docx":
        text = _load_docx(path)
    elif ext in (".html", ".htm"):
        text = _html_to_text(_read_text(path))
    else:
        text = _read_text(path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, date


def discover_files(input_dir: Path) -> list[Path]:
    """All supported files below input_dir, sorted by relative path."""
    files = [p for p in input_dir.rglob("*")
             if p.is_file() and p.suffix.lower() in config.SUPPORTED_EXTENSIONS
             and not any(part.startswith(".") for part in p.relative_to(input_dir).parts)]
    return sorted(files, key=lambda p: p.relative_to(input_dir).as_posix().lower())


def chunk_text(text: str, size: int = config.CHUNK_CHARS,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Split at paragraph boundaries into chunks of <= size chars with overlap."""
    if len(text) <= size:
        return [text]
    paragraphs: list[str] = []
    for para in text.split("\n\n"):
        while len(para) > size:            # hard-split oversized paragraphs
            paragraphs.append(para[:size])
            para = para[size - overlap:]
        paragraphs.append(para)
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for para in paragraphs:
        if current and length + len(para) + 2 > size:
            chunks.append("\n\n".join(current))
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(current):  # carry trailing paragraphs as overlap
                if tail_len + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 2
            current, length = tail, tail_len
        current.append(para)
        length += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks
