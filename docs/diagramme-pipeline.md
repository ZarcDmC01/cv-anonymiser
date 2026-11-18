# Diagramme du pipeline

Traitement d'un CV, de l'upload au PDF anonymisé (`pipeline.py` → `process_cv`).
Les diagrammes sont en [Mermaid](https://mermaid.js.org/) : ils s'affichent dans VS Code (aperçu Markdown), GitHub et GitLab.

## Vue d'ensemble

```mermaid
flowchart TD
    A[/"CV déposé par l'ESM<br/>PDF · DOCX · TXT · MD · JPG · PNG"/] --> B

    subgraph P1["1 · Lecture — parsing.py"]
        B{"Type de fichier"}
        B -- "PDF texte" --> C1["PyMuPDF<br/>texte page par page"]
        B -- "DOCX" --> C2["python-docx<br/>paragraphes + tableaux"]
        B -- "TXT / MD" --> C3["lecture directe"]
        B -- "Image ou page scannée" --> C4["OCR : Tesseract si présent,<br/>sinon modèle vision Ollama"]
        C1 --> D["Texte brut"]
        C2 --> D
        C3 --> D
        C4 --> D
        D --> E["Découpage en chunks<br/>(CHUNK_CHARS = 6000)"]
    end

    subgraph P2["2 · Extraction — extract.py"]
        E --> F["LLM Ollama (mode JSON)<br/>1 appel par chunk"]
        F --> G["Normalisation + fusion<br/>→ JSON d'origine (données perso)"]
    end

    subgraph P3["3 · Anonymisation en 2 étapes — anonymise.py · anonymise_agent.py"]
        G --> H["Étape 1 — masquage par crochets<br/>[NOM] [EMAIL] [ENTREPRISE_1]…"]
        H --> I["Étape 2 — agent Ollama<br/>réécriture au style du CV de référence<br/>(l'agent ne voit jamais l'identité réelle)"]
        I --> J{"Contrôles"}
        J -- "fuite · crochet résiduel ·<br/>qualité (secteurs, années…)" --> K{"Essais restants ?<br/>(MAX_RETRIES = 2)"}
        K -- oui --> I
        K -- non --> L["Purge forcée des fuites restantes"]
        J -- OK --> M["Dossier de compétences"]
        L --> M
    end

    subgraph P4["4 · Rendu — render.py"]
        M --> N["DOCX<br/>bandeau, synthèse, compétences,<br/>expériences, formations, langues"]
        N --> O{"Plateforme"}
        O -- "Windows" --> O1["Microsoft Word (COM)"]
        O -- "Docker / Linux" --> O2["LibreOffice (headless)"]
        O1 --> Q[("PDF anonymisé<br/>data/output/id.pdf")]
        O2 --> Q
    end

    subgraph P5["5 · Contrôle qualité — evaluate.py"]
        G --> R["Score d'extraction<br/>(recall vs texte brut)"]
        M --> S["Score du dossier<br/>chiffres · années · compétences · structure<br/>+ similarité embeddings − éléments inventés"]
        R --> T["Score global /100<br/>0,3 × extraction + 0,7 × dossier"]
        S --> T
    end

    subgraph P6["6 · Enregistrement — db.py · notify.py"]
        T --> U[("Base SQLite<br/>CV + score + infos perso<br/>+ JSON d'origine / dossier")]
        Q --> U
        U --> V["Notification aux entreprises<br/>cloche + e-mail si SMTP"]
    end

    V --> W[/"Retour à l'ESM :<br/>id · réf · lien PDF · score · fuites"/]
```

## Étapes et fichiers produits

| # | Étape | Module | Modèle Ollama | Sortie |
|---|---|---|---|---|
| 1 | Lecture + chunking | `parsing.py` | vision (`qwen2.5vl:7b`) uniquement pour les scans | texte brut |
| 2 | Extraction | `extract.py` | `OLLAMA_MODEL` (JSON) | `data/json/<id>.json` |
| 3a | Masquage par crochets | `anonymise.py` | — (code déterministe) | `data/json/<id>.masked.json` |
| 3b | Réécriture au style de référence | `anonymise_agent.py` | `OLLAMA_MODEL` | `data/json/<id>.dossier.json` |
| 4 | DOCX puis PDF | `render.py` | — | `data/output/<id>.docx` / `.pdf` |
| 5 | Score de fidélité | `evaluate.py` | `nomic-embed-text` | `data/json/<id>.report.json` |
| 6 | Base + notifications | `db.py`, `notify.py` | — | ligne dans `data/cv.db` |

## Boucle de l'agent (étape 3b)

```mermaid
flowchart LR
    A["JSON masqué<br/>(crochets)"] --> B["Prompt système<br/>règles + exemple de référence"]
    B --> C["Ollama → dossier JSON"]
    C --> D{"Fuite d'une donnée<br/>perso ? crochet restant ?"}
    D -- oui --> E["Retour d'erreur<br/>ajouté au prompt"]
    C --> F{"Qualité : même secteur partout,<br/>« A / B / C », environnement<br/>dupliqué, secteur manquant ?"}
    F -- oui --> E
    E --> C
    D -- non --> G["Années d'expérience<br/>recalculées par le code"]
    F -- non --> G
    G --> H["Dossier validé"]
```

Règles de sécurité de l'étape : l'agent ne reçoit que le CV masqué ; toute donnée personnelle encore présente après les essais est remplacée de force par `[…]` ; les années d'expérience sont calculées en code (année la plus ancienne) puis imposées dans la synthèse.

## Gestion des erreurs

| Situation | Comportement |
|---|---|
| JSON invalide renvoyé par le LLM | jusqu'à 3 essais, température +0,2 à chaque essai |
| Page scannée | OCR Tesseract, sinon modèle vision (image limitée à 1600 px, 3 essais) |
| Ollama injoignable / modèle absent | erreur claire (HTTP 422) avec la commande `ollama pull` à lancer |
| Base injoignable | le CV est quand même généré ; l'erreur est renvoyée dans `excel_error` |
| Aucun texte lisible | erreur 422 |
