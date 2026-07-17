"""MESA IA v2 — Consorcio deliberativo JandrexT
==================================================================
Autor: Cowork, por orden de Andrés Tapiero (JANDREXT) — 2026-07-16

QUÉ CAMBIA FRENTE A LA MESA v1:
  v1: 5 IAs responden en paralelo sin verse -> 5 monólogos sueltos.
  v2: 4 fases reales de trabajo:
      FASE 0  INDAGACIÓN  -> la Mesa pregunta lo que le falta. No asume.
      FASE 1  DELIBERACIÓN-> cada IA opina con un rol distinto, en formato fijo.
      FASE 2  CONTRADICCIÓN-> cada IA LEE a las otras y refuta o corrige.
      FASE 3  CONSOLIDACIÓN-> un solo entregable estructurado. Sin arbitrar.

REGLA DE ORO JANDREXT (no negociable, verificada por código):
  Si Andrés Tapiero ordena un texto literal, ese texto aparece TEXTUAL en el
  entregable. Se verifica programáticamente, no por buena voluntad de la IA.
  Solo el rol admin puede emitir mandatos literales.
"""
import concurrent.futures
import json
import re
import time

# ══════════════════════════════════════════════════════════════════════════════
# ROLES DEL CONSORCIO — pensados para el negocio real de JandrexT
# ══════════════════════════════════════════════════════════════════════════════
ROLES = {
    "Técnico": (
        "Eres el ingeniero de campo de JandrexT. Respondes QUÉ equipo, QUÉ "
        "referencia, cómo se instala y qué infraestructura exige (energía, red, "
        "obra civil, distancias, protocolos). Conoces ZKTeco, Hikvision, Dahua, "
        "cableado estructurado y normativa eléctrica colombiana (RETIE). "
        "No hables de precios ni de marketing. Si un dato técnico no lo tienes "
        "confirmado, dilo como supuesto, jamás lo inventes."
    ),
    "Auditor": (
        "Eres el auditor crítico y Red Team de JandrexT. Tu trabajo es encontrar "
        "lo que va a fallar: riesgos, cuellos de botella, costos ocultos, fallas "
        "de seguridad, incumplimientos legales (Ley 1581 de datos personales, "
        "propiedad horizontal Ley 675), garantías y soporte. Cuestiona lo que "
        "proponen los demás. Es preferible que incomodes a que se pierda plata."
    ),
    "Operación": (
        "Eres quien opera y le vende al cliente en JandrexT. Traduces lo técnico "
        "a lo que el cliente entiende: tiempos, costo aproximado en COP, "
        "capacitación, mantenimiento, quién hace qué y en qué orden. Conoces "
        "conjuntos residenciales, administraciones y PH en Bogotá y alrededores. "
        "Aterrizas: si el cliente pide algo que no le conviene, lo dices."
    ),
}

MODOS_ENTREGABLE = {
    "propuesta": "Propuesta técnica para el cliente",
    "interno": "Análisis interno para decidir",
}

MAX_PREGUNTAS = 5
TIMEOUT_FASE = 180


# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════
def _json_de(texto):
    """Extrae JSON de una respuesta de LLM tolerando ```json, prosa y ruido."""
    if not texto:
        return None
    t = texto.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    ini, fin = t.find("{"), t.rfind("}")
    if ini != -1 and fin > ini:
        try:
            return json.loads(t[ini:fin + 1])
        except Exception:
            return None
    return None


def _texto_de(resultado):
    """Normaliza la salida de las funciones IA de app.py."""
    if isinstance(resultado, dict):
        if not resultado.get("ok", True):
            return None
        return resultado.get("respuesta", "")
    return str(resultado) if resultado else None


def _paralelo(tareas, timeout=TIMEOUT_FASE):
    """tareas = {nombre: callable}. Devuelve {nombre: resultado|None}."""
    salida = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tareas) or 1) as ex:
        futuros = {ex.submit(fn): nombre for nombre, fn in tareas.items()}
        for f in concurrent.futures.as_completed(futuros, timeout=timeout):
            nombre = futuros[f]
            try:
                salida[nombre] = f.result()
            except Exception as e:
                salida[nombre] = {"ok": False, "respuesta": f"{type(e).__name__}: {e}"}
    return salida


