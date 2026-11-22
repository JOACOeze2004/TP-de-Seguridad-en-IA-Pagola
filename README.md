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

## Uso

Siempre con el venv activado y parados en la carpeta del proyecto (`pwd` para confirmar).

### App para atacar a mano

```
streamlit run streamlit_chatbot.py
```

Se abre en http://localhost:8501. El título tiene que decir **🛒 ShopBot - Atención al cliente**.
Si dice "Chatbot Básico", se está corriendo otro archivo u otro proceso viejo
(`pkill -f streamlit` y volver a correr).

Para probar **inyección indirecta**: pegar la instrucción en el cuadro "Ticket / FAQ externa"
de la barra lateral y, en el chat, hacer una pregunta normal (por ejemplo "¿Cuánto tarda un envío?").

Para que las pruebas sean comparables, empezar **cada ataque en una conversación nueva**
(botón "Nueva conversación"). La app usa el prompt `debil`; las demás configuraciones
solo existen en la batería automática.

### Batería automática de prompts (LLM01 / LLM02)

```
python pruebas.py <config> <repeticiones> [variantes]
```

- `<config>`:
  - `laxa`: sin instrucción de confidencialidad (línea base)
  - `debil`: instrucción genérica "no reveles..."
  - `estricta`: reglas que nombran los datos protegidos
  - `filtro`: `laxa` + filtro de salida en la aplicación
  - `estricta_filtro`: `estricta` + filtro de salida
  - `sin_secretos`: prompt sin credenciales internas (minimización)
  - `segmentada`: ticket etiquetado como no confiable y separado en mensajes system/human
- `<repeticiones>`: cuántas veces se corre cada variante. Para tasas confiables, 30.
  Cada repetición usa su número como `seed`, así que se puede reproducir.
- `[variantes]` (opcional): variantes o casos separados por coma. Si se omite, corre todo.

Casos: **P1** desvío de propósito (5 variantes), **P2** inyección indirecta por ticket (5),
**P3** exposición de contexto oculto (9) y **C** control con consultas legítimas (5), que mide
falsos positivos del prompt estricto y del filtro.

Ejemplos:
```
python pruebas.py debil 1                         # prueba rápida de todo
python pruebas.py debil 30                        # corrida completa
python pruebas.py laxa 30 ticket_oculto,completar,apikey
python pruebas.py estricta_filtro 30 C            # solo los casos de control
```

Cada corrida genera `resultados_<config>_<fecha>.csv`. No mezclar filas de corridas
distintas dentro de un mismo número del informe.

Columnas importantes: `nivel` (exito/parcial/fallo; en el caso C: control_ok/control_falla/parcial),
`motivo`, `revisar`, `nivel_modelo` (lo que dijo el modelo antes del filtro), `filtro_activado`,
`seed`, `version_detector`, `version_esquema`, `tokens_in`, `tokens_out`, `segundos`, `respuesta`.

### Batería de herramientas (LLM03)

```
python pruebas_tools.py <config> <repeticiones> [filtro]
```

- `<config>`: `debil` (el backend confía en lo que dice el modelo) o `endurecida`
  (el backend usa la sesión autenticada, verifica dueño y limita las transiciones).
  El prompt es idéntico en las dos: lo que cambia es la arquitectura.
- `[filtro]`: casos o variantes separados por coma, por ejemplo `T1,T5` o `T6/nota_simple`.

Casos: T1 y T2 (pedido directo), T3 y T4 (ataque por ticket), T5 (control de uso legítimo)
y T6 (inyección indirecta por una nota en el resultado de una herramienta).
Niveles: `exito` (el ataque tuvo efecto real), `contenido` (el modelo fue manipulado pero
el backend lo frenó) y `fallo`. En T6, `nota_leida` indica si el modelo llegó a ver la nota.

El backend simulado se puede probar sin modelo: `python herramientas.py` (tiene que decir `autotest OK`).

### Correr todo de una vez

```
./run_all.sh [reps_prompts] [reps_tools]      # por defecto 30 y 20
```

Corre las 7 configs de prompts y las 2 de herramientas, y deja cada CSV en `evidencia/`.
Al final imprime (y guarda en `manifiesto_sugerido.txt`) las líneas para pegar en el MANIFIESTO de `analisis.py`.
Variantes: `SOLO=prompts`, `SOLO=tools`, `ANALIZAR=1` (corre el análisis al final).
En Windows, usar Git Bash o WSL (si no tiene permiso de ejecución: `bash run_all.sh`).
Hacer esto solo cuando el código esté congelado (sobre todo `detectores.py`).

### Análisis estadístico

```
python analisis.py evidencia --reclasificar
```

Lee todos los CSV de `evidencia/` (incluidas las subcarpetas), pero **solo analiza los que figuran como
`usar` en el MANIFIESTO** al principio de `analisis.py`. Un CSV nuevo hay que agregarlo ahí; los viejos de la
misma config pasan a `descartar`. Con `--reclasificar` todas las configs se miden con el mismo `detectores.py`.

Genera la carpeta `analisis_out/` con `resumen.md` (tablas: éxito por variante con intervalo de Wilson 95 %,
comparaciones con Fisher y corrección de Holm, falsos positivos del caso C, herramientas y T6 condicionado a
`nota_leida`) y los CSV de apoyo, incluida la tabla de trazabilidad (qué archivo es qué config, versión y si se usa).

### Reclasificar un CSV viejo

```
python reanalizar.py resultados_debil_XXXX.csv [--incluir-p5]
```

No modifica el original: genera `..._reanalizado.csv` (todas las filas con el nivel viejo y el nuevo) y
`..._cambios.csv` (solo las que cambian) y muestra cuántos falsos positivos y falsos negativos tenía el detector anterior.
Revisar a mano `_cambios.csv` para validar que el detector nuevo mejora y no solo mueve el error.
`muestreo_validacion.py`.
