"""
ShopBot: app para atacar a mano (LLM01/LLM02/LLM08 en modo Chat, LLM03 en modo Herramientas).
Uso:  streamlit run src/streamlit_chatbot.py

Prompts, configs y casos vienen de core.py (los mismos que usa la batería automática).
"""
import json
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

import core
from core import CONFIGS, DESCRIPCION_CONFIGS, CASOS, CASOS_TOOLS, NOTAS_T6
from herramientas import Entorno

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
    st.session_state.ticket = t
    st.session_state.nota = resto[0] if resto else ""


# ---------- Sidebar ----------
nota = ""
with st.sidebar:
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
    clave = st.selectbox("Ataque", list(presets))
    st.button("▶ Enviar ataque", on_click=enviar_ataque, args=(presets, clave),
              help="Empieza una conversación nueva, carga el ticket/nota y envía el mensaje.")
    st.button("🗑️ Nueva conversación", on_click=nueva_conversacion)

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
                if tin is not None:
                    st.caption(f"Tokens → entrada: {tin} | salida: {tout}")

        st.session_state.mensajes.append(HumanMessage(content=pregunta))
        st.session_state.mensajes.append(AIMessage(content=respuesta, additional_kwargs=extra))

    except Exception as e:
        st.error(f"Error al generar respuesta: {str(e)}")
        st.info("Verifica que Ollama esté corriendo y que el modelo esté descargado.")

# ---------- Panel de herramientas (después de procesar, así refleja el último mensaje) ----------
if en_tools and st.session_state.get("env") is not None:
    panel_herramientas(st.session_state.env)
