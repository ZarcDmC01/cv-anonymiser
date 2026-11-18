"""Service ESN (FastAPI, port 8000) : base de données + création des CV anonymisés + site ESM.

  /esm            site ESM (ajouter / consulter les CV, infos perso, répondre aux demandes d'accès)
  /internal/*     API réservée au site Entreprises (autre serveur), protégée par X-Internal-Key

Le site Entreprises (entreprise_site/, port 8001, Docker) consulte les profils via /internal.
Lancement : python app.py
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

import db_client
import notify
from config import DATA_DIR, ESM_INVITE_CODE, INTERNAL_KEY, OUTPUT_DIR, SESSION_SECRET, UPLOAD_DIR
from parsing import SUPPORTED
from pipeline import process_cv

app = FastAPI(title="CV Anonymiser — ESN")
WEB = Path(__file__).parent / "web"


# ── Sessions : cookie signé (HMAC), sans état côté serveur ───
def _secret() -> bytes:
    if SESSION_SECRET:
        return SESSION_SECRET.encode()
    f = DATA_DIR / ".secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().encode()


SECRET = _secret()
SESSION_TTL = 12 * 3600


def _sign(user: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps({**user, "exp": int(time.time()) + SESSION_TTL}).encode()).decode()
    return f"{body}.{hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()}"


def _read(token: Optional[str]) -> Optional[dict]:
    try:
        body, sig = (token or "").rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(body))
        return data if data["exp"] > time.time() else None
    except Exception:
        return None


def user_of(role: Optional[str]):
    def dep(session: Optional[str] = Cookie(None, alias="session_esn")) -> dict:
        u = _read(session)
        if not u:
            raise HTTPException(401, "Connexion requise")
        if role and u["role"] != role:
            raise HTTPException(403, "Accès réservé")
        return u
    return dep


esm_user = user_of("esm")


def _db(fn, *a, **k):
    try:
        return fn(*a, **k)
    except db_client.DbError as e:
        raise HTTPException(e.status, e.detail)


# ── Pages & authentification ─────────────────────────────────
def _page(name: str, role: Optional[str], session: Optional[str]):
    u = _read(session)
    if not u or (role and u["role"] != role):
        return RedirectResponse("/login")
    return FileResponse(WEB / name, media_type="text/html")


@app.get("/", include_in_schema=False)
def home(session: Optional[str] = Cookie(None, alias="session_esn")):
    u = _read(session)
    return RedirectResponse("/esm" if u else "/login")


@app.get("/login", include_in_schema=False)
def login_page():
    html = (WEB / "login.html").read_text(encoding="utf-8").replace("__ROLE__", "esm")
    return HTMLResponse(html)


@app.get("/esm", include_in_schema=False)
def esm_page(session: Optional[str] = Cookie(None, alias="session_esn")):
    return _page("index.html", "esm", session)


class Creds(BaseModel):
    email: str
    password: str
    name: str = ""
    invite: str = ""


def _start_session(user: dict, resp: Response) -> dict:
    resp.set_cookie("session_esn", _sign(user), httponly=True, samesite="lax", max_age=SESSION_TTL)
    return user


@app.post("/auth/login")
def auth_login(b: Creds, resp: Response):
    user = _db(db_client.login, b.email, b.password)
    if user["role"] != "esm":
        raise HTTPException(403, "Ce site est réservé aux ESM : connecte-toi sur le site Entreprises.")
    return _start_session(user, resp)


@app.post("/auth/register")
def auth_register(b: Creds, resp: Response):
    if not hmac.compare_digest(b.invite, ESM_INVITE_CODE):
        raise HTTPException(403, "Code d'invitation ESM invalide")
    if not b.name.strip():
        raise HTTPException(422, "Nom requis")
    return _start_session(_db(db_client.create_user, b.email, b.name, "esm", b.password), resp)


@app.post("/auth/logout")
def auth_logout(resp: Response):
    resp.delete_cookie("session_esn")
    return {"ok": True}


@app.get("/auth/me")
def auth_me(u: dict = Depends(esm_user)):
    return {k: u[k] for k in ("id", "email", "name", "role")}


# ── Notifications (les deux sites) ───────────────────────────
@app.get("/api/notifications")
def notifications(u: dict = Depends(esm_user)):
    return _db(db_client.list_notifications, u["id"])


@app.post("/api/notifications/read")
def notifications_read(u: dict = Depends(esm_user)):
    return _db(db_client.mark_read, u["id"])


# ── Site ESM ─────────────────────────────────────────────────
@app.post("/upload")
def upload(file: UploadFile = File(...), u: dict = Depends(esm_user)):
    # `def` (et non async) : FastAPI l'exécute dans un thread, ce qui convient au travail bloquant
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Format non supporté ({ext}). Acceptés : {', '.join(sorted(SUPPORTED))}")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        return process_cv(dest, file.filename, owner_id=u["id"])
    except (ValueError, RuntimeError) as e:
        raise HTTPException(422, str(e))


HEADERS = ["ID", "Réf. consultant", "Date", "Fichier d'origine", "Prénom", "Nom", "Titre", "Email", "Téléphone", "Ville",
           "Nb expériences", "Compétences", "Fuites détectées", "Score fidélité /100", "Éléments manquants / suspects"]


def _rows() -> dict:
    cvs = _db(db_client.list_cvs, private=True)
    keys = ["id", "ref", "created_at", "original_name", "prenom", "nom", "titre", "email", "telephone", "ville",
            "nb_exp", "competences", "leaks", "score", "manquants"]
    return {"headers": HEADERS, "rows": [[c.get(k) for k in keys] for c in reversed(cvs)]}  # ordre chronologique


@app.get("/api/excel")  # nom conservé pour le tableau intégré
def api_table(u: dict = Depends(esm_user)):
    return _rows()


@app.get("/excel")
def export_excel(u: dict = Depends(esm_user)):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "CV"
    t = _rows()
    ws.append(t["headers"] + ["CV anonymisé (lien)"])
    for r in t["rows"]:
        ws.append(r + [f"http://localhost:8000/cv/{r[0]}.pdf"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="cv_index.xlsx"'})


@app.get("/api/esm/cvs/{cv_id}")
def esm_cv(cv_id: str, u: dict = Depends(esm_user)):
    return _db(db_client.get_cv, cv_id, private=True)


@app.get("/api/esm/requests")
def esm_requests(u: dict = Depends(esm_user)):
    return _db(db_client.list_requests)


class Answer(BaseModel):
    status: str


@app.post("/api/esm/requests/{rid}")
def esm_answer(rid: int, b: Answer, u: dict = Depends(esm_user)):
    req = _db(db_client.answer_request, rid, b.status)
    cv = _db(db_client.get_cv, req["cv_id"])
    verdict = "acceptée" if b.status == "accepted" else "refusée"
    notify.notify(_db(db_client.get_user, req["company_id"]), "reponse_acces",
                  f"Votre demande d'accès au profil {cv['ref']} a été {verdict}.")
    return req


# ── API interne pour le site Entreprises (autre serveur) ─────
def internal_key(x_internal_key: str = Header("")):
    if not hmac.compare_digest(x_internal_key, INTERNAL_KEY):
        raise HTTPException(401, "Clé interne invalide")


internal = APIRouter(prefix="/internal", dependencies=[Depends(internal_key)], include_in_schema=False)


class CompanyCreds(BaseModel):
    email: str
    password: str
    name: str = ""


@internal.post("/auth/login")
def int_login(b: CompanyCreds):
    user = _db(db_client.login, b.email, b.password)
    if user["role"] != "entreprise":
        raise HTTPException(403, "Compte ESM : connecte-toi sur le site ESN.")
    return user


@internal.post("/auth/register")
def int_register(b: CompanyCreds):
    if not b.name.strip():
        raise HTTPException(422, "Nom requis")
    return _db(db_client.create_user, b.email, b.name, "entreprise", b.password)


@internal.get("/cvs")  # champs anonymisés uniquement
def int_cvs(company_id: int, q: str = "", competences: str = "", min_annees: int = 0, max_annees: int = 100,
            min_score: float = 0):
    cvs = _db(db_client.list_cvs, private=False, q=q, competences=competences, min_annees=min_annees,
              max_annees=max_annees, min_score=min_score)
    status = {r["cv_id"]: r["status"] for r in _db(db_client.list_requests, company_id=company_id)}
    for c in cvs:
        c["access"] = status.get(c["id"])  # None / pending / accepted / refused
    return cvs


class AccessBody(BaseModel):
    company_id: int
    company_name: str = ""
    cv_id: str
    message: str = ""


@internal.post("/access-requests")
def int_ask(b: AccessBody):
    req = _db(db_client.create_request, b.cv_id, b.company_id, b.message)
    cv = _db(db_client.get_cv, b.cv_id)
    notify.notify_role("esm", "demande_acces", f"{b.company_name} demande l'accès aux informations du profil {cv['ref']}.")
    return req


@internal.get("/my-requests")
def int_my_requests(company_id: int):
    out = []
    for r in _db(db_client.list_requests, company_id=company_id):
        if r["status"] == "accepted":  # infos perso uniquement une fois la demande acceptée
            cv = _db(db_client.get_cv, r["cv_id"], private=True)
            r["perso"] = {k: cv.get(k) for k in ("prenom", "nom", "email", "telephone", "ville")}
        out.append(r)
    return out


@internal.get("/notifications")
def int_notifications(user_id: int):
    return _db(db_client.list_notifications, user_id)


@internal.post("/notifications/read")
def int_notifications_read(user_id: int):
    return _db(db_client.mark_read, user_id)


@internal.get("/cv/{cv_id}.pdf")
def int_pdf(cv_id: str):
    return _serve_pdf(cv_id)


app.include_router(internal)


# ── PDF anonymisé (ESM connecté, ou site Entreprises via /internal) ────────────────
@app.get("/cv/{cv_id}.pdf")
def get_cv(cv_id: str, u: dict = Depends(esm_user)):
    return _serve_pdf(cv_id)


def _serve_pdf(cv_id: str):
    if not re.fullmatch(r"[0-9a-f]{8}", cv_id):
        raise HTTPException(404)
    pdf = OUTPUT_DIR / f"{cv_id}.pdf"
    if not pdf.exists():
        raise HTTPException(404, "CV introuvable")
    return FileResponse(pdf, media_type="application/pdf", filename=f"cv_anonymise_{cv_id}.pdf",
                        content_disposition_type="inline")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
