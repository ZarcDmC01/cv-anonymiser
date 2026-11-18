"""Base de données SQLite du site ESN (utilisateurs, CV, demandes d'accès, notifications).

Module appelé directement par le service ESN (app.py) via db_client.py.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "data" / "cv.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('esm','entreprise')), salt TEXT NOT NULL, pwd_hash TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cvs(
  id TEXT PRIMARY KEY, ref TEXT, created_at TEXT, original_name TEXT, owner_id INTEGER,
  titre TEXT, ville TEXT, annees INTEGER, nb_exp INTEGER, competences TEXT, leaks TEXT, score REAL, manquants TEXT,
  prenom TEXT, nom TEXT, email TEXT, telephone TEXT,
  cv_json TEXT, dossier_json TEXT);
CREATE TABLE IF NOT EXISTS access_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, cv_id TEXT NOT NULL, company_id INTEGER NOT NULL, message TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','refused')),
  created_at TEXT NOT NULL, answered_at TEXT, UNIQUE(cv_id, company_id));
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT, message TEXT NOT NULL,
  created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    # pas de mode WAL : il échoue sur un dossier Windows monté dans Docker (fichier -shm)
    return c


def _run(sql: str, args: tuple = (), *, one=False, write=False):
    with _conn() as c:  # commit/rollback automatique
        cur = c.execute(sql, args)
        if write:
            return cur.lastrowid
        rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


with _conn() as _c:
    _c.executescript(SCHEMA)


now = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


# ── Utilisateurs ─────────────────────────────────────────────
class UserIn(BaseModel):
    email: str
    name: str
    role: str
    password: str


class Login(BaseModel):
    email: str
    password: str


def _public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role")}


def create_user(u: UserIn):
    if u.role not in ("esm", "entreprise"):
        raise HTTPException(422, "Rôle invalide")
    if len(u.password) < 6:
        raise HTTPException(422, "Mot de passe trop court (6 caractères minimum)")
    salt = secrets.token_hex(16)
    try:
        uid = _run("INSERT INTO users(email,name,role,salt,pwd_hash,created_at) VALUES(?,?,?,?,?,?)",
                   (u.email.strip().lower(), u.name.strip(), u.role, salt, _hash(u.password, salt), now()), write=True)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Cet e-mail est déjà utilisé")
    return _public_user(_run("SELECT * FROM users WHERE id=?", (uid,), one=True))


def login(b: Login):
    u = _run("SELECT * FROM users WHERE email=?", (b.email.strip().lower(),), one=True)
    if not u or not hmac.compare_digest(_hash(b.password, u["salt"]), u["pwd_hash"]):
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")
    return _public_user(u)


def list_users(role: Optional[str] = None):
    rows = _run("SELECT * FROM users" + (" WHERE role=?" if role else ""), (role,) if role else ())
    return [_public_user(u) for u in rows]


def get_user(uid: int):
    u = _run("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not u:
        raise HTTPException(404)
    return _public_user(u)


# ── CV ───────────────────────────────────────────────────────
PUBLIC_COLS = "id, ref, created_at, titre, annees, nb_exp, competences, score"
PRIVATE_COLS = "prenom, nom, email, telephone, ville, original_name, cv_json, owner_id, leaks, manquants"


class CvIn(BaseModel):
    id: str
    ref: str
    original_name: str = ""
    owner_id: Optional[int] = None
    titre: str = ""
    ville: str = ""
    annees: int = 0
    nb_exp: int = 0
    competences: str = ""
    leaks: str = ""
    score: Optional[float] = None
    manquants: str = ""
    prenom: str = ""
    nom: str = ""
    email: str = ""
    telephone: str = ""
    cv: dict = {}
    dossier: dict = {}


def save_cv(c: CvIn):
    _run("""INSERT OR REPLACE INTO cvs(id,ref,created_at,original_name,owner_id,titre,ville,annees,nb_exp,competences,
            leaks,score,manquants,prenom,nom,email,telephone,cv_json,dossier_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (c.id, c.ref, now(), c.original_name, c.owner_id, c.titre, c.ville, c.annees, c.nb_exp, c.competences,
          c.leaks, c.score, c.manquants, c.prenom, c.nom, c.email, c.telephone,
          json.dumps(c.cv, ensure_ascii=False), json.dumps(c.dossier, ensure_ascii=False)), write=True)
    return {"id": c.id}


