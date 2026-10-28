#!/usr/bin/env bash
# Levanta changedetection.io con Docker, registra los watches y abre el dashboard de precios.
# Uso (Mac/Linux), desde cualquier carpeta:  bash costa_rica_telecom/iniciar.sh
set -euo pipefail

CARPETA="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(dirname "$CARPETA")"
export CD_URL="${CD_URL:-http://127.0.0.1:5000}"
PYTHON="$(command -v python3 || command -v python)"

echo "1/4 Levantando changedetection.io con Docker..."
(cd "$RAIZ" && docker compose up -d)

echo "2/4 Esperando a que responda en $CD_URL ..."
for _ in $(seq 1 90); do
    curl -s -o /dev/null "$CD_URL" && break
    sleep 2
done

# La API key se genera en el primer arranque y queda guardada en el datastore del contenedor
LEER_KEY="import json,os; fs=[f for f in ('/datastore/changedetection.json','/datastore/url-watches.json') if os.path.exists(f)]; print(json.load(open(fs[0]))['settings']['application']['api_access_token'] if fs else '')"
CD_API_KEY="${CD_API_KEY:-}"
for _ in $(seq 1 30); do
    [ -n "$CD_API_KEY" ] && break
    CD_API_KEY="$(docker exec changedetection python3 -c "$LEER_KEY" 2>/dev/null || true)"
    [ -n "$CD_API_KEY" ] && break
    sleep 2
done
if [ -z "$CD_API_KEY" ]; then
    echo "No se pudo leer la API key. Cópiala de Settings > API en $CD_URL y corre:"
    echo "  CD_API_KEY=tu_api_key bash costa_rica_telecom/iniciar.sh"
    exit 1
fi
export CD_API_KEY

echo "3/4 Registrando los watches..."
"$PYTHON" "$CARPETA/registrar_watches.py"

echo "4/4 Preparando y abriendo el dashboard..."
if [ ! -d "$CARPETA/.venv" ]; then
    "$PYTHON" -m venv "$CARPETA/.venv"
fi
"$CARPETA/.venv/bin/pip" install -q -r "$CARPETA/dashboard/requirements.txt"
echo "Dashboard en http://localhost:8501  (changedetection.io en $CD_URL). Ctrl+C para cerrar el dashboard."
# Desde la carpeta del dashboard, para que Streamlit tome el tema de .streamlit/config.toml
cd "$CARPETA/dashboard"
"$CARPETA/.venv/bin/streamlit" run app.py
