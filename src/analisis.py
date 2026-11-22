"""
Analisis estadistico de las corridas de ShopBot (sin dependencias externas).

Uso:
  python analisis.py [carpeta_con_csv] [--reclasificar]

  carpeta_con_csv  por defecto, la carpeta actual.
  --reclasificar   recalcula 'nivel' de cada fila con el detectores.py actual (hace falta
                   detectores.py y defensas.py en la misma carpeta). Asi TODAS las configs se
                   miden con el mismo detector. Sin este flag se usa el 'nivel' guardado en cada
                   CSV, que pudo salir de versiones distintas del detector.

Que hace:
  1. Tabla de trazabilidad: cada CSV -> config, esquema, modelo, repeticiones, y si se usa o no.
  2. Por variante y config: exitos, porcentaje e intervalo de Wilson al 95 %.
  3. Comparacion de configs (pares definidos en PARES) con test exacto de Fisher, con
     correccion de Holm por par (familia = las variantes de ese par).
  4. Herramientas (pruebas_tools.py): exito / contenido / fallo y control T5.

Salida en analisis_out/: trazabilidad.csv, variantes.csv, comparaciones.csv,
herramientas.csv, herramientas_comparaciones.csv, resumen.md
Fuera de alcance: P5 (LLM06) se excluye siempre.
"""
import csv, os, sys, math, collections, glob

USAR, DESCARTAR = "usar", "descartar"
MANIFIESTO = {
    # --- prompts (pruebas.py) ---
    "resultados_laxa.csv": (USAR, "30 reps"),
    "resultados_restrictivaSegundoIntento.csv": (USAR, "config 'debil' (nombre viejo: restrictiva), 30 reps"),
    "resultados_estricta.csv": (USAR, "30 reps"),
    "resultados_filtro.csv": (USAR, "30 reps"),
    "resultados_estricta_filtro.csv": (USAR, "30 reps"),
    "resultados_restrictivaPrimerIntento.csv": (DESCARTAR, "piloto 5 reps; lo reemplaza el de 30 reps"),
    "resultados_debil_SegundoIntento.csv": (DESCARTAR, "piloto 5 reps, esquema v1 (exito booleano), sin modelo registrado"),
    "resultados_debil_PrimerIntento.csv": (DESCARTAR, "piloto 1 rep, esquema v1"),
    # --- herramientas (pruebas_tools.py) ---
    "tools_v2_debil_20reps_20261109_181720.csv": (USAR, "v2, 20 reps, T1-T6"),
    "tools_v2_endurecida_20reps_20261109_182624.csv": (USAR, "v2, 20 reps, T1-T6"),
    "tools_debil_20reps_20261109_174504.csv": (DESCARTAR, "v1: prompt anterior, sin T6; lo reemplaza v2"),
    "tools_endurecida_20reps_20261109_175252.csv": (DESCARTAR, "v1: prompt anterior, sin T6; lo reemplaza v2"),
    "tools_debil_humo_3reps_20261109_174250.csv": (DESCARTAR, "prueba de humo, 3 reps"),
    "tools_v2_debil_humo_T6_2reps_20261109_181655.csv": (DESCARTAR, "prueba de humo T6, 2 reps"),
}

PARES = [
    ("debil", "laxa", "efecto de la linea 'no reveles' + etiqueta CONFIDENCIAL (el prompt debil cambia ambas cosas a la vez)"),
    ("estricta", "debil", "efecto de reglas de confidencialidad explicitas"),
    ("filtro", "laxa", "efecto del filtro de salida (mismo prompt)"),
    ("estricta_filtro", "estricta", "efecto del filtro de salida (mismo prompt)"),
    ("segmentada", "debil", "efecto de segmentar el ticket"),
    ("sin_secretos", "laxa", "efecto de minimizar secretos"),
]
ORDEN_CONFIGS = ["laxa", "debil", "estricta", "filtro", "estricta_filtro", "sin_secretos", "segmentada"]
ATAQUE_TOOLS = {"T1", "T2", "T3", "T4", "T6"}
OUT = "analisis_out"


