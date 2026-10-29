#!/usr/bin/env python3
"""
Carga los precios de Internet + TV de la BD Máster (CSV exportado de Excel) en los JSON del dashboard.

Toma un mes y una región del CSV y reemplaza la lista 'internet_y_tv' de Telecable y de cada competidor del dashboard
(Kölbi, Claro, Tigo y Liberty) con el precio regular, el promocional y la vigencia de la promoción. Las listas de
'solo_internet' no se tocan: la BD Máster solo trae Internet + TV. Donde una velocidad ya existía en el JSON, se
conservan el nombre del plan y el enlace.

Uso:
    python3 costa_rica_telecom/importar_bd_maestra.py RUTA_AL_CSV [--mes oct-26] [--region Central]

El CSV no se sube al repositorio: el repo es público y la BD Máster tiene todo el histórico.
"""

import argparse
import csv
import json
import os
import re
import sys

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_TELECABLE = os.path.join(CARPETA, 'precios_telecable_manual.json')
RUTA_COMPETIDORES = os.path.join(CARPETA, 'precios_competidores_manual.json')

# Nombre en la BD Máster -> nombre en el dashboard
OPERADORES = {'Telecable': 'Telecable', 'Kolbi': 'Kölbi', 'Claro': 'Claro', 'Tigo': 'Tigo', 'Liberty': 'Liberty'}
MESES = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10,
         'nov': 11, 'dic': 12}

_VELOCIDAD = re.compile(r'(\d+(?:[.,]\d+)?)\s*([gm])bps', re.IGNORECASE)


def mbps(texto):
    m = _VELOCIDAD.search(texto or '')
    if not m:
        return None
    valor = float(m.group(1).replace(',', '.'))
    return valor * 1000 if m.group(2).lower() == 'g' else valor


def monto(texto):
    """'27900,00' -> 27900; vacío -> None"""
    texto = (texto or '').strip().replace('.', '').replace(',', '.')
    return round(float(texto)) if texto else None


def leer_csv(ruta, mes, region):
    """{operador del dashboard: [filas del mes y la región]}, en el orden del CSV."""
    # Excel en Windows exporta en Latin-1 (cp1252) y con punto y coma
    with open(ruta, encoding='cp1252', newline='') as f:
        filas = list(csv.DictReader(f, delimiter=';'))
    elegidas = {}
    for fila in filas:
        operador = OPERADORES.get((fila.get('Proveedor') or '').strip())
        if not operador or fila['Fecha'].strip().lower() != mes or fila['Región'].strip() != region:
            continue
        elegidas.setdefault(operador, []).append(fila)
    return elegidas


def planes_desde_csv(filas, anteriores, link_por_defecto):
    """Lista 'internet_y_tv' para el JSON a partir de las filas del CSV de un operador."""
    # Solo combos con TV de lo que ya estaba: la BD Máster no trae Internet + Telefonía
    previos = [p for p in anteriores if 'telefon' not in f"{p.get('plan', '')} {p.get('velocidad', '')}".lower()]
    planes = []
    for fila in filas:
        velocidad = mbps(fila['Velocidad'])
        regular = monto(fila['Precio regular'])
        promocion = monto(fila['Precio Promoción'])
        if velocidad is None or regular is None:
            continue
        mismos = [p for p in previos if mbps(p.get('velocidad')) == velocidad or mbps(p.get('plan')) == velocidad]
        # Entre varios planes de la misma velocidad, el que tiene el mismo precio
        previo = next((p for p in mismos if p['precio'] in (regular, promocion) or p.get('precio_anterior') == regular),
                      mismos[0] if mismos else None)
        texto_velocidad = f'{velocidad:g} Mbps'
        plan = {
            'plan': re.sub(r'\s*\(promo[^)]*\)', '', previo['plan']) if previo else f'Internet + TV {texto_velocidad}',
            'velocidad': previo['velocidad'] if previo else f'{texto_velocidad} + TV',
        }
        # Una "promoción" igual o más cara que el regular no es promoción
        if promocion is not None and promocion < regular:
            plan.update(precio_anterior=regular, precio=promocion)
            vigencia = ' '.join(fila['Vigencia de promoción'].split())
            if vigencia:
                plan['vigencia'] = vigencia
        else:
            plan['precio'] = regular
        plan['link'] = (previo or {}).get('link') or link_por_defecto
        planes.append(plan)
    return sorted(planes, key=lambda p: mbps(p['velocidad']) or 0)


def _a_json(valor, sangria=0):
    """JSON con sangría, pero cada plan en una sola línea, como ya estaban los archivos."""
    espacio = '  ' * (sangria + 1)
    if isinstance(valor, dict) and 'plan' not in valor:
        partes = [f'{espacio}{json.dumps(k, ensure_ascii=False)}: {_a_json(v, sangria + 1)}' for k, v in valor.items()]
        return '{\n' + ',\n'.join(partes) + '\n' + '  ' * sangria + '}'
    if isinstance(valor, list) and valor:
        return '[\n' + ',\n'.join(espacio + _a_json(v, sangria + 1) for v in valor) + '\n' + '  ' * sangria + ']'
    return json.dumps(valor, ensure_ascii=False)


def fecha_del_mes(mes):
    abreviatura, anio = mes.split('-')
    return f'20{anio}-{MESES[abreviatura]:02d}'


def main():
    parser = argparse.ArgumentParser(description='Carga Internet + TV de la BD Máster en los JSON del dashboard')
    parser.add_argument('csv', help='CSV exportado de la BD Máster')
    parser.add_argument('--mes', default='oct-26', help='Mes como aparece en la columna Fecha (por defecto oct-26)')
    parser.add_argument('--region', default='Central', help='Región a tomar (por defecto Central)')
    args = parser.parse_args()
    mes = args.mes.strip().lower()

    filas = leer_csv(args.csv, mes, args.region)
    faltan = [op for op in OPERADORES.values() if op not in filas]
    if faltan:
        print(f"Sin filas de {', '.join(faltan)} para {mes} en {args.region}.", file=sys.stderr)

    nota = f'Internet + TV: BD Máster, {mes}, región {args.region} (precio regular, promocional y vigencia).'

    with open(RUTA_TELECABLE, encoding='utf-8') as f:
        telecable = json.load(f)
    if 'Telecable' in filas:
        telecable['internet_y_tv'] = planes_desde_csv(filas['Telecable'], telecable.get('internet_y_tv', []),
                                                      telecable['fuente'])
        telecable['bd_maestra'] = nota
        print(f"Telecable: {len(telecable['internet_y_tv'])} planes de Internet + TV")

    with open(RUTA_COMPETIDORES, encoding='utf-8') as f:
        competidores = json.load(f)
    for op in competidores['operadores']:
        if op['operador'] in filas:
            op['internet_y_tv'] = planes_desde_csv(filas[op['operador']], op.get('internet_y_tv', []), op['fuente'])
            op['bd_maestra'] = nota
            print(f"{op['operador']}: {len(op['internet_y_tv'])} planes de Internet + TV")

    for ruta, contenido in ((RUTA_TELECABLE, telecable), (RUTA_COMPETIDORES, competidores)):
        contenido['mes_bd_maestra'] = fecha_del_mes(mes)
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(_a_json(contenido) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
