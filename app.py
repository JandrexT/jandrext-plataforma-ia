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
def gemini_fn(p, modelo="gemini-2.0-flash"):
    try:
        t=time.time()
        api_key=get_secret("GOOGLE_API_KEY")
        if not api_key: return {"ia":"Gemini","icono":"🔴","respuesta":"Sin API key","tiempo":0,"ok":False}
        GEMINI_URL="https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
        headers={"Content-Type":"application/json","x-goog-api-key":api_key}
        payload={"contents":[{"parts":[{"text":CONTEXTO+"\n\nConsulta: "+p}]}]}
        r=req.post(GEMINI_URL,headers=headers,json=payload,timeout=30)
        if r.status_code==200:
            txt=r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return {"ia":"Gemini","icono":"🔵","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Gemini","icono":"🔴","respuesta":f"HTTP {r.status_code} | {r.text[:200]}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Gemini","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

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
            json={"model":"meta-llama/llama-3-8b-instruct:free",
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

# ── MESA IA — DIRECTIVA Y AGENTES ─────────────────────────────────────────────────────
DIRECTIVA_FILOSOFICA = (
    "DIRECTIVA FILOSÓFICA: Nunca decir que algo no se puede. "
    "Siempre proponer el camino. Los obstáculos son variables medibles. "
    "El error es información. Modo: construcción permanente. Sin techo."
)

def claude_fn(p):
    try:
        t=time.time()
        api_key=get_secret("ANTHROPIC_API_KEY")
        if not api_key: return {"ia":"Claude","icono":"🟤","rol":"auditor lógico","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json"}
        sys_ctx=CONTEXTO+"\n\n"+DIRECTIVA_FILOSOFICA+"\n\nRol en Mesa IA: AUDITOR LÓGICO — analiza consistencia, detecta contradicciones, propone ruta sólida."
        r=req.post("https://api.anthropic.com/v1/messages",
            json={"model":"claude-haiku-4-5-20251001","max_tokens":1500,
                  "system":sys_ctx,"messages":[{"role":"user","content":p}]},
            headers=h,timeout=30)
        if r.status_code==200:
            txt=r.json()["content"][0]["text"].strip()
            return {"ia":"Claude","icono":"🟤","rol":"auditor lógico","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Claude","icono":"🔴","rol":"auditor lógico","respuesta":f"HTTP {r.status_code}: {r.text[:200]}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Claude","icono":"🔴","rol":"auditor lógico","respuesta":str(e),"tiempo":0,"ok":False}

def chatgpt_fn(p):
    try:
        t=time.time()
        api_key=get_secret("OPENAI_API_KEY")
        if not api_key: return {"ia":"ChatGPT","icono":"🟢","rol":"hipótesis","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
        sys_ctx=CONTEXTO+"\n\n"+DIRECTIVA_FILOSOFICA+"\n\nRol en Mesa IA: HIPÓTESIS — genera hipótesis creativas, posibilidades y escenarios alternativos."
        r=req.post("https://api.openai.com/v1/chat/completions",
            json={"model":"gpt-4o-mini",
                  "messages":[{"role":"system","content":sys_ctx},{"role":"user","content":p}],
                  "max_tokens":1500},
            headers=h,timeout=30)
        if r.status_code==200:
            txt=r.json()["choices"][0]["message"]["content"].strip()
            return {"ia":"ChatGPT","icono":"🟢","rol":"hipótesis","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"ChatGPT","icono":"🔴","rol":"hipótesis","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"ChatGPT","icono":"🔴","rol":"hipótesis","respuesta":str(e),"tiempo":0,"ok":False}

def gemini_mesa_fn(p):
    prompt_ext = DIRECTIVA_FILOSOFICA + "\n\nRol en Mesa IA: CONTEXTUALIZADOR — sitúa el problema en contexto amplio, tendencias del sector, referencias históricas, comparativas internacionales.\n\nPregunta: " + p
    r = gemini_fn(prompt_ext)
    r["rol"] = "contextualizador"
    r["ia"] = "Gemini"
    r["icono"] = "🔵"
    return r
def groq_mesa_fn(p):
    try:
        from groq import Groq; t=time.time()
        sys_ctx=CONTEXTO+"\n\n"+DIRECTIVA_FILOSOFICA+"\n\nRol en Mesa IA: ANÁLISIS RÁPIDO — diagnóstico directo y accionable, prioriza claridad."
        r=Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":sys_ctx},{"role":"user","content":p}],max_tokens=1500)
        return {"ia":"Groq","icono":"🟠","rol":"análisis rápido","respuesta":r.choices[0].message.content.strip(),"tiempo":round(time.time()-t,2),"ok":True}
    except Exception as e: return {"ia":"Groq","icono":"🔴","rol":"análisis rápido","respuesta":str(e),"tiempo":0,"ok":False}

def mistral_mesa_fn(p):
    try:
        t=time.time()
        api_key=get_secret("MISTRAL_API_KEY")
        if not api_key: return {"ia":"Mistral","icono":"🟡","rol":"perspectiva alternativa","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
        sys_ctx=CONTEXTO+"\n\n"+DIRECTIVA_FILOSOFICA+"\n\nRol en Mesa IA: PERSPECTIVA ALTERNATIVA — desafía supuestos, ofrece ángulos no convencionales."
        r=req.post("https://api.mistral.ai/v1/chat/completions",
            json={"model":"mistral-small-latest",
                  "messages":[{"role":"system","content":sys_ctx},{"role":"user","content":p}],
                  "max_tokens":1500},
            headers=h,timeout=30)
        if r.status_code==200:
            txt=r.json()["choices"][0]["message"]["content"].strip()
            return {"ia":"Mistral","icono":"🟡","rol":"perspectiva alternativa","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Mistral","icono":"🔴","rol":"perspectiva alternativa","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Mistral","icono":"🔴","rol":"perspectiva alternativa","respuesta":str(e),"tiempo":0,"ok":False}

def mesa_ia_sintesis_fn(pregunta, resultados):
    ok_r=[r for r in resultados if r["ok"]]
    if not ok_r: return "Sin respuestas disponibles.", "Bajo"
    resumen="\n\n".join([f"=== {r['ia']} ({r.get('rol','')}) ===\n{r['respuesta']}" for r in ok_r])
    prompt_s=(DIRECTIVA_FILOSOFICA+
        "\n\nEres Claude, sintetizador de la Mesa IA de JandrexT Soluciones Integrales."
        f"\n\nPregunta: \"{pregunta}\"\n\nPerspectivas:\n{resumen}"
        "\n\nResponde en este formato exacto:\n"
        "SÍNTESIS: [párrafo integrador orientado a acción]\n"
        "CONFIANZA: [Alto/Medio/Bajo]\n"
        "RUTA DE ACCIÓN:\n1. [paso]\n2. [paso]\n3. [paso]\n"
        "ADVERTENCIAS: [riesgos o 'Ninguna relevante']")
    try:
        api_key=get_secret("ANTHROPIC_API_KEY")
        if api_key:
            h={"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json"}
            r=req.post("https://api.anthropic.com/v1/messages",
                json={"model":"claude-haiku-4-5-20251001","max_tokens":2000,
                      "messages":[{"role":"user","content":prompt_s}]},
                headers=h,timeout=45)
            if r.status_code==200:
                txt=r.json()["content"][0]["text"].strip()
                confianza="Medio"
                if "CONFIANZA: Alto" in txt: confianza="Alto"
                elif "CONFIANZA: Bajo" in txt: confianza="Bajo"
                return txt, confianza
    except: pass
    try:
        api_key=get_secret("GOOGLE_API_KEY")
        if api_key:
            GURL="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
            hh={"Content-Type":"application/json","x-goog-api-key":api_key}
            rr=req.post(GURL,headers=hh,json={"contents":[{"parts":[{"text":prompt_s}]}]},timeout=45)
            if rr.status_code==200:
                txt=rr.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                confianza="Medio"
                if "CONFIANZA: Alto" in txt: confianza="Alto"
                elif "CONFIANZA: Bajo" in txt: confianza="Bajo"
                return txt, confianza
    except: pass
    return (ok_r[0]["respuesta"] if ok_r else "Sin síntesis."), "Bajo"

def juez_fn(pregunta, respuestas):
    ok_resps = [r for r in respuestas if r["ok"]]
    if not ok_resps: return "No se obtuvo respuesta de ninguna fuente."
    if len(ok_resps) == 1: return ok_resps[0]["respuesta"]
    resumen = "\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in ok_resps])
    prompt_juez = f"{CONTEXTO}\nPregunta del usuario: \"{pregunta}\"\nRespuestas de diferentes fuentes:\n{resumen}\n\nSintetiza la mejor respuesta: empática, profesional, práctica. Sin mencionar las fuentes ni encabezados."
    try:
        api_key = get_secret("GOOGLE_API_KEY")
        if api_key:
            GEMINI_URL="https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
            headers={"Content-Type":"application/json","x-goog-api-key":api_key}
            payload={"contents":[{"parts":[{"text":prompt_juez}]}]}
            r=req.post(GEMINI_URL,headers=headers,json=payload,timeout=30)
            if r.status_code==200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except: pass
    try:
        return groq_simple(prompt_juez)
    except: pass
    return max(ok_resps, key=lambda x: len(x["respuesta"]))["respuesta"]

def ia_generar(prompt, modelo="gemini-2.0-flash"):
    try:
        api_key=get_secret("GOOGLE_API_KEY")
        if not api_key:
            return groq_simple(prompt)
        GEMINI_URL="https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
        headers={"Content-Type":"application/json","x-goog-api-key":api_key}
        payload={"contents":[{"parts":[{"text":CONTEXTO+"\n\n"+prompt}]}]}
        r=req.post(GEMINI_URL,headers=headers,json=payload,timeout=30)
        if r.status_code==200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
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
            payload = {"contents":[{"parts":[{"text":prompt_json},{"inline_data":{"mime_type":mime,"data":b64}}]}]}
            GEMINI_URL="https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
            headers={"Content-Type":"application/json","x-goog-api-key":api_key}
            r = req.post(GEMINI_URL, headers=headers, json=payload, timeout=45)
            if r.status_code == 200:
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
# ── Supabase keep-alive ping (cada 5 min) ───────────────────────────────────────────────────
_ping_now=time.time()
if "supa_last_ping" not in st.session_state or _ping_now-st.session_state["supa_last_ping"]>300:
    try: supa("usuarios","GET",filtro="?limit=1")
    except: pass
    st.session_state["supa_last_ping"]=_ping_now

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
              ("👑","usuarios","Especialistas y Aliados"),("🧠","mesa_ia","Mesa IA"),("⚙️","config","Configuración")]
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
            with st.popover("⋮"):
                if st.button("🗑️ Eliminar",key=f"dm_{m['id']}",use_container_width=True):
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
# INICIO — DASHBOARD CON NAOMI ❤️
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# LABORATORIO FÚTBOL 1X2 — FUNCIONES
# ══════════════════════════════════════════════════════════════════════════════
ESTR_FTBL=["E1","E2","E3","E4","E5","E6","E7","E8","E9"]
ESTR_NAMES={"E1":"Local Fuerte","E2":"Visit Forma","E3":"Empate","E4":"Cuota Min","E5":"Dbl Chance","E6":"Cuota<2.2","E7":"Def Solida","E8":"Atq Voraz","E9":"Consenso"}

def predecir_1x2_ftbl(estrategia,partido):
    pos_l=partido.get("posicion_local",8);pos_v=partido.get("posicion_visitante",8)
    c1=float(partido.get("cuota_1",2.0));cx=float(partido.get("cuota_x",3.5));c2=float(partido.get("cuota_2",3.0))
    fl=int(partido.get("forma_local",2));fv=int(partido.get("forma_visitante",2))
    if estrategia=="E1":
        return ("1",min(88,85-pos_l*2)) if pos_l<=5 else ("2",min(80,75-pos_v*2)) if pos_v<=5 else ("1",45)
    elif estrategia=="E2":
        return ("2",65+fv*4) if fv>=4 else ("1",65+fl*4) if fl>=4 else ("X",52)
    elif estrategia=="E3":
        return ("X",62) if abs(pos_l-pos_v)<=3 else ("1",55) if pos_l<pos_v else ("2",55)
    elif estrategia=="E4":
        mc=min(c1,cx,c2); r="1" if mc==c1 else "2" if mc==c2 else "X"
        return (r,min(90,int(90/mc)))
    elif estrategia=="E5":
        return ("1",65) if fl>=3 and pos_l<=pos_v else ("2",65) if fv>=3 and pos_v<pos_l else ("X",55)
    elif estrategia=="E6":
        return ("1",58) if c1<2.2 else ("2",58) if c2<2.2 else ("X",52)
    elif estrategia=="E7":
        return ("1",72) if pos_l<=6 and fl>=3 else ("2",62) if pos_v<=6 else ("X",50)
    elif estrategia=="E8":
        return ("1",75) if fl>=4 else ("2",60) if fl<=1 and fv>=3 else ("1" if pos_l<pos_v else "X",53)
    elif estrategia=="E9":
        v={"1":0,"X":0,"2":0}
        if pos_l<pos_v: v["1"]+=2
        elif pos_l>pos_v: v["2"]+=2
        else: v["X"]+=1
        if fl>fv: v["1"]+=1
        elif fv>fl: v["2"]+=1
        else: v["X"]+=1
        if c1<c2: v["1"]+=1
        else: v["2"]+=1
        w=max(v,key=lambda k:v[k]); return (w,52+v[w]*6)
    return ("1",50)

def generar_150_rutas_ftbl(partidos):
    rutas=[]; n=0
    for e in ESTR_FTBL:
        n+=1; preds=[]; ct=0
        for p in partidos:
            pred,conf=predecir_1x2_ftbl(e,p)
            preds.append({"partido":f"{p.get('local','')} vs {p.get('visitante','')}","pred":pred,"conf":conf})
            ct+=conf
        rutas.append({"ruta":n,"estrategia":e,"preds":preds,"conf":round(ct/max(len(partidos),1))})
    pairs=[(ESTR_FTBL[i%9],ESTR_FTBL[(i+1)%9]) for i in range(141)]
    for idx_r,(e1,e2) in enumerate(pairs):
        n+=1; preds=[]; ct=0
        for j,p in enumerate(partidos):
            sel=e1 if (j+idx_r)%2==0 else e2
            pred,conf=predecir_1x2_ftbl(sel,p)
            conf=max(40,min(95,conf+(idx_r%11)-5))
            preds.append({"partido":f"{p.get('local','')} vs {p.get('visitante','')}","pred":pred,"conf":conf})
            ct+=conf
        rutas.append({"ruta":n,"estrategia":f"{e1}+{e2}","preds":preds,"conf":round(ct/max(len(partidos),1))})
    return rutas

def gemini_hipotesis_ftbl(ruta_num,estrategia,preds,conf):
    gkey=get_secret("GEMINI_API_KEY")
    if not gkey: return f"Ruta {ruta_num} | {estrategia} | {conf}%"
    try:
        resumen="; ".join([f"{p.get('partido','')} {p.get('pred','')}({p.get('conf',0)}%)" for p in preds[:4]])
        prompt=f"Analista 1X2: hipótesis técnica concisa (1-2 frases) para ruta {ruta_num}, estrategia {estrategia}, confianza {conf}%. Partidos: {resumen}."
        url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gkey}"
        body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":80,"temperature":0.3}}
        r_ghf=req.post(url,json=body,timeout=10)
        if r_ghf.status_code==200: return r_ghf.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except: pass
    return f"Ruta {ruta_num} | {estrategia} | {conf}%"

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
                    with st.popover("⋮",use_container_width=True):
                        if st.button("✏️ Renombrar",key=f"ren_c_{c['id']}",use_container_width=True):
                            st.session_state["ren_chat"]=c["id"]; st.rerun()
                        if st.button("📁 Mover a proyecto",key=f"mv_{c['id']}",use_container_width=True):
                            st.session_state[f"mover_{c['id']}"]=True; st.rerun()
                        if st.button("🗑️ Eliminar chat",key=f"dc_{c['id']}",use_container_width=True):
                            supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                            supa("chats","DELETE",filtro=f"?id=eq.{c['id']}")
                            if st.session_state.chat_activo==c["id"]: st.session_state.chat_activo=None
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
            with st.popover("⋮"):
                if st.button("✏️ Renombrar proyecto",key=f"ren_proj_{pid}",use_container_width=True):
                    st.session_state["edit_proy"]=pid; st.rerun()
                if st.button("🗑️ Eliminar proyecto",key=f"del_p_{pid}",use_container_width=True):
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
                        with st.popover("⋮",use_container_width=True):
                            if st.button("🗑️ Eliminar chat",key=f"dsc_{s['id']}",use_container_width=True):
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
                    with st.popover("⋮",use_container_width=True):
                        if st.button("🗑️ Eliminar tarea",key=f"dt_{t['id']}",use_container_width=True): supa("agenda","DELETE",filtro=f"?id=eq.{t['id']}"); st.rerun()

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
                with st.popover("⋮"):
                    if st.button("✏️ Editar",key=f"ea_{a['id']}",use_container_width=True):
                        st.session_state["edit_aliado"]=a["id"]; st.rerun()
                    if st.button("🗑️ Eliminar aliado",key=f"da_{a['id']}",use_container_width=True):
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
                with st.popover("⋮",use_container_width=True):
                    if st.button("🗑️ Eliminar manual",key=f"dm_{m['id']}",use_container_width=True): supa("manuales","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()

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
        v_ne=campo_voz_html5("Necesidad del aliado","ven_nec",height=100)
    with c2:
        v_ti=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion"])
        v_pr=st.selectbox("Presupuesto",["No definido","< $1M","$1M-$5M","$5M-$15M","$15M-$50M","> $50M"])
        v_ur=st.selectbox("Urgencia",["Normal","Urgente","Proyecto futuro"])
        v_co=st.text_input("Contacto",value=aliado_data.get("contacto",""))
    if st.button("💼 Generar propuesta",type="primary",use_container_width=True):
        nec=st.session_state.get("ven_nec","")
        if nec.strip():
            with st.spinner("Generando propuesta..."):
                prompt=f"""Propuesta comercial empática para JandrexT.
Aliado: {v_ali} | NIT: {aliado_data.get('nit','')} | Tipo: {v_ti} | Línea: {v_li}
Necesidad: {nec} | Presupuesto: {v_pr} | Urgencia: {v_ur} | Fecha: {fecha_str()}
Incluir: saludo, comprensión del problema, solución JandrexT, equipos, garantías, próximos pasos.
Apasionados por el buen servicio."""
                prop=ia_generar(prompt)
            st.markdown(f"### 💼 Propuesta — {v_ali}")
            st.markdown(prop)
            pdf=generar_pdf_html(f"Propuesta — {v_ali}",prop)
            st.download_button("📥 Descargar",data=pdf.encode("utf-8"),
                file_name=f"Propuesta_{ahora().strftime('%Y%m%d')}.html",mime="text/html")
        else: st.warning("⚠️ Describe la necesidad del aliado.")

# ══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="biblioteca" and tiene_modulo(u,"biblioteca"):
    st.markdown("## 📚 Biblioteca")
    tab1,tab2=st.tabs(["🔍 Consultas guardadas","📖 Guía de uso"])
    with tab1:
        buscar=campo_voz_html5("qué buscar","bib_bus",height=60,placeholder="Escribe o dicta qué buscar...")
        msgs=supa("mensajes_chat",filtro="?order=creado_en.desc") or []
        bval=st.session_state.get("bib_bus","")
        filtrados=[m for m in msgs if not bval or bval.lower() in m.get("pregunta","").lower() or bval.lower() in m.get("sintesis","").lower()]
        st.metric("Consultas",len(filtrados))
        proyectos_bib=supa("proyectos",filtro="?order=nombre.asc") or []
        proy_bib_nombres=["Sin proyecto"]+[p["nombre"] for p in proyectos_bib]
        for m in filtrados:
            with st.expander(f"📌 {m.get('pregunta','')[:60]}... | {m.get('creado_en','')[:10]}"):
                st.markdown(m.get("sintesis",""))
                st.code(m.get("sintesis",""),language=None)
                cb1,cb2=st.columns([3,1])
                with cb1:
                    proy_dest=st.selectbox("📁 Mover a proyecto",proy_bib_nombres,key=f"pbib_{m['id']}")
                with cb2:
                    if st.button("📁 Mover",key=f"mbib_{m['id']}",use_container_width=True):
                        pid_bib=next((p["id"] for p in proyectos_bib if p["nombre"]==proy_dest),None)
                        if pid_bib:
                            nuevo_chat=supa("chats","POST",{"titulo":m.get("pregunta","")[:50],
                                "proyecto_id":pid_bib,"usuario_id":u["id"]})
                            if nuevo_chat and isinstance(nuevo_chat,list):
                                supa("mensajes_chat","PATCH",{"chat_id":nuevo_chat[0]["id"]},f"?id=eq.{m['id']}")
                                st.success(f"✅ Movido a {proy_dest}"); st.rerun()
                with st.popover("⋮",use_container_width=True):
                    if st.button("🗑️ Eliminar consulta",key=f"db_{m['id']}",use_container_width=True): supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
    with tab2:
        mods_por_rol={"admin":["Chats","Proyectos","Agenda","Asistencia","Documentos","Manuales","Ventas","Aliados","Liquidaciones","Especialistas","Configuración"],
                      "tecnico":["Mi Agenda","Mi Asistencia","Consultas"],"cliente":["Mis Solicitudes","Mis Manuales"]}
        mod=st.selectbox("¿Sobre qué módulo necesitas ayuda?",mods_por_rol.get(rol,["General"]))
        if st.button("📖 Ver guía",use_container_width=True):
            with st.spinner("Generando guía..."):
                guia=ia_generar(f"Crea una guía paso a paso para usar '{mod}' en la plataforma JandrexT. Usuario: {rol_label}. Lenguaje simple y empático. Máximo 400 palabras.")
            st.markdown(f"### 📖 Guía: {mod}")
            st.markdown(guia)

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="liquidaciones" and tiene_modulo(u,"liquidaciones"):
    st.markdown("## 📊 Liquidaciones")
    esp_list=supa("usuarios",filtro="?rol=in.(tecnico,vendedor)&activo=eq.true") or []
    nombres_esp=[x["nombre"] for x in esp_list]
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
        st.markdown(f"**Bruto:** ${bruto:,.0f} | **Deducciones:** ${dedu:,.0f}")
        st.markdown(f"### 💰 Total: ${neto:,.0f} COP")
        if st.button("💾 Generar y enviar",type="primary",use_container_width=True):
            cd=next((x for x in esp_list if x["nombre"]==l_col),None)
            if cd:
                supa("liquidaciones","POST",{"colaborador_id":cd["id"],
                    "periodo_inicio":str(l_ini),"periodo_fin":str(l_fin),
                    "dias_trabajados":l_dia,"salario_base":l_sal,"tipo_salario":l_tip,
                    "deducciones":[{"concepto":"Préstamo","valor":d_pre},{"concepto":"Otras","valor":d_otr}],
                    "total":neto})
                telegram(f"💰 <b>Liquidación JandrexT</b>\n👤 {l_col}\n📅 {l_ini} al {l_fin}\n📆 Días: {l_dia}\n✅ Total: ${neto:,.0f} COP")
                st.success("✅ Generada y notificada"); st.rerun()
    with col_l:
        st.markdown("### 📋 Historial")
        esp_sel=st.selectbox("Filtrar",["Todos"]+nombres_esp)
        liqs=supa("liquidaciones",filtro="?order=creado_en.desc") or []
        if esp_sel!="Todos":
            cid=next((x["id"] for x in esp_list if x["nombre"]==esp_sel),None)
            if cid: liqs=[l for l in liqs if l.get("colaborador_id")==cid]
        total=sum(l.get("total",0) for l in liqs)
        st.metric(f"Total — {esp_sel}",f"${total:,.0f}")
        for liq in liqs:
            cn=next((x["nombre"] for x in esp_list if x["id"]==liq.get("colaborador_id")),"Desconocido")
            with st.expander(f"💰 {cn} · {liq.get('periodo_inicio','')} → {liq.get('periodo_fin','')}"):
                st.markdown(f"**Días:** {liq.get('dias_trabajados',0)} | **Total:** ${liq.get('total',0):,.0f}")
                with st.popover("⋮",use_container_width=True):
                    if st.button("🗑️ Eliminar liquidación",key=f"dl_{liq['id']}",use_container_width=True): supa("liquidaciones","DELETE",filtro=f"?id=eq.{liq['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SOLICITUDES (Aliados)
# ══════════════════════════════════════════════════════════════════════════════
elif sec in ["requerimientos","mis_manuales"]:
    st.markdown("## 🤝 Mis Solicitudes")
    col_f,col_l=st.columns([1,2])
    with col_f:
        st.markdown("### ➕ Nueva solicitud")
        r_ti=campo_voz_html5("el asunto","req_tit",height=70)
        r_de=campo_voz_html5("la descripción","req_desc",height=100)
        r_pr=st.selectbox("Urgencia",["normal","urgente","puede_esperar"])
        if st.button("📤 Enviar solicitud",type="primary",use_container_width=True):
            tit=st.session_state.get("req_tit","")
            if tit.strip():
                supa("requerimientos","POST",{"titulo":tit,"descripcion":st.session_state.get("req_desc",""),"prioridad":r_pr})
                telegram(f"🔔 <b>Nueva solicitud</b>\n📋 {tit}\n⚡ {r_pr}")
                st.success("✅ Solicitud enviada."); st.balloons()
                st.session_state["req_tit"]=""; st.session_state["req_desc"]=""; st.rerun()
            else: st.warning("⚠️ El asunto es obligatorio")
    with col_l:
        st.markdown("### 📋 Solicitudes")
        reqs=supa("requerimientos",filtro="?order=creado_en.desc") or []
        for r in reqs:
            ico="✅" if r["estado"]=="resuelto" else "🔄" if r["estado"]=="en_proceso" else "🆕"
            with st.expander(f"{ico} {r['titulo']} · {r.get('estado','')}"):
                st.markdown(f"**Descripción:** {r.get('descripcion','')}")
                st.markdown(f"**Urgencia:** {r.get('prioridad','')} | **Fecha:** {r.get('creado_en','')[:10]}")
                if rol=="admin":
                    ne=st.selectbox("Estado",["nuevo","en_proceso","resuelto"],
                        index=["nuevo","en_proceso","resuelto"].index(r.get("estado","nuevo")),key=f"re_{r['id']}")
                    if st.button("💾 Actualizar",key=f"ru_{r['id']}"): supa("requerimientos","PATCH",{"estado":ne},f"?id=eq.{r['id']}"); st.rerun()
                with st.popover("⋮",use_container_width=True):
                    if st.button("🗑️ Eliminar solicitud",key=f"dr_{r['id']}",use_container_width=True): supa("requerimientos","DELETE",filtro=f"?id=eq.{r['id']}"); st.rerun()

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
        u_cel=st.text_input("Celular *")
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
                np=st.text_input("Nueva contraseña",type="password",key=f"pw_{usr['id']}")
                ca,cb=st.columns(2)
                with ca:
                    if st.button("🔑 Cambiar",key=f"cp_{usr['id']}"):
                        if np: supa("usuarios","PATCH",{"password_hash":hash_pwd(np)},f"?id=eq.{usr['id']}"); st.success("✅")
                with cb:
                    bl="❌ Desactivar" if usr.get("activo") else "✅ Activar"
                    if st.button(bl,key=f"ac_{usr['id']}"): supa("usuarios","PATCH",{"activo":not usr.get("activo")},f"?id=eq.{usr['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="config" and rol=="admin":
    st.markdown("## ⚙️ Configuración")
    tab0,tab1,tab2,tab3,tab4=st.tabs(["🤖 IAs","📧 Correo","🤖 Telegram","🧪 Testers","📊 Sistema"])
    with tab0:
        st.markdown("### 🤖 Gestión de Inteligencias Artificiales")
        col_ia1,col_ia2=st.columns(2)
        with col_ia1:
            st.markdown("**Activar / desactivar fuentes**")
            nuevo_g=st.toggle("🔵 Gemini 2.0 Flash",value=st.session_state.get("ia_usar_g",True),key="tog_g")
            nuevo_r=st.toggle("🟠 Groq / LLaMA 3.3",value=st.session_state.get("ia_usar_r",True),key="tog_r")
            nuevo_m=st.toggle("🟡 Mistral AI",value=st.session_state.get("ia_usar_m",False),key="tog_m")
            nuevo_o=st.toggle("🔷 OpenRouter",value=st.session_state.get("ia_usar_o",False),key="tog_o")
            nuevo_v=st.toggle("🟣 Venice AI",value=st.session_state.get("ia_usar_v",False),key="tog_v")
            if st.button("💾 Guardar configuración IAs",type="primary"):
                st.session_state.ia_usar_g=nuevo_g; st.session_state.ia_usar_r=nuevo_r
                st.session_state.ia_usar_v=nuevo_v; st.session_state.ia_usar_m=nuevo_m
                st.session_state.ia_usar_o=nuevo_o
                vals=json.dumps({"usar_g":nuevo_g,"usar_r":nuevo_r,"usar_v":nuevo_v,
                                 "usar_m":nuevo_m,"usar_o":nuevo_o,"debug":False})
                try:
                    ex=supa("configuracion_ia",filtro="?clave=eq.ia_config")
                    if ex and isinstance(ex,list) and ex:
                        supa("configuracion_ia","PATCH",{"valor":vals},"?clave=eq.ia_config")
                    else:
                        supa("configuracion_ia","POST",{"clave":"ia_config","valor":vals})
                    st.session_state.ia_config_cargada=False
                    st.success("✅ Configuración guardada permanentemente")
                except: st.success("✅ Configuración guardada en sesión")
        with col_ia2:
            st.markdown("**Verificar conexión**")
            if st.button("🔍 Probar Gemini 2.0"):
                with st.spinner("Verificando..."):
                    res=gemini_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Gemini OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ Gemini: {res['respuesta'][:80]}")
            if st.button("🔍 Probar Groq"):
                with st.spinner("Verificando..."):
                    res=groq_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Groq OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ Groq: {res['respuesta'][:80]}")
            if st.button("🔍 Probar Mistral"):
                with st.spinner("Verificando..."):
                    res=mistral_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Mistral OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ Mistral: {res['respuesta'][:80]}")
            if st.button("🔍 Probar OpenRouter"):
                with st.spinner("Verificando..."):
                    res=openrouter_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ OpenRouter OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ OpenRouter: {res['respuesta'][:80]}")
    with tab1:
        st.markdown("### 📧 Correo electrónico")
        gu=get_secret("GMAIL_USER") or "No configurado"
        st.info(f"**Cuenta activa:** {gu}")
        et=st.text_input("Enviar prueba a:")
        if st.button("📧 Enviar prueba"):
            if et:
                ok=enviar_email(et,"JandrexT — Prueba","<h2>✅ Correo funcionando correctamente.</h2>")
                if ok: st.success("✅ Correo enviado")
            else: st.warning("Ingresa un correo de destino")
    with tab2:
        st.markdown("### 🤖 Telegram")
        tg_chat=get_secret("TELEGRAM_CHAT_ID_ADMIN") or "No configurado"
        st.info(f"**Bot:** @JandrexTAsistencia_bot | **Chat ID:** {tg_chat}")
        if st.button("📱 Enviar mensaje de prueba",type="primary"):
            resultado=telegram(f"✅ <b>Prueba JandrexT v16</b>\nPlataforma funcionando correctamente.\n{fecha_str()}")
            ok = resultado[0] if isinstance(resultado, tuple) else resultado
            msg_err = resultado[1] if isinstance(resultado, tuple) else ""
            if ok: st.success("✅ Mensaje enviado correctamente")
            else: st.error(f"❌ Error: {msg_err}")
    with tab3:
        st.markdown("### 🧪 Limpieza de datos de prueba")
        st.warning("⚠️ Elimina TODOS los datos generados por usuarios testers.")
        testers_emails=["especialista@test.jandrext.com","aliado@test.jandrext.com"]
        tester_ids=[]
        for em in testers_emails:
            res=supa("usuarios",filtro=f"?email=eq.{em}")
            if res and isinstance(res,list) and res: tester_ids.append(res[0]["id"])
        st.info(f"Testers encontrados: {len(tester_ids)} usuarios")
        if tester_ids:
            if st.button("🗑️ Limpiar todos los datos de prueba",type="primary"):
                count=0
                for tid in tester_ids:
                    supa("asistencia","DELETE",filtro=f"?colaborador_id=eq.{tid}")
                    chats_t=supa("chats",filtro=f"?usuario_id=eq.{tid}") or []
                    for c in chats_t:
                        supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                        supa("chats","DELETE",filtro=f"?id=eq.{c['id']}")
                        count+=1
                    supa("agenda","DELETE",filtro=f"?creado_por=eq.{tid}")
                    supa("manuales","DELETE",filtro=f"?creado_por=eq.{tid}")
                st.success(f"✅ Datos eliminados: {count} chats limpiados")
                st.rerun()
    with tab4:
        st.markdown("### 📊 Estado del sistema")
        c1,c2,c3=st.columns(3)
        total_u=len(supa("usuarios",filtro="?activo=eq.true") or [])
        total_p=len(supa("proyectos") or [])
        total_d=len(supa("documentos") or [])
        c1.metric("Usuarios activos",total_u)
        c2.metric("Proyectos",total_p)
        c3.metric("Documentos",total_d)
        total_a=len(supa("clientes") or [])
        total_t=len(supa("agenda",filtro="?estado=eq.pendiente") or [])
        total_m=len(supa("manuales") or [])
        c1.metric("Aliados",total_a)
        c2.metric("Tareas pendientes",total_t)
        c3.metric("Manuales",total_m)
        st.caption(f"Última actualización: {fecha_str()} | Plataforma v16.0 | JandrexT Soluciones Integrales")

# ══════════════════════════════════════════════════════════════════════════════
# MESA IA — 5 AGENTES EN PARALELO (SOLO ADMIN)
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="mesa_ia" and rol=="admin":
    st.markdown("## 🧠 Mesa IA — Consejo de Inteligencias")
    st.markdown(f"> *{DIRECTIVA_FILOSOFICA}*")
    # ── Modo selector ──────────────────────────────────────────────────────────
    cm1_md,cm2_md=st.columns(2)
    with cm1_md:
        if st.button("🧠 Mesa IA General",type="primary" if st.session_state.get("mesa_modo","general")=="general" else "secondary",use_container_width=True,key="btn_gen_md"):
            st.session_state["mesa_modo"]="general"; st.rerun()
    with cm2_md:
        if st.button("⚽ Laboratorio Fútbol 1X2",type="primary" if st.session_state.get("mesa_modo","general")=="futbol" else "secondary",use_container_width=True,key="btn_ftbl_md"):
            st.session_state["mesa_modo"]="futbol"; st.rerun()
    st.markdown("---")
    if st.session_state.get("mesa_modo","general")=="futbol":
        st.markdown("### ⚽ Laboratorio Fútbol 1X2 — Multiverso 150")
        bloques_ftbl=supa("futbol_bloques",filtro=f"?user_id=eq.{u['id']}&order=created_at.desc") or []
        tab_c,tab_r,tab_a=st.tabs(["📥 Cargar Bloque","🧮 150 Rutas","📊 Resultados"])
        with tab_c:
            LIGAS_F={"PL":"Premier League","PD":"La Liga","BL1":"Bundesliga","SA":"Serie A","FL1":"Ligue 1","WC":"Mundial 2026"}
            cl1f,cl2f,cl3f=st.columns([2,1,1])
            liga_f=cl1f.selectbox("Liga",list(LIGAS_F.keys()),format_func=lambda x:LIGAS_F[x],key="ftbl_liga")
            jornada_f=cl2f.number_input("Jornada",1,38,1,key="ftbl_jornada")
            temp_f=cl3f.text_input("Temporada","2024",key="ftbl_temp")
            if st.button("📥 Cargar partidos (Football-Data.org)",type="primary",use_container_width=True,key="ftbl_load"):
                with st.spinner("Consultando Football-Data.org..."):
                    fkey=get_secret("FOOTBALL_API_KEY"); data_fd=None
                    if fkey:
                        try:
                            r_fd=req.get(f"https://api.football-data.org/v4/competitions/{liga_f}/matches",
                                params={"matchday":int(jornada_f),"season":temp_f},
                                headers={"X-Auth-Token":fkey},timeout=15)
                            if r_fd.status_code==200: data_fd=r_fd.json()
                        except: pass
                if data_fd and "matches" in data_fd:
                    matches_fd=data_fd["matches"][:20]; bid_new=str(uuid.uuid4())
                    supa("futbol_bloques","POST",{"id":bid_new,"user_id":u["id"],"liga":LIGAS_F[liga_f],"jornada":int(jornada_f),"temporada":temp_f,"status":"cargado"})
                    for m_fd in matches_fd:
                        supa("futbol_partidos","POST",{"bloque_id":bid_new,"local":m_fd["homeTeam"]["name"],"visitante":m_fd["awayTeam"]["name"],"fecha":m_fd.get("utcDate",""),"posicion_local":8,"posicion_visitante":8,"cuota_1":2.0,"cuota_x":3.5,"cuota_2":3.0,"forma_local":2,"forma_visitante":2})
                    st.session_state["ftbl_bloque_sel"]=bid_new
                    st.success(f"✅ {len(matches_fd)} partidos cargados — {LIGAS_F[liga_f]} J{jornada_f}"); st.rerun()
                else:
                    st.error("❌ No se pudo cargar. Verifica FOOTBALL_API_KEY en Secrets.")
            if bloques_ftbl:
                st.markdown("---"); st.caption("Bloques guardados")
                for b_ftbl in bloques_ftbl:
                    if not isinstance(b_ftbl, dict): continue
                    cb1_f,cb2_f=st.columns([4,1])
                    with cb1_f:
                        if st.button(f"⚽ {b_ftbl.get('liga','')} J{b_ftbl.get('jornada','')} ({b_ftbl.get('temporada','')})",key=f"bsel_{b_ftbl.get('id','')}",use_container_width=True):
                            st.session_state["ftbl_bloque_sel"]=b_ftbl["id"]; st.rerun()
                    with cb2_f:
                        with st.popover("⋮",use_container_width=True):
                            if st.button("🗑️ Eliminar",key=f"bdel_{b_ftbl.get('id','')}",use_container_width=True):
                                supa("futbol_rutas","DELETE",filtro=f"?bloque_id=eq.{b_ftbl.get('id','')}")
                                supa("futbol_partidos","DELETE",filtro=f"?bloque_id=eq.{b_ftbl.get('id','')}")
                                supa("futbol_bloques","DELETE",filtro=f"?id=eq.{b_ftbl.get('id','')}"); st.rerun()
        with tab_r:
            bid_r_f=st.session_state.get("ftbl_bloque_sel")
            if not bid_r_f: st.info("👈 Primero carga o selecciona un bloque.")
            else:
                parts_r_f=supa("futbol_partidos",filtro=f"?bloque_id=eq.{bid_r_f}") or []
                rutas_r_f=supa("futbol_rutas",filtro=f"?bloque_id=eq.{bid_r_f}&order=confidence_score.desc") or []
                if not rutas_r_f:
                    with st.expander("✏️ Ajustar cuotas y forma"):
                        for p_rf in parts_r_f:
                            st.caption(f"⚽ {p_rf.get('local','')} vs {p_rf.get('visitante','')}")
                            cpa,cpb,cpc,cpd,cpe=st.columns(5)
                            nv_c1=cpa.number_input("C1",0.01,20.0,float(p_rf.get("cuota_1",2.0)),0.01,key=f"c1_{p_rf['id']}")
                            nv_cx=cpb.number_input("CX",0.01,20.0,float(p_rf.get("cuota_x",3.5)),0.01,key=f"cx_{p_rf['id']}")
                            nv_c2=cpc.number_input("C2",0.01,20.0,float(p_rf.get("cuota_2",3.0)),0.01,key=f"c2_{p_rf['id']}")
                            nv_fl=cpd.number_input("FmL",0,5,int(p_rf.get("forma_local",2)),key=f"fl_{p_rf['id']}")
                            nv_fv=cpe.number_input("FmV",0,5,int(p_rf.get("forma_visitante",2)),key=f"fv_{p_rf['id']}")
                            supa("futbol_partidos","PATCH",{"cuota_1":nv_c1,"cuota_x":nv_cx,"cuota_2":nv_c2,"forma_local":nv_fl,"forma_visitante":nv_fv},filtro=f"?id=eq.{p_rf['id']}")
                    if st.button("🧮 Generar 150 Rutas + Hipótesis IA",type="primary",use_container_width=True,key="ftbl_gen"):
                        if parts_r_f:
                            with st.spinner("Calculando 150 rutas con 9 estrategias..."):
                                rgs_f=generar_150_rutas_ftbl(parts_r_f); ids_gen_f=[]
                                for rg_f in rgs_f:
                                    rid_f=str(uuid.uuid4())
                                    supa("futbol_rutas","POST",{"id":rid_f,"bloque_id":bid_r_f,"ruta_numero":rg_f["ruta"],"estrategia":rg_f["estrategia"],"predicciones_json":json.dumps(rg_f["preds"]),"confidence_score":rg_f["conf"],"hipotesis":f"Ruta {rg_f['ruta']} | {rg_f['estrategia']}"})
                                    ids_gen_f.append((rid_f,rg_f))
                            top_ids_f=sorted(ids_gen_f,key=lambda x:-x[1]["conf"])[:15]
                            with st.spinner("🤖 Gemini generando hipótesis top 15..."):
                                def _gen_hip_f(item_f):
                                    rid_hf,rg_hf=item_f
                                    hip_f=gemini_hipotesis_ftbl(rg_hf["ruta"],rg_hf["estrategia"],rg_hf["preds"],rg_hf["conf"])
                                    supa("futbol_rutas","PATCH",{"hipotesis":hip_f},filtro=f"?id=eq.{rid_hf}")
                                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as _ex_f:
                                    list(_ex_f.map(_gen_hip_f,top_ids_f))
                            st.success("✅ 150 rutas + hipótesis IA generadas"); st.rerun()
                else:
                    st.markdown(f"##### 🗺️ {len(rutas_r_f)} rutas — Top por confianza")
                    for rg_f in rutas_r_f[:30]:
                        pj_f=json.loads(rg_f.get("predicciones_json") or "[]")
                        cf_f=rg_f.get("confidence_score",50)
                        icon_rf="🟢" if cf_f>=70 else "🟡" if cf_f>=55 else "🔴"
                        ok_rf=rg_f.get("resultado_correcto")
                        est_rf=(" ✅" if ok_rf==True else " ❌" if ok_rf==False else "")
                        with st.expander(f"{icon_rf} Ruta {rg_f['ruta_numero']} | {rg_f['estrategia']} | {cf_f}%{est_rf}"):
                            if rg_f.get("hipotesis"): st.caption(f"💡 {rg_f['hipotesis']}")
                            pred_cols_rf=st.columns(max(len(pj_f),1))
                            for ci_f,pi_f in enumerate(pj_f[:len(pred_cols_rf)]):
                                with pred_cols_rf[ci_f]:
                                    pts_rf=pi_f.get("partido","?").split(" vs ")
                                    st.markdown(f"**{pts_rf[0][:8]}** vs {pts_rf[1][:8] if len(pts_rf)>1 else '?'}")
                                    pv_rf=pi_f.get("pred","?")
                                    ic2_f="🟢" if pv_rf=="1" else "🔵" if pv_rf=="X" else "🔴"
                                    st.markdown(f"**{ic2_f} {pv_rf}**")
        with tab_a:
            bid_a_f=st.session_state.get("ftbl_bloque_sel")
            if not bid_a_f: st.info("👈 Selecciona un bloque.")
            else:
                parts_a_f=supa("futbol_partidos",filtro=f"?bloque_id=eq.{bid_a_f}") or []
                rutas_a_f=supa("futbol_rutas",filtro=f"?bloque_id=eq.{bid_a_f}") or []
                rutas_con_res=[r for r in rutas_a_f if r.get("resultado_correcto") is not None]
                if rutas_con_res:
                    st.markdown("### 📊 Dashboard de Rendimiento")
                    total_r=len(rutas_a_f); corr_r=sum(1 for r in rutas_con_res if r.get("resultado_correcto"))
                    pct_r=round(corr_r/max(len(rutas_con_res),1)*100,1)
                    m1_f,m2_f,m3_f=st.columns(3)
                    m1_f.metric("Rutas totales",str(total_r))
                    m2_f.metric("Rutas correctas",str(corr_r),f"{pct_r}% acierto")
                    est_acc_f={}
                    for r_af in rutas_a_f:
                        ok_af2=r_af.get("resultado_correcto")
                        if ok_af2 is None: continue
                        e_af2=r_af.get("estrategia","?"); est_acc_f.setdefault(e_af2,[]).append(1 if ok_af2 else 0)
                    if est_acc_f:
                        best_e_f=max(est_acc_f,key=lambda k:sum(est_acc_f[k])/max(len(est_acc_f[k]),1))
                        best_pct_f=round(sum(est_acc_f[best_e_f])/max(len(est_acc_f[best_e_f]),1)*100,1)
                        m3_f.metric("Mejor estrategia",best_e_f,f"{best_pct_f}%")
                    st.markdown("#### 📈 Accuracy por Estrategia")
                    for ek_f,ev_f in sorted(est_acc_f.items(),key=lambda x:-sum(x[1])/max(len(x[1]),1)):
                        avg_ef=sum(ev_f)/len(ev_f); pct_ef=round(avg_ef*100,1)
                        ic_ef="🟢" if avg_ef>=0.6 else "🟡" if avg_ef>=0.45 else "🔴"
                        st.progress(avg_ef,text=f"{ic_ef} {ek_f} — {pct_ef}% ({len(ev_f)} rutas)")
                    st.markdown("---")
                with st.expander("📝 Registrar resultados reales",expanded=not bool(rutas_con_res)):
                    if parts_a_f:
                        res_map_f={}
                        cols_ra_f=st.columns(min(len(parts_a_f),4))
                        for idx_ra_f,pa_f in enumerate(parts_a_f):
                            with cols_ra_f[idx_ra_f%len(cols_ra_f)]:
                                st.caption(f"{pa_f.get('local','')[:10]} vs {pa_f.get('visitante','')[:10]}")
                                res_pre_f=pa_f.get("resultado_real","_") or "_"
                                ops_f=["_","1","X","2"]; idx_op_f=ops_f.index(res_pre_f) if res_pre_f in ops_f else 0
                                r_sel_f=st.selectbox("",ops_f,index=idx_op_f,key=f"res_{pa_f['id']}",label_visibility="collapsed")
                                if r_sel_f!="_": res_map_f[pa_f["id"]]=r_sel_f
                        if st.button("💾 Guardar y calcular aciertos",type="primary",use_container_width=True,key="ftbl_res"):
                            for pid_rf,res_rf in res_map_f.items():
                                supa("futbol_partidos","PATCH",{"resultado_real":res_rf},filtro=f"?id=eq.{pid_rf}")
                            parts_fresh_f=supa("futbol_partidos",filtro=f"?bloque_id=eq.{bid_a_f}") or []
                            real_m_f={p_f["id"]:p_f.get("resultado_real","_") for p_f in parts_fresh_f}
                            for ruta_af in rutas_a_f:
                                pj_af=json.loads(ruta_af.get("predicciones_json") or "[]")
                                aci_af=sum(1 for p_f,pr_f in zip(parts_fresh_f,pj_af) if real_m_f.get(p_f["id"])==pr_f.get("pred"))
                                ok_af=aci_af/max(len(pj_af),1)>=0.6
                                supa("futbol_rutas","PATCH",{"resultado_correcto":ok_af},filtro=f"?id=eq.{ruta_af['id']}")
                            st.success("✅ Resultados calculados"); st.rerun()
                    else: st.info("No hay partidos.")
        st.stop()
    proyectos_ia=supa("mesa_ia_projects",filtro=f"?user_id=eq.{u['id']}&order=created_at.asc")
    col_proj,col_main=st.columns([1,3])
    with col_proj:
        st.markdown("#### 📁 Proyectos")
        if st.button("🆕 Nuevo proyecto",use_container_width=True,key="mesa_btn_nuevo"):
            st.session_state["mesa_new_proj"]=not st.session_state.get("mesa_new_proj",False)
        if st.session_state.get("mesa_new_proj",False):
            np_nom=st.text_input("Nombre del proyecto",key="mesa_np_nom")
            np_desc=st.text_area("Descripción (opcional)",key="mesa_np_desc",height=60)
            if st.button("Crear ✅",key="mesa_crear_p"):
                if np_nom.strip():
                    supa("mesa_ia_projects","POST",{"user_id":u["id"],"nombre":np_nom.strip(),"descripcion":np_desc})
                    st.session_state["mesa_new_proj"]=False
                    st.rerun()
        st.markdown("---")
        p_sel=st.session_state.get("mesa_proj_sel",None)
        for p in proyectos_ia:
            es_activo=p_sel==p["id"]
            cp1_mi,cp2_mi=st.columns([4,1])
            with cp1_mi:
                if st.button(f"{'▶ ' if es_activo else ''}{p['nombre']}",key=f"psel_{p['id']}",use_container_width=True):
                    st.session_state["mesa_proj_sel"]=p["id"]
                    st.session_state["mesa_proj_nombre"]=p["nombre"]
                    st.session_state.pop("mesa_resultados",None)
                    st.rerun()
            with cp2_mi:
                with st.popover("⋮"):
                    if st.button("✏️ Renombrar",key=f"ren_p_{p['id']}",use_container_width=True):
                        st.session_state["mesa_ren_proj"]=p["id"]; st.rerun()
                    if st.button("🗑️ Eliminar proyecto",key=f"del_p_{p['id']}",use_container_width=True):
                        supa("mesa_ia_sessions","DELETE",filtro=f"?project_id=eq.{p['id']}")
                        supa("mesa_ia_projects","DELETE",filtro=f"?id=eq.{p['id']}")
                        if st.session_state.get("mesa_proj_sel")==p["id"]: st.session_state.pop("mesa_proj_sel",None)
                        st.rerun()
        if not proyectos_ia:
            st.info("Sin proyectos aún. Crea uno arriba.")
    with col_main:
        proj_id=st.session_state.get("mesa_proj_sel",None)
        proj_nombre=st.session_state.get("mesa_proj_nombre","")
        if not proj_id:
            st.info("👈 Selecciona o crea un proyecto para comenzar.")
        else:
            st.markdown(f"### 📂 {proj_nombre}")
            sesiones=supa("mesa_ia_sessions",filtro=f"?project_id=eq.{proj_id}&order=created_at.desc&limit=10")
            if sesiones:
                st.markdown("#### 📋 Historial del proyecto")
                for s in sesiones:
                    conf_icon={"Alto":"🟢","Medio":"🟡","Bajo":"🔴"}.get(s.get("confidence_level",""),"⚪")
                    with st.expander(f"{conf_icon} {(s.get('user_prompt') or '')[:50]}...",expanded=False):
                        st.caption(s.get("created_at","")[:16])
                        st.markdown(f"**Confianza:** {s.get('confidence_level','')}")
                        st.markdown(s.get("consensus_response","")[:500])
                        with st.popover("⋮ Opciones"):
                            if st.button("🗑️ Eliminar sesión",key=f"dses_{s['id']}",use_container_width=True):
                                supa("mesa_ia_sessions","DELETE",filtro=f"?id=eq.{s['id']}"); st.rerun()
                st.markdown("---")
            if "mesa_resultados" in st.session_state:
                confianza=st.session_state.get("mesa_confianza","Medio")
                col_c={"Alto":"🟢","Medio":"🟡","Bajo":"🔴"}.get(confianza,"⚪")
                st.markdown(f"**Pregunta:** {st.session_state.get('mesa_prompt_guardado','')}")
                st.markdown(f"### {col_c} Confianza: **{confianza}**")
                st.markdown("#### 🧠 Síntesis de Claude")
                st.info(st.session_state.get("mesa_sintesis",""))
                st.markdown("#### 🗣️ Respuestas individuales")
                resultados_s=st.session_state["mesa_resultados"]
                cols_r=st.columns(len(resultados_s))
                for i,res in enumerate(resultados_s):
                    with cols_r[i]:
                        status_ok="✅" if res["ok"] else "❌"
                        st.markdown(f"**{res['icono']} {res['ia']}** {status_ok}")
                        st.caption(f"Rol: {res.get('rol','')} | {res.get('tiempo',0):.1f}s")
                        if res["ok"]:
                            st.markdown(f'<div style="background:#1a1a2e;padding:10px;border-radius:8px;font-size:0.85em">{res["respuesta"][:400]}</div>',unsafe_allow_html=True)
                        else:
                            st.error(res["respuesta"])
                st.markdown("---")
            st.markdown("#### 🆕 Nueva consulta")
            campo_voz_html5("Tu consulta a la Mesa IA","mesa_prompt",height=100,placeholder="Escribe la pregunta o desafío para los 5 agentes...")
            prompt_mesa=st.session_state.get("mesa_prompt","")
            if st.button("🧠 Consultar Mesa IA",type="primary",use_container_width=True,key="mesa_consultar"):
                if prompt_mesa.strip():
                    fns_mesa=[chatgpt_fn,claude_fn,gemini_mesa_fn,groq_mesa_fn,mistral_mesa_fn]
                    with st.spinner("🔄 Consultando los 5 agentes en paralelo..."):
                        resultados=[]
                        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
                            futs=[ex.submit(f,prompt_mesa) for f in fns_mesa]
                            for fut in concurrent.futures.as_completed(futs,timeout=35):
                                try: resultados.append(fut.result())
                                except Exception as e: resultados.append({"ia":"Agente","icono":"🔴","rol":"desconocido","respuesta":f"Timeout/Error: {str(e)[:100]}","tiempo":0,"ok":False})
                    st.session_state["mesa_resultados"]=resultados
                    st.session_state["mesa_prompt_guardado"]=prompt_mesa
                    resp_map={r["ia"]:r["respuesta"] for r in resultados}
                    sid=str(uuid.uuid4())
                    supa("mesa_ia_sessions","POST",{
                        "id":sid,"project_id":proj_id,"user_id":u["id"],
                        "user_prompt":prompt_mesa,
                        "gpt_response":resp_map.get("ChatGPT",""),
                        "claude_response":resp_map.get("Claude",""),
                        "gemini_response":resp_map.get("Gemini",""),
                        "groq_response":resp_map.get("Groq",""),
                        "mistral_response":resp_map.get("Mistral",""),
                        "status":"processing_synthesis","mode":"general"})
                    with st.spinner("🧠 Claude sintetizando consenso..."):
                        try: sintesis,confianza=mesa_ia_sintesis_fn(prompt_mesa,resultados)
                        except Exception as e: sintesis=f"Error en síntesis: {str(e)[:200]}";confianza="Bajo"
                    st.session_state["mesa_sintesis"]=sintesis
                    st.session_state["mesa_confianza"]=confianza
                    supa("mesa_ia_sessions","PATCH",{
                        "consensus_response":sintesis,
                        "confidence_level":confianza,
                        "status":"completed"},
                        filtro=f"?id=eq.{sid}")
                    st.session_state["mesa_prompt"]=""
                    st.rerun()
# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="footer-inst">
    <span class="footer-acc">JandrexT</span> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: <span class="footer-acc">Andrés Tapiero</span> &nbsp;·&nbsp;
    Plataforma v16.0 &nbsp;·&nbsp; 🔒 Sistema Interno<br>
    <span class="footer-lema-j">Apasionados por el buen servicio</span>
</div>""", unsafe_allow_html=True)
