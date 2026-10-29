import json
import math
import os
import tempfile

import pandas as pd

import datos


def test_velocidad_desde_el_texto_del_plan():
    assert datos.velocidad_mbps('300 Mbps + TV') == 300
    assert datos.velocidad_mbps('1 Gbps + TV') == 1000
    assert datos.velocidad_mbps('1024 Mbps simétrico') == 1024
    assert datos.velocidad_mbps('no indicada', 'Internet Mega 120') == 120
    assert datos.velocidad_mbps('120 MEGAS Internet') == 120
    assert datos.velocidad_mbps('no indicada', '') is None


def test_rangos_de_velocidad():
    assert datos.rango_velocidad(100) == 'Hasta 199 Mbps'
    assert datos.rango_velocidad(200) == '200–299 Mbps'
    assert datos.rango_velocidad(750) == '750–999 Mbps'
    assert datos.rango_velocidad(1024) == '1 Gbps o más'
    assert datos.rango_velocidad(None) is None


def test_formatos():
    assert datos.colones(25990) == '₡25.990'
    assert datos.colones(math.nan) == '—'
    assert datos.colones_con_signo(-2000) == '-₡2.000'
    assert datos.colones_con_signo(1500) == '+₡1.500'
    assert datos.porcentaje(0.041) == '+4,1 %'
    assert datos.velocidad_texto(1000) == '1 Gbps'
    assert datos.velocidad_texto(1024) == '1024 Mbps'


def _archivos(carpeta):
    telecable = {
        'fecha': '2026-10-23', 'fuente': 'https://telecable.example', '_nota': 'nota',
        'internet_y_tv': [
            {'plan': 'Básico', 'velocidad': '150 Mbps + TV', 'precio': 25990, 'link': 'https://t/basico'},
            {'plan': 'Estándar', 'velocidad': '300 Mbps + TV', 'precio_anterior': 29990, 'precio': 25990},
        ],
        'solo_internet': [{'plan': 'Básico', 'velocidad': '150 Mbps', 'precio': 22990}],
    }
    competidores = {
        'fecha': '2026-10-24',
        'operadores': [
            {'operador': 'Claro', 'fuente': 'https://claro.example', 'nota': 'n',
             'internet_y_tv': [
                 {'plan': 'Doble Play 300 Mbps Telefonía Fija', 'velocidad': '300 Mbps + Telefonía', 'precio': 23080},
                 {'plan': 'Doble Play 300 Mbps Ultra HD', 'velocidad': '300 Mbps + TV', 'precio': 23250},
             ],
             'solo_internet': []},
            {'operador': 'Liberty', 'fuente': 'https://liberty.example', 'nota': 'n',
             'internet_y_tv': [
                 {'plan': 'Doble Play Mega 120', 'velocidad': '120 Mbps + TV', 'precio_anterior': 32900, 'precio': 27900},
                 {'plan': 'Doble Play Mega 300', 'velocidad': '300 Mbps + TV', 'precio_anterior': 39900, 'precio': 27900},
             ],
             'solo_internet': []},
        ],
    }
    rutas = []
    for nombre, contenido in (('t.json', telecable), ('c.json', competidores)):
        ruta = os.path.join(carpeta, nombre)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(contenido, f)
        rutas.append(ruta)
    return rutas


def test_carga_planes_servicios_y_promociones():
    with tempfile.TemporaryDirectory() as carpeta:
        planes, notas = datos.cargar_planes(*_archivos(carpeta))
    assert list(planes['operador'].unique()) == ['Telecable', 'Claro', 'Liberty']
    assert [n['operador'] for n in notas] == ['Telecable', 'Claro', 'Liberty']

    claro = planes[planes['operador'] == 'Claro'].set_index('plan')
    assert claro.loc['Doble Play 300 Mbps Telefonía Fija', 'servicio'] == datos.INTERNET_TELEFONIA
    assert claro.loc['Doble Play 300 Mbps Ultra HD', 'servicio'] == datos.DOBLE_PLAY

    estandar = planes[(planes['operador'] == 'Telecable') & (planes['plan'] == 'Estándar')].iloc[0]
    assert estandar['precio_regular'] == 29990
    assert estandar['precio_promocional'] == 25990
    assert estandar['precio_vigente'] == 25990
    assert estandar['en_promocion']

    basico = planes[(planes['operador'] == 'Telecable') & (planes['servicio'] == datos.SOLO_INTERNET)].iloc[0]
    assert basico['precio_regular'] == 22990
    assert math.isnan(basico['precio_promocional'])
    assert not basico['en_promocion']


def test_comparaciones():
    with tempfile.TemporaryDirectory() as carpeta:
        planes, _ = datos.cargar_planes(*_archivos(carpeta))
    combos = datos.con_precio(planes[planes['servicio'] == datos.DOBLE_PLAY], 'vigente')

    # Empate de precio en Liberty: el plan de entrada es el más rápido
    entrada = datos.plan_de_entrada(combos).set_index('operador')
    assert entrada.loc['Liberty', 'mbps'] == 300
    assert entrada.loc['Claro', 'precio'] == 23250

    tabla = datos.comparar_por_rango(combos).set_index('rango')
    assert tabla.loc['Hasta 199 Mbps', 'precio_principal'] == 25990
    assert tabla.loc['Hasta 199 Mbps', 'minimo'] == 27900
    assert tabla.loc['Hasta 199 Mbps', 'principal_mas_barato']
    fila = tabla.loc['300–499 Mbps']
    assert fila['operador_mas_barato'] == 'Claro'
    assert fila['mediana'] == (23250 + 27900) / 2
    assert not fila['principal_mas_barato']

    # Con el precio regular, el Estándar de Telecable vuelve a ₡29.990
    regulares = datos.comparar_por_rango(datos.con_precio(planes[planes['servicio'] == datos.DOBLE_PLAY], 'regular'))
    assert regulares.set_index('rango').loc['300–499 Mbps', 'precio_principal'] == 29990


