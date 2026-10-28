# Monitoreo del sector telecom de Costa Rica

Lista inicial de watches para changedetection.io y un script que los registra por API.

- `watches.json`: las páginas a vigilar, con título, grupo (tag) y frecuencia de chequeo.
- `registrar_watches.py`: lee `watches.json` y crea los watches en tu instancia. Solo usa la librería estándar de Python.
- `dashboard/`: un dashboard en Streamlit que compara los precios de Telecable con los de la competencia y muestra
  lo que vigila changedetection.io.
- `precios_telecable_manual.json` y `precios_competidores_manual.json`: los precios de cada plan, capturados a mano
  desde el navegador (varios sitios bloquean la lectura automática).

**Operador principal: Telecable.** Es la referencia de las comparaciones del dashboard, y su watch está en el grupo
`Principal` (marcado con ⭐ en la página de Monitoreo).

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
cd costa_rica_telecom/dashboard   # desde aquí, para que tome el tema de .streamlit/config.toml
streamlit run app.py
```

Se abre en `http://localhost:8501`, con el morado de Telecable (`#872F98`) y en modo claro u oscuro según el
sistema. Tiene tres páginas:

- **Precios**: Telecable frente a la competencia, con los precios de los dos JSON. Arriba se eligen los
  competidores, el servicio (Doble Play, Solo Internet o Internet + Telefonía) y si se compara el precio vigente
  (con la promoción) o el regular. Muestra:
  - Indicadores: el plan de entrada de Telecable, el más barato de la competencia, la diferencia típica contra la
    mediana de la competencia y en cuántos rangos de velocidad Telecable es el más barato.
  - Por rango de velocidad, dónde queda Telecable frente a la franja de precios de la competencia.
  - El plan de entrada de cada operador y las promociones publicadas.
  - Precio según la velocidad, Telecable frente a cada competidor.
  - La tabla de planes, con enlace a cada uno y descarga en CSV.
- **Planes por operador**: la información tal como se capturó, sin cálculos ni gráficos. Una sección por operador
  con sus tablas de Doble Play y Solo Internet (plan, velocidad, precio regular, precio promocional y enlace), la
  fecha y la fuente de la captura, y un CSV con todos los planes.
- **Monitoreo**: el estado de cada página que vigila changedetection.io (al día, error 403, sin texto) y, por
  página, los precios de la última revisión, los cambios contra la anterior y su evolución. Solo aparece cuando
  el dashboard tiene la API key en `CD_API_KEY` (`iniciar.ps1` e `iniciar.sh` la ponen solos). La URL y la key
  se pueden cambiar en *Conexión con changedetection.io*.

Para actualizar precios basta con editar los JSON y recargar la página. La preparación de los datos está en
`dashboard/datos.py`, con sus pruebas en `dashboard/test_datos.py`.

En Monitoreo, los precios se leen del texto que guarda changedetection.io en cada revisión: montos con `₡`, `¢`, `CRC`,
`$`, `US$` o `USD`. Si una página muestra muchos precios que no son de planes, agrega un filtro CSS/XPath
al watch para que solo guarde la sección de planes.

## Publicar el dashboard en Streamlit Community Cloud

Para abrir *Precios* y *Planes por operador* desde cualquier lugar, sin que la laptop esté encendida:

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub y elige **Create app**.
2. Repositorio `jchazamora/changedetection.io`, rama `claude/practical-wright-lfqe2x`, archivo
   `costa_rica_telecom/dashboard/app.py`.
3. En *Advanced settings*, elige Python 3.12 (el mismo con el que se probó).
4. El repo es público, así que la app nace pública. En *Settings → Sharing*, elige *Only specific people can
   view this app* e invita los correos que quieras.

Notas:

- Community Cloud toma las dependencias de `dashboard/requirements.txt` y el tema de
  `dashboard/.streamlit/config.toml`.
- Monitoreo no aparece en la nube: changedetection.io corre en la laptop y allá no hay API key.
- Para actualizar precios, edita los JSON y súbelos a la rama: la app se actualiza sola.
- El plan gratuito permite una sola app privada, y quien invites puede invitar a otras personas.

## Agregar más páginas

Copia un bloque en `watches.json` y cambia `url`, `title`, `tag` y `time_between_check`.
Las claves que empiezan con `_` (como `_nota`) son comentarios y no se envían al API.
Otros campos útiles del API: `include_filters` (selectores CSS/XPath), `ignore_text`, `trigger_text`.
La lista completa está en `docs/api-spec.yaml`.

## Buenas prácticas

- No uses intervalos de pocos minutos: cada 3 a 6 horas basta para estos sitios.
- Revisa el `robots.txt` y los términos de uso de cada sitio.
- Si algún sitio bloquea IPs fuera del país, usa un servidor o proxy en Costa Rica (*Settings → CAPTCHA & Proxies*).
