import streamlit as st
import pandas as pd
import pdfplumber
import google.generativeai as genai
import json
from datetime import datetime
import io
import time
import re
from pypdf import PdfReader

# --- 1. CONFIGURACIÓN VISUAL (CON TU LOGO) ---
# Aquí configuramos que el icono de la pestaña sea tu imagen
st.set_page_config(page_title="Risk Credifamilia AI", page_icon="logo.png", layout="wide")

# Ocultar marcas de agua de Streamlit
st.markdown("""
    <style>
    .stDeployButton {display:none;}
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# Cabecera con Logo y Título
col_logo, col_texto = st.columns([1, 7])
with col_logo:
    try:
        st.image("logo.png", width=110)
    except:
        st.write("🛡️") # Emoji de respaldo si no carga la imagen
with col_texto:
    st.markdown("# Risk Credifamilia AI: Auditoría & Compliance 360°")
    st.caption("Plataforma de Validación Documental y SARLAFT")

# --- 2. BARRA LATERAL ---
with st.sidebar:
    st.header("🔐 Configuración")
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ Licencia Activa")
    else:
        api_key = st.text_input("API KEY:", type="password")
        if not api_key:
            st.warning("⚠️ Ingrese su Llave")
    
    st.divider()
    st.info("Modo: Análisis Forense + Extracción Total")
    
    if st.button("🔄 Nuevo Análisis"):
        st.rerun()

# --- 3. LÓGICA FORENSE (CSI: Hoja por Hoja) ---
def auditoria_hoja_por_hoja(archivo_pdf):
    reporte = { "adulterado": False, "paginas_afectadas": [], "log": [], "fecha_documento": None }
    meses = { "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06", "julio": "07", "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12" }

    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            for i, page in enumerate(pdf.pages):
                num_pag = i + 1
                texto = page.extract_text() or ""
                
                # Regex flexible para encontrar el PIN (acepta Pin No, Pin Numero, Pin #, etc.)
                match_pin = re.search(r"Pin\s*(?:N[oú]mero|No\.?|Nro\.?|#)?\s*:?\s*(\d+)", texto, re.IGNORECASE)
                
                # Regex para la fecha de impresión
                match_fecha = re.search(r"Impreso el\s+(\d{1,2})\s+de\s+([A-Za-z]+)\s+de\s+(\d{4})", texto, re.IGNORECASE)

                if match_pin and match_fecha:
                    pin = match_pin.group(1).strip()
                    dia = match_fecha.group(1).zfill(2)
                    mes_txt = match_fecha.group(2).lower()
                    anio = match_fecha.group(3)
                    
                    # Guardamos la fecha para validar vencimiento luego
                    if reporte["fecha_documento"] is None:
                        reporte["fecha_documento"] = f"{dia}-{meses.get(mes_txt,'00')}-{anio}"

                    # LA REGLA DE ORO: AAMMDD
                    mes_num = meses.get(mes_txt, "00")
                    anio_corto = anio[-2:] 
                    prefijo_esperado = f"{anio_corto}{mes_num}{dia}"
                    
                    if not pin.startswith(prefijo_esperado):
                        reporte["adulterado"] = True
                        reporte["paginas_afectadas"].append(num_pag)
                        reporte["log"].append(f"❌ PÁG {num_pag}: PIN ({pin}) no coincide con fecha ({dia}/{mes_txt}/{anio}).")
                    else:
                        reporte["log"].append(f"✅ PÁG {num_pag}: PIN OK")
                
                elif match_fecha and not match_pin:
                    reporte["log"].append(f"⚠️ PÁG {num_pag}: Fecha visible pero SIN PIN.")
    except Exception as e:
        reporte["log"].append(f"Error lectura: {str(e)}")
    return reporte

def analisis_metadatos(archivo_bytes):
    res = {"adulterado": False, "sw": "Desconocido"}
    try:
        reader = PdfReader(archivo_bytes)
        meta = reader.metadata
        if meta:
            sw = (meta.get("/Producer", "") + " " + meta.get("/Creator", "")).lower()
            res["sw"] = sw
            # Software de edición prohibido
            blacklist = ["word", "office", "ilovepdf", "smallpdf", "photoshop", "gimp", "canva", "nitro", "phantompdf"]
            for p in blacklist:
                if p in sw: res["adulterado"] = True
    except: pass
    return res

# --- 4. IA (MODELO FLASH 1.5) ---
def obtener_mejor_modelo(key):
    genai.configure(api_key=key)
    return genai.GenerativeModel('gemini-1.5-flash'), "Flash ⚡"

def analizar_riesgo_total(archivo_pdf, modelo):
    texto = ""
    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            for page in pdf.pages: texto += (page.extract_text() or "") + "\n"
    except Exception as e: return None, str(e)

    reglas_juridicas = """
    - PATRIMONIO DE FAMILIA / AFECTACIÓN A VIVIENDA FAMILIAR
    - USUFRUCTO / USO Y HABITACIÓN / SERVIDUMBRE
    - HIPOTECA / EMBARGO / CONDICIÓN RESOLUTORIA
    """
    reglas_sarlaft = """
    - ADJUDICACIÓN POR EXPROPIACION / EXPROPIACIÓN
    - EXTINCIÓN DEL DERECHO DE DOMINIO / RESTITUCIÓN
    - LAVADO DE ACTIVOS / TESTAFERRATO / ENRIQUECIMIENTO ILÍCITO
    - TOMA DE POSESIÓN / MEDIDA CAUTELAR / SANEAMIENTO FALSA TRADICIÓN
    """

    prompt = f"""
    Eres un Auditor Forense Inmobiliario.
    
    MISIÓN 1: EXTRACCIÓN DETALLADA DE PERSONAS (MODO BASE DE DATOS)
    Extrae TODAS las personas naturales y jurídicas. Desglosa los datos EXACTAMENTE en estas columnas:
    - "Tipo_Documento": CC, NIT, TI, CE o "No Registra".
    - "Numero_Documento": Solo el número (sin puntos, sin dígito de verificación si es NIT).
    - "Nombre": Nombre completo o Razón Social (Limpio).
    - "Rol": Propietario, Banco, Acreedor, Juez, Demandante.
    - "Ubicacion": Sección del documento (Anotaciones, Complementación, Salvedades).
    - "Anotacion": Número de la anotación (Ej: "5"). Si es Complementación pon "N/A".

    MISIÓN 2: HISTORIAL JURÍDICO DETALLADO (Reglas: {reglas_juridicas})
    Extrae un LISTADO de cada hallazgo jurídico encontrado, indicando:
    - "Concepto": Ej: Hipoteca, Embargo, Patrimonio de Familia.
    - "Estado": "VIGENTE" (o ABIERTA) si está activo, "CANCELADO" (o CERRADA) si ya se levantó.
    - "Anotacion": Número de la anotación donde se constituyó.
    - "Detalle": Breve descripción (Ej: "A favor de Davivienda").

    MISIÓN 3: HISTORIAL SARLAFT DETALLADO (Reglas: {reglas_sarlaft})
    Extrae un LISTADO de cada hallazgo SARLAFT, indicando Concepto, Estado, Anotación y Detalle.

    MISIÓN 4: FLIP (< 12 meses) y Falsa Tradición.

    JSON RESPUESTA:
    {{
      "municipio": "Ciudad",
      "historial_juridico": [
          {{ "Concepto": "Hipoteca", "Estado": "VIGENTE", "Anotacion": "10", "Detalle": "Hipoteca Abierta a favor de Banco X" }}
      ],
      "historial_sarlaft": [
          {{ "Concepto": "Extinción Dominio", "Estado": "CANCELADO", "Anotacion": "3", "Detalle": "Medida levantada" }}
      ],
      "alerta_flip": "SI/NO",
      "falsa_tradicion": "SI/NO",
      "personas_completo": [ 
          {{ "Tipo_Documento": "CC", "Numero_Documento": "123", "Nombre": "JUAN", "Rol": "Prop", "Ubicacion": "Anot", "Anotacion": "1" }} 
      ]
    }}
    TEXTO: {texto[:30000]} 
    """
    
    try:
        response = modelo.generate_content(prompt)
        limpio = response.text.replace("```json", "").replace("```", "").strip()
        if "{" in limpio:
            ini, fin = limpio.find("{"), limpio.rfind("}") + 1
            limpio = limpio[ini:fin]
        return json.loads(limpio), None
    except Exception as e: return None, str(e)

# --- 5. CÁLCULO SCORES ---
def calcular_scores(datos, rep_pag, rep_meta):
    s_jur, r_jur = 100, []
    s_sarl, r_sarl = 100, []

    # 1. Forense
    if rep_pag["adulterado"] or rep_meta["adulterado"]:
        s_jur = 0; s_sarl = 0
        r_jur.append("DOCUMENTO ADULTERADO"); r_sarl.append("🚨 FRAUDE DOCUMENTAL")
    
    # 2. Jurídico
    hist_jur = datos.get("historial_juridico", [])
    vigentes_jur = [x for x in hist_jur if "VIGENTE" in x.get("Estado", "").upper() or "ABIERTA" in x.get("Estado", "").upper()]
    
    embargos = [x for x in vigentes_jur if "EMBARGO" in x.get("Concepto", "").upper()]
    otros_grav = [x for x in vigentes_jur if "HIPOTECA" in x.get("Concepto", "").upper() or "GRAVAMEN" in x.get("Concepto", "").upper()]
    limitaciones = [x for x in vigentes_jur if any(k in x.get("Concepto", "").upper() for k in ["PATRIMONIO", "AFECTACION", "USUFRUCTO"])]

    if embargos: 
        s_jur -= 50; r_jur.append(f"⛔ {len(embargos)} Embargos Vigentes")
    elif otros_grav: 
        s_jur -= 20; r_jur.append(f"⚠️ {len(otros_grav)} Hipotecas/Gravámenes Vigentes")
    
    if limitaciones: 
        s_jur -= 20; r_jur.append(f"🔒 {len(limitaciones)} Limitaciones Vigentes")
    
    if datos.get("falsa_tradicion") == "SI": 
        s_jur -= 30; r_jur.append("🚫 Falsa Tradición")
    
    if s_jur < 0: s_jur = 0

    # 3. Sarlaft
    hist_sarl = datos.get("historial_sarlaft", [])
    vigentes_sarl = [x for x in hist_sarl if "VIGENTE" in x.get("Estado", "").upper()]
    
    if vigentes_sarl: 
        s_sarl = 0; r_sarl.append(f"🔥 ALERTA LISTAS: {len(vigentes_sarl)} Hallazgos Activos")
    
    if "SI" in str(datos.get("alerta_flip", "NO")).upper(): 
        s_sarl -= 30; r_sarl.append("Alerta Flip")
    
    # Vencimiento
    try:
        f_txt = rep_pag.get("fecha_documento")
        if f_txt:
            dias = (datetime.now() - datetime.strptime(f_txt, "%d-%m-%Y")).days
            if dias > 30: s_sarl -= 20; r_sarl.append(f"Vencido ({dias} días)")
    except: pass
    if s_sarl < 0: s_sarl = 0

    return s_jur, r_jur, s_sarl, r_sarl

# --- 6. GENERADOR EXCEL ---
def generar_excel_completo(datos, sj, rj, ss, rs, forense_log):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Dashboard
        pd.DataFrame({
            "Fecha": [datetime.now().strftime("%Y-%m-%d")],
            "Juridico": [sj], "SARLAFT": [ss],
            "Alertas Jur": [str(rj)], "Alertas SARLAFT": [str(rs)],
            "Forense": ["ADULTERADO" if sj==0 else "OK"]
        }).to_excel(writer, sheet_name='Dashboard', index=False)
        
        # PERSONAS LIMPIAS
        per = pd.DataFrame(datos.get("personas_completo", []))
        if not per.empty:
            columnas_orden = ["Tipo_Documento", "Numero_Documento", "Nombre", "Rol", "Ubicacion", "Anotacion"]
            for c in columnas_orden:
                if c not in per.columns: per[c] = ""
            per = per[columnas_orden]
            per = per.drop_duplicates(subset=["Numero_Documento", "Nombre"], keep="first")
            per["Estado_Inspektor"] = "Pendiente Validar"
            per.to_excel(writer, sheet_name='Base_Personas_Inspektor', index=False)
        
        # HISTORIALES
        df_j = pd.DataFrame(datos.get("historial_juridico", []))
        if not df_j.empty: df_j.to_excel(writer, sheet_name='Historial_Juridico', index=False)

        df_s = pd.DataFrame(datos.get("historial_sarlaft", []))
        if not df_s.empty: df_s.to_excel(writer, sheet_name='Historial_Sarlaft', index=False)

        # LOG FORENSE
        pd.DataFrame(forense_log, columns=["Log"]).to_excel(writer, sheet_name='Log_Forense', index=False)
    return output.getvalue()

# --- 7. INTERFAZ PRINCIPAL ---
uploaded_file = st.file_uploader("Sube el PDF (CTL)", type=["pdf"])

if uploaded_file:
    if st.button("🚀 Ejecutar Análisis 360°", type="primary"):
        if not api_key:
            st.error("❌ Falta la API KEY")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Pasos de análisis
            status_text.text("🔍 Fase 1: Escaneando PIN vs Fechas (CSI)...")
            bytes_forense = io.BytesIO(uploaded_file.getvalue())
            bytes_meta = io.BytesIO(uploaded_file.getvalue())
            rep_pag = auditoria_hoja_por_hoja(uploaded_file)
            progress_bar.progress(30)
            
            status_text.text("💾 Fase 2: Analizando Metadatos del PDF...")
            rep_meta = analisis_metadatos(bytes_meta)
            progress_bar.progress(50)
            
            status_text.text("🤖 Fase 3: IA Extrayendo Historial Completo...")
            modelo, _ = obtener_mejor_modelo(api_key)
            datos, error = analizar_riesgo_total(uploaded_file, modelo)
            progress_bar.progress(90)
            
            if error:
                st.error("Error en IA"); st.warning(error)
            elif datos:
                sj, rj, ss, rs = calcular_scores(datos, rep_pag, rep_meta)
                progress_bar.progress(100)
                status_text.text("✅ Análisis Completado")
                time.sleep(1)
                status_text.empty(); progress_bar.empty()
                
                st.divider()
                
                # ALERTA DE FRAUDE
                if rep_pag["adulterado"] or rep_meta["adulterado"]:
                    st.error("🚨 FRAUDE DETECTADO")
                    with st.expander("Evidencia Forense"):
                        st.write(rep_pag["log"])
                        st.write(f"Software: {rep_meta['sw']}")
                else:
                    st.success("✅ Documento Auténtico (PIN Válido)")

                # SCORES
                c1, c2 = st.columns(2)
                with c1:
                    st.metric("⚖️ JURÍDICO", f"{sj}/100")
                    if rj: 
                        for r in rj: st.error(f"{r}")
                    else: st.info("Sin alertas graves")
                with c2:
                    st.metric("🕵️ SARLAFT", f"{ss}/100")
                    if rs: 
                        for r in rs: st.error(f"{r}")
                    else: st.info("Cumplimiento OK")

                st.divider()
                
                # VISUALIZACIÓN DE RESULTADOS
                df_personas_raw = pd.DataFrame(datos.get("personas_completo", []))
                if not df_personas_raw.empty:
                    df_personas_clean = df_personas_raw.drop_duplicates(subset=["Numero_Documento", "Nombre"], keep="first")
                else: df_personas_clean = df_personas_raw

                t1, t2, t3 = st.tabs(["👥 Personas (Inspektor)", "⚖️ Historial Jurídico", "🕵️ Historial SARLAFT"])
                
                with t1:
                    st.info(f"Registros Únicos Consolidados: {len(df_personas_clean)}")
                    st.dataframe(df_personas_clean, use_container_width=True)
                
                with t2:
                    df_j = pd.DataFrame(datos.get("historial_juridico", []))
                    if not df_j.empty: st.dataframe(df_j, use_container_width=True)
                    else: st.info("No se encontraron afectaciones jurídicas.")
                
                with t3:
                    df_s = pd.DataFrame(datos.get("historial_sarlaft", []))
                    if not df_s.empty: st.dataframe(df_s, use_container_width=True)
                    else: st.info("No se encontraron registros SARLAFT.")

                # DESCARGA
                st.download_button(
                    "📥 Descargar Reporte Final (Excel)",
                    data=generar_excel_completo(datos, sj, rj, ss, rs, rep_pag["log"]),
                    file_name="Reporte_Credifamilia_360.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )