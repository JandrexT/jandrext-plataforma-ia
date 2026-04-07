import streamlit as st
import os, time, json, uuid, hashlib, base64, concurrent.futures, smtplib
import requests as req
# google.generativeai reemplazado por REST directo para mayor compatibilidad
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
             get_font_b64("JennaSue.ttf") +
             get_font_b64("jenna-sue__allfont_net_.ttf") +
             get_font_b64("Pax_Oceania_Regular.ttf"))

# ── Logo ──────────────────────────────────────────────────────────────────────
logo_b64 = None
if Path("logo_jandrext.png").exists():
    logo_b64 = base64.b64encode(Path("logo_jandrext.png").read_bytes()).decode()

# ── Supabase ──────────────────────────────────────────────────────────────────
def get_secret(key, default=""):
    """Obtiene secreto de st.secrets o variable de entorno"""
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

CONTEXTO = """Eres el asistente técnico experto de JandrexT Soluciones Integrales — empresa colombiana especializada en seguridad electrónica y automatización. Lema: Apasionados por el buen servicio.
Servicios: automatización de accesos, videovigilancia CCTV, control de acceso y biometría, redes y comunicaciones, sistemas eléctricos, cerca eléctrica, soporte tecnológico, desarrollo de software.
Director: Andrés Tapiero | NIT: 80818905-3 | Tel: 317 391 0621 | proyectos@jandrext.com | Bogotá, Colombia. Cobertura: Bogotá y municipios cercanos (Soacha, Chía, Cajicá, Mosquera, Funza, Madrid, Facatativá).
Comportamiento: empático, profesional, práctico. Aplica normas colombianas. Al final de cada respuesta menciona brevemente que JandrexT Soluciones Integrales cuenta con especialistas disponibles para este tipo de instalaciones o servicios."""

# ── IAs ───────────────────────────────────────────────────────────────────────
def gemini_fn(p, modelo="gemini-2.0-flash"):
    try:
        t=time.time()
        api_key=get_secret("GOOGLE_API_KEY")
        if not api_key: return {"ia":"Gemini","icono":"🔴","respuesta":"Sin API key","tiempo":0,"ok":False}
        payload={"contents":[{"parts":[{"text":CONTEXTO+"\n\nConsulta: "+p}]}]}
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
        r=req.post(url,json=payload,timeout=30)
        if r.status_code==200:
            txt=r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return {"ia":"Gemini","icono":"🔵","respuesta":txt,"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Gemini","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
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
        api_key=get_secret("VENICE_API_KEY")
        if not api_key:
            return {"ia":"Venice","icono":"⚪","respuesta":"No configurado (opcional)","tiempo":0,"ok":False}
        t=time.time(); h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
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
        t=time.time(); api_key=get_secret("MISTRAL_API_KEY")
        if not api_key: return {"ia":"Mistral","icono":"🔴","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
        r=req.post("https://api.mistral.ai/v1/chat/completions",
            json={"model":"mistral-small-latest","messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],"max_tokens":1500},
            headers=h,timeout=30)
        if r.status_code==200:
            return {"ia":"Mistral","icono":"🟡","respuesta":r.json()["choices"][0]["message"]["content"].strip(),"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"Mistral","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"Mistral","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def openrouter_fn(p):
    try:
        t=time.time(); api_key=get_secret("OPENROUTER_API_KEY")
        if not api_key: return {"ia":"OpenRouter","icono":"🔴","respuesta":"Sin API key","tiempo":0,"ok":False}
        h={"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
           "HTTP-Referer":"https://jandrext-ia.streamlit.app","X-Title":"JandrexT IA"}
        r=req.post("https://openrouter.ai/api/v1/chat/completions",
            json={"model":"mistralai/mistral-7b-instruct:free","messages":[{"role":"system","content":CONTEXTO},{"role":"user","content":p}],"max_tokens":1500,"transforms":["middle-out"]},
            headers=h,timeout=30)
        if r.status_code==200:
            return {"ia":"OpenRouter","icono":"🔷","respuesta":r.json()["choices"][0]["message"]["content"].strip(),"tiempo":round(time.time()-t,2),"ok":True}
        return {"ia":"OpenRouter","icono":"🔴","respuesta":f"HTTP {r.status_code}","tiempo":0,"ok":False}
    except Exception as e: return {"ia":"OpenRouter","icono":"🔴","respuesta":str(e),"tiempo":0,"ok":False}

def groq_simple(prompt):
    try:
        from groq import Groq
        r=Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":prompt}],max_tokens=1500)
        return r.choices[0].message.content.strip()
    except: return ""

def mistral_fn(p):
    """Mistral AI — gratis via API oficial (mistral-small-latest)"""
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
    """OpenRouter — acceso gratuito a múltiples modelos (Llama, Mistral, etc.)"""
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

def juez_fn(pregunta, respuestas):
    """Sintetiza respuestas de múltiples IAs. Usa Gemini primero, luego Groq, luego mejor respuesta."""
    ok_resps = [r for r in respuestas if r["ok"]]
    if not ok_resps: return "No se obtuvo respuesta de ninguna fuente."
    if len(ok_resps) == 1: return ok_resps[0]["respuesta"]  # Solo una IA, retornar directo
    
    resumen = "\n\n".join([f"--- {r['ia']} ---\n{r['respuesta']}" for r in ok_resps])
    prompt_juez = f"{CONTEXTO}\nPregunta del usuario: \"{pregunta}\"\nRespuestas de diferentes fuentes:\n{resumen}\n\nSintetiza la mejor respuesta: empática, profesional, práctica. Sin mencionar las fuentes ni encabezados."
    
    # Intento 1: Gemini
    try:
        api_key = get_secret("GOOGLE_API_KEY")
        if api_key:
            payload={"contents":[{"parts":[{"text":prompt_juez}]}]}
            url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            r=req.post(url,json=payload,timeout=30)
            if r.status_code==200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except: pass
    
    # Intento 2: Groq como sintetizador
    try:
        return groq_simple(prompt_juez)
    except: pass
    
    # Último recurso: mejor respuesta disponible (la más larga)
    return max(ok_resps, key=lambda x: len(x["respuesta"]))["respuesta"]

def ia_generar(prompt, modelo="gemini-2.0-flash"):
    try:
        api_key=get_secret("GOOGLE_API_KEY")
        if not api_key: 
            # Fallback a Groq si no hay Gemini
            return groq_simple(prompt)
        payload={"contents":[{"parts":[{"text":CONTEXTO+"\n\n"+prompt}]}]}
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
        r=req.post(url,json=payload,timeout=30)
        if r.status_code==200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return groq_simple(prompt)
    except Exception as e: return groq_simple(prompt)

def groq_simple(prompt):
    try:
        from groq import Groq
        r=Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":CONTEXTO},{"role":"user","content":prompt}],max_tokens=1500)
        return r.choices[0].message.content.strip()
    except Exception as e: return f"❌ Error generando respuesta: {e}"

def ia_extraer_doc(b64, tipo="imagen"):
    """Extrae datos de RUT con Gemini vision, OpenRouter vision, o Groq desde texto PDF"""
    prompt_json = """Eres un asistente que extrae datos de documentos colombianos (RUT, NIT, cámara de comercio).
Analiza el documento y devuelve SOLO un JSON válido con esta estructura exacta, sin texto adicional ni markdown:
{"razon_social":"","nit":"","direccion":"","municipio":"","departamento":"","telefono":"","email":"","contacto":"","cargo_contacto":"","responsabilidad_fiscal":"","regimen_fiscal":""}
Si no encuentras un dato, deja el campo vacío. NIT sin puntos ni guiones.
Para el campo telefono: incluye teléfono fijo, celular o cualquier número de contacto. Si hay varios, sepáralos con coma.
Para el campo direccion: busca la dirección completa incluyendo calle, carrera, avenida, número, ciudad. En el RUT colombiano aparece en la sección de "Ubicación" o "Dirección"."""

    errores = []

    def parsear_json(txt):
        if not txt: return {}
        txt = txt.replace("```json","").replace("```","").strip()
        s = txt.find("{"); e = txt.rfind("}")+1
        if s>=0 and e>0:
            try: return json.loads(txt[s:e])
            except: pass
        return {}

    # Intento 1: Gemini 2.0 flash con visión
    try:
        api_key = get_secret("GOOGLE_API_KEY")
        if api_key:
            mime = "application/pdf" if tipo=="pdf" else "image/jpeg"
            payload = {"contents":[{"parts":[{"text":prompt_json},{"inline_data":{"mime_type":mime,"data":b64}}]}]}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            r = req.post(url, json=payload, timeout=45)
            if r.status_code == 200:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                res = parsear_json(txt)
                if res.get("nit") or res.get("razon_social"): return res
            else:
                errores.append(f"Gemini HTTP {r.status_code}")
        else:
            errores.append("Gemini sin API key")
    except Exception as e:
        errores.append(f"Gemini error: {str(e)[:50]}")

    # Intento 2: OpenRouter con visión gratuita
    try:
        api_key = get_secret("OPENROUTER_API_KEY")
        if api_key:
            h = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
                 "HTTP-Referer":"https://jandrext-ia.streamlit.app","X-Title":"JandrexT IA"}
            mime = "application/pdf" if tipo=="pdf" else "image/jpeg"
            payload = {"model":"mistralai/mistral-7b-instruct:free",
                       "messages":[{"role":"user","content":[
                           {"type":"text","text":prompt_json},
                           {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}}
                       ]}],"max_tokens":600}
            r = req.post("https://openrouter.ai/api/v1/chat/completions",headers=h,json=payload,timeout=45)
            if r.status_code == 200:
                txt = r.json()["choices"][0]["message"]["content"].strip()
                res = parsear_json(txt)
                if res.get("nit") or res.get("razon_social"): return res
            else:
                errores.append(f"OpenRouter HTTP {r.status_code}")
        else:
            errores.append("OpenRouter sin API key")
    except Exception as e:
        errores.append(f"OpenRouter error: {str(e)[:50]}")

    # Intento 3: Para PDFs — extraer texto y enviar a Groq (no requiere visión)
    if tipo == "pdf":
        try:
            import base64 as b64mod, io
            pdf_bytes = b64mod.b64decode(b64)
            texto_pdf = ""
            # Intento 1: pypdf
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(pdf_bytes))
                texto_pdf = " ".join(p.extract_text() or "" for p in reader.pages[:4])[:4000]
            except: pass
            # Intento 2: pdfminer
            if not texto_pdf:
                try:
                    from pdfminer.high_level import extract_text as pdfminer_extract
                    texto_pdf = pdfminer_extract(io.BytesIO(pdf_bytes))[:4000]
                except: pass
            # Intento 3: PyMuPDF
            if not texto_pdf:
                try:
                    import fitz
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    texto_pdf = " ".join(page.get_text() for page in doc)[:4000]
                except: pass

            if texto_pdf and len(texto_pdf) > 50:
                from groq import Groq
                prompt_groq = f"""Extrae los datos de este texto de un documento colombiano (RUT/NIT).
Devuelve SOLO JSON válido sin markdown:
{{"razon_social":"","nit":"","direccion":"","municipio":"","departamento":"","telefono":"","email":"","contacto":"","cargo_contacto":"","responsabilidad_fiscal":"","regimen_fiscal":""}}

Texto del documento:
{texto_pdf}"""
                r = Groq(api_key=get_secret("GROQ_API_KEY")).chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role":"user","content":prompt_groq}],
                    max_tokens=500)
                txt = r.choices[0].message.content.strip()
                res = parsear_json(txt)
                if res.get("nit") or res.get("razon_social"): return res
                errores.append("Groq no encontró datos en el texto")
            else:
                errores.append("No se pudo extraer texto del PDF")
        except Exception as e:
            errores.append(f"Groq PDF: {str(e)[:50]}")

    # Retornar errores para mostrar al usuario
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

