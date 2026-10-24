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
        "version": "3.4.0",
        "fecha": "2026-10-24",
        "titulo": "El nomenclador manda, cambios externos en el histórico y problemas a la vista",
        "cambios": [
            ("corregido", "El Word del contrato y de su modificación podía salir con el "
                        "salario de otro rol: tras un movimiento de nómina a un cargo con "
                        "otro rol, el contrato conservaba una copia del rol anterior. El "
                        "rol ya es solo del cargo, como define el Gestor de cargos."),
            ("mejorado", "Maestría, Doctorado, CNCI e Instructor se leen siempre del "
                        "nomenclador: cambiar un importe lo cambia desde hoy para todos. "
                        "Los importes tecleados a mano que no coincidían se revisan en "
                        "Subsanación (CTR-023). No se puede borrar una entrada en uso."),
            ("corregido", "El salario, la tarifa horaria y las horas extras se calculan "
                        "igual en todas las pantallas que en el Word y los informes. Antes "
                        "la pantalla de edición ignoraba el salario fijo y el de los "
                        "cuadros, y las horas extras salían distintas en cada pantalla."),
            ("nuevo", "Cambios externos: al cambiar la escala salarial, el rol o el "
                        "departamento de un cargo, un nomenclador de cargo, el nombre de una "
                        "unidad o departamento, un importe o el grado científico de la "
                        "ficha, cada trabajador afectado lo ve en su histórico (y en su "
                        "PDF), con el motivo. No es un movimiento de nómina."),
            ("nuevo", "Motivo del cambio: se pide solo cuando el cambio afecta a "
                        "contratos. «Error humano» corrige un error de tecleo sin dejar "
                        "rastro en el histórico (queda en Auditoría) y anula el cambio "
                        "equivocado anterior."),
            ("nuevo", "Histórico del trabajador: interruptor «Incluir cambios externos» "
                        "para ver solo los movimientos de nómina o también los cambios."),
            ("nuevo", "Triángulos de problemas: rojo (crítico) en cascada en el Gestor de "
                        "plantilla, de contrato a cargo, departamento y unidad; ámbar "
                        "(alto) en el contrato o el cargo. En Contratos, la fila crítica "
                        "se enmarca en rojo. Al pulsar el triángulo se explica qué pasa y "
                        "cómo se soluciona. Nuevo filtro «Con problemas»."),
            ("mejorado", "Las advertencias se mantienen al día solas: al guardar un "
                        "contrato, una ficha o un cargo se revisan sus reglas, el primer "
                        "inicio de sesión del día lanza la revisión completa y, al entrar, "
                        "Administradores y Moderadores ponen al día su campana (cada 4 h)."),
            ("mejorado", "Al cambiar «Ocupa plaza» de un tipo de contrato se recuentan las "
                        "plazas, y un movimiento de unidad actualiza la unidad de la ficha. "
                        "Al pasar un cargo a Cuadro se le quitan el rol y el tridente."),
            ("nuevo", "Subsanación: reglas nuevas para el fondo de tiempo y el porcentaje "
                        "de horas extras (CFG-004), la escala salarial incompleta (CFG-005) "
                        "y el cargo sin rol (EST-008). Rojo = criticidad Crítica en toda la "
                        "aplicación."),
            ("corregido", "El vencimiento de contrato de Subsanación contaba la duración en "
                        "meses: ahora en días, como el Word y el recordatorio, y avisa "
                        "desde el mismo día del vencimiento."),
            ("corregido", "La Pre-Nómina no podía crearse con un instructor de 100 o más "
                        "(tope de 99,99) y guardaba Maestría y Doctorado sin centavos."),
            ("eliminado", "El Tridente I por defecto: un contrato dinámico sin tridente se "
                        "queda sin él y se avisa hasta que RRHH elija el correcto. Y las "
                        "reglas CTR-007 y CTR-019, que ya no pueden darse."),
            ("seguridad", "Las pantallas de Nomencladores y Configuración ya exigen el token "
                        "CSRF: una página ajena no puede cambiar datos en nombre de un "
                        "administrador con la sesión abierta."),
        ],
    },

    {
        "version": "3.3.0",
        "fecha": "2026-10-13",
        "titulo": "Dashboard e Informes RRHH interactivos, y recontratados a la vista",
        "cambios": [
            ("nuevo", "Dashboard interactiva: Empleados Activos, Nuevas Altas, "
                    "Nuevas Bajas, el equilibrio de género, Unidades y "
                    "Departamentos llevan a su lista ya filtrada, conservando "
                    "las unidades elegidas. El Gestor de Plantilla llega con la "
                    "unidad abierta cuando solo hay una."),
            ("nuevo", "Dashboard: ventanas de detalle para el salario promedio "
                    "(por unidad y categoría), para cada mes del gráfico de "
                    "Altas y Bajas (altas en azul y bajas en rojo, por fecha) y "
                    "para cada barra de la Pirámide de Edades."),
            ("nuevo", "Ventana de Plazas desde «Vacantes Libres» y «Ocupación de "
                    "Plazas»: cargos con vacantes, llenos, inactivos o todos, "
                    "quién ocupa cada uno y botón «Contratar aquí» con el cargo "
                    "ya elegido."),
            ("nuevo", "Años de Servicio: filtro «De __ a __ años» y botón «Ver "
                    "más» con unidad, cargo, fecha de alta en la entidad e "
                    "importe por escala. Cumpleaños: pestaña «Buscar» entre dos "
                    "fechas. Recordatorios: filtro por prioridad. Radar de "
                    "Jubilaciones: con el expediente y el histórico a un doble "
                    "clic."),
            ("nuevo", "Informes RRHH interactivos: en el Consolidado, "
                    "Trabajadores por UEB, Puestos Clave, Registro Diario y Altas "
                    "y Bajas, pulsar una cifra muestra quiénes son (o qué cargos, "
                    "en las de plazas), también sobre un cierre mensual."),
            ("nuevo", "Contratos: filtros «Alta desde/hasta», «Recontratados», "
                    "«Baja anterior desde/hasta» y «Jubilados recontratados». "
                    "Con esos filtros, una línea verde señala a los "
                    "recontratados."),
            ("nuevo", "Bajas: filtros de unidad y «Baja desde/hasta». Avisos "
                    "cruzados entre las dos listas: en Contratos, quién entró en "
                    "el período y ya causó baja; en Bajas, quién causó baja y "
                    "fue recontratado, con enlace a sus contratos."),
            ("nuevo", "Subsanación: cuatro reglas nuevas para fechas imposibles: "
                    "bajas posteriores al contrato vigente (MOV-009), bajas con "
                    "fecha futura (MOV-010), movimientos con año anterior a 1900 "
                    "(MOV-011) y contratos con fecha de alta anterior a 1900 "
                    "(CTR-022)."),
            ("mejorado", "Las cifras de altas y bajas cuentan personas: quien se "
                        "fue y volvió varias veces en el mismo período cuenta una "
                        "vez, con la nota «2 bajas en el período». La tarjeta, la "
                        "lista y su aviso siempre coinciden."),
            ("mejorado", "Al causar baja se borran los avisos de su contrato y las "
                        "alertas de datos de su ficha, que ya nadie podía "
                        "resolver; el aviso «Baja de contrato» se conserva."),
            ("mejorado", "El resumen de cierre del Ranking que reciben los "
                        "Administradores muestra el nombre de usuario de quien no "
                        "tiene nombre en su ficha."),
            ("corregido", "Abrir una advertencia de un contrato que ya había "
                        "causado baja daba un error de página no encontrada. "
                        "Ahora se explica qué pasó y se ofrece volver."),
            ("corregido", "El asistente de contratación mostraba un error técnico "
                        "en vez del mensaje del formulario (por ejemplo, «el "
                        "cargo no tiene plazas disponibles»), y aceptaba años "
                        "imposibles como 0026 en la fecha efectiva."),
            ("corregido", "En Aspirantes y Bajas, cambiar un filtro del panel no "
                        "recargaba la tabla, y en Bajas esos filtros no "
                        "filtraban nada."),
            ("corregido", "En el Consolidado de Fuerza de Trabajo, el botón Word "
                        "no hacía nada y el PDF solo tenía en cuenta la primera "
                        "unidad elegida e ignoraba el cierre."),
        ],
    },

    {
        "version": "3.2.0",
        "fecha": "2026-10-12",
        "titulo": "Anexo 14-B, Ranking Mensual, auditoría completa y tablas a pantalla justa",
        "cambios": [
            ("nuevo", "Anexo 14-B «Formación y Desarrollo», con pantalla propia y "
                    "Excel: una hoja por departamento más las de Adiestrados, "
                    "Contratados y Fuera de plantilla. Una fila por plaza "
                    "aprobada, también las vacantes, con el importe mensual y "
                    "la tarifa horaria, el nivel de preparación, los años de "
                    "servicio y la CLA y nocturnidad del último reporte de "
                    "Pre-Nómina cerrado."),
            ("nuevo", "Anexos 14 y 14-A: una pestaña por unidad que se carga al "
                    "abrirla, selector de varias unidades a la vez y Excel con "
                    "portada y resumen. Nuevo botón para bajar el 14 y el 14-A "
                    "en un solo libro. Si hay filtros puestos, Orbith pregunta "
                    "si exportar la plantilla completa o solo lo filtrado."),
            ("nuevo", "Días e Importe de la misión en el contrato. Se pueden "
                    "completar también desde el informe Misiones "
                    "Internacionales, con confirmación antes de guardar, "
                    "aviso si otro usuario cambió el dato a la vez y registro "
                    "en Auditoría. La regla CTR-021 de Subsanación avisa de las "
                    "misiones sin días o sin importe."),
            ("nuevo", "Subsanación: regla CTR-020 para los contratos fijos en "
                    "cargos fuera de plantilla, y pestaña «Índice de Reglas» "
                    "que explica qué comprueba cada código y cómo se corrige."),
            ("nuevo", "Subsanación: regla MOV-008 para los movimientos de nómina "
                    "que conservan un número de expediente distinto al de su "
                    "contrato. En MOV-008 y MOV-002 un Administrador puede "
                    "corregir el caso con un botón, con confirmación y registro "
                    "en Auditoría. Además, al corregir el expediente de un "
                    "contrato, sus movimientos toman el número nuevo."),
            ("nuevo", "Búsqueda con prefijos en Aspirantes, Bajas, Contratos y "
                    "Subsanación: E: expediente, N: nombre, CI: carnet, CA: "
                    "cargo, U: unidad y COD: código de regla. Se pueden "
                    "combinar y los acentos no importan."),
            ("nuevo", "El formulario de contrato muestra los años de servicio y "
                    "su importe, calculados al momento desde la F. Alta "
                    "Entidad y la escala vigente."),
            ("nuevo", "Auditoría completa: todo lo que se crea, edita o elimina "
                    "desde los formularios (contratos, aspirantes, estructura y "
                    "nomencladores) queda registrado con el antes y el después. "
                    "Antes solo se auditaban las Solicitudes y el panel de "
                    "administración. Filtro por módulo, y las acciones Alta, "
                    "Movimiento y Baja tienen color e icono propios."),
            ("nuevo", "Parámetros Generales: opción para borrar la auditoría "
                    "más antigua que los años que se elijan. Viene apagada."),
            ("nuevo", "Guía de Orbith: categoría «Exportar» con ocho tareas que "
                    "muestran el avance por formato, tarea «Busca con "
                    "prefijos» y tareas según el rol. Todas las tareas tienen "
                    "ya su guía visual paso a paso («¿Cómo funciona?»)."),
            ("nuevo", "Ranking Mensual Orbith, en el menú de la foto: el trabajo "
                    "de cada día suma XP, con niveles y una clasificación por "
                    "rol. El día 1 se cierra el mes y llega el resultado a la "
                    "campana. Los tres primeros de cada rol lucen el mes "
                    "siguiente una distinción oro, plata o bronce, que se "
                    "puede ocultar en Configuración."),
            ("nuevo", "Estadísticas de uso, solo para Administradores: ranking "
                    "del mes, uso de Orbith por usuario y módulo, usuarios sin "
                    "actividad y unidades sin cierre en plazo, con botón para "
                    "enviarles un recordatorio."),
            ("nuevo", "Todas las tablas comparten estilo: caben justas en la "
                    "pantalla, con la cabecera fija y la paginación siempre a "
                    "la vista. Páginas numeradas y «Filas por página» 10, 25, "
                    "50 o 100, que se recuerda por usuario y se puede elegir "
                    "en Configuración. Los Informes RRHH y los Anexos fijan "
                    "también su cabecera al desplazar."),
            ("mejorado", "Títulos de página más pequeños y más arriba, y sin la "
                        "barra superior vacía en el escritorio: más espacio "
                        "para el contenido en todas las pantallas."),
            ("mejorado", "Un solo formulario de Baja para la Lista de Contratos "
                        "y el Gestor de Plantilla. El del Gestor no pedía "
                        "Observaciones ni ofrecía el PDF al terminar."),
            ("mejorado", "Cierres Mensuales adopta los colores de los Informes "
                        "RRHH."),
            ("corregido", "El Anexo 14 dejaba fuera las unidades que no son "
                        "Principales, como las UEB de Florida, Nuevitas y "
                        "Despacho."),
            ("corregido", "Al exportar el Contrato de Trabajo o su Modificación, "
                        "la «Fecha Efectiva de Firma» salía con la fecha de alta. "
                        "Ahora propone la del último movimiento de nómina del "
                        "contrato, y se puede cambiar antes de exportar."),
            ("corregido", "La fecha mínima para dar de baja o hacer un movimiento "
                        "de nómina podía salir más temprana de la cuenta si el "
                        "expediente del contrato se había corregido. Las listas "
                        "de Contratos y del Gestor de Plantilla, además, la "
                        "calculan ahora sin una consulta por cada fila."),
            ("corregido", "Los filtros de Auditoría, Advertencias y Solicitudes "
                        "se cerraban al marcar la primera opción."),
            ("corregido", "Auditoría, Subsanación e Informe Inteligente dejaban "
                        "una franja en blanco encima del título."),
            ("seguridad", "Los avisos de la campana muestran su texto tal cual: "
                        "un título o mensaje con código ya no puede ejecutarse "
                        "en el navegador de quien lo abre."),
            ("eliminado", "La exportación a PDF del Anexo 14, que no se usaba."),
        ],
    },

    {
        "version": "3.1.0",
        "fecha": "2026-09-15",
        "titulo": "Cargos fuera de la plantilla aprobada, y una aplicación más ligera",
        "cambios": [
            ("nuevo", "Interruptor «En Plantilla» en el alta y la edición de "
                    "cargos. Un cargo fuera de la plantilla aprobada existe y "
                    "puede tener trabajadores, pero no suma en ninguna cifra de "
                    "plazas aprobadas ni admite contratos que ocupen plaza. Los "
                    "cargos que cuelgan de una Unidad Organizativa temporal "
                    "nacen ya marcados como fuera de plantilla."),
            ("nuevo", "Un mismo cargo puede repetirse en el departamento si uno "
                    "está dentro de la plantilla aprobada y el otro fuera. El "
                    "desplegable de cargos se ajusta solo al mover el "
                    "interruptor, y no deja crear dos iguales del mismo lado."),
            ("nuevo", "Al elegir un cargo fuera de plantilla en el formulario de "
                    "contrato, los tipos de contrato que ocupan plaza se "
                    "desactivan solos. Y no se puede sacar de la plantilla un "
                    "cargo que ya tenga un contrato indeterminado asociado."),
            ("nuevo", "En el Gestor de Plantilla, los cargos fuera de la "
                    "plantilla aprobada se distinguen en ámbar, y la tarjeta de "
                    "Cargos estrena un filtro Todos / En plantilla / Fuera de "
                    "plantilla."),
            ("nuevo", "El Informe Inteligente incorpora el campo «En Plantilla», "
                    "que se puede mostrar y filtrar, también sobre un período "
                    "cerrado. Las tarjetas del resumen y el desglose por unidad "
                    "ignoran siempre los cargos fuera de plantilla."),
            ("nuevo", "El Anexo 14 lista los cargos fuera de la plantilla "
                    "aprobada en una sección aparte, con su propio subtotal y "
                    "sin sumar al total oficial, tanto en pantalla como en PDF "
                    "y Excel."),
            ("corregido", "Cualquier error de validación al editar un Cargo, un "
                        "Departamento o una Unidad Organizativa devolvía un "
                        "error 500 en lugar del formulario con sus mensajes. "
                        "Afectaba a seis pantallas."),
            ("corregido", "El botón «Confirmar y Guardar» de Parámetros "
                        "Generales quedaba desactivado para siempre, sin que "
                        "nada explicara por qué."),
            ("corregido", "Editar un contrato o los datos personales de un "
                        "trabajador desde el Gestor de Plantilla devolvía al "
                        "usuario a la lista de contratos y perdía la unidad, el "
                        "departamento y el cargo que tenía seleccionados."),
            ("corregido", "Un cargo podía quedar marcado como Funcionario y "
                        "Designado a la vez si se creaba sin pasar por el "
                        "formulario."),
            ("mejorado", "Las páginas viajan comprimidas: el Gestor de Plantilla "
                        "pasa de 270 KB a 55 KB y el Dashboard de 229 KB a "
                        "45 KB. Un 80% menos de datos en cada pantalla que se "
                        "abre, que se nota sobre todo con conexiones lentas."),
            ("mejorado", "La aplicación reutiliza la conexión con la base de "
                        "datos en lugar de abrir una nueva en cada petición. "
                        "Menos consumo de memoria en el servidor."),
            ("mejorado", "El listado de Solicitudes resuelve los contadores de "
                        "las tres pestañas en una sola consulta en vez de tres."),
            ("mejorado", "La imagen de la pantalla de acceso pasa de 917 KB a "
                        "62 KB."),
            ("seguridad", "Los respaldos de la base de datos dejan de guardarse "
                        "en el repositorio de código: contenían datos personales "
                        "de los trabajadores."),
        ],
    },

    {
        "version": "3.0.2",
        "fecha": "2026-09-04",
        "titulo": "Los seis Informes de RRHH exportan a Word y PDF, con una imagen común",
        "cambios": [
            ("nuevo", "Botón «Ejecutar todos los análisis» en la lista de "
                    "Usuarios, solo para Administradores: busca incidencias, "
                    "actualiza los recordatorios y analiza la integridad de la "
                    "base de datos, los tres seguidos y mostrando el progreso. "
                    "Antes había que pulsar tres botones repartidos en dos "
                    "pantallas."),
            ("corregido", "La búsqueda de incidencias creaba los avisos solo "
                        "para quien pulsaba el botón. El nuevo «Ejecutar todos "
                        "los análisis» los reparte a los destinatarios de cada "
                        "Unidad Organizativa, y los que no tienen unidad van a "
                        "los Administradores."),
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
