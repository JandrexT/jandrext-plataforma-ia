import streamlit as st
import os, time, json, uuid, hashlib, base64, concurrent.futures
import requests as req
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Fuentes institucionales ───────────────────────────────────────────────────
def get_font_b64(fname):
    p = Path(fname)
    if p.exists():
        ext = "truetype" if fname.endswith(".ttf") else "opentype"
        b64 = base64.b64encode(p.read_bytes()).decode()
        return f"@font-face{{font-family:'{p.stem}';src:url(data:font/{ext};base64,{b64});}}\n"
    return ""

FONTS_CSS = (get_font_b64("Disclaimer-Plain.otf") +
             get_font_b64("Disclaimer-Classic.otf") +
             get_font_b64("JennaSue.ttf"))

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPA_URL = os.getenv("SUPABASE_URL","")
SUPA_KEY = os.getenv("SUPABASE_ANON_KEY","")

def supa(tabla, metodo="GET", data=None, filtro=""):
    url = f"{SUPA_URL}/rest/v1/{tabla}{filtro}"
    h = {"apikey":SUPA_KEY,"Authorization":f"Bearer {SUPA_KEY}",
         "Content-Type":"application/json","Prefer":"return=representation"}
    try:
        if metodo=="GET":     r=req.get(url,headers=h,timeout=10)
        elif metodo=="POST":  r=req.post(url,headers=h,json=data,timeout=10)
        elif metodo=="PATCH": r=req.patch(url,headers=h,json=data,timeout=10)
        elif metodo=="DELETE":r=req.delete(url,headers=h,timeout=10)
        return r.json() if r.text else []
    except: return []

def hash_pwd(pwd):
    try:
        import bcrypt
        return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
    except:
        return hashlib.sha256(pwd.encode()).hexdigest()

def verify_pwd(pwd, hashed):
    try:
        import bcrypt
        if hashed.startswith("$2"):
            return bcrypt.checkpw(pwd.encode(), hashed.encode())
    except: pass
    return (hashlib.md5(pwd.encode()).hexdigest() == hashed or
            hashlib.sha256(pwd.encode()).hexdigest() == hashed)

def verificar_login(email, pwd):
    # Verificar bloqueo
    bloqueo = supa("intentos_login", filtro=f"?email=eq.{email}")
    if bloqueo and isinstance(bloqueo, list) and bloqueo:
        b = bloqueo[0]
        if b.get("bloqueado_hasta"):
            try:
                hasta = datetime.fromisoformat(b["bloqueado_hasta"].replace("Z",""))
                if datetime.utcnow() < hasta:
                    minutos = int((hasta - datetime.utcnow()).seconds / 60) + 1
                    return None, f"🔒 Cuenta bloqueada. Intenta en {minutos} minutos."
            except: pass

    res = supa("usuarios", filtro=f"?email=eq.{email}&activo=eq.true")
    if res and isinstance(res,list) and res and verify_pwd(pwd, res[0].get("password_hash","")):
        # Limpiar intentos
        supa("intentos_login","DELETE",filtro=f"?email=eq.{email}")
        return res[0], None

    # Registrar intento fallido
    if bloqueo and isinstance(bloqueo,list) and bloqueo:
        intentos = bloqueo[0].get("intentos",0) + 1
        data = {"intentos": intentos}
        if intentos >= 5:
            data["bloqueado_hasta"] = (datetime.utcnow()+timedelta(minutes=30)).isoformat()
        supa("intentos_login","PATCH",data,f"?email=eq.{email}")
    else:
        supa("intentos_login","POST",{"email":email,"intentos":1})
    return None, "❌ Correo o contraseña incorrectos."

def tiene_modulo(u, mod):
    if u.get("rol") == "admin": return True
    return mod in (u.get("modulos") or [])

def puede_borrar(u, creado_por_id=None):
    if u.get("rol") == "admin": return True
    return False

# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram(msg):
    try:
        token=os.getenv("TELEGRAM_BOT_TOKEN","")
        chat=os.getenv("TELEGRAM_CHAT_ID_ADMIN","")
        if token and chat:
            req.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id":chat,"text":msg,"parse_mode":"HTML"},timeout=8)
    except: pass

# ── IAs ───────────────────────────────────────────────────────────────────────
CONTEXTO = """Eres asistente experto de JandrexT Soluciones Integrales — empresa colombiana apasionados por el buen servicio.
Servicios: automatización de accesos, videovigilancia CCTV, control de acceso y biometría,
redes y comunicaciones, sistemas eléctricos, cerca eléctrica, soporte tecnológico, desarrollo de software.
Director: Andrés Tapiero | Lema: Apasionados por el buen servicio
Comportamiento: empático, profesional, práctico. Incluye mantenimiento preventivo cuando aplique."""

LINEAS_SERVICIO = [
    "Automatización de accesos","Videovigilancia CCTV",
    "Control de acceso y biometría","Redes y comunicaciones",
    "Sistemas eléctricos","Cerca eléctrica",
    "Soporte tecnológico","Desarrollo de software","Consultoría y diagnóstico"
]

CHECKLISTS = {
    "Videovigilancia CCTV": [
        "Verificar estado de cámaras existentes",
        "Revisar señal de video en DVR/NVR",
        "Verificar grabación activa",
        "Revisar disco duro (espacio y estado)",
        "Verificar acceso remoto (app/web)",
        "Limpiar lentes de cámaras",
        "Revisar cableado y conexiones",
        "Verificar fuentes de alimentación",
        "Ajustar ángulos de visión si aplica",
        "Documentar estado final con fotos",
    ],
    "Automatización de accesos": [
        "Verificar funcionamiento del motor",
        "Revisar finales de carrera",
        "Lubricar partes mecánicas",
        "Revisar tarjeta controladora",
        "Verificar fotoceldas de seguridad",
        "Revisar botón de paro de emergencia",
        "Verificar luz intermitente de advertencia",
        "Probar control remoto y/o app",
        "Revisar batería de respaldo",
        "Documentar estado final con fotos",
    ],
    "Control de acceso y biometría": [
        "Verificar lectura de tarjetas/biometría",
        "Revisar comunicación TCP/IP",
        "Verificar base de datos de usuarios",
        "Revisar permisos por zonas",
        "Verificar registro de eventos",
        "Revisar cableado RS485",
        "Probar apertura/cierre de puerta",
        "Verificar sincronización de horarios",
        "Revisar firmware",
        "Documentar estado final con fotos",
    ],
    "Cerca eléctrica": [
        "Revisar tensión del sistema",
        "Verificar sistema de puesta a tierra",
        "Revisar hilos de cerca (cortes/tensión)",
        "Verificar energizador",
        "Probar supervisión de corte de línea",
        "Revisar señalización normativa",
        "Verificar batería de respaldo",
        "Revisar teclado/panel de control",
        "Documentar estado final con fotos",
    ],
}

