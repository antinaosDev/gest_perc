import time
import os
import pandas as pd
import streamlit as st
import pyperclip
import altair as alt  # Librería de gráficos de alto rendimiento
from datetime import datetime, timedelta
from groq import Groq # Importamos la librería de IA
import requests # Para llamadas API robustas
import re # IMPORTANTE: Para limpiar las etiquetas <think>
import json # NECESARIO: Para leer las credenciales y el contador JSON
import tempfile # NECESARIO PARA EL PDF
from fpdf import FPDF # NECESARIO PARA EL PDF

# Librerías de Automatización
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

# -----------------------------------------------------------------------------
# 0. CONSTANTES DE LOCALIZACIÓN Y CONFIGURACIÓN
# -----------------------------------------------------------------------------
MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}
DIAS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
}

# === DATOS DE ARRANQUE (BOOTSTRAP) ===
MASTER_ACCOUNT_ID = "cuenta_some" 
URL_ADMIN_MASTER = "https://docs.google.com/spreadsheets/d/1UkY4sTIalaHhJGgBBPyelgcxU3ebFX-NYa74c2qdviw/edit?usp=sharing"

# === TUS IMÁGENES POR DEFECTO (RESPALDO DE SEGURIDAD) ===
DEFAULT_LOGO_ALAIN = "https://drive.google.com/file/d/1QyEf4sN2lMxaBOOY8asFDTYFxELcT_rR/view?usp=sharing"
DEFAULT_LOGO_NOTI = "https://drive.google.com/file/d/14GQkoC_ykLs6BPK75FQDiCrbQ8Xj9r4b/view?usp=sharing"

# CREDENCIALES BOOTSTRAP (Fijas)
try:
    BOOTSTRAP_CREDS = dict(st.secrets["gcp_service_account"])
except Exception:
    BOOTSTRAP_CREDS = {}

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE UTILIDAD Y BACKEND
# -----------------------------------------------------------------------------

def procesar_imagen_drive(url_drive, creds_dict):
    """Procesa URLs de Google Drive para obtener contenido binario de imágenes."""
    if not url_drive or len(url_drive) < 10: return None
    file_id = None
    patterns = [r'/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    for pattern in patterns:
        match = re.search(pattern, url_drive)
        if match:
            file_id = match.group(1)
            break
    if not file_id: return None
    public_download_url = f"https://drive.google.com/uc?export=view&id={file_id}"
    try:
        response = requests.get(public_download_url, timeout=5)
        if response.status_code == 200: return response.content 
    except: pass
    try:
        scopes = ['https://www.googleapis.com/auth/drive.readonly']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        creds.refresh(Request()) 
        headers = {"Authorization": f"Bearer {creds.token}"}
        api_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        response = requests.get(api_url, headers=headers, timeout=5)
        if response.status_code == 200: return response.content
    except: pass
    return public_download_url

def load_app_configuration(account_id):
    """Carga la configuración dinámica desde Google Sheets (Admin Master)."""
    config = {
        'valido': False, 'mensaje': '', 'datos': {}, 'credenciales_finales': None, 
        'licencia': {}, 'uso_ia_actual': 0, 'row_index': -1, 'templates': {}, 
        'imagenes': {'LOGO_ALAIN': None, 'LOGO_NOTI': None} 
    }
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
        records = sheet_admin.get_all_records()
        target_row = None
        row_idx = -1
        for idx, item in enumerate(records):
            if str(item['CUENTA']) == account_id:
                target_row = item
                row_idx = idx + 2 
                break
        if not target_row:
            config['mensaje'] = f"Cuenta '{account_id}' no encontrada en Admin."
            return config

        config['row_index'] = row_idx
        estado_app = str(target_row.get('ESTADO_APP', 'INACTIVO')).upper().strip()
        estado_ia = str(target_row.get('ESTADO_IA', 'GRATIS')).upper().strip()
        
        try: limite_gratis_conf = int(target_row.get('LIMITE_GRATIS', 2))
        except: limite_gratis_conf = 2
        try: limite_pro_conf = int(target_row.get('LIMITE_PRO', 5))
        except: limite_pro_conf = 5
        
        limite = limite_pro_conf if estado_ia == 'PRO' else limite_gratis_conf
        activo = True if estado_app == 'ACTIVO' else False
        config['licencia'] = {'activo': activo, 'plan': estado_ia, 'limite': limite}

        if not activo:
            config['mensaje'] = "La cuenta está desactivada administrativamente."
            return config

        usos_raw = target_row.get('USOS_IA', '')
        hoy_str = datetime.now().strftime("%d/%m/%Y")
        contador_calculado = 0
        try:
            if isinstance(usos_raw, str) and "{" in usos_raw:
                datos_uso = json.loads(usos_raw)
                if datos_uso.get('fecha') == hoy_str:
                    contador_calculado = int(datos_uso.get('contador', 0))
            else: contador_calculado = 0
        except: contador_calculado = 0
        config['uso_ia_actual'] = contador_calculado

        config['templates']['MSG_AGEND'] = str(target_row.get('MENSAJE_AGEND', '')).strip()
        config['templates']['MSG_REAGEND'] = str(target_row.get('MENSAJE_REAGEND', '')).strip()
        config['templates']['PROMPT'] = str(target_row.get('PROMPT', '')).strip()
        
        config['datos']['GROQ_API_KEY'] = str(target_row.get('GROQ_API_KEY', '')).strip()
        config['datos']['URL_SHEET'] = str(target_row.get('URL_SHEET', '')).strip()
        
        cred_raw = target_row.get('CREDENTIAL_DICT', '')
        if isinstance(cred_raw, dict): config['credenciales_finales'] = cred_raw
        elif isinstance(cred_raw, str) and len(cred_raw) > 10:
            try: config['credenciales_finales'] = json.loads(cred_raw)
            except: config['credenciales_finales'] = BOOTSTRAP_CREDS
        else: config['credenciales_finales'] = BOOTSTRAP_CREDS

        url_logo_alain = str(target_row.get('LOGO_ALAIN', '')).strip() 
        url_logo_noti = str(target_row.get('LOGO_NOTI', '')).strip()    
        if len(url_logo_alain) < 5: url_logo_alain = DEFAULT_LOGO_ALAIN
        if len(url_logo_noti) < 5: url_logo_noti = DEFAULT_LOGO_NOTI

        config['imagenes']['LOGO_ALAIN'] = procesar_imagen_drive(url_logo_alain, BOOTSTRAP_CREDS)
        config['imagenes']['LOGO_NOTI'] = procesar_imagen_drive(url_logo_noti, BOOTSTRAP_CREDS)

        config['valido'] = True
            
    except Exception as e:
        config['mensaje'] = f"Error conectando a Admin Master: {e}"
        
    return config

def registrar_consumo_ia(row_index, nuevo_contador):
    """Actualiza el contador de uso de IA en la hoja Admin."""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
        hoy_str = datetime.now().strftime("%d/%m/%Y")
        json_data = json.dumps({"fecha": hoy_str, "contador": nuevo_contador})
        sheet_admin.update_cell(row_index, 8, json_data) 
        return True
    except Exception as e:
        return False

# === CLASE AVANZADA PARA GENERAR PDF (DISEÑO INSTITUCIONAL ALTO CONTRASTE) ===
class PDFReport(FPDF):
    def __init__(self, logo_alain_data, logo_noti_data):
        super().__init__()
        self.logo_alain_data = logo_alain_data
        self.logo_noti_data = logo_noti_data
    
    def header(self):
        # FONDO BLANCO EN CABECERA PARA MAXIMO CONTRASTE CON LOGOS
        self.set_fill_color(255, 255, 255) 
        self.rect(0, 0, 210, 40, 'F')
        
        # Logos (Guardar temporalmente si son bytes)
        if self.logo_noti_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_noti_data)
                logo_path = f.name
            try: self.image(logo_path, 10, 5, 25)
            except: pass
            
        if self.logo_alain_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_alain_data)
                logo_path_2 = f.name
            try: self.image(logo_path_2, 175, 5, 25)
            except: pass

        # Títulos alineados
        self.set_y(10)
        self.set_font('Arial', 'B', 18)
        self.set_text_color(0, 109, 182) # Azul Medio (#006DB6)
        self.cell(0, 8, 'CESFAM CHOLCHOL', 0, 1, 'C')
        
        self.set_font('Arial', '', 12)
        self.set_text_color(15, 37, 87) # Azul Marino (#0F2557)
        self.cell(0, 6, 'REPORTE EJECUTIVO DE GESTIÓN CLÍNICA', 0, 1, 'C')
        
        # Fecha en Español manual
        hoy = datetime.now()
        fecha_str = f"{hoy.day} de {MESES_ES[hoy.month]} del {hoy.year} - {hoy.strftime('%H:%M')}"
        
        self.set_font('Arial', 'I', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Fecha de Emisión: {fecha_str}', 0, 1, 'C')
        
        # Línea divisoria decorativa
        self.set_draw_color(136, 197, 67) # Verde Lima (#88C543)
        self.set_line_width(0.8)
        self.line(10, 38, 200, 38)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Elaborado por el desarrollador: Alain Antinao Sepúlveda | Página {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 14)
        # Azul Marino Institucional (#0F2557)
        self.set_text_color(15, 37, 87)
        self.cell(0, 10, label, 0, 1, 'L')
        self.set_draw_color(0, 109, 182) # Línea Azul
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def kpi_table_row(self, label, value, is_header=False):
        self.set_font('Arial', 'B' if is_header else '', 10)
        fill = 1 if is_header else 0
        if is_header:
             self.set_fill_color(240, 245, 250) # Gris azulado
             self.set_text_color(15, 37, 87)
        else:
             self.set_text_color(50, 50, 50)
             
        self.cell(100, 8, label, 1, 0, 'L', fill)
        self.cell(90, 8, str(value), 1, 1, 'C', fill)
        self.ln()

def generate_pdf_report(df, stats, ai_analysis, logos):
    pdf = PDFReport(logos['LOGO_ALAIN'], logos['LOGO_NOTI'])
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # 1. Resumen Mensual Actual
    pdf.chapter_title("1. Rendimiento Mes Actual")
    pdf.kpi_table_row("Total Pacientes (Mes)", str(stats['total_mes']), True)
    pdf.kpi_table_row("Confirmados (Mes)", str(stats['confirmados_mes']))
    pdf.kpi_table_row("Tasa Confirmación (Mes)", f"{stats['tasa_mes']}%")
    pdf.ln(5)

    # 2. Resumen Global Histórico
    pdf.chapter_title("2. Totales Históricos (Global)")
    pdf.kpi_table_row("Total Pacientes (Histórico)", str(stats['total_global']), True)
    pdf.kpi_table_row("Confirmados (Global)", str(stats['confirmados_global']))
    pdf.kpi_table_row("Cancelados (Global)", str(stats['rechazados_global']))
    pdf.kpi_table_row("Tasa Eficiencia Global", f"{stats['tasa_global']}%")
    pdf.ln(5)

    # 3. Gestión de Disponibilidad
    pdf.chapter_title("3. Gestión de Cupos y Disponibilidad")
    
    if stats['disponibles'] > 0:
        pdf.set_text_color(0, 100, 0) # Verde oscuro
        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 6, f"ALERTA DE OPORTUNIDAD: Se han detectado {stats['disponibles']} cupos disponibles (pacientes que no asistirán) para fechas futuras. Se recomienda activar lista de espera.")
        pdf.set_text_color(0,0,0)
    else:
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 6, "No hay cupos liberados para fechas futuras en este momento. La agenda se mantiene sin cancelaciones anticipadas.")
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 8, "Cola de Envío Pendiente:", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, f"Existen {stats['cola_activa']} mensajes listos para ser enviados en los próximos 2 días.")
    pdf.ln(5)

    # 4. Análisis IA
    pdf.add_page()
    pdf.chapter_title("4. Análisis Estratégico Inteligente (IA)")
    pdf.set_font('Arial', 'I', 9)
    pdf.cell(0, 6, "Análisis generado automáticamente por Inteligencia Artificial basado en datos en tiempo real.", 0, 1)
    pdf.ln(2)
    
    pdf.set_font('Arial', '', 10)
    if ai_analysis:
        # Limpieza robusta de caracteres especiales para FPDF (latin-1 limitations)
        clean_text = ai_analysis.replace('**', '').replace('###', '').replace('*', '-')
        # Reemplazar caracteres problemáticos comunes
        replacements = {
            '“': '"', '”': '"', '‘': "'", '’': "'", '–': '-', '—': '-', '…': '...', 'ñ': 'n', 'Ñ': 'N', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U'
        }
        # FPDF standard fonts don't support UTF-8 properly without specific font files. 
        # Transliteration is safer for standard PDF generation without external font files.
        for k, v in replacements.items():
            clean_text = clean_text.replace(k, v)
            
        try:
            clean_text = clean_text.encode('latin-1', 'replace').decode('latin-1')
        except:
            clean_text = "Error de codificacion en el texto de IA."

        pdf.multi_cell(0, 6, clean_text)
    else:
        pdf.multi_cell(0, 6, "No se pudo generar el análisis detallado en este momento.")

    # Output
    return pdf.output(dest='S').encode('latin-1')