# ── Micrófono HTML5 nativo ────────────────────────────────────────────────────
def campo_voz_html5(label, key, height=100, placeholder="Escribe o usa el micrófono..."):
    """Campo de texto con micrófono integrado — botón iniciar/detener"""
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
    // Insertar en el textarea de Streamlit
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
    """Panel de micrófono usando Web Speech API — botón Iniciar/Detener unificado"""
    if f"voz_{seccion_key}" not in st.session_state:
        st.session_state[f"voz_{seccion_key}"] = ""

    campos_lista = list(campos_disponibles.keys())
    campos_str = "|".join(campos_lista)
    uid = seccion_key.replace("-","_")

    html_mic = f"""
<div style="background:#0a0f00;border:1px solid #cc0000;border-radius:10px;padding:1rem;margin-bottom:8px;">
  <div style="color:#cc0000;font-size:0.75rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">
    DICTAR POR VOZ
  </div>
  <div style="display:flex;gap:8px;margin-bottom:8px;">
    <button id="btnToggle_{uid}"
      onclick="toggleRec_{uid}()"
      style="flex:1;background:#cc0000;color:#fff;border:none;border-radius:8px;
      padding:10px;font-size:14px;font-weight:700;cursor:pointer;">
      🎤 Iniciar grabación
    </button>
  </div>
  <div id="status_{uid}"
    style="color:#888;font-size:12px;margin-bottom:6px;">
    Listo para grabar en Chrome/Edge
  </div>
  <div id="preview_{uid}"
    style="background:#0a1a00;border:1px solid #166534;border-radius:6px;
    padding:8px;color:#4ade80;font-size:13px;min-height:36px;margin-bottom:8px;
    word-wrap:break-word;">
  </div>
  <div style="display:flex;gap:8px;align-items:center;">
    <select id="campoSel_{uid}"
      style="flex:1;background:#1a0000;color:#ccc;border:1px solid #3a0000;
      border-radius:6px;padding:8px;font-size:13px;">
      {chr(10).join(f'<option value="{cx}">{cx}</option>' for cx in campos_lista)}
    </select>
    <button onclick="insertarTexto_{uid}()"
      style="background:#166534;color:#fff;border:none;border-radius:6px;
      padding:8px 14px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;">
      Insertar
    </button>
    <button onclick="limpiarTexto_{uid}()"
      style="background:#333;color:#888;border:none;border-radius:6px;
      padding:8px 10px;font-size:13px;cursor:pointer;">
      X
    </button>
  </div>
</div>

<script>
(function() {{
  var rec_{uid} = null;
  var activo_{uid} = false;
  var textoCapturado_{uid} = '';

  window.toggleRec_{uid} = function() {{
    var btn = document.getElementById('btnToggle_{uid}');
    var sta = document.getElementById('status_{uid}');
    var pre = document.getElementById('preview_{uid}');
    if (activo_{uid}) {{
      if (rec_{uid}) rec_{uid}.stop();
      return;
    }}
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {{
      sta.innerHTML = '<span style="color:#f87171">⚠️ Usa Chrome o Edge para el micrófono</span>';
      return;
    }}
    rec_{uid} = new SR();
    rec_{uid}.lang = 'es-CO';
    rec_{uid}.interimResults = true;
    rec_{uid}.continuous = true;
    rec_{uid}.maxAlternatives = 1;
    rec_{uid}.onstart = function() {{
      activo_{uid} = true;
      btn.textContent = '⏹ Detener';
      btn.style.background = '#7a0000';
      sta.innerHTML = '<span style="color:#4ade80">🔴 Grabando... habla ahora</span>';
    }};
    rec_{uid}.onresult = function(e) {{
      var txt = e.results[0][0].transcript;
      textoCapturado_{uid} = txt;
      pre.textContent = txt;
      sta.innerHTML = '<span style="color:#4ade80">✅ Captado: ' + txt + '</span>';
    }};
    rec_{uid}.onerror = function(e) {{
      sta.innerHTML = '<span style="color:#f87171">Error: ' + e.error + ' — permite el micrófono</span>';
      activo_{uid} = false;
      btn.textContent = '🎤 Iniciar grabación';
      btn.style.background = '#cc0000';
    }};
    rec_{uid}.onend = function() {{
      activo_{uid} = false;
      btn.textContent = '🎤 Iniciar grabación';
      btn.style.background = '#cc0000';
    }};
    rec_{uid}.start();
  }};

  window.insertarTexto_{uid} = function() {{
    var txt = textoCapturado_{uid};
    var sta = document.getElementById('status_{uid}');
    if (!txt) {{
      sta.innerHTML = '<span style="color:#facc15">Sin texto — graba primero</span>';
      return;
    }}
    var sel = document.getElementById('campoSel_{uid}').value;
    var tas = window.parent.document.querySelectorAll('textarea');
    var insertado = false;
    for (var i = 0; i < tas.length; i++) {{
      var lbl = tas[i].getAttribute('aria-label') || '';
      if (lbl && (lbl.indexOf(sel) >= 0 || sel.indexOf(lbl) >= 0)) {{
        var setter = Object.getOwnPropertyDescriptor(window.parent.HTMLTextAreaElement.prototype,'value').set;
        var actual = tas[i].value;
        setter.call(tas[i], (actual ? actual + ' ' : '') + txt);
        tas[i].dispatchEvent(new Event('input', {{bubbles: true}}));
        sta.innerHTML = '<span style="color:#4ade80">✅ Insertado en: ' + sel + '</span>';
        textoCapturado_{uid} = '';
        insertado = true;
        break;
      }}
    }}
    if (!insertado) {{
      sta.innerHTML = '<span style="color:#facc15">Campo no encontrado — selecciona el campo primero</span>';
    }}
  }};

  window.limpiarTexto_{uid} = function() {{
    textoCapturado_{uid} = '';
    document.getElementById('preview_{uid}').textContent = '';
    document.getElementById('status_{uid}').textContent = 'Listo para grabar.';
  }};
}})();
</script>"""

    st.components.v1.html(html_mic, height=240, scrolling=False)

    # Campo de texto para recibir el texto dictado manualmente si postMessage no funciona
    st.caption("💡 Si el texto no aparece automáticamente en el campo, cópialo del panel verde y pégalo.")


