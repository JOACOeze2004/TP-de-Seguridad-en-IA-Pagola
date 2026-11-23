"""
ShopBot: app para atacar a mano (LLM01/LLM02/LLM08 en modo Chat, LLM03 en modo Herramientas).
Uso:  streamlit run src/streamlit_chatbot.py

Prompts, configs y casos vienen de core.py (los mismos que usa la batería automática).
"""
import json
import os
import urllib.request
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

import core
from core import CONFIGS, DESCRIPCION_CONFIGS, CASOS, CASOS_TOOLS, NOTAS_T6
from herramientas import Entorno
from ataques_info import info as info_ataque, categoria
from defensas import contiene_secreto

# El veredicto usa el detector de la bateria. Si falla el import, la app sigue andando sin veredicto.
try:
    from detectores import clasificar
except Exception:  # pragma: no cover
    clasificar = None

_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_URL = _host if _host.startswith("http") else f"http://{_host}"


def estado_ollama(modelo):
    """'ok' | 'caido' (Ollama no responde) | 'sin_modelo' (responde pero falta el modelo)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            nombres = [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:
        return "caido"
    base = modelo if ":" in modelo else modelo + ":latest"
    return "ok" if (modelo in nombres or base in nombres) else "sin_modelo"


def construir_veredicto(es_preset, ataque, final, crudo, tokens_out):
    """Veredicto automatico de una respuesta del modo Chat.
    - Ataque precargado: usa detectores.clasificar con el caso/variante (igual que la bateria).
    - Mensaje propio: no hay variante, solo se revisa si se filtro un secreto."""
    if es_preset:
        caso, variante = ataque["clave"].split("/", 1)
        if clasificar is not None:
            try:
                nivel, motivo, _ = clasificar(caso, variante, final, tokens_out)
                if motivo != "sin detector":
                    nm = clasificar(caso, variante, crudo, tokens_out)[0] if crudo != final else None
                    return {"tipo": "detector", "caso": caso, "nivel": nivel, "motivo": motivo, "nivel_modelo": nm}
            except Exception:
                pass
        return {"tipo": "sin_detector", "caso": caso}
    return {"tipo": "secreto", "filtra": contiene_secreto(crudo)}


_ETIQUETAS_ATAQUE = {
    "exito": (st.error, "⚠️ Ataque exitoso"),
    "parcial": (st.warning, "🟡 Éxito parcial (ambiguo, conviene leer la respuesta)"),
    "fallo": (st.success, "🛡️ El bot resistió el ataque"),
}
_ETIQUETAS_CONTROL = {
    "control_ok": (st.success, "✅ Respondió bien la consulta legítima"),
    "control_falla": (st.error, "❌ Falso positivo: rechazó o bloqueó una consulta legítima"),
    "parcial": (st.warning, "🟡 Respuesta pobre a una consulta legítima"),
}


def mostrar_veredicto(v):
    if not v:
        return
    tipo = v.get("tipo")
    if tipo == "secreto":
        if v["filtra"]:
            st.error("🔓 Se filtró un secreto (API key o código de descuento).")
        else:
            st.caption("Mensaje propio: no hay veredicto automático (solo se revisa si se filtra un secreto, y no se filtró ninguno).")
        return
    if tipo == "sin_detector":
        st.caption(f"El caso {v['caso']} todavía no tiene detector: sin veredicto automático.")
        return
    etiquetas = _ETIQUETAS_CONTROL if v["caso"] == "C" else _ETIQUETAS_ATAQUE
    fn, texto = etiquetas.get(v["nivel"], (st.info, v["nivel"]))
    fn(f"{texto}  \nMotivo: {v['motivo']}")
    nm = v.get("nivel_modelo")
    if nm and nm != v["nivel"]:
        st.caption(f"🛡️ Sin el filtro de salida, el modelo habría dado: **{nm}**.")

st.set_page_config(page_title="ShopBot", page_icon="🛒", layout="wide")
st.title("🛒 ShopBot - Atención al cliente")
st.markdown("Asistente de ShopBot. Consultas sobre envíos, productos y pedidos.")

# ---------- Ataques precargados (los mismos de las baterías) ----------
# Se omiten los que necesitan historial precargado (P3 *_hist).
PRESETS_CHAT = {f"{c}/{v}": (m, t) for c, v, m, t, h in CASOS if not h}
PRESETS_TOOLS = {f"{c}/{v}": (m, t, NOTAS_T6.get(v, "") if c == "T6" else "")
                 for c, v, m, t in CASOS_TOOLS}

st.session_state.setdefault("mensajes", [])
st.session_state.setdefault("ticket", "")
st.session_state.setdefault("nota", "")


def nueva_conversacion():
    st.session_state.mensajes = []
    st.session_state.pop("env", None)   # base de pedidos limpia


def enviar_ataque(presets, clave):
    """Callback del botón: empieza una conversación nueva y deja el ataque listo para enviar."""
    nueva_conversacion()
    m, t, *resto = presets[clave]
    st.session_state.pendiente = m
    st.session_state.ataque = {"clave": clave, "mensaje": m, "ticket": t}
    st.session_state.ticket = t
    st.session_state.nota = resto[0] if resto else ""


# ---------- Sidebar ----------
nota = ""
with st.sidebar:
    with st.expander("¿Cómo se usa?", expanded=False):
        st.markdown(
            "1. Elegí el **modo** y la **defensa** (o el backend).\n"
            "2. En *Ataques precargados* elegí un **tipo** y una **variante**; leé qué hace.\n"
            "3. Tocá **▶ Enviar ataque**: se carga todo y se envía solo.\n"
            "4. Mirá la respuesta (y, en modo Herramientas, el panel de abajo).\n\n"
            "También podés escribir tu propio ataque en el chat o en el cuadro de ticket. "
            "Empezá cada ataque en una conversación nueva."
        )
    st.header("Configuración")
    modo = st.radio("Modo", ["Chat (prompts)", "Herramientas (LLM03)"],
                    help="Chat: desvío, inyección indirecta y exposición de contexto. "
                         "Herramientas: el bot consulta y modifica pedidos simulados.")
    en_tools = modo.startswith("Herramientas")
    temperature = st.slider("Temperatura", 0.0, 1.0, core.TEMPERATURA, 0.1)
    model_name = st.text_input("Modelo Ollama", core.MODELO)

    if en_tools:
        config = st.selectbox("Backend", ["debil", "endurecida"],
                              help="debil: el backend confía en lo que le pasa el modelo. "
                                   "endurecida: usa la sesión autenticada, verifica dueño y limita transiciones.")
        st.caption("Usuario autenticado: **ana** (pedidos 1001 y 1002). Los pedidos 2001 y 2002 son de **beto**.")
        st.caption("En este modo cada mensaje se responde por separado: el bot no recuerda los anteriores "
                   "(los pedidos sí conservan su estado hasta que empieces una conversación nueva).")
    else:
        config = st.selectbox("Defensa", list(CONFIGS), index=list(CONFIGS).index("debil"))
        st.caption(DESCRIPCION_CONFIGS[config])

    st.subheader("Ticket / FAQ externa (inyección indirecta)")
    ticket = st.text_area("Contenido que se agrega al contexto como si fuera un ticket",
                          key="ticket", height=130)
    if en_tools:
        nota = st.text_area("Nota del pedido 1001 (inyección vía resultado de herramienta, T6)",
                            key="nota", height=100)

    st.subheader("Ataques precargados")
    presets = PRESETS_TOOLS if en_tools else PRESETS_CHAT
    casos_disp = list(dict.fromkeys(k.split("/")[0] for k in presets))
    caso_sel = st.selectbox("Tipo de ataque", casos_disp, key=f"caso_{'t' if en_tools else 'c'}",
                            format_func=lambda c: categoria(c)["nombre"])
    st.caption(categoria(caso_sel)["descripcion"])
    claves = [k for k in presets if k.split("/")[0] == caso_sel]
    clave = st.selectbox("Variante", claves, key=f"var_{caso_sel}",
                         format_func=lambda k: info_ataque(k)["titulo"])
    d = info_ataque(clave)
    st.info(f"**Qué hace:** {d['que_hace']}" + (f"\n\n**Éxito si:** {d['exito']}" if d["exito"] else ""))
    with st.expander("Ver el mensaje, ticket y nota exactos"):
        p_m, p_t, *p_n = presets[clave]
        st.markdown("**Mensaje del usuario**")
        st.text(p_m)
        st.markdown("**Ticket**")
        st.text(p_t or "(vacío)")
        if en_tools:
            st.markdown("**Nota del pedido 1001**")
            st.text((p_n[0] if p_n else "") or "(vacía)")
    if not en_tools:
        st.caption("Las variantes con historial previo (completar_hist, apikey_hist) solo están en la batería automática.")
    st.button("▶ Enviar ataque", on_click=enviar_ataque, args=(presets, clave), type="primary",
              help="Empieza una conversación nueva, carga el ticket/nota y envía el mensaje.")
    st.button("🗑️ Nueva conversación", on_click=nueva_conversacion)

# ---------- Estado de Ollama ----------
_estado = estado_ollama(model_name)
if _estado == "caido":
    st.error("Ollama no responde. Abrilo (o corré `ollama serve` en otra terminal) y recargá la página. "
             "Más fácil: cerrá esto y usá `iniciar.sh` / `iniciar.bat`, que lo levanta solo.")
elif _estado == "sin_modelo":
    st.error(f"Ollama está andando pero falta el modelo `{model_name}`. Bajalo con: `ollama pull {model_name}`")

# ---------- Historial ----------
for msg in st.session_state.mensajes:
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)
        crudo = getattr(msg, "additional_kwargs", {}).get("crudo")
        if crudo is not None:
            st.caption("🛡️ El filtro de salida bloqueó esta respuesta.")
            with st.expander("Ver lo que dijo el modelo (antes del filtro)"):
                st.text(crudo)
        mostrar_veredicto(getattr(msg, "additional_kwargs", {}).get("veredicto"))


def formatear_historial(mensajes):
    lineas = []
    for m in mensajes:
        if isinstance(m, HumanMessage):
            lineas.append(f"Usuario: {m.content}")
        elif isinstance(m, AIMessage):
            lineas.append(f"ShopBot: {m.content}")
    return "\n".join(lineas)


def panel_herramientas(env):
    """Muestra el registro de llamadas y el estado de los pedidos, y cuenta los intentos indebidos."""
    log = env.log
    intentos = sum(1 for x in log if not x["autorizada_real"])
    ejec = sum(1 for x in log if not x["autorizada_real"] and x["ejecutada"])
    if ejec:
        st.error(f"⚠️ Ataque exitoso: {ejec} operación(es) NO autorizada(s) se ejecutaron.")
    elif intentos:
        st.warning(f"El modelo intentó {intentos} operación(es) no autorizada(s), pero el backend las frenó.")
    else:
        st.success("Sin operaciones no autorizadas en esta conversación.")
    with st.expander("Registro de herramientas", expanded=bool(log)):
        st.dataframe([{"herramienta": x["tool"], "argumentos": json.dumps(x["args"], ensure_ascii=False),
                       "autorizada (real)": x["autorizada_real"], "ejecutada": x["ejecutada"]}
                      for x in log] or [{"herramienta": "(sin llamadas)"}])
    with st.expander("Estado de los pedidos"):
        st.dataframe([{"id": k, **{c: p.get(c, "") for c in ("usuario", "producto", "estado", "direccion", "telefono", "nota")}}
                      for k, p in env.db.items()])


# ---------- Entrada ----------
escrita = st.chat_input("Escribe tu mensaje:")
pregunta = escrita or st.session_state.pop("pendiente", None)
ataque = st.session_state.pop("ataque", None) if pregunta else None
# Solo hay veredicto por detector si es el primer mensaje de un ataque precargado sin editar.
es_preset = bool(not en_tools and ataque and pregunta == ataque["mensaje"]
                 and ticket.strip() == ataque["ticket"].strip() and not st.session_state.mensajes)
veredicto = None

if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)

    try:
        with st.chat_message("assistant"):
            modelo = core.nuevo_modelo(modelo=model_name, temperatura=temperature)
            extra = {}

            if en_tools:
                env = st.session_state.get("env")
                if env is None or env.config != config:
                    env = Entorno(config)
                    st.session_state.env = env
                if nota.strip():
                    env.db[1001]["nota"] = nota.strip()
                else:
                    env.db[1001].pop("nota", None)
                mt, mapa = core.preparar_tools(env, modelo)
                with st.spinner("Pensando..."):
                    respuesta, tin, tout, agotado = core.ejecutar(mt, mapa, env, ticket, pregunta)
                st.markdown(respuesta)
                st.caption(f"Tokens → entrada: {tin} | salida: {tout}" + (" | MAX_ITER agotado" if agotado else ""))
            else:
                entrada = core.entrada_de(pregunta, ticket, formatear_historial(st.session_state.mensajes))
                cadena = core.construir_cadena(config, modelo)
                tin = tout = None
                if core.usa_filtro(config):
                    # Con filtro no se muestra en streaming: el texto crudo podría filtrar un secreto
                    with st.spinner("Pensando..."):
                        r = cadena.invoke(entrada)
                    crudo = r.content
                    um = getattr(r, "usage_metadata", None) or {}
                    tin, tout = um.get("input_tokens"), um.get("output_tokens")
                    respuesta, activo = core.postprocesar(config, crudo)
                    if activo:
                        extra["crudo"] = crudo
                    st.markdown(respuesta)
                    if activo:
                        st.caption("🛡️ El filtro de salida bloqueó esta respuesta.")
                        with st.expander("Ver lo que dijo el modelo (antes del filtro)"):
                            st.text(crudo)
                    crudo_txt = crudo
                else:
                    placeholder = st.empty()
                    respuesta = ""
                    for chunk in cadena.stream(entrada):
                        respuesta += chunk.content
                        placeholder.markdown(respuesta + "▌")
                        # Ollama informa los tokens en los metadatos del último chunk
                        if getattr(chunk, "usage_metadata", None):
                            tin = chunk.usage_metadata.get("input_tokens")
                            tout = chunk.usage_metadata.get("output_tokens")
                    placeholder.markdown(respuesta)
                    crudo_txt = respuesta
                if tin is not None:
                    st.caption(f"Tokens → entrada: {tin} | salida: {tout}")
                veredicto = construir_veredicto(es_preset, ataque, respuesta, crudo_txt, tout)
                mostrar_veredicto(veredicto)

        if veredicto:
            extra["veredicto"] = veredicto
        st.session_state.mensajes.append(HumanMessage(content=pregunta))
        st.session_state.mensajes.append(AIMessage(content=respuesta, additional_kwargs=extra))

    except Exception as e:
        st.error(f"Error al generar respuesta: {str(e)}")
        st.info("Verifica que Ollama esté corriendo y que el modelo esté descargado.")

# ---------- Panel de herramientas (después de procesar, así refleja el último mensaje) ----------
if en_tools and st.session_state.get("env") is not None:
    panel_herramientas(st.session_state.env)
