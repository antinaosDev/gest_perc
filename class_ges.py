import pandas as pd
import re
import requests
from io import BytesIO
import streamlit as st
import polars as pl





# Definir los diccionarios de palabras clave y rangos etarios
diccionario = {
    "Insuficiencia Renal Cronica Terminal": {"PK": [
        "insuficiencia renal", "terminal", "deficiencia renal", "falta renal", 
        "insuficiencia terminal", "insuficiencia renal crónica"
    ],"emin":0,"emax":150} ,
    "Cardiopatia Congenita Operable": { "PK": [
        "cardiopatía", "congénita", "enfermedad cardíaca", "cardiopatía congénita", "malformación cardíaca", 
        "trastorno cardíaco", "cardiopatía operable"
    ],"emin":0,"emax":14},
    "Cancer Cervico Uterino": {"PK":[
        "cáncer cervical", "cérvico uterino", "tumor cervical", "cáncer del cuello uterino", "neoplasia uterina", 
        "cáncer cérvico uterino"
    ],"emin":0,"emax":150},
    "Alivio del Dolor": {"PK":[
        "alivio del dolor", "alivio sintomático", "alivio", 
        "tratamiento del dolor", "control del dolor"
    ],"emin":0,"emax":150},
    "Infarto Agudo del Miocardio": {"PK":[
        "infarto de miocardio", "infarto agudo", "infarto cardíaco", "ataque al corazón", "infarto coronario", 
        "infarto miocárdico"
    ],"emin":0,"emax":150},
    "Diabetes Mellitus Tipo II":{"PK": [
        "diabetes tipo 2", "diabetes mellitus tipo 2", "mellitus no insulinodependiente",
        "diabetes tipo II", "diabetes mellitus no especificada, sin complicación",
        "diabetes mellitus sin complicación", "diabetes mellitus tipo 2, sin complicación"
    ],"emin":0,"emax":150},
    "Diabetes Mellitus Tipo I": {"PK":[
        "diabetes mellitus", "diabetes tipo 1", "diabetes mellitus tipo 1", "diabetes tipo I",
        "mellitus insulinodependiente", "diabetes mellitus insulinodependiente",
        "diabetes mellitus especificada, con complicaciones circulatorias periféricas"
    ],"emin":0,"emax":150},
    "Cancer de Mamas": {"PK":[
        "cáncer de mama", "cáncer mamario", "tumor mamario", "carcinoma mamario", "neoplasia mamaria", 
        "cáncer de mamas"
    ],"emin":0,"emax":150},
    "Disrafias Espinales": {"PK":[
        "disrafias", "espinales", "defectos del tubo neural", "malformaciones espinales", "espina bífida", 
        "disrafia espinal"
    ],"emin":0,"emax":150},
    "Escoliosis":{"PK": [
        "escoliosis", "curvatura de la columna", "desviación espinal", "columna vertebral curvada", 
        "escoliosis idiopática"
    ],"emin":0,"emax":24},
    "Cataratas":{"PK": [
        "cataratas", "opacidad del cristalino", "trastorno del ojo", "catarata senil", "catarata congénita", 
        "catarata opaca"
    ],"emin":0,"emax":150},
    "Endoprotesis Total de Caderas": {"PK":[
        "endoprótesis", "prótesis total de cadera", "implante de cadera", "reemplazo total de cadera", 
        "endoprótesis de cadera"
    ],"emin":66,"emax":150},
    "Fisura Labiopalatina":{"PK": [
        "fisura labial", "fisura palatina", "fisura labiopalatina", "malformación labio-palatal", "defecto congénito labial"
    ],"emin":0,"emax":150},
    "Cancer de Leucemia, Linfomas y/o Tumores Sólidos":{"PK": [
        "leucemia", "linfomas", "tumores sólidos", "cáncer hematológico", "neoplasias hematológicas", 
        "linfoma maligno", "tumor linfático"
    ],"emin":0,"emax":14},
    "Esquizofrenia": {"PK":[
        "esquizofrenia", "trastorno esquizofrénico", "enfermedad mental crónica", "esquizofrenia paranoide", 
        "esquizofrenia desorganizada"
    ],"emin":0,"emax":150},
    "Cancer de Testiculo":{"PK": [
        "cáncer testicular", "tumor testicular", "neoplasia testicular", "carcinoma testicular", "cáncer de testículo"
    ],"emin":16,"emax":150},
    "Linfoma en Adultos":{"PK": [
        "linfoma", "linfoma en adultos", "neoplasia linfática", "linfoma maligno", "tumor linfático"
    ],"emin":16,"emax":150},
     "VIH/SIDA":{"PK": [
        r'\bVIH\b', r'\bvirus de inmunodeficiencia humana\b', r'\bsíndrome de inmunodeficiencia adquirida\b', r'\binfección por VIH\b'
    ],"emin":0,"emax":150},
    "Infeccion Respiratoria Aguda": {"PK":[
        "infección respiratoria", "infección aguda", "trastorno respiratorio", "afección respiratoria"
    ],"emin":0,"emax":4},
    "Neumonia": {"PK":[
        "neumonía", "inflamación pulmonar", "infección pulmonar", "neumonía bacteriana", "neumonía viral"
    ],"emin":66,"emax":150},
    "Hipertension Arterial":{"PK": [
        "hipertensión", "presión alta", "hipertensión arterial", "enfermedad hipertensiva", "trastorno hipertensivo", 
        "presión arterial alta"
    ],"emin":16,"emax":150},
    "Epilepsia no Refractaria": {
    "PK": [
        "epilepsia", "epilepsia refractaria", "epilepsia resistente", "crisis epiléptica no controlada", 
        "epilepsia no controlada"
    ],
    "emin": 0,
    "emax": 14
},
    "Salud Oral Integral":{"PK": [
        "salud oral", "cuidado bucal", "salud bucal", "higiene oral", "salud dental", "enfermedad oral"
    ],"emin":0,"emax":5},
    "Prematurez": {"PK": [
        "prematurez", "nacimiento prematuro", "prematuridad", "bebé prematuro", "desarrollo prematuro"
    ],"emin":0,"emax":0},
    "Marcapasos":{"PK": [
        "marcapasos", "estimulador cardíaco", "dispositivo de marcapasos", "aparato de marcapasos", "marcapasos cardíaco"
    ],"emin":16,"emax":150},
    "Colecistectomia Preventiva": {"PK":[
        "colecistectomía", "cirugía preventiva", "extracción de vesícula biliar", "colecistectomía profiláctica", 
        "prevención de cálculos biliares"
    ],"emin":36,"emax":48},
    "Cancer Gastrico": {"PK":[
        "cáncer gástrico", "tumor gástrico", "neoplasia gástrica", "cáncer de estómago", "carcinoma gástrico"
    ],"emin":0,"emax":150},
    "Cancer de Prostata": {"PK":[
        "cáncer de próstata", "tumor prostático", "neoplasia prostática", "carcinoma prostático", "cáncer prostático"
    ],"emin":16,"emax":150},
    "Vicios de Refraccion":{"PK": [
        "vicios de refracción", "errores refractivos", "trastornos refractivos", "problemas refractivos oculares"
    ],"emin":66,"emax":150},
    "Estrabismo":{"PK": [
        "estrabismo", "desviación ocular", "ojo bizco", "trastorno de alineación ocular", "estrabismo convergente", 
        "estrabismo divergente"
    ],"emin":0,"emax":8},
    "Retinopatía Diabetica":{"PK": [
        "retinopatía diabética", "daño retinal diabético", "enfermedad retinal diabética", "retinopatía asociada a diabetes"
    ],"emin":0,"emax":150},
    "Desprendimiento de Retina":{"PK": [
        "desprendimiento de retina", "desprendimiento retinal", "problema retinal", "separación de retina"
    ],"emin":0,"emax":150},
    "Hemofilia":{"PK": ["hemofilia", "trastorno hemorrágico", "enfermedad de la coagulación", "deficiencia de factores de coagulación", "hemorragia"
                        ]
    ,"emin":0,"emax":150},
    "Depresion": {"PK":[
        "depresión", "trastorno depresivo", "estado depresivo", "enfermedad depresiva", "depresión clínica"
    ],"emin":16,"emax":150},
    "Hiperplasia de Prostata":{"PK": [
        "hiperplasia prostática", "hiperplasia próstata","agrandamiento de próstata", "hiperplasia benigna de próstata", "trastorno prostático"
    ],"emin":16,"emax":150},
    "Ortesis": {"PK":[
        "ortesis", "dispositivo ortopédico", "soporte ortopédico", "prótesis ortopédica", "aparato ortopédico"
    ],"emin":66,"emax":150},
    "Accidente Cerebrovascular Isquemico":{"PK": [
        "cerebrovascular isquémico", "ACV isquémico", "infarto cerebral", "accidente cerebrovascular isquémico", 
        "ictus isquémico"
    ],"emin":16,"emax":150},
    "Enfermedad Pulmonar Obstructiva Cronica":{"PK": [
        "EPOC","pulmonar crónica", "enfermedad pulmonar crónica", "enfermedad pulmonar obstructiva crónica", 
        "bronquitis crónica"
    ],"emin":0,"emax":14},
    "Asma Bronquial":{"PK": [
        "asma", "asma bronquial", "enfermedad asmática", "trastorno asmático", "crisis asmática", 
        "asma crónica"
    ],"emin":16,"emax":150},
    "Sindrome de Dificultad Respiratoria": {"PK": [
        "síndrome de dificultad respiratoria", "SDSR", "síndrome respiratorio", "dificultad respiratoria", 
        "trastorno respiratorio agudo"
    ],"emin":0,"emax":0},
    "Tratamiento Medico en Personas con Artrosis de Cadera y/o Rodilla, Leve o Moderada": {"PK": [
        "tratamiento médico artrosis", "artrosis de cadera", "artrosis de rodilla", "artrosis leve", 
        "artrosis moderada", "tratamiento artrosis"
    ],"emin":56,"emax":150},
    "Hemorragia Subaracnoidea Secundaria a Ruptura de Aneurisma Cerebral": {"PK": [
        "hemorragia subaracnoidea", "aneurisma cerebral", "hemorragia cerebral", "ruptura de aneurisma", 
        "hemorragia secundaria"
    ],"emin":0,"emax":150},
    "Tratamiento Quirurgico de Tumores Primarios del Sistema Nervioso Central": {"PK":[
        "tratamiento quirúrgico tumores", "tumores del sistema nervioso", "cirugía de tumores cerebrales", 
        "neoplasias del sistema nervioso", "tumores primarios cerebrales"
    ],"emin":16,"emax":150},
    "Hernia del Nucleo Pulposo Lumbar": {"PK": [
        "hernia lumbar", "hernia del núcleo pulposo", "herniación lumbar", "problema lumbar", 
        "disco intervertebral herniado"
    ],"emin":0,"emax":150},
    "Leucemia en Personas de 15 años y mas":{"PK": [
        "leucemia", "leucemia en adultos", "leucemia en mayores de 15 años", "cáncer hematológico", 
        "neoplasia leucémica"
    ],"emin":16,"emax":150},
    "Urgencias Odontologicas Ambulatorias":{"PK": [
        "urgencias odontológicas", "atención dental urgente", "emergencias dentales", "cuidado odontológico ambulatorio","Odontológica Ambulatoria"
    ],"emin":0,"emax":150},
    "Atencion Odontologica en Personas de 60 anios":{"PK": [
        "odontológica","atención odontológica", "cuidado dental en mayores", "atención dental en personas de 60 años", 
        "salud bucal en ancianos"
    ],"emin":61,"emax":150},
    "Politraumatizado Grave": {"PK":[
        "politraumatizado", "traumatismos graves", "paciente politraumatizado", "trauma severo", 
        "atención de politraumatizados"
    ],"emin":0,"emax":150},
    "Atencion de Urgencia por Traumatismo Craneo Encefalico Moderado o Grave": {"PK":[
        "traumatismo cráneo encefálico", "traumatismo cerebral","traumatismo cráneo","lesión cerebral moderada", 
        "lesión cerebral grave", "atención urgente trauma cerebral"
    ],"emin":0,"emax":150},
    "Atencion Ocular Grave": {"PK":[
        "atención ocular", "emergencia ocular", "problema ocular grave", "cuidado ocular crítico", 
        "emergencia oftalmológica"
    ],"emin":0,"emax":150},
    "Fibrosis Quistica":{"PK": [
        "fibrosis quística", "enfermedad pulmonar genética", "trastorno pulmonar", "fibrosis quística sistémica", 
        "enfermedad hereditaria"
    ],"emin":0,"emax":150},
    "Artritis Juvenil Reumatoide":{"PK": [
        "artritis","artritis juvenil", "artritis reumatoide", "artritis en niños", "enfermedad articular juvenil", 
        "artritis infantil"
    ],"emin":0,"emax":16},
    "Consumo Perjudicial y Dependencia de Alcohol y Drogas":{"PK": [
        "dependencia de alcohol", "adicción a drogas", "consumo perjudicial", "trastorno por consumo de sustancias", 
        "abuso de alcohol"
    ],"emin":0,"emax":19},
    "Analgesia de Parto":{"PK": [
        "analgesia de parto", "alivio del dolor en parto", "manejo del dolor en parto", "analgesia obstétrica", 
        "control del dolor durante el parto"
    ],"emin":0,"emax":150},
    "Gran Quemado": {"PK":[
        "gran quemado", "paciente quemado", "quemaduras graves", "tratamiento de quemaduras extensas", 
        "quemaduras severas"
    ],"emin":0,"emax":150},
    "Hipoacusia Bilateral en Personas que Requieren Uso de Audifono":{"PK": [
        "hipoacusia bilateral", "pérdida auditiva", "uso de audífono", "sordera bilateral", 
        "deficiencia auditiva bilateral"
    ],"emin":66,"emax":150},
    "Retinopatia del Prematuro":{"PK": [
        "retinopatía","retinopatía del prematuro", "retinopatía en prematuros", "enfermedad ocular en prematuros", 
        "problema ocular prematuro"
    ],"emin":0,"emax":0},
    "Displasia Broncopulmonar del Prematuro":{"PK": [
        "Broncopulmonar","displasia broncopulmonar", "enfermedad pulmonar en prematuros", "displasia pulmonar prematura", 
        "problema respiratorio prematuro"
    ],"emin":0,"emax":0},
    "Hipoacusia Neurosensorial Bilateral del Prematuro":{"PK": [
        "hipoacusia","hipoacusia neurosensorial", "pérdida auditiva bilateral", "deficiencia auditiva en prematuros", 
        "sordera neurosensorial bilateral"
    ],"emin":0,"emax":0},
    "Epilepsia no Refractaria": {"PK": [
        "epilepsia","no refractaria", "epilepsia no refractaria", "epilepsia resistente", "crisis epiléptica no controlada", 
        "epilepsia no controlada"
    ],"emin":16,"emax":150},
    "Asma Bronquial": {"PK":[
        "asma", "asma bronquial", "enfermedad asmática", "trastorno asmático", "crisis asmática", 
        "asma crónica"
    ],"emin":16,"emax":150},
    "Enfermedad de Parkinson":{"PK":[
        "enfermedad de Parkinson", "Parkinson", "trastorno de Parkinson", "parkinsonismo", 
        "enfermedad neurodegenerativa"
    ],"emin":17,"emax":150},
    "Artritis Reumatoide Juvenil":{"PK": [
        "artritis","artritis reumatoide", "artritis juvenil", "enfermedad articular juvenil", "artritis crónica en niños", 
        "artritis reumatoide infantil"
    ],"emin":0,"emax":16},
    "Prevencion Secundaria en Pacientes con IRC":{"PK": [
        "prevención secundaria", "insuficiencia renal crónica", "tratamiento de IRC", "cuidado de pacientes con IRC", 
        "manejo de insuficiencia renal"
    ],"emin":14,"emax":150},
    "Displasia Luxante de Cadera": {"PK": [
        "displasia","displasia de cadera", "luxación de cadera", "displasia luxante", "problema de cadera", 
        "displasia coxofemoral"
    ],"emin":0,"emax":0},
    "Salud Oral de la Embarazada":{"PK": ["Salud Oral de la Embarazada","Salud oral de la embarazada"
        ,"salud oral durante el embarazo", "cuidado dental en embarazadas", "salud bucal de la embarazada", 
        "atención odontológica en embarazo"
    ],"emin":13,"emax":150},
    "Esclerosis Multiple Recurrente Remitente (todo beneficio)":{"PK": [
        "esclerosis múltiple", "esclerosis múltiple remitente", "EM recurrente", "esclerosis múltiple recurrente remitente", 
        "enfermedad neurológica"
    ],"emin":0,"emax":150},
    "Hepatitis B":{"PK": [
        "hepatitis B", "infección por hepatitis B", "enfermedad hepática viral", "hepatitis B crónica", 
        "hepatitis viral"
    ],"emin":0,"emax":150},
    "Hepatitis C":{"PK": [
        "hepatitis C", "infección por hepatitis C", "enfermedad hepática viral", "hepatitis C crónica", 
        "hepatitis viral"
    ],"emin":0,"emax":150},
    "Cancer Colorrectal": {"PK":[
        "cáncer colorrectal", "tumor colorrectal", "neoplasia colorrectal", "carcinoma colorrectal", 
        "cáncer de colon"
    ],"emin":16,"emax":150},
    "Cancer de Ovario Epitelial": {"PK":[
        "cáncer de ovario", "cáncer epitelial de ovario", "tumor de ovario", "neoplasia epitelial de ovario", 
        "carcinoma ovárico"
    ],"emin":0,"emax":150},
    "Cancer Vesical":{"PK": [
        "cáncer vesical", "cáncer de vejiga", "tumor vesical", "neoplasia de vejiga", "carcinoma vesical"
    ],"emin":16,"emax":150},
    "Osteosarcoma":{"PK": [
        "osteosarcoma", "tumor óseo", "sarcoma óseo", "neoplasia ósea", "cáncer óseo"
    ],"emin":16,"emax":150},
    "Tratamiento Quirurgico de Valvula Aortica":{"PK": [
        "tratamiento quirúrgico", "válvula aórtica", "cirugía de válvula aórtica", "reemplazo de válvula aórtica", 
        "intervención quirúrgica aórtica"
    ],"emin":16,"emax":150},
    "Trastorno Bipolar":{"PK": [
        "bipolar","trastorno bipolar", "enfermedad bipolar", "trastorno afectivo bipolar", "bipolaridad", 
        "enfermedad mental bipolar"
    ],"emin":16,"emax":150},
    "Hipotiroidismo":{"PK": [
        "hipotiroidismo", "función tiroidea reducida", "tiroiditis", "trastorno tiroideo", "deficiencia tiroidea"
    ],"emin":16,"emax":150},
    "Tratamiento de Hipoacusia en Menores de 2 años": {
    "PK": [
        "hipoacusia", "tratamiento de hipoacusia", "deficiencia auditiva en menores", 
        "pérdida auditiva en niños pequeños", "hipoacusia en menores de 2 años"
    ],
    "emin": 0,
    "emax": 1
},
    "Lupus Eritematoso Sistemico":{"PK": [
        "lupus eritematoso sistémico", "lupus", "enfermedad autoinmune", "trastorno autoinmune", 
        "lupus sistémico"
    ],"emin":0,"emax":150},
    "Tratamiento Quirurgico de Valvulas Tricuspides":{"PK": [
        "tratamiento quirúrgico válvulas tricúspides", "válvula tricúspide", "cirugía de válvula tricúspide", 
        "reemplazo de válvula tricúspide", "intervención quirúrgica tricúspide"
    ],"emin":16,"emax":150},
    "Tratamiento para Erradicacion de Helicobacter Pylori":{"PK": [
        "Pylori","tratamiento helicobacter pylori", "erradicación helicobacter", "terapia para helicobacter pylori", 
        "cura helicobacter pylori", "tratamiento para erradicación bacteriana"
    ],"emin":0,"emax":150},
    "Cancer de Pulmon":{"PK": [
        "cáncer de pulmón", "tumor pulmonar", "neoplasia pulmonar", "carcinoma pulmonar", 
        "cáncer pulmonar"
    ],"emin":0,"emax":150},
    "Cancer de Tiroides":{"PK": [
        "cáncer de tiroides", "tumor tiroides", "neoplasia tiroides", "carcinoma tiroides", 
        "cáncer tiroides"
    ],"emin":0,"emax":150},
    "Cancer Renal":{"PK": [
        "cáncer renal", "tumor renal", "neoplasia renal", "carcinoma renal", "cáncer de riñón"
    ],"emin":0,"emax":150},
    "Mieloma Multiple": {"PK":[
        "mieloma múltiple", "cáncer de médula ósea", "neoplasia de médula ósea", "tumor de médula ósea", 
        "mieloma"
    ],"emin":0,"emax":150},
    "Enfermedad de Alzheimer y otras demencias":{
        "PK": [
            "enfermedad de Alzheimer", "Alzheimer", "demencia", "enfermedades neurodegenerativas", 
            "demencia senil", "Demencia en la enfermedad de Alzheimer", "Demencia vascular", 
            "Demencia multinfarto", "Otras demencias vasculares", "Demencia en la enfermedad de Pick", 
            "Demencia en la enfermedad de Creutzfeldt-Jakob", "Demencia por cuerpos de Lewy", 
            "Demencias frontotemporales", "Demencia en la enfermedad de Huntington", 
            "Demencia en la enfermedad de Parkinson", "Demencia en la infección por VIH", 
            "Demencia en enfermedades especíﬁcas clasiﬁcadas en otro lugar"
        ],
        "emin": 0,
        "emax": 150
    }

}