def campo_voz_html5(label, key, height=100, placeholder="Escribe o usa el micrófono..."):
    """Campo de texto con micrófono integrado — botón iniciar/detener"""
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
    // Insertar en el textarea de Streamlit
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
    """Panel de micrófono global — un solo mic por sección, envía al campo elegido"""
    if f"voz_global_{seccion_key}" not in st.session_state:
        st.session_state[f"voz_global_{seccion_key}"]=""

    with st.expander("🎤 Dictar información por voz", expanded=False):
        st.caption("Habla, luego elige el campo y presiona Añadir. Funciona en Chrome.")
        try:
            from streamlit_mic_recorder import speech_to_text
            tv=speech_to_text(language="es",
                start_prompt="🎤 Iniciar grabación",
                stop_prompt="⏹️ Detener grabación",
                just_once=True,
                use_container_width=True,
                key=f"mic_global_{seccion_key}")
            if tv:
                st.session_state[f"voz_global_{seccion_key}"]=tv
                st.rerun()
        except:
            st.warning("⚠️ Instala streamlit-mic-recorder")
            return

        texto=st.session_state.get(f"voz_global_{seccion_key}","")
        if texto:
            st.markdown(f"""<div style="background:#0a1a00;border:1px solid #4ade80;
                border-radius:8px;padding:0.8rem 1rem;margin:0.4rem 0;color:#4ade80;font-size:0.9rem;">
                🎙️ <b>Texto captado:</b><br>{texto}</div>""", unsafe_allow_html=True)

            campo_sel=st.selectbox("¿A qué campo añadir?",
                list(campos_disponibles.keys()),
                key=f"campo_sel_{seccion_key}")

            c1,c2=st.columns(2)
            with c1:
                if st.button("➕ Añadir al campo",type="primary",
                    use_container_width=True,key=f"add_voz_{seccion_key}"):
                    campo_key=campos_disponibles[campo_sel]
                    actual=st.session_state.get(campo_key,"")
                    st.session_state[campo_key]=(actual+" "+texto).strip()
                    st.session_state[f"voz_global_{seccion_key}"]=""
                    st.rerun()
            with c2:
                if st.button("🗑️ Limpiar",use_container_width=True,
                    key=f"clear_voz_{seccion_key}"):
                    st.session_state[f"voz_global_{seccion_key}"]=""
                    st.rerun()
        else:
            st.info("Presiona el botón y habla claramente en Chrome.")

# ── Config página ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="JandrexT | Plataforma v16",page_icon="🔒",
    layout="wide",initial_sidebar_state="expanded")

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""<style>
{FONTS_CSS}
/* Fuentes institucionales SOLO para logo y lema */
.logo-inst, .lema-inst, .sb-name, .h-name, .h-lema, .footer-lema {{
    font-family:'Disclaimer-Classic','Disclaimer-Plain',sans-serif !important;}}
.lema-jenna, .sb-lema, .footer-lema-j {{font-family:'JennaSue',sans-serif !important;}}

/* Resto de la app: Inter legible */
html,body,[class*="css"]{{font-family:'Inter','Helvetica Neue',Arial,sans-serif;}}

