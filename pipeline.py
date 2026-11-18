"""Orchestration : fichier -> texte -> JSON -> crochets -> agent (style) -> DOCX -> PDF -> service BDD."""
import json
import uuid
from pathlib import Path

from anonymise_agent import build_dossier
from config import JSON_DIR, OUTPUT_DIR, PUBLIC_BASE_URL
import db_client
import notify
from evaluate import evaluate, summary_missing
from extract import extract_cv
from parsing import extract_text
from render import build_docx, docx_to_pdf


def _dump(name: str, obj: dict):
    (JSON_DIR / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def process_cv(path: Path, original_name: str, owner_id: int | None = None) -> dict:
    cv_id = uuid.uuid4().hex[:8]
    ref = f"CONS-{cv_id[:6].upper()}"

    text = extract_text(path)                                   # 1. parse
    cv = extract_cv(text)                                       # 2. extraction LLM -> JSON d'origine
    _dump(f"{cv_id}.json", cv)

    masked, dossier, leaks = build_dossier(cv)                  # 3. crochets  4. agent : réécriture au style de référence
    _dump(f"{cv_id}.masked.json", masked)
    _dump(f"{cv_id}.dossier.json", dossier)

    docx_path = build_docx(dossier, ref, OUTPUT_DIR / f"{cv_id}.docx")  # 5. Word
    docx_to_pdf(docx_path, OUTPUT_DIR / f"{cv_id}.pdf")                 # 6. PDF

    report = evaluate(text, cv, masked, dossier, dossier["annees_experience"])  # 7. score de fidélité
    _dump(f"{cv_id}.report.json", report)

    url = f"{PUBLIC_BASE_URL}/cv/{cv_id}.pdf"
    ident = cv.get("identite", {})
    comps = dossier.get("competences_cles") or cv.get("competences", [])
    db_error = None
    try:                                                        # 8. Service BDD (remplace l'Excel)
        db_client.save_cv(
            id=cv_id, ref=ref, original_name=original_name, owner_id=owner_id,
            titre=dossier.get("titre") or ident.get("titre") or "", ville=ident.get("ville") or "",
            annees=int(dossier.get("annees_experience") or 0), nb_exp=len(cv.get("experiences", [])),
            competences=", ".join(comps), leaks=", ".join(leaks) if leaks else "aucune",
            score=report["score_global"], manquants=summary_missing(report),
            prenom=ident.get("prenom") or "", nom=ident.get("nom") or "", email=ident.get("email") or "",
            telephone=ident.get("telephone") or "", cv=cv, dossier=dossier)
        notify.notify_role("entreprise", "nouveau_cv", f"Nouveau profil disponible : {ref} — {dossier.get('titre', '')}")
    except db_client.DbError as e:
        db_error = e.detail
    excel_error = db_error
    return {"id": cv_id, "ref": ref, "pdf_url": url, "leaks": leaks, "excel_error": excel_error,
            "score": report["score_global"], "score_extraction": report["extraction"]["score"],
            "score_dossier": report["dossier"]["score"], "manquants": summary_missing(report)}
