/**
 * Botón «ver contraseña» con protección contra el autocompletado del navegador.
 *
 * EL PROBLEMA QUE RESUELVE
 * ------------------------
 * Poner `input.type = 'text'` hace que el navegador pinte el valor que haya en
 * el campo, venga de donde venga. Los navegadores protegen a propósito sus
 * contraseñas guardadas —para verlas en el gestor de Chrome o Edge hay que pasar
 * por Windows Hello o la contraseña de la cuenta— y un botón de «ver» en la
 * página se salta esa protección por completo, porque el valor autocompletado ya
 * está dentro del input.
 *
 * El escenario real en un PC compartido: alguien deja la sesión de Windows
 * abierta, el navegador tiene guardada la contraseña de Orbith, y quien pase
 * abre el login, pulsa el ojo y se lleva una contraseña que nunca supo. Y si esa
 * persona reutiliza claves entre sistemas, que es lo habitual, el daño no se
 * queda en Orbith.
 *
 * LA REGLA
 * --------
 * El ojo solo revela lo que el usuario haya ESCRITO en esta carga de página.
 * Se sostiene sobre tres comprobaciones que se refuerzan entre sí:
 *
 *   1. `contaminado`: el campo recibió en algún momento un valor que el usuario
 *      no tecleó. Solo se limpia cuando el campo se vacía DEL TODO. Esto cierra
 *      el hueco evidente: si bastara con teclear un carácter más sobre lo
 *      autocompletado, cualquiera añadiría una letra y revelaría la contraseña
 *      guardada entera.
 *   2. `escrito`: copia de lo último que el usuario tecleó. Si el valor actual
 *      no coincide, es que llegó por otra vía. Cubre el caso de los navegadores
 *      que autocompletan SIN emitir evento `input`, que la comprobación 1 no
 *      llegaría a ver.
 *   3. Campo vacío: no hay nada que mostrar.
 *
 * A esas tres se suma una cuarta, la más directa: la pseudo-clase `:autofill`
 * (`:-webkit-autofill` en los navegadores antiguos). Es el propio navegador
 * diciendo «este valor lo rellené yo». Se consulta en cada repaso y, en cuanto
 * da positivo, deja `contaminado` marcado para siempre —hasta vaciar el campo—
 * porque el navegador la retira en cuanto el usuario toca el campo y sin ese
 * pestillo bastaría escribir una letra para que la señal desapareciera.
 *
 * La señal de «el usuario está editando» es `beforeinput`, no `keydown`. Es una
 * corrección importante: `keydown` NO se dispara con los teclados en pantalla de
 * Android, el dictado por voz ni los métodos de entrada IME, así que usarlo
 * dejaba el botón muerto para esos usuarios. `beforeinput` sí cubre todos esos
 * casos y el autocompletado no lo emite.
 *
 * Pegar SÍ cuenta como manual: quien pega una contraseña ya la tiene en el
 * portapapeles, así que verla no le descubre nada, y bloquearlo solo estorbaría
 * a quien use un gestor de contraseñas externo.
 *
 * Si aun así alguna señal fallara, el botón se queda bloqueado: es la dirección
 * correcta del fallo, molesta pero no revela nada.
 */
