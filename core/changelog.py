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
        "version": "3.8.1",
        "fecha": "2026-10-26",
        "titulo": "Correcciones en Usuarios, permisos especiales, contrato y Aspirantes",
        "cambios": [
            ("mejorado", "Permisos especiales: el Moderador con «Resolver solicitudes» puede aprobar o rechazar también sus propias solicitudes, incluidas las que envió antes de tener el permiso."),
            ("mejorado", "Registrar y Editar contrato: «Modalidad de trabajo» pasa arriba y «Chofer Profesional» y «Jubilado Recontratado» debajo."),
            ("corregido", "Los selectores de varias opciones (unidades del usuario, del Dashboard, de Informes…) no enseñaban la «×» de cada elemento elegido: ahora se ve y se quita con un clic, sin abrir la lista."),
            ("corregido", "Al editar un usuario, su propio nombre aparecía como «El usuario ya existe»."),
            ("mejorado", "Editar contrato: debajo de «F. de Contratación» (que muestra la fecha de la situación actual, la del último movimiento) se ve en pequeño la fecha del Alta Inicial cuando son distintas."),
            ("corregido", "Editor del histórico: el tridente salía en minúsculas («tridente i»); ahora se ve «Tridente I»."),
            ("corregido", "Contratar desde la Lista de Contratos («+ Nuevo»): al pulsar «Continuar» no aparecía la ventana del movimiento de nómina de Alta Inicial y no se guardaba nada. Desde Aspirantes, Bajas y el Gestor de Plantilla ya funcionaba."),
            ("corregido", "Aspirantes y Bajas: el Moderador pulsaba Eliminar, confirmaba y no pasaba nada. Ahora envía la solicitud de eliminación de cualquier persona de la lista (con el permiso especial «Editar sin solicitud» elimina directamente)."),
            ("mejorado", "Búsqueda con prefijos: en Bajas, «U:» busca la unidad donde la persona causó baja; en Aspirantes ya no se ofrece, porque un aspirante no pertenece a ninguna unidad."),
            ("mejorado", "Subsanación: los avisos sobre los datos personales de un trabajador llegan al Moderador de la unidad de su contrato."),
            ("eliminado", "La ficha de la persona ya no guarda una unidad propia (era un dato duplicado e incoherente): la unidad es siempre la del cargo de su contrato."),
        ],
    },
    {
        "version": "3.8.0",
        "fecha": "2026-10-25",
        "titulo": "Permisos especiales para Moderadores, reglas de Subsanación activables y plazas sobregiradas",
        "cambios": [
            ("nuevo", "Permisos especiales: el Administrador crea perfiles con nombre (Usuarios → Perfiles de permisos) y asigna uno a cada Moderador, con fecha de caducidad y motivo opcionales. Siete permisos para toda la empresa: resolver solicitudes (incluye guardar sin solicitud), editar sin solicitud, nomencladores y parámetros, gestor de plantilla completo, editor del histórico, Subsanación como administrador, y auditoría y estadísticas. Nunca dan acceso al admin de Django ni a Usuarios, ni permiten resolver una solicitud propia."),
            ("nuevo", "Auditoría: lo que un Moderador hace gracias a un permiso especial queda marcado «con permiso especial». Asignar, cambiar o quitar un perfil queda en Auditoría y se avisa al Moderador por la campana."),
            ("nuevo", "Subsanación → Índice de Reglas: el Administrador puede desactivar las reglas que ya están limpias para aliviar el análisis (no se borran y sus avisos abiertos siguen normales), ver cuántos avisos tiene cada una, su último fallo y cuánto tarda, y «Probar ahora» una regla sin crear avisos, con opción de reactivarla."),
            ("nuevo", "Plazas sobregiradas: un contrato que ocupa plaza en un cargo con más ocupantes que plazas aprobadas no se guarda en «Editar contrato»; un aviso lista a todos los que ocupan la plaza y explica cómo resolverlo (movimiento de nómina, editor del histórico o subir las plazas aprobadas). El Moderador lo pide con una solicitud personalizada."),
            ("nuevo", "Subsanación: regla EST-011 «Cargo con más plazas cubiertas que aprobadas» y EST-010 «Unidad principal con departamentos propios»."),
            ("nuevo", "Aviso común «No se puede guardar todavía» en todos los formularios de alta y edición (aspirantes, contratos, movimientos, unidades, departamentos, cargos, bajas…): el botón se ve inactivo y, al pulsarlo, un recuadro dice qué falta o qué está mal y en qué pestaña, y lleva al campo."),
            ("nuevo", "Editor del histórico: Unidad, Departamento y Cargo en cascada; el grupo escala al pasar el ratón por el cargo; mismas reglas que el contrato para el tridente (cuadros sin tridente), el motivo y la duración; y plazas libres solo en el último evento del contrato vigente."),
            ("nuevo", "Editor del histórico: los eventos antiguos se ven con los nombres de entonces, y la casilla «Escribir a mano» permite anotar una plaza que ya no existe (o un movimiento que faltó), con la unidad de hoy a la que corresponde. Se marca «escrito a mano» en el editor, el Histórico y su PDF."),
            ("nuevo", "Notificaciones: cada usuario tiene su propia bandeja, y el Administrador una pestaña «Supervisión» con lo que se avisó a todos."),
            ("mejorado", "Editar contrato: los datos que solo cambian con un movimiento llevan al Administrador al editor del histórico; al Moderador, a una solicitud personalizada."),
            ("mejorado", "Las unidades principales no pueden tener departamentos (los tienen sus subunidades): lo impiden el formulario, el Gestor (con una explicación en el botón «+») y el importador de Excel."),
            ("mejorado", "No se pueden aprobar menos plazas de las que están cubiertas al editar un cargo."),
            ("corregido", "Editar contrato no dejaba guardar a ciertos cuadros (p. ej. Director de UEB con salario Dinámico): una copia oculta del tridente se daba por obligatoria."),
            ("corregido", "Editar contrato vaciaba el Cargo de un Indeterminado en un cargo lleno, contándose a sí mismo como si ocupara otra plaza."),
            ("corregido", "Un movimiento de nómina que pasaba a un tipo que ocupa plaza sin cambiar de cargo no comprobaba si había plaza libre."),
            ("corregido", "Editor del histórico: no reconocía el cargo de un evento cuando la unidad o el departamento se habían renombrado, y el tridente se bloqueaba según el tipo de salario sin mirar si el cargo era de cuadro."),
            ("corregido", "«Marcar todas como leídas» de un Administrador marcaba también las copias de los Moderadores."),
        ],
    },
    {
        "version": "3.7.1",
        "fecha": "2026-10-25",
        "titulo": "Histórico completo: tipo y motivo obligatorios, departamento y situación tras los cambios externos",
        "cambios": [
            ("nuevo", "Histórico del trabajador: columna Departamento en la ventana, en el PDF «Exportar Todo» y en el editor del histórico."),
            ("nuevo", "Histórico: debajo de cada cambio externo, una fila «Actualizado por cambio externo» con cómo quedó la persona (unidad, departamento, cargo y salario) y las fechas del movimiento al que afecta."),
            ("nuevo", "Histórico con los cambios externos ocultos: el último movimiento muestra la situación final, con la insignia «actualizado» y las celdas que cambiaron marcadas; al pasar el ratón se ve el dato del movimiento. En el PDF, un asterisco y una nota al final con los datos anteriores."),
            ("nuevo", "Subsanación: regla MOV-016 «Histórico sin tipo de contrato o sin motivo», con botón al editor del histórico."),
            ("nuevo", "Comando «reparar_tipos_historico»: rellena el tipo de contrato y el motivo que faltan en el histórico cuando se pueden saber con certeza (el contrato vigente, la baja o el movimiento siguiente)."),
            ("mejorado", "Editor del histórico: el tipo de contrato es obligatorio, y el motivo cuando el tipo lo pide. Ya no se ofrece «Sin tipo» ni se puede guardar sin ellos."),
            ("corregido", "La Lista de Contratos mostraba «None» cuando un contrato no tenía salario calculable; ahora dice «Sin salario» y explica por qué (también en el Excel)."),
            ("corregido", "Nomenclador de cargos: «Director Funcional» estaba en el grupo escala XIV (errata del Excel de cargos); pasa al XXIV y sus contratos recuperan el salario."),
            ("eliminado", "Una plantilla antigua de informe de contratos que ninguna pantalla usaba."),
        ],
    },
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
