"""Score de fidélité : le CV anonymisé a-t-il gardé toute l'information utile du CV de base ?

Deux niveaux, 100 % déterministes sauf la similarité sémantique (embeddings nomic-embed-text) :
  1. EXTRACTION : texte brut du CV  ->  JSON       (le LLM a-t-il oublié des chiffres, dates, mots ?)
  2. DOSSIER    : CV masqué (crochets) -> dossier  (l'agent a-t-il perdu ou inventé quelque chose ?)
Les noms, coordonnées, employeurs, écoles et villes sont volontairement exclus du « attendu » :
ils sont masqués par conception.
"""
import difflib
import math
import re
import unicodedata

from anonymise import flatten

BRACKET_RE = re.compile(r"\[[A-Z_0-9…]*\]")
NUM_RE = re.compile(r"\d+(?:[  .,]\d{3})*(?:[.,]\d+)?")
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
WORD_RE = re.compile(r"[a-z][a-z+#.\-]{4,}")
STOP = set("""avec dans pour cette depuis entre sous leur leurs plus tout tous toute toutes sont etre avoir
fait faire ainsi alors donc ainsi comme aussi autres autre chez vers selon apres avant dont ces ses mes
niveau annee annees mois travail projet projets equipe gestion mise place suivi""".split())

W = {"structure": 0.30, "chiffres": 0.20, "annees": 0.10, "competences": 0.20, "semantique": 0.20}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.finditer(BRACKET_RE.sub(" ", text)):
        tok = m.group()
        if YEAR_RE.fullmatch(tok):
            continue
        if re.fullmatch(r"\d{1,3}(?:[  .,]\d{3})+", tok):
            tok = re.sub(r"\D", "", tok)
        else:
            tok = tok.replace(",", ".").replace(" ", "")
        if len(re.sub(r"\D", "", tok)) >= 8:  # téléphone, etc.
            continue
        out.add(tok)
    return out


def _years(text: str) -> set[str]:
    return set(YEAR_RE.findall(BRACKET_RE.sub(" ", text)))


def _words(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(_norm(BRACKET_RE.sub(" ", text))) if w not in STOP}


def _recall(expected: set, got: set) -> tuple[float | None, list]:
    if not expected:
        return None, []
    missing = sorted(expected - got)
    return 1 - len(missing) / len(expected), missing


def _best(a: str, candidates: list[str]) -> float:
    a = _norm(a)
    return max((difflib.SequenceMatcher(None, a, _norm(c)).ratio() for c in candidates), default=0.0)


def _cosine(u, v) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    return dot / (math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v)) or 1)


def _content(cv: dict) -> dict:
    """CV sans l'identité directe (ce qui doit survivre à l'anonymisation)."""
    return {k: v for k, v in cv.items() if k != "identite"}


def _skill_terms(cv: dict) -> list[str]:
    terms = []
    for c in cv["competences"]:
        main = re.sub(r"\(.*?\)", "", c).strip()
        if main:
            terms.append(main)
    return terms


def evaluate_extraction(raw_text: str, cv: dict) -> dict:
    """Le JSON extrait contient-il les chiffres, années et mots du texte brut ?"""
    flat = flatten(cv)
    rn, mn = _recall(_numbers(raw_text), _numbers(flat))
    ry, my = _recall(_years(raw_text), _years(flat))
    rw, mw = _recall(_words(raw_text), _words(flat))
    parts = [(rn, .4), (ry, .2), (rw, .4)]
    tot = sum(w for r, w in parts if r is not None)
    score = sum(r * w for r, w in parts if r is not None) / tot if tot else 1.0
    return {"score": round(score * 100), "chiffres": rn, "annees": ry, "mots": rw,
            "manquants": {"chiffres": mn[:15], "annees": my[:10], "mots": mw[:20]}}


