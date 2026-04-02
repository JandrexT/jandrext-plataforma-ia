# ============================================================
# MÓDULO NAOMI v2 — Asistente Virtual JandrexT
# Flujo corregido: Telegram + Supabase + Agenda al agendar
# ============================================================

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
import pytz
import os

BOGOTA_TZ = pytz.timezone("America/Bogota")
SUPABASE_URL = "https://ktzgkueikwzhyhpfqqwg.supabase.co"

HORARIO = {
    "semana": {"inicio": 8, "fin": 18},
    "sabado": {"inicio": 8, "fin": 13},
}

COBERTURA = [
    "bogotá", "bogota", "soacha", "chía", "chia",
    "cajicá", "cajica", "mosquera", "funza", "madrid",
    "facatativá", "facatativa", "colombia"
]

SERVICIOS = {
    "cctv": "CCTV / Videovigilancia",
    "acceso": "Control de Acceso y Biometría",
    "redes": "Redes y Cableado Estructurado",
    "cercas": "Cercas Eléctricas",
    "otro": "Otro servicio",
}

# ============================================================
# CREDENTIALS — Usa exactamente los mismos secrets que app.py
# ============================================================
def _get_secret(key, default=""):
    """Idéntica a get_secret() de app.py"""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except:
        return os.getenv(key, default)

def _telegram_token():
    return _get_secret("TELEGRAM_BOT_TOKEN", "8795518431:AAGVIGSbtk7FhK4qBKCCY0HZ5ET7bd8EQTQ")

def _telegram_chat():
    return _get_secret("TELEGRAM_CHAT_ID_ADMIN", "1773051960")

def _supabase_key():
    return _get_secret("SUPABASE_ANON_KEY", _get_secret("SUPABASE_KEY", ""))

# ============================================================
# HELPERS
# ============================================================
def hora_bogota():
    return datetime.now(BOGOTA_TZ)

def esta_en_horario():
    ahora = hora_bogota()
    dia = ahora.weekday()
    hora = ahora.hour
    if dia == 6: return False
    if dia == 5: return HORARIO["sabado"]["inicio"] <= hora < HORARIO["sabado"]["fin"]
    return HORARIO["semana"]["inicio"] <= hora < HORARIO["semana"]["fin"]

def validar_cobertura(ciudad: str) -> bool:
    if not ciudad: return True  # si no hay ciudad, no bloqueamos
    c = ciudad.lower().strip()
    return any(z in c for z in COBERTURA)

# ============================================================
# TELEGRAM
# ============================================================
def enviar_telegram(mensaje: str) -> bool:
    try:
        token = _telegram_token()
        chat_id = _telegram_chat()
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        st.warning(f"⚠️ Error Telegram: {e}")
        return False

# ============================================================
# SUPABASE
# ============================================================
def supa_post(tabla: str, datos: dict, key: str = "") -> dict:
    try:
        if not key: key = _supabase_key()
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{tabla}",
            headers={
                "Content-Type": "application/json",
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "return=representation"
            },
            json=datos,
            timeout=10
        )
        if r.ok and r.text:
            data = r.json()
            return data[0] if isinstance(data, list) else data
        return {}
    except Exception as e:
        return {}

def supa_get(tabla: str, filtro: str = "", key: str = "") -> list:
    try:
        if not key: key = _supabase_key()
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{tabla}{filtro}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10
        )
        return r.json() if r.ok else []
    except:
        return []

def supa_patch(tabla: str, filtro: str, datos: dict, key: str = ""):
    try:
        if not key: key = _supabase_key()
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/{tabla}{filtro}",
            headers={
                "Content-Type": "application/json",
                "apikey": key,
                "Authorization": f"Bearer {key}"
            },
            json=datos,
            timeout=10
        )
    except: pass

