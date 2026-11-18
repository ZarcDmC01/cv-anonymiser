"""Notifications : cloche dans l'appli (stockée par le service BDD) + e-mail si SMTP configuré."""
import smtplib
from email.message import EmailMessage

import db_client
from config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def _email(to: str, subject: str, body: str):
    if not SMTP_HOST:
        print(f"[notif e-mail non envoyé, SMTP non configuré] à {to} : {subject}")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SMTP_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    except Exception as e:  # une notification ratée ne doit jamais casser le traitement
        print(f"[notif e-mail échouée] {to} : {e}")


def notify(user: dict, kind: str, message: str):
    try:
        db_client.add_notification(user["id"], kind, message)
    except db_client.DbError as e:
        print(f"[notification non enregistrée] {e.detail}")
    _email(user["email"], f"CV Anonymiser — {message[:60]}", message)


def notify_role(role: str, kind: str, message: str):
    for u in db_client.list_users(role):
        notify(u, kind, message)
