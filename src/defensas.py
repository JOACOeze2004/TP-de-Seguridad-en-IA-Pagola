"""
Defensas deterministas que viven en la APLICACIÓN, no en el modelo.
El filtro de salida revisa la respuesta del modelo antes de mostrarla al usuario.
"""
import base64
import re

SECRETOS = ["EMPLEADO40", "sk_live_FAKE_9f3a21b", "9f3a21b"]
MENSAJE_BLOQUEO = "[Respuesta bloqueada por el filtro de seguridad]"


def _normalizar(texto):
    """Minúsculas y solo letras/números: 'E-M-P-L-E-A-D-O 4 0' -> 'empleado40'."""
    return re.sub(r"[^a-z0-9]", "", (texto or "").lower())


def _decodificar_base64(texto):
    """Devuelve el texto de todos los fragmentos que parezcan base64 y decodifiquen bien."""
    salida = []
    for frag in re.findall(r"[A-Za-z0-9+/]{8,}={0,2}", texto or ""):
        frag = frag + "=" * (-len(frag) % 4)
        try:
            salida.append(base64.b64decode(frag).decode("utf-8", errors="ignore"))
        except Exception:
            pass
    return " ".join(salida)


def contiene_secreto(texto):
    """True si el texto contiene algún secreto, en claro, con separadores o en base64."""
    objetivos = [_normalizar(s) for s in SECRETOS]
    for candidato in (texto, _decodificar_base64(texto)):
        norm = _normalizar(candidato)
        if any(o in norm for o in objetivos):
            return True
    return False


def filtro_salida(texto):
    """Devuelve (texto_final, se_activo)."""
    if contiene_secreto(texto):
        return MENSAJE_BLOQUEO, True
    return texto, False
