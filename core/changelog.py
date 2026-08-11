"""Historial de versiones de Orbith.

Fuente única de la versión del sistema y de las novedades que se muestran en el
menú de usuario ("Novedades de la versión" y "Acerca de Orbith").

CÓMO AÑADIR UNA VERSIÓN NUEVA
-----------------------------
Añade un diccionario al PRINCIPIO de la lista CHANGELOG (el primero es siempre
la versión vigente) con esta forma:

    {
        "version": "2.2.0",
        "fecha": "2026-08-15",
        "titulo": "Resumen corto de la entrega",   # opcional
        "cambios": [
            ("nuevo", "Descripción de la funcionalidad añadida."),
            ("corregido", "Descripción del error resuelto."),
            ("mejorado", "Descripción de la optimización."),
        ],
    }

Cada cambio es una tupla (tipo, descripción). Los tipos válidos están en
TIPOS_CAMBIO; si usas uno que no existe, se muestra con estilo neutro.
No hace falta migración ni reinicio de base de datos: basta con editar este
archivo y desplegar.
"""

# Etiqueta y color (clase de Bootstrap) de cada tipo de cambio.
TIPOS_CAMBIO = {
    "nuevo": ("Nuevo", "bg-label-primary"),
    "corregido": ("Corregido", "bg-label-danger"),
    "mejorado": ("Mejorado", "bg-label-success"),
    "seguridad": ("Seguridad", "bg-label-warning"),
    "eliminado": ("Eliminado", "bg-label-secondary"),
}

