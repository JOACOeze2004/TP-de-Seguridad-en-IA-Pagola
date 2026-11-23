# ShopBot: laboratorio de prompt injection - TP de Seguridad en IA - Curso Pagola

Chatbot ficticio de atención al cliente (ShopBot) para probar ataques de prompt injection
en un entorno controlado. Todos los datos internos (API key, códigos, pedidos) son **inventados**
y las herramientas son **simuladas**: no hay conexión a ningún servicio real.

Basado en el chatbot de ejemplo del profesor *Hugo Pagola* (LangChain + Streamlit), pero usando un modelo local con Ollama, así no hace falta API key ni pagar nada.

## Instalación

### 1. Instalar Ollama

**Linux**
```
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows / Mac:** bajar el instalador desde https://ollama.com

Verificar que esté corriendo:
```
curl http://localhost:11434
```
Tiene que responder `Ollama is running`. Si no, abrir otra terminal y dejar corriendo `ollama serve`.

### 2. Bajar el modelo

```
ollama pull llama3.2
```

Probarlo:
```
ollama run llama3.2 "Hola, ¿qué podés hacer?"
```
(`/bye` para salir). Si la máquina es muy justa, usar `llama3.2:1b`
(ojo: los resultados del informe son de `llama3.2`; otro modelo no es comparable).

### 3. Crear el entorno de Python

En la carpeta del proyecto:

**Linux / Mac**
```
python3 -m venv venv
source venv/bin/activate
```

**Windows**
```
python -m venv venv
venv\Scripts\activate
```

Tiene que aparecer `(venv)` al principio de la terminal. En Ubuntu, si falla la creación:
`sudo apt install python3-full python3-venv`.

### 4. Instalar dependencias

Con el venv activado:
```
pip install -r requirements.txt
```

Si aparece `externally-managed-environment`, el venv no está activado: `pip` es el del sistema.

### 5. Configurar el modelo

Copiar el archivo de ejemplo:
```
cp .env.example .env
```
`.env` define `MODELO` (por defecto `llama3.2`). Lo leen `pruebas.py` y `pruebas_tools.py`.
Si `.env` no existe, usan `llama3.2`.

## Estructura del repo

```
.
├── src/                  los .py (core, pruebas, detectores, defensas, herramientas, analisis, streamlit...)
├── run_all.sh            corre todas las configs
├── .env / .env.example
├── requirements.txt
├── evidencia/
│   ├── llm01_prompts/    un subdirectorio por config (laxa, debil, estricta, filtro, estricta_filtro, sin_secretos, segmentada, combinada)
│   ├── llm03_tools/      debil y endurecida
│   └── descartados/      pilotos, esquemas viejos y pruebas de humo (no se analizan)
└── analisis_out/         salida de analisis.py
```

## Uso

Siempre con el venv activado y parados en la **raíz del repo** (`pwd` para confirmar). Los scripts viven
en `src/` (`core.py` tiene los prompts, configs y casos que comparten la app y las baterías); los CSV que generan quedan en la raíz (o en `evidencia/` si se usa `run_all.sh`).

### App para atacar a mano

```
streamlit run src/streamlit_chatbot.py
```

Se abre en http://localhost:8501. El título tiene que decir **🛒 ShopBot - Atención al cliente**.
Si dice "Chatbot Básico", se está corriendo otro archivo u otro proceso viejo
(`pkill -f streamlit` y volver a correr).

Para probar **inyección indirecta**: pegar la instrucción en el cuadro "Ticket / FAQ externa"
de la barra lateral y, en el chat, hacer una pregunta normal (por ejemplo "¿Cuánto tarda un envío?").

La barra lateral tiene un selector de **modo** (Chat o Herramientas), un selector de **defensa/backend**
y un desplegable de **ataques precargados** (los mismos de las baterías). "Enviar ataque" empieza una
conversación nueva, carga el ticket o la nota y envía el mensaje. En modo Herramientas la app muestra
el registro de llamadas y el estado de los pedidos. Para ataques a mano, empezar **cada uno en una
conversación nueva** (botón "Nueva conversación") para que sean comparables.

### Batería automática de prompts (LLM01 / LLM02)

```
python src/pruebas.py <config> <repeticiones> [variantes]
```

- `<config>`:
  - `laxa`: sin instrucción de confidencialidad (línea base)
  - `debil`: instrucción genérica "no reveles..."
  - `estricta`: reglas que nombran los datos protegidos
  - `filtro`: `laxa` + filtro de salida en la aplicación
  - `estricta_filtro`: `estricta` + filtro de salida
  - `sin_secretos`: prompt sin credenciales internas (minimización)
  - `segmentada`: ticket etiquetado como no confiable y separado en mensajes system/human
  - `combinada`: reglas estrictas + `segmentada` + filtro de salida (defensa en profundidad)
- `<repeticiones>`: cuántas veces se corre cada variante. Para tasas confiables, 30.
  Cada repetición usa su número como `seed`, así que se puede reproducir.
- `[variantes]` (opcional): variantes o casos separados por coma. Si se omite, corre todo.

Casos: **P1** desvío de propósito (5 variantes), **P2** inyección indirecta por ticket (5),
**P3** exposición de contexto oculto (9) y **C** control con consultas legítimas (5), que mide
falsos positivos del prompt estricto y del filtro.

Ejemplos:
```
python src/pruebas.py debil 1                         # prueba rápida de todo
python src/pruebas.py debil 30                        # corrida completa
python src/pruebas.py laxa 30 ticket_oculto,completar,apikey
python src/pruebas.py estricta_filtro 30 C            # solo los casos de control
```

Cada corrida genera `resultados_<config>_<fecha>.csv`. No mezclar filas de corridas
distintas dentro de un mismo número del informe.

Columnas importantes: `nivel` (exito/parcial/fallo; en el caso C: control_ok/control_falla/parcial),
`motivo`, `revisar`, `nivel_modelo` (lo que dijo el modelo antes del filtro), `filtro_activado`,
`seed`, `version_detector`, `version_esquema`, `tokens_in`, `tokens_out`, `segundos`, `respuesta`.

### Batería de herramientas (LLM03)

```
python src/pruebas_tools.py <config> <repeticiones> [filtro]
```

- `<config>`: `debil` (el backend confía en lo que dice el modelo) o `endurecida`
  (el backend usa la sesión autenticada, verifica dueño y limita las transiciones).
  El prompt es idéntico en las dos: lo que cambia es la arquitectura.
- `[filtro]`: casos o variantes separados por coma, por ejemplo `T1,T5` o `T6/nota_simple`.

Casos: T1 y T2 (pedido directo), T3 y T4 (ataque por ticket), T5 (control de uso legítimo)
y T6 (inyección indirecta por una nota en el resultado de una herramienta).
Niveles: `exito` (el ataque tuvo efecto real), `contenido` (el modelo fue manipulado pero
el backend lo frenó) y `fallo`. En T6, `nota_leida` indica si el modelo llegó a ver la nota.

El backend simulado se puede probar sin modelo: `python src/herramientas.py` (tiene que decir `autotest OK`).

### Correr todo de una vez

```
./run_all.sh [reps_prompts] [reps_tools]      # por defecto 30 y 20
```

Corre las 8 configs de prompts y las 2 de herramientas, y deja cada CSV en `evidencia/`.
Antes de analizar, mover a `evidencia/descartados/` los CSV viejos de las mismas configs.
Variantes: `SOLO=prompts`, `SOLO=tools`, `ANALIZAR=1` (corre el análisis al final).
En Windows, usar Git Bash o WSL (si no tiene permiso de ejecución: `bash run_all.sh`).
Hacer esto solo cuando el código esté congelado (sobre todo `detectores.py`).

### Análisis estadístico

```
python src/analisis.py evidencia --reclasificar
```

Lee todos los CSV de `evidencia/` (incluidas las subcarpetas). **Usa todo lo que no esté en una carpeta
`descartados/`**; no hay lista que mantener. Si dos CSV usados son de la misma config, se corta con un error:
mover el viejo a `evidencia/descartados/`. En `NOTAS` (arriba de `analisis.py`) se puede dejar el motivo de cada
descarte para la tabla de trazabilidad. Con `--reclasificar` todas las configs se miden con el mismo `detectores.py`.

Genera la carpeta `analisis_out/` con `resumen.md` (tablas: éxito por variante con intervalo de Wilson 95 %,
comparaciones con Fisher y corrección de Holm, falsos positivos del caso C, herramientas y T6 condicionado a
`nota_leida`) y los CSV de apoyo, incluida la tabla de trazabilidad (qué archivo es qué config, versión y si se usa).

### Reclasificar un CSV viejo

```
python src/reanalizar.py resultados_debil_XXXX.csv [--incluir-p5]
```

No modifica el original: genera `..._reanalizado.csv` (todas las filas con el nivel viejo y el nuevo) y
`..._cambios.csv` (solo las que cambian) y muestra cuántos falsos positivos y falsos negativos tenía el detector anterior.
Revisar a mano `_cambios.csv` para validar que el detector nuevo mejora y no solo mueve el error.