# ============================================================
# IA — GROQ
# ============================================================
PROMPT_NAOMI = """Eres Naomi, asistente virtual de JandrexT Soluciones Integrales,
empresa colombiana de seguridad electrónica en Bogotá.

PERSONALIDAD:
- Empática, cálida, colombiana. Hablas en nombre del equipo: "podemos", "te colaboramos".
- Escuchas primero. Generas valor antes de pedir datos.
- Máximo 3 oraciones por respuesta. Concisa pero cálida.
- Cierras siempre con: Apasionados por el buen servicio ❤️ JandrexT

SERVICIOS (prioridad): CCTV, Control de Acceso, Redes, Cercas Eléctricas.
COBERTURA: Bogotá, Soacha, Chía, Cajicá, Mosquera, Funza, Madrid, Facatativá.

FLUJO NATURAL:
1. Escucha y entiende la necesidad
2. Explica brevemente cómo JandrexT puede ayudar
3. Pregunta nombre y teléfono de forma natural
4. Si quiere visita técnica: pregunta dirección, fecha y hora preferida
5. Confirma: "Nuestro equipo te contactará hoy antes de las 6pm para confirmar"

REGLAS:
- NUNCA des precios. Di: "En la visita técnica gratuita te cotizamos."
- Fuera de horario (Lun-Vie 8am-6pm, Sáb 8am-1pm): recibe solicitud, explica que confirman el próximo día hábil.
- Si ciudad fuera de cobertura: sé empático y claro."""


def llamar_groq(mensajes: list, groq_key: str) -> str:
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {groq_key}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": PROMPT_NAOMI}, *mensajes],
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return "Disculpa, tuve un problema técnico. ¿Puedes repetir tu mensaje? ❤️"


def extraer_datos(mensajes: list, groq_key: str) -> dict:
    """Extrae datos del cliente desde la conversación."""
    try:
        historial = "\n".join([
            f"{'Cliente' if m['role']=='user' else 'Naomi'}: {m['content']}"
            for m in mensajes if m['role'] in ['user','assistant']
        ])
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {groq_key}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{
                    "role": "system",
                    "content": """Analiza la conversación y extrae datos del cliente.
Responde SOLO JSON válido sin markdown:
{"nombre":"","telefono":"","ciudad":"","direccion":"","servicio":"cctv|acceso|redes|cercas|otro","fecha_preferida":"YYYY-MM-DD","hora_preferida":"HH:MM","quiere_agendar":false,"resumen":""}
Si no hay dato deja el campo vacío. quiere_agendar=true si el cliente menciona visita, instalación o quiere que vayan."""
                }, {"role": "user", "content": historial}],
                "max_tokens": 300,
                "temperature": 0
            },
            timeout=10
        )
        txt = r.json()["choices"][0]["message"]["content"].strip()
        txt = txt.replace("```json","").replace("```","").strip()
        return json.loads(txt)
    except:
        return {}

# ============================================================
# GUARDAR EN AGENDA
# ============================================================
def crear_tarea_agenda(datos: dict, lead_id: str, supa_key: str = "") -> bool:
    """Crea una tarea en la agenda de la plataforma."""
    try:
        nombre = datos.get("nombre", "Cliente sin nombre")
        telefono = datos.get("telefono", "Sin teléfono")
        servicio = SERVICIOS.get(datos.get("servicio", ""), datos.get("servicio", "Sin servicio"))
        ciudad = datos.get("ciudad", "Bogotá")
        direccion = datos.get("direccion", "Por confirmar")
        fecha = datos.get("fecha_preferida", hora_bogota().strftime("%Y-%m-%d"))
        hora = datos.get("hora_preferida", "09:00")

        tarea = {
            "tarea": f"Visita técnica — {nombre} · {servicio}",
            "cliente": f"{nombre} ({telefono})",
            "prioridad": "🟡 Normal (60h)",
            "descripcion": f"Solicitud recibida por Naomi.\nNombre: {nombre}\nTeléfono: {telefono}\nDirección: {direccion}, {ciudad}\nServicio: {servicio}\nFecha preferida: {fecha} a las {hora}",
            "estado": "pendiente",
            "campo": True,
            "checklist_tipo": servicio,
            "checklist_items": [],
            "fecha_limite": f"{fecha}T{hora}:00",
            "asignados": ["Andrés Tapiero"],
            "creado_por": "naomi-bot",
            "satelite": "",
            "seguimiento": False
        }
        result = supa_post("agenda", tarea, supa_key)
        return bool(result)
    except:
        return False

