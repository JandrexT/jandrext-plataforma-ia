import streamlit as st
import os, time, json, uuid, hashlib, concurrent.futures
import requests as req
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPA_URL = os.getenv("SUPABASE_URL","")
SUPA_KEY = os.getenv("SUPABASE_ANON_KEY","")

def supa(tabla, metodo="GET", data=None, filtro=""):
    url = f"{SUPA_URL}/rest/v1/{tabla}{filtro}"
    h = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
         "Content-Type": "application/json", "Prefer": "return=representation"}
    try:
        if metodo == "GET":    r = req.get(url, headers=h, timeout=10)
        elif metodo == "POST": r = req.post(url, headers=h, json=data, timeout=10)
        elif metodo == "PATCH":r = req.patch(url, headers=h, json=data, timeout=10)
        elif metodo == "DELETE":r=req.delete(url, headers=h, timeout=10)
        return r.json() if r.text else []
    except: return []

def hash_pwd(pwd): return hashlib.md5(pwd.encode()).hexdigest()

def verificar_login(email, pwd):
    res = supa("usuarios", filtro=f"?email=eq.{email}&activo=eq.true")
    if res and isinstance(res, list) and res[0].get("password_hash") == hash_pwd(pwd):
        return res[0]
    return None

def tiene_modulo(usuario, modulo):
    if usuario.get("rol") == "admin": return True
    return modulo in (usuario.get("modulos") or [])

# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram(msg):
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN","")
        chat  = os.getenv("TELEGRAM_CHAT_ID_ADMIN","")
        if token and chat:
            req.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id":chat,"text":msg,"parse_mode":"HTML"}, timeout=8)
    except: pass

# ── IAs ───────────────────────────────────────────────────────────────────────
CONTEXTO = """Eres asistente experto de JandrexT Soluciones Integrales — empresa colombiana apasionada por el buen servicio.
Especializada en: automatización de accesos, videovigilancia CCTV, infraestructura eléctrica/redes, software, servicios tecnológicos e ingeniería.
Director: Andrés Tapiero | Lema: Apasionado por el buen servicio.
Comportamiento: empático, profesional, práctico. Incluye mantenimiento preventivo cuando aplique."""

