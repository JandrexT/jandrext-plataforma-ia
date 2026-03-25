import streamlit as st
import os, time, json, uuid, concurrent.futures
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Rutas ────────────────────────────────────────────────────────────────────
DATA_DIR      = Path("jandrext_data")
CHATS_DIR     = DATA_DIR / "chats"
PROYECTOS_DIR = DATA_DIR / "proyectos"
BIBLIOTECA    = DATA_DIR / "biblioteca.json"
MANUALES_DIR  = DATA_DIR / "manuales"

for d in [CHATS_DIR, PROYECTOS_DIR, MANUALES_DIR]:
    d.mkdir(parents=True, exist_ok=True)
if not BIBLIOTECA.exists():
    BIBLIOTECA.write_text("[]", encoding="utf-8")

# ── Contexto institucional JandrexT ──────────────────────────────────────────
CONTEXTO_JANDREXT = """
Eres un asistente experto de JandrexT Soluciones Integrales, empresa colombiana especializada en:
1. Automatización de accesos: motores para puertas, electroimanes, lectores RFID, biometría, controladoras ZKTeco
2. Videovigilancia CCTV: cámaras análogas e IP, DVR/NVR, monitoreo centralizado
3. Infraestructura eléctrica y redes: cableado estructurado UTP/coaxial, UPS, diagnóstico de fallas
4. Desarrollo de software: plataformas para propiedad horizontal, automatización de procesos, integración con APIs
5. Servicios tecnológicos: mantenimiento de equipos, redes domésticas, recuperación de información
6. Ingeniería y diagnóstico: análisis técnico, corrección de errores, informes técnicos para soporte legal

Director de Proyectos: Andrés Tapiero
Clientes: conjuntos residenciales, empresas, administraciones, clientes naturales

INSTRUCCIONES DE COMPORTAMIENTO:
- Sé siempre EMPÁTICO y PROFESIONAL, nunca frío ni genérico
- Adapta el lenguaje al tipo de cliente (técnico para empresas, simple para clientes naturales)
- Incluye recomendaciones de mantenimiento preventivo cuando sea relevante
- Enfócate en durabilidad, estabilidad y escalabilidad de las soluciones
- Cuando generes propuestas, usa el enfoque diferencial: integración completa hardware+software+operación
"""

PLANTILLAS = {
    "🎥 Diagnóstico CCTV": "Necesito realizar un diagnóstico técnico de un sistema de videovigilancia. El cliente tiene [describir situación]. ¿Qué pasos debo seguir, qué herramientas necesito y qué informe debo entregar?",
    "🚗 Cotización control de acceso": "El cliente necesita un sistema de control de acceso vehicular y peatonal para [describir predio]. ¿Qué equipos recomiendan, cuál sería el proceso de instalación y qué mantenimiento preventivo se debe hacer?",
    "🔌 Falla eléctrica": "Se presenta una falla eléctrica en el sistema de [describir]. Los síntomas son [describir]. ¿Cómo diagnostico la causa raíz y cómo la soluciono de forma segura y definitiva?",
    "📋 Propuesta técnica": "Necesito generar una propuesta técnica profesional para [tipo de cliente] que requiere [servicio]. Incluir descripción técnica, equipos, tiempo estimado y recomendaciones.",
    "🛡️ Mantenimiento preventivo": "¿Cuál es el plan de mantenimiento preventivo recomendado para [tipo de sistema] instalado en [tipo de predio]? Incluir frecuencias, tareas específicas y señales de alerta.",
    "📱 Configuración DVR/NVR": "Necesito una guía paso a paso para configurar un DVR/NVR [marca/modelo] incluyendo: acceso inicial, configuración de cámaras, contraseñas seguras, acceso remoto y respaldo de grabaciones.",
    "💼 Propuesta comercial": "Genera una propuesta comercial completa para [tipo de cliente] interesado en [servicio]. Debe ser profesional, empática y mostrar el valor diferencial de JandrexT.",
    "📖 Manual de usuario": "Crea un manual de usuario para [sistema instalado] en [nombre del proyecto/cliente]. Incluir: descripción del sistema, operación diaria, solución de problemas comunes y contacto de soporte.",
}

