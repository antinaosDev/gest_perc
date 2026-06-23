

import polars as pl
import re
import pandas as pd
from typing import List

import re
import pandas as pd


def class_pat(df):

    diccionario = {
    "Consumo Perjudicial o Dependiente de OH": {"PK": [
        "alcohol", "consumo de alcohol", "dependencia de alcohol", "alcoholismo", "bebida alcohólica"
    ]},

    "Tabaquismo": {"PK": [
        "tabaco", "cigarro", "fumar", "fumador", "cigarrillo", "adicción tabaco"
    ]},

    "Consumo Perjudicial o Dependiente de Droga Comosustancia Principal o Poli": {"PK": [
        "droga", "consumo de droga", "dependencia droga", "adicción drogas", "sustancias"
    ]},

    "Anemia Crónica": {"PK": [
        "anemia", "déficit hemoglobina", "baja hemoglobina", "anemia crónica"
    ]},

    "Trastornos Alimentarios": {"PK": [
        "trastorno alimentario", "anorexia", "bulimia", "alimentación compulsiva", "alimentación desordenada"
    ]},

    "Artritis Reumatoidea": {"PK": [
        "artritis", "reumatoidea", "inflamación articular", "artritis crónica", "artritis reumatoide"
    ]},

    "Artrosis de Rodilla, Cadera u Otro Tipo": {"PK": [
        "artrosis", "degeneración articular", "artrosis rodilla", "artrosis cadera", "articulación desgastada"
    ]},

    "Asma": {"PK": [
        "asma", "crisis asmática", "dificultad respiratoria", "broncoespasmo"
    ]},

    "Catarata/Retinopatía": {"PK": [
        "catarata", "retinopatía", "problemas de visión", "opacidad ocular", "retina dañada"
    ]},

    "Ceguera": {"PK": [
        "ceguera", "no ve", "pérdida de visión", "invidente", "sin vista"
    ]},

    "Demencia": {"PK": [
        "demencia", "Alzheimer", "deterioro cognitivo", "pérdida memoria", "trastorno cognitivo"
    ]},

    "Depresión Leve o Moderada": {"PK": [
        "depresión", "depresión leve", "depresión moderada", "tristeza prolongada", "desánimo"
    ]},

    "Depresión Grave, Grave con Ideación Suicida, Refractaria y con Psicosis": {"PK": [
        "depresión grave", "ideación suicida", "depresión con psicosis", "depresión resistente", "suicidio"
    ]},

    "Diabetes Mellitus": {"PK": [
        "diabetes", "azúcar alta", "glucosa elevada", "diabetes mellitus", "insulina"
    ]},

    "Dificultades Socioeconómicas o Psicosociales": {"PK": [
        "problema social", "dificultades económicas", "contexto social adverso", "problema psicosocial"
    ]},

    "Dislipidemias": {"PK": [
        "dislipidemia", "colesterol alto", "triglicéridos altos", "hiperlipidemia", "alteración lípidos"
    ]},

    "Enfermedad Cerebrovascular/ACV/AVE": {"PK": [
        "accidente cerebrovascular", "acv", "ave", "derrame cerebral", "enfermedad cerebrovascular"
    ]},

    "Isquemia Cerebral Transitoria": {"PK": [
        "isquemia cerebral", "accidente isquémico transitorio", "AIT", "isquemia transitoria"
    ]},

    "Enfermedad Hepática": {"PK": [
        "hígado", "hepatopatía", "enfermedad hepática", "cirrosis", "hígado dañado"
    ]},

    "EPOC": {"PK": [
        "epoc", "enfermedad pulmonar obstructiva crónica", "enfisema", "bronquitis crónica"
    ]},

    "Enfermedad Renal Crónica": {"PK": [
        "insuficiencia renal", "enfermedad renal crónica", "daño renal", "falla renal"
    ]},

    "Enfermedad Renal Crónica Avanzada": {"PK": [
        "insuficiencia renal avanzada", "falla renal avanzada", "enfermedad renal terminal"
    ]},

    "Enfermedades Cardiovasculares/miocardiopatía": {"PK": [
        "cardiopatía", "enfermedad cardíaca", "miocardiopatía", "problema cardíaco"
    ]},

    "Trastorno Ansioso": {"PK": [
        "ansiedad", "trastorno ansioso", "crisis de ansiedad", "trastorno de pánico"
    ]},

    "Trastorno de Personalidad": {"PK": [
        "trastorno de personalidad", "personalidad límite", "trastorno borderline", "trastorno antisocial"
    ]},

    "Tuberculosis": {"PK": [
        "tuberculosis", "tbc", "infección pulmonar", "bacilo de koch"
    ]},

    "Enteritis Crónica/Colitis Ulcerosa/Crohn": {"PK": [
        "colitis ulcerosa", "crohn", "enteritis crónica", "inflamación intestinal", "enfermedad inflamatoria intestinal"
    ]},

    "Epilepsia": {"PK": [
        "epilepsia", "convulsiones", "ataques epilépticos", "crisis epiléptica"
    ]},

    "Esclerosis Múltiple": {"PK": [
        "esclerosis múltiple", "EM", "trastorno neurológico", "esclerosis"
    ]},

    "Esquizofrenia": {"PK": [
        "esquizofrenia", "psicosis", "trastorno psicótico", "esquizofrénico"
    ]},

    "Fibrilación Auricular/Flutter": {"PK": [
        "fibrilación auricular", "flutter", "arritmia auricular", "palpitaciones irregulares"
    ]},

    "Función Limitada/Discapacidad/Dependencia": {"PK": [
        "discapacidad", "limitación funcional", "dependencia física", "incapacidad"
    ]},

    "Glaucoma": {"PK": [
        "glaucoma", "presión ocular alta", "daño nervio óptico"
    ]},

    "Hiperuricemia": {"PK": [
        "ácido úrico", "hiperuricemia", "gota"
    ]},

    "Hipertensión": {"PK": [
        "hipertensión", "presión alta", "tensión arterial alta", "HTA"
    ]},

    "Hipertrofia Prostática Benigna": {"PK": [
        "hipertrofia prostática", "próstata agrandada", "problema urinario", "HPB"
    ]},

    "Trastornos Tiroideos": {"PK": [
        "hipotiroidismo", "hipertiroidismo", "tiroides", "trastorno tiroideo"
    ]},

    "Infección por VIH/SIDA":{"PK": [
        r'\bVIH\b', r'\bvirus de inmunodeficiencia humana\b', r'\bsíndrome de inmunodeficiencia adquirida\b', r'\binfección por VIH\b'
    ]},
    "Insuficiencia Cardíaca": {"PK": [
        "insuficiencia cardíaca", "falla cardíaca", "corazón débil", "deficiencia cardíaca"
    ]},

    "Lupus": {"PK": [
        "lupus", "lupus eritematoso", "lupus sistémico"
    ]},

    "Malignidad/Neoplasia/Tumor Maligno/Cáncer No Especificado": {"PK": [
        "cáncer", "tumor", "neoplasia maligna", "malignidad", "carcinoma"
    ]},

    "Maltrato Físico/Psicológico/Abuso Sexual/Violación": {"PK": [
        "maltrato físico", "maltrato psicológico", "abuso sexual", "violación", "violencia"
    ]},

    "Intento Suicida": {"PK": [
        "suicidio", "intento de suicidio", "autolesión", "conducta suicida"
    ]},

    "Dolor Neuropático/Fibromialgia": {"PK": [
        "fibromialgia", "dolor neuropático", "dolor crónico", "dolor nervioso"
    ]},

    "Obesidad": {"PK": [
        "obesidad", "sobrepeso severo", "obeso", "exceso de peso"
    ]},

    "Parkinsonismo": {"PK": [
        "parkinson", "parkinsonismo", "temblores", "rigidez muscular"
    ]},

    "Presbiacusia/Hipoacusia/Sordera": {"PK": [
        "sordera", "hipoacusia", "pérdida auditiva", "presbiacusia"
    ]},

    "Trastornos de Coagulación": {"PK": [
        "trastorno de coagulación", "hemofilia", "coagulación defectuosa", "sangrado fácil"
    ]},

    "Retraso Mental": {"PK": [
        "retraso mental", "discapacidad intelectual", "déficit cognitivo", "discapacidad mental"
    ]},

    "Arritmia Cardíaca/Taquicardia Paroxística": {"PK": [
        "arritmia", "taquicardia", "palpitaciones rápidas", "arritmia cardíaca"
    ]},

    "Trastornos de Sueño": {"PK": [
        "trastorno de sueño", "insomnio", "apnea del sueño", "sueño interrumpido"
    ]},

    "Otros Trastornos de Salud Mental": {"PK": [
        "trastorno mental", "problema psicológico", "trastorno psiquiátrico", "enfermedad mental"
    ]},

    "Úlcera Crónica de la Piel": {"PK": [
        "úlcera crónica", "llaga en piel", "herida crónica", "úlceras cutáneas"
    ]}
}

    # Columnas de diagnóstico
    col_diag = [c for c in df.columns if c.startswith("DIAGNOSTICO")]

    # Clasificar diagnósticos directamente en Pandas (evita copias pesadas a Polars)
    for col in col_diag:
        # Inicializar como 'Sin Clasificar'
        df[f"{col}_CLASIFICADO"] = "Sin Clasificar"
        
        # Convertir a string de forma segura y a minúsculas para comparar
        diag_series = df[col].astype(str).str.strip().str.lower()
        
        for cat, vals in diccionario.items():
            patron = "|".join([re.escape(f.lower()) for f in vals["PK"]])
            
            # Buscamos coincidencias con regex insensible a mayúsculas
            mask = diag_series.str.contains(patron, regex=True, na=False)
            df.loc[mask, f"{col}_CLASIFICADO"] = cat

    # Agrupación ultra-eficiente por RUT para obtener conteo de patologías únicas
    # Extraemos solo RUT y las columnas clasificadas para evitar copiar todo el DataFrame
    cols_class = [f"{col}_CLASIFICADO" for col in col_diag]
    if 'RUT' in df.columns and cols_class:
        df_temp = df[['RUT'] + cols_class].copy()
        
        # Flattener (melt) para contar en forma vectorial y limpia
        df_melted = df_temp.melt(id_vars=['RUT'], value_vars=cols_class, value_name='DIAG')
        
        # Filtrar no clasificados y nulos
        df_melted = df_melted[(df_melted['DIAG'] != 'Sin Clasificar') & (df_melted['DIAG'].notna())]
        
        # Agrupar y contar únicos
        df_num_class = df_melted.groupby('RUT')['DIAG'].nunique()
        
        # Asignar directamente usando .map() para evitar copiar las 70 columnas en un merge
        df['TOTAL_UNICAS'] = df['RUT'].map(df_num_class)
    else:
        df['TOTAL_UNICAS'] = 0

    df['TOTAL_UNICAS'] = df['TOTAL_UNICAS'].fillna(0).astype(int)

    return df