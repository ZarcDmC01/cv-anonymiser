"""Configuration centrale (surchargeable par variables d'environnement)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"      # CV d'origine
JSON_DIR = DATA_DIR / "json"           # JSON extrait (données d'origine)
OUTPUT_DIR = DATA_DIR / "output"       # CV anonymisés (.docx + .pdf)
EXCEL_PATH = DATA_DIR / "cv_index.xlsx"

for _d in (UPLOAD_DIR, JSON_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")  # OCR des scans
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "12288"))

# Habillage du dossier (bandeau)
BRAND_NAME = os.getenv("BRAND_NAME", "Fil Rouge Consulting")
BRAND_COLOR = os.getenv("BRAND_COLOR", "9F1239")  # hex sans #

# Base des liens écrits dans l'Excel
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

# Taille max d'un chunk de texte envoyé au LLM (caractères)
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "6000"))

# --- Architecture à deux services -------------------------------------------
# Service BDD (db_service.py, port 8001) <-> Service API/sites (app.py, port 8000)
DB_SERVICE_URL = os.getenv("DB_SERVICE_URL", "http://127.0.0.1:8001")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "dev-internal-key")      # secret partagé entre les 2 services
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "cv.db")))
ESM_INVITE_CODE = os.getenv("ESM_INVITE_CODE", "esm-demo")       # requis pour créer un compte ESM
SESSION_SECRET = os.getenv("SESSION_SECRET", "")                 # vide = généré et gardé dans data/.secret

# E-mails (optionnels) : sans SMTP_HOST, les notifications restent dans l'appli (cloche) et la console
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@localhost")