TIPOS_PROYECTO = {
    "🏢 Copropiedad / Propiedad Horizontal": "El proyecto es para una copropiedad o conjunto residencial. Considera normativas de propiedad horizontal, múltiples usuarios, administración y convivencia.",
    "🏭 Empresa": "El proyecto es para una empresa. Considera continuidad operativa, seguridad corporativa, escalabilidad y retorno de inversión.",
    "🏠 Cliente Natural": "El proyecto es para un hogar o usuario individual. Usa lenguaje simple, enfócate en facilidad de uso, economía y soporte cercano.",
    "🏛️ Administración": "El proyecto es para una administración pública o privada. Considera procesos formales, documentación, licitaciones y normativas.",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def cargar_json(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except: return []

def guardar_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def listar_proyectos():
    return sorted([p for p in PROYECTOS_DIR.iterdir() if p.is_dir()],
                  key=lambda p: p.stat().st_mtime, reverse=True)

def listar_chats_globales():
    return sorted(CHATS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

def listar_chats_proyecto(pid):
    d = PROYECTOS_DIR / pid / "chats"
    d.mkdir(exist_ok=True)
    return sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

def guardar_consulta_chat(ruta_chat, pregunta, respuestas, sintesis, ias):
    data = cargar_json(ruta_chat) if ruta_chat.exists() else []
    data.append({
        "id": str(uuid.uuid4())[:8],
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pregunta": pregunta,
        "respuestas": [{"ia": r["ia"], "texto": r["respuesta"], "tiempo": r["tiempo"]} for r in respuestas if r["ok"]],
        "sintesis": sintesis,
        "ias": ias,
    })
    guardar_json(ruta_chat, data)

def guardar_en_biblioteca(proyecto, pregunta, sintesis, ias):
    lib = cargar_json(BIBLIOTECA)
    lib.insert(0, {
        "id": str(uuid.uuid4())[:8],
        "proyecto": proyecto,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pregunta": pregunta,
        "sintesis": sintesis,
        "ias": ias,
    })
    guardar_json(BIBLIOTECA, lib)

# ── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="JandrexT | Plataforma Multi-IA",
    page_icon="🧠", layout="wide",
    initial_sidebar_state="expanded",
)

# ── Estilos ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.header-inst{background:linear-gradient(135deg,#0a0000 0%,#1a0000 60%,#0a0000 100%);
    border-radius:14px;padding:1.5rem 2rem;margin-bottom:1.2rem;border:1px solid #cc0000;position:relative;overflow:hidden;}
.brand-name{font-size:2rem;font-weight:900;color:#fff;letter-spacing:2px;margin:0;text-transform:uppercase;}
.brand-accent{color:#cc0000;}
.brand-sub{color:#666;font-size:0.7rem;letter-spacing:4px;text-transform:uppercase;margin:0;}
.director-badge{background:rgba(204,0,0,0.1);border:1px solid rgba(204,0,0,0.35);
    border-radius:7px;padding:0.4rem 0.9rem;display:inline-block;margin-top:0.6rem;}
.director-nombre{color:#ffcccc;font-size:0.82rem;font-weight:700;margin:0;}
.director-cargo{color:#cc0000;font-size:0.7rem;margin:0;}
.powered{position:absolute;top:1.2rem;right:1.2rem;background:rgba(204,0,0,0.1);
    border:1px solid rgba(204,0,0,0.25);border-radius:20px;padding:0.25rem 0.8rem;
    color:#cc0000;font-size:0.65rem;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;}
.chat-user{background:linear-gradient(135deg,#1a0000,#2a0000);border:1px solid #cc0000;
    border-radius:12px 12px 4px 12px;padding:0.8rem 1.1rem;margin:0.5rem 0;color:#f0f0f0;}
.chat-ia{background:linear-gradient(135deg,#0a0a0a,#111);border:1px solid #222;
    border-radius:12px 12px 12px 4px;padding:0.8rem 1.1rem;margin:0.5rem 0;color:#e0e0e0;}
.chat-meta{color:#555;font-size:0.72rem;margin-bottom:0.3rem;}
.ia-card{background:linear-gradient(135deg,#0f0000,#1a0808);border:1px solid #2a0000;
    border-radius:10px;padding:1rem;transition:border-color 0.2s;}
.ia-card:hover{border-color:#cc0000;}
.ia-card h4{margin:0 0 0.3rem 0;font-size:0.95rem;color:#f0f0f0;font-weight:600;}
.badge-ok{color:#4ade80;font-weight:600;font-size:0.82rem;}
.badge-err{color:#f87171;font-weight:600;font-size:0.82rem;}
.tiempo{color:#555;font-size:0.75rem;margin-left:5px;}
.juez-card{background:linear-gradient(135deg,#0f0000,#1a0000);border:2px solid #cc0000;
    border-radius:12px;padding:1.5rem;margin-top:0.8rem;color:#f0f0f0;line-height:1.75;}
.juez-titulo{color:#cc0000;font-size:0.7rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;}
.sidebar-brand{background:linear-gradient(135deg,#0f0000,#1a0000);border:1px solid #cc0000;
    border-radius:10px;padding:0.9rem;margin-bottom:0.5rem;text-align:center;}
.sidebar-brand-name{color:#fff;font-weight:900;font-size:1rem;margin:0;letter-spacing:2px;text-transform:uppercase;}
.sidebar-brand-sub{color:#cc0000;font-size:0.62rem;margin:0;letter-spacing:2px;text-transform:uppercase;font-weight:600;}
.voz-box{background:linear-gradient(135deg,#0f0000,#1a0000);border:1px solid #cc0000;
    border-radius:10px;padding:0.8rem 1.2rem;margin-bottom:0.8rem;}
.plantilla-btn{background:#0f0000;border:1px solid #2a0000;border-radius:8px;
    padding:0.5rem 0.8rem;margin:0.2rem;cursor:pointer;color:#ccc;font-size:0.82rem;
    transition:all 0.2s;display:inline-block;}
.plantilla-btn:hover{border-color:#cc0000;color:#fff;}
.manual-card{background:#0f0000;border:1px solid #cc0000;border-radius:10px;padding:1.2rem;margin-bottom:0.5rem;}
.manual-titulo{color:#ff6666;font-size:0.95rem;font-weight:700;margin:0 0 0.3rem 0;}
.manual-meta{color:#555;font-size:0.72rem;}
.footer-inst{background:#0a0000;border:1px solid #1a0000;border-radius:8px;
    padding:0.8rem;text-align:center;margin-top:1.5rem;color:#444;font-size:0.72rem;}
.footer-inst span{color:#cc0000;font-weight:700;}
.divider{border:none;border-top:1px solid #1a0000;margin:1.2rem 0;}
.section-title{color:#cc0000;font-size:0.72rem;font-weight:700;letter-spacing:2px;
    text-transform:uppercase;margin:1rem 0 0.5rem 0;}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
defaults = {
    "seccion": "chat", "chat_activo": None,
    "proyecto_activo": None, "subchat_activo": None,
    "plantilla_texto": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Funciones IA ──────────────────────────────────────────────────────────────
def consultar_gemini(p, modelo="gemini-1.5-flash"):
    try:
        import google.generativeai as genai
        t = time.time()
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        r = genai.GenerativeModel(modelo).generate_content(CONTEXTO_JANDREXT + "\n\nConsulta: " + p)
        return {"ia":"Gemini","icono":"🔵","respuesta":r.text.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Gemini","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def consultar_groq(p, modelo="llama-3.3-70b-versatile"):
    try:
        from groq import Groq
        t = time.time()
        r = Groq(api_key=os.getenv("GROQ_API_KEY")).chat.completions.create(
            model=modelo,
            messages=[
                {"role":"system","content":CONTEXTO_JANDREXT},
                {"role":"user","content":p}
            ], max_tokens=1500)
        return {"ia":"Groq · LLaMA","icono":"🟠","respuesta":r.choices[0].message.content.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Groq · LLaMA","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def consultar_venice(p, modelo="llama-3.3-70b"):
    try:
        import requests as req
        t = time.time()
        h = {"Authorization":f"Bearer {os.getenv('VENICE_API_KEY')}","Content-Type":"application/json"}
        r = req.post("https://api.venice.ai/api/v1/chat/completions",
            json={"model":modelo,"messages":[
                {"role":"system","content":CONTEXTO_JANDREXT},
                {"role":"user","content":p}
            ],"max_tokens":1500}, headers=h, timeout=30)
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return {"ia":"Venice AI","icono":"🟣","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Venice AI","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def juez_gemini(pregunta, respuestas, contexto_extra=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        resumen = "\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in respuestas if r["ok"]])
        prompt = f"""{CONTEXTO_JANDREXT}
{contexto_extra}

Pregunta del equipo JandrexT: "{pregunta}"

Respuestas de las IAs consultadas:
{resumen}

Sintetiza la mejor respuesta. Sé empático, profesional y práctico.
Si aplica, incluye recomendaciones de mantenimiento preventivo.
Adapta el lenguaje al contexto de JandrexT Soluciones Integrales."""
        r = genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e:
        return f"❌ Error: {e}"

def generar_documento(tipo, contenido, proyecto=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        prompt = f"""{CONTEXTO_JANDREXT}

Genera un {tipo} profesional e institucional para JandrexT Soluciones Integrales.
Director de Proyectos: Andrés Tapiero
{f'Proyecto: {proyecto}' if proyecto else ''}

Información base:
{contenido}

El documento debe:
- Tener formato profesional con secciones claras
- Usar membrete institucional de JandrexT
- Incluir fecha: {datetime.now().strftime('%d de %B de %Y')}
- Ser empático pero técnicamente preciso
- Incluir recomendaciones de mantenimiento preventivo si aplica
- Cerrar con datos de contacto de JandrexT Soluciones Integrales"""
        r = genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e:
        return f"❌ Error generando documento: {e}"

# ── Panel de consulta ─────────────────────────────────────────────────────────
def panel_consulta(ruta_chat, nombre_proyecto="General", tipo_proyecto="",
                   usar_gemini=True, usar_groq=True, usar_venice=True,
                   modelo_gemini="gemini-1.5-flash", modelo_groq="llama-3.3-70b-versatile",
                   modelo_venice="llama-3.3-70b"):

    contexto_extra = TIPOS_PROYECTO.get(tipo_proyecto, "") if tipo_proyecto else ""

    # Historial
    mensajes = cargar_json(ruta_chat) if ruta_chat.exists() else []
    if mensajes:
        st.markdown("##### 💬 Conversación")
        for m in mensajes:
            st.markdown(f'<div class="chat-user"><span class="chat-meta">🧑 {m["fecha"]} · {" · ".join(m["ias"])}</span><br>{m["pregunta"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="chat-ia"><span class="chat-meta">🏛️ JandrexT IA</span><br>{m["sintesis"]}</div>', unsafe_allow_html=True)
        st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # Plantillas rápidas
    with st.expander("📋 Plantillas rápidas por línea de servicio"):
        cols = st.columns(4)
        for i, (nombre, texto) in enumerate(PLANTILLAS.items()):
            with cols[i % 4]:
                if st.button(nombre, key=f"plt_{ruta_chat.stem}_{i}", use_container_width=True):
                    st.session_state[f"input_{ruta_chat.stem}"] = texto
                    st.rerun()

    # Voz
    voz_key   = f"voz_texto_{ruta_chat.stem}"
    input_key = f"input_{ruta_chat.stem}"
    if voz_key   not in st.session_state: st.session_state[voz_key]   = ""
    if input_key not in st.session_state: st.session_state[input_key] = ""

    try:
        from streamlit_mic_recorder import speech_to_text
        st.markdown('<div class="voz-box">', unsafe_allow_html=True)
        c1, c2 = st.columns([1,3])
        with c1:
            texto_voz = speech_to_text(language="es", start_prompt="🎤 Hablar",
                stop_prompt="⏹️ Detener", just_once=True,
                use_container_width=True, key=f"mic_{ruta_chat.stem}")
        with c2:
            st.caption("**1.** 🎤 Hablar → **2.** Di tu consulta → **3.** ⏹️ Detener")
        st.markdown('</div>', unsafe_allow_html=True)
        if texto_voz:
            st.session_state[voz_key]   = texto_voz
            st.session_state[input_key] = texto_voz
            st.success(f"🎙️ *{texto_voz}*")
    except ImportError:
        pass

    pregunta = st.text_area("✍️ Nueva consulta",
        height=110, key=input_key,
        placeholder="Escribe tu consulta, usa el micrófono o selecciona una plantilla...")

    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        consultar = st.button("🚀 Consultar todas las IAs", use_container_width=True,
            type="primary", key=f"btn_{ruta_chat.stem}")

    if consultar and pregunta.strip():
        ias = []
        if usar_gemini: ias.append(lambda p: consultar_gemini(p, modelo_gemini))
        if usar_groq:   ias.append(lambda p: consultar_groq(p, modelo_groq))
        if usar_venice: ias.append(lambda p: consultar_venice(p, modelo_venice))
        if not ias:
            st.warning("Activa al menos una IA.")
            return

        with st.spinner("Consultando IAs con contexto JandrexT..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ias)) as ex:
                resultados = list(ex.map(lambda fn: fn(pregunta), ias))

        orden = {"Gemini":0,"Groq · LLaMA":1,"Venice AI":2}
        resultados.sort(key=lambda r: orden.get(r["ia"],99))

        cols = st.columns(len(resultados))
        for i, res in enumerate(resultados):
            with cols[i]:
                cls = "badge-ok" if res["ok"] else "badge-err"
                st.markdown(f'<div class="ia-card"><h4>{res["icono"]} {res["ia"]}</h4><span class="{cls}">{"✓ OK" if res["ok"] else "✗ Error"}</span><span class="tiempo">⏱ {res["tiempo"]}s</span></div>', unsafe_allow_html=True)
                if res["ok"]:
                    with st.expander("Ver respuesta"):
                        st.write(res["respuesta"])

        ok = [r for r in resultados if r["ok"]]
        if ok:
            with st.spinner("Sintetizando respuesta JandrexT..."):
                sintesis = juez_gemini(pregunta, ok, contexto_extra)

            st.markdown(f'<div class="juez-card"><div class="juez-titulo">🏛️ Respuesta JandrexT · {nombre_proyecto}</div><br>{sintesis}</div>', unsafe_allow_html=True)

            with st.expander("📋 Copiar texto"):
                st.code(sintesis, language=None)

            ias_names = [r["ia"] for r in ok]
            guardar_consulta_chat(ruta_chat, pregunta, ok, sintesis, ias_names)
            guardar_en_biblioteca(nombre_proyecto, pregunta, sintesis, ias_names)
            st.session_state[input_key] = ""
            st.session_state[voz_key]   = ""
            st.rerun()
        else:
            st.error("❌ Ninguna IA respondió. Verifica tus API keys.")
    elif consultar:
        st.warning("⚠️ Escribe o dicta una consulta.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""<div class="sidebar-brand">
        <p class="sidebar-brand-name">Jandre<span style="color:#cc0000">x</span>T</p>
        <p class="sidebar-brand-sub">Soluciones Integrales</p>
    </div>""", unsafe_allow_html=True)

    st.markdown('<p class="section-title">📌 Navegación</p>', unsafe_allow_html=True)
    secciones = [("💬","chat","Chats"),("📁","proyectos","Proyectos"),
                 ("📚","biblioteca","Biblioteca"),("📄","documentos","Documentos"),
                 ("📖","manuales","Manuales"),("💼","ventas","Asistente de Ventas")]
    for ico, key, label in secciones:
        if st.button(f"{ico}  {label}", key=f"nav_{key}", use_container_width=True):
            st.session_state.seccion = key
            st.rerun()

    st.markdown("---")
    st.markdown('<p class="section-title">⚡ IAs activas</p>', unsafe_allow_html=True)
    usar_gemini = st.toggle("🔵 Gemini", value=True)
    usar_groq   = st.toggle("🟠 Groq",   value=True)
    usar_venice = st.toggle("🟣 Venice",  value=True)

    st.markdown("---")
    st.markdown('<p class="section-title">🔧 Modelos</p>', unsafe_allow_html=True)
    modelo_gemini = st.selectbox("Gemini", ["gemini-1.5-flash","gemini-1.5-pro","gemini-2.0-flash"])
    modelo_groq   = st.selectbox("Groq",   ["llama-3.3-70b-versatile","llama-3.1-8b-instant"])
    modelo_venice = st.selectbox("Venice", ["llama-3.3-70b","mistral-31-24b"])
    st.caption("🔒 Keys desde `.env` o Secrets.")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""<div class="header-inst">
    <span class="powered">⚡ Plataforma Multi-IA v7</span>
    <p class="brand-name">Jandre<span class="brand-accent">x</span>T</p>
    <p class="brand-sub">Soluciones Integrales</p>
    <div class="director-badge">
        <p class="director-nombre">👤 Andrés Tapiero</p>
        <p class="director-cargo">Director de Proyectos · JandrexT Soluciones Integrales</p>
    </div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.seccion == "chat":
    st.markdown("## 💬 Chats")
    st.caption("Consultas generales con contexto JandrexT siempre activo.")
    col_lista, col_chat = st.columns([1,3])

    with col_lista:
        st.markdown('<p class="section-title">Mis chats</p>', unsafe_allow_html=True)
        if st.button("➕ Nuevo chat", use_container_width=True):
            nid = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.session_state.chat_activo = CHATS_DIR / f"{nid}.json"
            st.rerun()
        for cf in listar_chats_globales():
            data = cargar_json(cf)
            nombre = data[0]["pregunta"][:28]+"..." if data else "Chat vacío"
            fecha  = data[-1]["fecha"] if data else ""
            if st.button(f"💬 {nombre}\n{fecha}", key=f"ch_{cf.stem}", use_container_width=True):
                st.session_state.chat_activo = cf
                st.rerun()

    with col_chat:
        if st.session_state.chat_activo:
            ruta = Path(st.session_state.chat_activo)
            data = cargar_json(ruta) if ruta.exists() else []
            titulo = data[0]["pregunta"][:40]+"..." if data else "Nuevo chat"
            st.markdown(f"### 💬 {titulo}")
            panel_consulta(ruta, "General", "", usar_gemini, usar_groq, usar_venice,
                          modelo_gemini, modelo_groq, modelo_venice)
        else:
            st.info("👈 Selecciona un chat o crea uno nuevo.")

# ══════════════════════════════════════════════════════════════════════════════
# PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.seccion == "proyectos":
    st.markdown("## 📁 Proyectos")
    st.caption("Organiza consultas por proyecto con contexto específico por tipo de cliente.")
    col_proy, col_cont = st.columns([1,3])

    with col_proy:
        st.markdown('<p class="section-title">Proyectos</p>', unsafe_allow_html=True)
        with st.expander("➕ Nuevo proyecto"):
            n_nombre = st.text_input("Nombre del proyecto", key="np_nombre")
            n_desc   = st.text_input("Descripción", key="np_desc")
            n_tipo   = st.selectbox("Tipo de cliente", list(TIPOS_PROYECTO.keys()), key="np_tipo")
            n_client = st.text_input("Nombre del cliente", key="np_client")
            if st.button("Crear", use_container_width=True, key="btn_crear_proy"):
                if n_nombre.strip():
                    pid = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{n_nombre[:15].replace(' ','_')}"
                    pdir = PROYECTOS_DIR / pid
                    pdir.mkdir(parents=True)
                    (pdir / "chats").mkdir()
                    guardar_json(pdir/"meta.json", {
                        "nombre": n_nombre, "descripcion": n_desc,
                        "tipo": n_tipo, "cliente": n_client,
                        "creado": datetime.now().strftime("%Y-%m-%d %H:%M")
                    })
                    st.session_state.proyecto_activo = pid
                    st.session_state.subchat_activo  = None
                    st.rerun()

        for pdir in listar_proyectos():
            meta = cargar_json(pdir/"meta.json") if (pdir/"meta.json").exists() else {}
            nombre = meta.get("nombre", pdir.name)
            tipo   = meta.get("tipo","")[:20]
            nchats = len(list((pdir/"chats").glob("*.json")))
            activo = st.session_state.proyecto_activo == pdir.name
            if st.button(f"{'▶ ' if activo else ''}📁 {nombre}\n{tipo} · {nchats} chats",
                         key=f"proy_{pdir.name}", use_container_width=True):
                st.session_state.proyecto_activo = pdir.name
                st.session_state.subchat_activo  = None
                st.rerun()

    with col_cont:
        if st.session_state.proyecto_activo:
            pid  = st.session_state.proyecto_activo
            pdir = PROYECTOS_DIR / pid
            meta = cargar_json(pdir/"meta.json") if (pdir/"meta.json").exists() else {}
            nombre_proy = meta.get("nombre", pid)
            tipo_proy   = meta.get("tipo","")
            cliente     = meta.get("cliente","")
            desc        = meta.get("descripcion","")

            st.markdown(f"### 📁 {nombre_proy}")
            cols_m = st.columns(3)
            if tipo_proy:   cols_m[0].caption(f"🏷️ {tipo_proy}")
            if cliente:     cols_m[1].caption(f"👤 {cliente}")
            if desc:        cols_m[2].caption(f"📝 {desc}")
            st.markdown('<hr class="divider">', unsafe_allow_html=True)

            col_sc, col_sc_cont = st.columns([1,2])
            with col_sc:
                st.markdown('<p class="section-title">Sub-chats</p>', unsafe_allow_html=True)
                if st.button("➕ Nuevo sub-chat", use_container_width=True, key="btn_nuevo_sc"):
                    nid = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.session_state.subchat_activo = pdir/"chats"/f"{nid}.json"
                    st.rerun()
                for scf in listar_chats_proyecto(pid):
                    data = cargar_json(scf)
                    n_sc = data[0]["pregunta"][:22]+"..." if data else "Sub-chat vacío"
                    f_sc = data[-1]["fecha"] if data else ""
                    activo_sc = str(st.session_state.subchat_activo) == str(scf)
                    if st.button(f"{'▶ ' if activo_sc else ''}💬 {n_sc}\n{f_sc}",
                                 key=f"sc_{scf.stem}", use_container_width=True):
                        st.session_state.subchat_activo = scf
                        st.rerun()

            with col_sc_cont:
                if st.session_state.subchat_activo:
                    ruta_sc = Path(st.session_state.subchat_activo)
                    data_sc = cargar_json(ruta_sc) if ruta_sc.exists() else []
                    titulo_sc = data_sc[0]["pregunta"][:32]+"..." if data_sc else "Nuevo sub-chat"
                    st.markdown(f"#### 💬 {titulo_sc}")
                    panel_consulta(ruta_sc, nombre_proy, tipo_proy,
                                  usar_gemini, usar_groq, usar_venice,
                                  modelo_gemini, modelo_groq, modelo_venice)
                else:
                    st.info("👈 Crea o selecciona un sub-chat.")
        else:
            st.info("👈 Selecciona un proyecto o crea uno nuevo.")

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.seccion == "biblioteca":
    st.markdown("## 📚 Biblioteca")
    st.caption("Registro completo de todas las consultas.")
    lib = cargar_json(BIBLIOTECA)
    if not lib:
        st.info("La biblioteca está vacía. Realiza consultas para que aparezcan aquí.")
    else:
        c1,c2,c3 = st.columns(3)
        proyectos_unicos = ["Todos"] + list(dict.fromkeys([l["proyecto"] for l in lib]))
        filtro_proy   = c1.selectbox("📁 Proyecto", proyectos_unicos)
        filtro_buscar = c2.text_input("🔍 Buscar")
        c3.metric("Total consultas", len(lib))

        filtrada = lib
        if filtro_proy != "Todos":
            filtrada = [l for l in filtrada if l["proyecto"] == filtro_proy]
        if filtro_buscar:
            filtrada = [l for l in filtrada if filtro_buscar.lower() in l["pregunta"].lower()
                        or filtro_buscar.lower() in l["sintesis"].lower()]

        st.markdown(f"**{len(filtrada)} resultado(s)**")
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        for item in filtrada:
            with st.expander(f"📌 {item['pregunta'][:65]}...  |  📁 {item['proyecto']}  |  📅 {item['fecha']}"):
                st.markdown(f"**IAs:** {' · '.join(item['ias'])}")
                st.markdown(item["sintesis"])
                st.code(item["sintesis"], language=None)

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.seccion == "documentos":
    st.markdown("## 📄 Generador de Documentos")
    st.caption("Crea propuestas técnicas, informes y actas con membrete JandrexT.")

    tipo_doc = st.selectbox("Tipo de documento", [
        "Propuesta Técnica", "Informe de Diagnóstico",
        "Acta de Mantenimiento", "Informe Técnico para Soporte Legal",
        "Cotización de Servicios", "Acta de Entrega de Proyecto",
    ])

    proyecto_doc = st.text_input("Nombre del proyecto / cliente")
    tipo_cliente = st.selectbox("Tipo de cliente", list(TIPOS_PROYECTO.keys()))

    contenido = st.text_area("Describe el contenido del documento",
        height=150,
        placeholder="Ej: Sistema de videovigilancia con 8 cámaras IP instalado en Conjunto Residencial Los Pinos. Se instalaron cámaras Hikvision 2MP, NVR de 16 canales, acceso remoto configurado...")

    if st.button("📄 Generar documento", type="primary", use_container_width=False):
        if contenido.strip():
            with st.spinner("Generando documento institucional JandrexT..."):
                ctx = TIPOS_PROYECTO.get(tipo_cliente,"")
                documento = generar_documento(tipo_doc, f"{ctx}\n{contenido}", proyecto_doc)
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown(f"### 📄 {tipo_doc}")
            if proyecto_doc: st.caption(f"Proyecto: {proyecto_doc}")
            st.markdown(documento)
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.code(documento, language=None)

            # Guardar en biblioteca
            guardar_en_biblioteca(
                proyecto_doc or "Documentos",
                f"[{tipo_doc}] {contenido[:60]}",
                documento, ["Gemini"]
            )
        else:
            st.warning("⚠️ Describe el contenido del documento.")

# ══════════════════════════════════════════════════════════════════════════════
# MANUALES
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.seccion == "manuales":
    st.markdown("## 📖 Generador de Manuales")
    st.caption("Crea manuales técnicos y de usuario personalizados para cada proyecto.")

    col_form, col_lista_man = st.columns([2,1])

    with col_form:
        st.markdown("### Crear nuevo manual")
        man_proyecto  = st.text_input("Nombre del proyecto / cliente")
        man_sistema   = st.text_input("Sistema instalado",
            placeholder="Ej: DVR Hikvision DS-7208HGHI, Sistema CCTV 8 cámaras")
        man_tipo      = st.selectbox("Tipo de manual", [
            "Manual de Usuario", "Manual Técnico de Instalación",
            "Guía de Configuración y Contraseñas",
            "Plan de Mantenimiento Preventivo",
            "Manual de Operación Diaria",
            "Guía de Acceso Remoto",
        ])
        man_detalles  = st.text_area("Detalles específicos del sistema",
            height=130,
            placeholder="Ej: DVR con 8 canales, contraseña admin123, IP local 192.168.1.100, configurado con acceso remoto por app iVMS-4500, grabación continua 24/7 en disco 2TB...")
        man_cliente_tipo = st.selectbox("Tipo de cliente destinatario", list(TIPOS_PROYECTO.keys()))

        if st.button("📖 Generar manual", type="primary"):
            if man_sistema.strip() and man_detalles.strip():
                with st.spinner("Generando manual personalizado..."):
                    ctx = TIPOS_PROYECTO.get(man_cliente_tipo,"")
                    prompt_manual = f"""
Crea un {man_tipo} completo y profesional para JandrexT Soluciones Integrales.

Proyecto/Cliente: {man_proyecto}
Sistema: {man_sistema}
Tipo de destinatario: {ctx}
Detalles específicos: {man_detalles}
Fecha: {datetime.now().strftime('%d de %B de %Y')}

El manual debe incluir:
1. Portada con datos de JandrexT y del proyecto
2. Índice de contenido
3. Descripción del sistema instalado
4. Instrucciones paso a paso (numeradas y claras)
5. Contraseñas y datos de acceso (si aplica)
6. Solución de problemas comunes
7. Plan de mantenimiento preventivo con frecuencias
8. Señales de alerta y cuándo llamar a soporte
9. Datos de contacto de JandrexT Soluciones Integrales - Andrés Tapiero

Usa lenguaje adaptado al tipo de destinatario. Sé empático, claro y muy práctico.
Incluye advertencias de seguridad donde sea necesario.
"""
                    manual = generar_documento(man_tipo, prompt_manual, man_proyecto)

                # Guardar manual
                mid = datetime.now().strftime("%Y%m%d_%H%M%S")
                man_path = MANUALES_DIR / f"{mid}_{man_proyecto[:15].replace(' ','_')}.json"
                guardar_json(man_path, {
                    "titulo": f"{man_tipo} — {man_sistema}",
                    "proyecto": man_proyecto,
                    "sistema": man_sistema,
                    "tipo": man_tipo,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "contenido": manual,
                })

                st.markdown('<hr class="divider">', unsafe_allow_html=True)
                st.markdown(f"### 📖 {man_tipo}")
                st.caption(f"Proyecto: {man_proyecto} · Sistema: {man_sistema}")
                st.markdown(manual)
                st.code(manual, language=None)
                st.success("✅ Manual guardado en la biblioteca de manuales.")
                st.rerun()
            else:
                st.warning("⚠️ Completa el sistema instalado y los detalles.")

    with col_lista_man:
        st.markdown("### 📚 Manuales guardados")
        manuales = sorted(MANUALES_DIR.glob("*.json"),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        if not manuales:
            st.info("No hay manuales aún.")
        else:
            for mf in manuales:
                data_m = cargar_json(mf)
                if isinstance(data_m, dict):
                    with st.expander(f"📖 {data_m.get('proyecto','')}\n{data_m.get('tipo','')}"):
                        st.caption(f"📅 {data_m.get('fecha','')} · {data_m.get('sistema','')}")
                        st.markdown(data_m.get("contenido",""))
                        st.code(data_m.get("contenido",""), language=None)

# ══════════════════════════════════════════════════════════════════════════════
# ASISTENTE DE VENTAS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.seccion == "ventas":
    st.markdown("## 💼 Asistente de Ventas y Propuestas")
    st.caption("Genera propuestas comerciales personalizadas con el enfoque diferencial de JandrexT.")

    c1, c2 = st.columns(2)
    with c1:
        v_cliente    = st.text_input("Nombre del cliente / empresa")
        v_tipo       = st.selectbox("Tipo de cliente", list(TIPOS_PROYECTO.keys()))
        v_necesidad  = st.text_area("¿Qué necesita el cliente?", height=100,
            placeholder="Ej: Conjunto de 120 apartamentos que necesita renovar el sistema de control de acceso vehicular y mejorar las cámaras del parqueadero...")
    with c2:
        v_presupuesto = st.selectbox("Rango de presupuesto aproximado", [
            "No definido", "Menos de $1.000.000 COP",
            "$1.000.000 - $5.000.000 COP", "$5.000.000 - $15.000.000 COP",
            "$15.000.000 - $50.000.000 COP", "Más de $50.000.000 COP",
        ])
        v_urgencia = st.selectbox("Urgencia", ["Normal","Urgente","Proyecto futuro"])
        v_contacto = st.text_input("Contacto / cargo", placeholder="Ej: Carlos Gómez, Administrador")

    if st.button("💼 Generar propuesta comercial", type="primary", use_container_width=False):
        if v_necesidad.strip():
            with st.spinner("Generando propuesta comercial JandrexT..."):
                ctx = TIPOS_PROYECTO.get(v_tipo,"")
                prompt_venta = f"""
{CONTEXTO_JANDREXT}
{ctx}

Genera una propuesta comercial profesional, empática y convincente para:
Cliente: {v_cliente}
Contacto: {v_contacto}
Necesidad: {v_necesidad}
Presupuesto: {v_presupuesto}
Urgencia: {v_urgencia}
Fecha: {datetime.now().strftime('%d de %B de %Y')}

La propuesta debe incluir:
1. Saludo personalizado y empático
2. Comprensión del problema/necesidad del cliente
3. Solución propuesta (específica, no genérica) usando las líneas de servicio JandrexT
4. Equipos y materiales recomendados con justificación técnica
5. Beneficios concretos para el cliente
6. Enfoque diferencial JandrexT: integración completa hardware+software+operación
7. Garantías y soporte post-instalación
8. Plan de mantenimiento preventivo incluido
9. Próximos pasos claros
10. Cierre empático y profesional con datos de contacto

Tono: profesional, empático, cercano. Nunca genérico.
"""
                propuesta = juez_gemini(prompt_venta, 
                    [{"ia":"Gemini","respuesta": generar_documento("Propuesta Comercial", prompt_venta, v_cliente),"ok":True}])

            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown(f"### 💼 Propuesta Comercial — {v_cliente}")
            st.markdown(propuesta)
            st.code(propuesta, language=None)

            guardar_en_biblioteca(
                v_cliente or "Ventas",
                f"[Propuesta Comercial] {v_necesidad[:60]}",
                propuesta, ["Gemini"]
            )
        else:
            st.warning("⚠️ Describe la necesidad del cliente.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""<div class="footer-inst">
    <span>JandrexT</span> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: <span>Andrés Tapiero</span> &nbsp;·&nbsp;
    Plataforma Multi-IA v7.0 &nbsp;·&nbsp; 🔒 Uso Interno
</div>""", unsafe_allow_html=True)
