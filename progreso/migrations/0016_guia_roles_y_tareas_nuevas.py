from django.db import migrations

# La Guía de Orbith estaba incompleta en tres sentidos:
#
# * No distinguía roles. Un Observador veía «Crea tu primer Aspirante» o
#   «Ejecuta tu primer análisis» aunque no puede hacerlo, y nunca llegaba al
#   100 %. Aquí se marca qué roles ven cada tarea (campos de 0015).
# * Había instrucciones desactualizadas. Subsanación no está dentro de
#   «Administración» sino en el menú principal, el botón que lanza el análisis
#   es «Analizar la base de datos» (lo otro es la pestaña), Contrato y Mov.
#   Nómina son entradas directas del menú, y el cierre mensual tenía tres
#   pasos que no decían dónde estaba el botón.
# * Faltaban módulos: Solicitudes, Gestor de Plantilla, Informes RRHH,
#   Notificaciones (recordatorios) y Reportar problema.
#
# Todos los textos se comprobaron contra las plantillas actuales.

A, M, O = 'A', 'M', 'O'

ROLES = {
    'primer_aspirante': ('A', 'M'),
    'primera_contratacion': ('A', 'M'),
    'primer_movimiento_interno': ('A', 'M'),
    'primer_movimiento_cedido': ('M',),
    'primer_movimiento_recibido': ('M',),
    'primera_baja': ('A', 'M'),
    'primer_informe_generado': ('A', 'M', 'O'),
    'primera_exportacion_pdf': ('A', 'M', 'O'),
    'primera_exportacion_word': ('A', 'M', 'O'),
    'primera_exportacion_excel': ('A', 'M', 'O'),
    'primer_analisis_subsanacion': ('A',),
    'primera_revision_hallazgo': ('A', 'M'),
    'primer_informe_favorito': ('A', 'M', 'O'),
    'primer_cierre_declarado': ('A', 'M'),
    'primera_solicitud_enviada': ('M',),
    'primera_exploracion_plantilla': ('A', 'M', 'O'),
    'primer_informe_rrhh': ('A', 'M', 'O'),
    'primer_recordatorio_completado': ('M',),
    'primer_reporte_problema': ('A', 'M', 'O'),
    'primera_solicitud_decidida': ('A',),
    'primer_recordatorio_creado': ('A',),
}

