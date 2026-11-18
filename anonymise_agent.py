"""Agent Ollama : réécrit le CV déjà masqué en crochets dans le style du CV de référence.

Étape 1 (anonymise.mask_cv, déterministe) : noms/coordonnées/employeurs -> [NOM], [ENTREPRISE_1]...
Étape 2 (ici, LLM) : réécriture en « dossier de compétences » ; l'agent ne voit jamais les vraies valeurs.

Le CV de référence (reference/cv_reference.png, transcrit dans reference/reference_pair.json)
sert de modèle : employeur -> secteur, école -> type d'établissement, synthèse de profil,
réalisations chiffrées, ligne « Environnement ».
"""
import json
import re
from datetime import date
from pathlib import Path

from anonymise import collect_terms, find_leaks, force_scrub, mask_cv
from ollama_client import chat_json

REFERENCE = json.loads((Path(__file__).parent / "reference" / "reference_pair.json").read_text(encoding="utf-8"))
MAX_RETRIES = 2

SYSTEM_PROMPT = f"""Tu es un agent d'anonymisation de CV pour un cabinet de conseil. Tu transformes \
un CV DÉJÀ MASQUÉ par des crochets (JSON) en « dossier de compétences » anonymisé, en suivant \
EXACTEMENT le style du CV de référence ci-dessous.

RÈGLES DE MASQUAGE (issues du CV de référence) :
1. Le CV contient des marqueurs entre crochets ([NOM], [VILLE], [ENTREPRISE_1], [ETABLISSEMENT_1]...). \
Ils NE DOIVENT JAMAIS apparaître dans ta réponse : aucun crochet. Retire-les des phrases ou remplace-les \
par un terme générique. Aucun nom, email, téléphone, adresse, ville, lien, date de naissance.
2. [ENTREPRISE_n] -> SECTEUR générique et court (« Banque », « Assurance », « Industrie », « E-commerce », \
« Mutuelle / santé », « Conseil », « Secteur public », « Start-up tech »...) DÉDUIT du contexte (poste, \
outils, missions). CHAQUE expérience a SON propre secteur, un seul par expérience : jamais de liste \
« A / B / C » reprenant plusieurs expériences. Jamais de nom d'entreprise, de client, de site, de produit \
ou de projet interne.
3. [ETABLISSEMENT_n] -> TYPE déduit du diplôme : « Université » (licence, master), « École d'ingénieurs » \
(diplôme d'ingénieur), « École de commerce », « IUT » (DUT, BUT), « Lycée » (baccalauréat, BTS seulement), \
« Organisme de formation ». Le diplôme est conservé sans l'établissement.
4. Les technologies, outils, certifications éditeur (Microsoft, Scrum...) et les chiffres sont CONSERVÉS.
5. « realisations » : 2 à 4 puces par expérience, phrases courtes commençant par un nom d'action ou un \
verbe, chiffres conservés. « environnement » : UNIQUEMENT les technologies citées dans CETTE expérience, \
séparées par des virgules ; ne recopie jamais la liste complète des compétences à chaque expérience.
6. « synthese » : 2 à 3 phrases à la 3e personne, sans nom ni pronom genré, qui commencent par \
« Ce profil, avec N ans d'expérience... » (N = annees_experience fourni), citent les secteurs et un ou \
deux résultats chiffrés.
7. « titre » : intitulé de poste professionnel + spécialité (« Data Analyst — Business Intelligence & Data Visualisation »).
8. « competences_cles » : 6 à 10 éléments. Expériences du plus récent au plus ancien ; « fin » = \
« aujourd'hui » si le poste est en cours.
9. N'INVENTE RIEN : tout fait, chiffre ou outil doit venir du CV d'origine.

Réponds UNIQUEMENT par un objet JSON de même forme que la « sortie » de l'exemple.

EXEMPLE — CV masqué en entrée (fictif) :
{json.dumps(REFERENCE["entree"], ensure_ascii=False)}

EXEMPLE — dossier anonymisé attendu :
{json.dumps(REFERENCE["sortie"], ensure_ascii=False)}"""


BRACKET_RE = re.compile(r"\[[A-Z_0-9…]*\]")


def _years_of_experience(cv: dict) -> int:
    years = [int(m.group()) for e in cv["experiences"]
             for m in [re.search(r"(19|20)\d{2}", e["debut"])] if m]
    return max(0, date.today().year - min(years)) if years else 0


def _s(v) -> str:
    return str(v or "").strip()


