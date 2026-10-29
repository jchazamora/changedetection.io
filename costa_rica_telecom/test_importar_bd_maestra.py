import os
import tempfile

import importar_bd_maestra as imp

CSV = (
    'Fecha;Proveedor;Región;Velocidad;Precio regular;Precio Promoción;Vigencia de promoción;;;;;\r\n'
    'sep-26;Liberty;Central;120 mbps;27900,00;;;;;;;\r\n'
    'oct-26;Liberty;Central;120 mbps;27900,00;19900,00;Permanente;;;;;\r\n'
    'oct-26;Liberty;Brunca;120 mbps;30000,00;;;;;;;\r\n'
    'oct-26;Claro;Central;400 mbps;32400,00;32400,00;;;;;;\r\n'
    'oct-26;Tigo;Central;125 mbps;20990,00;18500,00;12 meses ;;;;;\r\n'
    'oct-26;Telca;Central;100 mbps;15000,00;;;;;;;\r\n'
)


def _leer():
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, 'bd.csv')
        with open(ruta, 'w', encoding='cp1252', newline='') as f:
            f.write(CSV)
        return imp.leer_csv(ruta, 'oct-26', 'Central')


def test_filtra_mes_region_y_operadores():
    filas = _leer()
    assert sorted(filas) == ['Claro', 'Liberty', 'Tigo']  # Telca no está en el dashboard
    assert len(filas['Liberty']) == 1


def test_planes_con_promocion_vigencia_y_plan_existente():
    filas = _leer()
    anteriores = [{'plan': 'Doble Play Mega 120', 'velocidad': '120 Mbps + TV', 'precio_anterior': 32900, 'precio': 27900,
                   'link': 'https://libertycr.com/doble-play'}]
    liberty = imp.planes_desde_csv(filas['Liberty'], anteriores, 'https://libertycr.com')
    assert liberty == [{'plan': 'Doble Play Mega 120', 'velocidad': '120 Mbps + TV', 'precio_anterior': 27900,
                        'precio': 19900, 'vigencia': 'Permanente', 'link': 'https://libertycr.com/doble-play'}]

    tigo = imp.planes_desde_csv(filas['Tigo'], [], 'https://www.tigo.cr/planes')
    assert tigo[0]['plan'] == 'Internet + TV 125 Mbps'
    assert (tigo[0]['precio_anterior'], tigo[0]['precio'], tigo[0]['vigencia']) == (20990, 18500, '12 meses')

    # Una promoción igual al precio regular no es promoción
    claro = imp.planes_desde_csv(filas['Claro'], [], 'https://www.claro.cr')
    assert claro[0]['precio'] == 32400 and 'precio_anterior' not in claro[0]
