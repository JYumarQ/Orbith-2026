/**
 * Recorrido "Completa tu primer cierre mensual" (`primer_cierre_declarado`,
 * Administrador y Moderador).
 *
 * - `primer_cierre_declarado:gestor`: en el Gestor de Plantilla, elegir la
 *   unidad → revisar sus datos → "Declarar actualizada" (el logro) → "Volver
 *   a Pendiente". Si el botón está apagado (fuera de plazo, ya declarada o
 *   unidad principal), lo explica y sigue igual. Al final ofrece seguir en
 *   Cierres Mensuales.
 * - `primer_cierre_declarado:cierres`: la pantalla Cierres Mensuales (plazo,
 *   cifras, estados, historial y, para el Administrador, "Procesar cierres").
 *
 * Lo cargan templates/pages/plantilla/gestor_plantilla.html y
 * templates/pages/cierres/list_cierres.html.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  // Los mismos días que `cierres/constantes.py` (DIA_INICIO_VENTANA / DIA_FIN_VENTANA).
  const DIA_INICIO = 20;
  const DIA_FIN = 25;

  const enGestor = !!document.getElementById('btn-declarar-unit');
  const enCierres = !!document.getElementById('lista_cierres');

  function iniciar(pasos) {
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  // ------------------------------------------------------------------
  // Gestor de Plantilla
  // ------------------------------------------------------------------
  function unidad() {
    return document.querySelector('#lista-unidades-container .active-unit');
  }

  function botonApagado(id) {
    const b = document.getElementById(id);
    return !b || b.classList.contains('btn-add-disabled');
  }

  // Declaración correcta: el POST de "Declarar actualizada" volvió bien.
  let declarado = false;
  document.body.addEventListener('htmx:afterRequest', function (e) {
    const ruta = (e.detail.pathInfo && e.detail.pathInfo.requestPath) || '';
    if (/\/cierres\/\d+\/declarar\/?$/.test(ruta) && e.detail.successful) declarado = true;
  });

  // Por qué no se puede declarar ahora la unidad elegida.
  function motivoApagado() {
    const u = unidad();
    const dia = new Date().getDate();
    if (u && u.dataset.puedeReabrir === 'true') {
      return 'Esta unidad <strong>ya está declarada</strong> para este mes. Si necesitas corregir algo, usa "Volver a Pendiente" mientras dure el plazo.';
    }
    if (dia < DIA_INICIO || dia > DIA_FIN) {
      return 'Ahora está apagado porque <strong>el plazo está cerrado</strong>: se declara del día <strong>' + DIA_INICIO + ' al ' + DIA_FIN +
        '</strong> de cada mes. Vuelve entonces para conseguir el logro.';
    }
    return 'Ahora está apagado: esta unidad no se puede declarar (no está entre las tuyas, o le queda un mes anterior por declarar).';
  }

  function pasosGestor() {
    const seleccion = window.OrbithPasosSeleccionGestor ? window.OrbithPasosSeleccionGestor().slice(0, 1) : [];
    seleccion.forEach(function (paso) {
      paso.texto = 'Elige la unidad que vas a declarar. Si es una Unidad Principal, despliega sus subunidades con la flecha (o con doble clic) y elige una: ' +
        'las principales no se declaran, su estado sale del de sus subunidades.';
      paso.saltarSi = function () { const u = unidad(); return !!u && u.dataset.esPrincipal !== 'true'; };
    });
    return seleccion.concat([
      {
        selector: '#col-panel-dept, #col-panel-cargo, #col-panel-contrato',
        titulo: 'Revisa antes de declarar',
        texto: 'Al declarar, Orbith guarda una <strong>fotografía</strong> de la unidad tal como está: sus departamentos, cargos y contratos. ' +
          'Esa fotografía es la que leen los informes de ese mes, así que comprueba que todo esté al día.',
      },
      {
        selector: '#btn-declarar-unit', interactivo: true, paciencia: 3000,
        alEntrar: function () { declarado = false; },
        titulo: 'Declarar actualizada',
        texto: function () {
          if (declarado) return '¡Declarada!';
          return botonApagado('btn-declarar-unit')
            ? 'El botón verde del calendario, <strong>"Declarar actualizada"</strong>, cierra el mes de la unidad. ' + motivoApagado()
            : 'Pulsa el botón verde del calendario, <strong>"Declarar actualizada"</strong>, y confirma. ¡Y consigues el logro!';
        },
        textoEspera: 'Pulsa "Declarar actualizada" y confirma.',
        // Apagado, no hay nada que esperar: el paso se puede pasar con "Siguiente".
        esperar: function () {
          if (declarado) return 'declarado';
          return botonApagado('btn-declarar-unit') ? 'apagado' : '';
        },
      },
      {
        selector: '#btn-reabrir-unit, #btn-declarar-unit',
        titulo: 'Si te equivocas',
        texto: function () {
          return (declarado ? '<strong>¡Logro conseguido!</strong> ' : '') +
            'El botón amarillo, <strong>"Volver a Pendiente"</strong>, descarta la fotografía para corregir los datos y volver a declarar, mientras dure el plazo. ' +
            'Los cambios que hagas una vez cerrado el plazo cuentan para el mes siguiente.';
        },
        acciones: [{
          texto: 'Ver Cierres Mensuales', icono: 'bx-calendar-check',
          ejecutar: function () { window.OrbithRecorrido.continuarEn('/cierres/', 'primer_cierre_declarado:cierres'); },
        }],
      },
    ]);
  }

  // ------------------------------------------------------------------
  // Cierres Mensuales
  // ------------------------------------------------------------------
  function filaDe(selector, id) {
    const el = document.querySelector(selector);
    const fila = el && el.closest('.row');
    if (!fila) return '';
    if (!fila.id) fila.id = id;
    return '#' + fila.id;
  }

  function pasosCierres() {
    return [
      {
        selector: '.inf-hero',
        titulo: 'Cierres Mensuales',
        texto: 'Cada mes, del día <strong>' + DIA_INICIO + ' al ' + DIA_FIN + '</strong>, cada unidad declara su plantilla al día. ' +
          'Arriba a la derecha ves si el plazo está abierto ahora.',
      },
      {
        selector: function () { return filaDe('.inf-kpi', 'orCierresCifras'); },
        titulo: 'Cifras',
        texto: 'Cuántas unidades hay, cuántas están <strong>actualizadas</strong>, cuántas <strong>desactualizadas</strong> (dejaron pasar su plazo) y cuántas no se han declarado nunca.',
      },
      {
        selector: '#search_container, #filter_estado, #lista_cierres',
        titulo: 'Estado por unidad',
        texto: 'Busca una unidad o filtra por estado. El botón de cada fila abre su <strong>historial</strong>: las fotografías de cada mes.',
      },
      {
        // Solo el Administrador tiene este botón: para los demás, se salta.
        selector: '#btn-procesar',
        titulo: 'Procesar cierres',
        texto: 'Marca como <strong>desactualizadas</strong> las unidades que no declararon a tiempo. Es manual a propósito: nadie quiere que el servidor lo decida por su cuenta.',
      },
    ];
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  if (enGestor) window.OrbithRecorridos['primer_cierre_declarado:gestor'] = function () { iniciar(pasosGestor()); };
  if (enCierres) window.OrbithRecorridos['primer_cierre_declarado:cierres'] = function () { iniciar(pasosCierres()); };
})();
