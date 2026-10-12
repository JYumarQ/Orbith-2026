/**
 * Recorrido "Buscar con prefijos" (tarea `primera_busqueda_prefijos`).
 *
 * Sirve en cualquier pantalla con un buscador `input[data-prefijos]`
 * (Aspirantes, Bajas, Contratos y Subsanación; ver static/js/busqueda_prefijos.js).
 * Se registra como `primera_busqueda_prefijos:<pantalla>`. La tarea la completa
 * el servidor al recibir la búsqueda (progreso.middleware.busco_con_prefijo).
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const EJEMPLOS = {
    E: 'E:8855', N: 'N:Juan', CI: 'CI:850101', CA: 'CA:ayudante', U: 'U:flor', COD: 'COD:CTR',
  };
  const NOMBRES = {
    E: 'expediente', N: 'nombre y apellidos', CI: 'carnet (vale el principio)', CA: 'cargo',
    U: 'unidad (vale parte del nombre)', COD: 'código de regla',
  };

  function buscador() { return document.querySelector('input[data-prefijos]'); }

  function validos() {
    const b = buscador();
    return b ? b.dataset.prefijos.split(',').map(function (s) { return s.trim().toUpperCase(); }) : [];
  }

  // El grupo del buscador: el campo y el botón "?" que le añade busqueda_prefijos.js.
  function grupo() {
    const b = buscador();
    if (!b) return '';
    const g = b.closest('.input-group') || b.parentElement;
    if (!g.id) g.id = 'orGrupoBuscador';
    return '#' + g.id;
  }

  function usaPrefijo() {
    const b = buscador();
    if (!b) return '';
    const escritos = (b.value.match(/(?:^|\s)(COD|CI|CA|E|N|U):\s*\S/gi) || [])
      .map(function (m) { return m.trim().split(':')[0].toUpperCase(); });
    return escritos.some(function (p) { return validos().indexOf(p) !== -1; }) ? 'si' : '';
  }

  function pasos(alEntrarBuscador) {
    return [
      {
        selector: grupo, interactivo: true, avanceManual: true,
        alEntrar: alEntrarBuscador,
        titulo: 'Buscar con prefijos',
        texto: function () {
          const lista = validos().map(function (p) {
            return '<li><strong>' + p + ':</strong> ' + NOMBRES[p] + ' <code>' + EJEMPLOS[p] + '</code></li>';
          }).join('');
          return 'Además de buscar como siempre, puedes buscar en un dato concreto con un <strong>prefijo</strong>. Aquí valen:' +
            '<ul class="mb-1 mt-1 ps-3">' + lista + '</ul>' +
            'Escribe uno, por ejemplo <code>' + EJEMPLOS[validos()[0]] + '</code>. El botón <strong>"?"</strong> del buscador lo recuerda.';
        },
        textoEspera: 'Escribe una búsqueda con un prefijo.',
        esperar: usaPrefijo,
      },
      {
        selector: grupo,
        titulo: '¡Logro conseguido!',
        texto: 'Se pueden <strong>combinar</strong>: <code>N:Juan U:Florida</code>. Cada prefijo abarca hasta el siguiente, ' +
          'y lo escrito antes del primero se busca como siempre. Da igual mayúsculas o acentos.',
      },
    ];
  }

  // En Subsanación el buscador está en la pestaña Hallazgos, que se carga al abrirla.
  function abrirHallazgos() {
    const boton = document.querySelector('[data-bs-target="#paneHallazgos"]');
    if (boton && !boton.classList.contains('active')) boton.click();
  }

  const CLAVES = { 'Aspirantes': 'aspirantes', 'Bajas': 'bajas', 'Contratos': 'contratos', 'Subsanación': 'subsanacion' };
  window.OrbithRecorridos = window.OrbithRecorridos || {};

  function registrar(pantalla, alEntrar) {
    window.OrbithRecorridos['primera_busqueda_prefijos:' + CLAVES[pantalla]] = function () {
      if (alEntrar) {
        alEntrar();
        // Espera a que HTMX traiga la pestaña con su buscador.
        let intentos = 0;
        const esperar = setInterval(function () {
          if (buscador() || ++intentos > 20) {
            clearInterval(esperar);
            window.OrbithRecorrido.iniciar({ pasos: pasos(alEntrar) });
          }
        }, 150);
        return;
      }
      window.OrbithRecorrido.iniciar({ pasos: pasos() });
    };
  }

  if (document.querySelector('[data-bs-target="#paneHallazgos"]')) {
    registrar('Subsanación', abrirHallazgos);
  } else {
    const b = buscador();
    if (b && CLAVES[b.dataset.pantalla]) registrar(b.dataset.pantalla);
  }
})();
