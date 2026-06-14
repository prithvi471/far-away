from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


class UnsupportedDocumentError(RuntimeError):
    pass


@dataclass
class ParsedDocument:
    path: Path
    content_hash: str
    text: str
    metadata: dict[str, str]


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_document(path_value: str | Path) -> ParsedDocument:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".log"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".json":
        text = _json_to_text(path)
    elif suffix == ".docx":
        text = _docx_to_text(path)
    elif suffix == ".pdf":
        text = _pdf_to_text(path)
    else:
        raise UnsupportedDocumentError(f"Unsupported document type: {suffix}")
    return ParsedDocument(
        path=path,
        content_hash=sha256_file(path),
        text=normalize_space(text),
        metadata={"suffix": suffix, "filename": path.name},
    )


def normalize_space(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()


def _json_to_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, indent=2, sort_keys=True)


def _docx_to_text(path: Path) -> str:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", namespace):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def _pdf_to_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise UnsupportedDocumentError("PDF parsing requires optional dependency: pip install pypdf") from exc
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def summarize_text(text: str, max_chars: int = 900) -> str:
    clean = normalize_space(text)
    if len(clean) <= max_chars:
        return clean
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    summary = ""
    for sentence in sentences:
        if len(summary) + len(sentence) + 1 > max_chars:
            break
        summary = f"{summary} {sentence}".strip()
    return summary or clean[:max_chars].rsplit(" ", 1)[0]


def extract_skills(text: str, catalog: list[str]) -> list[str]:
    haystack = f" {text.lower()} "
    found: list[str] = []
    for skill in catalog:
        normalized = skill.strip().lower()
        if not normalized:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack):
            found.append(normalized)
    return sorted(set(found))


def extract_candidate_tasks(text: str) -> list[str]:
    tasks: list[str] = []
    patterns = [
        re.compile(r"^\s*(?:[-*]\s*)?\[[ xX]\]\s*(.+)$"),
        re.compile(r"^\s*(?:[-*]\s*)?(?:TODO|Task|Action|Requirement|REQ)\s*[:\-]\s*(.+)$", re.I),
    ]
    for line in text.splitlines():
        for pattern in patterns:
            match = pattern.match(line)
            if match:
                value = match.group(1).strip()
                if value:
                    tasks.append(value)
                break
    return tasks

