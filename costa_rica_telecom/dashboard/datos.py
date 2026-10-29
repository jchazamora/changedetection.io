"""
Precios de los planes capturados a mano (Telecable y la competencia), en tablas listas para el dashboard.

Cada operador tiene dos listas de planes: 'internet_y_tv' (combos) y 'solo_internet'. Cada plan trae 'precio'
(el vigente) y, cuando hay promoción, 'precio_anterior' (el regular) y opcionalmente 'promo_meses' (cuánto dura la
promoción; si falta, se busca en el nombre del plan, como en "(promo 4 meses)").
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
    'precio_vigente', 'en_promocion', 'promo_meses', 'link', 'fecha', 'fuente',
]

# "300 Mbps + TV", "1 Gbps", "150 Mbps simétrico" / "Mega 120", "120 MEGAS"
_VELOCIDAD = re.compile(r'(\d+(?:[.,]\d+)?)\s*([gm])bps', re.IGNORECASE)
_MEGAS = re.compile(r'megas?\s*(\d+)|(\d+)\s*megas?', re.IGNORECASE)
# "(promo 4 meses)", "promoción por 6 meses"
_MESES_PROMO = re.compile(r'promo\w*\s*(?:de\s+|por\s+)?(\d+)\s*mes', re.IGNORECASE)


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


def meses_de_promocion(plan):
    """Duración de la promoción en meses: el campo 'promo_meses' o lo que diga el nombre del plan, o None."""
    if plan.get('promo_meses'):
        return int(plan['promo_meses'])
    m = _MESES_PROMO.search(plan.get('plan', ''))
    return int(m.group(1)) if m else None


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
                'promo_meses': meses_de_promocion(p) if promocional is not None else None,
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


# --- Precios de entrada: Internet solo y combo por velocidad -------------------------------------

INTERNET = 'Internet'
COMBO = 'Combo'

VIGENCIA_CORTA = 'Promoción de hasta 6 meses'
VIGENCIA_LARGA = 'Promoción de más de 6 meses'
VIGENCIA_SIN_DATO = 'Promoción sin plazo publicado'
VIGENCIA_REGULAR = 'Precio regular, sin plazo'
VIGENCIAS = [VIGENCIA_CORTA, VIGENCIA_LARGA, VIGENCIA_SIN_DATO, VIGENCIA_REGULAR]


def vigencia(en_promocion, meses):
    if not en_promocion:
        return VIGENCIA_REGULAR
    if meses is None or pd.isna(meses):
        return VIGENCIA_SIN_DATO
    return VIGENCIA_CORTA if meses <= 6 else VIGENCIA_LARGA


def precios_de_entrada(planes, max_mbps=None, base='vigente'):
    """Por velocidad y operador, el Internet solo y el combo (Internet + TV) más baratos, con la vigencia del precio."""
    df = con_precio(planes[planes['servicio'].isin([SOLO_INTERNET, DOBLE_PLAY])].dropna(subset=['mbps']), base)
    if max_mbps is not None:
        df = df[df['mbps'] <= max_mbps]
    df['tipo'] = df['servicio'].map({SOLO_INTERNET: INTERNET, DOBLE_PLAY: COMBO})
    # Con el precio regular no hay promoción que mostrar
    promo = df['en_promocion'] & (base != 'regular')
    df['vigencia'] = [vigencia(p, m) for p, m in zip(promo, df['promo_meses'])]
    df = df.sort_values('precio').drop_duplicates(['mbps', 'operador', 'tipo'])
    return df.sort_values(['mbps', 'tipo']).reset_index(drop=True)


def mas_baratos_por_velocidad(entrada):
    """Por velocidad y tipo, el precio más bajo y los operadores que lo tienen (puede haber empate)."""
    minimos = entrada.groupby(['mbps', 'tipo'])['precio'].transform('min')
    ganadores = entrada[entrada['precio'] == minimos]
    return (ganadores.groupby(['mbps', 'tipo'], as_index=False)
            .agg(precio=('precio', 'first'), operadores=('operador', list)))


def _lista(elementos):
    elementos = list(elementos)
    return elementos[0] if len(elementos) == 1 else ', '.join(elementos[:-1]) + ' y ' + elementos[-1]


def _velocidades(mbps):
    return _lista([velocidad_texto(m) for m in sorted(mbps)])


def resumen_entrada(entrada, principal=PRINCIPAL):
    """Frases cortas con lo más importante de la tabla de precios de entrada."""
    if entrada.empty:
        return []
    ganadores = mas_baratos_por_velocidad(entrada)
    frases = []
    for tipo, nombre in ((INTERNET, 'Internet solo'), (COMBO, 'combo')):
        del_tipo = ganadores[ganadores['tipo'] == tipo]
        if del_tipo.empty:
            continue
        # Solo cuentan las velocidades con al menos dos operadores: con uno solo no hay con quién comparar
        ofertas = entrada[entrada['tipo'] == tipo].groupby('mbps')['operador'].nunique()
        del_tipo = del_tipo[del_tipo['mbps'].map(ofertas) >= 2]
        if del_tipo.empty:
            continue
        conteo = del_tipo.explode('operadores')['operadores'].value_counts()
        lider = conteo.index[0]
        donde = del_tipo[del_tipo['operadores'].map(lambda ops: lider in ops)]['mbps']
        frases.append(f'{lider} tiene el {nombre} más barato en {len(donde)} de {len(del_tipo)} velocidades '
                      f'con competencia ({_velocidades(donde)}).')

        propios = entrada[(entrada['tipo'] == tipo) & (entrada['operador'] == principal) & entrada['mbps'].isin(del_tipo['mbps'])]
        if propios.empty:
            continue
        minimos = del_tipo.set_index('mbps')['precio']
        gana = propios[propios['precio'] <= propios['mbps'].map(minimos)]
        pierde = propios[propios['precio'] > propios['mbps'].map(minimos)]
        n = len(propios)
        donde_tiene = 'la única velocidad' if n == 1 else f'las {n} velocidades'
        if pierde.empty:
            frase = f'En {nombre}, {principal} es el más barato en {donde_tiene} donde tiene oferta'
        else:
            diferencia = colones((pierde['precio'] - pierde['mbps'].map(minimos)).mean())
            if gana.empty:
                ninguna = 'en la única velocidad' if n == 1 else f'en ninguna de las {n} velocidades'
                frase = (f'En {nombre}, {principal} no es el más barato {ninguna} donde tiene '
                         f'oferta: está en promedio {diferencia} por encima del más barato')
            else:
                frase = (f'En {nombre}, {principal} es el más barato en {len(gana)} de {n} velocidades donde tiene '
                         f'oferta; en las demás está en promedio {diferencia} por encima del más barato')
        frases.append(frase + '.')
    return frases