def list_cvs(private: bool = False, q: str = "", competences: str = "", min_annees: int = 0,
             max_annees: int = 100, min_score: float = 0, limit: int = 200):
    """private=false -> uniquement les champs anonymisés. Filtres : q (titre/compétences), competences
    (liste séparée par des virgules, toutes requises), expérience min/max, score min."""
    where, args = ["annees BETWEEN ? AND ?", "COALESCE(score,0) >= ?"], [min_annees, max_annees, min_score]
    if q.strip():
        where.append("(LOWER(titre) LIKE ? OR LOWER(competences) LIKE ?)")
        args += [f"%{q.strip().lower()}%"] * 2
    for comp in [x.strip().lower() for x in competences.split(",") if x.strip()]:
        where.append("LOWER(competences) LIKE ?")
        args.append(f"%{comp}%")
    cols = f"{PUBLIC_COLS}, {PRIVATE_COLS}" if private else PUBLIC_COLS
    rows = _run(f"SELECT {cols} FROM cvs WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?", (*args, limit))
    for r in rows:
        r.pop("cv_json", None)  # volumineux : réservé au détail
    return rows


def get_cv(cv_id: str, private: bool = False):
    r = _run("SELECT * FROM cvs WHERE id=?", (cv_id,), one=True)
    if not r:
        raise HTTPException(404, "CV introuvable")
    r["cv"], r["dossier"] = json.loads(r.pop("cv_json") or "{}"), json.loads(r.pop("dossier_json") or "{}")
    if not private:
        keep = set(PUBLIC_COLS.replace(" ", "").split(",")) | {"dossier"}
        r = {k: v for k, v in r.items() if k in keep}
    return r


# ── Demandes d'accès ─────────────────────────────────────────
class AccessIn(BaseModel):
    cv_id: str
    company_id: int
    message: str = ""


class AccessAnswer(BaseModel):
    status: str


def create_request(b: AccessIn):
    if not _run("SELECT 1 FROM cvs WHERE id=?", (b.cv_id,), one=True):
        raise HTTPException(404, "CV introuvable")
    try:
        rid = _run("INSERT INTO access_requests(cv_id,company_id,message,created_at) VALUES(?,?,?,?)",
                   (b.cv_id, b.company_id, b.message, now()), write=True)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Une demande existe déjà pour ce profil")
    return _run("SELECT * FROM access_requests WHERE id=?", (rid,), one=True)


def list_requests(status: Optional[str] = None, company_id: Optional[int] = None, cv_id: Optional[str] = None):
    """Jointure utile aux deux sites : ref/titre du CV + nom de l'entreprise."""
    where, args = [], []
    for col, val in (("r.status", status), ("r.company_id", company_id), ("r.cv_id", cv_id)):
        if val is not None:
            where.append(f"{col}=?")
            args.append(val)
    return _run("""SELECT r.*, c.ref, c.titre, u.name AS company_name, u.email AS company_email
                   FROM access_requests r JOIN cvs c ON c.id=r.cv_id JOIN users u ON u.id=r.company_id"""
                + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.created_at DESC", tuple(args))


def get_request(rid: int):
    r = _run("SELECT * FROM access_requests WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    return r


def answer_request(rid: int, b: AccessAnswer):
    if b.status not in ("accepted", "refused"):
        raise HTTPException(422, "Statut invalide")
    _run("UPDATE access_requests SET status=?, answered_at=? WHERE id=?", (b.status, now(), rid), write=True)
    return get_request(rid)


# ── Notifications ────────────────────────────────────────────
class NotifIn(BaseModel):
    user_id: int
    kind: str = ""
    message: str


def add_notification(b: NotifIn):
    return {"id": _run("INSERT INTO notifications(user_id,kind,message,created_at) VALUES(?,?,?,?)",
                       (b.user_id, b.kind, b.message, now()), write=True)}


def list_notifications(user_id: int, unread: bool = False):
    return _run("SELECT * FROM notifications WHERE user_id=?" + (" AND read=0" if unread else "") +
                " ORDER BY id DESC LIMIT 100", (user_id,))


def mark_read(user_id: int):
    _run("UPDATE notifications SET read=1 WHERE user_id=?", (user_id,), write=True)
    return {"ok": True}
