#!/bin/sh
# Deux serveurs dans le même conteneur, un par port
PORT=8001 python entreprise_site/main.py &
PORT=8000 exec python app.py