def gemini(p, modelo="gemini-1.5-flash"):
    try:
        import google.generativeai as genai
        t = time.time()
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        r = genai.GenerativeModel(modelo).generate_content(CONTEXTO+"\n\nConsulta: "+p)
        return {"ia":"Gemini","icono":"🔵","respuesta":r.text.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Gemini","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def groq_ia(p, modelo="llama-3.3-70b-versatile"):
    try:
        from groq import Groq
        t = time.time()
        r = Groq(api_key=os.getenv("GROQ_API_KEY","")).chat.completions.create(
            model=modelo, messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":p}], max_tokens=1500)
        return {"ia":"Groq·LLaMA","icono":"🟠","respuesta":r.choices[0].message.content.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Groq·LLaMA","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def venice(p, modelo="llama-3.3-70b"):
    try:
        t = time.time()
        h = {"Authorization":f"Bearer {os.getenv('VENICE_API_KEY','')}","Content-Type":"application/json"}
        r = req.post("https://api.venice.ai/api/v1/chat/completions",
            json={"model":modelo,"messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],"max_tokens":1500},
            headers=h, timeout=30)
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return {"ia":"Venice","icono":"🟣","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Venice","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def juez(pregunta, respuestas, ctx=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        resumen = "\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in respuestas if r["ok"]])
        prompt = f"{CONTEXTO}\n{ctx}\nPregunta: \"{pregunta}\"\nRespuestas:\n{resumen}\nSintetiza la mejor respuesta. Empático, profesional. Sin encabezados."
        r = genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e:
        return f"❌ Error: {e}"

def generar_doc(tipo, contenido, proyecto=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        prompt = f"""{CONTEXTO}
Genera un {tipo} profesional para JandrexT Soluciones Integrales.
Lema: Apasionado por el buen servicio | Director: Andrés Tapiero | NIT: 80818905-3
{f'Proyecto: {proyecto}' if proyecto else ''}
Fecha: {datetime.now().strftime('%d de %B de %Y')}
Contenido: {contenido}
Incluir: membrete JandrexT, secciones claras, normas colombianas aplicables,
términos y condiciones estándar JandrexT, datos de pago:
- Banco AV Villas Cta Ahorros 065779337
- Banco Caja Social Cta Ahorros 24109787510
- Nequi/Daviplata 317 391 0621
- Correo: proyectos@jandrext.com"""
        r = genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e:
        return f"❌ Error: {e}"

# ── Configuración página ──────────────────────────────────────────────────────
st.set_page_config(page_title="JandrexT | Plataforma", page_icon="🧠",
    layout="wide", initial_sidebar_state="expanded")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.login-box{max-width:420px;margin:4rem auto;background:#0f0000;border:1px solid #cc0000;border-radius:16px;padding:2.5rem;}
.logo-j{color:#cc0000;font-size:3.5rem;font-weight:900;letter-spacing:3px;display:inline;}
.logo-mid{color:#fff;font-size:2.2rem;font-weight:900;letter-spacing:3px;display:inline;}
.logo-t{color:#cc0000;font-size:3.5rem;font-weight:900;letter-spacing:3px;display:inline;}
.logo-sub{color:#666;font-size:0.7rem;letter-spacing:5px;text-transform:uppercase;margin:0;}
.logo-lema{color:#cc4444;font-size:0.95rem;font-style:italic;margin:0.2rem 0;}
.header-inst{background:linear-gradient(135deg,#0a0000,#1a0000);border-radius:12px;
    padding:1.2rem 1.8rem;margin-bottom:1rem;border:1px solid #cc0000;
    display:flex;align-items:center;justify-content:space-between;}
.header-left{}
.header-user{color:#cc6666;font-size:0.8rem;text-align:right;}
.header-rol{color:#cc0000;font-size:0.7rem;letter-spacing:1px;text-transform:uppercase;}
.ia-card{background:#0f0000;border:1px solid #2a0000;border-radius:10px;padding:1rem;transition:border-color 0.2s;}
.ia-card:hover{border-color:#cc0000;}
.ia-card h4{margin:0 0 0.3rem 0;font-size:0.95rem;color:#f0f0f0;font-weight:600;}
.badge-ok{color:#4ade80;font-weight:600;font-size:0.82rem;}
.badge-err{color:#f87171;font-weight:600;font-size:0.82rem;}
.tiempo{color:#555;font-size:0.75rem;margin-left:5px;}
.juez-card{background:#0f0000;border:2px solid #cc0000;border-radius:12px;padding:1.5rem;color:#f0f0f0;line-height:1.75;}
.chat-user{background:#1a0000;border:1px solid #cc0000;border-radius:12px 12px 4px 12px;padding:0.8rem 1rem;margin:0.4rem 0;color:#f0f0f0;}
.chat-ia{background:#0a0a0a;border:1px solid #222;border-radius:12px 12px 12px 4px;padding:0.8rem 1rem;margin:0.4rem 0;color:#e0e0e0;}
.meta{color:#555;font-size:0.72rem;margin-bottom:0.2rem;}
.agenda-card{background:#0f0000;border-left:4px solid #cc0000;border-radius:0 8px 8px 0;padding:0.8rem 1rem;margin-bottom:0.4rem;}
.req-card{background:#0a0f00;border:1px solid #166534;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.4rem;}
.sidebar-brand{background:#0f0000;border:1px solid #cc0000;border-radius:10px;padding:0.8rem;text-align:center;margin-bottom:0.5rem;}
.sb-name{color:#fff;font-weight:900;font-size:0.95rem;margin:0;letter-spacing:2px;text-transform:uppercase;}
.sb-sub{color:#cc0000;font-size:0.6rem;margin:0;letter-spacing:2px;text-transform:uppercase;}
.sb-lema{color:#cc6666;font-size:0.78rem;font-style:italic;margin:0.2rem 0 0 0;}
.user-badge{background:#1a0000;border:1px solid #cc0000;border-radius:8px;padding:0.5rem 0.8rem;margin-bottom:0.5rem;text-align:center;}
.user-nombre{color:#ffcccc;font-size:0.82rem;font-weight:700;margin:0;}
.user-rol{color:#cc0000;font-size:0.7rem;margin:0;text-transform:uppercase;letter-spacing:1px;}
.footer-inst{background:#0a0000;border:1px solid #1a0000;border-radius:8px;padding:0.7rem;text-align:center;margin-top:1.5rem;color:#444;font-size:0.72rem;}
.footer-inst span{color:#cc0000;font-weight:700;}
.divider{border:none;border-top:1px solid #1a0000;margin:1rem 0;}
.sec-title{color:#cc0000;font-size:0.72rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin:0.8rem 0 0.4rem 0;}
.notif-alerta{background:#1a0a00;border:1px solid #cc6600;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.4rem;color:#ffcc88;}

/* ── RESPONSIVE MÓVIL ── */
@media (max-width: 768px) {
    .header-inst{flex-direction:column;gap:0.5rem;padding:1rem;}
    .header-user{text-align:left;}
    .stButton>button{min-height:52px;font-size:1rem;border-radius:12px;}
    .stTextInput>div>input{min-height:48px;font-size:1rem;border-radius:10px;}
    .stSelectbox>div>div{min-height:48px;font-size:1rem;}
    .stTextArea>div>textarea{font-size:1rem;}
    .stForm{padding:0.5rem;}
    h2{font-size:1.4rem;}
    h3{font-size:1.1rem;}
    .ia-card{padding:0.7rem;}
    .juez-card{padding:1rem;}
    .footer-inst{font-size:0.65rem;}
    div[data-testid="column"]{min-width:100%;}
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "usuario" not in st.session_state: st.session_state.usuario = None
if "seccion"  not in st.session_state: st.session_state.seccion  = "chat"
if "recordar" not in st.session_state: st.session_state.recordar = False

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.usuario:
    st.markdown("""
    <div class="login-box">
        <div style="text-align:center;margin-bottom:1.5rem;">
            <div><span class="logo-j">J</span><span class="logo-mid">ANDREX</span><span class="logo-t">T</span></div>
            <p class="logo-sub">Soluciones Integrales</p>
            <p class="logo-lema">Apasionado por el buen servicio</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.container():
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.markdown("### 🔐 Iniciar sesión")
            email   = st.text_input("Correo electrónico", placeholder="usuario@jandrext.com")
            pwd     = st.text_input("Contraseña", type="password")
            recordar = st.checkbox("Recordar en este dispositivo")
            if st.button("Ingresar", type="primary", use_container_width=True):
                if email and pwd:
                    with st.spinner("Verificando..."):
                        usuario = verificar_login(email.strip(), pwd.strip())
                    if usuario:
                        st.session_state.usuario = usuario
                        st.session_state.recordar = recordar
                        st.rerun()
                    else:
                        st.error("❌ Correo o contraseña incorrectos.")
                else:
                    st.warning("⚠️ Completa todos los campos.")
            st.caption("¿Olvidaste tu contraseña? Contacta al administrador: proyectos@jandrext.com")
    st.stop()

# ── Usuario autenticado ───────────────────────────────────────────────────────
u = st.session_state.usuario
rol = u.get("rol","")
nombre = u.get("nombre","")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""<div class="sidebar-brand">
        <p class="sb-name">Jandre<span style="color:#cc0000">x</span>T</p>
        <p class="sb-sub">Soluciones Integrales</p>
        <p class="sb-lema">Apasionado por el buen servicio</p>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""<div class="user-badge">
        <p class="user-nombre">👤 {nombre}</p>
        <p class="user-rol">{rol}</p>
    </div>""", unsafe_allow_html=True)

    st.markdown('<p class="sec-title">📌 Navegación</p>', unsafe_allow_html=True)

    SECCIONES = [
        ("💬","chat","Chats"),("📁","proyectos","Proyectos"),
        ("📅","agenda","Agenda"),("👥","asistencia","Asistencia"),
        ("📚","biblioteca","Biblioteca"),("📄","documentos","Documentos"),
        ("📖","manuales","Manuales"),("💼","ventas","Ventas"),
        ("🏢","clientes","Clientes"),("📊","liquidaciones","Liquidaciones"),
    ]
    if rol == "admin":
        SECCIONES += [("👑","usuarios","Usuarios"),("⚙️","config","Configuración")]
    if rol == "cliente":
        SECCIONES = [("📋","requerimientos","Mis Requerimientos"),("📖","mis_manuales","Mis Manuales")]

    for ico, key, label in SECCIONES:
        if tiene_modulo(u, key):
            activo = "▶ " if st.session_state.seccion == key else ""
            if st.button(f"{ico} {activo}{label}", key=f"nav_{key}", use_container_width=True):
                st.session_state.seccion = key
                st.rerun()

    st.markdown("---")
    if rol == "admin":
        st.markdown('<p class="sec-title">⚡ IAs</p>', unsafe_allow_html=True)
        usar_gemini = st.toggle("🔵 Gemini", value=True)
        usar_groq   = st.toggle("🟠 Groq",   value=True)
        usar_venice = st.toggle("🟣 Venice",  value=True)
        modelo_g = st.selectbox("Gemini", ["gemini-1.5-flash","gemini-1.5-pro"], label_visibility="collapsed")
    else:
        usar_gemini = usar_groq = usar_venice = True
        modelo_g = "gemini-1.5-flash"

    st.markdown("---")
    if st.button("🚪 Cerrar sesión", use_container_width=True):
        st.session_state.usuario = None
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="header-inst">
    <div class="header-left">
        <div><span style="color:#cc0000;font-size:1.6rem;font-weight:900;">J</span>
        <span style="color:#fff;font-size:1.2rem;font-weight:900;letter-spacing:2px;">ANDREX</span>
        <span style="color:#cc0000;font-size:1.6rem;font-weight:900;">T</span></div>
        <div style="color:#666;font-size:0.65rem;letter-spacing:4px;text-transform:uppercase;">Soluciones Integrales · Plataforma v9.0</div>
    </div>
    <div class="header-user">
        <div style="color:#ffcccc;font-weight:600;">{nombre}</div>
        <div class="header-rol">{rol}</div>
        <div style="color:#555;font-size:0.7rem;">{datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
    </div>
</div>""", unsafe_allow_html=True)

sec = st.session_state.seccion

# ── Panel de consulta IA ──────────────────────────────────────────────────────
def panel_ia(chat_id, nombre_ctx="General"):
    msgs = supa("mensajes_chat", filtro=f"?chat_id=eq.{chat_id}&order=creado_en.asc")
    if msgs and isinstance(msgs, list):
        for m in msgs:
            st.markdown(f'<div class="chat-user"><span class="meta">🧑 {m.get("creado_en","")[:16]}</span><br>{m.get("pregunta","")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="chat-ia"><span class="meta">🏛️ JandrexT IA</span><br>{m.get("sintesis","")}</div>', unsafe_allow_html=True)
        st.markdown('<hr class="divider">', unsafe_allow_html=True)

    vk = f"voz_{chat_id}"
    ik = f"inp_{chat_id}"
    if vk not in st.session_state: st.session_state[vk] = ""
    if ik not in st.session_state: st.session_state[ik] = ""

    try:
        from streamlit_mic_recorder import speech_to_text
        c1,c2 = st.columns([1,3])
        with c1:
            tv = speech_to_text(language="es", start_prompt="🎤 Hablar",
                stop_prompt="⏹️ Detener", just_once=True,
                use_container_width=True, key=f"mic_{chat_id}")
        with c2:
            st.caption("🎤 Hablar → di tu consulta → ⏹️ Detener")
        if tv:
            st.session_state[vk] = tv
            st.session_state[ik] = tv
            st.success(f"🎙️ *{tv}*")
    except: pass

    pregunta = st.text_area("✍️ Consulta", height=100, key=ik,
        placeholder="Escribe o usa el micrófono...")

    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        btn = st.button("🚀 Consultar IAs", use_container_width=True, type="primary", key=f"btn_{chat_id}")

    if btn and pregunta.strip():
        fns = []
        if usar_gemini: fns.append(lambda p: gemini(p, modelo_g))
        if usar_groq:   fns.append(lambda p: groq_ia(p))
        if usar_venice: fns.append(lambda p: venice(p))
        if not fns: st.warning("Activa al menos una IA."); return

        with st.spinner("Consultando IAs..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
                resultados = list(ex.map(lambda f: f(pregunta), fns))

        cols = st.columns(len(resultados))
        for i,res in enumerate(resultados):
            with cols[i]:
                cls = "badge-ok" if res["ok"] else "badge-err"
                st.markdown(f'<div class="ia-card"><h4>{res["icono"]} {res["ia"]}</h4><span class="{cls}">{"✓" if res["ok"] else "✗"}</span><span class="tiempo">⏱{res["tiempo"]}s</span></div>', unsafe_allow_html=True)
                if res["ok"]:
                    with st.expander("Ver"): st.write(res["respuesta"])

        ok = [r for r in resultados if r["ok"]]
        if ok:
            with st.spinner("Sintetizando..."):
                sintesis = juez(pregunta, ok)
            st.markdown(f'<div class="juez-card"><div style="color:#cc0000;font-size:0.7rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:0.8rem;">🏛️ SÍNTESIS · {nombre_ctx}</div>{sintesis}</div>', unsafe_allow_html=True)
            with st.expander("📋 Copiar"): st.code(sintesis, language=None)
            supa("mensajes_chat", "POST", {"chat_id":chat_id,"pregunta":pregunta,
                "sintesis":sintesis,"ias_usadas":[r["ia"] for r in ok]})
            st.session_state[ik] = ""
            st.session_state[vk] = ""
            st.rerun()
    elif btn: st.warning("⚠️ Escribe una consulta.")

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
# ══════════════════════════════════════════════════════════════════════════════
if sec == "chat" and tiene_modulo(u, "chat"):
    st.markdown("## 💬 Chats")
    col_l, col_c = st.columns([1,3])
    with col_l:
        st.markdown('<p class="sec-title">Mis chats</p>', unsafe_allow_html=True)
        if st.button("➕ Nuevo chat", use_container_width=True):
            nuevo = supa("chats","POST",{"titulo":"Nuevo chat","usuario_id":u["id"]})
            if nuevo and isinstance(nuevo,list):
                st.session_state["chat_activo"] = nuevo[0]["id"]
                st.rerun()
        chats = supa("chats", filtro=f"?usuario_id=eq.{u['id']}&order=creado_en.desc")
        if chats and isinstance(chats, list):
            for c in chats:
                if st.button(f"💬 {c.get('titulo','Chat')[:25]}", key=f"c_{c['id']}", use_container_width=True):
                    st.session_state["chat_activo"] = c["id"]
                    st.rerun()
    with col_c:
        cid = st.session_state.get("chat_activo")
        if cid:
            panel_ia(cid, "General")
        else:
            st.info("👈 Selecciona o crea un chat.")

# ══════════════════════════════════════════════════════════════════════════════
# PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "proyectos" and tiene_modulo(u, "proyectos"):
    st.markdown("## 📁 Proyectos")
    col_l, col_c = st.columns([1,3])
    with col_l:
        st.markdown('<p class="sec-title">Proyectos</p>', unsafe_allow_html=True)
        if rol in ["admin","vendedor"]:
            with st.expander("➕ Nuevo proyecto"):
                pn = st.text_input("Nombre", key="pn")
                pd = st.text_input("Cliente", key="pd")
                pt = st.selectbox("Tipo", ["copropiedad","empresa","natural","administracion"], key="pt")
                if st.button("Crear", key="btn_proy"):
                    if pn:
                        nuevo = supa("proyectos","POST",{"nombre":pn,"descripcion":pd,"tipo":pt,"creado_por":u["id"]})
                        if nuevo: st.success("✅ Proyecto creado"); st.rerun()
        proyectos = supa("proyectos", filtro="?order=creado_en.desc")
        if proyectos and isinstance(proyectos, list):
            for p in proyectos:
                if st.button(f"📁 {p['nombre'][:25]}", key=f"p_{p['id']}", use_container_width=True):
                    st.session_state["proy_activo"] = p["id"]
                    st.session_state["proy_nombre"] = p["nombre"]
                    st.rerun()
    with col_c:
        pid = st.session_state.get("proy_activo")
        pnombre = st.session_state.get("proy_nombre","Proyecto")
        if pid:
            st.markdown(f"### 📁 {pnombre}")
            if st.button("➕ Nuevo sub-chat", key="nuevo_sc"):
                nuevo = supa("chats","POST",{"titulo":f"Chat {pnombre}","proyecto_id":pid,"usuario_id":u["id"]})
                if nuevo and isinstance(nuevo,list):
                    st.session_state["sc_activo"] = nuevo[0]["id"]
                    st.rerun()
            sub = supa("chats", filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc")
            if sub and isinstance(sub,list):
                for s in sub:
                    if st.button(f"💬 {s.get('titulo','')[:22]}", key=f"sc_{s['id']}", use_container_width=True):
                        st.session_state["sc_activo"] = s["id"]
                        st.rerun()
            scid = st.session_state.get("sc_activo")
            if scid: panel_ia(scid, pnombre)
        else:
            st.info("👈 Selecciona un proyecto.")

# ══════════════════════════════════════════════════════════════════════════════
# AGENDA
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "agenda" and tiene_modulo(u, "agenda"):
    st.markdown("## 📅 Agenda y Pendientes")
    col_f, col_l = st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva tarea")
        a_t  = st.text_input("Tarea *")
        a_cl = st.text_input("Cliente / Sitio *")
        a_pr = st.selectbox("Prioridad", ["🔴 Urgente (36h)","🟡 Normal (60h)","🟢 Puede esperar (90h)"])
        a_fe = st.date_input("Fecha límite", min_value=datetime.today())
        a_as = st.multiselect("Asignados", ["Andrés Tapiero","Técnico 1","Técnico 2","Técnico 3","Vendedor","Subcontratista"])
        a_sa = st.text_input("Colaborador satélite")
        a_es = st.text_input("Escalamiento")
        a_ca = st.checkbox("¿Requiere visita en campo?")
        a_de = st.text_area("Descripción", height=70)
        a_ei = st.text_area("Estado inicial", height=60)
        a_re = st.text_area("Recomendaciones", height=60)
        a_le = st.text_area("Lección aprendida", height=50)
        a_se = st.checkbox("¿Requiere seguimiento?")
        a_fs = st.date_input("Fecha seguimiento") if a_se else None

        if st.button("💾 Guardar tarea", type="primary", use_container_width=True):
            if a_t and a_cl:
                horas = 36 if "Urgente" in a_pr else 60 if "Normal" in a_pr else 90
                data = {"tarea":a_t,"cliente":a_cl,"prioridad":a_pr,
                    "horas_limite":horas,"fecha_limite":str(datetime.now()+timedelta(hours=horas)),
                    "asignados":a_as,"satelite":a_sa,"escalamiento":a_es,"campo":a_ca,
                    "descripcion":a_de,"estado_inicial":a_ei,"recomendaciones":a_re,
                    "leccion":a_le,"seguimiento":a_se,
                    "fecha_seguimiento":str(a_fs) if a_fs else None,
                    "creado_por":u["id"]}
                res = supa("agenda","POST",data)
                if res:
                    asig = ", ".join(a_as) if a_as else "Sin asignar"
                    telegram(f"📅 <b>Nueva tarea</b>\n📋 {a_t}\n👤 {a_cl}\n👥 {asig}\n{a_pr}")
                    st.success("✅ Tarea guardada y notificada")
                    st.rerun()
            else: st.warning("⚠️ Completa los campos obligatorios (*)")

    with col_l:
        st.markdown("### 📋 Tareas")
        tareas = supa("agenda", filtro="?order=creado_en.desc")
        c1,c2,c3 = st.columns(3)
        if tareas and isinstance(tareas,list):
            c1.metric("Total", len(tareas))
            c2.metric("Pendientes", len([t for t in tareas if t.get("estado")=="pendiente"]))
            c3.metric("Urgentes", len([t for t in tareas if "Urgente" in t.get("prioridad","")]))
            for t in tareas:
                ico = "🔴" if "Urgente" in t.get("prioridad","") else "🟡" if "Normal" in t.get("prioridad","") else "🟢"
                with st.expander(f"{ico} {t['tarea']} · {t.get('cliente','')} · {t.get('estado','pendiente')}"):
                    st.markdown(f"**Prioridad:** {t.get('prioridad','')} | **Límite:** {t.get('fecha_limite','')[:10]}")
                    st.markdown(f"**Asignados:** {', '.join(t.get('asignados') or [])}")
                    if t.get("descripcion"): st.markdown(f"**Desc:** {t['descripcion']}")
                    if t.get("estado_inicial"): st.markdown(f"**Estado inicial:** {t['estado_inicial']}")
                    nuevo_estado = st.selectbox("Estado", ["pendiente","en_proceso","completado"],
                        index=["pendiente","en_proceso","completado"].index(t.get("estado","pendiente")),
                        key=f"est_{t['id']}")
                    ef = st.text_area("Estado final / Evidencia", key=f"ef_{t['id']}", value=t.get("estado_final",""), height=60)
                    if st.button("💾 Actualizar", key=f"upd_{t['id']}"):
                        supa("agenda","PATCH",{"estado":nuevo_estado,"estado_final":ef},f"?id=eq.{t['id']}")
                        if nuevo_estado == "completado":
                            telegram(f"✅ <b>Tarea completada</b>\n📋 {t['tarea']}\n👤 {t.get('cliente','')}\n📝 {ef[:100]}")
                        st.success("✅ Actualizado"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ASISTENCIA
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "asistencia" and tiene_modulo(u, "asistencia"):
    st.markdown("## 👥 Control de Asistencia")

    # ── Componente de geolocalización móvil ──────────────────────────────────
    geo_html = """
    <style>
    .geo-btn{background:#cc0000;color:#fff;border:none;border-radius:12px;padding:1rem 1.5rem;
        font-size:1.1rem;font-weight:700;width:100%;cursor:pointer;margin:0.3rem 0;
        display:flex;align-items:center;justify-content:center;gap:0.5rem;touch-action:manipulation;}
    .geo-btn:active{background:#990000;}
    .geo-salida{background:#1a1a1a;border:2px solid #cc0000;}
    .geo-status{background:#0a0a0a;border:1px solid #333;border-radius:10px;
        padding:0.8rem;margin:0.5rem 0;color:#ccc;font-size:0.85rem;min-height:60px;}
    .geo-coords{color:#4ade80;font-size:0.8rem;font-family:monospace;}
    #mapa{width:100%;height:220px;border-radius:10px;border:1px solid #cc0000;margin:0.5rem 0;}
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <div id="geo-status" class="geo-status">📍 Presiona un botón para registrar tu ubicación...</div>
    <div id="mapa"></div>
    <div id="geo-coords" class="geo-coords"></div>

    <input type="text" id="geo-lat" style="display:none"/>
    <input type="text" id="geo-lng" style="display:none"/>

    <script>
    var mapa = L.map('mapa').setView([4.711, -74.0721], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {attribution:'© OpenStreetMap'}).addTo(mapa);
    var marker = null;

    function obtenerUbicacion(tipo) {
        document.getElementById('geo-status').innerHTML = '⏳ Obteniendo ubicación GPS...';
        if (!navigator.geolocation) {
            document.getElementById('geo-status').innerHTML = '❌ Tu dispositivo no soporta geolocalización.';
            return;
        }
        navigator.geolocation.getCurrentPosition(function(pos) {
            var lat = pos.coords.latitude.toFixed(6);
            var lng = pos.coords.longitude.toFixed(6);
            var acc = Math.round(pos.coords.accuracy);
            document.getElementById('geo-lat').value = lat;
            document.getElementById('geo-lng').value = lng;
            document.getElementById('geo-coords').innerHTML = '📌 Lat: ' + lat + ' | Lng: ' + lng + ' | Precisión: ' + acc + 'm';
            var ico = tipo === 'entrada' ? '✅' : '🏁';
            document.getElementById('geo-status').innerHTML = ico + ' <b>Ubicación capturada</b><br>Lat: ' + lat + ' Lng: ' + lng + '<br>Precisión: ' + acc + 'm';
            if (marker) mapa.removeLayer(marker);
            marker = L.marker([lat, lng]).addTo(mapa)
                .bindPopup(ico + ' ' + tipo.toUpperCase() + '<br>' + new Date().toLocaleTimeString())
                .openPopup();
            mapa.setView([lat, lng], 15);
            // Enviar al padre
            window.parent.postMessage({type: 'geo', lat: lat, lng: lng, tipo: tipo}, '*');
        }, function(err) {
            document.getElementById('geo-status').innerHTML = '⚠️ Error: ' + err.message + '<br>Activa el GPS y permite el acceso.';
        }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
    }
    </script>

    <button class="geo-btn" onclick="obtenerUbicacion('entrada')">✅ Registrar ENTRADA con GPS</button>
    <button class="geo-btn geo-salida" onclick="obtenerUbicacion('salida')">🏁 Registrar SALIDA con GPS</button>
    """
    st.components.v1.html(geo_html, height=480, scrolling=False)

    st.markdown('<hr style="border-color:#1a0000;margin:1rem 0;">', unsafe_allow_html=True)

    # ── Registro manual con formulario móvil optimizado ───────────────────────
    st.markdown("### ✍️ Completar registro")
    with st.form("form_asistencia", clear_on_submit=True):
        m_col = st.text_input("👤 Colaborador", value=nombre)
        m_tip = st.selectbox("📋 Tipo", ["entrada","salida"])
        m_pro = st.text_input("📍 Proyecto / Cliente")
        m_tar = st.text_input("🔧 Tarea realizada")
        m_lat = st.text_input("🌐 Latitud (del mapa)", placeholder="Opcional — se llena con GPS")
        m_lng = st.text_input("🌐 Longitud (del mapa)", placeholder="Opcional — se llena con GPS")
        submitted = st.form_submit_button("💾 Guardar registro", use_container_width=True, type="primary")
        if submitted:
            ubicacion = f"{m_lat},{m_lng}" if m_lat and m_lng else ""
            data = {"colaborador_id":u["id"],"colaborador_nombre":m_col,
                "tipo":m_tip,"proyecto":m_pro,"tarea":m_tar,"ubicacion":ubicacion}
            supa("asistencia","POST",data)
            emoji = "✅" if m_tip=="entrada" else "🏁"
            geo_txt = f"\n📌 GPS: {ubicacion}" if ubicacion else ""
            telegram(f"{emoji} <b>{m_col}</b> registró {m_tip}\n📍 {m_pro}\n📋 {m_tar}{geo_txt}")
            st.success("✅ Registrado y notificado"); st.rerun()

    st.markdown('<hr style="border-color:#1a0000;margin:1rem 0;">', unsafe_allow_html=True)

    # ── Mapa admin con todos los técnicos ─────────────────────────────────────
    if rol == "admin":
        st.markdown("### 🗺️ Mapa de técnicos en campo")
        hoy = datetime.now().strftime("%Y-%m-%d")
        registros = supa("asistencia", filtro=f"?fecha=gte.{hoy}T00:00:00&order=fecha.desc")
        activos = [r for r in (registros or []) if r.get("ubicacion") and r["tipo"]=="entrada" and not r.get("salida")]

        if activos:
            markers_js = ""
            for r in activos:
                try:
                    lat, lng = r["ubicacion"].split(",")
                    markers_js += f"""L.marker([{lat},{lng}]).addTo(mapa_admin)
                        .bindPopup('<b>{r.get("colaborador_nombre","")}</b><br>📍 {r.get("proyecto","")}<br>📋 {r.get("tarea","")}<br>🕐 {r.get("fecha","")[:16]}').openPopup();"""
                except: pass

            mapa_admin_html = f"""
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <div id="mapa_admin" style="width:100%;height:350px;border-radius:10px;border:1px solid #cc0000;"></div>
            <script>
            var mapa_admin = L.map('mapa_admin').setView([4.711,-74.0721],11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(mapa_admin);
            {markers_js}
            </script>"""
            st.components.v1.html(mapa_admin_html, height=370)
            st.metric("Técnicos en campo ahora", len(activos))
            for r in activos:
                st.markdown(f"🟢 **{r.get('colaborador_nombre','')}** — {r.get('proyecto','')} — {r.get('fecha','')[:16]}")
        else:
            mapa_vacio = """
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <div id="mv" style="width:100%;height:300px;border-radius:10px;border:1px solid #333;"></div>
            <script>var mv=L.map('mv').setView([4.711,-74.0721],11);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(mv);</script>"""
            st.components.v1.html(mapa_vacio, height=320)
            st.info("No hay técnicos con GPS activo en este momento.")

        st.markdown("### 📊 Todos los registros de hoy")
        if registros and isinstance(registros, list):
            for r in registros:
                bg = "#0a1a0a" if r["tipo"]=="entrada" else "#1a0a0a"
                ico = "✅" if r["tipo"]=="entrada" else "🏁"
                geo = f" · 📌 GPS" if r.get("ubicacion") else ""
                st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.3rem;">
                    {ico} <b>{r.get('colaborador_nombre','')}</b> · {r.get('fecha','')[:16]}{geo}<br>
                    📍 {r.get('proyecto','')} · 📋 {r.get('tarea','')}
                </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CLIENTES
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "clientes" and tiene_modulo(u, "clientes"):
    st.markdown("## 🏢 Clientes")
    col_f, col_l = st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo cliente")
        c_n  = st.text_input("Nombre / Razón Social *")
        c_rs = st.text_input("NIT")
        c_di = st.text_input("Dirección")
        c_te = st.text_input("Teléfono")
        c_em = st.text_input("Email")
        c_ti = st.selectbox("Tipo", ["copropiedad","empresa","natural","administracion"])
        c_co = st.text_input("Contacto")
        c_ca = st.text_input("Cargo del contacto")
        if st.button("💾 Guardar cliente", type="primary", use_container_width=True):
            if c_n:
                supa("clientes","POST",{"nombre":c_n,"nit":c_rs,"direccion":c_di,
                    "telefono":c_te,"email":c_em,"tipo":c_ti,"contacto":c_co,"cargo_contacto":c_ca})
                st.success("✅ Cliente guardado"); st.rerun()
            else: st.warning("⚠️ El nombre es obligatorio")
    with col_l:
        st.markdown("### 📋 Clientes registrados")
        clientes = supa("clientes", filtro="?order=creado_en.desc")
        if clientes and isinstance(clientes,list):
            st.metric("Total clientes", len(clientes))
            for c in clientes:
                with st.expander(f"🏢 {c['nombre']} · {c.get('tipo','')}"):
                    st.markdown(f"**NIT:** {c.get('nit','')} | **Tel:** {c.get('telefono','')} | **Email:** {c.get('email','')}")
                    st.markdown(f"**Dirección:** {c.get('direccion','')}")
                    st.markdown(f"**Contacto:** {c.get('contacto','')} — {c.get('cargo_contacto','')}")

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "documentos" and tiene_modulo(u, "documentos"):
    st.markdown("## 📄 Generador de Documentos")
    tipo_doc = st.selectbox("Tipo de documento", [
        "cotizacion","orden_trabajo","orden_servicio",
        "contrato","acta_entrega","informe"])
    labels = {"cotizacion":"Cotización","orden_trabajo":"Orden de Trabajo",
              "orden_servicio":"Orden de Servicio","contrato":"Contrato de Servicio",
              "acta_entrega":"Acta de Entrega","informe":"Informe Técnico"}
    proyecto_doc = st.text_input("Proyecto / cliente")
    tipo_cliente = st.selectbox("Tipo de cliente", ["copropiedad","empresa","natural","administracion"])
    contenido = st.text_area("Describe el contenido del documento", height=150,
        placeholder="Equipos, actividades, valores, condiciones específicas...")
    valor = st.number_input("Valor total (COP)", min_value=0, step=50000)
    anticipo = st.number_input("Anticipo (COP)", min_value=0, step=50000)

    if st.button(f"📄 Generar {labels.get(tipo_doc,'Documento')}", type="primary"):
        if contenido.strip():
            with st.spinner("Generando documento institucional..."):
                num_res = supa("documentos","POST",{
                    "tipo":tipo_doc,"contenido":contenido,
                    "valor_total":valor,"anticipo":anticipo,
                    "saldo":valor-anticipo,"creado_por":u["id"]})
                contenido_full = f"Tipo de cliente: {tipo_cliente}\nValor total: ${valor:,.0f} COP\nAnticipo: ${anticipo:,.0f} COP\nSaldo: ${valor-anticipo:,.0f} COP\n\n{contenido}"
                documento = generar_doc(labels.get(tipo_doc,"Documento"), contenido_full, proyecto_doc)
            st.markdown(f"### 📄 {labels.get(tipo_doc,'Documento')}")
            if num_res and isinstance(num_res,list):
                st.caption(f"ID: {num_res[0].get('id','')[:8]}")
            st.markdown(documento)
            st.code(documento, language=None)
        else: st.warning("⚠️ Describe el contenido.")

# ══════════════════════════════════════════════════════════════════════════════
# MANUALES
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "manuales" and tiene_modulo(u, "manuales"):
    st.markdown("## 📖 Generador de Manuales")
    col_f, col_l = st.columns([2,1])
    with col_f:
        m_pro = st.text_input("Proyecto / cliente")
        m_sis = st.text_input("Sistema instalado", placeholder="Ej: DVR Hikvision DS-7208HGHI")
        m_tip = st.selectbox("Tipo de manual", ["Manual de Usuario","Manual Técnico",
            "Guía de Configuración y Contraseñas","Plan de Mantenimiento Preventivo",
            "Manual de Operación Diaria","Guía de Acceso Remoto"])
        m_det = st.text_area("Detalles específicos", height=130,
            placeholder="IP, contraseñas, configuración, equipos...")
        m_cli = st.selectbox("Tipo de destinatario", ["copropiedad","empresa","natural","administracion"])
        if st.button("📖 Generar manual", type="primary"):
            if m_sis and m_det:
                with st.spinner("Generando manual..."):
                    prompt = f"""Crea un {m_tip} completo para JandrexT Soluciones Integrales.
Proyecto: {m_pro} | Sistema: {m_sis} | Destinatario: {m_cli}
Detalles: {m_det} | Fecha: {datetime.now().strftime('%d de %B de %Y')}
Incluir: portada JandrexT, índice, descripción del sistema, instrucciones paso a paso,
contraseñas y accesos, solución de problemas, mantenimiento preventivo con frecuencias,
señales de alerta, contacto JandrexT - Andrés Tapiero 317 391 0621."""
                    manual = generar_doc(m_tip, prompt, m_pro)
                    supa("manuales","POST",{"titulo":f"{m_tip} — {m_sis}","tipo":m_tip,
                        "sistema":m_sis,"contenido":manual,"creado_por":u["id"]})
                st.markdown(f"### 📖 {m_tip}")
                st.markdown(manual)
                st.code(manual, language=None)
                st.success("✅ Manual guardado.")
            else: st.warning("⚠️ Completa sistema y detalles.")
    with col_l:
        st.markdown("### 📚 Guardados")
        mans = supa("manuales", filtro=f"?creado_por=eq.{u['id']}&order=creado_en.desc")
        if mans and isinstance(mans,list):
            for m in mans:
                with st.expander(f"📖 {m.get('tipo','')}"):
                    st.caption(m.get("sistema",""))
                    st.write(m.get("contenido",""))

# ══════════════════════════════════════════════════════════════════════════════
# VENTAS
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "ventas" and tiene_modulo(u, "ventas"):
    st.markdown("## 💼 Asistente de Ventas")
    c1,c2 = st.columns(2)
    with c1:
        v_cl = st.text_input("Cliente / empresa")
        v_ti = st.selectbox("Tipo", ["copropiedad","empresa","natural","administracion"])
        v_ne = st.text_area("¿Qué necesita el cliente?", height=100)
    with c2:
        v_pr = st.selectbox("Presupuesto", ["No definido","< $1M","$1M-$5M","$5M-$15M","$15M-$50M","> $50M"])
        v_ur = st.selectbox("Urgencia", ["Normal","Urgente","Proyecto futuro"])
        v_co = st.text_input("Contacto / cargo")
    if st.button("💼 Generar propuesta", type="primary"):
        if v_ne:
            with st.spinner("Generando propuesta comercial..."):
                prompt = f"""Cliente: {v_cl} | Tipo: {v_ti} | Contacto: {v_co}
Necesidad: {v_ne} | Presupuesto: {v_pr} | Urgencia: {v_ur}
Genera propuesta comercial empática y profesional con: saludo personalizado,
comprensión del problema, solución específica JandrexT, equipos recomendados,
beneficios concretos, garantías, mantenimiento preventivo, próximos pasos y cierre."""
                propuesta = generar_doc("Propuesta Comercial", prompt, v_cl)
            st.markdown(f"### 💼 Propuesta — {v_cl}")
            st.markdown(propuesta)
            st.code(propuesta, language=None)
        else: st.warning("⚠️ Describe la necesidad.")

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "liquidaciones" and tiene_modulo(u, "liquidaciones"):
    st.markdown("## 📊 Liquidaciones de Colaboradores")
    usuarios_list = supa("usuarios", filtro="?rol=in.(tecnico,vendedor)&activo=eq.true")
    nombres_list = [x["nombre"] for x in (usuarios_list or [])] if usuarios_list else []

    col_f, col_l = st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva liquidación")
        l_col = st.selectbox("Colaborador", nombres_list if nombres_list else ["Sin colaboradores"])
        l_ini = st.date_input("Período inicio")
        l_fin = st.date_input("Período fin")
        l_dia = st.number_input("Días trabajados", min_value=0, max_value=31)
        l_sal = st.number_input("Salario base (COP)", min_value=0, step=50000)
        l_tip = st.selectbox("Tipo salario", ["diario","proyecto"])
        st.markdown("**Deducciones:**")
        d_pre = st.number_input("Préstamo/Anticipo", min_value=0, step=10000)
        d_otr = st.number_input("Otras deducciones", min_value=0, step=10000)
        total_bruto = l_sal * l_dia if l_tip == "diario" else l_sal
        total_dedu  = d_pre + d_otr
        total_neto  = total_bruto - total_dedu
        st.markdown(f"**Total bruto:** ${total_bruto:,.0f} COP")
        st.markdown(f"**Deducciones:** ${total_dedu:,.0f} COP")
        st.markdown(f"**Total neto: ${total_neto:,.0f} COP**")

        if st.button("💾 Generar liquidación", type="primary", use_container_width=True):
            col_data = next((x for x in (usuarios_list or []) if x["nombre"]==l_col), None)
            if col_data:
                data = {"colaborador_id":col_data["id"],"periodo_inicio":str(l_ini),
                    "periodo_fin":str(l_fin),"dias_trabajados":l_dia,
                    "salario_base":l_sal,"tipo_salario":l_tip,
                    "deducciones":[{"concepto":"Préstamo","valor":d_pre},{"concepto":"Otras","valor":d_otr}],
                    "total":total_neto}
                res = supa("liquidaciones","POST",data)
                msg = f"""💰 <b>Liquidación JandrexT</b>
👤 {l_col}
📅 {l_ini} al {l_fin}
📆 Días trabajados: {l_dia}
💵 Salario base: ${l_sal:,.0f}
➖ Deducciones: ${total_dedu:,.0f}
✅ <b>Total neto: ${total_neto:,.0f} COP</b>
📧 proyectos@jandrext.com"""
                telegram(msg)
                st.success(f"✅ Liquidación generada y enviada por Telegram")
                st.rerun()

    with col_l:
        st.markdown("### 📋 Liquidaciones")
        liqs = supa("liquidaciones", filtro="?order=creado_en.desc")
        if liqs and isinstance(liqs,list):
            for liq in liqs:
                col_nombre = next((x["nombre"] for x in (usuarios_list or []) if x["id"]==liq.get("colaborador_id")), "Desconocido")
                with st.expander(f"💰 {col_nombre} · {liq.get('periodo_inicio','')} → {liq.get('periodo_fin','')}"):
                    st.markdown(f"**Días:** {liq.get('dias_trabajados',0)} | **Total:** ${liq.get('total',0):,.0f} COP")
                    st.markdown(f"**Estado:** {liq.get('estado','pendiente')}")

# ══════════════════════════════════════════════════════════════════════════════
# REQUERIMIENTOS (CLIENTES)
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "requerimientos":
    st.markdown("## 📋 Requerimientos")
    col_f, col_l = st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo requerimiento")
        r_ti = st.text_input("Título del requerimiento *")
        r_de = st.text_area("Descripción detallada", height=100)
        r_pr = st.selectbox("Prioridad", ["normal","urgente","puede_esperar"])
        if st.button("📤 Enviar requerimiento", type="primary", use_container_width=True):
            if r_ti:
                supa("requerimientos","POST",{"titulo":r_ti,"descripcion":r_de,"prioridad":r_pr})
                telegram(f"🔔 <b>Nuevo requerimiento de cliente</b>\n📋 {r_ti}\n📝 {r_de[:100]}\n⚡ {r_pr}")
                st.success("✅ Requerimiento enviado. JandrexT fue notificado.")
                st.rerun()
            else: st.warning("⚠️ El título es obligatorio")
    with col_l:
        st.markdown("### 📋 Mis requerimientos")
        reqs = supa("requerimientos", filtro="?order=creado_en.desc")
        if reqs and isinstance(reqs,list):
            for r in reqs:
                est_color = "#166534" if r["estado"]=="resuelto" else "#1a0000"
                with st.expander(f"📌 {r['titulo']} · {r['estado']}"):
                    st.markdown(f"**Descripción:** {r.get('descripcion','')}")
                    st.markdown(f"**Prioridad:** {r.get('prioridad','')} | **Fecha:** {r.get('creado_en','')[:10]}")

# ══════════════════════════════════════════════════════════════════════════════
# USUARIOS (SOLO ADMIN)
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "usuarios" and rol == "admin":
    st.markdown("## 👑 Gestión de Usuarios")
    col_f, col_l = st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo usuario")
        u_n  = st.text_input("Nombre completo *")
        u_e  = st.text_input("Email *")
        u_p  = st.text_input("Contraseña temporal *", type="password")
        u_r  = st.selectbox("Rol", ["tecnico","vendedor","cliente","admin"])
        u_t  = st.text_input("Teléfono")
        u_m  = st.multiselect("Módulos visibles", ["chat","proyectos","agenda","asistencia",
            "biblioteca","documentos","manuales","ventas","clientes","liquidaciones"])
        if st.button("💾 Crear usuario", type="primary", use_container_width=True):
            if u_n and u_e and u_p:
                res = supa("usuarios","POST",{"nombre":u_n,"email":u_e,
                    "password_hash":hash_pwd(u_p),"rol":u_r,"telefono":u_t,"modulos":u_m})
                if res:
                    telegram(f"👤 <b>Nuevo usuario creado</b>\n{u_n} ({u_r})\n📧 {u_e}\n🔑 Contraseña temporal asignada")
                    st.success(f"✅ Usuario {u_n} creado")
                    st.rerun()
            else: st.warning("⚠️ Completa nombre, email y contraseña")

    with col_l:
        st.markdown("### 📋 Usuarios registrados")
        todos = supa("usuarios", filtro="?order=creado_en.desc")
        if todos and isinstance(todos,list):
            st.metric("Total usuarios", len(todos))
            for usr in todos:
                with st.expander(f"👤 {usr['nombre']} · {usr['rol']} · {'✅ Activo' if usr.get('activo') else '❌ Inactivo'}"):
                    st.markdown(f"**Email:** {usr['email']} | **Tel:** {usr.get('telefono','')}")
                    st.markdown(f"**Módulos:** {', '.join(usr.get('modulos') or [])}")
                    nueva_pwd = st.text_input("Nueva contraseña", type="password", key=f"pwd_{usr['id']}")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("🔑 Cambiar pwd", key=f"cp_{usr['id']}"):
                            if nueva_pwd:
                                supa("usuarios","PATCH",{"password_hash":hash_pwd(nueva_pwd)},f"?id=eq.{usr['id']}")
                                st.success("✅ Contraseña actualizada")
                    with col_b:
                        estado_btn = "❌ Desactivar" if usr.get("activo") else "✅ Activar"
                        if st.button(estado_btn, key=f"act_{usr['id']}"):
                            supa("usuarios","PATCH",{"activo":not usr.get("activo")},f"?id=eq.{usr['id']}")
                            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA
# ══════════════════════════════════════════════════════════════════════════════
elif sec == "biblioteca" and tiene_modulo(u, "biblioteca"):
    st.markdown("## 📚 Biblioteca")
    msgs = supa("mensajes_chat", filtro="?order=creado_en.desc")
    if msgs and isinstance(msgs,list):
        buscar = st.text_input("🔍 Buscar")
        filtrados = [m for m in msgs if not buscar or buscar.lower() in m.get("pregunta","").lower() or buscar.lower() in m.get("sintesis","").lower()]
        st.metric("Total consultas", len(filtrados))
        for m in filtrados:
            with st.expander(f"📌 {m.get('pregunta','')[:60]}... | 📅 {m.get('creado_en','')[:10]}"):
                st.markdown(f"**IAs:** {' · '.join(m.get('ias_usadas') or [])}")
                st.markdown(m.get("sintesis",""))
                st.code(m.get("sintesis",""), language=None)
    else: st.info("La biblioteca está vacía. Realiza consultas para que aparezcan aquí.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""<div class="footer-inst">
    <span>JandrexT</span> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: <span>Andrés Tapiero</span> &nbsp;·&nbsp;
    Plataforma v9.0 &nbsp;·&nbsp; 🔒 Sistema Interno<br>
    <span style="font-style:italic;color:#cc4444;">Apasionado por el buen servicio</span>
</div>""", unsafe_allow_html=True)