# === EJECUCIÓN DE CARGA AL INICIO ===
APP_CONFIG = load_app_configuration(MASTER_ACCOUNT_ID)

# Configuración de página Streamlit
try:
    st.set_page_config(
        page_title="Medtify | Clinical Data Platform",
        page_icon="🏥", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
except: pass

if not APP_CONFIG['valido']:
    st.error(f"⛔ ERROR DE INICIO: {APP_CONFIG['mensaje']}")
    st.stop()

# === VARIABLES GLOBALES ===
DYNAMIC_CREDS = APP_CONFIG['credenciales_finales']
GROQ_API_KEY = APP_CONFIG['datos']['GROQ_API_KEY']
URL_SHEET = APP_CONFIG['datos']['URL_SHEET']
STATUS_LICENCIA = APP_CONFIG['licencia']
ROW_INDEX_ADMIN = APP_CONFIG['row_index']
CUSTOM_TEMPLATES = APP_CONFIG['templates']
AI_MODEL = "llama-3.3-70b-versatile"
# IMÁGENES (Puede ser Bytes o URL String)
IMG_LOGO_NOTI = APP_CONFIG['imagenes']['LOGO_NOTI']
IMG_LOGO_ALAIN = APP_CONFIG['imagenes']['LOGO_ALAIN']

# Sincronizar session_state
if 'ai_usage' not in st.session_state:
    st.session_state.ai_usage = APP_CONFIG['uso_ia_actual']

if 'ultimo_reporte_ia' not in st.session_state:
    st.session_state.ultimo_reporte_ia = None

# --- LISTAS MAESTRAS DE CLASIFICACIÓN (ROBUSTAS) ---
RESPUESTAS_SI = [
    "sí", "si", "sip", "sii", "siii", "sipo", "sipu", "sipi", "sí, confirmo", "confirmo",
    "confirmado", "confirmada", "confirmadísimo", "confirmadísima", "claro", "claro que sí",
    "por supuesto", "obvio", "obvio que sí", "obviao", "obvio po", "obvio que voy",
    "obvio hermano voy", "de todas maneras", "de todas formas", "de una", "de pana",
    "de pana sí", "de pana voy", "altiro", "altiro sí", "altiro voy", "bacán", "bacán voy",
    "filete", "la raja voy", "pulento", "terrible sí", "terrible filete voy", "ahí estaré",
    "voy", "voy sí", "sí voy", "sí voy a ir", "sí alcanzo", "sí puedo", "puedo ir",
    "confirmo asistencia", "confirmo la hora", "confirmo cita", "asistiré", "llego",
    "llego sí", "llegaré", "cuento con ir", "cualquier cosa llego", "ningún problema",
    "ningún drama", "todo bien", "todo ok", "ok", "okay", "okey", "oki", "okis",
    "dale sí", "dale no más", "vale", "vale sí", "va", "vamos", "yes", "yes bro",
    "simon", "affirmative", "afirmativo", "positivo", "sí, sin falta", "sí, estaré ahí",
    "me sirve", "me acomoda", "está bien", "está perfect", "perfect", "perfecto",
    "excelente", "súper", "super bien", "joya", "joyita", "regio", "maravilloso",
    "ya", "ya sí", "ya bacán", "ya voy", "ya confirmo", "ya estaré", "listo", "lito",
    "listo confirmo", "listoco", "todo listo", "listo entonces", "listo voy",
    "confirmadito", "simonazo", "seeh", "seee", "seeeh", "sehhh", "seee si",
    "vamos pa’ esa", "vamos nomás", "vamo’", "vamo altiro", "✔️", "👍", "👌", "🙌",
    "🤙", "💯", "🔥 voy", "🍀 voy", "✨ sí"
]

RESPUESTAS_NO = [
    "no", "nop", "nope", "noo", "nooo", "noppo", "nopo", "no puedo", "no puedo ir",
    "no voy", "no alcanzo", "no me da", "no me da el tiempo", "no me sirve",
    "no me acomoda", "no estoy disponible", "no podré asistir", "no asistiré", "no iré",
    "no llego", "no estaré", "no me es posible", "me es imposible", "imposible",
    "negativo", "lamentablemente no puedo", "tengo que cancelar", "cancelo", "cancelado",
    "cancelada", "cancelar hora", "cancelar asistencia", "reagendar", "quiero reagendar",
    "necesito reagendar", "necesito otra hora", "cambiar hora", "no puedo a esa hora",
    "no puedo ese día", "no puedo no más", "no me tinca", "no me resulta",
    "hoy no me resulta", "no puedo sorry", "sorry no puedo", "no sorry", "no quiero ir",
    "prefiero no ir", "voy a faltar", "estoy ocupado", "estoy tapado de cosas",
    "estoy enfermo", "estoy enferma", "estoy pal gato", "estoy pa’ la cagá",
    "no tengo tiempo", "no llego ni cagando", "no alcanzo ni al metro", "no será posible",
    "no cacho si pueda", "no estoy en condiciones", "no doy más", "no puedo manejar",
    "mi pega no me deja", "tengo reunión", "no la hago", "no me da la agenda",
    "no lo lograré", "🚫", "❌", "🛑", "🙅", "🙅‍♂️", "🙅‍♀️"
]

# --- LISTAS DESPLEGABLES MAESTRAS ---
LISTA_PROFESIONES = sorted([
    "ASISTENTE SOCIAL", "EDUCADORA", "ENFERMERA(O)", "FONOAUDIOLOGO", "KINESIOLOGO",
    "MATRON(A)", "MEDICO APS", "NUTRICIONISTA", "ODONTOLOGIA APS", "PROCEDIMIENTO",
    "PROFESOR", "PSICOLOGIA", "QUIMICO FARMACEUTICO", "TECNICO ENFERMERIA",
    "TECNICO ODONTOLOGIA", "TECNOLOGO MEDICO", "TERAPEUTA OCUPACIONAL"
])

LISTA_HORAS = [f"{h:02d}:{m:02d}" for h in range(8, 18) for m in (0, 15, 30, 45)]

LISTA_MOTIVOS = sorted([
    "ACCIONES PREVENTIVAS", "ACCIONES REMOTAS", "ADM MEDICAMENTO EV", "CAMPAÑA PAP", "CATEER URINARIO",
    "CONSEJERIA FAMILIAR", "CONSEJERIA INDIVIDUAL", "CONSULTA", "CONSULTA (MADIS)", "CONSULTA ABREVIADA",
    "CONSULTA BREVE", "CONSULTA CONTROL APS", "CONSULTA DIAGNOSTICO ADULTO PRAPS", "CONSULTA FONOAUDIOLOGICA",
    "CONSULTA INDIVIDUAL", "CONSULTA INGRESO", "CONSULTA INGRESO ADULTO MAYOR", "CONSULTA INGRESO DENTAL",
    "CONSULTA INGRESO ECICEP G1 Y G2", "CONSULTA INGRESO ECICEP G3", "CONSULTA KINESICA AGUDA RESPIRATORIA",
    "CONSULTA LACTANCIA MATERNA", "CONSULTA MATRONA", "CONSULTA MORBILIDAD INFANTIL", "CONSULTA NUTRICIONAL 3 AÑOS 6 MESES",
    "CONSULTA NUTRICIONAL 3 MESES", "CONSULTA PERIODONCIA", "CONSULTA PROTESIS REMOVIBLE", "CONSULTA PSICOLOGICA",
    "CONSULTA REGULACION FERTILIDAD", "CONSULTA SALUD MENTAL", "CONSULTA SOCIAL", "CONSULTA TRATAMIENTO GES GESTANTE",
    "CONSULTA URGENCIA", "CONSULTA VACUNATORIO", "CONSULTORIA", "CONTROL", "CONTROL CARDIOVASCULAR",
    "CONTROL ECICEP G1 Y G2", "CONTROL ECICEP G3", "CONTROL ENFERMERIA", "CONTROL FONOAUDIOLOGICO",
    "CONTROL GRUPAL", "CONTROL INDIVIDUAL", "CONTROL NANEAS", "CONTROL ODONTOLOGICO", "CONTROL PERIODONTAL",
    "CONTROL PRENATAL", "CONTROL RESPIRATORIO CRONICO", "CONTROL SALUD INTEGRAL ADOLESCENTE", "CONTROL SALUD INTEGRAL DIADA",
    "CONTROL SALUD INTEGRAL INFANCIA", "CONTROL SALUD INTEGRAL INFANCIA (1 Y 3 MESES)", "CONTROL SALUD INTEGRAL INFANCIA C/ESPE",
    "CONTROL SALUD MENTAL", "CONTROL SALUD SEXUAL Y REPRODUCTIVA", "CURACION MENOR", "CURACIONES AVANZADAS",
    "CURACIONES SIMPLES", "ECOGRAFIA", "ECOGRAFIA OBSTETRICA", "EDUCACION", "EDUCACION GRUPAL", "EDUCACION GRUPAL (MADIS)",
    "EDUCACION INDIVIDUAL", "ELECTROCARDIOGRAMA", "EMP", "EMPAM", "EMPAM SEGUIMIENTO", "EVALUACION - ENTRENAMIENTO AT (REHABILITACION)",
    "EVALUACION INICIAL (REHABILITACION)", "EVALUACION INTERMEDIA (REHABILITACION)", "EXAMEN FUNCIONAL VIII PAR",
    "EXAMEN OCULAR", "FONDO DE OJO", "GESTION ADMINISTRATIVA", "GESTION DE CASO", "HOSPITAL DIGITAL RURAL",
    "HOSPITALIZACION ABREVIADA - INTERVENCION PSICOSOCIAL", "INCLUYE PRESION ARTERIAL", "INGRESO-REINGRESO RESPIRATORIO",
    "INGRESO/EGRESO MAS AMA", "INTERVENCION PSICOSOCIAL", "INTERVENCION PSICOSOCIAL GRUPAL", "INYECTABLE",
    "LAVADO DE OIDOS", "MEMPAM", "MEMPAM SEGUIMIENTO", "OTRAS", "OTRAS INTERVENCIONES", "OTROS CONTROLES",
    "OTROS PROCEDIMIENTOS", "OTROS PROCEDIMIENTOS AUDIOLOGICOS", "OTROS PROCEDIMIENTOS RADIOLOGICOS", "PROCEDIMIENTO - TTO - OTRAS",
    "PSICOTERAPIA INDIVIDUAL", "RADIOGRAFIA", "REEDUCACION GRUPAL", "REFERENCIA ASISTIDA", "REFERENCIA ODONTOLOGICA",
    "REHABILITACION", "REHABILITACION INDIVIDUAL", "REHABILITACION PULMONAR", "SALUD FAMILIAR", "SCREENING PRESION ARTERIAL",
    "TALLER", "TALLER MAS AMA", "TALLER NEP", "TALLER PROMOCION LENGUAJE", "TALLER PROMOCION MOTOR", "TAMIZAJE",
    "TAMIZAJE PRAPS", "TECNICO ENFERMERIA", "TELECONSULTA", "TELEINTERCONSULTA", "TEST DE EJERCICIO", "TEST DE MARCHE",
    "TOMA MUESTRA", "TRABAJO EXTRAMURAL", "TRATAMIENTO ODONTOLOGICO INTEGRAL", "TTO - OTRAS", "VACUNATORIO",
    "VDRL, PR VDRL, SDA SC", "VIDA SANA", "VIDA SANA EDUCACION", "VISITA DOMICILIARIA", "VISITA DOMICILIARIA INTEGRAL",
    "VISITA FARMACEUTICA EN DOMICILIO", "VISITAS DOMICILIARIA"
])

# --- CSS PROFESIONAL (PALETA INSTITUCIONAL APLICADA) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --primary-blue: #006DB6;  /* Azul Medio Institucional */
        --navy-blue: #0F2557;     /* Azul Marino Institucional */
        --success-green: #88C543; /* Verde Lima Institucional */
        --text-dark: #0F2557;     /* Texto principal en Azul Marino */
        --text-gray: #8898AA;
        --bg-light: #F5F7FB;
        --white: #FFFFFF;
        --card-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: var(--bg-light);
        color: var(--text-dark);
    }

    section[data-testid="stSidebar"] {
        background-color: var(--white);
        border-right: 1px solid #E0E6ED;
    }

    .header-container {
        background: var(--white);
        padding: 2rem;
        border-radius: 16px;
        box-shadow: var(--card-shadow);
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-left: 6px solid var(--primary-blue);
    }
    .header-title { font-size: 1.75rem; font-weight: 700; margin: 0; color: var(--text-dark); }
    .header-subtitle { font-size: 0.95rem; color: var(--text-gray); margin-top: 4px; }
    .date-badge { background-color: #F0F2F5; color: var(--primary-blue); padding: 8px 16px; border-radius: 50px; font-weight: 600; font-size: 0.85rem; border: 1px solid #E0E6ED; }

    .metric-container {
        background: var(--white);
        padding: 1.5rem;
        border-radius: 16px;
        box-shadow: var(--card-shadow);
        height: 100%;
        position: relative;
        overflow: hidden;
        transition: transform 0.2s ease;
    }
    .metric-container:hover { transform: translateY(-3px); }
    .metric-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-gray); font-weight: 600; margin-bottom: 8px; }
    .metric-value { font-size: 2.2rem; font-weight: 700; color: var(--text-dark); }
    .metric-icon { position: absolute; top: 1.5rem; right: 1.5rem; font-size: 1.5rem; opacity: 0.2; }
    
    .color-green { color: var(--success-green); }
    .color-orange { color: #FF9F43; }
    .color-blue { color: var(--primary-blue); }

    .stButton > button {
        border-radius: 8px; font-weight: 600; border: none; padding: 0.6rem 1.5rem; transition: all 0.3s ease; width: 100%;
        border: 2px solid #006DB6;
        color: #0F2557;
        background-color: white;
    }
    .stButton > button:hover {
        background-color: #F5F7FB;
        border-color: #88C543;
        color: #006DB6;
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* Primary Button override (if used via type='primary') */
    button[kind="primary"] {
        background-color: #006DB6 !important;
        border-color: #006DB6 !important;
        color: white !important;
    }

    .terminal-window {
        background: var(--navy-blue); /* Fondo Azul Marino para consola */
        border-radius: 12px; padding: 0; box-shadow: var(--card-shadow);
        font-family: 'Consolas', 'Monaco', monospace; overflow: hidden; border: 1px solid var(--primary-blue);
    }
    .terminal-header { background: #0a193d; padding: 8px 16px; display: flex; gap: 6px; border-bottom: 1px solid #1c3570; }
    .terminal-dot { width: 10px; height: 10px; border-radius: 50%; }
    .dot-red { background: #FF5F56; } .dot-yellow { background: #FFBD2E; } .dot-green { background: #27C93F; }
    .terminal-body { padding: 16px; height: 350px; overflow-y: auto; color: #E0E6ED; font-size: 0.85rem; line-height: 1.5; }
    .log-success { color: var(--success-green); } .log-error { color: #FF5F56; } .log-info { color: #4FC3F7; }

    .stDataFrame { background: var(--white); border-radius: 12px; padding: 5px; box-shadow: var(--card-shadow); }
    
    /* Estilo para el reporte de IA */
    .report-container {
        background-color: #ffffff;
        padding: 30px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        margin-top: 20px;
    }
    .report-header {
        border-bottom: 2px solid var(--primary-blue);
        padding-bottom: 10px;
        margin-bottom: 20px;
        color: var(--primary-blue);
        font-weight: 700;
        font-size: 1.2rem;
    }
    
    /* Footer Adjustment */
    img { margin-bottom: 0px; } 

</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. LOGICA DEL NEGOCIO (BACKEND)
# -----------------------------------------------------------------------------

def connect_sheet():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(DYNAMIC_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_SHEET).sheet1, "OK"
    except Exception as e: return None, str(e)

# --- FUNCIÓN DE CARGA ---
@st.cache_data(ttl=15)
def get_data_fresh():
    """Obtiene datos frescos de Google Sheets."""
    sheet, msg = connect_sheet()
    if not sheet: return None
    data = sheet.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    df.columns = df.columns.str.strip()
    
    # === PRE-PROCESAMIENTO AVANZADO PARA ANALITICA BI ===
    try:
        # 0. Determinación de Fecha y Hora Efectiva (Handling Rescheduling)
        # Default a la original
        df['FECHA_EFECTIVA'] = df['FECHA_AGENDADA']
        df['HORA_EFECTIVA'] = df['HORA_AGENDADA']
        
        # Identificar registros reagendados válidos (CAMBIO_DE_HORA='SI' y datos presentes)
        df['CAMBIO_CLEAN'] = df['CAMBIO_DE_HORA'].astype(str).str.strip().str.upper()
        mask_reag = (df['CAMBIO_CLEAN'] == 'SI') & (df['NUEVA_FECHA'].astype(str).str.len() > 5) & (df['HORA_NUEVA_FECHA'].astype(str).str.len() > 2)
        
        # Sobreescribir con datos nuevos donde corresponda
        df.loc[mask_reag, 'FECHA_EFECTIVA'] = df.loc[mask_reag, 'NUEVA_FECHA']
        df.loc[mask_reag, 'HORA_EFECTIVA'] = df.loc[mask_reag, 'HORA_NUEVA_FECHA']

        # 1. Procesamiento de Fechas Efectivas
        df['FECHA_DT'] = pd.to_datetime(df['FECHA_EFECTIVA'], format="%d/%m/%Y", errors='coerce')
        df['NUEVA_FECHA_DT'] = pd.to_datetime(df['NUEVA_FECHA'], format="%d/%m/%Y", errors='coerce') # Mantener para referencia
        
        # 2. Extracción de Hora y Formato AM/PM para Heatmap (Usando Hora Efectiva Limpia)
        
        # Función auxiliar de limpieza
        def clean_time_str(t_str):
            if not isinstance(t_str, str): return str(t_str)
            # Quitar puntos y espacios extra: "8:30 a.m." -> "8:30 am" -> "8:30 AM"
            t_str = t_str.lower().replace('.', '').strip()
            return t_str.upper()

        df['HORA_EFECTIVA_CLEAN'] = df['HORA_EFECTIVA'].apply(clean_time_str)

        # Convertimos a datetime tolerante a errores (intentando formato 12h y 24h)
        temp_dates = pd.to_datetime(df['HORA_EFECTIVA_CLEAN'], format='%I:%M %p', errors='coerce')
        
        # Fallback para formato 24h si el anterior falla
        mask_na = temp_dates.isna()
        if mask_na.any():
             temp_dates_24 = pd.to_datetime(df.loc[mask_na, 'HORA_EFECTIVA_CLEAN'], format='%H:%M', errors='coerce')
             temp_dates = temp_dates.fillna(temp_dates_24)

        df['HORA_INT'] = temp_dates.dt.hour.fillna(-1).astype(int) # 0-23
        df['HORA_LABEL'] = temp_dates.dt.strftime('%I %p').fillna('S/I') # 08 AM, 02 PM
        
        # Legacy support
        df['HORA_SIMPLE'] = df['HORA_AGENDADA'].astype(str).str.split(':').str[0] 
        
        # 3. Normalización de Texto
        df['MOTIVO_CLEAN'] = df['MOTIVO_CONSULTA'].astype(str).str.upper().str.strip()
        df['PROFESION_CLEAN'] = df['PROFESION'].astype(str).str.upper().str.strip()
        df['ESTADO_CLEAN'] = df['ESTADO'].replace('', 'PENDIENTE').fillna('PENDIENTE')

        # 4. Procesamiento Demográfico
        if 'EDAD_ACTUAL' in df.columns:
            df['EDAD_NUM'] = pd.to_numeric(df['EDAD_ACTUAL'], errors='coerce').fillna(0)
        else:
            df['EDAD_NUM'] = 0
        
        # 5. Calculo Días Restantes (Usando FECHA_DT que ahora es la efectiva)
        now = pd.Timestamp.now().normalize()
        if 'FECHA_DT' in df.columns:
            df['DIAS_RESTANTES'] = (df['FECHA_DT'] - now).dt.days.fillna(-999)
            dias_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
            df['DIA_SEMANA_ES'] = df['FECHA_DT'].dt.dayofweek.map(dias_es)
        else:
            df['DIAS_RESTANTES'] = -999
            df['DIA_SEMANA_ES'] = None

        # 6. ESTANDARIZACION DE CONFIRMACIONES
        df['STATUS_CONFIRMACION'] = 'PENDIENTE'
        if 'CONFIRMA_HORA' in df.columns:
            df.loc[df['CONFIRMA_HORA'].str.contains('CONFIRMADO', na=False), 'STATUS_CONFIRMACION'] = 'CONFIRMADO'
            df.loc[df['CONFIRMA_HORA'].str.contains('NO ASISTIRA', na=False), 'STATUS_CONFIRMACION'] = 'NO ASISTIRA'
        if 'CONFIRMA_REAGEN' in df.columns:
            df.loc[df['CONFIRMA_REAGEN'].str.contains('CONFIRMADO', na=False), 'STATUS_CONFIRMACION'] = 'CONFIRMADO (R)'
            df.loc[df['CONFIRMA_REAGEN'].str.contains('NO ASISTIRA', na=False), 'STATUS_CONFIRMACION'] = 'NO ASISTIRA (R)'
        
        # 7. ESTADO DEL PACIENTE UNIFICADO
        df['ESTADO_REAL'] = 'PENDIENTE'
        df.loc[df['ESTADO'].str.contains('OK', na=False), 'ESTADO_REAL'] = 'NOTIFICADO'
        if 'ESTADO_REA' in df.columns:
            df.loc[df['ESTADO_REA'].str.contains('OK', na=False), 'ESTADO_REAL'] = 'NOTIFICADO'
        df.loc[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO'), 'ESTADO_REAL'] = 'CONFIRMADO'

    except Exception as e:
        pass 
        
    return df

def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--remote-debugging-port=9222")
    user_data = os.path.join(os.getcwd(), "medtify_session")
    options.add_argument(f"--user-data-dir={user_data}")
    try: return webdriver.Chrome(options=options)
    except: return None

def esperar_login_qr(driver):
    wait = WebDriverWait(driver, 120)
    try:
        wait.until(EC.presence_of_element_located((By.ID, "side")))
        return True
    except TimeoutException: return False

def calcular_dias(fecha_texto):
    try:
        fecha_cita = datetime.strptime(str(fecha_texto).strip(), "%d/%m/%Y").date()
        hoy = datetime.now().date()
        return (fecha_cita - hoy).days
    except: return -999

# === FUNCIÓN PARA LLAMADA A IA (GROQ) CON PROMPT DINÁMICO ===
def generar_analisis_clinico(df):
    try:
        client = Groq(api_key=GROQ_API_KEY)
        
        # --- 1. CÁLCULO DE VARIABLES ESTADÍSTICAS ---
        fecha_hoy = datetime.now().strftime("%d/%m/%Y")
        total_pacientes = len(df)
        
        # Demografía
        avg_edad = round(df['EDAD_NUM'].mean(), 1) if 'EDAD_NUM' in df.columns else 0
        pacientes_adulto_mayor = len(df[df['EDAD_NUM'] >= 65]) if 'EDAD_NUM' in df.columns else 0
        dist_genero = df['GENERO'].value_counts().head(3).to_dict() if 'GENERO' in df.columns else {}
        
        # Operativa y Gestión de Citas
        notificados = len(df[df['ESTADO'].str.contains('OK', na=False)])
        confirmados = len(df[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
        cancelados = len(df[df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')]) # Nuevos datos de rechazo
        pendientes_respuesta = notificados - confirmados - cancelados
        
        # Tasa de Conversión (Confirmados / Total Notificados)
        tasa_conf = int((confirmados / notificados) * 100) if notificados > 0 else 0
        
        # Cupos Recuperables (Cancelados con fecha futura)
        cupos_recuperables = 0
        if 'DIAS_RESTANTES' in df.columns:
            cupos_recuperables = len(df[
                (df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')) & 
                (df['DIAS_RESTANTES'] > 0)
            ])

        # Gestión de Demanda
        top_prof_orig = df['PROFESION'].value_counts().head(3).to_dict()
        reasig_pendientes = len(df[(df['CAMBIO_DE_HORA'] == 'SI') & (df['ESTADO_REA'] == '')])
        errores_notif = len(df[df['ESTADO'].str.contains('ERROR', na=False)])
        
        # Recurrencia (Proxy de cronicidad)
        ruts_unicos = df['RUT'].nunique() if 'RUT' in df.columns else 0
        recurrencia = total_pacientes - ruts_unicos

        # --- 2. CONSTRUCCIÓN DEL PROMPT ESTRATÉGICO ---
        stats_for_prompt = {
            "fecha_hoy": fecha_hoy,
            "total_pacientes": total_pacientes,
            "avg_edad": avg_edad,
            "pacientes_adulto_mayor": pacientes_adulto_mayor,
            "dist_genero": dist_genero,
            "confirmados": confirmados,
            "cancelados": cancelados,
            "pendientes_respuesta": pendientes_respuesta,
            "tasa_conf": tasa_conf,
            "cupos_recuperables": cupos_recuperables,
            "reasig_pendientes": reasig_pendientes,
            "errores_notif": errores_notif,
            "top_prof_orig": top_prof_orig,
            "recurrencia": recurrencia
        }

        # PROMPT ACTUALIZADO
        prompt = f"""
        Actúa como el **Director de Estrategia Clínica y Operaciones del CESFAM Cholchol**. 
        Tu objetivo es maximizar la "Eficiencia del Recurso Médico" mediante Yield Management (Gestión de Cupos) para el día {stats_for_prompt['fecha_hoy']}.
        
        TABLERO DE MANDO INTEGRAL (KPIs EN TIEMPO REAL):
        
        1. 👥 **Perfil del Paciente & Brecha:**
           - Edad Promedio: {stats_for_prompt['avg_edad']} años.
           - Adultos Mayores (65+): {stats_for_prompt['pacientes_adulto_mayor']} (Prioridad en contactabilidad asistida).
           - Género: {stats_for_prompt['dist_genero']}.
           
        2. 📉 **Funnel de Asistencia (Conversión):**
           - Carga Total Agenda: {stats_for_prompt['total_pacientes']}.
           - ✅ Confirmados (Seguros): {stats_for_prompt['confirmados']} (Tasa Respuesta: {stats_for_prompt['tasa_conf']}%).
           - ❌ Cancelaciones Explícitas: {stats_for_prompt['cancelados']} (Cupos liberados).
           - ❓ Incertidumbre (Sin Respuesta): {stats_for_prompt['pendientes_respuesta']} (Riesgo latente de No-Show).
           
        3. ♻️ **Gestión de Activos (Cupos):**
           - 💎 **CUPOS RECUPERABLES (Oportunidad de Oro):** {stats_for_prompt['cupos_recuperables']} citas canceladas anticipadamente para fechas futuras.
           - 🛡️ Demanda en Espera (Reagendamientos): {stats_for_prompt['reasig_pendientes']} pacientes esperando cupo.
           
        4. ⚠️ **Fricción Operativa:**
           - Errores de Contacto: {stats_for_prompt['errores_notif']}.
           - Recurrencia: {stats_for_prompt['recurrencia']} (Pacientes policonsultantes/crónicos).

        INSTRUCCIONES DE ANÁLISIS ESTRATÉGICO (Genera 3 párrafos concisos):

        **EJE 1: DIAGNÓSTICO DE ADHERENCIA Y RIESGO**
        Analiza la Tasa de Confirmación ({stats_for_prompt['tasa_conf']}%) frente a la Incertidumbre. Si la incertidumbre es alta (>30%) y hay muchos Adultos Mayores, advierte sobre la "Brecha Digital" y sugiere barrido telefónico manual inmediato.

        **EJE 2: ESTRATEGIA DE "YIELD MANAGEMENT" (LLENADO DE CUPOS)**
        Cruza los datos: Tienes {stats_for_prompt['cupos_recuperables']} cupos liberados y {stats_for_prompt['reasig_pendientes']} pacientes en cola. 
        Define una táctica agresiva para mover a los pacientes de la lista de espera a esos huecos vacíos. Si {stats_for_prompt['cupos_recuperables']} > 0, esto es una ALERTA DE OPORTUNIDAD POSITIVA.

        **EJE 3: DIRECTIVAS TÁCTICAS PARA EL EQUIPO SOME**
        Redacta 3 órdenes claras y priorizadas en formato lista:
        1. **Rescate de Cupos:** Instrucción específica sobre qué hacer con los {stats_for_prompt['cupos_recuperables']} espacios libres.
        2. **Gestión de Incertidumbre:** Qué hacer con los {stats_for_prompt['pendientes_respuesta']} que leyeron pero no respondieron.
        3. **Foco Clínico:** Recomendación basada en las profesiones más demandadas ({list(stats_for_prompt['top_prof_orig'].keys())}).
        
        Tono: Ejecutivo, Directivo, Resolutivo. Sin saludos genéricos.
        """
        
        completion = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=850
        )
        # Limpieza de tags de pensamiento (para modelos que razonan)
        content = completion.choices[0].message.content
        content_clean = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return content_clean

    except Exception as e:
        return f"⚠️ Error en análisis IA: {str(e)}"

def enviar_mensaje_wsp(driver, numero, mensaje):
    wait = WebDriverWait(driver, 10)
    action = ActionChains(driver)
    try: action.send_keys(Keys.ESCAPE).perform(); time.sleep(0.5)
    except: pass

    try:
        try: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-icon="new-chat-outline"]')))
        except: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="Nuevo chat"]')))
        btn.click()
        time.sleep(1.0)

        input_drawer = driver.switch_to.active_element
        num_clean = str(numero).replace("+", "").replace(" ", "").strip()
        num_fmt = f"+56{num_clean}" if len(num_clean) == 9 else f"+{num_clean}"
        input_drawer.send_keys(num_fmt)
        time.sleep(2.0)
        input_drawer.send_keys(Keys.ENTER)
        time.sleep(1.0)

        try: 
            msg_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '#main footer div[contenteditable="true"]')))
        except TimeoutException:
            action.send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
            action.send_keys(Keys.ESCAPE).perform()
            time.sleep(1.0)
            return False, "Número Inválido / No tiene WhatsApp"

        msg_box.click()
        pyperclip.copy(mensaje)
        msg_box.send_keys(Keys.CONTROL, "v")
        time.sleep(0.5)
        msg_box.send_keys(Keys.ENTER)
        time.sleep(1)
        return True, "Enviado OK"
    except Exception as e:
        try: action.send_keys(Keys.ESCAPE).perform()
        except: pass
        return False, f"Error: {str(e)}"

# === FUNCIÓN DE MENSAJES DINÁMICOS ===
def get_template(row, tipo):
    # Convertimos la fila a diccionario para usar .format(**row)
    # Aseguramos que todos los valores sean string para evitar errores
    data_row = {k: str(v) for k, v in row.to_dict().items()}
    
    if tipo == "REAGENDAMIENTO":
        custom_msg = CUSTOM_TEMPLATES.get('MSG_REAGEND', '')
        # Si hay mensaje personalizado en el Excel, lo usamos
        if custom_msg and len(custom_msg) > 10:
            try:
                return custom_msg.format(**data_row)
            except:
                pass # Si falla la inyección de variables, pasa al default
        
        # DEFAULT
        return f"""🚨 *REAGENDAMIENTO DE HORA - CESFAM CHOLCHOL* 🚨
Estimado/a {data_row.get('NOMBRE_PACIENTE', '')}:
Por motivos de fuerza mayor, es necesario reprogramar su hora médica. 
Lamentamos cualquier inconveniente que esto pueda causarle y agradecemos su comprensión.

📅 Nueva fecha: {data_row.get('NUEVA_FECHA', '')}
⏰ Nueva hora: {data_row.get('HORA_NUEVA_FECHA', '')}
👨‍⚕️ Profesional asignado: {data_row.get('NOM_PROF_REASIG', '')}
📋 Motivo de la consulta: {data_row.get('MOTIVO_CONSULTA_REA', '')}

📍 Lugar: CESFAM Cholchol
✉️ Necesitas cancelar o confirmar tu hora, contáctanos a: cholcholsome@gmail.com

Atentamente,
Equipo CESFAM Cholchol

🤖 Este es un mensaje automático. Si necesitas asistencia personalizada, por favor visita nuestras dependencias."""

    elif tipo == "RECORDATORIO":
        custom_msg = CUSTOM_TEMPLATES.get('MSG_AGEND', '')
        if custom_msg and len(custom_msg) > 10:
            try:
                return custom_msg.format(**data_row)
            except:
                pass 

        # DEFAULT
        return f"""🏥 *RECORDATORIO HORA MÉDICA - CESFAM CHOLCHOL*
Estimado/a {data_row.get('NOMBRE_PACIENTE', '')}:
Le recordamos su próxima atención de salud:

📅 Fecha: {data_row.get('FECHA_AGENDADA', '')}
⏰ Hora: {data_row.get('HORA_AGENDADA', '')}
👨‍⚕️ Profesional: {data_row.get('NOMBRE_PROFESIONAL', '')}
📋 Motivo Consulta: {data_row.get('MOTIVO_CONSULTA', '')}
📍 Lugar: CESFAM Cholchol
✉️ Necesitas cancelar o confirmar tu hora, contáctanos a: cholcholsome@gmail.com

🔔 *Importante:* Llegar 20 min antes.

Atentamente,
Equipo CESFAM Cholchol

🤖 Este es un mensaje automático. Si necesitas asistencia personalizada, por favor visita nuestras dependencias.
699: 
700: 👉 *IMPORTANTE: Responde SI para confirmar tu asistencia.*"""

    return ""

def verificar_respuestas_wsp(driver, numero):
    """
    Versión Robustecida v3.0 (Con clasificación SI/NO)
    """
    wait = WebDriverWait(driver, 15) 
    action = ActionChains(driver)
    
    try: action.send_keys(Keys.ESCAPE).perform(); time.sleep(0.5)
    except: pass

    try:
        # 1. Buscar y abrir chat
        try: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-icon="new-chat-outline"]')))
        except: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="Nuevo chat"]')))
        btn.click()
        time.sleep(1.0)

        input_drawer = driver.switch_to.active_element
        num_clean = str(numero).replace("+", "").replace(" ", "").strip()
        num_fmt = f"+56{num_clean}" if len(num_clean) == 9 else f"+{num_clean}"
        input_drawer.send_keys(num_fmt)
        time.sleep(2.0)
        input_drawer.send_keys(Keys.ENTER)
        
        # Esperar a que cargue el historial del chat
        time.sleep(3.0) 

        # 2. Lógica de Lectura Inteligente
        try:
            # Buscamos TODOS los contenedores de mensajes (filas)
            rows = driver.find_elements(By.CSS_SELECTOR, 'div[role="row"]')
            
            if not rows:
                return "ERROR", "Chat vacío"

            # Tomamos el ÚLTIMO mensaje (el más reciente)
            last_row = rows[-1]
            
            # --- DETECTAR DIRECCIÓN (ENTRANTE VS SALIENTE) ---
            es_mensaje_mio = False
            try:
                # Buscamos cualquier icono de confirmación de lectura
                last_row.find_element(By.CSS_SELECTOR, 'span[data-icon*="msg-"]')
                es_mensaje_mio = True
            except:
                es_mensaje_mio = False # Si no tiene ticks, es un mensaje recibido

            if es_mensaje_mio:
                return "PENDIENTE", "El último mensaje es tuyo"

            # --- EXTRAER TEXTO ---
            try:
                text_element = last_row.find_element(By.CSS_SELECTOR, "span.selectable-text")
                mensaje_texto = text_element.text.strip()
            except:
                # Fallback
                mensaje_texto = last_row.text.strip()

            msg_clean = mensaje_texto.lower()

            # --- LÓGICA DE CLASIFICACIÓN ROBUSTA (Primero NO, luego SI) ---
            
            # 1. Chequeo de Negación/Cancelación (Prioridad Alta)
            for frase in RESPUESTAS_NO:
                if frase in msg_clean:
                    return "NO ASISTIRA", mensaje_texto

            # 2. Chequeo de Confirmación
            for frase in RESPUESTAS_SI:
                if frase in msg_clean:
                    return "CONFIRMADO", mensaje_texto

            # 3. Respuesta no clasificada
            return "AMBIGUO", f"No clasificado: {mensaje_texto}"

        except Exception as e:
            return "ERROR", f"Error analizando chat: {str(e)}"

    except Exception as e:
        try: action.send_keys(Keys.ESCAPE).perform()
        except: pass
        return "ERROR", f"Error general: {str(e)}"

# === CLASE AVANZADA PARA GENERAR PDF (DISEÑO INSTITUCIONAL ALTO CONTRASTE) ===
class PDFReport(FPDF):
    def __init__(self, logo_alain_data, logo_noti_data):
        super().__init__()
        self.logo_alain_data = logo_alain_data
        self.logo_noti_data = logo_noti_data
    
    def header(self):
        # FONDO BLANCO EN CABECERA PARA MAXIMO CONTRASTE CON LOGOS
        self.set_fill_color(255, 255, 255) 
        self.rect(0, 0, 210, 40, 'F')
        
        # Logos (Guardar temporalmente si son bytes)
        if self.logo_noti_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_noti_data)
                logo_path = f.name
            try: self.image(logo_path, 10, 5, 25)
            except: pass
            
        if self.logo_alain_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_alain_data)
                logo_path_2 = f.name
            try: self.image(logo_path_2, 175, 5, 25)
            except: pass

        # Títulos alineados
        self.set_y(10)
        self.set_font('Arial', 'B', 18)
        self.set_text_color(0, 109, 182) # Azul Medio (#006DB6)
        self.cell(0, 8, 'CESFAM CHOLCHOL', 0, 1, 'C')
        
        self.set_font('Arial', '', 12)
        self.set_text_color(15, 37, 87) # Azul Marino (#0F2557)
        self.cell(0, 6, 'REPORTE EJECUTIVO DE GESTIÓN CLÍNICA', 0, 1, 'C')
        
        # Fecha en Español manual
        hoy = datetime.now()
        fecha_str = f"{hoy.day} de {MESES_ES[hoy.month]} del {hoy.year} - {hoy.strftime('%H:%M')}"
        
        self.set_font('Arial', 'I', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Fecha de Emisión: {fecha_str}', 0, 1, 'C')
        
        # Línea divisoria decorativa
        self.set_draw_color(136, 197, 67) # Verde Lima (#88C543)
        self.set_line_width(0.8)
        self.line(10, 38, 200, 38)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Elaborado por el desarrollador: Alain Antinao Sepúlveda | Página {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 14)
        # Azul Marino Institucional (#0F2557)
        self.set_text_color(15, 37, 87)
        self.cell(0, 10, label, 0, 1, 'L')
        self.set_draw_color(0, 109, 182) # Línea Azul
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def kpi_table_row(self, label, value, is_header=False):
        self.set_font('Arial', 'B' if is_header else '', 10)
        fill = 1 if is_header else 0
        if is_header:
             self.set_fill_color(240, 245, 250) # Gris azulado
             self.set_text_color(15, 37, 87)
        else:
             self.set_text_color(50, 50, 50)
             
        self.cell(100, 8, label, 1, 0, 'L', fill)
        self.cell(90, 8, str(value), 1, 1, 'C', fill)
        self.ln()

def generate_pdf_report(df, stats, ai_analysis, logos):
    pdf = PDFReport(logos['LOGO_ALAIN'], logos['LOGO_NOTI'])
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # 1. Resumen Mensual Actual
    pdf.chapter_title("1. Rendimiento Mes Actual")
    pdf.kpi_table_row("Total Pacientes (Mes)", str(stats['total_mes']), True)
    pdf.kpi_table_row("Confirmados (Mes)", str(stats['confirmados_mes']))
    pdf.kpi_table_row("Tasa Confirmación (Mes)", f"{stats['tasa_mes']}%")
    pdf.ln(5)

    # 2. Resumen Global Histórico
    pdf.chapter_title("2. Totales Históricos (Global)")
    pdf.kpi_table_row("Total Pacientes (Histórico)", str(stats['total_global']), True)
    pdf.kpi_table_row("Confirmados (Global)", str(stats['confirmados_global']))
    pdf.kpi_table_row("Cancelados (Global)", str(stats['rechazados_global']))
    pdf.kpi_table_row("Tasa Eficiencia Global", f"{stats['tasa_global']}%")
    pdf.ln(5)

    # 3. Gestión de Disponibilidad
    pdf.chapter_title("3. Gestión de Cupos y Disponibilidad")
    
    if stats['disponibles'] > 0:
        pdf.set_text_color(0, 100, 0) # Verde oscuro
        pdf.set_font('Arial', 'B', 10)
        pdf.multi_cell(0, 6, f"ALERTA DE OPORTUNIDAD: Se han detectado {stats['disponibles']} cupos disponibles (pacientes que no asistirán) para fechas futuras. Se recomienda activar lista de espera.")
        pdf.set_text_color(0,0,0)
    else:
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 6, "No hay cupos liberados para fechas futuras en este momento. La agenda se mantiene sin cancelaciones anticipadas.")
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 8, "Cola de Envío Pendiente:", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, f"Existen {stats['cola_activa']} mensajes listos para ser enviados en los próximos 2 días.")
    pdf.ln(5)

    # 4. Análisis IA
    pdf.add_page()
    pdf.chapter_title("4. Análisis Estratégico Inteligente (IA)")
    pdf.set_font('Arial', 'I', 9)
    pdf.cell(0, 6, "Análisis generado automáticamente por Inteligencia Artificial basado en datos en tiempo real.", 0, 1)
    pdf.ln(2)
    
    pdf.set_font('Arial', '', 10)
    if ai_analysis:
        # Limpieza robusta de caracteres especiales para FPDF (latin-1 limitations)
        clean_text = ai_analysis.replace('**', '').replace('###', '').replace('*', '-')
        # Reemplazar caracteres problemáticos comunes
        replacements = {
            '“': '"', '”': '"', '‘': "'", '’': "'", '–': '-', '—': '-', '…': '...', 'ñ': 'n', 'Ñ': 'N', 'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U'
        }
        for k, v in replacements.items():
            clean_text = clean_text.replace(k, v)
            
        try:
            clean_text = clean_text.encode('latin-1', 'replace').decode('latin-1')
        except:
            clean_text = "Error de codificacion en el texto de IA."

        pdf.multi_cell(0, 6, clean_text)
    else:
        pdf.multi_cell(0, 6, "No se pudo generar el análisis detallado en este momento.")

    # Output
    return pdf.output(dest='S').encode('latin-1')

# -----------------------------------------------------------------------------
# 3. INTERFAZ DE USUARIO (FRONTEND)
# -----------------------------------------------------------------------------

# === VERIFICACIÓN INICIAL DE LICENCIA ===
status = STATUS_LICENCIA

# Inicializar contador de sesión si no existe
if 'ai_usage' not in st.session_state:
    st.session_state.ai_usage = APP_CONFIG['uso_ia_actual']

# === VARIABLE PARA PERSISTENCIA DEL REPORTE ===
if 'ultimo_reporte_ia' not in st.session_state:
    st.session_state.ultimo_reporte_ia = None

# --- SIDEBAR ---
with st.sidebar:
    # Lógica de Logo Dinámico
    if IMG_LOGO_NOTI:
        st.image(IMG_LOGO_NOTI, use_container_width=True)
    else:
        st.markdown("<h2 style='color:#006DB6;text-align:center;'>Medtify</h2>", unsafe_allow_html=True)
    
    st.markdown("### Navegación")
    menu_option = st.radio(
        "",
        ["Dashboard Analytics", "Gestión de Horas", "Nuevo Ingreso", "Centro de Notificaciones", "Base de Pacientes"],
        index=0,
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # === MOSTRAR ESTADO DE LA CUENTA ===
    if status['activo']:
        st.success(f"✅ Cuenta Activa: {MASTER_ACCOUNT_ID}")
        
        limite_diario = status['limite']
        uso_actual = st.session_state.ai_usage
        
        if status['plan'] == 'PRO':
            st.markdown(f"🌟 **Plan PRO** ({limite_diario} Consultas)")
        else:
            st.markdown(f"🌱 **Plan GRATIS** ({limite_diario} Consultas)")
        
        st.progress(min(uso_actual / limite_diario, 1.0))
        st.caption(f"Uso IA Hoy: {uso_actual}/{limite_diario}")
        
        if uso_actual >= limite_diario:
            st.warning("⚠️ Límite diario alcanzado")
            
    else:
        st.error("⛔ Cuenta Suspendida o No Encontrada")
        st.stop() # DETIENE LA EJECUCIÓN SI NO TIENE LICENCIA ACTIVA
    
    st.markdown(f"**Estado Sistema:**")
    st.markdown("🟢 Conectado a Sheets")
    st.markdown("🔴 Bot Inactivo" if 'driver' not in locals() else "🟢 Bot Activo")

# --- CARGA DE DATOS (CON CACHÉ INTELIGENTE) ---
df = get_data_fresh()
if df is None:
    st.error("Error crítico: No se pudo conectar a la base de datos.")
    st.stop()

# -----------------------------------------------------------------------------
# VISTA 1: DASHBOARD ANALYTICS (ACTUALIZADO CON GESTIÓN DE DISPONIBILIDAD)
# -----------------------------------------------------------------------------
if menu_option == "Dashboard Analytics":
    # HEADER
    hoy_header = datetime.now()
    fecha_header_esp = f"{hoy_header.day} de {MESES_ES[hoy_header.month]} de {hoy_header.year}"
    
    st.markdown(f"""
    <div class="header-container">
        <div>
            <h1 class="header-title">📊 Inteligencia Clínica</h1>
            <p class="header-subtitle">Análisis Estadístico y Gestión de Disponibilidad | CESFAM Cholchol</p>
        </div>
        <div class="date-badge">
            📅 {fecha_header_esp}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- 1. CÁLCULOS DE MÉTRICAS (GLOBAL VS MES ACTUAL) ---
    
    # Globales
    total_global = len(df)
    confirmados_global = len(df[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
    rechazados_global = len(df[df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')])
    notificados_global = len(df[df['ESTADO'].str.contains('OK') | df['ESTADO_REA'].str.contains('OK')])
    tasa_global = int((confirmados_global / notificados_global) * 100) if notificados_global > 0 else 0
    
    # Mensuales (Mes Actual)
    if 'FECHA_DT' in df.columns:
        mes_actual = datetime.now().month
        anio_actual = datetime.now().year
        df_mes = df[(df['FECHA_DT'].dt.month == mes_actual) & (df['FECHA_DT'].dt.year == anio_actual)]
        
        total_mes = len(df_mes)
        confirmados_mes = len(df_mes[df_mes['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
        rechazados_mes = len(df_mes[df_mes['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')])
        notificados_mes = len(df_mes[df_mes['ESTADO'].str.contains('OK') | df_mes['ESTADO_REA'].str.contains('OK')])
        tasa_mes = int((confirmados_mes / notificados_mes) * 100) if notificados_mes > 0 else 0
    else:
        total_mes = 0; confirmados_mes = 0; rechazados_mes = 0; tasa_mes = 0

    # --- 2. CÁLCULO DE "HORAS DISPONIBLES" (Lógica del Usuario) ---
    # Criterio: Status es 'NO ASISTIRA' Y la fecha es FUTURA (días > 0)
    # Excluye citas de hoy (0) o pasadas (<0)
    if 'DIAS_RESTANTES' in df.columns:
        horas_disponibles_df = df[
            (df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')) & 
            (df['DIAS_RESTANTES'] > 0)
        ]
        total_horas_disponibles = len(horas_disponibles_df)
    else:
        total_horas_disponibles = 0

    # Reagendamientos Pendientes (Gestión administrativa)
    reagendamientos_pendientes = len(df[(df['CAMBIO_DE_HORA'] == 'SI') & (df['ESTADO_REA'] == '')])

    # Recurrencia (Total - Unique RUTs)
    ruts_unicos = df['RUT'].nunique() if 'RUT' in df.columns else 0
    recurrentes = len(df) - ruts_unicos

    # --- 3. PANELES DE KPI ---
    
    # BOTÓN EXPORTAR PDF (Ligado a Créditos IA)
    # LÓGICA: AL PRESIONAR EL BOTÓN, PRIMERO EJECUTA LA IA Y LUEGO GENERA EL PDF
    if st.button("📄 Exportar Reporte Ejecutivo (PDF + Análisis IA Auto)"):
        if st.session_state.ai_usage >= status['limite']:
            st.error("🚫 Límite de créditos alcanzado. No se puede generar el análisis IA para el reporte.")
        else:
            with st.spinner("🤖 La IA está analizando los datos en tiempo real..."):
                # 1. Ejecutar Análisis IA (Descuenta crédito)
                ai_result = generar_analisis_clinico(df)
                
                # 2. Guardar en sesión (para que no se pierda al recargar)
                st.session_state.ultimo_reporte_ia = ai_result
                
                # 3. Descontar Crédito y Guardar en Nube
                nuevo_contador = st.session_state.ai_usage + 1
                st.session_state.ai_usage = nuevo_contador
                registrar_consumo_ia(ROW_INDEX_ADMIN, nuevo_contador)
            
            with st.spinner("📄 Maquetando Reporte PDF Institucional..."):
                # 4. Preparar estadísticas para el PDF
                stats_export = { 
                    'total_global': total_global, 
                    'confirmados_global': confirmados_global, 
                    'rechazados_global': rechazados_global, 
                    'tasa_global': tasa_global,
                    'total_mes': total_mes,
                    'confirmados_mes': confirmados_mes,
                    'tasa_mes': tasa_mes,
                    'disponibles': total_horas_disponibles,
                    'cola_activa': len(df[(df['ESTADO'] == '') & (df['DIAS_RESTANTES'] >= 1) & (df['DIAS_RESTANTES'] <= 2)]) if 'DIAS_RESTANTES' in df.columns else 0
                }
                
                # 5. Generar PDF usando la clase PDFReport personalizada
                pdf_bytes = generate_pdf_report(df, stats_export, ai_result, APP_CONFIG['imagenes'])
                
                st.download_button(
                    label="⬇️ Descargar Reporte PDF Final", 
                    data=pdf_bytes, 
                    file_name=f"Reporte_Ejecutivo_{datetime.now().strftime('%Y%m%d')}.pdf", 
                    mime='application/pdf'
                )
                st.success("✅ Reporte generado y crédito descontado exitosamente.")
    
    # BLOQUE DE DISPONIBILIDAD (NUEVO DESTACADO)
    if total_horas_disponibles > 0:
        st.markdown("""
        <div style="background-color: #d4edda; border-left: 5px solid #88C543; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <h4 style="color: #155724; margin:0;">✅ Oportunidad de Gestión</h4>
            <p style="color: #155724; margin:0;">Se han detectado cupos liberados para días futuros.</p>
        </div>
        """, unsafe_allow_html=True)

    # --- MÉTRICAS SEPARADAS POR MES E HISTÓRICO ---
    st.markdown(f"#### 📅 Mes en Curso: {MESES_ES[datetime.now().month]}")
    m1, m2, m3 = st.columns(3)
    
    with m1:
        st.metric(
            label="Pacientes este Mes", 
            value=total_mes, 
            delta="Agenda Mensual", 
            delta_color="off",
            border=True
        )
    with m2:
        st.metric(
            label="Confirmados este Mes", 
            value=confirmados_mes, 
            delta=f"{tasa_mes}% Tasa de Éxito",
            border=True
        )
    with m3:
        st.metric(
            label="Horas Disp. Futuras", 
            value=total_horas_disponibles, 
            delta="Cupos Recuperables", 
            delta_color="normal",
            border=True
        )

    st.write("")
    st.markdown("#### 🌍 Histórico Global")
    m4, m5, m6 = st.columns(3)
    
    with m4: 
        st.metric("Total Histórico", total_global, border=True)
    with m5: 
        st.metric("Total Confirmados", confirmados_global, f"{tasa_global}% Global", border=True)
    with m6: 
        st.metric("Reagendamientos Pendientes", reagendamientos_pendientes, "Requiere Acción", delta_color="inverse", border=True)
    
    st.write("")
    # Métricas adicionales (Fila 3)
    c1, c2 = st.columns(2)
    
    # Cola de envío (Próx 2 días) - Excluyendo cancelados
    if 'DIAS_RESTANTES' in df.columns:
        cola_activa = len(df[
            (df['ESTADO'] == '') & 
            (df['CAMBIO_DE_HORA'] != 'SI') & 
            (df['DIAS_RESTANTES'] >= 1) & 
            (df['DIAS_RESTANTES'] <= 2) &
            (~df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA', na=False)) # Exclude cancellations
        ])
    else:
        cola_activa = 0

    with c1: st.metric("Cola de Envío (Próx. 2 días)", cola_activa, "Listos para salir", border=True)
    with c2: st.metric("Pacientes Recurrentes", recurrentes, "Mismo RUT", border=True)

    st.divider()
    
    # --- SISTEMA DE PESTAÑAS (ACTUALIZADO) ---
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📉 Respuesta Paciente", "📊 Demografía", "🩺 Carga Asistencial", "♻️ Gestión Cupos", "⏰ Gestión Temporal", "⚠️ Control Cambios", "🗓️ Calendario", "🧠 IA Analista"
    ])
    
    # === TAB 1: RESPUESTA PACIENTE (Update con No Asistira) ===
    with tab1:
        c_donut, c_funnel = st.columns(2)
        
        with c_donut:
            st.markdown("##### 📢 Estado de Confirmación")
            # Preparamos datos para Donut Chart
            df_status = df['STATUS_CONFIRMACION'].value_counts().reset_index()
            df_status.columns = ['Estado', 'Cantidad']
            
            base = alt.Chart(df_status).encode(theta=alt.Theta("Cantidad", stack=True))
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color("Estado", scale=alt.Scale(domain=['CONFIRMADO', 'NO ASISTIRA', 'PENDIENTE', 'CONFIRMADO (R)', 'NO ASISTIRA (R)'], range=['#88C543', '#D32F2F', '#A8A8A8', '#6DA036', '#9A2323'])),
                order=alt.Order("Cantidad", sort="descending"),
                tooltip=["Estado", "Cantidad"]
            )
            text = base.mark_text(radius=140).encode(
                text="Cantidad",
                order=alt.Order("Cantidad", sort="descending"),
                color=alt.value("black") 
            )
            st.altair_chart(pie + text, use_container_width=True)

        with c_funnel:
            st.markdown("##### 📉 Embudo de Gestión")
            funnel_data = pd.DataFrame({
                'Etapa': ['1. Total Agendado', '2. Notificados', '3. Confirmados', '4. Cancelados'],
                'Cantidad': [total_global, notificados_global, confirmados_global, rechazados_global]
            })
            c_funnel_chart = alt.Chart(funnel_data).mark_bar().encode(
                x=alt.X('Cantidad', title='N° Pacientes'),
                y=alt.Y('Etapa', sort=None, title=''),
                color=alt.Color('Etapa', scale=alt.Scale(scheme='tealblues')),
                tooltip=['Etapa', 'Cantidad']
            ).properties(height=300)
            st.altair_chart(c_funnel_chart, use_container_width=True)

    # === TAB 2: DEMOGRAFÍA ===
    with tab2:
        col_edad, col_genero = st.columns(2)
        with col_edad:
            st.markdown("##### 🎂 Distribución por Edad")
            if 'EDAD_NUM' in df.columns:
                # === MODIFICACIÓN SOLICITADA: RANGOS ETARIOS PERSONALIZADOS ===
                df['Rango_Edad'] = pd.cut(
                    df['EDAD_NUM'], 
                    bins=[-1, 4, 9, 14, 19, 44, 64, 79, 150], 
                    labels=['0-4', '5-9', '10-14', '15-19', '20-44', '45-64', '65-79', '80+'],
                    right=True
                )
                df_age = df['Rango_Edad'].value_counts().sort_index().reset_index()
                df_age.columns = ['Rango', 'Cantidad']
                
                chart_age = alt.Chart(df_age).mark_bar(color='#006DB6').encode(
                    x=alt.X('Rango', title='Grupo Etario', sort=None),
                    y=alt.Y('Cantidad', title='N° Pacientes'),
                    tooltip=['Rango', 'Cantidad']
                ).properties(height=300)
                st.altair_chart(chart_age, use_container_width=True)
            else:
                st.info("Datos de edad no disponibles.")

        with col_genero:
            st.markdown("##### ⚧️ Distribución por Género")
            if 'GENERO' in df.columns:
                df_gen = df['GENERO'].value_counts().reset_index()
                df_gen.columns = ['Genero', 'Total']
                chart_gen = alt.Chart(df_gen).mark_arc(innerRadius=50).encode(
                    theta=alt.Theta(field="Total", type="quantitative"),
                    color=alt.Color(field="Genero", type="nominal", scale=alt.Scale(scheme='pastel1')),
                    tooltip=['Genero', 'Total']
                ).properties(height=300)
                st.altair_chart(chart_gen, use_container_width=True)

    # === TAB 3: CARGA ASISTENCIAL ===
    with tab3:
        c_prof, c_motivo = st.columns(2)
        with c_prof:
            st.markdown("##### 👨‍⚕️ Carga por Profesional")
            df_prof = df['NOMBRE_PROFESIONAL'].value_counts().reset_index().head(10)
            df_prof.columns = ['Profesional', 'Pacientes']
            chart_prof = alt.Chart(df_prof).mark_bar(cornerRadius=5).encode(
                x=alt.X('Pacientes', title='Total Atenciones'),
                y=alt.Y('Profesional', sort='-x', title=None),
                color=alt.Color('Pacientes', scale=alt.Scale(scheme='blues')),
                tooltip=['Profesional', 'Pacientes']
            ).properties(height=400)
            st.altair_chart(chart_prof, use_container_width=True)
        with c_motivo:
            st.markdown("##### 📋 Top Motivos de Consulta")
            if 'MOTIVO_CLEAN' in df.columns:
                df_motivo = df['MOTIVO_CLEAN'].value_counts().reset_index().head(10)
                df_motivo.columns = ['Motivo', 'Frecuencia']
                chart_motivo = alt.Chart(df_motivo).mark_bar(color='#FF9F43', cornerRadius=5).encode(
                    x=alt.X('Frecuencia'),
                    y=alt.Y('Motivo', sort='-x', title=None),
                    tooltip=['Motivo', 'Frecuencia']
                ).properties(height=400)
                st.altair_chart(chart_motivo, use_container_width=True)

    # === TAB 4: GESTIÓN CUPOS (NUEVO) ===
    with tab4:
        st.markdown("##### ♻️ Detalle de Horas Disponibles (Recuperables)")
        st.caption("Pacientes que respondieron 'NO' y cuya cita es en el futuro (Días Restantes > 0).")
        
        if total_horas_disponibles > 0:
            # Mostrar tabla filtrada solo con columnas relevantes para gestión rápida
            st.dataframe(
                horas_disponibles_df[['FECHA_AGENDADA', 'HORA_AGENDADA', 'NOMBRE_PROFESIONAL', 'RUT', 'NOMBRE_PACIENTE', 'TELEFONO', 'DIAS_RESTANTES']],
                use_container_width=True,
                hide_index=True
            )
            
            # Gráfico de disponibilidad por día
            st.markdown("##### 📅 Disponibilidad por Fecha")
            df_disp_date = horas_disponibles_df['FECHA_AGENDADA'].value_counts().reset_index()
            df_disp_date.columns = ['Fecha', 'Cupos Libres']
            
            chart_disp = alt.Chart(df_disp_date).mark_bar(color='#88C543').encode(
                x=alt.X('Fecha', sort=None),
                y=alt.Y('Cupos Libres'),
                tooltip=['Fecha', 'Cupos Libres']
            ).properties(height=300)
            st.altair_chart(chart_disp, use_container_width=True)
            
        else:
            st.success("🎉 No hay cancelaciones futuras pendientes de reasignar. ¡Agenda eficiente!")

    # === TAB 5: GESTIÓN TEMPORAL (HEATMAP MEJORADO) ===
    with tab5:
        st.markdown("##### 🕒 Mapa de Calor: Días vs Horas Punta")
        st.caption("Visualiza las cargas horarias críticas distribuidas por día de la semana (Considera reagendamientos).")
        
        if 'HORA_INT' in df.columns and 'DIA_SEMANA_ES' in df.columns:
            # Filtramos horas inválidas
            df_heat = df[df['HORA_INT'] != -1].copy()
            
            dias_orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            
            heatmap = alt.Chart(df_heat).mark_rect().encode(
                x=alt.X('HORA_LABEL:O', title='Bloque Horario', sort=alt.EncodingSortField(field="HORA_INT", order="ascending")),
                y=alt.Y('DIA_SEMANA_ES:O', title='Día de la Semana', sort=dias_orden),
                color=alt.Color('count()', title='Carga Pacientes', scale=alt.Scale(scheme='orangered')),
                tooltip=[
                    alt.Tooltip('DIA_SEMANA_ES', title='Día'),
                    alt.Tooltip('HORA_LABEL', title='Hora'),
                    alt.Tooltip('count()', title='Pacientes')
                ]
            ).properties(height=350).configure_axis(
                labelFontSize=12,
                titleFontSize=14
            )
            
            st.altair_chart(heatmap, use_container_width=True)
        else:
            st.warning("Datos insuficientes para generar el mapa de calor temporal.")

    # === TAB 6: CONTROL DE CAMBIOS ===
    with tab6:
        col_kpi_rea, col_chart_rea = st.columns([1, 2])
        total_reagendados_historicos = len(df[df['CAMBIO_DE_HORA'] == 'SI'])
        with col_kpi_rea:
            st.warning(f"Total Reagendamientos: {total_reagendados_historicos}")
            st.markdown("**Desglose:**")
            if total_reagendados_historicos > 0:
                if 'ESTADO_REA' in df.columns:
                    counts_rea = df[df['CAMBIO_DE_HORA'] == 'SI']['ESTADO_REA'].value_counts()
                    st.write(counts_rea)
        with col_chart_rea:
            st.markdown("##### 🔄 Motivos de Reagendamiento")
            if total_reagendados_historicos > 0:
                df_mot_rea = df[df['CAMBIO_DE_HORA'] == 'SI']['MOTIVO_CONSULTA_REA'].value_counts().reset_index()
                df_mot_rea.columns = ['Motivo Cambio', 'Cantidad']
                chart_mot_rea = alt.Chart(df_mot_rea).mark_arc().encode(
                    theta=alt.Theta(field="Cantidad", type="quantitative"),
                    color=alt.Color(field="Motivo Cambio", type="nominal", scale=alt.Scale(scheme='category20b')),
                    tooltip=['Motivo Cambio', 'Cantidad']
                )
                st.altair_chart(chart_mot_rea, use_container_width=True)

    # === TAB 7: CALENDARIO (LOCALIZADO) ===
    with tab7:
        col_evol, col_cal = st.columns([1, 2])
        
        with col_evol:
            st.markdown("##### 📈 Evolución Mensual")
            if 'FECHA_DT' in df.columns:
                # Agrupar por mes y año usando la FECHA_EFECTIVA (FECHA_DT)
                df_monthly = df.set_index('FECHA_DT').resample('ME').size().reset_index(name='Total')
                
                # TRADUCCIÓN DE MESES
                df_monthly['Mes_Num'] = df_monthly['FECHA_DT'].dt.month
                df_monthly['Año'] = df_monthly['FECHA_DT'].dt.year
                df_monthly['Mes_Label'] = df_monthly.apply(lambda x: f"{MESES_ES[x['Mes_Num']]} {x['Año']}", axis=1)
                
                chart_monthly = alt.Chart(df_monthly).mark_bar(color='#006DB6').encode(
                    x=alt.X('Mes_Label', sort=None, title='Mes'),
                    y=alt.Y('Total', title='Total Pacientes'),
                    tooltip=['Mes_Label', 'Total']
                ).properties(height=300)
                st.altair_chart(chart_monthly, use_container_width=True)
            else:
                st.info("No hay datos históricos suficientes.")

        with col_cal:
            st.markdown("##### 🗓️ Calendario Semanal (Heatmap)")
            if 'FECHA_DT' in df.columns and 'DIA_SEMANA_ES' in df.columns:
                df_cal = df.copy()
                # Usamos la FECHA_DT que ahora es la efectiva
                df_cal = df_cal[df_cal['FECHA_DT'].notna()]
                dias_orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                heatmap = alt.Chart(df_cal).mark_rect().encode(
                    x=alt.X('DIA_SEMANA_ES:N', title='Día de la Semana', sort=dias_orden), 
                    y=alt.Y('week(FECHA_DT):O', title='Semana del Año'),
                    color=alt.Color('count()', title='N° Pacientes', scale=alt.Scale(scheme='greens')),
                    tooltip=[
                        alt.Tooltip('yearmonthdate(FECHA_DT)', title='Fecha'),
                        alt.Tooltip('DIA_SEMANA_ES', title='Día'),
                        alt.Tooltip('count()', title='Pacientes')
                    ]
                ).properties(width=700, height=300)
                st.altair_chart(heatmap, use_container_width=True)
            else:
                st.warning("No hay fechas válidas para generar el calendario.")

    # === TAB 8: ANALISTA VIRTUAL ===
    with tab8:
        col_ia_1, col_ia_2 = st.columns([1, 2])
        
        with col_ia_1:
            st.markdown("### 🧠 Analista Virtual")
            limite_max = status['limite']
            uso_actual = st.session_state.ai_usage
            
            st.markdown(f"""
            <div style="background-color:#F8F9FA; padding:15px; border-radius:10px; border-left: 4px solid #006DB6; font-size:0.9rem;">
                <strong>Plan Actual:</strong> {status['plan']}<br>
                <strong>Consultas:</strong> {uso_actual} / {limite_max}
            </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            st.divider()
            
            if uso_actual >= limite_max:
                st.error(f"🚫 Límite diario alcanzado ({limite_max}).")
                st.button("✨ Generar Reporte", disabled=True)
            else:
                if st.button("✨ Generar Reporte Ejecutivo", type="primary", use_container_width=True):
                    
                    with col_ia_2:
                        with st.spinner("🧠 Analizando datos y registrando consumo..."):
                            # 1. Generar Reporte (Usando Prompt de Excel)
                            resultado_ia = generar_analisis_clinico(df)
                            
                            # 2. Guardar en Memoria para persistencia
                            st.session_state.ultimo_reporte_ia = resultado_ia
                            
                            # 3. Incrementar Contador Local
                            nuevo_contador = uso_actual + 1
                            st.session_state.ai_usage = nuevo_contador
                            
                            # 4. Guardar Contador en Nube (Col H)
                            exito_save = registrar_consumo_ia(ROW_INDEX_ADMIN, nuevo_contador)
                            
                            if exito_save:
                                st.toast("Consumo registrado en la nube", icon="✅")
                            else:
                                st.warning("Error guardando contador en nube")
                            
                            # 5. Recargar para actualizar UI
                            time.sleep(0.5)
                            st.rerun()
        
        with col_ia_2:
            # MOSTRAR EL REPORTE (Persistente)
            if st.session_state.ultimo_reporte_ia:
                st.markdown(f"""
                <div class="report-container">
                    <div class="report-header">
                        📊 REPORTE GERENCIAL DIARIO | {datetime.now().strftime("%d/%m/%Y")}
                    </div>
                    <div style="color: #444; line-height: 1.6;">
                        {st.session_state.ultimo_reporte_ia}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("🗑️ Limpiar Pantalla"):
                    st.session_state.ultimo_reporte_ia = None
                    st.rerun()
            else:
                st.info("👋 Presiona el botón para que la IA analice los datos.")

# -----------------------------------------------------------------------------
# VISTA 2: GESTIÓN DE HORAS (REAGENDAMIENTO)
# -----------------------------------------------------------------------------
elif menu_option == "Gestión de Horas":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">📝 Gestión de Horas Médicas</h1>
            <p class="header-subtitle">Seleccione un paciente de la tabla para modificar sus datos</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_search, _ = st.columns([2, 1])
    with col_search:
        search_text = st.text_input("🔎 Filtrar por Nombre, RUT o Teléfono:", placeholder="Escriba para filtrar la tabla...")

    df_view = df.copy()
    if search_text:
        mask = df_view.astype(str).apply(lambda x: x.str.contains(search_text, case=False, na=False)).any(axis=1)
        df_view = df_view[mask]

    st.info("👆 Haga clic en la casilla a la izquierda de la fila para seleccionar un paciente.")
    
    event = st.dataframe(
        df_view,
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        height=400,
        hide_index=True
    )

    if len(event.selection.rows) > 0:
        selected_row_index = event.selection.rows[0]
        patient_selected = df_view.iloc[selected_row_index]
        
        st.divider()
        st.markdown(f"### ✏️ Editando: **{patient_selected['NOMBRE_PACIENTE']}** (RUT: {patient_selected.get('RUT', 'S/I')})")
        
        with st.form("form_reagendamiento"):
            st.info(f"📅 Cita Actual: {patient_selected['FECHA_AGENDADA']} a las {patient_selected['HORA_AGENDADA']} con {patient_selected['NOMBRE_PROFESIONAL']}")
            
            activar_reagendamiento = st.checkbox("🛑 Activar Reagendamiento", value=(str(patient_selected['CAMBIO_DE_HORA']) == "SI"))
            
            col_a, col_b = st.columns(2)
            with col_a:
                new_date_val = patient_selected['NUEVA_FECHA']
                try:
                    default_date = datetime.strptime(new_date_val, "%d/%m/%Y") if new_date_val else datetime.now()
                except:
                    default_date = datetime.now()
                    
                new_fecha = st.date_input("Nueva Fecha", value=default_date)
                
                # === SELECTBOX DE HORAS ===
                current_time_val = patient_selected['HORA_NUEVA_FECHA']
                idx_hora = 0
                if current_time_val in LISTA_HORAS:
                    idx_hora = LISTA_HORAS.index(current_time_val)
                
                new_hora_str = st.selectbox("Nueva Hora (Menú)", LISTA_HORAS, index=idx_hora)
            
            with col_b:
                new_prof = st.text_input("Profesional Reasignado (Nombre)", value=patient_selected['NOM_PROF_REASIG'])
                current_prof_rea = patient_selected['PROFESION_PROF_RE'] if patient_selected['PROFESION_PROF_RE'] in LISTA_PROFESIONES else LISTA_PROFESIONES[0]
                new_profesion_rea = st.selectbox("Profesión (Reasignado)", LISTA_PROFESIONES, index=LISTA_PROFESIONES.index(current_prof_rea))
                current_motivo_rea = patient_selected['MOTIVO_CONSULTA_REA'] if patient_selected['MOTIVO_CONSULTA_REA'] in LISTA_MOTIVOS else LISTA_MOTIVOS[0]
                new_motivo = st.selectbox("Motivo Reagendamiento", LISTA_MOTIVOS, index=LISTA_MOTIVOS.index(current_motivo_rea))

            submit_update = st.form_submit_button("💾 Guardar Cambios")
            
            if submit_update:
                try:
                    sheet_obj, msg = connect_sheet()
                    if sheet_obj:
                        row_num = patient_selected.name + 2
                        cambio_val = "SI" if activar_reagendamiento else "NO"
                        fecha_str = new_fecha.strftime("%d/%m/%Y") if activar_reagendamiento else ""
                        hora_str = new_hora_str if activar_reagendamiento else ""
                        
                        # === CRÍTICO: ACTUALIZACIÓN DE CELDAS CON NUEVOS ÍNDICES ===
                        sheet_obj.update_cell(row_num, 16, cambio_val) # CAMBIO_DE_HORA
                        sheet_obj.update_cell(row_num, 17, fecha_str) # NUEVA_FECHA
                        sheet_obj.update_cell(row_num, 18, hora_str)  # HORA_NUEVA_FECHA
                        sheet_obj.update_cell(row_num, 19, new_prof)  # NOM_PROF_REASIG
                        sheet_obj.update_cell(row_num, 20, new_profesion_rea) # PROFESION_PROF_RE
                        sheet_obj.update_cell(row_num, 21, new_motivo) # MOTIVO_CONSULTA_REA
                        
                        if activar_reagendamiento:
                            sheet_obj.update_cell(row_num, 22, "") # Reset ESTADO_REA
                        
                        st.success("✅ Datos actualizados correctamente en la nube.")
                        time.sleep(1.5)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Error de conexión.")
                except Exception as e:
                    st.error(f"Error al actualizar: {e}")


# -----------------------------------------------------------------------------
# VISTA 3: NUEVO INGRESO
# -----------------------------------------------------------------------------
elif menu_option == "Nuevo Ingreso":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">📥 Nuevo Ingreso</h1>
            <p class="header-subtitle">Registrar paciente manualmente en el sistema con datos demográficos</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("form_ingreso", clear_on_submit=True):
        st.markdown("**1. Datos Personales**")
        c1, c2, c3 = st.columns(3)
        with c1:
            rut = st.text_input("RUT Paciente", placeholder="Ej: 12.345.678-9") # NUEVO CAMPO RUT
            nombre = st.text_input("Nombre Completo Paciente", placeholder="Ej: Juan Pérez")
            telefono = st.text_input("Teléfono", placeholder="Ej: 56912345678 (Debe comenzar con 569)")
        with c2:
            # Definimos 'hoy' primero para usarlo como límite máximo
            hoy = datetime.now()

            fecha_nac = st.date_input(
                "Fecha de Nacimiento",
                value=datetime(1980, 1, 1),       # Fecha por defecto
                min_value=datetime(1900, 1, 1),   # Fecha mínima (lo más antiguo)
                max_value=hoy                     # <--- ESTO AGREGA EL LÍMITE HASTA HOY
            )

            # Cálculo de edad (se mantiene igual, pero usamos .date() para comparar correctamente)
            hoy_edad = hoy.date()
            edad_calc = hoy_edad.year - fecha_nac.year - ((hoy_edad.month, hoy_edad.day) < (fecha_nac.month, fecha_nac.day))

            
        with c3:
            genero = st.selectbox("Género", ["Femenino", "Masculino", "Otro", "No Informa"])
            
        st.markdown("**2. Datos de la Atención**")
        c4, c5 = st.columns(2)
        with c4:
            fecha = st.date_input("Fecha de Atención", min_value=datetime.now())
            hora = st.time_input("Hora de Atención")
        with c5:
            profesional = st.text_input("Nombre Profesional", placeholder="Ej: Dra. Ana López")
            profesion = st.selectbox("Profesión", LISTA_PROFESIONES)
            motivo = st.selectbox("Motivo Consulta", LISTA_MOTIVOS)
        
        submit = st.form_submit_button("💾 Guardar Paciente", use_container_width=True)
        
        if submit:
            if not (telefono.startswith("569") and len(telefono) == 11 and telefono.isdigit()):
                st.error("⚠️ El teléfono debe tener el formato 569XXXXXXXX (11 dígitos y comenzar con 569).")
            elif nombre and telefono and profesional and rut:
                try:
                    sheet_obj, msg = connect_sheet()
                    if sheet_obj:
                        # === MAPEO DE 26 COLUMNAS CON RUT INCLUIDO ===
                        new_row = [
                            rut,                                            # 1. RUT
                            nombre,                                         # 2. NOMBRE_PACIENTE
                            telefono,                                       # 3. TELEFONO
                            fecha_nac.strftime("%d/%m/%Y"),                 # 4. FECHA_NACIMIENTO
                            str(edad_calc),                                 # 5. EDAD_ACTUAL
                            genero,                                         # 6. GENERO
                            fecha.strftime("%d/%m/%Y"),                     # 7. FECHA_AGENDADA
                            hora.strftime("%H:%M"),                         # 8. HORA_AGENDADA
                            profesional,                                    # 9. NOMBRE_PROFESIONAL
                            profesion,                                      # 10. PROFESION
                            motivo,                                         # 11. MOTIVO_CONSULTA
                            "", "", "", "",                                 # 12-15: Datos Notif 1
                            "NO",                                           # 16: CAMBIO_DE_HORA
                            "", "", "", "", "",                             # 17-21: Datos Reagendamiento
                            "", "", "",                                     # 22-24: Datos Notif 2
                            "", ""                                          # 25-26: CONFIRMA_HORA, CONFIRMA_REAGEN
                        ]
                        sheet_obj.append_row(new_row)
                        st.success(f"✅ Paciente {nombre} ({edad_calc} años) registrado exitosamente.")
                        st.cache_data.clear() 
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Error de conexión con Google Sheets.")
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
            else:
                st.warning("⚠️ Por favor complete los campos obligatorios (RUT, Nombre, Teléfono).")

# -----------------------------------------------------------------------------
# VISTA 4: CENTRO DE NOTIFICACIONES
# -----------------------------------------------------------------------------
elif menu_option == "Centro de Notificaciones":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">Centro de Notificaciones</h1>
            <p class="header-subtitle">Motor de automatización de WhatsApp</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_action, col_terminal = st.columns([1, 2])

    with col_action:
        st.markdown("### 🚀 Control de Misión")
        st.markdown("""
        <div style="background:white; padding:20px; border-radius:16px; box-shadow: var(--card-shadow);">
            <p style="color:#8898AA; font-size:0.9rem;">
                El bot procesará automáticamente:<br>
                • Recordatorios (2 días antes)<br>
                • Reagendamientos Urgentes
            </p>
            <hr style="margin:15px 0; border-top:1px solid #eee;">
            <p style="font-weight:600; margin-bottom:10px;">Estado del Servicio:</p>
            <span style="background:#E6FFFA; color:#28C76F; padding:5px 10px; border-radius:4px; font-size:0.8rem; font-weight:bold;">DISPONIBLE</span>
        </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        iniciar = st.button("▶ INICIAR ENVÍOS MASIVOS", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.info("📱 Mantén tu celular conectado a internet.")
        
        st.write("")
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        verificar = st.button("🔎 VERIFICAR RESPUESTAS", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with col_terminal:
        st.markdown("### 📟 Log del Sistema")
        log_placeholder = st.empty()
        
        log_placeholder.markdown("""
        <div class="terminal-window">
            <div class="terminal-header">
                <div class="terminal-dot dot-red"></div>
                <div class="terminal-dot dot-yellow"></div>
                <div class="terminal-dot dot-green"></div>
            </div>
            <div class="terminal-body">
                <span class="log-info">[SYSTEM]</span> Esperando comando de inicio...<br>
                <span class="log-info">[SYSTEM]</span> Conexión a GSheets: OK<br>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if iniciar:
            driver = init_driver()
            if not driver:
                st.error("Error crítico: No se pudo iniciar Chrome Driver.")
                st.stop()
            
            logs = []
            def update_terminal(new_log_line):
                logs.append(new_log_line)
                log_content = "<br>".join(logs[-15:])
                log_placeholder.markdown(f"""
                <div class="terminal-window">
                    <div class="terminal-header">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                    </div>
                    <div class="terminal-body">
                        {log_content}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            update_terminal(f'<span class="log-info">[BOOT]</span> Iniciando navegador seguro...')
            
            try:
                driver.get("https://web.whatsapp.com")
                update_terminal(f'<span class="log-info">[AUTH]</span> Esperando escaneo QR...')
                
                if esperar_login_qr(driver):
                    update_terminal(f'<span class="log-success">[AUTH]</span> Login exitoso. Acceso concedido.')
                    time.sleep(2)
                else:
                    update_terminal(f'<span class="log-error">[ERROR]</span> Tiempo agotado. Abortando.')
                    driver.quit()
                    st.stop()

                sheet_conn, _ = connect_sheet()
                data = sheet_conn.get_all_values()
                df_proc = pd.DataFrame(data[1:], columns=data[0])
                df_proc.columns = df_proc.columns.str.strip()
                
                total_rows = len(df_proc)
                progress_bar = st.progress(0)

                for idx, row in df_proc.iterrows():
                    try: 
                        try: _ = driver.window_handles
                        except: break

                        fila = idx + 2
                        nombre = row['NOMBRE_PACIENTE']
                        
                        es_cambio = str(row['CAMBIO_DE_HORA']).strip().upper() == "SI"
                        st_rea = str(row['ESTADO_REA']).strip()
                        st_nor = str(row['ESTADO']).strip()
                        
                        # === TIMESTAMP CON FECHA Y HORA ===
                        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
                        
                        accion = False

                        if es_cambio and st_rea == "":
                            update_terminal(f'<span class="log-info">[PROC]</span> Reagendando: {nombre}...')
                            
                            if not row['HORA_NUEVA_FECHA'] or not row['NUEVA_FECHA']:
                                update_terminal(f'<span class="log-error">[FAIL]</span> Datos incompletos para {nombre}')
                            else:
                                # === CAMBIO: Usar mensaje dinámico desde Admin ===
                                msg = get_template(row, "REAGENDAMIENTO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                if ok:
                                    try:
                                        sheet_conn.update_cell(fila, 22, "NOTIFICADO OK") # ESTADO_REA
                                        sheet_conn.update_cell(fila, 23, ahora)            # FECHA_NOTIF_2
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")       # METODO_REA
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT]</span> Reagendamiento enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 22, "ERROR")          
                                        sheet_conn.update_cell(fila, 23, ahora)
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR]</span> Fallo envío a {nombre}: {log}')
                            accion = True
                            time.sleep(2) 

                        elif not es_cambio and st_nor == "":
                            dias = calcular_dias(row['FECHA_AGENDADA'])
                            
                            if str(row['OBSERVACION']).strip() == "":
                                try:
                                    if dias == 0: sheet_conn.update_cell(fila, 15, "⚠️ Atención HOY")
                                    elif dias == 1: sheet_conn.update_cell(fila, 15, "⚠️ Falta 1 día")
                                    elif dias == 2: sheet_conn.update_cell(fila, 15, "⚠️ Faltan 2 días")
                                    elif dias > 2: sheet_conn.update_cell(fila, 15, f"Faltan {dias} días")
                                except: pass

                            if 1 <= dias <= 2:
                                update_terminal(f'<span class="log-info">[PROC]</span> Recordatorio: {nombre} ({dias} días)...')
                                # === CAMBIO: Usar mensaje dinámico desde Admin ===
                                msg = get_template(row, "RECORDATORIO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                
                                if ok:
                                    try:
                                        sheet_conn.update_cell(fila, 12, "NOTIFICADO OK") # ESTADO
                                        sheet_conn.update_cell(fila, 13, ahora)            # FECHA_NOTIF_1
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")       # METODO
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT]</span> Recordatorio enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 12, "ERROR")          
                                        sheet_conn.update_cell(fila, 13, ahora)
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR]</span> Fallo envío a {nombre}: {log}')
                                accion = True
                                time.sleep(2) 
                            elif dias < 0:
                                 if row['OBSERVACION'] == "": 
                                     try: sheet_conn.update_cell(fila, 15, "Fecha Pasada") 
                                     except: pass

                    except Exception as e_inner:
                        update_terminal(f'<span class="log-error">[CRIT] Error en fila {fila}: {str(e_inner)}</span>')
                        continue 

                    progress_bar.progress((idx + 1) / total_rows)

                update_terminal(f'<span class="log-success">[DONE]</span> Todas las tareas finalizadas.')
                st.balloons()
                st.cache_data.clear() 
                
            except Exception as e:
                st.error(f"Error crítico: {e}")
            finally:
                if driver: driver.quit()

        if verificar:
            driver = init_driver()
            if not driver:
                st.error("Error crítico: No se pudo iniciar Chrome Driver.")
                st.stop()
            
            logs = []
            def update_terminal(new_log_line):
                logs.append(new_log_line)
                log_content = "<br>".join(logs[-15:])
                log_placeholder.markdown(f"""
                <div class="terminal-window">
                    <div class="terminal-header">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                    </div>
                    <div class="terminal-body">
                        {log_content}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            update_terminal(f'<span class="log-info">[BOOT]</span> Iniciando verificación de respuestas...')
            
            try:
                driver.get("https://web.whatsapp.com")
                update_terminal(f'<span class="log-info">[AUTH]</span> Esperando escaneo QR...')
                
                if esperar_login_qr(driver):
                    update_terminal(f'<span class="log-success">[AUTH]</span> Login exitoso.')
                    time.sleep(2)
                else:
                    update_terminal(f'<span class="log-error">[ERROR]</span> Tiempo agotado.')
                    driver.quit()
                    st.stop()

                sheet_conn, _ = connect_sheet()
                data = sheet_conn.get_all_values()
                df_proc = pd.DataFrame(data[1:], columns=data[0])
                df_proc.columns = df_proc.columns.str.strip()
                
                total_rows = len(df_proc)
                progress_bar = st.progress(0)
                
                count_confirmados = 0
                count_rechazos = 0

                for idx, row in df_proc.iterrows():
                    try: 
                        try: _ = driver.window_handles
                        except: break

                        fila = idx + 2
                        nombre = row['NOMBRE_PACIENTE']
                        
                        # LOGICA CRÍTICA: DETECTAR SI ES REAGENDAMIENTO O NORMAL
                        es_reagendamiento = str(row['CAMBIO_DE_HORA']).strip().upper() == "SI"
                        
                        if es_reagendamiento:
                            col_confirma = 26 # CONFIRMA_REAGEN
                            estado_notif = str(row['ESTADO_REA']).strip()
                            estado_actual_conf = str(row['CONFIRMA_REAGEN'])
                            # === NUEVA LÓGICA: SELECCIÓN DE FECHA TARGET ===
                            fecha_target_str = row['NUEVA_FECHA'] 
                        else:
                            col_confirma = 25 # CONFIRMA_HORA
                            estado_notif = str(row['ESTADO']).strip()
                            estado_actual_conf = str(row['CONFIRMA_HORA'])
                            # === NUEVA LÓGICA: SELECCIÓN DE FECHA TARGET ===
                            fecha_target_str = row['FECHA_AGENDADA']

                        # === NUEVA LÓGICA: FILTRO POR FECHA (SOLO FUTURO/HOY) ===
                        dias_para_cita = calcular_dias(fecha_target_str)
                        if dias_para_cita < 0:
                            # La fecha ya pasó, saltamos este registro
                            continue 
                        
                        # Si ya tiene una respuesta final ("CONFIRMADO" o "NO ASISTIRA"), saltamos
                        ya_finalizado = "CONFIRMADO" in estado_actual_conf or "NO ASISTIRA" in estado_actual_conf

                        # Solo verificamos si fue notificado y NO ha finalizado aún
                        if estado_notif == "NOTIFICADO OK" and not ya_finalizado:
                            update_terminal(f'<span class="log-info">[CHECK]</span> Revisando {nombre}...')
                            
                            # === AQUÍ USAMOS LA NUEVA FUNCIÓN QUE RETORNA ESTADOS ===
                            estado_clasificacion, detalle = verificar_respuestas_wsp(driver, row['TELEFONO'])
                            
                            if estado_clasificacion == "CONFIRMADO":
                                update_terminal(f'<span class="log-success">[YES]</span> {nombre}: "{detalle}"')
                                try:
                                    sheet_conn.update_cell(fila, col_confirma, "CONFIRMADO")
                                    count_confirmados += 1
                                except Exception as e_sheet:
                                    update_terminal(f'<span class="log-error">[SAVE ERR]</span> {e_sheet}')
                            
                            elif estado_clasificacion == "NO ASISTIRA":
                                update_terminal(f'<span class="log-error">[NO]</span> {nombre}: "{detalle}"')
                                try:
                                    sheet_conn.update_cell(fila, col_confirma, "NO ASISTIRA")
                                    count_rechazos += 1
                                except Exception as e_sheet:
                                    update_terminal(f'<span class="log-error">[SAVE ERR]</span> {e_sheet}')
                                    
                            else:
                                # AMBIGUO, ERROR o PENDIENTE (Tuyo)
                                update_terminal(f'<span class="log-info">[WAIT]</span> {nombre}: "{detalle}"')
                            
                            time.sleep(1)

                    except Exception as e_inner:
                        update_terminal(f'<span class="log-error">[ERR] {nombre}: {str(e_inner)}</span>')
                        continue 

                    progress_bar.progress((idx + 1) / total_rows)

                update_terminal(f'<span class="log-success">[DONE]</span> Proceso completo. {count_confirmados} Confirmados | {count_rechazos} Cancelaciones.')
                st.balloons()
                st.cache_data.clear() 
                
            except Exception as e:
                st.error(f"Error crítico: {e}")
            finally:
                if driver: driver.quit()
elif menu_option == "Base de Pacientes":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">Base de Pacientes</h1>
            <p class="header-subtitle">Registro maestro de citas y estados de notificación</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_search, col_filter = st.columns([3, 1])
    with col_search:
        search_term = st.text_input("🔎 Buscar paciente por RUT, nombre o teléfono")
    with col_filter:
        filter_status = st.selectbox("Filtrar Estado", ["Todos", "Pendientes", "Notificados", "Errores"])

    df_display = df.copy()
    if search_term:
        df_display = df_display[
            df_display['NOMBRE_PACIENTE'].str.contains(search_term, case=False) | 
            df_display['TELEFONO'].str.contains(search_term) |
            df_display['RUT'].str.contains(search_term) # Busqueda por RUT Agregada
        ]
    
    if filter_status == "Pendientes":
        df_display = df_display[df_display['ESTADO'] == '']
    elif filter_status == "Notificados":
        df_display = df_display[df_display['ESTADO'].str.contains('OK')]
    elif filter_status == "Errores":
        df_display = df_display[df_display['ESTADO'].str.contains('ERROR')]

    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Descargar Datos Actuales (CSV)",
        data=csv,
        file_name=f"reporte_pacientes_{datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
        use_container_width=True
    )

    st.dataframe(
        df_display, 
        use_container_width=True, 
        height=600,
        column_config={
            "RUT": st.column_config.TextColumn("RUT", width="medium"),
            "TELEFONO": st.column_config.TextColumn("Teléfono", width="medium"),
            "NOMBRE_PACIENTE": st.column_config.TextColumn("Paciente", width="large"),
            "EDAD_ACTUAL": st.column_config.NumberColumn("Edad"),
            "ESTADO": st.column_config.TextColumn("Estado", width="small"),
        }
    )

# --- FOOTER ---
st.markdown("---")
with st.container():
    col1, col2, col3, col4 = st.columns([3,1,5,1])
    with col2:
        # LOGO PIE DE PÁGINA (Dinámico)
        if IMG_LOGO_ALAIN:
            st.image(IMG_LOGO_ALAIN, width=150)
        else:
            st.info("Logo Dev")
            
    with col3:
        st.markdown("""
            <div style='text-align: left; color: #888888; font-size: 16px; padding-bottom: 20px;'>
                💼 Aplicación desarrollada por <strong>Alain Antinao Sepúlveda</strong> <br>
                📧 Contacto: <a href="mailto:alain.antinao.s@gmail.com" style="color: #006DB6;">alain.antinao.s@gmail.com</a> <br>
                🌐 Más información en: <a href="https://alain-antinao-s.notion.site/Alain-C-sar-Antinao-Sep-lveda-1d20a081d9a980ca9d43e283a278053e" target="_blank" style="color: #006DB6;">Mi página personal</a>
            </div>
        """, unsafe_allow_html=True)