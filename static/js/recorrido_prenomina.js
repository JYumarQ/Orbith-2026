/**
 * Recorrido de exportar de Pre-Nómina (tarea `exportar_prenomina`, categoría
 * "Exportar" de la Guía; solo Administrador y Moderador).
 *
 * - `exportar_prenomina:lista`: la lista de Reportes de Pago, sus filtros y
 *   abrir un reporte. Al abrirlo, la guía sigue dentro del reporte.
 * - `exportar_prenomina:reporte`: dentro del reporte, "Exportar" y, al final,
 *   el ciclo exportar → rellenar en Excel → "Importar".
 *
 * Lo cargan templates/pages/prenomina/lista_reportes.html y detalle_reporte.html.
 * Nunca descarga nada por el usuario: señala, explica y espera.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const enLista = !!document.getElementById('resultados_reportes');
  const enReporte = !!document.getElementById('btnExportarReporte');

  // --- Lista: abrir un reporte deja pedida la segunda parte ---
  let pedirReporte = false;
  document.addEventListener('click', function (e) {
    if (!pedirReporte || !e.target.closest) return;
    const abre = e.target.closest('#resultados_reportes a[href], #resultados_reportes tr[data-href]');
    if (abre && window.orbithIniciarGuia) window.orbithIniciarGuia('exportar_prenomina:reporte');
  }, true);

  function hayReportes() {
    return !!document.querySelector('#resultados_reportes .pn-fila-reporte');
  }

  function pasosLista() {
    return [
      {
        selector: '.pn-encabezado',
        titulo: 'Reportes de Pago',
        texto: 'La Pre-Nómina se lleva en <strong>reportes de pago</strong>: uno por Unidad Organizativa y mes, con los pagos de cada trabajador.',
      },
      {
        selector: '#filtros_reportes',
        titulo: 'Buscar un reporte',
        texto: 'Busca por <strong>unidad</strong>, elige el <strong>período</strong> (los meses resaltados tienen algún reporte) o filtra por <strong>estado</strong>.',
      },
      {
        // La tabla y no `#resultados_reportes`: ese contenedor mide 0 de ancho
        // (la tabla se desborda de él) y el recorrido lo daría por invisible.
        // Sin reportes no hay tabla: se señala el aviso de lista vacía.
        selector: function () {
          if (document.querySelector('#resultados_reportes table')) return '#resultados_reportes table';
          const hijo = Array.prototype.find.call(
            document.querySelectorAll('#resultados_reportes > *'),
            function (el) { return el.getBoundingClientRect().width > 2; });
          if (!hijo) return '';
          if (!hijo.id) hijo.id = 'orPrenominaVacio';
          return '#' + hijo.id;
        },
        interactivo: true,
        alEntrar: function () { pedirReporte = true; },
        alSalir: function () { pedirReporte = false; },
        titulo: 'Abre un reporte',
        texto: function () {
          return hayReportes()
            ? 'Haz clic en la fila de un reporte o en su botón <strong>"Abrir el reporte"</strong>: la guía sigue dentro.'
            : 'Todavía no hay reportes con estos filtros. Quita los filtros o crea uno con <strong>"Nuevo reporte"</strong>, y ábrelo.';
        },
        textoEspera: 'Abre un reporte para continuar.',
        // La espera la corta la propia navegación al abrir el reporte.
        esperar: function () { return ''; },
      },
    ];
  }

  // --- Dentro del reporte ---
  let exportado = false;
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#btnExportarReporte')) exportado = true;
  }, true);

  function pasosReporte() {
    return [
      {
        selector: '.pn-encabezado',
        titulo: 'El reporte',
        texto: 'Arriba, la unidad, el período y el estado del reporte; debajo, los datos de su encabezado (horas del mes y firmas) y la rejilla de pagos.',
      },
      {
        selector: '#btnExportarReporte', interactivo: true,
        alEntrar: function () { exportado = false; },
        titulo: 'Exportar',
        texto: 'Pulsa <strong>"Exportar"</strong>: se descarga el Excel con la misma hoja que usa Recursos Humanos, con su encabezado, las horas del mes y las tres firmas.',
        textoEspera: 'Pulsa "Exportar".',
        esperar: function () { return exportado ? 'si' : ''; },
      },
      {
        selector: '#btnImportarReporte, #btnExportarReporte',
        titulo: '¡Logro conseguido!',
        texto: function () {
          return 'Lo encontrarás en tus <strong>descargas</strong>. ' +
            (document.getElementById('btnImportarReporte')
              ? 'Puedes rellenarlo en Excel y volver a subirlo con <strong>"Importar"</strong> en este mismo reporte. ' +
                'Orbith reconoce el archivo: si es de otro reporte o de otro mes, te avisa en vez de mezclar los datos.'
              : 'Quien puede editar el reporte puede rellenarlo en Excel y volver a subirlo con "Importar".');
        },
      },
    ];
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  if (enLista) {
    window.OrbithRecorridos['exportar_prenomina:lista'] = function () {
      window.OrbithRecorrido.iniciar({ pasos: pasosLista() });
    };
  }
  if (enReporte) {
    window.OrbithRecorridos['exportar_prenomina:reporte'] = function () {
      window.OrbithRecorrido.iniciar({ pasos: pasosReporte() });
    };
  }
})();