def gemini_ia(p, modelo="gemini-1.5-flash"):
    try:
        import google.generativeai as genai
        t=time.time()
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        r=genai.GenerativeModel(modelo).generate_content(CONTEXTO+"\n\nConsulta: "+p)
        return {"ia":"Gemini","icono":"🔵","respuesta":r.text.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Gemini","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def groq_ia(p, modelo="llama-3.3-70b-versatile"):
    try:
        from groq import Groq
        t=time.time()
        r=Groq(api_key=os.getenv("GROQ_API_KEY","")).chat.completions.create(
            model=modelo,messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],max_tokens=1500)
        return {"ia":"Groq·LLaMA","icono":"🟠","respuesta":r.choices[0].message.content.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Groq·LLaMA","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def venice_ia(p, modelo="llama-3.3-70b"):
    try:
        t=time.time()
        h={"Authorization":f"Bearer {os.getenv('VENICE_API_KEY','')}","Content-Type":"application/json"}
        r=req.post("https://api.venice.ai/api/v1/chat/completions",
            json={"model":modelo,"messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],"max_tokens":1500},
            headers=h,timeout=30)
        txt=r.json()["choices"][0]["message"]["content"].strip()
        return {"ia":"Venice","icono":"🟣","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e:
        return {"ia":"Venice","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def juez_ia(pregunta, respuestas, ctx=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        resumen="\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in respuestas if r["ok"]])
        prompt=f"{CONTEXTO}\n{ctx}\nPregunta: \"{pregunta}\"\nRespuestas:\n{resumen}\nSintetiza la mejor respuesta. Empático, profesional. Sin encabezados."
        r=genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e: return f"❌ Error: {e}"

def generar_doc_ia(tipo, contenido, proyecto=""):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        prompt=f"""{CONTEXTO}
Genera un {tipo} profesional para JandrexT Soluciones Integrales.
Lema: Apasionados por el buen servicio | Director: Andrés Tapiero | NIT: 80818905-3
{f'Proyecto: {proyecto}' if proyecto else ''}
Fecha: {datetime.now().strftime('%d de %B de %Y')}
Contenido: {contenido}
Incluir: membrete JandrexT con fuente institucional, secciones claras, normas colombianas aplicables,
términos y condiciones estándar JandrexT, datos de pago:
- Banco AV Villas Cta Ahorros 065779337
- Banco Caja Social Cta Ahorros 24109787510
- Nequi/Daviplata 317 391 0621 | proyectos@jandrext.com"""
        r=genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e: return f"❌ Error: {e}"

def generar_informe_ia(descripcion_voz, fotos_descripciones, proyecto, tipo_servicio):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        prompt=f"""{CONTEXTO}
Genera un pre-informe técnico estructurado basado en el reporte del especialista en campo.

Proyecto: {proyecto}
Tipo de servicio: {tipo_servicio}
Descripción del especialista: {descripcion_voz}
Evidencias fotográficas: {fotos_descripciones}

El informe debe incluir:
1. Resumen ejecutivo del servicio realizado
2. Estado encontrado (antes)
3. Trabajos realizados (durante)
4. Estado final (después)
5. Materiales utilizados
6. Pendientes o recomendaciones
7. Plan de mantenimiento preventivo sugerido
8. Observaciones adicionales

Tono profesional y empático. Usar terminología técnica apropiada."""
        r=genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt)
        return r.text.strip()
    except Exception as e: return f"❌ Error: {e}"

# ── Config página ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="JandrexT | Plataforma",page_icon="🧠",
    layout="wide",initial_sidebar_state="expanded")

# ── CSS con fuentes institucionales ──────────────────────────────────────────
hora_actual = datetime.now().hour
saludo = "Buenos días" if hora_actual < 12 else "Buenas tardes" if hora_actual < 18 else "Buenas noches"

