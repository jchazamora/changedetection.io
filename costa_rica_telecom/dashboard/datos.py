"""
Precios de los planes capturados a mano (Telecable y la competencia), en tablas listas para el dashboard.

Cada operador tiene dos listas de planes: 'internet_y_tv' (combos) y 'solo_internet'. Cada plan trae 'precio'
(el vigente) y, cuando hay promoción, 'precio_anterior' (el regular).
"""

import json
import math
import os
import re

import pandas as pd

_CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
RUTA_TELECABLE = os.path.join(_CARPETA, 'precios_telecable_manual.json')
RUTA_COMPETIDORES = os.path.join(_CARPETA, 'precios_competidores_manual.json')

PRINCIPAL = 'Telecable'

DOBLE_PLAY = 'Doble Play'
SOLO_INTERNET = 'Solo Internet'
INTERNET_TELEFONIA = 'Internet + Telefonía'
SERVICIOS = [DOBLE_PLAY, SOLO_INTERNET, INTERNET_TELEFONIA]

# Rangos de velocidad para comparar planes parecidos entre operadores: (desde, hasta sin incluir, etiqueta)
RANGOS = [
    (0, 200, 'Hasta 199 Mbps'),
    (200, 300, '200–299 Mbps'),
    (300, 500, '300–499 Mbps'),
    (500, 750, '500–749 Mbps'),
    (750, 1000, '750–999 Mbps'),
    (1000, math.inf, '1 Gbps o más'),
]
ETIQUETAS_RANGO = [etiqueta for _, _, etiqueta in RANGOS]

COLUMNAS = [
    'operador', 'servicio', 'plan', 'velocidad', 'mbps', 'rango', 'precio_regular', 'precio_promocional',
    'precio_vigente', 'en_promocion', 'link', 'fecha', 'fuente',
]

# "300 Mbps + TV", "1 Gbps", "150 Mbps simétrico" / "Mega 120", "120 MEGAS"
_VELOCIDAD = re.compile(r'(\d+(?:[.,]\d+)?)\s*([gm])bps', re.IGNORECASE)
_MEGAS = re.compile(r'megas?\s*(\d+)|(\d+)\s*megas?', re.IGNORECASE)


def velocidad_mbps(*textos):
    """Velocidad de bajada en Mbps del primer texto que la indique, o None."""
    for texto in textos:
        if not texto:
            continue
        m = _VELOCIDAD.search(texto)
        if m:
            valor = float(m.group(1).replace(',', '.'))
            return valor * 1000 if m.group(2).lower() == 'g' else valor
        m = _MEGAS.search(texto)
        if m:
            return float(m.group(1) or m.group(2))
    return None


def rango_velocidad(mbps):
    if mbps is None or pd.isna(mbps):
        return None
    for desde, hasta, etiqueta in RANGOS:
        if desde <= mbps < hasta:
            return etiqueta
    return None


def colones(monto):
    """₡25.990, con punto como separador de miles como en los sitios de los operadores."""
    if monto is None or pd.isna(monto):
        return '—'
    return '₡' + f'{monto:,.0f}'.replace(',', '.')


def colones_con_signo(monto):
    # Guion simple: st.metric lo usa para saber si la diferencia es negativa
    signo = '+' if monto > 0 else '-' if monto < 0 else ''
    return signo + colones(abs(monto))


def porcentaje(valor):
    return f'{valor * 100:+.1f} %'.replace('.', ',')


def velocidad_texto(mbps):
    if mbps is None or pd.isna(mbps):
        return '—'
    return f'{mbps / 1000:g} Gbps' if mbps >= 1000 and mbps % 1000 == 0 else f'{mbps:g} Mbps'


def _servicio(clave, plan):
    if clave == 'solo_internet':
        return SOLO_INTERNET
    texto = f"{plan.get('plan', '')} {plan.get('velocidad', '')}".lower()
    return INTERNET_TELEFONIA if 'telefon' in texto or 'voz' in texto else DOBLE_PLAY


