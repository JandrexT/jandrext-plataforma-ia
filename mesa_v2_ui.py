"""MESA IA v2 — Interfaz Streamlit
Se apoya en mesa_v2.py (motor puro, probado aparte).
Uso desde app.py:
    import mesa_v2_ui
    mesa_v2_ui.render(ias, consolidador_fn, supa, u, proyecto_id)
"""
import json

import streamlit as st

import mesa_v2 as M


def _reset():
    for k in ("mv2_paso", "mv2_consulta", "mv2_mandato", "mv2_modo",
              "mv2_indagacion", "mv2_resultado", "mv2_respuestas"):
        st.session_state.pop(k, None)


def _guardar(supa, usuario, proyecto_id, consulta, resultado):
    try:
        supa("mesa_ia_sessions", "POST", {
            "user_id": usuario.get("id"),
            "mode": "mesa_v2_" + resultado.get("modo", ""),
            "project_id": proyecto_id,
            "pregunta": consulta,
            "respuesta": resultado.get("entregable", "")[:20000],
        })
    except Exception:
        pass


def render(ias, consolidador_fn, supa, usuario, proyecto_id=None):
    """ias = {"Técnico": fn, "Auditor": fn, "Operación": fn}"""
    es_admin = (usuario.get("role") == "admin" or usuario.get("rol") == "admin")

    st.markdown("## 🧠 Mesa IA — Consorcio deliberativo")
    st.caption("Indaga antes de opinar · delibera en dos rondas · entrega un solo "
               "resultado estructurado. No es velocidad: es criterio.")

    paso = st.session_state.get("mv2_paso", "inicio")

    # ── PASO 1 — LA CONSULTA ────────────────────────────────────────────────
    if paso == "inicio":
        consulta = st.text_area(
            "¿Qué necesita resolver?",
            height=120,
            placeholder="Ej: Un cliente necesita terminal de reconocimiento facial "
                        "para 30 empleados. Le ofrecí ZKTeco y Hikvision.\n\n"
                        "Ej: Hay que hacer el sorteo de parqueaderos de carros y motos "
                        "en el conjunto Vizcaya sin que se demoren 15 días.",
            key="mv2_in_consulta")

        c1, c2 = st.columns([1, 1])
        with c1:
            modo_lbl = st.radio("Qué quiere recibir",
                                ["Propuesta técnica para el cliente",
                                 "Análisis interno para decidir"],
                                key="mv2_in_modo")
        with c2:
            indagar = st.toggle("Que me pregunte lo que falta antes de opinar",
                                value=True, key="mv2_in_indagar")
            contradecir = st.toggle("Segunda ronda: que se refuten entre ellas",
                                    value=True, key="mv2_in_contra")

        mandato = ""
        if es_admin:
            with st.expander("⚖️ Mandato literal de Andrés Tapiero (regla de oro)"):
                st.caption('Lo que ponga aquí es orden NO negociable para toda la Mesa. '
                           'Lo que escriba entre "comillas dobles" debe aparecer '
                           'textual en el entregable — el sistema lo verifica y le '
                           'avisa si alguna IA no obedeció.')
                mandato = st.text_area(
                    "Instrucción del director",
                    height=80,
                    placeholder='Ej: cierra siempre con "Apasionados por el buen servicio"\n'
                                'Ej: no recomiendes Dahua, solo ZKTeco o Hikvision',
                    key="mv2_in_mandato")

        if st.button("🧠 Convocar la Mesa", type="primary", use_container_width=True):
            if not consulta.strip():
                st.warning("Escriba primero qué necesita resolver.")
                return
            st.session_state["mv2_consulta"] = consulta
            st.session_state["mv2_mandato"] = mandato or ""
            st.session_state["mv2_modo"] = ("propuesta" if "Propuesta" in modo_lbl
                                            else "interno")
            if not indagar:
                st.session_state["mv2_respuestas"] = ""
                st.session_state["mv2_paso"] = "deliberar"
                st.rerun()
            with st.spinner("Analizando qué falta saber..."):
                ind = M.fase_indagacion(consulta, consolidador_fn,
                                        st.session_state["mv2_mandato"])
            st.session_state["mv2_indagacion"] = ind
            st.session_state["mv2_paso"] = "indagando"
            st.rerun()
        return

    # ── PASO 2 — INDAGACIÓN ─────────────────────────────────────────────────
    if paso == "indagando":
        ind = st.session_state.get("mv2_indagacion", {})
        st.info(f"**Entendí esto:** {ind.get('entendimiento','(sin lectura)')}")

        preguntas = ind.get("preguntas", [])
        if ind.get("error"):
            st.warning(ind["error"] + " Puede continuar sin indagación.")
        if not preguntas:
            st.caption("La Mesa no necesita más datos. Puede deliberar.")
        else:
            st.markdown("### La Mesa necesita saber:")
            st.caption("Responda lo que sepa. Lo que deje vacío se marcará como "
                       "supuesto por confirmar — no se inventa.")

        respuestas = []
        for i, p in enumerate(preguntas):
            crit = "🔴" if p.get("critica") else "🟡"
            st.markdown(f"**{crit} {p.get('pregunta','')}**")
            st.caption(f"Por qué importa: {p.get('por_que','')}")
            r = st.text_input("Respuesta", key=f"mv2_r_{i}",
                              label_visibility="collapsed",
                              placeholder="Escriba aquí, o déjelo vacío si no sabe")
            if r.strip():
                respuestas.append(f"P: {p.get('pregunta','')}\nR: {r.strip()}")

        sup = ind.get("supuestos_razonables", [])
        if sup:
            with st.expander("Lo que la Mesa asumiría si no responde"):
                for s in sup:
                    st.markdown(f"- {s}")

        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("✅ Deliberar con estas respuestas", type="primary",
                         use_container_width=True):
                st.session_state["mv2_respuestas"] = "\n\n".join(respuestas)
                st.session_state["mv2_paso"] = "deliberar"
                st.rerun()
        with c2:
            if st.button("↩ Empezar de nuevo", use_container_width=True):
                _reset()
                st.rerun()
        return

    # ── PASO 3 — DELIBERACIÓN ───────────────────────────────────────────────
    if paso == "deliberar":
        n = len(ias)
        with st.spinner(f"Deliberando: {n} roles opinan, se leen entre ellos y se "
                        f"refutan, luego se consolida. Esto toma su tiempo — es a "
                        f"propósito."):
            res = M.correr_mesa(
                consulta=st.session_state["mv2_consulta"],
                respuestas_usuario=st.session_state.get("mv2_respuestas", ""),
                ias=ias,
                consolidador_fn=consolidador_fn,
                modo=st.session_state.get("mv2_modo", "propuesta"),
                mandato=st.session_state.get("mv2_mandato", ""),
                con_contradiccion=st.session_state.get("mv2_in_contra", True))
        st.session_state["mv2_resultado"] = res
        st.session_state["mv2_paso"] = "listo"
        if res.get("ok"):
            _guardar(supa, usuario, proyecto_id,
                     st.session_state["mv2_consulta"], res)
        st.rerun()
        return

    # ── PASO 4 — RESULTADO ──────────────────────────────────────────────────
    if paso == "listo":
        res = st.session_state.get("mv2_resultado", {})

        if not res.get("ok"):
            st.error(res.get("error", "La Mesa no pudo entregar resultado."))
            if st.button("↩ Intentar de nuevo"):
                _reset()
                st.rerun()
            return

        if res.get("mandato_cumplido") is False:
            st.error("⚠️ **Su mandato literal NO se cumplió.** Falta textualmente: "
                     + " · ".join(f'"{f}"' for f in res.get("mandato_faltante", []))
                     + ". Revise el entregable antes de enviarlo.")
        elif st.session_state.get("mv2_mandato"):
            st.success("✅ Su mandato literal se cumplió (verificado por el sistema).")

        m1, m2, m3 = st.columns(3)
        m1.metric("Roles que deliberaron", len(res.get("roles_participantes", [])))
        m2.metric("Hubo refutación", "Sí" if res.get("hubo_contradiccion") else "No")
        m3.metric("Tiempo", f"{res.get('segundos', 0)}s")

        cambiaron = res.get("cambiaron_de_opinion") or []
        if cambiaron:
            st.info("🔄 Cambiaron de postura al leer a los demás: "
                    + ", ".join(cambiaron) + ". Señal de deliberación real.")

        st.markdown("---")
        st.markdown(res.get("entregable", ""))
        st.markdown("---")

        with st.expander("🔍 Ver cómo se deliberó (posturas y refutaciones)"):
            for rol, d in res.get("posturas", {}).items():
                rev = res.get("revisiones", {}).get(rol, {})
                st.markdown(f"#### {rol}")
                st.markdown(f"**Postura inicial:** {d.get('postura','')}")
                if rev.get("postura_final"):
                    st.markdown(f"**Tras leer a los otros:** {rev.get('postura_final')}")
                if d.get("discrepancia_con_cliente"):
                    st.warning(f"Discrepa del cliente: {d['discrepancia_con_cliente']}")
                if d.get("supuestos"):
                    st.caption("Supuestos: " + "; ".join(d["supuestos"]))
                if d.get("riesgos"):
                    st.caption("Riesgos: " + "; ".join(d["riesgos"]))
                for r in rev.get("refuto", []) or []:
                    st.markdown(f"> 🔁 Le refuta a **{r.get('a_quien','')}**: "
                                f"{r.get('por_que_esta_mal','')}")
                st.markdown("---")

        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ Descargar entregable",
                               data=res.get("entregable", ""),
                               file_name="mesa-ia-jandrext.md",
                               mime="text/markdown",
                               use_container_width=True)
        with c2:
            if st.button("🧠 Nueva consulta", type="primary", use_container_width=True):
                _reset()
                st.rerun()
