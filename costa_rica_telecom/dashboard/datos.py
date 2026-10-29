"""
Precios de los planes capturados a mano (Telecable y la competencia), en tablas listas para el dashboard.

Cada operador tiene dos listas de planes: 'internet_y_tv' (combos) y 'solo_internet'. Cada plan trae 'precio'
(el vigente) y, cuando hay promoción, 'precio_anterior' (el regular) y opcionalmente 'vigencia' (cuánto dura la
promoción, como en la BD Máster: "12 meses", "promocional 6 meses", "Permanente", "Indefinido") o 'promo_meses'.
Si faltan, la duración se busca en el nombre del plan, como en "(promo 4 meses)".
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
    'precio_vigente', 'en_promocion', 'promo_meses', 'promo_indefinida', 'link', 'fecha', 'fuente',
]

# "300 Mbps + TV", "1 Gbps", "150 Mbps simétrico" / "Mega 120", "120 MEGAS"
_VELOCIDAD = re.compile(r'(\d+(?:[.,]\d+)?)\s*([gm])bps', re.IGNORECASE)
_MEGAS = re.compile(r'megas?\s*(\d+)|(\d+)\s*megas?', re.IGNORECASE)
# "(promo 4 meses)" en el nombre del plan; "12 meses", "promoción por 6 meses" en la vigencia
_MESES_PROMO = re.compile(r'promo\w*\s*(?:de\s+|por\s+)?(\d+)\s*mes', re.IGNORECASE)
_MESES = re.compile(r'(\d+)\s*mes', re.IGNORECASE)


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
    """Duración de la promoción en meses: 'promo_meses', la 'vigencia' o lo que diga el nombre del plan, o None."""
    if plan.get('promo_meses'):
        return int(plan['promo_meses'])
    m = _MESES.search(plan.get('vigencia') or '') or _MESES_PROMO.search(plan.get('plan', ''))
    return int(m.group(1)) if m else None


def promocion_indefinida(plan):
    """La BD Máster marca con "Permanente" o "Indefinido" las promociones sin fecha de fin."""
    texto = (plan.get('vigencia') or '').lower()
    return 'indefinid' in texto or 'permanente' in texto


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
                'promo_indefinida': promocional is not None and promocion_indefinida(p),
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
        notas.append({'operador': PRINCIPAL, 'fecha': t['fecha'], 'fuente': t['fuente'],
                      'nota': ' '.join(filter(None, [t.get('_nota'), t.get('bd_maestra')]))})
    if os.path.exists(ruta_competidores):
        with open(ruta_competidores, encoding='utf-8') as f:
            c = json.load(f)
        for op in c['operadores']:
            fecha = op.get('fecha', c.get('fecha'))
            filas += _filas(op['operador'], op['fuente'], fecha, op)
            notas.append({'operador': op['operador'], 'fecha': fecha, 'fuente': op['fuente'],
                          'nota': ' '.join(filter(None, [op.get('nota'), op.get('bd_maestra')]))})
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
VIGENCIA_INDEFINIDA = 'Promoción indefinida'
VIGENCIA_SIN_DATO = 'Promoción sin plazo publicado'
VIGENCIA_REGULAR = 'Precio regular'
VIGENCIAS = [VIGENCIA_CORTA, VIGENCIA_LARGA, VIGENCIA_INDEFINIDA, VIGENCIA_SIN_DATO, VIGENCIA_REGULAR]


def vigencia(en_promocion, meses, indefinida=False):
    if not en_promocion:
        return VIGENCIA_REGULAR
    if indefinida:
        return VIGENCIA_INDEFINIDA
    if meses is None or pd.isna(meses):
        return VIGENCIA_SIN_DATO
    return VIGENCIA_CORTA if meses <= 6 else VIGENCIA_LARGA


def plazo_promocion(planes):
    """Texto de la vigencia de la promoción de cada plan: '12 meses', 'Indefinida', 'Sin dato' o vacío sin promoción."""
    def texto(promo, meses, indefinida):
        if not promo:
            return ''
        if indefinida:
            return 'Indefinida'
        return f'{int(meses)} meses' if meses is not None and not pd.isna(meses) else 'Sin dato'
    return [texto(*fila) for fila in zip(planes['en_promocion'], planes['promo_meses'], planes['promo_indefinida'])]


def precios_de_entrada(planes, max_mbps=None, base='vigente'):
    """Por velocidad y operador, el Internet solo y el combo (Internet + TV) más baratos, con la vigencia del precio."""
    df = con_precio(planes[planes['servicio'].isin([SOLO_INTERNET, DOBLE_PLAY])].dropna(subset=['mbps']), base)
    if max_mbps is not None:
        df = df[df['mbps'] <= max_mbps]
    df['tipo'] = df['servicio'].map({SOLO_INTERNET: INTERNET, DOBLE_PLAY: COMBO})
    # Con el precio regular no hay promoción que mostrar
    promo = df['en_promocion'] & (base != 'regular')
    df['vigencia'] = [vigencia(p, m, i) for p, m, i in zip(promo, df['promo_meses'], df['promo_indefinida'])]
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


# --- Resumen ejecutivo: dónde está Telecable frente a la competencia ------------------------------

# Una diferencia de hasta 3 % se considera precio similar
TOLERANCIA_IGUAL = 0.03

MEJOR = 'mejor'               # Telecable es el más barato del rango
IGUAL = 'igual'               # Telecable está a no más de 3 % del más barato
PEOR = 'peor'                 # algún competidor es más barato
SIN_PLAN = 'sin_plan'         # la competencia tiene planes en el rango y Telecable no
SOLO_TELECABLE = 'solo_telecable'

_NOMBRE_SERVICIO = {DOBLE_PLAY: 'Internet + TV', SOLO_INTERNET: 'Solo Internet'}


def nombre_servicio(servicio):
    return _NOMBRE_SERVICIO.get(servicio, servicio)


def rango_texto(rango):
    """'Hasta 199 Mbps' -> 'hasta 199 Mbps', para usarlo dentro de una frase."""
    return rango[0].lower() + rango[1:] if rango.startswith('Hasta') else rango


def _estado(propio, rival):
    dif = (propio - rival) / rival
    if dif < -TOLERANCIA_IGUAL:
        return MEJOR
    return IGUAL if dif <= TOLERANCIA_IGUAL else PEOR


def _con_vigencia(df):
    df = df.copy()
    df['vigencia'] = [vigencia(p, m, i) for p, m, i in zip(df['en_promocion'], df['promo_meses'], df['promo_indefinida'])]
    df['plazo'] = plazo_promocion(df)
    return df


def _mejores_por_servicio(df):
    """mejor_por_rango por separado para cada servicio (el más barato de cada operador, rango y servicio)."""
    partes = [mejor_por_rango(df[df['servicio'] == s]) for s in df['servicio'].unique()]
    return pd.concat(partes, ignore_index=True) if partes else df.iloc[0:0].assign(rango=None)


def posicion_por_rango(planes, base='vigente', principal=PRINCIPAL):
    """Por servicio y rango de velocidad: el plan más barato de Telecable frente al más barato de la competencia."""
    df = _con_vigencia(con_precio(planes[planes['servicio'].isin([DOBLE_PLAY, SOLO_INTERNET])], base))
    if base == 'regular':
        df['plazo'] = ''
    mejores = _mejores_por_servicio(df)
    filas = []
    for servicio in (DOBLE_PLAY, SOLO_INTERNET):
        for etiqueta in ETIQUETAS_RANGO:
            en_rango = mejores[(mejores['servicio'] == servicio) & (mejores['rango'] == etiqueta)]
            if en_rango.empty:
                continue
            propio = en_rango[en_rango['operador'] == principal]
            otros = en_rango[en_rango['operador'] != principal]  # del más barato al más caro
            fila = {'servicio': servicio, 'rango': etiqueta, 'competidores': len(otros)}
            if not propio.empty:
                p = propio.iloc[0]
                fila.update(plan=p['plan'], mbps=p['mbps'], precio=p['precio'], plazo=p['plazo'], link=p['link'])
            if not otros.empty:
                r = otros.iloc[0]
                fila.update(rival=r['operador'], plan_rival=r['plan'], mbps_rival=r['mbps'], precio_rival=r['precio'],
                            plazo_rival=r['plazo'], link_rival=r['link'],
                            mas_baratos=int((otros['precio'] < fila.get('precio', math.inf)).sum()))
            if propio.empty:
                fila['estado'] = SIN_PLAN
            elif otros.empty:
                fila['estado'] = SOLO_TELECABLE
            else:
                fila['estado'] = _estado(fila['precio'], fila['precio_rival'])
                fila['diferencia'] = fila['precio'] - fila['precio_rival']
                fila['diferencia_pct'] = fila['diferencia'] / fila['precio_rival']
            filas.append(fila)
    columnas = ['servicio', 'rango', 'estado', 'plan', 'mbps', 'precio', 'plazo', 'link', 'competidores', 'rival',
                'plan_rival', 'mbps_rival', 'precio_rival', 'plazo_rival', 'link_rival', 'mas_baratos', 'diferencia',
                'diferencia_pct']
    return pd.DataFrame(filas).reindex(columns=columnas)


def cara_a_cara(planes, base='vigente', principal=PRINCIPAL):
    """Por competidor y servicio: en cuántos rangos Telecable es más barato, similar o más caro, y la diferencia típica."""
    mejores = _mejores_por_servicio(con_precio(planes[planes['servicio'].isin([DOBLE_PLAY, SOLO_INTERNET])], base))
    filas = []
    for rival in [op for op in mejores['operador'].unique() if op != principal]:
        for servicio in (DOBLE_PLAY, SOLO_INTERNET):
            del_servicio = mejores[mejores['servicio'] == servicio]
            propios = del_servicio[del_servicio['operador'] == principal].set_index('rango')['precio']
            suyos = del_servicio[del_servicio['operador'] == rival].set_index('rango')['precio']
            comunes = propios.index.intersection(suyos.index)
            if comunes.empty:
                continue
            estados = [_estado(propios[r], suyos[r]) for r in comunes]
            filas.append({
                'rival': rival, 'servicio': servicio, 'rangos': len(comunes),
                MEJOR: estados.count(MEJOR), IGUAL: estados.count(IGUAL), PEOR: estados.count(PEOR),
                'diferencia_pct': ((propios[comunes] - suyos[comunes]) / suyos[comunes]).median(),
            })
    return pd.DataFrame(filas, columns=['rival', 'servicio', 'rangos', MEJOR, IGUAL, PEOR, 'diferencia_pct'])


def conteo_estados(posicion):
    """Cuántos rangos hay en cada estado, y la diferencia típica (mediana) de Telecable frente al más barato."""
    cuenta = {e: int((posicion['estado'] == e).sum()) for e in (MEJOR, IGUAL, PEOR, SIN_PLAN)}
    comparables = posicion[posicion['estado'].isin([MEJOR, IGUAL, PEOR])]
    cuenta['comparados'] = len(comparables)
    cuenta['tipica'] = comparables['diferencia_pct'].median() if len(comparables) else None
    return cuenta


def resumen_por_rival(cara):
    """Por competidor, sumando Internet + TV y Solo Internet: rangos ganados, similares y perdidos, y la diferencia
    típica de Telecable (promedio de las medianas de cada servicio, pesado por los rangos comparados)."""
    filas = []
    for rival, c in cara.groupby('rival', sort=False):
        filas.append({
            'rival': rival, MEJOR: int(c[MEJOR].sum()), IGUAL: int(c[IGUAL].sum()), PEOR: int(c[PEOR].sum()),
            'rangos': int(c['rangos'].sum()),
            'diferencia_pct': (c['diferencia_pct'] * c['rangos']).sum() / c['rangos'].sum(),
        })
    # Primero los que más presionan a Telecable
    return pd.DataFrame(filas, columns=['rival', MEJOR, IGUAL, PEOR, 'rangos', 'diferencia_pct']).sort_values(
        'diferencia_pct', ascending=False).reset_index(drop=True)


def hallazgos(planes, posicion, base='vigente', principal=PRINCIPAL):
    """Conclusiones en lenguaje simple, cada una marcada como 'bien', 'mal' o 'mercado'."""
    resultado = []
    comparables = posicion[posicion['estado'].isin([MEJOR, IGUAL, PEOR])]

    for servicio in (DOBLE_PLAY, SOLO_INTERNET):
        s = comparables[comparables['servicio'] == servicio]
        if s.empty:
            continue
        n = len(s)
        mejor, igual, peor = (int((s['estado'] == e).sum()) for e in (MEJOR, IGUAL, PEOR))
        tono = 'bien' if mejor > peor else 'mal' if peor > mejor else 'mercado'
        resultado.append((tono, f'En {nombre_servicio(servicio)}, Telecable tiene el mejor precio en {mejor} de {n} rangos '
                                f'de velocidad, un precio similar en {igual} y es más caro en {peor}.'))

    if not comparables.empty:
        peor = comparables.sort_values('diferencia_pct', ascending=False).iloc[0]
        if peor['estado'] == PEOR:
            resultado.append(('mal', f"La mayor desventaja está en {nombre_servicio(peor['servicio'])} de "
                                     f"{rango_texto(peor['rango'])}: {peor['rival']} cobra {colones(peor['precio_rival'])} por "
                                     f"{velocidad_texto(peor['mbps_rival'])}, {colones(peor['diferencia'])} "
                                     f"({peor['diferencia_pct'] * 100:.0f} %) menos que Telecable."))
        mejor = comparables.sort_values('diferencia_pct').iloc[0]
        if mejor['estado'] == MEJOR:
            resultado.append(('bien', f"La mayor ventaja está en {nombre_servicio(mejor['servicio'])} de "
                                      f"{rango_texto(mejor['rango'])}: Telecable cobra {colones(mejor['precio'])}, "
                                      f"{colones(-mejor['diferencia'])} ({-mejor['diferencia_pct'] * 100:.0f} %) menos "
                                      f"que {mejor['rival']}, el más barato de la competencia."))

    sin_plan = posicion[posicion['estado'] == SIN_PLAN]
    if not sin_plan.empty:
        huecos = [f"{nombre_servicio(f['servicio'])} de {rango_texto(f['rango'])}" for _, f in sin_plan.iterrows()]
        resultado.append(('mercado', f'Telecable no tiene plan en {_lista(huecos)}, donde la competencia sí ofrece.'))

    competencia = _con_vigencia(con_precio(planes[(planes['operador'] != principal)
                                                  & planes['servicio'].isin([DOBLE_PLAY, SOLO_INTERNET])], base))
    if not competencia.empty:
        barato = competencia.sort_values(['precio', 'mbps'], ascending=[True, False]).iloc[0]
        detalle = f" en promoción ({barato['plazo'].lower()}, regular {colones(barato['precio_regular'])})" \
            if barato['en_promocion'] and base != 'regular' else ''
        resultado.append(('mercado', f"La oferta más agresiva del mercado es {barato['operador']} "
                                     f"{nombre_servicio(barato['servicio'])} {velocidad_texto(barato['mbps'])} a "
                                     f"{colones(barato['precio'])}{detalle}."))
        if base != 'regular':
            promos = competencia[competencia['en_promocion']]
            largas = promos[promos['vigencia'].isin([VIGENCIA_LARGA, VIGENCIA_INDEFINIDA])]
            if not promos.empty:
                resultado.append(('mercado', f'{len(promos)} de {len(competencia)} planes de la competencia están en '
                                             f'promoción; {len(largas)} de ellos por más de 6 meses o sin fecha de fin, '
                                             'así que no son descuentos pasajeros.'))

    if not comparables.empty:
        contra = comparables[comparables['estado'] == PEOR]['rival'].value_counts()
        if not contra.empty:
            resultado.append(('mal', f'{contra.index[0]} es el competidor que más presiona: es el más barato frente a '
                                     f'Telecable en {contra.iloc[0]} de {len(comparables)} rangos de velocidad.'))
    return resultado


_NOMBRES_MES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
                'noviembre', 'diciembre']


def mes_bd_maestra(ruta=RUTA_COMPETIDORES):
    """'octubre 2026' si los precios de Internet + TV vienen de la BD Máster (ver importar_bd_maestra.py), o None."""
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding='utf-8') as f:
        mes = json.load(f).get('mes_bd_maestra')
    if not mes:
        return None
    anio, numero = mes.split('-')
    return f'{_NOMBRES_MES[int(numero) - 1]} {anio}'
