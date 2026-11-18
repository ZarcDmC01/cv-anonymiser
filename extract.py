"""Extraction structurée (texte du CV -> JSON) via le LLM Ollama."""
import json
import re

from ollama_client import chat_json
from parsing import chunk_text

SCHEMA = {
    "identite": {
        "prenom": "", "nom": "", "titre": "", "email": "", "telephone": "",
        "adresse": "", "ville": "", "linkedin": "", "github": "", "site_web": "",
        "date_naissance": "",
    },
    "profil": "",
    "experiences": [{"poste": "", "entreprise": "", "lieu": "", "debut": "", "fin": "", "description": [""]}],
    "formations": [{"diplome": "", "etablissement": "", "lieu": "", "annee": "", "details": ""}],
    "competences": [""],
    "langues": [{"langue": "", "niveau": ""}],
    "projets": [{"nom": "", "description": ""}],
    "certifications": [""],
    "centres_interet": [""],
}

SYSTEM_PROMPT = f"""Tu es un extracteur d'informations de CV. Tu reçois le texte brut d'un CV \
(parfois désordonné à cause des colonnes) et tu renvoies UNIQUEMENT un objet JSON respectant \
exactement ce schéma (mêmes clés) :

{json.dumps(SCHEMA, ensure_ascii=False, indent=1)}

Règles :
- Recopie les informations telles qu'écrites dans le CV. N'invente RIEN : champ absent = "" ou [].
- "experiences", "formations", "projets" : une entrée par élément ; "description" est une liste de puces.
- "competences" : liste de compétences/outils individuels.
- Pas de texte hors du JSON."""


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("Réponse du LLM non JSON")
        return json.loads(m.group(0))


def _normalize(data: dict) -> dict:
    """Force la présence de toutes les clés du schéma avec les bons types."""
    out = json.loads(json.dumps(SCHEMA))  # deep copy
    ident = data.get("identite") if isinstance(data.get("identite"), dict) else {}
    for k in out["identite"]:
        out["identite"][k] = str(ident.get(k) or "").strip()
    out["profil"] = str(data.get("profil") or "").strip()

    for key, tmpl in (("experiences", SCHEMA["experiences"][0]), ("formations", SCHEMA["formations"][0]),
                      ("langues", SCHEMA["langues"][0]), ("projets", SCHEMA["projets"][0])):
        items = data.get(key) if isinstance(data.get(key), list) else []
        out[key] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            row = {}
            for k, default in tmpl.items():
                v = it.get(k)
                if isinstance(default, list):
                    v = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else (
                        [str(v).strip()] if v else [])
                else:
                    v = str(v or "").strip()
                row[k] = v
            if any(row.values()):
                out[key].append(row)

    for key in ("competences", "certifications", "centres_interet"):
        v = data.get(key)
        out[key] = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
    return out


def _merge(a: dict, b: dict) -> dict:
    """Fusionne deux extractions (CV long découpé en chunks)."""
    for k, v in b["identite"].items():
        if not a["identite"][k]:
            a["identite"][k] = v
    if not a["profil"]:
        a["profil"] = b["profil"]
    for key in ("experiences", "formations", "langues", "projets", "competences",
                "certifications", "centres_interet"):
        for item in b[key]:
            if item not in a[key]:
                a[key].append(item)
    return a


def extract_cv(text: str) -> dict:
    result = None
    for chunk in chunk_text(text):
        raw = chat_json(SYSTEM_PROMPT, f"Texte du CV :\n\n{chunk}")
        part = _normalize(_parse_json(raw))
        result = part if result is None else _merge(result, part)
    return result
