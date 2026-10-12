/**
 * Recorrido visual de la lista de Aspirantes y del alta de un aspirante.
 *
 * Se lanza desde el menú "¿Cómo funciona?" de la lista de Aspirantes y desde
 * "Ir a Aspirantes" en la Guía de Orbith (tarea `primer_aspirante`, ver
 * `progreso_guia.js`).
 *
 * Primero enseña la lista (buscador, filtros, orden y botones). Después, si
 * el rol puede crear aspirantes, pide pulsar "Nuevo" y acompaña el formulario
 * por bloques: cada paso resalta a la vez los campos del bloque y espera a que
 * estén rellenos los obligatorios; los opcionales se pueden pasar sin
 * rellenar. Termina pidiendo pulsar "Guardar": al guardarse, Orbith entrega el
 * logro de la Guía. El recorrido nunca escribe ni guarda nada por el usuario.
 */
(function () {
  const boton = document.getElementById('btnRecorridoAspirantes');
  if (!boton || !window.OrbithRecorrido) return;

  const ROL = boton.dataset.rol || 'observador';
  const A = 'admin';
  const M = 'moderador';
  const O = 'observador';
  const TODOS = [A, M, O];
  const EDICION = [A, M];

  const FORM = '#formAgregarAspirante';
  const ESPERA_CAMPOS = 'Completa los campos obligatorios para continuar.';
  // Si el usuario cierra el formulario a medias, el recorrido vuelve solo al
  // paso "Nuevo". Sin `texto`: no hace falta un enlace mientras el
  // formulario sigue abierto.
  const VOLVER_A_NUEVO = { a: 'nuevo' };

  function valor(id) {
    const el = document.getElementById(id);
    return el ? String(el.value || '').trim() : '';
  }

  // Todos los campos con valor y ninguno marcado en rojo por la validación
  // en vivo (`aspirante_formulario.js` pone `is-invalid`).
  function rellenos(ids) {
    return ids.every(function (id) {
      const el = document.getElementById(id);
      return el && valor(id) && !el.classList.contains('is-invalid');
    }) ? 'si' : '';
  }

  // El menú "Más filtros" se despliega mientras dura su paso para que se vea.
  // Se abre con `autoClose: false`: con el comportamiento normal, cualquier
  // clic fuera (incluido en la tarjeta del recorrido) lo plegaría. Al salir
  // se desecha esa instancia y el botón vuelve a funcionar como siempre.
  function abrirFiltros() {
    const btn = document.getElementById('btnMasFiltrosAspirantes');
    if (!btn || !window.bootstrap) return;
    const actual = bootstrap.Dropdown.getInstance(btn);
    if (actual) actual.dispose();
    new bootstrap.Dropdown(btn, { autoClose: false }).show();
  }

  function cerrarFiltros() {
    const btn = document.getElementById('btnMasFiltrosAspirantes');
    const instancia = btn && window.bootstrap && bootstrap.Dropdown.getInstance(btn);
    if (!instancia) return;
    instancia.hide();
    instancia.dispose();
  }

  const PASOS = [
    // --- La lista ---
    {
      roles: TODOS, selector: '#tablaAspirantesCard',
      titulo: 'Lista de Aspirantes',
      texto: 'Aquí están las personas registradas en Orbith que todavía no tienen contrato. Desde esta pantalla se buscan, se editan, se contratan y se dan de alta aspirantes nuevos.',
    },
    {
      roles: TODOS, selector: '#search',
      titulo: 'Buscador',
      texto: 'Escribe un nombre, un apellido o un carnet: la tabla se filtra mientras escribes. Con Esc se borra la búsqueda. ' +
        'También admite <strong>prefijos</strong> para buscar en un dato concreto, como <code>N:Juan</code>, <code>CI:850101</code> o <code>U:flor</code>: el botón <strong>"?"</strong> del buscador los explica.',
    },
    {
      roles: TODOS, selector: '#btnMasFiltrosAspirantes, #btnMasFiltrosAspirantes + .dropdown-menu',
      titulo: 'Más filtros',
      texto: 'Este botón abre los filtros que ves desplegados: <strong>ubicación</strong> (provincia y municipio), <strong>datos personales</strong> (sexo y raza) y <strong>formación</strong> (nivel educacional, especialidad y grado científico). Cada filtro se aplica al momento y "Reset" los quita todos.',
      alEntrar: abrirFiltros,
      alSalir: cerrarFiltros,
    },
    {
      roles: TODOS, selector: '#tablaAspirantesCard thead tr',
      titulo: 'Ordenar la tabla',
      texto: 'Pulsa el título de una columna (CI, Nombre y Apellidos, Ubicación, Nivel Educacional o Especialidad) para ordenar por ella. Pulsando otra vez se invierte el orden.',
    },
    {
      roles: TODOS, selector: '#aspirante-toolbar',
      titulo: 'Editar, Contrato y Eliminar',
      texto: function () {
        if (ROL === O) {
          return 'Estos botones editan, contratan o eliminan al aspirante seleccionado. Tu usuario es de solo consulta, así que para ti quedan siempre apagados.';
        }
        return 'Haz clic en una fila para seleccionar un aspirante y se encienden estos botones:' +
          '<ul class="ps-3 mb-0 mt-1">' +
          '<li><i class="fas fa-user-edit text-primary"></i> <strong>Editar</strong> sus datos.</li>' +
          '<li><i class="fas fa-file-signature text-success"></i> <strong>Contrato</strong>: empieza su contratación (lo verás en la tarea "Realiza tu primera contratación").</li>' +
          '<li><i class="fas fa-trash text-danger"></i> <strong>Eliminar</strong> el aspirante, previa confirmación.</li>' +
          '</ul>';
      },
    },

    // --- Alta de un aspirante ---
    {
      id: 'nuevo', roles: EDICION, selector: '#btnNuevoAspirante', interactivo: true,
      titulo: 'Crea un aspirante',
      texto: 'Pulsa <strong>"Nuevo"</strong> para abrir el formulario. Te acompaño campo a campo.',
      esperar: function () {
        return document.querySelector('#crear_aspir.show ' + FORM) ? 'abierto' : '';
      },
    },
    {
      roles: EDICION, selector: '#id_doc_identidad, #id_serie_ci, #edad_calculada, #id_sexo',
      interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER_A_NUEVO,
      titulo: 'Identidad',
      texto: 'Escribe el <strong>Doc. de Identidad</strong> (11 dígitos): Orbith calcula la <strong>edad</strong> y propone el <strong>sexo</strong>, así compruebas que lo tecleaste bien. ' +
             'La <strong>serie del carnet</strong> (9 caracteres) es opcional. Si el carnet ya pertenece a un trabajador, se marca en rojo.',
      esperar: function () { return rellenos(['id_doc_identidad', 'id_sexo']); },
    },
    {
      roles: EDICION, selector: '#id_nombre, #id_papellido, #id_sapellido',
      interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER_A_NUEVO,
      titulo: 'Nombre y apellidos',
      texto: 'Completa el <strong>nombre</strong> y los <strong>dos apellidos</strong>. Los tres son obligatorios.',
      esperar: function () { return rellenos(['id_nombre', 'id_papellido', 'id_sapellido']); },
    },
    {
      roles: EDICION, selector: '#id_movil_personal, #id_fijo_personal',
      interactivo: true, opcional: true, volver: VOLVER_A_NUEVO,
      titulo: 'Contacto',
      texto: 'El <strong>móvil</strong> y el <strong>teléfono fijo</strong> no son obligatorios, pero conviene ponerlos: Subsanación los reclama después. Si el móvil ya es de otro trabajador, se marca en rojo.',
    },
    {
      roles: EDICION, selector: '#id_direccion, #id_provincia, #id_municipio, #id_codigo_postal',
      interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER_A_NUEVO,
      titulo: 'Dirección',
      texto: 'Elige la <strong>Provincia</strong> y después el <strong>Municipio</strong>: la lista de municipios se carga según la provincia. Los dos son obligatorios. ' +
             'La <strong>dirección</strong> y el <strong>código postal</strong> son opcionales.',
      esperar: function () { return rellenos(['id_provincia', 'id_municipio']); },
    },
    {
      roles: EDICION, selector: '#id_nivel_educ, #id_especialidad, #bloqueTituloOro, #id_grado_cientifico',
      interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER_A_NUEVO,
      titulo: 'Formación',
      texto: 'El <strong>Nivel Educacional</strong> es obligatorio. Con Técnico Medio o Nivel Superior puedes elegir una <strong>Especialidad</strong>, y con Nivel Superior marcar <strong>Título de Oro</strong>; con otros niveles esos campos quedan apagados. ' +
             'El <strong>grado científico</strong> es opcional.',
      esperar: function () { return rellenos(['id_nivel_educ']); },
    },
    {
      roles: EDICION, selector: '#id_raza',
      interactivo: true, avanceManual: true, textoEspera: ESPERA_CAMPOS, volver: VOLVER_A_NUEVO,
      titulo: 'Raza',
      texto: 'Elige la <strong>raza</strong>: es obligatoria.',
      esperar: function () { return rellenos(['id_raza']); },
    },
    {
      roles: EDICION, selector: '#id_tpantalon, #id_tcamisa, #id_tzapatos',
      interactivo: true, opcional: true, volver: VOLVER_A_NUEVO,
      titulo: 'Tallas',
      texto: 'Las tallas de <strong>pantalón</strong>, <strong>camisa</strong> y <strong>zapatos</strong> son opcionales, aunque Subsanación las reclama después si faltan.',
    },
    {
      roles: EDICION, selector: FORM + ' button[type="submit"]',
      interactivo: true, volver: VOLVER_A_NUEVO,
      titulo: 'Guardar',
      texto: 'Antes de guardar, mira los colores: <strong>amarillo</strong> es lo que falta, <strong>verde</strong> lo correcto y <strong>rojo</strong> un error que hay que corregir. ' +
             'Pulsa <strong>"Guardar"</strong> y confirma. ¡Al guardarse conseguirás el logro!',
    },
  ];

  function iniciar() {
    window.OrbithRecorrido.iniciar({
      pasos: PASOS.filter(function (p) { return p.roles.indexOf(ROL) !== -1; }),
    });
  }

  // Se lanza desde el menú "¿Cómo funciona?" (`data-recorrido`, ver
  // `orbith_recorrido.js`) y desde "Ir a Aspirantes" en la Guía.
  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['primer_aspirante'] = iniciar;
})();