# ============================================================
# FLUJO PRINCIPAL — Notificar cuando quiere agendar
# ============================================================
def procesar_y_notificar(mensajes: list, groq_key: str, supa_key: str = ""):
    """
    Extrae datos y notifica SOLO cuando el cliente quiere agendar.
    Guarda lead + crea tarea en agenda + notifica Telegram.
    """
    if st.session_state.get("naomi_solicitud_guardada"):
        return  # Ya se procesó

    datos = extraer_datos(mensajes, groq_key)
    if not datos:
        return

    quiere_agendar = datos.get("quiere_agendar", False)
    tiene_nombre = bool(datos.get("nombre"))
    tiene_telefono = bool(datos.get("telefono"))

    # Solo procesamos cuando quiere agendar y tenemos datos mínimos
    if not quiere_agendar:
        return

    nombre = datos.get("nombre", "Cliente")
    telefono = datos.get("telefono", "Sin teléfono")
    ciudad = datos.get("ciudad", "Bogotá")
    direccion = datos.get("direccion", "Por confirmar")
    servicio = datos.get("servicio", "otro")
    servicio_label = SERVICIOS.get(servicio, servicio)
    fecha = datos.get("fecha_preferida", hora_bogota().strftime("%Y-%m-%d"))
    hora_pref = datos.get("hora_preferida", "09:00")
    resumen = datos.get("resumen", "")

    # 1. Guardar lead en Supabase
    lead_id = st.session_state.get("naomi_lead_id")
    if not lead_id:
        lead = supa_post("leads_chatbot", {
            "nombre": nombre,
            "telefono": telefono,
            "ciudad": ciudad,
            "direccion": direccion,
            "servicio_interes": servicio,
            "canal": "jandrext-ia",
            "estado": "nuevo",
            "mensaje_inicial": mensajes[1]["content"] if len(mensajes) > 1 else ""
        }, supa_key)
        if lead and lead.get("id"):
            lead_id = lead["id"]
            st.session_state.naomi_lead_id = lead_id
            st.info(f"📋 Lead guardado: {lead_id[:8]}...")
        else:
            skey = _supabase_key()
            st.warning(f"⚠️ Lead no guardado. Supabase key: {'OK' if len(skey)>10 else 'VACÍA — revisar secrets'}")

    # 2. Guardar solicitud de visita
    historial_txt = "\n".join([
        f"{'Cliente' if m['role']=='user' else 'Naomi'}: {m['content']}"
        for m in mensajes
    ])
    solicitud = supa_post("solicitudes_visita", {
        "lead_id": lead_id,
        "nombre_cliente": nombre,
        "telefono_cliente": telefono,
        "direccion": direccion,
        "ciudad": ciudad,
        "servicio": servicio,
        "fecha_preferida": fecha,
        "hora_preferida": hora_pref,
        "estado": "pendiente",
        "canal": "jandrext-ia",
        "historial_conversacion": historial_txt
    }, supa_key)

    # 3. Crear tarea en Agenda
    crear_tarea_agenda(datos, lead_id or "", supa_key)

    # 4. Notificar Telegram — inmediato
    msg_telegram = (
        f"🔔 <b>Nueva Solicitud — Naomi JandrexT</b>\n\n"
        f"👤 <b>{nombre}</b>\n"
        f"📞 {telefono}\n"
        f"📍 {direccion}, {ciudad}\n"
        f"🔧 {servicio_label}\n"
        f"📆 {fecha} a las {hora_pref}\n"
    )
    if resumen:
        msg_telegram += f"💬 {resumen}\n"
    msg_telegram += (
        f"\n⏰ <b>Confirmar antes de las 6:00pm de hoy</b>\n"
        f"📲 Canal: jandrext-ia\n"
        f"🕐 {hora_bogota().strftime('%d/%m/%Y %H:%M')}"
    )

    ok = enviar_telegram(msg_telegram)
    st.session_state.naomi_solicitud_guardada = True

    # Diagnóstico visible para admin
    if ok:
        st.success("✅ Solicitud registrada. Un especialista te contactará en el transcurso del día.")
    else:
        token = _telegram_token()
        chat = _telegram_chat()
        skey = _supabase_key()
        st.error(f"⚠️ Error Telegram. Token: {'OK' if len(token)>10 else 'VACÍO'} | Chat: {'OK' if chat else 'VACÍO'} | Supa: {'OK' if len(skey)>10 else 'VACÍA'}")