INSTRUCCIONES_ANTERIORES = {
    'primera_contratacion': (
        'Ve al listado de Aspirantes.\n'
        'Haz clic sobre la fila del Aspirante que vas a contratar: se resalta y se activan los botones de arriba.\n'
        'Pulsa el botón verde "Contrato" (el del ícono de la firma).\n'
        'En la primera pantalla, elige la Unidad Organizativa, el Departamento y el Cargo (cada uno filtra al siguiente).\n'
        'Completa también el No. de Expediente, el Tipo de Contrato, el Registro Militar y la F. Alta Entidad: son obligatorios siempre.\n'
        'Si el Tipo de Contrato elegido lo exige, aparecerá el Motivo de Contrato: complétalo también.\n'
        'Si el salario es Dinámico y el cargo no es de Cuadro, elige además el Tridente.\n'
        'Pulsa "Continuar".\n'
        'En la segunda pantalla ("Movimiento de Nómina"), la Fecha Efectiva ya viene completada y bloqueada: no hay que tocarla. Escribe la Fecha de Solicitud y pulsa "Confirmar Movimiento".\n'
        'Listo: el Aspirante pasa a estado "Activo" de forma automática, no hace falta hacer nada más.'
    ),
    'primer_movimiento_interno': (
        'Ve a Contrato → Lista de Contratos.\n'
        'Haz clic en la fila del trabajador para seleccionarlo.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir": la fila queda resaltada en amarillo.\n'
        'Ve a Contrato → Mov. Nómina.\n'
        'Dentro de "Solicitudes Pendientes", haz clic en esa misma fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Completa la Unidad Organizativa, el Departamento, el Cargo, la Fecha Efectiva del Movimiento y la Fecha de Solicitud (puedes repetir la misma unidad si solo cambias cargo o salario): las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar.'
    ),
    'primer_movimiento_cedido': (
        'Ve a Contrato → Lista de Contratos.\n'
        'Haz clic en la fila del trabajador que va a cambiar de unidad.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir".\n'
        'Listo: el contrato queda marcado "en proceso" (fila en amarillo) y disponible en la bandeja de movimientos pendientes para que el moderador que lo recibe lo complete desde su propia sesión.\n'
        'Si necesitas anular la solicitud, vuelve a esa fila (ahora en rojo) y pulsa "Cancelar Movimiento".'
    ),
    'primer_movimiento_recibido': (
        'Ve a Contrato → Mov. Nómina.\n'
        'En "Solicitudes Pendientes" verás los contratos que cualquier moderador haya marcado "en proceso" en todo el sistema: busca al trabajador que esperas recibir.\n'
        'Haz clic en su fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Elige tu Unidad Organizativa, Departamento y Cargo de destino (el desplegable de Unidad solo te mostrará las tuyas), y completa la Fecha Efectiva del Movimiento y la Fecha de Solicitud: las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar: el trabajador queda incorporado a tu unidad.'
    ),
    'primera_baja': (
        'Ve a Contrato → Lista de Contratos.\n'
        'Haz clic sobre la fila del trabajador para seleccionarlo: se activan los botones de arriba.\n'
        'Pulsa el botón rojo "Dar de Baja".\n'
        'En el Formulario de Baja, completa la Fecha de Baja, la Fecha de Documento y la Causa de Baja: las tres son obligatorias. La Fecha de Baja no puede ser anterior al último movimiento de nómina registrado del trabajador.\n'
        'Observaciones y los interruptores "Cobró sistema de pago" / "Completar cargo" son opcionales.\n'
        'Pulsa "Confirmar Baja" y, en el mensaje que aparece, confirma de nuevo con "Sí, dar de baja".\n'
        'Al terminar, el sistema te ofrece exportar el PDF del movimiento generado.'
    ),
    'primera_exportacion_pdf': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "PDF".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.'
    ),
    'primera_exportacion_word': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Word".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.'
    ),
    'primera_exportacion_excel': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Excel".\n'
        'El archivo se descarga con las mismas columnas, filtros y orden que ves en pantalla.\n'
        'Otros módulos, como Plantilla → Anexo 14, tienen su propio botón de Excel.'
    ),
    'primer_analisis_subsanacion': (
        'Ve a Administración → Subsanación.\n'
        'Pulsa "Ejecutar nuevo análisis".\n'
        'Espera a que termine de revisar cada módulo.\n'
        'Consulta el índice de salud y los hallazgos detectados.'
    ),
    'primera_revision_hallazgo': (
        'Ve a Administración → Subsanación.\n'
        'En el listado de hallazgos, pulsa "Ver detalle" sobre uno de ellos.\n'
        'Cambia su estado (revisado, corregido, ignorado, falso positivo) desde el modal.\n'
        'Si vas a ignorarlo o marcarlo falso positivo, deja una nota antes de guardar.'
    ),
    'primer_cierre_declarado': (
        'Ve a Plantilla → Gestor de Plantilla.\n'
        'Selecciona tu Unidad Organizativa.\n'
        'Pulsa "Declarar actualizada" para el cierre del mes en curso.'
    ),
}

