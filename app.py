import streamlit as st
import os, time, json, uuid, hashlib, base64, concurrent.futures, smtplib
import requests as req
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import pytz

load_dotenv()

# ── Zona horaria Colombia ─────────────────────────────────────────────────────
TZ_COL = pytz.timezone("America/Bogota")
def ahora(): return datetime.now(TZ_COL)
def ahora_str(): return ahora().strftime("%Y-%m-%d %H:%M")
def fecha_str(): return ahora().strftime("%d/%m/%Y %H:%M")
hora_actual = ahora().hour
saludo = "Buenos días" if hora_actual < 12 else "Buenas tardes" if hora_actual < 18 else "Buenas noches"

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
    except: return hashlib.sha256(pwd.encode()).hexdigest()

def verify_pwd(pwd, hashed):
    try:
        import bcrypt
        if hashed and hashed.startswith("$2"):
            return bcrypt.checkpw(pwd.encode(), hashed.encode())
    except: pass
    return (hashlib.md5(pwd.encode()).hexdigest() == hashed or
            hashlib.sha256(pwd.encode()).hexdigest() == hashed)

def verificar_login(email, pwd):
    bloqueo = supa("intentos_login", filtro=f"?email=eq.{email}")
    if bloqueo and isinstance(bloqueo,list) and bloqueo:
        b = bloqueo[0]
        if b.get("bloqueado_hasta"):
            try:
                hasta = datetime.fromisoformat(b["bloqueado_hasta"].replace("Z",""))
                if datetime.utcnow() < hasta:
                    mins = int((hasta-datetime.utcnow()).seconds/60)+1
                    return None, f"🔒 Cuenta bloqueada. Intenta en {mins} minutos."
            except: pass
    res = supa("usuarios", filtro=f"?email=eq.{email}&activo=eq.true")
    if res and isinstance(res,list) and res and verify_pwd(pwd, res[0].get("password_hash","")):
        supa("intentos_login","DELETE",filtro=f"?email=eq.{email}")
        return res[0], None
    if bloqueo and isinstance(bloqueo,list) and bloqueo:
        intentos = bloqueo[0].get("intentos",0)+1
        data = {"intentos":intentos}
        if intentos >= 5: data["bloqueado_hasta"]=(datetime.utcnow()+timedelta(minutes=30)).isoformat()
        supa("intentos_login","PATCH",data,f"?email=eq.{email}")
    else: supa("intentos_login","POST",{"email":email,"intentos":1})
    return None, "❌ Correo o contraseña incorrectos."

def tiene_modulo(u, mod):
    if u.get("rol")=="admin": return True
    return mod in (u.get("modulos") or [])

def puede_borrar(u): return u.get("rol")=="admin"

# ── Email ─────────────────────────────────────────────────────────────────────
def enviar_email(destinatario, asunto, cuerpo_html):
    try:
        gmail_user = os.getenv("GMAIL_USER","")
        gmail_pwd  = os.getenv("GMAIL_APP_PASSWORD","")
        if not gmail_user or not gmail_pwd: return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = f"JandrexT Soluciones Integrales <{gmail_user}>"
        msg["To"] = destinatario
        msg.attach(MIMEText(cuerpo_html,"html","utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(gmail_user, gmail_pwd)
            s.sendmail(gmail_user, destinatario, msg.as_string())
        return True
    except Exception as e:
        st.warning(f"⚠️ No se pudo enviar el correo: {e}")
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
Director: Andrés Tapiero | Lema: Apasionados por el buen servicio | NIT: 80818905-3
Tel: 317 391 0621 | proyectos@jandrext.com | Bogotá, Colombia
Comportamiento: empático, profesional, práctico. Normas colombianas cuando aplique."""

LINEAS = ["Automatización de accesos","Videovigilancia CCTV","Control de acceso y biometría",
          "Redes y comunicaciones","Sistemas eléctricos","Cerca eléctrica",
          "Soporte tecnológico","Desarrollo de software","Consultoría y diagnóstico"]

CHECKLISTS = {
    "Videovigilancia CCTV":["Verificar estado de cámaras","Revisar señal en DVR/NVR","Verificar grabación activa",
        "Revisar disco duro (espacio y estado)","Verificar acceso remoto","Limpiar lentes",
        "Revisar cableado y conexiones","Verificar fuentes de alimentación","Ajustar ángulos","Documentar con fotos"],
    "Automatización de accesos":["Verificar motor","Revisar finales de carrera","Lubricar partes mecánicas",
        "Revisar tarjeta controladora","Verificar fotoceldas","Revisar botón de paro",
        "Verificar luz intermitente","Probar control remoto/app","Revisar batería de respaldo","Documentar con fotos"],
    "Control de acceso y biometría":["Verificar lectura tarjetas/biometría","Revisar comunicación TCP/IP",
        "Verificar base de datos usuarios","Revisar permisos por zonas","Verificar registro de eventos",
        "Revisar cableado RS485","Probar apertura/cierre","Verificar horarios","Revisar firmware","Documentar con fotos"],
    "Cerca eléctrica":["Revisar tensión del sistema","Verificar puesta a tierra","Revisar hilos de cerca",
        "Verificar energizador","Probar supervisión de corte","Revisar señalización","Verificar batería","Revisar teclado","Documentar con fotos"],
}

ROL_LABEL = {"admin":"Administrador","tecnico":"Especialista","vendedor":"Asesor Comercial","cliente":"Aliado"}

def gemini_fn(p, modelo="gemini-1.5-flash"):
    try:
        import google.generativeai as genai
        t=time.time(); genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        r=genai.GenerativeModel(modelo).generate_content(CONTEXTO+"\n\nConsulta: "+p)
        return {"ia":"Gemini","icono":"🔵","respuesta":r.text.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"Gemini","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def groq_fn(p):
    try:
        from groq import Groq; t=time.time()
        r=Groq(api_key=os.getenv("GROQ_API_KEY","")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],max_tokens=1500)
        return {"ia":"Groq·LLaMA","icono":"🟠","respuesta":r.choices[0].message.content.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"Groq·LLaMA","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def venice_fn(p):
    try:
        t=time.time(); h={"Authorization":f"Bearer {os.getenv('VENICE_API_KEY','')}","Content-Type":"application/json"}
        r=req.post("https://api.venice.ai/api/v1/chat/completions",
            json={"model":"llama-3.3-70b","messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],"max_tokens":1500},
            headers=h,timeout=30)
        return {"ia":"Venice","icono":"🟣","respuesta":r.json()["choices"][0]["message"]["content"].strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"Venice","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def juez_fn(pregunta, respuestas):
    try:
        import google.generativeai as genai; genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        resumen="\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in respuestas if r["ok"]])
        r=genai.GenerativeModel("gemini-1.5-pro").generate_content(
            f"{CONTEXTO}\nPregunta: \"{pregunta}\"\nRespuestas:\n{resumen}\nSintetiza la mejor respuesta. Empático, profesional, práctico.")
        return r.text.strip()
    except Exception as e: return f"❌ Error síntesis: {e}"

def ia_generar(prompt, modelo="gemini-1.5-pro"):
    try:
        import google.generativeai as genai; genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        r=genai.GenerativeModel(modelo).generate_content(CONTEXTO+"\n\n"+prompt)
        return r.text.strip()
    except Exception as e: return f"❌ Error: {e}"

def ia_extraer_datos_doc(contenido_b64, tipo_doc="imagen"):
    try:
        import google.generativeai as genai; genai.configure(api_key=os.getenv("GOOGLE_API_KEY",""))
        prompt="""Extrae los siguientes datos de este documento y devuelve SOLO un JSON válido sin markdown:
{
  "razon_social": "",
  "nit": "",
  "direccion": "",
  "municipio": "",
  "departamento": "",
  "telefono": "",
  "email": "",
  "contacto": "",
  "cargo_contacto": "",
  "responsabilidad_fiscal": "",
  "regimen_fiscal": "",
  "tipo": "copropiedad"
}
Si no encuentras un campo, déjalo vacío."""
        model=genai.GenerativeModel("gemini-1.5-pro")
        if tipo_doc=="pdf":
            part={"inline_data":{"mime_type":"application/pdf","data":contenido_b64}}
        else:
            part={"inline_data":{"mime_type":"image/jpeg","data":contenido_b64}}
        r=model.generate_content([prompt, part])
        txt=r.text.strip().replace("```json","").replace("```","").strip()
        return json.loads(txt)
    except Exception as e: return {}

# ── PDF ───────────────────────────────────────────────────────────────────────
def generar_pdf_html(titulo, contenido, logo_b64=None):
    logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height:60px;" />' if logo_b64 else ""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{{font-family:Arial,sans-serif;font-size:11px;color:#222;margin:0;padding:20px;}}
.header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #cc0000;padding-bottom:10px;margin-bottom:20px;}}
.brand{{color:#cc0000;font-size:20px;font-weight:900;letter-spacing:2px;}}
.lema{{color:#cc0000;font-style:italic;font-size:10px;}}
.titulo{{text-align:center;font-size:14px;font-weight:bold;margin:15px 0;color:#cc0000;}}
.contenido{{white-space:pre-wrap;line-height:1.6;}}
.footer{{border-top:1px solid #ccc;margin-top:20px;padding-top:10px;font-size:9px;color:#666;text-align:center;}}
</style></head><body>
<div class="header">
<div>{logo_tag}<div class="brand">JandrexT</div><div style="font-size:9px;letter-spacing:2px;">SOLUCIONES INTEGRALES</div><div class="lema">Apasionados por el buen servicio</div></div>
<div style="text-align:right;font-size:9px;">Director: Andrés Tapiero<br>317 391 0621<br>proyectos@jandrext.com<br>Bogotá, Colombia<br>{fecha_str()}</div>
</div>
<div class="titulo">{titulo}</div>
<div class="contenido">{contenido}</div>
<div class="footer">JandrexT Soluciones Integrales · NIT: 80818905-3 · CL 80 No. 70C-67 Local 2 Barrio Bonanza, Bogotá · Apasionados por el buen servicio</div>
</body></html>"""
    return html

# ── Config página ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="JandrexT",page_icon="🧠",layout="wide",initial_sidebar_state="expanded")

# ── Logo b64 ──────────────────────────────────────────────────────────────────
logo_b64 = None
if Path("logo_jandrext.png").exists():
    logo_b64 = base64.b64encode(Path("logo_jandrext.png").read_bytes()).decode()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""<style>
{FONTS_CSS}
html,body,[class*="css"]{{font-family:'Disclaimer-Plain','Inter',sans-serif;}}

.login-wrap{{max-width:460px;margin:3rem auto;background:#0f0000;border:1px solid #cc0000;border-radius:16px;padding:2.5rem;}}
.logo-j{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-size:4.5rem;font-weight:900;letter-spacing:6px;line-height:1;}}
.logo-mid{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-size:2.8rem;font-weight:900;letter-spacing:6px;line-height:1;}}
.logo-t{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-size:4.5rem;font-weight:900;letter-spacing:6px;line-height:1;}}
.logo-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#555;font-size:0.7rem;letter-spacing:6px;text-transform:uppercase;margin:0.4rem 0 0 0;}}
.logo-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:1.15rem;margin:0.3rem 0;}}

