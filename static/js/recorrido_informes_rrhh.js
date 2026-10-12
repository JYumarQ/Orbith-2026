/**
 * Informes RRHH: explicación de cada informe y recorrido guiado.
 *
 * Lo carga la barra común de los siete informes
 * (templates/pages/informes/partials/toolbar_informes.html).
 *
 * - AYUDA: qué muestra cada informe. Es la fuente única del botón "?" junto
 *   al selector de informe (un globo de texto) y del paso "El informe" del
 *   recorrido. La clave es el `url_name` de la vista.
 * - Recorrido `primer_informe_rrhh:informes`: la barra común (período, unidad,
 *   selector de informe) y el informe abierto, con un paso extra en los que
 *   tienen filtros propios. Si el usuario cambia de informe en el selector,
 *   la página se recarga y el recorrido sigue en el nuevo con la clave
 *   `primer_informe_rrhh:actual`.
 *
 * - Recorrido `exportar_informes_rrhh:informes` (categoría "Exportar"):
 *   acompaña hasta tener PDF, Word y Excel (ver recorrido_exportar.js). Cuenta
 *   cualquiera de los siete informes.
 *
 * La tarea "Consulta los Informes RRHH" se completa con solo abrir un informe
 * (informes/views.py::GuiaInformeRRHHMixin): ese recorrido enseña, no espera.
 */
