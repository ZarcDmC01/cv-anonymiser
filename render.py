"""Dossier de compétences anonymisé : JSON -> DOCX (python-docx) -> PDF (Word via docx2pdf).

Style calqué sur reference/cv_reference.png : bandeau bordeaux, synthèse en encadré rose,
pastilles de compétences, secteur à la place de l'employeur, ligne « Environnement ».
"""
from datetime import date
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from config import BRAND_COLOR, BRAND_NAME

BRAND = RGBColor.from_string(BRAND_COLOR)
INK = RGBColor(0x1A, 0x1A, 0x1A)
TEXT = RGBColor(0x33, 0x3D, 0x4A)
MUTED = RGBColor(0x6B, 0x72, 0x80)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT = RGBColor(0xF6, 0xD5, 0xDD)

M = 1.8                       # marge latérale du contenu (cm)
RIGHT_TAB = Cm(21 - M)        # tabulation de droite pour les dates


# ── primitives XML ─────────────────────────────────────────
def _shade(el_pr, fill: str):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    el_pr.append(shd)


def _border(pPr, side: str, color: str, sz: str = "4", space: str = "1"):
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        pPr.append(bdr)
    b = OxmlElement(f"w:{side}")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), sz)
    b.set(qn("w:space"), space)
    b.set(qn("w:color"), color)
    bdr.append(b)


def _cell_margins(cell, top=0, bottom=0, left=0, right=0):
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for side, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:w"), str(int(v * 567)))
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    tcPr.append(mar)


def _table(doc, rows, cols, widths_cm, indent_cm=0.0):
    t = doc.add_table(rows=rows, cols=cols)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.allow_autofit = False
    tblPr = t._tbl.tblPr
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), str(int(indent_cm * 567)))
    ind.set(qn("w:type"), "dxa")
    tblPr.append(ind)
    for row in t.rows:
        for c, w in zip(row.cells, widths_cm):
            c.width = Cm(w)
    return t


def _clear(cell):
    for p in list(cell.paragraphs):
        p._element.getparent().remove(p._element)


def _para(container, runs, left=M, right=M, before=0, after=0, align=None, first=None):
    """runs = [(texte, {bold, italic, size, color, fill})]"""
    p = container.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.left_indent, pf.right_indent = Cm(left), Cm(right)
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    if first is not None:
        pf.first_line_indent = Cm(first)
    for text, st in runs:
        r = p.add_run(text)
        r.bold = st.get("bold", False)
        r.italic = st.get("italic", False)
        r.font.size = Pt(st.get("size", 9.5))
        r.font.color.rgb = st.get("color", TEXT)
        if st.get("fill"):
            _shade(r._r.get_or_add_rPr(), st["fill"])
    return p


def _section(doc, title):
    p = _para(doc, [(title.upper(), {"bold": True, "size": 9.5, "color": BRAND})], before=13, after=4)
    _border(p._p.get_or_add_pPr(), "bottom", "D1D5DB")


def _bullet(doc, text):
    _para(doc, [("•  ", {"color": BRAND}), (text, {"size": 9})], left=M + 0.45, first=-0.4, before=1)


