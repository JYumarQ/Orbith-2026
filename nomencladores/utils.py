"""Utilidades del nomenclador de cargos (las usa `nomencladores/importacion.py`)."""

def normalizar(texto):
    """Limpia espacios, saltos de línea y ELIMINA los 'nan' de Excel"""
    if texto is None:
        return ""
    
    t = str(texto).strip()
    if t.lower() == 'nan':
        return ""
        
    return " ".join(t.split())

def obtener_categoria_codigo(texto):
    """Mapea el texto del Excel a los códigos de 3 letras de tu modelo"""
    t = normalizar(texto).upper()
    if not t: return None
    
    # Mapeo según tu models.py
    if 'OBRERO' in t or 'OPERARIO' in t: return 'OPE'
    if 'ADMINISTRATIVO' in t: return 'ADM'
    if 'SERVICIO' in t: return 'SER'
    if 'TÉCNICO' in t or 'TECNICO' in t: return 'TEC'
    if 'EJECUTIVO' in t: return 'CEJ'
    if 'CUADRO' in t or 'DIRIGENTE' in t: return 'CDI'
    
    return None
