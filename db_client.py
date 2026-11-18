"""Accès à la base depuis le service ESN (appels directs au module db, traduction des erreurs)."""
from fastapi import HTTPException

import db


class DbError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except HTTPException as e:
        raise DbError(e.status_code, str(e.detail))


def create_user(email, name, role, password): return _call(db.create_user, db.UserIn(email=email, name=name, role=role, password=password))
def login(email, password): return _call(db.login, db.Login(email=email, password=password))
def list_users(role=None): return _call(db.list_users, role)
def get_user(uid): return _call(db.get_user, uid)

def save_cv(**fields): return _call(db.save_cv, db.CvIn(**fields))
def list_cvs(private=False, **filters): return _call(db.list_cvs, private=private, **{k: v for k, v in filters.items() if v not in (None, "")})
def get_cv(cv_id, private=False): return _call(db.get_cv, cv_id, private)

def create_request(cv_id, company_id, message=""): return _call(db.create_request, db.AccessIn(cv_id=cv_id, company_id=company_id, message=message))
def list_requests(**filters): return _call(db.list_requests, **{k: v for k, v in filters.items() if v is not None})
def get_request(rid): return _call(db.get_request, rid)
def answer_request(rid, status): return _call(db.answer_request, rid, db.AccessAnswer(status=status))

def add_notification(user_id, kind, message): return _call(db.add_notification, db.NotifIn(user_id=user_id, kind=kind, message=message))
def list_notifications(user_id): return _call(db.list_notifications, user_id)
def mark_read(user_id): return _call(db.mark_read, user_id)