def test_comparacion_sin_principal_ni_competencia():
    with tempfile.TemporaryDirectory() as carpeta:
        planes, _ = datos.cargar_planes(*_archivos(carpeta))
    solo_claro = datos.con_precio(planes[planes['operador'] == 'Claro'])
    tabla = datos.comparar_por_rango(solo_claro)
    assert not tabla['comparable'].any()
    assert tabla['precio_principal'].isna().all()


def test_meses_de_promocion():
    assert datos.meses_de_promocion({'plan': 'Internet 350 Mbps (promo 4 meses)'}) == 4
    assert datos.meses_de_promocion({'plan': 'Combo', 'promo_meses': 12}) == 12
    assert datos.meses_de_promocion({'plan': 'Doble Play Mega 300'}) is None


def _planes_entrada():
    filas = [
        # operador, servicio, plan, mbps, regular, vigente, promo, meses
        ('Telecable', datos.SOLO_INTERNET, 'Estándar', 300, 25990, 22990, True, 6),
        ('Telecable', datos.DOBLE_PLAY, 'Estándar', 300, 29990, 25990, True, None),
        ('Kölbi', datos.SOLO_INTERNET, 'Internet 300', 300, 14095, 14095, False, None),
        ('Kölbi', datos.SOLO_INTERNET, 'Internet 500', 500, 15095, 15095, False, None),
        ('Claro', datos.DOBLE_PLAY, 'Ultra HD', 300, 23250, 23250, False, None),
        ('Claro', datos.DOBLE_PLAY, 'Ultra HD Plus', 300, 24685, 24685, False, None),
        ('Claro', datos.DOBLE_PLAY, 'Ultra HD 1 Gbps', 1024, 46045, 46045, False, None),
        ('Tigo', datos.SOLO_INTERNET, 'Internet 500', 500, 28150, 21990, True, 12),
        ('Claro', datos.INTERNET_TELEFONIA, 'Telefonía', 300, 23080, 23080, False, None),
    ]
    return pd.DataFrame([{
        'operador': o, 'servicio': s, 'plan': p, 'mbps': m, 'precio_regular': r, 'precio_vigente': v,
        'en_promocion': e, 'promo_meses': meses,
    } for o, s, p, m, r, v, e, meses in filas])


def test_precios_de_entrada():
    entrada = datos.precios_de_entrada(_planes_entrada(), max_mbps=500)
    # Sin Internet + Telefonía ni planes de más de 500 Mbps, y un solo combo de Claro en 300 (el más barato)
    assert set(entrada['tipo']) == {datos.INTERNET, datos.COMBO}
    assert entrada['mbps'].max() == 500
    claro = entrada[entrada['operador'] == 'Claro']
    assert list(claro['plan']) == ['Ultra HD']

    vig = entrada.set_index(['operador', 'tipo', 'mbps'])['vigencia']
    assert vig[('Telecable', datos.INTERNET, 300)] == datos.VIGENCIA_CORTA
    assert vig[('Telecable', datos.COMBO, 300)] == datos.VIGENCIA_SIN_DATO
    assert vig[('Tigo', datos.INTERNET, 500)] == datos.VIGENCIA_LARGA
    assert vig[('Kölbi', datos.INTERNET, 300)] == datos.VIGENCIA_REGULAR

    regular = datos.precios_de_entrada(_planes_entrada(), max_mbps=500, base='regular')
    assert set(regular['vigencia']) == {datos.VIGENCIA_REGULAR}
    assert regular.set_index(['operador', 'tipo', 'mbps']).loc[('Tigo', datos.INTERNET, 500), 'precio'] == 28150


def test_resumen_entrada():
    entrada = datos.precios_de_entrada(_planes_entrada(), max_mbps=500)
    ganadores = datos.mas_baratos_por_velocidad(entrada).set_index(['mbps', 'tipo'])
    assert ganadores.loc[(300, datos.INTERNET), 'operadores'] == ['Kölbi']
    assert ganadores.loc[(500, datos.INTERNET), 'precio'] == 15095

    frases = datos.resumen_entrada(entrada)
    assert frases[0] == ('Kölbi tiene el Internet solo más barato en 2 de 2 velocidades con competencia '
                         '(300 Mbps y 500 Mbps).')
    assert frases[1] == ('En Internet solo, Telecable no es el más barato en la única velocidad donde tiene '
                         'oferta: está en promedio ₡8.895 por encima del más barato.')
    assert frases[2].startswith('Claro tiene el combo más barato en 1 de 1')
    assert frases[3].startswith('En combo, Telecable no es el más barato en la única velocidad')

    # Con el combo de Telecable más barato que el de Claro, gana en todas
    planes = _planes_entrada()
    planes.loc[(planes['operador'] == 'Telecable') & (planes['servicio'] == datos.DOBLE_PLAY), 'precio_vigente'] = 20000
    frases = datos.resumen_entrada(datos.precios_de_entrada(planes, max_mbps=500))
    assert frases[-1] == 'En combo, Telecable es el más barato en la única velocidad donde tiene oferta.'
    assert datos.resumen_entrada(entrada.iloc[0:0]) == []