# ============================================================
# WIDGET NAOMI — Dashboard
# ============================================================
def widget_naomi_dashboard(groq_key: str, supabase_key: str = ""):
    """Widget de Naomi para el Dashboard principal."""

    st.markdown("""
    <style>
    .naomi-container {border: 2px solid #cc0000; border-radius: 12px; overflow: hidden; margin-bottom: 16px;}
    .naomi-header {background: linear-gradient(135deg, #c0392b, #e74c3c); padding: 14px 18px; display: flex; align-items: center; gap: 12px;}
    .naomi-title {color: white; font-weight: 700; font-size: 16px; margin: 0;}
    .naomi-status {color: rgba(255,255,255,0.85); font-size: 12px;}
    .msg-naomi {background: #fff5f5; border-left: 3px solid #e74c3c; border-radius: 0 10px 10px 0; padding: 10px 14px; margin: 6px 0; font-size: 14px; color: #1e293b;}
    .msg-user {background: linear-gradient(135deg, #c0392b, #e74c3c); border-radius: 10px 10px 0 10px; padding: 10px 14px; margin: 6px 0 6px 40px; font-size: 14px; color: white;}
    .naomi-footer {text-align: center; padding: 8px; font-size: 11px; color: #94a3b8; border-top: 1px solid #f0f0f0;}
    </style>
    """, unsafe_allow_html=True)

    # Inicializar sesión
    if "naomi_mensajes" not in st.session_state:
        st.session_state.naomi_mensajes = []
        st.session_state.naomi_session_id = str(uuid.uuid4())
        st.session_state.naomi_lead_id = None
        st.session_state.naomi_solicitud_guardada = False
        st.session_state.naomi_turno = 0

        en_horario = esta_en_horario()
        if en_horario:
            bienvenida = "¡Hola, qué gusto saludarte! ❤️\nSoy Naomi. Estoy aquí para ayudarte a proteger lo que más te importa. ¿En qué te podemos colaborar hoy?"
        else:
            bienvenida = "¡Hola, qué gusto saludarte! ❤️\nSoy Naomi. Estamos fuera de horario (Lun-Vie 8am-6pm, Sáb 8am-1pm), pero con mucho gusto recibo tu solicitud y el equipo te contactará el próximo día hábil. ¿En qué te podemos colaborar?"
        st.session_state.naomi_mensajes.append({"role": "assistant", "content": bienvenida})

    en_horario = esta_en_horario()

    # Header
    st.markdown(f"""
    <div class="naomi-container">
      <div class="naomi-header">
        <span style="font-size:24px;">🤖</span>
        <div>
          <p class="naomi-title">Naomi — Asistente JandrexT</p>
          <p class="naomi-status">
            <span style="width:8px;height:8px;border-radius:50%;background:{'#4ade80' if en_horario else '#fbbf24'};display:inline-block;margin-right:4px;"></span>
            {'En línea' if en_horario else 'Fuera de horario — recibimos tu solicitud'}
          </p>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Historial mensajes
    for msg in st.session_state.naomi_mensajes:
        if msg["role"] == "assistant":
            st.markdown(f'<div class="msg-naomi">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="msg-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)

    # Input
    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_input(
            "Mensaje",
            key=f"naomi_input_{st.session_state.naomi_turno}",
            placeholder="Escríbenos, estamos para colaborarte...",
            label_visibility="collapsed"
        )
    with col2:
        enviar = st.button("Enviar ❤️", key=f"naomi_btn_{st.session_state.naomi_turno}", use_container_width=True)

    col_reset, col_info = st.columns([1, 2])
    with col_reset:
        if st.button("🔄 Nueva conversación", key="naomi_reset"):
            for key in list(st.session_state.keys()):
                if key.startswith("naomi_"):
                    del st.session_state[key]
            st.rerun()
    with col_info:
        if st.session_state.get("naomi_solicitud_guardada"):
            st.success("✅ Solicitud registrada en agenda")

    # Procesar mensaje
    if enviar and user_input.strip():
        st.session_state.naomi_mensajes.append({"role": "user", "content": user_input.strip()})

        with st.spinner("Naomi está escribiendo..."):
            historial_ia = [{"role": m["role"], "content": m["content"]} for m in st.session_state.naomi_mensajes]
            respuesta = llamar_groq(historial_ia, groq_key)

        st.session_state.naomi_mensajes.append({"role": "assistant", "content": respuesta})
        st.session_state.naomi_turno += 1

        # Analizar y notificar si quiere agendar
        if not st.session_state.get("naomi_solicitud_guardada"):
            procesar_y_notificar(st.session_state.naomi_mensajes, groq_key, supabase_key)

        st.rerun()

    # Footer
    st.markdown('<div class="naomi-footer">Apasionados por el buen servicio ❤️ JandrexT Soluciones Integrales</div>', unsafe_allow_html=True)


# ============================================================
# PANEL TORRE DE CONTROL — Solo Admin
# ============================================================
def panel_torre_control(supabase_key: str = "", rol: str = ""):
    """Panel de despacho para el Administrador."""
    if rol != "Administrador":
        return

    st.markdown("#### 🗼 Torre de Control")

    try:
        solicitudes = supa_get("solicitudes_visita", "?order=creado_en.desc&limit=15", supabase_key)
        pendientes = [s for s in solicitudes if s.get("estado") == "pendiente"]

        col1, col2, col3 = st.columns(3)
        col1.metric("📋 Pendientes", len(pendientes))
        col2.metric("✅ Total hoy", len([s for s in solicitudes if s.get("creado_en","")[:10] == hora_bogota().strftime("%Y-%m-%d")]))
        col3.metric("📊 Total", len(solicitudes))

        if pendientes:
            st.warning(f"⚠️ {len(pendientes)} solicitud(es) sin asignar — límite 6:00pm")

        for s in solicitudes[:8]:
            estado = s.get("estado", "pendiente")
            ico = {"pendiente": "🟡", "asignado": "🔵", "confirmado": "🟢", "completado": "⚫", "cancelado": "🔴"}.get(estado, "⚪")
            with st.expander(f"{ico} {s.get('nombre_cliente','Sin nombre')} · {s.get('servicio','').upper()} · {s.get('fecha_preferida','')}"):
                st.write(f"📞 **{s.get('telefono_cliente','')}** | 📍 {s.get('direccion','')}, {s.get('ciudad','')}")
                st.write(f"🕐 {s.get('hora_preferida','')} | Estado: **{estado}**")
                if estado == "pendiente":
                    if st.button("✅ Asignar a Andrés", key=f"asig_{s['id']}"):
                        supa_patch("solicitudes_visita", f"?id=eq.{s['id']}", {
                            "estado": "asignado",
                            "fecha_asignacion": datetime.now(BOGOTA_TZ).isoformat(),
                            "asignado_por": "Andrés Tapiero"
                        }, supabase_key)
                        enviar_telegram(
                            f"✅ <b>Visita Asignada</b>\n\n"
                            f"👤 {s.get('nombre_cliente')}\n"
                            f"📞 {s.get('telefono_cliente')}\n"
                            f"📍 {s.get('direccion')}, {s.get('ciudad')}\n"
                            f"📆 {s.get('fecha_preferida')} a las {s.get('hora_preferida')}\n"
                            f"👷 Asignado: Andrés Tapiero"
                        )
                        st.success("✅ Asignado. Telegram enviado.")
                        st.rerun()
    except Exception as e:
        st.error(f"Error cargando solicitudes: {e}")
