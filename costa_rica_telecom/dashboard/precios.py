"""
Extracción de precios (colones y dólares) del texto que guarda changedetection.io en cada snapshot.
"""

import re
from dataclasses import dataclass

# Símbolo seguido del monto: "₡19.900", "¢ 34,600", "CRC 25000", "$25.99", "US$ 30", "USD 1,250.50",
# "₡38 900.00" (Kölbi separa los miles con un espacio). Los miles con espacio van aparte para que en
# "₡24.900 500 Mbps" no se junte la velocidad con el precio.
_PATRON_PRECIO = re.compile(
    r'(?P<simbolo>₡|¢|CRC|US\$|USD|\$)\s?'
    r'(?P<numero>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?'
    r'|\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,2})?'
    r'|\d+(?:[.,]\d{1,2})?)',
    re.IGNORECASE,
)

_MAX_LARGO_LINEA = 200


@dataclass(frozen=True)
class Precio:
    moneda: str   # 'CRC' o 'USD'
    monto: float
    linea: str    # texto donde aparece el precio, para relacionarlo con el plan


def _a_numero(texto):
    """'19.900' -> 19900, '34,600' -> 34600, '25.99' -> 25.99, '1.234,50' -> 1234.5, '38 900.00' -> 38900"""
    t = re.sub(r'\s', '', texto)
    # Un separador final seguido de 1 o 2 dígitos es decimal; con 3 dígitos es de miles
    m = re.match(r'^(.*?)[.,](\d{1,2})$', t)
    entero, decimales = (m.group(1), m.group(2)) if m else (t, '')
    entero = re.sub(r'[.,]', '', entero)
    return float(f"{entero}.{decimales}" if decimales else entero)


def extraer_precios(texto):
    """Devuelve los precios encontrados en el texto, sin repetir, en orden de aparición."""
    vistos = set()
    resultado = []
    for linea in (texto or '').splitlines():
        # Quita espacios repetidos y las viñetas que deja la conversión de HTML a texto
        linea = ' '.join(linea.split()).lstrip('*•·- ')
        if not linea:
            continue
        for m in _PATRON_PRECIO.finditer(linea):
            simbolo = m.group('simbolo').upper()
            moneda = 'CRC' if simbolo in ('₡', '¢', 'CRC') else 'USD'
            precio = Precio(moneda, _a_numero(m.group('numero')), linea[:_MAX_LARGO_LINEA])
            if precio not in vistos:
                vistos.add(precio)
                resultado.append(precio)
    return resultado
