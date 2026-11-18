@echo off
setlocal
cd /d "%~dp0"
title CV Anonymiser

REM Modele Ollama (modifiable) : qwen2.5:3b (defaut), qwen2.5:7b...
if "%OLLAMA_MODEL%"=="" set OLLAMA_MODEL=qwen2.5:3b
if "%OLLAMA_VISION_MODEL%"=="" set OLLAMA_VISION_MODEL=qwen2.5vl:7b
if "%EMBED_MODEL%"=="" set EMBED_MODEL=nomic-embed-text
if "%INTERNAL_KEY%"=="" set INTERNAL_KEY=dev-internal-key

REM 1. Ollama : le lance s'il ne repond pas
curl -s -o nul http://localhost:11434/api/tags
if errorlevel 1 (
    echo [..] Demarrage d'Ollama...
    start "Ollama" /min ollama serve
    timeout /t 5 /nobreak >nul
)

REM 2. Modeles : texte (extraction/reecriture), vision (OCR des scans/images), embeddings (score)
for %%M in (%OLLAMA_MODEL% %OLLAMA_VISION_MODEL% %EMBED_MODEL%) do (
    ollama list | findstr /i /b /c:"%%M" >nul
    if errorlevel 1 (
        echo [..] Telechargement du modele %%M...
        ollama pull %%M
    )
)

REM 3. Dependances (premiere fois seulement)
if not exist "venv\Scripts\python.exe" (
    echo [..] Creation du venv...
    python -m venv venv
)
venv\Scripts\python.exe -c "import fastapi, fitz, docx, openpyxl, docx2pdf, httpx" 2>nul
if errorlevel 1 (
    echo [..] Installation des dependances...
    venv\Scripts\python.exe -m pip install -q -r requirements.txt
)

REM 4. Services : Docker si disponible (un conteneur, deux ports), sinon deux serveurs Python locaux
curl -s -o nul http://localhost:8000/login
if not errorlevel 1 (
    echo [OK] Services deja actifs sur :8000 et :8001
    goto :open
)
docker info >nul 2>&1
if not errorlevel 1 (
    echo [..] Demarrage dans Docker : ESN :8000 + Entreprises :8001...
    docker compose up -d --build --remove-orphans
    timeout /t 5 /nobreak >nul
    goto :open
)
echo [..] Docker indisponible : demarrage local des deux serveurs...
set OLLAMA_URL=http://localhost:11434
start "Site Entreprises :8001" /min cmd /c "cd entreprise_site && ..env\Scripts\python.exe main.py"
start "Site ESN :8000" /min venv\Scripts\python.exe app.py
timeout /t 5 /nobreak >nul

:open
echo.
echo [OK] ESN         : http://localhost:8000  (creation des CV, base, demandes d'acces)
echo [OK] Entreprises : http://localhost:8001  (consultation, filtres, demandes d'acces)
start "" http://localhost:8000
start "" http://localhost:8001
echo.
echo Arret : docker compose down  (ou ferme les fenetres "Site ...")
pause