def _list(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [_s(x) for x in v if _s(x)] if isinstance(v, list) else []


def _normalize(d: dict, annees_fallback: int) -> dict:
    out = {
        "titre": _s(d.get("titre")),
        "annees_experience": annees_fallback,
        "synthese": _s(d.get("synthese")),
        "competences_cles": _list(d.get("competences_cles")),
        "experiences": [], "formations": [], "langues": [],
        "certifications": _list(d.get("certifications")),
    }
    for e in d.get("experiences") or []:
        if isinstance(e, dict):
            out["experiences"].append({
                "poste": _s(e.get("poste")), "secteur": _s(e.get("secteur")),
                "debut": _s(e.get("debut")), "fin": _s(e.get("fin")),
                "realisations": _list(e.get("realisations")), "environnement": _s(e.get("environnement"))})
    for f in d.get("formations") or []:
        if isinstance(f, dict):
            out["formations"].append({"annee": _s(f.get("annee")), "diplome": _s(f.get("diplome")),
                                      "type_etablissement": _s(f.get("type_etablissement"))})
    for l in d.get("langues") or []:
        if isinstance(l, dict):
            out["langues"].append({"langue": _s(l.get("langue")), "niveau": _s(l.get("niveau"))})
    return out


def _parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("Réponse de l'agent de masquage non JSON")
        return json.loads(m.group(0))


def _check(dossier: dict, terms: set[str]) -> list[str]:
    from anonymise import flatten
    leaks = find_leaks(dossier, terms)
    if BRACKET_RE.search(flatten(dossier)):
        leaks.append("crochets résiduels")
    return leaks


def _quality_issues(d: dict) -> list[str]:
    """Défauts de style/fidélité qui justifient de relancer l'agent (pas des fuites)."""
    issues = []
    exps = d["experiences"]
    if len(exps) > 1:
        secteurs = [e["secteur"] for e in exps]
        if len(set(secteurs)) == 1:
            issues.append("toutes les expériences ont le même secteur : donne à chacune SON secteur")
        if any(s.count("/") >= 2 for s in secteurs):
            issues.append("un secteur est une liste « A / B / C » : un seul secteur par expérience")
        envs = [e["environnement"] for e in exps if e["environnement"]]
        if len(envs) > 1 and len(set(envs)) == 1:
            issues.append("« environnement » est identique pour toutes les expériences : "
                          "ne garde que les outils propres à chacune")
    if any(not e["secteur"] for e in exps):
        issues.append("une expérience n'a pas de secteur")
    return issues


def _fix_years(d: dict, n: int) -> dict:
    """Le nombre d'années est calculé en code : on l'impose dans la synthèse."""
    if n:
        d["synthese"] = re.sub(r"\b\d+\s+ans?\b(?=\s+d['’]expérience)", f"{n} an{'s' if n > 1 else ''}",
                               d["synthese"], count=1)
    return d


def _strip_brackets(obj):
    if isinstance(obj, str):
        return re.sub(r"\s{2,}", " ", BRACKET_RE.sub("", obj)).strip()
    if isinstance(obj, list):
        return [_strip_brackets(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_brackets(v) for k, v in obj.items()}
    return obj


def build_dossier(cv: dict) -> tuple[dict, dict, list[str]]:
    """Retourne (CV masqué en crochets, dossier final, éléments masqués de force)."""
    annees = _years_of_experience(cv)
    masked = mask_cv(cv)  # étape 1 : crochets. L'agent ne reçoit JAMAIS les vraies valeurs.
    payload = {k: v for k, v in masked.items() if k != "identite"}
    payload["titre_actuel"] = masked["identite"]["titre"]
    payload["annees_experience"] = annees
    user = "CV d'origine :\n" + json.dumps(payload, ensure_ascii=False)

    terms = collect_terms(cv)
    raw = chat_json(SYSTEM_PROMPT, user, temperature=0.2)
    dossier = _normalize(_parse(raw), annees)
    leaks = _check(dossier, terms)
    issues = _quality_issues(dossier)

    for _ in range(MAX_RETRIES):
        if not leaks and not issues:
            break
        msg = ""
        if leaks:
            msg += "Informations à masquer encore présentes : " + "; ".join(leaks) + ". "
        if issues:
            msg += "Défauts à corriger : " + "; ".join(issues) + ". "
        retry = (user + "\n\nTa réponse précédente :\n" + json.dumps(dossier, ensure_ascii=False)
                 + "\n\n" + msg + "Réécris le dossier complet en corrigeant tout cela.")
        dossier = _normalize(_parse(chat_json(SYSTEM_PROMPT, retry, temperature=0.2)), annees)
        leaks = _check(dossier, terms)
        issues = _quality_issues(dossier)

    forced = leaks
    if forced:  # dernier recours : masquage déterministe
        dossier = _strip_brackets(force_scrub(dossier, terms))
    dossier["annees_experience"] = annees or dossier["annees_experience"]
    dossier = _fix_years(dossier, annees)
    return masked, dossier, forced
