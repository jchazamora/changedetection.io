# Levanta changedetection.io con Docker, registra los watches y abre el dashboard de precios.
# Uso (Windows, PowerShell), desde la carpeta del repo:
#   powershell -ExecutionPolicy Bypass -File costa_rica_telecom\iniciar.ps1
$ErrorActionPreference = 'Stop'

$Carpeta = $PSScriptRoot
$Raiz = Split-Path $Carpeta -Parent
if (-not $env:CD_URL) { $env:CD_URL = 'http://127.0.0.1:5000' }

Write-Host '1/4 Levantando changedetection.io con Docker...'
Push-Location $Raiz
docker compose up -d
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'docker compose falló. ¿Está abierto Docker Desktop?' }
Pop-Location

Write-Host "2/4 Esperando a que responda en $env:CD_URL ..."
for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-WebRequest -Uri $env:CD_URL -UseBasicParsing -TimeoutSec 5 | Out-Null; break }
    catch { Start-Sleep -Seconds 2 }
}

# La API key se genera en el primer arranque y queda guardada en el datastore del contenedor
$LeerKey = "import json,os; fs=[f for f in ('/datastore/changedetection.json','/datastore/url-watches.json') if os.path.exists(f)]; print(json.load(open(fs[0]))['settings']['application']['api_access_token'] if fs else '')"
if (-not $env:CD_API_KEY) {
    for ($i = 0; $i -lt 30; $i++) {
        $key = (docker exec changedetection python3 -c $LeerKey 2>$null | Out-String).Trim()
        if ($key) { $env:CD_API_KEY = $key; break }
        Start-Sleep -Seconds 2
    }
}
if (-not $env:CD_API_KEY) {
    throw "No se pudo leer la API key. Cópiala de Settings > API en $env:CD_URL, ejecuta `$env:CD_API_KEY='tu_api_key' y vuelve a correr este script."
}

Write-Host '3/4 Registrando los watches...'
python "$Carpeta\registrar_watches.py"

Write-Host '4/4 Preparando y abriendo el dashboard...'
if (-not (Test-Path "$Carpeta\.venv")) { python -m venv "$Carpeta\.venv" }
& "$Carpeta\.venv\Scripts\pip.exe" install -q -r "$Carpeta\dashboard\requirements.txt"
Write-Host "Dashboard en http://localhost:8501  (changedetection.io en $env:CD_URL). Ctrl+C para cerrar el dashboard."
# Desde la carpeta del dashboard, para que Streamlit tome el tema de .streamlit\config.toml
Push-Location "$Carpeta\dashboard"
try { & "$Carpeta\.venv\Scripts\streamlit.exe" run app.py }
finally { Pop-Location }
