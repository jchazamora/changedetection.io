"""
Dashboard de precios del sector telecom de Costa Rica.

- Mercado: suscriptores y participación de mercado por operador (Internet fijo y TV paga), con los datos de SUTEL
  de suscriptores_sutel.csv (ver mercado.py).
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
import mercado
from precios import extraer_precios

PRINCIPAL = datos.PRINCIPAL
GRUPO_PRINCIPAL = 'principal'
ZONA_CR = ZoneInfo('America/Costa_Rica')
SIMBOLO = {'CRC': '₡', 'USD': '$'}

st.set_page_config(page_title='Precios Telecom CR', page_icon='📶', layout='wide')


# --- Colores, formas y estilos -------------------------------------------------------------------

# Telecable va siempre en morado y cada competidor con su color (los que definió Telecable); el gris queda para
# "Otros" y el mercado total. El morado es apenas más claro que el de marca (#872F98), que sobre fondo oscuro no
# llega al contraste mínimo.
MORADO = '#9B3DAF'
GRIS = '#8A8696'
COLOR_OPERADOR = {PRINCIPAL: MORADO, 'Tigo': '#263AC7', 'Liberty': '#4559FF', 'Claro': '#DE4633', 'Kölbi': '#2AD42E'}
# Sobre el verde de Kölbi el texto blanco no se lee: ahí va oscuro
TEXTO_OSCURO = '#241E2B'
TEXTO_SOBRE = {'Kölbi': TEXTO_OSCURO}


def color_de(operador):
    return COLOR_OPERADOR.get(operador, GRIS)


def texto_sobre(operador):
    return TEXTO_SOBRE.get(operador, '#FFFFFF')


# La forma también identifica a cada operador, para quien no distinga bien los colores
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
    return [color_de(op) for op in operadores]


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
        'Vigencia de la promoción': datos.plazo_promocion(orden),
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


# --- Página de resumen ejecutivo ------------------------------------------------------------------

# Pensada para que un director la lea en un minuto. Semáforo: verde Telecable más barato, amarillo similar, rojo la
# competencia más barata, gris sin plan. Cada estado lleva ícono y texto, así que no depende solo del color.
# Los fondos son translúcidos y el texto hereda el color del tema, para que funcione en modo claro y oscuro.
ESTILOS_RESUMEN = """
<style>
.tc-r { --verde: #1E7F4F; --amarillo: #E0A800; --rojo: #C62828; --gris: #8A8696; --morado: #872F98;
  --txt-verde: #1E7F4F; --txt-rojo: #C62828; --txt-amarillo: #8A6A00;
  --tarjeta: rgba(138, 134, 150, .06); --borde: rgba(138, 134, 150, .3); }
