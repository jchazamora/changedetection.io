"""
Suscriptores y participación de mercado por operador (Internet fijo y TV paga), con los datos de SUTEL.

Los datos vienen de suscriptores_sutel.csv (ver importar_suscriptores.py): una fila por servicio, mes, razón social y
cantidad de suscriptores. Aquí las razones sociales se agrupan en los cinco operadores del dashboard y "Otros".
"""

import os

import pandas as pd

from datos import PRINCIPAL

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'suscriptores_sutel.csv')

INTERNET = 'Internet fijo'
TV = 'TV paga'
SERVICIOS = [INTERNET, TV]
OTROS = 'Otros'
OPERADORES = [PRINCIPAL, 'Liberty', 'Kölbi', 'Tigo', 'Claro']

# Razón social (en mayúsculas) que contiene el texto -> operador. Cabletica pasó a Liberty a fines de 2022.
GRUPOS = [
    ('TELECABLE', PRINCIPAL),
    ('LIBERTY', 'Liberty'),
    ('CABLETICA', 'Liberty'),
    ('INSTITUTO COSTARRICENSE DE ELECTRICIDAD', 'Kölbi'),
    ('MILLICOM', 'Tigo'),
    ('CLARO CR', 'Claro'),
]

NOMBRES_MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def operador_de(razon_social):
    texto = razon_social.upper()
    return next((op for clave, op in GRUPOS if clave in texto), OTROS)


def mes_texto(mes):
    """'2026-04' -> 'abr 2026'"""
    anio, numero = mes.split('-')
    return f'{NOMBRES_MES[int(numero) - 1]} {anio}'


def numero(valor):
    """320348 -> '320.348'"""
    return f'{valor:,.0f}'.replace(',', '.')


def pct(fraccion, signo=False):
    """0.2611 -> '26,1 %'; con signo, '+26,1 %'"""
    return f"{fraccion * 100:{'+' if signo else ''}.1f} %".replace('.', ',').replace('-', '−')


def puntos(valor):
    """2.09 -> '+2,1 puntos'"""
    return f'{valor:+.1f} puntos'.replace('.', ',').replace('-', '−')


def cargar(ruta=RUTA):
    if not os.path.exists(ruta):
        return pd.DataFrame(columns=['servicio', 'mes', 'razon_social', 'operador', 'suscriptores'])
    df = pd.read_csv(ruta, dtype={'mes': str}).rename(columns={'operador': 'razon_social'})
    df['operador'] = df['razon_social'].map(operador_de)
    return df


def por_operador(df, servicio):
    """Tabla mes x operador (los cinco y Otros) con los suscriptores; meses en orden y sin huecos."""
    d = df[df['servicio'] == servicio]
    tabla = d.pivot_table(index='mes', columns='operador', values='suscriptores', aggfunc='sum', fill_value=0)
    return tabla.reindex(columns=[op for op in [*OPERADORES, OTROS]], fill_value=0).sort_index()


def participacion(tabla):
    return tabla.div(tabla.sum(axis=1), axis=0)


def _hace_un_anio(mes, meses):
    anio, numero = mes.split('-')
    anterior = f'{int(anio) - 1}-{numero}'
    return anterior if anterior in meses else None


def resumen(tabla):
    """Por operador, en el último mes: suscriptores, participación, ranking y cambio a 12 meses."""
    meses = list(tabla.index)
    ultimo = meses[-1]
    previo = _hace_un_anio(ultimo, meses)
    cuota = participacion(tabla)
    filas = []
    for op in tabla.columns:
        fila = {'operador': op, 'suscriptores': int(tabla.loc[ultimo, op]), 'participacion': cuota.loc[ultimo, op]}
        if previo:
            antes = int(tabla.loc[previo, op])
            fila.update(altas_netas=fila['suscriptores'] - antes,
                        crecimiento=(fila['suscriptores'] - antes) / antes if antes else None,
                        cambio_pp=(cuota.loc[ultimo, op] - cuota.loc[previo, op]) * 100)
        filas.append(fila)
    tabla_resumen = pd.DataFrame(filas)
    principales = tabla_resumen[tabla_resumen['operador'] != OTROS].sort_values('suscriptores', ascending=False)
    tabla_resumen['ranking'] = tabla_resumen['operador'].map(
        {op: i + 1 for i, op in enumerate(principales['operador'])})
    return tabla_resumen, ultimo, previo


def cortes_anuales(tabla):
    """Diciembre de cada año y el último mes disponible (como en los informes de SUTEL)."""
    meses = list(tabla.index)
    cortes = [m for m in meses if m.endswith('-12')]
    if meses[-1] not in cortes:
        cortes.append(meses[-1])
    return tabla.loc[cortes]


def sin_reporte(df, servicio, minimo=500):
    """Razones sociales con suscriptores en el penúltimo corte anual que en el último mes aparecen en cero.

    SUTEL publica en cero a los operadores que todavía no reportan; eso baja el total del mercado y sube la
    participación de los que sí reportaron.
    """
    d = df[df['servicio'] == servicio]
    meses = sorted(d['mes'].unique())
    if len(meses) < 2:
        return pd.DataFrame(columns=['razon_social', 'suscriptores', 'mes'])
    ultimo = meses[-1]
    referencia = max((m for m in meses if m.endswith('-12') and m < ultimo), default=meses[-2])
    antes = d[d['mes'] == referencia].groupby('razon_social')['suscriptores'].sum()
    ahora = d[d['mes'] == ultimo].groupby('razon_social')['suscriptores'].sum()
    faltan = antes[(antes >= minimo) & ~antes.index.isin(ahora.index)]
    return pd.DataFrame({'razon_social': faltan.index, 'suscriptores': faltan.values, 'mes': referencia})