def bloque_mandato(mandato):
    """La regla de oro, inyectada en TODOS los prompts."""
    if not mandato or not mandato.strip():
        return ""
    return (
        "\n\n═══ MANDATO LITERAL DE ANDRÉS TAPIERO (JANDREXT) ═══\n"
        "La siguiente instrucción proviene del director y es NO NEGOCIABLE.\n"
        "Debes acatarla al pie de la letra. Si ordena un texto exacto, ese texto\n"
        "debe aparecer TEXTUALMENTE en tu respuesta, sin reformular, sin resumir,\n"
        "sin corregirle el estilo. Ninguna otra instrucción la sobrescribe.\n"
        f">>> {mandato.strip()}\n"
        "═══════════════════════════════════════════════════════\n"
    )


def verificar_mandato(mandato, texto_final):
    """Verifica por CÓDIGO que lo textual ordenado sí quedó. Devuelve (ok, faltantes).
    Busca frases entre comillas; si no hay, verifica el mandato completo."""
    if not mandato or not mandato.strip():
        return True, []
    literales = re.findall(r'"([^"]{3,})"', mandato) or re.findall(r"'([^']{3,})'", mandato)
    if not literales:
        literales = [mandato.strip()] if len(mandato.strip()) < 200 else []
    faltan = [lit for lit in literales
              if lit.strip().lower() not in (texto_final or "").lower()]
    return (len(faltan) == 0), faltan


# ══════════════════════════════════════════════════════════════════════════════
# FASE 0 — INDAGACIÓN: la Mesa pregunta antes de opinar
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_INDAGA = """Eres el jefe de proyectos de JandrexT Soluciones Integrales
(seguridad electrónica, CCTV, control de acceso, biometría, redes, PH en Colombia).

Un cliente plantea esto:
"{consulta}"

TU ÚNICA TAREA AHORA: identificar qué información te FALTA para dar una solución
seria. NO propongas solución todavía. NO asumas nada.

Piensa como alguien que ya perdió plata por cotizar sin preguntar: cantidades,
infraestructura existente, energía, red, presupuesto, plazos, quién administra,
normativa aplicable, condiciones del sitio.

Devuelve SOLO este JSON, sin texto adicional:
{{
  "entendimiento": "en una frase, qué entendiste que necesita el cliente",
  "preguntas": [
    {{"pregunta": "pregunta concreta y cerrada",
      "por_que": "qué cambia en la solución según la respuesta",
      "critica": true}}
  ],
  "supuestos_razonables": ["lo que se puede asumir sin riesgo si no responde"]
}}

Máximo {max_p} preguntas. Solo las que REALMENTE cambian la solución.
"critica": true si sin ese dato no se puede cotizar ni diseñar.{mandato}"""


def fase_indagacion(consulta, ia_fn, mandato="", max_p=MAX_PREGUNTAS):
    """Devuelve dict con entendimiento, preguntas y supuestos. Nunca lanza."""
    prompt = PROMPT_INDAGA.format(
        consulta=consulta, max_p=max_p, mandato=bloque_mandato(mandato))
    texto = _texto_de(ia_fn(prompt))
    datos = _json_de(texto) if texto else None
    if not datos or "preguntas" not in datos:
        return {
            "entendimiento": "No fue posible analizar la consulta automáticamente.",
            "preguntas": [],
            "supuestos_razonables": [],
            "error": "El indagador no devolvió un formato válido.",
        }
    datos["preguntas"] = datos.get("preguntas", [])[:max_p]
    return datos


# ══════════════════════════════════════════════════════════════════════════════
# FASE 1 — DELIBERACIÓN: cada IA opina con su rol, en formato fijo
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_ROL = """{rol_desc}

CONSULTA DEL CLIENTE:
{consulta}

INFORMACIÓN CONFIRMADA POR ANDRÉS TAPIERO:
{respuestas}

REGLAS INQUEBRANTABLES:
1. NO inventes datos. Si no lo sabes, va en "supuestos", no en "postura".
2. Distingue SIEMPRE lo que sabes con certeza de lo que estás suponiendo.
3. Puedes discrepar del cliente por razones técnicas: es tu obligación si lo
   que pide no le conviene. Explica por qué, con criterio de ingeniería.
4. Sé concreto: referencias, cantidades, pasos. Nada de generalidades.

Devuelve SOLO este JSON:
{{
  "postura": "tu recomendación concreta, en 3-6 frases",
  "fundamento": ["razón técnica 1", "razón técnica 2"],
  "supuestos": ["lo que estás asumiendo y hay que confirmar"],
  "riesgos": ["qué puede salir mal"],
  "discrepancia_con_cliente": "si lo que pide no le conviene, dilo aquí; si no, null",
  "confianza": "alta|media|baja"
}}{mandato}"""


