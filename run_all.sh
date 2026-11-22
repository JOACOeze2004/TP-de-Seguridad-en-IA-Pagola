#!/usr/bin/env bash
# Corre TODAS las configuraciones y deja cada CSV en su carpeta de evidencia/.
#
# Uso:   ./run_all.sh [reps_prompts] [reps_tools]        (por defecto 30 y 20)
#   SOLO=prompts ./run_all.sh     solo pruebas.py (LLM01)
#   SOLO=tools   ./run_all.sh     solo pruebas_tools.py (LLM03)
#   ANALIZAR=1   ./run_all.sh     al final corre analisis.py --reclasificar
#
# Hay que correrlo con el venv activado, Ollama andando y los scripts congelados
# (detectores.py final). En Windows: Git Bash o WSL.
set -euo pipefail
cd "$(dirname "$0")"

REPS_P=${1:-30}
REPS_T=${2:-20}
PY=${PYTHON:-python}
SOLO=${SOLO:-todo}
EV=evidencia
CONFIGS_P="laxa debil estricta filtro estricta_filtro sin_secretos segmentada"
CONFIGS_T="debil endurecida"
nuevos=()

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
  nuevos+=("$f")
  echo "-> $2/$f"
}

echo "Modelo: ${MODELO:-(el de .env, o llama3.2)} | reps prompts: $REPS_P | reps tools: $REPS_T | SOLO=$SOLO"

if [ "$SOLO" != "tools" ]; then
  for c in $CONFIGS_P; do
    echo; echo "=== prompts: $c ($REPS_P reps) ==="
    $PY pruebas.py "$c" "$REPS_P"
    mover "resultados_${c}_[0-9]*.csv" "$EV/llm01_prompts/$c"
  done
fi

if [ "$SOLO" != "prompts" ]; then
  for c in $CONFIGS_T; do
    echo; echo "=== tools: $c ($REPS_T reps) ==="
    $PY pruebas_tools.py "$c" "$REPS_T"
    mover "resultados_tools_${c}_[0-9]*.csv" "$EV/llm03_tools/$c"
  done
fi

# líneas listas para pegar en el MANIFIESTO de analisis.py
{
  echo "# Pegar en MANIFIESTO (analisis.py) y pasar los CSV viejos de las mismas configs a DESCARTAR:"
  for f in "${nuevos[@]}"; do echo "    \"$f\": (USAR, \"tanda final\"),"; done
} | tee manifiesto_sugerido.txt

if [ "${ANALIZAR:-0}" = "1" ]; then
  echo; echo "=== análisis ==="
  $PY analisis.py "$EV" --reclasificar
else
  echo; echo "Siguiente paso: actualizar MANIFIESTO y correr:  python analisis.py $EV --reclasificar"
fi