INSTRUCCIONES_NUEVAS = {
    'primera_contratacion': (
        'En el menú lateral, pulsa "Aspirante": te lleva directo al listado.\n'
        'Haz clic sobre la fila del Aspirante que vas a contratar: se resalta y se activan los botones de arriba.\n'
        'Pulsa el botón verde "Contrato" (el del ícono de la firma).\n'
        'En la primera pantalla, elige la Unidad Organizativa, el Departamento y el Cargo (cada uno filtra al siguiente).\n'
        'Completa también el No. de Expediente, el Tipo de Contrato, el Registro Militar y la F. Alta Entidad: son obligatorios siempre.\n'
        'Si el Tipo de Contrato elegido lo exige, aparecerá el Motivo de Contrato: complétalo también.\n'
        'Si el salario es Dinámico y el cargo no es de Cuadro, elige además el Tridente.\n'
        'Pulsa "Continuar".\n'
        'En la segunda pantalla ("Movimiento de Nómina"), la Fecha Efectiva ya viene completada y bloqueada: no hay que tocarla. Escribe la Fecha de Solicitud y pulsa "Confirmar Movimiento".\n'
        'Listo: el Aspirante pasa a estado "Activo" de forma automática, no hace falta hacer nada más.'
    ),
    'primer_movimiento_interno': (
        'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.\n'
        'Haz clic en la fila del trabajador para seleccionarlo.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir": la fila queda resaltada en amarillo.\n'
        'En el menú lateral, pulsa "Mov. Nómina".\n'
        'Dentro de "Solicitudes Pendientes", haz clic en esa misma fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Completa la Unidad Organizativa, el Departamento, el Cargo, la Fecha Efectiva del Movimiento y la Fecha de Solicitud (puedes repetir la misma unidad si solo cambias cargo o salario): las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar.'
    ),
    'primer_movimiento_cedido': (
        'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.\n'
        'Haz clic en la fila del trabajador que va a cambiar de unidad.\n'
        'Pulsa el botón amarillo "Enviar a Mov. Nómina" (ícono de sincronizar) en la barra superior.\n'
        'Confirma en el mensaje "¿Desea Permitir un Movimiento de Nómina?" pulsando "Sí, permitir".\n'
        'Listo: el contrato queda marcado "en proceso" (fila en amarillo) y disponible en la bandeja de movimientos pendientes para que el moderador que lo recibe lo complete desde su propia sesión.\n'
        'Si necesitas anular la solicitud, vuelve a esa fila (ahora en rojo) y pulsa "Cancelar Movimiento".'
    ),
    'primer_movimiento_recibido': (
        'En el menú lateral, pulsa "Mov. Nómina".\n'
        'En "Solicitudes Pendientes" verás los contratos que cualquier moderador haya marcado "en proceso" en todo el sistema: busca al trabajador que esperas recibir.\n'
        'Haz clic en su fila para seleccionarla.\n'
        'Pulsa "Confirmar Movimiento".\n'
        'Elige tu Unidad Organizativa, Departamento y Cargo de destino (el desplegable de Unidad solo te mostrará las tuyas), y completa la Fecha Efectiva del Movimiento y la Fecha de Solicitud: las dos fechas son obligatorias.\n'
        'Pulsa "Confirmar Movimiento" para guardar: el trabajador queda incorporado a tu unidad.'
    ),
    'primera_baja': (
        'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.\n'
        'Haz clic sobre la fila del trabajador para seleccionarlo: se activan los botones de arriba.\n'
        'Pulsa el botón rojo "Dar de Baja".\n'
        'En el Formulario de Baja, completa la Fecha de Baja, la Fecha de Documento y la Causa de Baja: las tres son obligatorias. La Fecha de Baja no puede ser anterior al último movimiento de nómina registrado del trabajador.\n'
        'Observaciones y los interruptores "Cobró sistema de pago" / "Completar cargo" son opcionales.\n'
        'Pulsa "Confirmar Baja" y, en el mensaje que aparece, confirma de nuevo con "Sí, dar de baja".\n'
        'Al terminar, el sistema te ofrece exportar el PDF del movimiento generado.'
    ),
    'primera_exportacion_pdf': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "PDF".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.\n'
        'Cuenta cualquier exportación de Orbith en este formato, por ejemplo la de los botones de Informes RRHH.'
    ),
    'primera_exportacion_word': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Word".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.\n'
        'Cuenta cualquier exportación de Orbith en este formato, por ejemplo la de los botones de Informes RRHH.'
    ),
    'primera_exportacion_excel': (
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Excel".\n'
        'El archivo se descarga con las mismas columnas, filtros y orden que ves en pantalla.\n'
        'Cuenta cualquier exportación de Orbith en este formato, por ejemplo la de los botones de Informes RRHH, los Anexos 14 o Subsanación.'
    ),
    'primer_analisis_subsanacion': (
        'En el menú lateral, pulsa "Subsanación".\n'
        'Abre la pestaña "Ejecutar nuevo análisis" (solo la ve el Administrador).\n'
        'Pulsa "Analizar la base de datos". El análisis solo lee datos: no modifica nada.\n'
        'Espera sin cambiar de página: Orbith revisa los módulos uno a uno y te muestra el avance. Termina cuando aparece "Análisis terminado".\n'
        'En la pestaña "Dashboard" verás la salud general de los datos y la salud por categoría.\n'
        'En la pestaña "Hallazgos" tienes cada problema encontrado, listo para revisarlo.'
    ),
    'primera_revision_hallazgo': (
        'En el menú lateral, pulsa "Subsanación" y abre la pestaña "Hallazgos". Si eres Moderador, solo verás los de tus unidades.\n'
        'Si quieres acotar la lista, usa los filtros; después pulsa "Ver detalle" en un hallazgo.\n'
        'Lee qué problema se detectó. Si hay que corregir el dato, pulsa el botón azul que lleva al registro (se abre en otra pestaña) y corrígelo desde su formulario: Subsanación nunca cambia datos por ti.\n'
        'En "Registrar una revisión", elige el Estado: Pendiente, En revisión, Corregido, Ignorado o Falso positivo.\n'
        'Si eliges Ignorado o Falso positivo, la Observación es obligatoria: explica por qué.\n'
        'Pulsa "Guardar revisión".'
    ),
    'primer_cierre_declarado': (
        'En el menú lateral, pulsa "Gestor de Plantilla".\n'
        'En la columna "1. Unidades Organizativas", haz clic en tu unidad para seleccionarla.\n'
        'Revisa que sus departamentos, cargos y contratos estén al día: al declarar, Orbith guarda una fotografía de la unidad tal como está en ese momento.\n'
        'En la barra de esa columna, pulsa el botón verde del calendario ("Declarar actualizada").\n'
        'Si te equivocaste y el botón amarillo "Volver a Pendiente" está activo, puedes reabrirla.\n'
        'Para ver el estado de todas tus unidades, despliega "Gestor de Plantilla" en el menú (flecha o doble clic) y entra en "Cierres Mensuales".'
    ),
}

