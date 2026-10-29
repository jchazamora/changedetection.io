#!/usr/bin/env python3
"""
Convierte los Excel de suscriptores de SUTEL (Internet fijo y TV paga) en el CSV que usa el dashboard.

Cada Excel tiene una fila por operador (razón social), una columna por mes ("enero del 2022") y una fila TOTALES al
final. El CSV queda en formato largo: servicio, mes (AAAA-MM), operador, suscriptores. Solo se guardan los meses desde
enero 2022 y los valores distintos de cero; un operador sin fila en un mes tiene cero suscriptores ese mes.

Uso:
    python3 costa_rica_telecom/importar_suscriptores.py --internet "Suscriptores por Internet.xlsx" --tv "Suscriptores por TV.xlsx"
"""

import argparse
import csv
import os
import sys

import pandas as pd

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_CSV = os.path.join(CARPETA, 'suscriptores_sutel.csv')
DESDE = '2022-01'

MESES = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
         'septiembre': 9, 'setiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12}


def mes_iso(texto):
    """'enero del 2022' -> '2022-01'"""
    partes = str(texto).lower().replace(' del ', ' ').split()
    return f'{int(partes[-1])}-{MESES[partes[0]]:02d}'


def leer_excel(ruta):
    """{(mes, operador): suscriptores} de un Excel de SUTEL; comprueba que cuadre con la fila TOTALES."""
    df = pd.read_excel(ruta, sheet_name=0, header=None)
    fila_meses = next(i for i in range(10) if isinstance(df.iloc[i, 1], str))
    meses = [mes_iso(m) for m in df.iloc[fila_meses, 1:]]
    cuerpo = df.iloc[fila_meses + 1:].dropna(subset=[0]).set_index(0)
    cuerpo.columns = meses
    cuerpo.index = [' '.join(str(n).split()) for n in cuerpo.index]
    totales = cuerpo.loc['TOTALES']
    cuerpo = cuerpo.drop('TOTALES').fillna(0).astype(int)
    if not (cuerpo.sum() == totales).all():
        raise ValueError(f'{ruta}: la suma de los operadores no coincide con la fila TOTALES')
    return cuerpo


def main():
    parser = argparse.ArgumentParser(description='Convierte los Excel de suscriptores de SUTEL al CSV del dashboard')
    parser.add_argument('--internet', required=True, help='Excel de suscripciones de Internet fijo')
    parser.add_argument('--tv', required=True, help='Excel de suscriptores de TV paga')
    args = parser.parse_args()

    filas = []
    for servicio, ruta in (('Internet fijo', args.internet), ('TV paga', args.tv)):
        cuerpo = leer_excel(ruta)
        meses = [m for m in cuerpo.columns if m >= DESDE]
        for operador, valores in cuerpo[meses].iterrows():
            filas += [(servicio, mes, operador, int(v)) for mes, v in valores.items() if v]
        print(f'{servicio}: {meses[0]} a {meses[-1]}, {len(cuerpo)} operadores')

    with open(RUTA_CSV, 'w', encoding='utf-8', newline='') as f:
        escritor = csv.writer(f)
        escritor.writerow(['servicio', 'mes', 'operador', 'suscriptores'])
        escritor.writerows(sorted(filas))
    print(f'{len(filas)} filas en {RUTA_CSV}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