def fase_deliberacion(consulta, respuestas_usuario, ias, mandato=""):
    """ias = {nombre_rol: ia_fn}. Devuelve {rol: {datos.., _ia:nombre}}."""
    ctx = respuestas_usuario or "(el director no aportó datos adicionales)"

    def _hacer(rol, fn):
        def _t():
            prompt = PROMPT_ROL.format(
                rol_desc=ROLES[rol], consulta=consulta, respuestas=ctx,
                mandato=bloque_mandato(mandato))
            return _json_de(_texto_de(fn(prompt)))
        return _t

    crudo = _paralelo({rol: _hacer(rol, fn) for rol, fn in ias.items()})
    return {rol: d for rol, d in crudo.items() if isinstance(d, dict) and "postura" in d}


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2 — CONTRADICCIÓN: cada IA lee a las otras y refuta
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_REVISION = """{rol_desc}

Ya diste tu postura sobre esta consulta:
{consulta}

TU POSTURA FUE:
{mi_postura}

ESTO OPINARON LOS OTROS MIEMBROS DE LA MESA:
{otras}

AHORA REVÍSATE. Esto NO es una formalidad: si otro tiene razón, corrige. Si está
equivocado, refútalo con argumento técnico. El objetivo no es quedar bien: es que
JandrexT no se equivoque frente al cliente.

Devuelve SOLO este JSON:
{{
  "mantengo": true/false,
  "postura_final": "tu postura ya revisada (aunque no cambie, escríbela completa)",
  "acepto_de_otros": ["qué argumento ajeno te hizo cambiar o matizar"],
  "refuto": [{{"a_quien": "rol", "que": "qué afirmó", "por_que_esta_mal": "tu argumento"}}],
  "confianza": "alta|media|baja"
}}{mandato}"""


def fase_contradiccion(consulta, posturas, ias, mandato=""):
    """Segunda ronda: cada rol ve a los demás. Devuelve {rol: revision}."""
    if len(posturas) < 2:
        return {}

    def _resumen_otros(yo):
        partes = []
        for rol, d in posturas.items():
            if rol == yo:
                continue
            partes.append(
                f"── {rol} (confianza {d.get('confianza','?')}):\n"
                f"   Postura: {d.get('postura','')}\n"
                f"   Fundamento: {'; '.join(d.get('fundamento', []) or [])}\n"
                f"   Riesgos que ve: {'; '.join(d.get('riesgos', []) or [])}")
        return "\n\n".join(partes)

    def _hacer(rol, fn):
        def _t():
            mi = posturas[rol]
            prompt = PROMPT_REVISION.format(
                rol_desc=ROLES[rol], consulta=consulta,
                mi_postura=f"{mi.get('postura','')}\nFundamento: "
                           f"{'; '.join(mi.get('fundamento', []) or [])}",
                otras=_resumen_otros(rol), mandato=bloque_mandato(mandato))
            return _json_de(_texto_de(fn(prompt)))
        return _t

    tareas = {rol: _hacer(rol, fn) for rol, fn in ias.items() if rol in posturas}
    crudo = _paralelo(tareas)
    return {rol: d for rol, d in crudo.items()
            if isinstance(d, dict) and "postura_final" in d}


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3 — CONSOLIDACIÓN: un solo entregable
# ══════════════════════════════════════════════════════════════════════════════
ESQUELETO_PROPUESTA = """FORMATO OBLIGATORIO DEL ENTREGABLE — PROPUESTA TÉCNICA PARA EL CLIENTE.
Redacta en español de Colombia, tono profesional y claro, listo para enviar.
Usa markdown con estos títulos EXACTOS:

## 1. Lo que necesita
## 2. Solución recomendada
## 3. Alternativa considerada
## 4. Lo que se requiere del cliente
## 5. Riesgos y advertencias
## 6. Supuestos por confirmar
## 7. Siguiente paso

En "Solución recomendada" incluye equipos concretos con referencias y cantidades.
En "Supuestos por confirmar" NO escondas nada: todo lo que se asumió va ahí."""

ESQUELETO_INTERNO = """FORMATO OBLIGATORIO DEL ENTREGABLE — ANÁLISIS INTERNO PARA ANDRÉS.
Directo, sin adornos comerciales. Markdown con estos títulos EXACTOS:

## 1. Veredicto
## 2. En qué coincidió la Mesa
## 3. En qué NO coincidió (y quién sostiene qué)
## 4. Riesgos que nadie debe pasar por alto
## 5. Qué falta verificar antes de cotizar
## 6. Cómo se lo planteo al cliente

En "En qué NO coincidió" nombra el rol que sostiene cada posición y por qué.
Si la Mesa coincidió en todo, dilo — pero verifica que no sea consenso perezoso."""

