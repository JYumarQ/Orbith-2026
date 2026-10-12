/**
 * Recorridos visuales del Informe Inteligente.
 *
 * - Generar un informe (`primer_informe_generado`): tipo de datos → campos →
 *   "Generar informe", con paradas que solo explican (fecha del informe,
 *   unidad, desglose y tarjetas, orden) y una opcional donde se puede actuar
 *   (filtros). Termina explicando el resumen, la tabla y la Evolución mensual,
 *   y ofrece seguir con exportar o con guardar como favorito.
 * - Exportar (`exportar_informe_inteligente`, categoría "Exportar"): acompaña
 *   hasta tener PDF, Word y Excel (ver recorrido_exportar.js).
 * - Guardar como favorito (`primer_informe_favorito`): guardar y, tras la
 *   recarga que hace la pantalla al guardar, recorrer "Mis favoritos e
 *   historial" (clave `primer_informe_favorito:panel`).
 *
 * Exportar y Favoritos necesitan un informe en pantalla: si no lo hay,
 * empiezan con unos pasos cortos para generarlo (`pasosRapidos`).
 */
(function () {
  if (!window.OrbithRecorrido || !document.getElementById('btnGenerarVistaPrevia')) return;

  function camposMarcados() {
    return document.querySelectorAll('#panelCamposContainer .campo-checkbox:checked').length;
  }

  // Despliega un panel plegable de Bootstrap y recuerda si estaba plegado,
  // para dejarlo como estaba al salir del paso.
  function desplegable(id) {
    let estabaPlegado = false;
    return {
      abrir: function () {
        const el = document.getElementById(id);
        if (!el || !window.bootstrap) return;
        estabaPlegado = !el.classList.contains('show');
        if (estabaPlegado) bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).show();
      },
      restaurar: function () {
        const el = document.getElementById(id);
        if (!el || !window.bootstrap || !estabaPlegado) return;
        // Si el usuario añadió filtros o ya tenía un orden, se queda abierto.
        const enUso = id === 'panelFiltros'
          ? !!el.querySelector('.ii-filter-row')
          : !!(document.getElementById('selectOrdenarPor') || {}).value;
        if (!enUso) bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).hide();
      },
    };
  }

  const panelCampos = desplegable('panelCampos');
  const panelFiltros = desplegable('panelFiltros');
  const panelOrden = desplegable('panelOrden');

  // Al generar, el fragmento de resultados se reemplaza entero. Se marca el
  // resumen que hubiera en pantalla al llegar al paso (de una sesión anterior)
  // para que el paso solo avance con uno NUEVO.
  function marcarResultadosViejos() {
    const viejo = document.querySelector('#resultadosContainer .ii-resumen');
    if (viejo) viejo.dataset.orRecorridoViejo = '1';
  }

  function informeNuevo() {
    return document.querySelector('#resultadosContainer .ii-resumen:not([data-or-recorrido-viejo])') ? 'generado' : '';
  }

  function totalRegistros() {
    const el = document.querySelector('#resultadosContainer [data-total-registros]');
    return el ? Number(el.dataset.totalRegistros) : 0;
  }

  // Hay un informe con filas en pantalla: los botones de exportar solo salen
  // entonces, y "Guardar como favorito" se enciende al generar.
  function hayInforme() {
    return !!document.querySelector('#resultadosContainer .ii-btn-export');
  }

  // Aviso de informe_inteligente.js al guardar un favorito nuevo. El de cada
  // exportación (`ii:exportacion`) lo escucha la guía de exportar, más abajo.
  let favoritoGuardado = false;
  let recorridoFavoritoActivo = false;
  document.addEventListener('ii:favorito-guardado', function () {
    favoritoGuardado = true;
    // La pantalla se recarga enseguida para pintar el favorito en la lista:
    // se deja pedida la segunda parte, que progreso_guia.js lanza al cargar.
    if (recorridoFavoritoActivo && window.OrbithRecorrido.activo() && window.orbithIniciarGuia) {
      window.orbithIniciarGuia('primer_informe_favorito:panel');
      // Sin esto, el navegador devuelve la página tras la recarga a la altura
      // del botón "Guardar informe" cuando ya se ha señalado el botón de
      // favoritos de arriba, que queda fuera de la vista.
      try { history.scrollRestoration = 'manual'; } catch (e) { /* no crítico */ }
    }
  });

  function iniciar(pasos, alTerminar) {
    window.OrbithRecorrido.iniciar({ pasos: pasos, alTerminar: alTerminar });
  }

  // Pasos cortos para tener un informe en pantalla. Si ya lo hay al empezar,
  // ni se añaden (así el contador dice "Paso 1 de 2" y no "Paso 5 de 6").
  function pasosRapidos(motivo) {
    if (hayInforme()) return [];
    const yaHay = function () { return hayInforme(); };
    return [
      {
        selector: '#selectModeloRaiz', interactivo: true, saltarSi: yaHay,
        titulo: 'Primero, un informe',
        texto: motivo + ' Elige el tipo de datos (o deja el que está) y pulsa "Siguiente".',
      },
      {
        selector: '#panelCamposContainer', interactivo: true, avanceManual: true, saltarSi: yaHay,
        alEntrar: panelCampos.abrir,
        titulo: 'Marca los campos',
        texto: 'Marca las columnas que quieres en el informe. Salen en el orden en que las marcas.',
        textoEspera: 'Marca al menos un campo para continuar.',
        esperar: function () { return camposMarcados() ? 'si' : ''; },
      },
      {
        id: 'rapidoGenerar',
        selector: '#btnGenerarVistaPrevia', interactivo: true, saltarSi: yaHay,
        alEntrar: marcarResultadosViejos,
        titulo: 'Genera el informe',
        texto: 'Pulsa <strong>"Generar informe"</strong>.',
        esperar: informeNuevo,
      },
      {
        selector: '#resultadosContainer .ii-resumen', saltarSi: yaHay,
        volver: { a: 'rapidoGenerar', texto: 'Volver a generar' },
        titulo: 'Sin registros',
        texto: 'Ningún registro cumple esta configuración, así que no hay nada que guardar ni exportar. Cambia los campos o los filtros y vuelve a generar.',
      },
    ];
  }

  function pasosGenerar() {
    return [
      {
        selector: '#selectModeloRaiz', interactivo: true,
        titulo: '¿Sobre qué desea informar?',
        texto: 'Empieza eligiendo el tipo de datos: <strong>Contratos</strong>, <strong>Bajas</strong>, <strong>Plantilla</strong>, <strong>Aspirantes</strong> o <strong>Movimientos de Nómina</strong>. ' +
               'Cada uno trae sus propios campos. Puedes dejar el que está y pulsar "Siguiente".',
      },
      {
        selector: '#cajaPeriodo',
        titulo: 'Fecha del informe',
        texto: 'Con <strong>"Datos actuales"</strong> ves la información de ahora mismo. Si eliges un mes cerrado, el informe muestra la plantilla <strong>tal como estaba</strong> ese mes, según su cierre mensual. ' +
               'Si el botón está apagado es porque ese tipo de datos no guarda fotografía mensual o aún no hay cierres.',
      },
      {
        selector: '#filtro_unidades_ii',
        titulo: 'Unidad Organizativa',
        texto: 'Acota el informe a una o varias unidades. Una Unidad Principal incluye sus subunidades. Sin nada elegido, entra todo lo que tu rol te permite ver.',
      },
      {
        selector: '#selectDesglosarPor, #selectTarjetas',
        titulo: 'Desglose y tarjetas del resumen',
        texto: '<strong>Desglosar por</strong> agrupa el resumen en barras (por ejemplo, cuántas mujeres y cuántos hombres). ' +
               'Las <strong>Tarjetas</strong> son las cifras de arriba del resumen (total, edad promedio...). Ninguno de los dos cambia las columnas de la tabla.',
      },
      {
        selector: '#panelCamposContainer', interactivo: true, avanceManual: true,
        alEntrar: panelCampos.abrir,
        titulo: '1. Campos a mostrar',
        texto: 'Marca los campos que quieres ver como <strong>columnas</strong>. Salen en el <strong>orden en que los marcas</strong>: si quieres el nombre primero, márcalo primero. ' +
               'Usa el buscador para encontrar un campo. El candado solo avisa de que es un dato sensible.',
        textoEspera: 'Marca al menos un campo para continuar.',
        esperar: function () { return camposMarcados() ? 'si' : ''; },
      },
      {
        selector: '#bloqueFiltrosII', interactivo: true, opcional: true,
        alEntrar: panelFiltros.abrir, alSalir: panelFiltros.restaurar,
        titulo: '2. Filtros',
        texto: 'Pulsa <strong>"Añadir filtro"</strong> y elige campo, operador y valor. <strong>Todos los filtros se cumplen a la vez</strong>: solo entran los registros que cumplen todas las condiciones. ' +
               'Para un "o" dentro del mismo campo usa el operador <strong>"Es alguno de"</strong>. Si no necesitas filtros, pulsa "Siguiente".',
      },
      {
        selector: '#bloqueOrdenII',
        alEntrar: panelOrden.abrir, alSalir: panelOrden.restaurar,
        titulo: '3. Ordenar el detalle',
        texto: 'Opcional: aquí eliges por qué columna se ordenan las filas y en qué sentido. Solo aparecen los campos que marcaste en el paso 1.',
      },
      {
        selector: '#btnGenerarVistaPrevia', interactivo: true,
        alEntrar: marcarResultadosViejos,
        titulo: 'Generar informe',
        texto: 'Pulsa <strong>"Generar informe"</strong>. A la izquierda verás cuántos registros cumplen tu configuración. ¡Y consigues el logro!',
        esperar: informeNuevo,
      },
      {
        selector: '#resultadosContainer .ii-resumen',
        titulo: 'Resumen del informe',
        texto: function () {
          if (!totalRegistros()) {
            return 'Ningún registro cumple esta configuración. Prueba a quitar algún filtro o a cambiar de unidad y vuelve a generar.';
          }
          const resumen = document.querySelector('#resultadosContainer .ii-resumen');
          if (resumen && !resumen.querySelector('.ii-kpi, .ii-desglose')) {
            return 'El resumen está vacío porque no elegiste <strong>Tarjetas</strong> ni <strong>Desglose</strong>. ' +
                   'Si los eliges arriba y vuelves a generar, aquí verás las cifras y las barras de cada grupo con su porcentaje.';
          }
          return 'Arriba van las <strong>tarjetas</strong> con las cifras que elegiste y, debajo, las <strong>barras del desglose</strong> con cuántos registros hay en cada grupo y su porcentaje. ' +
                 'Todo se calcula sobre los registros que cumplen los filtros.';
        },
      },
      {
        selector: '#resultadosContainer .ii-head-tabla',
        titulo: 'Detalle de registros',
        texto: 'Debajo está la tabla con una columna por cada campo marcado. Si hay muchos registros, se reparten en páginas: los botones de página están al final de la tabla.',
      },
      {
        selector: '#panelEvolucion',
        titulo: 'Evolución mensual',
        texto: 'Al desplegarlo verás un gráfico con cómo cambió un dato mes a mes durante el año, usando los cierres mensuales. Respeta los filtros que tengas puestos.',
      },
      {
        selector: '#resultadosContainer .ii-btn-export, #btnGuardarFavorito',
        titulo: '¡Informe generado!',
        texto: 'Desde aquí puedes <strong>exportarlo</strong> a PDF, Word o Excel, con las mismas columnas, filtros y orden, o <strong>guardarlo como favorito</strong> para recuperarlo cuando quieras. ' +
               '¿Seguimos con alguna de las dos?',
        acciones: [
          { texto: 'Exportarlo', icono: 'bx-download', ejecutar: iniciarExportar },
          { texto: 'Guardarlo como favorito', icono: 'bx-star', ejecutar: function () { window.OrbithRecorrido.lanzar('primer_informe_favorito:informe'); } },
        ],
      },
    ];
  }

  // Guía de exportar compartida con Informes RRHH (recorrido_exportar.js):
  // acompaña hasta tener PDF, Word y Excel. Si no hay informe en pantalla,
  // empieza con los pasos cortos para generarlo.
  const guiaExportar = window.OrbithGuiaExportar ? window.OrbithGuiaExportar({
    codigo: 'exportar_informe_inteligente',
    selector: '#resultadosContainer .ii-btn-export',
    explicacion: 'El documento sale con las mismas columnas, filtros y orden que ves en pantalla:' +
      '<ul class="mb-1 mt-1 ps-3">' +
      '<li><strong>PDF</strong>: para imprimir o enviar tal cual.</li>' +
      '<li><strong>Word</strong>: para retocarlo antes de entregarlo.</li>' +
      '<li><strong>Excel</strong>: para trabajar con los datos. No tiene límite de columnas ni de filas.</li>' +
      '</ul>' +
      'Si el informe no cabe en un PDF o un Word, Orbith te avisa antes y te propone alternativas.',
    antes: function () { return pasosRapidos('Para exportar hace falta un informe en pantalla.'); },
  }) : null;
  document.addEventListener('ii:exportacion', function (e) {
    if (guiaExportar) guiaExportar.marcar(e.detail && e.detail.tipo);
  });

  function iniciarExportar() {
    if (guiaExportar) guiaExportar.iniciar();
  }

  function pasosFavorito() {
    return pasosRapidos('Para guardar un favorito hace falta un informe en pantalla.').concat([
      {
        id: 'favBoton',
        selector: '#btnGuardarFavorito', interactivo: true,
        titulo: 'Guardar como favorito',
        texto: 'Un favorito guarda <strong>la configuración</strong> del informe (tipo de datos, campos, filtros y orden), no los datos: al abrirlo, se genera con la información del momento. ' +
               'Pulsa <strong>"Guardar como favorito"</strong>.',
        esperar: function () { return document.querySelector('#modalGuardarFavorito.show') ? 'abierto' : ''; },
      },
      {
        selector: '#inputNombreFavorito, #inputDescripcionFavorito', interactivo: true, avanceManual: true,
        volver: { a: 'favBoton' },
        titulo: 'Nombre y descripción',
        texto: 'Ponle un <strong>nombre</strong> que lo identifique, por ejemplo "Mujeres por unidad". La <strong>descripción</strong> es opcional.',
        textoEspera: 'Escribe un nombre para continuar.',
        esperar: function () {
          const nombre = document.getElementById('inputNombreFavorito');
          return nombre && nombre.value.trim() ? 'si' : '';
        },
      },
      {
        selector: '#btnConfirmarGuardarFavorito', interactivo: true,
        volver: { a: 'favBoton' }, paciencia: 3000,
        titulo: 'Guardar informe',
        texto: 'Pulsa <strong>"Guardar informe"</strong>. La página se recarga para mostrarlo en tu lista y la guía sigue después. ¡Y consigues el logro!',
        esperar: function () { return favoritoGuardado ? 'guardado' : ''; },
      },
      {
        selector: '#btnPanelFavoritos',
        titulo: '¡Guardado!',
        texto: 'Recargando la página para mostrarlo en tus favoritos…',
      },
    ]);
  }

  function iniciarFavorito() {
    favoritoGuardado = false;
    iniciar(pasosFavorito(), function () { recorridoFavoritoActivo = false; });
    // Después de iniciar: si había otro recorrido de favoritos abierto, su
    // `alTerminar` acaba de poner la marca a false.
    recorridoFavoritoActivo = true;
  }

  // Segunda parte, después de la recarga.
  function pasosPanelFavoritos() {
    return [
      {
        selector: '#btnPanelFavoritos', interactivo: true,
        titulo: 'Mis favoritos e historial',
        texto: 'Tu informe ya está guardado. Pulsa <strong>"Mis favoritos e historial"</strong> para verlo.',
        esperar: function () { return document.querySelector('#panelFavoritos.show') ? 'abierto' : ''; },
      },
      {
        selector: '#listaFavoritos',
        // La recarga ya pasó: se devuelve al navegador su comportamiento normal.
        alEntrar: function () { try { history.scrollRestoration = 'auto'; } catch (e) { /* no crítico */ } },
        titulo: 'Tus informes favoritos',
        texto: 'Haz clic en el <strong>nombre</strong> de un favorito para abrirlo y generarlo con los datos de hoy. A la derecha de cada uno:' +
               '<ul class="mb-0 mt-1 ps-3">' +
               '<li><i class="bi bi-send text-primary"></i> <strong>Compartir</strong>: se lo envía como notificación a otros usuarios, que deciden si lo guardan.</li>' +
               '<li><i class="bi bi-pencil"></i> <strong>Editar</strong>: cambiar el nombre, la descripción o la configuración.</li>' +
               '<li><i class="bi bi-trash3 text-danger"></i> <strong>Eliminar</strong>.</li>' +
               '</ul>',
      },
      {
        selector: '#bloqueUltimoInforme',
        titulo: 'Último informe generado',
        texto: 'Aquí queda siempre el último informe que generaste, aunque no lo guardaras. Con <strong>"Recargar este informe"</strong> lo recuperas tal cual.',
      },
    ];
  }

  window.OrbithRecorridos = window.OrbithRecorridos || {};
  window.OrbithRecorridos['primer_informe_generado:informe'] = function () { iniciar(pasosGenerar()); };
  window.OrbithRecorridos['exportar_informe_inteligente:informe'] = iniciarExportar;
  window.OrbithRecorridos['primer_informe_favorito:informe'] = iniciarFavorito;
  window.OrbithRecorridos['primer_informe_favorito:panel'] = function () { iniciar(pasosPanelFavoritos()); };
})();
