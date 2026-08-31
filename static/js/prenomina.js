/* Cableado de los modales de Pre-Nómina.
 *
 * Vive en un fichero propio y no repetido en cada plantilla por un motivo
 * concreto: el arreglo que hay aquí abajo es sutil, y tenerlo en tres copias
 * garantizaba que tarde o temprano una se quedara atrás.
 *
 * EL PROBLEMA QUE RESUELVE
 * ------------------------
 * El constructor de `bootstrap.Modal` guarda una referencia al diálogo **una
 * sola vez**:
 *
 *     this._dialog = SelectorEngine.findOne('.modal-dialog', this._element)
 *
 * Nuestros contenedores nacen vacíos (`<div class="modal" id="..."></div>`) y
 * htmx les mete el contenido después. Si la instancia se crea al cargar la
 * página, `_dialog` queda en `null` para siempre, y al llamar a `show()`
 * Bootstrap intenta `querySelector` sobre `null`:
 *
 *     Uncaught TypeError: Illegal invocation
 *         at Object.findOne ... at Je._showElement
 *
 * La solución es crear la instancia **después** de cada intercambio, tirando la
 * anterior. Es barato (una vez por apertura de modal) y deja de depender de en
 * qué momento se cargó la página.
 */
(function () {
  'use strict';

  window.orbith = window.orbith || {};

  /* Deja listo un contenedor de modal que se rellena por htmx. */
  window.orbith.cablearModalHtmx = function (idModal) {
    var contenedor = document.getElementById(idModal);
    if (!contenedor || contenedor.dataset.orbithCableado === '1') { return; }
    contenedor.dataset.orbithCableado = '1';

    contenedor.addEventListener('htmx:afterSwap', function () {
      // Sin contenido no hay `.modal-dialog` que mostrar. Puede pasar si una
      // vista devuelve un fragmento vacío.
      if (!contenedor.querySelector('.modal-dialog')) { return; }

      // Tirar la instancia previa: la suya apunta al diálogo anterior, que
      // htmx acaba de sustituir.
      var previa = bootstrap.Modal.getInstance(contenedor);
      if (previa) { previa.dispose(); }

      bootstrap.Modal.getOrCreateInstance(contenedor).show();
    });

    // `closeModal` es el evento que ya emiten Solicitudes, Contratos y
    // Estructura Organizativa; aquí solo se atiende para este contenedor.
    document.body.addEventListener('closeModal', function () {
      var instancia = bootstrap.Modal.getInstance(contenedor);
      if (instancia) { instancia.hide(); }
    });
  };

  /* Confirmación con el SweetAlert2 del proyecto para los botones que lleven
   * `data-confirmar`. Se intercepta `htmx:confirm`, igual que hace
   * `gestor_plantilla.html`. */
  window.orbith.cablearConfirmacionHtmx = function () {
    if (document.body.dataset.orbithConfirmacion === '1') { return; }
    document.body.dataset.orbithConfirmacion = '1';

    document.body.addEventListener('htmx:confirm', function (evento) {
      var pregunta = evento.detail.elt.getAttribute('data-confirmar');
      if (!pregunta) { return; }
      evento.preventDefault();

      Swal.fire({
        title: evento.detail.elt.getAttribute('data-titulo') || '¿Continuar?',
        text: pregunta,
        icon: evento.detail.elt.getAttribute('data-icono') || 'question',
        showCancelButton: true,
        confirmButtonText: 'Sí, continuar',
        cancelButtonText: 'Cancelar',
        confirmButtonColor: evento.detail.elt.getAttribute('data-color') || '#696cff'
      }).then(function (resultado) {
        if (resultado.isConfirmed) { evento.detail.issueRequest(true); }
      });
    });
  };
})();
