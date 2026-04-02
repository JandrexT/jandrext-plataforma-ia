# ============================================================
# MÓDULO NAOMI — Asistente Virtual JandrexT
# Integrar en app.py de jandrext-ia
# Visible para todos los roles: Admin, Especialista, Asesor, Aliado
# ============================================================

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
import pytz

# ============================================================
# CONFIGURACIÓN
# ============================================================
BOGOTA_TZ = pytz.timezone("America/Bogota")

HORARIO = {
    "semana": {"inicio": 8, "fin": 18},   # Lun-Vie
    "sabado": {"inicio": 8, "fin": 13},    # Sábado
}

COBERTURA = [
    "bogotá", "bogota", "soacha", "chía", "chia",
    "cajicá", "cajica", "mosquera", "funza", "madrid",
    "facatativá", "facatativa"
]

SERVICIOS = {
    "cctv": "CCTV / Videovigilancia",
    "acceso": "Control de Acceso y Biometría",
    "redes": "Redes y Cableado Estructurado",
    "cercas": "Cercas Eléctricas",
    "otro": "Otro servicio",
}

TELEGRAM_TOKEN = "8795518431:AAGVIGSbtk7FhK4qBKCCY0HZ5ET7bd8EQTQ"
TELEGRAM_CHAT_ID = "1773051960"
SUPABASE_URL = "https://ktzgkueikwzhyhpfqqwg.supabase.co"


# ============================================================
# HELPERS
# ============================================================
def hora_bogota():
    return datetime.now(BOGOTA_TZ)


def esta_en_horario():
    ahora = hora_bogota()
    dia = ahora.weekday()  # 0=lun, 6=dom
    hora = ahora.hour
    if dia == 6:  # Domingo
        return False
    if dia == 5:  # Sábado
        return HORARIO["sabado"]["inicio"] <= hora < HORARIO["sabado"]["fin"]
    return HORARIO["semana"]["inicio"] <= hora < HORARIO["semana"]["fin"]


def validar_cobertura(ciudad: str) -> bool:
    c = ciudad.lower().strip()
    return any(z in c for z in COBERTURA)


def enviar_telegram(mensaje: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": mensaje,
                "parse_mode": "HTML"
            },
            timeout=5
        )
    except Exception:
        pass


def supabase_post(tabla: str, datos: dict, supabase_key: str):
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/{tabla}",
            headers={
                "Content-Type": "application/json",
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Prefer": "return=representation"
            },
            json=datos,
            timeout=10
        )
        return res.json()[0] if res.ok else None
    except Exception:
        return None


# ============================================================
# IA — GROQ
# ============================================================
PROMPT_NAOMI = """Eres Naomi, asistente virtual de JandrexT Soluciones Integrales, \
empresa colombiana de seguridad electrónica y automatización con sede en Bogotá.

PERSONALIDAD:
- Empática, cálida y profesional. No vendes productos, acompañas al cliente a encontrar la solución que necesita.
- Siempre escuchas primero antes de ofrecer soluciones.
- Hablas en nombre del equipo: usa "podemos", "te colaboramos", "estamos aquí".
- Lenguaje natural, colombiano, cercano pero profesional.
- Máximo 3 oraciones por respuesta. Concisa pero cálida.
- Siempre cierras con: "Apasionados por el buen servicio ❤️ JandrexT"

SERVICIOS (en orden de prioridad):
1. CCTV / Videovigilancia
2. Control de Acceso y Biometría
3. Redes y Cableado Estructurado
4. Cercas Eléctricas

COBERTURA: Bogotá, Soacha, Chía, Cajicá, Mosquera, Funza, Madrid, Facatativá.

FLUJO:
1. Escucha primero — entiende la necesidad antes de hablar de servicios
2. Genera valor — explica brevemente cómo JandrexT puede ayudar
3. Captura datos naturalmente: nombre → teléfono → ciudad → dirección → servicio
4. Si quiere agendar: captura fecha y hora preferida
5. Valida cobertura geográfica antes de confirmar
6. Confirma que el equipo contactará ese mismo día antes de las 6pm

REGLAS:
- NUNCA des precios exactos. Di: "En la visita técnica gratuita te damos la cotización exacta."
- Si la ciudad no tiene cobertura: sé empático y claro.
- Fuera de horario (Lun-Vie 8am-6pm, Sáb 8am-1pm): recibe la solicitud, explica que confirman el próximo día hábil.
- Si el cliente quiere cancelar o reprogramar: maneja con empatía y actualiza."""


