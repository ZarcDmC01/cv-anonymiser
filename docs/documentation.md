# Documentation — CV Anonymiser

Pipeline locale d'anonymisation de CV : un CV (PDF, DOCX, image…) est lu, analysé par un LLM Ollama, masqué, réécrit au style d'un dossier de compétences de référence, converti en PDF et mis à disposition des entreprises sans aucune donnée personnelle.

Voir aussi : [diagramme-flux.md](diagramme-flux.md) · [diagramme-pipeline.md](diagramme-pipeline.md)

## 1. Vue d'ensemble

Deux sites FastAPI distincts, un par port :

| Site | Port | Rôle |
|---|---|---|
| **ESN** (`app.py`) | 8000 | base de données, création des CV anonymisés, site ESM, API interne |
| **Entreprises** (`entreprise_site/main.py`) | 8001 | consultation des CV anonymisés, filtres, demandes d'accès |

Le site Entreprises n'a ni base ni pipeline : il appelle l'API interne de l'ESN (`/internal/*`) avec l'en-tête `X-Internal-Key`.
Ollama (modèles IA) tourne sur la machine hôte.

## 2. Démarrage

### Prérequis
- Windows avec [Ollama](https://ollama.com) installé et Docker Desktop (recommandé) ou Python 3.12+.
- Sans Docker : Microsoft Word installé (conversion PDF) et un `venv` (créé automatiquement).

### Lancement
Double-clic sur **`demarrer.bat`**. Il :
1. démarre Ollama s'il ne répond pas ;
2. télécharge les modèles manquants (texte, vision, embeddings) ;
3. si Docker tourne : `docker compose up -d --build --remove-orphans` (un conteneur, deux ports) ; sinon lance les deux serveurs Python en local ;
4. ouvre `http://localhost:8000` (ESN) et `http://localhost:8001` (Entreprises).

Arrêt : `docker compose down`, ou fermer les fenêtres « Site ESN » / « Site Entreprises ».

### Comptes
Créés sur la page `/login` de chaque site.
- **ESM** : exige le code d'invitation `ESM_INVITE_CODE` (défaut `esm-demo`).
- **Entreprise** : inscription libre.

## 3. Utilisation

### Site ESN — `http://localhost:8000/esm`
- **📄 Anonymiser** : glisser un CV ; à la fin, aperçu du PDF, score de fidélité et alertes (fuites).
- **🔑 Demandes d'accès** : accepter ou refuser les demandes des entreprises.
- **📊 Tableau** : tous les CV avec les infos personnelles, recherche, détail (éléments manquants/suspects), lien PDF, export Excel (`/excel`).
- 🔔 : notifications ; déconnexion en haut à droite.

### Site Entreprises — `http://localhost:8001`
- **🔎 Rechercher** : filtres par mot-clé, compétences (liste séparée par des virgules, toutes requises), expérience min/max. Ouverture du PDF anonymisé.
- **Demander l'accès** à un profil (message facultatif).
- **🔑 Mes demandes** : statut ; les coordonnées du candidat apparaissent uniquement si la demande est acceptée.

## 4. Pipeline de traitement

| Étape | Module | Détail |
|---|---|---|
| Lecture | `parsing.py` | PDF (PyMuPDF), DOCX, TXT/MD, images ; OCR Tesseract ou modèle vision pour les scans ; chunks de 6000 caractères |
| Extraction | `extract.py` | LLM en mode JSON (schéma : identité, profil, expériences, formations, compétences, langues, projets, certifications, centres d'intérêt) |
| Masquage | `anonymise.py` | remplace noms, e-mails, téléphones, liens, villes, entreprises, établissements par des crochets numérotés |
| Réécriture | `anonymise_agent.py` | agent Ollama qui reformule au style du CV de référence (`reference/`), avec contrôle de fuites et de qualité |
| Rendu | `render.py` | DOCX (bandeau, synthèse, compétences, expériences…) puis PDF |
| Score | `evaluate.py` | fidélité extraction + dossier, similarité par embeddings, détection d'éléments inventés |
| Enregistrement | `db.py`, `notify.py` | base SQLite, notifications |

Détails et diagrammes : [diagramme-pipeline.md](diagramme-pipeline.md).

### Score de fidélité (0–100)
`global = 0,3 × extraction + 0,7 × dossier`
- **Extraction** : part des chiffres, années et compétences du texte brut retrouvée dans le JSON.
- **Dossier** : structure (30 %), chiffres (20 %), années (10 %), compétences (20 %), similarité sémantique par embeddings (20 %) ; −4 points par chiffre ou outil inventé (max −20).
- Interprétation : ≥ 85 bon · 70–84 à relire · < 70 à vérifier.

## 5. Données et sécurité

| Donnée | Emplacement | Sensibilité |
|---|---|---|
| CV d'origine | `data/uploads/` | **personnelle** |
| JSON extrait | `data/json/<id>.json` | **personnelle** |
| JSON masqué / dossier / rapport | `data/json/<id>.masked.json`, `.dossier.json`, `.report.json` | anonymisé |
| PDF / DOCX anonymisés | `data/output/` | anonymisé |
| Base (comptes, CV, demandes, notifications) | `data/cv.db` | contient les infos perso + mots de passe hachés (PBKDF2-SHA256) |

Mesures en place :
- l'agent de réécriture ne reçoit **jamais** l'identité réelle (uniquement le CV masqué) ;
- vérification de fuites après réécriture, purge forcée en dernier recours ;
- le site Entreprises ne reçoit les champs personnels qu'après acceptation d'une demande ;
- API interne protégée par `X-Internal-Key` ; sessions en cookie signé (HMAC), `HttpOnly`, 12 h ;
- les deux conteneurs/ports ne sont publiés que sur `127.0.0.1`.

À faire avant toute mise en ligne : changer `INTERNAL_KEY`, `SESSION_SECRET`, `ESM_INVITE_CODE`, passer en HTTPS (cookies `Secure`), protéger `data/`.

## 6. Configuration (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | serveur Ollama (`host.docker.internal` dans Docker) |
| `OLLAMA_MODEL` | `qwen2.5:3b` | extraction et réécriture |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:7b` | OCR des scans/images |
| `EMBED_MODEL` | `nomic-embed-text` | score de similarité |
| `OLLAMA_NUM_CTX` | `12288` | contexte du modèle |
| `CHUNK_CHARS` | `6000` | taille des chunks |
| `INTERNAL_KEY` | `dev-internal-key` | secret ESN ↔ Entreprises |
| `SESSION_SECRET` | généré (`data/.secret`) | signature des cookies |
| `ESM_INVITE_CODE` | `esm-demo` | création d'un compte ESM |
| `ESN_URL` | `http://127.0.0.1:8000` | adresse de l'ESN vue par le site Entreprises |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | base des liens PDF |
| `BRAND_NAME`, `BRAND_COLOR` | Fil Rouge Consulting, `9F1239` | habillage du dossier |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | vides | e-mails (optionnels) |
| `DB_PATH` | `data/cv.db` | fichier de la base |

## 7. Structure du projet

```
app.py                  Site ESN (:8000) : site ESM, upload, API interne
entreprise_site/        Site Entreprises (:8001)
  main.py · web/
pipeline.py             Orchestration d'un CV
parsing.py · extract.py · anonymise.py · anonymise_agent.py · render.py · evaluate.py
ollama_client.py        Appels HTTP à Ollama
db.py · db_client.py    Base SQLite et accès
notify.py               Notifications (cloche + e-mail)
reference/              CV de référence (image + exemple entrée/sortie)
web/                    Pages du site ESN (index.html, login.html)
data/                   uploads · json · output · cv.db
docs/                   Cette documentation et les diagrammes
Dockerfile · start.sh · docker-compose.yml · demarrer.bat
```

## 8. API

### ESN — session ESM (cookie `session_esn`)
| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/login`, `/auth/register`, `/auth/logout` | authentification |
| POST | `/upload` | traiter un CV (champ `file`) |
| GET | `/api/excel`, `/excel` | tableau (JSON) / export .xlsx |
| GET | `/api/esm/cvs/{id}`, `/cv/{id}.pdf` | détail privé / PDF |
| GET, POST | `/api/esm/requests`, `/api/esm/requests/{id}` | demandes d'accès (body `{"status":"accepted"\|"refused"}`) |
| GET, POST | `/api/notifications`, `/api/notifications/read` | notifications |

### ESN — API interne (en-tête `X-Internal-Key`)
`/internal/auth/login`, `/internal/auth/register`, `/internal/cvs`, `/internal/access-requests`, `/internal/my-requests`, `/internal/notifications`, `/internal/cv/{id}.pdf`.

### Site Entreprises — session (cookie `session_ent`)
`/auth/*`, `/api/cvs`, `/api/access-requests`, `/api/my-requests`, `/api/notifications`, `/cv/{id}.pdf`.

## 9. Dépannage

| Symptôme | Cause / solution |
|---|---|
| `500 … cudaMalloc failed: out of memory` | mémoire GPU/RAM saturée : fermer des applications, redémarrer Ollama, utiliser un modèle plus petit |
| « Ollama injoignable » | lancer `ollama serve` ; dans Docker, Ollama doit tourner sur l'hôte |
| « Modèle introuvable » | `ollama pull <modèle>` (le `.bat` le fait pour les 3 modèles) |
| « Code d'invitation ESM invalide » | utiliser `ESM_INVITE_CODE` (défaut `esm-demo`) |
| « Serveur ESN injoignable » (site Entreprises) | démarrer l'ESN ; vérifier `ESN_URL` et `INTERNAL_KEY` identiques |
| « Aucun texte lisible » | scan sans OCR : vérifier que `qwen2.5vl:7b` est installé |
| Port 8000/8001 occupé | arrêter l'ancien processus ou conteneur avant de relancer |
| Les deux sites se déconnectent | ne pas partager les noms de cookie (déjà distincts) |

## 10. Limites connues

- La conversion PDF dépend de Word (Windows, hors Docker) ou de LibreOffice (Docker) : la mise en page peut légèrement différer.
- Un petit modèle (3b) peut produire plus de relances ou un score de fidélité plus bas : surveiller le score et les « éléments suspects ».
- Les secteurs d'activité sont déduits du contexte par le LLM, pas d'une source externe.
