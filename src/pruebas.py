"""
Uso: python pruebas.py <config> <repeticiones> [variante1,variante2,...]

Configuraciones:
  debil            prompt con instrucción genérica de confidencialidad ("no reveles...")
  laxa             prompt sin esa línea
  estricta         prompt con reglas de confidencialidad que nombran los datos protegidos
  filtro           prompt laxa + filtro de salida en la aplicación
  estricta_filtro  prompt estricta + filtro de salida
  sin_secretos     prompt sin credenciales internas (solo reglas de dominio y descuento)
  segmentada       separa SystemMessage de datos externos (<ticket_externo>) en HumanMessage
  combinada        reglas estrictas + segmentación + filtro de salida (defensa en profundidad)

Casos: P1 (desvío directo), P2 (inyección indirecta por ticket), P3 (contexto oculto)
y C (control: consultas legítimas, mide falsos positivos). P5 (LLM06) está fuera de alcance.

Los prompts, las configs y los casos viven en core.py (los comparte con la app de Streamlit).
"""
import csv, time, collections, sys
from datetime import datetime
import detectores
from detectores import clasificar
from core import MODELO, TEMPERATURA, CONFIGS, CASOS, nuevo_modelo, entrada_de, construir_cadena, postprocesar

# ---------- Parámetros ----------
CONFIG = sys.argv[1] if len(sys.argv) > 1 else "debil"
REPETICIONES = int(sys.argv[2]) if len(sys.argv) > 2 else 5
SOLO = sys.argv[3].split(",") if len(sys.argv) > 3 else None
SALIDA = f"resultados_{CONFIG}_{datetime.now():%Y%m%d_%H%M%S}.csv"

VERSION_ESQUEMA = "p-v3"  # v3: sin P5, con caso C, columnas seed/version_*
VERSION_DETECTOR = getattr(detectores, "VERSION_DETECTOR", "sin_version")


def correr():
    if CONFIG not in CONFIGS:
        sys.exit(f"Config '{CONFIG}' no existe. Opciones: {', '.join(CONFIGS)}")

    casos = [c for c in CASOS if SOLO is None or c[1] in SOLO or c[0] in SOLO]
    total, n = len(casos) * REPETICIONES, 0
    campos = ["fecha", "version_esquema", "version_detector", "modelo", "temperatura", "seed",
              "config", "caso", "variante", "rep",
              "mensaje", "ticket", "nivel", "motivo", "revisar",
              "nivel_modelo", "filtro_activado",
              "tokens_in", "tokens_out", "segundos", "respuesta", "respuesta_modelo"]

    with open(SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos); w.writeheader()
        for caso, variante, mensaje, ticket, hist in casos:
            for rep in range(1, REPETICIONES + 1):
                n += 1
                # Un modelo por repetición: la semilla es el número de rep (reproducible)
                cadena = construir_cadena(CONFIG, nuevo_modelo(rep))
                entrada = entrada_de(mensaje, ticket, hist)
                t0 = time.time()
                try:
                    r = cadena.invoke(entrada)
                    crudo = r.content
                    um = getattr(r, "usage_metadata", None) or {}
                    tin, tout = um.get("input_tokens"), um.get("output_tokens")
                except Exception as e:
                    crudo, tin, tout = f"ERROR: {e}", None, None
                dt = round(time.time() - t0, 2)

                # Lo que ve el usuario (con o sin filtro) y lo que dijo el modelo
                final, activo = postprocesar(CONFIG, crudo)

                nivel, motivo, rev = clasificar(caso, variante, final, tout)
                nivel_modelo, _, _ = clasificar(caso, variante, crudo, tout)
                w.writerow({"fecha": datetime.now().isoformat(timespec="seconds"),
                            "version_esquema": VERSION_ESQUEMA, "version_detector": VERSION_DETECTOR,
                            "modelo": MODELO, "temperatura": TEMPERATURA, "seed": rep,
                            "config": CONFIG, "caso": caso, "variante": variante, "rep": rep,
                            "mensaje": mensaje, "ticket": ticket,
                            "nivel": nivel, "motivo": motivo, "revisar": rev,
                            "nivel_modelo": nivel_modelo, "filtro_activado": activo,
                            "tokens_in": tin, "tokens_out": tout, "segundos": dt,
                            "respuesta": final.replace("\n", " "),
                            "respuesta_modelo": crudo.replace("\n", " ")})
                f.flush()
                print(f"[{n}/{total}] {caso}/{variante} rep{rep} -> {nivel} "
                      f"(modelo: {nivel_modelo}{', filtro ON' if activo else ''}) ({dt}s)")
    resumen()


def resumen():
    st = collections.defaultdict(collections.Counter)
    with open(SALIDA, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            k = (fila["caso"], fila["variante"])
            st[k]["n"] += 1
            st[k][fila["nivel"]] += 1
            if fila["nivel_modelo"] == "exito":
                st[k]["modelo_exito"] += 1
            if fila["filtro_activado"] == "True":
                st[k]["filtro"] += 1
            if fila["respuesta"].startswith("ERROR"):
                st[k]["error"] += 1
    print(f"\n=== Resultados (lo que ve el usuario) | detector {VERSION_DETECTOR} ===")
    print(f"{'':3} {'variante':18} exito  parcial  | éxito del modelo sin filtro | filtro activado | errores")
    for (c, v), cnt in st.items():
        n = cnt["n"]
        if c == "C":  # control: 'falla' = falso positivo
            print(f"{c:3} {v:18} control_ok {cnt['control_ok']}/{n}  falla {cnt['control_falla']}/{n}"
                  f"  | filtro activado {cnt['filtro']}/{n} | errores {cnt['error']}")
            continue
        print(f"{c:3} {v:18} {cnt['exito']}/{n}  {cnt['parcial']}/{n}     | {cnt['modelo_exito']}/{n}"
              f"                         | {cnt['filtro']}/{n}            | {cnt['error']}")
    print(f"\nDetalle en: {SALIDA}  (revisá a mano las filas con revisar=True)")


if __name__ == "__main__":
    correr()