TAREAS_NUEVAS = [
    {
        'codigo': 'primera_solicitud_enviada',
        'categoria': 'PRI',
        'orden': 45,
        'titulo': 'Envía tu primera solicitud de cambio',
        'descripcion': 'Propusiste un cambio para que lo apruebe un Administrador.',
        'modulo': 'Solicitudes',
        'url_relacionada': '/solicitudes/',
        'instrucciones': (
            'Algunos cambios no se guardan directamente: los propones y un Administrador los aprueba. Pasa al añadir, editar o eliminar departamentos y cargos de la plantilla, al editar una unidad o un contrato, y al eliminar un trabajador.\n'
            'En esos formularios verás el campo "Motivo de la solicitud" y el botón "Enviar Solicitud" en lugar de "Guardar".\n'
            'Explica en el motivo por qué pides el cambio: lo leerá el Administrador que lo revise.\n'
            'Para añadir o editar un Nomenclador de Cargo, pulsa "Solicitudes" en el menú lateral y después "Añadir Solicitud".\n'
            'Pulsa "Enviar Solicitud".\n'
            'Sigue su estado en Solicitudes, con las pestañas "En Espera", "Aprobadas" y "Rechazadas". Mientras esté En Espera puedes editarla con el lápiz.'
        ),
    },
    {
        'codigo': 'primera_exploracion_plantilla',
        'categoria': 'EXP',
        'orden': 52,
        'titulo': 'Recorre la plantilla hasta un trabajador',
        'descripcion': 'Navegaste por el Gestor de Plantilla hasta las personas de un cargo.',
        'modulo': 'Gestor de Plantilla',
        'url_relacionada': '/estructuras/gestor/',
        'instrucciones': (
            'En el menú lateral, pulsa "Gestor de Plantilla". El botón "¿Cómo funciona?" de la cabecera te hace un recorrido visual por cada botón.\n'
            'Columna "1. Unidades Organizativas": haz clic en una unidad. Su barra permite editarla, declararla actualizada para el cierre mensual o volverla a Pendiente; el Administrador además puede añadir y eliminar unidades.\n'
            'Columna "2. Departamentos": haz clic en uno. Desde su barra puedes añadir, editar y eliminar departamentos.\n'
            'Columna "3. Cargos": haz clic en uno. Puedes añadir, editar y eliminar cargos, y ver solo los que están dentro o fuera de la plantilla aprobada.\n'
            'Columna "4. Contratos": aparecen las personas que ocupan el cargo. Al seleccionar una puedes editar su contrato o sus datos personales, enviarla a Mov. Nómina, exportar su contrato o darla de baja. El botón "+" contrata a un aspirante en ese cargo y el doble clic abre su histórico.\n'
            'Cada columna tiene su buscador ("Filtrar...") y se ordena pulsando su título. El Observador solo consulta, el Moderador ve únicamente sus unidades y muchos de sus cambios se envían como solicitud.'
        ),
    },
    {
        'codigo': 'primer_informe_rrhh',
        'categoria': 'EXP',
        'orden': 55,
        'titulo': 'Consulta los Informes RRHH',
        'descripcion': 'Abriste uno de los informes de Recursos Humanos.',
        'modulo': 'Informes RRHH',
        'url_relacionada': '/informes/economia/',
        'instrucciones': (
            'En el menú lateral, dentro de "Informes", pulsa "Informes RRHH": se abre el Consolidado de la Fuerza de Trabajo.\n'
            'Con el selector de la derecha cambias de informe: Consolidado F. Trabajo, Trabajadores x UEB, Resumen Puestos Clave, Misiones Internacionales, Registro Diario por Trabajadores, Contratos Determinados (Motivos) y Altas y Bajas del Mes.\n'
            'El filtro de Unidad Organizativa (icono del edificio) limita el informe a las unidades que elijas.\n'
            'Junto al título, el selector de período te deja ver la información actual o la fotografía de un mes ya cerrado. En "Altas y Bajas del Mes" eliges el mes de los movimientos.\n'
            'Los botones PDF, Excel y Word descargan el informe tal como lo ves.'
        ),
    },
    {
        'codigo': 'primer_recordatorio_completado',
        'categoria': 'EXP',
        'orden': 92,
        'titulo': 'Completa tu primer recordatorio',
        'descripcion': 'Marcaste como completado un recordatorio que te envió un Administrador.',
        'modulo': 'Notificaciones',
        'url_relacionada': '/notificaciones/notificaciones/lista/?tab=recordatorios&sub=administracion',
        'instrucciones': (
            'En el menú lateral, pulsa "Notificaciones".\n'
            'Abre la pestaña "Recordatorios" y, dentro, "Administración": son los que un Administrador creó para tu unidad. En "Sistema" están los automáticos, que se resuelven solos.\n'
            'Lee el título, el mensaje y la fecha objetivo.\n'
            'Cuando hayas hecho lo que pide, pulsa "Marcar completado" en su fila.'
        ),
    },
    {
        'codigo': 'primer_reporte_problema',
        'categoria': 'EXP',
        'orden': 95,
        'titulo': 'Aprende a reportar un problema',
        'descripcion': 'Enviaste tu primer reporte de problema al Administrador.',
        'modulo': 'Soporte',
        'url_relacionada': '',
        'instrucciones': (
            'Pulsa tu foto de perfil en el menú lateral y elige "Acerca de Orbith".\n'
            'Pulsa "Reportar problema".\n'
            'En "Describa el problema", explica qué ocurrió, en qué pantalla y qué esperabas que pasara.\n'
            'Si puedes, pulsa "Añadir imagen" para adjuntar hasta 4 capturas (2 MB como máximo cada una). Si viste un error en la consola (F12), pégalo en su apartado.\n'
            'Pulsa "Enviar reporte": el Administrador lo verá en su bandeja, junto con la pantalla desde la que lo enviaste.'
        ),
    },
    {
        'codigo': 'primera_solicitud_decidida',
        'categoria': 'DOM',
        'orden': 125,
        'titulo': 'Decide tu primera solicitud',
        'descripcion': 'Aprobaste o rechazaste una solicitud enviada por un Moderador.',
        'modulo': 'Solicitudes',
        'url_relacionada': '/solicitudes/',
        'instrucciones': (
            'En el menú lateral, pulsa "Solicitudes".\n'
            'En la pestaña "En Espera", pulsa el botón "Revisar" de una solicitud. Mientras la revisas, nadie más puede tocarla.\n'
            'Compara la situación actual con la propuesta: los campos que cambian aparecen resaltados. Lee también el motivo indicado por el Moderador.\n'
            'Si hace falta, puedes modificar los valores propuestos antes de aprobar.\n'
            'Pulsa "Aprobar solicitud" y confirma con "Sí, aprobar": el cambio se aplica en ese momento.\n'
            'Para rechazarla, pulsa "Rechazar", escribe el motivo del rechazo y pulsa "Rechazar solicitud": el Moderador lo recibirá en su notificación.\n'
            'Si decides no resolverla ahora, pulsa "Cancelar revisión" para liberarla. Si cierras sin hacerlo, se libera sola a los 30 minutos.'
        ),
    },
    {
        'codigo': 'primer_recordatorio_creado',
        'categoria': 'DOM',
        'orden': 130,
        'titulo': 'Crea tu primer recordatorio',
        'descripcion': 'Enviaste un recordatorio a los responsables de una unidad.',
        'modulo': 'Notificaciones',
        'url_relacionada': '/notificaciones/notificaciones/lista/?tab=recordatorios&sub=administracion',
        'instrucciones': (
            'En el menú lateral, pulsa "Notificaciones".\n'
            'Abre la pestaña "Recordatorios" y, dentro, "Administración".\n'
            'Pulsa "Nuevo recordatorio".\n'
            'Completa el Título, el Mensaje, la Fecha objetivo y la Unidad organizativa: los cuatro son obligatorios.\n'
            'Pulsa "Crear recordatorio": lo reciben los moderadores de esa unidad y los administradores.\n'
            'Cuando alguien lo marque como completado, deja de estar pendiente.'
        ),
    },
]


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')

    for datos in TAREAS_NUEVAS:
        TareaGuia.objects.update_or_create(codigo=datos['codigo'], defaults=datos)

    for codigo, instrucciones in INSTRUCCIONES_NUEVAS.items():
        TareaGuia.objects.filter(codigo=codigo).update(instrucciones=instrucciones)

    # Los roles se aplican al final para que también cubran las tareas nuevas.
    for codigo, roles in ROLES.items():
        TareaGuia.objects.filter(codigo=codigo).update(
            para_admin=A in roles, para_moderador=M in roles, para_observador=O in roles)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')

    TareaGuia.objects.filter(codigo__in=[t['codigo'] for t in TAREAS_NUEVAS]).delete()

    for codigo, instrucciones in INSTRUCCIONES_ANTERIORES.items():
        TareaGuia.objects.filter(codigo=codigo).update(instrucciones=instrucciones)

    # Volver a "todos ven todo", como antes de 0015.
    TareaGuia.objects.update(para_admin=True, para_moderador=True, para_observador=True)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0015_tareaguia_roles'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
