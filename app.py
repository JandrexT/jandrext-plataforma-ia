import streamlit as st
import hashlib
import json
import re
import time
import os
import base64
from datetime import datetime, date, timedelta
import pytz
import requests
from supabase import create_client, Client

# ─────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="JandrexT IA",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded"
)

TIMEZONE = pytz.timezone("America/Bogota")

def now_bogota():
    return datetime.now(TIMEZONE)

def format_fecha(dt):
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except:
            return dt
    try:
        return dt.astimezone(TIMEZONE).strftime("%d/%m/%Y %H:%M")
    except:
        return str(dt)

# ─────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

supabase: Client = init_supabase()

# ─────────────────────────────────────────────
# HASHING
# ─────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()

def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    md5_hash = hashlib.md5(password.encode()).hexdigest()
    if md5_hash == stored_hash:
        return True
    sha256_hash = hashlib.sha256(password.encode()).hexdigest()
    if sha256_hash == stored_hash:
        return True
    bcrypt_hash = None
    try:
        import bcrypt
        if stored_hash.startswith("$2"):
            bcrypt_hash = bcrypt.checkpw(password.encode(), stored_hash.encode())
            return bcrypt_hash
    except:
        pass
    return False

# ─────────────────────────────────────────────
# SESIÓN PERSISTENTE
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "logged_in": False,
        "user_id": None,
        "user_email": "",
        "user_name": "",
        "user_role": "",
        "login_attempts": 0,
        "login_blocked_until": None,
        "active_module": "Chats",
        # Config IAs (solo admin puede cambiar)
        "ia_groq_enabled": True,
        "ia_gemini_enabled": True,
        "ia_venice_enabled": False,
        "ia_primary": "groq",  # ia preferida
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# ─────────────────────────────────────────────
# NOTIFICACIONES
# ─────────────────────────────────────────────
def send_telegram(message: str):
    try:
        token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID_ADMIN", "1773051960")
        if not token:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
    except:
        pass

def send_email(to: str, subject: str, body: str):
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        gmail_user = st.secrets.get("GMAIL_USER", "")
        gmail_pass = st.secrets.get("GMAIL_APP_PASSWORD", "")
        if not gmail_user:
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, to, msg.as_string())
    except:
        pass

# ─────────────────────────────────────────────
# IAs — FUNCIONES INTERNAS (sin exponer al usuario)
# ─────────────────────────────────────────────
def consultar_groq(prompt: str, system: str = "") -> str:
    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
        if not api_key:
            return ""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.7
        }
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                         headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return ""
    except:
        return ""

def consultar_gemini(prompt: str, system: str = "") -> str:
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY", "")
        if not api_key:
            return ""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return ""
    except:
        return ""

