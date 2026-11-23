"""
Analisis estadistico de las corridas de ShopBot (sin dependencias externas).

Uso:
  python analisis.py [carpeta_con_csv] [--reclasificar]

  carpeta_con_csv  por defecto, la carpeta actual. Se busca en TODAS las subcarpetas
                   (evidencia/llm01_prompts/laxa/..., evidencia/llm03_tools/..., etc.).
                   Todo CSV dentro de una carpeta 'descartados/' se descarta; el resto se usa.
                   Los nombres de archivo no pueden repetirse entre subcarpetas.
  --reclasificar   recalcula 'nivel' de cada fila con el detectores.py actual (hace falta
                   detectores.py y defensas.py junto a analisis.py, en src/). Asi TODAS
                   las configs se miden con el mismo detector. Sin este flag se usa el 'nivel'
                   guardado en cada CSV, que pudo salir de versiones distintas del detector.

Que hace:
  1. Tabla de trazabilidad: cada CSV -> config, esquema, version, modelo, repeticiones, y si se usa o no.
  2. Por variante y config: exitos, porcentaje e intervalo de Wilson al 95 %.
  3. Comparacion de configs (pares definidos en PARES) con test exacto de Fisher, con
     correccion de Holm por par (familia = las variantes de ese par). Se hace sobre el exito
     del atacante (P1-P3) y sobre los falsos positivos del caso de control C.
  4. Caso de control C (pruebas.py): falsos positivos del prompt y del filtro de salida.
  5. Herramientas (pruebas_tools.py): exito / contenido / fallo, control T5, T6 condicionado a que
     la nota se haya leido (columna nota_leida, solo CSV v3) y comparacion directo vs indirecto
     (mismo texto por distinto canal: ticket vs nota en el resultado de la herramienta).

Salida en analisis_out/: trazabilidad.csv, variantes.csv, control.csv, comparaciones.csv,
herramientas.csv, herramientas_comparaciones.csv, resumen.md
Fuera de alcance: P5 (LLM06) se excluye siempre.
"""
import csv, os, sys, math, collections, glob

USAR, DESCARTAR = "usar", "descartar"
CARPETA_DESCARTADOS = "descartados"
# El uso lo decide la CARPETA: todo CSV que cuelgue de una carpeta llamada 'descartados' se
# descarta y el resto se usa. NOTAS es opcional: sirve solo para dejar el motivo en la trazabilidad.
NOTAS = {
    "resultados_restrictivaPrimerIntento.csv": "piloto 5 reps",
    "resultados_debil_SegundoIntento.csv": "piloto 5 reps, esquema v1, sin modelo registrado",
    "resultados_debil_PrimerIntento.csv": "piloto 1 rep, esquema v1",
    "resultados_restrictivaSegundoIntento.csv": "config 'debil' (nombre viejo: restrictiva), esquema anterior",
    "tools_debil_20reps_20261109_174504.csv": "v1: prompt anterior, sin T6",
    "tools_endurecida_20reps_20261109_175252.csv": "v1: prompt anterior, sin T6",
    "tools_debil_humo_3reps_20261109_174250.csv": "prueba de humo, 3 reps",
    "tools_v2_debil_humo_T6_2reps_20261109_181655.csv": "prueba de humo T6, 2 reps",
}


def uso_de(ruta, carpeta):
    """(uso, motivo) de un CSV segun su ubicacion bajo 'carpeta'."""
    partes = os.path.normpath(os.path.relpath(ruta, carpeta)).split(os.sep)
    nota = NOTAS.get(partes[-1], "")
    if CARPETA_DESCARTADOS in partes[:-1]:
        return DESCARTAR, nota or f"en {CARPETA_DESCARTADOS}/"
    return USAR, nota