CHANGELOG = [
    {
        "version": "2.4.1",
        "fecha": "2026-08-11",
        "titulo": "Modo mantenimiento, notificaciones y reportes mejorados",
        "cambios": [
            ("nuevo", "Modo mantenimiento: los usuarios no administradores ven "
                    "una pantalla de mantenimiento cuando está activo."),
            ("nuevo", "Reporte de problemas: los usuarios pueden adjuntar hasta "
                    "4 imágenes y pegar el error de consola del navegador "
                    "(F12) para facilitar la depuración."),
            ("nuevo", "Sistema 100% offline: vendorizados Sortable.js y "
                    "Chart.js, eliminada la dependencia de CDN externos."),
            ("mejorado", "Integración del centro de notificaciones con el módulo "
                        "de subsanación."),
            ("mejorado", "Eliminados paquetes no usados del proyecto "
                        "(google-generativeai, requests)."),
            ("corregido", "Validación de imágenes en reportes con mensajes en "
                        "español."),
        ],
    },
    {
        "version": "2.4.0",
        "fecha": "2026-08-11",
        "titulo": "Rediseño del Dashboard, panel de administración y ajustes móviles",
        "cambios": [
            ("nuevo", "Dashboard: los filtros de Unidad Organizativa y "
                      "Departamento ahora son selectores modernos con chips, "
                      "buscador y contador, en vez del selector múltiple "
                      "clásico, con botón «Restablecer filtros»."),
            ("nuevo", "Dashboard: la Pirámide de Edades permite definir "
                      "libremente los cortes de edad (ej. 25,35,45,55,65) y "
                      "se recalcula al instante sin recargar la página; el "
                      "tooltip muestra cantidad y porcentaje por franja."),
            ("nuevo", "Radar de Jubilaciones: nueva pestaña «Jubilados "
                      "Recontratados» a partir del campo del contrato, junto "
                      "a las ya existentes de edad próxima y cumplida."),
            ("mejorado", "Dashboard: se intercambiaron las tarjetas «Salario "
                         "Escala Promedio» y «Nuevas Bajas» y se unificó la "
                         "paleta de colores de los gráficos de pastel de "
                         "Nivel Educacional y Nivel de Preparación con el "
                         "resto de gráficos."),
            ("mejorado", "Dashboard: el cálculo histórico de Altas/Bajas "
                         "recorre las tablas una sola vez en vez de una vez "
                         "por cada mes mostrado."),
            ("nuevo", "Panel de administración de Django ampliado en todas "
                      "las apps (listados con búsqueda, filtros y "
                      "autocompletado) y nueva vista de Movimientos de "
                      "Nómina agrupada por trabajador; se sumaron los "
                      "módulos de Cierres y Subsanación."),
            ("mejorado", "Ajustes de experiencia en móvil: objetivos táctiles "
                         "más grandes, menú de Gestor de Plantilla con botón "
                         "«Ver opciones», barras de herramientas fijas al "
                         "hacer scroll y un nuevo widget de paginación "
                         "reutilizable en los listados largos."),
        ],
    },
    {
        "version": "2.3.1",
        "fecha": "2026-08-10",
        "titulo": "Filtros del Dashboard y recordatorio de contrato",
        "cambios": [
            ("nuevo", "Filtros por Unidad Organizativa y Departamento en el "
                      "Dashboard principal, respetando siempre el alcance real de "
                      "cada usuario (un Moderador nunca ve datos fuera de sus "
                      "unidades, aunque edite la URL a mano)."),
            ("mejorado", "Ajustes internos del motor del Informe Inteligente."),
            ("mejorado", "El recordatorio de «contrato próximo a vencer» ahora abre "
                         "directamente el formulario de Movimiento de Nómina (antes "
                         "abría Editar contrato), con el aviso de que se está "
                         "corrigiendo desde Recordatorios y el retorno automático a "
                         "esa bandeja al guardar."),
        ],
    },
    {
        "version": "2.3.0",
        "fecha": "2026-08-09",
        "titulo": "Solicitudes, Cierres Mensuales y Auditoría",
        "cambios": [
            ("nuevo", "Módulo Solicitudes reconstruido: flujo de aprobación entre "
                      "Moderadores y Administradores, integrado con Cargos, "
                      "Departamentos, Unidades Organizativas y Contratos, con "
                      "comparación visual entre la situación actual y los cambios "
                      "propuestos antes de aprobar."),
            ("nuevo", "Módulo Cierres: cada Unidad Organizativa declara su "
                      "información al día mes a mes, con estados visuales "
                      "(Pendiente / Actualizada / Desactualizada) y actualización "
                      "automática del estado de la unidad padre según sus unidades "
                      "hijas."),
            ("nuevo", "Módulo Auditoría: registro histórico de quién creó o "
                      "modificó cada cambio importante del sistema y cuándo."),
            ("mejorado", "Permisos y acciones del Gestor de Plantilla."),
            ("mejorado", "Correcciones y ajustes en informes históricos."),
            ("corregido", "No se podía eliminar por completo a un aspirante que "
                          "tenía bajas registradas en su historial."),
        ],
    },
    {
        "version": "2.2.0",
        "fecha": "2026-08-06",
        "titulo": "Centro de Notificaciones: Advertencias y Recordatorios",
        "cambios": [
            ("nuevo", "Subsanación: motor que detecta automáticamente problemas de "
                      "integridad en Aspirantes, Contratos y Nómina (carnet con "
                      "formato inválido, datos de contacto sin completar, fechas de "
                      "vencimiento de licencia/recalificación/seguro de chófer sin "
                      "registrar, motivo o duración del contrato faltante, entre "
                      "otras) y los muestra como Advertencias clasificadas por "
                      "severidad."),
            ("nuevo", "Pestaña Recordatorios: avisos automáticos de cumpleaños, "
                      "contrato próximo a vencer, documentos de chófer por vencer y "
                      "jubilación próxima, con prioridad visual por colores según "
                      "cercanía de la fecha y recordatorios manuales para "
                      "Administración."),
            ("nuevo", "Al corregir un registro desde una Advertencia o un "
                      "Recordatorio, el formulario avisa de dónde viene y, al "
                      "guardar, vuelve automáticamente ahí (Contrato, Aspirante, "
                      "Cargo, Departamento, Unidad Organizativa, Usuario)."),
            ("nuevo", "Botones «Buscar incidencias» y «Actualizar recordatorios» "
                      "para forzar el escaneo bajo demanda, sin esperar a la "
                      "revisión automática."),
            ("nuevo", "Exportación del Anexo 14 a Excel, con formato y bloque de "
                      "firmas."),
            ("mejorado", "Reorganización del menú lateral para dar cabida a las "
                         "nuevas secciones."),
        ],
    },
    {
        "version": "2.1.0",
        "fecha": "2026-07-30",
        "titulo": "Menú de usuario y auditoría del flujo de contratación",
        "cambios": [
            ("nuevo", "Menú de usuario con perfil, preferencias personales, "
                      "información del sistema y novedades de cada versión."),
            ("nuevo", "Foto de perfil configurable para cada usuario."),
            ("nuevo", "Preferencias de interfaz persistentes: estado de la barra "
                      "lateral y activación de las animaciones."),
            ("nuevo", "Formulario para reportar problemas al administrador."),
            ("corregido", "El campo Motivo no se cargaba al abrir el asistente "
                          "Finalizar Contrato, lo que dejaba el botón Confirmar "
                          "Movimiento deshabilitado en los contratos Determinados "
                          "y Adiestrados."),
            ("corregido", "El Modelo de Movimiento de Nómina podía imprimirse con "
                          "los datos de otro trabajador."),
            ("corregido", "Un contrato a medias podía asignarse al trabajador "
                          "equivocado al abrir el asistente desde otra ficha."),
            ("corregido", "Las columnas de teléfono fijo y móvil salían "
                          "intercambiadas en la exportación a Excel."),
            ("mejorado", "Eliminado el parpadeo de los desplegables de búsqueda "
                         "en toda la aplicación."),
            ("mejorado", "El listado de cargos y el histórico del trabajador "
                         "consultan la base de datos muchas menos veces."),
            ("seguridad", "Las pantallas de contratación comprueban el rol del "
                          "usuario: los observadores ya no pueden modificar datos."),
        ],
    },
    {
        "version": "2.0.0",
        "fecha": "2026-06-05",
        "titulo": "Informe Inteligente y Gestor de Plantilla",
        "cambios": [
            ("nuevo", "Informe Inteligente: creación de informes personalizados "
                      "seleccionando campos y filtros."),
            ("nuevo", "Gestor de Plantilla con el Anexo 14."),
            ("nuevo", "Asistente para finalizar la contratación generando el "
                      "movimiento de nómina inicial."),
            ("mejorado", "Histórico completo del trabajador con exportación a PDF."),
        ],
    },
]

