from precios import Precio, extraer_precios


def montos(texto):
    return [(p.moneda, p.monto) for p in extraer_precios(texto)]


def test_colones_con_separador_de_miles():
    assert montos('Internet 100 Mbps ₡19.900 i.v.i.') == [('CRC', 19900)]
    assert montos('Combo TV + Internet ¢34,600') == [('CRC', 34600)]
    assert montos('Plan básico CRC 25000') == [('CRC', 25000)]
    assert montos('Plan ₡1.234.500') == [('CRC', 1234500)]


def test_dolares_y_decimales():
    assert montos('Plan Pro $25.99 al mes') == [('USD', 25.99)]
    assert montos('US$ 30 mensuales') == [('USD', 30)]
    assert montos('Total USD 1,250.50') == [('USD', 1250.5)]
    assert montos('Total ₡1.234,50') == [('CRC', 1234.5)]


def test_conserva_la_linea_y_no_repite():
    texto = 'Fibra 200 Mbps   ₡24.900\n\nFibra 200 Mbps ₡24.900\nFibra 500 Mbps ₡32.900'
    assert extraer_precios(texto) == [
        Precio('CRC', 24900, 'Fibra 200 Mbps ₡24.900'),
        Precio('CRC', 32900, 'Fibra 500 Mbps ₡32.900'),
    ]


def test_quita_vinetas_de_la_linea():
    assert extraer_precios('  * Fibra 100 Mbps ₡19.900')[0].linea == 'Fibra 100 Mbps ₡19.900'


def test_ignora_numeros_sin_moneda():
    assert montos('Velocidad 100 Mbps, llame al 4080-4000') == []
    assert montos('') == []
