import os
import tempfile

import pandas as pd

import mercado


def _csv(filas):
    carpeta = tempfile.mkdtemp()
    ruta = os.path.join(carpeta, 's.csv')
    pd.DataFrame(filas, columns=['servicio', 'mes', 'operador', 'suscriptores']).to_csv(ruta, index=False)
    return mercado.cargar(ruta)


def _datos():
    filas = []
    for mes, tele, lib, ice, otro in (('2024-12', 100, 80, 90, 30), ('2025-04', 110, 85, 70, 30),
                                       ('2025-12', 120, 90, 60, 30), ('2026-04', 130, 95, 50, 0)):
        filas += [
            ('Internet fijo', mes, 'TELECABLE SOCIEDAD ANONIMA', tele),
            ('Internet fijo', mes, 'LIBERTY TELECOMUNICACIONES DE COSTA RICA LY SOCIEDAD ANONIMA', lib),
            ('Internet fijo', mes, 'INSTITUTO COSTARRICENSE DE ELECTRICIDAD', ice),
        ]
        if otro:
            filas.append(('Internet fijo', mes, 'CABLE CARIBE, S.A.', otro))
    filas += [('TV paga', '2026-04', 'TELECABLE SOCIEDAD ANONIMA', 65), ('TV paga', '2026-04', 'MILLICOM CABLE COSTA RICA SOCIEDAD ANONIMA', 40)]
    return _csv(filas)


def test_agrupa_razones_sociales():
    assert mercado.operador_de('CABLETICA, SOCIEDAD ANONIMA') == 'Liberty'
    assert mercado.operador_de('LIBERTY SERVICIOS FIJOS LY SOCIEDAD ANONIMA') == 'Liberty'
    assert mercado.operador_de('MILLICOM CABLE COSTA RICA SOCIEDAD ANONIMA') == 'Tigo'
    assert mercado.operador_de('INSTITUTO COSTARRICENSE DE ELECTRICIDAD') == 'Kölbi'
    assert mercado.operador_de('COOPERATIVA DE ELECTRIFICACION RURAL DE SAN CARLOS R L') == mercado.OTROS
    assert mercado.mes_texto('2026-04') == 'abr 2026'


def test_resumen_y_cortes():
    df = _datos()
    tabla = mercado.por_operador(df, mercado.INTERNET)
    assert list(tabla.columns) == ['Telecable', 'Liberty', 'Kölbi', 'Tigo', 'Claro', 'Otros']
    res, ultimo, previo = mercado.resumen(tabla)
    assert (ultimo, previo) == ('2026-04', '2025-04')
    t = res.set_index('operador').loc['Telecable']
    assert t['suscriptores'] == 130 and t['ranking'] == 1
    assert t['altas_netas'] == 20
    assert round(t['participacion'], 4) == round(130 / 275, 4)
    assert list(mercado.cortes_anuales(tabla).index) == ['2024-12', '2025-12', '2026-04']


def test_sin_reporte_y_hallazgos():
    df = _datos()
    faltan = mercado.sin_reporte(df, mercado.INTERNET, minimo=10)
    assert list(faltan['razon_social']) == ['CABLE CARIBE, S.A.'] and faltan['mes'].iloc[0] == '2025-12'

    # Sin el operador que no reportó, en ningún mes
    d, excluidos = mercado.solo_reportados(df, mercado.INTERNET)
    assert list(excluidos['razon_social']) == ['CABLE CARIBE, S.A.']
    assert 'CABLE CARIBE, S.A.' not in set(d['razon_social'])

    frases = [t for _, t in mercado.hallazgos(d, mercado.INTERNET)]
    assert frases[0] == ('Telecable es el operador con más suscriptores de Internet fijo: 130 (47,3 % del mercado), '
                         '35 más que Liberty.')
    assert any(f.startswith('Kölbi es el que más participación perdió: −') for f in frases)
    assert mercado.pct(0.2611) == '26,1 %' and mercado.puntos(2.09) == '+2,1 puntos'


def test_convergencia():
    mes, tv_por_100 = mercado.convergencia(_datos())
    assert mes == '2026-04'
    assert tv_por_100['Telecable'] == 50
    assert 'Tigo' not in tv_por_100  # sin Internet fijo en los datos, no hay proporción