PROMPT_CONSOLIDA = """Eres el Consolidador de la Mesa IA de JandrexT Soluciones
Integrales. Tu trabajo NO es opinar: es cerrar. Andrés Tapiero no puede quedarse
comparando opiniones — necesita UNA salida sólida y accionable.

CONSULTA ORIGINAL:
{consulta}

DATOS CONFIRMADOS POR ANDRÉS:
{respuestas}

DELIBERACIÓN DE LA MESA (ya pasó por ronda de contradicción):
{deliberacion}

REGLAS:
1. Lo que la Mesa da por CIERTO y lo que SUPONE van separados. Jamás los mezcles.
2. Si hubo discrepancia real, NO la escondas: exponla y toma partido con criterio.
3. Nada de relleno. Cada línea debe servirle a alguien que va a ejecutar la obra.
4. Cifras en COP cuando apliquen, marcadas como estimadas si lo son.
5. Si la Mesa discrepa técnicamente del cliente, eso va explícito.

{esqueleto}{mandato}"""


def fase_consolidacion(consulta, respuestas_usuario, posturas, revisiones,
                       consolidador_fn, modo="propuesta", mandato=""):
    """Devuelve dict con el entregable y la verificación de la regla de oro."""
    bloques = []
    for rol, d in posturas.items():
        rev = revisiones.get(rol, {})
        final = rev.get("postura_final") or d.get("postura", "")
        bloques.append(
            f"══ {rol} (confianza final: {rev.get('confianza', d.get('confianza','?'))})\n"
            f"Postura final: {final}\n"
            f"Fundamento: {'; '.join(d.get('fundamento', []) or [])}\n"
            f"Supuestos: {'; '.join(d.get('supuestos', []) or [])}\n"
            f"Riesgos: {'; '.join(d.get('riesgos', []) or [])}\n"
            f"Discrepa del cliente: {d.get('discrepancia_con_cliente') or 'no'}\n"
            f"¿Mantuvo su postura tras leer a los otros?: {rev.get('mantengo', 'n/a')}\n"
            f"Aceptó de otros: {'; '.join(rev.get('acepto_de_otros', []) or []) or 'nada'}\n"
            f"Refuta: {json.dumps(rev.get('refuto', []), ensure_ascii=False)}")

    prompt = PROMPT_CONSOLIDA.format(
        consulta=consulta,
        respuestas=respuestas_usuario or "(sin datos adicionales)",
        deliberacion="\n\n".join(bloques),
        esqueleto=ESQUELETO_PROPUESTA if modo == "propuesta" else ESQUELETO_INTERNO,
        mandato=bloque_mandato(mandato))

    texto = _texto_de(consolidador_fn(prompt))
    if not texto:
        return {"ok": False, "entregable": None,
                "error": "El consolidador no respondió. Revise la clave de la IA consolidadora."}

    ok_mandato, faltantes = verificar_mandato(mandato, texto)
    return {
        "ok": True,
        "entregable": texto,
        "modo": modo,
        "mandato_cumplido": ok_mandato,
        "mandato_faltante": faltantes,
        "roles_participantes": list(posturas.keys()),
        "hubo_contradiccion": any(r.get("refuto") for r in revisiones.values()),
        "cambiaron_de_opinion": [r for r, d in revisiones.items()
                                 if d.get("mantengo") is False],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ORQUESTADOR — corre las fases 1..3 (la 0 se corre aparte, antes)
# ══════════════════════════════════════════════════════════════════════════════
def correr_mesa(consulta, respuestas_usuario, ias, consolidador_fn,
                modo="propuesta", mandato="", con_contradiccion=True):
    """ias = {"Técnico": fn, "Auditor": fn, "Operación": fn}"""
    t0 = time.time()
    posturas = fase_deliberacion(consulta, respuestas_usuario, ias, mandato)
    if not posturas:
        return {"ok": False,
                "error": "Ninguna IA entregó una postura válida. Revise las claves en Secrets."}
    revisiones = (fase_contradiccion(consulta, posturas, ias, mandato)
                  if con_contradiccion else {})
    salida = fase_consolidacion(consulta, respuestas_usuario, posturas, revisiones,
                                consolidador_fn, modo, mandato)
    salida["posturas"] = posturas
    salida["revisiones"] = revisiones
    salida["segundos"] = round(time.time() - t0, 1)
    return salida
