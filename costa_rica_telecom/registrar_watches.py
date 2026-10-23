#!/usr/bin/env python3
"""
Registra en changedetection.io los watches definidos en watches.json, usando el API REST.

Uso:
    export CD_URL=http://127.0.0.1:5000        # opcional, este es el valor por defecto
    export CD_API_KEY=tu_api_key                # Settings > API en la interfaz web
    python3 registrar_watches.py [--archivo watches.json] [--dry-run]

Las URLs que ya existen en changedetection.io se omiten, así que se puede correr varias veces.
Solo usa la librería estándar de Python.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watches.json')


def llamar_api(base_url, api_key, metodo, ruta, datos=None):
    cuerpo = json.dumps(datos).encode('utf-8') if datos is not None else None
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/{ruta}",
        data=cuerpo,
        method=metodo,
        headers={'x-api-key': api_key, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        texto = resp.read().decode('utf-8')
        return resp.status, json.loads(texto) if texto.strip().startswith(('{', '[')) else texto


def limpiar(watch):
    # Las claves con '_' son notas para humanos, no campos del API
    return {k: v for k, v in watch.items() if not k.startswith('_')}


def main():
    parser = argparse.ArgumentParser(description='Registra watches de telecom CR en changedetection.io')
    parser.add_argument('--archivo', default=DEFAULT_ARCHIVO, help='Ruta al JSON con los watches')
    parser.add_argument('--dry-run', action='store_true', help='Solo muestra lo que se registraría')
    args = parser.parse_args()

    base_url = os.getenv('CD_URL', 'http://127.0.0.1:5000')
    api_key = os.getenv('CD_API_KEY', '')

    with open(args.archivo, encoding='utf-8') as f:
        watches = [limpiar(w) for w in json.load(f)['watches']]

    if args.dry_run:
        for w in watches:
            print(f"[dry-run] {w['title']}: {w['url']}")
        print(f"{len(watches)} watches en {args.archivo}")
        return 0

    if not api_key:
        print('Falta CD_API_KEY (Settings > API en la interfaz web).', file=sys.stderr)
        return 1

    try:
        _, existentes = llamar_api(base_url, api_key, 'GET', 'watch')
    except urllib.error.HTTPError as e:
        print(f'No se pudo listar los watches existentes: HTTP {e.code} {e.read().decode()}', file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f'No se pudo conectar a {base_url}: {e.reason}', file=sys.stderr)
        return 1

    urls_existentes = {w['url'] for w in existentes.values()}
    creados = omitidos = errores = 0

    for w in watches:
        if w['url'] in urls_existentes:
            print(f"= Ya existe: {w['title']} ({w['url']})")
            omitidos += 1
            continue
        try:
            _, respuesta = llamar_api(base_url, api_key, 'POST', 'watch', w)
            print(f"+ Creado: {w['title']} -> {respuesta.get('uuid') if isinstance(respuesta, dict) else respuesta}")
            creados += 1
        except urllib.error.HTTPError as e:
            print(f"! Error en {w['title']}: HTTP {e.code} {e.read().decode().strip()}", file=sys.stderr)
            errores += 1

    print(f'Listo: {creados} creados, {omitidos} ya existían, {errores} con error.')
    return 1 if errores else 0


if __name__ == '__main__':
    sys.exit(main())