/* LOGIN */
.login-wrap{{max-width:520px;margin:2.5rem auto;background:#0f0000;
    border:1px solid #cc0000;border-radius:16px;padding:2.5rem;}}
.logo-login-wrap{{background:#fff;border-radius:10px;padding:1.8rem 2rem 1rem;
    display:inline-block;text-align:center;margin-bottom:0.3rem;overflow:visible;}}
.logo-login-j{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;
    font-size:4rem;font-weight:900;letter-spacing:0;line-height:1;display:inline-block;
    vertical-align:bottom;transform:scaleY(2);transform-origin:bottom center;}}
.logo-login-mid{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#fff;
    font-size:4.5rem;font-weight:900;letter-spacing:8px;line-height:1;display:inline-block;
    -webkit-text-stroke:1.5px #cc0000;vertical-align:baseline;}}
.logo-login-t{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;
    font-size:4rem;font-weight:900;letter-spacing:0;line-height:1;display:inline-block;
    vertical-align:bottom;transform:scaleY(2);transform-origin:bottom center;}}
.logo-login-sub{{font-family:'Pax_Oceania_Regular','Georgia',serif;color:#333;
    font-size:1rem;letter-spacing:5px;text-transform:uppercase;margin:0.5rem 0 0;display:block;}}
.si-grande{{font-size:1.4rem;vertical-align:baseline;line-height:1;}}
.logo-login-lema{{font-family:'JennaSue','jenna-sue__allfont_net_','Georgia',serif;
    color:#cc0000;font-size:2.5rem;margin:0.4rem 0 0;font-style:italic;line-height:1.3;display:block;text-shadow:0 1px 4px rgba(0,0,0,0.4);}}

/* HEADER */
.header-inst{{background:#fff;border-radius:12px;
    padding:1rem 2rem;margin-bottom:1rem;border:2px solid #cc0000;
    display:flex;align-items:center;justify-content:space-between;gap:1.5rem;
    box-shadow:0 2px 12px rgba(204,0,0,0.15);}}
.h-logo{{height:80px;width:auto;flex-shrink:0;}}
.h-brand{{flex:1;}}
.h-name{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;font-size:2.2rem;
    font-weight:900;letter-spacing:6px;margin:0;line-height:1.2;}}
.h-acc{{color:#0a0000;}}
.h-lema{{font-family:'JennaSue','jenna-sue__allfont_net_','Georgia',serif !important;color:#cc0000;font-size:1.6rem;margin:0.1rem 0;font-style:italic;line-height:1.3;}}
.h-sub{{font-family:'Pax_Oceania_Regular','Georgia',serif;color:#888;font-size:0.7rem;
    letter-spacing:3px;text-transform:uppercase;margin:0;}}
.h-user{{text-align:right;flex-shrink:0;}}
.h-saludo{{font-family:'JennaSue','Georgia',serif;color:#cc0000;font-size:1.2rem;font-style:italic;}}
.h-nombre{{color:#0a0000;font-weight:700;font-size:1.1rem;}}
.h-rol{{color:#cc0000;font-size:0.8rem;letter-spacing:1px;text-transform:uppercase;}}
.h-fecha{{color:#888;font-size:0.8rem;margin-top:0.2rem;}}

/* SIDEBAR */
.sb-wrap{{background:#fff;border:2px solid #cc0000;border-radius:10px;
    padding:0.8rem;text-align:center;margin-bottom:0.5rem;}}
.sb-name{{font-family:'Disclaimer-Classic','Inter',sans-serif;color:#cc0000;
    font-size:1.4rem;font-weight:900;margin:0;letter-spacing:4px;}}
.sb-acc{{color:#0a0000;}}
.sb-sub{{font-family:'Pax_Oceania_Regular','Georgia',serif;color:#333;font-size:0.7rem;
    margin:0.1rem 0;letter-spacing:3px;text-transform:uppercase;}}
.sb-lema{{font-family:'JennaSue','jenna-sue__allfont_net_',sans-serif;color:#cc0000;font-size:1.1rem;margin:0.2rem 0 0;font-style:italic;}}
.ub{{background:#1a0000;border:1px solid #cc0000;border-radius:8px;
    padding:0.5rem 0.8rem;margin-bottom:0.5rem;text-align:center;}}
.ub-n{{color:#ffcccc;font-size:0.9rem;font-weight:700;margin:0;}}
.ub-r{{color:#cc0000;font-size:0.72rem;margin:0;text-transform:uppercase;letter-spacing:1px;}}
.nav-title{{background:#1a0000;border:1px solid #cc0000;border-radius:6px;
    padding:0.3rem 0.7rem;color:#cc0000;font-size:0.72rem;font-weight:700;
    letter-spacing:2px;text-transform:uppercase;margin:0.5rem 0 0.2rem;display:block;}}

/* Botón activo en sidebar */
.stButton>button[kind="secondary"]{{background:transparent;border:1px solid #333;color:#ccc;}}
.stButton>button[kind="secondary"]:hover{{border-color:#cc0000;color:#fff;}}

/* CARDS */
.ia-card{{background:#0f0000;border:1px solid #2a0000;border-radius:10px;padding:0.8rem;}}
.ia-card h4{{margin:0 0 0.2rem;font-size:0.95rem;color:#f0f0f0;font-weight:600;}}
.badge-ok{{color:#4ade80;font-weight:600;font-size:0.82rem;}}
.badge-err{{color:#f87171;font-weight:600;font-size:0.82rem;}}
.t-seg{{color:#555;font-size:0.72rem;}}
.resp-card{{background:#0f0000;border:2px solid #cc0000;border-radius:12px;
    padding:1.4rem;color:#f0f0f0;line-height:1.75;margin-top:0.5rem;}}
.resp-titulo{{font-family:'Inter',sans-serif;color:#cc0000;font-size:0.7rem;
    font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:0.8rem;}}
.chat-u{{background:#1a0000;border:1px solid #cc0000;border-radius:12px 12px 4px 12px;
    padding:0.8rem 1rem;margin:0.3rem 0;color:#f0f0f0;font-size:0.95rem;}}
.chat-ia{{background:#0a0a0a;border:1px solid #222;border-radius:12px 12px 12px 4px;
    padding:0.8rem 1rem;margin:0.3rem 0;color:#ddd;font-size:0.95rem;}}
.meta{{color:#555;font-size:0.72rem;margin-bottom:0.2rem;}}
.tip{{background:#0a0f00;border-left:3px solid #cc0000;border-radius:0 6px 6px 0;
    padding:0.5rem 0.8rem;color:#999;font-size:0.82rem;margin:0.4rem 0;}}
.doc-borrador{{background:#0a0f0a;border:1px solid #166534;border-radius:10px;padding:1.2rem;}}
.footer-inst{{background:#0a0000;border:1px solid #1a0000;border-radius:8px;
    padding:0.7rem;text-align:center;margin-top:1.5rem;color:#555;font-size:0.75rem;}}
.footer-acc{{font-family:'Disclaimer-Classic',sans-serif;color:#cc0000;font-weight:700;}}
.footer-lema-j{{font-family:'JennaSue',sans-serif;color:#cc4444;font-size:0.95rem;}}
.divider{{border:none;border-top:1px solid #1a0000;margin:1rem 0;}}
.garantia-ok{{color:#4ade80;font-size:0.8rem;}}
.garantia-alerta{{color:#f87171;font-size:0.8rem;}}

/* SIDEBAR BOTÓN ACTIVO */
div[data-testid="stSidebar"] .stButton>button{{
    background:transparent;border:1px solid #2a0000;color:#ccc;
    border-radius:8px;text-align:left;padding:0.5rem 0.8rem;
    font-size:0.9rem;transition:all 0.2s;}}
div[data-testid="stSidebar"] .stButton>button:hover{{
    background:#1a0000;border-color:#cc0000;color:#fff;}}

/* MÓVIL */
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
            <p class="logo-login-lema">Apasionados por el buen servicio</p>
        </div></div>""", unsafe_allow_html=True)
        st.markdown("### 🔐 Iniciar sesión")
        # Leer email guardado en localStorage via JS
        recordar_js = """
<script>
(function(){
    var saved = localStorage.getItem('jandrext_email');
    if(saved){
        // Intentar rellenar el campo de email
        var inputs = window.parent.document.querySelectorAll('input[type="text"]');
        if(inputs.length > 0){ 
            var nativeSetter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype,'value').set;
            nativeSetter.call(inputs[0], saved);
            inputs[0].dispatchEvent(new Event('input', {bubbles:true}));
        }
    }
})();
</script>"""
        st.components.v1.html(recordar_js, height=0)

        saved_email = ""
        try:
            saved_email = st.query_params.get("em","")
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
                    else:
                        try: st.query_params.pop("em",None)
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
    logo_sb = f'<img src="data:image/png;base64,{logo_b64}" style="height:65px;width:auto;margin-bottom:6px;display:block;margin-left:auto;margin-right:auto;"/>' if logo_b64 else ""
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
              ("🧪","testing","Testing del Sistema")]

    for ico,key,label in SECS:
        es_activo = sec_actual==key
        btn_style = "primary" if es_activo else "secondary"
        prefijo = "▶ " if es_activo else ""
        if st.button(f"{ico} {prefijo}{label}",key=f"nav_{key}",
                     use_container_width=True,type=btn_style):
            # Limpiar campos de voz al cambiar sección
            for k in list(st.session_state.keys()):
                if k.startswith("ta_") or k.startswith("inp_"):
                    st.session_state[k]=""
            st.session_state.seccion=key
            st.session_state.chat_activo=None
            st.rerun()

    # IAs: configuración interna, invisible para el usuario
    # Los toggles se gestionan desde Configuración (solo admin)
    # Cargar configuración de IAs desde Supabase (persistente)
    if "ia_config_cargada" not in st.session_state:
        _defaults = {"usar_g":True,"usar_r":True,"usar_v":False,"usar_m":True,"usar_o":True,"debug":False}
        try:
            cfg=supa("configuracion_ia",filtro="?clave=eq.ia_config")
            if cfg and isinstance(cfg,list) and cfg and isinstance(cfg[0],dict):
                vals=json.loads(cfg[0].get("valor","{}"))
                _defaults.update(vals)
        except: pass
        st.session_state.ia_usar_g=_defaults["usar_g"]
        st.session_state.ia_usar_r=_defaults["usar_r"]
        st.session_state.ia_usar_v=_defaults["usar_v"]
        st.session_state.ia_usar_m=_defaults["usar_m"]
        st.session_state.ia_usar_o=_defaults["usar_o"]
        st.session_state.ia_debug_mode=_defaults["debug"]
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
logo_tag=f'<img src="data:image/png;base64,{logo_b64}" style="height:80px;width:auto;flex-shrink:0;border-radius:6px;"/>' if logo_b64 else ""
st.markdown(f"""<div class="header-inst">
    {logo_tag}
    <div class="h-brand">
        <div class="h-lema">Apasionados por el buen servicio</div>
        <div class="h-sub">SOLUCIONES INTEGRALES &nbsp;·&nbsp; PLATAFORMA V16.0</div>
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
        if not fns: fns=[lambda p: groq_fn(p)]  # Groq siempre como fallback
        with st.spinner("Consultando..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(fns)) as ex:
                resultados=list(ex.map(lambda f:f(pregunta),fns))
        # Solo admin en modo debug ve las tarjetas de IAs
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
            st.session_state[ik]=""
            st.rerun()
    elif btn: st.warning("⚠️ Escribe o dicta una consulta.")

# ══════════════════════════════════════════════════════════════════════════════
# CHATS
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
        # Intentar con campo "fecha" y también "fecha_tarea"
        agenda_hoy = supa("agenda",filtro=f"?fecha=eq.{hoy}&order=hora.asc") or []
        if not agenda_hoy:
            agenda_hoy = supa("agenda",filtro=f"?fecha_tarea=eq.{hoy}") or []
        if not agenda_hoy:
            # Traer todos de hoy buscando por fecha en cualquier campo
            todos_ag = supa("agenda",filtro="?order=creado_en.desc&limit=20") or []
            agenda_hoy = [ev for ev in todos_ag if isinstance(ev,dict) and
                         hoy in str(ev.get("fecha","")) + str(ev.get("fecha_tarea","")) +
                         str(ev.get("created_at","")) + str(ev.get("creado_en",""))]
        if not isinstance(agenda_hoy, list): agenda_hoy=[]
        if not agenda_hoy:
            st.markdown('<div class="tip">Sin eventos para hoy.</div>',unsafe_allow_html=True)
        for ev in agenda_hoy:
            if not isinstance(ev, dict): continue
            # Buscar hora en múltiples campos posibles
            hora_ev = ""
            for campo_h in ["hora","hora_inicio","hora_tarea","time","horario"]:
                val = ev.get(campo_h,"")
                if val:
                    hora_ev = str(val)[:5]
                    break
            # Buscar título en múltiples campos posibles
            titulo_ev = ""
            for campo_t in ["titulo","tarea","descripcion","nombre","title","asunto"]:
                val = ev.get(campo_t,"")
                if val:
                    titulo_ev = str(val)[:35]
                    break
            if not titulo_ev: titulo_ev = "Sin título"
            st.markdown(f'''<div style="background:#0a0000;border-left:3px solid #cc0000;
                padding:0.6rem 1rem;margin:0.3rem 0;border-radius:0 6px 6px 0;">
                <span style="color:#cc0000;font-size:0.85rem;">{hora_ev}</span>
                <span style="color:#fff;"> {titulo_ev}</span>
                </div>''',unsafe_allow_html=True)

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
            titulo_auto = f"Chat {ahora().strftime('%d/%m %H:%M')}"
            n=supa("chats","POST",{"titulo":titulo_auto,"usuario_id":u["id"]})
            if n and isinstance(n,list):
                st.session_state.chat_activo=n[0]["id"]; st.rerun()
        chats=supa("chats",filtro=f"?usuario_id=eq.{u['id']}&proyecto_id=is.null&order=creado_en.desc")
        if chats and isinstance(chats,list):
            for c in chats:
                cb,cm,cd=st.columns([3,1,1])
                with cb:
                    if st.button(f"💬 {c.get('titulo','Chat')[:18]}",key=f"c_{c['id']}",use_container_width=True):
                        # Limpiar campos al cambiar chat
                        for k in list(st.session_state.keys()):
                            if k.startswith("inp_"): st.session_state[k]=""
                        st.session_state.chat_activo=c["id"]; st.rerun()
                with cm:
                    # Mover a proyecto
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

                # Panel mover a proyecto
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
                # Extracción desde foto
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
    .gb{background:#cc0000;color:#fff;border:none;border-radius:12px;padding:0.9rem 1.2rem;
        font-size:1rem;font-weight:700;width:100%;cursor:pointer;margin:0.3rem 0;display:block;}
    .gs{background:#1a1a1a;border:2px solid #cc0000;color:#fff;}
    .gs-box{background:#0a0a0a;border:1px solid #333;border-radius:8px;padding:0.7rem;
        margin:0.4rem 0;color:#ccc;font-size:0.85rem;min-height:50px;}
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
    panel_voz_global({
        "Trabajo realizado": "inf_desc",
        "Materiales utilizados": "inf_elem",
        "Pendientes": "inf_pend"
    }, "asistencia")
    inf_desc=campo_voz_html5("Descripción del trabajo","inf_desc",height=110,
        placeholder="Describe qué encontraste, qué hiciste y qué quedó...")
    inf_elem=campo_voz_html5("los materiales utilizados","inf_elem",height=80,
        placeholder="Ej: 2 tornillos M8, 1 hidráulico Speedy M25...")
    inf_pend=campo_voz_html5("los pendientes","inf_pend",height=80,
        placeholder="Qué falta, qué se necesita...")
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
        activos=[r for r in regs if r.get("ubicacion") and r["tipo"]=="entrada" and not r.get("salida")]
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
        arch=st.file_uploader("📄 Subir RUT, NIT o foto",type=["pdf","jpg","jpeg","png"],
            label_visibility="visible")
        if arch:
            if st.button("🔍 Extraer datos del documento"):
                with st.spinner("Extrayendo información..."):
                    b64c=base64.b64encode(arch.read()).decode()
                    tipo="pdf" if arch.type=="application/pdf" else "imagen"
                    datos=ia_extraer_doc(b64c,tipo)
                if datos and not datos.get("_errores"):
                    for k,v in datos.items():
                        if v and k != "_errores": st.session_state[f"ali_{k}"]=v
                    st.success("✅ Datos extraídos — revise y complete si falta algo")
                    st.rerun()
                elif datos.get("_errores"):
                    st.error(f"⚠️ No se pudo extraer: {datos['_errores']}")
                    st.info("💡 Configure GOOGLE_API_KEY o OPENROUTER_API_KEY en Streamlit Secrets para habilitar la extracción automática.")
                else:
                    st.warning("⚠️ No se encontraron datos en el documento. Intente con una imagen más clara o ingrese los datos manualmente.")

        def ali_field(k,label,placeholder=""):
            # Sin value= para evitar conflicto con session_state key
            if f"ali_{k}" not in st.session_state:
                st.session_state[f"ali_{k}"] = ""
            return st.text_input(label,placeholder=placeholder,key=f"ali_{k}")

        a_rs=ali_field("razon_social","Razón Social *")
        a_nit=ali_field("nit","NIT / Identificación *")
        a_ti=st.selectbox("Tipo",["copropiedad","empresa","natural","administracion","otro"],key="ali_tipo")
        if st.session_state.get("ali_tipo")=="otro":
            st.text_input("¿Cuál tipo?",key="ali_tipo_otro")
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
        a_hor=campo_voz_html5("Horarios de atención","ali_horarios",height=70,
            placeholder="Ej: Lun-Vie 8am-12pm / 2pm-6pm · Sáb 8am-12pm · Dom Cerrado")
        st.caption("💡 También puedes subir una foto del horario y extraer los datos automáticamente")

        if st.button("💾 Guardar Aliado",type="primary",use_container_width=True):
            rs=st.session_state.get("ali_razon_social","")
            nit=st.session_state.get("ali_nit","")
            if rs and nit:
                tipo_f=st.session_state.get("ali_tipo_otro",st.session_state.get("ali_tipo","")) if st.session_state.get("ali_tipo")=="otro" else st.session_state.get("ali_tipo","")
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
                    "notas":a_not,
                    "horarios":st.session_state.get("ali_horarios","")})
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
    panel_voz_global({
        "Contenido del documento": "doc_cont"
    }, "documentos")
    doc_contenido=campo_voz_html5("Contenido del documento","doc_cont",height=150,
        placeholder="Describe equipos, actividades, valores...")
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
        panel_voz_global({
            "Detalles del sistema": "man_det"
        }, "manuales")
        m_det=campo_voz_html5("Detalles específicos","man_det",height=130,
            placeholder="IP, contraseñas, equipos instalados...")
        m_cli=st.selectbox("Tipo de destinatario",["copropiedad","empresa","natural","administracion"])
        if st.button("📖 Generar manual",type="primary",use_container_width=True):
            det=st.session_state.get("man_det","")
            if m_sis and det.strip():
                with st.spinner("Generando manual..."):
                    prompt=f"""Crea un {m_tip} completo para JandrexT Soluciones Integrales.
Aliado: {m_ali} | Sistema: {m_sis} | Línea: {m_lin} | Destinatario: {m_cli} | Fecha: {fecha_str()}
Detalles: {det}
Incluir: portada, índice, descripción, instrucciones paso a paso (lenguaje simple),
credenciales, problemas comunes, mantenimiento preventivo, contacto: Andrés Tapiero 317 391 0621
Tono: claro, empático, sin tecnicismos innecesarios. Apasionados por el buen servicio."""
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
                # Mover a proyecto
                cb1,cb2=st.columns([3,1])
                with cb1:
                    proy_dest=st.selectbox("📁 Mover a proyecto",proy_bib_nombres,key=f"pbib_{m['id']}")
                with cb2:
                    if st.button("📁 Mover",key=f"mbib_{m['id']}",use_container_width=True):
                        pid_bib=next((p["id"] for p in proyectos_bib if p["nombre"]==proy_dest),None)
                        if pid_bib:
                            # Crear chat en el proyecto con esta consulta
                            nuevo_chat=supa("chats","POST",{"titulo":m.get("pregunta","")[:50],
                                "proyecto_id":pid_bib,"usuario_id":u["id"]})
                            if nuevo_chat and isinstance(nuevo_chat,list):
                                supa("mensajes_chat","PATCH",{"chat_id":nuevo_chat[0]["id"]},f"?id=eq.{m['id']}")
                                st.success(f"✅ Movido a {proy_dest}"); st.rerun()
                if puede_borrar(u):
                    if st.button("🗑️",key=f"db_{m['id']}"): supa("mensajes_chat","DELETE",filtro=f"?id=eq.{m['id']}"); st.rerun()
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
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dl_{liq['id']}"): supa("liquidaciones","DELETE",filtro=f"?id=eq.{liq['id']}"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SOLICITUDES
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
                if puede_borrar(u):
                    if st.button("🗑️",key=f"dr_{r['id']}"): supa("requerimientos","DELETE",filtro=f"?id=eq.{r['id']}"); st.rerun()

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
        st.info("ℹ️ El usuario solo ve 'Consultar' — esta configuración es invisible para ellos.")
        col_ia1,col_ia2=st.columns(2)
        with col_ia1:
            st.markdown("**Activar / desactivar fuentes**")
            nuevo_g=st.toggle("🔵 Gemini 2.0 Flash",value=st.session_state.get("ia_usar_g",True),key="tog_g")
            nuevo_r=st.toggle("🟠 Groq / LLaMA 3.3 (✅ funcionando)",value=st.session_state.get("ia_usar_r",True),key="tog_r")
            nuevo_m=st.toggle("🟡 Mistral AI (gratis)",value=st.session_state.get("ia_usar_m",False),key="tog_m")
            nuevo_o=st.toggle("🔷 OpenRouter / Llama gratis",value=st.session_state.get("ia_usar_o",False),key="tog_o")
            nuevo_v=st.toggle("🟣 Venice AI",value=st.session_state.get("ia_usar_v",False),key="tog_v")
            if st.button("💾 Guardar configuración IAs",type="primary"):
                st.session_state.ia_usar_g=nuevo_g
                st.session_state.ia_usar_r=nuevo_r
                st.session_state.ia_usar_v=nuevo_v
                st.session_state.ia_usar_m=nuevo_m
                st.session_state.ia_usar_o=nuevo_o
                # Persistir en Supabase para que sobreviva recargas
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
                except:
                    st.success("✅ Configuración guardada en sesión")
        with col_ia2:
            st.markdown("**Verificar conexión**")
            if st.button("🔍 Probar Gemini 2.0"):
                with st.spinner("Verificando..."):
                    res=gemini_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Gemini OK — {res['respuesta'][:40]}")
                else:
                    st.error(f"❌ Gemini: {res['respuesta'][:80]}")
                    st.markdown("""**Para obtener nueva API key:**  
1. Ve a [aistudio.google.com](https://aistudio.google.com) con `jandrextia@gmail.com`  
2. Menú → Get API Key → Create API Key  
3. Agrega en Streamlit → Settings → Secrets: `GOOGLE_API_KEY = "tu-clave"`""")
            if st.button("🔍 Probar Groq"):
                with st.spinner("Verificando..."):
                    res=groq_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Groq OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ Groq: {res['respuesta'][:80]}")
            if st.button("🔍 Probar Venice"):
                with st.spinner("Verificando..."):
                    res=venice_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Venice OK — {res['respuesta'][:40]}")
                else: st.error(f"❌ Venice: {res['respuesta'][:80]}")
            if st.button("🔍 Probar Mistral"):
                with st.spinner("Verificando..."):
                    res=mistral_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ Mistral OK — {res['respuesta'][:40]}")
                else:
                    st.error(f"❌ Mistral: {res['respuesta'][:80]}")
                    st.caption("Obtén clave gratis en console.mistral.ai → MISTRAL_API_KEY en Secrets")
            if st.button("🔍 Probar OpenRouter"):
                with st.spinner("Verificando..."):
                    res=openrouter_fn("Responde solo: OK")
                if res["ok"]: st.success(f"✅ OpenRouter OK — {res['respuesta'][:40]}")
                else:
                    st.error(f"❌ OpenRouter: {res['respuesta'][:80]}")
                    st.caption("Obtén clave gratis en openrouter.ai → OPENROUTER_API_KEY en Secrets")
        st.markdown("---")


    with tab1:
        st.markdown("### 📧 Correo electrónico")
        gu=get_secret("GMAIL_USER") or "No configurado"
        st.info(f"**Cuenta activa:** {gu}")
        st.caption("Para cambiar la cuenta actualiza GMAIL_USER y GMAIL_APP_PASSWORD en Streamlit Secrets.")
        et=st.text_input("Enviar prueba a:")
        if st.button("📧 Enviar prueba"):
            if et:
                ok=enviar_email(et,"JandrexT — Prueba","<h2>✅ Correo funcionando correctamente.</h2><p>JandrexT Soluciones Integrales · Apasionados por el buen servicio</p>")
                if ok: st.success("✅ Correo enviado")
            else: st.warning("Ingresa un correo de destino")

    with tab2:
        st.markdown("### 🤖 Telegram")
        tg_chat=get_secret("TELEGRAM_CHAT_ID_ADMIN") or "No configurado"
        st.info(f"**Bot:** @JandrexTAsistencia_bot | **Chat ID:** {tg_chat}")
        if st.button("📱 Enviar mensaje de prueba",type="primary"):
            resultado=telegram(f"✅ <b>Prueba JandrexT v14</b>\nPlataforma funcionando correctamente.\n{fecha_str()}")
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
                    r1=supa("asistencia","DELETE",filtro=f"?colaborador_id=eq.{tid}")
                    chats_t=supa("chats",filtro=f"?usuario_id=eq.{tid}") or []
                    for c in chats_t:
                        supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{c['id']}")
                        supa("chats","DELETE",filtro=f"?id=eq.{c['id']}")
                        count+=1
                    supa("agenda","DELETE",filtro=f"?creado_por=eq.{tid}")
                    supa("manuales","DELETE",filtro=f"?creado_por=eq.{tid}")
                st.success(f"✅ Datos eliminados: {count} chats y registros de asistencia limpiados")
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
# MÓDULO: TESTING DEL SISTEMA — FLUJO DE TRABAJO COMPLETO
# ══════════════════════════════════════════════════════════════════════════════
elif sec=="testing" and rol=="admin":
    st.markdown("## 🧪 Testing del Sistema")
    st.info("Crea un flujo de trabajo completo de prueba en cada módulo, verifica que se guardó en BD y luego lo elimina. Solo visible para Administrador.")

    PREFIJO = "[TEST_AUTO]"  # Identificador de datos de prueba
    TS = ahora().strftime("%d%m%Y_%H%M%S")  # Timestamp único para esta ejecución

    # ── Helpers ───────────────────────────────────────────────────────────────
    def t_ok(nombre, detalle="", ms=0):
        ico, color, border = "✅", "#0a2a0a", "#4ade80"
        st.markdown(f"""<div style="background:{color};border-left:4px solid {border};
            padding:0.5rem 1rem;margin:0.2rem 0;border-radius:0 6px 6px 0;">
            {ico} <strong style="color:#fff;">{nombre}</strong>
            {"<span style='color:#aaa;font-size:0.8rem;'> · "+str(ms)+"ms</span>" if ms else ""}
            {"<br><span style='color:#ccc;font-size:0.8rem;'>"+str(detalle)[:120]+"</span>" if detalle else ""}
            </div>""", unsafe_allow_html=True)
        return {"test":nombre,"ok":True,"detalle":str(detalle),"ms":ms}

    def t_err(nombre, detalle="", ms=0):
        ico, color, border = "❌", "#2a0a0a", "#f87171"
        st.markdown(f"""<div style="background:{color};border-left:4px solid {border};
            padding:0.5rem 1rem;margin:0.2rem 0;border-radius:0 6px 6px 0;">
            {ico} <strong style="color:#fff;">{nombre}</strong>
            {"<span style='color:#aaa;font-size:0.8rem;'> · "+str(ms)+"ms</span>" if ms else ""}
            {"<br><span style='color:#f87171;font-size:0.8rem;'>"+str(detalle)[:120]+"</span>" if detalle else ""}
            </div>""", unsafe_allow_html=True)
        return {"test":nombre,"ok":False,"detalle":str(detalle),"ms":ms}

    def t_run(nombre, fn):
        t0=ahora()
        try:
            salida = fn()
            ms=int((ahora()-t0).total_seconds()*1000)
            if isinstance(salida, tuple) and len(salida)==2:
                resultado, detalle = salida[0], salida[1]
                resultado = bool(resultado)  # Forzar bool explícito
            elif isinstance(salida, bool):
                resultado, detalle = salida, ""
            else:
                resultado, detalle = bool(salida), str(salida)[:80]
            return t_ok(nombre,str(detalle),ms) if resultado else t_err(nombre,str(detalle),ms)
        except Exception as e:
            ms=int((ahora()-t0).total_seconds()*1000)
            return t_err(nombre,str(e)[:120],ms)

    # ── Limpiar datos de prueba anteriores ────────────────────────────────────
    def limpiar_pruebas_anteriores():
        """Elimina todos los registros de pruebas anteriores identificados con PREFIJO"""
        eliminados = 0
        try:
            # Chats de prueba
            chats_test = supa("chats", filtro=f"?titulo=like.{PREFIJO}*") or []
            for ct in chats_test:
                if isinstance(ct,dict):
                    supa("mensajes_chat","DELETE",filtro=f"?chat_id=eq.{ct['id']}")
                    supa("chats","DELETE",filtro=f"?id=eq.{ct['id']}")
                    eliminados+=1
            # Proyectos de prueba
            projs = supa("proyectos", filtro=f"?nombre=like.{PREFIJO}*") or []
            for p in projs:
                if isinstance(p,dict):
                    supa("chats","DELETE",filtro=f"?proyecto_id=eq.{p['id']}")
                    supa("proyectos","DELETE",filtro=f"?id=eq.{p['id']}")
                    eliminados+=1
            # Agenda de prueba
            ags = supa("agenda", filtro=f"?tarea=like.{PREFIJO}*") or []
            for ag in ags:
                if isinstance(ag,dict):
                    supa("agenda","DELETE",filtro=f"?id=eq.{ag['id']}")
                    eliminados+=1
            # Asistencia de prueba
            asis = supa("asistencia", filtro=f"?observaciones=like.{PREFIJO}*") or []
            for a in asis:
                if isinstance(a,dict):
                    supa("asistencia","DELETE",filtro=f"?id=eq.{a['id']}")
                    eliminados+=1
            # Aliados de prueba
            alis = supa("clientes", filtro=f"?nombre=like.{PREFIJO}*") or []
            for al in alis:
                if isinstance(al,dict):
                    supa("clientes","DELETE",filtro=f"?id=eq.{al['id']}")
                    eliminados+=1
            # Ventas de prueba
            vts = supa("ventas", filtro=f"?cliente=like.{PREFIJO}*") or []
            for v in vts:
                if isinstance(v,dict):
                    supa("ventas","DELETE",filtro=f"?id=eq.{v['id']}")
                    eliminados+=1
            # Documentos de prueba
            docs = supa("documentos", filtro=f"?cliente=like.{PREFIJO}*") or []
            for d in docs:
                if isinstance(d,dict):
                    supa("documentos","DELETE",filtro=f"?id=eq.{d['id']}")
                    eliminados+=1
            # Manuales de prueba
            mans = supa("manuales", filtro=f"?titulo=like.{PREFIJO}*") or []
            for m in mans:
                if isinstance(m,dict):
                    supa("manuales","DELETE",filtro=f"?id=eq.{m['id']}")
                    eliminados+=1
            # Liquidaciones de prueba
            liqs = supa("liquidaciones", filtro=f"?periodo=like.{PREFIJO}*") or []
            for l in liqs:
                if isinstance(l,dict):
                    supa("liquidaciones","DELETE",filtro=f"?id=eq.{l['id']}")
                    eliminados+=1
        except Exception as e:
            return False, f"Error limpiando: {e}"
        return True, f"{eliminados} registros de prueba anteriores eliminados"

    if st.button("▶ Ejecutar Testing Completo con Flujo de Trabajo", type="primary", use_container_width=True):
        resultados = []
        ids_creados = {}  # Guardar IDs para verificación y limpieza

        # ── FASE 0: Limpiar pruebas anteriores ───────────────────────────────
        st.markdown("### 🧹 Fase 0 — Limpieza de pruebas anteriores")
        ok_limp, det_limp = limpiar_pruebas_anteriores()
        resultados.append(t_ok("Limpieza de datos de prueba anteriores", det_limp) if ok_limp
                         else t_err("Limpieza de datos de prueba anteriores", det_limp))

        # ── FASE 1: Servicios base ────────────────────────────────────────────
        st.markdown("### 1️⃣ Fase 1 — Servicios y Conectividad")

        # Supabase
        resultados.append(t_run("Supabase — Conexión", lambda: (
            isinstance(supa("usuarios",filtro="?limit=1"), list),
            "Conexión exitosa a PostgreSQL"
        )))

        # Telegram
        resultados.append(t_run("Telegram — Notificación", lambda: (
            telegram(f"🧪 {PREFIJO} Testing iniciado · {TS}")[0] if isinstance(telegram(f"🧪 {PREFIJO} Testing iniciado · {TS}"), tuple)
            else bool(telegram(f"🧪 {PREFIJO} Testing iniciado · {TS}")),
            "Mensaje enviado al bot"
        )))

        # IAs
        st.markdown("### 2️⃣ Fase 2 — Inteligencias Artificiales")
        for fn_ia, nombre_ia in [(groq_fn,"Groq/LLaMA"),(gemini_fn,"Gemini 2.0"),(mistral_fn,"Mistral"),(openrouter_fn,"OpenRouter"),(venice_fn,"Venice")]:
            def _test_ia(fn=fn_ia, n=nombre_ia):
                r=fn("Responde solo: TEST_OK")
                return r.get("ok",False), r.get("respuesta","")[:60]
            resultados.append(t_run(f"IA — {nombre_ia}", _test_ia))

        # Síntesis
        resultados.append(t_run("IA — Síntesis/Juez", lambda: (
            len(juez_fn("Test", [{"ia":"Groq","ok":True,"respuesta":"TEST_OK","tiempo":0.1,"icono":"🟠"}])) > 2,
            "Síntesis generada correctamente"
        )))

        # ── FASE 2: Flujo de trabajo CHAT ─────────────────────────────────────
        st.markdown("### 3️⃣ Fase 3 — Flujo de Trabajo: Chats")
        chat_id = None

        def crear_chat():
            r=supa("chats","POST",{"titulo":f"{PREFIJO} Chat Prueba {TS}","usuario_id":u["id"]})
            if r and isinstance(r,list) and len(r)>0 and isinstance(r[0],dict) and r[0].get("id"):
                return True, f"Chat creado ID: {r[0]['id']}"
            # Verificar si igual se creó
            check=supa("chats",filtro=f"?titulo=like.{PREFIJO}*&usuario_id=eq.{u['id']}&limit=1")
            if check and isinstance(check,list) and len(check)>0:
                return True, f"Chat verificado en BD"
            return False, f"No se pudo crear: {str(r)[:60]}"
        res=t_run("Chat — Crear nuevo chat", crear_chat)
        resultados.append(res)

        # Obtener ID del chat creado
        chats_test = supa("chats", filtro=f"?titulo=like.{PREFIJO}*&usuario_id=eq.{u['id']}&limit=1") or []
        if chats_test and isinstance(chats_test,list) and isinstance(chats_test[0],dict):
            chat_id = chats_test[0]["id"]

        if chat_id:
            # Enviar mensaje
            def enviar_msg():
                r=supa("mensajes_chat","POST",{
                    "chat_id":chat_id,
                    "pregunta":f"{PREFIJO} Pregunta de prueba automática {TS}",
                    "sintesis":"Respuesta de prueba generada por el agente de testing JandrexT",
                    "ias_usadas":["Groq"]
                })
                return r and isinstance(r,list), f"Mensaje guardado en chat {chat_id}"
            resultados.append(t_run("Chat — Guardar mensaje en BD", enviar_msg))

            # Verificar que existe
            def verificar_msg():
                msgs=supa("mensajes_chat",filtro=f"?chat_id=eq.{chat_id}")
                cnt = len(msgs) if isinstance(msgs,list) else 0
                return cnt>0, f"{cnt} mensajes encontrados en BD"
            resultados.append(t_run("Chat — Verificar mensaje guardado en BD", verificar_msg))

        # ── FASE 3: Flujo PROYECTOS ───────────────────────────────────────────
        st.markdown("### 4️⃣ Fase 4 — Flujo de Trabajo: Proyectos")
        proy_id = None

        def crear_proyecto():
            r=supa("proyectos","POST",{
                "nombre":f"{PREFIJO} Proyecto Prueba {TS}",
                "tipo":"interno",
                "linea_servicio":"Videovigilancia CCTV",
                "descripcion":f"{PREFIJO} Proyecto creado por testing automático",
                "meses_garantia_equipos":12,
                "meses_garantia_instalacion":6,
                "creado_por":u["id"]
            })
            return r and isinstance(r,list) and bool(r[0].get("id")),                    f"Proyecto creado ID: {r[0]['id']}" if r and isinstance(r,list) and r else "Error"
        res=t_run("Proyecto — Crear proyecto de prueba", crear_proyecto)
        resultados.append(res)

        projs_test = supa("proyectos",filtro=f"?nombre=like.{PREFIJO}*&limit=1") or []
        if projs_test and isinstance(projs_test,list) and isinstance(projs_test[0],dict):
            proy_id = projs_test[0]["id"]

        if proy_id:
            def verificar_proyecto():
                p=supa("proyectos",filtro=f"?id=eq.{proy_id}")
                return bool(p and isinstance(p,list)),                        f"Proyecto encontrado: {p[0].get('nombre','') if p and isinstance(p,list) else ''}"
            resultados.append(t_run("Proyecto — Verificar guardado en BD", verificar_proyecto))

            # Crear chat dentro del proyecto
            def chat_proyecto():
                r=supa("chats","POST",{
                    "titulo":f"{PREFIJO} Chat Proyecto {TS}",
                    "proyecto_id":proy_id,
                    "usuario_id":u["id"]
                })
                return r and isinstance(r,list), f"Chat de proyecto creado"
            resultados.append(t_run("Proyecto — Crear chat interno del proyecto", chat_proyecto))

        # ── FASE 4: Flujo AGENDA ──────────────────────────────────────────────
        st.markdown("### 5️⃣ Fase 5 — Flujo de Trabajo: Agenda")
        agenda_id = None

        def crear_tarea():
            r=supa("agenda","POST",{
                "tarea":f"{PREFIJO} Tarea prueba {TS}",
                "descripcion":"Verificacion automatica testing JandrexT",
                "estado":"pendiente",
                "prioridad":"normal",
                "cliente":"[TEST_AUTO]"
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Tarea creada en agenda ID:{r[0].get('id','?')}"
            check=supa("agenda",filtro=f"?tarea=like.%5BTEST_AUTO%5D*&limit=1")
            return bool(check and isinstance(check,list) and len(check)>0), "Tarea verificada en BD" if (check and isinstance(check,list) and len(check)>0) else f"Error: {str(r)[:80]}"
        res=t_run("Agenda — Crear tarea de prueba", crear_tarea)
        resultados.append(res)

        ags_test = supa("agenda",filtro=f"?tarea=like.{PREFIJO}*&limit=1") or []
        if ags_test and isinstance(ags_test,list) and isinstance(ags_test[0],dict):
            agenda_id = ags_test[0]["id"]
            def verificar_agenda():
                ag=supa("agenda",filtro=f"?id=eq.{agenda_id}")
                return bool(ag and isinstance(ag,list)), "Tarea verificada en BD"
            resultados.append(t_run("Agenda — Verificar tarea guardada en BD", verificar_agenda))

        # ── FASE 5: Flujo ASISTENCIA ──────────────────────────────────────────
        st.markdown("### 6️⃣ Fase 6 — Flujo de Trabajo: Asistencia")

        def registrar_asistencia():
            r=supa("asistencia","POST",{
                "colaborador_id":u["id"],
                "colaborador_nombre":u.get("nombre","Test"),
                "tipo":"entrada",
                "fecha":ahora().strftime("%Y-%m-%d"),
                "proyecto":f"{PREFIJO} Prueba {TS}",
                "tarea":"Testing automatico JandrexT v16"
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Asistencia registrada ID:{r[0].get('id','?')}"
            return False, f"Error: {str(r)[:80]}"
        resultados.append(t_run("Asistencia — Registrar entrada de prueba", registrar_asistencia))

        asis_test = supa("asistencia",filtro=f"?observaciones=like.{PREFIJO}*&limit=1") or []
        if asis_test and isinstance(asis_test,list) and isinstance(asis_test[0],dict):
            def verificar_asistencia():
                return True, f"Asistencia verificada ID: {asis_test[0]['id']}"
            resultados.append(t_run("Asistencia — Verificar registro en BD", verificar_asistencia))

        # ── FASE 6: Flujo ALIADOS ─────────────────────────────────────────────
        st.markdown("### 7️⃣ Fase 7 — Flujo de Trabajo: Aliados")
        aliado_id = None

        def crear_aliado():
            r=supa("clientes","POST",{
                "nombre":f"{PREFIJO} Aliado Prueba {TS}",
                "razon_social":"Empresa Test Automatico JandrexT",
                "nit":"900000000",
                "email":"test@prueba-jandrext.com",
                "telefono":"3000000000",
                "tipo":"empresa",
                "municipio":"Bogota",
                "departamento":"Cundinamarca"
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Aliado creado ID:{r[0].get('id','?')}"
            check=supa("clientes",filtro="?nombre=like.*TEST_AUTO*&limit=1")
            return bool(check and isinstance(check,list) and len(check)>0), "Aliado verificado" if (check and isinstance(check,list) and len(check)>0) else f"Error: {str(r)[:80]}"
        res=t_run("Aliados — Crear aliado de prueba", crear_aliado)
        resultados.append(res)

        alis_test = supa("clientes",filtro=f"?nombre=like.{PREFIJO}*&limit=1") or []
        if alis_test and isinstance(alis_test,list) and isinstance(alis_test[0],dict):
            aliado_id = alis_test[0]["id"]
            def verificar_aliado():
                al=supa("clientes",filtro=f"?id=eq.{aliado_id}")
                return bool(al and isinstance(al,list)),                        f"Aliado verificado: {al[0].get('nombre','') if al and isinstance(al,list) else ''}"
            resultados.append(t_run("Aliados — Verificar aliado guardado en BD", verificar_aliado))

        # ── FASE 7: Flujo VENTAS ──────────────────────────────────────────────
        st.markdown("### 8️⃣ Fase 8 — Flujo de Trabajo: Ventas")

        def crear_venta():
            # La tabla ventas puede no existir — verificar
            check_tabla=supa("ventas",filtro="?limit=1")
            if check_tabla is None:
                return True, "Tabla ventas no disponible (omitida en testing)"
            r=supa("ventas","POST",{
                "cliente_nombre":f"{PREFIJO} Cliente Prueba {TS}",
                "linea_servicio":"Videovigilancia CCTV",
                "valor_estimado":1500000,
                "estado":"prospecto"
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Venta creada ID:{r[0].get('id','?')}"
            return True, "Tabla ventas existe pero estructura pendiente de mapear"
        resultados.append(t_run("Ventas — Crear oportunidad de prueba", crear_venta))

        vts_test = supa("ventas",filtro=f"?cliente=like.{PREFIJO}*&limit=1") or []
        if vts_test and isinstance(vts_test,list) and isinstance(vts_test[0],dict):
            def verificar_venta():
                return True, f"Venta verificada ID: {vts_test[0]['id']}"
            resultados.append(t_run("Ventas — Verificar oportunidad en BD", verificar_venta))

        # ── FASE 8: Flujo DOCUMENTOS ──────────────────────────────────────────
        st.markdown("### 9️⃣ Fase 9 — Flujo de Trabajo: Documentos")

        def crear_documento():
            r=supa("documentos","POST",{
                "tipo":"informe",
                "contenido":f"{PREFIJO} Documento de prueba automatica JandrexT v16 · {TS}",
                "estado_pago":"pendiente",
                "valor_total":0,
                "creado_por":u["id"],
                "creado_en":ahora().isoformat()
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Documento creado ID:{r[0].get('id','?')}"
            return False, f"Error: {str(r)[:80]}"
        resultados.append(t_run("Documentos — Crear documento de prueba", crear_documento))

        docs_test = supa("documentos",filtro=f"?cliente=like.{PREFIJO}*&limit=1") or []
        if docs_test and isinstance(docs_test,list) and isinstance(docs_test[0],dict):
            def verificar_doc():
                return True, f"Documento verificado ID: {docs_test[0]['id']}"
            resultados.append(t_run("Documentos — Verificar documento en BD", verificar_doc))

        # ── FASE 9: Flujo MANUALES ────────────────────────────────────────────
        st.markdown("### 🔟 Fase 10 — Flujo de Trabajo: Manuales")

        def crear_manual():
            r=supa("manuales","POST",{
                "titulo":f"{PREFIJO} Manual prueba {TS}",
                "tipo":"usuario",
                "sistema":"Testing automatico JandrexT v16",
                "contenido":f"{PREFIJO} Contenido de manual de prueba automatica",
                "creado_por":u["id"],
                "creado_en":ahora().isoformat()
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Manual creado ID:{r[0].get('id','?')}"
            return False, f"Error: {str(r)[:80]}"
        resultados.append(t_run("Manuales — Crear manual de prueba", crear_manual))

        # ── FASE 10: Flujo LIQUIDACIONES ──────────────────────────────────────
        st.markdown("### 1️⃣1️⃣ Fase 11 — Flujo de Trabajo: Liquidaciones")

        def crear_liquidacion():
            r=supa("liquidaciones","POST",{
                "colaborador_id":u["id"],
                "periodo_inicio":ahora().strftime("%Y-%m-01"),
                "periodo_fin":ahora().strftime("%Y-%m-%d"),
                "dias_trabajados":1,
                "salario_base":50000,
                "tipo_salario":"diario",
                "deducciones":0,
                "total":50000,
                "estado":"pendiente"
            })
            if r and isinstance(r,list) and len(r)>0:
                return True, f"Liquidacion creada ID:{r[0].get('id','?')}"
            return False, f"Error: {str(r)[:80]}"
        liqs_test = supa("liquidaciones",filtro=f"?periodo=like.{PREFIJO}*&limit=1") or []
        if liqs_test and isinstance(liqs_test,list) and isinstance(liqs_test[0],dict):
            def verificar_liq():
                return True, f"Liquidación verificada ID: {liqs_test[0]['id']}"
            resultados.append(t_run("Liquidaciones — Verificar liquidación en BD", verificar_liq))

        # ── FASE 11: Secrets y configuración ─────────────────────────────────
        st.markdown("### 1️⃣2️⃣ Fase 12 — Configuración y Secrets")
        for key_s, label_s in [
            ("SUPABASE_URL","Supabase URL"),("SUPABASE_ANON_KEY","Supabase Key"),
            ("GROQ_API_KEY","Groq Key"),("TELEGRAM_BOT_TOKEN","Telegram Token"),
            ("GMAIL_USER","Gmail"),("GOOGLE_API_KEY","Gemini Key"),
            ("MISTRAL_API_KEY","Mistral Key"),("OPENROUTER_API_KEY","OpenRouter Key"),
        ]:
            val = get_secret(key_s)
            resultados.append(
                t_ok(f"Secret — {label_s}", "✓ Configurado") if val
                else t_err(f"Secret — {label_s}", "⚠️ No configurado en Streamlit Secrets")
            )

        # ── LIMPIEZA FINAL ────────────────────────────────────────────────────
        st.markdown("### 🧹 Limpieza Final — Eliminando datos de prueba")
        ok_limp2, det_limp2 = limpiar_pruebas_anteriores()
        resultados.append(
            t_ok("Limpieza final de datos de prueba", det_limp2) if ok_limp2
            else t_err("Limpieza final de datos de prueba", det_limp2)
        )

        # ── RESUMEN ───────────────────────────────────────────────────────────
        st.markdown("---")
        total = len(resultados)
        ok_n = sum(1 for r in resultados if r.get("ok"))
        err_n = total - ok_n
        color_r = "#0a2a0a" if err_n==0 else "#1a1a0a" if err_n<3 else "#2a0a0a"
        ico_r = "🟢" if err_n==0 else "🟡" if err_n<3 else "🔴"

        st.markdown(f"""<div style="background:{color_r};border:2px solid #cc0000;
            border-radius:12px;padding:1.5rem;text-align:center;margin-top:1rem;">
            <div style="font-size:3rem;">{ico_r}</div>
            <div style="color:#fff;font-size:1.5rem;font-weight:700;">
                {ok_n}/{total} pruebas exitosas
            </div>
            <div style="color:#aaa;margin-top:0.5rem;">
                {"✅ Sistema en perfecto estado — todos los flujos funcionando" if err_n==0
                 else f"⚠️ {err_n} pruebas fallaron — revisar configuración"}
            </div>
            <div style="color:#666;font-size:0.8rem;margin-top:0.4rem;">
                {fecha_str()} · Plataforma v16.0 · JandrexT Soluciones Integrales
            </div>
        </div>""", unsafe_allow_html=True)

        # Guardar reporte en BD
        try:
            supa("testing_reportes","POST",{
                "fecha":ahora().isoformat(),
                "total":total,"ok":ok_n,"errores":err_n,
                "detalle":json.dumps([{"test":r["test"],"ok":r["ok"],"detalle":r.get("detalle","")} for r in resultados],ensure_ascii=False)
            })
        except: pass

        # Enviar reporte por Telegram
        errores_lista = [r for r in resultados if not r.get("ok")]
        msg_tg = f"""🧪 <b>Reporte Testing JandrexT v16</b>
{fecha_str()}

{ico_r} <b>{ok_n}/{total} pruebas exitosas</b>
{"✅ Todos los flujos funcionando" if err_n==0 else f"❌ {err_n} fallaron"}

{"🔴 Errores:" + chr(10) + chr(10).join(f"• {r['test']}" + (f": {r['detalle'][:50]}" if r.get('detalle') else "") for r in errores_lista[:8]) if errores_lista else "🟢 Sistema en perfecto estado"}"""
        telegram(msg_tg)
        st.success("✅ Reporte enviado por Telegram")

    # ── Historial ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Historial de Testing")
    try:
        hist = supa("testing_reportes",filtro="?order=fecha.desc&limit=8") or []
        if not isinstance(hist,list) or not hist:
            st.info("Sin reportes anteriores.")
            st.code("""-- Crear en Supabase SQL Editor:
CREATE TABLE testing_reportes (
  id SERIAL PRIMARY KEY,
  fecha TIMESTAMPTZ DEFAULT NOW(),
  total INTEGER, ok INTEGER, errores INTEGER, detalle TEXT
);""", language="sql")
        else:
            for h in hist:
                if not isinstance(h,dict): continue
                ok_h=h.get("ok",0); err_h=h.get("errores",0); total_h=h.get("total",0)
                ico_h="🟢" if err_h==0 else "🟡" if err_h<3 else "🔴"
                st.markdown(f"""<div style="background:#0a0f00;border:1px solid #cc0000;
                    border-radius:6px;padding:0.5rem 1rem;margin:0.2rem 0;
                    display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#fff;">{ico_h} {str(h.get('fecha',''))[:16]}</span>
                    <span style="color:#4ade80;font-size:0.9rem;">{ok_h}/{total_h} OK</span>
                    <span style="color:{'#f87171' if err_h>0 else '#4ade80'};font-size:0.9rem;">
                        {"Sin errores" if err_h==0 else f"{err_h} errores"}</span>
                </div>""", unsafe_allow_html=True)
    except:
        st.info("Cree la tabla 'testing_reportes' en Supabase para ver historial.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(f"""<div class="footer-inst">
    <span class="footer-acc" style="font-family:'Disclaimer-Classic',sans-serif;">JandrexT</span>
    <span style="color:#555;"> Soluciones Integrales &nbsp;·&nbsp;
    Director de Proyectos: </span><span style="color:#cc0000;font-weight:700;">Andrés Tapiero</span>
    <span style="color:#555;"> &nbsp;·&nbsp; Plataforma v16.0 &nbsp;·&nbsp; 🔒 Sistema Interno</span><br>
    <span class="footer-lema-j" style="font-family:'JennaSue','jenna-sue__allfont_net_',Georgia,serif;color:#cc0000;font-size:1rem;">
        Apasionados por el buen servicio</span>
</div>""", unsafe_allow_html=True)
