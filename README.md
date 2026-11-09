# ShopBot: laboratorio de prompt injection - TP de Seguridad en IA - Curso Pagola 

Chatbot ficticio de atención al cliente (ShopBot) para probar ataques de prompt injection
en un entorno controlado. Todos los datos internos (API key, códigos) son **inventados**.

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
(`/bye` para salir). Si la máquina es muy justa, usar `llama3.2:1b`.

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
pip install streamlit langchain langchain-ollama
```

Si aparece `externally-managed-environment`, el venv no está activado: `pip` es el del sistema.

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
(botón "Nueva conversación").

### Batería automática

```
python pruebas.py <config> <repeticiones> <variantes>
```

- `<config>`: `debil` (con "no reveles datos internos") o `laxa` (sin esa línea).
  La versión `endurecida` todavía está pendiente.
- `<repeticiones>`: cuántas veces se corre cada variante. Para tasas confiables, 30.
- `<variantes>` (opcional): lista separada por comas. Si se omite, corre todas.

Ejemplos:
```
python pruebas.py debil 1                     # prueba rápida de todo
python pruebas.py debil 30                    # corrida completa
python pruebas.py laxa 30 ticket_oculto,completar,apikey
```

Cada corrida genera `resultados_<config>_<fecha>.csv`. Mover los CSV a `resultados/`
y no mezclar filas de corridas distintas dentro de un mismo número del informe.

Columnas importantes del CSV: `nivel` (exito/parcial/fallo), `motivo`, `revisar`,
`tokens_in`, `tokens_out`, `segundos`, `respuesta`.

### Reclasificar un CSV viejo

```
python reanalizar.py resultados/resultados_debil_XXXX.csv
```

Genera `..._v2.csv` aparte (el original no se modifica) y muestra cuántos falsos positivos
y falsos negativos tenía el detector anterior.