(function (global) {
  'use strict';

  var MOTIVO_AUTOCOMPLETADO =
    'Por seguridad no se puede mostrar una contraseña rellenada por el ' +
    'navegador. Bórrela y escríbala si necesita verla.';
  var MOTIVO_VACIO = 'Escriba la contraseña para poder mostrarla.';

  function activarVerPassword(campo, boton) {
    if (!campo || !boton || boton.dataset.verPasswordActivo === '1') return;
    boton.dataset.verPasswordActivo = '1';

    var iconoVer = boton.querySelector('[data-icono="ver"]');
    var iconoOcultar = boton.querySelector('[data-icono="ocultar"]');

    // Un campo de contraseña que llega con valor solo puede venir del
    // autocompletado: Django nunca reenvía el valor de una contraseña al
    // repintar un formulario, ni siquiera tras un intento fallido.
    var contaminado = campo.value !== '';
    var escrito = '';
    var pulsacion = false;
    var valorAntesDeLaTecla = '';
    // Selección en el momento de editar: hace falta para distinguir «escribió
    // encima de una parte» de «seleccionó todo y lo sustituyó».
    var seleccionInicio = 0;
    var seleccionFin = 0;

    /** ¿El navegador marca este campo como rellenado por él? */
    function esAutocompletado() {
      // `matches` lanza si el selector no se conoce, así que se prueban por
      // separado: `:autofill` es el estándar y `:-webkit-autofill` el veterano.
      try { if (campo.matches(':autofill')) return true; } catch (e) { /* no soportado */ }
      try { if (campo.matches(':-webkit-autofill')) return true; } catch (e) { /* no soportado */ }
      return false;
    }

    function bloqueado() {
      // El pestillo se echa aquí y no solo en el `input`: el navegador retira la
      // marca en cuanto el usuario toca el campo, y para entonces ya es tarde.
      if (esAutocompletado()) contaminado = true;

      if (campo.value === '') return MOTIVO_VACIO;
      if (contaminado) return MOTIVO_AUTOCOMPLETADO;
      if (campo.value !== escrito) return MOTIVO_AUTOCOMPLETADO;
      return null;
    }

    function pintar(visible) {
      if (iconoVer) iconoVer.style.display = visible ? 'none' : '';
      if (iconoOcultar) iconoOcultar.style.display = visible ? '' : 'none';
      boton.setAttribute('aria-pressed', visible ? 'true' : 'false');
    }

    function ocultar() {
      campo.type = 'password';
      pintar(false);
    }

    function sincronizar() {
      var motivo = bloqueado();

      // Se usa `aria-disabled` y no el atributo `disabled`: un botón deshabilitado
      // de verdad no recibe eventos de ratón en varios navegadores y el usuario se
      // quedaría sin ver el aviso que explica por qué no funciona.
      boton.setAttribute('aria-disabled', motivo ? 'true' : 'false');
      boton.style.opacity = motivo ? '0.45' : '';
      boton.style.cursor = motivo ? 'not-allowed' : '';

      if (motivo) {
        ocultar();
        boton.title = motivo;
        boton.setAttribute('aria-label', motivo);
        return;
      }

      var visible = campo.type === 'text';
      boton.title = visible ? 'Ocultar contraseña' : 'Mostrar contraseña';
      boton.setAttribute('aria-label', boton.title);
    }

    // `beforeinput` es la señal principal (cubre teclado físico, teclado en
    // pantalla, dictado e IME); `keydown` y `paste` se mantienen como respaldo.
    ['beforeinput', 'keydown', 'paste'].forEach(function (evento) {
      campo.addEventListener(evento, function (e) {
        // `isTrusted` distingue la acción real de una sintética lanzada por script.
        if (!e.isTrusted) return;
        pulsacion = true;
        valorAntesDeLaTecla = campo.value;
        seleccionInicio = campo.selectionStart;
        seleccionFin = campo.selectionEnd;
      });
    });

    campo.addEventListener('input', function () {
      // ¿La edición se llevó por delante TODO lo que había? Si el usuario tenía
      // seleccionado el contenido entero y escribió encima, de lo anterior no
      // queda ni un carácter, así que el valor nuevo es enteramente suyo.
      var sustituyoTodo = pulsacion &&
                          seleccionInicio === 0 &&
                          seleccionFin === valorAntesDeLaTecla.length &&
                          valorAntesDeLaTecla !== '';

      if (campo.value === '') {
        // Vaciar el campo lo devuelve al punto de partida.
        contaminado = false;
        escrito = '';
      } else if (!pulsacion) {
        // El valor cambió sin que el usuario editara: autocompletado.
        contaminado = true;
      } else if (sustituyoTodo || valorAntesDeLaTecla === '') {
        // Partía de vacío, o sustituyó el contenido entero: nada de lo que hay
        // ahora en el campo viene del navegador.
        contaminado = false;
        escrito = campo.value;
      } else if (valorAntesDeLaTecla === escrito && !contaminado) {
        // Sigue construyendo sobre lo que él mismo había escrito.
        escrito = campo.value;
      } else {
        // Escribió SOBRE algo que no había escrito él: queda contaminado hasta
        // que vacíe el campo o lo sustituya entero.
        contaminado = true;
      }

      pulsacion = false;
      sincronizar();
    });

    boton.addEventListener('click', function () {
      // Se vuelve a comprobar aquí, y no se confía en el estado pintado: entre el
      // último `sincronizar()` y este clic el navegador ha podido autocompletar
      // sin avisar.
      if (bloqueado()) {
        sincronizar();
        return;
      }

      var visible = campo.type === 'text';
      campo.type = visible ? 'password' : 'text';
      pintar(!visible);
      sincronizar();

      // Devolver el foco al campo con el cursor al final: sin esto habría que
      // volver a pinchar para seguir escribiendo.
      campo.focus();
      try {
        campo.setSelectionRange(campo.value.length, campo.value.length);
      } catch (e) { /* no aplica a todos los tipos de input */ }
    });

    // Varios navegadores autocompletan un instante DESPUÉS de cargar la página,
    // así que el estado inicial se repasa un par de veces.
    sincronizar();
    setTimeout(sincronizar, 0);
    setTimeout(sincronizar, 600);
  }

  /** Activa todos los pares campo/botón marcados dentro de `raiz`. */
  function activarEn(raiz) {
    (raiz || document).querySelectorAll('[data-ver-password]').forEach(function (boton) {
      activarVerPassword(document.getElementById(boton.dataset.verPassword), boton);
    });
  }

  global.OrbithVerPassword = { activar: activarVerPassword, activarEn: activarEn };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { activarEn(document); });
  } else {
    activarEn(document);
  }
})(window);