# Versión vigente: siempre la primera entrada de la lista.
ORBITH_VERSION = CHANGELOG[0]["version"] if CHANGELOG else "0.0.0"
ORBITH_FECHA_VERSION = CHANGELOG[0]["fecha"] if CHANGELOG else ""

# Datos fijos que muestra el modal "Acerca de Orbith".
ORBITH_INFO = {
    "nombre": "Orbith",
    "descripcion": (
        "Sistema de gestión de Recursos Humanos: plantilla, contratación, "
        "movimientos de nómina, bajas e informes."
    ),
    "desarrollador": [  # ← Cambia esto
        "Juan Manuel Yumar Quiles",
        "Armides Campos Mayo",
    ],
    "tecnologias": [
        ("Python", "bxl-python"),
        ("Django", "bx-server"),
        ("PostgreSQL", "bx-data"),
        ("HTMX", "bx-transfer-alt"),
        ("Bootstrap", "bxl-bootstrap"),
    ],
}


def obtener_changelog():
    """Devuelve el changelog con las etiquetas de cada tipo ya resueltas."""
    versiones = []
    for entrada in CHANGELOG:
        cambios = []
        for tipo, descripcion in entrada.get("cambios", []):
            etiqueta, clase = TIPOS_CAMBIO.get(tipo, (tipo.capitalize(), "bg-label-secondary"))
            cambios.append({"etiqueta": etiqueta, "clase": clase, "descripcion": descripcion})
        versiones.append({
            "version": entrada["version"],
            "fecha": entrada.get("fecha", ""),
            "titulo": entrada.get("titulo", ""),
            "cambios": cambios,
        })
    return versiones