def evaluate_dossier(masked: dict, dossier: dict, annees_calculees: int = 0, use_embeddings: bool = True) -> dict:
    src = _content(masked)
    src_flat, dos_flat = flatten(src), flatten(dossier)
    dos_norm = _norm(dos_flat)
    details, missing, invented = {}, {}, {}

    # Structure : expériences, formations, langues, certifications
    struct = []
    miss_struct = []
    for key, label, field in (("experiences", "expériences", "poste"), ("formations", "formations", "diplome")):
        orig = [x[field] for x in src[key] if x[field]]
        cand = [x[field] for x in dossier[key] if x[field]]
        if orig:
            ok = [o for o in orig if _best(o, cand) >= 0.6]
            struct.append(len(ok) / len(orig))
            miss_struct += [f"{label}: {o}" for o in orig if o not in ok]
    langs = [l["langue"].split()[0] for l in src["langues"] if l["langue"]]
    if langs:
        ok = [l for l in langs if _norm(l) in dos_norm]
        struct.append(len(ok) / len(langs))
        miss_struct += [f"langue: {l}" for l in langs if l not in ok]
    certs = [c for c in src["certifications"] if c]
    if certs:
        ok = [c for c in certs if _best(c, dossier["certifications"]) >= 0.6]
        struct.append(len(ok) / len(certs))
        miss_struct += [f"certification: {c}" for c in certs if c not in ok]
    details["structure"] = sum(struct) / len(struct) if struct else None
    missing["structure"] = miss_struct

    # Chiffres, années, compétences
    details["chiffres"], missing["chiffres"] = _recall(_numbers(src_flat), _numbers(dos_flat))
    src_years = _years(" ".join(e["debut"] + " " + e["fin"] for e in src["experiences"])
                       + " " + " ".join(f["annee"] for f in src["formations"]))
    details["annees"], missing["annees"] = _recall(src_years, _years(dos_flat))
    terms = _skill_terms(src)
    got = {t for t in terms if _norm(t) in dos_norm}
    details["competences"], missing["competences"] = _recall(set(terms), got)

    # Ajouts suspects (non présents dans la source)
    allowed_nums = _numbers(flatten(masked)) | ({str(annees_calculees)} if annees_calculees else set())
    invented["chiffres"] = sorted(_numbers(dos_flat) - allowed_nums)
    src_norm = _norm(flatten(masked))
    env_terms = [re.sub(r"\(.*?\)", "", t).strip() for t in dossier["competences_cles"]
                 + [x for e in dossier["experiences"] for x in e["environnement"].split(",")]]
    invented["outils"] = sorted({t for t in env_terms if t and _norm(t) not in src_norm})

    # Similarité sémantique globale (embeddings)
    cos = None
    if use_embeddings:
        try:
            from ollama_client import embed
            cos = _cosine(embed(re.sub(r"\s+", " ", BRACKET_RE.sub(" ", src_flat))[:3000]),
                          embed(re.sub(r"\s+", " ", dos_flat)[:3000]))
            details["semantique"] = max(0.0, min(1.0, (cos - 0.5) / 0.4))
        except Exception:
            details["semantique"] = None
    else:
        details["semantique"] = None

    lex, lex_missing = _recall(_words(src_flat), _words(dos_flat))

    parts = [(details[k], W[k]) for k in W if details.get(k) is not None]
    tot = sum(w for _, w in parts)
    base = sum(v * w for v, w in parts) / tot if tot else 1.0
    penalty = min(0.2, 0.04 * (len(invented["chiffres"]) + len(invented["outils"])))
    score = max(0.0, base - penalty)
    return {"score": round(score * 100),
            "details": {k: (None if v is None else round(v, 2)) for k, v in details.items()},
            "cosinus": None if cos is None else round(cos, 3),
            "couverture_lexicale": None if lex is None else round(lex, 2),
            "manquants": {k: v[:15] for k, v in missing.items() if v},
            "ajouts_suspects": {k: v[:15] for k, v in invented.items() if v},
            "penalite": round(penalty * 100)}


def evaluate(raw_text: str, cv: dict, masked: dict, dossier: dict, annees: int = 0) -> dict:
    ex = evaluate_extraction(raw_text, cv)
    do = evaluate_dossier(masked, dossier, annees)
    return {"score_global": round(0.3 * ex["score"] + 0.7 * do["score"]),
            "extraction": ex, "dossier": do}


def summary_missing(report: dict) -> str:
    """Résumé court des éléments manquants/suspects, pour l'Excel."""
    out = []
    for lvl, d in (("extraction", report["extraction"]["manquants"]), ("dossier", report["dossier"]["manquants"])):
        for k, v in d.items():
            if v:
                out.append(f"{lvl}/{k}: " + ", ".join(map(str, v[:6])))
    for k, v in report["dossier"]["ajouts_suspects"].items():
        if v:
            out.append(f"ajouts/{k}: " + ", ".join(map(str, v[:6])))
    return " | ".join(out) or "rien"
