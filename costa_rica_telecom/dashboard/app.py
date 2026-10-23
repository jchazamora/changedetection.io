"""
Dashboard de precios del sector telecom de Costa Rica.

Lee los watches y snapshots de changedetection.io por API, extrae los precios de cada página
y los compara contra el operador principal (los watches del grupo 'Principal').

Uso:
    export CD_URL=http://127.0.0.1:5000
    export CD_API_KEY=tu_api_key
    streamlit run costa_rica_telecom/dashboard/app.py
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from precios import extraer_precios

ZONA_CR = ZoneInfo('America/Costa_Rica')
GRUPO_PRINCIPAL = 'principal'
SIMBOLO = {'CRC': '₡', 'USD': '$'}

st.set_page_config(page_title='Precios Telecom CR', page_icon='📶', layout='wide')


# --- Acceso al API de changedetection.io ---------------------------------------------------------

def _api(base_url, api_key, ruta, como_texto=False):
    resp = requests.get(f"{base_url.rstrip('/')}/api/v1/{ruta}", headers={'x-api-key': api_key}, timeout=30)
    resp.raise_for_status()
    return resp.text if como_texto else resp.json()


@st.cache_data(ttl=300, show_spinner=False)
def cargar_grupos(base_url, api_key):
    return {uuid: t['title'] for uuid, t in _api(base_url, api_key, 'tags').items()}


@st.cache_data(ttl=300, show_spinner=False)
def cargar_watches(base_url, api_key):
    return _api(base_url, api_key, 'watch')


@st.cache_data(ttl=300, show_spinner=False)
def cargar_historial(base_url, api_key, uuid):
    return sorted(_api(base_url, api_key, f'watch/{uuid}/history').keys(), key=int)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def cargar_snapshot(base_url, api_key, uuid, timestamp):
    # Un snapshot nunca cambia, así que se puede guardar en caché por mucho tiempo
    return _api(base_url, api_key, f'watch/{uuid}/history/{timestamp}', como_texto=True)


# --- Utilidades ----------------------------------------------------------------------------------

def fecha_cr(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=ZONA_CR).replace(tzinfo=None)


def formato_monto(monto, moneda):
    if pd.isna(monto):
        return '—'
    decimales = 0 if moneda == 'CRC' else 2
    return f"{SIMBOLO[moneda]}{monto:,.{decimales}f}"


def precios_de(precios, moneda):
    return [p for p in precios if p.moneda == moneda]


# --- Barra lateral -------------------------------------------------------------------------------

with st.sidebar:
    st.header('Conexión')
    base_url = st.text_input('URL de changedetection.io', os.getenv('CD_URL', 'http://127.0.0.1:5000'))
    api_key = st.text_input('API key', os.getenv('CD_API_KEY', ''), type='password',
                            help='Settings → API en changedetection.io')
    if st.button('Actualizar datos'):
        st.cache_data.clear()

if not api_key:
    st.info('Ingresa la API key de changedetection.io en la barra lateral (Settings → API).')
    st.stop()

try:
    grupos = cargar_grupos(base_url, api_key)
    watches = cargar_watches(base_url, api_key)
except requests.RequestException as e:
    st.error(f'No se pudo leer el API de changedetection.io en {base_url}: {e}')
    st.stop()

with st.sidebar:
    st.header('Filtros')
    nombres_grupos = sorted(set(grupos.values()), key=str.lower)
    grupo_elegido = st.selectbox(
        'Grupo', ['Todos'] + nombres_grupos,
        index=1 + nombres_grupos.index('CR Telecom') if 'CR Telecom' in nombres_grupos else 0,
    )
    moneda = st.radio('Moneda', ['CRC', 'USD'], format_func=lambda m: f"{SIMBOLO[m]} {m}", horizontal=True)
    max_snapshots = st.slider('Snapshots en el historial', 2, 100, 30,
                              help='Cuántas revisiones anteriores leer por página para la evolución de precios')


# --- Datos por página ----------------------------------------------------------------------------

paginas = []
with st.spinner('Leyendo snapshots...'):
    for uuid, w in watches.items():
        nombres = [grupos.get(t, '') for t in w.get('tags', [])]
        if grupo_elegido != 'Todos' and grupo_elegido not in nombres:
            continue
        historial = cargar_historial(base_url, api_key, uuid)
        precios = extraer_precios(cargar_snapshot(base_url, api_key, uuid, historial[-1])) if historial else []
        paginas.append({
            'uuid': uuid,
            'titulo': w.get('title') or w.get('page_title') or w['url'],
            'url': w.get('link') or w['url'],
            'grupos': [n for n in nombres if n],
            'principal': any(n.lower() == GRUPO_PRINCIPAL for n in nombres),
            'ultimo_chequeo': fecha_cr(w.get('last_checked')),
            'ultimo_cambio': fecha_cr(w.get('last_changed')),
            'error': w.get('last_error') or '',
            'historial': historial,
            'precios': precios,
        })

# El operador principal siempre primero
paginas.sort(key=lambda p: (not p['principal'], p['titulo'].lower()))
principales = [p for p in paginas if p['principal']]
montos_principal = [x.monto for p in principales for x in precios_de(p['precios'], moneda)]
ref_principal = min(montos_principal) if montos_principal else None
nombre_principal = principales[0]['titulo'] if principales else None


# --- Encabezado ----------------------------------------------------------------------------------

st.title('📶 Precios del sector telecom — Costa Rica')
if nombre_principal:
    st.caption(f"Operador principal: **{nombre_principal}**. Las diferencias se calculan contra su precio más bajo en {moneda}.")
else:
    st.caption("Ningún watch está en el grupo 'Principal', así que no hay referencia para comparar.")

con_precios = [p for p in paginas if precios_de(p['precios'], moneda)]
cambios = [p['ultimo_cambio'] for p in paginas if p['ultimo_cambio']]
c1, c2, c3, c4 = st.columns(4)
c1.metric('Páginas monitoreadas', len(paginas))
c2.metric(f'Con precios en {moneda}', len(con_precios))
c3.metric('Precio más bajo del principal', formato_monto(ref_principal, moneda) if ref_principal else '—')
c4.metric('Último cambio detectado', max(cambios).strftime('%d/%m %H:%M') if cambios else '—')

if not paginas:
    st.warning('No hay páginas en este grupo.')
    st.stop()


# --- Resumen por página --------------------------------------------------------------------------

st.subheader('Resumen por página')
filas = []
for p in paginas:
    montos = [x.monto for x in precios_de(p['precios'], moneda)]
    minimo = min(montos) if montos else None
    filas.append({
        '': '⭐' if p['principal'] else '',
        'Página': p['titulo'],
        'Precios': len(montos),
        'Mínimo': minimo,
        'Máximo': max(montos) if montos else None,
        'vs. principal': ((minimo - ref_principal) / ref_principal * 100) if minimo and ref_principal and not p['principal'] else None,
        'Último cambio': p['ultimo_cambio'],
        'Último chequeo': p['ultimo_chequeo'],
        'Error': p['error'],
        'Enlace': p['url'],
    })

formato_columna = '₡%,d' if moneda == 'CRC' else '$%,.2f'
st.dataframe(
    pd.DataFrame(filas),
    hide_index=True,
    column_config={
        'Mínimo': st.column_config.NumberColumn(format=formato_columna),
        'Máximo': st.column_config.NumberColumn(format=formato_columna),
        'vs. principal': st.column_config.NumberColumn(format='%+.1f%%', help='Precio mínimo comparado con el del principal'),
        'Último cambio': st.column_config.DatetimeColumn(format='DD/MM/YYYY HH:mm'),
        'Último chequeo': st.column_config.DatetimeColumn(format='DD/MM/YYYY HH:mm'),
        'Enlace': st.column_config.LinkColumn(display_text='Abrir página'),
    },
)

if len(con_precios) > 1:
    st.subheader(f'Precio más bajo por página ({moneda})')
    comparacion = pd.DataFrame(
        {'Página': p['titulo'], 'Precio más bajo': min(x.monto for x in precios_de(p['precios'], moneda))}
        for p in con_precios
    ).set_index('Página')
    st.bar_chart(comparacion, horizontal=True)


# --- Detalle por página --------------------------------------------------------------------------

st.subheader('Detalle por página')
titulos = [p['titulo'] for p in paginas]
elegida = paginas[titulos.index(st.selectbox('Página', titulos))]
st.markdown(f"[{elegida['url']}]({elegida['url']})  ·  grupos: {', '.join(elegida['grupos']) or '—'}")
if elegida['error']:
    st.error(f"Último error al revisar la página: {elegida['error']}")

if not elegida['historial']:
    st.info('Esta página todavía no tiene snapshots. Aparecerán después de la primera revisión.')
    st.stop()

actuales = precios_de(elegida['precios'], moneda)
izq, der = st.columns([3, 2])

with izq:
    st.markdown(f'**Precios en la última revisión** ({len(actuales)})')
    if actuales:
        st.dataframe(
            pd.DataFrame({'Precio': formato_monto(x.monto, moneda), 'Texto donde aparece': x.linea} for x in actuales),
            hide_index=True,
        )
    else:
        st.info(f'No se encontraron precios en {moneda} en el texto de esta página.')

# Comparación con la revisión anterior
with der:
    if len(elegida['historial']) >= 2:
        anterior_ts = elegida['historial'][-2]
        anteriores = precios_de(extraer_precios(cargar_snapshot(base_url, api_key, elegida['uuid'], anterior_ts)), moneda)
        nuevos = set(actuales) - set(anteriores)
        quitados = set(anteriores) - set(actuales)
        st.markdown(f"**Cambios contra la revisión del {fecha_cr(anterior_ts):%d/%m/%Y %H:%M}**")
        if not nuevos and not quitados:
            st.success('Sin cambios de precio.')
        for x in sorted(nuevos, key=lambda x: x.monto):
            st.markdown(f"🟢 **{formato_monto(x.monto, moneda)}** — {x.linea}")
        for x in sorted(quitados, key=lambda x: x.monto):
            st.markdown(f"🔴 ~~{formato_monto(x.monto, moneda)}~~ — {x.linea}")
    else:
        st.info('Hace falta una segunda revisión para comparar cambios.')

# Evolución en el tiempo: cada punto es un precio encontrado en una revisión
revisiones = elegida['historial'][-max_snapshots:]
serie = [
    {'Fecha': fecha_cr(ts), 'Precio': x.monto}
    for ts in revisiones
    for x in precios_de(extraer_precios(cargar_snapshot(base_url, api_key, elegida['uuid'], ts)), moneda)
]

if len(revisiones) >= 2 and serie:
    st.markdown(f'**Evolución de precios** (últimas {len(revisiones)} revisiones)')
    st.scatter_chart(pd.DataFrame(serie), x='Fecha', y='Precio')
