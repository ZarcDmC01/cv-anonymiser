"""Client HTTP minimal pour Ollama (repris de LettreMotivation-IA, adapté au JSON)."""
import httpx

from config import EMBED_MODEL, OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_URL, OLLAMA_VISION_MODEL


def embed(text: str) -> list[float]:
    resp = httpx.post(f"{OLLAMA_URL}/api/embeddings", json={"model": EMBED_MODEL, "prompt": text}, timeout=120.0)
    resp.raise_for_status()
    return resp.json()["embedding"]


def vision_ocr(png_bytes: bytes) -> str:
    """OCR via un modèle vision Ollama (utile pour les CV scannés sans Tesseract)."""
    import base64

    import time
    try:
      for attempt in range(3):  # le chargement du modèle vision peut échouer au 1er essai (500)
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_VISION_MODEL,
                "messages": [{
                    "role": "user",
                    "content": "Transcris fidèlement TOUT le texte de ce CV, dans l'ordre de lecture "
                               "(colonne par colonne), sans rien ajouter ni résumer ni commenter.",
                    "images": [base64.b64encode(png_bytes).decode()],
                }],
                "stream": False,
                "options": {"temperature": 0.0, "num_ctx": 8192},
            },
            timeout=600.0,
        )
        if resp.status_code < 500:
            break
        time.sleep(5)
    except httpx.ConnectError as e:
        raise RuntimeError(f"Ollama injoignable sur {OLLAMA_URL}.") from e
    if resp.status_code == 404:
        raise RuntimeError(f"Modèle vision introuvable : `ollama pull {OLLAMA_VISION_MODEL}`.")
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _valid_json(raw: str) -> bool:
    import json
    import re

    m = re.search(r"\{.*\}", raw, re.S)
    for cand in (raw, m.group(0) if m else ""):
        try:
            json.loads(cand)
            return True
        except (json.JSONDecodeError, TypeError):
            pass
    return False


def chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """Appelle le modèle en mode JSON et renvoie un JSON valide (3 essais, température croissante)."""
    raw = ""
    for attempt in range(3):
        raw = _chat_json_once(system_prompt, user_prompt, temperature + 0.2 * attempt)
        if _valid_json(raw):
            return raw
    return raw  # l'appelant lèvera une erreur claire


def _chat_json_once(system_prompt: str, user_prompt: str, temperature: float) -> str:
    """Un appel au modèle en mode JSON strict ; renvoie le contenu brut (str)."""
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX},
            },
            timeout=600.0,
        )
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Ollama injoignable sur {OLLAMA_URL}. Lance `ollama serve` "
            f"et `ollama pull {OLLAMA_MODEL}`."
        ) from e
    if resp.status_code == 404:
        raise RuntimeError(f"Modèle introuvable : `ollama pull {OLLAMA_MODEL}`.")
    resp.raise_for_status()
    return resp.json()["message"]["content"]
