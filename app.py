import streamlit as st
import os, time, json, uuid, hashlib, base64, concurrent.futures, smtplib
import requests as req
# google.generativeai reemplazado por REST directo para mayor compatibilidad
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from naomi_modulo import widget_naomi_dashboard, panel_torre_control
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
             get_font_b64("JennaSue.ttf") +
             get_font_b64("jenna-sue__allfont_net_.ttf") +
             get_font_b64("Pax_Oceania_Regular.ttf"))

# ── Logo ──────────────────────────────────────────────────────────────────────
logo_b64 = None
if Path("logo_jandrext.png").exists():
    logo_b64 = base64.b64encode(Path("logo_jandrext.png").read_bytes()).decode()

# ── Supabase ──────────────────────────────────────────────────────────────────
def get_secret(key, default=""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except:
        return os.getenv(key, default)

SUPA_URL = get_secret("SUPABASE_URL")
SUPA_KEY = get_secret("SUPABASE_ANON_KEY")

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
def enviar_email(dest, asunto, cuerpo):
    try:
        gu=get_secret("GMAIL_USER"); gp=get_secret("GMAIL_APP_PASSWORD")
        if not gu or not gp: return False
        msg=MIMEMultipart("alternative")
        msg["Subject"]=asunto; msg["From"]=f"JandrexT <{gu}>"; msg["To"]=dest
        msg.attach(MIMEText(cuerpo,"html","utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(gu,gp); s.sendmail(gu,dest,msg.as_string())
        return True
    except Exception as e: st.warning(f"⚠️ Error correo: {e}"); return False

# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram(msg):
    try:
        token=get_secret("TELEGRAM_BOT_TOKEN").strip()
        chat=get_secret("TELEGRAM_CHAT_ID_ADMIN").strip()
        if not token or not chat: return False, "Token o Chat ID vacío"
        r=req.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id":chat,"text":msg,"parse_mode":"HTML"},timeout=10)
        if r.status_code==200: return True, "OK"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e: return False, str(e)

# ── Constantes ────────────────────────────────────────────────────────────────
LINEAS = ["Automatización de accesos","Videovigilancia CCTV","Control de acceso y biometría",
          "Redes y comunicaciones","Sistemas eléctricos","Cerca eléctrica",
          "Soporte tecnológico","Desarrollo de software","Consultoría y diagnóstico"]

ROL_LABEL = {"admin":"Administrador","tecnico":"Especialista",
             "vendedor":"Asesor Comercial","cliente":"Aliado"}

CHECKLISTS = {
    "Videovigilancia CCTV":["Verificar estado de cámaras","Revisar señal en DVR/NVR",
        "Verificar grabación activa","Revisar disco duro","Verificar acceso remoto",
        "Limpiar lentes","Revisar cableado","Verificar fuentes de alimentación",
        "Ajustar ángulos","Documentar con fotos"],
    "Automatización de accesos":["Verificar motor","Revisar finales de carrera",
        "Lubricar partes mecánicas","Revisar tarjeta controladora","Verificar fotoceldas",
        "Revisar botón de paro","Verificar luz intermitente","Probar control remoto",
        "Revisar batería de respaldo","Documentar con fotos"],
    "Control de acceso y biometría":["Verificar lectura tarjetas/biometría",
        "Revisar comunicación TCP/IP","Verificar base de datos usuarios",
        "Revisar permisos por zonas","Verificar registro de eventos","Revisar cableado RS485",
        "Probar apertura/cierre","Verificar horarios","Revisar firmware","Documentar con fotos"],
    "Cerca eléctrica":["Revisar tensión del sistema","Verificar puesta a tierra",
        "Revisar hilos de cerca","Verificar energizador","Probar supervisión de corte",
        "Revisar señalización","Verificar batería","Revisar teclado","Documentar con fotos"],
}

CONTEXTO = """Eres asistente experto de JandrexT Soluciones Integrales — empresa colombiana apasionados por el buen servicio.
Servicios: automatización de accesos, videovigilancia CCTV, control de acceso y biometría,
redes y comunicaciones, sistemas eléctricos, cerca eléctrica, soporte tecnológico, desarrollo de software.
Director: Andrés Tapiero | Lema: Apasionados por el buen servicio | NIT: 80818905-3
Tel: 317 391 0621 | proyectos@jandrext.com | Bogotá, Colombia
Comportamiento: empático, profesional, práctico. Normas colombianas cuando aplique."""

# ── IAs ───────────────────────────────────────────────────────────────────────
# FIX 1 — Fallback de modelos Gemini (2.0 y 1.5 discontinuados jun/2026)
GEMINI_MODELS=["gemini-2.5-flash-lite","gemini-2.5-flash","gemini-2.5-flash-preview-05-20"]

def _gemini_call(prompt_txt, temperatura=0.7, max_tokens=1500, sistema=None):
    """Helper interno: intenta modelos Gemini en orden, retorna (texto, modelo) o (None, error_str)."""
    api_key=get_secret("GOOGLE_API_KEY")
    if not api_key: return None,"GOOGLE_API_KEY no configurada"
    headers={"Content-Type":"application/json","x-goog-api-key":api_key}
    errores=[]
    txt_prompt=((sistema or CONTEXTO)+"\n\nConsulta: "+prompt_txt) if sistema is not None else prompt_txt
    for modelo in GEMINI_MODELS:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        payload={"contents":[{"parts":[{"text":txt_prompt}]}],
                 "generationConfig":{"temperature":temperatura,"maxOutputTokens":max_tokens}}
        try:
            r=req.post(url,headers=headers,json=payload,timeout=30)
            if r.status_code==200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip(), modelo
            errores.append(f"{modelo}: HTTP {r.status_code}")
        except Exception as e:
            errores.append(f"{modelo}: {type(e).__name__}: {str(e)[:60]}")
    return None," | ".join(errores)

def gemini_fn(p, modelo=None, sistema=None):
    """Gemini para Mesa General — con fallback automático de modelos."""
    t=time.time()
    txt,mod=_gemini_call(p,temperatura=0.7,max_tokens=1500,sistema=(sistema or CONTEXTO))
    if txt: return {"ia":"Gemini","icono":"🔵","respuesta":txt,"modelo":mod,"tiempo":round(time.time()-t,2),"ok":True}
    return {"ia":"Gemini","icono":"🔴","respuesta":f"Gemini no disponible: {mod}","modelo":"none","tiempo":round(time.time()-t,2),"ok":False}

def gemini_mesa_fn(prompt_texto, temperatura=0.0, max_tokens=4000):
    """Gemini REST nativo puro — sin CONTEXTO JandrexT. Retorna solo texto con fallback."""
    txt,mod=_gemini_call(prompt_texto,temperatura=temperatura,max_tokens=max_tokens,sistema="")
    if txt: return txt
    return f"Error Gemini: {mod}"

def gemini_deporte_fn(p):
    """Gemini para análisis deportivo — sin CONTEXTO corporativo, fallback automático."""
    api_key=get_secret("GOOGLE_API_KEY")
    if not api_key:
        return {"ia":"Gemini","icono":"🔵","respuesta":"GOOGLE_API_KEY no configurada","tiempo":0,"ok":False}
    headers={"Content-Type":"application/json","x-goog-api-key":api_key}
    errores=[]
    for modelo in GEMINI_MODELS:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        payload={"contents":[{"parts":[{"text":p}]}],
                 "generationConfig":{"temperature":0.0,"maxOutputTokens":4000}}
        try:
            t=time.time()
            r=req.post(url,headers=headers,json=payload,timeout=30)
            if r.status_code==200:
                txt=r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                return {"ia":"Gemini","icono":"🔵","respuesta":txt,"modelo":modelo,"tiempo":round(time.time()-t,2),"ok":True}
            errores.append(f"{modelo}: HTTP {r.status_code}")
        except Exception as e:
            errores.append(f"{modelo}: {type(e).__name__}: {str(e)[:80]}")
    return {"ia":"Gemini","icono":"🔴","respuesta":"Gemini no disponible. Intentos: "+" | ".join(errores),"modelo":"none","tiempo":0,"ok":False}

def groq_fn(p):
    try:
        from groq import Groq; t=time.time()
        r=Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
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
        if r.status_code==200:
            d=r.json()
            txt=d["choices"][0]["message"]["content"].strip() if "choices" in d else str(d.get("result","")).strip()
            return {"ia":"Venice","icono":"🟣","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Venice","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Venice","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def mistral_fn(p):
    try:
        t=time.time()
        api_key=get_secret("MISTRAL_API_KEY")
        if not api_key: return {"ia":"Mistral","icono":"🟡","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
        r=req.post("https://api.mistral.ai/v1/chat/completions",
            json={"model":"mistral-small-latest",
                  "messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],
                  "max_tokens":1500},
            headers=h,timeout=30)
        if r.status_code==200:
            txt=r.json()["choices"][0]["message"]["content"].strip()
            return {"ia":"Mistral","icono":"🟡","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Mistral","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Mistral","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def openrouter_fn(p):
    try:
        t=time.time()
        api_key=get_secret("OPENROUTER_API_KEY")
        if not api_key: return {"ia":"OpenRouter","icono":"🔷","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
           "HTTP-Referer":"https://jandrext-ia.streamlit.app","X-Title":"JandrexT IA"}
        r=req.post("https://openrouter.ai/api/v1/chat/completions",
            json={"model":"meta-llama/llama-3.1-8b-instruct:free",
                  "messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],
                  "max_tokens":1500},
            headers=h,timeout=30)
        if r.status_code==200:
            txt=r.json()["choices"][0]["message"]["content"].strip()
            return {"ia":"OpenRouter","icono":"🔷","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"OpenRouter","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"OpenRouter","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def groq_simple(prompt):
    try:
        from groq import Groq
        r=Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":prompt}],max_tokens=1500)
        return r.choices[0].message.content.strip()
    except Exception as e: return f"❌ Error generando respuesta: {e}"

def juez_fn(pregunta, respuestas):
    ok_resps = [r for r in respuestas if r["ok"]]
    if not ok_resps: return "No se obtuvo respuesta de ninguna fuente."
    if len(ok_resps) == 1: return ok_resps[0]["respuesta"]
    resumen = "\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in ok_resps])
    prompt_juez = f"{CONTEXTO}\nPregunta del usuario: \"{pregunta}\"\nRespuestas de diferentes fuentes:\n{resumen}\n\nSintetiza la mejor respuesta: empática, profesional, práctica. Sin mencionar las fuentes ni encabezados."
    try:
        api_key = get_secret("GOOGLE_API_KEY")
        if api_key:
            _txt,_mod=_gemini_call(prompt_juez,temperatura=0.3,max_tokens=1500,sistema="")
            if _txt: return _txt
    except: pass
    try:
        return groq_simple(prompt_juez)
    except: pass
    return max(ok_resps, key=lambda x: len(x["respuesta"]))["respuesta"]

def ia_generar(prompt, modelo=None):
    try:
        txt,_=_gemini_call(prompt,temperatura=0.7,max_tokens=1500,sistema=CONTEXTO)
        if txt: return txt
        return groq_simple(prompt)
    except Exception as e: return groq_simple(prompt)

def ia_extraer_doc(b64, tipo="imagen"):
    prompt_json = """Eres un asistente que extrae datos de documentos colombianos (RUT, NIT, cámara de comercio).
Analiza el documento y devuelve SOLO un JSON válido con esta estructura exacta, sin texto adicional ni markdown:
{"razon_social":"","nit":"","direccion":"","municipio":"","departamento":"","telefono":"","email":"","contacto":"","cargo_contacto":"","responsabilidad_fiscal":"","regimen_fiscal":""}
Si no encuentras un dato, deja el campo vacío. NIT sin puntos ni guiones."""
    errores = []
    def parsear_json(txt):
        if not txt: return {}
        txt = txt.replace("```json","").replace("```","").strip()
        s = txt.find("{"); e = txt.rfind("}")+1
        if s>=0 and e>0:
            try: return json.loads(txt[s:e])
            except: pass
        return {}
    try:
        api_key = get_secret("GOOGLE_API_KEY")
        if api_key:
            mime = "application/pdf" if tipo=="pdf" else "image/jpeg"
            payload = {"contents":[{"parts":[{"text":prompt_json},{"inline_data":{"mime_type":mime,"data":b64}}]}],
                       "generationConfig":{"temperature":0.0,"maxOutputTokens":600}}
            headers_d={"Content-Type":"application/json","x-goog-api-key":api_key}
            _doc_ok=False
            for _m in GEMINI_MODELS:
                _doc_url=f"https://generativelanguage.googleapis.com/v1beta/models/{_m}:generateContent"
                r=req.post(_doc_url,headers=headers_d,json=payload,timeout=45)
                if r.status_code==200: _doc_ok=True; break
            if not _doc_ok: raise Exception(f"Todos los modelos fallaron")
            if _doc_ok:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                res = parsear_json(txt)
                if res.get("nit") or res.get("razon_social"): return res
    except Exception as e: errores.append(f"Gemini: {str(e)[:50]}")
    try:
        api_key = get_secret("OPENROUTER_API_KEY")
        if api_key:
            h = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
                 "HTTP-Referer":"https://jandrext-ia.streamlit.app","X-Title":"JandrexT IA"}
            mime = "application/pdf" if tipo=="pdf" else "image/jpeg"
            payload = {"model":"qwen/qwen2.5-vl-72b-instruct:free",
                       "messages":[{"role":"user","content":[
                           {"type":"text","text":prompt_json},
                           {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}}
                       ]}],"max_tokens":600}
            r = req.post("https://openrouter.ai/api/v1/chat/completions",headers=h,json=payload,timeout=45)
            if r.status_code == 200:
                txt = r.json()["choices"][0]["message"]["content"].strip()
                res = parsear_json(txt)
                if res.get("nit") or res.get("razon_social"): return res
    except Exception as e: errores.append(f"OpenRouter: {str(e)[:50]}")
    return {"_errores": " | ".join(errores)} if errores else {}

def generar_pdf_html(titulo, contenido):
    logo_tag=f'<img src="data:image/png;base64,{logo_b64}" style="height:55px;"/>' if logo_b64 else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;font-size:11px;margin:20px;color:#222;}}
.hdr{{display:flex;justify-content:space-between;border-bottom:2px solid #cc0000;padding-bottom:10px;margin-bottom:20px;}}
.brand{{color:#cc0000;font-size:18px;font-weight:900;letter-spacing:2px;}}
.lema{{color:#cc0000;font-style:italic;font-size:10px;}}
.tit{{text-align:center;font-size:13px;font-weight:bold;color:#cc0000;margin:15px 0;}}
pre{{white-space:pre-wrap;line-height:1.6;}}
.ftr{{border-top:1px solid #ccc;margin-top:20px;padding-top:8px;font-size:9px;color:#888;text-align:center;}}
</style></head><body>
<div class="hdr"><div>{logo_tag}<div class="brand">JandrexT</div>
<div style="font-size:9px;letter-spacing:2px;">SOLUCIONES INTEGRALES</div>
<div class="lema">Apasionados por el buen servicio</div></div>
<div style="text-align:right;font-size:9px;">Andrés Tapiero · 317 391 0621<br>proyectos@jandrext.com<br>Bogotá, Colombia<br>{fecha_str()}</div></div>
<div class="tit">{titulo}</div>
<pre>{contenido}</pre>
<div class="ftr">JandrexT Soluciones Integrales · NIT: 80818905-3 · CL 80 No. 70C-67 Local 2, Bogotá · Apasionados por el buen servicio</div>
</body></html>"""


def openai_fn(p):
    try:
        import openai; t=time.time()
        api_key=get_secret("OPENAI_API_KEY")
        if not api_key: return {"ia":"ChatGPT","icono":"\U0001f7e2","respuesta":"Sin API key","tiempo":0,"ok":False}
        client=openai.OpenAI(api_key=api_key)
        r=client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],
            max_tokens=1500,temperature=0.7)
        txt=r.choices[0].message.content.strip()
        return {"ia":"ChatGPT","icono":"\U0001f7e2","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"ChatGPT","icono":"\U0001f534","respuesta":str(e),"tiempo":0,"ok":False}

def claude_fn(p):
    try:
        import anthropic; t=time.time()
        api_key=get_secret("ANTHROPIC_API_KEY")
        if not api_key: return {"ia":"Claude","icono":"\U0001f7e4","respuesta":"Sin API key","tiempo":0,"ok":False}
        client=anthropic.Anthropic(api_key=api_key)
        r=client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=CONTEXTO,
            messages=[{"role":"user","content":p}])
        txt=r.content[0].text.strip()
        return {"ia":"Claude","icono":"\U0001f7e4","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"Claude","icono":"\U0001f534","respuesta":str(e),"tiempo":0,"ok":False}

# ── Micrófono HTML5 ───────────────────────────────────────────────────────────
def campo_voz_html5(label, key, height=100, placeholder="Escribe o usa el micrófono..."):
    if key not in st.session_state: st.session_state[key]=""
    uid = key.replace("-","_").replace(" ","_")
    mic_html = f"""
<div style="margin-bottom:6px;">
  <button id="micBtn_{uid}" onclick="toggleMic_{uid}()" style="
    background:#cc0000;color:#fff;border:none;border-radius:8px;
    padding:8px 18px;font-size:0.9rem;font-weight:700;cursor:pointer;
    margin-right:8px;transition:all 0.2s;">
    🎤 Iniciar grabación
  </button>
  <span id="micStatus_{uid}" style="font-size:0.8rem;color:#888;">
    Listo — Chrome/Edge recomendado
  </span>
</div>
<script>
var micRec_{uid}=null, micActive_{uid}=false;
function toggleMic_{uid}(){{
  var btn=document.getElementById('micBtn_{uid}');
  var sta=document.getElementById('micStatus_{uid}');
  if(micActive_{uid}){{
    if(micRec_{uid}) micRec_{uid}.stop();
    micActive_{uid}=false;
    btn.textContent='🎤 Iniciar grabación';
    btn.style.background='#cc0000';
    sta.textContent='Grabación detenida.';
    return;
  }}
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){{ sta.innerHTML='<span style="color:#f87171">⚠️ Usa Google Chrome o Edge</span>'; return; }}
  micRec_{uid}=new SR();
  micRec_{uid}.lang='es-CO';
  micRec_{uid}.interimResults=true;
  micRec_{uid}.continuous=true;
  micRec_{uid}.maxAlternatives=1;
  micRec_{uid}.onstart=function(){{
    micActive_{uid}=true;
    btn.textContent='⏹ Detener';
    btn.style.background='#7a0000';
    sta.innerHTML='<span style="color:#4ade80">🔴 Grabando... habla ahora</span>';
  }};
  micRec_{uid}.onresult=function(e){{
    var txt='';
    for(var i=e.resultIndex;i<e.results.length;i++){{
      if(e.results[i].isFinal) txt+=e.results[i][0].transcript+' ';
    }}
    if(!txt) return;
    txt=txt.trim();
    sta.innerHTML='<span style="color:#4ade80">✅ '+txt+'</span>';
    var tas=window.parent.document.querySelectorAll('textarea');
    for(var i=0;i<tas.length;i++){{
      if(tas[i].getAttribute('aria-label')==='{label}'){{
        var setter=Object.getOwnPropertyDescriptor(window.parent.HTMLTextAreaElement.prototype,'value').set;
        setter.call(tas[i],txt);
        tas[i].dispatchEvent(new Event('input',{{bubbles:true}}));
        break;
      }}
    }}
    micActive_{uid}=false;
    btn.textContent='🎤 Iniciar grabación';
    btn.style.background='#cc0000';
  }};
  micRec_{uid}.onerror=function(e){{
    sta.innerHTML='<span style="color:#f87171">Error: '+e.error+' — permite el micrófono en Chrome</span>';
    micActive_{uid}=false;
    btn.textContent='🎤 Iniciar grabación';
    btn.style.background='#cc0000';
  }};
  micRec_{uid}.onend=function(){{
    micActive_{uid}=false;
    btn.textContent='🎤 Iniciar grabación';
    btn.style.background='#cc0000';
  }};
  micRec_{uid}.start();
}}
</script>"""
    st.components.v1.html(mic_html, height=55)
    val=st.text_area(label,value=st.session_state.get(key,""),
        height=height,key=f"ta_{key}",placeholder=placeholder)
    st.session_state[key]=val
    return val

def panel_voz_global(campos_disponibles, seccion_key):
    if f"voz_{seccion_key}" not in st.session_state:
        st.session_state[f"voz_{seccion_key}"] = ""
    campos_lista = list(campos_disponibles.keys())
    uid = seccion_key.replace("-","_")
    html_mic = f"""
<div style="background:#0a0f00;border:1px solid #cc0000;border-radius:10px;padding:1rem;margin-bottom:8px;">
  <div style="color:#cc0000;font-size:0.75rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">DICTAR POR VOZ</div>
  <button id="btnToggle_{uid}" onclick="toggleRec_{uid}()" style="width:100%;background:#cc0000;color:#fff;border:none;border-radius:8px;padding:10px;font-size:14px;font-weight:700;cursor:pointer;margin-bottom:8px;">🎤 Iniciar grabación</button>
  <div id="status_{uid}" style="color:#888;font-size:12px;margin-bottom:6px;">Listo para grabar en Chrome/Edge</div>
  <div id="preview_{uid}" style="background:#0a1a00;border:1px solid #166534;border-radius:6px;padding:8px;color:#4ade80;font-size:13px;min-height:36px;margin-bottom:8px;"></div>
  <div style="display:flex;gap:8px;align-items:center;">
    <select id="campoSel_{uid}" style="flex:1;background:#1a0000;color:#ccc;border:1px solid #3a0000;border-radius:6px;padding:8px;font-size:13px;">
      {chr(10).join(f'<option value="{cx}">{cx}</option>' for cx in campos_lista)}
    </select>
    <button onclick="insertarTexto_{uid}()" style="background:#166534;color:#fff;border:none;border-radius:6px;padding:8px 14px;font-size:13px;font-weight:700;cursor:pointer;">Insertar</button>
    <button onclick="limpiarTexto_{uid}()" style="background:#333;color:#888;border:none;border-radius:6px;padding:8px 10px;font-size:13px;cursor:pointer;">X</button>
  </div>
</div>
<script>
(function() {{
  var rec_{uid}=null,activo_{uid}=false,textoCapturado_{uid}='';
  window.toggleRec_{uid}=function(){{
    var btn=document.getElementById('btnToggle_{uid}');
    var sta=document.getElementById('status_{uid}');
    if(activo_{uid}){{if(rec_{uid})rec_{uid}.stop();return;}}
    var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!SR){{sta.innerHTML='<span style="color:#f87171">⚠️ Usa Chrome o Edge</span>';return;}}
    rec_{uid}=new SR();rec_{uid}.lang='es-CO';rec_{uid}.interimResults=true;rec_{uid}.continuous=true;
    rec_{uid}.onstart=function(){{activo_{uid}=true;btn.textContent='⏹ Detener';btn.style.background='#7a0000';sta.innerHTML='<span style="color:#4ade80">🔴 Grabando...</span>';}};
    rec_{uid}.onresult=function(e){{var txt=e.results[0][0].transcript;textoCapturado_{uid}=txt;document.getElementById('preview_{uid}').textContent=txt;sta.innerHTML='<span style="color:#4ade80">✅ '+txt+'</span>';}};
    rec_{uid}.onerror=function(e){{sta.innerHTML='<span style="color:#f87171">Error: '+e.error+'</span>';activo_{uid}=false;btn.textContent='🎤 Iniciar grabación';btn.style.background='#cc0000';}};
    rec_{uid}.onend=function(){{activo_{uid}=false;btn.textContent='🎤 Iniciar grabación';btn.style.background='#cc0000';}};
    rec_{uid}.start();
  }};
  window.insertarTexto_{uid}=function(){{
    var txt=textoCapturado_{uid};
    if(!txt){{document.getElementById('status_{uid}').innerHTML='<span style="color:#facc15">Sin texto</span>';return;}}
    var sel=document.getElementById('campoSel_{uid}').value;
    var tas=window.parent.document.querySelectorAll('textarea');
    for(var i=0;i<tas.length;i++){{
      var lbl=tas[i].getAttribute('aria-label')||'';
      if(lbl&&(lbl.indexOf(sel)>=0||sel.indexOf(lbl)>=0)){{
        var setter=Object.getOwnPropertyDescriptor(window.parent.HTMLTextAreaElement.prototype,'value').set;
        setter.call(tas[i],(tas[i].value?tas[i].value+' ':'')+txt);
        tas[i].dispatchEvent(new Event('input',{{bubbles:true}}));
        document.getElementById('status_{uid}').innerHTML='<span style="color:#4ade80">✅ Insertado</span>';
        textoCapturado_{uid}='';break;
      }}
    }}
  }};
  window.limpiarTexto_{uid}=function(){{textoCapturado_{uid}='';document.getElementById('preview_{uid}').textContent='';document.getElementById('status_{uid}').textContent='Listo.';}};
}})();
</script>"""
    st.components.v1.html(html_mic, height=240, scrolling=False)
    st.caption("💡 Si el texto no aparece automáticamente, cópialo del panel verde y pégalo.")

# ── Config página ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="JandrexT | Plataforma v16",page_icon="🔒",
    layout="wide",initial_sidebar_state="expanded")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""<style>
{FONTS_CSS}
.logo-inst,.lema-inst,.sb-name,.h-name,.h-lema,.footer-lema{{font-family:'Disclaimer-Classic','Disclaimer-Plain',sans-serif !important;}}
.lema-jenna,.sb-lema,.footer-lema-j{{font-family:'JennaSue',sans-serif !important;}}
html,body,[class*="css"]{{font-family:'Inter','Helvetica Neue',Arial,sans-serif;}}
.login-wrap{{max-width:520px;margin:2.5rem auto;background:#0f0000;border:1px solid #cc0000;border-radius:16px;padding:2.5rem;}}
.header-inst{{background:#fff;border-radius:12px;padding:1rem 2rem;margin-bottom:1rem;border:2px solid #cc0000;display:flex;align-items:center;justify-content:space-between;gap:1.5rem;box-shadow:0 2px 12px rgba(204,0,0,0.15);}}
.h-logo{{height:80px;width:auto;flex-shrink:0;}}
.h-brand{{flex:1;}}
.h-name{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;font-size:2.2rem;font-weight:900;letter-spacing:6px;margin:0;line-height:1.2;}}
.h-acc{{color:#0a0000;}}
.h-lema{{font-family:'JennaSue','Georgia',serif;color:#cc0000;font-size:1.1rem;margin:0.2rem 0;font-style:italic;}}
.h-sub{{font-family:'Pax_Oceania_Regular','Georgia',serif;color:#666;font-size:0.75rem;letter-spacing:4px;text-transform:uppercase;margin:0.1rem 0;}}
.h-user{{text-align:right;flex-shrink:0;}}
.h-saludo{{font-family:'JennaSue','Georgia',serif;color:#cc0000;font-size:1.2rem;font-style:italic;}}
.h-nombre{{color:#0a0000;font-weight:700;font-size:1.1rem;}}
.h-rol{{color:#cc0000;font-size:0.8rem;letter-spacing:1px;text-transform:uppercase;}}
.h-fecha{{color:#888;font-size:0.8rem;margin-top:0.2rem;}}
.sb-wrap{{background:#fff;border:2px solid #cc0000;border-radius:10px;padding:0.8rem;text-align:center;margin-bottom:0.5rem;}}
.sb-name{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;font-size:1.4rem;font-weight:900;margin:0;letter-spacing:4px;}}
.sb-acc{{color:#0a0000;}}
.sb-sub{{font-family:'Pax_Oceania_Regular','Georgia',serif;color:#333;font-size:0.7rem;margin:0.1rem 0;letter-spacing:3px;text-transform:uppercase;}}
.sb-lema{{font-family:'JennaSue',sans-serif;color:#cc0000;font-size:0.95rem;margin:0.2rem 0 0;}}
.ub{{background:#1a0000;border:1px solid #cc0000;border-radius:8px;padding:0.5rem 0.8rem;margin-bottom:0.5rem;text-align:center;}}
.ub-n{{color:#ffcccc;font-size:0.9rem;font-weight:700;margin:0;}}
.ub-r{{color:#cc0000;font-size:0.72rem;margin:0;text-transform:uppercase;letter-spacing:1px;}}
.nav-title{{background:#1a0000;border:1px solid #cc0000;border-radius:6px;padding:0.3rem 0.7rem;color:#cc0000;font-size:0.72rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin:0.5rem 0 0.2rem;display:block;}}
.ia-card{{background:#0f0000;border:1px solid #2a0000;border-radius:10px;padding:0.8rem;}}
.ia-card h4{{margin:0 0 0.2rem;font-size:0.95rem;color:#f0f0f0;font-weight:600;}}
.badge-ok{{color:#4ade80;font-weight:600;font-size:0.82rem;}}
.badge-err{{color:#f87171;font-weight:600;font-size:0.82rem;}}
.t-seg{{color:#555;font-size:0.72rem;}}
.resp-card{{background:#0f0000;border:2px solid #cc0000;border-radius:12px;padding:1.4rem;color:#f0f0f0;line-height:1.75;margin-top:0.5rem;}}
.resp-titulo{{font-family:'Inter',sans-serif;color:#cc0000;font-size:0.7rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:0.8rem;}}
.chat-u{{background:#1a0000;border:1px solid #cc0000;border-radius:12px 12px 4px 12px;padding:0.8rem 1rem;margin:0.3rem 0;color:#f0f0f0;font-size:0.95rem;}}
.chat-ia{{background:#0a0a0a;border:1px solid #222;border-radius:12px 12px 12px 4px;padding:0.8rem 1rem;margin:0.3rem 0;color:#ddd;font-size:0.95rem;}}
.meta{{color:#555;font-size:0.72rem;margin-bottom:0.2rem;}}
.tip{{background:#0a0f00;border-left:3px solid #cc0000;border-radius:0 6px 6px 0;padding:0.5rem 0.8rem;color:#999;font-size:0.82rem;margin:0.4rem 0;}}
.doc-borrador{{background:#0a0f0a;border:1px solid #166534;border-radius:10px;padding:1.2rem;}}
.footer-inst{{background:#0a0000;border:1px solid #1a0000;border-radius:8px;padding:0.7rem;text-align:center;margin-top:1.5rem;color:#555;font-size:0.75rem;}}
.footer-acc{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-weight:700;}}
.footer-lema-j{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:0.95rem;}}
.divider{{border:none;border-top:1px solid #1a0000;margin:1rem 0;}}
.garantia-ok{{color:#4ade80;font-size:0.8rem;}}
.garantia-alerta{{color:#f87171;font-size:0.8rem;}}
div[data-testid="stSidebar"] .stButton>button{{background:transparent;border:1px solid #2a0000;color:#ccc;border-radius:8px;text-align:left;padding:0.5rem 0.8rem;font-size:0.9rem;transition:all 0.2s;}}
div[data-testid="stSidebar"] .stButton>button:hover{{background:#1a0000;border-color:#cc0000;color:#fff;}}
@media(max-width:768px){{
    .header-inst{{flex-direction:column;padding:0.8rem;gap:0.5rem;}}
    .h-user{{text-align:left;}}
    .h-logo{{height:50px;}}
    .h-name{{font-size:1.8rem;letter-spacing:4px;}}
    .stButton>button{{min-height:50px;font-size:1rem;}}
    .stTextInput>div>input{{min-height:46px;font-size:1rem;}}
    h2{{font-size:1.4rem;}} h3{{font-size:1.1rem;}}
}}
</style>""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for k,v in [("usuario",None),("seccion","inicio"),("chat_activo",None),
            ("proy_activo",None),("proy_nombre",""),("sc_activo",None),
            ("confirm_logout",False)]:
    if k not in st.session_state: st.session_state[k]=v

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.usuario:
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        if logo_b64:
            logo_login = f'<img src="data:image/png;base64,{logo_b64}" style="height:140px;width:auto;display:block;margin:0 auto 0.5rem;filter:drop-shadow(0 2px 8px rgba(0,0,0,0.3));"/>'
        else:
            logo_login = '<div style="font-family:sans-serif;color:#cc0000;font-size:3rem;font-weight:900;text-align:center;">JandrexT</div>'
        st.markdown(f"""<div class="login-wrap">
        <div style="text-align:center;margin-bottom:1.5rem;">
            {logo_login}
            <p style="font-family:\'JennaSue\',serif;color:#cc0000;font-size:2rem;margin:0.2rem 0;font-style:italic;">Apasionados por el buen servicio</p>
        </div></div>""", unsafe_allow_html=True)
        st.markdown("### 🔐 Iniciar sesión")
        saved_email = ""
        try: saved_email = st.query_params.get("em","")
        except: pass
        email=st.text_input("Correo electrónico",value=saved_email,placeholder="usuario@jandrext.com")
        pwd=st.text_input("Contraseña",type="password")
        recordar=st.checkbox("Recordar en este dispositivo", value=bool(saved_email))
        if st.button("Ingresar",type="primary",use_container_width=True):
            if email and pwd:
                with st.spinner("Verificando..."):
                    usuario,error=verificar_login(email.strip(),pwd.strip())
                if usuario:
                    st.session_state.usuario=usuario
                    if recordar:
                        try: st.query_params["em"]=email.strip()
                        except: pass
                    st.rerun()
                else: st.error(error)
            else: st.warning("⚠️ Completa todos los campos.")
        st.caption("¿Olvidaste tu contraseña? Contacta: proyectos@jandrext.com · 317 391 0621")
    st.stop()

u=st.session_state.usuario
rol=u.get("rol",""); nombre=u.get("nombre","")
rol_label=ROL_LABEL.get(rol,rol)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    logo_sb = f'<img src="data:image/png;base64,{logo_b64}" style="height:60px;width:auto;margin-bottom:4px;"/><br/>' if logo_b64 else ""
    st.markdown(f"""<div class="sb-wrap">
        {logo_sb}
        <p class="sb-lema">Apasionados por el buen servicio</p>
    </div>
    <div class="ub"><p class="ub-n">👤 {nombre}</p><p class="ub-r">{rol_label}</p></div>""",
    unsafe_allow_html=True)
    st.markdown('<span class="nav-title">📌 Navegación</span>',unsafe_allow_html=True)
    sec_actual=st.session_state.seccion
    if rol=="cliente":
        SECS=[("📋","requerimientos","Mis Solicitudes"),("📖","mis_manuales","Mis Manuales")]
    elif rol=="tecnico":
        SECS=[("📅","agenda","Mi Agenda"),("👥","asistencia","Mi Asistencia"),("💬","chat","Consultas")]
    else:
        SECS=[("🏠","inicio","Inicio"),("💬","chat","Chats"),("📁","proyectos","Proyectos"),
              ("📅","agenda","Agenda"),("👥","asistencia","Asistencia"),
              ("📚","biblioteca","Biblioteca"),("📄","documentos","Documentos"),
              ("📖","manuales","Manuales"),("💼","ventas","Ventas"),
              ("🤝","aliados","Aliados"),("📊","liquidaciones","Liquidaciones"),
              ("👑","usuarios","Especialistas y Aliados"),("⚙️","config","Configuración"),
              ("🧠","mesa_ia","Mesa IA")]
    for ico,key,label in SECS:
        es_activo = sec_actual==key
        btn_style = "primary" if es_activo else "secondary"
        prefijo = "▶ " if es_activo else ""
        if st.button(f"{ico} {prefijo}{label}",key=f"nav_{key}",
                     use_container_width=True,type=btn_style):
            for k in list(st.session_state.keys()):
                if k.startswith("ta_") or k.startswith("inp_"):
                    st.session_state[k]=""
            st.session_state.seccion=key
            st.session_state.chat_activo=None
            st.rerun()

    # Cargar configuración IAs
    if "ia_config_cargada" not in st.session_state:
        try:
            cfg=supa("configuracion_ia",filtro="?clave=eq.ia_config")
            if cfg and isinstance(cfg,list) and cfg:
                vals=json.loads(cfg[0].get("valor","{}"))
                st.session_state.ia_usar_g=vals.get("usar_g",True)
                st.session_state.ia_usar_r=vals.get("usar_r",True)
                st.session_state.ia_usar_v=vals.get("usar_v",False)
                st.session_state.ia_usar_m=vals.get("usar_m",True)
                st.session_state.ia_usar_o=vals.get("usar_o",True)
                st.session_state.ia_debug_mode=vals.get("debug",False)
            else:
                st.session_state.ia_usar_g=True
                st.session_state.ia_usar_r=True
                st.session_state.ia_usar_v=False
                st.session_state.ia_usar_m=True
                st.session_state.ia_usar_o=True
                st.session_state.ia_debug_mode=False
        except:
            st.session_state.ia_usar_g=True
            st.session_state.ia_usar_r=True
            st.session_state.ia_usar_v=False
            st.session_state.ia_usar_m=True
            st.session_state.ia_usar_o=True
            st.session_state.ia_debug_mode=False
        st.session_state.ia_config_cargada=True
    usar_g=st.session_state.ia_usar_g
    usar_r=st.session_state.ia_usar_r
    usar_v=st.session_state.ia_usar_v
    usar_m=st.session_state.ia_usar_m
    usar_o=st.session_state.ia_usar_o

    st.markdown("---")
    if st.button("🚪 Cerrar sesión",use_container_width=True):
        if st.session_state.confirm_logout:
            st.session_state.clear(); st.rerun()
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
        <p class="h-sub">Soluciones Integrales · Plataforma v16.0</p>
    </div>
    <div class="h-user">
        <div class="h-saludo">{saludo},</div>
        <div class="h-nombre">{nombre}</div>
        <div class="h-rol">{rol_label}</div>
        <div class="h-fecha">{fecha_str()}</div>
    </div>
</div>""", unsafe_allow_html=True)

sec=st.session_state.seccion

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
    st.markdown('<div class="tip">💡 Escriba su consulta o use el micrófono (Chrome/Edge). Presione Consultar al terminar.</div>',unsafe_allow_html=True)
    ik=f"inp_{chat_id}"
    if ik not in st.session_state: st.session_state[ik]=""
    campo_voz_html5("Tu consulta",ik,height=90,placeholder="Escribe o dicta su consulta técnica...")
    pregunta=st.session_state.get(ik,"")
    c1,c2,c3=st.columns([1,2,1])
    with c2:
        btn=st.button("🔍 Consultar",use_container_width=True,type="primary",key=f"btn_{chat_id}")
    if btn and pregunta.strip():
        fns=[]
        if usar_g: fns.append(lambda p: gemini_fn(p))
        if usar_r: fns.append(lambda p: groq_fn(p))
        if usar_v: fns.append(lambda p: venice_fn(p))
        if usar_m: fns.append(lambda p: mistral_fn(p))
        if usar_o: fns.append(lambda p: openrouter_fn(p))
        if not fns: fns=[lambda p: groq_fn(p)]
        with st.spinner("Consultando..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
                resultados=list(ex.map(lambda f:f(pregunta),fns))
        if rol=="admin" and st.session_state.get("ia_debug_mode",False):
            cols=st.columns(len(resultados))
            for i,res in enumerate(resultados):
                with cols[i]:
                    cls="badge-ok" if res["ok"] else "badge-err"
                    st.markdown(f'<div class="ia-card"><h4>{res["icono"]} {res["ia"]}</h4><span class="{cls}">{"✓" if res["ok"] else "✗"}</span><span class="t-seg"> ⏱{res["tiempo"]}s</span></div>',unsafe_allow_html=True)
        ok=[r for r in resultados if r["ok"]]
        if ok:
            with st.spinner("Procesando respuesta..."):
                sintesis=juez_fn(pregunta,ok)
            firma = "\n\n---\n*JandrexT Soluciones Integrales · Apasionados por el buen servicio · proyectos@jandrext.com · 317 391 0621*"
            st.markdown(f'<div class="resp-card"><div class="resp-titulo">🏛️ RESPUESTA JANDREXT · {ctx}</div>{sintesis}{firma}</div>',unsafe_allow_html=True)
            with st.expander("📋 Copiar texto"): st.code(sintesis,language=None)
            cnt=len(supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}") or [])
            if cnt==0: supa("chats","PATCH",{"titulo":pregunta[:50]},f"?id=eq.{chat_id}")
            supa("mensajes_chat","POST",{"chat_id":chat_id,"pregunta":pregunta,
                "sintesis":sintesis,"ias_usadas":[r["ia"] for r in ok]})
            st.session_state[ik]=""
            st.rerun()
    elif btn: st.warning("⚠️ Escribe o dicta una consulta.")

# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES FOOTBALL LAB — Correcciones 1/2/3
# ══════════════════════════════════════════════════════════════════════════════

def detectar_texto_futbol_1x2(texto):
    """Detecta automáticamente si el texto pegado contiene partidos/cuotas deportivas."""
    import re
    if not texto: return False
    t=texto.lower()
    kw=["empate","mundial","group","grupo","octavos","cuartos","semifinal","final",
        "copa","league","premier","liga","bundesliga","serie a","ligue","mls",
        "wplay","betplay","codere","1x2","parlay","apuesta"]
    if any(k in t for k in kw): return True
    decimals=re.findall(r'\b\d+\.\d{1,2}\b',texto)
    if len(decimals)>=3: return True
    if '★' in texto and re.search(r'\d+\.\d{2}',texto): return True
    return False

def limpiar_texto_wplay(texto):
    """Universal Wplay: ★ como separador de línea, luego limpieza. PRESERVA newlines."""
    import re
    # ★ separa elementos en Wplay — convertir a newline
    texto=texto.replace("★","\n").replace("⭐","\n")
    # Eliminar códigos de evento (3+ dígitos > 200)
    texto=re.sub(r'\b[2-9]\d{2,}\b','',texto)
    # Eliminar artefactos de paginación
    texto=re.sub(r'P[aá]gina ant\.?|Siguiente p[aá]gina|\d+\s*/\s*\d+','',texto,flags=re.IGNORECASE)
    # Separar cuota pegada a siguiente hora: "7.00 17:00" → "7.00\n17:00"
    texto=re.sub(r'(\d+\.\d+)\s+(\d{1,2}:\d{2})',r'\1\n\2',texto)
    # Colapsar espacios dentro de cada línea, preservar newlines
    lineas=[re.sub(r'[ \t]+',' ',l).strip() for l in texto.split('\n')]
    return '\n'.join(l for l in lineas if l)

def parser_regex_wplay(texto_limpio):
    """Parser universal Wplay — maneja:
    A) 'Equipo X.XX' en misma línea + 'Empate X.XX' en misma línea (post-limpieza ★→newline)
    B) 'Equipo' en línea + 'X.XX' en siguiente (un elemento por línea)
    C) '14:00 15 Jun' hora+fecha combinada en misma línea."""
    import re
    def _es_cuota(s): return bool(re.match(r'^\d+\.\d+$',s))
    def _es_empate(s): return bool(re.match(r'^[Ee]mpate$',s))
    def _es_empate_cuota(s):
        m=re.match(r'^[Ee]mpate\s+(\d+\.\d+)$',s); return m.group(1) if m else None
    def _es_hora_fecha(s): return bool(re.match(r'^\d{1,2}:\d{2}\s+\d{1,2}\s+\w+',s))
    def _es_hora(s): return bool(re.match(r'^\d{1,2}:\d{2}$',s))
    def _es_fecha(s): return bool(re.match(r'^\d{1,2}\s+[A-Za-z\u00c0-\u024f]{3,}$',s))
    def _team_cuota(s):
        m=re.match(r'^(.+?)\s+(\d+\.\d+)$',s)
        return (m.group(1).strip(),float(m.group(2))) if m else None
    def _full_match_line(s):
        """Detecta 'Equipo X.XX Empate X.XX' todo en una línea (formato compacto Wplay)."""
        m=re.match(r'^(.+?)\s+(\d+\.\d+)\s+[Ee]mpate\s+(\d+\.\d+)$',s)
        return (m.group(1).strip(),float(m.group(2)),float(m.group(3))) if m else None
    partidos=[]; lineas=[l.strip() for l in texto_limpio.split('\n') if l.strip()]
    hora=""; fecha=""; i=0
    while i<len(lineas):
        l=lineas[i]
        if _es_hora_fecha(l):
            mhf=re.match(r'^(\d{1,2}:\d{2})\s+(.+)$',l)
            if mhf: hora=mhf.group(1); fecha=mhf.group(2).strip()
            i+=1; continue
        if _es_hora(l): hora=l; i+=1; continue
        if _es_fecha(l): fecha=l; i+=1; continue
        if _es_cuota(l): i+=1; continue
        if _es_empate(l): i+=1; continue
        # Formato compacto: "Equipo1 X.XX Empate X.XX" en misma línea
        fm=_full_match_line(l)
        if fm:
            equipo1,cuota1,cuotax=fm; i+=1
            equipo2=None; cuota2=None
            if i<len(lineas):
                tc2=_team_cuota(lineas[i])
                if tc2 and not _es_empate(tc2[0]):
                    equipo2,cuota2=tc2; i+=1
                elif i+1<len(lineas) and _es_cuota(lineas[i+1]):
                    equipo2=lineas[i]; cuota2=float(lineas[i+1]); i+=2
            if equipo2:
                partidos.append({"local":equipo1,"visitante":equipo2,"cuota_1":cuota1,"cuota_x":cuotax,"cuota_2":cuota2,"hora":hora,"fecha":fecha,"fuente":"manual","cuotas_estimadas":False,"contexto_h2h":"","observacion":""})
            continue
        # Intentar extraer partido — equipo1+cuota1
        equipo1=None; cuota1=None
        tc=_team_cuota(l)
        if tc and not _es_empate(tc[0]):
            equipo1,cuota1=tc; i+=1
        elif i+1<len(lineas) and _es_cuota(lineas[i+1]):
            equipo1=l; cuota1=float(lineas[i+1]); i+=2
        if equipo1 is None: i+=1; continue
        # Cuota empate
        cuotax=None
        if i<len(lineas):
            ec=_es_empate_cuota(lineas[i])
            if ec: cuotax=float(ec); i+=1
            elif _es_empate(lineas[i]):
                i+=1
                if i<len(lineas) and _es_cuota(lineas[i]): cuotax=float(lineas[i]); i+=1
        if cuotax is None: continue
        # Equipo2+cuota2
        equipo2=None; cuota2=None
        if i<len(lineas):
            tc2=_team_cuota(lineas[i])
            if tc2 and not _es_empate(tc2[0]):
                equipo2,cuota2=tc2; i+=1
            elif i+1<len(lineas) and _es_cuota(lineas[i+1]):
                equipo2=lineas[i]; cuota2=float(lineas[i+1]); i+=2
        if equipo2 is None: continue
        partidos.append({
            "local":equipo1,"visitante":equipo2,
            "cuota_1":cuota1,"cuota_x":cuotax,"cuota_2":cuota2,
            "hora":hora,"fecha":fecha,
            "fuente":"manual","cuotas_estimadas":False,
            "contexto_h2h":"","observacion":""
        })
    return partidos

# ══════════════════════════════════════════════════════════════════════════════
# INICIO — DASHBOARD CON NAOMI ❤️
# ══════════════════════════════════════════════════════════════════════════════
if sec=="inicio":
    st.markdown("## 🏠 Panel Principal")
    col1,col2,col3,col4=st.columns(4)
    try:
        total_p=len(supa("proyectos") or [])
        total_a=len(supa("clientes") or [])
        hoy=ahora().strftime("%Y-%m-%d")
        eventos_hoy=len(supa("agenda",filtro=f"?fecha=eq.{hoy}") or [])
        total_u=len(supa("usuarios",filtro="?activo=eq.true") or [])
    except: total_p=total_a=eventos_hoy=total_u=0
    for col,num,label in zip([col1,col2,col3,col4],
        [total_p,total_a,eventos_hoy,total_u],
        ["Proyectos","Aliados","Eventos hoy","Usuarios activos"]):
        with col:
            st.markdown(f'''<div style="background:#0f0000;border:1px solid #cc0000;
                border-radius:10px;padding:1.2rem;text-align:center;">
                <div style="font-size:2.5rem;font-weight:900;color:#cc0000;">{num}</div>
                <div style="color:#ccc;font-size:0.85rem;">{label}</div></div>''',
                unsafe_allow_html=True)

    st.markdown("<br>",unsafe_allow_html=True)
    col_a,col_b=st.columns(2)
    with col_a:
        st.markdown("### 📁 Proyectos recientes")
        for p in (supa("proyectos",filtro="?order=creado_en.desc&limit=5") or []):
            st.markdown(f'''<div style="background:#0a0000;border-left:3px solid #cc0000;
                padding:0.6rem 1rem;margin:0.3rem 0;border-radius:0 6px 6px 0;">
                <span style="color:#fff;font-weight:600;">{p.get("nombre","")[:40]}</span>
                <span style="color:#cc0000;font-size:0.8rem;"> · {p.get("linea_servicio","")}</span>
                </div>''',unsafe_allow_html=True)
    with col_b:
        st.markdown("### 📅 Agenda de hoy")
        agenda_hoy=supa("agenda",filtro=f"?fecha=eq.{hoy}&order=hora.asc") or []
        if not agenda_hoy:
            st.markdown('<div class="tip">Sin eventos para hoy.</div>',unsafe_allow_html=True)
        for ev in agenda_hoy:
            if not isinstance(ev, dict): continue
            hora_ev = str(ev.get("hora","") or ev.get("hora_inicio","") or "")[:5]
            titulo_ev = str(ev.get("titulo","") or ev.get("tarea","") or "Sin título")[:30]
            st.markdown(f'''<div style="background:#0a0000;border-left:3px solid #cc0000;
                padding:0.6rem 1rem;margin:0.3rem 0;border-radius:0 6px 6px 0;">
                <span style="color:#cc0000;font-size:0.85rem;">{hora_ev}</span>
                <span style="color:#fff;"> {titulo_ev}</span>
                </div>''',unsafe_allow_html=True)

    # ── Naomi — Asistente Virtual ❤️ ─────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🤖 Naomi — Asistente Virtual JandrexT")
    col_naomi, col_torre = st.columns([3, 2])
    with col_naomi:
        widget_naomi_dashboard(
            groq_key=get_secret("GROQ_API_KEY"),
            supabase_key=SUPA_KEY,
        )
    with col_torre:
        panel_torre_control(
            supabase_key=SUPA_KEY,
            rol=rol_label,
        )
    st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="chat":
    st.markdown("## 💬 Chats")
    proyectos_list=supa("proyectos",filtro="?order=nombre.asc") or []
    proy_nombres=["Sin proyecto"]+[p["nombre"] for p in proyectos_list]
    cl,cc=st.columns([1,3])
    with cl:
        st.markdown('<span class="nav-title">Mis chats</span>',unsafe_allow_html=True)
        if st.button("➕ Nuevo chat",use_container_width=True):
            for k in list(st.session_state.keys()):
                if k.startswith("inp_"): st.session_state[k]=""
            n=supa("chats","POST",{"titulo":"Nuevo chat","usuario_id":u["id"]})
            if n and isinstance(n,list):
                st.session_state.chat_activo=n[0]["id"]; st.rerun()
        chats=supa("chats",filtro=f"?usuario_id=eq.{u['id']}&proyecto_id=is.null&order=creado_en.desc")
        if chats and isinstance(chats,list):
            for c in chats:
                cb,cm,cd=st.columns([3,1,1])
                with cb:
                    if st.button(f"💬 {c.get('titulo','Chat')[:18]}",key=f"c_{c['id']}",use_container_width=True):
                        for k in list(st.session_state.keys()):
                            if k.startswith("inp_"): st.session_state[k]=""
                        st.session_state.chat_activo=c["id"]; st.rerun()
                with cm:
                    if st.button("📁",key=f"mp_{c['id']}",help="Mover a proyecto"):
                        st.session_state[f"mover_{c['id']}"]=True
                with cd:
                    if puede_borrar(u):
                        if st.button("🗑️",key=f"dc_{c['id']}"):
                            supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                            supa("chats","DELETE",filtro=f"?id=eq.{c['id']}")
                            if st.session_state.chat_activo==c["id"]:
                                st.session_state.chat_activo=None
                            st.rerun()
                if st.session_state.get(f"mover_{c['id']}"):
                    proy_sel=st.selectbox("Mover a:",proy_nombres,key=f"ps_{c['id']}")
                    if st.button("✅ Confirmar",key=f"pc_{c['id']}"):
                        pid_dest=next((p["id"] for p in proyectos_list if p["nombre"]==proy_sel),None)
                        if pid_dest:
                            supa("chats","PATCH",{"proyecto_id":pid_dest},f"?id=eq.{c['id']}")
                            st.session_state[f"mover_{c['id']}"]=False
                            st.success(f"✅ Movido a {proy_sel}"); st.rerun()
    with cc:
        cid=st.session_state.chat_activo
        if cid:
            cd=supa("chats",filtro=f"?id=eq.{cid}")
            tit=cd[0].get("titulo","Chat") if cd and isinstance(cd,list) else "Chat"
            nt=st.text_input("✏️ Nombre del chat",value=tit,key=f"tit_{cid}")
            if nt!=tit: supa("chats","PATCH",{"titulo":nt},f"?id=eq.{cid}")
            panel_consulta(cid,"General")
        else:
            st.info("👈 Selecciona o crea un chat.")

# ══════════════════════════════════════════════════════════════════════════════
# PROYECTOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="proyectos":
    st.markdown("## 📁 Proyectos")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado","JandrexT (Proyecto interno)"]+[a["nombre"] for a in aliados_list]
    cl,cc=st.columns([1,3])
    with cl:
        st.markdown('<span class="nav-title">Proyectos</span>',unsafe_allow_html=True)
        if rol in ["admin","vendedor"]:
            with st.expander("➕ Nuevo proyecto"):
                arch=st.file_uploader("📷 Subir foto/doc del proyecto",type=["jpg","jpeg","png","pdf"])
                if arch and st.button("🔍 Extraer datos",key="ext_proy"):
                    with st.spinner("Extrayendo..."):
                        b64c=base64.b64encode(arch.read()).decode()
                        tipo="pdf" if arch.type=="application/pdf" else "imagen"
                        datos=ia_extraer_doc(b64c,tipo)
                    if datos:
                        if datos.get("razon_social"): st.session_state["pn"]=datos.get("razon_social","")
                        st.success("✅ Datos extraídos")
                pn=st.text_input("Nombre del proyecto *",key="pn")
                pa=st.selectbox("Aliado",aliados_nombres,key="pa")
                pt=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion","interno"],key="pt")
                pl=st.selectbox("Línea de servicio",LINEAS,key="pl")
                pge=st.number_input("Meses garantía equipos",0,60,12,key="pge")
                pgi=st.number_input("Meses garantía instalación",0,24,6,key="pgi")
                if st.button("Crear proyecto",key="btn_proy",type="primary"):
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
        buscar_p=st.text_input("🔍 Buscar proyecto",key="bp")
        proyectos=supa("proyectos",filtro="?order=creado_en.desc") or []
        filtrados=[p for p in proyectos if not buscar_p or buscar_p.lower() in p.get("nombre","").lower()]
        for p in filtrados:
            es_act=st.session_state.proy_activo==p["id"]
            if st.button(f"{'▶ ' if es_act else ''}📁 {p['nombre'][:20]}",
                key=f"p_{p['id']}",use_container_width=True,
                type="primary" if es_act else "secondary"):
                st.session_state.proy_activo=p["id"]
                st.session_state.proy_nombre=p["nombre"]
                st.session_state.sc_activo=None; st.rerun()
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
                        c3.markdown(f'<span class="{"garantia-ok" if dias>30 else "garantia-alerta"}">{"✅" if dias>30 else "⚠️"} Garantía {lbl}: {dias}d</span>',unsafe_allow_html=True)
                    except: pass
            if puede_borrar(u):
                if st.button("🗑️ Eliminar proyecto",key=f"del_p_{pid}"):
                    supa("proyectos","DELETE",filtro=f"?id=eq.{pid}")
                    st.session_state.proy_activo=None; st.rerun()
            tab1,tab2=st.tabs(["💬 Chats del proyecto","📄 Documentos del proyecto"])
            with tab1:
                if st.button("➕ Nuevo chat del proyecto",key="nsc"):
                    n=supa("chats","POST",{"titulo":f"Chat {p.get('nombre','')}",
                        "proyecto_id":pid,"usuario_id":u["id"]})
                    if n and isinstance(n,list): st.session_state.sc_activo=n[0]["id"]; st.rerun()
                subs=supa("chats",filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc") or []
                for s in subs:
                    sb,sd=st.columns([4,1])
                    with sb:
                        if st.button(f"💬 {s.get('titulo','')[:22]}",key=f"sc_{s['id']}",use_container_width=True):
                            st.session_state.sc_activo=s["id"]; st.rerun()
                    with sd:
                        if puede_borrar(u):
                            if st.button("🗑️",key=f"dsc_{s['id']}"):
                                supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{s['id']}")
                                supa("chats","DELETE",filtro=f"?id=eq.{s['id']}"); st.rerun()
                scid=st.session_state.sc_activo
                if scid: panel_consulta(scid,p.get("nombre",""))
                else: st.info("👈 Crea o selecciona un chat del proyecto.")
            with tab2:
                docs=supa("documentos",filtro=f"?proyecto_id=eq.{pid}&order=creado_en.desc") or []
                TIPOS_LBL={"cotizacion":"Cotización","orden_trabajo":"OT","orden_servicio":"OS",
                           "contrato":"Contrato","acta_entrega":"Acta","informe":"Informe"}
                if docs:
                    for d in docs:
                        mes=d.get("creado_en","")[:7]
                        with st.expander(f"📄 {TIPOS_LBL.get(d.get('tipo',''),'Doc')} · {mes} · ${d.get('valor_total',0):,.0f}"):
                            st.markdown(f"**Estado:** {d.get('estado_pago','pendiente')}")
                            st.markdown(d.get("contenido","")[:200]+"...")
                else: st.info("No hay documentos en este proyecto aún.")
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
            a_t=campo_voz_html5("Tarea *","ag_tarea",height=80,placeholder="Describe la tarea...")
            a_al=st.selectbox("Aliado / Sitio *",aliados_nombres)
            a_li=st.selectbox("Línea de servicio",LINEAS)
            a_pr=st.selectbox("Prioridad",["🔴 Urgente (36h)","🟡 Normal (60h)","🟢 Puede esperar (90h)"])
            a_fe=st.date_input("Fecha límite",min_value=ahora().date())
            a_as=st.multiselect("Especialistas",["Andrés Tapiero","Especialista 1","Especialista 2","Subcontratista"])
            a_sa=st.text_input("Colaborador satélite")
            a_ca=st.checkbox("¿Requiere visita en campo?")
            a_de=campo_voz_html5("la descripción","ag_desc",height=90)
            a_ei=campo_voz_html5("el estado inicial","ag_ei",height=70,placeholder="Cómo estaba antes...")
            a_re=campo_voz_html5("recomendaciones","ag_recom",height=70)
            a_le=campo_voz_html5("lección aprendida","ag_leccion",height=60)
            a_se=st.checkbox("¿Requiere seguimiento?")
            a_fs=st.date_input("Fecha seguimiento") if a_se else None
            checklist_items=[]
            if a_li in CHECKLISTS:
                st.markdown(f"**✅ Checklist — {a_li}**")
                for item in CHECKLISTS[a_li]:
                    checklist_items.append({"item":item,"completado":False})
                st.caption(f"{len(checklist_items)} ítems")
            if st.button("👁️ Vista previa",use_container_width=True):
                a_t_val=st.session_state.get("ag_tarea","")
                if a_t_val.strip():
                    with st.spinner("Generando resumen..."):
                        res=ia_generar(f"Resume en 5 líneas esta tarea para JandrexT:\nTarea: {a_t_val}\nAliado: {a_al}\nLínea: {a_li}\nPrioridad: {a_pr}\nEspecialistas: {', '.join(a_as)}\nDescripción: {st.session_state.get('ag_desc','')}")
                    st.info(f"**Vista previa:**\n{res}")
                    st.session_state["ag_listo"]=True
                else: st.warning("⚠️ Escribe la tarea primero")
            if st.session_state.get("ag_listo"):
                if st.button("✅ Confirmar y crear tarea",type="primary",use_container_width=True):
                    horas=36 if "Urgente" in a_pr else 60 if "Normal" in a_pr else 90
                    data={"tarea":st.session_state.get("ag_tarea",""),
                        "cliente":a_al,"prioridad":a_pr,"horas_limite":horas,
                        "fecha_limite":str(ahora()+timedelta(hours=horas)),
                        "asignados":a_as,"satelite":a_sa,"campo":a_ca,
                        "descripcion":st.session_state.get("ag_desc",""),
                        "estado_inicial":st.session_state.get("ag_ei",""),
                        "recomendaciones":st.session_state.get("ag_recom",""),
                        "leccion":st.session_state.get("ag_leccion",""),
                        "seguimiento":a_se,"fecha_seguimiento":str(a_fs) if a_fs else None,
                        "checklist_tipo":a_li,"checklist_items":checklist_items,
                        "creado_por":u["id"]}
                    if supa("agenda","POST",data):
                        telegram(f"📅 <b>Nueva tarea</b>\n📋 {data['tarea']}\n🤝 {a_al}\n🔧 {a_li}\n{a_pr}")
                        for k in ["ag_tarea","ag_desc","ag_ei","ag_recom","ag_leccion"]:
                            st.session_state[k]=""
                        st.session_state["ag_listo"]=False
                        st.success("✅ Tarea creada"); st.rerun()
        else: st.info("Solo el administrador puede crear tareas.")
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
        m1.metric("Total",len(tareas)); m2.metric("Pendientes",len([t for t in tareas if t.get("estado")=="pendiente"]))
        m3.metric("Urgentes",len([t for t in tareas if "Urgente" in t.get("prioridad","")]))
        for t in tareas:
            ico="🔴" if "Urgente" in t.get("prioridad","") else "🟡" if "Normal" in t.get("prioridad","") else "🟢"
            with st.expander(f"{ico} {t['tarea']} · {t.get('cliente','')} · {t.get('estado','pendiente')}"):
                st.markdown(f"**Línea:** {t.get('checklist_tipo','')} | **Límite:** {t.get('fecha_limite','')[:10]}")
                st.markdown(f"**Especialistas:** {', '.join(t.get('asignados') or [])}")
                if t.get("descripcion"): st.markdown(f"**Desc:** {t['descripcion']}")
                items=t.get("checklist_items") or []
                if items:
                    st.markdown("**✅ Checklist:**")
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
                ef=st.text_area("Estado final",key=f"ef_{t['id']}",value=t.get("estado_final",""),height=60)
                ca,cb=st.columns([3,1])
                with ca:
                    if st.button("💾 Actualizar",key=f"upd_{t['id']}",use_container_width=True):
                        supa("agenda","PATCH",{"estado":ne,"estado_final":ef},f"?id=eq.{t['id']}")
                        if ne=="completado": telegram(f"✅ <b>Completada</b>\n📋 {t['tarea']}\n🤝 {t.get('cliente','')}")
                        st.success("✅"); st.rerun()
                with cb:
                    if puede_borrar(u):
                        if st.button("🗑️",key=f"dt_{t['id']}"): supa("agenda","DELETE",filtro=f"?id=eq.{t['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ASISTENCIA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="asistencia":
    st.markdown("## 👥 Asistencia y Campo")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]
    geo_html="""<style>
    .gb{background:#cc0000;color:#fff;border:none;border-radius:12px;padding:0.9rem 1.2rem;font-size:1rem;font-weight:700;width:100%;cursor:pointer;margin:0.3rem 0;display:block;}
    .gs{background:#1a1a1a;border:2px solid #cc0000;color:#fff;}
    .gs-box{background:#0a0a0a;border:1px solid #333;border-radius:8px;padding:0.7rem;margin:0.4rem 0;color:#ccc;font-size:0.85rem;min-height:50px;}
    #mp{width:100%;height:180px;border-radius:8px;border:1px solid #cc0000;margin:0.4rem 0;}
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <div id="gs-box" class="gs-box">📍 Presiona para capturar ubicación GPS...</div>
    <div id="mp"></div>
    <button class="gb" onclick="gps('entrada')">✅ Registrar ENTRADA con GPS</button>
    <button class="gb gs" onclick="gps('salida')">🏁 Registrar SALIDA con GPS</button>
    <script>
    var map=L.map('mp').setView([4.711,-74.0721],11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var mk=null;
    function gps(tipo){
        document.getElementById('gs-box').innerHTML='⏳ Obteniendo GPS...';
        navigator.geolocation.getCurrentPosition(function(p){
            var lat=p.coords.latitude.toFixed(6),lng=p.coords.longitude.toFixed(6);
            document.getElementById('gs-box').innerHTML=(tipo=='entrada'?'✅':'🏁')+' <b>'+tipo.toUpperCase()+'</b><br>'+lat+', '+lng+' | Precisión: '+Math.round(p.coords.accuracy)+'m';
            if(mk)map.removeLayer(mk);
            mk=L.marker([lat,lng]).addTo(map).bindPopup(tipo).openPopup();
            map.setView([lat,lng],15);
        },function(e){document.getElementById('gs-box').innerHTML='⚠️ '+e.message;},{enableHighAccuracy:true,timeout:15000});
    }
    </script>"""
    st.components.v1.html(geo_html,height=370,scrolling=False)
    with st.form("form_asist",clear_on_submit=True):
        c1,c2=st.columns(2)
        m_col=c1.text_input("👤 Especialista",value=nombre)
        m_tip=c2.selectbox("Tipo",["entrada","salida"])
        m_pro=st.selectbox("📍 Proyecto / Aliado",aliados_nombres)
        m_tar=st.text_input("🔧 Tarea realizada")
        m_lat=st.text_input("🌐 Latitud",placeholder="Del mapa GPS arriba")
        m_lng=st.text_input("🌐 Longitud",placeholder="Del mapa GPS arriba")
        if st.form_submit_button("💾 Guardar registro",use_container_width=True,type="primary"):
            ub=f"{m_lat},{m_lng}" if m_lat and m_lng else ""
            supa("asistencia","POST",{"colaborador_id":u["id"],"colaborador_nombre":m_col,
                "tipo":m_tip,"proyecto":m_pro,"tarea":m_tar,"ubicacion":ub})
            emoji="✅" if m_tip=="entrada" else "🏁"
            telegram(f"{emoji} <b>{m_col}</b> — {m_tip}\n📍 {m_pro}\n📋 {m_tar}")
            st.success("✅ Registrado"); st.rerun()
    st.markdown('<hr class="divider">',unsafe_allow_html=True)
    st.markdown("### 📋 Informe de trabajo")
    inf_aliado=st.selectbox("Proyecto / Aliado",aliados_nombres,key="inf_ali")
    inf_serv=st.selectbox("Tipo de servicio",LINEAS,key="inf_serv")
    panel_voz_global({"Trabajo realizado":"inf_desc","Materiales utilizados":"inf_elem","Pendientes":"inf_pend"},"asistencia")
    inf_desc=campo_voz_html5("Descripción del trabajo","inf_desc",height=110,placeholder="Describe qué encontraste, qué hiciste y qué quedó...")
    inf_elem=campo_voz_html5("los materiales utilizados","inf_elem",height=80,placeholder="Ej: 2 tornillos M8, 1 hidráulico Speedy M25...")
    inf_pend=campo_voz_html5("los pendientes","inf_pend",height=80,placeholder="Qué falta, qué se necesita...")
    inf_visita=st.selectbox("¿Requiere otra visita?",["No","Sí — urgente","Sí — programada"])
    if st.button("📋 Generar informe",type="primary",use_container_width=True):
        desc_val=st.session_state.get("inf_desc","")
        if desc_val.strip():
            with st.spinner("Generando informe profesional..."):
                prompt=f"""Genera un informe técnico profesional para JandrexT Soluciones Integrales.
Aliado: {inf_aliado} | Servicio: {inf_serv} | Especialista: {nombre} | Fecha: {fecha_str()}
Trabajo: {desc_val}
Materiales: {st.session_state.get('inf_elem','')}
Pendientes: {st.session_state.get('inf_pend','')}
Otra visita: {inf_visita}
Estructura: 1.Resumen 2.Estado encontrado 3.Trabajos realizados 4.Materiales 5.Pendientes 6.Visita siguiente 7.Mantenimiento preventivo
Tono profesional y empático. Apasionados por el buen servicio."""
                informe=ia_generar(prompt)
            st.markdown('<div class="doc-borrador">',unsafe_allow_html=True)
            st.markdown(f"### 📋 Informe — {inf_aliado}")
            st.markdown(informe)
            st.markdown('</div>',unsafe_allow_html=True)
            pdf_html=generar_pdf_html(f"Informe Técnico — {inf_aliado}",informe)
            st.download_button("📥 Descargar informe",data=pdf_html.encode("utf-8"),
                file_name=f"Informe_{ahora().strftime('%Y%m%d')}.html",mime="text/html")
            telegram(f"📋 <b>Informe generado</b>\n👤 {nombre}\n📍 {inf_aliado}\n🔧 {inf_serv}")
        else: st.warning("⚠️ Describe el trabajo realizado.")
    if rol=="admin":
        st.markdown('<hr class="divider">',unsafe_allow_html=True)
        st.markdown("### 🗺️ Especialistas en campo")
        hoy=ahora().strftime("%Y-%m-%d")
        regs=supa("asistencia",filtro=f"?fecha=gte.{hoy}T00:00:00&order=fecha.desc") or []
        activos=[r for r in regs if r.get("ubicacion") and r["tipo"]=="entrada"]
        if activos:
            markers=""
            for r in activos:
                try:
                    lat,lng=r["ubicacion"].split(",")
                    cn=r.get("colaborador_nombre",""); pr=r.get("proyecto","")
                    markers+=f"L.marker([{lat},{lng}]).addTo(m).bindPopup('<b>{cn}</b><br>{pr}').openPopup();"
                except: pass
            st.components.v1.html(f"""<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <div id="ma" style="width:100%;height:280px;border-radius:10px;border:1px solid #cc0000;"></div>
            <script>var m=L.map('ma').setView([4.711,-74.0721],11);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);{markers}</script>""",height=300)
            st.metric("En campo",len(activos))
        else: st.info("No hay especialistas con GPS activo.")
        for r in regs:
            bg="#0a1a0a" if r["tipo"]=="entrada" else "#1a0a0a"
            ico="✅" if r["tipo"]=="entrada" else "🏁"
            st.markdown(f"""<div style="background:{bg};border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.3rem;">
                {ico} <b>{r.get('colaborador_nombre','')}</b> · {r.get('fecha','')[:16]}<br>
                📍 {r.get('proyecto','')} · 📋 {r.get('tarea','')}</div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ALIADOS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="aliados":
    st.markdown("## 🤝 Aliados")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nuevo Aliado")
        st.info("💡 Sube el RUT o foto del documento para extraer datos automáticamente.")
        arch=st.file_uploader("📄 Subir RUT, NIT o foto",type=["pdf","jpg","jpeg","png"])
        if arch:
            if st.button("🔍 Extraer datos del documento"):
                with st.spinner("Extrayendo información..."):
                    b64c=base64.b64encode(arch.read()).decode()
                    tipo="pdf" if arch.type=="application/pdf" else "imagen"
                    datos=ia_extraer_doc(b64c,tipo)
                if datos and not datos.get("_errores"):
                    for k,v in datos.items():
                        if v and k != "_errores": st.session_state[f"ali_{k}"]=v
                    st.success("✅ Datos extraídos"); st.rerun()
                elif datos.get("_errores"):
                    st.error(f"⚠️ No se pudo extraer: {datos['_errores']}")
                else:
                    st.warning("⚠️ No se encontraron datos. Ingrese manualmente.")
        def ali_field(k,label,placeholder=""):
            if f"ali_{k}" not in st.session_state: st.session_state[f"ali_{k}"] = ""
            return st.text_input(label,placeholder=placeholder,key=f"ali_{k}")
        a_rs=ali_field("razon_social","Razón Social *")
        a_nit=ali_field("nit","NIT / Identificación *")
        a_ti=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion","otro"],key="ali_tipo")
        a_dir=ali_field("direccion","Dirección")
        a_mun=ali_field("municipio","Municipio")
        a_dep=ali_field("departamento","Departamento")
        a_tel=ali_field("telefono","Teléfono")
        a_email=ali_field("email","Correo electrónico")
        a_co=ali_field("contacto","Nombre del contacto")
        a_ca=ali_field("cargo_contacto","Cargo del contacto")
        a_rf=ali_field("responsabilidad_fiscal","Responsabilidad Fiscal","R-99-PN")
        a_reg=ali_field("regimen_fiscal","Régimen Fiscal","49")
        a_not=st.text_area("Notas adicionales",key="ali_notas",height=60)
        a_hor=campo_voz_html5("Horarios de atención","ali_horarios",height=70,placeholder="Ej: Lun-Vie 8am-12pm · Sáb 8am-12pm")
        if st.button("💾 Guardar Aliado",type="primary",use_container_width=True):
            rs=st.session_state.get("ali_razon_social","")
            nit=st.session_state.get("ali_nit","")
            if rs and nit:
                tipo_f=st.session_state.get("ali_tipo","")
                res=supa("clientes","POST",{
                    "nombre":rs,"razon_social":rs,"nit":nit,"tipo":tipo_f,
                    "direccion":st.session_state.get("ali_direccion",""),
                    "municipio":st.session_state.get("ali_municipio",""),
                    "departamento":st.session_state.get("ali_departamento",""),
                    "telefono":st.session_state.get("ali_telefono",""),
                    "email":st.session_state.get("ali_email",""),
                    "contacto":st.session_state.get("ali_contacto",""),
                    "cargo_contacto":st.session_state.get("ali_cargo_contacto",""),
                    "responsabilidad_fiscal":st.session_state.get("ali_responsabilidad_fiscal",""),
                    "regimen_fiscal":st.session_state.get("ali_regimen_fiscal",""),
                    "notas":a_not,"horarios":st.session_state.get("ali_horarios","")})
                if res:
                    for k in list(st.session_state.keys()):
                        if k.startswith("ali_"): del st.session_state[k]
                    st.success("✅ Aliado guardado"); st.rerun()
            else: st.warning("⚠️ Razón Social y NIT son obligatorios")
    with col_l:
        st.markdown("### 📋 Aliados registrados")
        aliados=supa("clientes",filtro="?order=nombre.asc") or []
        buscar_a=st.text_input("🔍 Buscar aliado")
        filtrados=[a for a in aliados if not buscar_a or buscar_a.lower() in a.get("nombre","").lower()]
        st.metric("Total aliados",len(filtrados))
        for a in filtrados:
            with st.expander(f"🤝 {a['nombre']} · {a.get('nit','')}"):
                c1,c2=st.columns(2)
                c1.markdown(f"**Tipo:** {a.get('tipo','')} | **Tel:** {a.get('telefono','')}")
                c1.markdown(f"**Email:** {a.get('email','')}")
                c1.markdown(f"**Dir:** {a.get('direccion','')} · {a.get('municipio','')}")
                c2.markdown(f"**Contacto:** {a.get('contacto','')} — {a.get('cargo_contacto','')}")
                c2.markdown(f"**NIT:** {a.get('nit','')} | **Rég:** {a.get('regimen_fiscal','')}")
                if a.get("notas"): st.caption(f"📝 {a['notas']}")
                if a.get("horarios"): st.info(f"🕐 Horarios: {a['horarios']}")
                if puede_borrar(u):
                    if st.button("🗑️ Eliminar",key=f"da_{a['id']}"):
                        supa("clientes","DELETE",filtro=f"?id=eq.{a['id']}"); st.rerun()

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
    panel_voz_global({"Contenido del documento":"doc_cont"},"documentos")
    doc_contenido=campo_voz_html5("Contenido del documento","doc_cont",height=150,placeholder="Describe equipos, actividades, valores...")
    c1,c2=st.columns(2)
    doc_valor=c1.number_input("Valor total (COP)",min_value=0,step=50000)
    doc_anticipo=c2.number_input("Anticipo (COP)",min_value=0,step=50000)
    aliado_data=next((a for a in aliados_list if a["nombre"]==doc_aliado),{})
    if st.button("👁️ Generar borrador",use_container_width=True,type="primary"):
        cont=st.session_state.get("doc_cont","")
        if cont.strip():
            with st.spinner("Generando borrador..."):
                saldo=doc_valor-doc_anticipo
                prompt=f"""Genera un {TIPOS_DOC[tipo_doc]} profesional para JandrexT Soluciones Integrales.
EMISOR: JANDREXT SOLUCIONES INTEGRALES | NIT: 80818905-3 | Dir: CL 80 70C-67 Local 2 Bogotá
Tel: 317 391 0621 | proyectos@jandrext.com | Representante: José Andrés Tapiero Gómez
ALIADO: {aliado_data.get('razon_social',doc_aliado)} | NIT: {aliado_data.get('nit','')}
Dir: {aliado_data.get('direccion','')} {aliado_data.get('municipio','')} | Tel: {aliado_data.get('telefono','')}
Contacto: {aliado_data.get('contacto','')} — {aliado_data.get('cargo_contacto','')}
PROYECTO: {doc_proy} | LÍNEA: {doc_linea} | Fecha: {fecha_str()}
VALOR: ${doc_valor:,.0f} | ANTICIPO: ${doc_anticipo:,.0f} | SALDO: ${saldo:,.0f}
CONTENIDO: {cont}
Incluir: numeración, descripción técnica, cuadro económico, 16 términos y condiciones JandrexT,
normas colombianas, pagos: AV Villas 065779337 / Caja Social 24109787510 / Nequi 317 391 0621
Firma: José Andrés Tapiero Gómez, Director de Proyectos."""
                borrador=ia_generar(prompt)
                st.session_state["doc_borrador"]=borrador
                st.session_state["doc_listo"]=True
        else: st.warning("⚠️ Describe el contenido.")
    if st.session_state.get("doc_listo"):
        st.markdown('<div class="doc-borrador">',unsafe_allow_html=True)
        borrador=st.text_area("✏️ Revisa y edita si necesitas",
            value=st.session_state.get("doc_borrador",""),height=400,key="doc_editor")
        st.markdown('</div>',unsafe_allow_html=True)
        c1,c2,c3=st.columns(3)
        with c1:
            if st.button("✅ Confirmar y guardar",type="primary",use_container_width=True):
                cid=next((a["id"] for a in aliados_list if a["nombre"]==doc_aliado),None)
                pid=next((p["id"] for p in proyectos_list if p["nombre"]==doc_proy),None)
                supa("documentos","POST",{"tipo":tipo_doc,"contenido":borrador,
                    "cliente_id":cid,"proyecto_id":pid,"valor_total":doc_valor,
                    "anticipo":doc_anticipo,"saldo":doc_valor-doc_anticipo,
                    "estado_pago":"pendiente","creado_por":u["id"]})
                st.session_state["doc_listo"]=False; st.session_state["doc_cont"]=""
                st.success("✅ Guardado en el proyecto"); st.rerun()
        with c2:
            pdf=generar_pdf_html(f"{TIPOS_DOC[tipo_doc]} — {doc_aliado}",borrador)
            st.download_button("📥 Descargar",data=pdf.encode("utf-8"),
                file_name=f"{tipo_doc}_{ahora().strftime('%Y%m%d')}.html",
                mime="text/html",use_container_width=True)
        with c3:
            em=aliado_data.get("email","")
            if em:
                if st.button(f"📧 Enviar",use_container_width=True):
                    ok=enviar_email(em,f"JandrexT — {TIPOS_DOC[tipo_doc]}",
                        f"<pre style='font-family:Arial;font-size:11px;'>{borrador}</pre>")
                    if ok: st.success(f"✅ Enviado a {em}")
            else: st.caption("Sin email del aliado")

# ══════════════════════════════════════════════════════════════════════════════
# MANUALES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="manuales" and tiene_modulo(u,"manuales"):
    st.markdown("## 📖 Manuales")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Sin aliado"]+[a["nombre"] for a in aliados_list]
    col_f,col_l=st.columns([2,1])
    with col_f:
        m_ali=st.selectbox("Aliado / Proyecto",aliados_nombres)
        m_sis=st.text_input("Sistema instalado")
        m_tip=st.selectbox("Tipo de manual",["Manual de Usuario","Manual Técnico",
            "Guía de Configuración y Contraseñas","Plan de Mantenimiento Preventivo",
            "Manual de Operación Diaria","Guía de Acceso Remoto"])
        m_lin=st.selectbox("Línea de servicio",LINEAS)
        panel_voz_global({"Detalles del sistema":"man_det"},"manuales")
        m_det=campo_voz_html5("Detalles específicos","man_det",height=130,placeholder="IP, contraseñas, equipos instalados...")
        m_cli=st.selectbox("Tipo de destinatario",["copropiedad","empresa","natural","administracion"])
        if st.button("📖 Generar manual",type="primary",use_container_width=True):
            det=st.session_state.get("man_det","")
            if m_sis and det.strip():
                with st.spinner("Generando manual..."):
                    prompt=f"""Crea un {m_tip} completo para JandrexT Soluciones Integrales.
Aliado: {m_ali} | Sistema: {m_sis} | Línea: {m_lin} | Destinatario: {m_cli} | Fecha: {fecha_str()}
Detalles: {det}
Incluir: portada, índice, descripción, instrucciones paso a paso, credenciales, problemas comunes,
mantenimiento preventivo, contacto: Andrés Tapiero 317 391 0621
Tono: claro, empático. Apasionados por el buen servicio."""
                    manual=ia_generar(prompt)
                    cid=next((a["id"] for a in aliados_list if a["nombre"]==m_ali),None)
                    supa("manuales","POST",{"titulo":f"{m_tip} — {m_sis}","tipo":m_tip,
                        "sistema":m_sis,"contenido":manual,"cliente_id":cid,"creado_por":u["id"]})
                st.markdown(f"### 📖 {m_tip}")
                st.markdown(manual)
                pdf=generar_pdf_html(f"{m_tip} — {m_sis}",manual)
                st.download_button("📥 Descargar manual",data=pdf.encode("utf-8"),
                    file_name=f"Manual_{ahora().strftime('%Y%m%d')}.html",mime="text/html")
                st.session_state["man_det"]=""; st.success("✅ Manual guardado")
            else: st.warning("⚠️ Completa sistema y detalles.")
    with col_l:
        st.markdown("### 📚 Guardados")
        mans=supa("manuales",filtro="?order=creado_en.desc") or []
        for m in mans:
            with st.expander(f"📖 {m.get('tipo','')[:22]}"):
                st.caption(m.get("sistema",""))
                pdf=generar_pdf_html(m.get("titulo","Manual"),m.get("contenido",""))
                st.download_button("📥",data=pdf.encode("utf-8"),
                    file_name=f"Manual_{m['id'][:6]}.html",mime="text/html",key=f"dl_man_{m['id']}")
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dm_{m['id']}"): supa("manuales","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# VENTAS
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="ventas" and tiene_modulo(u,"ventas"):
    st.markdown("## 💼 Asistente de Ventas")
    aliados_list=supa("clientes",filtro="?order=nombre.asc") or []
    aliados_nombres=["Nuevo aliado"]+[a["nombre"] for a in aliados_list]
    c1,c2=st.columns(2)
   
    tab_v1,tab_v2=st.tabs(["➕ Nueva propuesta","📋 Historial"])
    with tab_v1:
        col_vf,col_vl=st.columns([2,1])
        with col_vf:
            v_cli=st.selectbox("Cliente / Prospecto",aliados_nombres)
            v_ser=st.multiselect("Servicios a cotizar",["CCTV","Alarmas","Control de Acceso","Redes","Domótica","Mantenimiento","Instalación"])
            panel_voz_global({"Notas de la visita":"v_notas"},"ventas")
            v_not=campo_voz_html5("Notas de la visita / necesidades","v_notas",height=110,placeholder="Qué necesita el cliente, presupuesto estimado, prioridades...")
            v_val=st.number_input("Valor estimado (COP)",min_value=0,step=50000,value=0)
            v_est=st.selectbox("Estado",["Prospecto","Propuesta enviada","En negociación","Ganado","Perdido"])
            if st.button("📤 Generar propuesta con IA",type="primary",use_container_width=True):
                notas=st.session_state.get("v_notas","")
                if v_ser and notas.strip():
                    with st.spinner("Generando propuesta comercial..."):
                        prompt=f"""Genera una propuesta comercial profesional para JandrexT Soluciones Integrales.
Cliente: {v_cli} | Servicios: {', '.join(v_ser)} | Valor estimado: ${v_val:,.0f} COP | Estado: {v_est}
Necesidades detectadas: {notas}
Fecha: {fecha_str()}
La propuesta debe incluir: saludo personalizado, descripción de la solución, beneficios, valor agregado,
condiciones comerciales, garantías, datos de contacto: Andrés Tapiero 317 391 0621 / proyectos@jandrext.com
Tono: profesional, confiable, orientado a resultados. Apasionados por el buen servicio."""
                        propuesta=ia_generar(prompt)
                        cid=next((a["id"] for a in aliados_list if a["nombre"]==v_cli),None)
                        supa("ventas","POST",{"cliente_id":cid,"servicios":v_ser,"valor":v_val,
                            "estado":v_est,"notas":notas,"propuesta":propuesta,"creado_por":u["id"]})
                    st.markdown("### 📄 Propuesta generada")
                    st.markdown(propuesta)
                    pdf=generar_pdf_html(f"Propuesta — {v_cli}",propuesta)
                    st.download_button("📥 Descargar propuesta",data=pdf.encode("utf-8"),
                        file_name=f"Propuesta_{ahora().strftime('%Y%m%d')}.html",mime="text/html")
                    st.session_state["v_notas"]=""
                    st.success("✅ Propuesta guardada")
                else: st.warning("⚠️ Selecciona servicios y agrega notas.")
        with col_vl:
            st.markdown("### 📊 Pipeline")
            ventas_list=supa("ventas",filtro="?order=creado_en.desc") or []
            est_counts={}
            for v in ventas_list:
                e=v.get("estado","")
                est_counts[e]=est_counts.get(e,0)+1
            for e,c in est_counts.items():
                st.metric(e,c)
    with tab_v2:
        ventas_list=supa("ventas",filtro="?order=creado_en.desc") or []
        for v in ventas_list:
            cli_n=v.get("cliente_id","")
            with st.expander(f"💼 {cli_n[:20]} — {v.get('estado','')} — ${v.get('valor',0):,.0f}"):
                st.write(f"**Servicios:** {', '.join(v.get('servicios',[]))}")
                st.write(v.get("propuesta","")[:400]+"...")
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dv_{v['id']}"): supa("ventas","DELETE",filtro=f"?id=eq.{v['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="liquidaciones" and tiene_modulo(u,"liquidaciones"):
    st.markdown("## 📊 Liquidaciones")
    tab_l1,tab_l2=st.tabs(["➕ Nueva","📋 Historial"])
    with tab_l1:
        aliados_list2=supa("clientes",filtro="?order=nombre.asc") or []
        al_nombres2=["Seleccionar"]+[a["nombre"] for a in aliados_list2]
        l_ali=st.selectbox("Aliado/Técnico",al_nombres2)
        l_periodo=st.text_input("Período (ej: Mayo 2026)")
        l_serv=st.number_input("Servicios completados",min_value=0,step=1)
        l_valor=st.number_input("Valor a liquidar (COP)",min_value=0,step=10000)
        l_desc=st.text_area("Observaciones",height=80)
        if st.button("💰 Generar liquidación",type="primary",use_container_width=True):
            if l_ali!="Seleccionar" and l_periodo and l_valor>0:
                lid=str(uuid.uuid4())
                supa("liquidaciones","POST",{"id":lid,"aliado":l_ali,"periodo":l_periodo,
                    "servicios":l_serv,"valor":l_valor,"observaciones":l_desc,"creado_por":u["id"]})
                st.success(f"✅ Liquidación registrada: {l_ali} — ${l_valor:,.0f} COP")
            else: st.warning("⚠️ Completa todos los campos.")
    with tab_l2:
        liqs=supa("liquidaciones",filtro="?order=creado_en.desc") or []
        for lq in liqs:
            with st.expander(f"💰 {lq.get('aliado','')} — {lq.get('periodo','')} — ${lq.get('valor',0):,.0f}"):
                st.write(f"Servicios: {lq.get('servicios',0)} | Obs: {lq.get('observaciones','')}")
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dlq_{lq['id']}"): supa("liquidaciones","DELETE",filtro=f"?id=eq.{lq['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ESPECIALISTAS Y ALIADOS (USUARIOS)
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="usuarios" and u.get("role")=="admin":
    st.markdown("## 👑 Especialistas y Aliados")
    tab_u1,tab_u2=st.tabs(["➕ Crear usuario","📋 Lista"])
    with tab_u1:
        nu_email=st.text_input("Email")
        nu_pwd=st.text_input("Contraseña",type="password")
        nu_role=st.selectbox("Rol",["admin","usuario","cliente","aliado"])
        nu_nombre=st.text_input("Nombre completo")
        nu_modulos=st.multiselect("Módulos activos",["chat","proyectos","agenda","asistencia","documentos","manuales","ventas","aliados","liquidaciones"])
        if st.button("➕ Crear usuario",type="primary",use_container_width=True):
            if nu_email and nu_pwd and nu_nombre:
                ph=hashlib.sha256(nu_pwd.encode()).hexdigest()
                supa("usuarios","POST",{"email":nu_email,"password_hash":ph,"role":nu_role,
                    "nombre":nu_nombre,"modulos":nu_modulos,"activo":True})
                st.success(f"✅ Usuario {nu_nombre} creado.")
            else: st.warning("⚠️ Email, contraseña y nombre son obligatorios.")
    with tab_u2:
        users=supa("usuarios",filtro="?order=creado_en.desc") or []
        for usr in users:
            with st.expander(f"👤 {usr.get('nombre','')} ({usr.get('role','')}) — {usr.get('email','')}"):
                st.write(f"Módulos: {', '.join(usr.get('modulos',[]))}")
                activo=usr.get("activo",True)
                if st.button("🔒 Desactivar" if activo else "🔓 Activar",key=f"ua_{usr['id']}"):
                    supa("usuarios","PATCH",{"activo":not activo},filtro=f"?id=eq.{usr['id']}")
                    st.rerun()
                if puede_borrar(u):
                    if st.button("🗑️",key=f"du_{usr['id']}"): supa("usuarios","DELETE",filtro=f"?id=eq.{usr['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA (ADMIN)
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="biblioteca":
    st.markdown("## 📚 Biblioteca de Conocimiento")
    docs=supa("documentos",filtro="?order=creado_en.desc") or []
    mans=supa("manuales",filtro="?order=creado_en.desc") or []
    todos=[{"tipo":"📄 Doc","titulo":d.get("titulo",""),"contenido":d.get("contenido",""),"fecha":d.get("creado_en","")} for d in docs] + \
          [{"tipo":"📖 Manual","titulo":m.get("titulo",""),"contenido":m.get("contenido",""),"fecha":m.get("creado_en","")} for m in mans]
    q=st.text_input("🔍 Buscar en biblioteca","")
    filtrados=[t for t in todos if q.lower() in t["titulo"].lower() or q.lower() in t["contenido"].lower()] if q else todos
    st.caption(f"{len(filtrados)} documentos encontrados")
    for t in filtrados[:50]:
        with st.expander(f"{t['tipo']} {t['titulo'][:50]}"):
            st.caption(t["fecha"][:10] if t["fecha"] else "")
            st.write(t["contenido"][:500]+"..." if len(t["contenido"])>500 else t["contenido"])

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="config" and u.get("role")=="admin":
    st.markdown("## ⚙️ Configuración del Sistema")
    st.markdown("### 🔑 Estado de APIs")
    apis_check=[
        ("🟢 Gemini","GOOGLE_API_KEY"),("🟢 Groq","GROQ_API_KEY"),
        ("🟢 Mistral","MISTRAL_API_KEY"),("🟢 OpenAI","OPENAI_API_KEY"),
        ("🟢 Claude","ANTHROPIC_API_KEY"),("🗄️ Supabase URL","SUPABASE_URL"),
        ("🗄️ Supabase Key","SUPABASE_ANON_KEY"),
    ]
    c1c,c2c=st.columns(2)
    for i,(nombre,key) in enumerate(apis_check):
        val=get_secret(key)
        status="✅ Configurada" if val else "❌ No configurada"
        (c1c if i%2==0 else c2c).metric(nombre,status)
    st.markdown("---")
    st.markdown("### 👤 Mi cuenta")
    nuevo_nombre=st.text_input("Nombre",value=u.get("nombre",""))
    nuevo_pwd=st.text_input("Nueva contraseña (dejar en blanco para no cambiar)",type="password")
    if st.button("💾 Guardar cambios"):
        upd={"nombre":nuevo_nombre}
        if nuevo_pwd: upd["password_hash"]=hashlib.sha256(nuevo_pwd.encode()).hexdigest()
        supa("usuarios","PATCH",upd,filtro=f"?id=eq.{u['id']}")
        st.success("✅ Datos actualizados")
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# REQUERIMIENTOS (CLIENTE)
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="requerimientos" and u.get("role")=="cliente":
    st.markdown("## 📋 Mis Requerimientos")
    panel_voz_global({"Descripción del requerimiento":"req_desc"},"requerimientos")
    r_tipo=st.selectbox("Tipo",["Solicitud de servicio","Queja","Garantía","Consulta","Otro"])
    r_desc=campo_voz_html5("Descripción","req_desc",height=120,placeholder="Describe tu solicitud...")
    r_pri=st.selectbox("Prioridad",["Normal","Alta","Urgente"])
    if st.button("📤 Enviar requerimiento",type="primary",use_container_width=True):
        desc=st.session_state.get("req_desc","")
        if desc.strip():
            supa("requerimientos","POST",{"cliente_id":u["id"],"tipo":r_tipo,
                "descripcion":desc,"prioridad":r_pri,"estado":"Nuevo"})
            st.success("✅ Requerimiento enviado. Te contactaremos pronto.")
            st.session_state["req_desc"]=""
        else: st.warning("⚠️ Describe tu solicitud.")
    st.markdown("---")
    st.markdown("### 📬 Mis solicitudes")
    reqs=supa("requerimientos",filtro=f"?cliente_id=eq.{u['id']}&order=creado_en.desc") or []
    for r in reqs:
        ico={"Nuevo":"🟡","En proceso":"🔵","Resuelto":"✅"}.get(r.get("estado",""),"⚪")
        with st.expander(f"{ico} {r.get('tipo','')} — {r.get('estado','')}"):
            st.write(r.get("descripcion",""))
            st.caption(r.get("creado_en","")[:10])

# ══════════════════════════════════════════════════════════════════════════════
# MIS MANUALES (CLIENTE)
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="mis_manuales" and u.get("role")=="cliente":
    st.markdown("## 📖 Mis Manuales")
    mans=supa("manuales",filtro=f"?cliente_id=eq.{u['id']}&order=creado_en.desc") or []
    if not mans:
        st.info("No tienes manuales asignados aún.")
    for m in mans:
        with st.expander(f"📖 {m.get('titulo','')}"):
            st.write(m.get("contenido","")[:300]+"...")
            pdf=generar_pdf_html(m.get("titulo","Manual"),m.get("contenido",""))
            st.download_button("📥 Descargar",data=pdf.encode("utf-8"),
                file_name=f"Manual_{m['id'][:6]}.html",mime="text/html",key=f"cm_{m['id']}")


elif sec=="mesa_ia":
    # ── Modo actual (general | futbol)
    if "mesa_modo" not in st.session_state: st.session_state["mesa_modo"]="general"

    # ── Panel izquierdo: proyectos + selector de modo
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🧠 Mesa IA")
        modo_sel=st.radio("Modo",["🤝 Consejo General","⚽ Football Lab"],
            index=0 if st.session_state["mesa_modo"]=="general" else 1,key="mesa_modo_radio")
        if "General" in modo_sel: st.session_state["mesa_modo"]="general"
        else: st.session_state["mesa_modo"]="futbol"
        st.markdown("---")
        # Proyectos en sidebar
        st.markdown("### 📁 Proyectos")
        projs=supa("proyectos",filtro="?order=creado_en.desc") or []
        proj_id=st.session_state.get("mesa_proj_id",None)
        if st.button("➕ Nuevo proyecto",use_container_width=True):
            st.session_state["mesa_proj_new"]=True
        if st.session_state.get("mesa_proj_new"):
            np_nom=st.text_input("Nombre del proyecto","",key="np_nom")
            if st.button("✔ Crear",key="np_crear"):
                if np_nom.strip():
                    r=supa("proyectos","POST",{"nombre":np_nom,"estado":"activo","creado_por":u["id"]})
                    st.session_state["mesa_proj_new"]=False
                    if r: st.session_state["mesa_proj_id"]=r[0]["id"]
                    st.rerun()
        for p in projs[:10]:
            sel="▶ " if p["id"]==proj_id else ""
            if st.button(f"{sel}{p['nombre'][:28]}",key=f"mp_{p['id']}",use_container_width=True):
                st.session_state["mesa_proj_id"]=p["id"]
                st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # MODO GENERAL — Consejo de 5 IAs
    # ════════════════════════════════════════════════════════════════════
    if st.session_state["mesa_modo"]=="general":
        st.markdown("## 🧠 Mesa IA — Consejo de Inteligencia")
        st.caption("5 inteligencias artificiales deliberando en paralelo sobre tu consulta estratégica.")

        hist_gen=st.session_state.get("mesa_hist_gen",[])

        for msg in hist_gen:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        pregunta=st.chat_input("¿Qué quieres que analice el Consejo?")
        if pregunta:
            # ── CORRECCIÓN 1: Detectar texto de fútbol → redirigir a Football Lab
            if detectar_texto_futbol_1x2(pregunta):
                st.session_state["mesa_modo"]="futbol"
                st.session_state["ftbl_texto_pendiente"]=pregunta
                st.info("⚽ **Partidos detectados → Football Lab activado automáticamente**")
                st.rerun()

            hist_gen.append({"role":"user","content":pregunta})
            with st.chat_message("user"): st.markdown(pregunta)
            with st.spinner("🧠 Convocando al Consejo... (5 IAs en paralelo)"):
                # Roles específicos
                roles={
                    "ChatGPT":"Eres el estratega creativo. Genera soluciones innovadoras, fuera de la caja.",
                    "Claude":"Eres el auditor crítico. Identifica riesgos, contradicciones y puntos débiles.",
                    "Gemini":"Eres el contextualizador. Aporta datos, tendencias y contexto del mercado.",
                    "Groq":"Eres el analista rápido. Da respuestas concisas y accionables.",
                    "Mistral":"Eres la perspectiva alternativa. Cuestiona supuestos y propone enfoques distintos."
                }
                def _run_ia_gen(ia_nombre):
                    rol=roles.get(ia_nombre,"")
                    p_full=f"{rol}\n\nContexto previo:\n{CONTEXTO}\n\nPregunta estratégica:\n{pregunta}"
                    if ia_nombre=="ChatGPT": return openai_fn(p_full)
                    elif ia_nombre=="Claude": return claude_fn(p_full)
                    elif ia_nombre=="Gemini": return gemini_fn(p_full)
                    elif ia_nombre=="Groq": return groq_fn(p_full)
                    elif ia_nombre=="Mistral": return mistral_fn(p_full)
                ias_gen=["ChatGPT","Claude","Gemini","Groq","Mistral"]
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    futuros={ex.submit(_run_ia_gen,ia):ia for ia in ias_gen}
                    resp_gen={ia:f.result() for f,ia in [(f,futuros[f]) for f in concurrent.futures.as_completed(futuros)]}
                # Síntesis con Claude
                contexto_votos="\n\n".join([f"**{ia}** ({resp_gen[ia].get('icono','')}):\n{resp_gen[ia].get('respuesta','Sin respuesta')[:600]}" for ia in ias_gen])
                sintesis_prompt=f"""Eres el moderador del Consejo de Inteligencia JandrexT.
Has recibido los análisis de 5 IAs sobre esta pregunta: "{pregunta}"

ANÁLISIS:
{contexto_votos}

Sintetiza en 3 secciones:
1. **PUNTOS DE CONSENSO** — En qué coinciden la mayoría de las IAs
2. **PERSPECTIVAS DIVERGENTES** — Qué visiones diferentes aportan
3. **RECOMENDACIÓN FINAL** — La acción más inteligente según el Consejo

Sé directo, concreto y accionable. Máximo 400 palabras."""
                sintesis=claude_fn(sintesis_prompt)
            # Mostrar resultados
            with st.chat_message("assistant"):
                cols=st.columns(5)
                for i,ia in enumerate(ias_gen):
                    r=resp_gen.get(ia,{})
                    with cols[i]:
                        st.markdown(f"**{r.get('icono','')} {ia}**")
                        st.caption(f"⏱️ {r.get('tiempo',0)}s")
                        ok=r.get("ok",False)
                        st.markdown("✅" if ok else "❌")
                st.markdown("---")
                st.markdown("### 🧠 Síntesis del Consejo")
                st.markdown(sintesis.get("respuesta","Sin síntesis"))
                st.markdown("---")
                with st.expander("📖 Ver análisis completos"):
                    for ia in ias_gen:
                        r=resp_gen.get(ia,{})
                        st.markdown(f"**{r.get('icono','')} {ia}** ({r.get('tiempo',0)}s)")
                        st.markdown(r.get("respuesta","Sin respuesta"))
                        st.markdown("---")
            resp_completa=f"**Síntesis del Consejo:**\n{sintesis.get('respuesta','')}"
            hist_gen.append({"role":"assistant","content":resp_completa})
            st.session_state["mesa_hist_gen"]=hist_gen
            # Guardar en Supabase
            supa("mesa_ia_sessions","POST",{
                "user_id":u["id"],"mode":"general",
                "project_id":st.session_state.get("mesa_proj_id"),
                "pregunta":pregunta,"respuesta":resp_completa
            })

    # ════════════════════════════════════════════════════════════════════
    # MODO FOOTBALL LAB — Laboratorio Fútbol 1X2 "Multiverso 150"
    # ════════════════════════════════════════════════════════════════════
    elif st.session_state["mesa_modo"]=="futbol":
        st.markdown("## ⚽ Laboratorio Fútbol 1X2 — Multiverso 150")
        st.caption("5 IAs analizan en paralelo • 150 rutas con control de exposición 65% • Tickets diferenciados • Modo simulado")

        # ── PING SILENCIOSO GEMINI al entrar al módulo
        if "ftbl_gemini_status" not in st.session_state:
            with st.spinner("🔍 Verificando conexión con IAs..."):
                _ping=gemini_deporte_fn("Responde solo: OK")
                st.session_state["ftbl_gemini_status"]="active" if _ping.get("ok") else "failed"
                st.session_state["ftbl_gemini_err"]=_ping.get("respuesta","")[:150] if not _ping.get("ok") else ""
        if st.session_state.get("ftbl_gemini_status")=="failed":
            _err=st.session_state.get("ftbl_gemini_err","sin detalle")
            st.warning(f"⚠️ Gemini no disponible: {_err}. Análisis con 4 IAs. El flujo continúa normalmente.")

        # ── MODO SIMULADO TOGGLE
        modo_simulado=st.toggle("🔬 Modo simulado (no descuenta bankroll real)",value=True,key="ftbl_modo_sim")
        if modo_simulado:
            st.caption("📋 Modo simulado activo — los tickets se registran pero no afectan bankroll real.")

        tab_f1,tab_f2,tab_f3,tab_f4,tab_f5=st.tabs([
            "📥 Cargar Partidos",
            "🎯 Veredicto IA / Tickets",
            "📒 Registro / Voucher",
            "📈 Resultados",
            "📚 Biblioteca"
        ])

        # ────────────────────────────────────────────────────────────────
        # TAB 1 — CARGAR PARTIDOS
        # ────────────────────────────────────────────────────────────────
        with tab_f1:
            st.markdown("### 📋 Pegar partidos desde cualquier fuente")
            st.caption("Funciona con Wplay, Codere, Betplay, texto libre — copia crudo, sin limpiar.")

            liga_m=st.text_input("🏆 Liga / Competición","Mundial 2026",key="ftbl_liga")
            jornada_m=st.text_input("📅 Fase / Jornada","Fase de Grupos",key="ftbl_jor")

            # Detectar torneo
            def detectar_torneo(liga_str, jor_str):
                t=(liga_str+" "+jor_str).lower()
                if any(x in t for x in ["mundial","world cup","fifa"]): return "Mundial 2026"
                if "libertadores" in t: return "Copa Libertadores"
                if "sudamericana" in t: return "Copa Sudamericana"
                if "premier" in t: return "Premier League"
                if any(x in t for x in ["laliga","la liga","liga española"]): return "La Liga"
                if "bundesliga" in t: return "Bundesliga"
                if "serie a" in t: return "Serie A"
                if "ligue" in t: return "Ligue 1"
                return liga_str or "Torneo no identificado"

            torneo_detectado=detectar_torneo(liga_m,jornada_m)
            # Ajustar pesos: en eliminatorias mundialistas, cuota_valor x2
            es_mundial="Mundial" in torneo_detectado

            texto_pendiente=st.session_state.pop("ftbl_texto_pendiente",None)
            if texto_pendiente:
                st.success("⚽ Texto de Mesa General redirigido aquí automáticamente")

            txt_m=st.text_area(
                "📋 Pega aquí los partidos (copia crudo de Wplay, Codere, etc.)",
                height=260,
                value=texto_pendiente or "",
                key=f"ftbl_txt_m_{st.session_state.get('ftbl_mc',0)}",
                placeholder="""Ejemplo — pega exactamente lo que copias de Wplay:

MUNDIAL 2026 - PARTIDOS
Página ant. 1 / 6 Siguiente página ★ 14:00 15 Jun
★ Bélgica 1.48
Empate 4.00
★ Egipto 7.00 235"""
            )

            col_p1,col_p2=st.columns([1,1])
            with col_p1:
                btn_parsear=st.button("🧠 Parsear partidos",type="primary",use_container_width=True)
            with col_p2:
                btn_limpiar=st.button("🗑️ Limpiar",use_container_width=True)

            if btn_limpiar:
                st.session_state["ftbl_partidos_preview"]=[]
                st.session_state["ftbl_mc"]=st.session_state.get("ftbl_mc",0)+1
                st.rerun()

            if btn_parsear:
                txt_val=st.session_state.get(f"ftbl_txt_m_{st.session_state.get('ftbl_mc',0)}",txt_m)
                if not txt_val: txt_val=txt_m
                if txt_val and txt_val.strip():
                    texto_limpio=limpiar_texto_wplay(txt_val)
                    with st.spinner("🔍 Parseando partidos..."):
                        partidos_preview=[]

                        # CAPA 1: Regex
                        partidos_preview=parser_regex_wplay(texto_limpio)
                        if partidos_preview:
                            st.success(f"✅ Regex extrajo {len(partidos_preview)} partido(s)")

                        # CAPA 2: Gemini fallback (solo si regex < 3)
                        if len(partidos_preview)<3:
                            if partidos_preview:
                                st.info(f"🔄 Regex extrajo {len(partidos_preview)} — ampliando con Gemini...")
                            else:
                                st.info("🔄 Regex no extrajo partidos — intentando con Gemini...")
                            pr_parse=(
                                "Eres extractor de datos deportivos 1X2.\n"
                                "Analiza este texto de casa de apuestas.\n"
                                "Patrón: Equipo1 + cuota1 / Empate + cuotaX / Equipo2 + cuota2.\n"
                                "Ignora números solos mayores a 100 (son códigos de evento).\n"
                                "Devuelve SOLO JSON sin explicación ni markdown:\n"
                                '[{"local":"...","visitante":"...","cuota_1":1.0,'
                                '"cuota_x":1.0,"cuota_2":1.0,"fecha":"","hora":"",'
                                '"fuente":"manual","cuotas_estimadas":false,'
                                '"contexto_h2h":"","observacion":""}]\n\n'
                                f"Texto limpio:\n{texto_limpio}"
                            )
                            raw_gemini=gemini_mesa_fn(pr_parse,temperatura=0.0,max_tokens=4000)
                            if raw_gemini.startswith("Error"):
                                st.warning(f"⚠️ Gemini parser: {raw_gemini[:120]}")
                            else:
                                raw=raw_gemini.strip()
                                if raw.startswith("```"): raw=raw.split("```")[1].lstrip("json").strip()
                                if raw.endswith("```"): raw=raw[:-3].strip()
                                try:
                                    g_partidos=json.loads(raw)
                                    if isinstance(g_partidos,list) and len(g_partidos)>len(partidos_preview):
                                        partidos_preview=g_partidos
                                        st.success(f"✅ Gemini extrajo {len(partidos_preview)} partido(s)")
                                except: pass

                        # Validar cuotas
                        partidos_validos=[]
                        for p in partidos_preview:
                            try:
                                c1=float(p.get("cuota_1",2.0))
                                cx=float(p.get("cuota_x",3.5))
                                c2=float(p.get("cuota_2",3.0))
                                if c1<=0: c1=2.0; p["cuotas_estimadas"]=True
                                if cx<=0: cx=3.5; p["cuotas_estimadas"]=True
                                if c2<=0: c2=3.0; p["cuotas_estimadas"]=True
                                p["cuota_1"]=c1; p["cuota_x"]=cx; p["cuota_2"]=c2
                                partidos_validos.append(p)
                            except: pass

                        if partidos_validos:
                            st.session_state["ftbl_partidos_preview"]=partidos_validos
                            st.session_state["ftbl_liga_preview"]=liga_m
                            st.session_state["ftbl_jor_preview"]=jornada_m
                            st.session_state["ftbl_torneo"]=torneo_detectado
                        else:
                            st.error("❌ No se pudieron extraer partidos. Verifica el formato del texto.")

            # Preview
            preview=st.session_state.get("ftbl_partidos_preview",[])
            if preview:
                st.markdown(f"### ✅ {len(preview)} partidos — Torneo: **{st.session_state.get('ftbl_torneo',torneo_detectado)}**")
                st.caption("Revisa y ajusta cuotas antes de confirmar")
                for i,p in enumerate(preview):
                    col_a,col_b,col_c,col_d=st.columns([3,1,1,1])
                    with col_a: st.write(f"**{p.get('local','')}** vs **{p.get('visitante','')}**")
                    with col_b:
                        new_c1=st.number_input("1",min_value=1.01,value=float(p.get("cuota_1",2.0)),step=0.01,key=f"pc1_{i}",label_visibility="collapsed")
                        preview[i]["cuota_1"]=new_c1
                    with col_c:
                        new_cx=st.number_input("X",min_value=1.01,value=float(p.get("cuota_x",3.2)),step=0.01,key=f"pcx_{i}",label_visibility="collapsed")
                        preview[i]["cuota_x"]=new_cx
                    with col_d:
                        new_c2=st.number_input("2",min_value=1.01,value=float(p.get("cuota_2",3.5)),step=0.01,key=f"pc2_{i}",label_visibility="collapsed")
                        preview[i]["cuota_2"]=new_c2
                    if p.get("cuotas_estimadas"):
                        st.caption("⚠️ Cuota estimada — verifica antes de apostar")

                col_conf,col_canc=st.columns([1,1])
                with col_conf:
                    if st.button("✅ Confirmar y activar bloque",type="primary",use_container_width=True):
                        liga_ok=st.session_state.get("ftbl_liga_preview",liga_m)
                        jor_ok=st.session_state.get("ftbl_jor_preview",jornada_m)
                        tor_ok=st.session_state.get("ftbl_torneo",torneo_detectado)
                        bloque_id=str(uuid.uuid4())
                        supa("futbol_bloques","POST",{
                            "id":bloque_id,"liga":liga_ok,"jornada":jor_ok,
                            "n_partidos":len(preview),"creado_por":u["id"]
                        })
                        for p in preview:
                            supa("futbol_partidos","POST",{
                                "bloque_id":bloque_id,"local":p.get("local",""),
                                "visitante":p.get("visitante",""),
                                "cuota_1":float(p.get("cuota_1",2.0)),
                                "cuota_x":float(p.get("cuota_x",3.2)),
                                "cuota_2":float(p.get("cuota_2",3.5))
                            })
                        st.session_state["ftbl_bloque_id"]=bloque_id
                        st.session_state["ftbl_partidos_activos"]=preview
                        st.session_state["ftbl_liga_activa"]=liga_ok
                        st.session_state["ftbl_jor_activa"]=jor_ok
                        st.session_state["ftbl_torneo_activo"]=tor_ok
                        st.session_state["ftbl_partidos_preview"]=[]
                        st.session_state["ftbl_mc"]=st.session_state.get("ftbl_mc",0)+1
                        # Limpiar análisis anteriores
                        for k in ["ftbl_rutas_150","ftbl_resp_ias","ftbl_sintesis","ftbl_coincidencias"]:
                            st.session_state.pop(k,None)
                        st.success(f"✅ {len(preview)} partidos activados. Ve a 🎯 Veredicto IA / Tickets")
                        st.rerun()
                with col_canc:
                    if st.button("❌ Cancelar",use_container_width=True):
                        st.session_state["ftbl_partidos_preview"]=[]
                        st.rerun()

            # Bloques guardados
            st.markdown("---")
            st.markdown("### 📂 Bloques guardados")
            bloques=supa("futbol_bloques",filtro="?order=creado_en.desc") or []
            if not isinstance(bloques,list): bloques=[]
            for b in [x for x in bloques[:8] if isinstance(x,dict)]:
                btn_lbl=f"⚽ {b.get('liga','')} — {b.get('jornada','')} ({b.get('n_partidos',0)} partidos)"
                if st.button(btn_lbl,key=f"bl_{b['id']}",use_container_width=True):
                    parts=supa("futbol_partidos",filtro=f"?bloque_id=eq.{b['id']}") or []
                    st.session_state["ftbl_bloque_id"]=b["id"]
                    st.session_state["ftbl_partidos_activos"]=parts
                    st.session_state["ftbl_liga_activa"]=b.get("liga","")
                    st.session_state["ftbl_jor_activa"]=b.get("jornada","")
                    st.session_state["ftbl_torneo_activo"]=detectar_torneo(b.get("liga",""),b.get("jornada",""))
                    for k in ["ftbl_rutas_150","ftbl_resp_ias","ftbl_sintesis","ftbl_coincidencias"]:
                        st.session_state.pop(k,None)
                    st.success(f"✅ Bloque activado: {len(parts)} partidos. Ve a 🎯 Veredicto IA / Tickets")
                    st.rerun()

        # ────────────────────────────────────────────────────────────────
        # TAB 2 — VEREDICTO IA / TICKETS
        # ────────────────────────────────────────────────────────────────
        with tab_f2:
            # Define siempre (evita NameError en re-renders)
            _ias_nombres=["ChatGPT","Claude","Gemini","Groq","Mistral"]
            _ico_map={"ChatGPT":"🟢","Claude":"🟤","Gemini":"🔵","Groq":"🟠","Mistral":"🟡"}

            partidos_act=st.session_state.get("ftbl_partidos_activos",[])
            liga_act=st.session_state.get("ftbl_liga_activa","")
            jor_act=st.session_state.get("ftbl_jor_activa","")
            torneo_act=st.session_state.get("ftbl_torneo_activo","")

            if not partidos_act:
                st.info("⬅️ Primero carga un bloque de partidos en 📥 Cargar Partidos")
            else:
                st.markdown(f"### ⚽ {liga_act} — {jor_act}")
                st.caption(f"{len(partidos_act)} partidos | Torneo: {torneo_act}")

                with st.expander("📋 Ver partidos del bloque"):
                    for p in partidos_act:
                        c1,c2,c3=st.columns([4,1,1])
                        c1.write(f"**{p.get('local','')}** vs **{p.get('visitante','')}**")
                        c2.metric("1",f"{float(p.get('cuota_1',2.0)):.2f}")
                        c3.metric("X/2",f"{float(p.get('cuota_x',3.2)):.2f}/{float(p.get('cuota_2',3.5)):.2f}")

                n_rutas=st.slider("🎯 Mostrar N mejores rutas",min_value=5,max_value=20,value=10,step=1)

                # Helper definido en scope externo para que el display lo acceda en cada rerender
                def _ticket_txt(nombre,picks_sel,monto,ligat,jorl,nota=""):
                    n_ias_ok=len(st.session_state.get("ftbl_ias_ok",[]))
                    lines=[f"🎟️ {nombre} — {ligat}",f"📅 {jorl}","━"*24]
                    cuota_t=1.0
                    for k,v in picks_sel:
                        local,visitante=k.split("|")
                        lines.append(f"⚽ {local} vs {visitante}")
                        lines.append(f"   → {v['pred_txt']} ({v['pred']}) @ {v['cuota']:.2f}")
                        lines.append(f"   IAs: {v['n_ias']}/5 | {v['conf']} | Riesgo: {v['riesgo']}")
                        cuota_t*=v["cuota"]
                    lines+=["━"*24,f"💰 Apuesta ${monto:,.0f} → Retorno: ${monto*cuota_t:,.0f}",
                            f"📊 Cuota total: {cuota_t:.2f}x",f"📱 jandrext-ia.streamlit.app | {n_ias_ok}/5 IAs"]
                    if nota: lines.append(f"📌 {nota}")
                    return "\n".join(lines)

                if st.button("🚀 Analizar con 5 IAs y generar tickets",type="primary",use_container_width=True):
                    with st.spinner("🧠 5 IAs analizando (15-30s)..."):
                        import random, math

                        ESTRATEGIAS=[
                            ("VICTORIA_LOCAL",   {"c1":1.4,"cx":0.3,"c2":0.3}),
                            ("EMPATE_TECHNICO",  {"c1":0.3,"cx":1.4,"c2":0.3}),
                            ("VISITANTE_SORPRESA",{"c1":0.3,"cx":0.3,"c2":1.4}),
                            ("ALTA_CONFIANZA",   {"c1":0.5,"cx":0.3,"c2":0.2}),
                            ("CUOTA_VALOR",      {"c1":0.2,"cx":0.4,"c2":0.4}),
                            ("FORMA_RECIENTE",   {"c1":0.45,"cx":0.35,"c2":0.2}),
                            ("POSICION_TABLA",   {"c1":0.5,"cx":0.25,"c2":0.25}),
                            ("MIXTA_EQUILIBRADA",{"c1":0.35,"cx":0.35,"c2":0.3}),
                            ("CONTRA_CORRIENTE", {"c1":0.2,"cx":0.3,"c2":0.5}),
                        ]
                        # En fase de torneo Mundial: POSICION_TABLA peso=0, CUOTA_VALOR x2
                        if es_mundial or "Mundial" in torneo_act:
                            ESTRATEGIAS=[e for e in ESTRATEGIAS if e[0]!="POSICION_TABLA"]

                        def generar_prediccion(partido,pesos):
                            c1=float(partido.get("cuota_1",2.0))
                            cx=float(partido.get("cuota_x",3.2))
                            c2=float(partido.get("cuota_2",3.5))
                            p1=1/c1; px=1/cx; p2=1/c2
                            total=p1+px+p2
                            p1/=total; px/=total; p2/=total
                            s1=p1*pesos["c1"]; sx=px*pesos["cx"]; s2=p2*pesos["c2"]
                            pred=["1","X","2"][[s1,sx,s2].index(max(s1,sx,s2))]
                            cuota={"1":c1,"X":cx,"2":c2}[pred]
                            prob={"1":p1,"X":px,"2":p2}[pred]
                            # EV = probabilidad_implícita * cuota - 1
                            ev=round((prob*cuota)-1,4)
                            return pred,cuota,ev

                        n_p=len(partidos_act)
                        rutas_raw=[]
                        configs=[(min(10,n_p),50),(min(15,n_p),50),(min(20,n_p),50)]
                        seen_hashes=set()
                        for n_sel,n_gen in configs:
                            for _ in range(n_gen):
                                sel=random.sample(partidos_act,min(n_sel,n_p))
                                est_nom,pesos=random.choice(ESTRATEGIAS)
                                picks=[]
                                cuota_total=1.0
                                ev_total=0.0
                                n_empates=0
                                for p in sel:
                                    pred,cuota,ev=generar_prediccion(p,pesos)
                                    if pred=="X": n_empates+=1
                                    picks.append({"local":p.get("local",""),"visitante":p.get("visitante",""),
                                                  "pred":pred,"cuota":cuota,"ev":ev})
                                    cuota_total*=cuota
                                    ev_total+=ev
                                # Límite empates por longitud de ruta
                                max_emp={10:4,15:4,20:5}.get(len(picks),4)
                                if n_empates>max_emp: continue
                                # Evitar rutas idénticas
                                ruta_hash=hashlib.md5(str(sorted([(pk["local"],pk["pred"]) for pk in picks])).encode()).hexdigest()
                                if ruta_hash in seen_hashes: continue
                                seen_hashes.add(ruta_hash)
                                rutas_raw.append({
                                    "estrategia":est_nom,"picks":picks,
                                    "cuota_total":round(cuota_total,2),
                                    "ev_total":round(ev_total/len(picks),4) if picks else 0,
                                    "n_picks":len(picks),"n_empates":n_empates
                                })

                        # Control exposición 65%
                        total_rutas=len(rutas_raw) or 1
                        match_counts={}
                        for r in rutas_raw:
                            for pk in r["picks"]:
                                k=f"{pk['local']}|{pk['pred']}"
                                match_counts[k]=match_counts.get(k,0)+1
                        rutas_ok=[r for r in rutas_raw if not any(
                            match_counts.get(f"{pk['local']}|{pk['pred']}",0)/total_rutas>0.65
                            for pk in r["picks"]
                        )]
                        if len(rutas_ok)<30: rutas_ok=rutas_raw

                        for r in rutas_ok:
                            r["score_final"]=round(r["ev_total"]*0.5+math.log(max(r["cuota_total"],1.01))*0.3+r["n_picks"]*0.02,4)
                        rutas_ok.sort(key=lambda x:x["score_final"],reverse=True)
                        rutas_150=rutas_ok[:150]

                        # 5 IAs en paralelo
                        top_n=min(5,len(rutas_150))
                        top_rutas=rutas_150[:top_n]
                        partidos_str="\n".join([
                            f"{p.get('local','')} vs {p.get('visitante','')} | 1:{float(p.get('cuota_1',2.0)):.2f} X:{float(p.get('cuota_x',3.2)):.2f} 2:{float(p.get('cuota_2',3.5)):.2f}"
                            for p in partidos_act
                        ])
                        rutas_str="\n".join([
                            f"Ruta {i+1}: {r['estrategia']} | {r['n_picks']} picks | Cuota:{r['cuota_total']:.2f} | EV:{r['ev_total']:.3f} | "+
                            " | ".join([f"{pk['local']} {pk['pred']}@{pk['cuota']:.2f}" for pk in r['picks'][:4]])
                            for i,r in enumerate(top_rutas)
                        ])

                        BASE_DEPORTE=(
                            f"Eres un analista experto en apuestas deportivas 1X2.\n"
                            f"Torneo: {torneo_act}. Analiza SOLO sobre fútbol y apuestas.\n"
                            "No menciones contextos empresariales ni temas ajenos al deporte.\n"
                        )
                        roles_futbol={
                            "ChatGPT":(BASE_DEPORTE+"ROL: Generador de predicciones.\nPropón predicción 1/X/2 por partido con justificación breve. Identifica las 3 mejores combinaciones para parlay. Di 1, X o 2 por cada partido."),
                            "Claude":(BASE_DEPORTE+"ROL: Auditor de riesgos.\nDetecta partidos trampa y riesgos ocultos. Indica riesgo bajo/medio/alto por partido. ¿Cuáles evitarías en un parlay?"),
                            "Gemini":(BASE_DEPORTE+f"ROL: Contextualizador {torneo_act}.\nAporta contexto: H2H reciente, fase del torneo, motivación, jugadores clave, factores externos. Si no tienes datos: indica [SIN DATOS]."),
                            "Groq":(BASE_DEPORTE+"ROL: Análisis rápido.\nLos 5 partidos más predecibles. Una línea: equipo + 1/X/2 + razón. Sé muy conciso."),
                            "Mistral":(BASE_DEPORTE+"ROL: Perspectiva alternativa.\n¿Cuotas subvaloradas? ¿Empates estructurales? ¿Visitante con valor real? ¿Dónde se equivoca el mercado?")
                        }

                        def _run_ia_futbol(ia_nombre):
                            rol_ia=roles_futbol.get(ia_nombre,"")
                            prompt_ia=(
                                f"{rol_ia}\n\n"
                                f"PARTIDOS ({liga_act} — {jor_act}):\n{partidos_str}\n\n"
                                f"TOP {top_n} RUTAS:\n{rutas_str}\n\n"
                                "Responde en máximo 300 palabras. Solo análisis deportivo."
                            )
                            try:
                                if ia_nombre=="ChatGPT": r=openai_fn(prompt_ia)
                                elif ia_nombre=="Claude": r=claude_fn(prompt_ia)
                                elif ia_nombre=="Gemini":
                                    r=gemini_deporte_fn(prompt_ia)
                                    if not r.get("ok"):
                                        r={"ia":"Gemini","icono":"🔵","respuesta":"Gemini no disponible.","ok":False,"tiempo":0}
                                elif ia_nombre=="Groq": r=groq_fn(prompt_ia)
                                elif ia_nombre=="Mistral": r=mistral_fn(prompt_ia)
                                else: r={"ia":ia_nombre,"respuesta":"No disponible","ok":False,"tiempo":0}
                            except Exception as e_ia:
                                r={"ia":ia_nombre,"respuesta":f"Error: {str(e_ia)[:80]}","ok":False,"tiempo":0}
                            r["ia"]=ia_nombre
                            return r

                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                            futs={ex.submit(_run_ia_futbol,ia):ia for ia in _ias_nombres}
                            resp_futbol={ia:f.result() for f,ia in [(f,futs[f]) for f in concurrent.futures.as_completed(futs)]}

                        ias_ok_list=[ia for ia in _ias_nombres if resp_futbol[ia].get("ok")]
                        ias_fail_list=[ia for ia in _ias_nombres if not resp_futbol[ia].get("ok")]
                        n_ias_ok=len(ias_ok_list)

                        # Síntesis consenso con Claude
                        resp_texts="\n\n".join([
                            f"**{ia}**: {resp_futbol[ia].get('respuesta','')[:400]}"
                            for ia in ias_ok_list
                        ])
                        sint_fut_prompt=(
                            f"Eres árbitro de análisis deportivo puro — {torneo_act}.\n"
                            f"{n_ias_ok}/5 IAs disponibles analizaron {top_n} rutas.\n\n"
                            f"ANÁLISIS:\n{resp_texts}\n\n"
                            "Sintetiza SOLO sobre apuestas deportivas:\n"
                            "1. **RUTA RECOMENDADA** (número + estrategia con mayor consenso)\n"
                            "2. **CONFIANZA** (🟢 Alta ≥4 IAs / 🟡 Media 3 / 🔴 Baja <3) + razón\n"
                            "3. **PICKS MÁS SEGUROS** — donde coincide la mayoría\n"
                            "4. **RIESGO OCULTO** — pick más peligroso y por qué\n\n"
                            "Máximo 250 palabras. Sin mencionar empresas ni contextos ajenos."
                        )
                        sint_fut=claude_fn(sint_fut_prompt)

                        # Veredicto por partido (consenso + riesgo)
                        veredicto_partidos={}
                        for p in partidos_act:
                            local=p.get("local","")
                            visitante=p.get("visitante","")
                            c1=float(p.get("cuota_1",2.0))
                            cx=float(p.get("cuota_x",3.2))
                            c2=float(p.get("cuota_2",3.5))
                            # Probabilidad implícita normalizada
                            pr1=1/c1; prx=1/cx; pr2=1/c2
                            tot=pr1+prx+pr2; pr1/=tot; prx/=tot; pr2/=tot
                            # Pick de mayor probabilidad
                            picks_prob={"1":(pr1,c1),"X":(prx,cx),"2":(pr2,c2)}
                            best_pred=max(picks_prob,key=lambda k:picks_prob[k][0])
                            best_cuota=picks_prob[best_pred][1]
                            best_prob=picks_prob[best_pred][0]
                            ev_partido=round((best_prob*best_cuota)-1,4)
                            # Contar IAs que mencionan al local favorably
                            n_ias_favor=0
                            for ia in ias_ok_list:
                                txt=resp_futbol[ia].get("respuesta","").lower()
                                if local.lower()[:5] in txt or visitante.lower()[:5] in txt:
                                    n_ias_favor+=1
                            # FIX 3 — Confianza por consenso (independiente del EV)
                            if n_ias_favor>=4: conf="🟢 Alta confianza"
                            elif n_ias_favor>=3: conf="🟡 Media confianza"
                            elif n_ias_favor>=2: conf="🟡 Confianza media"
                            else: conf="🔴 Baja confianza"
                            # apta_para: por consenso y cuota — NUNCA "No recomendada" para consenso>=3
                            _cons_ratio=n_ias_favor/max(n_ias_ok,1)
                            if _cons_ratio>=0.75 and best_cuota<=2.00:
                                apta_para="Ticket conservador corto"
                            elif _cons_ratio>=0.60 and best_cuota<=2.50:
                                apta_para="Ticket balanceado"
                            elif _cons_ratio>=0.50 and best_cuota>2.50:
                                apta_para="Ticket de valor"
                            elif _cons_ratio<0.50 or (ev_partido<-0.05 and _cons_ratio<0.60):
                                apta_para="Evitar"
                            else:
                                apta_para="Ticket balanceado"
                            # Riesgo por cuota
                            if best_cuota<1.5: riesgo="Bajo"
                            elif best_cuota<2.5: riesgo="Medio"
                            else: riesgo="Alto"
                            pred_txt={"1":f"{local} gana","X":"Empate","2":f"{visitante} gana"}.get(best_pred,best_pred)
                            veredicto_partidos[f"{local}|{visitante}"]={
                                "pred":best_pred,"pred_txt":pred_txt,
                                "cuota":best_cuota,"ev":ev_partido,
                                "n_ias":n_ias_favor,"conf":conf,"riesgo":riesgo,"apta_para":apta_para
                            }

                        # Generar 3 tickets diferenciados
                        # Todos los partidos ordenados por consenso (FIX 2+3: sin filtro EV)
                        todos_picks=[(k,v) for k,v in veredicto_partidos.items()]
                        todos_picks.sort(key=lambda x:-x[1]["n_ias"])
                        picks_ev_pos=[(k,v) for k,v in todos_picks if v["ev"]>=0]
                        picks_ordenados=picks_ev_pos  # para rutas y referencias

                        # FIX 3: Ticket Conservador SIEMPRE generado
                        # Primero intentar picks con EV>=0 y cuota<=2.50
                        _cand_conserv=[(k,v) for k,v in todos_picks if v["ev"]>=0 and v["cuota"]<=2.50]
                        if len(_cand_conserv)>=2:
                            ticket_conserv=_cand_conserv[:4]
                            _nota_conserv=""
                        else:
                            # FIX 3 fallback: top 3 por consenso sin importar EV ni cuota
                            ticket_conserv=todos_picks[:min(3,len(todos_picks))]
                            _nota_conserv="No hay picks premium, pero estas son las mejores opciones disponibles para intento controlado."
                        st.session_state["ftbl_nota_conserv"]=_nota_conserv

                        ticket_balanc=picks_ev_pos[:min(6,len(picks_ev_pos))] or todos_picks[:min(4,len(todos_picks))]
                        ticket_prem=[(k,v) for k,v in picks_ev_pos if v["conf"]=="🟢 Alta confianza"][:5]

                        gemini_ctx=resp_futbol.get("Gemini",{}).get("respuesta","Sin contexto Gemini")[:300]

                        # Guardar todo
                        st.session_state["ftbl_rutas_150"]=rutas_150
                        st.session_state["ftbl_resp_ias"]=resp_futbol
                        st.session_state["ftbl_sintesis"]=sint_fut
                        st.session_state["ftbl_veredicto"]=veredicto_partidos
                        st.session_state["ftbl_tickets"]={
                            "conservador":ticket_conserv,
                            "balanceado":ticket_balanc,
                            "premium":ticket_prem,
                            "gemini_ctx":gemini_ctx
                        }
                        st.session_state["ftbl_ias_ok"]=ias_ok_list
                        st.session_state["ftbl_ias_fail"]=ias_fail_list
                        st.rerun()

                # ── MOSTRAR RESULTADOS (después del rerun)
                rutas_150=st.session_state.get("ftbl_rutas_150",[])
                resp_futbol=st.session_state.get("ftbl_resp_ias",{})
                sint_fut=st.session_state.get("ftbl_sintesis",{})
                veredicto_partidos=st.session_state.get("ftbl_veredicto",{})
                tickets_data=st.session_state.get("ftbl_tickets",{})
                ias_ok_list=st.session_state.get("ftbl_ias_ok",[])
                ias_fail_list=st.session_state.get("ftbl_ias_fail",[])
                n_ias_ok=len(ias_ok_list)

                if rutas_150:
                    # Estado IAs
                    st.markdown(f"**{n_ias_ok}/5 IAs disponibles:** {', '.join(ias_ok_list)}")
                    if ias_fail_list:
                        st.caption(f"❌ No disponibles: {', '.join(ias_fail_list)}")
                    cols5=st.columns(5)
                    for i,ia in enumerate(_ias_nombres):
                        r=resp_futbol.get(ia,{})
                        with cols5[i]:
                            st.markdown(f"**{_ico_map.get(ia,'⚪')} {ia}**")
                            st.caption(f"{'✅' if r.get('ok') else '❌'} {r.get('tiempo',0):.1f}s")

                    st.markdown("---")

                    # ── VEREDICTO POR PARTIDO
                    st.markdown("### 🎯 Veredicto por partido")
                    for k,v in veredicto_partidos.items():
                        local,visitante=k.split("|")
                        with st.container():
                            st.markdown(
                                f"**{local} vs {visitante}** @{v['cuota']:.2f}\n\n"
                                f"→ **Pick:** {v['pred_txt']} | "
                                f"**Consenso:** {v['n_ias']}/{n_ias_ok} IAs | "
                                f"**{v['conf']}** | **Riesgo:** {v['riesgo']}\n\n"
                                f"→ *Apta para: {v['apta_para']}*"
                            )
                            st.markdown("---")

                    # ── SÍNTESIS CONSEJO
                    st.markdown("### 🧠 Síntesis del Consejo")
                    sint_txt=sint_fut.get("respuesta","") if isinstance(sint_fut,dict) else str(sint_fut)
                    st.info(sint_txt if sint_txt else "Síntesis no disponible.")

                    # Análisis individuales
                    with st.expander("🔬 Ver análisis completos de cada IA"):
                        for ia in _ias_nombres:
                            res=resp_futbol.get(ia,{})
                            ok_txt="✅" if res.get("ok") else "❌"
                            with st.expander(f"{_ico_map.get(ia,'🤖')} {ia} {ok_txt} ({res.get('tiempo',0):.1f}s)"):
                                st.write(res.get("respuesta","Sin respuesta"))

                    st.markdown("---")

                    # ── 3 TICKETS DIFERENCIADOS
                    st.markdown("### 🎟️ Tickets sugeridos")
                    gemini_ctx=tickets_data.get("gemini_ctx","")

                    tcol1,tcol2,tcol3=st.columns(3)

                    with tcol1:
                        st.markdown("**🟢 Conservador ($1.000-$2.000)**")
                        picks_c=tickets_data.get("conservador",[])
                        nota_c=st.session_state.get("ftbl_nota_conserv","")
                        if picks_c:
                            txt_c=_ticket_txt("TICKET CONSERVADOR",picks_c,1000,liga_act,jor_act,nota=nota_c)
                            if gemini_ctx: txt_c+=f"\n\n📍 Contexto Gemini:\n{gemini_ctx}"
                            st.code(txt_c,language=None)
                        else:
                            st.info("⚠️ Sin partidos analizados aún. Genera el análisis primero.")

                    with tcol2:
                        st.markdown("**🟡 Balanceado ($1.000)**")
                        picks_b=tickets_data.get("balanceado",[])
                        if picks_b:
                            txt_b=_ticket_txt("TICKET BALANCEADO",picks_b,1000,liga_act,jor_act)
                            if gemini_ctx: txt_b+=f"\n\n📍 Contexto Gemini:\n{gemini_ctx}"
                            st.code(txt_b,language=None)
                        else:
                            st.info("⚠️ Sin partidos analizados aún. Genera el análisis primero.")

                    with tcol3:
                        st.markdown("**🔴 Premium ($5.000) — solo ≥4 IAs**")
                        picks_p=tickets_data.get("premium",[])
                        if picks_p:
                            txt_p=_ticket_txt("TICKET PREMIUM",picks_p,5000,liga_act,jor_act)
                            if gemini_ctx: txt_p+=f"\n\n📍 Contexto Gemini:\n{gemini_ctx}"
                            st.code(txt_p,language=None)
                        else:
                            st.caption("No hay picks con Alta confianza 🟢 esta vez.")

                    st.caption("☝️ Selecciona el texto del ticket y copia (Ctrl+A / Cmd+A dentro del cuadro)")

                    st.markdown("---")

                    # ── TOP N RUTAS — FIX 4 + FIX 6
                    # FIX 4: Re-ordenar rutas por consenso IAs primero, luego EV, penalizar cuotas extremas
                    def _score_ruta(r):
                        cuota=r.get("cuota_total",1)
                        ev=r.get("ev_total",0)
                        n_picks=r.get("n_picks",1)
                        # Penalizaciones
                        if cuota>100000: return -9999
                        if cuota>10000: return -999 + ev
                        if cuota>1000: return -99 + ev
                        if ev<-0.03: return ev - 0.5  # No puede ser Top3
                        # Score: consenso + ev moderado
                        return ev*0.5 + min(math.log(max(cuota,1.01)),4)*0.3 + n_picks*0.02
                    rutas_150_sorted=sorted(rutas_150,key=_score_ruta,reverse=True)

                    # FIX 6: Filtrar rutas ocultas
                    rutas_ocultas=st.session_state.get("rutas_ocultas",[])
                    rutas_visibles=[r for r in rutas_150_sorted if r.get("id") not in rutas_ocultas]
                    top_show=rutas_visibles[:n_rutas]

                    # Separar en secciones
                    _sec_rec=[r for r in top_show if r.get("cuota_total",0)<=50 and r.get("ev_total",0)>=-0.03]
                    _sec_bal=[r for r in top_show if r.get("cuota_total",0)<=1000 and r not in _sec_rec]
                    _sec_exp=[r for r in top_show if r.get("cuota_total",0)>1000 and r.get("cuota_total",0)<=100000]
                    _sec_lot=[r for r in top_show if r.get("cuota_total",0)>100000]

                    if rutas_ocultas:
                        if st.button("👁️ Mostrar rutas ocultas",key="mostrar_ocultas_top"):
                            st.session_state["rutas_ocultas"]=[]
                            st.rerun()
                        st.caption(f"{len(rutas_ocultas)} ruta(s) oculta(s) | disponibles en Biblioteca")

                    st.markdown(f"### 🏆 Top {len(top_show)} Rutas (de {len(rutas_150)} generadas)")

                    def _render_rutas(lista_rutas,sec_label,expandir_primero=False):
                        for idx_s,r in enumerate(lista_rutas):
                            r_id=r.get("id",idx_s)
                            if r["ev_total"]>0.05: color="🟢"
                            elif r["ev_total"]>0: color="🟡"
                            else: color="🔴"
                            n_ias_acuerdo=0
                            for ia in ias_ok_list:
                                txt=resp_futbol.get(ia,{}).get("respuesta","").lower()
                                if r["estrategia"].lower()[:6] in txt: n_ias_acuerdo+=1
                            if r["ev_total"]<0:
                                consenso_ruta="🔴 Bajo valor esperado"
                            elif n_ias_acuerdo>=4: consenso_ruta="🟢 Alta confianza"
                            elif n_ias_acuerdo>=3: consenso_ruta="🟡 Confianza media"
                            else: consenso_ruta="🔴 Baja confianza"
                            exp_label=(f"{color} {r['estrategia']} | {r['n_picks']} picks | "
                                       f"Cuota: {r['cuota_total']:.2f} | EV: {r['ev_total']:.3f} | {consenso_ruta}")
                            with st.expander(exp_label,expanded=(expandir_primero and idx_s==0)):
                                # FIX 6: Botón ✕ eliminar ruta
                                col_tbl,col_del=st.columns([10,1])
                                with col_del:
                                    _key_del=f"del_ruta_{sec_label}_{idx_s}_{r_id}"
                                    if st.button("✕",key=_key_del,help="Ocultar esta ruta"):
                                        st.session_state.setdefault("rutas_ocultas",[])
                                        if r_id not in st.session_state["rutas_ocultas"]:
                                            st.session_state["rutas_ocultas"].append(r_id)
                                        st.toast("Ruta ocultada. Disponible en Biblioteca.")
                                        st.rerun()
                                with col_tbl:
                                    picks_md="| Partido | Pred | Cuota | EV |\n|---|---|---|---|\n"
                                    for pk in r["picks"]:
                                        picks_md+=f"| {pk['local']} vs {pk['visitante']} | **{pk['pred']}** | {pk['cuota']:.2f} | {pk['ev']:+.3f} |\n"
                                    st.markdown(picks_md)
                                    st.caption(f"IAs en consenso: {n_ias_acuerdo}/{n_ias_ok} | {consenso_ruta}")
                                ticket_lines=[
                                    f"🎟️ PARLAY — {liga_act}",f"📅 {jor_act} | {r['estrategia']}",
                                    f"🎯 Cuota: {r['cuota_total']:.2f}x | EV: {r['ev_total']:+.3f}","━"*24,
                                ]
                                for pk in r["picks"]:
                                    pred_txt={"1":f"{pk['local']} gana","X":"Empate","2":f"{pk['visitante']} gana"}.get(pk["pred"],pk["pred"])
                                    ticket_lines+=[f"⚽ {pk['local']} vs {pk['visitante']}",f"   → {pred_txt} ({pk['pred']}) @ {pk['cuota']:.2f}"]
                                ticket_lines+=["━"*24,f"💰 $1.000 → ${1000*r['cuota_total']:,.0f}",
                                               f"🧠 Football Lab | {consenso_ruta}","📱 jandrext-ia.streamlit.app"]
                                st.code("\n".join(ticket_lines),language=None)

                    if _sec_rec:
                        st.markdown("#### 🎯 Recomendados")
                        _render_rutas(_sec_rec,"rec",expandir_primero=True)
                    if _sec_bal:
                        st.markdown("#### ⚖️ Balanceados")
                        _render_rutas(_sec_bal,"bal")
                    if _sec_exp:
                        st.markdown("#### 🎲 Experimentales _(cuota > 1.000x)_")
                        _render_rutas(_sec_exp,"exp")
                    if _sec_lot:
                        st.markdown("#### 🎰 Entretenimiento / Lotería _(cuota > 100.000x)_")
                        _render_rutas(_sec_lot,"lot")

        # ────────────────────────────────────────────────────────────────
        # TAB 3 — REGISTRO / VOUCHER
        # ────────────────────────────────────────────────────────────────
        with tab_f3:
            st.markdown("### 📒 Registro de Apuesta / Voucher")
            modo_sim_val=st.session_state.get("ftbl_modo_sim",True)
            st.info(f"Modo actual: {'🔬 Simulado' if modo_sim_val else '💰 Real'}")

            tickets_data_r=st.session_state.get("ftbl_tickets",{})
            liga_r=st.session_state.get("ftbl_liga_activa","")
            jor_r=st.session_state.get("ftbl_jor_activa","")
            tor_r=st.session_state.get("ftbl_torneo_activo","")

            if not tickets_data_r:
                st.info("⬅️ Primero genera el análisis en 🎯 Veredicto IA / Tickets")
            else:
                tipo_ticket=st.selectbox("Tipo de ticket a registrar",
                    ["Conservador","Balanceado","Premium","Personalizado"])
                casa_apuestas=st.selectbox("Casa de apuestas",["Wplay","Codere","Betplay","Otra"])
                stake=st.number_input("Monto apostado ($)",min_value=0,value=1000,step=500)
                voucher_txt=st.text_area("📋 Pega aquí el comprobante (opcional)",height=120,
                    placeholder="Copia el número de ticket o código de confirmación de la casa de apuestas...")

                if st.button("💾 Registrar apuesta",type="primary",use_container_width=True):
                    ticket_id=str(uuid.uuid4())[:8].upper()
                    n_ias_r=len(st.session_state.get("ftbl_ias_ok",[]))
                    supa("football_bets","POST",{
                        "user_id":u["id"],
                        "ticket_id":ticket_id,
                        "casa_apuestas":casa_apuestas,
                        "torneo":tor_r,
                        "tipo_ticket":tipo_ticket.lower(),
                        "stake":stake,
                        "status":"simulated" if modo_sim_val else "placed",
                        "voucher_text":voucher_txt,
                        "consenso_ias":n_ias_r,
                        "simulado":modo_sim_val,
                        "ai_ticket_json":json.dumps(tickets_data_r.get(tipo_ticket.lower(),{}),ensure_ascii=False)[:2000]
                    })
                    if modo_sim_val:
                        st.success(f"✅ Ticket #{ticket_id} registrado en modo SIMULADO. No afecta bankroll.")
                    else:
                        st.success(f"✅ Ticket #{ticket_id} registrado en modo REAL. Revisa tu saldo.")

                # Apuestas registradas
                st.markdown("---")
                st.markdown("### 📋 Apuestas registradas")
                bets=supa("football_bets",filtro=f"?user_id=eq.{u['id']}&order=created_at.desc&limit=10") or []
                if not isinstance(bets,list): bets=[]
                for bet in [x for x in bets if isinstance(x,dict)]:
                    modo_b="🔬" if bet.get("simulado") else "💰"
                    st.markdown(
                        f"{modo_b} **#{bet.get('ticket_id','')}** | {bet.get('tipo_ticket','')} | "
                        f"{bet.get('casa_apuestas','')} | ${bet.get('stake',0):,.0f} | "
                        f"Estado: `{bet.get('status','')}`"
                    )

        # ────────────────────────────────────────────────────────────────
        # TAB 4 — RESULTADOS
        # ────────────────────────────────────────────────────────────────
        with tab_f4:
            st.markdown("### 📈 Resultados y Accuracy")
            st.info("📅 Próximamente: carga de resultados reales y cálculo de ROI por estrategia.")

        # ────────────────────────────────────────────────────────────────
        # TAB 5 — BIBLIOTECA
        # ────────────────────────────────────────────────────────────────
        with tab_f5:
            st.markdown("### 📚 Biblioteca de Bloques")
            bloques_bib=supa("futbol_bloques",filtro="?order=creado_en.desc") or []
            if not isinstance(bloques_bib,list): bloques_bib=[]
            if not bloques_bib:
                st.info("Aún no hay bloques guardados.")
            for b in [x for x in bloques_bib[:20] if isinstance(x,dict)]:
                st.markdown(f"⚽ **{b.get('liga','')} — {b.get('jornada','')} | {b.get('n_partidos',0)} partidos")
