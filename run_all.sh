#!/usr/bin/env bash
# Corre TODAS las configuraciones y deja cada CSV en su carpeta de evidencia/.
#
# Uso:   ./run_all.sh [reps_prompts] [reps_tools]        (por defecto 30 y 20)
#        ./run_all.sh 2>&1 | tee run_all.log               (recomendado: deja el log)
#   Si se corta, volver a correr: saltea las configs que ya tienen CSV en evidencia/.
#   Para rehacer una config, borrar (o mover a descartados/) su CSV.
#   SOLO=prompts ./run_all.sh     solo pruebas.py (LLM01)
#   SOLO=tools   ./run_all.sh     solo pruebas_tools.py (LLM03)
#   ANALIZAR=1   ./run_all.sh     al final corre analisis.py --reclasificar
#
# analisis.py usa todo CSV de evidencia/ salvo los que estén en evidencia/descartados/.
#
# Los .py viven en src/ (se puede cambiar con SRC=otra_carpeta). El script se queda parado
# en la raiz del repo: asi evidencia/, los CSV y analisis_out/ quedan en la raiz.
#
# Hay que correrlo con el venv activado, Ollama andando y los scripts congelados
# (detectores.py final). En Windows: Git Bash o WSL.
set -euo pipefail
cd "$(dirname "$0")"

REPS_P=${1:-30}
REPS_T=${2:-20}
PY=${PYTHON:-python}
SRC=${SRC:-src}
SOLO=${SOLO:-todo}
EV=evidencia
CONFIGS_P="laxa debil estricta filtro estricta_filtro sin_secretos segmentada combinada"
CONFIGS_T="debil endurecida"

[ -d "$SRC" ] || { echo "No encuentro la carpeta '$SRC/' (corré el script desde la raiz del repo, o usá SRC=ruta)"; exit 1; }
for f in pruebas.py pruebas_tools.py core.py analisis.py detectores.py defensas.py herramientas.py; do
  [ -f "$SRC/$f" ] || { echo "Falta $SRC/$f"; exit 1; }
done

if [ -z "${SKIP_CHECK:-}" ]; then
  curl -sf http://localhost:11434 >/dev/null || { echo "Ollama no responde en localhost:11434 (probá: ollama serve)"; exit 1; }
  $PY -c "import langchain_ollama, dotenv" 2>/dev/null || { echo "Faltan dependencias: activá el venv y corré: pip install -r requirements.txt"; exit 1; }
fi

# mover <patron> <carpeta destino>: mueve el CSV más reciente que coincida con el patron
mover() {
  local f
  f=$(ls -t $1 2>/dev/null | head -1 || true)
  [ -n "$f" ] || { echo "No encontré el CSV generado ($1)"; exit 1; }
  mkdir -p "$2"
  mv "$f" "$2/"
  echo "-> $2/$f"
}

echo "Modelo: ${MODELO:-(el de .env, o llama3.2)} | reps prompts: $REPS_P | reps tools: $REPS_T | SOLO=$SOLO"

# Registro del entorno (modelo con su digest, versiones de paquetes) para la trazabilidad
M=${MODELO:-$(grep -E '^MODELO=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"\r' || true)}
M=${M:-llama3.2}
mkdir -p "$EV"
{ date; echo "--- ollama list"; ollama list; echo "--- ollama show $M"; ollama show "$M"; echo "--- pip freeze"; $PY -m pip freeze; } > "$EV/entorno.txt" 2>&1 || true
echo "-> $EV/entorno.txt"

if [ "$SOLO" != "tools" ]; then
  for c in $CONFIGS_P; do
    # si se cayó a mitad, al volver a correr se saltea lo que ya terminó (CSV en su carpeta)
    compgen -G "$EV/llm01_prompts/$c/*.csv" >/dev/null && { echo "salteo prompts/$c (ya tiene CSV)"; continue; }
    echo; echo "=== prompts: $c ($REPS_P reps) ==="
    $PY "$SRC/pruebas.py" "$c" "$REPS_P"
    mover "resultados_${c}_[0-9]*.csv" "$EV/llm01_prompts/$c"
  done
fi

if [ "$SOLO" != "prompts" ]; then
  for c in $CONFIGS_T; do
    compgen -G "$EV/llm03_tools/$c/*.csv" >/dev/null && { echo "salteo tools/$c (ya tiene CSV)"; continue; }
    echo; echo "=== tools: $c ($REPS_T reps) ==="
    $PY "$SRC/pruebas_tools.py" "$c" "$REPS_T"
    mover "resultados_tools_${c}_[0-9]*.csv" "$EV/llm03_tools/$c"
  done
fi

echo
echo "Aviso: antes de analizar, mové a $EV/descartados/ los CSV viejos de las mismas configs (analisis.py usa todo lo que no esté ahí)."

if [ "${ANALIZAR:-0}" = "1" ]; then
  echo; echo "=== análisis ==="
  $PY "$SRC/analisis.py" "$EV" --reclasificar
else
  echo; echo "Siguiente paso:  python $SRC/analisis.py $EV --reclasificar"
fi