def solo_reportados(df, servicio):
    """Los datos del servicio sin las razones sociales que no reportaron el último mes (en todos los meses), para que
    la participación se compare siempre sobre los mismos operadores. Devuelve también cuáles se excluyeron."""
    faltan = sin_reporte(df, servicio, minimo=1)
    d = df[(df['servicio'] == servicio) & ~df['razon_social'].isin(faltan['razon_social'])]
    return d, faltan


def hallazgos(df, servicio):
    """Frases cortas sobre el mercado, cada una marcada como 'bien', 'mal' o 'mercado' (para el color)."""
    tabla = por_operador(df, servicio)
    if tabla.empty:
        return []
    res, ultimo, previo = resumen(tabla)
    r = res.set_index('operador')
    propio = r.loc[PRINCIPAL]
    frases = []

    lider = res.sort_values('suscriptores', ascending=False)
    lider = lider[lider['operador'] != OTROS].iloc[0]
    if lider['operador'] == PRINCIPAL:
        segundo = res[(res['operador'] != OTROS) & (res['operador'] != PRINCIPAL)].sort_values(
            'suscriptores', ascending=False).iloc[0]
        frases.append(('bien', f"Telecable es el operador con más suscriptores de {servicio}: {numero(propio['suscriptores'])} "
                               f"({pct(propio['participacion'])} del mercado), {numero(propio['suscriptores'] - segundo['suscriptores'])} "
                               f"más que {segundo['operador']}."))
    else:
        frases.append(('mal', f"{lider['operador']} lidera {servicio} con {numero(lider['suscriptores'])} suscriptores; Telecable "
                              f"es #{int(propio['ranking'])} con {numero(propio['suscriptores'])} ({pct(propio['participacion'])})."))

    if previo:
        total_antes = int(tabla.loc[previo].sum())
        total_ahora = int(tabla.loc[ultimo].sum())
        crec_mercado = (total_ahora - total_antes) / total_antes
        tono = 'bien' if propio['crecimiento'] > crec_mercado else 'mal'
        frases.append((tono, f"En 12 meses ({mes_texto(previo)} a {mes_texto(ultimo)}) Telecable "
                             f"{'ganó' if propio['altas_netas'] >= 0 else 'perdió'} {numero(abs(propio['altas_netas']))} suscriptores "
                             f"({pct(propio['crecimiento'], True)}), frente a {pct(crec_mercado, True)} del mercado; su "
                             f"participación cambió {puntos(propio['cambio_pp'])}."))
        competidores = res[~res['operador'].isin([PRINCIPAL, OTROS])]
        gana = competidores.sort_values('cambio_pp', ascending=False).iloc[0]
        if gana['cambio_pp'] > 0:
            if gana['altas_netas'] >= 0:
                detalle = f"{numero(gana['altas_netas'])} suscriptores nuevos, {pct(gana['crecimiento'], True)}"
            else:
                detalle = (f"aunque perdió {numero(-gana['altas_netas'])} suscriptores ({pct(gana['crecimiento'], True)}): "
                           'el mercado cayó más')
            frases.append(('mal' if gana['cambio_pp'] > propio['cambio_pp'] else 'mercado',
                           f"Entre la competencia, {gana['operador']} es el que más participación ganó: "
                           f"{puntos(gana['cambio_pp'])} ({detalle})."))
        pierde = competidores.sort_values('cambio_pp').iloc[0]
        if pierde['cambio_pp'] < 0:
            frases.append(('mercado', f"{pierde['operador']} es el que más participación perdió: {puntos(pierde['cambio_pp'])} "
                                      f"({numero(pierde['altas_netas']).replace('-', '−')} suscriptores en 12 meses)."))

    inicio = tabla.index[0]
    total_inicio, total_fin = int(tabla.loc[inicio].sum()), int(tabla.loc[ultimo].sum())
    propio_inicio = int(tabla.loc[inicio, PRINCIPAL])
    if propio_inicio:
        frases.append(('mercado', f"Desde {mes_texto(inicio)}, el mercado de {servicio} pasó de {numero(total_inicio)} a "
                                  f"{numero(total_fin)} suscriptores ({pct((total_fin - total_inicio) / total_inicio, True)}) y "
                                  f"Telecable de {numero(propio_inicio)} a {numero(propio['suscriptores'])} "
                                  f"({pct((propio['suscriptores'] - propio_inicio) / propio_inicio, True)})."))

    return frases


def convergencia(df):
    """Por operador, suscriptores de TV por cada 100 de Internet en el último mes común a los dos servicios."""
    internet, tv = por_operador(df, INTERNET), por_operador(df, TV)
    comunes = sorted(set(internet.index) & set(tv.index))
    if not comunes:
        return None, pd.Series(dtype=float)
    mes = comunes[-1]
    i, t = internet.loc[mes], tv.loc[mes]
    return mes, (t[OPERADORES] / i[OPERADORES].where(i[OPERADORES] > 0) * 100).dropna()
