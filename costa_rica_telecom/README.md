# Monitoreo del sector telecom de Costa Rica

Lista inicial de watches para changedetection.io y un script que los registra por API.

- `watches.json`: las páginas a vigilar, con título, grupo (tag) y frecuencia de chequeo.
- `registrar_watches.py`: lee `watches.json` y crea los watches en tu instancia. Solo usa la librería estándar de Python.
- `dashboard/`: un dashboard en Streamlit para ver los precios de cada página y compararlos con el operador principal.

**Operador principal: Telecable.** Su watch está en el grupo `Principal`, que el dashboard usa como referencia
para calcular las diferencias de precio. Para cambiar el principal, mueve otro watch a ese grupo.

## Inicio rápido (un solo comando)

Con Docker Desktop abierto y Python 3 instalado, desde la carpeta del repo:

- **Windows** (PowerShell):
  ```powershell
  powershell -ExecutionPolicy Bypass -File costa_rica_telecom\iniciar.ps1
  ```
- **Mac/Linux**:
  ```bash
  bash costa_rica_telecom/iniciar.sh
  ```

El script levanta changedetection.io, lee la API key, registra los watches, instala el dashboard
y lo abre en `http://localhost:8501`. Se puede volver a correr cuando quieras: no duplica watches.

## Pasos uno por uno

1. **Levantar changedetection.io** desde la raíz del repo, con la zona horaria de Costa Rica.
   En `docker-compose.yml`, descomenta `environment:` y agrega:

   ```yaml
   environment:
     - TZ=America/Costa_Rica
   ```

   Luego:

   ```bash
   docker compose up -d
   ```

   La interfaz queda en `http://127.0.0.1:5000`.

2. **Obtener la API key**: en la interfaz, *Settings → API*. Copia la clave.

3. **Registrar los watches**:

   ```bash
   export CD_URL=http://127.0.0.1:5000
   export CD_API_KEY=tu_api_key
   python3 costa_rica_telecom/registrar_watches.py --dry-run   # revisar primero
   python3 costa_rica_telecom/registrar_watches.py
   ```

   Si una URL ya existe, el script la omite, así que puedes correrlo de nuevo después de editar la lista.

4. **Configurar notificaciones** en el grupo **CR Telecom** (*Groups → CR Telecom → Notifications*), o de forma global en *Settings → Notifications*. Ejemplos de URL:
   - Telegram: `tgram://TOKEN_DEL_BOT/ID_DEL_CHAT`
   - Email: `mailtos://usuario:clave@gmail.com?to=destino@correo.com`

5. **Afinar cada watch**: la lista apunta a las páginas de inicio. Las portadas cambian a menudo (banners, promociones), así que conviene:
   - Cambiar la URL por la página concreta (planes, tarifas, resoluciones, comunicados).
   - Usar *Filters & Triggers* con un selector CSS/XPath para vigilar solo esa sección.
   - Si una página no muestra contenido sin JavaScript, cambiar el fetcher a Chrome/Playwright
     (requiere el servicio `sockpuppetbrowser` de `docker-compose.yml`).

## Dashboard de precios

```bash
pip install -r costa_rica_telecom/dashboard/requirements.txt
export CD_URL=http://127.0.0.1:5000
export CD_API_KEY=tu_api_key
streamlit run costa_rica_telecom/dashboard/app.py
```

Se abre en `http://localhost:8501`. La URL y la API key también se pueden escribir en la barra lateral.

Qué muestra:
- **Resumen por página**: cuántos precios se encontraron, mínimo y máximo, diferencia contra el principal
  y enlace a la página.
- **Precio más bajo por página**: gráfico de barras para comparar operadores.
- **Detalle por página**: cada precio con el texto donde aparece (para saber a qué plan corresponde),
  los precios que aparecieron o desaparecieron desde la revisión anterior y su evolución en el tiempo.

Los precios se leen del texto que guarda changedetection.io en cada revisión: montos con `₡`, `¢`, `CRC`,
`$`, `US$` o `USD`. Si una página muestra muchos precios que no son de planes, agrega un filtro CSS/XPath
al watch para que solo guarde la sección de planes.

## Agregar más páginas

Copia un bloque en `watches.json` y cambia `url`, `title`, `tag` y `time_between_check`.
Las claves que empiezan con `_` (como `_nota`) son comentarios y no se envían al API.
Otros campos útiles del API: `include_filters` (selectores CSS/XPath), `ignore_text`, `trigger_text`.
La lista completa está en `docs/api-spec.yaml`.

## Buenas prácticas

- No uses intervalos de pocos minutos: cada 3 a 6 horas basta para estos sitios.
- Revisa el `robots.txt` y los términos de uso de cada sitio.
- Si algún sitio bloquea IPs fuera del país, usa un servidor o proxy en Costa Rica (*Settings → CAPTCHA & Proxies*).
