#!/usr/bin/env bash
# Arranca ShopBot con un comando: ./iniciar.sh
# Crea el venv si falta, instala dependencias, verifica Ollama y el modelo, y abre la app.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "Falta Python 3. En Ubuntu: sudo apt install python3-full python3-venv"; exit 1; }

# 1) entorno virtual y dependencias
if [ ! -x venv/bin/python ]; then
  echo ">> Creando entorno virtual..."
  python3 -m venv venv || { echo "Falló venv. En Ubuntu: sudo apt install python3-full python3-venv"; exit 1; }
fi
# shellcheck disable=SC1091
source venv/bin/activate
if [ ! -f venv/.deps_ok ] || [ requirements.txt -nt venv/.deps_ok ]; then
  echo ">> Instalando dependencias (solo la primera vez)..."
  pip install -q -r requirements.txt
  touch venv/.deps_ok
fi

# 2) .env con el modelo
if [ ! -f .env ]; then
  if [ -f .env.example ]; then cp .env.example .env; else echo "MODELO=llama3.2" > .env; fi
fi
MODELO=$(grep -E '^MODELO=' .env | head -1 | cut -d= -f2- | tr -d '"\r' || true)
MODELO=${MODELO:-llama3.2}

# 3) Ollama instalado y andando
command -v ollama >/dev/null || {
  echo "Falta Ollama. Instalalo con:  curl -fsSL https://ollama.com/install.sh | sh"
  echo "(Mac/Windows: https://ollama.com) y volvé a correr ./iniciar.sh"
  exit 1
}
if ! curl -sf http://localhost:11434 >/dev/null; then
  echo ">> Iniciando Ollama..."
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  for _ in $(seq 1 20); do curl -sf http://localhost:11434 >/dev/null && break; sleep 1; done
  curl -sf http://localhost:11434 >/dev/null || { echo "Ollama no arrancó. Mirá /tmp/ollama.log"; exit 1; }
fi

# 4) modelo descargado
if ! ollama list | awk 'NR>1{print $1}' | grep -qE "^${MODELO}(:latest)?$|^${MODELO}$"; then
  echo ">> Bajando el modelo $MODELO (puede tardar unos minutos)..."
  ollama pull "$MODELO"
fi

# 5) evita la pregunta del email la primera vez que corre Streamlit
mkdir -p "$HOME/.streamlit"
[ -f "$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"

echo ">> Listo. Abriendo ShopBot en http://localhost:8501  (Ctrl+C para cerrar)"
exec python -m streamlit run src/streamlit_chatbot.py