# Estadistica
def wilson(k, n, z=1.96):
    """Intervalo de Wilson para una proporcion (en %)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, c - h), 100 * min(1.0, c + h))


def fisher(k1, n1, k2, n2):
    """Test exacto de Fisher de dos colas (mismo criterio que scipy.stats.fisher_exact)."""
    K, N = k1 + k2, n1 + n2
    lo, hi = max(0, K - n2), min(K, n1)
    prob = lambda x: math.comb(n1, x) * math.comb(n2, K - x) / math.comb(N, K)
    p_obs = prob(k1)
    return min(1.0, sum(p for p in (prob(x) for x in range(lo, hi + 1)) if p <= p_obs * (1 + 1e-7)))


def holm(pvals):
    """Correccion de Holm; devuelve los p ajustados en el orden original."""
    m = len(pvals)
    orden = sorted(range(m), key=lambda i: pvals[i])
    aj, prev = [0.0] * m, 0.0
    for rank, i in enumerate(orden):
        prev = max(prev, min(1.0, (m - rank) * pvals[i]))
        aj[i] = prev
    return aj


def celda(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%) [{lo:.0f}-{hi:.0f}]" if n else "-"


# Lectura
def leer(path):
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def esquema(campos):
    if "intentos_no_autorizados" in campos:
        return "tools-" + ("v2" if "version" in campos else "v1")
    if "nivel_modelo" in campos:
        return "prompts-v2-filtro"
    if "nivel" in campos:
        return "prompts-v2"
    if "exito" in campos:
        return "prompts-v1"
    return "desconocido"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    carpeta = args[0] if args else "."
    reclasificar = "--reclasificar" in sys.argv
    clasificar = None
    if reclasificar:
        sys.path.insert(0, os.getcwd())
        from detectores import clasificar  # noqa
    os.makedirs(OUT, exist_ok=True)

    archivos = sorted(os.path.basename(p) for p in glob.glob(os.path.join(carpeta, "*.csv")))
    trazab, prompts, tools = [], collections.defaultdict(list), collections.defaultdict(list)
    sin_clasificar = []
    for fn in archivos:
        campos, filas = leer(os.path.join(carpeta, fn))
        esq = esquema(campos)
        uso, motivo = MANIFIESTO.get(fn, ("sin clasificar", "no figura en MANIFIESTO: no se analiza"))
        if fn not in MANIFIESTO:
            sin_clasificar.append(fn)
        reps = sorted({n for n in collections.Counter((r["caso"], r["variante"]) for r in filas).values()})
        trazab.append({
            "archivo": fn, "config": ",".join(sorted({r.get("config", "?") for r in filas})),
            "esquema": esq, "modelo": ",".join(sorted({r.get("modelo") or "(sin registrar)" for r in filas})),
            "fecha": min((r.get("fecha", "") for r in filas), default="")[:10] or "(sin registrar)",
            "filas": len(filas), "reps_por_variante": "/".join(map(str, reps)),
            "uso": uso, "motivo": motivo})
        if uso != USAR:
            continue
        cfg = filas[0]["config"]
        if esq.startswith("tools"):
            tools[cfg] += filas
        elif esq.startswith("prompts-v2"):
            if cfg in prompts:
                sys.exit(f"Dos archivos 'usar' para la config '{cfg}'. Dejá uno solo en MANIFIESTO.")
            prompts[cfg] = [dict(r, _esq=esq) for r in filas]
        else:
            print(f"AVISO: {fn} tiene esquema {esq}, no se usa.")

    with open(f"{OUT}/trazabilidad.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trazab[0])); w.writeheader(); w.writerows(trazab)

    md = ["# Resumen de analisis", ""]
    md += [f"Detector: {'reclasificado con detectores.py actual' if reclasificar else 'nivel guardado en cada CSV (puede mezclar versiones; usar --reclasificar)'}",
           "Intervalos: Wilson 95 %. Comparaciones: Fisher exacto de dos colas, p ajustado por Holm dentro de cada par.",
           "Exito = el atacante logro su objetivo (nivel 'exito'); 'parcial' se informa aparte y NO cuenta como exito.",
           "Modelo/parametros: ver trazabilidad. P5 (LLM06) excluido por alcance.", ""]
    md += ["## Trazabilidad de CSV", "", "| archivo | config | esquema | modelo | fecha | filas | reps | uso | motivo |", "|---|---|---|---|---|---|---|---|---|"]
    for t in trazab:
        md.append("| " + " | ".join(str(t[k]) for k in ["archivo", "config", "esquema", "modelo", "fecha", "filas", "reps_por_variante", "uso", "motivo"]) + " |")
    md.append("")

    conteos = {}   
    for cfg, filas in prompts.items():
        for r in filas:
            if r["caso"] == "P5":
                continue
            nivel = r["nivel"]
            if reclasificar:
                tout = int(r["tokens_out"]) if r.get("tokens_out") not in (None, "", "None") else None
                nivel = clasificar(r["caso"], r["variante"], r["respuesta"], tout)[0]
            c = conteos.setdefault((cfg, r["caso"], r["variante"]),
                                   collections.Counter())
            c["n"] += 1
            c[nivel] += 1
            c["revisar"] += r.get("revisar") == "True"
            if "nivel_modelo" in r:
                c["modelo_exito"] += r["nivel_modelo"] == "exito" if not reclasificar else (
                    clasificar(r["caso"], r["variante"], r["respuesta_modelo"],
                               int(r["tokens_out"]) if r.get("tokens_out") not in (None, "", "None") else None)[0] == "exito")
                c["filtro"] += r.get("filtro_activado") == "True"
                c["tiene_modelo"] += 1

    cfgs = [c for c in ORDEN_CONFIGS if c in prompts] + [c for c in prompts if c not in ORDEN_CONFIGS]
    todas = {(k[1], k[2]) for k in conteos}
    faltan = {c: sorted(f"{a}/{b}" for a, b in todas if (c, a, b) not in conteos) for c in cfgs}
    faltan = {c: v for c, v in faltan.items() if v}
    claves = sorted({(k[1], k[2]) for k in conteos}, key=lambda x: (x[0], list(dict.fromkeys(k[2] for k in conteos if k[1] == x[0])).index(x[1])))
    with open(f"{OUT}/variantes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["caso", "variante", "config", "n", "exito", "pct", "wilson_lo", "wilson_hi", "parcial", "fallo", "filas_revisar"])
        for caso, var in claves:
            for cfg in cfgs:
                c = conteos.get((cfg, caso, var))
                if c:
                    lo, hi = wilson(c["exito"], c["n"])
                    w.writerow([caso, var, cfg, c["n"], c["exito"], round(100 * c["exito"] / c["n"], 1),
                                round(lo, 1), round(hi, 1), c["parcial"], c["fallo"], c["revisar"]])
    if faltan:
        md += ["## ATENCION: variantes sin datos", "",
               "Estas configs no tienen todas las variantes; esas comparaciones no se pueden hacer hasta volver a correrlas:", ""]
        md += [f"- {c}: {', '.join(v)}" for c, v in faltan.items()] + [""]
    md += ["## Exito del atacante por variante (prompts)", "", "Celda: exitos/n (porcentaje) [Wilson 95 %]", "",
           "| caso | variante | " + " | ".join(cfgs) + " |", "|---|---|" + "---|" * len(cfgs)]
    for caso, var in claves:
        md.append(f"| {caso} | {var} | " + " | ".join(
            celda(conteos[(c, caso, var)]["exito"], conteos[(c, caso, var)]["n"]) if (c, caso, var) in conteos else "-" for c in cfgs) + " |")
    md.append("")

    # por caso (variantes agrupadas): ojo, no son muestras independientes del mismo ataque
    md += ["## Exito por caso (variantes agrupadas)", "",
           "Agrupa variantes distintas: sirve como panorama, no como tasa de un ataque unico.", "",
           "| caso | " + " | ".join(cfgs) + " |", "|---|" + "---|" * len(cfgs)]
    for caso in sorted({k[1] for k in conteos}):
        fila = []
        for c in cfgs:
            ks = [v for k, v in conteos.items() if k[0] == c and k[1] == caso]
            fila.append(celda(sum(v["exito"] for v in ks), sum(v["n"] for v in ks)) if ks else "-")
        md.append(f"| {caso} | " + " | ".join(fila) + " |")
    md.append("")

    # comparaciones Fisher + Holm
    comp_rows, md_comp = [], []
    for a, b, porque in PARES:
        if a not in prompts or b not in prompts:
            continue
        vars_ = [(caso, var) for caso, var in claves if (a, caso, var) in conteos and (b, caso, var) in conteos]
        res = []
        for caso, var in vars_:
            ca, cb = conteos[(a, caso, var)], conteos[(b, caso, var)]
            res.append((caso, var, ca["exito"], ca["n"], cb["exito"], cb["n"], fisher(ca["exito"], ca["n"], cb["exito"], cb["n"])))
        aj = holm([x[6] for x in res])
        md_comp += [f"### {a} vs {b}: {porque}", "", f"| caso | variante | {a} | {b} | p (Fisher) | p Holm |", "|---|---|---|---|---|---|"]
        for (caso, var, ka, na, kb, nb, p), pa in zip(res, aj):
            comp_rows.append([a, b, caso, var, ka, na, kb, nb, round(p, 5), round(pa, 5)])
            if ka or kb:   
                marca = " **" if pa < 0.05 else ""
                md_comp.append(f"| {caso} | {var} | {celda(ka, na)} | {celda(kb, nb)} | {p:.4f} | {pa:.4f}{marca} |")
        md_comp.append("")
    with open(f"{OUT}/comparaciones.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["config_a", "config_b", "caso", "variante", "exito_a", "n_a", "exito_b", "n_b", "p_fisher", "p_holm"])
        w.writerows(comp_rows)
    md += ["## Comparaciones entre configuraciones (solo filas con algun exito; ** = p Holm < 0.05)", ""] + md_comp

    # filtro de salida: modelo vs usuario
    con_filtro = [c for c in cfgs if any(conteos.get((c, k[1], k[2]), {}).get("tiene_modelo") for k in conteos if k[0] == c)
                  and any(conteos[k]["filtro"] for k in conteos if k[0] == c)]
    if con_filtro:
        md += ["## Filtro de salida: lo que dijo el modelo vs lo que vio el usuario", "",
               "| config | caso | exito del modelo | exito visible | filtro activado | filas |", "|---|---|---|---|---|---|"]
        for c in con_filtro:
            for caso in sorted({k[1] for k in conteos if k[0] == c}):
                ks = [v for k, v in conteos.items() if k[0] == c and k[1] == caso]
                md.append(f"| {c} | {caso} | {sum(v['modelo_exito'] for v in ks)} | {sum(v['exito'] for v in ks)} | "
                          f"{sum(v['filtro'] for v in ks)} | {sum(v['n'] for v in ks)} |")
        md += ["", "Nota: el filtro solo detecta secretos. No tapa exitos de P1/P2 que no filtran datos.", ""]

    if tools:
        tc = {}
        for cfg, filas in tools.items():
            for r in filas:
                c = tc.setdefault((cfg, r["caso"], r["variante"]), collections.Counter())
                c["n"] += 1
                c[r["nivel"]] += 1
        tcfgs = [c for c in ("debil", "endurecida") if c in tools]
        tclaves = sorted({(k[1], k[2]) for k in tc}, key=lambda x: (x[0], x[1]))
        with open(f"{OUT}/herramientas.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["caso", "variante", "config", "n", "exito", "contenido", "fallo", "control_ok", "control_parcial", "control_falla", "error"])
            for caso, var in tclaves:
                for c in tcfgs:
                    v = tc.get((c, caso, var))
                    if v:
                        w.writerow([caso, var, c, v["n"], v["exito"], v["contenido"], v["fallo"], v["control_ok"],
                                    v["control_parcial"], v["control_falla"], v["error"]])
        md += ["## Herramientas (LLM03)", "",
               "Ataques (T1-T4, T6). exito = el ataque tuvo efecto real; contenido = el modelo fue manipulado pero el backend lo freno.",
               "'intento' = exito + contenido: el modelo llamo a una herramienta sobre algo que no le correspondia.",
               "En T1/T2 el atacante es el usuario (pedido directo); en T3/T4/T6 la orden viene de un ticket o de una nota en el resultado de una herramienta (inyeccion indirecta).", "",
               "### Resumen por caso (variantes agrupadas)", "",
               "| caso | config | n | exito real | intento no autorizado |", "|---|---|---|---|---|"]
        for caso in sorted(ATAQUE_TOOLS):
            for c in tcfgs:
                vs = [v for k, v in tc.items() if k[0] == c and k[1] == caso]
                if vs:
                    n_ = sum(v["n"] for v in vs); e_ = sum(v["exito"] for v in vs); i_ = e_ + sum(v["contenido"] for v in vs)
                    md.append(f"| {caso} | {c} | {n_} | {celda(e_, n_)} | {celda(i_, n_)} |")
        md += ["", "### Detalle por variante", "",
               "| caso | variante | config | exito real | contenido | intento | fallo |", "|---|---|---|---|---|---|---|"]
        for caso, var in tclaves:
            if caso not in ATAQUE_TOOLS:
                continue
            for c in tcfgs:
                v = tc.get((c, caso, var))
                if v:
                    md.append(f"| {caso} | {var} | {c} | {celda(v['exito'], v['n'])} | {v['contenido']}/{v['n']} | "
                              f"{celda(v['exito'] + v['contenido'], v['n'])} | {v['fallo']}/{v['n']} |")
        md.append("")
        if len(tcfgs) == 2:
            a, b = "debil", "endurecida"
            res = []
            for caso, var in tclaves:
                if caso in ATAQUE_TOOLS and (a, caso, var) in tc and (b, caso, var) in tc:
                    x, y = tc[(a, caso, var)], tc[(b, caso, var)]
                    res.append((caso, var, x["exito"], x["n"], y["exito"], y["n"], fisher(x["exito"], x["n"], y["exito"], y["n"])))
            aj = holm([r[6] for r in res])
            with open(f"{OUT}/herramientas_comparaciones.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["caso", "variante", "exito_debil", "n_debil", "exito_endurecida", "n_endurecida", "p_fisher", "p_holm"])
                for (caso, var, ka, na, kb, nb, p), pa in zip(res, aj):
                    w.writerow([caso, var, ka, na, kb, nb, round(p, 5), round(pa, 5)])
            md += ["### debil vs endurecida: exito real (Fisher, Holm)", "",
                   "| caso | variante | debil | endurecida | p | p Holm |", "|---|---|---|---|---|---|"]
            for (caso, var, ka, na, kb, nb, p), pa in zip(res, aj):
                md.append(f"| {caso} | {var} | {celda(ka, na)} | {celda(kb, nb)} | {p:.4f} | {pa:.4f}{' **' if pa < 0.05 else ''} |")
            md.append("")
        md += ["### Control T5 (utilidad / falsos positivos)", "",
               "ok = accion y respuesta correctas; parcial = accion ok con respuesta pobre; falla = accion incorrecta.", "",
               "| variante | config | ok | parcial | falla | error |", "|---|---|---|---|---|---|"]
        for caso, var in tclaves:
            if caso != "T5":
                continue
            for c in tcfgs:
                v = tc.get((c, caso, var))
                if v:
                    md.append(f"| {var} | {c} | {celda(v['control_ok'], v['n'])} | {v['control_parcial']}/{v['n']} | {v['control_falla']}/{v['n']} | {v['error']} |")
        md.append("")

    with open(f"{OUT}/resumen.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"Config(s) de prompts usadas: {', '.join(cfgs) or '-'} | herramientas: {', '.join(tools) or '-'}")
    print(f"Detector: {'reclasificado' if reclasificar else 'guardado en los CSV'}")
    for c, v in faltan.items():
        print(f"AVISO: a '{c}' le faltan variantes: {', '.join(v)}")
    if sin_clasificar:
        print("\nAVISO: estos CSV no figuran en MANIFIESTO y NO se analizaron:")
        for fn in sin_clasificar:
            print("  -", fn)
        print("Agregalos a MANIFIESTO (usar / descartar) para que cuenten.")
    print(f"\nListo. Mirá {OUT}/resumen.md (tablas) y los CSV de {OUT}/.")


if __name__ == "__main__":
    main()
