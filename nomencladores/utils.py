import pandas as pd
from django.db import transaction
from .models import NCargo, NGrupoEscala

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
    if 'OPERARIO' in t or 'OBRERO' in t: return 'OPE'
    if 'ADMINISTRATIVO' in t: return 'ADM'
    if 'SERVICIO' in t: return 'SER'
    if 'TÉCNICO' in t or 'TECNICO' in t: return 'TEC'
    if 'EJECUTIVO' in t: return 'CEJ'
    if 'CUADRO' in t or 'DIRIGENTE' in t: return 'CDI'
    
    return None

def importar_cargos_excel(archivo, estrategia):
    log = {'creados': 0, 'actualizados': 0, 'saltados': 0, 'errores': []}

    try:
        # 1. Leer Excel con PANDAS
        xls = pd.ExcelFile(archivo)
        
        # Intentamos buscar la hoja 'CARGOS_CODIGO', si no, la primera
        hoja = 'CARGOS_CODIGO' if 'CARGOS_CODIGO' in xls.sheet_names else xls.sheet_names[0]
        
        # --- CAMBIO IMPORTANTE PARA "Cargos OK.xlsx" ---
        # header=0 significa que los títulos están en la FILA 1
        df = pd.read_excel(xls, sheet_name=hoja, header=0, dtype=str)
        
        # Limpiar nombres de columnas
        df.columns = df.columns.str.replace('\n', ' ').str.strip()

        col_cargo = 'Cargos'
        if col_cargo not in df.columns:
             # Fallback por si la columna se llama diferente
             if len(df.columns) > 0: col_cargo = df.columns[0] # En tu nuevo excel, Cargos es la primera (A)
             else: return {'fatal': "No se encontró la columna 'Cargos' en el Excel."}

        # 2. Procesar filas
        with transaction.atomic():
            for index, row in df.iterrows():
                # Fila visual en Excel = index + header(1) + 1 base = index + 2
                fila = index + 2 
                
                nombre = normalizar(row.get(col_cargo))
                if not nombre: continue 

                # Obtener datos (Usando los nombres exactos de "Cargos OK.xlsx")
                grupo_txt = normalizar(row.get('Grupo  Escala') or row.get('Grupo Escala')) 
                cat_txt = normalizar(row.get('Categoría Ocupacional'))
                salario_txt = row.get('Salario Básico')

                # Validaciones
                if not grupo_txt:
                    log['errores'].append(f"Fila {fila}: Falta 'Grupo Escala' para el cargo '{nombre}'")
                    continue
                
                if not cat_txt:
                    log['errores'].append(f"Fila {fila}: Falta 'Categoría' para el cargo '{nombre}'")
                    continue

                cat_codigo = obtener_categoria_codigo(cat_txt)
                if not cat_codigo:
                    log['errores'].append(f"Fila {fila}: Categoría desconocida '{cat_txt}'")
                    continue

                grupo_obj = NGrupoEscala.objects.filter(nivel__iexact=grupo_txt).first()
                if not grupo_obj:
                    log['errores'].append(f"Fila {fila}: El Grupo '{grupo_txt}' no existe en la BD.")
                    continue

                try:
                    salario_Lim = str(salario_txt).replace('$', '').replace(',', '').strip()
                    if salario_Lim.lower() == 'nan': salario_val = 0
                    else: salario_val = float(salario_Lim)
                except:
                    salario_val = 0

                # --- Guardar ---
                cargo_obj, created = NCargo.objects.get_or_create(
                    descripcion__iexact=nombre,
                    defaults={
                        'descripcion': nombre,
                        'cat_ocupacional': cat_codigo,
                        'grupo_escala': grupo_obj,
                        'salario_basico': salario_val,
                        'activo': True
                    }
                )

                if created:
                    log['creados'] += 1
                else:
                    if estrategia == 'ACTUALIZAR':
                        cargo_obj.descripcion = nombre
                        cargo_obj.cat_ocupacional = cat_codigo
                        cargo_obj.grupo_escala = grupo_obj
                        cargo_obj.salario_basico = salario_val
                        cargo_obj.activo = True
                        cargo_obj.save()
                        log['actualizados'] += 1
                    else:
                        log['saltados'] += 1

    except Exception as e:
        return {'fatal': str(e)}

    return log