# ── document ───────────────────────────────────────────────
def build_docx(d: dict, ref: str, out_path: Path) -> Path:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(0)
    sec.top_margin, sec.bottom_margin = Cm(0), Cm(1.8)
    sec.footer_distance = Cm(0.8)
    doc.styles["Normal"].font.name = "Calibri"
    doc.paragraphs[0]._element.getparent().remove(doc.paragraphs[0]._element) if doc.paragraphs else None

    today = date.today().strftime("%d/%m/%Y")

    # Bandeau
    band = _table(doc, 1, 2, [12.5, 8.5])
    left, right = band.rows[0].cells
    for c in (left, right):
        _shade(c._tc.get_or_add_tcPr(), BRAND_COLOR)
        _cell_margins(c, top=0.7, bottom=0.7)
        _clear(c)
    _para(left, [(BRAND_NAME, {"bold": True, "size": 15, "color": WHITE})], left=M)
    _para(left, [("DOSSIER DE COMPÉTENCES", {"size": 7.5, "color": SOFT})], left=M, before=1)
    _para(right, [("Réf. consultant", {"size": 7.5, "color": SOFT})], right=M, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _para(right, [(ref, {"bold": True, "size": 11, "color": WHITE})], right=M, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _para(right, [(today, {"size": 7.5, "color": SOFT})], right=M, align=WD_ALIGN_PARAGRAPH.RIGHT)

    # Titre
    _para(doc, [(d["titre"] or "Profil consultant", {"bold": True, "size": 17, "color": INK})], before=16, after=2)
    if d["annees_experience"]:
        n = d["annees_experience"]
        _para(doc, [(f"{n} an{'s' if n > 1 else ''} d'expérience", {"bold": True, "size": 9.5, "color": BRAND})], after=6)

    # Synthèse
    if d["synthese"]:
        box = _table(doc, 1, 1, [21 - 2 * M], indent_cm=M)
        cell = box.rows[0].cells[0]
        _shade(cell._tc.get_or_add_tcPr(), "FDEEF1")
        _cell_margins(cell, top=0.25, bottom=0.25, left=0.4, right=0.4)
        b = OxmlElement("w:tcBorders")
        lb = OxmlElement("w:left")
        lb.set(qn("w:val"), "single"); lb.set(qn("w:sz"), "24"); lb.set(qn("w:color"), BRAND_COLOR)
        b.append(lb)
        cell._tc.get_or_add_tcPr().append(b)
        _clear(cell)
        _para(cell, [("SYNTHÈSE DU PROFIL", {"bold": True, "size": 7.5, "color": BRAND})], left=0, right=0)
        _para(cell, [(d["synthese"], {"size": 9.5})], left=0, right=0, before=3)
        _para(cell, [("Synthèse rédigée par IA à partir du CV", {"italic": True, "size": 7, "color": MUTED})],
              left=0, right=0, before=2, align=WD_ALIGN_PARAGRAPH.RIGHT)

    # Compétences clés (pastilles)
    if d["competences_cles"]:
        _section(doc, "Compétences clés")
        runs = []
        for c in d["competences_cles"]:
            runs.append((f" {c} ", {"size": 8.5, "fill": "EEF0F3"}))
            runs.append(("  ", {"size": 8.5}))
        _para(doc, runs, after=0)

    # Expériences
    if d["experiences"]:
        _section(doc, "Expériences professionnelles")
        for e in d["experiences"]:
            dates = " – ".join(x for x in (e["debut"], e["fin"]) if x)
            p = _para(doc, [(e["poste"], {"bold": True, "size": 10, "color": INK}),
                            ((" — " + e["secteur"]) if e["secteur"] else "", {"size": 9.5, "color": MUTED}),
                            ("\t" + dates if dates else "", {"size": 9, "color": MUTED})], before=7)
            p.paragraph_format.tab_stops.add_tab_stop(RIGHT_TAB, WD_TAB_ALIGNMENT.RIGHT)
            for r in e["realisations"]:
                _bullet(doc, r)
            if e["environnement"]:
                _para(doc, [("Environnement : ", {"bold": True, "size": 8.5, "color": BRAND}),
                            (e["environnement"], {"size": 8.5})], before=2)

    # Formation
    if d["formations"]:
        _section(doc, "Formation")
        for f in d["formations"]:
            t = f"{f['diplome']}" + (f" ({f['type_etablissement']})" if f["type_etablissement"] else "")
            _para(doc, [(f["annee"], {"bold": True, "size": 9, "color": INK}),
                        ((" — " if f["annee"] else "") + t, {"size": 9})], before=2)

    # Langues | Certifications
    if d["langues"] or d["certifications"]:
        two = _table(doc, 1, 2, [(21 - 2 * M) / 2] * 2, indent_cm=M)
        for cell, title, items in ((two.rows[0].cells[0], "Langues",
                                    [f"{l['langue']}" + (f" ({l['niveau']})" if l["niveau"] else "") for l in d["langues"]]),
                                   (two.rows[0].cells[1], "Certifications", d["certifications"])):
            _clear(cell)
            if items:
                p = _para(cell, [(title.upper(), {"bold": True, "size": 9.5, "color": BRAND})], left=0, right=0.4, before=13, after=4)
                _border(p._p.get_or_add_pPr(), "bottom", "D1D5DB")
                for it in items:
                    _para(cell, [("•  ", {"color": BRAND}), (it, {"size": 9})], left=0.45, right=0.4, first=-0.4, before=1)
            else:
                _para(cell, [("", {})], left=0, right=0)

    # Pied de page
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _border(fp._p.get_or_add_pPr(), "top", "D1D5DB", space="6")
    r = fp.add_run(f"Document confidentiel — CV anonymisé conformément au RGPD · {BRAND_NAME} · Réf. {ref}")
    r.font.size = Pt(7.5)
    r.font.color.rgb = MUTED

    doc.save(out_path)
    return out_path


def docx_to_pdf(docx_path: Path, pdf_path: Path) -> Path:
    """Windows : Microsoft Word (COM). Linux/Docker : LibreOffice en ligne de commande."""
    if sys.platform == "win32":
        import pythoncom
        from docx2pdf import convert

        pythoncom.CoInitialize()  # exécutable depuis un thread de FastAPI
        try:
            convert(str(docx_path), str(pdf_path))
        finally:
            pythoncom.CoUninitialize()
    else:
        import shutil
        import subprocess
        import tempfile

        office = shutil.which("soffice") or shutil.which("libreoffice")
        if not office:
            raise RuntimeError("LibreOffice introuvable pour la conversion PDF.")
        with tempfile.TemporaryDirectory() as tmp:  # profil isolé : évite les verrous entre conversions
            subprocess.run([office, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--convert-to", "pdf",
                            "--outdir", tmp, str(docx_path)], check=True, timeout=180, capture_output=True)
            shutil.move(str(Path(tmp) / (docx_path.stem + ".pdf")), str(pdf_path))
    if not pdf_path.exists():
        raise RuntimeError("La conversion PDF a échoué (Word / LibreOffice installé ?).")
    return pdf_path
