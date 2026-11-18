# Diagramme de flux

Qui parle à qui, et quelles données circulent. Pour le détail du traitement d'un CV, voir [diagramme-pipeline.md](diagramme-pipeline.md).

## Architecture : deux sites, deux ports

```mermaid
flowchart LR
    ESM(["👤 ESM"])
    ENT(["🏢 Entreprise"])

    subgraph DOCKER["Conteneur Docker (ou 2 processus Python en local)"]
        direction LR
        subgraph ESN["Site ESN — app.py · :8000"]
            E1["Site ESM<br/>/esm · /login"]
            E2["Pipeline CV<br/>extraction · anonymisation · PDF"]
            E3["API interne<br/>/internal/*"]
            E4[("SQLite<br/>data/cv.db")]
            E5[("PDF<br/>data/output")]
        end
        subgraph SITE2["Site Entreprises — entreprise_site/main.py · :8001"]
            S1["Pages<br/>/login · /entreprises"]
            S2["Proxy vers l'ESN<br/>(clé interne)"]
        end
    end

    OLL["Ollama (hôte) :11434<br/>texte · vision · embeddings"]

    ESM -- "HTTP, cookie session_esn" --> E1
    ENT -- "HTTP, cookie session_ent" --> S1
    E1 --> E2
    E2 -- "HTTP /api/chat · /api/embeddings" --> OLL
    E2 --> E4
    E2 --> E5
    E1 --> E4
    S1 --> S2
    S2 -- "HTTP + X-Internal-Key" --> E3
    E3 --> E4
    E3 --> E5
```

Principes de séparation :

- **Un seul propriétaire de la base** : l'ESN. Le site Entreprises n'a ni base, ni pipeline, ni accès à Ollama.
- **Le site Entreprises ne voit que de l'anonymisé** : l'API interne ne renvoie les champs personnels (nom, e-mail, téléphone, ville) qu'après une demande d'accès **acceptée** par l'ESM.
- **Deux cookies distincts** (`session_esn`, `session_ent`) : les cookies `localhost` sont partagés entre ports, sans cela les deux sites se déconnecteraient mutuellement.

## Flux 1 — Ajouter un CV (ESM)

```mermaid
sequenceDiagram
    actor ESM
    participant ESN as Site ESN :8000
    participant LLM as Ollama
    participant DB as SQLite
    participant ENT as Entreprises (cloche / e-mail)

    ESM->>ESN: POST /upload (fichier CV)
    ESN->>ESN: Lecture + chunking
    opt Page scannée / image
        ESN->>LLM: OCR (modèle vision)
        LLM-->>ESN: texte
    end
    ESN->>LLM: Extraction JSON (par chunk)
    LLM-->>ESN: données du CV
    ESN->>ESN: Masquage par crochets
    loop jusqu'à validation (max 2 relances)
        ESN->>LLM: Réécriture au style de référence
        LLM-->>ESN: dossier de compétences
        ESN->>ESN: Contrôle fuites + qualité
    end
    ESN->>ESN: DOCX puis PDF (Word ou LibreOffice)
    ESN->>LLM: Embeddings (score de fidélité)
    ESN->>DB: Enregistre CV, score, infos perso
    ESN-->>ENT: Notification « Nouveau profil disponible »
    ESN-->>ESM: id · réf · lien PDF · score
```

## Flux 2 — Rechercher et demander l'accès (Entreprise)

```mermaid
sequenceDiagram
    actor ENT as Entreprise
    participant S as Site Entreprises :8001
    participant ESN as Site ESN :8000
    participant DB as SQLite
    actor ESM

    ENT->>S: Connexion / inscription
    S->>ESN: /internal/auth/login (clé interne)
    ESN->>DB: Vérifie le compte (rôle « entreprise »)
    ESN-->>S: utilisateur
    S-->>ENT: cookie session_ent

    ENT->>S: Recherche (mot-clé, compétences, expérience)
    S->>ESN: GET /internal/cvs?filtres
    ESN->>DB: Requête sur les champs anonymisés
    ESN-->>S: profils + statut de la demande
    S-->>ENT: cartes de profils (sans info perso)

    ENT->>S: Demander l'accès à un profil
    S->>ESN: POST /internal/access-requests
    ESN->>DB: Crée la demande (statut pending)
    ESN-->>ESM: Notification « demande d'accès »

    ESM->>ESN: Accepter / refuser (onglet Demandes d'accès)
    ESN->>DB: Met à jour le statut
    ESN-->>ENT: Notification de la réponse

    ENT->>S: Mes demandes
    S->>ESN: GET /internal/my-requests
    ESN-->>S: statut + infos perso si « accepted »
    S-->>ENT: coordonnées du candidat (si acceptée)
```

## Cycle de vie d'une demande d'accès

```mermaid
stateDiagram-v2
    [*] --> pending: l'entreprise demande l'accès
    pending --> accepted: l'ESM accepte
    pending --> refused: l'ESM refuse
    accepted --> [*]: infos perso visibles par cette entreprise
    refused --> [*]
```

Une seule demande par couple (CV, entreprise) : une seconde demande renvoie une erreur 409.

## Notifications

| Événement | Destinataire | Canaux |
|---|---|---|
| Nouveau CV traité | toutes les entreprises | cloche + e-mail* |
| Demande d'accès créée | tous les comptes ESM | cloche + e-mail* |
| Demande acceptée / refusée | l'entreprise concernée | cloche + e-mail* |

\* E-mail uniquement si `SMTP_HOST` est défini ; sinon un message est écrit dans la console du serveur.