.header-inst{{background:linear-gradient(135deg,#0a0000,#1a0000);border-radius:12px;
    padding:1.2rem 2rem;margin-bottom:1rem;border:1px solid #cc0000;
    display:flex;align-items:center;justify-content:space-between;gap:1rem;}}
.h-logo{{height:55px;width:auto;flex-shrink:0;}}
.h-brand{{flex:1;}}
.h-name{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-size:1.9rem;font-weight:900;letter-spacing:5px;margin:0;line-height:1;}}
.h-acc{{color:#cc0000;}}
.h-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:1rem;margin:0.1rem 0;}}
.h-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#444;font-size:0.62rem;letter-spacing:4px;text-transform:uppercase;margin:0;}}
.h-user{{text-align:right;flex-shrink:0;}}
.h-saludo{{font-family:'JennaSue',sans-serif;color:#cc6666;font-size:0.9rem;}}
.h-nombre{{color:#fff;font-weight:700;font-size:0.92rem;}}
.h-rol{{color:#cc0000;font-size:0.65rem;letter-spacing:1px;text-transform:uppercase;}}
.h-fecha{{color:#444;font-size:0.68rem;}}

.sb-wrap{{background:#0f0000;border:1px solid #cc0000;border-radius:10px;padding:1rem;text-align:center;margin-bottom:0.5rem;}}
.sb-name{{font-family:'Disclaimer-Classic',sans-serif;color:#fff;font-weight:900;font-size:1.05rem;margin:0;letter-spacing:3px;}}
.sb-acc{{color:#cc0000;}}
.sb-sub{{font-family:'Disclaimer-Plain',sans-serif;color:#cc0000;font-size:0.62rem;margin:0;letter-spacing:2px;text-transform:uppercase;}}
.sb-lema{{font-family:'JennaSue',sans-serif;color:#cc6666;font-size:0.85rem;margin:0.2rem 0 0;}}
.ub{{background:#1a0000;border:1px solid #cc0000;border-radius:8px;padding:0.5rem 0.8rem;margin-bottom:0.5rem;text-align:center;}}
.ub-n{{color:#ffcccc;font-size:0.82rem;font-weight:700;margin:0;}}
.ub-r{{color:#cc0000;font-size:0.68rem;margin:0;text-transform:uppercase;letter-spacing:1px;}}

.nav-title{{font-family:'Disclaimer-Plain',sans-serif;background:#1a0000;border:1px solid #cc0000;
    border-radius:6px;padding:0.3rem 0.6rem;color:#cc0000;font-size:0.7rem;font-weight:700;
    letter-spacing:2px;text-transform:uppercase;margin:0.6rem 0 0.3rem;display:block;}}

.ia-card{{background:#0f0000;border:1px solid #2a0000;border-radius:10px;padding:0.8rem;}}
.ia-card h4{{margin:0 0 0.2rem;font-size:0.9rem;color:#f0f0f0;font-weight:600;}}
.badge-ok{{color:#4ade80;font-weight:600;font-size:0.8rem;}}
.badge-err{{color:#f87171;font-weight:600;font-size:0.8rem;}}
.t-seg{{color:#555;font-size:0.72rem;}}
.resp-card{{background:#0f0000;border:2px solid #cc0000;border-radius:12px;padding:1.4rem;color:#f0f0f0;line-height:1.75;margin-top:0.5rem;}}
.resp-titulo{{font-family:'Disclaimer-Plain',sans-serif;color:#cc0000;font-size:0.68rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:0.8rem;}}
.chat-u{{background:#1a0000;border:1px solid #cc0000;border-radius:12px 12px 4px 12px;padding:0.7rem 1rem;margin:0.3rem 0;color:#f0f0f0;}}
.chat-ia{{background:#0a0a0a;border:1px solid #222;border-radius:12px 12px 12px 4px;padding:0.7rem 1rem;margin:0.3rem 0;color:#ddd;}}
.meta{{color:#555;font-size:0.7rem;margin-bottom:0.2rem;}}
.tip{{background:#0a0f00;border-left:3px solid #cc0000;border-radius:0 6px 6px 0;padding:0.5rem 0.8rem;color:#999;font-size:0.78rem;margin:0.4rem 0;}}
.garantia-ok{{color:#4ade80;font-size:0.78rem;}}
.garantia-alerta{{color:#f87171;font-size:0.78rem;}}
.doc-borrador{{background:#0a0f0a;border:1px solid #166534;border-radius:10px;padding:1.2rem;}}
.footer-inst{{background:#0a0000;border:1px solid #1a0000;border-radius:8px;padding:0.7rem;text-align:center;margin-top:1.5rem;color:#444;font-size:0.7rem;}}
.footer-acc{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-weight:700;}}
.footer-lema{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:0.88rem;}}
.divider{{border:none;border-top:1px solid #1a0000;margin:1rem 0;}}

@media(max-width:768px){{
    .header-inst{{flex-direction:column;padding:0.8rem;gap:0.5rem;}}
    .h-user{{text-align:left;}}
    .h-logo{{height:40px;}}
    .h-name{{font-size:1.4rem;}}
    .stButton>button{{min-height:50px;font-size:1rem;border-radius:10px;}}
    .stTextInput>div>input{{min-height:46px;font-size:1rem;}}
    .stSelectbox>div>div{{min-height:46px;}}
    h2{{font-size:1.3rem;}} h3{{font-size:1.1rem;}}
}}
</style>""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k,v in [("usuario",None),("seccion","chat"),("chat_activo",None),
            ("proy_activo",None),("proy_nombre",""),("sc_activo",None),
            ("confirm_logout",False)]:
    if k not in st.session_state: st.session_state[k]=v

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.usuario:
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        st.markdown("""<div class="login-wrap">
        <div style="text-align:center;margin-bottom:1.5rem;">
            <div style="line-height:1.1;">
                <span class="logo-j">J</span><span class="logo-mid">ANDREX</span><span class="logo-t">T</span>
            </div>
            <p class="logo-sub">Soluciones Integrales</p>
            <p class="logo-lema">Apasionados por el buen servicio</p>
        </div></div>""", unsafe_allow_html=True)
        st.markdown("### 🔐 Iniciar sesión")
        email=st.text_input("Correo electrónico",placeholder="usuario@jandrext.com")
        pwd=st.text_input("Contraseña",type="password")
        st.checkbox("Recordar en este dispositivo")
        if st.button("Ingresar",type="primary",use_container_width=True):
            if email and pwd:
                with st.spinner("Verificando..."):
                    usuario,error=verificar_login(email.strip(),pwd.strip())
                if usuario: st.session_state.usuario=usuario; st.rerun()
                else: st.error(error)
            else: st.warning("⚠️ Completa todos los campos.")
        st.caption("¿Olvidaste tu contraseña? Contacta: proyectos@jandrext.com | 317 391 0621")
    st.stop()

u=st.session_state.usuario
rol=u.get("rol","")
nombre=u.get("nombre","")
rol_label=ROL_LABEL.get(rol,rol)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""<div class="sb-wrap">
        <p class="sb-name">Jandre<span class="sb-acc">x</span>T</p>
        <p class="sb-sub">Soluciones Integrales</p>
        <p class="sb-lema">Apasionados por el buen servicio</p>
    </div>
    <div class="ub"><p class="ub-n">👤 {nombre}</p><p class="ub-r">{rol_label}</p></div>""",
    unsafe_allow_html=True)

    st.markdown('<span class="nav-title">📌 Navegación</span>',unsafe_allow_html=True)

    if rol=="cliente":
        SECS=[("📋","requerimientos","Mis Solicitudes"),("📖","mis_manuales","Mis Manuales")]
    elif rol=="tecnico":
        SECS=[("📅","agenda","Mi Agenda"),("👥","asistencia","Mi Asistencia"),("💬","chat","Consultas")]
    else:
        SECS=[("💬","chat","Chats"),("📁","proyectos","Proyectos"),
              ("📅","agenda","Agenda"),("👥","asistencia","Asistencia"),
              ("📚","biblioteca","Biblioteca"),("📄","documentos","Documentos"),
              ("📖","manuales","Manuales"),("💼","ventas","Ventas"),
              ("🤝","aliados","Aliados"),("📊","liquidaciones","Liquidaciones"),
              ("👑","usuarios","Especialistas y Aliados"),("⚙️","config","Configuración")]

    for ico,key,label in SECS:
        activo="▶ " if st.session_state.seccion==key else ""
        if st.button(f"{ico} {activo}{label}",key=f"nav_{key}",use_container_width=True):
            st.session_state.seccion=key; st.rerun()

    if rol=="admin":
        st.markdown('<span class="nav-title">⚡ IAs</span>',unsafe_allow_html=True)
        usar_g=st.toggle("🔵 Gemini",value=True)
        usar_r=st.toggle("🟠 Groq",value=True)
        usar_v=st.toggle("🟣 Venice",value=True)
        modelo_g=st.selectbox("",["gemini-1.5-flash","gemini-1.5-pro"],label_visibility="collapsed")
    else:
        usar_g=usar_r=usar_v=True; modelo_g="gemini-1.5-flash"

    st.markdown("---")
    if st.button("🚪 Cerrar sesión",use_container_width=True):
        if st.session_state.confirm_logout:
            st.session_state.usuario=None; st.session_state.confirm_logout=False; st.rerun()
        else:
            st.session_state.confirm_logout=True
            st.warning("¿Confirmas? Presiona de nuevo.")

# ── Header ────────────────────────────────────────────────────────────────────
logo_tag=f'<img src="data:image/png;base64,{logo_b64}" class="h-logo"/>' if logo_b64 else ""
st.markdown(f"""<div class="header-inst">
    {logo_tag}
    <div class="h-brand">
        <p class="h-name">Jandre<span class="h-acc">x</span>T</p>
        <p class="h-lema">Apasionados por el buen servicio</p>
        <p class="h-sub">Soluciones Integrales · Plataforma v12.0</p>
    </div>
    <div class="h-user">
        <div class="h-saludo">{saludo},</div>
        <div class="h-nombre">{nombre}</div>
        <div class="h-rol">{rol_label}</div>
        <div class="h-fecha">{fecha_str()}</div>
    </div>
</div>""", unsafe_allow_html=True)

sec=st.session_state.seccion

# ── Componente de voz ─────────────────────────────────────────────────────────
def campo_voz(label, key, height=100, placeholder="Escribe o usa el micrófono..."):
    if key not in st.session_state: st.session_state[key]=""
    try:
        from streamlit_mic_recorder import speech_to_text
        c1,c2=st.columns([1,4])
        with c1:
            tv=speech_to_text(language="es",start_prompt="🎤",stop_prompt="⏹️",
                just_once=True,use_container_width=True,key=f"mic_{key}")
        with c2: st.caption(f"🎤 Presiona para dictar {label}")
        if tv:
            st.session_state[key]=(st.session_state[key]+" "+tv).strip()
            st.rerun()
    except: pass
    val=st.text_area(label,value=st.session_state[key],height=height,
        key=f"ta_{key}",placeholder=placeholder)
    st.session_state[key]=val
    return val

# ── Panel consulta ────────────────────────────────────────────────────────────
def panel_consulta(chat_id, ctx="General"):
    msgs=supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}&order=creado_en.asc")
    if msgs and isinstance(msgs,list):
        for m in msgs:
            st.markdown(f'<div class="chat-u"><span class="meta">🧑 {m.get("creado_en","")[:16]}</span><br>{m.get("pregunta","")}</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="chat-ia"><span class="meta">🏛️ JandrexT</span><br>{m.get("sintesis","")}</div>',unsafe_allow_html=True)
            if puede_borrar(u):
                if st.button("🗑️",key=f"dm_{m['id']}"):
                    supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
        st.markdown('<hr class="divider">',unsafe_allow_html=True)

    st.markdown('<div class="tip">💡 Escribe tu consulta técnica o usa el micrófono.</div>',unsafe_allow_html=True)
    pregunta=campo_voz("✍️ Consulta",f"inp_{chat_id}",height=90)
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        btn=st.button("🔍 Consultar",use_container_width=True,type="primary",key=f"btn_{chat_id}")
    if btn and pregunta.strip():
        fns=[]
        if usar_g: fns.append(lambda p: gemini_fn(p,modelo_g))
        if usar_r: fns.append(lambda p: groq_fn(p))
        if usar_v: fns.append(lambda p: venice_fn(p))
        if not fns: st.warning("Activa al menos una IA."); return
        with st.spinner("Consultando..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
                resultados=list(ex.map(lambda f:f(pregunta),fns))
        cols=st.columns(len(resultados))
        for i,res in enumerate(resultados):
            with cols[i]:
                cls="badge-ok" if res["ok"] else "badge-err"
                st.markdown(f'<div class="ia-card"><h4>{res["icono"]} {res["ia"]}</h4><span class="{cls}">{"✓" if res["ok"] else "✗"}</span><span class="t-seg"> ⏱{res["tiempo"]}s</span></div>',unsafe_allow_html=True)
                if res["ok"]:
                    with st.expander("Ver"): st.write(res["respuesta"])
        ok=[r for r in resultados if r["ok"]]
        if ok:
            with st.spinner("Procesando respuesta..."):
                sintesis=juez_fn(pregunta,ok)
            st.markdown(f'<div class="resp-card"><div class="resp-titulo">🏛️ RESPUESTA JANDREXT · {ctx}</div>{sintesis}</div>',unsafe_allow_html=True)
            with st.expander("📋 Copiar"): st.code(sintesis,language=None)
            cnt=len(supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}") or [])
            if cnt==0: supa("chats","PATCH",{"titulo":pregunta[:50]},f"?id=eq.{chat_id}")
            supa("mensajes_chat","POST",{"chat_id":chat_id,"pregunta":pregunta,
                "sintesis":sintesis,"ias_usadas":[r["ia"] for r in ok]})
            st.session_state[f"inp_{chat_id}"]=""; st.rerun()
    elif btn: st.warning("⚠️ Escribe o dicta una consulta.")

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
# ══════════════════════════════════════════════════════════════════════════════
if sec=="chat":
    st.markdown("## 💬 Chats")
    cl,cc=st.columns([1,3])
    with cl:
        st.markdown('<span class="nav-title">Mis chats</span>',unsafe_allow_html=True)
        if st.button("➕ Nuevo chat",use_container_width=True):
            n=supa("chats","POST",{"titulo":"Nuevo chat","usuario_id":u["id"]})
            if n and isinstance(n,list): st.session_state.chat_activo=n[0]["id"]; st.rerun()
        chats=supa("chats",filtro=f"?usuario_id=eq.{u['id']}&order=creado_en.desc")
        if chats and isinstance(chats,list):
            for c in chats:
                cb,cd=st.columns([4,1])
                with cb:
                    if st.button(f"💬 {c.get('titulo','Chat')[:22]}",key=f"c_{c['id']}",use_container_width=True):
                        st.session_state.chat_activo=c["id"]; st.rerun()
                with cd:
                    if puede_borrar(u):
                        if st.button("🗑️",key=f"dc_{c['id']}"):
                            supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                            supa("chats","DELETE",filtro=f"?id=eq.{c['id']}"); st.rerun()
    with cc:
        cid=st.session_state.chat_activo
        if cid:
            cd=supa("chats",filtro=f"?id=eq.{cid}")
            tit=cd[0].get("titulo","Chat") if cd and isinstance(cd,list) else "Chat"
            nt=st.text_input("✏️ Nombre del chat",value=tit,key=f"tit_{cid}")
            if nt!=tit: supa("chats","PATCH",{"titulo":nt},f"?id=eq.{cid}")
            panel_consulta(cid,"General")
        else: st.info("👈 Selecciona o crea un chat.")

# ══════════════════════════════════════════════════════════════════════════════
# ALIADOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="aliados":
    st.markdown("## 🤝 Aliados")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo Aliado")
        st.markdown('<div class="tip">💡 Sube el RUT o una foto del documento del aliado para extraer los datos automáticamente.</div>',unsafe_allow_html=True)

        archivo_doc=st.file_uploader("📄 Subir RUT, NIT o foto del aliado",type=["pdf","jpg","jpeg","png"])
        if archivo_doc:
            if st.button("🔍 Extraer datos del documento",use_container_width=True):
                with st.spinner("Extrayendo datos..."):
                    contenido=base64.b64encode(archivo_doc.read()).decode()
                    tipo="pdf" if archivo_doc.type=="application/pdf" else "imagen"
                    datos=ia_extraer_datos_doc(contenido,tipo)
                if datos:
                    for k,v in datos.items():
                        st.session_state[f"ali_{k}"]=v
                    st.success("✅ Datos extraídos automáticamente")
                    st.rerun()

        def ali(k,label,placeholder="",options=None):
            val=st.session_state.get(f"ali_{k}","")
            if options: return st.selectbox(label,options,index=options.index(val) if val in options else 0,key=f"ali_{k}")
            return st.text_input(label,value=val,placeholder=placeholder,key=f"ali_{k}")

        a_rs=ali("razon_social","Razón Social *")
        a_nit=ali("nit","NIT / Identificación *")
        a_ti=ali("tipo","Tipo de Aliado",options=["copropiedad","empresa","natural","administracion","otro"])
        if st.session_state.get("ali_tipo")=="otro":
            a_ti_otro=st.text_input("¿Cuál tipo?",key="ali_tipo_otro")
        a_dir=ali("direccion","Dirección")
        a_mun=ali("municipio","Municipio")
        a_dep=ali("departamento","Departamento")
        a_tel=ali("telefono","Teléfono")
        a_email=ali("email","Correo electrónico")
        a_co=ali("contacto","Nombre del contacto")
        a_ca=ali("cargo_contacto","Cargo del contacto")
        a_rf=ali("responsabilidad_fiscal","Responsabilidad Fiscal",placeholder="R-99-PN")
        a_reg=ali("regimen_fiscal","Régimen Fiscal",placeholder="49")
        a_not=st.text_area("Notas adicionales",key="ali_notas",height=60)

        if st.button("💾 Guardar Aliado",type="primary",use_container_width=True):
            if a_rs and a_nit:
                tipo_final=st.session_state.get("ali_tipo_otro",a_ti) if a_ti=="otro" else a_ti
                res=supa("clientes","POST",{"nombre":a_rs,"razon_social":a_rs,"nit":a_nit,
                    "tipo":tipo_final,"direccion":a_dir,"municipio":a_mun,"departamento":a_dep,
                    "telefono":a_tel,"email":a_email,"contacto":a_co,"cargo_contacto":a_ca,
                    "responsabilidad_fiscal":a_rf,"regimen_fiscal":a_reg,"notas":a_not})
                if res:
                    for k in ["razon_social","nit","tipo","direccion","municipio","departamento",
                              "telefono","email","contacto","cargo_contacto","responsabilidad_fiscal","regimen_fiscal"]:
                        if f"ali_{k}" in st.session_state: del st.session_state[f"ali_{k}"]
                    st.success("✅ Aliado guardado"); st.rerun()
            else: st.warning("⚠️ Razón Social y NIT son obligatorios")

    with col_l:
        st.markdown("### 📋 Aliados registrados")
        aliados=supa("clientes",filtro="?order=creado_en.desc")
        if aliados and isinstance(aliados,list):
            buscar_a=st.text_input("🔍 Buscar aliado")
            filtrados=[a for a in aliados if not buscar_a or buscar_a.lower() in a.get("nombre","").lower() or buscar_a.lower() in a.get("nit","").lower()]
            st.metric("Total aliados",len(filtrados))
            for a in filtrados:
                with st.expander(f"🤝 {a['nombre']} · {a.get('nit','')}"):
                    c1,c2=st.columns(2)
                    c1.markdown(f"**Tipo:** {a.get('tipo','')} | **Tel:** {a.get('telefono','')}")
                    c1.markdown(f"**Email:** {a.get('email','')}")
                    c1.markdown(f"**Dir:** {a.get('direccion','')} · {a.get('municipio','')}")
                    c2.markdown(f"**Contacto:** {a.get('contacto','')} — {a.get('cargo_contacto','')}")
                    c2.markdown(f"**Régimen:** {a.get('regimen_fiscal','')} | **Resp:** {a.get('responsabilidad_fiscal','')}")
                    if a.get("notas"): st.caption(f"📝 {a['notas']}")
                    if puede_borrar(u):
                        if st.button("🗑️ Eliminar",key=f"da_{a['id']}"):
                            supa("clientes","DELETE",filtro=f"?id=eq.{a['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="proyectos":
    st.markdown("## 📁 Proyectos")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]

    cl,cc=st.columns([1,3])
    with cl:
        st.markdown('<span class="nav-title">Proyectos</span>',unsafe_allow_html=True)
        if rol in ["admin","vendedor"]:
            with st.expander("➕ Nuevo proyecto"):
                pn=st.text_input("Nombre *",key="pn")
                pa=st.selectbox("Aliado",aliados_nombres,key="pa")
                pt=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion"],key="pt")
                pl=st.selectbox("Línea de servicio",LINEAS,key="pl")
                pge=st.number_input("Meses garantía equipos",0,60,12,key="pge")
                pgi=st.number_input("Meses garantía instalación",0,24,6,key="pgi")
                if st.button("Crear",key="btn_proy"):
                    if pn:
                        cliente_id=next((a["id"] for a in aliados_list if a["nombre"]==pa),None)
                        fge=(ahora()+timedelta(days=pge*30)).date()
                        fgi=(ahora()+timedelta(days=pgi*30)).date()
                        supa("proyectos","POST",{"nombre":pn,"tipo":pt,"linea_servicio":pl,
                            "cliente_id":cliente_id,"descripcion":pa,
                            "meses_garantia_equipos":pge,"meses_garantia_instalacion":pgi,
                            "fecha_garantia_equipos":str(fge),"fecha_garantia_instalacion":str(fgi),
                            "creado_por":u["id"]})
                        st.success("✅ Proyecto creado"); st.rerun()

        buscar_p=st.text_input("🔍 Buscar",key="bp")
        proyectos=supa("proyectos",filtro="?order=creado_en.desc") or []
        filtrados=[p for p in proyectos if not buscar_p or buscar_p.lower() in p.get("nombre","").lower()]
        for p in filtrados:
            if st.button(f"📁 {p['nombre'][:22]}\n{p.get('linea_servicio','')[:18]}",
                key=f"p_{p['id']}",use_container_width=True):
                st.session_state.proy_activo=p["id"]
                st.session_state.proy_nombre=p["nombre"]; st.rerun()

    with cc:
        pid=st.session_state.proy_activo
        if pid:
            pd=supa("proyectos",filtro=f"?id=eq.{pid}")
            p=pd[0] if pd and isinstance(pd,list) else {}
            st.markdown(f"### 📁 {p.get('nombre','')}")
            c1,c2,c3=st.columns(3)
            c1.caption(f"🏷️ {p.get('linea_servicio','')}")
            c2.caption(f"🤝 {p.get('descripcion','')}")
            hoy=ahora().date()
            for lbl,fld in [("Equipos","fecha_garantia_equipos"),("Instalación","fecha_garantia_instalacion")]:
                fg=p.get(fld,"")
                if fg:
                    try:
                        fd=datetime.strptime(fg[:10],"%Y-%m-%d").date()
                        dias=(fd-hoy).days
                        cls="garantia-ok" if dias>30 else "garantia-alerta"
                        ico="✅" if dias>30 else "⚠️"
                        c3.markdown(f'<span class="{cls}">{ico} Garantía {lbl}: {dias}d</span>',unsafe_allow_html=True)
                    except: pass

            # Sub-chats del proyecto
            tab1,tab2=st.tabs(["💬 Chats del proyecto","📄 Documentos del proyecto"])
            with tab1:
                if st.button("➕ Nuevo chat",key="nsc"):
                    n=supa("chats","POST",{"titulo":f"Chat {p.get('nombre','')}",
                        "proyecto_id":pid,"usuario_id":u["id"]})
                    if n and isinstance(n,list): st.session_state.sc_activo=n[0]["id"]; st.rerun()
                subs=supa("chats",filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc") or []
                for s in subs:
                    cb,cd=st.columns([4,1])
                    with cb:
                        if st.button(f"💬 {s.get('titulo','')[:22]}",key=f"sc_{s['id']}",use_container_width=True):
                            st.session_state.sc_activo=s["id"]; st.rerun()
                    with cd:
                        if puede_borrar(u):
                            if st.button("🗑️",key=f"dsc_{s['id']}"):
                                supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{s['id']}")
                                supa("chats","DELETE",filtro=f"?id=eq.{s['id']}"); st.rerun()
                scid=st.session_state.sc_activo
                if scid: panel_consulta(scid,p.get("nombre",""))
                else: st.info("👈 Selecciona o crea un chat del proyecto.")

            with tab2:
                docs=supa("documentos",filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc") or []
                TIPOS_LABEL={"cotizacion":"Cotización","orden_trabajo":"OT","orden_servicio":"OS",
                             "contrato":"Contrato","acta_entrega":"Acta","informe":"Informe"}
                if docs:
                    for d in docs:
                        mes=d.get("creado_en","")[:7]
                        tipo_lbl=TIPOS_LABEL.get(d.get("tipo",""),"Doc")
                        with st.expander(f"📄 {tipo_lbl} · {mes} · ${d.get('valor_total',0):,.0f}"):
                            st.markdown(f"**Estado:** {d.get('estado_pago','pendiente')}")
                            st.markdown(d.get("contenido","")[:300]+"...")
                else: st.info("No hay documentos en este proyecto.")
        else: st.info("👈 Selecciona un proyecto.")

# ══════════════════════════════════════════════════════════════════════════════
# AGENDA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="agenda":
    st.markdown("## 📅 Agenda")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]

    col_f,col_l=st.columns([1,2])
    with col_f:
        if rol=="admin":
            st.markdown("### ➕ Nueva tarea")
            a_t=campo_voz("Tarea *","ag_tarea",height=80,placeholder="Describe la tarea...")
            a_al=st.selectbox("Aliado / Sitio *",aliados_nombres,key="ag_aliado")
            a_li=st.selectbox("Línea de servicio",LINEAS,key="ag_linea")
            a_pr=st.selectbox("Prioridad",["🔴 Urgente (36h)","🟡 Normal (60h)","🟢 Puede esperar (90h)"],key="ag_prio")
            a_fe=st.date_input("Fecha límite",min_value=ahora().date(),key="ag_fecha")
            a_as=st.multiselect("Especialistas",["Andrés Tapiero","Especialista 1","Especialista 2","Especialista 3","Subcontratista"],key="ag_asig")
            a_sa=st.text_input("Colaborador satélite",key="ag_sat")
            a_ca=st.checkbox("¿Requiere visita en campo?",key="ag_campo")
            a_de=campo_voz("Descripción detallada","ag_desc",height=90)
            a_ei=campo_voz("Estado inicial","ag_estado_ini",height=70,placeholder="Cómo estaba antes...")
            a_re=campo_voz("Recomendaciones","ag_recom",height=70)
            a_le=campo_voz("Lección aprendida","ag_leccion",height=60)
            a_se=st.checkbox("¿Requiere seguimiento?",key="ag_seg")
            a_fs=st.date_input("Fecha seguimiento") if a_se else None

            checklist_items=[]
            if a_li in CHECKLISTS:
                st.markdown(f"**✅ Checklist — {a_li}**")
                for item in CHECKLISTS[a_li]:
                    checklist_items.append({"item":item,"completado":False})
                st.caption(f"{len(checklist_items)} ítems cargados")

            if st.button("👁️ Vista previa antes de guardar",use_container_width=True):
                if a_t.strip():
                    with st.spinner("Generando resumen..."):
                        resumen=ia_generar(f"""Resume esta tarea para JandrexT en máximo 5 líneas:
Tarea: {a_t}
Aliado: {a_al}
Línea: {a_li}
Prioridad: {a_pr}
Especialistas: {', '.join(a_as)}
Descripción: {a_de}
Formato: lista clara y concisa.""")
                    st.info(f"**Vista previa:**\n{resumen}")
                    st.session_state["ag_resumen"]=resumen
                    st.session_state["ag_listo"]=True
                else: st.warning("⚠️ Escribe la tarea primero")

            if st.session_state.get("ag_listo"):
                if st.button("✅ Confirmar y generar tarea",type="primary",use_container_width=True):
                    horas=36 if "Urgente" in a_pr else 60 if "Normal" in a_pr else 90
                    cliente_id=next((a["id"] for a in aliados_list if a["nombre"]==a_al),None)
                    data={"tarea":a_t,"cliente":a_al,"prioridad":a_pr,"horas_limite":horas,
                        "fecha_limite":str(ahora()+timedelta(hours=horas)),
                        "asignados":a_as,"satelite":a_sa,"campo":a_ca,
                        "descripcion":a_de,"estado_inicial":a_ei,"recomendaciones":a_re,
                        "leccion":a_le,"seguimiento":a_se,
                        "fecha_seguimiento":str(a_fs) if a_fs else None,
                        "checklist_tipo":a_li,"checklist_items":checklist_items,
                        "creado_por":u["id"]}
                    res=supa("agenda","POST",data)
                    if res:
                        asig=", ".join(a_as) if a_as else "Sin asignar"
                        telegram(f"📅 <b>Nueva tarea</b>\n📋 {a_t}\n🤝 {a_al}\n🔧 {a_li}\n👥 {asig}\n{a_pr}")
                        for k in ["ag_tarea","ag_desc","ag_estado_ini","ag_recom","ag_leccion"]:
                            st.session_state[k]=""
                        st.session_state["ag_listo"]=False
                        st.success("✅ Tarea creada"); st.rerun()
        else:
            st.info("Solo los administradores pueden crear tareas.")

    with col_l:
        st.markdown("### 📋 Tareas")
        c1,c2,c3=st.columns(3)
        buscar_a=c1.text_input("🔍 Buscar")
        filtro_est=c2.selectbox("Estado",["Todos","pendiente","en_proceso","completado"])
        filtro_pri=c3.selectbox("Prioridad",["Todas","Urgente","Normal","Puede esperar"])

        tareas=supa("agenda",filtro="?order=creado_en.desc") or []
        if rol=="tecnico": tareas=[t for t in tareas if nombre in (t.get("asignados") or [])]
        if buscar_a: tareas=[t for t in tareas if buscar_a.lower() in t.get("tarea","").lower() or buscar_a.lower() in t.get("cliente","").lower()]
        if filtro_est!="Todos": tareas=[t for t in tareas if t.get("estado")==filtro_est]
        if filtro_pri!="Todas": tareas=[t for t in tareas if filtro_pri in t.get("prioridad","")]

        m1,m2,m3=st.columns(3)
        m1.metric("Total",len(tareas))
        m2.metric("Pendientes",len([t for t in tareas if t.get("estado")=="pendiente"]))
        m3.metric("Urgentes",len([t for t in tareas if "Urgente" in t.get("prioridad","")]))

        for t in tareas:
            ico="🔴" if "Urgente" in t.get("prioridad","") else "🟡" if "Normal" in t.get("prioridad","") else "🟢"
            with st.expander(f"{ico} {t['tarea']} · {t.get('cliente','')} · {t.get('estado','pendiente')}"):
                st.markdown(f"**Línea:** {t.get('checklist_tipo','')} | **Límite:** {t.get('fecha_limite','')[:10]}")
                st.markdown(f"**Especialistas:** {', '.join(t.get('asignados') or [])}")
                if t.get("descripcion"): st.markdown(f"**Desc:** {t['descripcion']}")
                items=t.get("checklist_items") or []
                if items:
                    st.markdown(f"**✅ Checklist:**")
                    items_act=list(items); cambiado=False
                    for i,item in enumerate(items_act):
                        nv=st.checkbox(item["item"],value=item.get("completado",False),key=f"chk_{t['id']}_{i}")
                        if nv!=item.get("completado",False): items_act[i]["completado"]=nv; cambiado=True
                    if cambiado:
                        supa("agenda","PATCH",{"checklist_items":items_act},f"?id=eq.{t['id']}")
                        comp=sum(1 for x in items_act if x.get("completado"))
                        st.caption(f"✅ {comp}/{len(items_act)} completados")
                ne=st.selectbox("Estado",["pendiente","en_proceso","completado"],
                    index=["pendiente","en_proceso","completado"].index(t.get("estado","pendiente")),
                    key=f"est_{t['id']}")
                ef=st.text_area("Estado final / Evidencia",key=f"ef_{t['id']}",value=t.get("estado_final",""),height=60)
                ca,cb=st.columns([3,1])
                with ca:
                    if st.button("💾 Actualizar",key=f"upd_{t['id']}",use_container_width=True):
                        supa("agenda","PATCH",{"estado":ne,"estado_final":ef},f"?id=eq.{t['id']}")
                        if ne=="completado": telegram(f"✅ <b>Tarea completada</b>\n📋 {t['tarea']}\n🤝 {t.get('cliente','')}\n📝 {ef[:100]}")
                        st.success("✅ Actualizado"); st.rerun()
                with cb:
                    if puede_borrar(u):
                        if st.button("🗑️",key=f"dt_{t['id']}"):
                            supa("agenda","DELETE",filtro=f"?id=eq.{t['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ASISTENCIA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="asistencia":
    st.markdown("## 👥 Asistencia y Campo")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]

    geo_html="""<style>
    .gb{background:#cc0000;color:#fff;border:none;border-radius:12px;padding:0.9rem 1.2rem;
        font-size:1rem;font-weight:700;width:100%;cursor:pointer;margin:0.3rem 0;display:block;}
    .gs{background:#1a1a1a;border:2px solid #cc0000;color:#fff;}
    .gs-box{background:#0a0a0a;border:1px solid #333;border-radius:8px;padding:0.7rem;
        margin:0.4rem 0;color:#ccc;font-size:0.82rem;min-height:50px;}
    #mp{width:100%;height:180px;border-radius:8px;border:1px solid #cc0000;margin:0.4rem 0;}
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <div id="gs-status" class="gs-box">📍 Presiona para capturar ubicación GPS...</div>
    <div id="mp"></div>
    <button class="gb" onclick="gps('entrada')">✅ Registrar ENTRADA con GPS</button>
    <button class="gb gs" onclick="gps('salida')">🏁 Registrar SALIDA con GPS</button>
    <script>
    var map=L.map('mp').setView([4.711,-74.0721],11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var mk=null;
    function gps(tipo){
        document.getElementById('gs-status').innerHTML='⏳ Obteniendo GPS...';
        navigator.geolocation.getCurrentPosition(function(p){
            var lat=p.coords.latitude.toFixed(6),lng=p.coords.longitude.toFixed(6);
            document.getElementById('gs-status').innerHTML=(tipo=='entrada'?'✅':'🏁')+' <b>'+tipo.toUpperCase()+'</b><br>'+lat+', '+lng+' | Prec: '+Math.round(p.coords.accuracy)+'m';
            if(mk)map.removeLayer(mk);
            mk=L.marker([lat,lng]).addTo(map).bindPopup(tipo).openPopup();
            map.setView([lat,lng],15);
        },function(e){document.getElementById('gs-status').innerHTML='⚠️ '+e.message;},{enableHighAccuracy:true,timeout:15000});
    }
    </script>"""
    st.components.v1.html(geo_html,height=380,scrolling=False)

    st.markdown("### ✍️ Completar registro")
    with st.form("form_asist",clear_on_submit=True):
        c1,c2=st.columns(2)
        m_col=c1.text_input("👤 Especialista",value=nombre)
        m_tip=c2.selectbox("Tipo",["entrada","salida"])
        m_pro=st.selectbox("📍 Proyecto / Aliado",aliados_nombres)
        m_tar=st.text_input("🔧 Tarea realizada")
        m_lat=st.text_input("🌐 Latitud",placeholder="Del mapa GPS")
        m_lng=st.text_input("🌐 Longitud",placeholder="Del mapa GPS")
        sub=st.form_submit_button("💾 Guardar",use_container_width=True,type="primary")
        if sub:
            ub=f"{m_lat},{m_lng}" if m_lat and m_lng else ""
            supa("asistencia","POST",{"colaborador_id":u["id"],"colaborador_nombre":m_col,
                "tipo":m_tip,"proyecto":m_pro,"tarea":m_tar,"ubicacion":ub})
            emoji="✅" if m_tip=="entrada" else "🏁"
            telegram(f"{emoji} <b>{m_col}</b> — {m_tip}\n📍 {m_pro}\n📋 {m_tar}")
            st.success("✅ Registrado"); st.rerun()

    st.markdown('<hr class="divider">',unsafe_allow_html=True)
    st.markdown("### 📋 Informe de trabajo")
    st.markdown('<div class="tip">💡 Dicta o escribe lo que hiciste. El sistema genera el informe automáticamente.</div>',unsafe_allow_html=True)

    inf_aliado=st.selectbox("Proyecto / Aliado",aliados_nombres,key="inf_ali")
    inf_serv=st.selectbox("Tipo de servicio",LINEAS,key="inf_serv")
    inf_desc=campo_voz("Descripción del trabajo realizado","inf_desc",height=110,
        placeholder="Describe qué encontraste, qué hiciste y qué quedó...")
    inf_elem_uso=campo_voz("Elementos / materiales utilizados","inf_elem_uso",height=80,
        placeholder="Ej: 2 tornillos M8, 1 hidráulico Speedy M25, cable UTP 5m...")
    inf_elem_nec=campo_voz("Elementos que se necesitan / pendientes","inf_elem_nec",height=80,
        placeholder="Ej: Falta 1 cámara IP, reprogramar controladora...")
    inf_visita=st.selectbox("¿Requiere otra visita?",["No","Sí — urgente","Sí — programada"],key="inf_visita")

    if st.button("📋 Generar informe",type="primary"):
        if inf_desc.strip():
            with st.spinner("Generando informe profesional..."):
                prompt=f"""Genera un informe técnico profesional para JandrexT Soluciones Integrales.

Aliado/Proyecto: {inf_aliado}
Tipo de servicio: {inf_serv}
Especialista: {nombre}
Fecha: {fecha_str()}

Descripción del trabajo: {inf_desc}
Elementos utilizados: {inf_elem_uso}
Elementos pendientes/necesarios: {inf_elem_nec}
Requiere otra visita: {inf_visita}

Estructura el informe con:
1. Resumen ejecutivo
2. Estado encontrado
3. Trabajos realizados
4. Materiales utilizados
5. Pendientes y recomendaciones
6. ¿Requiere otra visita? ¿Por qué?
7. Plan de mantenimiento preventivo sugerido

Tono profesional y empático. Lema: Apasionados por el buen servicio."""
                informe=ia_generar(prompt)

            st.markdown('<div class="doc-borrador">',unsafe_allow_html=True)
            st.markdown(f"### 📋 Informe — {inf_aliado}")
            st.markdown(informe)
            st.markdown('</div>',unsafe_allow_html=True)
            st.code(informe,language=None)
            telegram(f"📋 <b>Informe generado</b>\n👤 {nombre}\n📍 {inf_aliado}\n🔧 {inf_serv}\n{'⚠️ Requiere visita: '+inf_visita if 'Sí' in inf_visita else ''}")

            # Descargar como HTML
            pdf_html=generar_pdf_html(f"Informe Técnico — {inf_aliado}",informe,logo_b64)
            st.download_button("📥 Descargar informe",data=pdf_html.encode("utf-8"),
                file_name=f"Informe_{inf_aliado}_{ahora().strftime('%Y%m%d')}.html",
                mime="text/html",use_container_width=True)
        else: st.warning("⚠️ Describe el trabajo realizado.")

    if rol=="admin":
        st.markdown('<hr class="divider">',unsafe_allow_html=True)
        st.markdown("### 🗺️ Especialistas en campo")
        hoy=ahora().strftime("%Y-%m-%d")
        regs=supa("asistencia",filtro=f"?fecha=gte.{hoy}T00:00:00&order=fecha.desc") or []
        activos=[r for r in regs if r.get("ubicacion") and r["tipo"]=="entrada" and not r.get("salida")]
        if activos:
            markers=""
            for r in activos:
                try:
                    lat,lng=r["ubicacion"].split(",")
                    cn=r.get("colaborador_nombre",""); pr=r.get("proyecto","")
                    markers+=f"L.marker([{lat},{lng}]).addTo(m).bindPopup('<b>{cn}</b><br>{pr}').openPopup();"
                except: pass
            mapa_html=f"""<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <div id="ma" style="width:100%;height:280px;border-radius:10px;border:1px solid #cc0000;"></div>
            <script>var m=L.map('ma').setView([4.711,-74.0721],11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);{markers}</script>"""
            st.components.v1.html(mapa_html,height=300)
            st.metric("En campo",len(activos))
        else: st.info("No hay especialistas con GPS activo.")

        st.markdown("### 📊 Registros de hoy")
        for r in regs:
            bg="#0a1a0a" if r["tipo"]=="entrada" else "#1a0a0a"
            ico="✅" if r["tipo"]=="entrada" else "🏁"
            st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.3rem;">
                {ico} <b>{r.get('colaborador_nombre','')}</b> · {r.get('fecha','')[:16]}<br>
                📍 {r.get('proyecto','')} · 📋 {r.get('tarea','')}
            </div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="documentos" and tiene_modulo(u,"documentos"):
    st.markdown("## 📄 Documentos")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    proyectos_list=supa("proyectos",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]
    proyectos_nombres=["Sin proyecto"]+[p["nombre"] for p in proyectos_list]

    TIPOS_DOC={"cotizacion":"Cotización","orden_trabajo":"Orden de Trabajo",
               "orden_servicio":"Orden de Servicio","contrato":"Contrato de Servicio",
               "acta_entrega":"Acta de Entrega","informe":"Informe Técnico"}

    tipo_doc=st.selectbox("Tipo de documento",list(TIPOS_DOC.keys()),format_func=lambda x:TIPOS_DOC[x])
    c1,c2=st.columns(2)
    doc_aliado=c1.selectbox("Aliado",aliados_nombres)
    doc_proy=c2.selectbox("Proyecto",proyectos_nombres)
    doc_linea=st.selectbox("Línea de servicio",LINEAS)
    doc_contenido=campo_voz("Describe el contenido del documento","doc_cont",height=150,
        placeholder="Describe equipos, actividades, condiciones específicas...")
    c1,c2,c3=st.columns(3)
    doc_valor=c1.number_input("Valor total (COP)",min_value=0,step=50000)
    doc_anticipo=c2.number_input("Anticipo (COP)",min_value=0,step=50000)
    doc_tipo_ali=c3.selectbox("Tipo aliado",["copropiedad","empresa","natural","administracion","otro"])
    if doc_tipo_ali=="otro":
        doc_tipo_otro=st.text_input("¿Cuál tipo de aliado?")

    # Datos del aliado seleccionado
    aliado_data=next((a for a in aliados_list if a["nombre"]==doc_aliado),{})

    if st.button("👁️ Generar borrador",use_container_width=True):
        if doc_contenido.strip():
            with st.spinner("Generando borrador..."):
                tipo_final=doc_tipo_otro if doc_tipo_ali=="otro" else doc_tipo_ali
                saldo=doc_valor-doc_anticipo
                prompt=f"""Genera un {TIPOS_DOC[tipo_doc]} profesional para JandrexT Soluciones Integrales.

DATOS DEL EMISOR:
Empresa: JANDREXT SOLUCIONES INTEGRALES
Representante: José Andrés Tapiero Gómez
NIT: 80818905-3 | Tel: 317 391 0621
Email: proyectos@jandrext.com
Dirección: CL 80 70C-67 Local 2, Barrio Bonanza, Bogotá D.C.

DATOS DEL ALIADO:
Razón Social: {aliado_data.get('razon_social',doc_aliado)}
NIT: {aliado_data.get('nit','')}
Dirección: {aliado_data.get('direccion','')} · {aliado_data.get('municipio','')}
Tel: {aliado_data.get('telefono','')} | Email: {aliado_data.get('email','')}
Contacto: {aliado_data.get('contacto','')} — {aliado_data.get('cargo_contacto','')}

PROYECTO: {doc_proy} | LÍNEA: {doc_linea}
VALOR TOTAL: ${doc_valor:,.0f} COP
ANTICIPO: ${doc_anticipo:,.0f} COP
SALDO: ${saldo:,.0f} COP
Fecha: {fecha_str()}

CONTENIDO: {doc_contenido}

Incluir: numeración automática, descripción técnica detallada, cuadro económico,
términos y condiciones JandrexT (16 puntos estándar), normas colombianas aplicables,
datos de pago (AV Villas 065779337, Caja Social 24109787510, Nequi 317 391 0621),
firma: José Andrés Tapiero Gómez, Director de Proyectos."""
                borrador=ia_generar(prompt,"gemini-1.5-pro")
                st.session_state["doc_borrador"]=borrador
                st.session_state["doc_listo"]=True
        else: st.warning("⚠️ Describe el contenido.")

    if st.session_state.get("doc_listo") and st.session_state.get("doc_borrador"):
        st.markdown('<div class="doc-borrador">',unsafe_allow_html=True)
        st.markdown(f"### 📄 Borrador — {TIPOS_DOC[tipo_doc]}")
        borrador=st.text_area("✏️ Revisa y edita si necesitas",value=st.session_state["doc_borrador"],height=400,key="doc_editor")
        st.markdown('</div>',unsafe_allow_html=True)

        c1,c2,c3=st.columns(3)
        with c1:
            if st.button("✅ Confirmar y guardar",type="primary",use_container_width=True):
                cliente_id=next((a["id"] for a in aliados_list if a["nombre"]==doc_aliado),None)
                proy_id=next((p["id"] for p in proyectos_list if p["nombre"]==doc_proy),None)
                supa("documentos","POST",{"tipo":tipo_doc,"contenido":borrador,
                    "cliente_id":cliente_id,"proyecto_id":proy_id,
                    "valor_total":doc_valor,"anticipo":doc_anticipo,"saldo":doc_valor-doc_anticipo,
                    "estado_pago":"pendiente","creado_por":u["id"]})
                st.session_state["doc_listo"]=False
                st.session_state["doc_borrador"]=""
                st.session_state["doc_cont"]=""
                st.success("✅ Documento guardado en el proyecto"); st.rerun()
        with c2:
            pdf_html=generar_pdf_html(f"{TIPOS_DOC[tipo_doc]} — {doc_aliado}",borrador,logo_b64)
            st.download_button("📥 Descargar",data=pdf_html.encode("utf-8"),
                file_name=f"{tipo_doc}_{doc_aliado}_{ahora().strftime('%Y%m%d')}.html",
                mime="text/html",use_container_width=True)
        with c3:
            email_dest=aliado_data.get("email","")
            if email_dest:
                if st.button(f"📧 Enviar a {email_dest[:20]}",use_container_width=True):
                    html_email=f"""<div style="font-family:Arial;max-width:700px;margin:auto;">
                    <div style="background:#0a0000;padding:15px;border-radius:8px;margin-bottom:20px;">
                    <span style="color:#cc0000;font-size:20px;font-weight:900;letter-spacing:3px;">JandrexT</span>
                    <span style="color:#fff;font-size:14px;"> Soluciones Integrales</span><br>
                    <span style="color:#cc4444;font-style:italic;font-size:12px;">Apasionados por el buen servicio</span>
                    </div>
                    <h2 style="color:#cc0000;">{TIPOS_DOC[tipo_doc]}</h2>
                    <pre style="white-space:pre-wrap;font-size:11px;">{borrador}</pre>
                    <hr><p style="color:#666;font-size:10px;">JandrexT Soluciones Integrales · NIT: 80818905-3 · proyectos@jandrext.com · 317 391 0621</p>
                    </div>"""
                    ok=enviar_email(email_dest,f"JandrexT — {TIPOS_DOC[tipo_doc]}",html_email)
                    if ok: st.success(f"✅ Enviado a {email_dest}")
            else:
                st.caption("⚠️ El aliado no tiene email registrado")

# ══════════════════════════════════════════════════════════════════════════════
# MANUALES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="manuales" and tiene_modulo(u,"manuales"):
    st.markdown("## 📖 Manuales")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]
    col_f,col_l=st.columns([2,1])
    with col_f:
        m_ali=st.selectbox("Proyecto / Aliado",aliados_nombres)
        m_sis=st.text_input("Sistema instalado",placeholder="Ej: DVR Hikvision DS-7208HGHI")
        m_tip=st.selectbox("Tipo de manual",["Manual de Usuario","Manual Técnico",
            "Guía de Configuración y Contraseñas","Plan de Mantenimiento Preventivo",
            "Manual de Operación Diaria","Guía de Acceso Remoto"])
        m_lin=st.selectbox("Línea de servicio",LINEAS)
        m_det=campo_voz("Detalles específicos","man_det",height=130,
            placeholder="IP, contraseñas, equipos instalados, configuración...")
        m_cli=st.selectbox("Tipo de destinatario",["copropiedad","empresa","natural","administracion"])
        if st.button("📖 Generar manual",type="primary",use_container_width=True):
            if m_sis and st.session_state.get("man_det","").strip():
                with st.spinner("Generando manual..."):
                    prompt=f"""Crea un {m_tip} completo para JandrexT Soluciones Integrales.
Lema: Apasionados por el buen servicio
Aliado/Proyecto: {m_ali} | Sistema: {m_sis} | Línea: {m_lin}
Destinatario: {m_cli} | Fecha: {fecha_str()}
Detalles: {st.session_state.get('man_det','')}

Incluir: portada JandrexT, índice, descripción del sistema,
instrucciones paso a paso (como para alguien sin experiencia técnica),
credenciales y accesos, problemas comunes y soluciones,
mantenimiento preventivo con frecuencias y señales de alerta,
contacto de soporte: Andrés Tapiero 317 391 0621 proyectos@jandrext.com
Tono: claro, empático, sin tecnicismos innecesarios."""
                    manual=ia_generar(prompt,"gemini-1.5-pro")
                    cliente_id=next((a["id"] for a in aliados_list if a["nombre"]==m_ali),None)
                    supa("manuales","POST",{"titulo":f"{m_tip} — {m_sis}","tipo":m_tip,
                        "sistema":m_sis,"contenido":manual,"cliente_id":cliente_id,"creado_por":u["id"]})
                st.markdown(f"### 📖 {m_tip}")
                st.markdown(manual)
                pdf_html=generar_pdf_html(f"{m_tip} — {m_sis}",manual,logo_b64)
                st.download_button("📥 Descargar manual",data=pdf_html.encode("utf-8"),
                    file_name=f"Manual_{m_sis}_{ahora().strftime('%Y%m%d')}.html",
                    mime="text/html",use_container_width=True)
                st.success("✅ Manual guardado")
                st.session_state["man_det"]=""
            else: st.warning("⚠️ Completa sistema y detalles.")
    with col_l:
        st.markdown("### 📚 Guardados")
        mans=supa("manuales",filtro="?order=creado_en.desc") or []
        for m in mans:
            with st.expander(f"📖 {m.get('tipo','')[:25]}"):
                st.caption(m.get("sistema",""))
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dm_{m['id']}"):
                        supa("manuales","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
                st.write(m.get("contenido","")[:300]+"...")

# ══════════════════════════════════════════════════════════════════════════════
# VENTAS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="ventas" and tiene_modulo(u,"ventas"):
    st.markdown("## 💼 Asistente de Ventas")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Nuevo aliado"]+[a["nombre"] for a in aliados_list]
    c1,c2=st.columns(2)
    with c1:
        v_ali=st.selectbox("Aliado",aliados_nombres)
        aliado_data=next((a for a in aliados_list if a["nombre"]==v_ali),{})
        v_li=st.selectbox("Línea de servicio",LINEAS)
        v_ne=campo_voz("¿Qué necesita el aliado?","ven_nec",height=100)
    with c2:
        v_ti=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion"])
        v_pr=st.selectbox("Presupuesto",["No definido","< $1M","$1M-$5M","$5M-$15M","$15M-$50M","> $50M"])
        v_ur=st.selectbox("Urgencia",["Normal","Urgente","Proyecto futuro"])
        v_co=st.text_input("Contacto / cargo",value=aliado_data.get("contacto",""))
    if st.button("💼 Generar propuesta",type="primary",use_container_width=True):
        if st.session_state.get("ven_nec","").strip():
            with st.spinner("Generando propuesta..."):
                prompt=f"""Genera una propuesta comercial empática y profesional para JandrexT Soluciones Integrales.
Aliado: {v_ali} | NIT: {aliado_data.get('nit','')} | Tipo: {v_ti}
Contacto: {v_co} | Tel: {aliado_data.get('telefono','')}
Línea de servicio: {v_li} | Presupuesto: {v_pr} | Urgencia: {v_ur}
Necesidad: {st.session_state.get('ven_nec','')}
Fecha: {fecha_str()}

Incluir: saludo personalizado, comprensión del problema, solución específica JandrexT,
equipos y materiales recomendados, beneficios concretos, garantías (equipos 12m, instalación 6m),
mantenimiento preventivo, próximos pasos y cierre empático.
Lema: Apasionados por el buen servicio."""
                prop=ia_generar(prompt,"gemini-1.5-pro")
            st.markdown(f"### 💼 Propuesta — {v_ali}")
            st.markdown(prop)
            pdf_html=generar_pdf_html(f"Propuesta Comercial — {v_ali}",prop,logo_b64)
            st.download_button("📥 Descargar propuesta",data=pdf_html.encode("utf-8"),
                file_name=f"Propuesta_{v_ali}_{ahora().strftime('%Y%m%d')}.html",
                mime="text/html",use_container_width=True)
            if aliado_data.get("email"):
                if st.button(f"📧 Enviar a {aliado_data['email']}"):
                    enviar_email(aliado_data["email"],"JandrexT — Propuesta Comercial",
                        f"<pre>{prop}</pre>")
        else: st.warning("⚠️ Describe la necesidad del aliado.")

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="biblioteca" and tiene_modulo(u,"biblioteca"):
    st.markdown("## 📚 Biblioteca")
    tab1,tab2=st.tabs(["🔍 Consultas guardadas","📖 Manual de la plataforma"])
    with tab1:
        buscar=campo_voz("🔍 Buscar en consultas","bib_buscar",height=60,placeholder="Escribe o dicta qué buscar...")
        msgs=supa("mensajes_chat",filtro="?order=creado_en.desc") or []
        filtrados=[m for m in msgs if not buscar or buscar.lower() in m.get("pregunta","").lower() or buscar.lower() in m.get("sintesis","").lower()]
        st.metric("Consultas encontradas",len(filtrados))
        for m in filtrados:
            with st.expander(f"📌 {m.get('pregunta','')[:60]}... | 📅 {m.get('creado_en','')[:10]}"):
                st.markdown(m.get("sintesis",""))
                st.code(m.get("sintesis",""),language=None)
                if puede_borrar(u):
                    if st.button("🗑️",key=f"db_{m['id']}"):
                        supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
    with tab2:
        modulos_por_rol = {
            "admin": ["Chats","Proyectos","Agenda","Asistencia","Biblioteca","Documentos","Manuales","Ventas","Aliados","Liquidaciones","Usuarios","Configuración"],
            "tecnico": ["Mi Agenda","Mi Asistencia","Consultas"],
            "cliente": ["Mis Solicitudes","Mis Manuales"],
        }
        modulo_sel=st.selectbox("¿Sobre qué módulo necesitas ayuda?",modulos_por_rol.get(rol,["General"]))
        if st.button("📖 Ver guía de uso",use_container_width=True):
            with st.spinner("Generando guía..."):
                guia=ia_generar(f"""Crea una guía paso a paso para usar el módulo "{modulo_sel}" de la plataforma JandrexT Soluciones Integrales.
El usuario es un {rol_label}. Usa lenguaje simple, empático y claro. Sin tecnicismos.
Incluye: para qué sirve, cómo usarlo paso a paso, consejos y preguntas frecuentes.
Máximo 400 palabras. Lema: Apasionados por el buen servicio.""")
            st.markdown(f"### 📖 Guía: {modulo_sel}")
            st.markdown(guia)

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
        l_dia=st.number_input("Días trabajados",0,31)
        l_sal=st.number_input("Salario base (COP)",0,step=50000)
        l_tip=st.selectbox("Tipo",["diario","proyecto"])
        d_pre=st.number_input("Préstamo/Anticipo",0,step=10000)
        d_otr=st.number_input("Otras deducciones",0,step=10000)
        bruto=l_sal*l_dia if l_tip=="diario" else l_sal
        dedu=d_pre+d_otr; neto=bruto-dedu
        st.markdown(f"**Bruto:** ${bruto:,.0f} | **Dedu:** ${dedu:,.0f}")
        st.markdown(f"### Total neto: ${neto:,.0f} COP")
        if st.button("💾 Generar y enviar",type="primary",use_container_width=True):
            cd=next((x for x in esp_list if x["nombre"]==l_col),None)
            if cd:
                supa("liquidaciones","POST",{"colaborador_id":cd["id"],
                    "periodo_inicio":str(l_ini),"periodo_fin":str(l_fin),
                    "dias_trabajados":l_dia,"salario_base":l_sal,"tipo_salario":l_tip,
                    "deducciones":[{"concepto":"Préstamo","valor":d_pre},{"concepto":"Otras","valor":d_otr}],
                    "total":neto})
                msg=f"""💰 <b>Liquidación JandrexT</b>
👤 {l_col} | 📅 {l_ini} al {l_fin}
📆 Días: {l_dia} | 💵 Base: ${l_sal:,.0f}
➖ Deducciones: ${dedu:,.0f}
✅ <b>Total: ${neto:,.0f} COP</b>"""
                telegram(msg)
                st.success("✅ Liquidación generada y notificada"); st.rerun()
    with col_l:
        st.markdown("### 📋 Historial")
        esp_sel=st.selectbox("Filtrar por especialista",["Todos"]+nombres_esp)
        liqs=supa("liquidaciones",filtro="?order=creado_en.desc") or []
        if esp_sel!="Todos":
            cd=next((x["id"] for x in esp_list if x["nombre"]==esp_sel),None)
            if cd: liqs=[l for l in liqs if l.get("colaborador_id")==cd]
        total_periodo=sum(l.get("total",0) for l in liqs)
        st.metric(f"Total pagado — {esp_sel}",f"${total_periodo:,.0f}")
        for liq in liqs:
            cn=next((x["nombre"] for x in esp_list if x["id"]==liq.get("colaborador_id")),"Desconocido")
            with st.expander(f"💰 {cn} · {liq.get('periodo_inicio','')} → {liq.get('periodo_fin','')}"):
                st.markdown(f"**Días:** {liq.get('dias_trabajados',0)} | **Total:** ${liq.get('total',0):,.0f} COP")
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dl_{liq['id']}"):
                        supa("liquidaciones","DELETE",filtro=f"?id=eq.{liq['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# REQUERIMIENTOS / SOLICITUDES
# ══════════════════════════════════════════════════════════════════════════════
elif sec in ["requerimientos","mis_manuales"]:
    st.markdown("## 🤝 Mis Solicitudes")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva solicitud")
        st.markdown('<div class="tip">💡 Tu solicitud llegará inmediatamente al equipo JandrexT por múltiples canales.</div>',unsafe_allow_html=True)
        r_ti=campo_voz("Asunto *","req_tit",height=70)
        r_de=campo_voz("Descripción detallada","req_desc",height=100)
        r_pr=st.selectbox("Urgencia",["normal","urgente","puede_esperar"])
        if st.button("📤 Enviar solicitud",type="primary",use_container_width=True):
            if st.session_state.get("req_tit","").strip():
                supa("requerimientos","POST",{"titulo":r_ti,"descripcion":r_de,"prioridad":r_pr})
                telegram(f"🔔 <b>Nueva solicitud de Aliado</b>\n📋 {r_ti}\n📝 {r_de[:100]}\n⚡ {r_pr}")
                st.success("✅ Solicitud enviada. JandrexT fue notificado."); st.balloons()
                st.session_state["req_tit"]=""; st.session_state["req_desc"]=""; st.rerun()
            else: st.warning("⚠️ El asunto es obligatorio")
    with col_l:
        st.markdown("### 📋 Mis solicitudes")
        reqs=supa("requerimientos",filtro="?order=creado_en.desc") or []
        for r in reqs:
            ico="✅" if r["estado"]=="resuelto" else "🔄" if r["estado"]=="en_proceso" else "🆕"
            with st.expander(f"{ico} {r['titulo']} · {r.get('estado','')}"):
                st.markdown(f"**Descripción:** {r.get('descripcion','')}")
                st.markdown(f"**Urgencia:** {r.get('prioridad','')} | **Fecha:** {r.get('creado_en','')[:10]}")
                if rol=="admin":
                    ne=st.selectbox("Estado",["nuevo","en_proceso","resuelto"],
                        index=["nuevo","en_proceso","resuelto"].index(r.get("estado","nuevo")),
                        key=f"re_{r['id']}")
                    if st.button("💾 Actualizar",key=f"ru_{r['id']}"):
                        supa("requerimientos","PATCH",{"estado":ne},f"?id=eq.{r['id']}"); st.rerun()
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dr_{r['id']}"):
                        supa("requerimientos","DELETE",filtro=f"?id=eq.{r['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# USUARIOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="usuarios" and rol=="admin":
    st.markdown("## 👑 Especialistas y Aliados")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo usuario")
        u_n=st.text_input("Nombre completo *")
        u_e=st.text_input("Email *")
        u_p=st.text_input("Contraseña temporal *",type="password")
        u_r=st.selectbox("Rol",["tecnico","vendedor","cliente","admin"],format_func=lambda x:ROL_LABEL.get(x,x))
        u_td=st.selectbox("Tipo documento",["cedula","cedula_extranjeria","pasaporte","nit"])
        u_nd=st.text_input("Número de documento *")
        u_cel=st.text_input("Celular principal *")
        u_cel2=st.text_input("Celular alternativo")
        u_ce=st.text_input("Contacto de emergencia")
        u_esp=st.selectbox("Especialidad",[""] + LINEAS)
        u_hab=st.multiselect("Habilidades secundarias",LINEAS)
        u_vin=st.selectbox("Vinculación",["directo","subcontratista","satelite"])
        u_m=st.multiselect("Módulos visibles",["chat","proyectos","agenda","asistencia",
            "biblioteca","documentos","manuales","ventas","aliados","liquidaciones"])
        if st.button("💾 Crear usuario",type="primary",use_container_width=True):
            if u_n and u_e and u_p and u_nd and u_cel:
                res=supa("usuarios","POST",{"nombre":u_n,"email":u_e,
                    "password_hash":hash_pwd(u_p),"rol":u_r,
                    "tipo_documento":u_td,"numero_documento":u_nd,
                    "celular":u_cel,"celular_alternativo":u_cel2,
                    "contacto_emergencia":u_ce,"especialidad_principal":u_esp,
                    "habilidades":u_hab,"tipo_vinculacion":u_vin,"modulos":u_m})
                if res:
                    telegram(f"👤 <b>Nuevo {ROL_LABEL.get(u_r,u_r)}</b>\n{u_n}\n📧 {u_e}\n📱 {u_cel}")
                    st.success(f"✅ {ROL_LABEL.get(u_r,u_r)} {u_n} creado"); st.rerun()
            else: st.warning("⚠️ Completa todos los campos obligatorios (*)")
    with col_l:
        st.markdown("### 📋 Usuarios")
        todos=supa("usuarios",filtro="?order=creado_en.desc") or []
        st.metric("Total",len(todos))
        for usr in todos:
            rl=ROL_LABEL.get(usr.get("rol",""),usr.get("rol",""))
            act="✅" if usr.get("activo") else "❌"
            with st.expander(f"👤 {usr['nombre']} · {rl} · {act}"):
                c1,c2=st.columns(2)
                c1.markdown(f"**Email:** {usr['email']}")
                c1.markdown(f"**Doc:** {usr.get('tipo_documento','')} {usr.get('numero_documento','')}")
                c1.markdown(f"**Celular:** {usr.get('celular','')}")
                c2.markdown(f"**Especialidad:** {usr.get('especialidad_principal','')}")
                c2.markdown(f"**Vinculación:** {usr.get('tipo_vinculacion','')}")
                c2.markdown(f"**Emergencia:** {usr.get('contacto_emergencia','')}")
                np=st.text_input("Nueva contraseña",type="password",key=f"pw_{usr['id']}")
                ca,cb=st.columns(2)
                with ca:
                    if st.button("🔑 Cambiar",key=f"cp_{usr['id']}"):
                        if np:
                            supa("usuarios","PATCH",{"password_hash":hash_pwd(np)},f"?id=eq.{usr['id']}")
                            st.success("✅ Contraseña actualizada")
                with cb:
                    bl="❌ Desactivar" if usr.get("activo") else "✅ Activar"
                    if st.button(bl,key=f"ac_{usr['id']}"):
                        supa("usuarios","PATCH",{"activo":not usr.get("activo")},f"?id=eq.{usr['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="config" and rol=="admin":
    st.markdown("## ⚙️ Configuración")
    tab1,tab2,tab3=st.tabs(["📧 Correo","🤖 Telegram","🧪 Testers"])

    with tab1:
        st.markdown("### 📧 Configuración de correo")
        gmail_user=os.getenv("GMAIL_USER","No configurado")
        st.info(f"**Cuenta activa:** {gmail_user}")
        st.markdown("Para cambiar la cuenta de correo, actualiza `GMAIL_USER` y `GMAIL_APP_PASSWORD` en Streamlit Secrets.")
        email_test=st.text_input("Enviar correo de prueba a:")
        if st.button("📧 Enviar prueba"):
            if email_test:
                ok=enviar_email(email_test,"JandrexT — Prueba de correo",
                    "<h2>✅ El sistema de correo funciona correctamente.</h2><p>JandrexT Soluciones Integrales · Apasionados por el buen servicio</p>")
                if ok: st.success("✅ Correo enviado correctamente")
            else: st.warning("⚠️ Ingresa un correo de destino")

    with tab2:
        st.markdown("### 🤖 Configuración Telegram")
        tg_token=os.getenv("TELEGRAM_BOT_TOKEN","No configurado")
        tg_chat=os.getenv("TELEGRAM_CHAT_ID_ADMIN","No configurado")
        st.info(f"**Bot:** @JandrexTAsistencia_bot\n**Chat ID:** {tg_chat}")
        if st.button("📱 Enviar mensaje de prueba"):
            telegram(f"✅ <b>Prueba de conexión JandrexT</b>\nPlataforma v12 funcionando correctamente.\n{fecha_str()}")
            st.success("✅ Mensaje enviado")

    with tab3:
        st.markdown("### 🧪 Gestión de datos de prueba")
        st.warning("⚠️ Esta acción eliminará TODOS los datos generados por los usuarios testers. No afecta datos de producción.")
        testers=["especialista@test.jandrext.com","aliado@test.jandrext.com"]
        tester_ids=[]
        for email_t in testers:
            res=supa("usuarios",filtro=f"?email=eq.{email_t}")
            if res and isinstance(res,list): tester_ids.append(res[0]["id"])

        if tester_ids:
            st.info(f"Testers encontrados: {len(tester_ids)}")
            if st.button("🗑️ Limpiar datos de testers",type="primary"):
                for tid in tester_ids:
                    supa("asistencia","DELETE",filtro=f"?colaborador_id=eq.{tid}")
                    chats_t=supa("chats",filtro=f"?usuario_id=eq.{tid}") or []
                    for c in chats_t:
                        supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                        supa("chats","DELETE",filtro=f"?id=eq.{c['id']}")
                supa("agenda","DELETE",filtro=f"?creado_por=eq.{tester_ids[0]}")
                st.success("✅ Datos de prueba eliminados correctamente")
        else:
            st.info("No se encontraron usuarios testers.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="footer-inst">
    <span class="footer-acc">JandrexT</span> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: <span class="footer-acc">Andrés Tapiero</span> &nbsp;·&nbsp;
    Plataforma v12.0 &nbsp;·&nbsp; 🔒 Sistema Interno<br>
    <span class="footer-lema">Apasionados por el buen servicio</span>
</div>""", unsafe_allow_html=True)