# Pares a comparar: (config A, config B, por que). Se omiten si falta alguna de las dos.
PARES = [
    ("debil", "laxa", "efecto de la linea 'no reveles' + etiqueta CONFIDENCIAL (el prompt debil cambia ambas cosas a la vez)"),
    ("estricta", "debil", "efecto de reglas de confidencialidad explicitas"),
    ("filtro", "laxa", "efecto del filtro de salida (mismo prompt)"),
    ("estricta_filtro", "estricta", "efecto del filtro de salida (mismo prompt)"),
    ("segmentada", "debil", "efecto de segmentar el ticket (cambia varias cosas a la vez, ver informe)"),
    ("sin_secretos", "laxa", "efecto de minimizar secretos"),
    ("combinada", "estricta_filtro", "efecto de segmentar el ticket (mismas reglas estrictas y mismo filtro)"),
    ("combinada", "segmentada", "efecto de sumar reglas estrictas y filtro a la segmentacion"),
    ("combinada", "debil", "defensa en profundidad vs la config de la app original"),
]
# Mismo texto de ataque por distinto canal: (ticket en el prompt) vs (nota en el resultado de la herramienta).
# nota_entregado y nota_json NO son identicos a sus equivalentes de T4, asi que no se comparan.
PARES_CANAL = [
    (("T3", "ticket_simple"), ("T6", "nota_simple")),
    (("T3", "ticket_supervisor"), ("T6", "nota_supervisor")),
    (("T4", "ticket_cancelar"), ("T6", "nota_cancelar")),
]
ORDEN_CONFIGS = ["laxa", "debil", "estricta", "filtro", "estricta_filtro", "sin_secretos", "segmentada", "combinada"]
ATAQUE_TOOLS = {"T1", "T2", "T3", "T4", "T6"}
OUT = "analisis_out"
SUFIJOS_DERIVADOS = ("_reanalizado.csv", "_cambios.csv")   # salidas de reanalizar.py: se ignoran


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


def tabla_fisher(titulo, items, nom_a, nom_b, mostrar_ceros=True):
    """items: lista de (etiqueta, ka, na, kb, nb). Holm sobre toda la lista (la familia).
    Devuelve (filas_csv, lineas_md). Con mostrar_ceros=False el md omite las filas 0 vs 0
    (siguen en el csv y en la familia de Holm)."""
    items = [it for it in items if it[2] and it[4]]
    if not items:
        return [], []
    ps = [fisher(ka, na, kb, nb) for _, ka, na, kb, nb in items]
    aj = holm(ps)
    md = [f"### {titulo}", "", f"| comparacion | {nom_a} | {nom_b} | p (Fisher) | p Holm |", "|---|---|---|---|---|"]
    filas = []
    for (et, ka, na, kb, nb), p, pa in zip(items, ps, aj):
        filas.append([titulo, et, ka, na, kb, nb, round(p, 5), round(pa, 5)])
        if mostrar_ceros or ka or kb:
            md.append(f"| {et} | {celda(ka, na)} | {celda(kb, nb)} | {p:.4f} | {pa:.4f}{' **' if pa < 0.05 else ''} |")
    md.append("")
    return filas, md


def escribir_csv(ruta, cabecera, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)


def _int(x):
    return int(x) if x not in (None, "", "None") else None


# Lectura
def leer(path):
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)


def esquema(campos):
    if "intentos_no_autorizados" in campos:
        if "iter_agotado" in campos:
            return "tools-v3"
        return "tools-v2" if "version" in campos else "tools-v1"
    if "version_esquema" in campos:
        return "prompts-v3"
    if "nivel_modelo" in campos:
        return "prompts-v2-filtro"
    if "nivel" in campos:
        return "prompts-v2"
    if "exito" in campos:
        return "prompts-v1"
    return "desconocido"


