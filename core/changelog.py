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
        "version": "3.0.2",
        "fecha": "2026-09-03",
        "titulo": "Los seis Informes de RRHH exportan a Word y PDF, con una imagen común",
        "cambios": [
            ("nuevo", "Los SEIS Informes de RRHH se exportan ya a Word y a PDF. "
                    "Antes solo tres tenían Word y dos, PDF: estrenan salida "
                    "Trabajadores por UEB, Misiones Internacionales, Contratos "
                    "Determinados y Registro Diario por Trabajadores."),
            ("nuevo", "Todos los documentos llevan el mismo encabezado en cada "
                    "página: logo, empresa, provincia, la unidad del informe, "
                    "quién lo exportó, el período y «Hoja X de Y», con la fecha "
                    "de exportación al pie."),
            ("nuevo", "Contratos Determinados: conmutador «Desglosado / "
                    "Consolidado». Desglosado agrupa por tipo de contrato, "
                    "motivo y unidad; consolidado quita el nivel de la unidad y "
                    "la pasa a columna. La pantalla, el Word y el PDF salen "
                    "como se elija, y la elección se recuerda."),
            ("nuevo", "Un color fijo para cada Categoría Ocupacional en toda la "
                    "aplicación: Obreros, Técnicos, Administrativos, Servicios y "
                    "Cuadros tienen su color en los gráficos del Dashboard y de "
                    "los informes, en los desgloses y en las insignias de los "
                    "listados."),
            ("nuevo", "Registro Diario: el Plan Mensual se edita con doble clic "
                    "sobre la cifra, y solo se guarda con el botón «Guardar "
                    "plan». Pulsando Escape se descarta el cambio."),
            ("nuevo", "Trabajadores por UEB estrena cifras de cabecera —total, "
                    "mujeres, unidades con personal y la de mayor plantilla— y "
                    "una columna de «% del total», para comparar unidades y no "
                    "solo enumerarlas."),
            ("mejorado", "El filtro por Unidad Organizativa vive ahora en la "
                        "barra del título, el mismo sitio en los seis informes. "
                        "Antes cada pantalla lo colocaba donde le parecía."),
            ("mejorado", "Los seis informes comparten paleta: mismos colores "
                        "para las cifras de cabecera, las cabeceras de tabla y "
                        "las filas de totales. El naranja significa siempre «lo "
                        "que falta» y el rojo «lo crítico»."),
            ("mejorado", "El nombre del fichero descargado dice de qué es: "
                        "«Puestos_Clave_Nuevitas_Septiembre_2026.docx» en vez de "
                        "«Puestos_Clave_9_2026.docx»."),
            ("mejorado", "El botón de PDF de los informes se ve como un botón: "
                        "era el único de la aplicación con el fondo transparente "
                        "y solo se coloreaba al pasar el ratón por encima."),
            ("mejorado", "Las plantillas de Word de todos los informes viven "
                        "juntas en la misma carpeta, incluida la del Modelo de "
                        "Movimiento de Nómina."),
            ("corregido", "Contratos Determinados coloreaba las categorías por "
                        "orden de tamaño, así que la misma categoría cambiaba de "
                        "color según los datos: Obreros salía de un color un mes "
                        "y de otro al siguiente."),
            ("corregido", "El PDF de Puestos Clave no repetía la cabecera de "
                        "columnas al pasar de página."),
            ("corregido", "Registro Diario: el campo del Plan se veía más alto "
                        "que las otras tres cifras de su tarjeta, y el "
                        "cumplimiento se partía en dos líneas."),
        ],
    },
    {
        "version": "3.0.1",
        "fecha": "2026-09-02",
        "titulo": "Informes por unidad, filtros unificados y validación de formularios",
        "cambios": [
            ("nuevo", "Puestos Clave: el informe se puede ver repartido por "
                    "Unidad Organizativa —cada unidad con sus totales y sus "
                    "cargos debajo, y las direcciones principales encabezando "
                    "su rama— o consolidado, sumando cada cargo de todas las "
                    "unidades. Se elige con el conmutador «Desglosado / "
                    "Consolidado» de la barra de filtros, que recuerda su "
                    "última posición."),
            ("nuevo", "Puestos Clave en Word y PDF: encabezado con el logo, la "
                    "provincia, el municipio y la unidad del informe, quién lo "
                    "exportó, el período y «Hoja X de Y» en todas las páginas. "
                    "El nombre del fichero lleva la unidad y el mes."),
            ("nuevo", "Filtro por Unidad Organizativa en TODOS los informes de "
                    "RRHH, con selección múltiple. Elegir una unidad principal "
                    "incluye sus subunidades, y cada subunidad se puede "
                    "consultar por separado."),
            ("nuevo", "Lista de Contratos: filtros por Unidad Organizativa, "
                    "Departamento y Cargo, todos de selección múltiple."),
            ("nuevo", "Nomencladores de importes: Maestría, Doctorado, "
                    "Instructor y CNCI. El contrato toma de ahí sus importes en "
                    "vez de escribirlos a mano, y una regla de Subsanación "
                    "avisa de los contratos cuyo importe ya no coincide."),
            ("nuevo", "Informe Inteligente: dieciséis medidas para Contratos "
                    "—cuadros, mujeres en puestos clave, grado científico, "
                    "nivel superior, título de oro, profesionales, jubilados "
                    "recontratados, contratos determinados, antigüedad y "
                    "misiones— y ocho para Estructura y Plantilla, con la "
                    "cobertura de la plantilla y las plazas vacantes. Todas se "
                    "pueden dibujar en la Evolución mensual."),
            ("nuevo", "Informe Inteligente: campos nuevos de Puesto Clave y "
                    "Contrato Determinado en Contratos, y Puesto Clave y Plazas "
                    "Vacantes en Estructura y Plantilla."),
            ("nuevo", "Selector de período unificado en Informes RRHH e Informe "
                    "Inteligente: una rejilla de meses que marca en gris los "
                    "que no tienen cierre declarado."),
            ("nuevo", "Usuarios: columna de Rol en el listado y botón "
                    "«Actualizar conexiones» para ver al momento quién está "
                    "dentro."),
            ("nuevo", "Usuarios: al asignar una Unidad Principal a un moderador "
                    "entran también sus subunidades, y las unidades que ya "
                    "lleva otro moderador aparecen apagadas en el desplegable. "
                    "Una subunidad nueva se reparte sola, sin tener que reabrir "
                    "la ficha del moderador."),
            ("nuevo", "Subsanación: siete reglas nuevas —cargo sin nivel de "
                    "preparación, unidad que no declaró su cierre mensual, "
                    "moderador sin todas las subunidades de su principal, "
                    "subunidad sin su principal, contrato determinado vencido "
                    "con el trabajador activo, fecha de alta en la entidad "
                    "imposible, importe distinto al del nomenclador y fórmula "
                    "de Pago por Importe que ya no es válida."),
            ("mejorado", "Un solo criterio de color en todos los formularios: "
                        "amarillo el campo obligatorio que falta, rojo el dato "
                        "escrito que no es válido y verde el correcto. El botón "
                        "de guardar espera a que no quede nada pendiente. Los "
                        "campos opcionales ya no se pintan de amarillo."),
            ("mejorado", "Todos los desplegables de la aplicación se ven y se "
                        "manejan igual, con buscador para escribir en vez de "
                        "recorrer la lista."),
            ("mejorado", "El selector de unidades del Dashboard, de Informes "
                        "RRHH y de Informe Inteligente es el mismo control, con "
                        "las subunidades indentadas bajo su principal y "
                        "búsqueda por rama."),
            ("mejorado", "Informes RRHH: el desplegable de tipo de informe "
                        "conserva la fuente de datos —si está mirando un cierre "
                        "de agosto, sigue en agosto al cambiar de informe."),
            ("mejorado", "El Observador deja de tener acceso al panel de "
                        "Notificaciones; conserva sus avisos personales en la "
                        "campana."),
            ("corregido", "La exportación a Word del Resumen de Puestos Clave y "
                        "del Resumen por UEB no generaba el documento."),
            ("corregido", "Puestos Clave: exportar a Word o PDF con el filtro de "
                        "unidades puesto devolvía un error."),
            ("corregido", "Lista de Contratos: al cambiar de página se perdían "
                        "los filtros aplicados."),
            ("corregido", "El panel de filtros de la Lista de Contratos se "
                        "cerraba al elegir en un desplegable."),
            ("corregido", "Informe Inteligente: el selector de Unidad "
                        "Organizativa no respondía, y la pantalla saltaba al "
                        "final al recuperar un informe guardado."),
            ("corregido", "Parámetros Generales: el REUP no se validaba en el "
                        "navegador."),
            ("corregido", "Formulario de Baja: «Causa de Baja» es obligatorio y "
                        "no se marcaba como tal."),
            ("corregido", "Cierres mensuales: la fotografía guardaba los "
                        "importes sin decimales."),
            ("corregido", "Aspirantes: el sexo deducido del carné de identidad "
                        "no se daba por válido, y los desplegables encadenados "
                        "del contrato se quedaban en verde después de "
                        "vaciarse."),
            ("corregido", "Corregida la errata «Maetría» en el formulario de "
                        "contrato."),
            ("eliminado", "Retirada la pantalla de Cargos a página completa de "
                        "Nomencladores: estaba rota y duplicaba Configuración → "
                        "Familias de Cargos."),
        ],
    },
    {
        "version": "3.0.0",
        "fecha": "2026-08-31",
        "titulo": "Pre-Nómina, seguridad del acceso y saneamiento de estáticos",
        "cambios": [
            ("nuevo", "Pre-Nómina: módulo completo de Reportes de Pago, con "
                    "conceptos por horas, conceptos por importe y claves de "
                    "ausencia, más importación y exportación de datos."),
            ("nuevo", "Pre-Nómina → Calendario: definición de jornadas, "
                    "calendarios de pago y asignación de calendario a cada "
                    "trabajador."),
            ("nuevo", "Pre-Nómina → Mis Plantillas: plantillas de reporte "
                    "reutilizables por usuario."),
            ("nuevo", "Nomencladores propios de Pre-Nómina: Pago Asociado por "
                    "Horas, Pago Asociado por Importe, Escala de Años de "
                    "Servicio y Claves de Ausencia."),
            ("nuevo", "Pantalla de acceso y cambio de contraseña: botón para "
                    "mostrar u ocultar la contraseña mientras se escribe. Solo "
                    "muestra lo que usted teclea: nunca una contraseña "
                    "rellenada por el navegador, para que nadie pueda leer en "
                    "un equipo compartido una clave guardada que no conoce."),
            ("nuevo", "Pantalla de acceso: el enlace «¿Problemas para acceder?» "
                    "abre un formulario que envía la incidencia a la bandeja "
                    "del Administrador sin necesidad de iniciar sesión."),
            ("seguridad", "Bloqueo por intentos fallidos: 10 fallos en 5 minutos "
                        "bloquean la cuenta. Protege también el panel de "
                        "administración de Django, y el Administrador puede "
                        "desbloquear una cuenta al instante."),
            ("seguridad", "Auditoría de accesos: los inicios de sesión, los "
                        "intentos fallidos y los cierres de sesión quedan "
                        "registrados. Nunca se guarda la contraseña."),
            ("seguridad", "Caducidad de sesión: se cierra a los 60 minutos de "
                        "inactividad, con un techo de 12 horas, y la sesión "
                        "termina al cerrar el navegador. Antes duraba dos "
                        "semanas."),
            ("seguridad", "Retiradas las páginas de cambio y reseteo de "
                        "contraseña que Django publica de serie: estaban "
                        "accesibles sin iniciar sesión y sin plantilla, así que "
                        "devolvían un error 500."),
            ("seguridad", "El sistema arranca en modo seguro si falta el fichero "
                        "de configuración del entorno, en lugar de mostrar "
                        "trazas con detalles internos."),
            ("seguridad", "La cookie de sesión pasa a ser inaccesible desde "
                        "JavaScript y no viaja en peticiones de otros sitios."),
            ("seguridad", "Las contraseñas siguen ahora un único criterio en los "
                        "tres sitios donde se fijan: alta de usuario, cambio "
                        "desde «Mi Perfil» y panel de administración. Antes el "
                        "cambio aceptaba contraseñas que el alta rechazaba, "
                        "entre ellas algunas de las más usadas del mundo. Se "
                        "mantienen las exigencias de longitud, mayúscula y "
                        "número, y se añaden el rechazo de contraseñas comunes "
                        "y de las parecidas al nombre de usuario."),
            ("corregido", "Los avisos de contraseña al dar de alta un usuario "
                        "salían en inglés. Ahora están en español, como el "
                        "resto del sistema."),
            ("corregido", "Estáticos: la carpeta generada por «collectstatic» "
                        "estaba versionada y desactualizada, de modo que en "
                        "producción faltaban recursos que carga toda la "
                        "aplicación. Ahora se genera en cada despliegue."),
            ("corregido", "Pantalla de acceso: el usuario ya no se borra al "
                        "fallar el intento, los avisos de éxito dejan de "
                        "mostrarse en rojo como si fueran errores y el teclado "
                        "del móvil ya no fuerza la mayúscula inicial."),
            ("corregido", "Quien ya tiene la sesión abierta y vuelve a la "
                        "pantalla de acceso va directo al inicio, en lugar de "
                        "ver otra vez el formulario."),
            ("mejorado", "Los gestores de contraseñas del navegador ya "
                        "reconocen los campos de la pantalla de acceso."),
            ("eliminado", "Nomencladores «Horario» y «Jornada»: sus tablas "
                        "estaban vacías, ninguna pantalla los usaba y ningún "
                        "contrato tenía jornada asignada. El tiempo de trabajo "
                        "se gestiona ahora desde Pre-Nómina → Calendario."),
        ],
    },

    {
        "version": "2.5.0",
        "fecha": "2026-08-18",
        "titulo": "Guía de progreso, permisos granulares y auditoría en admin",
        "cambios": [
            ("nuevo", "Guía de Progreso: sistema de tareas guiadas para nuevos "
                    "usuarios, con seguimiento de pasos completados, "
                    "instrucciones contextuales y barra de progreso."),
            ("nuevo", "Permisos granulares en contratos y subsanación para un "
                    "control más fino de accesos."),
            ("nuevo", "Mixins de auditoría en el panel de administración para "
                    "registrar automáticamente quién crea o modifica registros."),
            ("nuevo", "Campo 'fecha_alta_entidad' en contratos para registrar "
                    "la fecha real de alta en la entidad."),
            ("mejorado", "Reestructuración de templates del Dashboard para "
                        "facilitar su mantenimiento."),
            ("mejorado", "Recodificación y deduplicación de eventos de "
                        "notificaciones para evitar duplicados y mejorar "
                        "el rendimiento."),
            ("mejorado", "Actualización masiva de vistas, formularios y "
                        "plantillas en contratos, subsanación y solicitudes."),
            ("corregido", "Corrección en la gestión de cumpleaños y jubilaciones "
                        "en el sistema de notificaciones."),
        ],
    },

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