def llamar_groq(mensajes: list, groq_key: str) -> str:
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {groq_key}"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": PROMPT_NAOMI},
                    *mensajes
                ],
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=15
        )
        data = res.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Disculpa, tuve un problema técnico momentáneo. ¿Puedes repetir tu mensaje? ❤️"


def extraer_datos_cliente(mensajes: list, groq_key: str) -> dict:
    """Extrae datos del cliente de la conversación usando IA."""
    try:
        historial = "\n".join([
            f"{'Cliente' if m['role'] == 'user' else 'Naomi'}: {m['content']}"
            for m in mensajes
        ])
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {groq_key}"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": """Analiza la conversación y extrae datos del cliente.
Responde SOLO con JSON válido, sin markdown, sin explicación:
{"nombre":"","telefono":"","ciudad":"","direccion":"","servicio":"cctv|acceso|redes|cercas|otro","fecha_preferida":"YYYY-MM-DD","hora_preferida":"HH:MM","quiere_agendar":false}
Si no hay dato deja el campo vacío."""
                    },
                    {"role": "user", "content": historial}
                ],
                "max_tokens": 200,
                "temperature": 0
            },
            timeout=10
        )
        text = res.json()["choices"][0]["message"]["content"]
        return json.loads(text.strip())
    except Exception:
        return {}


