"""
Uso: python reanalizar.py <archivo.csv> [--incluir-p5]
Reclasifica un CSV de pruebas.py con el detectores.py actual y compara contra la clasificación guardada.
Genera <archivo>_reanalizado.csv y <archivo>_cambios.csv.
"""
import csv, sys, collections
from detectores import clasificar

NIVELES = ["exito", "parcial", "fallo"]


def detectar_esquema(campos):
    if "intentos_no_autorizados" in campos:
        sys.exit("Este CSV es de pruebas_tools.py (no usa detectores.py): no se reclasifica aca.")
    if "nivel_modelo" in campos and "respuesta_modelo" in campos:
        return "v2-filtro"
    if "nivel" in campos:
        return "v2"
    if "exito" in campos:
        return "v1"
    sys.exit(f"Esquema no reconocido. Columnas: {campos}")


def nivel_viejo(fila, esquema):
    if esquema == "v1":
        return "exito" if fila["exito"] == "True" else "no_exito"  # v1 no distingue parcial de fallo
    return fila["nivel"]


def a_int(x):
    return int(x) if x not in (None, "", "None") else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    incluir_p5 = "--incluir-p5" in sys.argv
    if not args:
        sys.exit(__doc__)
    fn = args[0]

    with open(fn, encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames
        filas = list(lector)
    esquema = detectar_esquema(campos)

    p5 = [r for r in filas if r["caso"] == "P5"]
    if not incluir_p5:
        filas = [r for r in filas if r["caso"] != "P5"]
    print(f"Archivo: {fn}\nEsquema: {esquema} | filas analizadas: {len(filas)}"
          f"{f' (se excluyeron {len(p5)} de P5, fuera de alcance)' if p5 and not incluir_p5 else ''}\n")

    por_variante = collections.defaultdict(collections.Counter)
    matriz = collections.Counter()
    cambios = []
    for r in filas:
        tout = a_int(r.get("tokens_out"))
        viejo = nivel_viejo(r, esquema)
        nuevo, motivo, rev = clasificar(r["caso"], r["variante"], r["respuesta"], tout)
        r["nivel_viejo"], r["nivel_nuevo"] = viejo, nuevo
        r["motivo_nuevo"], r["revisar_nuevo"] = motivo, rev
        if esquema == "v2-filtro":
            nm, _, _ = clasificar(r["caso"], r["variante"], r["respuesta_modelo"], tout)
            r["nivel_modelo_viejo"], r["nivel_modelo_nuevo"] = r["nivel_modelo"], nm
        # en v1 solo se puede comparar "exito" contra "no exito"
        comparable = nuevo if esquema != "v1" else ("exito" if nuevo == "exito" else "no_exito")
        r["cambio"] = viejo != comparable
        matriz[(viejo, comparable)] += 1
        por_variante[(r["caso"], r["variante"])][(viejo, comparable)] += 1
        if r["cambio"]:
            cambios.append(r)

    filas_m = NIVELES if esquema != "v1" else ["exito", "no_exito"]
    cols_m = filas_m
    print("Matriz (filas = clasificacion que traia el CSV, columnas = detector actual)")
    print(f"{'':12}" + "".join(f"{c:>10}" for c in cols_m))
    for a in filas_m:
        print(f"{a:12}" + "".join(f"{matriz[(a, b)]:>10}" for b in cols_m))
    n = len(filas)
    print(f"\nFilas que cambian: {len(cambios)}/{n} ({100 * len(cambios) / n:.1f}%)")
    if esquema != "v1":
        print(f"  fallo -> exito:  {matriz[('fallo', 'exito')]}   (posibles falsos positivos nuevos)")
        print(f"  exito -> fallo:  {matriz[('exito', 'fallo')]}   (posibles falsos negativos nuevos)")
        print(f"  a/desde parcial: {sum(v for (a, b), v in matriz.items() if a != b and 'parcial' in (a, b))}")
    else:
        print(f"  no_exito -> exito: {matriz[('no_exito', 'exito')]}")
        print(f"  exito -> no_exito: {matriz[('exito', 'no_exito')]}")

    # ---- detalle por variante (solo donde hay cambios) ----
    print("\nVariantes con cambios (viejo->nuevo: cantidad)")
    hay = False
    for (c, v), cnt in sorted(por_variante.items()):
        dif = {k: x for k, x in cnt.items() if k[0] != k[1]}
        if dif:
            hay = True
            txt = ", ".join(f"{a}->{b}: {x}" for (a, b), x in sorted(dif.items()))
            print(f"  {c}/{v:18} de {sum(cnt.values())}: {txt}")
    if not hay:
        print("  (ninguna)")

    if esquema == "v2-filtro":
        cm = sum(1 for r in filas if r["nivel_modelo_viejo"] != r["nivel_modelo_nuevo"])
        print(f"\nnivel_modelo (sin filtro) cambia en {cm}/{n} filas")

    base = fn[:-4] if fn.endswith(".csv") else fn
    extra = ["nivel_viejo", "nivel_nuevo", "motivo_nuevo", "revisar_nuevo", "cambio"]
    if esquema == "v2-filtro":
        extra += ["nivel_modelo_viejo", "nivel_modelo_nuevo"]
    salida_campos = list(campos) + [c for c in extra if c not in campos]
    for nombre, datos in ((f"{base}_reanalizado.csv", filas), (f"{base}_cambios.csv", cambios)):
        with open(nombre, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=salida_campos, extrasaction="ignore")
            w.writeheader()
            w.writerows(datos)
    print(f"\nGuardado: {base}_reanalizado.csv y {base}_cambios.csv")
    print("Revisa a mano _cambios.csv: es la muestra para validar si el detector nuevo mejora o solo mueve el error.")


if __name__ == "__main__":
    main()
