/**
 * Recorridos de Subsanación.
 *
 * - `primera_revision_hallazgo:subsanacion` (Administrador y Moderador):
 *   Hallazgos → "Ver detalle" → la explicación → el registro → Estado y
 *   Observación → "Guardar revisión" → historial → Índice de Reglas.
 *
 * - `primer_analisis_subsanacion:subsanacion` (solo Administrador): qué es Subsanación → pestaña
 * "Ejecutar nuevo análisis" → "Analizar la base de datos" y esperar a
 * "Análisis terminado" (el logro) → un paso en Dashboard, otro en Hallazgos y
 * otro en el Índice de Reglas.
 *
 * Lo carga templates/pages/subsanacion/index.html. El análisis solo lee datos.
 */
(function () {
  // Hallazgos la tienen el Administrador y el Moderador; "Ejecutar nuevo
  // análisis", solo el Administrador (ver el registro, al final).
  if (!window.OrbithRecorrido || !document.querySelector('[data-bs-target="#paneHallazgos"]')) return;

  function pestanaActiva(id) {
    const panel = document.getElementById(id);
    return !!panel && panel.classList.contains('active');
  }

  // Pulsa una pestaña (si no está ya abierta) para enseñar su contenido; el
  // clic también hace que HTMX la cargue. Se mira el BOTÓN y no el panel: el
  // botón se marca activo al momento, el panel solo al acabar la animación, y
  // un segundo clic en medio la deshacía.
  function abrirPestana(id) {
    return function () {
      const boton = document.querySelector('[data-bs-target="#' + id + '"]');
      if (boton && !boton.classList.contains('active')) boton.click();
    };
  }

  function analisisEnCurso() {
    return !!document.querySelector('#zonaAnalisis .alert-info .spinner-border');
  }

  function analisisTerminado() {
    return document.querySelector('#zonaAnalisis .sub-paso-hecho .bi-flag-fill') ? 'terminado' : '';
  }

  function pasos() {
    return [
      {
        selector: '.sub-hero',
        titulo: 'Subsanación',
        texto: 'El centro de diagnóstico de los datos: busca inconsistencias (un contrato sin cargo, una fecha imposible…), explica por qué ocurren y te lleva al registro para corregirlas. ' +
          '<strong>Nunca modifica nada por su cuenta.</strong>',
      },
      {
        selector: '[data-bs-target="#paneAnalisis"]', interactivo: true,
        titulo: 'Ejecutar nuevo análisis',
        texto: 'Abre la pestaña <strong>"Ejecutar nuevo análisis"</strong>. Solo la ve el Administrador, porque revisa los datos de toda la empresa.',
        esperar: function () {
          return pestanaActiva('paneAnalisis') && document.getElementById('zonaAnalisis') ? 'abierta' : '';
        },
      },
      {
        selector: '#zonaAnalisis', interactivo: true, paciencia: 3000,
        titulo: 'Analizar la base de datos',
        texto: function () {
          if (analisisEnCurso()) {
            return 'Ya hay un análisis en curso, lanzado antes. Espera a que termine: cuando acabe, recarga la página y vuelve a lanzarlo desde aquí.';
          }
          return 'Pulsa <strong>"Analizar la base de datos"</strong> y <strong>espera sin cambiar de página</strong>: Orbith revisa las categorías una a una y te enseña el avance. ' +
            'Termina cuando aparece <strong>"Análisis terminado"</strong>. ¡Y consigues el logro!';
        },
        textoEspera: 'Espera a que aparezca "Análisis terminado".',
        esperar: analisisTerminado,
      },
      {
        selector: '#zonaAnalisis',
        titulo: 'Análisis terminado',
        texto: 'Arriba tienes el resumen de lo que encontró. Con los botones de debajo vas a los hallazgos o al dashboard; la guía te los enseña ahora.',
      },
      {
        selector: '#paneDashboard',
        preparar: abrirPestana('paneDashboard'),
        alEntrar: abrirPestana('paneDashboard'),
        titulo: 'Dashboard',
        texto: 'La <strong>salud general</strong> de los datos y la salud de cada categoría: cuanto más alta, menos problemas. Así ves de un vistazo dónde conviene empezar.',
      },
      {
        selector: '#paneHallazgos',
        preparar: abrirPestana('paneHallazgos'),
        alEntrar: abrirPestana('paneHallazgos'),
        titulo: 'Hallazgos',
        texto: 'Cada problema encontrado, con su explicación y un acceso al registro para corregirlo. ' +
          'El buscador admite <strong>prefijos</strong>, como <code>N:Juan</code> o <code>COD:CTR</code> (el código de la regla). ' +
          'Revisar uno es otra tarea de la Guía: <strong>"Revisa manualmente tu primer hallazgo"</strong>.',
      },
      {
        selector: '[data-bs-target="#paneReglas"], #paneReglas',
        preparar: abrirPestana('paneReglas'),
        alEntrar: abrirPestana('paneReglas'),
        titulo: 'Índice de Reglas',
        texto: 'Qué comprueba cada regla, por qué suele fallar, qué impacto tiene y <strong>cómo se corrige</strong>. ' +
          'Cada regla con hallazgos abiertos tiene un enlace que te lleva a ellos. Arriba, la ayuda de la búsqueda con prefijos.',
        acciones: [{
          texto: 'Revisar un hallazgo', icono: 'bx-check-shield',
          ejecutar: function () { window.OrbithRecorrido.lanzar('primera_revision_hallazgo:subsanacion'); },
        }],
      },
    ];
  }

  // ------------------------------------------------------------------
  // "Revisa manualmente tu primer hallazgo" (`primera_revision_hallazgo`,
  // Administrador y Moderador): Hallazgos → "Ver detalle" → la explicación →
  // el registro → Estado y Observación → "Guardar revisión" → historial.
  // ------------------------------------------------------------------
  const MODAL = '#contenidoModalHallazgo';

  // Un bloque del detalle por el texto de su título ("¿Qué encontró?"...).
  function bloque(texto, id) {
    const titulo = Array.prototype.find.call(
      document.querySelectorAll(MODAL + ' .sub-guia-titulo, ' + MODAL + ' .sub-panel-title'),
      function (t) { return t.textContent.indexOf(texto) !== -1; });
    if (!titulo) return '';
    const caja = titulo.closest('.sub-guia-bloque, .sub-panel') || titulo.parentElement;
    if (!caja.id) caja.id = id;
    return '#' + caja.id;
  }

  function varios(lista) {
    return function () { return lista.map(function (p) { return bloque(p[0], p[1]); }).filter(Boolean).join(', '); };
  }

  function detalleAbierto() {
    return document.querySelector('#modalHallazgo.show ' + MODAL + ' #estadoHallazgo') ? 'abierto' : '';
  }

  // La revisión se guarda por HTMX y la ventana se vuelve a pintar con el
  // estado nuevo: basta con saber que la petición salió bien.
  let revisionGuardada = false;
  document.body.addEventListener('htmx:afterRequest', function (e) {
    const ruta = (e.detail.pathInfo && e.detail.pathInfo.requestPath) || '';
    if (/\/estado\/?$/.test(ruta) && e.detail.successful) revisionGuardada = true;
  });

  function hayHallazgos() {
    return !!document.querySelector('#paneHallazgos [data-bs-target="#modalHallazgo"]');
  }

  function pasosRevision() {
    return [
      {
        selector: '[data-bs-target="#paneHallazgos"], #paneHallazgos',
        preparar: abrirPestana('paneHallazgos'),
        alEntrar: abrirPestana('paneHallazgos'),
        titulo: 'Hallazgos',
        texto: 'Aquí están los problemas encontrados' +
          (document.querySelector('[data-bs-target="#paneAnalisis"]') ? '.' : ' en <strong>tus unidades</strong>.') +
          ' Acota con el buscador (admite prefijos, como <code>COD:CTR</code>), la Categoría, la Gravedad y el Estado, o marca <strong>"Solo críticos"</strong>.',
      },
      {
        id: 'verDetalle',
        selector: '#paneHallazgos table', interactivo: true,
        titulo: 'Ver detalle',
        texto: function () {
          return hayHallazgos()
            ? 'Pulsa <strong>"Ver detalle"</strong> en un hallazgo.'
            : 'No hay hallazgos con estos filtros. Quita los filtros, o espera al próximo análisis.';
        },
        textoEspera: 'Pulsa "Ver detalle" en un hallazgo.',
        esperar: detalleAbierto,
      },
      {
        selector: function () { return bloque('Qué encontró', 'orHallazgoQue'); },
        volver: { a: 'verDetalle' },
        titulo: '¿Qué encontró?',
        texto: 'Lo que se detectó, con los datos concretos del registro afectado.',
      },
      {
        selector: varios([['Por qué es un problema', 'orHallazgoImpacto'], ['Por qué ocurre', 'orHallazgoCausa'], ['Cómo se corrige', 'orHallazgoSolucion']]),
        volver: { a: 'verDetalle' },
        titulo: 'Por qué importa y cómo se arregla',
        texto: 'Qué consecuencias tiene, por qué suele pasar y, sobre todo, <strong>cómo se corrige</strong>.',
      },
      {
        selector: MODAL + ' a.btn-primary[target="_blank"]', interactivo: true, opcional: true,
        volver: { a: 'verDetalle' },
        titulo: 'Ir al registro',
        texto: 'El botón azul abre el registro <strong>en otra pestaña</strong> para que lo corrijas desde su formulario: Subsanación nunca cambia datos por ti. ' +
          'Al volver aquí, registra la revisión.',
      },
      {
        selector: '#estadoHallazgo, #notaHallazgo', interactivo: true,
        volver: { a: 'verDetalle' },
        titulo: 'Registrar una revisión',
        texto: '<ul class="mb-1 ps-3">' +
          '<li><strong>Pendiente</strong> y <strong>En revisión</strong>: sigue abierto. Si solo quieres probar, <strong>En revisión</strong> deja constancia de que lo estás mirando.</li>' +
          '<li><strong>Corregido</strong>: el próximo análisis lo comprueba; si el problema sigue, lo reabre solo.</li>' +
          '<li><strong>Ignorado</strong> o <strong>Falso positivo</strong>: lo silencian, pero vuelve si el dato cambia. Piden una <strong>Observación</strong> que explique por qué.</li>' +
          '</ul>',
      },
      {
        selector: MODAL + ' form [type="submit"]', interactivo: true, paciencia: 3000,
        volver: { a: 'verDetalle' },
        alEntrar: function () { revisionGuardada = false; },
        titulo: 'Guardar revisión',
        texto: 'Pulsa <strong>"Guardar revisión"</strong>. ¡Y consigues el logro!',
        textoEspera: 'Pulsa "Guardar revisión".',
        esperar: function () { return revisionGuardada ? 'si' : ''; },
      },
      {
        selector: function () { return bloque('Historial', 'orHallazgoHistorial'); },
        titulo: 'Historial de revisiones',
        texto: 'Cada cambio de estado queda aquí, con quién lo hizo, cuándo y su observación, también los automáticos del análisis.',
      },
      {
        selector: '[data-bs-target="#paneReglas"], #paneReglas',
        preparar: function () {
          const modal = document.getElementById('modalHallazgo');
          if (modal && modal.classList.contains('show') && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).hide();
          abrirPestana('paneReglas')();
        },
        alEntrar: function () {
          const modal = document.getElementById('modalHallazgo');
          if (modal && modal.classList.contains('show') && window.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).hide();
          abrirPestana('paneReglas')();
        },
        titulo: 'Índice de Reglas',
        texto: 'Para entender cualquier código de regla: qué comprueba, por qué falla, su impacto y cómo se corrige, con enlace a sus hallazgos abiertos.',
      },
    ];
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  if (document.querySelector('[data-bs-target="#paneAnalisis"]')) {
    window.OrbithRecorridos['primer_analisis_subsanacion:subsanacion'] = function () {
      window.OrbithRecorrido.iniciar({ pasos: pasos() });
    };
  }
  window.OrbithRecorridos['primera_revision_hallazgo:subsanacion'] = function () {
    window.OrbithRecorrido.iniciar({ pasos: pasosRevision() });
  };
})();
