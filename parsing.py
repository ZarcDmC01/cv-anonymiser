"""Lecture du contenu des CV (PDF, DOCX, TXT/MD) + découpage en chunks."""
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document

from config import CHUNK_CHARS
from ollama_client import vision_ocr

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"}


def _page_png(page, max_side: int = 1600) -> bytes:
    """Rend une page en PNG, côté max borné : les scans en très grand format feraient planter le modèle vision."""
    zoom = min(150 / 72, max_side / max(page.rect.width, page.rect.height))
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


def _pdf_text(path: Path) -> str:
    parts = []
    with fitz.open(path) as pdf:
        for page in pdf:
            # pas de sort=True : il entrelace les colonnes des CV en 2 colonnes
            text = page.get_text("text")
            if len(text.strip()) < 30:  # page scannée -> Tesseract si dispo, sinon modèle vision
                try:
                    text = page.get_textpage_ocr(language="fra+eng", full=True).extractText()
                except Exception:
                    pass
            if len(text.strip()) < 30:
                text = vision_ocr(_page_png(page))
            parts.append(text)
    return "\n".join(parts)


def _docx_text(path: Path) -> str:
    doc = Document(path)
    lines = [p.text for p in doc.paragraphs]
    # Les CV en 2 colonnes sont souvent des tableaux
    for table in doc.tables:
        for row in table.rows:
            seen = set()
            for cell in row.cells:
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                lines.extend(p.text for p in cell.paragraphs)
    return "\n".join(lines)


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        text = _pdf_text(path)
    elif ext == ".docx":
        text = _docx_text(path)
    elif ext in (".png", ".jpg", ".jpeg"):
        with fitz.open(path) as img:  # PyMuPDF ouvre aussi les images ; on borne la taille
            text = vision_ocr(_page_png(img[0]))
    elif ext in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError(f"Format non supporté : {ext} (acceptés : {', '.join(sorted(SUPPORTED))})")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text.strip()) < 30:
        raise ValueError("Aucun texte lisible (PDF scanné ? installe Tesseract pour l'OCR).")
    return text


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Découpe sur les lignes vides en paquets <= max_chars (un CV tient souvent en 1 chunk)."""
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], ""
    for block in text.split("\n\n"):
        if current and len(current) + len(block) + 2 > max_chars:
            chunks.append(current)
            current = ""
        while len(block) > max_chars:  # bloc géant sans ligne vide
            chunks.append(block[:max_chars])
            block = block[max_chars:]
        current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks
