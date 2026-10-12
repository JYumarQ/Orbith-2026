/**
 * Paso de recorrido "Exportar" para las tareas que piden PDF, Word y Excel
 * (categoría "Exportar" de la Guía: `exportar_informe_inteligente` y
 * `exportar_informes_rrhh`).
 *
 * Resalta los tres botones, marca los formatos que el usuario ya tiene hechos
 * (los pide a /progreso/tarea/<codigo>/partes/) y acompaña hasta completar los
 * tres: tras cada descarga dice cuántos lleva y cuáles le faltan. Se puede
 * terminar antes con "Terminar".
 *
 * Uso:
 *   const guia = OrbithGuiaExportar({ codigo, selector, explicacion, antes });
 *   guia.marcar('pdf');   // la pantalla avisa de cada descarga
 *   guia.iniciar();       // lanza el recorrido
 *
 * `antes` (opcional) es una función que devuelve pasos previos (por ejemplo,
 * generar un informe si aún no hay ninguno). Se llama al iniciar.
 */
(function () {
  if (!window.OrbithRecorrido) return;

  const FORMATOS = ['pdf', 'word', 'excel'];
  const ETIQUETA = { pdf: 'PDF', word: 'Word', excel: 'Excel' };

  function lista(nombres) {
    const e = nombres.map(function (f) { return '<strong>' + ETIQUETA[f] + '</strong>'; });
    return e.length > 1 ? e.slice(0, -1).join(', ') + ' y ' + e[e.length - 1] : e.join('');
  }

  window.OrbithGuiaExportar = function (opciones) {
    const hechas = new Set();
    let completaAlEmpezar = false;
    let nuevas = 0;
    let ultima = '';
    let activa = false;

    function faltan() {
      return FORMATOS.filter(function (f) { return !hechas.has(f); });
    }

    function marcar(formato) {
      if (!ETIQUETA[formato]) return;
      hechas.add(formato);
      if (activa) { nuevas += 1; ultima = formato; }
    }

    function estado() {
      return '<div class="d-flex gap-2 my-2">' + FORMATOS.map(function (f) {
        const hecho = hechas.has(f);
        return '<span class="badge ' + (hecho ? 'bg-label-success' : 'bg-label-secondary') + '">' +
          (hecho ? '✔ ' : '') + ETIQUETA[f] + '</span>';
      }).join('') + '</div>';
    }

    function texto() {
      let aviso;
      const pendientes = faltan();
      if (completaAlEmpezar) {
        aviso = 'Ya tienes este logro: exporta en el formato que necesites.';
      } else if (!pendientes.length) {
        aviso = '¡Ya tienes los tres formatos!';
      } else if (nuevas && pendientes.length) {
        aviso = '¡' + ETIQUETA[ultima] + ' descargado! ' + (3 - pendientes.length) + ' de 3. Te ' +
          (pendientes.length > 1 ? 'faltan ' : 'falta ') + lista(pendientes) + ': pulsa ' +
          (pendientes.length > 1 ? 'uno de ellos.' : 'ese botón.');
      } else if (hechas.size) {
        aviso = 'Para el logro necesitas los tres formatos. Te ' +
          (pendientes.length > 1 ? 'faltan ' : 'falta ') + lista(pendientes) + '.';
      } else {
        aviso = 'Para el logro necesitas los tres formatos: pulsa uno para empezar.';
      }
      return opciones.explicacion + estado() + aviso;
    }

    function pasos() {
      return [
        {
          selector: opciones.selector, interactivo: true,
          titulo: 'Exportar',
          texto: texto,
          textoEspera: completaAlEmpezar ? 'Pulsa el formato que quieras.' : 'Pulsa un formato que te falte.',
          esperar: function () {
            return (completaAlEmpezar ? nuevas > 0 : !faltan().length) ? 'listo' : '';
          },
          acciones: [{ texto: 'Terminar', icono: 'bx-check', ejecutar: function () { window.OrbithRecorrido.terminar(); } }],
        },
        {
          selector: opciones.selector,
          titulo: completaAlEmpezar ? '¡Documento en camino!' : '¡Logro conseguido!',
          texto: completaAlEmpezar
            ? 'Cuando termine de prepararse lo encontrarás en tus <strong>descargas</strong>.'
            : 'Exportaste en <strong>PDF, Word y Excel</strong>. Encontrarás los documentos en tus <strong>descargas</strong>.',
        },
      ];
    }

    function iniciar() {
      hechas.clear();
      completaAlEmpezar = false;
      nuevas = 0;
      fetch('/progreso/tarea/' + encodeURIComponent(opciones.codigo) + '/partes/', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }, cache: 'no-store',
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function (datos) {
          (datos.partes || []).forEach(function (p) { if (p.hecha) hechas.add(p.clave); });
          completaAlEmpezar = !!datos.completada;
        })
        // Sin respuesta, la guía funciona igual: empieza sin marcas.
        .catch(function () {})
        .then(function () {
          const previos = typeof opciones.antes === 'function' ? opciones.antes() : [];
          window.OrbithRecorrido.iniciar({
            pasos: previos.concat(pasos()),
            alTerminar: function () { activa = false; },
          });
          // Después de iniciar: si había otro recorrido abierto (o este
          // mismo), su `alTerminar` acaba de poner la marca a false.
          activa = window.OrbithRecorrido.activo();
        });
    }

    return { marcar: marcar, iniciar: iniciar };
  };
})();
