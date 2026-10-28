"""
Dashboard de precios del sector telecom de Costa Rica.

- Precios: compara los planes de Telecable (operador principal) con los de la competencia, con los precios
  capturados a mano en precios_telecable_manual.json y precios_competidores_manual.json (ver datos.py).
- Planes por operador: esos mismos precios tal como se capturaron, en tablas por operador, sin cálculos.
- Monitoreo: estado de las páginas que vigila changedetection.io (por API) y los precios de sus snapshots.
  Solo aparece si está definida CD_API_KEY: en Streamlit Community Cloud no hay changedetection.io al que conectarse.

Si los Secrets de Streamlit tienen una sección [usuarios], pide usuario y contraseña antes de mostrar nada (ver acceso.py).

Uso, desde esta carpeta para que tome el tema de .streamlit/config.toml:
    export CD_URL=http://127.0.0.1:5000
    export CD_API_KEY=tu_api_key
    streamlit run app.py
"""

import math
import os
import re
import time
import unicodedata
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import requests
import streamlit as st

import acceso
import datos
from precios import extraer_precios

PRINCIPAL = datos.PRINCIPAL
GRUPO_PRINCIPAL = 'principal'
ZONA_CR = ZoneInfo('America/Costa_Rica')
SIMBOLO = {'CRC': '₡', 'USD': '$'}

st.set_page_config(page_title='Precios Telecom CR', page_icon='📶', layout='wide')


# --- Colores, formas y estilos -------------------------------------------------------------------

# Telecable va en morado y la competencia en gris, para que se vea primero dónde queda Telecable. Los gráficos no
# saben si el tema es claro u oscuro (Streamlit no lo informa bien al cargar ni al cambiarlo), así que los dos colores
# se eligieron para pasar el validador de paletas (daltonismo, visión normal y contraste) sobre ambos fondos.
# El morado es apenas más claro que el de marca (#872F98), que sobre fondo oscuro no llega al contraste mínimo.
MORADO = '#9B3DAF'
GRIS = '#8A8696'

# La forma identifica a cada operador; el color solo separa a Telecable del resto
FORMAS = {PRINCIPAL: 'circle', 'Kölbi': 'square', 'Claro': 'triangle-up', 'Tigo': 'diamond', 'Liberty': 'cross'}
_FORMAS_EXTRA = ['triangle-down', 'triangle-right', 'triangle-left', 'wedge']

TAMANO_PRINCIPAL, TAMANO_COMPETENCIA = 260, 150

# Etiquetas de los ejes: "₡25 mil" y "300 Mbps" / "1 Gbps"
EJE_COLONES = "datum.value == 0 ? '₡0' : '₡' + format(datum.value / 1000, ',.0f') + ' mil'"
EJE_MBPS = "datum.value >= 1000 ? format(datum.value / 1000, '.0f') + ' Gbps' : datum.value + ' Mbps'"

ESTILOS = """
<style>
.tc-hero {
  background: linear-gradient(115deg, #872F98 0%, #6E2580 55%, #4E1A59 100%);
  border-radius: 1rem; padding: 1.5rem 1.75rem; color: #FFFFFF;
}
.tc-hero .tc-titulo { font-family: Poppins, sans-serif; font-size: 1.85rem; font-weight: 700; line-height: 1.15; }
.tc-hero .tc-sub { margin-top: .45rem; font-size: 1rem; opacity: .9; max-width: 60rem; }
.tc-hero .tc-chips { margin-top: .9rem; display: flex; flex-wrap: wrap; gap: .45rem; }
.tc-hero .tc-chip {
  background: rgba(255, 255, 255, .14); border: 1px solid rgba(255, 255, 255, .3);
  border-radius: 999px; padding: .15rem .75rem; font-size: .82rem;
}
@media (max-width: 640px) {
  .tc-hero { padding: 1.1rem 1.2rem; }
  .tc-hero .tc-titulo { font-size: 1.4rem; }
}
/* Vega dibuja en negro el texto de los gráficos en ambos temas: que use el color de texto del tema activo */
.vega-embed .mark-text.role-mark text { fill: currentColor; }
</style>
"""


def forma(operador):
    return FORMAS.get(operador) or _FORMAS_EXTRA[sum(map(ord, operador)) % len(_FORMAS_EXTRA)]


def encabezado(titulo, subtitulo, chips=()):
    chips_html = ''.join(f'<span class="tc-chip">{escape(chip)}</span>' for chip in chips)
    st.html(
        f'{ESTILOS}<div class="tc-hero"><div class="tc-titulo">{escape(titulo)}</div>'
        f'<div class="tc-sub">{escape(subtitulo)}</div><div class="tc-chips">{chips_html}</div></div>'
    )