st.markdown(f"""<style>
{FONTS_CSS}
html,body,[class*="css"]{{font-family:'Disclaimer-Plain','Inter',sans-serif;}}

.login-box{{max-width:440px;margin:3rem auto;background:#0f0000;
    border:1px solid #cc0000;border-radius:16px;padding:2.5rem;}}
.logo-login{{text-align:center;margin-bottom:1.5rem;}}
.logo-j{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-size:4rem;font-weight:900;letter-spacing:3px;}}
.logo-mid{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-size:2.5rem;font-weight:900;letter-spacing:3px;}}
.logo-t{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-size:4rem;font-weight:900;letter-spacing:3px;}}
.logo-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#666;font-size:0.72rem;letter-spacing:5px;text-transform:uppercase;margin:0;}}
.logo-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:1.1rem;margin:0.3rem 0;}}

.header-inst{{background:linear-gradient(135deg,#0a0000,#1a0000);border-radius:12px;
    padding:1.2rem 1.8rem;margin-bottom:1rem;border:1px solid #cc0000;
    display:flex;align-items:center;justify-content:space-between;}}
.h-brand{{}}
.h-brand-name{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-size:1.8rem;font-weight:900;letter-spacing:3px;margin:0;}}
.h-brand-acc{{color:#cc0000;}}
.h-brand-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:0.95rem;margin:0;}}
.h-brand-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#555;font-size:0.62rem;letter-spacing:4px;text-transform:uppercase;margin:0;}}
.h-user{{text-align:right;}}
.h-saludo{{color:#ffcccc;font-size:0.85rem;font-family:'JennaSue',sans-serif;}}
.h-nombre{{color:#fff;font-weight:700;font-size:0.9rem;}}
.h-rol{{color:#cc0000;font-size:0.65rem;letter-spacing:1px;text-transform:uppercase;}}
.h-fecha{{color:#555;font-size:0.68rem;}}

.sidebar-brand{{background:#0f0000;border:1px solid #cc0000;border-radius:10px;padding:0.9rem;text-align:center;margin-bottom:0.5rem;}}
.sb-name{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-weight:900;font-size:1rem;margin:0;letter-spacing:2px;}}
.sb-acc{{color:#cc0000;}}
.sb-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#cc0000;font-size:0.6rem;margin:0;letter-spacing:2px;text-transform:uppercase;}}
.sb-lema{{font-family:'JennaSue',sans-serif;color:#cc6666;font-size:0.82rem;margin:0.2rem 0 0 0;}}
.user-badge{{background:#1a0000;border:1px solid #cc0000;border-radius:8px;padding:0.5rem 0.8rem;margin-bottom:0.5rem;text-align:center;}}
.ub-nombre{{color:#ffcccc;font-size:0.82rem;font-weight:700;margin:0;}}
.ub-rol{{color:#cc0000;font-size:0.68rem;margin:0;text-transform:uppercase;letter-spacing:1px;}}

.ia-card{{background:#0f0000;border:1px solid #2a0000;border-radius:10px;padding:1rem;transition:border-color 0.2s;}}
.ia-card:hover{{border-color:#cc0000;}}
.ia-card h4{{margin:0 0 0.3rem;font-size:0.95rem;color:#f0f0f0;font-weight:600;}}
.badge-ok{{color:#4ade80;font-weight:600;font-size:0.82rem;}}
.badge-err{{color:#f87171;font-weight:600;font-size:0.82rem;}}
.tiempo{{color:#555;font-size:0.75rem;margin-left:5px;}}
.juez-card{{background:#0f0000;border:2px solid #cc0000;border-radius:12px;padding:1.5rem;color:#f0f0f0;line-height:1.75;}}
.juez-titulo{{font-family:'Disclaimer-Plain',sans-serif;color:#cc0000;font-size:0.7rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;}}
.chat-u{{background:#1a0000;border:1px solid #cc0000;border-radius:12px 12px 4px 12px;padding:0.8rem 1rem;margin:0.4rem 0;color:#f0f0f0;}}
.chat-ia{{background:#0a0a0a;border:1px solid #222;border-radius:12px 12px 12px 4px;padding:0.8rem 1rem;margin:0.4rem 0;color:#e0e0e0;}}
.meta{{color:#555;font-size:0.72rem;margin-bottom:0.2rem;}}
.ayuda-tip{{background:#0a0f00;border-left:3px solid #cc0000;border-radius:0 8px 8px 0;padding:0.6rem 1rem;color:#aaa;font-size:0.8rem;margin:0.5rem 0;}}
.footer-inst{{background:#0a0000;border:1px solid #1a0000;border-radius:8px;padding:0.8rem;text-align:center;margin-top:1.5rem;color:#444;font-size:0.72rem;}}
.footer-acc{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-weight:700;}}
.footer-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:0.9rem;}}
.divider{{border:none;border-top:1px solid #1a0000;margin:1rem 0;}}
.sec-title{{font-family:'Disclaimer-Plain',sans-serif;color:#cc0000;font-size:0.72rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin:0.8rem 0 0.4rem 0;}}
.checklist-item{{background:#0a0f00;border:1px solid #1a2000;border-radius:6px;padding:0.4rem 0.8rem;margin:0.2rem 0;}}
.informe-box{{background:#0a0f0a;border:1px solid #166534;border-radius:10px;padding:1.2rem;color:#e0f0e0;}}
.garantia-ok{{color:#4ade80;font-size:0.8rem;}}
.garantia-vence{{color:#f87171;font-size:0.8rem;}}

@media(max-width:768px){{
    .header-inst{{flex-direction:column;gap:0.5rem;padding:1rem;}}
    .h-user{{text-align:left;}}
    .stButton>button{{min-height:52px;font-size:1rem;border-radius:12px;}}
    .stTextInput>div>input{{min-height:48px;font-size:1rem;}}
    .stSelectbox>div>div{{min-height:48px;}}
    h2{{font-size:1.4rem;}} h3{{font-size:1.1rem;}}
}}
</style>""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k,v in [("usuario",None),("seccion","chat"),("chat_activo",None),
            ("proy_activo",None),("proy_nombre",""),("sc_activo",None)]:
    if k not in st.session_state: st.session_state[k]=v

# ── Roles en español ──────────────────────────────────────────────────────────
ROL_LABEL = {"admin":"Administrador","tecnico":"Especialista",
             "vendedor":"Asesor Comercial","cliente":"Aliado"}

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.usuario:
    col1,col2,col3 = st.columns([1,2,1])
    with col2:
        st.markdown("""<div class="login-box">
        <div class="logo-login">
            <div><span class="logo-j">J</span><span class="logo-mid">ANDREX</span><span class="logo-t">T</span></div>
            <p class="logo-sub">Soluciones Integrales</p>
            <p class="logo-lema">Apasionados por el buen servicio</p>
        </div></div>""", unsafe_allow_html=True)
        st.markdown("### 🔐 Iniciar sesión")
        email    = st.text_input("Correo electrónico", placeholder="usuario@jandrext.com")
        pwd      = st.text_input("Contraseña", type="password")
        recordar = st.checkbox("Recordar en este dispositivo")
        if st.button("Ingresar", type="primary", use_container_width=True):
            if email and pwd:
                with st.spinner("Verificando..."):
                    usuario, error = verificar_login(email.strip(), pwd.strip())
                if usuario:
                    st.session_state.usuario = usuario
                    st.rerun()
                else:
                    st.error(error)
            else:
                st.warning("⚠️ Completa todos los campos.")
        st.caption("¿Olvidaste tu contraseña? Contacta: proyectos@jandrext.com | 317 391 0621")
    st.stop()

# ── Usuario autenticado ───────────────────────────────────────────────────────
u     = st.session_state.usuario
rol   = u.get("rol","")
nombre= u.get("nombre","")
rol_label = ROL_LABEL.get(rol, rol)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""<div class="sidebar-brand">
        <p class="sb-name">Jandre<span class="sb-acc">x</span>T</p>
        <p class="sb-sub">Soluciones Integrales</p>
        <p class="sb-lema">Apasionados por el buen servicio</p>
    </div>
    <div class="user-badge">
        <p class="ub-nombre">👤 {nombre}</p>
        <p class="ub-rol">{rol_label}</p>
    </div>""", unsafe_allow_html=True)

    st.markdown('<p class="sec-title">📌 Navegación</p>', unsafe_allow_html=True)

    if rol == "cliente":
        SECCIONES=[("📋","requerimientos","Mis Solicitudes"),("📖","mis_manuales","Mis Manuales")]
    elif rol == "tecnico":
        SECCIONES=[("📅","agenda","Mi Agenda"),("👥","asistencia","Mi Asistencia"),
                   ("💬","chat","Consultas")]
    else:
        SECCIONES=[("💬","chat","Chats"),("📁","proyectos","Proyectos"),
                   ("📅","agenda","Agenda"),("👥","asistencia","Asistencia"),
                   ("📚","biblioteca","Biblioteca"),("📄","documentos","Documentos"),
                   ("📖","manuales","Manuales"),("💼","ventas","Ventas"),
                   ("🏢","clientes","Aliados"),("📊","liquidaciones","Liquidaciones"),
                   ("👑","usuarios","Especialistas y Aliados"),("⚙️","config","Configuración")]

    for ico,key,label in SECCIONES:
        if tiene_modulo(u,key) or rol=="admin":
            activo="▶ " if st.session_state.seccion==key else ""
            if st.button(f"{ico} {activo}{label}",key=f"nav_{key}",use_container_width=True):
                st.session_state.seccion=key; st.rerun()

    # Panel IAs solo para admin
    if rol == "admin":
        st.markdown("---")
        st.markdown('<p class="sec-title">⚡ IAs activas</p>', unsafe_allow_html=True)
        usar_g = st.toggle("🔵 Gemini", value=True)
        usar_r = st.toggle("🟠 Groq",   value=True)
        usar_v = st.toggle("🟣 Venice",  value=True)
        modelo_g = st.selectbox("Modelo Gemini",["gemini-1.5-flash","gemini-1.5-pro"],label_visibility="collapsed")
    else:
        usar_g=usar_r=usar_v=True
        modelo_g="gemini-1.5-flash"

    st.markdown("---")
    if st.button("🚪 Cerrar sesión", use_container_width=True):
        if st.session_state.get("confirm_logout"):
            st.session_state.usuario=None; st.rerun()
        else:
            st.session_state["confirm_logout"]=True
            st.warning("¿Confirmas que deseas salir? Presiona de nuevo.")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="header-inst">
    <div class="h-brand">
        <p class="h-brand-name">Jandre<span class="h-brand-acc">x</span>T</p>
        <p class="h-brand-lema">Apasionados por el buen servicio</p>
        <p class="h-brand-sub">Soluciones Integrales · Plataforma v11.0</p>
    </div>
    <div class="h-user">
        <div class="h-saludo">{saludo},</div>
        <div class="h-nombre">{nombre}</div>
        <div class="h-rol">{rol_label}</div>
        <div class="h-fecha">{datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
    </div>
</div>""", unsafe_allow_html=True)

sec = st.session_state.seccion

# ── Panel consulta IA ─────────────────────────────────────────────────────────
def panel_ia(chat_id, ctx="General"):
    msgs = supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}&order=creado_en.asc")
    if msgs and isinstance(msgs,list):
        for m in msgs:
            st.markdown(f'<div class="chat-u"><span class="meta">🧑 {m.get("creado_en","")[:16]}</span><br>{m.get("pregunta","")}</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="chat-ia"><span class="meta">🏛️ JandrexT IA</span><br>{m.get("sintesis","")}</div>',unsafe_allow_html=True)
            if puede_borrar(u):
                if st.button("🗑️",key=f"del_msg_{m['id']}",help="Eliminar mensaje"):
                    supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
        st.markdown('<hr class="divider">',unsafe_allow_html=True)

    st.markdown('<div class="ayuda-tip">💡 Escribe tu consulta técnica, usa el micrófono o selecciona una plantilla. La IA responderá con contexto JandrexT.</div>',unsafe_allow_html=True)

    vk=f"voz_{chat_id}"; ik=f"inp_{chat_id}"
    if vk not in st.session_state: st.session_state[vk]=""
    if ik not in st.session_state: st.session_state[ik]=""

    try:
        from streamlit_mic_recorder import speech_to_text
        c1,c2=st.columns([1,3])
        with c1:
            tv=speech_to_text(language="es",start_prompt="🎤 Hablar",
                stop_prompt="⏹️ Detener",just_once=True,use_container_width=True,key=f"mic_{chat_id}")
        with c2: st.caption("🎤 Hablar → di tu consulta → ⏹️ Detener")
        if tv:
            st.session_state[vk]=tv; st.session_state[ik]=tv
            st.success(f"🎙️ *{tv}*")
    except: pass

    pregunta=st.text_area("✍️ Consulta",height=100,key=ik,
        placeholder="Escribe o usa el micrófono...")
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        btn=st.button("🚀 Consultar",use_container_width=True,type="primary",key=f"btn_{chat_id}")

    if btn and pregunta.strip():
        fns=[]
        if usar_g: fns.append(lambda p: gemini_ia(p,modelo_g))
        if usar_r: fns.append(lambda p: groq_ia(p))
        if usar_v: fns.append(lambda p: venice_ia(p))
        if not fns: st.warning("Activa al menos una IA."); return

        with st.spinner("Consultando..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
                resultados=list(ex.map(lambda f:f(pregunta),fns))

        cols=st.columns(len(resultados))
        for i,res in enumerate(resultados):
            with cols[i]:
                cls="badge-ok" if res["ok"] else "badge-err"
                st.markdown(f'<div class="ia-card"><h4>{res["icono"]} {res["ia"]}</h4><span class="{cls}">{"✓" if res["ok"] else "✗"}</span><span class="tiempo">⏱{res["tiempo"]}s</span></div>',unsafe_allow_html=True)
                if res["ok"]:
                    with st.expander("Ver"): st.write(res["respuesta"])

        ok=[r for r in resultados if r["ok"]]
        if ok:
            with st.spinner("Sintetizando..."):
                sintesis=juez_ia(pregunta,ok)
            st.markdown(f'<div class="juez-card"><div class="juez-titulo">🏛️ RESPUESTA JANDREXT · {ctx}</div><br>{sintesis}</div>',unsafe_allow_html=True)
            with st.expander("📋 Copiar"): st.code(sintesis,language=None)
            # Actualizar título del chat
            msgs_count=len(supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}") or [])
            if msgs_count==0:
                supa("chats","PATCH",{"titulo":pregunta[:50]},f"?id=eq.{chat_id}")
            supa("mensajes_chat","POST",{"chat_id":chat_id,"pregunta":pregunta,
                "sintesis":sintesis,"ias_usadas":[r["ia"] for r in ok]})
            st.session_state[ik]=""; st.session_state[vk]=""; st.rerun()
    elif btn: st.warning("⚠️ Escribe una consulta.")

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
# ══════════════════════════════════════════════════════════════════════════════
if sec=="chat" and tiene_modulo(u,"chat"):
    st.markdown("## 💬 Chats")
    st.markdown('<div class="ayuda-tip">💡 Crea un chat para cada tema o proyecto. El historial queda guardado permanentemente.</div>',unsafe_allow_html=True)
    col_l,col_c=st.columns([1,3])
    with col_l:
        st.markdown('<p class="sec-title">Mis chats</p>',unsafe_allow_html=True)
        if st.button("➕ Nuevo chat",use_container_width=True):
            nuevo=supa("chats","POST",{"titulo":"Nuevo chat","usuario_id":u["id"]})
            if nuevo and isinstance(nuevo,list):
                st.session_state.chat_activo=nuevo[0]["id"]; st.rerun()
        chats=supa("chats",filtro=f"?usuario_id=eq.{u['id']}&order=creado_en.desc")
        if chats and isinstance(chats,list):
            for c in chats:
                col_btn,col_del=st.columns([4,1])
                with col_btn:
                    if st.button(f"💬 {c.get('titulo','Chat')[:22]}",key=f"c_{c['id']}",use_container_width=True):
                        st.session_state.chat_activo=c["id"]; st.rerun()
                with col_del:
                    if puede_borrar(u):
                        if st.button("🗑️",key=f"dc_{c['id']}"):
                            supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                            supa("chats","DELETE",filtro=f"?id=eq.{c['id']}"); st.rerun()
    with col_c:
        cid=st.session_state.chat_activo
        if cid:
            # Título editable
            chat_data=supa("chats",filtro=f"?id=eq.{cid}")
            titulo_actual=chat_data[0].get("titulo","Chat") if chat_data and isinstance(chat_data,list) else "Chat"
            nuevo_titulo=st.text_input("✏️ Nombre del chat",value=titulo_actual,key=f"tit_{cid}")
            if nuevo_titulo != titulo_actual:
                supa("chats","PATCH",{"titulo":nuevo_titulo},f"?id=eq.{cid}")
            panel_ia(cid,"General")
        else:
            st.info("👈 Selecciona o crea un chat.")

# ══════════════════════════════════════════════════════════════════════════════
# PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="proyectos":
    st.markdown("## 📁 Proyectos")
    col_l,col_c=st.columns([1,3])
    with col_l:
        st.markdown('<p class="sec-title">Proyectos</p>',unsafe_allow_html=True)
        if rol in ["admin","vendedor"]:
            with st.expander("➕ Nuevo proyecto"):
                pn=st.text_input("Nombre *",key="pn")
                pc=st.text_input("Cliente/Aliado",key="pc")
                pt=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion"],key="pt")
                pl=st.selectbox("Línea de servicio",LINEAS_SERVICIO,key="pl")
                pg_e=st.number_input("Meses garantía equipos",min_value=0,max_value=60,value=12,key="pge")
                pg_i=st.number_input("Meses garantía instalación",min_value=0,max_value=24,value=6,key="pgi")
                if st.button("Crear",key="btn_proy"):
                    if pn:
                        fecha_g_e=(datetime.now()+timedelta(days=pg_e*30)).date()
                        fecha_g_i=(datetime.now()+timedelta(days=pg_i*30)).date()
                        supa("proyectos","POST",{"nombre":pn,"descripcion":pc,"tipo":pt,
                            "linea_servicio":pl,"meses_garantia_equipos":pg_e,
                            "meses_garantia_instalacion":pg_i,
                            "fecha_garantia_equipos":str(fecha_g_e),
                            "fecha_garantia_instalacion":str(fecha_g_i),
                            "creado_por":u["id"]})
                        st.success("✅ Proyecto creado"); st.rerun()
        proyectos=supa("proyectos",filtro="?order=creado_en.desc")
        if proyectos and isinstance(proyectos,list):
            buscar_p=st.text_input("🔍 Buscar proyecto",key="buscar_proy")
            filtrados=[p for p in proyectos if not buscar_p or buscar_p.lower() in p.get("nombre","").lower()]
            for p in filtrados:
                linea=p.get("linea_servicio","")[:15]
                if st.button(f"📁 {p['nombre'][:20]}\n{linea}",key=f"p_{p['id']}",use_container_width=True):
                    st.session_state.proy_activo=p["id"]
                    st.session_state.proy_nombre=p["nombre"]; st.rerun()
    with col_c:
        pid=st.session_state.proy_activo
        if pid:
            pdata=supa("proyectos",filtro=f"?id=eq.{pid}")
            p=pdata[0] if pdata and isinstance(pdata,list) else {}
            st.markdown(f"### 📁 {p.get('nombre','')}")
            c1,c2,c3=st.columns(3)
            c1.caption(f"🏷️ {p.get('linea_servicio','')}")
            c2.caption(f"👤 {p.get('descripcion','')}")
            # Garantías
            hoy=datetime.now().date()
            for label,field in [("Equipos","fecha_garantia_equipos"),("Instalación","fecha_garantia_instalacion")]:
                fg=p.get(field,"")
                if fg:
                    try:
                        fd=datetime.strptime(fg[:10],"%Y-%m-%d").date()
                        dias=(fd-hoy).days
                        cls="garantia-ok" if dias>30 else "garantia-vence"
                        ico="✅" if dias>30 else "⚠️"
                        c3.markdown(f'<span class="{cls}">{ico} Garantía {label}: {fg[:10]} ({dias}d)</span>',unsafe_allow_html=True)
                    except: pass

            col_sc,col_scc=st.columns([1,2])
            with col_sc:
                st.markdown('<p class="sec-title">Sub-chats</p>',unsafe_allow_html=True)
                if st.button("➕ Nuevo sub-chat",use_container_width=True,key="nsc"):
                    nuevo=supa("chats","POST",{"titulo":f"Chat {p.get('nombre','')}","proyecto_id":pid,"usuario_id":u["id"]})
                    if nuevo and isinstance(nuevo,list):
                        st.session_state.sc_activo=nuevo[0]["id"]; st.rerun()
                subs=supa("chats",filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc")
                if subs and isinstance(subs,list):
                    for s in subs:
                        cb,cd=st.columns([4,1])
                        with cb:
                            if st.button(f"💬 {s.get('titulo','')[:20]}",key=f"sc_{s['id']}",use_container_width=True):
                                st.session_state.sc_activo=s["id"]; st.rerun()
                        with cd:
                            if puede_borrar(u):
                                if st.button("🗑️",key=f"dsc_{s['id']}"):
                                    supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{s['id']}")
                                    supa("chats","DELETE",filtro=f"?id=eq.{s['id']}"); st.rerun()
            with col_scc:
                scid=st.session_state.sc_activo
                if scid: panel_ia(scid,p.get("nombre",""))
                else: st.info("👈 Crea o selecciona un sub-chat.")
        else:
            st.info("👈 Selecciona un proyecto.")

# ══════════════════════════════════════════════════════════════════════════════
# AGENDA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="agenda":
    st.markdown("## 📅 Agenda y Tareas")
    st.markdown('<div class="ayuda-tip">💡 Crea tareas, asígnalas al equipo y lleva el seguimiento completo con evidencias y checklists.</div>',unsafe_allow_html=True)
    col_f,col_l=st.columns([1,2])
    with col_f:
        if rol=="admin":
            st.markdown("### ➕ Nueva tarea")
            a_t=st.text_input("Tarea *")
            a_cl=st.text_input("Aliado / Sitio *")
            a_li=st.selectbox("Línea de servicio",LINEAS_SERVICIO)
            a_pr=st.selectbox("Prioridad",["🔴 Urgente (36h)","🟡 Normal (60h)","🟢 Puede esperar (90h)"])
            a_fe=st.date_input("Fecha límite",min_value=datetime.today())
            a_as=st.multiselect("Especialistas asignados",["Andrés Tapiero","Especialista 1","Especialista 2","Especialista 3","Asesor Comercial","Subcontratista"])
            a_sa=st.text_input("Colaborador satélite")
            a_ca=st.checkbox("¿Requiere visita en campo?")
            a_de=st.text_area("Descripción",height=70)
            a_ei=st.text_area("Estado inicial",height=60,placeholder="Cómo estaba antes...")
            a_re=st.text_area("Recomendaciones",height=60)
            a_le=st.text_area("Lección aprendida",height=50)
            a_se=st.checkbox("¿Requiere seguimiento?")
            a_fs=st.date_input("Fecha seguimiento") if a_se else None
            # Checklist automático
            checklist_items=[]
            if a_li in CHECKLISTS:
                st.markdown(f"**✅ Checklist automático — {a_li}**")
                for item in CHECKLISTS[a_li]:
                    checklist_items.append({"item":item,"completado":False})
                st.caption(f"{len(checklist_items)} ítems cargados automáticamente")

            if st.button("💾 Guardar tarea",type="primary",use_container_width=True):
                if a_t and a_cl:
                    horas=36 if "Urgente" in a_pr else 60 if "Normal" in a_pr else 90
                    data={"tarea":a_t,"cliente":a_cl,"prioridad":a_pr,"horas_limite":horas,
                        "fecha_limite":str(datetime.now()+timedelta(hours=horas)),
                        "asignados":a_as,"satelite":a_sa,"campo":a_ca,"descripcion":a_de,
                        "estado_inicial":a_ei,"recomendaciones":a_re,"leccion":a_le,
                        "seguimiento":a_se,"fecha_seguimiento":str(a_fs) if a_fs else None,
                        "checklist_tipo":a_li,"checklist_items":checklist_items,
                        "creado_por":u["id"]}
                    res=supa("agenda","POST",data)
                    if res:
                        asig=", ".join(a_as) if a_as else "Sin asignar"
                        telegram(f"📅 <b>Nueva tarea JandrexT</b>\n📋 {a_t}\n👤 {a_cl}\n🔧 {a_li}\n👥 {asig}\n{a_pr}")
                        st.success("✅ Tarea guardada"); st.rerun()
                else: st.warning("⚠️ Completa campos obligatorios (*)")
        else:
            st.info("Solo los administradores pueden crear tareas.")

    with col_l:
        st.markdown("### 📋 Tareas")
        # Búsqueda y filtros
        col_b1,col_b2,col_b3=st.columns(3)
        buscar_a=col_b1.text_input("🔍 Buscar")
        filtro_est=col_b2.selectbox("Estado",["Todos","pendiente","en_proceso","completado"])
        filtro_pri=col_b3.selectbox("Prioridad",["Todas","Urgente","Normal","Puede esperar"])

        tareas=supa("agenda",filtro="?order=creado_en.desc")
        if tareas and isinstance(tareas,list):
            # Si es especialista, solo sus tareas
            if rol=="tecnico":
                tareas=[t for t in tareas if nombre in (t.get("asignados") or [])]
            if buscar_a:
                tareas=[t for t in tareas if buscar_a.lower() in t.get("tarea","").lower() or buscar_a.lower() in t.get("cliente","").lower()]
            if filtro_est!="Todos":
                tareas=[t for t in tareas if t.get("estado")==filtro_est]
            if filtro_pri!="Todas":
                tareas=[t for t in tareas if filtro_pri in t.get("prioridad","")]

            c1,c2,c3=st.columns(3)
            c1.metric("Total",len(tareas))
            c2.metric("Pendientes",len([t for t in tareas if t.get("estado")=="pendiente"]))
            c3.metric("Urgentes",len([t for t in tareas if "Urgente" in t.get("prioridad","")]))

            for t in tareas:
                ico="🔴" if "Urgente" in t.get("prioridad","") else "🟡" if "Normal" in t.get("prioridad","") else "🟢"
                with st.expander(f"{ico} {t['tarea']} · {t.get('cliente','')} · {t.get('estado','pendiente')}"):
                    st.markdown(f"**Línea:** {t.get('checklist_tipo','')} | **Límite:** {t.get('fecha_limite','')[:10]}")
                    st.markdown(f"**Especialistas:** {', '.join(t.get('asignados') or [])}")
                    if t.get("descripcion"): st.markdown(f"**Desc:** {t['descripcion']}")
                    if t.get("estado_inicial"): st.markdown(f"**Estado inicial:** {t['estado_inicial']}")

                    # Checklist
                    items=t.get("checklist_items") or []
                    if items:
                        st.markdown(f"**✅ Checklist ({t.get('checklist_tipo','')}):**")
                        items_act=list(items)
                        cambiado=False
                        for i,item in enumerate(items_act):
                            nuevo_val=st.checkbox(item["item"],value=item.get("completado",False),key=f"chk_{t['id']}_{i}")
                            if nuevo_val!=item.get("completado",False):
                                items_act[i]["completado"]=nuevo_val; cambiado=True
                        if cambiado:
                            supa("agenda","PATCH",{"checklist_items":items_act},f"?id=eq.{t['id']}")
                            completados=sum(1 for x in items_act if x.get("completado"))
                            st.caption(f"✅ {completados}/{len(items_act)} ítems completados")

                    nuevo_est=st.selectbox("Estado",["pendiente","en_proceso","completado"],
                        index=["pendiente","en_proceso","completado"].index(t.get("estado","pendiente")),
                        key=f"est_{t['id']}")
                    ef=st.text_area("Estado final / Evidencia",key=f"ef_{t['id']}",value=t.get("estado_final",""),height=60)

                    col_upd,col_del=st.columns([3,1])
                    with col_upd:
                        if st.button("💾 Actualizar",key=f"upd_{t['id']}",use_container_width=True):
                            supa("agenda","PATCH",{"estado":nuevo_est,"estado_final":ef},f"?id=eq.{t['id']}")
                            if nuevo_est=="completado":
                                telegram(f"✅ <b>Tarea completada</b>\n📋 {t['tarea']}\n👤 {t.get('cliente','')}\n📝 {ef[:100]}")
                            st.success("✅ Actualizado"); st.rerun()
                    with col_del:
                        if puede_borrar(u):
                            if st.button("🗑️",key=f"del_t_{t['id']}"):
                                supa("agenda","DELETE",filtro=f"?id=eq.{t['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ASISTENCIA con GPS e Informe IA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="asistencia":
    st.markdown("## 👥 Asistencia y Campo")
    st.markdown('<div class="ayuda-tip">💡 Registra entrada/salida con GPS. Sube fotos y notas de voz para generar el informe automáticamente.</div>',unsafe_allow_html=True)

    geo_html="""
    <style>
    .geo-btn{background:#cc0000;color:#fff;border:none;border-radius:12px;padding:1rem 1.5rem;
        font-size:1.1rem;font-weight:700;width:100%;cursor:pointer;margin:0.3rem 0;
        display:flex;align-items:center;justify-content:center;gap:0.5rem;}
    .geo-salida{background:#1a1a1a;border:2px solid #cc0000;}
    .geo-status{background:#0a0a0a;border:1px solid #333;border-radius:10px;
        padding:0.8rem;margin:0.5rem 0;color:#ccc;font-size:0.85rem;}
    #mapa{width:100%;height:200px;border-radius:10px;border:1px solid #cc0000;margin:0.5rem 0;}
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <div id="geo-status" class="geo-status">📍 Presiona para capturar tu ubicación GPS...</div>
    <div id="mapa"></div>
    <button class="geo-btn" onclick="getGeo('entrada')">✅ Registrar ENTRADA con GPS</button>
    <button class="geo-btn geo-salida" onclick="getGeo('salida')">🏁 Registrar SALIDA con GPS</button>
    <script>
    var map=L.map('mapa').setView([4.711,-74.0721],11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var mk=null;
    function getGeo(tipo){
        document.getElementById('geo-status').innerHTML='⏳ Obteniendo GPS...';
        navigator.geolocation.getCurrentPosition(function(p){
            var lat=p.coords.latitude.toFixed(6),lng=p.coords.longitude.toFixed(6);
            document.getElementById('geo-status').innerHTML=(tipo=='entrada'?'✅':'🏁')+' <b>'+tipo.toUpperCase()+'</b> registrado<br>📌 '+lat+', '+lng+' | Precisión: '+Math.round(p.coords.accuracy)+'m';
            if(mk)map.removeLayer(mk);
            mk=L.marker([lat,lng]).addTo(map).bindPopup(tipo).openPopup();
            map.setView([lat,lng],15);
            window.parent.postMessage({geo:true,lat:lat,lng:lng,tipo:tipo},'*');
        },function(e){document.getElementById('geo-status').innerHTML='⚠️ '+e.message+' — Activa el GPS.';},{enableHighAccuracy:true,timeout:15000});
    }
    </script>"""
    st.components.v1.html(geo_html,height=420,scrolling=False)

    st.markdown("### ✍️ Completar registro")
    with st.form("form_asist",clear_on_submit=True):
        c1,c2=st.columns(2)
        m_col=c1.text_input("👤 Especialista",value=nombre)
        m_tip=c2.selectbox("Tipo",["entrada","salida"])
        m_pro=st.text_input("📍 Proyecto / Aliado")
        m_tar=st.text_input("🔧 Tarea realizada")
        m_lat=st.text_input("🌐 Latitud GPS",placeholder="Se llena automáticamente con el mapa")
        m_lng=st.text_input("🌐 Longitud GPS",placeholder="Se llena automáticamente con el mapa")
        sub=st.form_submit_button("💾 Guardar registro",use_container_width=True,type="primary")
        if sub:
            ub=f"{m_lat},{m_lng}" if m_lat and m_lng else ""
            supa("asistencia","POST",{"colaborador_id":u["id"],"colaborador_nombre":m_col,
                "tipo":m_tip,"proyecto":m_pro,"tarea":m_tar,"ubicacion":ub})
            emoji="✅" if m_tip=="entrada" else "🏁"
            geo_txt=f"\n📌 GPS: {ub}" if ub else ""
            telegram(f"{emoji} <b>{m_col}</b> registró {m_tip}\n📍 {m_pro}\n📋 {m_tar}{geo_txt}")
            st.success("✅ Registrado"); st.rerun()

    # Generador de informe con IA
    st.markdown('<hr class="divider">',unsafe_allow_html=True)
    st.markdown("### 📋 Generar informe de trabajo")
    st.markdown('<div class="ayuda-tip">💡 Describe con voz o texto lo que hiciste. La IA organiza el informe profesional automáticamente.</div>',unsafe_allow_html=True)

    inf_proyecto=st.text_input("Proyecto / Aliado",key="inf_proy")
    inf_servicio=st.selectbox("Tipo de servicio",LINEAS_SERVICIO,key="inf_serv")

    vk_inf="voz_informe"
    if vk_inf not in st.session_state: st.session_state[vk_inf]=""
    try:
        from streamlit_mic_recorder import speech_to_text
        c1,c2=st.columns([1,3])
        with c1:
            tv=speech_to_text(language="es",start_prompt="🎤 Describir trabajo",
                stop_prompt="⏹️ Detener",just_once=True,use_container_width=True,key="mic_inf")
        with c2: st.caption("Describe qué encontraste, qué hiciste y qué quedó pendiente")
        if tv:
            st.session_state[vk_inf]=tv; st.success(f"🎙️ *{tv}*")
    except: pass

    inf_desc=st.text_area("📝 Descripción del trabajo",value=st.session_state[vk_inf],height=120,
        placeholder="Ej: Llegué al conjunto, revisé las 4 cámaras del parqueadero, una estaba sin señal por cable suelto...",key="inf_desc_ta")
    inf_fotos=st.text_area("📸 Descripción de evidencias fotográficas",height=80,
        placeholder="Ej: Foto 1: cámara sin señal, Foto 2: cable reconectado, Foto 3: sistema funcionando...")

    if st.button("🤖 Generar informe con IA",type="primary",use_container_width=False):
        if inf_desc.strip():
            with st.spinner("La IA está organizando tu informe..."):
                informe=generar_informe_ia(inf_desc,inf_fotos,inf_proyecto,inf_servicio)
            st.markdown('<div class="informe-box">',unsafe_allow_html=True)
            st.markdown(f"### 📋 Pre-informe — {inf_proyecto}")
            st.markdown(informe)
            st.markdown('</div>',unsafe_allow_html=True)
            st.code(informe,language=None)
            telegram(f"📋 <b>Pre-informe generado</b>\n👤 {nombre}\n📍 {inf_proyecto}\n🔧 {inf_servicio}")
        else: st.warning("⚠️ Describe el trabajo realizado.")

    # Mapa admin
    if rol=="admin":
        st.markdown('<hr class="divider">',unsafe_allow_html=True)
        st.markdown("### 🗺️ Especialistas en campo")
        hoy=datetime.now().strftime("%Y-%m-%d")
        regs=supa("asistencia",filtro=f"?fecha=gte.{hoy}T00:00:00&order=fecha.desc")
        activos=[r for r in (regs or []) if r.get("ubicacion") and r["tipo"]=="entrada" and not r.get("salida")]
        if activos:
            markers=""
            for r in activos:
                try:
                    lat,lng=r["ubicacion"].split(",")
                    markers+=f"L.marker([{lat},{lng}]).addTo(m).bindPopup('<b>{r.get(\"colaborador_nombre\",\"\")}</b><br>📍{r.get(\"proyecto\",\"\")}<br>📋{r.get(\"tarea\",\"\")}<br>🕐{r.get(\"fecha\",\"\")[:16]}').openPopup();"
                except: pass
            mapa_html=f"""<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <div id="ma" style="width:100%;height:300px;border-radius:10px;border:1px solid #cc0000;"></div>
            <script>var m=L.map('ma').setView([4.711,-74.0721],11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);{markers}</script>"""
            st.components.v1.html(mapa_html,height=320)
            st.metric("En campo ahora",len(activos))
        else:
            st.info("No hay especialistas con GPS activo en este momento.")

        st.markdown("### 📊 Registros de hoy")
        if regs and isinstance(regs,list):
            for r in regs:
                bg="#0a1a0a" if r["tipo"]=="entrada" else "#1a0a0a"
                ico="✅" if r["tipo"]=="entrada" else "🏁"
                geo="📌" if r.get("ubicacion") else ""
                st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.3rem;">
                    {ico} <b>{r.get('colaborador_nombre','')}</b> · {r.get('fecha','')[:16]} {geo}<br>
                    📍 {r.get('proyecto','')} · 📋 {r.get('tarea','')}
                </div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# USUARIOS / ESPECIALISTAS Y ALIADOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="usuarios" and rol=="admin":
    st.markdown("## 👑 Especialistas y Aliados")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo usuario")
        u_n=st.text_input("Nombre completo *")
        u_e=st.text_input("Email *")
        u_p=st.text_input("Contraseña temporal *",type="password")
        u_r=st.selectbox("Rol",["tecnico","vendedor","cliente","admin"],
            format_func=lambda x: ROL_LABEL.get(x,x))
        u_td=st.selectbox("Tipo documento",["cedula","cedula_extranjeria","pasaporte","nit"])
        u_nd=st.text_input("Número de documento *")
        u_cel=st.text_input("Celular principal *")
        u_cel2=st.text_input("Celular alternativo")
        u_ce=st.text_input("Contacto de emergencia")
        u_esp=st.selectbox("Especialidad principal",[""] + LINEAS_SERVICIO)
        u_hab=st.multiselect("Habilidades secundarias",LINEAS_SERVICIO)
        u_vin=st.selectbox("Tipo vinculación",["directo","subcontratista","satelite"])
        u_tel=st.text_input("Teléfono")
        u_m=st.multiselect("Módulos visibles",["chat","proyectos","agenda","asistencia",
            "biblioteca","documentos","manuales","ventas","clientes","liquidaciones"])

        if st.button("💾 Crear usuario",type="primary",use_container_width=True):
            if u_n and u_e and u_p and u_nd and u_cel:
                res=supa("usuarios","POST",{"nombre":u_n,"email":u_e,
                    "password_hash":hash_pwd(u_p),"rol":u_r,"telefono":u_tel,
                    "tipo_documento":u_td,"numero_documento":u_nd,
                    "celular":u_cel,"celular_alternativo":u_cel2,
                    "contacto_emergencia":u_ce,"especialidad_principal":u_esp,
                    "habilidades":u_hab,"tipo_vinculacion":u_vin,"modulos":u_m})
                if res:
                    telegram(f"👤 <b>Nuevo {ROL_LABEL.get(u_r,u_r)}</b>\n{u_n}\n📧 {u_e}\n📱 {u_cel}\n🔑 Contraseña temporal asignada")
                    st.success(f"✅ {ROL_LABEL.get(u_r,u_r)} {u_n} creado"); st.rerun()
            else: st.warning("⚠️ Completa todos los campos obligatorios (*)")

    with col_l:
        st.markdown("### 📋 Usuarios registrados")
        todos=supa("usuarios",filtro="?order=creado_en.desc")
        if todos and isinstance(todos,list):
            st.metric("Total",len(todos))
            for usr in todos:
                rol_usr=ROL_LABEL.get(usr.get("rol",""),usr.get("rol",""))
                activo="✅" if usr.get("activo") else "❌"
                with st.expander(f"👤 {usr['nombre']} · {rol_usr} · {activo}"):
                    c1,c2=st.columns(2)
                    c1.markdown(f"**Email:** {usr['email']}")
                    c1.markdown(f"**Doc:** {usr.get('tipo_documento','')} {usr.get('numero_documento','')}")
                    c1.markdown(f"**Celular:** {usr.get('celular','')}")
                    c2.markdown(f"**Especialidad:** {usr.get('especialidad_principal','')}")
                    c2.markdown(f"**Vinculación:** {usr.get('tipo_vinculacion','')}")
                    c2.markdown(f"**Emergencia:** {usr.get('contacto_emergencia','')}")
                    st.markdown(f"**Módulos:** {', '.join(usr.get('modulos') or [])}")
                    nueva_pwd=st.text_input("Nueva contraseña",type="password",key=f"pwd_{usr['id']}")
                    ca,cb=st.columns(2)
                    with ca:
                        if st.button("🔑 Cambiar contraseña",key=f"cp_{usr['id']}"):
                            if nueva_pwd:
                                supa("usuarios","PATCH",{"password_hash":hash_pwd(nueva_pwd)},f"?id=eq.{usr['id']}")
                                st.success("✅ Contraseña actualizada")
                    with cb:
                        btn_lbl="❌ Desactivar" if usr.get("activo") else "✅ Activar"
                        if st.button(btn_lbl,key=f"act_{usr['id']}"):
                            supa("usuarios","PATCH",{"activo":not usr.get("activo")},f"?id=eq.{usr['id']}")
                            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="documentos" and tiene_modulo(u,"documentos"):
    st.markdown("## 📄 Documentos")
    TIPOS_DOC={"cotizacion":"Cotización","orden_trabajo":"Orden de Trabajo",
               "orden_servicio":"Orden de Servicio","contrato":"Contrato de Servicio",
               "acta_entrega":"Acta de Entrega","informe":"Informe Técnico"}
    tipo_doc=st.selectbox("Tipo",list(TIPOS_DOC.keys()),format_func=lambda x:TIPOS_DOC[x])
    proyecto_doc=st.text_input("Proyecto / Aliado")
    linea_doc=st.selectbox("Línea de servicio",LINEAS_SERVICIO)
    tipo_cli=st.selectbox("Tipo de aliado",["copropiedad","empresa","natural","administracion"])
    contenido=st.text_area("Describe el contenido",height=150)
    valor=st.number_input("Valor total (COP)",min_value=0,step=50000)
    anticipo=st.number_input("Anticipo (COP)",min_value=0,step=50000)
    if st.button(f"📄 Generar {TIPOS_DOC.get(tipo_doc,'Documento')}",type="primary"):
        if contenido.strip():
            with st.spinner("Generando documento..."):
                res=supa("documentos","POST",{"tipo":tipo_doc,"contenido":contenido,
                    "valor_total":valor,"anticipo":anticipo,"saldo":valor-anticipo,"creado_por":u["id"]})
                num=""
                if res and isinstance(res,list):
                    num=f"ID: {res[0].get('id','')[:8]}"
                contenido_full=f"Tipo aliado: {tipo_cli}\nLínea: {linea_doc}\nValor: ${valor:,.0f}\nAnticipo: ${anticipo:,.0f}\nSaldo: ${valor-anticipo:,.0f}\n\n{contenido}"
                doc=generar_doc_ia(TIPOS_DOC.get(tipo_doc,"Documento"),contenido_full,proyecto_doc)
            st.markdown(f"### 📄 {TIPOS_DOC.get(tipo_doc,'')} {num}")
            st.markdown(doc)
            st.code(doc,language=None)
        else: st.warning("⚠️ Describe el contenido.")

# ══════════════════════════════════════════════════════════════════════════════
# MANUALES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="manuales" and tiene_modulo(u,"manuales"):
    st.markdown("## 📖 Manuales")
    col_f,col_l=st.columns([2,1])
    with col_f:
        m_pro=st.text_input("Proyecto / Aliado")
        m_sis=st.text_input("Sistema instalado")
        m_tip=st.selectbox("Tipo",["Manual de Usuario","Manual Técnico",
            "Guía de Configuración y Contraseñas","Plan de Mantenimiento Preventivo",
            "Manual de Operación Diaria","Guía de Acceso Remoto"])
        m_lin=st.selectbox("Línea de servicio",LINEAS_SERVICIO)
        m_det=st.text_area("Detalles específicos",height=130)
        m_cli=st.selectbox("Tipo de destinatario",["copropiedad","empresa","natural","administracion"])
        if st.button("📖 Generar manual",type="primary"):
            if m_sis and m_det:
                with st.spinner("Generando manual..."):
                    prompt=f"""Crea un {m_tip} completo para JandrexT Soluciones Integrales.
Lema: Apasionados por el buen servicio
Proyecto: {m_pro} | Sistema: {m_sis} | Línea: {m_lin} | Destinatario: {m_cli}
Detalles: {m_det} | Fecha: {datetime.now().strftime('%d de %B de %Y')}
Incluir: portada JandrexT, índice, descripción, instrucciones paso a paso,
contraseñas y accesos, problemas comunes, mantenimiento preventivo con frecuencias,
señales de alerta, contacto: Andrés Tapiero 317 391 0621 proyectos@jandrext.com"""
                    manual=generar_doc_ia(m_tip,prompt,m_pro)
                    supa("manuales","POST",{"titulo":f"{m_tip} — {m_sis}","tipo":m_tip,
                        "sistema":m_sis,"contenido":manual,"creado_por":u["id"]})
                st.markdown(f"### 📖 {m_tip}")
                st.markdown(manual)
                st.code(manual,language=None)
                st.success("✅ Manual guardado")
            else: st.warning("⚠️ Completa sistema y detalles.")
    with col_l:
        st.markdown("### 📚 Guardados")
        mans=supa("manuales",filtro=f"?creado_por=eq.{u['id']}&order=creado_en.desc")
        if mans and isinstance(mans,list):
            for m in mans:
                with st.expander(f"📖 {m.get('tipo','')}"):
                    st.caption(m.get("sistema",""))
                    if puede_borrar(u):
                        if st.button("🗑️ Eliminar",key=f"del_man_{m['id']}"):
                            supa("manuales","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
                    st.write(m.get("contenido",""))

# ══════════════════════════════════════════════════════════════════════════════
# VENTAS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="ventas" and tiene_modulo(u,"ventas"):
    st.markdown("## 💼 Asistente de Ventas")
    c1,c2=st.columns(2)
    with c1:
        v_cl=st.text_input("Aliado / empresa")
        v_ti=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion"])
        v_li=st.selectbox("Línea de servicio",LINEAS_SERVICIO)
        v_ne=st.text_area("¿Qué necesita?",height=100)
    with c2:
        v_pr=st.selectbox("Presupuesto",["No definido","< $1M","$1M-$5M","$5M-$15M","$15M-$50M","> $50M"])
        v_ur=st.selectbox("Urgencia",["Normal","Urgente","Proyecto futuro"])
        v_co=st.text_input("Contacto / cargo")
    if st.button("💼 Generar propuesta",type="primary"):
        if v_ne:
            with st.spinner("Generando propuesta..."):
                prompt=f"""Aliado: {v_cl} | Tipo: {v_ti} | Línea: {v_li} | Contacto: {v_co}
Necesidad: {v_ne} | Presupuesto: {v_pr} | Urgencia: {v_ur}
Genera propuesta comercial empática con: saludo, comprensión del problema,
solución específica JandrexT, equipos, garantías, mantenimiento preventivo, próximos pasos."""
                prop=generar_doc_ia("Propuesta Comercial",prompt,v_cl)
            st.markdown(f"### 💼 Propuesta — {v_cl}")
            st.markdown(prop)
            st.code(prop,language=None)
        else: st.warning("⚠️ Describe la necesidad.")

# ══════════════════════════════════════════════════════════════════════════════
# ALIADOS (clientes) — REQUERIMIENTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec in ["requerimientos","clientes"]:
    st.markdown("## 🤝 Aliados y Solicitudes")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva solicitud")
        st.markdown('<div class="ayuda-tip">💡 Envía tu solicitud y JandrexT será notificado inmediatamente por múltiples canales.</div>',unsafe_allow_html=True)
        r_ti=st.text_input("Asunto de la solicitud *")
        r_de=st.text_area("Descripción detallada",height=100)
        r_pr=st.selectbox("Urgencia",["normal","urgente","puede_esperar"])
        if st.button("📤 Enviar solicitud",type="primary",use_container_width=True):
            if r_ti:
                supa("requerimientos","POST",{"titulo":r_ti,"descripcion":r_de,"prioridad":r_pr})
                telegram(f"🔔 <b>Nueva solicitud de Aliado</b>\n📋 {r_ti}\n📝 {r_de[:100]}\n⚡ {r_pr}")
                st.success("✅ Solicitud enviada. JandrexT fue notificado.")
                st.balloons(); st.rerun()
            else: st.warning("⚠️ El asunto es obligatorio")
    with col_l:
        st.markdown("### 📋 Solicitudes")
        reqs=supa("requerimientos",filtro="?order=creado_en.desc")
        if reqs and isinstance(reqs,list):
            for r in reqs:
                est_ico="✅" if r["estado"]=="resuelto" else "🔄" if r["estado"]=="en_proceso" else "🆕"
                with st.expander(f"{est_ico} {r['titulo']} · {r.get('estado','')}"):
                    st.markdown(f"**Descripción:** {r.get('descripcion','')}")
                    st.markdown(f"**Urgencia:** {r.get('prioridad','')} | **Fecha:** {r.get('creado_en','')[:10]}")
                    if rol=="admin":
                        nuevo_est=st.selectbox("Estado",["nuevo","en_proceso","resuelto"],
                            index=["nuevo","en_proceso","resuelto"].index(r.get("estado","nuevo")),
                            key=f"rest_{r['id']}")
                        if st.button("💾 Actualizar",key=f"rupd_{r['id']}"):
                            supa("requerimientos","PATCH",{"estado":nuevo_est},f"?id=eq.{r['id']}"); st.rerun()
                        if puede_borrar(u):
                            if st.button("🗑️",key=f"rdel_{r['id']}"):
                                supa("requerimientos","DELETE",filtro=f"?id=eq.{r['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="liquidaciones" and tiene_modulo(u,"liquidaciones"):
    st.markdown("## 📊 Liquidaciones")
    esp_list=supa("usuarios",filtro="?rol=in.(tecnico,vendedor)&activo=eq.true") or []
    nombres_esp=[x["nombre"] for x in esp_list] if esp_list else []
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva liquidación")
        l_col=st.selectbox("Especialista",nombres_esp if nombres_esp else ["Sin especialistas"])
        l_ini=st.date_input("Período inicio")
        l_fin=st.date_input("Período fin")
        l_dia=st.number_input("Días trabajados",min_value=0,max_value=31)
        l_sal=st.number_input("Salario base (COP)",min_value=0,step=50000)
        l_tip=st.selectbox("Tipo salario",["diario","proyecto"])
        st.markdown("**Deducciones:**")
        d_pre=st.number_input("Préstamo/Anticipo",min_value=0,step=10000)
        d_otr=st.number_input("Otras deducciones",min_value=0,step=10000)
        bruto=l_sal*l_dia if l_tip=="diario" else l_sal
        dedu=d_pre+d_otr; neto=bruto-dedu
        st.markdown(f"**Bruto:** ${bruto:,.0f} | **Dedu:** ${dedu:,.0f} | **Neto: ${neto:,.0f}**")
        if st.button("💾 Generar y enviar",type="primary",use_container_width=True):
            col_data=next((x for x in esp_list if x["nombre"]==l_col),None)
            if col_data:
                supa("liquidaciones","POST",{"colaborador_id":col_data["id"],
                    "periodo_inicio":str(l_ini),"periodo_fin":str(l_fin),
                    "dias_trabajados":l_dia,"salario_base":l_sal,"tipo_salario":l_tip,
                    "deducciones":[{"concepto":"Préstamo","valor":d_pre},{"concepto":"Otras","valor":d_otr}],
                    "total":neto})
                msg=f"""💰 <b>Liquidación JandrexT</b>
👤 {l_col} | 📅 {l_ini} al {l_fin}
📆 Días: {l_dia} | 💵 Base: ${l_sal:,.0f}
➖ Deducciones: ${dedu:,.0f}
✅ <b>Total neto: ${neto:,.0f} COP</b>
📧 proyectos@jandrext.com"""
                telegram(msg)
                st.success("✅ Liquidación generada y notificada"); st.rerun()
    with col_l:
        st.markdown("### 📋 Liquidaciones")
        liqs=supa("liquidaciones",filtro="?order=creado_en.desc") or []
        for liq in liqs:
            cn=next((x["nombre"] for x in esp_list if x["id"]==liq.get("colaborador_id")),"Desconocido")
            with st.expander(f"💰 {cn} · {liq.get('periodo_inicio','')} → {liq.get('periodo_fin','')}"):
                st.markdown(f"**Días:** {liq.get('dias_trabajados',0)} | **Total:** ${liq.get('total',0):,.0f} COP")
                if puede_borrar(u):
                    if st.button("🗑️",key=f"del_liq_{liq['id']}"):
                        supa("liquidaciones","DELETE",filtro=f"?id=eq.{liq['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="biblioteca" and tiene_modulo(u,"biblioteca"):
    st.markdown("## 📚 Biblioteca")
    msgs=supa("mensajes_chat",filtro="?order=creado_en.desc") or []
    buscar=st.text_input("🔍 Buscar en consultas")
    filtrados=[m for m in msgs if not buscar or buscar.lower() in m.get("pregunta","").lower() or buscar.lower() in m.get("sintesis","").lower()]
    st.metric("Total consultas",len(filtrados))
    for m in filtrados:
        with st.expander(f"📌 {m.get('pregunta','')[:60]}... | 📅 {m.get('creado_en','')[:10]}"):
            st.markdown(f"**IAs:** {' · '.join(m.get('ias_usadas') or [])}")
            st.markdown(m.get("sintesis",""))
            st.code(m.get("sintesis",""),language=None)
            if puede_borrar(u):
                if st.button("🗑️ Eliminar",key=f"del_bib_{m['id']}"):
                    supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="footer-inst">
    <span class="footer-acc">JandrexT</span> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: <span class="footer-acc">Andrés Tapiero</span> &nbsp;·&nbsp;
    Plataforma v11.0 &nbsp;·&nbsp; 🔒 Sistema Interno<br>
    <span class="footer-lema">Apasionados por el buen servicio</span>
</div>""", unsafe_allow_html=True)
