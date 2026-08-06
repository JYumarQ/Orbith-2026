from .base import BaseExcelReport
from ..styles import Styles
from ..printer import ExcelPrinter
from ..helpers import ExcelHelpers


def _obtener_nombre_persona(dir_dict):
    """Extrae de forma segura el nombre completo del aspirante/director desde el diccionario."""
    if not isinstance(dir_dict, dict):
        return ""
    
    asp = dir_dict.get("aspirante")
    if not asp:
        nombre_directo = dir_dict.get("nombre") or dir_dict.get("nombre_completo")
        return str(nombre_directo).strip() if nombre_directo else ""
    
    if isinstance(asp, str):
        return asp.strip()
    
    if isinstance(asp, dict):
        nombre = asp.get("nombre_completo") or asp.get("nombre") or ""
        return str(nombre).strip()
    
    if hasattr(asp, "nombre_completo"):
        val = getattr(asp, "nombre_completo")
        val_str = val() if callable(val) else str(val)
        return val_str.strip()
        
    if hasattr(asp, "get_nombre_completo"):
        return str(asp.get_nombre_completo()).strip()
        
    res = str(asp).strip()
    return res if res and not res.startswith("<") else ""


def _obtener_departamentos(unidad):
    """Obtiene la lista de departamentos de una unidad probando varios atributos comunes."""
    if hasattr(unidad, "departamentos_con_cargos"):
        deptos = getattr(unidad, "departamentos_con_cargos")
        return list(deptos() if callable(deptos) else deptos) if deptos else []
        
    if hasattr(unidad, "departamentos"):
        deptos = getattr(unidad, "departamentos")
        if hasattr(deptos, "all"):
            return list(deptos.all())
        elif callable(deptos):
            return list(deptos())
        elif isinstance(deptos, (list, tuple)):
            return list(deptos)
            
    if hasattr(unidad, "departamento_set"):
        return list(unidad.departamento_set.all())
        
    return []


def _obtener_cargos(depto):
    """Obtiene la lista de cargos de un departamento probando varios atributos comunes."""
    if hasattr(depto, "cargos_filtrados"):
        cargos = getattr(depto, "cargos_filtrados")
        return list(cargos() if callable(cargos) else cargos) if cargos else []
        
    if hasattr(depto, "cargos"):
        cargos = getattr(depto, "cargos")
        if hasattr(cargos, "all"):
            return list(cargos.all())
        elif callable(cargos):
            return list(cargos())
        elif isinstance(cargos, (list, tuple)):
            return list(cargos)
            
    if hasattr(depto, "cargo_set"):
        return list(depto.cargo_set.all())
        
    return []