# ============================================================
# WIDGET NAOMI — Para insertar en Dashboard
# ============================================================
def widget_naomi_dashboard(groq_key: str, supabase_key: str):
    """
    Widget de Naomi para el Dashboard principal.
    Llamar desde el dashboard con:
        from naomi_modulo import widget_naomi_dashboard
        widget_naomi_dashboard(groq_key=GROQ_KEY, supabase_key=SUPABASE_KEY)
    """

    # CSS personalizado — colores institucionales JandrexT (rojo/blanco)
    st.markdown("""
    <style>
    .naomi-header {
        background: linear-gradient(135deg, #c0392b, #e74c3c);
        border-radius: 12px 12px 0 0;
        padding: 14px 18px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .naomi-title { color: white; font-weight: 700; font-size: 16px; margin: 0; }
    .naomi-status { color: rgba(255,255,255,0.85); font-size: 12px; }
    .naomi-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
    .naomi-container {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        margin-bottom: 16px;
    }
    .msg-naomi {
        background: #f8fafc;
        border-left: 3px solid #e74c3c;
        border-radius: 0 10px 10px 0;
        padding: 10px 14px;
        margin: 6px 0;
        font-size: 14px;
        color: #1e293b;
    }
    .msg-user {
        background: linear-gradient(135deg, #c0392b, #e74c3c);
        border-radius: 10px 10px 0 10px;
        padding: 10px 14px;
        margin: 6px 0 6px 40px;
        font-size: 14px;
        color: white;
    }
    .naomi-footer {
        text-align: center;
        padding: 8px;
        font-size: 11px;
        color: #94a3b8;
        background: #f8fafc;
        border-top: 1px solid #e2e8f0;
    }
    </style>
    """, unsafe_allow_html=True)

    # Inicializar estado de sesión
    if "naomi_mensajes" not in st.session_state:
        st.session_state.naomi_mensajes = []
        st.session_state.naomi_session_id = str(uuid.uuid4())
        st.session_state.naomi_lead_id = None
        st.session_state.naomi_solicitud_guardada = False
        st.session_state.naomi_turno = 0

        # Mensaje de bienvenida
        en_horario = esta_en_horario()
        if en_horario:
            bienvenida = "¡Hola, qué gusto saludarte! ❤️\nSoy Naomi. Estoy aquí para ayudarte a proteger lo que más te importa. ¿En qué te podemos colaborar hoy?"
        else:
            bienvenida = "¡Hola, qué gusto saludarte! ❤️\nSoy Naomi. En este momento estamos fuera de horario (Lun-Vie 8am-6pm, Sáb 8am-1pm), pero con mucho gusto recibo tu solicitud y el equipo te contactará el próximo día hábil. ¿En qué te podemos colaborar?"
        st.session_state.naomi_mensajes.append({
            "role": "assistant",
            "content": bienvenida
        })

    en_horario = esta_en_horario()

    # Header
    st.markdown(f"""
    <div class="naomi-container">
        <div class="naomi-header">
            <span style="font-size:24px;">🤖</span>
            <div>
                <p class="naomi-title">Naomi — Asistente JandrexT</p>
                <p class="naomi-status">
                    <span class="naomi-dot" style="background:{'#4ade80' if en_horario else '#fbbf24'};"></span>
                    {'En línea' if en_horario else 'Fuera de horario — recibimos tu solicitud'}
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Historial de mensajes
    with st.container():
        for msg in st.session_state.naomi_mensajes:
            if msg["role"] == "assistant":
                st.markdown(f'<div class="msg-naomi">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="msg-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)

    # Input del usuario
    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_input(
            "Escribe tu mensaje",
            key=f"naomi_input_{st.session_state.naomi_turno}",
            placeholder="Cuéntanos qué necesitas...",
            label_visibility="collapsed"
        )
    with col2:
        enviar = st.button("Enviar ❤️", key=f"naomi_btn_{st.session_state.naomi_turno}", use_container_width=True)

    # Botón limpiar chat
    if st.button("🔄 Nueva conversación", key="naomi_reset"):
        for key in ["naomi_mensajes", "naomi_session_id", "naomi_lead_id",
                    "naomi_solicitud_guardada", "naomi_turno"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    # Procesar mensaje
    if enviar and user_input.strip():
        # Agregar mensaje del usuario
        st.session_state.naomi_mensajes.append({
            "role": "user",
            "content": user_input.strip()
        })

        # Llamar a Naomi (IA)
        with st.spinner("Naomi está escribiendo..."):
            historial_ia = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.naomi_mensajes
            ]
            respuesta = llamar_groq(historial_ia, groq_key)

        # Agregar respuesta
        st.session_state.naomi_mensajes.append({
            "role": "assistant",
            "content": respuesta
        })
        st.session_state.naomi_turno += 1

        # Cada 3 turnos: extraer y guardar datos
        if st.session_state.naomi_turno % 3 == 0:
            datos = extraer_datos_cliente(
                [m for m in st.session_state.naomi_mensajes],
                groq_key
            )

            # Guardar lead si hay nombre y teléfono
            if datos.get("nombre") and datos.get("telefono") and not st.session_state.naomi_lead_id:
                lead = supabase_post("leads_chatbot", {
                    "nombre": datos.get("nombre", ""),
                    "telefono": datos.get("telefono", ""),
                    "ciudad": datos.get("ciudad", ""),
                    "direccion": datos.get("direccion", ""),
                    "servicio_interes": datos.get("servicio", "desconocido"),
                    "canal": "jandrext-ia",
                    "estado": "nuevo",
                    "mensaje_inicial": st.session_state.naomi_mensajes[1]["content"] if len(st.session_state.naomi_mensajes) > 1 else ""
                }, supabase_key)

                if lead and lead.get("id"):
                    st.session_state.naomi_lead_id = lead["id"]
                    enviar_telegram(
                        f"🔔 <b>Nuevo Lead — Naomi JandrexT</b>\n\n"
                        f"👤 <b>{datos.get('nombre')}</b>\n"
                        f"📞 {datos.get('telefono')}\n"
                        f"🏙️ {datos.get('ciudad', 'Sin ciudad')}\n"
                        f"🔧 {SERVICIOS.get(datos.get('servicio', ''), datos.get('servicio', 'Sin servicio'))}\n"
                        f"📲 Canal: jandrext-ia\n"
                        f"🕐 {hora_bogota().strftime('%d/%m/%Y %H:%M')}"
                    )

            # Guardar solicitud de visita
            if (datos.get("quiere_agendar") and
                datos.get("nombre") and datos.get("telefono") and
                datos.get("direccion") and datos.get("fecha_preferida") and
                not st.session_state.naomi_solicitud_guardada):

                ciudad = datos.get("ciudad", "Bogotá")
                if validar_cobertura(ciudad):
                    historial_texto = "\n".join([
                        f"{'Cliente' if m['role'] == 'user' else 'Naomi'}: {m['content']}"
                        for m in st.session_state.naomi_mensajes
                    ])
                    solicitud = supabase_post("solicitudes_visita", {
                        "lead_id": st.session_state.naomi_lead_id,
                        "nombre_cliente": datos.get("nombre"),
                        "telefono_cliente": datos.get("telefono"),
                        "direccion": datos.get("direccion"),
                        "ciudad": ciudad,
                        "servicio": datos.get("servicio", "otro"),
                        "fecha_preferida": datos.get("fecha_preferida"),
                        "hora_preferida": datos.get("hora_preferida", "09:00"),
                        "estado": "pendiente",
                        "canal": "jandrext-ia",
                        "historial_conversacion": historial_texto
                    }, supabase_key)

                    if solicitud and solicitud.get("id"):
                        st.session_state.naomi_solicitud_guardada = True
                        enviar_telegram(
                            f"📅 <b>Nueva Solicitud de Visita — Naomi</b>\n\n"
                            f"👤 <b>{datos.get('nombre')}</b>\n"
                            f"📞 {datos.get('telefono')}\n"
                            f"📍 {datos.get('direccion')}, {ciudad}\n"
                            f"🔧 {SERVICIOS.get(datos.get('servicio', ''), 'Sin servicio')}\n"
                            f"📆 {datos.get('fecha_preferida')} a las {datos.get('hora_preferida', '09:00')}\n\n"
                            f"⏰ <b>Asignar antes de las 6:00pm de hoy</b>\n"
                            f"🆔 ID: {solicitud['id'][:8]}"
                        )

        st.rerun()

    # Footer
    st.markdown("""
    <div class="naomi-footer">
        Apasionados por el buen servicio ❤️ JandrexT Soluciones Integrales
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# PANEL DE DESPACHO — Torre de Control (solo Admin)
# ============================================================
def panel_torre_control(supabase_key: str, rol: str):
    """Panel de despacho visible solo para Administrador."""
    if rol != "Administrador":
        return

    st.markdown("---")
    st.subheader("🗼 Torre de Control — Solicitudes Naomi")

    col1, col2, col3 = st.columns(3)

    try:
        # Cargar solicitudes
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/solicitudes_visita?order=creado_en.desc&limit=20",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}"
            },
            timeout=10
        )
        solicitudes = res.json() if res.ok else []

        pendientes = [s for s in solicitudes if s.get("estado") == "pendiente"]
        asignadas = [s for s in solicitudes if s.get("estado") == "asignado"]

        col1.metric("📋 Pendientes", len(pendientes))
        col2.metric("✅ Asignadas hoy", len(asignadas))
        col3.metric("📊 Total solicitudes", len(solicitudes))

        if pendientes:
            st.warning(f"⚠️ Tienes {len(pendientes)} solicitud(es) sin asignar. Recuerda: límite hoy antes de las 6:00pm.")

        for s in solicitudes[:10]:
            estado = s.get("estado", "pendiente")
            color = {"pendiente": "🟡", "asignado": "🔵", "confirmado": "🟢", "completado": "⚫", "cancelado": "🔴"}.get(estado, "⚪")

            with st.expander(f"{color} {s.get('nombre_cliente', 'Sin nombre')} — {s.get('servicio', '').upper()} — {s.get('fecha_preferida', '')}"):
                c1, c2 = st.columns(2)
                c1.write(f"📞 **Teléfono:** {s.get('telefono_cliente', '')}")
                c1.write(f"📍 **Dirección:** {s.get('direccion', '')}, {s.get('ciudad', '')}")
                c2.write(f"🕐 **Hora preferida:** {s.get('hora_preferida', '')}")
                c2.write(f"📌 **Estado:** {estado}")

                if estado == "pendiente":
                    if st.button(f"✅ Asignar a Andrés Tapiero", key=f"asignar_{s['id']}"):
                        requests.patch(
                            f"{SUPABASE_URL}/rest/v1/solicitudes_visita?id=eq.{s['id']}",
                            headers={
                                "Content-Type": "application/json",
                                "apikey": supabase_key,
                                "Authorization": f"Bearer {supabase_key}"
                            },
                            json={
                                "estado": "asignado",
                                "fecha_asignacion": datetime.now(BOGOTA_TZ).isoformat(),
                                "asignado_por": "Andrés Tapiero"
                            },
                            timeout=10
                        )
                        enviar_telegram(
                            f"✅ <b>Visita Asignada — Naomi</b>\n\n"
                            f"👤 {s.get('nombre_cliente')}\n"
                            f"📍 {s.get('direccion')}, {s.get('ciudad')}\n"
                            f"📆 {s.get('fecha_preferida')} a las {s.get('hora_preferida')}\n"
                            f"👷 Asignado a: Andrés Tapiero"
                        )
                        st.success("✅ Solicitud asignada. Telegram enviado.")
                        st.rerun()

    except Exception as e:
        st.error(f"Error cargando solicitudes: {e}")
