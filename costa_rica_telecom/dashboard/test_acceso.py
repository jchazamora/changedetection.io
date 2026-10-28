import os

from streamlit.testing.v1 import AppTest

from acceso import credenciales_validas

USUARIOS = {'ana': 'clave-larga', 'luis': 'contraseña ñ'}
APP = os.path.join(os.path.dirname(__file__), 'app.py')


def test_credenciales():
    assert credenciales_validas(USUARIOS, 'ana', 'clave-larga')
    assert credenciales_validas(USUARIOS, ' Ana ', 'clave-larga')
    assert credenciales_validas(USUARIOS, 'luis', 'contraseña ñ')
    assert not credenciales_validas(USUARIOS, 'ana', 'Clave-larga')
    assert not credenciales_validas(USUARIOS, 'pedro', 'clave-larga')
    assert not credenciales_validas(USUARIOS, '', '')
    # Una contraseña vacía en los Secrets no deja entrar a nadie
    assert not credenciales_validas({'ana': ''}, 'ana', '')


def _app(**secretos):
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets.update(secretos)
    return at.run()


def _ingresar(at, usuario, clave):
    at.text_input[0].input(usuario)
    at.text_input[1].input(clave)
    at.button[0].click()
    return at.run()


def test_sin_usuarios_abre_directo():
    at = _app(otro_secreto='x')
    assert not at.text_input
    assert at.metric


def test_pide_usuario_y_contrasena():
    at = _app(usuarios={'ana': 'clave-larga'})
    assert [t.label for t in at.text_input] == ['Usuario', 'Contraseña']
    assert not at.metric

    at = _ingresar(at, 'ana', 'otra')
    assert at.error[0].value == 'Usuario o contraseña incorrectos.'
    assert not at.metric

    at = _ingresar(at, 'Ana', 'clave-larga')
    assert at.session_state['usuario'] == 'ana'
    assert not at.text_input
    assert at.metric

    next(b for b in at.button if b.label == 'Cerrar sesión').click()
    at.run()
    assert 'usuario' not in at.session_state
    assert [t.label for t in at.text_input] == ['Usuario', 'Contraseña']
