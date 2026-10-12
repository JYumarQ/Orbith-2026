/**
 * Anexos 14, 14A y 14B: explicación de cada anexo y recorrido guiado.
 *
 * Lo carga templates/pages/informes_anexo/partials/ayuda_recorrido_anexo.html,
 * incluido en la cabecera de los tres anexos.
 *
 * - AYUDA: qué es cada anexo. Lo usan el botón "?" (un globo) y el primer paso
 *   del recorrido.
 * - Recorrido `exportar_anexos:anexo14|anexo14a|anexo14b`: la pantalla entera
 *   (cabecera, cifras, filtros de cargo en el 14, unidades y pestañas, firmas)
 *   y la exportación. La tarea de la Guía pide exportar los TRES anexos (el
 *   libro combinado cuenta para el 14 y el 14A): al exportar, marca el avance y
 *   ofrece seguir en el anexo que falte.
 *
 * Nunca descarga nada por el usuario: señala, explica y espera.
 */
(function () {
  const AYUDA = {
    '14': {
      titulo: 'Anexo 14',
      texto: 'El <strong>detalle</strong> de la plantilla aprobada: una fila por cargo, con su rol, nivel de preparación, grupo escala y plazas, ' +
        'ordenado por unidad, dirección y departamento. Es el modelo oficial que se entrega al organismo junto con el 14A. ' +
        'Su Excel trae portada, resumen y una hoja por unidad.',
    },
    '14a': {
      titulo: 'Anexo 14A',
      texto: 'El <strong>conteo</strong> de la plantilla: cuántas plazas hay por categoría ocupacional, sin nombrar los cargos. ' +
        'El Resumen tiene una fila por unidad; cada pestaña desglosa sus direcciones y departamentos con subtotales. ' +
        'Las plazas fuera de la plantilla aprobada se cuentan aparte. Se entrega junto con el 14.',
    },
    '14b': {
      titulo: 'Anexo 14B',
      texto: '<strong>Quién ocupa cada plaza</strong> aprobada y cuánto cobra: nombre, carné, formación y el salario desglosado. ' +
        'Hay una fila por plaza, así que las vacantes salen con su cargo y el salario en cero. ' +
        'Quienes cobran sin ocupar plaza aprobada van aparte (Adiestrados y Contratados). Su Excel va en un libro propio.',
    },
  };
  const ETIQUETA = { '14': 'Anexo 14', '14a': 'Anexo 14A', '14b': 'Anexo 14B' };
  const URL_ANEXO = { '14': '/informes-anexo/anexo14/', '14a': '/informes-anexo/anexo14a/', '14b': '/informes-anexo/anexo14b/' };

  const boton = document.getElementById('btnAyudaAnexo');
  const anexo = boton ? boton.dataset.anexo : '';
  const ayuda = AYUDA[anexo];

  // --- Botón "?" ---
  document.addEventListener('DOMContentLoaded', function () {
    if (!boton || !ayuda || !window.bootstrap) return;
    // El HTML son textos fijos de este archivo, nunca datos del usuario.
    new bootstrap.Popover(boton, {
      title: ayuda.titulo, content: ayuda.texto, html: true,
      trigger: 'focus', placement: 'bottom', customClass: 'anexo-popover',
    });
  });

  if (!window.OrbithRecorrido || !ayuda) return;

  // El panel que contiene a `elemento`, con un id para poder señalarlo. En el
  // 14A las tarjetas de cifras van en una fila suelta, sin panel: vale la fila.
  function panelDe(elemento, id) {
    const panel = elemento && (elemento.closest('.anx-panel') || elemento.closest('.row'));
    if (!panel) return '';
    if (!panel.id) panel.id = id;
    return '#' + panel.id;
  }

  // --- Avance de la tarea (✔ 14 ○ 14A ○ 14B) ---
  const hechas = new Set();
  let exportado = false;

  function faltan() {
    return ['14', '14a', '14b'].filter(function (a) { return !hechas.has(a); });
  }

  function estado() {
    return '<div class="d-flex gap-2 my-2">' + ['14', '14a', '14b'].map(function (a) {
      const hecho = hechas.has(a);
      return '<span class="badge ' + (hecho ? 'bg-label-success' : 'bg-label-secondary') + '">' +
        (hecho ? '✔ ' : '') + ETIQUETA[a] + '</span>';
    }).join('') + '</div>';
  }

  // Qué anexos cuenta cada botón de exportar. El del Anexo 14 con filtros de
  // cargo puestos no descarga: abre una ventana que pregunta qué bajar, y son
  // las opciones de esa ventana las que cuentan.
  document.addEventListener('click', function (e) {
    const b = e.target.closest && e.target.closest('.anx-btn-export');
    if (!b) return;
    if (b.dataset.filtrosActivos === '1' && !b.closest('#modalFiltrosExport')) return;
    const combinado = b.classList.contains('anx-btn-export--combinado') && !b.closest('#modalFiltrosExport');
    (combinado ? ['14', '14a'] : [anexo]).forEach(function (a) { hechas.add(a); });
    exportado = true;
  }, true);

  function pasoExportar() {
    const conCombinado = anexo !== '14b';
    return {
      selector: '#accionesExportAnexo14', interactivo: true,
      alEntrar: function () { exportado = false; },
      titulo: 'Exportar a Excel',
      texto: function () {
        return (conCombinado
          ? '<strong>"Solo ' + ETIQUETA[anexo] + '"</strong> descarga este anexo. <strong>"Anexo 14 y 14A"</strong> descarga los dos en un mismo libro: ' +
            'es el fichero que se entrega al organismo, y es un <strong>atajo</strong> porque cuenta para los dos anexos de la tarea. '
          : 'El 14B se descarga en su propio libro. ') +
          (anexo === '14' ? 'Si tienes filtros de cargo puestos, Orbith te pregunta si quieres la plantilla completa o lo que estás viendo. ' : '') +
          'La tarea de la Guía pide los tres anexos:' + estado() + 'Pulsa uno de los botones.';
      },
      textoEspera: 'Pulsa un botón de exportar.',
      esperar: function () { return exportado ? 'si' : ''; },
      paciencia: 3000,
    };
  }

  function pasoFinal() {
    const pendientes = faltan();
    const paso = {
      selector: '#accionesExportAnexo14',
      titulo: pendientes.length ? 'Excel en camino' : '¡Logro conseguido!',
      texto: estado() + (pendientes.length
        ? 'Lo encontrarás en tus <strong>descargas</strong>. Para el logro te ' + (pendientes.length > 1 ? 'faltan ' : 'falta el ') +
          pendientes.map(function (a) { return '<strong>' + ETIQUETA[a] + '</strong>'; }).join(' y ') + '.'
        : 'Exportaste los Anexos 14, 14A y 14B. Los encontrarás en tus <strong>descargas</strong>.'),
    };
    if (pendientes.length) {
      paso.acciones = pendientes.map(function (a) {
        return {
          texto: 'Seguir en el ' + ETIQUETA[a], icono: 'bx-right-arrow-alt',
          ejecutar: function () { window.OrbithRecorrido.continuarEn(URL_ANEXO[a], 'exportar_anexos:anexo' + a); },
        };
      });
    }
    return paso;
  }

  function pasos() {
    return [
      {
        selector: '.inf-hero',
        titulo: ayuda.titulo,
        texto: ayuda.texto + ' El botón <strong>"?"</strong> junto al título lo recuerda en cualquier momento.',
      },
      {
        selector: function () { return panelDe(document.querySelector('.anx-meta-card'), 'orAnexoDatos'); },
        titulo: 'Datos de la entidad',
        texto: 'Empresa, organismo y REUP salen de <strong>Parámetros Generales</strong>; provincia y municipio, de la unidad. Son los mismos que encabezan el Excel.',
      },
      {
        selector: function () { return panelDe(document.querySelector('.inf-kpi'), 'orAnexoCifras'); },
        titulo: 'Cifras',
        texto: 'El total de plazas aprobadas y su reparto por categoría ocupacional.' +
          (anexo === '14' ? ' La tarjeta "Unidades" dice cuántas entran en el informe.' : ''),
      },
      {
        selector: function () {
          return panelDe(document.querySelector('#formFiltrosAnexo14 button[type="submit"]'), 'orAnexoFiltros');
        },
        interactivo: true, opcional: true,
        titulo: 'Filtros de cargo',
        texto: 'Busca un cargo por su nombre o acota por <strong>categoría ocupacional</strong> o <strong>rol estructural</strong>, y pulsa "Filtrar". ' +
          'La flecha circular los quita. Solo cambian lo que ves: el documento oficial es la plantilla completa.',
      },
      {
        selector: function () { return panelDe(document.getElementById('filtro_unidades_anexo'), 'orAnexoUnidades'); },
        titulo: 'Unidades y pestañas',
        texto: 'Arriba eliges <strong>sobre qué unidades</strong> va el anexo; sin nada marcado entra todo tu alcance. ' +
          'Debajo, <strong>una pestaña por unidad</strong>: se carga al pulsarla.' +
          (anexo === '14b' ? '' : ' La de Resumen es la primera que se mira.'),
      },
      {
        selector: '#bloqueFirmasAnexo14', interactivo: true, opcional: true,
        titulo: 'Firmas',
        texto: 'El <strong>Director de Capital Humano</strong> propone y el <strong>Director General</strong> aprueba. ' +
          'Si Orbith no los encuentra por su cargo, elígelos a mano: sus nombres salen en el Excel.',
      },
      pasoExportar(),
      // Se construye al llegar, con el avance ya actualizado.
      {
        selector: '#accionesExportAnexo14',
        titulo: 'Excel en camino',
        texto: function () { return pasoFinal().texto; },
        alEntrar: function () {
          const final = pasoFinal();
          this.titulo = final.titulo;
          this.acciones = final.acciones;
        },
      },
    ];
  }

  function iniciar() {
    const globo = window.bootstrap && bootstrap.Popover.getInstance(boton);
    if (globo) globo.hide();
    hechas.clear();
    fetch('/progreso/tarea/exportar_anexos/partes/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }, cache: 'no-store',
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (datos) { (datos.partes || []).forEach(function (p) { if (p.hecha) hechas.add(p.clave); }); })
      .catch(function () {})
      .then(function () { window.OrbithRecorrido.iniciar({ pasos: pasos() }); });
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['exportar_anexos:anexo' + anexo] = iniciar;
})();
