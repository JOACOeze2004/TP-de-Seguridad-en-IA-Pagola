"""Reclasifica un CSV viejo con los detectores v2 y compara con el detector original.
Uso: python reanalizar.py resultados_debil_XXXX.csv"""
import csv, sys, collections
from detectores import clasificar

fn = sys.argv[1]
rows = list(csv.DictReader(open(fn, encoding="utf-8")))
out = fn.replace(".csv", "_v2.csv")

stats = collections.defaultdict(lambda: collections.Counter())
conf = collections.Counter()
for r in rows:
    tout = int(r["tokens_out"]) if r.get("tokens_out") not in (None, "", "None") else None
    nivel, motivo, rev = clasificar(r["caso"], r["variante"], r["respuesta"], tout)
    r.update(nivel=nivel, motivo=motivo, revisar=rev)
    stats[(r["caso"], r["variante"])][nivel] += 1
    viejo = r["exito"] == "True"
    nuevo = nivel == "exito"
    conf[(viejo, nuevo)] += 1

campos = list(rows[0].keys())
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=campos); w.writeheader(); w.writerows(rows)

print(f"{'caso':4} {'variante':18} exito parcial fallo")
for (c, v), cnt in stats.items():
    n = sum(cnt.values())
    print(f"{c:4} {v:18} {cnt['exito']}/{n}    {cnt['parcial']}/{n}     {cnt['fallo']}/{n}")

print("\nDetector viejo vs nuevo (nuevo 'exito' = verdad de referencia)")
print(f"  coinciden éxito:         {conf[(True, True)]}")
print(f"  falsos positivos viejos: {conf[(True, False)]}")
print(f"  falsos negativos viejos: {conf[(False, True)]}")
print(f"  coinciden fallo:         {conf[(False, False)]}")
print(f"\nGuardado en {out}. Revisá a mano las filas con revisar=True.")
