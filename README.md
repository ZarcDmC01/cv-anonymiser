# CV Anonymiser

Dépose un CV (PDF/DOCX/TXT) → extraction JSON par LLM local → **masquage en crochets** (`[NOM]`, `[ENTREPRISE_1]`…) →
**agent Ollama qui réécrit au style du CV de référence** (`reference/cv_reference.png`) → DOCX → PDF, stocké dans la base (service BDD).

L'agent ne voit jamais les vraies valeurs (CV déjà masqué) : il déduit le secteur (Banque, Industrie…) du contexte.
Un contrôle final relance l'agent si une donnée d'origine ou un crochet subsiste, puis masque de force en dernier recours.
Style (nom du bandeau, couleur) : `BRAND_NAME`, `BRAND_COLOR`. Exemple d'apprentissage : `reference/reference_pair.json`.

## Lancement
```
ollama serve
ollama pull qwen2.5:3b        # ou OLLAMA_MODEL=qwen2.5:7b
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe app.py      # http://localhost:8000
```
API : `POST /upload` (champ `file`), `GET /cv/{id}.pdf`, `GET /excel`.

## Modules
`parsing.py` lecture + chunking · `extract.py` LLM → JSON · `anonymise.py` crochets + contrôle de fuite · `anonymise_agent.py` agent de réécriture ·
`render.py` DOCX + PDF (Word requis) · `db.py` · `db_client.py` · `notify.py` · `pipeline.py` · `app.py`

Sorties dans `data/` : `uploads/`, `json/` (`<id>.json` original, `<id>.masked.json` crochets, `<id>.dossier.json` final), `output/`, `cv_index.xlsx`.
Variables : `OLLAMA_MODEL`, `OLLAMA_URL`, `PUBLIC_BASE_URL`, `CHUNK_CHARS`.

Attention : `cv_index.xlsx` et `data/json/<id>.json` contiennent les données d'origine non masquées.


## Architecture : deux sites, deux ports

```
 ESM ──► Site ESN (app.py, :8000) ◄──HTTP /internal + X-Internal-Key── Site Entreprises (entreprise_site/main.py, :8001) ◄── Entreprises
          base SQLite (data/cv.db), pipeline IA, PDF, site ESM            consultation, filtres, demandes d'accès
```

- **ESN (:8000)** : base de données + création des CV anonymisés + site ESM (`/esm`). Expose une API interne `/internal/*` protégée par `INTERNAL_KEY`.
- **Entreprises (:8001)** : serveur FastAPI distinct, sans base ni pipeline ; il interroge l'ESN. Il ne reçoit jamais les infos perso, sauf après acceptation d'une demande.
- **Docker** : un seul conteneur (`Dockerfile`, `docker-compose.yml`) lance les deux serveurs, un par port. Ollama reste sur l'hôte (`host.docker.internal:11434`), le PDF est produit par LibreOffice (Word sous Windows hors Docker). Données dans `./data`.
- `demarrer.bat` : Docker si disponible, sinon deux serveurs Python locaux.

| Site | URL | Fonctions |
|---|---|---|
| ESN | `:8000/esm` | ajouter un CV (PDF, DOCX, JPG, PNG…), tableau avec infos perso, répondre aux demandes d'accès |
| Entreprises | `:8001` | CV anonymisés, recherche (mot-clé, compétences, expérience), demande d'accès, infos perso après acceptation |

Comptes : créés sur `/login` de chaque site. Un compte ESM exige `ESM_INVITE_CODE` (défaut `esm-demo`). Les deux sites utilisent des cookies distincts.
Notifications : cloche sur les deux sites ; e-mails si `SMTP_HOST` (+ `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`) est défini.