def primero(filas, *columnas):
    """Primer valor no vacio de las columnas dadas, o '(sin registrar)'."""
    for col in columnas:
        v = next((r.get(col) for r in filas if r.get(col)), None)
        if v:
            return v
    return "(sin registrar)"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    carpeta = args[0] if args else "."
    reclasificar = "--reclasificar" in sys.argv
    clasificar = None
    if reclasificar:
        sys.path.insert(0, os.getcwd())
        from detectores import clasificar  # noqa
    os.makedirs(OUT, exist_ok=True)

    # ---- descubrir CSV (recursivo; ignora la carpeta de salida y los derivados de reanalizar.py) ----
    rutas = {}
    for p in glob.glob(os.path.join(carpeta, "**", "*.csv"), recursive=True):
        partes = os.path.normpath(p).split(os.sep)
        if OUT in partes[:-1] or p.endswith(SUFIJOS_DERIVADOS):
            continue
        nombre = os.path.basename(p)
        if nombre in rutas:
            sys.exit(f"El archivo '{nombre}' aparece dos veces:\n  {rutas[nombre]}\n  {p}\n"
                     "Los nombres no pueden repetirse entre subcarpetas.")
        rutas[nombre] = p
    archivos = sorted(rutas)

    trazab, prompts, tools = [], collections.defaultdict(list), collections.defaultdict(list)
    tools_archivo = {}
    for fn in archivos:
        campos, filas = leer(rutas[fn])
        esq = esquema(campos)
        uso, motivo = uso_de(rutas[fn], carpeta)
        if "caso" in campos and "variante" in campos:
            reps = sorted({n for n in collections.Counter((r["caso"], r["variante"]) for r in filas).values()})
        else:
            reps = []
        trazab.append({
            "archivo": fn, "carpeta": os.path.dirname(os.path.relpath(rutas[fn], carpeta)) or ".",
            "config": ",".join(sorted({r.get("config", "?") for r in filas})),
            "esquema": esq,
            "version": primero(filas, "version_esquema", "version"),
            "detector": primero(filas, "version_detector"),
            "seed": "si" if "seed" in campos else "no",
            "modelo": ",".join(sorted({r.get("modelo") or "(sin registrar)" for r in filas})),
            "fecha": min((r.get("fecha", "") for r in filas), default="")[:10] or "(sin registrar)",
            "filas": len(filas), "reps_por_variante": "/".join(map(str, reps)),
            "uso": uso, "motivo": motivo})
        if uso != USAR or not filas:
            continue
        cfg = filas[0]["config"]
        if esq.startswith("tools"):
            if cfg in tools_archivo:
                sys.exit(f"Dos archivos 'usar' de herramientas para la config '{cfg}': "
                         f"{tools_archivo[cfg]} y {fn}. Mové el viejo a {CARPETA_DESCARTADOS}/.")
            tools_archivo[cfg] = fn
            tools[cfg] = filas
        elif esq.startswith("prompts") and esq != "prompts-v1":
            if cfg in prompts:
                sys.exit(f"Dos archivos 'usar' para la config '{cfg}' (el segundo es {fn}). "
                         f"Mové el viejo a {CARPETA_DESCARTADOS}/.")
            prompts[cfg] = filas
        else:
            print(f"AVISO: {fn} tiene esquema {esq}, no se usa.")

    if trazab:
        escribir_csv(f"{OUT}/trazabilidad.csv", list(trazab[0]), [list(t.values()) for t in trazab])

    cols_traza = ["archivo", "carpeta", "config", "esquema", "version", "detector", "seed", "modelo", "fecha", "filas",
                  "reps_por_variante", "uso", "motivo"]
    md = ["# Resumen de analisis", ""]
    md += [f"Detector: {'reclasificado con detectores.py actual' if reclasificar else 'nivel guardado en cada CSV (puede mezclar versiones; usar --reclasificar)'}",
           "Intervalos: Wilson 95 %. Comparaciones: Fisher exacto de dos colas, p ajustado por Holm dentro de cada familia.",
           "Exito = el atacante logro su objetivo (nivel 'exito'); 'parcial' se informa aparte y NO cuenta como exito.",
           "Control C / T5: miden utilidad y falsos positivos, no ataque.",
           "Modelo/parametros: ver trazabilidad. P5 (LLM06) excluido por alcance.", ""]
    md += ["## Trazabilidad de CSV", "", "| " + " | ".join(cols_traza) + " |", "|" + "---|" * len(cols_traza)]
    for t in trazab:
        md.append("| " + " | ".join(str(t[k]) for k in cols_traza) + " |")
    md.append("")

    conteos = {}   # (config, caso, variante) -> Counter
    orden_var = []
    for cfg, filas in prompts.items():
        for r in filas:
            if r["caso"] == "P5":
                continue
            k = (r["caso"], r["variante"])
            if k not in orden_var:
                orden_var.append(k)
            nivel, nm = r["nivel"], r.get("nivel_modelo")
            if reclasificar:
                t = _int(r.get("tokens_out"))
                nivel = clasificar(r["caso"], r["variante"], r["respuesta"], t)[0]
                if nm is not None and "respuesta_modelo" in r:
                    nm = clasificar(r["caso"], r["variante"], r["respuesta_modelo"], t)[0]
            c = conteos.setdefault((cfg, *k), collections.Counter())
            c["n"] += 1
            c[nivel] += 1
            c["revisar"] += r.get("revisar") == "True"
            if nm is not None:
                c["tiene_modelo"] += 1
                c["modelo_exito"] += nm == "exito"
                c["modelo_falla"] += nm == "control_falla"
                c["filtro"] += r.get("filtro_activado") == "True"

    cfgs = [c for c in ORDEN_CONFIGS if c in prompts] + [c for c in prompts if c not in ORDEN_CONFIGS]
    claves = sorted(set(orden_var), key=lambda x: (x[0], orden_var.index(x)))
    claves_ataque = [k for k in claves if k[0] != "C"]
    claves_ctrl = [k for k in claves if k[0] == "C"]
    faltan = {c: sorted(f"{a}/{b}" for a, b in claves if (c, a, b) not in conteos) for c in cfgs}
    faltan = {c: v for c, v in faltan.items() if v}

    filas_var = []
    for caso, var in claves_ataque:
        for cfg in cfgs:
            c = conteos.get((cfg, caso, var))
            if c:
                lo, hi = wilson(c["exito"], c["n"])
                filas_var.append([caso, var, cfg, c["n"], c["exito"], round(100 * c["exito"] / c["n"], 1),
                                  round(lo, 1), round(hi, 1), c["parcial"], c["fallo"], c["revisar"]])
    if prompts:
        escribir_csv(f"{OUT}/variantes.csv", ["caso", "variante", "config", "n", "exito", "pct", "wilson_lo", "wilson_hi",
                                              "parcial", "fallo", "filas_revisar"], filas_var)
    if faltan:
        md += ["## ATENCION: variantes sin datos", "",
               "Estas configs no tienen todas las variantes; esas comparaciones no se pueden hacer hasta volver a correrlas:", ""]
        md += [f"- {c}: {', '.join(v)}" for c, v in faltan.items()] + [""]

    if cfgs:
        md += ["## Exito del atacante por variante (prompts)", "", "Celda: exitos/n (porcentaje) [Wilson 95 %]", "",
               "| caso | variante | " + " | ".join(cfgs) + " |", "|---|---|" + "---|" * len(cfgs)]
        for caso, var in claves_ataque:
            md.append(f"| {caso} | {var} | " + " | ".join(
                celda(conteos[(c, caso, var)]["exito"], conteos[(c, caso, var)]["n"]) if (c, caso, var) in conteos else "-" for c in cfgs) + " |")
        md.append("")

        md += ["## Exito por caso (variantes agrupadas)", "",
               "Agrupa variantes distintas: sirve como panorama, no como tasa de un ataque unico.", "",
               "| caso | " + " | ".join(cfgs) + " |", "|---|" + "---|" * len(cfgs)]
        for caso in sorted({k[0] for k in claves_ataque}):
            fila = []
            for c in cfgs:
                ks = [v for k, v in conteos.items() if k[0] == c and k[1] == caso]
                fila.append(celda(sum(v["exito"] for v in ks), sum(v["n"] for v in ks)) if ks else "-")
            md.append(f"| {caso} | " + " | ".join(fila) + " |")
        md.append("")

    if claves_ctrl:
        filas_ctrl = []
        for caso, var in claves_ctrl:
            for cfg in cfgs:
                c = conteos.get((cfg, caso, var))
                if c:
                    lo, hi = wilson(c["control_falla"], c["n"])
                    filas_ctrl.append([var, cfg, c["n"], c["control_ok"], c["control_falla"], c["parcial"],
                                       round(100 * c["control_falla"] / c["n"], 1), round(lo, 1), round(hi, 1),
                                       c["filtro"], c["modelo_falla"] if c["tiene_modelo"] else "", c["revisar"]])
        escribir_csv(f"{OUT}/control.csv", ["variante", "config", "n", "control_ok", "control_falla", "parcial", "pct_falla",
                                            "wilson_lo", "wilson_hi", "filtro_activado", "falla_modelo_sin_filtro", "filas_revisar"], filas_ctrl)
        md += ["## Control C: falsos positivos (consultas legitimas)", "",
               "control_falla = rechazo o bloqueo de una consulta legitima (o filtracion de un secreto). "
               "Cuanto mas bajo, mejor utilidad. Celda: fallas/n (porcentaje) [Wilson 95 %]", "",
               "| variante | " + " | ".join(cfgs) + " |", "|---|" + "---|" * len(cfgs)]
        for caso, var in claves_ctrl:
            md.append(f"| {var} | " + " | ".join(
                celda(conteos[(c, caso, var)]["control_falla"], conteos[(c, caso, var)]["n"]) if (c, caso, var) in conteos else "-" for c in cfgs) + " |")
        md += ["", "Resumen por config (todas las variantes de C): lo que ve el usuario vs lo que dijo el modelo sin filtro.", "",
               "| config | n | control_ok | falla (visible) | parcial | falla del modelo (sin filtro) | filtro activado |",
               "|---|---|---|---|---|---|---|"]
        for c in cfgs:
            ks = [v for k, v in conteos.items() if k[0] == c and k[1] == "C"]
            if ks:
                n_ = sum(v["n"] for v in ks)
                tm = sum(v["tiene_modelo"] for v in ks)
                md.append(f"| {c} | {n_} | {sum(v['control_ok'] for v in ks)} | {celda(sum(v['control_falla'] for v in ks), n_)} | "
                          f"{sum(v['parcial'] for v in ks)} | {sum(v['modelo_falla'] for v in ks) if tm else '-'} | "
                          f"{sum(v['filtro'] for v in ks) if tm else '-'} |")
        md.append("")
    elif prompts:
        md += ["## Control C", "", "Ninguna config usada tiene el caso C (corridas anteriores a pruebas.py v3). "
               "Los falsos positivos no se pueden medir con prompts hasta volver a correr.", ""]

    # ---- comparaciones entre configs (Fisher + Holm) ----
    comp_rows, md_comp = [], []
    for metrica, cl, titulo_m in (("exito", claves_ataque, "exito del atacante"),
                                  ("control_falla", claves_ctrl, "falsos positivos (control C)")):
        for a, b, porque in PARES:
            if a not in prompts or b not in prompts:
                continue
            items = [(f"{caso}/{var}", conteos[(a, caso, var)][metrica], conteos[(a, caso, var)]["n"],
                      conteos[(b, caso, var)][metrica], conteos[(b, caso, var)]["n"])
                     for caso, var in cl if (a, caso, var) in conteos and (b, caso, var) in conteos]
            f_, m_ = tabla_fisher(f"{a} vs {b} [{titulo_m}]: {porque}", items, a, b, mostrar_ceros=False)
            comp_rows += f_
            md_comp += m_
    if comp_rows:
        escribir_csv(f"{OUT}/comparaciones.csv", ["grupo", "caso_variante", "k_a", "n_a", "k_b", "n_b", "p_fisher", "p_holm"], comp_rows)
    md += ["## Comparaciones entre configuraciones (solo filas con algun evento; ** = p Holm < 0.05)", ""] + md_comp

    # ---- filtro de salida: modelo vs usuario (solo ataques; el control esta arriba) ----
    con_filtro = [c for c in cfgs if any(v["filtro"] for k, v in conteos.items() if k[0] == c)]
    if con_filtro:
        md += ["## Filtro de salida: lo que dijo el modelo vs lo que vio el usuario", "",
               "| config | caso | exito del modelo | exito visible | filtro activado | filas |", "|---|---|---|---|---|---|"]
        for c in con_filtro:
            for caso in sorted({k[1] for k in conteos if k[0] == c and k[1] != "C"}):
                ks = [v for k, v in conteos.items() if k[0] == c and k[1] == caso]
                md.append(f"| {c} | {caso} | {sum(v['modelo_exito'] for v in ks)} | {sum(v['exito'] for v in ks)} | "
                          f"{sum(v['filtro'] for v in ks)} | {sum(v['n'] for v in ks)} |")
        md += ["", "Nota: el filtro solo detecta secretos. No tapa exitos de P1/P2 que no filtran datos.", ""]

    # ---------------- herramientas ----------------
    if tools:
        tc = {}
        for cfg, filas in tools.items():
            for r in filas:
                c = tc.setdefault((cfg, r["caso"], r["variante"]), collections.Counter())
                c["n"] += 1
                c[r["nivel"]] += 1
                c["agotado"] += r.get("iter_agotado") == "True"
                if r.get("nota_leida") not in (None, ""):
                    c["tiene_nota"] += 1
                    leida = r["nota_leida"] == "True"
                    c["leida"] += leida
                    if leida:
                        c["exito_leida"] += r["nivel"] == "exito"
                        c["intento_leida"] += r["nivel"] in ("exito", "contenido")
        tcfgs = [c for c in ("debil", "endurecida") if c in tools]
        tclaves = sorted({(k[1], k[2]) for k in tc}, key=lambda x: (x[0], x[1]))
        filas_t = []
        for caso, var in tclaves:
            for c in tcfgs:
                v = tc.get((c, caso, var))
                if v:
                    filas_t.append([caso, var, c, v["n"], v["exito"], v["contenido"], v["fallo"], v["control_ok"],
                                    v["control_parcial"], v["control_falla"], v["error"],
                                    v["leida"] if v["tiene_nota"] else "", v["agotado"]])
        escribir_csv(f"{OUT}/herramientas.csv", ["caso", "variante", "config", "n", "exito", "contenido", "fallo", "control_ok",
                                                 "control_parcial", "control_falla", "error", "nota_leida", "iter_agotado"], filas_t)
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

        # T6 condicionado a que el modelo haya leido la nota
        t6 = [(var, c) for caso, var in tclaves if caso == "T6" for c in tcfgs if (c, caso, var) in tc]
        if t6:
            md += ["### T6: efecto de la nota condicionado a que el modelo la leyo", "",
                   "La nota solo llega al modelo si este llama a consultar_pedido(1001). Si no la lee, el ataque no tuvo oportunidad: "
                   "contarlo como 'fallo' diluye la tasa. 'nota leida' y las columnas '| leida' requieren CSV v3 (columna nota_leida).", "",
                   "| variante | config | nota leida | exito real | exito real \\| leida | intento | intento \\| leida |", "|---|---|---|---|---|---|---|"]
            for var, c in t6:
                v = tc[(c, "T6", var)]
                n_ = v["n"]
                if v["tiene_nota"]:
                    md.append(f"| {var} | {c} | {celda(v['leida'], n_)} | {celda(v['exito'], n_)} | {celda(v['exito_leida'], v['leida'])} | "
                              f"{celda(v['exito'] + v['contenido'], n_)} | {celda(v['intento_leida'], v['leida'])} |")
                else:
                    md.append(f"| {var} | {c} | n/d | {celda(v['exito'], n_)} | n/d | {celda(v['exito'] + v['contenido'], n_)} | n/d |")
            md.append("")

        comp_t = []
        if len(tcfgs) == 2:
            a, b = "debil", "endurecida"
            items = [(f"{caso}/{var}", tc[(a, caso, var)]["exito"], tc[(a, caso, var)]["n"],
                      tc[(b, caso, var)]["exito"], tc[(b, caso, var)]["n"])
                     for caso, var in tclaves if caso in ATAQUE_TOOLS and (a, caso, var) in tc and (b, caso, var) in tc]
            f_, m_ = tabla_fisher("debil vs endurecida: exito real", items, a, b)
            comp_t += f_
            md += m_

        # directo (ticket) vs indirecto (nota en el resultado de la herramienta): mismo texto, distinto canal
        for c in tcfgs:
            pares = [(x, y) for x, y in PARES_CANAL if (c, *x) in tc and (c, *y) in tc]
            if not pares:
                continue
            for metrica, titulo_m in (("exito", "exito real"), ("intento", "intento no autorizado")):
                def k_(v):
                    return v["exito"] if metrica == "exito" else v["exito"] + v["contenido"]
                items = [(f"{x[1]} vs {y[1]}", k_(tc[(c, *x)]), tc[(c, *x)]["n"], k_(tc[(c, *y)]), tc[(c, *y)]["n"]) for x, y in pares]
                f_, m_ = tabla_fisher(f"[{c}] ticket (T3/T4) vs nota en resultado de herramienta (T6): {titulo_m}", items,
                                      "ticket", "nota (todas las corridas)")
                comp_t += f_
                md += m_
            # solo con la nota efectivamente leida (CSV v3)
            items = []
            for x, y in pares:
                vy = tc[(c, *y)]
                if vy["tiene_nota"] and vy["leida"]:
                    vx = tc[(c, *x)]
                    items.append((f"{x[1]} vs {y[1]}", vx["exito"] + vx["contenido"], vx["n"], vy["intento_leida"], vy["leida"]))
            f_, m_ = tabla_fisher(f"[{c}] ticket vs nota, solo corridas donde la nota se leyo: intento no autorizado", items,
                                  "ticket", "nota (leida)")
            comp_t += f_
            md += m_
        if comp_t:
            escribir_csv(f"{OUT}/herramientas_comparaciones.csv",
                         ["grupo", "caso_variante", "k_a", "n_a", "k_b", "n_b", "p_fisher", "p_holm"], comp_t)

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
        ag = sum(v["agotado"] for v in tc.values())
        if ag:
            md += [f"Aviso: en {ag} ejecuciones el modelo agoto MAX_ITER pidiendo herramientas (columna iter_agotado).", ""]

    with open(f"{OUT}/resumen.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"Config(s) de prompts usadas: {', '.join(cfgs) or '-'} | herramientas: {', '.join(tools) or '-'}")
    print(f"Detector: {'reclasificado' if reclasificar else 'guardado en los CSV'}")
    for c, v in faltan.items():
        print(f"AVISO: a '{c}' le faltan variantes: {', '.join(v)}")
    print(f"\nListo. Mirá {OUT}/resumen.md (tablas) y los CSV de {OUT}/.")


if __name__ == "__main__":
    main()
