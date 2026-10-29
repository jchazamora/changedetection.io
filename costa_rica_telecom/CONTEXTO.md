# Contexto del proyecto (para continuar en otra sesión de Claude Code)

Resumen de lo trabajado en una sesión anterior de Claude Code (en la nube) para seguir en una sesión local.

## Objetivo

Un sistema de monitoreo de páginas del sector telecom de Costa Rica, basado en este repo
(fork de changedetection.io), con:
- Detección de cambios en sitios de operadores, regulador y gobierno.
- **Telecable como operador principal** (referencia para comparar precios).
- Un dashboard en Streamlit para ver los precios y relacionarlos con cada página.
- Avisos por **correo** (pendiente, ver abajo).

El usuario escribe en español y usa Windows con Docker Desktop instalado.

## Lo que ya está hecho (rama `claude/practical-wright-lfqe2x`)

Todo está en `costa_rica_telecom/`:

| Archivo | Qué hace |
|---|---|
| `watches.json` | 8 páginas a vigilar, con grupo (tag) y frecuencia. Las claves con `_` son notas. |
| `registrar_watches.py` | Registra los watches por el API REST (`/api/v1/watch`, header `x-api-key`). Omite URLs que ya existen. Solo librería estándar. |
| `iniciar.ps1` / `iniciar.sh` | Un comando que hace todo: `docker compose up -d`, lee la API key del contenedor (`/datastore/changedetection.json` → `settings.application.api_access_token`), registra los watches, crea `.venv`, instala el dashboard y lo abre. |
| `dashboard/app.py` | Dashboard Streamlit. Lee watches, grupos y snapshots por API. Resumen por página, comparación contra el principal, detalle con el texto donde aparece cada precio, cambios contra la revisión anterior y evolución en el tiempo. |
| `dashboard/precios.py` | Extrae precios del texto de los snapshots: `₡`, `¢`, `CRC`, `$`, `US$`, `USD`. Separadores de miles `.` o `,`. |
| `dashboard/test_precios.py` | Pruebas de la extracción (`pytest` dentro de `dashboard/`). |
| `README.md` | Instrucciones en español. |

### Páginas en `watches.json`

| Sitio | URL | Grupos | Frecuencia |
|---|---|---|---|
| Telecable (principal) | https://www.telecablecr.com/ | CR Telecom, Operadores, Principal | 2 h |
| SUTEL | https://www.sutel.go.cr/ | CR Telecom, Regulador | 3 h |
| MICITT | https://www.micitt.go.cr/ | CR Telecom, Gobierno | 6 h |
| Grupo ICE | https://www.grupoice.com/ | CR Telecom, Operadores | 6 h |
| Kölbi | https://www.kolbi.cr/ | CR Telecom, Operadores | 6 h |
| Claro | https://www.claro.cr/ | CR Telecom, Operadores | 6 h |
| Tigo | https://www.tigo.cr/ | CR Telecom, Operadores | 6 h |
| Liberty | https://www.libertycr.com/ | CR Telecom, Operadores | 6 h |

El dashboard toma como principal cualquier watch del grupo `Principal`.

## Qué se probó y qué no

- Probado en la sesión en la nube: registro de watches contra una instancia real de changedetection.io,
  el dashboard con páginas de ejemplo locales (detectó un cambio de precio) e `iniciar.sh` completo con un
  Docker simulado.
- **No probado**: `iniciar.ps1` en Windows real, y ninguna URL real de Costa Rica (la red de la nube las
  bloqueaba). Las URLs son las conocidas, sin verificar. La de Telecable se dedujo de su correo de
  servicio al cliente (`@telecablecr.com`).

## Pendiente

1. **Correr todo en Windows**: `powershell -ExecutionPolicy Bypass -File costa_rica_telecom\iniciar.ps1`
   desde la carpeta del repo (no desde `C:\WINDOWS\system32`). Corregir lo que falle.
2. **Verificar las URLs** y cambiar las páginas de inicio por las páginas de **planes/tarifas** de cada
   operador (empezando por Telecable), y de resoluciones/comunicados para SUTEL y MICITT.
   El usuario debe pasar esos links.
3. Si alguna página carga los precios con JavaScript: activar el fetcher de Chrome/Playwright
   (servicio `sockpuppetbrowser` en `docker-compose.yml`).
4. Agregar filtros CSS/XPath por watch para guardar solo la sección de planes y reducir ruido.
5. **Avisos por correo** (el usuario pidió verlo después del dashboard). En changedetection.io se configura
   con una URL de Apprise en el grupo `CR Telecom` (Groups → CR Telecom → Notifications) o en
   Settings → Notifications. Por ejemplo, con Gmail y una contraseña de aplicación:
   `mailtos://usuario:contraseña_app@gmail.com?to=destino@correo.com`. Hace falta que el usuario
   indique la cuenta de envío y el correo de destino. No guardar contraseñas en el repo.

## Actualización (29/10/2026, sesión en la nube)

- La app publicada (Streamlit Community Cloud) usa `costa_rica_telecom/dashboard/app.py` de esta rama.
- Página nueva de inicio **Resumen ejecutivo** (pedido de la jefatura: muy visual, poco gráfico, legible para un
  director): semáforo por rango de velocidad, conclusiones en frases y cara a cara por competidor. Lógica en
  `datos.posicion_por_rango`, `datos.cara_a_cara` y `datos.hallazgos`.
- Página **Precios de entrada**: tabla velocidad × operador como la diapositiva de la jefatura, con la vigencia de cada
  promoción.
- Internet + TV de los cinco operadores viene de la BD Máster, octubre 2026, región Central
  (`importar_bd_maestra.py`). Solo Internet sigue siendo la captura de los sitios del 28/10/2026.
- En la BD Máster, Telecable tiene precios distintos en Huetar Norte y Pacífico Central; el dashboard usa Central.

## Actualización (página Mercado)

- Página **Mercado**: suscriptores y participación por operador (Internet fijo y TV paga), datos de SUTEL desde
  enero 2022 (`suscriptores_sutel.csv`, generado con `importar_suscriptores.py` desde los Excel de SUTEL).
- Desde enero 2026, SUTEL publica en cero a decenas de operadores pequeños que no reportaron; por defecto la página
  los quita de todos los meses para comparar la participación sobre el mismo grupo.
- En los datos, Kölbi (ICE) salta de ~238 mil a ~280 mil suscriptores de Internet en enero 2025; parece un ajuste de
  reporte, no crecimiento real.
