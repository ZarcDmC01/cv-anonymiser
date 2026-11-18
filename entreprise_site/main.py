"""Site Entreprises (FastAPI, port 8001) : consultation des CV anonymisés, filtres, demandes d'accès.

Serveur distinct du site ESN : il n'a ni base de données ni pipeline, il interroge l'API interne de l'ESN
(ESN_URL + X-Internal-Key). Tourne dans Docker (voir docker-compose.yml) ou en local : python main.py
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

ESN_URL = os.getenv("ESN_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "dev-internal-key")
WEB = Path(__file__).parent / "web"
SECRET = (os.getenv("SESSION_SECRET") or secrets.token_hex(32)).encode()  # sessions perdues au redémarrage si non fixé
TTL = 12 * 3600

app = FastAPI(title="CV Anonymiser — Entreprises")


def esn(method: str, path: str, **kw):
    try:
        r = httpx.request(method, f"{ESN_URL}/internal{path}", headers={"X-Internal-Key": INTERNAL_KEY}, timeout=30.0, **kw)
    except httpx.HTTPError:
        raise HTTPException(503, f"Serveur ESN injoignable ({ESN_URL}). Démarre-le d'abord.")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(r.status_code, str(detail))
    return r


def _sign(user: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps({**user, "exp": int(time.time()) + TTL}).encode()).decode()
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


def current(session: Optional[str] = Cookie(None, alias="session_ent")) -> dict:
    u = _read(session)
    if not u:
        raise HTTPException(401, "Connexion requise")
    return u


@app.get("/", include_in_schema=False)
def home(session: Optional[str] = Cookie(None, alias="session_ent")):
    return RedirectResponse("/entreprises" if _read(session) else "/login")


@app.get("/login", include_in_schema=False)
def login_page():
    return HTMLResponse((WEB / "login.html").read_text(encoding="utf-8").replace("__ROLE__", "entreprise"))


@app.get("/entreprises", include_in_schema=False)
def page(session: Optional[str] = Cookie(None, alias="session_ent")):
    return FileResponse(WEB / "entreprises.html") if _read(session) else RedirectResponse("/login")


class Creds(BaseModel):
    email: str
    password: str
    name: str = ""
    invite: str = ""  # inutilisé ici (réservé à l'ESN)


def _start(user: dict, resp: Response) -> dict:
    resp.set_cookie("session_ent", _sign(user), httponly=True, samesite="lax", max_age=TTL)
    return user


@app.post("/auth/login")
def login(b: Creds, resp: Response):
    return _start(esn("POST", "/auth/login", json={"email": b.email, "password": b.password}).json(), resp)


@app.post("/auth/register")
def register(b: Creds, resp: Response):
    return _start(esn("POST", "/auth/register", json={"email": b.email, "password": b.password, "name": b.name}).json(), resp)


@app.post("/auth/logout")
def logout(resp: Response):
    resp.delete_cookie("session_ent")
    return {"ok": True}


@app.get("/auth/me")
def me(u: dict = Depends(current)):
    return {k: u[k] for k in ("id", "email", "name", "role")}


@app.get("/api/cvs")
def cvs(q: str = "", competences: str = "", min_annees: int = 0, max_annees: int = 100, min_score: float = 0,
        u: dict = Depends(current)):
    return esn("GET", "/cvs", params={"company_id": u["id"], "q": q, "competences": competences,
                                      "min_annees": min_annees, "max_annees": max_annees, "min_score": min_score}).json()


class AccessBody(BaseModel):
    cv_id: str
    message: str = ""


@app.post("/api/access-requests")
def ask(b: AccessBody, u: dict = Depends(current)):
    return esn("POST", "/access-requests", json={"company_id": u["id"], "company_name": u["name"],
                                                 "cv_id": b.cv_id, "message": b.message}).json()


@app.get("/api/my-requests")
def my_requests(u: dict = Depends(current)):
    return esn("GET", "/my-requests", params={"company_id": u["id"]}).json()


@app.get("/api/notifications")
def notifications(u: dict = Depends(current)):
    return esn("GET", "/notifications", params={"user_id": u["id"]}).json()


@app.post("/api/notifications/read")
def notifications_read(u: dict = Depends(current)):
    return esn("POST", "/notifications/read", params={"user_id": u["id"]}).json()


@app.get("/cv/{cv_id}.pdf")
def pdf(cv_id: str, u: dict = Depends(current)):
    r = esn("GET", f"/cv/{cv_id}.pdf")
    return Response(r.content, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8001")))
