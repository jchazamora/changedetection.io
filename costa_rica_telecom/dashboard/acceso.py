"""
Usuario y contraseña para entrar al dashboard.

Los usuarios van en los Secrets de Streamlit (en Community Cloud: Settings → Secrets; en la máquina local:
.streamlit/secrets.toml junto a app.py, que no se sube a git), uno por línea:

    [usuarios]
    jorge = "una contraseña larga"

Sin la sección [usuarios] el dashboard abre sin pedir nada, como al usarlo en la propia máquina.
"""

import hmac

import streamlit as st


def usuarios_configurados():
    """{usuario en minúsculas: contraseña} tomados de los Secrets, o {} si no hay."""
    try:
        usuarios = st.secrets.get('usuarios') or {}
    except FileNotFoundError:  # no hay ningún secrets.toml
        usuarios = {}
    return {str(usuario).strip().lower(): str(clave) for usuario, clave in usuarios.items()}


def credenciales_validas(usuarios, usuario, clave):
    """El usuario no distingue mayúsculas ni espacios alrededor; la contraseña sí."""
    esperada = usuarios.get((usuario or '').strip().lower())
    # Se compara aunque el usuario no exista, para que el tiempo de respuesta no revele cuáles existen
    coincide = hmac.compare_digest((clave or '').encode(), (esperada or '').encode())
    return bool(esperada) and coincide
