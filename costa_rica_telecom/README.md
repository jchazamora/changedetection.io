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
sistema. Tiene estas páginas:

- **Resumen ejecutivo** (la de inicio): pensada para que un director la lea en un minuto. Compara el plan más
  barato de Telecable con el más barato de la competencia en cada rango de velocidad, para Internet + TV y Solo
  Internet, y lo dice con un semáforo: verde si Telecable es más barato, amarillo si la diferencia es de 3 % o menos,
  rojo si la competencia es más barata, gris si Telecable no tiene plan. Arriba, el titular (en cuántos rangos gana
  cada lado), la diferencia típica de Telecable frente al más barato y cuántos rangos hay de cada color; luego
  "En una mirada" en tres columnas (dónde estamos bien, dónde estamos mal y cómo se mueve el mercado); el mapa de
  precios con una tarjeta por velocidad y servicio (diferencia en % y los dos precios); y una tarjeta por competidor
  con los rangos ganados, similares y perdidos.

- **Precios**: Telecable frente a la competencia, con los precios de los dos JSON. Arriba se eligen los
  competidores, el servicio (Doble Play, Solo Internet o Internet + Telefonía) y si se compara el precio vigente
  (con la promoción) o el regular. Muestra:
  - Indicadores: el plan de entrada de Telecable, el más barato de la competencia, la diferencia típica contra la
    mediana de la competencia y en cuántos rangos de velocidad Telecable es el más barato.
  - Por rango de velocidad, dónde queda Telecable frente a la franja de precios de la competencia.
  - El plan de entrada de cada operador y las promociones publicadas.
  - Precio según la velocidad, Telecable frente a cada competidor.
  - La tabla de planes, con enlace a cada uno y descarga en CSV.
- **Mercado**: suscriptores y participación de mercado de Telecable frente a Liberty, Kölbi, Tigo, Claro y "Otros",
  en Internet fijo y TV paga, con los datos de SUTEL desde enero 2022 hasta el último mes publicado. Titular con la
  posición y la participación de Telecable, indicadores (suscriptores, participación, ranking y tamaño del mercado,
  con su cambio en 12 meses), conclusiones en frases, suscriptores de Telecable y participación de cada operador al
  cierre de cada año, participación mes a mes, ranking con altas netas y "Internet y TV juntos" (suscriptores de TV
  por cada 100 de Internet). Por defecto compara solo los operadores que reportaron el último mes: SUTEL publica en
  cero a los que todavía no reportan, y eso inflaría la participación de los grandes.
- **Precios de entrada**: una tabla como la de las presentaciones, con una fila por velocidad y una columna por
  operador (Telecable primero). En cada celda, el Internet solo y el combo (Internet + TV) más baratos de ese
  operador en esa velocidad, con una etiqueta de vigencia: promoción de hasta 6 meses (amarillo), de más de 6 meses
  (azul), promoción sin plazo publicado (borde) o precio regular (morado). `▼` marca el más barato de cada
  velocidad. Cada precio abre la página del plan. Debajo, un resumen automático (quién tiene el Internet y el combo
  más baratos, y dónde queda Telecable) y la descarga en CSV. Se filtra por competidores, velocidad máxima
  (500 Mbps por defecto) y precio vigente o regular.
- **Planes por operador**: la información tal como se capturó, sin cálculos ni gráficos. Una sección por operador
  con sus tablas de Doble Play y Solo Internet (plan, velocidad, precio regular, precio promocional y enlace), la
  fecha y la fuente de la captura, y un CSV con todos los planes.
- **Monitoreo**: el estado de cada página que vigila changedetection.io (al día, error 403, sin texto) y, por
  página, los precios de la última revisión, los cambios contra la anterior y su evolución. Solo aparece cuando
  el dashboard tiene la API key en `CD_API_KEY` (`iniciar.ps1` e `iniciar.sh` la ponen solos). La URL y la key
  se pueden cambiar en *Conexión con changedetection.io*.

### Suscriptores de SUTEL

La página Mercado lee `suscriptores_sutel.csv`, que se genera desde los Excel de SUTEL de suscriptores por operador:

```bash
python3 costa_rica_telecom/importar_suscriptores.py --internet "Suscriptores por Internet.xlsx" --tv "Suscriptores por TV.xlsx"
```

Guarda desde enero 2022 hasta el último mes de cada archivo y comprueba que la suma de los operadores coincida con la
fila TOTALES. Las razones sociales se agrupan en `dashboard/mercado.py`: Liberty incluye Liberty Servicios Fijos y
Cabletica; Kölbi es el ICE; Tigo es Millicom. Después de correrlo, subir el CSV y reiniciar la app.

### Precios de Internet + TV desde la BD Máster

Los precios de Internet + TV (regular, promocional y vigencia de la promoción) se cargan desde el CSV de la BD Máster
con:

```bash
python3 costa_rica_telecom/importar_bd_maestra.py "BD_Máster_Precios_Internet_TV.csv" --mes oct-26 --region Central
```

Toma el mes y la región indicados para Telecable, Kölbi, Claro, Tigo y Liberty (los demás proveedores del archivo se
ignoran) y reemplaza la lista `internet_y_tv` de cada uno en los JSON, conservando el nombre y el enlace de los planes
que ya existían. Solo Internet no cambia: la BD Máster no lo trae. El CSV no se sube al repositorio (el repo es
público); solo quedan en los JSON los precios del mes elegido. Después de correrlo, subir los JSON y reiniciar la app.

Para actualizar precios a mano basta con editar los JSON y recargar la página. La duración de una promoción va en
`"promo_meses"` (por ejemplo `"promo_meses": 6`) junto a `"precio_anterior"`; si falta, se toma del nombre del plan
cuando dice algo como "(promo 4 meses)". La preparación de los datos está en
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
4. El repo es público, así que la app nace abierta para cualquiera con el enlace. Para pedir usuario y
   contraseña, en *Settings → Secrets* escribe un usuario por línea y guarda:

   ```toml
   [usuarios]
   jorge = "una contraseña larga"
   ana = "otra contraseña"
   ```

   Para agregar, cambiar o quitar a alguien, edita esa misma lista. Los Secrets no se suben a GitHub.

Notas:

- Community Cloud toma las dependencias de `dashboard/requirements.txt` y el tema de
  `dashboard/.streamlit/config.toml`.
- Monitoreo no aparece en la nube: changedetection.io corre en la laptop y allá no hay API key.
- Sin la sección `[usuarios]` la app no pide ingreso (así funciona en la laptop). Al recargar la página se vuelve
  a pedir el ingreso.
- Para actualizar precios, edita los JSON y súbelos a la rama. Si en unos minutos la app no muestra el cambio,
  usa *Manage app → Reboot app*.
- Otra opción, en vez de usuarios propios: *Settings → Sharing → Only specific people can view this app*, que
  pide entrar con la cuenta de Google o GitHub de cada correo invitado. El plan gratuito permite una sola app
  privada.

## Agregar más páginas

Copia un bloque en `watches.json` y cambia `url`, `title`, `tag` y `time_between_check`.
Las claves que empiezan con `_` (como `_nota`) son comentarios y no se envían al API.
Otros campos útiles del API: `include_filters` (selectores CSS/XPath), `ignore_text`, `trigger_text`.
La lista completa está en `docs/api-spec.yaml`.

## Buenas prácticas

- No uses intervalos de pocos minutos: cada 3 a 6 horas basta para estos sitios.
- Revisa el `robots.txt` y los términos de uso de cada sitio.
- Si algún sitio bloquea IPs fuera del país, usa un servidor o proxy en Costa Rica (*Settings → CAPTCHA & Proxies*).