def cargar_archivo_class_ges_pandas(df: pd.DataFrame, diccionario: dict) -> pd.DataFrame:
    # Hacemos una copia local de las columnas necesarias para trabajar de forma ligera
    # para evitar duplicar las 70 columnas en la RAM!
    df_temp = df[['EDAD', 'DIAGNOSTICO 1', 'DIAGNOSTICO 2', 'DIAGNOSTICO 3']].copy()
    
    # Rellenar nulos
    for i in range(1, 4):
        df_temp[f"DIAGNOSTICO {i}"] = df_temp[f"DIAGNOSTICO {i}"].astype(str).str.strip().str.lower()
        df_temp[f"FINAL_{i}"] = "Sin Clasificar"

    # Clasificación y criterio etario en Pandas vectorizado
    for i in range(1, 4):
        diag_col = f"DIAGNOSTICO {i}"
        final_col = f"FINAL_{i}"
        
        # Para cada categoría
        for categoria, valores in diccionario.items():
            patron = "|".join([re.escape(f.lower()) for f in valores["PK"]])
            edad_min, edad_max = valores["emin"], valores["emax"]
            
            # Encontrar coincidencia de palabra clave
            mask_kw = df_temp[diag_col].str.contains(patron, regex=True, na=False)
            
            # Encontrar filas que cumplen criterio etario
            mask_edad = (df_temp['EDAD'] >= edad_min) & (df_temp['EDAD'] <= edad_max)
            
            # Coincide y cumple edad -> Asignar categoría
            df_temp.loc[mask_kw & mask_edad, final_col] = categoria
            
            # Coincide pero no cumple edad -> Fuera de criterio etario
            mask_fuera = mask_kw & ~mask_edad & (df_temp[final_col] == "Sin Clasificar")
            df_temp.loc[mask_fuera, final_col] = "Fuera de criterio etario"

    # Determinar CAT_GES (primera coincidencia válida entre FINAL_1, FINAL_2, FINAL_3)
    # Inicializar con Sin Clasificar
    cat_ges = pd.Series("Sin Clasificar", index=df.index)
    
    # Ir de FINAL_3 a FINAL_1 (para que FINAL_1 tenga prioridad al sobreescribir)
    for i in [3, 2, 1]:
        final_col = f"FINAL_{i}"
        mask_valid = ~df_temp[final_col].isin(["Sin Clasificar", "Fuera de criterio etario"])
        cat_ges[mask_valid] = df_temp.loc[mask_valid, final_col]
        
    # Asignar al DataFrame original
    df['CAT_GES'] = cat_ges
    return df