def _filas(operador, fuente, fecha, planes_por_servicio):
    filas = []
    for clave in ('internet_y_tv', 'solo_internet'):
        for p in planes_por_servicio.get(clave, []):
            promocional = p['precio'] if 'precio_anterior' in p else None
            mbps = velocidad_mbps(p.get('velocidad'), p.get('plan'))
            filas.append({
                'operador': operador,
                'servicio': _servicio(clave, p),
                'plan': p['plan'],
                'velocidad': p.get('velocidad', ''),
                'mbps': mbps,
                'rango': rango_velocidad(mbps),
                'precio_regular': float(p.get('precio_anterior', p['precio'])),
                'precio_promocional': float(promocional) if promocional is not None else math.nan,
                'precio_vigente': float(p['precio']),
                'en_promocion': promocional is not None,
                'link': p.get('link'),
                'fecha': fecha,
                'fuente': fuente,
            })
    return filas


def cargar_planes(ruta_telecable=RUTA_TELECABLE, ruta_competidores=RUTA_COMPETIDORES):
    """Todos los planes en una tabla (Telecable primero) y la nota de captura de cada operador."""
    filas, notas = [], []
    if os.path.exists(ruta_telecable):
        with open(ruta_telecable, encoding='utf-8') as f:
            t = json.load(f)
        filas += _filas(PRINCIPAL, t['fuente'], t['fecha'], t)
        notas.append({'operador': PRINCIPAL, 'fecha': t['fecha'], 'fuente': t['fuente'], 'nota': t.get('_nota', '')})
    if os.path.exists(ruta_competidores):
        with open(ruta_competidores, encoding='utf-8') as f:
            c = json.load(f)
        for op in c['operadores']:
            fecha = op.get('fecha', c.get('fecha'))
            filas += _filas(op['operador'], op['fuente'], fecha, op)
            notas.append({'operador': op['operador'], 'fecha': fecha, 'fuente': op['fuente'], 'nota': op.get('nota', '')})
    return pd.DataFrame(filas, columns=COLUMNAS), notas


def con_precio(planes, base='vigente'):
    """Agrega 'precio' según la base a comparar ('vigente', con la promoción si la hay, o 'regular')."""
    df = planes.copy()
    df['precio'] = df['precio_regular'] if base == 'regular' else df['precio_vigente']
    return df


def _mas_baratos(df):
    # Ante un empate de precio gana el plan más rápido: es la mejor oferta por ese monto
    return df.sort_values(['precio', 'mbps'], ascending=[True, False])


def plan_de_entrada(df):
    """El plan más barato de cada operador, del más barato al más caro."""
    return _mas_baratos(df).drop_duplicates('operador').reset_index(drop=True)


def mejor_por_rango(df):
    """El plan más barato de cada operador en cada rango de velocidad."""
    return _mas_baratos(df.dropna(subset=['rango'])).drop_duplicates(['operador', 'rango']).reset_index(drop=True)


def comparar_por_rango(df, principal=PRINCIPAL):
    """Por rango de velocidad: el plan más barato del principal frente a los precios de la competencia."""
    mejores = mejor_por_rango(df)
    filas = []
    for etiqueta in ETIQUETAS_RANGO:
        en_rango = mejores[mejores['rango'] == etiqueta]
        if en_rango.empty:
            continue
        propio = en_rango[en_rango['operador'] == principal]
        otros = en_rango[en_rango['operador'] != principal]
        fila = {'rango': etiqueta, 'competidores': len(otros)}
        if not propio.empty:
            p = propio.iloc[0]
            fila.update(plan_principal=p['plan'], mbps_principal=p['mbps'], precio_principal=p['precio'])
        if not otros.empty:
            barato = otros.iloc[0]  # 'mejores' ya viene del más barato al más caro
            fila.update(
                minimo=otros['precio'].min(), mediana=otros['precio'].median(), maximo=otros['precio'].max(),
                operador_mas_barato=barato['operador'], plan_mas_barato=barato['plan'], mbps_mas_barato=barato['mbps'],
            )
        filas.append(fila)
    columnas = [
        'rango', 'competidores', 'plan_principal', 'mbps_principal', 'precio_principal', 'minimo', 'mediana',
        'maximo', 'operador_mas_barato', 'plan_mas_barato', 'mbps_mas_barato',
    ]
    tabla = pd.DataFrame(filas).reindex(columns=columnas)
    tabla['dif_mediana'] = tabla['precio_principal'] - tabla['mediana']
    tabla['dif_mediana_pct'] = tabla['dif_mediana'] / tabla['mediana']
    comparable = tabla['precio_principal'].notna() & tabla['minimo'].notna()
    tabla['principal_mas_barato'] = comparable & (tabla['precio_principal'] <= tabla['minimo'])
    tabla['comparable'] = comparable
    return tabla
