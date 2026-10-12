/**
 * Recorrido visual del Gestor de Plantilla.
 *
 * Se lanza desde el botón "¿Cómo funciona?" de la cabecera del Gestor y desde
 * "Ir a Gestor de Plantilla" en la Guía de Orbith (`progreso_guia.js` busca la
 * tarea en `window.OrbithRecorridos`).
 *
 * Es interactivo: los botones de cada columna se encienden solo cuando hay
 * algo seleccionado en ella, así que el recorrido pide al usuario elegir una
 * unidad, un departamento y un cargo, y después explica en UN solo paso los
 * botones Añadir, Editar y Eliminar, que son iguales en las tres columnas:
 * ese paso abre un hueco con su flecha sobre la barra de cada columna a la
 * vez. Nunca pulsa un botón por el usuario: solo los señala.
 *
 * Cada rol ve solo los pasos de los botones que tiene (`roles`). Además, un
 * paso cuyo botón no está en la página se salta solo (ver `orbith_recorrido.js`).
 */
(function () {
  const boton = document.getElementById('btnRecorridoGestor');
  if (!boton || !window.OrbithRecorrido) return;

  const ROL = boton.dataset.rol || 'observador';
  const A = 'admin';
  const M = 'moderador';
  const O = 'observador';
  const TODOS = [A, M, O];
  const EDICION = [A, M];

  const NOTA_SOLICITUD = ' <br><em>Como Moderador, normalmente el cambio se envía como solicitud para que lo apruebe un Administrador.</em>';

  // Identificador de lo seleccionado (o '' si no hay nada). `esperar` usa el
  // valor y no un simple sí/no para detectar que el usuario eligió OTRA cosa.
  function seleccion(selector) {
    const el = document.querySelector(selector);
    return el ? (el.dataset.pk || el.id || 'si') : '';
  }

  function unidadSeleccionada() {
    return document.querySelector('#lista-unidades-container .active-unit');
  }

  // Barra de botones de una columna (lo que hay a la derecha de su título).
  function barra(panel) {
    return '#' + panel + ' .card-header-dense > .gap-1';
  }

  const LISTA_CRUD =
    '<ul class="ps-3 mb-0 mt-1">' +
    '<li><i class="fas fa-pencil-alt"></i> <strong>Editar</strong>: abre su formulario.</li>' +
    '<li><i class="fas fa-trash text-danger"></i> <strong>Eliminar</strong>: lo borra, previa confirmación.</li>' +
    '<li><i class="fas fa-plus text-primary"></i> <strong>Añadir</strong>: crea uno nuevo dentro de lo elegido en la columna anterior.</li>' +
    '</ul>';

  const TEXTO_CRUD = {
    admin: 'Las tres primeras columnas tienen los mismos botones, que actúan sobre lo seleccionado:' +
           LISTA_CRUD + 'Crear y eliminar unidades es exclusivo del Administrador.',
    moderador: 'Las tres primeras columnas tienen los mismos botones, que actúan sobre lo seleccionado:' +
           LISTA_CRUD + 'En Unidades solo puedes editar las tuyas: crearlas y eliminarlas es cosa del Administrador.' +
           NOTA_SOLICITUD,
  };

  // Los tres pasos interactivos para llegar a un cargo. Se exponen en
  // `window.OrbithPasosSeleccionGestor` porque el recorrido de contratar desde
  // el Gestor (ver `recorrido_contratacion.js`) los reutiliza en vez de
  // copiarlos. Devuelve objetos nuevos en cada llamada.
  function pasosSeleccion() {
    return [
      {
        id: 'unidad', roles: TODOS, selector: '#lista-unidades-container', interactivo: true,
        titulo: 'Elige una unidad',
        texto: function () {
          const u = unidadSeleccionada();
          if (u && u.dataset.esPrincipal === 'true') {
            return '<strong>Elegiste una Unidad Principal</strong>, que no tiene departamentos propios. ' +
                   'Despliega sus subunidades con la flecha (o con doble clic) y elige una de ellas.';
          }
          return 'Haz clic en una unidad para seleccionarla. Si es una Unidad Principal, despliega sus subunidades con la flecha (o con doble clic) y elige una de ellas.';
        },
        // Una Unidad Principal no cuenta: no tiene departamentos y el paso
        // siguiente se quedaría vacío. Se espera a una subunidad o unidad normal.
        esperar: function () {
          const u = unidadSeleccionada();
          return u && u.dataset.esPrincipal !== 'true' ? u.dataset.pk : '';
        },
      },
      {
        id: 'departamento', roles: TODOS, selector: '#col-departamentos', interactivo: true,
        titulo: 'Elige un departamento',
        texto: 'Aquí aparecen los departamentos de la unidad. Haz clic en uno para seleccionarlo.',
        esperar: function () { return seleccion('#col-departamentos .active-dept'); },
        volver: { a: 'unidad', texto: '¿No tiene departamentos? Elegir otra unidad' },
      },
      {
        id: 'cargo', roles: TODOS, selector: '#col-cargos', interactivo: true,
        titulo: 'Elige un cargo',
        texto: 'Estos son los cargos del departamento, con su estado (ACTIVO o INACTIVO). Haz clic en uno para ver quién lo ocupa.',
        esperar: function () { return seleccion('#col-cargos .active-cargo'); },
        volver: { a: 'departamento', texto: '¿No hay cargos? Elegir otro departamento' },
      },
    ];
  }
  window.OrbithPasosSeleccionGestor = pasosSeleccion;

  const PASOS = [
    {
      roles: TODOS, selector: '.dashboard-container',
      titulo: 'Bienvenido al Gestor de Plantilla',
      texto: 'Aquí ves la estructura de la empresa en cuatro columnas: <strong>Unidades → Departamentos → Cargos → Contratos</strong>. ' +
             'Cada columna se llena cuando eliges algo en la anterior. Vamos a recorrerlas juntos.',
    },
    {
      roles: TODOS, selector: '.dashboard-container .card-header-dense > .gap-2',
      titulo: 'Las cuatro columnas',
      texto: 'Pulsa el título de cualquier columna para cambiar su orden. En Unidades, el punto de color de cada una indica su estado en el cierre mensual.',
    },
    {
      roles: TODOS, selector: '#search-unit, #search-dept, #search-cargo, #search-personal',
      titulo: 'Buscadores',
      texto: 'Cada columna tiene su buscador "Filtrar...": escribe parte de un nombre para encontrarlo. Los de las columnas 2, 3 y 4 se activan al elegir algo en la anterior.',
    },

    // --- Selección: unidad → departamento → cargo ---
    ...pasosSeleccion(),

    // --- Botones comunes de las tres primeras columnas, en un solo paso ---
    {
      roles: EDICION,
      selector: [barra('col-panel-unit'), barra('col-panel-dept'), barra('col-panel-cargo')].join(', '),
      titulo: 'Añadir, editar y eliminar',
      texto: TEXTO_CRUD[ROL] || '',
    },
    {
      roles: EDICION, selector: '#btn-declarar-unit, #btn-reabrir-unit',
      titulo: 'Cierre mensual de la unidad',
      texto: '<i class="fas fa-calendar-check text-success"></i> <strong>Declarar actualizada</strong>: cuando la plantilla de la unidad está al día, la declara para el cierre del mes y Orbith guarda una fotografía de cómo está.<br>' +
             '<i class="fas fa-undo-alt text-warning"></i> <strong>Volver a Pendiente</strong>: si declaraste por error, la reabre y descarta la fotografía.<br>' +
             'Cada uno se apaga cuando no se puede usar en ese momento.',
    },
    {
      roles: TODOS, selector: '#filtro-plantilla, #col-panel-cargo [title="Ordenar Activos/Inactivos"]',
      titulo: 'Dentro o fuera de plantilla',
      texto: 'El desplegable muestra todos los cargos, solo los que están en la plantilla aprobada o solo los que están fuera de ella. Pulsando "Estado" los ordenas por activos e inactivos.',
    },

    // --- 4. Contratos ---
    {
      roles: TODOS,
      selector: '#col-panel-contrato [title="Ordenar por Salario"], #col-panel-contrato [title="Ordenar por Expediente"]',
      titulo: '4. Contratos',
      texto: 'La última columna muestra las personas que ocupan el cargo, con su salario y su número de expediente. Pulsa "Salario" o "Expedientes" para ordenar por esa columna. Si nadie ocupa el cargo, verás "Plaza Vacante".',
    },
    {
      roles: EDICION, selector: '#btn-add-personal',
      titulo: 'Contratar',
      texto: 'El botón "+" abre la ventana "Nuevo contrato" para elegir un aspirante. El formulario llega con este cargo ya elegido.',
    },
    {
      roles: TODOS, selector: '#col-contratos', interactivo: true,
      titulo: 'Elige un trabajador',
      texto: 'Haz clic en una persona para seleccionarla: se encienden los botones de la columna.',
      esperar: function () { return seleccion('#col-contratos .active-contrato'); },
      volver: { a: 'cargo', texto: '¿Plaza vacante? Elegir otro cargo' },
    },
    {
      roles: EDICION, selector: '#btn-edit-contrato',
      titulo: 'Editar Contrato',
      texto: 'Abre el contrato de la persona seleccionada para corregir sus datos.' + (ROL === M ? NOTA_SOLICITUD : ''),
    },
    {
      roles: EDICION, selector: '#btn-edit-personal',
      titulo: 'Editar Datos Personales',
      texto: 'Abre la ficha personal del trabajador: nombre, carnet, dirección, nivel educacional, etc.',
    },
    {
      roles: EDICION, selector: '#btn-movimiento',
      titulo: 'Enviar a Mov. Nómina',
      texto: 'Marca el contrato para un movimiento de nómina (cambio de cargo, unidad o salario), que después se confirma en "Mov. Nómina". Si el contrato ya está en movimiento, este mismo botón aparece como una X roja y sirve para cancelarlo.',
    },
    {
      roles: TODOS, selector: '#btn-pdf',
      titulo: 'Exportar Contrato',
      texto: 'Abre en otra pestaña la exportación del contrato: eliges el documento (contrato de trabajo o modificación al contrato) y se descarga en Word.',
    },
    {
      roles: EDICION, selector: '#btn-baja',
      titulo: 'Dar de Baja',
      texto: 'Abre el Formulario de Baja del trabajador seleccionado: fecha de baja, fecha de documento y causa. Orbith pide confirmación antes de darla.',
    },
    {
      roles: TODOS, selector: '#col-contratos .active-contrato',
      titulo: 'Histórico del trabajador',
      texto: 'Con doble clic sobre una persona se abre su "Histórico del Trabajador", con todos sus movimientos.',
    },
    {
      roles: TODOS, selector: '#btnRecorridoGestor',
      titulo: '¡Listo!',
      texto: 'Ya conoces el Gestor de Plantilla. Puedes repetir este recorrido cuando quieras con el botón "¿Cómo funciona?". Si moviste esta tarjeta, el botón <i class="bx bx-reset"></i> de su barra la vuelve a colocar sola.',
    },
  ];

  function iniciar() {
    window.OrbithRecorrido.iniciar({
      pasos: PASOS.filter(function (p) { return p.roles.indexOf(ROL) !== -1; }),
    });
  }

  // Se lanza desde el menú "¿Cómo funciona?" (`data-recorrido`, ver
  // `orbith_recorrido.js`) y desde "Ir a Gestor de Plantilla" en la Guía.
  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['primera_exploracion_plantilla'] = iniciar;
})();