class Anexo14Report(BaseExcelReport):
    title = "ANEXO 14 — ESTRUCTURA JERÁRQUICA Y PLANTILLA APROBADA"
    filename = "Anexo_14_Plantilla.xlsx"

    def generate(self, datos):
        config = datos.get("configuracion")
        etiquetas_cat = datos.get("etiquetas_categoria") or {}
        
        # Configurar metadatos si existen
        if config and getattr(config, "nombre_empresa", None):
            self.empresa_nombre = config.nombre_empresa
        if config and getattr(config, "reup", None):
            self.reup = config.reup

        # Consolidar unidades a procesar (unidades directas + hijas + padre si tiene departamentos/cargos)
        unidades_a_procesar = []
        
        if datos.get("unidades"):
            unidades_a_procesar = list(datos.get("unidades"))
        
        for u in (datos.get("hijas") or []):
            if u not in unidades_a_procesar:
                unidades_a_procesar.append(u)
                
        padre = datos.get("padre_actual")
        if padre and padre not in unidades_a_procesar:
            # Si la unidad padre tiene departamentos directamente, la incluimos al inicio
            deptos_padre = _obtener_departamentos(padre)
            if deptos_padre or not unidades_a_procesar:
                unidades_a_procesar.insert(0, padre)

        if not unidades_a_procesar:
            self.wb.create_sheet("Sin Datos")
            return

        # Iterar por cada Unidad Organizativa
        for unidad in unidades_a_procesar:
            descripcion_unidad = getattr(unidad, "descripcion", "Unidad")
            
            # Limpiar caracteres prohibidos en pestañas de Excel
            safe_title = str(descripcion_unidad)[:31]
            for invalid_char in ["/", "\\", "?", "*", ":", "[", "]"]:
                safe_title = safe_title.replace(invalid_char, "-")

            ws = self.wb.create_sheet(title=safe_title)
            
            # Encabezado institucional
            start_table_row = self.build_common_header(ws, self.title, descripcion_unidad)
            
            # Encabezados de columnas
            headers = ["Cargo", "Cat. Ocup.", "Cant. Aprobada", "Rol", "Nivel de Preparación", "Grupo Escala"]
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=start_table_row, column=col_idx, value=header)
                cell.font = Styles.FONT_HEADER
                cell.alignment = Styles.ALIGN_CENTER
                cell.border = Styles.BORDER_ALL_THIN

            current_row = start_table_row + 1
            data_rows = []
            total_unidad = 0

            departamentos = _obtener_departamentos(unidad)

            # Departamentos dentro de la unidad
            for depto in departamentos:
                depto_desc = getattr(depto, "descripcion", "").upper()
                cargos = _obtener_cargos(depto)

                # Si el departamento no tiene cargos, saltar visualización vacía opcionalmente
                # (mantener si se desea mostrar banner aún sin cargos)
                ExcelHelpers.merge_and_style(
                    ws, 1, current_row, 6, current_row,
                    f"  ▼ DEPARTAMENTO: {depto_desc}",
                    font=Styles.FONT_DEPT,
                    fill=Styles.FILL_BRAND_LIGHT,
                    alignment=Styles.ALIGN_LEFT
                )
                current_row += 1
                subtotal_depto = 0

                # Cargos filtrados
                for cargo in cargos:
                    ncargo = getattr(cargo, "ncargo", None)
                    cat_ocup = getattr(ncargo, "cat_ocupacional", "") if ncargo else ""
                    cat_label = etiquetas_cat.get(cat_ocup, cat_ocup)
                    
                    # Grupo escala
                    grupo_escala_obj = getattr(ncargo, "grupo_escala", None) if ncargo else None
                    grupo_escala_nivel = getattr(grupo_escala_obj, "nivel", "") if grupo_escala_obj else ""

                    cant_aprobada = getattr(cargo, "cant_aprobada", 0) or 0
                    subtotal_depto += cant_aprobada

                    row_data = [
                        getattr(ncargo, "descripcion", "") if ncargo else "",
                        cat_label,
                        cant_aprobada,
                        cargo.rol.tipo if getattr(cargo, "rol", None) else "—",
                        cargo.nivel_preparacion.nombre if getattr(cargo, "nivel_preparacion", None) else "",
                        grupo_escala_nivel
                    ]

                    for col_idx, val in enumerate(row_data, start=1):
                        cell = ws.cell(row=current_row, column=col_idx, value=val)
                        cell.font = Styles.FONT_DATA
                        cell.border = Styles.BORDER_BOTTOM_THIN
                        if col_idx == 1:
                            cell.alignment = Styles.ALIGN_INDENT
                        elif col_idx == 3:
                            cell.alignment = Styles.ALIGN_RIGHT
                        else:
                            cell.alignment = Styles.ALIGN_CENTER

                    data_rows.append(current_row)
                    current_row += 1

                # Subtotal por Departamento
                if cargos:
                    ws.cell(row=current_row, column=1, value="Subtotal Departamento:").font = Styles.FONT_TOTAL
                    ws.cell(row=current_row, column=1).alignment = Styles.ALIGN_RIGHT
                    
                    subtotal_cell = ws.cell(row=current_row, column=3, value=subtotal_depto)
                    subtotal_cell.font = Styles.FONT_TOTAL
                    subtotal_cell.alignment = Styles.ALIGN_RIGHT
                    
                    total_unidad += subtotal_depto
                    current_row += 2

            # Total de la Unidad
            ws.cell(row=current_row, column=1, value=f"TOTAL {str(descripcion_unidad).upper()}:").font = Styles.FONT_HEADER
            ws.cell(row=current_row, column=1).alignment = Styles.ALIGN_RIGHT
            
            total_cell = ws.cell(row=current_row, column=3, value=total_unidad)
            total_cell.font = Styles.FONT_HEADER
            total_cell.alignment = Styles.ALIGN_RIGHT
            total_cell.border = Styles.BORDER_TOTALS
            current_row += 2

            # Firmas personalizadas
            dir_ch = datos.get("director_ch") or {}
            dir_gral = datos.get("director_gral") or {}
            
            nombre_ch = _obtener_nombre_persona(dir_ch)
            nombre_gral = _obtener_nombre_persona(dir_gral)
            
            cargo_ch = dir_ch.get("titulo", "Directora de Capital Humano") if isinstance(dir_ch, dict) else "Directora de Capital Humano"
            cargo_gral = dir_gral.get("titulo", "Director General") if isinstance(dir_gral, dict) else "Director General"

            self.build_custom_signatures(
                ws, 
                current_row, 
                cargo_left=cargo_ch, 
                nombre_left=nombre_ch,
                cargo_right=cargo_gral, 
                nombre_right=nombre_gral
            )

            # Formato de Impresión y Autoajuste de columnas
            ExcelPrinter.setup_page(ws, orientation="landscape", header_repeat_row=start_table_row)
            ExcelHelpers.auto_fit_columns(ws, data_rows)