def consultar_venice(prompt: str, system: str = "") -> str:
    try:
        api_key = st.secrets.get("VENICE_API_KEY", "")
        if not api_key:
            return ""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": "llama-3.3-70b",
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0.7
        }
        r = requests.post("https://api.venice.ai/api/v1/chat/completions",
                         headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return ""
    except:
        return ""

def consultar_ia(prompt: str, system: str = "") -> str:
    """
    Función principal de consulta IA.
    Intenta en orden según configuración admin.
    El usuario NUNCA ve qué IA responde.
    """
    primary = st.session_state.get("ia_primary", "groq")
    groq_on = st.session_state.get("ia_groq_enabled", True)
    gemini_on = st.session_state.get("ia_gemini_enabled", True)
    venice_on = st.session_state.get("ia_venice_enabled", False)

    order = []
    if primary == "groq":
        order = ["groq", "gemini", "venice"]
    elif primary == "gemini":
        order = ["gemini", "groq", "venice"]
    elif primary == "venice":
        order = ["venice", "groq", "gemini"]
    else:
        order = ["groq", "gemini", "venice"]

    for ia in order:
        if ia == "groq" and groq_on:
            resp = consultar_groq(prompt, system)
            if resp:
                return resp
        elif ia == "gemini" and gemini_on:
            resp = consultar_gemini(prompt, system)
            if resp:
                return resp
        elif ia == "venice" and venice_on:
            resp = consultar_venice(prompt, system)
            if resp:
                return resp

    return "En este momento no se puede procesar la consulta. Por favor intente más tarde."

# ─────────────────────────────────────────────
# CSS INSTITUCIONAL
# ─────────────────────────────────────────────
def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Montserrat', sans-serif !important;
    }

    .stApp {
        background: #f5f7fa;
    }

    .jandrext-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.2rem 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .jandrext-header h1 {
        font-size: 1.6rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: 1px;
    }

    .jandrext-header .lema {
        font-size: 0.8rem;
        opacity: 0.75;
        font-style: italic;
    }

    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 1.2rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 4px solid #0f3460;
        margin-bottom: 1rem;
    }

    .metric-card h3 {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f3460;
        margin: 0;
    }

    .metric-card p {
        color: #666;
        margin: 0;
        font-size: 0.85rem;
    }

    .stButton > button {
        background: linear-gradient(135deg, #0f3460, #16213e);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }

    .stButton > button:hover {
        background: linear-gradient(135deg, #e94560, #0f3460);
        transform: translateY(-1px);
    }

    .chat-msg-user {
        background: #0f3460;
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 18px 18px 4px 18px;
        margin: 0.5rem 0;
        max-width: 80%;
        margin-left: auto;
        font-size: 0.9rem;
    }

    .chat-msg-bot {
        background: white;
        color: #1a1a2e;
        padding: 0.8rem 1.2rem;
        border-radius: 18px 18px 18px 4px;
        margin: 0.5rem 0;
        max-width: 80%;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        font-size: 0.9rem;
    }

    .disclaimer {
        font-size: 0.7rem;
        color: #999;
        text-align: center;
        margin-top: 2rem;
        font-style: italic;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }

    [data-testid="stSidebar"] * {
        color: white !important;
    }

    [data-testid="stSidebar"] .stButton > button {
        background: rgba(255,255,255,0.1) !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
        color: white !important;
        width: 100%;
        text-align: left;
        margin: 2px 0;
    }

    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(233, 69, 96, 0.3) !important;
    }

    /* Login */
    .login-container {
        max-width: 420px;
        margin: 3rem auto;
        background: white;
        border-radius: 16px;
        padding: 2.5rem;
        box-shadow: 0 8px 32px rgba(0,0,0,0.12);
    }

    .login-logo {
        text-align: center;
        margin-bottom: 2rem;
    }

    .login-logo h2 {
        color: #0f3460;
        font-weight: 700;
        font-size: 1.8rem;
    }

    .login-logo p {
        color: #888;
        font-size: 0.85rem;
        font-style: italic;
    }

    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .badge-active { background: #d4edda; color: #155724; }
    .badge-pending { background: #fff3cd; color: #856404; }
    .badge-closed { background: #f8d7da; color: #721c24; }

    .section-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #0f3460;
        border-bottom: 3px solid #e94560;
        padding-bottom: 0.5rem;
        margin-bottom: 1.5rem;
    }

    .info-box {
        background: #e8f4fd;
        border-left: 4px solid #0f3460;
        padding: 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.5rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

inject_css()

# ─────────────────────────────────────────────
# SALUDO POR HORA
# ─────────────────────────────────────────────
def get_saludo():
    hora = now_bogota().hour
    if 5 <= hora < 12:
        return "Buenos días"
    elif 12 <= hora < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
def show_login():
    st.markdown("""
    <div class="login-container">
        <div class="login-logo">
            <h2>🔒 JandrexT</h2>
            <p>Apasionados por el buen servicio</p>
            <hr style="border-color:#e0e0e0;">
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### Iniciar sesión")

        # Verificar bloqueo
        if st.session_state.login_blocked_until:
            remaining = (st.session_state.login_blocked_until - now_bogota()).total_seconds()
            if remaining > 0:
                st.error(f"🔒 Cuenta bloqueada. Intente en {int(remaining//60)}m {int(remaining%60)}s")
                return
            else:
                st.session_state.login_blocked_until = None
                st.session_state.login_attempts = 0

        email = st.text_input("📧 Correo electrónico", key="login_email")
        password = st.text_input("🔑 Contraseña", type="password", key="login_pass")

        if st.button("Ingresar →", use_container_width=True):
            if not email or not password:
                st.warning("Complete todos los campos")
                return

            try:
                result = supabase.table("usuarios").select("*").eq("email", email).execute()
                if result.data:
                    user = result.data[0]
                    if verify_password(password, user.get("password_hash", "")):
                        st.session_state.logged_in = True
                        st.session_state.user_id = user["id"]
                        st.session_state.user_email = user["email"]
                        st.session_state.user_name = user.get("nombre", email.split("@")[0])
                        st.session_state.user_role = user.get("rol", "tecnico")
                        st.session_state.login_attempts = 0
                        st.session_state.active_module = "Chats"

                        # Persistencia: guardar en query params
                        st.query_params["uid"] = str(user["id"])

                        send_telegram(f"🔓 Login: {user.get('nombre', email)} ({user.get('rol','')})\n{format_fecha(now_bogota())}")
                        st.success("¡Bienvenido!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.session_state.login_attempts += 1
                        restantes = 5 - st.session_state.login_attempts
                        if st.session_state.login_attempts >= 5:
                            st.session_state.login_blocked_until = now_bogota() + timedelta(minutes=15)
                            st.error("🚫 Demasiados intentos. Bloqueado por 15 minutos.")
                            send_telegram(f"⚠️ Cuenta bloqueada: {email}")
                        else:
                            st.error(f"Credenciales incorrectas. {restantes} intentos restantes.")
                else:
                    st.session_state.login_attempts += 1
                    st.error("Usuario no encontrado.")
            except Exception as e:
                st.error(f"Error de conexión: {e}")

        st.markdown('<p class="disclaimer">JandrexT Soluciones Integrales · NIT 80818905-3<br>Sistema de uso interno exclusivo</p>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
def show_sidebar():
    role = st.session_state.user_role
    name = st.session_state.user_name

    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center; padding: 1rem 0;">
            <div style="font-size:2.5rem;">{'👑' if role=='admin' else '👤'}</div>
            <div style="font-weight:700; font-size:1rem;">{name}</div>
            <div style="font-size:0.75rem; opacity:0.7; text-transform:uppercase;">{
                'Administrador' if role=='admin' else
                'Especialista' if role=='tecnico' else
                'Asesor Comercial' if role=='vendedor' else
                'Aliado'
            }</div>
        </div>
        <hr style="border-color:rgba(255,255,255,0.2);">
        """, unsafe_allow_html=True)

        # MÓDULOS según rol
        modulos_admin = ["Chats", "Proyectos", "Agenda", "Asistencia", "Documentos",
                         "Manuales", "Biblioteca", "Ventas", "Aliados",
                         "Liquidaciones", "Especialistas y Aliados", "Configuración"]
        modulos_tecnico = ["Chats", "Proyectos", "Agenda", "Asistencia", "Documentos", "Manuales"]
        modulos_vendedor = ["Chats", "Proyectos", "Ventas", "Aliados", "Documentos"]
        modulos_cliente = ["Chats", "Proyectos", "Documentos"]

        if role == "admin":
            modulos = modulos_admin
        elif role == "tecnico":
            modulos = modulos_tecnico
        elif role == "vendedor":
            modulos = modulos_vendedor
        else:
            modulos = modulos_cliente

        iconos = {
            "Chats": "💬", "Proyectos": "📁", "Agenda": "📅",
            "Asistencia": "📍", "Documentos": "📄", "Manuales": "📚",
            "Biblioteca": "🗂️", "Ventas": "💰", "Aliados": "🤝",
            "Liquidaciones": "💵", "Especialistas y Aliados": "👥",
            "Configuración": "⚙️"
        }

        st.markdown("**MÓDULOS**")
        for mod in modulos:
            active = "→ " if st.session_state.active_module == mod else ""
            if st.button(f"{iconos.get(mod,'')} {active}{mod}", key=f"nav_{mod}"):
                st.session_state.active_module = mod
                st.rerun()

        st.markdown('<hr style="border-color:rgba(255,255,255,0.2);">', unsafe_allow_html=True)
        if st.button("🚪 Cerrar sesión"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.query_params.clear()
            st.rerun()

# ─────────────────────────────────────────────
# HEADER PRINCIPAL
# ─────────────────────────────────────────────
def show_header(titulo: str):
    saludo = get_saludo()
    name = st.session_state.user_name
    now = format_fecha(now_bogota())
    st.markdown(f"""
    <div class="jandrext-header">
        <div>
            <h1>🔒 {titulo}</h1>
            <div class="lema">Apasionados por el buen servicio</div>
        </div>
        <div style="text-align:right; font-size:0.85rem; opacity:0.85;">
            {saludo}, <strong>{name}</strong><br>
            <span style="font-size:0.75rem; opacity:0.7;">{now}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────
# MÓDULO: CHATS
# ─────────────────────────────────────────────
def modulo_chats():
    show_header("Consultar")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Micrófono Web Speech API
    mic_html = """
    <div id="mic-container" style="margin-bottom:10px;">
        <button id="mic-btn" onclick="toggleMic()" style="
            background: linear-gradient(135deg, #0f3460, #16213e);
            color: white; border: none; border-radius: 50%;
            width: 48px; height: 48px; font-size: 1.3rem;
            cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            transition: all 0.2s;">🎤</button>
        <span id="mic-status" style="margin-left:10px; font-size:0.8rem; color:#666;">
            Presione para hablar
        </span>
        <input type="hidden" id="mic-result" value="">
    </div>
    <script>
    let recognition = null;
    let isListening = false;

    function initRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            document.getElementById('mic-status').textContent = 'Micrófono no soportado en este navegador';
            document.getElementById('mic-btn').disabled = true;
            return null;
        }
        const r = new SpeechRecognition();
        r.lang = 'es-CO';
        r.interimResults = false;
        r.maxAlternatives = 1;
        r.onresult = function(event) {
            const text = event.results[0][0].transcript;
            document.getElementById('mic-result').value = text;
            document.getElementById('mic-status').textContent = '✅ ' + text;
            // Enviar al input de Streamlit
            const inputEl = window.parent.document.querySelector('textarea[aria-label="Escribe tu consulta..."]');
            if (inputEl) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.parent.HTMLTextAreaElement.prototype, 'value').set;
                nativeInputValueSetter.call(inputEl, text);
                inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            }
        };
        r.onerror = function(e) {
            document.getElementById('mic-status').textContent = '⚠️ Error: ' + e.error;
            isListening = false;
            document.getElementById('mic-btn').style.background = 'linear-gradient(135deg, #0f3460, #16213e)';
        };
        r.onend = function() {
            isListening = false;
            document.getElementById('mic-btn').style.background = 'linear-gradient(135deg, #0f3460, #16213e)';
            document.getElementById('mic-btn').textContent = '🎤';
        };
        return r;
    }

    function toggleMic() {
        if (!recognition) recognition = initRecognition();
        if (!recognition) return;
        if (isListening) {
            recognition.stop();
            isListening = false;
        } else {
            recognition.start();
            isListening = true;
            document.getElementById('mic-btn').style.background = 'linear-gradient(135deg, #e94560, #c0392b)';
            document.getElementById('mic-btn').textContent = '⏹️';
            document.getElementById('mic-status').textContent = '🔴 Escuchando...';
        }
    }
    </script>
    """

    st.components.v1.html(mic_html, height=70)

    # Historial
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(f'<div class="chat-msg-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-msg-bot">🤖 {msg["content"]}</div>', unsafe_allow_html=True)

    # Input
    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_area("Escribe tu consulta...", key="chat_input", height=80, label_visibility="visible")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        enviar = st.button("Consultar →", use_container_width=True)
        limpiar = st.button("🗑️ Limpiar", use_container_width=True)

    if limpiar:
        st.session_state.chat_history = []
        st.rerun()

    if enviar and user_input.strip():
        system_prompt = f"""Eres el asistente empresarial de JandrexT Soluciones Integrales, 
        empresa colombiana de seguridad electrónica. Servicios: CCTV, automatización de accesos, 
        control de acceso y biometría, cerca eléctrica, redes, eléctrico, software.
        Responde en español, de forma profesional y concisa.
        Usuario actual: {st.session_state.user_name} ({st.session_state.user_role})."""

        with st.spinner("Procesando consulta..."):
            respuesta = consultar_ia(user_input.strip(), system_prompt)

        st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})
        st.session_state.chat_history.append({"role": "assistant", "content": respuesta})

        # Guardar en Supabase
        try:
            supabase.table("chats").insert({
                "usuario_id": st.session_state.user_id,
                "mensaje": user_input.strip(),
                "respuesta": respuesta,
                "created_at": now_bogota().isoformat()
            }).execute()
        except:
            pass

        st.rerun()

    st.markdown('<p class="disclaimer">Las respuestas son orientativas. Verifique con personal técnico.</p>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# MÓDULO: PROYECTOS
# ─────────────────────────────────────────────
def modulo_proyectos():
    show_header("Proyectos")
    role = st.session_state.user_role

    tab1, tab2 = st.tabs(["📋 Lista de Proyectos", "➕ Nuevo Proyecto"])

    with tab1:
        try:
            if role == "admin":
                result = supabase.table("proyectos").select("*").order("created_at", desc=True).execute()
            elif role == "tecnico":
                result = supabase.table("proyectos").select("*").eq("especialista_id", st.session_state.user_id).order("created_at", desc=True).execute()
            else:
                result = supabase.table("proyectos").select("*").eq("cliente_id", st.session_state.user_id).order("created_at", desc=True).execute()

            proyectos = result.data or []

            if not proyectos:
                st.info("No hay proyectos registrados.")
            else:
                for p in proyectos:
                    estado = p.get("estado", "activo")
                    badge_class = "badge-active" if estado == "activo" else "badge-pending" if estado == "pendiente" else "badge-closed"
                    with st.expander(f"📁 {p.get('nombre','Sin nombre')} — {p.get('servicio','')}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Cliente (Aliado):** {p.get('cliente_nombre','')}")
                            st.markdown(f"**Servicio:** {p.get('servicio','')}")
                            st.markdown(f"**Fecha inicio:** {format_fecha(p.get('fecha_inicio',''))}")
                        with col2:
                            st.markdown(f"**Estado:** <span class='status-badge {badge_class}'>{estado.upper()}</span>", unsafe_allow_html=True)
                            st.markdown(f"**Dirección:** {p.get('direccion','')}")
                            st.markdown(f"**Valor:** ${p.get('valor',0):,.0f}")

                        if p.get("descripcion"):
                            st.markdown(f"**Descripción:** {p.get('descripcion','')}")

                        if role == "admin":
                            col_a, col_b = st.columns(2)
                            with col_a:
                                nuevo_estado = st.selectbox("Cambiar estado", ["activo","pendiente","cerrado","cancelado"],
                                                            index=["activo","pendiente","cerrado","cancelado"].index(estado) if estado in ["activo","pendiente","cerrado","cancelado"] else 0,
                                                            key=f"estado_{p['id']}")
                                if st.button("Actualizar", key=f"upd_{p['id']}"):
                                    supabase.table("proyectos").update({"estado": nuevo_estado}).eq("id", p["id"]).execute()
                                    st.success("Actualizado")
                                    st.rerun()
        except Exception as e:
            st.error(f"Error cargando proyectos: {e}")

    with tab2:
        if role not in ["admin", "vendedor"]:
            st.warning("Solo administradores y asesores pueden crear proyectos.")
            return

        with st.form("nuevo_proyecto"):
            st.markdown('<div class="section-title">Nuevo Proyecto</div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input("Nombre del proyecto *")
                servicio = st.selectbox("Línea de servicio *", [
                    "CCTV", "Automatización de accesos", "Control de acceso y biometría",
                    "Cerca eléctrica", "Redes", "Eléctrico", "Software", "Otro"
                ])
                cliente_nombre = st.text_input("Nombre del Aliado (cliente) *")
                direccion = st.text_input("Dirección del proyecto")
            with col2:
                valor = st.number_input("Valor del proyecto ($)", min_value=0, step=50000)
                fecha_inicio = st.date_input("Fecha inicio", value=date.today())
                estado = st.selectbox("Estado inicial", ["activo","pendiente"])
                descripcion = st.text_area("Descripción", height=100)

            submitted = st.form_submit_button("Crear Proyecto →")
            if submitted:
                if not nombre or not cliente_nombre:
                    st.error("Complete los campos obligatorios")
                else:
                    try:
                        supabase.table("proyectos").insert({
                            "nombre": nombre,
                            "servicio": servicio,
                            "cliente_nombre": cliente_nombre,
                            "direccion": direccion,
                            "valor": valor,
                            "fecha_inicio": fecha_inicio.isoformat(),
                            "estado": estado,
                            "descripcion": descripcion,
                            "creado_por": st.session_state.user_id,
                            "created_at": now_bogota().isoformat()
                        }).execute()
                        st.success(f"✅ Proyecto '{nombre}' creado exitosamente")
                        send_telegram(f"📁 Nuevo proyecto: {nombre}\nServicio: {servicio}\nAliado: {cliente_nombre}")
                    except Exception as e:
                        st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: AGENDA
# ─────────────────────────────────────────────
def modulo_agenda():
    show_header("Agenda")
    role = st.session_state.user_role

    tab1, tab2 = st.tabs(["📅 Eventos", "➕ Nuevo Evento"])

    with tab1:
        try:
            if role == "admin":
                result = supabase.table("agenda").select("*").order("fecha", desc=False).execute()
            else:
                result = supabase.table("agenda").select("*").eq("usuario_id", st.session_state.user_id).order("fecha", desc=False).execute()

            eventos = result.data or []
            hoy = date.today()

            proximos = [e for e in eventos if e.get("fecha", "") >= hoy.isoformat()]
            pasados = [e for e in eventos if e.get("fecha", "") < hoy.isoformat()]

            st.markdown("### Próximos eventos")
            if not proximos:
                st.info("No hay eventos próximos.")
            for e in proximos[:10]:
                with st.expander(f"📅 {e.get('fecha','')} — {e.get('titulo','')}"):
                    st.markdown(f"**Hora:** {e.get('hora','')}")
                    st.markdown(f"**Tipo:** {e.get('tipo','')}")
                    st.markdown(f"**Descripción:** {e.get('descripcion','')}")
                    st.markdown(f"**Lugar:** {e.get('lugar','')}")

            if pasados:
                with st.expander("📂 Eventos pasados"):
                    for e in pasados[-10:]:
                        st.markdown(f"- {e.get('fecha','')} · {e.get('titulo','')}")
        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        with st.form("nuevo_evento"):
            st.markdown('<div class="section-title">Nuevo Evento</div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                titulo = st.text_input("Título del evento *")
                tipo = st.selectbox("Tipo", ["Visita técnica", "Instalación", "Mantenimiento", "Reunión", "Capacitación", "Otro"])
                fecha = st.date_input("Fecha *", value=date.today())
            with col2:
                hora = st.time_input("Hora")
                lugar = st.text_input("Lugar / Dirección")
                descripcion = st.text_area("Descripción", height=80)

            submitted = st.form_submit_button("Agendar →")
            if submitted and titulo:
                try:
                    supabase.table("agenda").insert({
                        "titulo": titulo,
                        "tipo": tipo,
                        "fecha": fecha.isoformat(),
                        "hora": hora.strftime("%H:%M"),
                        "lugar": lugar,
                        "descripcion": descripcion,
                        "usuario_id": st.session_state.user_id,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Evento '{titulo}' agendado para {fecha}")
                    send_telegram(f"📅 Nuevo evento: {titulo}\nFecha: {fecha} {hora.strftime('%H:%M')}\nLugar: {lugar}")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: ASISTENCIA (GPS)
# ─────────────────────────────────────────────
def modulo_asistencia():
    show_header("Asistencia")

    gps_html = """
    <div id="gps-container" style="padding:1rem; background:#f8f9fa; border-radius:10px; margin-bottom:1rem;">
        <h4 style="margin:0 0 0.5rem 0; color:#0f3460;">📍 Verificación de ubicación</h4>
        <button onclick="getLocation()" style="
            background: linear-gradient(135deg, #0f3460, #16213e);
            color:white; border:none; border-radius:8px;
            padding: 0.6rem 1.5rem; cursor:pointer; font-size:0.9rem;">
            Obtener ubicación GPS
        </button>
        <div id="gps-result" style="margin-top:0.8rem; font-size:0.85rem; color:#333;"></div>
        <div id="map-container" style="margin-top:1rem;"></div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script>
    let map = null;
    function getLocation() {
        if (!navigator.geolocation) {
            document.getElementById('gps-result').innerHTML = '⚠️ GPS no disponible en este dispositivo.';
            return;
        }
        document.getElementById('gps-result').textContent = '🔍 Obteniendo ubicación...';
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                const lat = pos.coords.latitude.toFixed(6);
                const lng = pos.coords.longitude.toFixed(6);
                const acc = pos.coords.accuracy.toFixed(0);
                document.getElementById('gps-result').innerHTML =
                    '✅ Lat: <b>' + lat + '</b> | Lng: <b>' + lng + '</b> | Precisión: ' + acc + 'm';

                // Mapa Leaflet
                const mc = document.getElementById('map-container');
                mc.style.height = '250px';
                mc.style.borderRadius = '8px';
                if (map) { map.remove(); }
                map = L.map('map-container').setView([lat, lng], 16);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
                L.marker([lat, lng]).addTo(map).bindPopup('📍 Mi ubicación').openPopup();
            },
            function(err) {
                document.getElementById('gps-result').textContent = '⚠️ Error GPS: ' + err.message;
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    }
    </script>
    """
    st.components.v1.html(gps_html, height=420)

    tab1, tab2 = st.tabs(["📋 Mis registros", "✅ Registrar asistencia"])

    with tab2:
        with st.form("registro_asistencia"):
            tipo = st.selectbox("Tipo de registro", ["Entrada", "Salida", "Inicio de trabajo", "Fin de trabajo", "Pausa"])
            proyecto = st.text_input("Proyecto / Orden de trabajo")
            notas = st.text_area("Observaciones", height=80)
            submitted = st.form_submit_button("Registrar →")
            if submitted:
                try:
                    supabase.table("asistencia").insert({
                        "usuario_id": st.session_state.user_id,
                        "tipo": tipo,
                        "proyecto": proyecto,
                        "notas": notas,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Registro de {tipo} guardado — {format_fecha(now_bogota())}")
                except Exception as e:
                    st.error(f"Error: {e}")

    with tab1:
        try:
            result = supabase.table("asistencia").select("*").eq("usuario_id", st.session_state.user_id).order("created_at", desc=True).limit(20).execute()
            registros = result.data or []
            if not registros:
                st.info("No hay registros de asistencia.")
            for r in registros:
                st.markdown(f"- **{format_fecha(r.get('created_at',''))}** — {r.get('tipo','')} · {r.get('proyecto','')}")
        except Exception as e:
            st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: DOCUMENTOS
# ─────────────────────────────────────────────
def modulo_documentos():
    show_header("Documentos")

    SERVICIOS = ["CCTV", "Automatización de accesos", "Control de acceso y biometría",
                 "Cerca eléctrica", "Redes", "Eléctrico", "Software"]

    CHECKLISTS = {
        "CCTV": ["Verificar alimentación eléctrica","Revisar cableado UTP/coaxial","Configurar grabador DVR/NVR","Ajustar ángulo de cámaras","Prueba de grabación nocturna","Configurar acceso remoto"],
        "Automatización de accesos": ["Verificar motor/actuador","Probar sensores magnéticos","Configurar control remoto","Ajustar tiempos de apertura","Probar en modo manual","Verificar final de carrera"],
        "Control de acceso y biometría": ["Enrollar huellas/tarjetas","Configurar horarios de acceso","Probar lector biométrico","Verificar cerradura eléctrica","Configurar alarma anti-intrusión","Prueba de acceso"],
        "Cerca eléctrica": ["Verificar tensión del pulso (8-12kV)","Revisar aisladores","Probar sirena de alarma","Verificar toma a tierra","Revisar tensores del alambre","Probar energizador"],
        "Redes": ["Verificar cableado estructurado","Configurar switch/router","Probar conectividad","Documentar IPs asignadas","Prueba de velocidad","Organizar rack"],
        "Eléctrico": ["Verificar tablero eléctrico","Medir voltaje en puntos","Probar breakers","Verificar puesta a tierra","Revisar calibre de cables","Documentar circuitos"],
        "Software": ["Instalar/actualizar software","Configurar usuarios","Probar funcionalidades","Verificar backups","Documentar configuración","Capacitar usuario"]
    }

    tab1, tab2, tab3 = st.tabs(["📄 Generar Informe", "📋 Acta de Servicio", "📂 Documentos Guardados"])

    with tab1:
        st.markdown('<div class="section-title">Generador de Informe Técnico</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            cliente = st.text_input("Aliado (cliente) *")
            servicio = st.selectbox("Servicio *", SERVICIOS)
            direccion = st.text_input("Dirección del servicio")
            fecha_serv = st.date_input("Fecha del servicio", value=date.today())
        with col2:
            tecnico_nombre = st.text_input("Especialista", value=st.session_state.user_name)
            equipo = st.text_input("Equipos instalados / intervenidos")
            observaciones = st.text_area("Observaciones / trabajo realizado", height=120)

        # Checklist
        st.markdown("**✅ Checklist de verificación**")
        checks = CHECKLISTS.get(servicio, [])
        checklist_completado = {}
        cols = st.columns(2)
        for i, item in enumerate(checks):
            with cols[i % 2]:
                checklist_completado[item] = st.checkbox(item, key=f"chk_{i}")

        if st.button("Vista previa del informe →"):
            checks_ok = [k for k, v in checklist_completado.items() if v]
            checks_no = [k for k, v in checklist_completado.items() if not v]

            prompt = f"""Genera un informe técnico profesional para JandrexT Soluciones Integrales.
            Aliado: {cliente}
            Servicio: {servicio}
            Dirección: {direccion}
            Fecha: {fecha_serv}
            Especialista: {tecnico_nombre}
            Equipos: {equipo}
            Observaciones: {observaciones}
            Verificaciones completadas: {', '.join(checks_ok) if checks_ok else 'Ninguna'}
            Verificaciones pendientes: {', '.join(checks_no) if checks_no else 'Ninguna'}
            
            Redacta el informe en formato profesional, en español, con introducción, desarrollo y conclusiones."""

            with st.spinner("Generando informe..."):
                informe = consultar_ia(prompt)

            st.session_state["informe_preview"] = informe
            st.session_state["informe_data"] = {
                "cliente": cliente, "servicio": servicio, "fecha": str(fecha_serv),
                "tecnico": tecnico_nombre, "informe": informe
            }

        if "informe_preview" in st.session_state:
            st.markdown("---")
            st.markdown("### Vista previa del informe")
            st.markdown(st.session_state["informe_preview"])

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Confirmar y guardar"):
                    try:
                        data = st.session_state["informe_data"]
                        supabase.table("documentos").insert({
                            "tipo": "Informe técnico",
                            "cliente": data["cliente"],
                            "servicio": data["servicio"],
                            "fecha": data["fecha"],
                            "contenido": data["informe"],
                            "creado_por": st.session_state.user_id,
                            "created_at": now_bogota().isoformat()
                        }).execute()
                        st.success("✅ Informe guardado")
                        del st.session_state["informe_preview"]
                    except Exception as e:
                        st.error(f"Error: {e}")

            with col_b:
                # Descarga HTML
                html_content = f"""<!DOCTYPE html>
                <html><head><meta charset='UTF-8'>
                <title>Informe Técnico - {cliente}</title>
                <style>
                body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:20px;color:#333;}}
                h1{{color:#0f3460;border-bottom:3px solid #e94560;padding-bottom:10px;}}
                .header{{background:#0f3460;color:white;padding:20px;border-radius:8px;margin-bottom:20px;}}
                .content{{line-height:1.8;}}
                .footer{{margin-top:40px;color:#999;font-size:0.8rem;border-top:1px solid #eee;padding-top:10px;}}
                </style></head>
                <body>
                <div class='header'>
                    <h2 style='margin:0;color:white;'>🔒 JandrexT Soluciones Integrales</h2>
                    <p style='margin:0;opacity:0.8;'>Apasionados por el buen servicio</p>
                </div>
                <h1>Informe Técnico</h1>
                <p><strong>Aliado:</strong> {cliente}<br>
                <strong>Servicio:</strong> {servicio}<br>
                <strong>Fecha:</strong> {fecha_serv}<br>
                <strong>Especialista:</strong> {tecnico_nombre}</p>
                <hr>
                <div class='content'>{st.session_state.get('informe_preview','').replace(chr(10),'<br>')}</div>
                <div class='footer'>
                    Generado por JandrexT IA · {format_fecha(now_bogota())}<br>
                    NIT: 80818905-3 · proyectos@jandrext.com
                </div>
                </body></html>"""

                b64 = base64.b64encode(html_content.encode()).decode()
                filename = f"Informe_{cliente.replace(' ','_')}_{fecha_serv}.html"
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" download="{filename}" '
                    f'style="display:inline-block;padding:0.5rem 1rem;background:#0f3460;color:white;'
                    f'border-radius:8px;text-decoration:none;font-weight:600;">⬇️ Descargar HTML</a>',
                    unsafe_allow_html=True
                )

    with tab2:
        st.markdown('<div class="section-title">Acta de Servicio</div>', unsafe_allow_html=True)
        with st.form("acta_servicio"):
            col1, col2 = st.columns(2)
            with col1:
                acta_cliente = st.text_input("Aliado *")
                acta_servicio = st.selectbox("Servicio", SERVICIOS, key="acta_serv")
                acta_fecha = st.date_input("Fecha", value=date.today(), key="acta_fecha")
                acta_valor = st.number_input("Valor del servicio ($)", min_value=0, step=10000)
            with col2:
                acta_tecnico = st.text_input("Especialista", value=st.session_state.user_name, key="acta_tec")
                acta_garantia = st.selectbox("Garantía", ["Sin garantía","1 mes","3 meses","6 meses","1 año"])
                acta_estado = st.selectbox("Estado del servicio", ["Completado","Parcial","Pendiente revisión"])

            acta_descripcion = st.text_area("Descripción del trabajo realizado *", height=100)
            acta_observaciones = st.text_area("Observaciones del Aliado", height=60)

            submitted = st.form_submit_button("Generar Acta →")
            if submitted and acta_cliente and acta_descripcion:
                try:
                    from datetime import date as dt_date
                    num = supabase.rpc("siguiente_numero_acta", {}).execute()
                    numero_acta = f"ACTA-{now_bogota().year}-{str(getattr(num, 'data', 1) or 1).zfill(4)}"
                except:
                    numero_acta = f"ACTA-{now_bogota().strftime('%Y%m%d%H%M')}"

                html_acta = f"""<!DOCTYPE html>
                <html><head><meta charset='UTF-8'><title>Acta {numero_acta}</title>
                <style>
                body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:30px;}}
                .header{{background:#0f3460;color:white;padding:20px;border-radius:8px;text-align:center;}}
                table{{width:100%;border-collapse:collapse;margin:20px 0;}}
                td,th{{border:1px solid #ddd;padding:10px;}}
                th{{background:#f0f4f8;font-weight:600;width:35%;}}
                .firma{{margin-top:60px;display:flex;justify-content:space-around;}}
                .firma-box{{text-align:center;width:200px;border-top:2px solid #333;padding-top:10px;}}
                .footer{{color:#999;font-size:0.75rem;text-align:center;margin-top:30px;}}
                </style></head><body>
                <div class='header'>
                    <h2 style='margin:0;'>JANDREXT SOLUCIONES INTEGRALES</h2>
                    <p style='margin:0;opacity:0.85;'>Apasionados por el buen servicio · NIT: 80818905-3</p>
                </div>
                <h2 style='text-align:center;color:#0f3460;margin:20px 0;'>ACTA DE SERVICIO N° {numero_acta}</h2>
                <table>
                    <tr><th>Aliado</th><td>{acta_cliente}</td></tr>
                    <tr><th>Servicio</th><td>{acta_servicio}</td></tr>
                    <tr><th>Fecha</th><td>{acta_fecha}</td></tr>
                    <tr><th>Especialista</th><td>{acta_tecnico}</td></tr>
                    <tr><th>Valor</th><td>${acta_valor:,.0f} COP</td></tr>
                    <tr><th>Garantía</th><td>{acta_garantia}</td></tr>
                    <tr><th>Estado</th><td>{acta_estado}</td></tr>
                    <tr><th>Descripción</th><td>{acta_descripcion}</td></tr>
                    <tr><th>Observaciones</th><td>{acta_observaciones}</td></tr>
                </table>
                <div class='firma'>
                    <div class='firma-box'>Especialista<br><small>{acta_tecnico}</small></div>
                    <div class='firma-box'>Aliado<br><small>{acta_cliente}</small></div>
                </div>
                <div class='footer'>JandrexT Soluciones Integrales · proyectos@jandrext.com · {format_fecha(now_bogota())}</div>
                </body></html>"""

                b64 = base64.b64encode(html_acta.encode()).decode()
                filename = f"Acta_{numero_acta}_{acta_cliente.replace(' ','_')}.html"
                st.success(f"✅ Acta {numero_acta} generada")
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" download="{filename}" '
                    f'style="display:inline-block;padding:0.5rem 1.5rem;background:#0f3460;color:white;'
                    f'border-radius:8px;text-decoration:none;font-weight:600;margin-top:10px;">⬇️ Descargar Acta HTML</a>',
                    unsafe_allow_html=True
                )

                try:
                    supabase.table("documentos").insert({
                        "tipo": "Acta de servicio",
                        "numero": numero_acta,
                        "cliente": acta_cliente,
                        "servicio": acta_servicio,
                        "fecha": str(acta_fecha),
                        "contenido": acta_descripcion,
                        "valor": acta_valor,
                        "creado_por": st.session_state.user_id,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                except:
                    pass

    with tab3:
        try:
            if st.session_state.user_role == "admin":
                result = supabase.table("documentos").select("*").order("created_at", desc=True).limit(30).execute()
            else:
                result = supabase.table("documentos").select("*").eq("creado_por", st.session_state.user_id).order("created_at", desc=True).limit(20).execute()

            docs = result.data or []
            if not docs:
                st.info("No hay documentos guardados.")
            for d in docs:
                with st.expander(f"📄 {d.get('tipo','')} — {d.get('cliente','')} | {d.get('fecha','')}"):
                    st.markdown(f"**Servicio:** {d.get('servicio','')}")
                    st.markdown(f"**Número:** {d.get('numero','—')}")
                    if d.get("contenido"):
                        st.text_area("Contenido", value=d.get("contenido",""), height=100, key=f"cont_{d['id']}", disabled=True)
        except Exception as e:
            st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: MANUALES
# ─────────────────────────────────────────────
def modulo_manuales():
    show_header("Manuales Técnicos")

    tab1, tab2 = st.tabs(["📚 Consultar Manual", "➕ Agregar Manual"])

    with tab1:
        busqueda = st.text_input("🔍 Buscar manual...", placeholder="Ej: CCTV Hikvision, control de acceso...")

        try:
            if busqueda:
                result = supabase.table("manuales").select("*").ilike("titulo", f"%{busqueda}%").execute()
            else:
                result = supabase.table("manuales").select("*").order("created_at", desc=True).limit(20).execute()

            manuales = result.data or []
            if not manuales:
                st.info("No se encontraron manuales.")
            for m in manuales:
                with st.expander(f"📖 {m.get('titulo','')} — {m.get('categoria','')}"):
                    st.markdown(m.get("contenido",""))
                    if m.get("url"):
                        st.markdown(f"[🔗 Ver recurso externo]({m.get('url')})")
        except Exception as e:
            st.error(f"Error: {e}")

        st.markdown("---")
        st.markdown("### 💡 Consulta rápida")
        pregunta = st.text_input("¿Qué necesitas saber?", placeholder="Ej: Cómo configurar una cámara IP...")
        if st.button("Consultar base de conocimiento →") and pregunta:
            system = """Eres un experto técnico de JandrexT en seguridad electrónica colombiana.
            Especialidades: CCTV, control de acceso, biometría, cerca eléctrica, automatización, redes, eléctrico.
            Da respuestas técnicas claras y prácticas en español."""
            with st.spinner("Consultando..."):
                resp = consultar_ia(pregunta, system)
            st.markdown(f'<div class="info-box">{resp}</div>', unsafe_allow_html=True)

    with tab2:
        if st.session_state.user_role not in ["admin", "tecnico"]:
            st.warning("Solo Especialistas y Administradores pueden agregar manuales.")
            return
        with st.form("nuevo_manual"):
            titulo = st.text_input("Título del manual *")
            categoria = st.selectbox("Categoría", ["CCTV","Control de acceso","Biometría","Cerca eléctrica","Automatización","Redes","Eléctrico","General"])
            contenido = st.text_area("Contenido *", height=200)
            url = st.text_input("URL de recurso externo (opcional)")
            submitted = st.form_submit_button("Guardar Manual →")
            if submitted and titulo and contenido:
                try:
                    supabase.table("manuales").insert({
                        "titulo": titulo,
                        "categoria": categoria,
                        "contenido": contenido,
                        "url": url,
                        "creado_por": st.session_state.user_id,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success("✅ Manual guardado")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: BIBLIOTECA
# ─────────────────────────────────────────────
def modulo_biblioteca():
    show_header("Biblioteca de Recursos")

    tab1, tab2 = st.tabs(["📂 Recursos", "➕ Agregar Recurso"])

    with tab1:
        categoria_filter = st.selectbox("Filtrar por categoría", ["Todos","CCTV","Control de acceso","Redes","Eléctrico","Formatos","Videos","Proveedores","Otro"])
        try:
            if categoria_filter == "Todos":
                result = supabase.table("biblioteca").select("*").order("created_at", desc=True).execute()
            else:
                result = supabase.table("biblioteca").select("*").eq("categoria", categoria_filter).execute()
            recursos = result.data or []
            if not recursos:
                st.info("No hay recursos en esta categoría.")
            for r in recursos:
                col1, col2 = st.columns([3,1])
                with col1:
                    st.markdown(f"**{r.get('titulo','')}** — *{r.get('categoria','')}*")
                    if r.get("descripcion"):
                        st.caption(r.get("descripcion",""))
                with col2:
                    if r.get("url"):
                        st.markdown(f"[🔗 Abrir]({r.get('url')})")
                st.divider()
        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        with st.form("nuevo_recurso"):
            titulo = st.text_input("Título del recurso *")
            categoria = st.selectbox("Categoría", ["CCTV","Control de acceso","Redes","Eléctrico","Formatos","Videos","Proveedores","Otro"])
            descripcion = st.text_area("Descripción")
            url = st.text_input("Enlace / URL")
            submitted = st.form_submit_button("Agregar →")
            if submitted and titulo:
                try:
                    supabase.table("biblioteca").insert({
                        "titulo": titulo,
                        "categoria": categoria,
                        "descripcion": descripcion,
                        "url": url,
                        "creado_por": st.session_state.user_id,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success("✅ Recurso agregado")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: VENTAS
# ─────────────────────────────────────────────
def modulo_ventas():
    show_header("Ventas")
    role = st.session_state.user_role

    tab1, tab2, tab3 = st.tabs(["📊 Pipeline", "💰 Nueva Oportunidad", "📋 Cotizaciones"])

    with tab1:
        try:
            if role == "admin":
                result = supabase.table("ventas").select("*").order("created_at", desc=True).execute()
            else:
                result = supabase.table("ventas").select("*").eq("vendedor_id", st.session_state.user_id).order("created_at", desc=True).execute()

            ventas = result.data or []
            if not ventas:
                st.info("No hay oportunidades registradas.")
                return

            # Métricas
            total = sum(v.get("valor",0) for v in ventas)
            ganadas = [v for v in ventas if v.get("estado") == "ganada"]
            perdidas = [v for v in ventas if v.get("estado") == "perdida"]
            en_proceso = [v for v in ventas if v.get("estado") not in ["ganada","perdida"]]

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f'<div class="metric-card"><h3>{len(ventas)}</h3><p>Total oportunidades</p></div>', unsafe_allow_html=True)
            with col2:
                st.markdown(f'<div class="metric-card"><h3>{len(ganadas)}</h3><p>Ganadas</p></div>', unsafe_allow_html=True)
            with col3:
                st.markdown(f'<div class="metric-card"><h3>{len(en_proceso)}</h3><p>En proceso</p></div>', unsafe_allow_html=True)
            with col4:
                st.markdown(f'<div class="metric-card"><h3>${total/1e6:.1f}M</h3><p>Valor total</p></div>', unsafe_allow_html=True)

            for v in ventas[:15]:
                estado = v.get("estado","prospecto")
                badge = "badge-active" if estado=="ganada" else "badge-pending" if estado in ["prospecto","propuesta","negociación"] else "badge-closed"
                with st.expander(f"💰 {v.get('cliente','')} — ${v.get('valor',0):,.0f}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Servicio:** {v.get('servicio','')}")
                        st.markdown(f"**Estado:** <span class='status-badge {badge}'>{estado.upper()}</span>", unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"**Fecha:** {v.get('fecha','')}")
                        st.markdown(f"**Asesor:** {v.get('vendedor_nombre','')}")
                    if v.get("notas"):
                        st.caption(v.get("notas",""))

        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        with st.form("nueva_venta"):
            col1, col2 = st.columns(2)
            with col1:
                cliente = st.text_input("Aliado (cliente) *")
                servicio = st.selectbox("Servicio", ["CCTV","Automatización de accesos","Control de acceso y biometría","Cerca eléctrica","Redes","Eléctrico","Software","Paquete integral"])
                valor = st.number_input("Valor estimado ($)", min_value=0, step=100000)
            with col2:
                estado = st.selectbox("Estado", ["prospecto","propuesta","negociación","ganada","perdida"])
                fecha = st.date_input("Fecha", value=date.today())
                notas = st.text_area("Notas", height=80)

            submitted = st.form_submit_button("Registrar Oportunidad →")
            if submitted and cliente:
                try:
                    supabase.table("ventas").insert({
                        "cliente": cliente,
                        "servicio": servicio,
                        "valor": valor,
                        "estado": estado,
                        "fecha": fecha.isoformat(),
                        "notas": notas,
                        "vendedor_id": st.session_state.user_id,
                        "vendedor_nombre": st.session_state.user_name,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Oportunidad con {cliente} registrada")
                except Exception as e:
                    st.error(f"Error: {e}")

    with tab3:
        st.markdown("### Generar cotización")
        with st.form("cotizacion"):
            col1, col2 = st.columns(2)
            with col1:
                cot_cliente = st.text_input("Aliado *")
                cot_servicio = st.multiselect("Servicios a cotizar", ["CCTV","Automatización de accesos","Control de acceso y biometría","Cerca eléctrica","Redes","Eléctrico","Software"])
                cot_descripcion = st.text_area("Descripción del requerimiento", height=100)
            with col2:
                cot_valor = st.number_input("Valor total ($)", min_value=0, step=50000)
                cot_validez = st.selectbox("Validez de la oferta", ["15 días","30 días","60 días"])
                cot_incluye = st.text_area("Incluye", height=80, value="Materiales, mano de obra y garantía")

            submitted = st.form_submit_button("Generar Cotización →")
            if submitted and cot_cliente:
                try:
                    num_cot = f"COT-{now_bogota().strftime('%Y%m%d%H%M')}"
                except:
                    num_cot = "COT-001"

                html_cot = f"""<!DOCTYPE html>
                <html><head><meta charset='UTF-8'><title>Cotización {num_cot}</title>
                <style>
                body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:30px;color:#333;}}
                .header{{background:#0f3460;color:white;padding:20px;border-radius:8px;}}
                table{{width:100%;border-collapse:collapse;margin:20px 0;}}
                td,th{{border:1px solid #ddd;padding:12px;}}
                th{{background:#f0f4f8;}}
                .total{{background:#0f3460;color:white;font-size:1.2rem;font-weight:bold;}}
                .footer{{color:#999;font-size:0.75rem;text-align:center;margin-top:30px;}}
                </style></head><body>
                <div class='header'>
                    <h2 style='margin:0;color:white;'>JANDREXT SOLUCIONES INTEGRALES</h2>
                    <p style='margin:0;opacity:0.8;'>NIT: 80818905-3 · proyectos@jandrext.com</p>
                </div>
                <h2 style='color:#0f3460;'>COTIZACIÓN N° {num_cot}</h2>
                <p><strong>Aliado:</strong> {cot_cliente}<br>
                <strong>Fecha:</strong> {date.today()}<br>
                <strong>Validez:</strong> {cot_validez}<br>
                <strong>Asesor:</strong> {st.session_state.user_name}</p>
                <table>
                    <tr><th>Servicio</th><th>Descripción</th><th>Valor</th></tr>
                    <tr><td>{', '.join(cot_servicio)}</td><td>{cot_descripcion}</td><td>${cot_valor:,.0f}</td></tr>
                    <tr class='total'><td colspan='2'>TOTAL</td><td>${cot_valor:,.0f} COP</td></tr>
                </table>
                <p><strong>Incluye:</strong> {cot_incluye}</p>
                <div class='footer'>Apasionados por el buen servicio · {format_fecha(now_bogota())}</div>
                </body></html>"""

                b64 = base64.b64encode(html_cot.encode()).decode()
                fn = f"Cotizacion_{num_cot}_{cot_cliente.replace(' ','_')}.html"
                st.success(f"✅ Cotización {num_cot} generada")
                st.markdown(f'<a href="data:text/html;base64,{b64}" download="{fn}" style="display:inline-block;padding:0.5rem 1.5rem;background:#0f3460;color:white;border-radius:8px;text-decoration:none;font-weight:600;">⬇️ Descargar Cotización</a>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# MÓDULO: ALIADOS
# ─────────────────────────────────────────────
def modulo_aliados():
    show_header("Aliados")
    role = st.session_state.user_role

    tab1, tab2 = st.tabs(["👥 Lista de Aliados", "➕ Nuevo Aliado"])

    with tab1:
        busqueda = st.text_input("🔍 Buscar aliado...", placeholder="Nombre, empresa, NIT...")
        try:
            if busqueda:
                result = supabase.table("clientes").select("*").or_(
                    f"nombre.ilike.%{busqueda}%,empresa.ilike.%{busqueda}%,nit.ilike.%{busqueda}%"
                ).execute()
            else:
                result = supabase.table("clientes").select("*").order("nombre").execute()

            aliados = result.data or []
            if not aliados:
                st.info("No se encontraron aliados.")
            for a in aliados:
                with st.expander(f"🤝 {a.get('nombre','')} — {a.get('empresa','')}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**NIT/CC:** {a.get('nit','')}")
                        st.markdown(f"**Teléfono:** {a.get('telefono','')}")
                        st.markdown(f"**Email:** {a.get('email','')}")
                    with col2:
                        st.markdown(f"**Dirección:** {a.get('direccion','')}")
                        st.markdown(f"**Ciudad:** {a.get('ciudad','')}")
                        st.markdown(f"**Servicios:** {a.get('servicios','')}")
        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        with st.form("nuevo_aliado"):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input("Nombre completo *")
                empresa = st.text_input("Empresa / Razón social")
                nit = st.text_input("NIT / Cédula *")
                email = st.text_input("Email")
            with col2:
                telefono = st.text_input("Teléfono")
                direccion = st.text_input("Dirección")
                ciudad = st.text_input("Ciudad", value="Bogotá")
                servicios = st.multiselect("Servicios de interés",
                    ["CCTV","Automatización de accesos","Control de acceso y biometría","Cerca eléctrica","Redes","Eléctrico","Software"])

            notas = st.text_area("Notas adicionales", height=60)
            submitted = st.form_submit_button("Registrar Aliado →")
            if submitted and nombre and nit:
                try:
                    supabase.table("clientes").insert({
                        "nombre": nombre,
                        "empresa": empresa,
                        "nit": nit,
                        "email": email,
                        "telefono": telefono,
                        "direccion": direccion,
                        "ciudad": ciudad,
                        "servicios": ", ".join(servicios),
                        "notas": notas,
                        "creado_por": st.session_state.user_id,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Aliado '{nombre}' registrado exitosamente")
                    send_telegram(f"🤝 Nuevo Aliado: {nombre} — {empresa}")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: LIQUIDACIONES
# ─────────────────────────────────────────────
def modulo_liquidaciones():
    show_header("Liquidaciones")
    role = st.session_state.user_role

    tab1, tab2 = st.tabs(["📋 Liquidaciones", "➕ Nueva Liquidación"])

    with tab1:
        try:
            if role == "admin":
                result = supabase.table("liquidaciones").select("*").order("created_at", desc=True).execute()
            else:
                result = supabase.table("liquidaciones").select("*").eq("tecnico_id", st.session_state.user_id).order("created_at", desc=True).execute()

            liquidaciones = result.data or []
            if not liquidaciones:
                st.info("No hay liquidaciones registradas.")

            total_pendiente = sum(l.get("valor",0) for l in liquidaciones if l.get("estado") != "pagada")
            st.markdown(f'<div class="metric-card"><h3>${total_pendiente:,.0f}</h3><p>Total pendiente de pago</p></div>', unsafe_allow_html=True)

            for l in liquidaciones:
                estado = l.get("estado","pendiente")
                badge = "badge-active" if estado == "pagada" else "badge-pending"
                with st.expander(f"💵 {l.get('tecnico_nombre','')} — ${l.get('valor',0):,.0f} | {estado.upper()}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Período:** {l.get('periodo','')}")
                        st.markdown(f"**Proyectos:** {l.get('proyectos','')}")
                    with col2:
                        st.markdown(f"**Estado:** <span class='status-badge {badge}'>{estado}</span>", unsafe_allow_html=True)
                        st.markdown(f"**Fecha:** {format_fecha(l.get('created_at',''))}")

                    if role == "admin" and estado != "pagada":
                        if st.button("✅ Marcar como pagada", key=f"pag_{l['id']}"):
                            supabase.table("liquidaciones").update({"estado":"pagada"}).eq("id", l["id"]).execute()
                            st.success("Marcada como pagada")
                            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        with st.form("nueva_liquidacion"):
            col1, col2 = st.columns(2)
            with col1:
                periodo = st.text_input("Período *", placeholder="Ej: Marzo 2026")
                proyectos = st.text_area("Proyectos trabajados", height=80)
                valor = st.number_input("Valor a liquidar ($)", min_value=0, step=10000)
            with col2:
                descripcion = st.text_area("Descripción de trabajos", height=80)
                dias_trabajados = st.number_input("Días trabajados", min_value=0, max_value=31)

            submitted = st.form_submit_button("Crear Liquidación →")
            if submitted and periodo and valor > 0:
                try:
                    supabase.table("liquidaciones").insert({
                        "tecnico_id": st.session_state.user_id,
                        "tecnico_nombre": st.session_state.user_name,
                        "periodo": periodo,
                        "proyectos": proyectos,
                        "valor": valor,
                        "descripcion": descripcion,
                        "dias_trabajados": dias_trabajados,
                        "estado": "pendiente",
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Liquidación de {periodo} creada — ${valor:,.0f}")
                    send_telegram(f"💵 Nueva liquidación: {st.session_state.user_name}\nPeríodo: {periodo}\nValor: ${valor:,.0f}")
                except Exception as e:
                    st.error(f"Error: {e}")

# ─────────────────────────────────────────────
# MÓDULO: ESPECIALISTAS Y ALIADOS
# ─────────────────────────────────────────────
def modulo_especialistas():
    show_header("Especialistas y Aliados")
    role = st.session_state.user_role
    if role != "admin":
        st.warning("Acceso restringido a administradores.")
        return

    tab1, tab2, tab3 = st.tabs(["👷 Especialistas", "🤝 Aliados Comerciales", "➕ Nuevo Usuario"])

    with tab1:
        try:
            result = supabase.table("usuarios").select("*").eq("rol", "tecnico").execute()
            especialistas = result.data or []
            if not especialistas:
                st.info("No hay especialistas registrados.")
            for e in especialistas:
                with st.expander(f"👷 {e.get('nombre','')}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Email:** {e.get('email','')}")
                        st.markdown(f"**Teléfono:** {e.get('telefono','')}")
                    with col2:
                        st.markdown(f"**Especialidad:** {e.get('especialidad','')}")
                        st.markdown(f"**Activo:** {'✅' if e.get('activo',True) else '❌'}")
        except Exception as e:
            st.error(f"Error: {e}")

    with tab2:
        try:
            result = supabase.table("usuarios").select("*").eq("rol","cliente").execute()
            aliados = result.data or []
            for a in aliados:
                with st.expander(f"🤝 {a.get('nombre','')}"):
                    st.markdown(f"**Email:** {a.get('email','')}")
                    st.markdown(f"**Teléfono:** {a.get('telefono','')}")
        except Exception as e:
            st.error(f"Error: {e}")

    with tab3:
        with st.form("nuevo_usuario"):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input("Nombre completo *")
                email = st.text_input("Email *")
                rol = st.selectbox("Rol", ["tecnico","vendedor","cliente","admin"])
            with col2:
                telefono = st.text_input("Teléfono")
                especialidad = st.text_input("Especialidad (si aplica)")
                password = st.text_input("Contraseña temporal *", type="password")

            submitted = st.form_submit_button("Crear Usuario →")
            if submitted and nombre and email and password:
                try:
                    pw_hash = hash_password(password)
                    supabase.table("usuarios").insert({
                        "nombre": nombre,
                        "email": email,
                        "rol": rol,
                        "telefono": telefono,
                        "especialidad": especialidad,
                        "password_hash": pw_hash,
                        "activo": True,
                        "created_at": now_bogota().isoformat()
                    }).execute()
                    st.success(f"✅ Usuario '{nombre}' ({rol}) creado")
                    send_telegram(f"👤 Nuevo usuario: {nombre} ({rol})\nEmail: {email}")
                except Exception as e:
                    st.error(f"Error creando usuario: {e}")

# ─────────────────────────────────────────────
# MÓDULO: CONFIGURACIÓN (admin only)
# ─────────────────────────────────────────────
def modulo_configuracion():
    show_header("Configuración del Sistema")
    role = st.session_state.user_role
    if role != "admin":
        st.warning("Acceso restringido a administradores.")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["🤖 Gestión de IAs", "🔔 Notificaciones", "🧹 Limpieza de datos", "ℹ️ Sistema"])

    # ── TAB 1: IAs (SOLO ADMIN VE ESTO) ──
    with tab1:
        st.markdown('<div class="section-title">Gestión de Inteligencias Artificiales</div>', unsafe_allow_html=True)
        st.info("ℹ️ Los usuarios solo ven 'Consultar' — esta configuración es invisible para ellos.")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### IAs disponibles")
            groq_on = st.toggle("🟢 Groq / LLaMA (recomendado)", value=st.session_state.ia_groq_enabled)
            gemini_on = st.toggle("🔵 Gemini 2.0 Flash", value=st.session_state.ia_gemini_enabled)
            venice_on = st.toggle("🟣 Venice AI", value=st.session_state.ia_venice_enabled)

            primary = st.selectbox("IA principal (primera en consultar)",
                                   ["groq", "gemini", "venice"],
                                   index=["groq","gemini","venice"].index(st.session_state.ia_primary))

        with col2:
            st.markdown("### Estado de conexión")

            # Verificar Groq
            if st.button("🔍 Verificar Groq"):
                with st.spinner("Verificando..."):
                    resp = consultar_groq("Di solo: OK", "Responde solo OK")
                    if resp:
                        st.success(f"✅ Groq funcionando: {resp[:50]}")
                    else:
                        st.error("❌ Groq no responde — verificar GROQ_API_KEY")

            # Verificar Gemini
            if st.button("🔍 Verificar Gemini"):
                with st.spinner("Verificando..."):
                    resp = consultar_gemini("Di solo: OK", "Responde solo OK")
                    if resp:
                        st.success(f"✅ Gemini funcionando: {resp[:50]}")
                    else:
                        st.error("❌ Gemini no responde — verificar GOOGLE_API_KEY en aistudio.google.com")
                        st.markdown("""
                        **Para obtener nueva clave Gemini:**
                        1. Ve a [aistudio.google.com](https://aistudio.google.com) con `jandrextia@gmail.com`
                        2. Menú → Get API Key → Create API Key
                        3. Copia la clave y agrégala en Streamlit Cloud → Settings → Secrets
                        4. Clave: `GOOGLE_API_KEY = "tu-nueva-clave"`
                        """)

            # Verificar Venice
            if st.button("🔍 Verificar Venice"):
                with st.spinner("Verificando..."):
                    resp = consultar_venice("Di solo: OK", "Responde solo OK")
                    if resp:
                        st.success(f"✅ Venice funcionando: {resp[:50]}")
                    else:
                        st.error("❌ Venice no responde — verificar VENICE_API_KEY")

        if st.button("💾 Guardar configuración de IAs", type="primary"):
            st.session_state.ia_groq_enabled = groq_on
            st.session_state.ia_gemini_enabled = gemini_on
            st.session_state.ia_venice_enabled = venice_on
            st.session_state.ia_primary = primary
            st.success("✅ Configuración guardada para esta sesión")

        st.markdown("---")
        st.markdown("### 📊 Uso de IAs — Estado actual")
        estado_data = {
            "Groq/LLaMA": {"activa": groq_on, "nota": "Gratuita, muy rápida"},
            "Gemini 2.0 Flash": {"activa": gemini_on, "nota": "Requiere API key activa — verificar cuota"},
            "Venice AI": {"activa": venice_on, "nota": "Verificar API key en Venice dashboard"}
        }
        for ia, info in estado_data.items():
            st.markdown(f"{'✅' if info['activa'] else '⭕'} **{ia}** — {info['nota']}")

    # ── TAB 2: NOTIFICACIONES ──
    with tab2:
        st.markdown('<div class="section-title">Notificaciones</div>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Telegram")
            st.markdown(f"Bot: `@JandrexTAsistencia_bot`")
            msg_test = st.text_input("Mensaje de prueba", value="Prueba desde JandrexT IA v15")
            if st.button("📨 Enviar Telegram"):
                send_telegram(f"🔔 {msg_test}")
                st.success("Mensaje enviado")
        with col2:
            st.markdown("### Email SMTP")
            email_test = st.text_input("Email destino", value="proyectos@jandrext.com")
            if st.button("📧 Enviar Email de prueba"):
                send_email(email_test, "Prueba JandrexT IA v15", "<h1>Email de prueba</h1><p>Sistema funcionando.</p>")
                st.success("Email enviado (si las credenciales son válidas)")

    # ── TAB 3: LIMPIEZA ──
    with tab3:
        st.markdown('<div class="section-title">Limpieza de Datos de Prueba</div>', unsafe_allow_html=True)
        st.warning("⚠️ Solo eliminar datos de prueba. Esta acción es irreversible.")

        tablas = ["chats", "proyectos", "agenda", "asistencia", "documentos", "ventas", "liquidaciones"]
        tabla_sel = st.selectbox("Tabla a limpiar", tablas)
        criterio = st.text_input("Filtro (dejar vacío para ver todos)", placeholder="Ej: test, prueba, demo")

        if st.button("🔍 Ver registros"):
            try:
                if criterio:
                    result = supabase.table(tabla_sel).select("id, created_at").ilike("*", f"%{criterio}%").limit(20).execute()
                else:
                    result = supabase.table(tabla_sel).select("id, created_at").order("created_at", desc=True).limit(10).execute()
                st.json(result.data)
            except Exception as e:
                st.error(f"Error: {e}")

        st.markdown("---")
        st.markdown("### Eliminar usuarios de prueba")
        emails_test = ["especialista@test.jandrext.com", "aliado@test.jandrext.com"]
        for e in emails_test:
            if st.button(f"🗑️ Eliminar {e}"):
                try:
                    supabase.table("usuarios").delete().eq("email", e).execute()
                    st.success(f"Eliminado: {e}")
                except Exception as ex:
                    st.error(f"Error: {ex}")

    # ── TAB 4: SISTEMA ──
    with tab4:
        st.markdown('<div class="section-title">Información del Sistema</div>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
            **Empresa:** JandrexT Soluciones Integrales  
            **NIT:** 80818905-3  
            **Director:** Andrés Tapiero  
            **Versión:** v15  
            **Plataforma:** Streamlit Cloud  
            **BD:** Supabase PostgreSQL  
            **Zona horaria:** America/Bogota  
            **Fecha/hora:** {format_fecha(now_bogota())}
            """)
        with col2:
            st.markdown("""
            **IAs integradas:**  
            - Groq / LLaMA 3.3 70B  
            - Gemini 2.0 Flash  
            - Venice AI  
            
            **Notificaciones:**  
            - Telegram Bot  
            - Gmail SMTP  
            
            **Mapas:** OpenStreetMap / Leaflet
            """)

        # Estadísticas
        st.markdown("### 📊 Estadísticas de uso")
        tablas_stats = ["usuarios","proyectos","chats","documentos","ventas","aliados" if False else "clientes"]
        cols = st.columns(len(tablas_stats))
        for i, tabla in enumerate(tablas_stats):
            try:
                r = supabase.table(tabla).select("id", count="exact").execute()
                count = r.count or len(r.data or [])
                with cols[i]:
                    st.markdown(f'<div class="metric-card"><h3>{count}</h3><p>{tabla.capitalize()}</p></div>', unsafe_allow_html=True)
            except:
                pass

# ─────────────────────────────────────────────
# ROUTER PRINCIPAL
# ─────────────────────────────────────────────
def main():
    # Verificar persistencia de sesión por query param
    if not st.session_state.logged_in:
        uid = st.query_params.get("uid", None)
        if uid:
            try:
                result = supabase.table("usuarios").select("*").eq("id", uid).execute()
                if result.data:
                    user = result.data[0]
                    st.session_state.logged_in = True
                    st.session_state.user_id = user["id"]
                    st.session_state.user_email = user["email"]
                    st.session_state.user_name = user.get("nombre", "Usuario")
                    st.session_state.user_role = user.get("rol", "tecnico")
            except:
                pass

    if not st.session_state.logged_in:
        show_login()
        return

    show_sidebar()

    modulo = st.session_state.active_module

    if modulo == "Chats":
        modulo_chats()
    elif modulo == "Proyectos":
        modulo_proyectos()
    elif modulo == "Agenda":
        modulo_agenda()
    elif modulo == "Asistencia":
        modulo_asistencia()
    elif modulo == "Documentos":
        modulo_documentos()
    elif modulo == "Manuales":
        modulo_manuales()
    elif modulo == "Biblioteca":
        modulo_biblioteca()
    elif modulo == "Ventas":
        modulo_ventas()
    elif modulo == "Aliados":
        modulo_aliados()
    elif modulo == "Liquidaciones":
        modulo_liquidaciones()
    elif modulo == "Especialistas y Aliados":
        modulo_especialistas()
    elif modulo == "Configuración":
        modulo_configuracion()
    else:
        st.info(f"Módulo '{modulo}' en desarrollo.")

if __name__ == "__main__":
    main()