@media (prefers-color-scheme: dark) {
  .tc-r { --txt-verde: #5CC48E; --txt-rojo: #FF7B7B; --txt-amarillo: #F2C94C; }
}
.tc-r .tc-suave { opacity: .72; }
.tc-r a { color: inherit; }
.tc-r .tc-hero { background: linear-gradient(120deg, #9B3DAF 0%, #872F98 40%, #4E1A59 100%); color: #FFFFFF;
  border-radius: 1.3rem; padding: 1.8rem 2rem; display: grid; grid-template-columns: 1.6fr 1fr; gap: 1.8rem;
  align-items: center; box-shadow: 0 16px 36px rgba(78, 26, 89, .22); }
.tc-r .tc-eti { text-transform: uppercase; letter-spacing: .12em; font-size: .74rem; opacity: .8; font-weight: 600; }
.tc-r .tc-hero h1 { font-family: Poppins, sans-serif; font-size: 2.2rem; line-height: 1.15; margin: .4rem 0 .7rem;
  padding: 0; color: #FFFFFF; font-weight: 700; }
.tc-r .tc-hero p { margin: 0; opacity: .9; line-height: 1.5; }
.tc-r .tc-chips { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: 1rem; }
.tc-r .tc-chips span { background: rgba(255, 255, 255, .14); border: 1px solid rgba(255, 255, 255, .3);
  border-radius: 999px; padding: .15rem .75rem; font-size: .78rem; }
.tc-r .tc-indice { background: rgba(255, 255, 255, .1); border: 1px solid rgba(255, 255, 255, .24);
  border-radius: 1.1rem; padding: 1.2rem 1.3rem; text-align: center; }
.tc-r .tc-indice b { display: block; font-family: Poppins, sans-serif; font-size: 3.4rem; line-height: 1; }
.tc-r .tc-indice span { display: block; font-size: .9rem; opacity: .9; margin-top: .45rem; line-height: 1.4; }
.tc-r .tc-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: .9rem; }
.tc-r .tc-kpi { background: var(--tarjeta); border: 1px solid var(--borde); border-radius: 1.1rem; padding: 1rem 1.1rem;
  display: flex; gap: .85rem; align-items: center; }
.tc-r .tc-ic { flex: none; display: inline-flex; align-items: center; justify-content: center; color: #FFFFFF;
  font-weight: 800; background: var(--gris); }
.tc-r .tc-kpi .tc-ic { width: 2.9rem; height: 2.9rem; border-radius: .9rem; font-size: 1.25rem; }
.tc-r .tc-kpi b { display: block; font-family: Poppins, sans-serif; font-size: 2rem; line-height: 1; }
.tc-r .tc-kpi span { font-size: .84rem; opacity: .72; }
.tc-r .bien .tc-ic, .tc-r .tc-ic.bien { background: var(--verde); }
.tc-r .igual .tc-ic, .tc-r .tc-ic.igual { background: var(--amarillo); color: #241E2B; }
.tc-r .mal .tc-ic, .tc-r .tc-ic.mal { background: var(--rojo); }
.tc-r .tc-ic.mercado { background: var(--morado); }
.tc-r .tc-cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: .9rem; }
.tc-r .tc-col { background: var(--tarjeta); border: 1px solid var(--borde); border-top: 6px solid var(--gris);
  border-radius: 1.1rem; padding: 1.1rem 1.2rem; }
.tc-r .tc-col.bien { border-top-color: var(--verde); }
.tc-r .tc-col.mal { border-top-color: var(--rojo); }
.tc-r .tc-col.mercado { border-top-color: var(--morado); }
.tc-r .tc-col h4 { margin: 0 0 .7rem; padding: 0; font-size: 1.02rem; display: flex; align-items: center; gap: .5rem; }
.tc-r .tc-col h4 .tc-ic { width: 1.55rem; height: 1.55rem; border-radius: 50%; font-size: .82rem; }
.tc-r .tc-col ul { margin: 0; padding-left: 1.1rem; font-size: .9rem; line-height: 1.5; }
.tc-r .tc-col li { margin-bottom: .5rem; }
.tc-r .tc-mapa { display: grid; grid-template-columns: 9.5rem 1fr 1fr; gap: .65rem; }
.tc-r .tc-mapa-tit { font-weight: 700; padding: .1rem .2rem .4rem; border-bottom: 3px solid var(--morado); }
.tc-r .tc-mapa-rango { display: flex; align-items: center; font-weight: 700; }
.tc-r .tc-tile { border-radius: 1rem; padding: .85rem 1.05rem; background: var(--tarjeta); border: 1px solid var(--borde);
  border-left: 8px solid var(--gris); }
.tc-r .tc-tile.bien { border-left-color: var(--verde); background: linear-gradient(90deg, rgba(30, 127, 79, .14), var(--tarjeta) 65%); }
.tc-r .tc-tile.igual { border-left-color: var(--amarillo); background: linear-gradient(90deg, rgba(224, 168, 0, .17), var(--tarjeta) 65%); }
.tc-r .tc-tile.mal { border-left-color: var(--rojo); background: linear-gradient(90deg, rgba(198, 40, 40, .13), var(--tarjeta) 65%); }
.tc-r .tc-estado { font-size: .74rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; opacity: .75; }
.tc-r .bien .tc-estado { color: var(--txt-verde); opacity: 1; }
.tc-r .igual .tc-estado { color: var(--txt-amarillo); opacity: 1; }
.tc-r .mal .tc-estado { color: var(--txt-rojo); opacity: 1; }
.tc-r .tc-num { font-family: Poppins, sans-serif; font-size: 1.85rem; font-weight: 700; margin: .05rem 0 .2rem; }
.tc-r .tc-linea { font-size: .86rem; line-height: 1.45; }
.tc-r .tc-linea span { opacity: .72; }
.tc-r .tc-rivales { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: .9rem; }
.tc-r .tc-rival { background: var(--tarjeta); border: 1px solid var(--borde); border-radius: 1.1rem; padding: 1.05rem 1.15rem; }
.tc-r .tc-rival-top { display: flex; align-items: center; gap: .55rem; }
.tc-r .tc-rival-top strong { font-size: 1.15rem; flex: 1; }
.tc-r .tc-badge { font-size: .72rem; font-weight: 700; border-radius: 999px; padding: .12rem .6rem; }
.tc-r .tc-badge.mal { background: rgba(198, 40, 40, .14); color: var(--txt-rojo); }
.tc-r .tc-badge.bien { background: rgba(30, 127, 79, .14); color: var(--txt-verde); }
.tc-r .tc-badge.igual { background: rgba(224, 168, 0, .2); color: var(--txt-amarillo); }
.tc-r .tc-frase { margin: .65rem 0 .6rem; font-size: .95rem; }
.tc-r .tc-barra { display: flex; height: .75rem; border-radius: 999px; overflow: hidden; gap: 3px; }
.tc-r .tc-seg.bien { background: var(--verde); }
.tc-r .tc-seg.igual { background: var(--amarillo); }
.tc-r .tc-seg.mal { background: var(--rojo); }
.tc-r .tc-leyenda { display: flex; flex-wrap: wrap; gap: .3rem .75rem; font-size: .8rem; margin-top: .55rem; }
.tc-r .tc-leyenda span { white-space: nowrap; }
.tc-r .tc-leyenda i { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%; margin-right: .3rem; }
.tc-r i.bien { background: var(--verde); }
.tc-r i.igual { background: var(--amarillo); }
.tc-r i.mal { background: var(--rojo); }
.tc-r .tc-movil { display: none; }
@media (max-width: 900px) {
  .tc-r .tc-movil { display: inline; }
  .tc-r .tc-hero { grid-template-columns: 1fr; padding: 1.3rem 1.3rem; }
  .tc-r .tc-hero h1 { font-size: 1.6rem; }
  .tc-r .tc-kpis { grid-template-columns: repeat(2, 1fr); }
  .tc-r .tc-cols { grid-template-columns: 1fr; }
  .tc-r .tc-mapa { grid-template-columns: 1fr; }
  .tc-r .tc-mapa-tit.tc-vacia { display: none; }
  .tc-r .tc-mapa-rango { margin-top: .6rem; }
}
@media (max-width: 600px) {
  .tc-r .tc-kpi { flex-direction: column; align-items: flex-start; gap: .55rem; }
}
</style>
"""

ESTADO_CLASE = {datos.MEJOR: 'bien', datos.IGUAL: 'igual', datos.PEOR: 'mal', datos.SIN_PLAN: 'vacio',
                datos.SOLO_TELECABLE: 'vacio'}
ESTADO_TITULO = {datos.MEJOR: 'Telecable más barato', datos.IGUAL: 'Precio similar', datos.PEOR: 'Competencia más barata',
                 datos.SIN_PLAN: 'Telecable sin plan', datos.SOLO_TELECABLE: 'Sin competencia'}


def _html_resumen(cuerpo):
    st.html(f'{ESTILOS_RESUMEN}<div class="tc-r">{cuerpo}</div>')


def _pct(valor):
    return f"{'+' if valor > 0 else '−' if valor < 0 else ''}{abs(valor) * 100:.0f} %"


def _plazo(plazo):
    if plazo == 'Sin dato':
        return ' · en promoción'
    return f' · promo {escape(plazo.lower())}' if isinstance(plazo, str) and plazo else ''


def _precio(operador, precio, link):
    texto = f'{escape(operador)} <b>{escape(datos.colones(precio))}</b>'
    if isinstance(link, str) and link:
        texto = f'<a href="{escape(link)}" target="_blank" rel="noopener">{texto}</a>'
    return texto


def hero_resumen(cuenta, origen):
    comparados = cuenta['comparados']
    if cuenta[datos.PEOR] > cuenta[datos.MEJOR]:
        titular = f'La competencia tiene mejor precio en {cuenta[datos.PEOR]} de {comparados} rangos de velocidad'
    elif cuenta[datos.MEJOR] > cuenta[datos.PEOR]:
        titular = f'Telecable tiene mejor precio en {cuenta[datos.MEJOR]} de {comparados} rangos de velocidad'
    else:
        titular = 'Telecable y la competencia están parejos en precio'
    tipica = cuenta['tipica']
    indice = (f'<div class="tc-indice"><b>{_pct(tipica)}</b><span>Telecable frente al competidor más barato<br>'
              '(diferencia típica en los rangos comparados)</span></div>' if tipica is not None else '')
    chips = ''.join(f'<span>{escape(c)}</span>' for c in origen)
    _html_resumen(
        f'<div class="tc-hero"><div><div class="tc-eti">Posición de precios · Telecable vs. mercado</div>'
        f'<h1>{escape(titular)}</h1><p>Comparamos el plan más barato de Telecable con el más barato de la competencia '
        f'en cada rango de velocidad, para Internet + TV y Solo Internet.</p><div class="tc-chips">{chips}</div></div>'
        f'{indice}</div>'
    )


def kpis_resumen(cuenta):
    kpis = ''.join(
        f'<div class="tc-kpi {clase}"><div class="tc-ic">{icono}</div><div><b>{cuenta[estado]}</b>'
        f'<span>{texto}</span></div></div>'
        for estado, clase, icono, texto in (
            (datos.MEJOR, 'bien', '✓', 'rangos donde somos los más baratos'),
            (datos.IGUAL, 'igual', '=', 'rangos con precio similar'),
            (datos.PEOR, 'mal', '!', 'rangos donde la competencia es más barata'),
            (datos.SIN_PLAN, 'vacio', '–', 'rangos donde no tenemos plan'),
        )
    )
    _html_resumen(f'<div class="tc-kpis">{kpis}</div>')


def columnas_resumen(posicion, hallazgos):
    comparables = posicion[posicion['estado'].isin([datos.MEJOR, datos.IGUAL, datos.PEOR])]

    def donde(f):
        return f"<b>{escape(datos.nombre_servicio(f['servicio']))} {escape(datos.rango_texto(f['rango']))}</b>"

    bien = [f"{donde(f)}: {escape(datos.colones(f['precio']))}, {_pct(f['diferencia_pct'])} frente a {escape(f['rival'])}."
            for _, f in comparables[comparables['estado'] == datos.MEJOR].sort_values('diferencia_pct').iterrows()]
    bien += [f"{donde(f)}: precio similar a {escape(f['rival'])} ({_pct(f['diferencia_pct'])})."
             for _, f in comparables[comparables['estado'] == datos.IGUAL].iterrows()]
    mal = [f"{donde(f)}: {escape(f['rival'])} cobra {escape(datos.colones(f['precio_rival']))} "
           f"({escape(datos.velocidad_texto(f['mbps_rival']))}), Telecable {escape(datos.colones(f['precio']))} → "
           f"<b>{_pct(f['diferencia_pct'])}</b>."
           for _, f in comparables[comparables['estado'] == datos.PEOR]
           .sort_values('diferencia_pct', ascending=False).head(4).iterrows()]
    mercado = [escape(texto) for tono, texto in hallazgos if tono == 'mercado']

    def columna(clase, icono, titulo, items, vacio):
        lista = ''.join(f'<li>{i}</li>' for i in items) or f'<li>{vacio}</li>'
        return (f'<div class="tc-col {clase}"><h4><span class="tc-ic {clase}">{icono}</span>{titulo}</h4>'
                f'<ul>{lista}</ul></div>')

    _html_resumen(
        '<div class="tc-cols">'
        + columna('bien', '✓', 'Dónde estamos bien', bien, 'En ningún rango Telecable es el más barato.')
        + columna('mal', '!', 'Dónde estamos mal', mal, 'En ningún rango la competencia es más barata.')
        + columna('mercado', 'i', 'Cómo se mueve el mercado', mercado, 'Sin datos de la competencia.')
        + '</div>'
    )


def _tile(f):
    if f is None:
        return '<div class="tc-tile"><div class="tc-estado">Sin planes</div></div>'
    clase = ESTADO_CLASE[f['estado']]
    titulo = f'<div class="tc-estado">{ESTADO_TITULO[f["estado"]]}</div>'
    if f['estado'] == datos.SIN_PLAN:
        return (f'<div class="tc-tile {clase}">{titulo}<div class="tc-num">—</div><div class="tc-linea">Competencia desde '
                f"{_precio(f['rival'], f['precio_rival'], f['link_rival'])} <span>· "
                f"{escape(datos.velocidad_texto(f['mbps_rival']))}{_plazo(f['plazo_rival'])}</span></div></div>")
    if f['estado'] == datos.SOLO_TELECABLE:
        return (f'<div class="tc-tile {clase}">{titulo}<div class="tc-num">—</div><div class="tc-linea">'
                f"{_precio(datos.PRINCIPAL, f['precio'], f['link'])} <span>· {escape(datos.velocidad_texto(f['mbps']))}"
                f"</span></div></div>")
    return (f'<div class="tc-tile {clase}">{titulo}<div class="tc-num">{_pct(f["diferencia_pct"])}</div>'
            f"<div class=\"tc-linea\">{_precio(datos.PRINCIPAL, f['precio'], f['link'])} <span>· "
            f"{escape(datos.velocidad_texto(f['mbps']))}{_plazo(f['plazo'])}</span></div>"
            f"<div class=\"tc-linea\">{_precio(f['rival'], f['precio_rival'], f['link_rival'])} <span>· "
            f"{escape(datos.velocidad_texto(f['mbps_rival']))}{_plazo(f['plazo_rival'])}</span></div></div>")


def mapa_precios(posicion):
    celdas = ('<div class="tc-mapa-tit tc-vacia">Velocidad</div><div class="tc-mapa-tit tc-vacia">Internet + TV</div>'
              '<div class="tc-mapa-tit tc-vacia">Solo Internet</div>')
    for rango in [r for r in datos.ETIQUETAS_RANGO if (posicion['rango'] == r).any()]:
        celdas += f'<div class="tc-mapa-rango">{escape(rango)}</div>'
        for servicio in (datos.DOBLE_PLAY, datos.SOLO_INTERNET):
            f = posicion[(posicion['rango'] == rango) & (posicion['servicio'] == servicio)]
            tile = _tile(None if f.empty else f.iloc[0])
            # En pantallas angostas el mapa queda en una columna: cada tarjeta dice a qué servicio corresponde
            celdas += tile.replace('<div class="tc-estado">',
                                   f'<div class="tc-estado"><span class="tc-movil">{escape(datos.nombre_servicio(servicio))} · </span>', 1)
    _html_resumen(f'<div class="tc-mapa">{celdas}</div>')


def tarjetas_rivales(rivales):
    tarjetas = ''
    for _, r in rivales.iterrows():
        tipica = r['diferencia_pct'] * 100
        if tipica > 0.5:
            clase, insignia, frase = 'mal', 'Presiona', f'Telecable suele estar <b>{abs(tipica):.0f} % más caro</b>'
        elif tipica < -0.5:
            clase, insignia, frase = 'bien', 'Ventaja', f'Telecable suele estar <b>{abs(tipica):.0f} % más barato</b>'
        else:
            clase, insignia, frase = 'igual', 'Parejo', 'Precios <b>parejos</b>'
        barra = ''.join(f'<span class="tc-seg {c}" style="flex:{int(r[e])}"></span>'
                        for e, c in ((datos.MEJOR, 'bien'), (datos.IGUAL, 'igual'), (datos.PEOR, 'mal')) if r[e])
        color = color_de(r['rival'])
        tarjetas += (
            f'<div class="tc-rival"><div class="tc-rival-top"><i style="display:inline-block;width:.85rem;height:.85rem;'
            f'border-radius:50%;background:{color}"></i><strong>{escape(r["rival"])}</strong>'
            f'<span class="tc-badge {clase}">{insignia}</span></div><div class="tc-frase">{frase}</div>'
            f'<div class="tc-barra">{barra}</div><div class="tc-leyenda">'
            f'<span><i class="bien"></i>Ganamos {int(r[datos.MEJOR])}</span>'
            f'<span><i class="igual"></i>Similar {int(r[datos.IGUAL])}</span>'
            f'<span><i class="mal"></i>Perdemos {int(r[datos.PEOR])}</span></div>'
            f'<div class="tc-linea tc-suave" style="margin-top:.45rem">de {int(r["rangos"])} rangos comparados '
            '(Internet + TV y Solo Internet)</div></div>'
        )
    _html_resumen(f'<div class="tc-rivales">{tarjetas}</div>')


def pagina_resumen():
    planes, notas = cargar_planes((_version(datos.RUTA_TELECABLE), _version(datos.RUTA_COMPETIDORES)))
    if planes.empty:
        encabezado('Resumen ejecutivo', 'Dónde está Telecable frente a la competencia.')
        st.warning('Todavía no hay precios: se cargan de precios_telecable_manual.json y precios_competidores_manual.json.')
        return
    fechas = sorted(n['fecha'] for n in notas if n.get('fecha'))
    origen = [f'Solo Internet: sitios web al {fecha_corta(fechas[-1])}' if fechas else 'Solo Internet: sitios web']
    mes = datos.mes_bd_maestra()
    if mes:
        origen.insert(0, f'Internet + TV: BD Máster {mes}, región Central')
    origen.append(f'Similar = diferencia de hasta {datos.TOLERANCIA_IGUAL * 100:.0f} %')

    # El encabezado va arriba del selector, pero depende de lo que se elija en él
    cabeza = st.container()
    base = st.segmented_control(
        'Precio a comparar', ['Vigente', 'Regular'], default='Vigente', required=True, key='base_resumen',
        help='Vigente: con la promoción, si el plan tiene una. Regular: el precio sin promoción.',
    ).lower()
    posicion = datos.posicion_por_rango(planes, base)
    cuenta = datos.conteo_estados(posicion)

    with cabeza:
        hero_resumen(cuenta, origen)
        kpis_resumen(cuenta)

    st.subheader('En una mirada')
    st.caption('Lo que hay que saber, en tres columnas.')
    columnas_resumen(posicion, datos.hallazgos(planes, posicion, base))

    st.subheader('Mapa de precios por velocidad')
    st.caption('El número grande es cuánto más caro (+) o más barato (−) está Telecable frente al competidor más barato '
               'del rango. Los precios abren la página del plan.')
    mapa_precios(posicion)

    st.subheader('Frente a cada competidor')
    st.caption('Rangos de velocidad donde Telecable gana, empata o pierde contra cada uno, y su diferencia típica.')
    tarjetas_rivales(datos.resumen_por_rival(datos.cara_a_cara(planes, base)))


# --- Página de mercado (suscriptores y participación, datos de SUTEL) ----------------------------

# Cada operador con su color (ver COLOR_OPERADOR); Otros en gris claro y el mercado total en gris oscuro
MERCADO_TOTAL = 'Mercado total'
COLOR_MERCADO = {mercado.OTROS: '#C9C5D1', MERCADO_TOTAL: '#5E5A68'}
ORDEN_MERCADO = [*mercado.OPERADORES, mercado.OTROS]
# Hasta cuántos operadores se comparan a la vez en el gráfico de suscriptores
MAX_COMPARAR = 4


def color_mercado(operador):
    return COLOR_MERCADO.get(operador) or color_de(operador)


def texto_mercado(operador):
    return TEXTO_OSCURO if operador == mercado.OTROS else texto_sobre(operador)

ESTILOS_MERCADO = """
<style>
.tc-r .tc-ranking { width: 100%; border-collapse: separate; border-spacing: 0 .4rem; font-size: .92rem; }
.tc-r .tc-ranking th { text-align: left; padding: .3rem .7rem; font-weight: 600; border-bottom: 3px solid var(--morado);
  white-space: nowrap; }
.tc-r .tc-ranking td { padding: .6rem .7rem; background: var(--tarjeta); vertical-align: middle; white-space: nowrap; }
.tc-r .tc-ranking td:first-child { border-radius: .7rem 0 0 .7rem; font-weight: 800; width: 2.5rem; text-align: center; }
.tc-r .tc-ranking td:last-child { border-radius: 0 .7rem .7rem 0; }
.tc-r .tc-ranking tr.tc-propio td { background: rgba(155, 61, 175, .14); }
.tc-r .tc-cuota { display: flex; align-items: center; gap: .55rem; min-width: 13rem; }
.tc-r .tc-cuota-barra { flex: 1; height: .7rem; border-radius: 999px; background: rgba(138, 134, 150, .18); overflow: hidden; }
.tc-r .tc-cuota-barra span { display: block; height: 100%; border-radius: 999px; }
.tc-r .tc-cambio { font-weight: 700; }
.tc-r .tc-cambio.sube { color: var(--txt-verde); }
.tc-r .tc-cambio.baja { color: var(--txt-rojo); }
.tc-r .tc-hallazgos { display: grid; gap: .55rem; }
.tc-r .tc-hallazgo { display: flex; gap: .65rem; align-items: flex-start; padding: .75rem .95rem; border-radius: .8rem;
  background: var(--tarjeta); border: 1px solid var(--borde); line-height: 1.45; }
.tc-r .tc-hallazgo .tc-ic { width: 1.55rem; height: 1.55rem; border-radius: 50%; font-size: .82rem; margin-top: .05rem; }
.tc-r .tc-conv { display: grid; gap: .5rem; }
.tc-r .tc-conv-fila { display: grid; grid-template-columns: 6rem 1fr 3.5rem; gap: .6rem; align-items: center; font-size: .9rem; }
.tc-r .tc-conv-fila b { text-align: right; }
.tc-r .tc-conv-barra { height: .9rem; border-radius: 999px; background: rgba(138, 134, 150, .18); overflow: hidden; }
.tc-r .tc-conv-barra span { display: block; height: 100%; border-radius: 999px; }
.tc-r .tc-marco { overflow-x: auto; }
</style>
"""


@st.cache_data(show_spinner=False)
def cargar_suscriptores(version):
    # 'version' es la fecha de modificación del CSV: al reemplazarlo, la caché se invalida sola
    return mercado.cargar()


def _html_mercado(cuerpo):
    st.html(f'{ESTILOS_RESUMEN}{ESTILOS_MERCADO}<div class="tc-r">{cuerpo}</div>')


def _escala_mercado(operadores):
    dominio = [op for op in ORDEN_MERCADO if op in set(operadores)]
    return alt.Scale(domain=dominio, range=[color_mercado(op) for op in dominio])


def suscriptores_de(cortes, operador):
    return cortes.sum(axis=1) if operador == MERCADO_TOTAL else cortes[operador]


def _miles(valor):
    """320348 -> '320 mil'; para las etiquetas cuando las barras son angostas"""
    return f'{mercado.numero(round(valor / 1000))} mil' if valor >= 1000 else mercado.numero(valor)


def grafico_suscriptores(cortes, operadores=(PRINCIPAL,)):
    """Suscriptores al cierre de cada año y en el último mes. Con un operador: barras con el valor y una línea encima.
    Con varios: barras agrupadas por corte, cada operador con su color."""
    operadores = list(operadores)
    d = pd.concat([
        pd.DataFrame({'corte': [mercado.mes_texto(m) for m in cortes.index], 'operador': op,
                      'suscriptores': suscriptores_de(cortes, op).values})
        for op in operadores
    ], ignore_index=True)
    d['texto'] = d['suscriptores'].map(mercado.numero)
    x = alt.X('corte:N', sort=None, title=None, axis=alt.Axis(labelAngle=0, ticks=False, domain=False))
    y = alt.Y('suscriptores:Q', title=None, axis=None, scale=alt.Scale(domain=[0, max(d['suscriptores'].max(), 1) * 1.18]))
    tooltip = [alt.Tooltip('corte:N', title='Corte'), alt.Tooltip('operador:N', title='Operador'),
               alt.Tooltip('texto:N', title='Suscriptores')]

    if len(operadores) == 1:
        operador = operadores[0]
        color = color_mercado(operador)
        barras = alt.Chart(d).mark_bar(color=color, cornerRadiusTopLeft=6, cornerRadiusTopRight=6, size=46).encode(
            x=x, y=y, tooltip=tooltip)
        linea = alt.Chart(d).mark_line(color=color, strokeWidth=2, opacity=.55,
                                       point=alt.OverlayMarkDef(filled=True, size=60, color=color)).encode(x=x, y=y)
        # El valor va dentro de la barra, en un color que se lee sobre el de la barra; en una barra muy baja no cabe
        # y va encima, en gris, que se lee sobre ambos fondos
        d['alta'] = d['suscriptores'] >= d['suscriptores'].max() * .12
        dentro = alt.Chart(d[d['alta']]).mark_text(dy=14, fontSize=12, fontWeight=700, color=texto_mercado(operador),
                                                   aria=False).encode(x=x, y=y, text='texto:N')
        encima = alt.Chart(d[~d['alta']]).mark_text(dy=-14, fontSize=12, fontWeight=700, color=GRIS, aria=False).encode(
            x=x, y=y, text='texto:N')
        return alt.layer(barras, linea, dentro, encima).properties(height=300).configure_view(strokeWidth=0)

    # Varios operadores: barras una al lado de la otra, con el valor en miles encima de cada una
    d['etiqueta'] = d['suscriptores'].map(_miles)
    orden = alt.XOffset('operador:N', sort=operadores)
    color = alt.Color('operador:N', sort=operadores,
                      scale=alt.Scale(domain=operadores, range=[color_mercado(op) for op in operadores]),
                      legend=alt.Legend(title=None, orient='top', direction='horizontal', symbolType='square'))
    barras = alt.Chart(d).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=x, xOffset=orden, y=y, color=color, tooltip=tooltip)
    textos = alt.Chart(d).mark_text(dy=-8, fontSize=11, fontWeight=600, color=GRIS, aria=False).encode(
        x=x, xOffset=orden, y=y, text='etiqueta:N')
    return alt.layer(barras, textos).properties(height=320).configure_view(strokeWidth=0)


def grafico_participacion_cortes(cortes):
    """Participación de cada operador al cierre de cada año: barras apiladas al 100 %, Telecable abajo."""
    cuota = mercado.participacion(cortes)
    d = cuota.reset_index().melt(id_vars='mes', var_name='operador', value_name='cuota')
    d = d[d['cuota'] > 0]
    d['corte'] = d['mes'].map(mercado.mes_texto)
    d['orden'] = d['operador'].map({op: i for i, op in enumerate(ORDEN_MERCADO)})
    d['texto'] = [mercado.pct(c).replace(',0 %', ' %') if c >= .06 else '' for c in d['cuota']]
    d['color_texto'] = d['operador'].map(texto_mercado)
    x = alt.X('corte:N', sort=None, title=None, axis=alt.Axis(labelAngle=0, ticks=False, domain=False))
    y = alt.Y('cuota:Q', stack='normalize', title=None, axis=None)
    tooltip = [alt.Tooltip('corte:N', title='Corte'), alt.Tooltip('operador:N', title='Operador'),
               alt.Tooltip('cuota:Q', title='Participación', format='.1%')]
    color = alt.Color('operador:N', scale=_escala_mercado(d['operador']),
                      legend=alt.Legend(title=None, orient='bottom', direction='horizontal', columns=3, symbolType='square'))
    barras = alt.Chart(d).mark_bar(size=46).encode(x=x, y=y, color=color, order=alt.Order('orden:Q'), tooltip=tooltip)
    textos = alt.Chart(d).mark_text(fontSize=11, fontWeight=600, aria=False).encode(
        x=x, y=alt.Y('cuota:Q', stack='normalize', bandPosition=.5), detail='operador:N', order=alt.Order('orden:Q'),
        text='texto:N', color=alt.Color('color_texto:N', scale=None))
    return alt.layer(barras, textos).properties(height=300).configure_view(strokeWidth=0)


def grafico_participacion_mensual(tabla):
    """Participación mes a mes: cada operador con su color (Telecable más grueso) y su nombre al final de la línea."""
    cuota = mercado.participacion(tabla)[mercado.OPERADORES]
    d = cuota.reset_index().melt(id_vars='mes', var_name='operador', value_name='cuota')
    d = d[d.groupby('operador')['cuota'].transform('max') > 0]
    d['fecha'] = pd.to_datetime(d['mes'] + '-01')
    d['es_principal'] = (d['operador'] == PRINCIPAL).astype(int)
    x = alt.X('fecha:T', title=None, axis=alt.Axis(format='%Y', tickCount='year', grid=False))
    y = alt.Y('cuota:Q', title=None, axis=alt.Axis(format='.0%', tickCount=5))
    color = alt.Color('operador:N', scale=_escala_mercado(d['operador']), legend=None)
    tooltip = [alt.Tooltip('operador:N', title='Operador'), alt.Tooltip('fecha:T', title='Mes', format='%m/%Y'),
               alt.Tooltip('cuota:Q', title='Participación', format='.1%')]
    lineas = alt.Chart(d).mark_line().encode(
        x=x, y=y, color=color, size=alt.Size('es_principal:Q', scale=alt.Scale(domain=[0, 1], range=[1.8, 4]), legend=None),
        detail='operador:N', tooltip=tooltip)
    puntos = alt.Chart(d).mark_point(filled=True, size=600, opacity=.001, aria=False).encode(x=x, y=y, tooltip=tooltip)
    final = d[d['fecha'] == d['fecha'].max()].assign(etiqueta=lambda f: f['operador'] + ' ' + f['cuota'].map(mercado.pct))
    etiquetas = alt.Chart(final).mark_text(align='left', dx=8, fontSize=12, fontWeight=600, aria=False).encode(
        x=x, y=y, text='etiqueta:N', color=color)
    return (alt.layer(lineas, puntos, etiquetas).properties(height=320, padding={'right': 120})
            .configure_view(strokeWidth=0))


def ranking_mercado(res, previo):
    filas = ''
    principales = res[res['operador'] != mercado.OTROS].sort_values('suscriptores', ascending=False)
    otros = res[res['operador'] == mercado.OTROS]
    for _, r in pd.concat([principales, otros]).iterrows():
        # Un operador sin suscriptores en este servicio (Claro en TV paga) no va en el ranking
        if not r['suscriptores'] and not r.get('altas_netas'):
            continue
        clase = ' class="tc-propio"' if r['operador'] == PRINCIPAL else ''
        puesto = int(r['ranking']) if pd.notna(r['ranking']) else '–'
        celdas = (f'<td>{puesto}</td><td><b>{escape(r["operador"])}</b></td><td>{mercado.numero(r["suscriptores"])}</td>'
                  f'<td><div class="tc-cuota"><div class="tc-cuota-barra"><span style="width:{r["participacion"] * 100:.1f}%;'
                  f'background:{color_mercado(r["operador"])}">'
                  f'</span></div><b>{mercado.pct(r["participacion"])}</b></div></td>')
        if previo:
            def cambio(valor, texto):
                if pd.isna(valor):
                    return '<td>—</td>'
                sentido = 'sube' if valor > 0 else 'baja' if valor < 0 else ''
                flecha = '▲' if valor > 0 else '▼' if valor < 0 else '='
                return f'<td><span class="tc-cambio {sentido}">{flecha} {escape(texto)}</span></td>'
            celdas += cambio(r['cambio_pp'], mercado.puntos(r['cambio_pp']) if pd.notna(r['cambio_pp']) else '')
            altas = r['altas_netas']
            celdas += cambio(altas, f"{'+' if altas > 0 else '−' if altas < 0 else ''}{mercado.numero(abs(altas))}")
        filas += f'<tr{clase}>{celdas}</tr>'
    encabezados = '<th>#</th><th>Operador</th><th>Suscriptores</th><th>Participación</th>'
    if previo:
        encabezados += f'<th>Cambio en 12 meses</th><th>Altas netas desde {escape(mercado.mes_texto(previo))}</th>'
    _html_mercado(f'<div class="tc-marco"><table class="tc-ranking"><thead><tr>{encabezados}</tr></thead>'
                  f'<tbody>{filas}</tbody></table></div>')


def lista_mercado(frases):
    iconos = {'bien': ('bien', '✓'), 'mal': ('mal', '!'), 'mercado': ('mercado', 'i')}
    items = ''.join(f'<div class="tc-hallazgo"><span class="tc-ic {iconos[t][0]}">{iconos[t][1]}</span>'
                    f'<div>{escape(texto)}</div></div>' for t, texto in frases)
    _html_mercado(f'<div class="tc-hallazgos">{items}</div>')


def barras_convergencia(mes, tv_por_100):
    tv_por_100 = tv_por_100[tv_por_100 > 0].sort_values(ascending=False)
    maximo = max(tv_por_100.max(), 1)
    filas = ''.join(
        f'<div class="tc-conv-fila{" tc-propio" if op == PRINCIPAL else ""}"><span>{escape(op)}</span>'
        f'<div class="tc-conv-barra"><span style="width:{v / maximo * 100:.0f}%;background:{color_mercado(op)}"></span>'
        f'</div><b>{v:.0f}</b></div>'
        for op, v in tv_por_100.items()
    )
    _html_mercado(f'<div class="tc-conv">{filas}</div>')


def pagina_mercado():
    df = cargar_suscriptores(_version(mercado.RUTA))
    if df.empty:
        encabezado('Mercado y suscriptores', 'Suscriptores y participación de mercado por operador.')
        st.warning('Todavía no hay datos: se cargan de suscriptores_sutel.csv (ver importar_suscriptores.py).')
        return

    cabeza = st.container()
    with st.container(horizontal=True, gap='medium', vertical_alignment='bottom'):
        servicio = st.segmented_control('Servicio', mercado.SERVICIOS, default=mercado.INTERNET, required=True,
                                        key='servicio_mercado')
        comparable = st.toggle(
            'Comparar solo operadores que reportaron en el último mes', value=True, key='comparable_mercado',
            help='SUTEL publica en cero a los operadores que todavía no reportan el último mes. Activado, esos operadores '
                 'se quitan de todos los meses para que la participación se compare siempre sobre el mismo grupo.')
    if comparable:
        datos_servicio, excluidos = mercado.solo_reportados(df, servicio)
    else:
        datos_servicio, excluidos = df[df['servicio'] == servicio], mercado.sin_reporte(df, servicio, minimo=1)
    tabla = mercado.por_operador(datos_servicio, servicio)
    res, ultimo, previo = mercado.resumen(tabla)
    r = res.set_index('operador')
    propio = r.loc[PRINCIPAL]
    total = int(tabla.loc[ultimo].sum())

    with cabeza:
        puesto = int(propio['ranking'])
        titular = (f'Telecable es #{puesto} en {servicio} con {mercado.pct(propio["participacion"])} del mercado'
                   if puesto <= 3 else f'Telecable tiene {mercado.pct(propio["participacion"])} del mercado de {servicio}')
        otro = mercado.TV if servicio == mercado.INTERNET else mercado.INTERNET
        otro_res = mercado.resumen(mercado.por_operador(mercado.solo_reportados(df, otro)[0] if comparable else df, otro))[0]
        otro_propio = otro_res.set_index('operador').loc[PRINCIPAL]
        chips = ''.join(f'<span>{escape(c)}</span>' for c in (
            'Fuente: SUTEL, suscriptores por operador',
            f'{mercado.mes_texto(tabla.index[0])} a {mercado.mes_texto(ultimo)}',
            f'En {otro}: #{int(otro_propio["ranking"])} con {mercado.pct(otro_propio["participacion"])}',
        ))
        _html_mercado(
            f'<div class="tc-hero"><div><div class="tc-eti">Participación de mercado · {escape(servicio)}</div>'
            f'<h1>{escape(titular).replace(" %", "&nbsp;%")}</h1><p>{mercado.numero(propio["suscriptores"])} suscriptores de un total de '
            f'{mercado.numero(total)} en {escape(mercado.mes_texto(ultimo))}. Telecable frente a Liberty, Kölbi, Tigo, '
            f'Claro y el resto de los operadores.</p><div class="tc-chips">{chips}</div></div>'
            f'<div class="tc-indice"><b>{mercado.pct(propio["participacion"])}</b>'
            f'<span>del mercado de {escape(servicio)}<br>{escape(mercado.mes_texto(ultimo))}</span></div></div>'
        )
        if previo:
            total_previo = int(tabla.loc[previo].sum())
            kpis = [
                ('bien' if propio['altas_netas'] >= 0 else 'mal', '▲' if propio['altas_netas'] >= 0 else '▼',
                 mercado.numero(propio['suscriptores']),
                 f"suscriptores · {'+' if propio['altas_netas'] >= 0 else '−'}{mercado.numero(abs(propio['altas_netas']))} en 12 meses"),
                ('bien' if propio['cambio_pp'] >= 0 else 'mal', '%', mercado.pct(propio['participacion']),
                 f"participación · {mercado.puntos(propio['cambio_pp'])} en 12 meses"),
                ('bien' if puesto == 1 else 'igual', '#', f'#{puesto}', f'de {len(mercado.OPERADORES)} operadores principales'),
                ('vacio', 'Σ', mercado.numero(total),
                 f"suscriptores en el mercado · {mercado.pct((total - total_previo) / total_previo, True)} en 12 meses"),
            ]
            _html_mercado('<div class="tc-kpis">' + ''.join(
                f'<div class="tc-kpi {c}"><div class="tc-ic">{i}</div><div><b>{escape(n)}</b><span>{escape(t)}</span></div></div>'
                for c, i, n, t in kpis) + '</div>')
    if not excluidos.empty:
        detalle = ('se quitaron de todos los meses' if comparable else
                   'aparecen en cero; el total del último mes es menor y la participación de los grandes se ve mayor')
        st.caption(f'{len(excluidos)} operadores pequeños, con {mercado.numero(excluidos["suscriptores"].sum())} '
                   f'suscriptores en {mercado.mes_texto(excluidos["mes"].iloc[0])}, no reportaron '
                   f'{mercado.mes_texto(ultimo)}: {detalle}.')

    st.subheader('Lo que dicen los números')
    lista_mercado(mercado.hallazgos(datos_servicio, servicio))

    cortes = mercado.cortes_anuales(tabla)
    # A todo el ancho: al comparar varios operadores, las barras y sus números necesitan espacio
    with st.container(border=True):
        # Solo los operadores que tienen suscriptores en este servicio (Claro no tiene TV paga)
        opciones = [op for op in [*mercado.OPERADORES, mercado.OTROS] if tabla[op].any()] + [MERCADO_TOTAL]
        # Al cambiar de servicio se quitan los que ya no aplican; si no queda ninguno, vuelve a Telecable
        elegidos = [op for op in st.session_state.get('operadores_mercado', [PRINCIPAL]) if op in opciones]
        st.session_state['operadores_mercado'] = elegidos or [PRINCIPAL]
        elegidos = st.pills('Operadores', opciones, selection_mode='multi', key='operadores_mercado',
                            label_visibility='collapsed',
                            help=f'Elige uno para ver su evolución, o hasta {MAX_COMPARAR} para compararlos.')
        elegidos = [op for op in opciones if op in elegidos] or [PRINCIPAL]
        if len(elegidos) > MAX_COMPARAR:
            st.caption(f'Se comparan hasta {MAX_COMPARAR} a la vez: {datos._lista(elegidos[:MAX_COMPARAR])}.')
            elegidos = elegidos[:MAX_COMPARAR]
        if len(elegidos) == 1:
            st.markdown(f'**Suscriptores de {elegidos[0]} en {servicio}**')
        else:
            st.markdown(f'**Suscriptores en {servicio}: {datos._lista(elegidos)}**')
        variaciones = []
        for op in elegidos:
            valores = suscriptores_de(cortes, op)
            if len(valores) > 1 and valores.iloc[0]:
                cambio = mercado.pct((valores.iloc[-1] - valores.iloc[0]) / valores.iloc[0], True)
                variaciones.append(cambio if len(elegidos) == 1 else f'{op} {cambio}')
        variacion = (f' De {mercado.mes_texto(cortes.index[0])} a {mercado.mes_texto(cortes.index[-1])}: '
                     f"{' · '.join(variaciones)}." if variaciones else '')
        st.caption(f'Al cierre de cada año y en el último mes disponible.{variacion}')
        st.altair_chart(grafico_suscriptores(cortes, elegidos), width='stretch')
    izq, der = st.columns(2, gap='medium')
    with izq.container(border=True):
        st.markdown(f'**Participación de mercado en {servicio}**')
        st.caption('Al cierre de cada año y en el último mes. Telecable abajo, en morado.')
        st.altair_chart(grafico_participacion_cortes(cortes), width='stretch')

    with der.container(border=True):
        st.markdown('**Participación mes a mes**')
        st.caption('Telecable en morado y cada competidor con su color, con su participación del último mes al final de la '
                   'línea.')
        st.altair_chart(grafico_participacion_mensual(tabla), width='stretch')

    st.subheader('Ranking de operadores')
    st.caption(f'Suscriptores y participación en {mercado.mes_texto(ultimo)}. "Otros" agrupa al resto de operadores.')
    ranking_mercado(res, previo)

    mes_conv, tv_por_100 = mercado.convergencia(df)
    if mes_conv and not tv_por_100.empty:
        st.subheader('Internet y TV juntos')
        st.caption(f'Suscriptores de TV paga por cada 100 suscriptores de Internet fijo en {mercado.mes_texto(mes_conv)}. '
                   'Indica cuánto pesa la TV en la base de clientes de cada operador.')
        barras_convergencia(mes_conv, tv_por_100)

    descarga = tabla.reset_index().melt(id_vars='mes', var_name='operador', value_name='suscriptores')
    st.download_button('Descargar suscriptores por operador (CSV)', descarga.to_csv(index=False).encode('utf-8-sig'),
                       file_name=f"suscriptores_{servicio.lower().replace(' ', '_')}.csv", mime='text/csv',
                       icon=':material/download:')


# --- Página de precios de entrada (Internet solo y combo por velocidad) ---------------------------

# Colores de la vigencia de cada precio, como en las presentaciones: amarillo 6 meses, azul 12 meses, morado
# indefinido. Cada etiqueta lleva texto ("6 m", "Indef."), así que la vigencia no depende solo del color.
VIGENCIA_CLASE = {
    datos.VIGENCIA_CORTA: 'corta',
    datos.VIGENCIA_LARGA: 'larga',
    datos.VIGENCIA_INDEFINIDA: 'indefinida',
    datos.VIGENCIA_SIN_DATO: 'sin-dato',
    datos.VIGENCIA_REGULAR: 'regular',
}

ESTILOS_ENTRADA = """
<style>
.tc-matriz-marco { overflow-x: auto; }
.tc-matriz { width: 100%; border-collapse: separate; border-spacing: 0 .4rem; font-size: .92rem; min-width: 46rem; }
.tc-matriz th { padding: .35rem .6rem; text-align: left; font-family: Poppins, sans-serif; font-weight: 600;
  border-bottom: 3px solid #872F98; white-space: nowrap; }
.tc-matriz th.tc-principal { color: #FFFFFF; background: #872F98; border-radius: .6rem .6rem 0 0; }
.tc-matriz td { padding: .55rem .6rem; vertical-align: middle; background: rgba(138, 134, 150, .1); }
.tc-matriz td:first-child { font-weight: 600; white-space: nowrap; border-radius: .6rem 0 0 .6rem; }
.tc-matriz td:last-child { border-radius: 0 .6rem .6rem 0; }
.tc-matriz td.tc-principal { background: rgba(155, 61, 175, .14); }
.tc-oferta { display: flex; align-items: center; gap: .4rem; white-space: nowrap; line-height: 1.6; }
.tc-oferta .tc-tipo { opacity: .75; min-width: 3.6rem; }
.tc-oferta a { color: inherit; text-decoration: none; border-bottom: 1px dotted currentColor; }
.tc-oferta.tc-min .tc-monto { font-weight: 700; }
.tc-vig { display: inline-block; border-radius: 999px; padding: 0 .45rem; font-size: .72rem; font-weight: 600;
  line-height: 1.35rem; }
.tc-vig.corta { background: #F2C94C; color: #241E2B; }
.tc-vig.larga { background: #2F6FDE; color: #FFFFFF; }
.tc-vig.indefinida { background: #9B3DAF; color: #FFFFFF; }
.tc-vig.regular { background: rgba(138, 134, 150, .28); }
.tc-vig.sin-dato { border: 1.5px solid currentColor; line-height: calc(1.35rem - 3px); }
.tc-leyenda { display: flex; flex-wrap: wrap; gap: .4rem 1.1rem; margin-top: .4rem; font-size: .82rem; align-items: center; }
</style>
"""


def _etiqueta_vigencia(fila):
    if fila['vigencia'] == datos.VIGENCIA_REGULAR:
        return 'Regular'
    if fila['vigencia'] == datos.VIGENCIA_SIN_DATO:
        return 'Promo'
    if fila['vigencia'] == datos.VIGENCIA_INDEFINIDA:
        return 'Indef.'
    return f"{int(fila['promo_meses'])} m"


def _celda(ofertas, minimos, competidas):
    lineas = []
    for _, o in ofertas.sort_values('tipo', key=lambda t: t != datos.INTERNET).iterrows():
        # Solo se marca el más barato donde al menos dos operadores tienen ese tipo de plan en esa velocidad
        clave = (o['mbps'], o['tipo'])
        es_minimo = clave in competidas and o['precio'] <= minimos[clave]
        detalle = f"{o['plan']} · {o['vigencia']}"
        if o['en_promocion']:
            detalle += f" · regular {datos.colones(o['precio_regular'])}"
        monto = escape(datos.colones(o['precio'])) + (' ▼' if es_minimo else '')
        if isinstance(o['link'], str) and o['link']:
            monto = f'<a href="{escape(o["link"])}" target="_blank" rel="noopener">{monto}</a>'
        lineas.append(
            f'<div class="tc-oferta{" tc-min" if es_minimo else ""}" title="{escape(detalle)}">'
            f'<span class="tc-tipo">{escape(o["tipo"])}</span><span class="tc-monto">{monto}</span>'
            f'<span class="tc-vig {VIGENCIA_CLASE[o["vigencia"]]}">{escape(_etiqueta_vigencia(o))}</span></div>'
        )
    return ''.join(lineas)


def matriz_entrada(entrada, operadores):
    minimos = entrada.groupby(['mbps', 'tipo'])['precio'].min().to_dict()
    ofertas = entrada.groupby(['mbps', 'tipo'])['operador'].nunique()
    competidas = set(ofertas[ofertas >= 2].index)
    clase = {op: ' class="tc-principal"' if op == PRINCIPAL else '' for op in operadores}
    filas = []
    for mbps in sorted(entrada['mbps'].unique()):
        de_velocidad = entrada[entrada['mbps'] == mbps]
        celdas = ''.join(
            f'<td{clase[op]}>{_celda(de_velocidad[de_velocidad["operador"] == op], minimos, competidas)}</td>' for op in operadores
        )
        filas.append(f'<tr><td>{escape(datos.velocidad_texto(mbps))}</td>{celdas}</tr>')
    encabezados = ''.join(f'<th{clase[op]}>{escape(op)}</th>' for op in operadores)
    leyenda = ''.join(
        f'<span><span class="tc-vig {VIGENCIA_CLASE[v]}">{etiqueta}</span> {escape(v)}</span>'
        for v, etiqueta in ((datos.VIGENCIA_CORTA, '6 m'), (datos.VIGENCIA_LARGA, '12 m'),
                            (datos.VIGENCIA_INDEFINIDA, 'Indef.'), (datos.VIGENCIA_SIN_DATO, 'Promo'),
                            (datos.VIGENCIA_REGULAR, 'Regular'))
    )
    st.html(
        f'{ESTILOS_ENTRADA}<div class="tc-matriz-marco"><table class="tc-matriz">'
        f'<thead><tr><th>Velocidad</th>{encabezados}</tr></thead><tbody>{"".join(filas)}</tbody></table></div>'
        f'<div class="tc-leyenda"><strong>Vigencia del precio:</strong>{leyenda}<span>▼ el más barato en esa velocidad</span></div>'
    )


def pagina_entrada():
    planes, notas = cargar_planes((_version(datos.RUTA_TELECABLE), _version(datos.RUTA_COMPETIDORES)))
    competidores = [op for op in planes['operador'].unique() if op != PRINCIPAL]
    encabezado(
        'Precios de entrada',
        'Internet solo y combo (Internet + TV) más baratos de cada operador en cada velocidad, con la vigencia del '
        'precio.',
        chips=[f"Capturados: {fecha_corta(max((n['fecha'] for n in notas if n.get('fecha')), default=None))}"],
    )
    if planes.empty:
        st.warning('Todavía no hay precios: se cargan de precios_telecable_manual.json y precios_competidores_manual.json.')
        return

    velocidades = sorted(planes['mbps'].dropna().unique())
    with st.container(horizontal=True, gap='medium', vertical_alignment='bottom'):
        elegidos = st.pills('Competidores', competidores, selection_mode='multi', default=competidores,
                            key='competidores_entrada') or []
        maximo = st.select_slider('Velocidad máxima', velocidades, value=500 if 500 in velocidades else velocidades[-1],
                                  format_func=datos.velocidad_texto, key='max_entrada')
        base = st.segmented_control(
            'Precio a mostrar', ['Vigente', 'Regular'], default='Vigente', required=True, key='base_entrada',
            help='Vigente: con la promoción, si el plan tiene una. Regular: el precio sin promoción.',
        )
    operadores = [PRINCIPAL, *elegidos]
    entrada = datos.precios_de_entrada(planes[planes['operador'].isin(operadores)], maximo, base.lower())
    if entrada.empty:
        st.info('No hay planes de Internet solo ni combos hasta esa velocidad para los operadores elegidos.')
        return

    with st.container(border=True):
        matriz_entrada(entrada, [op for op in operadores if (entrada['operador'] == op).any()])
        st.caption('Pasa el cursor sobre un precio para ver el plan y, si está en promoción, su precio regular. '
                   'Cada precio abre la página del plan. La vigencia de las promociones sale de la BD Máster o del '
                   'sitio del operador; "Promo" indica que no hay dato de su duración.')

    frases = datos.resumen_entrada(entrada)
    if frases:
        st.markdown('**Lo que muestra la tabla**')
        st.markdown('\n'.join(f'- {f}' for f in frases))

    descarga = pd.DataFrame({
        'Velocidad (Mbps)': entrada['mbps'], 'Operador': entrada['operador'], 'Tipo': entrada['tipo'],
        'Plan': entrada['plan'], 'Precio': entrada['precio'], 'Precio regular': entrada['precio_regular'],
        'Vigencia': entrada['vigencia'], 'Vigencia de la promoción': datos.plazo_promocion(entrada),
        'Enlace': entrada['link'],
    })
    st.download_button('Descargar CSV', descarga.to_csv(index=False).encode('utf-8-sig'),
                       file_name='precios_de_entrada.csv', mime='text/csv', icon=':material/download:')


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
        'Precio promocional': planes['precio_promocional'], 'Vigencia de la promoción': datos.plazo_promocion(planes),
        'Enlace': planes['link'], 'Capturado': planes['fecha'],
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
                    'Vigencia de la promoción': datos.plazo_promocion(filas),
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
    st.Page(pagina_resumen, title='Resumen ejecutivo', icon=':material/insights:', url_path='resumen', default=True),
    st.Page(pagina_mercado, title='Mercado', icon=':material/groups:', url_path='mercado'),
    st.Page(pagina_entrada, title='Precios de entrada', icon=':material/grid_view:', url_path='entrada'),
    st.Page(pagina_precios, title='Precios', icon=':material/sell:', url_path='precios'),
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