def fecha_corta(texto):
    try:
        return datetime.strptime(texto, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return texto or '—'


# --- Gráficos de precios -------------------------------------------------------------------------

TOOLTIP = [
    alt.Tooltip('operador:N', title='Operador'),
    alt.Tooltip('plan:N', title='Plan'),
    alt.Tooltip('velocidad_txt:N', title='Velocidad'),
    alt.Tooltip('precio_txt:N', title='Precio'),
    alt.Tooltip('regular_txt:N', title='Precio regular'),
]


def _para_grafico(df):
    """Solo las columnas que usan los gráficos, con los textos de tooltips y etiquetas."""
    d = df[['operador', 'plan', 'mbps', 'rango', 'precio', 'precio_regular', 'en_promocion']].copy()
    d['velocidad_txt'] = d['mbps'].map(datos.velocidad_texto)
    d['precio_txt'] = d['precio'].map(datos.colones)
    d['regular_txt'] = [
        datos.colones(regular) if promo else 'Sin promoción' for regular, promo in zip(d['precio_regular'], d['en_promocion'])
    ]
    d['es_principal'] = (d['operador'] == PRINCIPAL).astype(int)
    d['tamano'] = d['es_principal'].map({1: TAMANO_PRINCIPAL, 0: TAMANO_COMPETENCIA})
    # Lo que lee un lector de pantalla en cada punto o barra (sin esto, Vega lee también los campos internos)
    d['descripcion'] = d['operador'] + ', ' + d['plan'] + ', ' + d['velocidad_txt'] + ', ' + d['precio_txt']
    return d


def _colores(operadores):
    return [MORADO if op == PRINCIPAL else GRIS for op in operadores]


def _escalas(operadores):
    """Color y forma por operador (Telecable primero), con una sola leyenda para los dos."""
    dominio = sorted(dict.fromkeys(operadores), key=lambda op: op != PRINCIPAL)
    # En filas de 3: una sola fila con los 5 operadores no cabe en el ancho de un celular
    leyenda = alt.Legend(title=None, orient='top', direction='horizontal', symbolSize=110, labelFontSize=12,
                         columns=3 if len(dominio) > 3 else len(dominio))
    color = alt.Color('operador:N', legend=leyenda, scale=alt.Scale(domain=dominio, range=_colores(dominio)))
    figura = alt.Shape('operador:N', legend=leyenda, scale=alt.Scale(domain=dominio, range=[forma(op) for op in dominio]))
    return color, figura


def _puntos(datos_grafico, x, y, color=None, figura=None):
    if color is None or figura is None:
        color, figura = _escalas(datos_grafico['operador'])
    puntos = alt.Chart(datos_grafico).mark_point(filled=True, opacity=1).encode(
        x=x, y=y, color=color, shape=figura, size=alt.Size('tamano:Q', scale=None, legend=None),
        order=alt.Order('es_principal:Q'), tooltip=TOOLTIP, description='descripcion:N',
    )
    # Área invisible más grande que cada punto, para que el tooltip no exija apuntar al centro
    objetivo = alt.Chart(datos_grafico).mark_point(filled=True, size=650, opacity=0.001, aria=False).encode(
        x=x, y=y, tooltip=TOOLTIP,
    )
    return puntos, objetivo


def grafico_rangos(df):
    """Por rango de velocidad: el plan más barato de cada operador sobre la franja de precios de la competencia."""
    mejores = _para_grafico(datos.mejor_por_rango(df))
    orden = [r for r in datos.ETIQUETAS_RANGO if r in set(mejores['rango'])]
    propios = mejores[mejores['es_principal'] == 1]
    competencia = mejores[mejores['es_principal'] == 0]

    # Un plan mucho más caro que los demás (como 800 Mbps a ₡164.700) aplasta al resto del gráfico: el eje llega
    # hasta 1,4 veces el plan más caro de Telecable y lo que pase de ahí queda al borde, rotulado con su precio.
    # Es un gráfico de puntos (no de barras), así que el eje puede empezar cerca del plan más barato.
    tope = None
    if not propios.empty:
        tope = math.ceil(propios['precio'].max() * 1.4 / 10000) * 10000
        if mejores['precio'].max() <= tope:
            tope = None
    piso = math.floor(mejores['precio'].min() * 0.8 / 5000) * 5000
    techo = tope or math.ceil(mejores['precio'].max() * 1.05 / 5000) * 5000
    escala = alt.Scale(domain=[piso, techo], clamp=True)
    eje = alt.Axis(labelExpr=EJE_COLONES, tickCount=6)

    def x(campo):
        return alt.X(campo, title='Precio mensual', scale=escala, axis=eje)

    y = alt.Y('rango:N', sort=orden, title=None, axis=alt.Axis(ticks=False, domain=False, labelPadding=10, labelFontSize=12))

    capas = []
    if not competencia.empty:
        franjas = competencia.groupby('rango', as_index=False).agg(minimo=('precio', 'min'), maximo=('precio', 'max'))
        franjas['desde_txt'] = franjas['minimo'].map(datos.colones)
        franjas['hasta_txt'] = franjas['maximo'].map(datos.colones)
        franjas['descripcion'] = 'Competencia en ' + franjas['rango'] + ': de ' + franjas['desde_txt'] + ' a ' + franjas['hasta_txt']
        # Gris translúcido: se ve como un gris claro sobre fondo blanco y como uno oscuro en el tema oscuro
        capas.append(alt.Chart(franjas).mark_bar(size=12, cornerRadius=6, color=GRIS, opacity=0.28).encode(
            y=y, x=x('minimo:Q'), x2='maximo:Q', description='descripcion:N',
            tooltip=[alt.Tooltip('rango:N', title='Rango'), alt.Tooltip('desde_txt:N', title='Competencia desde'),
                     alt.Tooltip('hasta_txt:N', title='Hasta')],
        ))
    capas.extend(_puntos(mejores, x('precio:Q'), y))
    if not propios.empty:
        capas.append(alt.Chart(propios).mark_text(dy=-17, fontSize=12, fontWeight=600, aria=False).encode(
            y=y, x=x('precio:Q'), text='precio_txt:N',
        ))
    recortados = mejores[mejores['precio'] > tope] if tope else mejores.iloc[0:0]
    if not recortados.empty:
        recortados = recortados.assign(etiqueta=recortados['operador'] + ' ' + recortados['precio_txt'] + ' ›', borde=tope)
        # Debajo del punto: arriba va el precio de Telecable y en pantallas angostas se encimarían
        capas.append(alt.Chart(recortados).mark_text(align='right', dx=-12, dy=16, fontSize=11, opacity=0.7,
                                                     aria=False).encode(
            y=y, x=x('borde:Q'), text='etiqueta:N',
        ))
    grafico = alt.layer(*capas).properties(height={'step': 52}).configure_view(strokeWidth=0)
    return grafico, (tope if not recortados.empty else None)


def grafico_entrada(entrada):
    """El plan más barato de cada operador, como barras horizontales con el precio en la punta."""
    d = _para_grafico(entrada)
    d['etiqueta'] = d['precio_txt'] + ' · ' + d['velocidad_txt']
    orden = d.sort_values(['precio', 'mbps'], ascending=[True, False])['operador'].tolist()
    y = alt.Y('operador:N', sort=orden, title=None, axis=alt.Axis(ticks=False, domain=False, labelPadding=10, labelFontSize=12))
    # Espacio a la derecha de la barra más larga para su etiqueta, también en el ancho de un celular
    x = alt.X('precio:Q', title=None, axis=None, scale=alt.Scale(domain=[0, d['precio'].max() * 1.9]))
    color = alt.Color('operador:N', legend=None, scale=alt.Scale(domain=orden, range=_colores(orden)))
    barras = alt.Chart(d).mark_bar(size=20, cornerRadiusEnd=4).encode(
        y=y, x=x, color=color, tooltip=TOOLTIP, description='descripcion:N',
    )
    textos = alt.Chart(d).mark_text(align='left', dx=6, fontSize=12, aria=False).encode(
        y=y, x=x, text='etiqueta:N',
    )
    return alt.layer(barras, textos).properties(height={'step': 44}).configure_view(strokeWidth=0)


def grafico_frente_a(df, competidor):
    """Precio según la velocidad: Telecable frente a un competidor."""
    d = _para_grafico(df[df['operador'].isin([PRINCIPAL, competidor])])
    # La línea une el plan más barato de cada velocidad; los puntos muestran todos los planes
    linea = d.sort_values('precio').drop_duplicates(['operador', 'mbps']).sort_values('mbps')
    x = alt.X('mbps:Q', title='Velocidad', scale=alt.Scale(type='log', domain=[90, 1150]),
              axis=alt.Axis(values=[100, 200, 300, 500, 1000], labelExpr=EJE_MBPS))
    y = alt.Y('precio:Q', title=None, scale=alt.Scale(zero=True), axis=alt.Axis(labelExpr=EJE_COLONES, tickCount=5))
    # Líneas y puntos comparten la misma codificación de color, para que la leyenda no desaparezca
    color, figura = _escalas([PRINCIPAL, competidor])
    lineas = alt.Chart(linea).mark_line(strokeWidth=2).encode(x=x, y=y, color=color, detail='operador:N')
    puntos, objetivo = _puntos(d, x, y, color, figura)
    return alt.layer(lineas, puntos, objetivo).properties(height=260).configure_view(strokeWidth=0)


# --- Página de precios ---------------------------------------------------------------------------

def _version(ruta):
    return os.path.getmtime(ruta) if os.path.exists(ruta) else None


@st.cache_data(show_spinner=False)
def cargar_planes(versiones):
    # 'versiones' son las fechas de modificación de los JSON: al editarlos, la caché se invalida sola
    return datos.cargar_planes()


def indicadores(entrada, comparacion, servicio):
    propio = entrada[entrada['operador'] == PRINCIPAL]
    otros = entrada[entrada['operador'] != PRINCIPAL]
    comparables = comparacion[comparacion['comparable']]
    k1, k2, k3, k4 = st.columns(4)

    with k1:
        if propio.empty:
            st.metric('Plan de entrada de Telecable', '—', help=f'Telecable no tiene planes de {servicio}.', border=True)
        else:
            p = propio.iloc[0]
            delta = descripcion = None
            if not otros.empty:
                o = otros.iloc[0]
                delta = datos.colones_con_signo(p['precio'] - o['precio'])
                descripcion = f"vs. {o['operador']}"
            st.metric(
                'Plan de entrada de Telecable', datos.colones(p['precio']), delta=delta, delta_color='inverse',
                delta_description=descripcion, border=True,
                help=f"{p['plan']} · {datos.velocidad_texto(p['mbps'])}. La diferencia es contra el plan más barato "
                     'de la competencia elegida.',
            )
    with k2:
        if otros.empty:
            st.metric('Más barato de la competencia', '—', border=True)
        else:
            o = otros.iloc[0]
            st.metric(
                'Más barato de la competencia', datos.colones(o['precio']),
                delta=f"{o['operador']} · {datos.velocidad_texto(o['mbps'])}", delta_color='off', delta_arrow='off',
                help=o['plan'], border=True,
            )
    with k3:
        ayuda = ('Diferencia típica (mediana) entre el plan de Telecable y la mediana de la competencia, en cada rango '
                 'de velocidad donde ambos tienen planes.')
        if comparables.empty:
            st.metric('Telecable frente a la mediana', '—', help=ayuda, border=True)
        else:
            tipica = comparables['dif_mediana_pct'].median()
            n = len(comparables)
            if tipica < 0:
                debajo = int((comparables['dif_mediana'] < 0).sum())
                delta, color, flecha = f'más barato en {debajo} de {n} rangos', 'normal', 'down'
            elif tipica > 0:
                encima = int((comparables['dif_mediana'] > 0).sum())
                delta, color, flecha = f'más caro en {encima} de {n} rangos', 'inverse', 'up'
            else:
                delta, color, flecha = 'igual a la mediana', 'off', 'off'
            st.metric('Telecable frente a la mediana', datos.porcentaje(tipica), delta=delta, delta_color=color,
                      delta_arrow=flecha, help=ayuda, border=True)
    with k4:
        ayuda = ('Rangos de velocidad en los que el plan de Telecable cuesta igual o menos que el más barato de la '
                 'competencia elegida.')
        if comparables.empty:
            st.metric('Rangos donde Telecable es el más barato', '—', help=ayuda, border=True)
        else:
            mas_barato = int(comparables['principal_mas_barato'].sum())
            st.metric('Rangos donde Telecable es el más barato', f'{mas_barato} de {len(comparables)}', help=ayuda,
                      border=True)


def tabla_rangos(comparacion):
    def mas_barato(fila):
        if pd.isna(fila['operador_mas_barato']):
            return '—'
        return f"{fila['operador_mas_barato']} · {datos.velocidad_texto(fila['mbps_mas_barato'])}"

    vista = pd.DataFrame({
        'Rango': comparacion['rango'],
        'Telecable': comparacion['precio_principal'],
        'Plan de Telecable': comparacion['plan_principal'],
        'Competencia desde': comparacion['minimo'],
        'Más barato': comparacion.apply(mas_barato, axis=1),
        'Mediana': comparacion['mediana'],
        'Telecable vs. mediana': comparacion['dif_mediana_pct'] * 100,
    })
    precio = st.column_config.NumberColumn(format='₡%,d')
    st.dataframe(vista, hide_index=True, width='stretch', placeholder='—', column_config={
        'Telecable': precio, 'Competencia desde': precio, 'Mediana': precio,
        'Telecable vs. mediana': st.column_config.NumberColumn(format='%+.1f %%'),
    })


def comparativo(df, elegidos, servicio):
    if df.empty:
        st.info('No hay planes de este servicio para los operadores elegidos.')
        return
    entrada = datos.plan_de_entrada(df)
    comparacion = datos.comparar_por_rango(df)
    tiene_principal = (df['operador'] == PRINCIPAL).any()
    if not tiene_principal:
        st.info(f'Telecable no tiene planes de {servicio}: se muestran solo los de la competencia.')

    indicadores(entrada, comparacion, servicio)

    izq, der = st.columns([3, 2], gap='medium')
    with izq.container(border=True):
        st.markdown('**¿Dónde queda Telecable en cada rango de velocidad?**')
        st.caption('Cada punto es el plan más barato de un operador en ese rango. La franja va del competidor más '
                   'barato al más caro.')
        grafico, tope = grafico_rangos(df)
        st.altair_chart(grafico, width='stretch')
        if tope:
            st.caption(f'Los planes de más de {datos.colones(tope)} quedan al borde del gráfico, con su precio real.')
        with st.expander('Ver como tabla'):
            tabla_rangos(comparacion)
    with der.container(border=True):
        st.markdown('**Plan de entrada por operador**')
        st.caption('El plan más barato de cada operador en este servicio.')
        st.altair_chart(grafico_entrada(entrada), width='stretch')
        promociones = df[df['en_promocion']].sort_values(['operador', 'mbps'])
        if not promociones.empty:
            st.markdown('**Promociones publicadas**')
            st.markdown('\n'.join(
                f"- **{p['operador']}** · {datos.velocidad_texto(p['mbps'])}: {datos.colones(p['precio_promocional'])} "
                f"(regular {datos.colones(p['precio_regular'])})"
                for _, p in promociones.iterrows()
            ))

    rivales = [op for op in elegidos if (df['operador'] == op).any()]
    if tiene_principal and rivales:
        st.subheader('Telecable frente a cada competidor')
        st.caption('Precio mensual según la velocidad, en escala logarítmica. La línea une el plan más barato de cada '
                   'velocidad.')
        for i in range(0, len(rivales), 2):
            for columna, rival in zip(st.columns(2, gap='medium'), rivales[i:i + 2]):
                with columna.container(border=True):
                    st.markdown(f'**Telecable vs. {rival}**')
                    st.altair_chart(grafico_frente_a(df, rival), width='stretch')


def tabla_planes(df, notas, servicio):
    orden = df.assign(_otro=df['operador'] != PRINCIPAL).sort_values(['_otro', 'operador', 'mbps', 'precio'])
    vista = pd.DataFrame({
        'Operador': orden['operador'],
        'Plan': orden['plan'],
        'Velocidad': orden['mbps'],
        'Precio regular': orden['precio_regular'],
        'Precio promocional': orden['precio_promocional'],
        'Enlace': orden['link'],
    })
    st.caption(f'{len(vista)} planes de {servicio}.')
    # Alto para ver hasta ~20 planes sin desplazarse dentro de la tabla
    st.dataframe(vista, hide_index=True, width='stretch', height=min(38 + 35 * len(vista), 740), placeholder='—', column_config={
        'Velocidad': st.column_config.NumberColumn(format='%d Mbps'),
        'Precio regular': st.column_config.NumberColumn(format='₡%,d'),
        'Precio promocional': st.column_config.NumberColumn(format='₡%,d', help='Vacío si el plan no tiene promoción.'),
        'Enlace': st.column_config.LinkColumn(display_text='Abrir plan'),
    })
    nombre = re.sub(r'[^a-z0-9]+', '_', servicio.lower()).strip('_')
    st.download_button('Descargar CSV', vista.to_csv(index=False).encode('utf-8-sig'), file_name=f'precios_{nombre}.csv',
                       mime='text/csv', icon=':material/download:')
    with st.expander('Fuentes y notas de captura'):
        for n in notas:
            st.markdown(f"**{n['operador']}** · capturado el {fecha_corta(n['fecha'])} · [ver fuente]({n['fuente']})")
            if n['nota']:
                st.caption(n['nota'])


def pagina_precios():
    planes, notas = cargar_planes((_version(datos.RUTA_TELECABLE), _version(datos.RUTA_COMPETIDORES)))
    competidores = [op for op in planes['operador'].unique() if op != PRINCIPAL]
    fechas = sorted(n['fecha'] for n in notas if n.get('fecha'))
    capturado = fecha_corta(fechas[-1]) if fechas else '—'
    if len(fechas) > 1 and fechas[0] != fechas[-1]:
        capturado = f'{fecha_corta(fechas[0])} al {capturado}'
    encabezado(
        'Precios de Internet y Doble Play',
        'Telecable frente a la competencia en Costa Rica, con los precios que publica cada operador.',
        chips=[f'{len(planes)} planes', f'{len(competidores)} competidores', f'Capturados: {capturado}'],
    )
    if planes.empty:
        st.warning('Todavía no hay precios: se cargan de precios_telecable_manual.json y precios_competidores_manual.json.')
        return

    # Filtros en una fila, arriba de todo lo que afectan
    servicios = [s for s in datos.SERVICIOS if (planes['servicio'] == s).any()]
    with st.container(horizontal=True, gap='medium', vertical_alignment='bottom'):
        elegidos = st.pills('Competidores', competidores, selection_mode='multi', default=competidores, key='competidores')
        servicio = st.segmented_control('Servicio', servicios, default=servicios[0], required=True, key='servicio', wrap=True)
        base = st.segmented_control(
            'Precio a comparar', ['Vigente', 'Regular'], default='Vigente', required=True, key='base',
            help='Vigente: con la promoción, si el plan tiene una. Regular: el precio sin promoción.',
        )
    elegidos = elegidos or []
    if not elegidos:
        st.info('Elige al menos un competidor para comparar. Mientras tanto se muestran solo los planes de Telecable.')
    seleccion = planes[(planes['servicio'] == servicio) & planes['operador'].isin([PRINCIPAL, *elegidos])]
    df = datos.con_precio(seleccion, base.lower())

    pestana_comparativo, pestana_planes = st.tabs(['Comparativo', 'Planes y precios'])
    with pestana_comparativo:
        comparativo(df, elegidos, servicio)
    with pestana_planes:
        tabla_planes(df, [n for n in notas if n['operador'] in {PRINCIPAL, *elegidos}], servicio)


# --- Página de planes por operador (la información tal como se capturó) ---------------------------

TITULOS_SERVICIO = {
    datos.DOBLE_PLAY: 'Doble Play (Internet + TV)',
    datos.SOLO_INTERNET: 'Solo Internet',
    datos.INTERNET_TELEFONIA: 'Internet + Telefonía',
}


def _ancla(texto):
    """'Kölbi' -> 'kolbi', para enlazar a la sección de cada operador."""
    ascii_ = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', ascii_.lower()).strip('-')


def pagina_tablas():
    planes, notas = cargar_planes((_version(datos.RUTA_TELECABLE), _version(datos.RUTA_COMPETIDORES)))
    operadores = list(planes['operador'].unique())
    encabezado(
        'Planes por operador',
        'La información tal como se capturó del sitio de cada operador, sin cálculos ni gráficos.',
        chips=[f'{len(planes)} planes', f'{len(operadores)} operadores'],
    )
    if planes.empty:
        st.warning('Todavía no hay precios: se cargan de precios_telecable_manual.json y precios_competidores_manual.json.')
        return

    st.markdown('Ir a: ' + ' · '.join(f'[{op}](#{_ancla(op)})' for op in operadores))
    todo = pd.DataFrame({
        'Operador': planes['operador'], 'Servicio': planes['servicio'], 'Plan': planes['plan'],
        'Velocidad': planes['velocidad'], 'Precio regular': planes['precio_regular'],
        'Precio promocional': planes['precio_promocional'], 'Enlace': planes['link'], 'Capturado': planes['fecha'],
    })
    st.download_button('Descargar todos los planes (CSV)', todo.to_csv(index=False).encode('utf-8-sig'),
                       file_name='planes_por_operador.csv', mime='text/csv', icon=':material/download:')

    columnas = {
        'Precio regular': st.column_config.NumberColumn(format='₡%,d'),
        'Precio promocional': st.column_config.NumberColumn(format='₡%,d', help='Vacío si el plan no tiene promoción.'),
        'Enlace': st.column_config.LinkColumn(display_text='Abrir plan'),
    }
    nota_de = {n['operador']: n for n in notas}
    for operador in operadores:
        propios = planes[planes['operador'] == operador]
        nota = nota_de.get(operador, {})
        with st.container(border=True):
            st.subheader(operador, anchor=_ancla(operador))
            fuente = nota.get('fuente')
            st.caption(f"Capturado el {fecha_corta(nota.get('fecha'))}"
                       + (f' desde [{fuente}]({fuente})' if fuente else '') + f". {nota.get('nota', '')}")
            # Doble Play y Solo Internet siempre (como en el sitio); Internet + Telefonía solo si el operador lo tiene
            servicios = [s for s in datos.SERVICIOS if s != datos.INTERNET_TELEFONIA or (propios['servicio'] == s).any()]
            for servicio in servicios:
                filas = propios[propios['servicio'] == servicio]
                st.markdown(f'**{TITULOS_SERVICIO[servicio]}**')
                if filas.empty:
                    st.info('Sin precios publicados en la página.')
                    continue
                st.dataframe(pd.DataFrame({
                    'Plan': filas['plan'],
                    'Velocidad': filas['velocidad'],
                    'Precio regular': filas['precio_regular'],
                    'Precio promocional': filas['precio_promocional'],
                    'Enlace': filas['link'],
                }), hide_index=True, width='stretch', placeholder='—', column_config=columnas)


# --- Página de monitoreo (changedetection.io) ----------------------------------------------------

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


def fecha_cr(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(int(timestamp), tz=ZONA_CR).replace(tzinfo=None)


def formato_monto(monto, moneda):
    if pd.isna(monto):
        return '—'
    if moneda == 'CRC':
        return datos.colones(monto)
    return f'{SIMBOLO[moneda]}{monto:,.2f}'


def precios_de(precios, moneda):
    return [p for p in precios if p.moneda == moneda]


def estado(watch):
    """Estado con ícono y texto, para que no dependa solo del color."""
    error = watch.get('last_error')
    if error:
        if 'no text found' in error.lower():
            return '⚠️ Sin texto'  # la página carga, pero su contenido llega por JavaScript
        codigo = re.search(r'\b([45]\d{2})\b', error)  # solo códigos HTTP de error (4xx y 5xx)
        return f'⚠️ Error {codigo.group(1)}' if codigo else '⚠️ Error'
    return '✅ Al día' if watch.get('last_checked') else '⏳ Sin revisar'


def grafico_evolucion(serie, moneda):
    eje = alt.Axis(labelExpr=EJE_COLONES) if moneda == 'CRC' else alt.Axis(format='$,.2f')
    return alt.Chart(serie).mark_point(filled=True, size=90, opacity=1, color=MORADO).encode(
        x=alt.X('Fecha:T', title=None),
        y=alt.Y('Precio:Q', title=None, axis=eje, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip('Fecha:T', title='Revisión', format='%d/%m/%Y %H:%M'), alt.Tooltip('Texto:N', title='Precio')],
    ).properties(height=260).configure_view(strokeWidth=0)


def pagina_monitoreo():
    encabezado(
        'Monitoreo de páginas',
        'Lo que changedetection.io revisa en los sitios de operadores, regulador y gobierno, y los precios que '
        'aparecen en cada revisión.',
    )
    base_url = os.getenv('CD_URL', 'http://127.0.0.1:5000')
    api_key = os.getenv('CD_API_KEY', '')
    with st.expander('Conexión con changedetection.io', expanded=not api_key, icon=':material/settings:'):
        base_url = st.text_input('URL de changedetection.io', base_url)
        api_key = st.text_input('API key', api_key, type='password', help='Settings → API en changedetection.io')
        if st.button('Actualizar datos', icon=':material/refresh:'):
            st.cache_data.clear()
    if not api_key:
        st.info('Ingresa la API key de changedetection.io (Settings → API) en la conexión de arriba.')
        return

    try:
        grupos = cargar_grupos(base_url, api_key)
        watches = cargar_watches(base_url, api_key)
    except requests.RequestException as e:
        st.error(f'No se pudo leer el API de changedetection.io en {base_url}: {e}')
        st.caption('Revisa que Docker Desktop esté abierto y que changedetection.io esté levantado '
                   '(costa_rica_telecom\\iniciar.ps1).')
        return

    nombres_grupos = sorted(set(grupos.values()), key=str.lower)
    with st.container(horizontal=True, gap='medium', vertical_alignment='bottom'):
        grupo = st.pills('Grupo', ['Todos'] + nombres_grupos, required=True, key='grupo',
                         default='CR Telecom' if 'CR Telecom' in nombres_grupos else 'Todos')
        moneda = st.segmented_control('Moneda', ['CRC', 'USD'], default='CRC', required=True, key='moneda',
                                      format_func=lambda m: f'{SIMBOLO[m]} {m}')

    paginas = []
    with st.spinner('Leyendo las revisiones...'):
        for uuid, w in watches.items():
            nombres = [grupos.get(t, '') for t in w.get('tags', [])]
            if grupo != 'Todos' and grupo not in nombres:
                continue
            historial = cargar_historial(base_url, api_key, uuid)
            precios = extraer_precios(cargar_snapshot(base_url, api_key, uuid, historial[-1])) if historial else []
            paginas.append({
                'uuid': uuid,
                'titulo': w.get('title') or w.get('page_title') or w['url'],
                'url': w.get('link') or w['url'],
                'grupos': [n for n in nombres if n],
                'principal': any(n.lower() == GRUPO_PRINCIPAL for n in nombres),
                'estado': estado(w),
                'ultimo_chequeo': fecha_cr(w.get('last_checked')),
                'ultimo_cambio': fecha_cr(w.get('last_changed')),
                'error': w.get('last_error') or '',
                'historial': historial,
                'precios': precios,
            })
    if not paginas:
        st.warning('No hay páginas en este grupo.')
        return
    paginas.sort(key=lambda p: (not p['principal'], p['titulo'].lower()))

    chequeos = [p['ultimo_chequeo'] for p in paginas if p['ultimo_chequeo']]
    cambios = [p['ultimo_cambio'] for p in paginas if p['ultimo_cambio']]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric('Páginas vigiladas', len(paginas), border=True)
    k2.metric('Con error al revisar', sum(1 for p in paginas if p['error']), border=True,
              help='Por ejemplo, un 403 cuando el sitio bloquea la lectura automática.')
    k3.metric('Última revisión', max(chequeos).strftime('%d/%m %H:%M') if chequeos else '—', border=True)
    k4.metric('Último cambio detectado', max(cambios).strftime('%d/%m %H:%M') if cambios else '—', border=True)

    st.dataframe(pd.DataFrame({
        '': ['⭐' if p['principal'] else '' for p in paginas],
        'Estado': [p['estado'] for p in paginas],
        'Página': [p['titulo'] for p in paginas],
        'Grupos': [p['grupos'] for p in paginas],
        'Revisiones': [len(p['historial']) for p in paginas],
        f'Precios en {moneda}': [len(precios_de(p['precios'], moneda)) for p in paginas],
        'Último chequeo': [p['ultimo_chequeo'] for p in paginas],
        'Último cambio': [p['ultimo_cambio'] for p in paginas],
        'Enlace': [p['url'] for p in paginas],
    }), hide_index=True, width='stretch', placeholder='—', column_config={
        '': st.column_config.TextColumn(width='small', help='Operador principal'),
        'Grupos': st.column_config.ListColumn(),
        'Último chequeo': st.column_config.DatetimeColumn(format='DD/MM/YYYY HH:mm'),
        'Último cambio': st.column_config.DatetimeColumn(format='DD/MM/YYYY HH:mm'),
        'Enlace': st.column_config.LinkColumn(display_text='Abrir página'),
    })

    st.subheader('Detalle por página')
    titulos = [p['titulo'] for p in paginas]
    elegida = paginas[titulos.index(st.selectbox('Página', titulos))]
    st.markdown(f"[{elegida['url']}]({elegida['url']})  ·  grupos: {', '.join(elegida['grupos']) or '—'}")
    if elegida['error']:
        st.error(f"Último error al revisar la página: {elegida['error']}")
    if not elegida['historial']:
        st.info('Esta página todavía no tiene snapshots. Aparecerán después de la primera revisión.')
        return

    actuales = precios_de(elegida['precios'], moneda)
    izq, der = st.columns([3, 2], gap='medium')
    with izq:
        st.markdown(f'**Precios en la última revisión** ({len(actuales)})')
        if actuales:
            st.dataframe(
                pd.DataFrame({'Precio': formato_monto(x.monto, moneda), 'Texto donde aparece': x.linea} for x in actuales),
                hide_index=True, width='stretch',
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
    revisiones = elegida['historial'][-30:]
    serie = pd.DataFrame([
        {'Fecha': fecha_cr(ts), 'Precio': x.monto, 'Texto': formato_monto(x.monto, moneda)}
        for ts in revisiones
        for x in precios_de(extraer_precios(cargar_snapshot(base_url, api_key, elegida['uuid'], ts)), moneda)
    ])
    if len(revisiones) >= 2 and not serie.empty:
        st.markdown(f'**Evolución de precios** (últimas {len(revisiones)} revisiones)')
        st.altair_chart(grafico_evolucion(serie, moneda), width='stretch')


# --- Ingreso con usuario y contraseña ------------------------------------------------------------

def pedir_ingreso(usuarios):
    """Formulario de ingreso. Al entrar guarda el usuario en la sesión y vuelve a cargar la página pedida."""
    _, centro, _ = st.columns([1, 1.4, 1])
    with centro:
        encabezado('Precios Telecom CR', 'Ingresa con tu usuario y contraseña.')
        with st.form('ingreso'):
            usuario = st.text_input('Usuario', autocomplete='username')
            clave = st.text_input('Contraseña', type='password', autocomplete='current-password')
            entrar = st.form_submit_button('Ingresar', type='primary', icon=':material/login:', width='stretch')
        if entrar:
            if acceso.credenciales_validas(usuarios, usuario, clave):
                st.session_state['usuario'] = usuario.strip().lower()
                st.rerun()
            time.sleep(1)  # frena los intentos seguidos de adivinar una contraseña
            st.error('Usuario o contraseña incorrectos.')


# --- Navegación ----------------------------------------------------------------------------------

paginas = [
    st.Page(pagina_precios, title='Precios', icon=':material/sell:', url_path='precios', default=True),
    st.Page(pagina_tablas, title='Planes por operador', icon=':material/table_rows:', url_path='planes'),
]
# changedetection.io corre en la máquina del dashboard. Sin API key (como en Streamlit Community Cloud) no hay
# nada que mostrar, y el formulario de conexión dejaría que cualquier visitante apunte el servidor a otra URL.
if os.getenv('CD_API_KEY'):
    paginas.append(
        st.Page(pagina_monitoreo, title='Monitoreo', icon=':material/monitor_heart:', url_path='monitoreo')
    )

# La sesión dura mientras la pestaña siga abierta: al recargar la página se vuelve a pedir el ingreso
usuarios = acceso.usuarios_configurados()
if usuarios and st.session_state.get('usuario') not in usuarios:
    # Con la navegación oculta, el enlace pedido (por ejemplo /planes) se abre después de ingresar
    st.navigation(paginas, position='hidden')
    pedir_ingreso(usuarios)
    st.stop()

st.navigation(paginas, position='top').run()

if usuarios:
    st.divider()
    with st.container(horizontal=True, vertical_alignment='center'):
        st.caption(f"Sesión iniciada como **{st.session_state['usuario']}**")
        if st.button('Cerrar sesión', type='tertiary', icon=':material/logout:'):
            del st.session_state['usuario']
            st.rerun()
