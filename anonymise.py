"""Filet de sécurité déterministe autour de l'agent de masquage.

L'agent (anonymise_agent.py) fait le vrai travail ; ici on :
  - collecte les valeurs sensibles du CV d'origine,
  - détecte celles qui auraient survécu dans le dossier produit (find_leaks),
  - les masque de force en dernier recours (force_scrub).
"""
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+33|0033|0)[\s.-]?[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github)\.com/\S+", re.I)

MIN_LEN = 3  # termes plus courts ignorés (faux positifs)


def collect_terms(cv: dict) -> set[str]:
    """Toutes les valeurs d'origine qui ne doivent pas apparaître dans le dossier."""
    ident = cv["identite"]
    raw = [ident["prenom"], ident["nom"], f'{ident["prenom"]} {ident["nom"]}',
           f'{ident["nom"]} {ident["prenom"]}', ident["email"], ident["telephone"],
           ident["adresse"], ident["ville"], ident["linkedin"], ident["github"],
           ident["site_web"], ident["date_naissance"]]
    for e in cv["experiences"]:
        raw += [e["entreprise"], e["lieu"]]
    for f in cv["formations"]:
        raw += [f["etablissement"], f["lieu"]]
    return {t.strip() for t in raw if t and len(t.strip()) >= MIN_LEN}


def mask_cv(cv: dict) -> dict:
    """Étape 1 : masquage déterministe en crochets ([NOM], [ENTREPRISE_1]...), partout y compris
    dans les textes libres. Les entités distinctes sont numérotées pour garder le fil."""
    ident = cv["identite"]
    mapping: dict[str, str] = {}

    def add(value, mask):
        value = (value or "").strip()
        if len(value) >= MIN_LEN:
            mapping.setdefault(value, mask)

    for v in (f'{ident["prenom"]} {ident["nom"]}', f'{ident["nom"]} {ident["prenom"]}', ident["nom"]):
        add(v, "[NOM]")
    add(ident["prenom"], "[PRENOM]")
    add(ident["email"], "[EMAIL]")
    add(ident["telephone"], "[TELEPHONE]")
    add(ident["adresse"], "[ADRESSE]")
    add(ident["ville"], "[VILLE]")
    for k in ("linkedin", "github", "site_web"):
        add(ident[k], "[LIEN]")
    add(ident["date_naissance"], "[DATE_NAISSANCE]")
    orgs: dict[str, str] = {}
    for e in cv["experiences"]:
        if e["entreprise"].strip() and e["entreprise"].strip() not in orgs:
            orgs[e["entreprise"].strip()] = f"[ENTREPRISE_{len(orgs) + 1}]"
        add(e["lieu"], "[VILLE]")
    schools: dict[str, str] = {}
    for f in cv["formations"]:
        if f["etablissement"].strip() and f["etablissement"].strip() not in schools:
            schools[f["etablissement"].strip()] = f"[ETABLISSEMENT_{len(schools) + 1}]"
        add(f["lieu"], "[VILLE]")
    for k, v in {**orgs, **schools}.items():
        add(k, v)

    def scrub(text: str) -> str:
        for t in sorted(mapping, key=len, reverse=True):
            text = _pattern(t).sub(mapping[t], text)
        text = EMAIL_RE.sub("[EMAIL]", text)
        text = URL_RE.sub("[LIEN]", text)
        return PHONE_RE.sub("[TELEPHONE]", text)

    def walk(o):
        if isinstance(o, str):
            return scrub(o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    masked = walk(cv)
    mi = masked["identite"]
    for k in ("prenom", "nom", "email", "telephone", "adresse", "ville", "linkedin", "github", "site_web"):
        mi[k] = ""  # l'identité directe n'est jamais transmise à la suite du pipeline
    mi["date_naissance"] = ""
    return masked


def _pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)


def flatten(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (list, tuple)):
        return "\n".join(flatten(x) for x in obj)
    if isinstance(obj, dict):
        return "\n".join(flatten(v) for v in obj.values())
    return ""


def find_leaks(dossier: dict, terms: set[str]) -> list[str]:
    flat = flatten(dossier)
    leaks = sorted(t for t in terms if _pattern(t).search(flat))
    for label, rx in (("email", EMAIL_RE), ("téléphone", PHONE_RE), ("lien", URL_RE)):
        if rx.search(flat):
            leaks.append(f"{label} résiduel")
    return leaks


def _scrub(text: str, terms: set[str]) -> str:
    for t in sorted(terms, key=len, reverse=True):
        text = _pattern(t).sub("[…]", text)
    text = EMAIL_RE.sub("[…]", text)
    text = URL_RE.sub("[…]", text)
    return PHONE_RE.sub("[…]", text)


def force_scrub(obj, terms: set[str]):
    if isinstance(obj, str):
        return _scrub(obj, terms)
    if isinstance(obj, list):
        return [force_scrub(x, terms) for x in obj]
    if isinstance(obj, dict):
        return {k: force_scrub(v, terms) for k, v in obj.items()}
    return obj