(function () {
  const AYUDA = {
    informe_economia: {
      titulo: 'Consolidado de la Fuerza de Trabajo',
      texto: 'Resume la plantilla por categoría ocupacional (Obreros, Técnicos, Cuadros, Servicios y Administrativos):' +
        '<ul class="mb-1 mt-1 ps-3">' +
        '<li><strong>Plantilla</strong>: plazas aprobadas, cubiertas y vacantes de la plantilla aprobada, y cuántas mujeres tienen contrato indeterminado.</li>' +
        '<li><strong>Determinado</strong> y <strong>Adiestramiento</strong>: trabajadores con esos tipos de contrato, y cuántas son mujeres.</li>' +
        '<li><strong>Total</strong>: cubiertas + determinados + adiestrados.</li>' +
        '</ul>' +
        'Las plazas fuera de la plantilla aprobada no suman en Plantilla, pero sus trabajadores sí cuentan.',
    },
    informe_trabajadores_ueb: {
      titulo: 'Trabajadores por UEB',
      texto: 'Cuántos trabajadores activos tiene cada unidad y cuántas son mujeres, con el porcentaje que representa sobre el total. ' +
        'Una Unidad Principal suma los de sus subunidades. Arriba: el total, las mujeres, cuántas unidades tienen personal y cuál tiene la mayor plantilla.',
    },
    informe_puestos_clave: {
      titulo: 'Resumen Puestos Clave',
      texto: 'Los cargos de la familia elegida (por defecto, los <strong>Puestos Clave</strong>) con su plantilla aprobada, cubierta y vacante, ' +
        'y la <strong>Eficiencia</strong>: el porcentaje de plazas cubiertas. También cuántos contratos determinados, mujeres y adiestrados tiene cada cargo. ' +
        'Con el filtro de familia puedes ver cualquier otro tipo de familia de cargos.',
    },
    informe_misiones: {
      titulo: 'Misiones Internacionales',
      texto: 'Los trabajadores que están cumpliendo misión internacional, agrupados por unidad, con su país, categoría ocupacional y grupo escala. ' +
        '<strong>Días</strong> es el tiempo que estará de misión e <strong>Importe</strong>, su pago. Arriba: el total en misión, el importe total y cuántos hay de cada categoría.',
    },
    informe_registro_diario: {
      titulo: 'Registro Diario por Trabajadores',
      texto: 'Los trabajadores por categoría ocupacional y cuántas son mujeres.' +
        '<ul class="mb-1 mt-1 ps-3">' +
        '<li><strong>Deducciones</strong>: obligaciones estatales y sociales, subsidios, licencias de maternidad y licencias sin sueldo.</li>' +
        '<li><strong>Promedio de Trabajadores</strong>: el total de trabajadores físicos menos las deducciones. Quienes están en misión no se restan.</li>' +
        '<li><strong>Eficiencia del Plan</strong>: compara el Promedio (Real) con el Plan del mes. Quien puede editar cambia el Plan con doble clic sobre su cifra.</li>' +
        '</ul>' +
        'Los gráficos muestran la plantilla física por categoría y por sexo.',
    },
    informe_motivos_contrato: {
      titulo: 'Contratos Determinados',
      texto: 'Los contratos por tiempo determinado, agrupados por tipo de contrato, motivo y unidad, con su fecha de alta, duración, días que le quedan y fecha de renovación. ' +
        'Arriba, el resumen por sexo, por categoría y por motivo.' +
        '<ul class="mb-1 mt-1 ps-3">' +
        '<li><strong>Vigente</strong>: le quedan más de 30 días.</li>' +
        '<li><strong>Advertencia</strong>: 30 días o menos.</li>' +
        '<li><strong>Crítica</strong>: 15 días o menos. Si los días salen en negativo, el contrato ya venció.</li>' +
        '</ul>',
    },
    informe_altas_bajas: {
      titulo: 'Altas y Bajas del Mes',
      texto: 'Quién entró y quién salió en un mes, en el formato que pide la UNE. Arriba: altas, bajas, mujeres y el saldo del mes (altas menos bajas). ' +
        'Debajo, el resumen por provincia y municipio (puestos clave y no clave) y el listado de cada alta y cada baja. ' +
        'Por defecto muestra el <strong>mes anterior</strong>. En las bajas, <strong>SPxR</strong> indica si cobró el sistema de pago y <strong>Comp. Cargo</strong>, si se completa el cargo. ' +
        'El Excel trae las cuatro hojas del modelo, listo para enviar.',
    },
  };

  // Filtros propios de algunos informes: un paso más en el recorrido.
  const FILTROS_PROPIOS = {
    informe_puestos_clave: {
      selector: '#form-filtros',
      texto: 'El filtro de familia cambia qué cargos se ven: los <strong>Puestos Clave</strong> o cualquier tipo de familia de cargos. ' +
        '<strong>Desglosado</strong> reparte los cargos por unidad; <strong>Consolidado</strong> los junta todos sumando todas las unidades.',
    },
    informe_motivos_contrato: {
      selector: '#searchInput, #filtrosMotivos',
      texto: 'Busca por expediente o nombre, y filtra por <strong>Alertas</strong> (cuánto le queda al contrato) y por <strong>Categoría</strong> ocupacional. ' +
        '<strong>Desglosado</strong> agrupa por tipo, motivo y unidad; <strong>Consolidado</strong> lo pone todo en una sola tabla, cómoda para buscar y llevarse la lista.',
    },
  };

  const boton = document.getElementById('btnAyudaInforme');
  const informe = boton ? boton.dataset.informe : '';
  const ayuda = AYUDA[informe];

  // --- Botón "?" junto al selector de informe ---
  document.addEventListener('DOMContentLoaded', function () {
    if (!boton || !ayuda || !window.bootstrap) return;
    // El HTML son textos fijos de este archivo, nunca datos del usuario.
    new bootstrap.Popover(boton, {
      title: ayuda.titulo,
      content: ayuda.texto,
      html: true,
      trigger: 'focus',
      placement: 'bottom',
      customClass: 'informe-rrhh-popover',
    });
  });

  // --- Recorrido ---
  if (!window.OrbithRecorrido || !ayuda) return;

  const esAltasBajas = informe === 'informe_altas_bajas';

  // Lo que hay debajo de la barra común: el principio del informe.
  function principioDelInforme() {
    let el = document.querySelector('.toolbar-card');
    while (el && (el = el.nextElementSibling)) {
      if (/^(SCRIPT|STYLE)$/.test(el.tagName) || el.classList.contains('alert')) continue;
      if (el.offsetHeight) {
        if (!el.id) el.id = 'orRecorridoInforme';
        return '#' + el.id;
      }
    }
    return '';
  }

  function pasosDelInforme() {
    const pasos = [
      {
        selector: principioDelInforme,
        titulo: ayuda.titulo,
        texto: ayuda.texto,
      },
    ];
    const filtros = FILTROS_PROPIOS[informe];
    if (filtros) {
      pasos.push({ selector: filtros.selector, titulo: 'Filtros de este informe', texto: filtros.texto });
    }
    pasos.push({
      selector: '.toolbar-card .btn-export',
      titulo: 'Exportar',
      texto: 'Los botones <strong>PDF</strong>, <strong>Word</strong> y <strong>Excel</strong> descargan el informe tal como lo ves: con el mismo período y las mismas unidades. ' +
        '"¿Cómo funciona?" → "Exportar este informe" te acompaña.',
    });
    return pasos;
  }

  // Si cambia de informe durante el paso del selector, deja pedida la
  // continuación: la propia barra navega al informe elegido.
  function alCambiarInforme() {
    if (this.value && this.value !== window.location.pathname && window.orbithIniciarGuia) {
      window.orbithIniciarGuia('primer_informe_rrhh:actual');
    }
  }

  function pasosCompletos() {
    return [
      {
        selector: '.toolbar-card h4',
        titulo: 'Informes RRHH',
        texto: 'Son siete informes sobre la plantilla. Todos comparten esta barra: el período, la unidad, el informe que ves y los botones de exportar.',
      },
      {
        selector: '#caja_periodo_informes',
        titulo: esAltasBajas ? 'Mes de los movimientos' : 'Período',
        texto: esAltasBajas
          ? 'En este informe eliges el <strong>mes</strong> de las altas y las bajas. Los meses resaltados tuvieron movimientos; los demás se pueden consultar igual y dirán cero.'
          : 'Con <strong>"Información actual"</strong> ves los datos de hoy. Si eliges un mes cerrado, ves la <strong>fotografía</strong> de su cierre mensual: la plantilla tal como estaba. ' +
            'El período se conserva al cambiar de informe.',
      },
      {
        selector: '#filtro_unidades_informes',
        titulo: 'Unidad Organizativa',
        texto: 'Limita el informe a las unidades que elijas. Una Unidad Principal incluye sus subunidades. Sin nada elegido, entra todo lo que tu rol te permite ver.',
      },
      {
        selector: '#selector-informes, #btnAyudaInforme', interactivo: true, opcional: true,
        alEntrar: function () { if (window.jQuery) window.jQuery('#selector-informes').on('change.orRecorrido', alCambiarInforme); },
        alSalir: function () { if (window.jQuery) window.jQuery('#selector-informes').off('change.orRecorrido'); },
        titulo: 'Elegir informe',
        texto: 'Aquí cambias de informe. Si eliges otro, la guía sigue en él. ' +
          'El botón <strong>"?"</strong> de al lado explica, en cualquier momento, qué muestra el informe que tienes abierto.',
      },
    ].concat(pasosDelInforme());
  }

  // El globo del "?" no debe quedar abierto debajo del recorrido.
  function iniciar(pasos) {
    const globo = window.bootstrap && bootstrap.Popover.getInstance(boton);
    if (globo) globo.hide();
    window.OrbithRecorrido.iniciar({ pasos: pasos });
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['primer_informe_rrhh:informes'] = function () { iniciar(pasosCompletos()); };
  window.OrbithRecorridos['primer_informe_rrhh:actual'] = function () { iniciar(pasosDelInforme()); };

  // --- Exportar este informe ---
  const guiaExportar = window.OrbithGuiaExportar ? window.OrbithGuiaExportar({
    codigo: 'exportar_informes_rrhh',
    selector: '.toolbar-card .btn-export',
    explicacion: 'Estos botones descargan el informe tal como lo ves, con el mismo período y las mismas unidades. ' +
      'Cuenta cualquiera de los siete informes: puedes hacer el PDF en este y el Word en otro.',
  }) : null;
  // Cada botón descarga navegando a su URL (la página no cambia): basta con
  // saber cuál se pulsó.
  document.addEventListener('click', function (e) {
    const b = e.target.closest && e.target.closest('.toolbar-card .btn-export');
    if (!b || !guiaExportar) return;
    const formato = b.classList.contains('btn-pdf') ? 'pdf' : b.classList.contains('btn-word') ? 'word' : 'excel';
    guiaExportar.marcar(formato);
  }, true);
  window.OrbithRecorridos['exportar_informes_rrhh:informes'] = function () {
    const globo = window.bootstrap && bootstrap.Popover.getInstance(boton);
    if (globo) globo.hide();
    if (guiaExportar) guiaExportar.iniciar();
  };
})();
