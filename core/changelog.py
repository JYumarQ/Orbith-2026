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

Se conservan las 10 ÚLTIMAS versiones (decisión del 24-10-2026; antes eran 5):
al añadir la undécima, se borra la más antigua del final de la lista.
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
        "version": "3.7.0",
        "fecha": "2026-10-25",
        "titulo": "Firmantes en el perfil, Excel en la administración y resoluciones en el Alta Inicial",
        "cambios": [
            ("nuevo", "Firmantes de los Anexos 17 en Configuración: cada Administrador y Moderador elige qué plaza de cuadro firma «Propuesto por» y «Aprobado por» y el título que se imprime. Firma quien ocupe la plaza ese día, con el título en femenino si es una mujer."),
            ("nuevo", "Administración de Django: importar y exportar en Excel el nomenclador de cargos y la estructura (unidades y departamentos). Se puede simular antes, es todo o nada y nunca borra; lo exportado se vuelve a importar sin cambios."),
            ("nuevo", "El grupo de nómina ya no se repite entre unidades: solo lo comparten una unidad principal y sus subunidades. Lo comprueban el formulario y el importador, y Subsanación avisa de los repetidos (regla EST-009)."),
            ("mejorado", "El movimiento de nómina del Alta Inicial tiene ahora los mismos campos que el movimiento normal: «Otros» y los números de resolución, que llegan rellenos con lo escrito en el contrato y se pueden completar o corregir. Lo que quede en esa ventana es lo que se guarda."),
            ("mejorado", "Registrar y Editar contrato: «Otros» va en la misma fila que Salario Escala, Tarifa Horaria, Tarifa Horas Extras y Pago Años de Servicio."),
            ("mejorado", "Pre-nómina: «Relacionado con» vale también para importes fijos y escalas; esos importes solo los cobra quien tenga horas en el concepto relacionado."),
            ("corregido", "Los números de resolución escritos al contratar se perdían al confirmar el Alta Inicial."),
            ("corregido", "El número de resolución de la C. Formal se exigía para continuar con el contrato; los cuatro números son opcionales y Subsanación recuerda los que falten."),
        ],
    },
    {
        "version": "3.6.0",
        "fecha": "2026-10-24",
        "titulo": "Editor del histórico, ventanas de la Dashboard con Excel y filtros más sencillos",
        "cambios": [
            ("nuevo", "Editor del histórico (solo Administrador): corrige todo el histórico de una persona —fechas, cargo, tipo, motivo, salario, Otros, bajas—, inserta movimientos que faltaron y borra los sobrantes. Se edita en borrador, se revisa y se guarda todo junto con un motivo obligatorio. Se abre con «Editar histórico» en la ventana del histórico."),
            ("nuevo", "Al corregir el histórico se corrigen también los meses ya cerrados en los que estaba vigente: sus fotografías, plazas y totales. Cada cierre queda marcado «Corregido el … por …: motivo» y se avisa al moderador de la unidad."),
            ("nuevo", "Solicitudes personalizadas: el Moderador explica al Administrador un problema que no tiene solicitud propia (pestaña «Personalizadas»); el Administrador responde y la cierra."),
            ("nuevo", "Dashboard: toda tarjeta y gráfico abre primero una ventana con las personas o las cifras de detrás, con buscador, «Ver más» hacia la lista con los mismos filtros y exportación a Excel con portada."),
            ("nuevo", "Dashboard: «Top causas de baja», «Unidades organizativas» y «Departamentos» ahora se pueden pulsar; los gráficos de distribución responden también al pulsar la porción, no solo la leyenda."),
            ("nuevo", "Subsanación: regla MOV-015 «Histórico que no encaja» (tipo de contrato, cargo, unidad, departamento, motivo o tridente). Su botón lleva al editor del histórico y el aviso se cierra solo al corregirlo."),
            ("nuevo", "Subsanación: el Moderador tiene su Dashboard con los problemas pendientes de sus unidades, por gravedad, por categoría y por unidad. Cada cifra abre Hallazgos ya filtrado."),
            ("nuevo", "Lista de Bajas: filtro por causa de la baja."),
            ("nuevo", "Página de diagnóstico del servidor en el admin de Django (Soporte) para revisar dónde se guardan los ficheros subidos."),
            ("mejorado", "Contratos y Bajas: filtros básicos a la vista y el resto en «Filtros avanzados»; encima de la tabla se ven los filtros en uso y cada uno se quita con su ✕."),
            ("mejorado", "Movimiento de nómina rediseñado: situación actual al 40 % y propuesta al 60 %, por bloques, resoluciones siempre visibles y aviso de si el salario sube, baja o no varía."),
            ("mejorado", "Editar contrato: unidad, departamento, cargo, tipo, motivo, tipo de salario, tridente y F. de contratación solo se cambian con un movimiento de nómina; el aviso ofrece hacerlo o enviar una solicitud personalizada."),
            ("mejorado", "Informe Inteligente: una columna por cada tipo de contrato del nomenclador en lugar de «Determinados» e «Indeterminados»."),
            ("mejorado", "El expediente es uno por persona: al corregirlo en el contrato cambia en todo su histórico, bajas y cierres."),
            ("seguridad", "El salario del movimiento y del alta lo calcula el servidor con la escala, no se toma el que manda el navegador."),
            ("seguridad", "Dos usuarios que guardan a la vez un movimiento, una baja o un alta de la misma persona ya no pueden dejar el histórico desordenado: el segundo espera y vuelve a comprobar."),
            ("corregido", "Subsanación: pulsar una cifra del Dashboard abría Hallazgos sin el filtro de esa cifra."),
            ("corregido", "El asistente de contratación guardaba el Alta Inicial sin tipo de contrato, motivo ni duración."),
            ("corregido", "Se podía terminar un contrato sin tipo de contrato: ahora es obligatorio."),
            ("corregido", "Contratos: al llegar con municipio o especialidad en la dirección, el filtro se perdía al buscar o cambiar de página."),
            ("corregido", "El logo de los Excel ya no se monta sobre el nombre de la empresa, y el triángulo de problemas «alto» se ve en amarillo."),
            ("eliminado", "El informe antiguo del Anexo 17 que ya no se usaba."),
        ],
    },
    {
        "version": "3.5.0",
        "fecha": "2026-10-24",
        "titulo": "Anexos 17, De Confianza, modalidad de trabajo, «Otros» y nombres de fichero claros",
        "cambios": [
            ("nuevo", "Los Anexos 17, 17.1 y 17.2 se llaman ahora Anexo 17, 17.1 y 17.2 en toda la aplicación: menú, pantallas, Excel y Guía."),
            ("nuevo", "El Excel del Anexo 17.2 sigue el modelo nuevo: cabeceras en vertical, columnas ajustadas y letra 12."),
            ("nuevo", "Switch «De Confianza» en el cargo (Gestor de Plantilla), con su No. de resolución en el contrato. Puede coincidir con Funcionario o Designado."),
            ("nuevo", "Contrato: «Modalidad de trabajo» con Trab. a distancia, Teletrabajo y Pluriempleo. El Moderador los cambia sin solicitud."),
            ("nuevo", "Campo «Otros» (grado científico + Instructor + CNCI + años de servicio) en el contrato y en el movimiento de nómina. El movimiento lo guarda, así su documento no cambia con el tiempo."),
            ("nuevo", "Movimiento de nómina: números de resolución (C. Formal, Funcionario, Designado y De Confianza), opcionales. Si se escriben, sustituyen a los del contrato."),
            ("nuevo", "Informe Inteligente: Dirección en «Datos del Trabajador»; De Confianza, su resolución y la modalidad de trabajo; y cuántos contratos tiene cada cargo en «Estructura y Plantilla Aprobada»."),
            ("nuevo", "Registro de errores del servidor, que el Administrador consulta y descarga desde el admin de Django (Soporte → Registro de errores)."),
            ("mejorado", "Los ficheros descargados se reconocen por su nombre: MOV_, ALTA_, BAJA_, CON_ o MOD_CON_ + nombre + expediente; los informes llevan su nombre, la unidad o el período y la fecha."),
            ("mejorado", "La sábana de Excel de Contratos exporta lo que se ve en la lista (filtros, búsqueda y orden), sin ventana intermedia y con columnas nuevas."),
            ("mejorado", "«Buscar incidencias» y la búsqueda automática van por partes: ya no se cortan por exceder el tiempo en el servidor."),
            ("mejorado", "Búsqueda automática: Administrador cada 2 horas, Moderador cada 30 minutos y solo sus registros, y ninguna a partir de las 16:00."),
            ("mejorado", "El Moderador guarda sin solicitud los números de resolución y el switch Jubilado recontratado."),
            ("mejorado", "Parámetros Generales: las pestañas siempre a la vista; en Salario, también los botones y la cabecera de la tabla."),
            ("mejorado", "Si el color de una unidad es muy claro, su nombre se oscurece solo para leerse, y el nomenclador avisa al elegirlo."),
            ("mejorado", "Histórico: ninguna fecha futura, nunca dos eventos el mismo día y recontratar como pronto al día siguiente de la baja."),
            ("corregido", "Un texto técnico aparecía al principio de todas las pantallas."),
            ("corregido", "Los switches Funcionario y Designado se veían apagados aunque estuvieran activos."),
            ("corregido", "El aviso «no se ha aplicado ningún cambio» del movimiento de nómina nunca saltaba."),
        ],
    },
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
        "titulo": "Anexo 17.2, Ranking Mensual, auditoría completa y tablas a pantalla justa",
        "cambios": [
            ("nuevo", "Anexo 17.2 «Formación y Desarrollo», con pantalla propia y "
                    "Excel: una hoja por departamento más las de Adiestrados, "
                    "Contratados y Fuera de plantilla. Una fila por plaza "
                    "aprobada, también las vacantes, con el importe mensual y "
                    "la tarifa horaria, el nivel de preparación, los años de "
                    "servicio y la CLA y nocturnidad del último reporte de "
                    "Pre-Nómina cerrado."),
            ("nuevo", "Anexos 17 y 17.1: una pestaña por unidad que se carga al "
                    "abrirla, selector de varias unidades a la vez y Excel con "
                    "portada y resumen. Nuevo botón para bajar el 17 y el 17.1 "
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
            ("corregido", "El Anexo 17 dejaba fuera las unidades que no son "
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
            ("eliminado", "La exportación a PDF del Anexo 17, que no se usaba."),
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
            ("nuevo", "El Anexo 17 lista los cargos fuera de la plantilla "
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
    {
        "version": "3.0.1",
        "fecha": "2026-09-02",
        "titulo": "Informes por unidad, filtros unificados y validación de formularios",
        "cambios": [
            ("nuevo", "Puestos Clave: el informe se puede ver repartido por Unidad Organizativa —cada unidad con sus totales y sus cargos debajo, y las direcciones principales encabezando su rama— o consolidado, sumando cada cargo de todas las unidades. Se elige con el conmutador «Desglosado / Consolidado» de la barra de filtros, que recuerda su última posición."),
            ("nuevo", "Puestos Clave en Word y PDF: encabezado con el logo, la provincia, el municipio y la unidad del informe, quién lo exportó, el período y «Hoja X de Y» en todas las páginas. El nombre del fichero lleva la unidad y el mes."),
            ("nuevo", "Filtro por Unidad Organizativa en TODOS los informes de RRHH, con selección múltiple. Elegir una unidad principal incluye sus subunidades, y cada subunidad se puede consultar por separado."),
            ("nuevo", "Lista de Contratos: filtros por Unidad Organizativa, Departamento y Cargo, todos de selección múltiple."),
            ("nuevo", "Nomencladores de importes: Maestría, Doctorado, Instructor y CNCI. El contrato toma de ahí sus importes en vez de escribirlos a mano, y una regla de Subsanación avisa de los contratos cuyo importe ya no coincide."),
            ("nuevo", "Informe Inteligente: dieciséis medidas para Contratos —cuadros, mujeres en puestos clave, grado científico, nivel superior, título de oro, profesionales, jubilados recontratados, contratos determinados, antigüedad y misiones— y ocho para Estructura y Plantilla, con la cobertura de la plantilla y las plazas vacantes. Todas se pueden dibujar en la Evolución mensual."),
            ("nuevo", "Informe Inteligente: campos nuevos de Puesto Clave y Contrato Determinado en Contratos, y Puesto Clave y Plazas Vacantes en Estructura y Plantilla."),
            ("nuevo", "Selector de período unificado en Informes RRHH e Informe Inteligente: una rejilla de meses que marca en gris los que no tienen cierre declarado."),
            ("nuevo", "Usuarios: columna de Rol en el listado y botón «Actualizar conexiones» para ver al momento quién está dentro."),
            ("nuevo", "Usuarios: al asignar una Unidad Principal a un moderador entran también sus subunidades, y las unidades que ya lleva otro moderador aparecen apagadas en el desplegable. Una subunidad nueva se reparte sola, sin tener que reabrir la ficha del moderador."),
            ("nuevo", "Subsanación: siete reglas nuevas —cargo sin nivel de preparación, unidad que no declaró su cierre mensual, moderador sin todas las subunidades de su principal, subunidad sin su principal, contrato determinado vencido con el trabajador activo, fecha de alta en la entidad imposible, importe distinto al del nomenclador y fórmula de Pago por Importe que ya no es válida."),
            ("mejorado", "Un solo criterio de color en todos los formularios: amarillo el campo obligatorio que falta, rojo el dato escrito que no es válido y verde el correcto. El botón de guardar espera a que no quede nada pendiente. Los campos opcionales ya no se pintan de amarillo."),
            ("mejorado", "Todos los desplegables de la aplicación se ven y se manejan igual, con buscador para escribir en vez de recorrer la lista."),
            ("mejorado", "El selector de unidades del Dashboard, de Informes RRHH y de Informe Inteligente es el mismo control, con las subunidades indentadas bajo su principal y búsqueda por rama."),
            ("mejorado", "Informes RRHH: el desplegable de tipo de informe conserva la fuente de datos —si está mirando un cierre de agosto, sigue en agosto al cambiar de informe."),
            ("mejorado", "El Observador deja de tener acceso al panel de Notificaciones; conserva sus avisos personales en la campana."),
            ("corregido", "La exportación a Word del Resumen de Puestos Clave y del Resumen por UEB no generaba el documento."),
            ("corregido", "Puestos Clave: exportar a Word o PDF con el filtro de unidades puesto devolvía un error."),
            ("corregido", "Lista de Contratos: al cambiar de página se perdían los filtros aplicados."),
            ("corregido", "El panel de filtros de la Lista de Contratos se cerraba al elegir en un desplegable."),
            ("corregido", "Informe Inteligente: el selector de Unidad Organizativa no respondía, y la pantalla saltaba al final al recuperar un informe guardado."),
            ("corregido", "Parámetros Generales: el REUP no se validaba en el navegador."),
            ("corregido", "Formulario de Baja: «Causa de Baja» es obligatorio y no se marcaba como tal."),
            ("corregido", "Cierres mensuales: la fotografía guardaba los importes sin decimales."),
            ("corregido", "Aspirantes: el sexo deducido del carné de identidad no se daba por válido, y los desplegables encadenados del contrato se quedaban en verde después de vaciarse."),
            ("corregido", "Corregida la errata «Maetría» en el formulario de contrato."),
            ("eliminado", "Retirada la pantalla de Cargos a página completa de Nomencladores: estaba rota y duplicaba Configuración → Familias de Cargos."),
        ],
    },
    {
        "version": "3.0.0",
        "fecha": "2026-08-31",
        "titulo": "Pre-Nómina, seguridad del acceso y saneamiento de estáticos",
        "cambios": [
            ("nuevo", "Pre-Nómina: módulo completo de Reportes de Pago, con conceptos por horas, conceptos por importe y claves de ausencia, más importación y exportación de datos."),
            ("nuevo", "Pre-Nómina → Calendario: definición de jornadas, calendarios de pago y asignación de calendario a cada trabajador."),
            ("nuevo", "Pre-Nómina → Mis Plantillas: plantillas de reporte reutilizables por usuario."),
            ("nuevo", "Nomencladores propios de Pre-Nómina: Pago Asociado por Horas, Pago Asociado por Importe, Escala de Años de Servicio y Claves de Ausencia."),
            ("nuevo", "Pantalla de acceso y cambio de contraseña: botón para mostrar u ocultar la contraseña mientras se escribe. Solo muestra lo que usted teclea: nunca una contraseña rellenada por el navegador, para que nadie pueda leer en un equipo compartido una clave guardada que no conoce."),
            ("nuevo", "Pantalla de acceso: el enlace «¿Problemas para acceder?» abre un formulario que envía la incidencia a la bandeja del Administrador sin necesidad de iniciar sesión."),
            ("seguridad", "Bloqueo por intentos fallidos: 10 fallos en 5 minutos bloquean la cuenta. Protege también el panel de administración de Django, y el Administrador puede desbloquear una cuenta al instante."),
            ("seguridad", "Auditoría de accesos: los inicios de sesión, los intentos fallidos y los cierres de sesión quedan registrados. Nunca se guarda la contraseña."),
            ("seguridad", "Caducidad de sesión: se cierra a los 60 minutos de inactividad, con un techo de 12 horas, y la sesión termina al cerrar el navegador. Antes duraba dos semanas."),
            ("seguridad", "Retiradas las páginas de cambio y reseteo de contraseña que Django publica de serie: estaban accesibles sin iniciar sesión y sin plantilla, así que devolvían un error 500."),
            ("seguridad", "El sistema arranca en modo seguro si falta el fichero de configuración del entorno, en lugar de mostrar trazas con detalles internos."),
            ("seguridad", "La cookie de sesión pasa a ser inaccesible desde JavaScript y no viaja en peticiones de otros sitios."),
            ("seguridad", "Las contraseñas siguen ahora un único criterio en los tres sitios donde se fijan: alta de usuario, cambio desde «Mi Perfil» y panel de administración. Antes el cambio aceptaba contraseñas que el alta rechazaba, entre ellas algunas de las más usadas del mundo. Se mantienen las exigencias de longitud, mayúscula y número, y se añaden el rechazo de contraseñas comunes y de las parecidas al nombre de usuario."),
            ("corregido", "Los avisos de contraseña al dar de alta un usuario salían en inglés. Ahora están en español, como el resto del sistema."),
            ("corregido", "Estáticos: la carpeta generada por «collectstatic» estaba versionada y desactualizada, de modo que en producción faltaban recursos que carga toda la aplicación. Ahora se genera en cada despliegue."),
            ("corregido", "Pantalla de acceso: el usuario ya no se borra al fallar el intento, los avisos de éxito dejan de mostrarse en rojo como si fueran errores y el teclado del móvil ya no fuerza la mayúscula inicial."),
            ("corregido", "Quien ya tiene la sesión abierta y vuelve a la pantalla de acceso va directo al inicio, en lugar de ver otra vez el formulario."),
            ("mejorado", "Los gestores de contraseñas del navegador ya reconocen los campos de la pantalla de acceso."),
            ("eliminado", "Nomencladores «Horario» y «Jornada»: sus tablas estaban vacías, ninguna pantalla los usaba y ningún contrato tenía jornada asignada. El tiempo de trabajo se gestiona ahora desde Pre-Nómina → Calendario."),
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
