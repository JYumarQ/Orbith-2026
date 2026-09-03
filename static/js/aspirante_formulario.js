/* Validación en vivo del formulario de datos personales del trabajador.
 *
 * Lo usan las DOS pantallas que editan un Aspirante:
 *   - `pages/aspirante/add_aspir.html`  (alta)
 *   - `pages/aspirante/updt_aspir.html` (edición, en modal o a página completa)
 *
 * Antes cada plantilla llevaba su propia copia de estas ~250 líneas. Eran casi
 * idénticas, pero no del todo, y esa deriva ya había producido fallos reales: la
 * pantalla de edición no comprobaba el CI duplicado (buscaba un elemento
 * `#error_ci_exist` que ni siquiera existía en su HTML) y las dos compartían un
 * único temporizador entre validaciones distintas. Al vivir aquí, cualquier arreglo
 * vale para las dos pantallas a la vez.
 *
 * La única diferencia real entre alta y edición es `aspiranteId`: al editar hay que
 * excluir al propio trabajador de las búsquedas de duplicados, o se detectaría a sí
 * mismo. Se resuelve con un parámetro, no con dos implementaciones.
 */
window.OrbithFormularioAspirante = window.OrbithFormularioAspirante || {};

/* Configuración de cada campo validado.
 *
 * `opcional: true` evita el borde amarillo cuando el campo está vacío. No es
 * cosmético: el envío se bloquea si queda algún amarillo, así que marcar un campo
 * como opcional es lo que permite guardar sin él. La serie del carnet es el caso
 * típico — es un dato importante, pero se reclama desde Subsanación (ASP-008), no
 * impidiendo guardar.
 */
OrbithFormularioAspirante.CAMPOS = {
  id_doc_identidad: { tipo: 'ci', mensaje: 'Inserte solo dígitos numéricos', esCI: true },
  id_serie_ci: { tipo: 'serie', mensaje: 'Solo letras y números', opcional: true, longitudExacta: 9 },
  id_sexo: { tipo: 'select' },
  id_nombre: { tipo: 'texto', mensaje: 'Inserte solo letras', capitalizar: true },
  id_papellido: { tipo: 'texto', mensaje: 'Inserte solo letras', capitalizar: true },
  id_sapellido: { tipo: 'texto', mensaje: 'Inserte solo letras', capitalizar: true },
  id_movil_personal: { tipo: 'telefono', mensaje: 'Solo números, espacios y paréntesis' },
  id_fijo_personal: { tipo: 'telefono', mensaje: 'Solo números, espacios y paréntesis' },
  id_provincia: { tipo: 'select' },
  id_municipio: { tipo: 'select' },
  id_raza: { tipo: 'select' },
  id_nivel_educ: { tipo: 'select' },
};

/* Caracteres que se BORRAN según se escriben. */
OrbithFormularioAspirante.PATRONES = {
  numeros: /[^0-9]/g,
  telefono: /[^0-9()\s+\-]/g,
  texto: /[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜçÇ\-\s]/g,
  serie: /[^A-Za-z0-9]/g,
};

/**
 * Arranca la validación sobre un formulario ya presente en el DOM.
 *
 * @param {Object}  opciones
 * @param {string}  opciones.formulario    Selector del <form>.
 * @param {string}  opciones.urlValidacion URL de `validar_datos_aspirante`.
 * @param {number}  [opciones.aspiranteId] PK del trabajador que se edita. Se envía al
 *   servidor para que se excluya a sí mismo al buscar duplicados. Se omite en el alta.
 */
OrbithFormularioAspirante.iniciar = function (opciones) {
  var formulario = document.querySelector(opciones.formulario);
  if (!formulario) return;

  // Evita duplicar los listeners si la plantilla se reinyecta en el modal sin
  // recargar la página (abrir el modal, cerrarlo y volver a abrirlo).
  if (formulario.dataset.orbithValidacionActiva === '1') return;
  formulario.dataset.orbithValidacionActiva = '1';

  var CAMPOS = OrbithFormularioAspirante.CAMPOS;
  var PATRONES = OrbithFormularioAspirante.PATRONES;
  var urlValidacion = opciones.urlValidacion;
  var aspiranteId = opciones.aspiranteId || null;

  var ciInput = formulario.querySelector('#id_doc_identidad');
  var serieInput = formulario.querySelector('#id_serie_ci');
  var movilInput = formulario.querySelector('#id_movil_personal');
  var sexInput = formulario.querySelector('#id_sexo');
  var edadOutput = formulario.querySelector('#edad_calculada');
  var warningSexo = formulario.querySelector('#warning_sexo');

  // ---------------------------------------------------------------------------
  // Consultas al servidor
  // ---------------------------------------------------------------------------

  /* Un temporizador POR VALIDACIÓN, no uno global.
   *
   * Antes CI y móvil compartían una sola variable `timer`, así que escribir el móvil
   * justo después del carnet cancelaba la comprobación del carnet (y viceversa): el
   * duplicado se dejaba de detectar sin que nada lo indicara. Con un temporizador por
   * clave, cada campo espera su propio rebote sin pisar a los demás.
   */
  var temporizadores = {};

  function consultar(clave, parametros, alRecibir) {
    clearTimeout(temporizadores[clave]);
    temporizadores[clave] = setTimeout(function () {
      var query = new URLSearchParams(parametros);
      if (aspiranteId) query.set('aspirante_id', aspiranteId);

      fetch(urlValidacion + '?' + query.toString())
        .then(function (respuesta) { return respuesta.json(); })
        .then(alRecibir)
        .catch(function (err) { console.error('Error validando ' + clave + ':', err); });
    }, 300);
  }

  /* Muestra u oculta un <small> de error y, de paso, pinta el campo. */
  function marcarError(input, selectorMensaje, hayError, texto) {
    var aviso = formulario.querySelector(selectorMensaje);
    if (aviso) {
      aviso.classList.toggle('d-none', !hayError);
      if (hayError && texto) aviso.innerText = texto;
    }
    if (!input) return;
    input.classList.toggle('is-invalid', !!hayError);
    if (hayError) input.classList.remove('is-valid');
  }

  // ---------------------------------------------------------------------------
  // Semáforo visual (amarillo = falta / rojo = mal / verde = bien)
  // ---------------------------------------------------------------------------

  function mostrarErrorFlotante(input, msg) {
    input.setCustomValidity(msg);
    input.reportValidity();
  }

  /* Los campos `tipo: 'select'` de este archivo pueden llevar Select2 montado
   * encima (ver static/js/select2_htmx.js). Select2 oculta el <select> real
   * (`display:none`) y pinta su propia UI en un `.select2-container` justo al
   * lado: pintar el semáforo solo en el <select> oculto lo deja invisible.
   * Se refleja la misma clase también ahí, igual que ya hace Contrato. */
  function sincronizarClaseSelect2(input) {
    if (!window.jQuery) return;
    var $seleccion = jQuery(input).next('.select2-container').find('.select2-selection');
    if (!$seleccion.length) return;
    $seleccion.removeClass('border-warning is-invalid is-valid border-success');
    ['border-warning', 'is-invalid', 'is-valid', 'border-success'].forEach(function (clase) {
      if (input.classList.contains(clase)) $seleccion.addClass(clase);
    });
  }

  /* Solo el ROJO. El amarillo y el verde los pone `validacion_visual.js`.
   *
   * Antes esta función pintaba los tres colores, y lo hacía SOLO sobre el campo
   * que había disparado el evento. Eso dejaba fuera todo lo que se rellena
   * solo: el sexo deducido del carnet seguía amarillo aunque ya tuviera valor,
   * porque nadie volvía a pintarlo. El ayudante común repinta el formulario
   * entero en cada cambio, así que ese caso desaparece de raíz.
   *
   * Lo que sí se queda aquí es el rojo, porque son reglas que el ayudante no
   * puede deducir del HTML: que el carnet tenga once dígitos y que la serie
   * tenga nueve. El ayudante respeta `is-invalid` y no pinta encima, y
   * `evaluarBoton()` lo cuenta para bloquear el botón Guardar.
   */
  function actualizarEstilo(input, cfg) {
    input.classList.remove('is-invalid', 'is-valid', 'border-success', 'border-warning');
    var valor = input.value.trim();

    if (valor && cfg.esCI && valor.length !== 11) {
      input.classList.add('is-invalid');
    } else if (valor && cfg.longitudExacta && valor.length !== cfg.longitudExacta) {
      // Campo de longitud exacta (la serie: 9). Vacío vale, a medio escribir no.
      input.classList.add('is-invalid');
    }
    sincronizarClaseSelect2(input);
  }

  /* Avisa al ayudante común de que un campo cambió SIN que el usuario lo tocara.
   *
   * Hace falta en los dos sitios donde este archivo escribe un valor por su
   * cuenta: el sexo deducido del carnet y los municipios que se recargan al
   * cambiar de provincia. Asignar `input.value` desde JavaScript no dispara
   * ningún evento, así que sin esto el campo se queda con el color anterior —
   * que es justo lo que hacía que el sexo autorrellenado siguiera amarillo.
   *
   * NO se lanza desde `actualizarEstilo()`: a esa la llama el propio manejador
   * de `change`, y emitir un `change` ahí dentro sería una recursión infinita.
   */
  function avisarCambioDeValor(input) {
    if (!input) return;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  /* El carnet codifica una fecha: se corrige mientras se escribe, para que el usuario
   * vea el problema en el dígito que acaba de teclear y no al enviar. */
  function validarLogicaCI(input) {
    var val = input.value;
    if (val.length < 4) return;

    var mes = parseInt(val.substring(2, 4), 10);
    if (mes < 1 || mes > 12) {
      input.value = val.substring(0, 2);
      mostrarErrorFlotante(input, 'Mes inválido (01-12)');
      return;
    }

    if (val.length >= 6) {
      var dia = parseInt(val.substring(4, 6), 10);
      var maxDias = 31;
      if ([4, 6, 9, 11].indexOf(mes) !== -1) maxDias = 30;
      if (mes === 2) maxDias = 29;

      if (dia < 1 || dia > maxDias) {
        input.value = val.substring(0, 4);
        mostrarErrorFlotante(input, 'Día inválido para este mes');
      }
    }
  }

  Object.keys(CAMPOS).forEach(function (id) {
    var cfg = CAMPOS[id];
    var input = formulario.querySelector('[id="' + id + '"]');
    if (!input) return;

    if (cfg.tipo !== 'select') {
      input.addEventListener('input', function () {
        this.setCustomValidity('');

        var tipoPatron = cfg.tipo === 'ci' ? 'numeros' : cfg.tipo;
        var patron = PATRONES[tipoPatron];

        if (patron && patron.test(this.value)) {
          this.value = this.value.replace(patron, '');
          mostrarErrorFlotante(this, cfg.mensaje);
        }

        if (cfg.tipo === 'ci') validarLogicaCI(this);

        // Mayúsculas sin mover el cursor: asignar `value` lo mandaría al final.
        if (cfg.tipo === 'serie') {
          var posicion = this.selectionStart;
          this.value = this.value.toUpperCase();
          this.setSelectionRange(posicion, posicion);
        }

        actualizarEstilo(this, cfg);
      });

      input.addEventListener('blur', function () { this.setCustomValidity(''); });

      if (cfg.capitalizar) {
        input.addEventListener('blur', function () {
          if (this.value) {
            this.value = this.value.toLowerCase()
              .replace(/(?:^|\s|['"([{])+\S/g, function (m) { return m.toUpperCase(); });
          }
          actualizarEstilo(this, cfg);
        });
      }
    } else {
      input.addEventListener('change', function () {
        actualizarEstilo(this, cfg);
        // Provincia recarga las opciones de Municipio por HTMX: el repintado se
        // hace al recibir 'opciones:actualizadas' (más abajo), no con un
        // temporizador a ciegas.
      });
      // El puente Select2 -> evento nativo 'change' (para que HTMX se entere de
      // la selección) lo monta `OrbithSelect2.iniciar()` en
      // static/js/select2_htmx.js, cargado antes que este archivo en
      // add_aspir.html / updt_aspir.html — no hace falta duplicarlo aquí.
    }

    actualizarEstilo(input, cfg);
  });

  /* Municipio: HTMX ya solo cambia sus <option> (`hx-swap="innerHTML"`), así que
   * el <select> y su listener de 'change' siguen vivos; lo único que hace falta
   * es repintar el semáforo cuando llega la nueva lista. `select2_htmx.js`
   * avisa de ello con el evento 'opciones:actualizadas'. */
  var muni = formulario.querySelector('#id_municipio');
  if (muni) {
    muni.addEventListener('opciones:actualizadas', function () {
      actualizarEstilo(this, CAMPOS.id_municipio);
      avisarCambioDeValor(this);
    });
  }

  // ---------------------------------------------------------------------------
  // Edad: derivada, nunca se guarda
  // ---------------------------------------------------------------------------

  /* La edad cambia sola con el paso de los días, así que no es un campo de la base de
   * datos: se deduce de la fecha de nacimiento, que a su vez Orbith calcula del carnet
   * al guardar. El valor lo da el SERVIDOR (`Aspirante._calcular_fecha_nacimiento`);
   * aquí solo se pinta. Reinterpretar el carnet en JavaScript daría una segunda
   * lectura del mismo dato, que podría acabar discrepando de la que se guarda.
   *
   * Si el carnet no codifica una fecha real se deja el guion: mejor eso que una edad
   * inventada. */
  function pintarEdad(edad, fechaNacimiento) {
    if (!edadOutput) return;
    if (edad === null || edad === undefined) {
      edadOutput.value = '—';
      edadOutput.title = 'Calculada a partir del carnet de identidad. No se guarda: se actualiza sola.';
      return;
    }
    edadOutput.value = edad + ' años';
    edadOutput.title = 'Nacido el ' + fechaNacimiento +
      ' (deducido del carnet). La edad no se guarda: se actualiza sola.';
  }

  // ---------------------------------------------------------------------------
  // Carnet de identidad: longitud, sexo, edad y duplicado
  // ---------------------------------------------------------------------------

  function autocompletarSexo(valCI) {
    if (!sexInput) return;
    // 10º dígito: par = masculino, impar = femenino.
    var sexoCalculado = parseInt(valCI.charAt(9), 10) % 2 === 0 ? 'M' : 'F';
    sexInput.value = sexoCalculado;
    sexInput.classList.remove('is-invalid');
    if (warningSexo) warningSexo.classList.add('d-none');

    if (window.jQuery && jQuery(sexInput).hasClass('select2-hidden-accessible')) {
      // Que Select2 relea el valor y repinte su propia caja.
      jQuery(sexInput).trigger('change.select2');
    }

    // Y que el ayudante común lo repinte de verde. Sin este aviso el campo se
    // quedaba AMARILLO pese a tener valor, que es exactamente el fallo que se
    // veía: rellenándolo a mano sí funcionaba, porque entonces sí había un
    // `change` del usuario.
    avisarCambioDeValor(sexInput);
  }

  if (ciInput) {
    ciInput.addEventListener('input', function () {
      var val = this.value;

      marcarError(null, '#error_ci_len', false);
      marcarError(null, '#error_ci_exist', false);
      ciInput.classList.remove('is-invalid', 'is-valid');

      if (val.length !== 11) {
        marcarError(ciInput, '#error_ci_len', true);
        if (warningSexo) warningSexo.classList.add('d-none');
        pintarEdad(null, '');
        return;
      }

      autocompletarSexo(val);

      // Una sola consulta resuelve las dos cosas que dependen del carnet: si ya está
      // registrado y qué edad codifica.
      consultar('ci', { doc_identidad: val }, function (data) {
        pintarEdad(data.edad, data.fecha_nacimiento);

        if (data.ci_existe) {
          marcarError(ciInput, '#error_ci_exist', true, data.ci_error_msg);
        } else {
          marcarError(ciInput, '#error_ci_exist', false);
          ciInput.classList.add('is-valid');
        }
      });
    });
  }

  /* Aviso suave: el sexo se autocompleta desde el carnet, pero se deja cambiar. Si el
   * usuario elige uno que no cuadra, se avisa sin bloquear: puede ser un carnet mal
   * emitido, y el caso lo recoge la regla ASP-004 de Subsanación. */
  if (sexInput && ciInput) {
    sexInput.addEventListener('change', function () {
      var valCI = ciInput.value;
      if (valCI.length !== 11 || !warningSexo) return;
      var sexoCalculado = parseInt(valCI.charAt(9), 10) % 2 === 0 ? 'M' : 'F';
      warningSexo.classList.toggle('d-none', !this.value || this.value === sexoCalculado);
    });

    // Al abrir una ficha existente el carnet ya viene relleno: se comprueba de
    // entrada si el sexo guardado cuadra con él, sin esperar a que el usuario
    // toque nada. En el alta el carnet está vacío y esto no hace nada.
    if (ciInput.value.length === 11) sexInput.dispatchEvent(new Event('change'));
  }

  // ---------------------------------------------------------------------------
  // Serie del carnet: formato y duplicado
  // ---------------------------------------------------------------------------

  if (serieInput) {
    serieInput.addEventListener('input', function () {
      var val = this.value.trim().toUpperCase();

      marcarError(null, '#error_serie_len', false);
      marcarError(null, '#error_serie_exist', false);

      // Vacía es válida: importante, pero no obligatoria.
      if (!val) return;

      if (val.length !== 9) {
        marcarError(null, '#error_serie_len', true);
        return;
      }

      consultar('serie', { serie: val }, function (data) {
        if (data.serie_existe) {
          marcarError(serieInput, '#error_serie_exist', true, data.serie_error_msg);
        } else {
          marcarError(serieInput, '#error_serie_exist', false);
          serieInput.classList.add('is-valid');
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Móvil: duplicado
  // ---------------------------------------------------------------------------

  if (movilInput) {
    movilInput.addEventListener('input', function () {
      var val = this.value.trim();
      marcarError(null, '#error_movil_exist', false);
      movilInput.classList.remove('is-invalid', 'is-valid');

      if (val.length < 6) return;

      // No hace falta recordar el móvil original para no detectarse a sí mismo: el
      // servidor ya excluye a este trabajador gracias a `aspirante_id`.
      consultar('movil', { movil: val }, function (data) {
        if (data.movil_existe) {
          marcarError(movilInput, '#error_movil_exist', true);
        } else {
          marcarError(movilInput, '#error_movil_exist', false);
          movilInput.classList.add('is-valid');
        }
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Nivel educativo: habilita Grado Científico y Título de Oro
  // ---------------------------------------------------------------------------

  var nivelEduc = formulario.querySelector('#id_nivel_educ');
  var grado = formulario.querySelector('#id_grado_cientifico');
  var tituloOro = formulario.querySelector('#id_titulo_oro');
  var avisoTituloOro = formulario.querySelector('#aviso_titulo_oro');

  function aplicarReglasDeNivel() {
    if (!nivelEduc) return;
    var esNivelSuperior = nivelEduc.value === 'NS';

    if (grado) {
      if (esNivelSuperior) {
        grado.removeAttribute('disabled');
      } else {
        // Se vacía además de bloquearse: un grado científico heredado de una
        // selección anterior se guardaría igualmente.
        grado.setAttribute('disabled', 'disabled');
        grado.value = '';
        if (window.jQuery && jQuery(grado).hasClass('select2-hidden-accessible')) {
          jQuery(grado).trigger('change.select2');
        }
      }
    }

    // El Título de Oro solo existe para graduados de Nivel Superior. Un campo
    // deshabilitado no viaja en el POST, así que esto ya basta para que el
    // servidor nunca reciba `titulo_oro=True` con otro nivel educativo.
    if (tituloOro) {
      if (esNivelSuperior) {
        tituloOro.removeAttribute('disabled');
        if (avisoTituloOro) avisoTituloOro.classList.add('d-none');
      } else if (!tituloOro.disabled) {
        // Este `if` hace el bloque idempotente: `nivelEduc` tiene un listener
        // nativo Y uno de jQuery para 'change', así que un solo evento real
        // ejecuta esta función dos veces seguidas. Sin la guarda, la segunda
        // pasada volvía a leer `checked` (ya puesto en `false` por la
        // primera) y ocultaba el aviso que la primera acababa de mostrar.
        var teniaMarcado = tituloOro.checked;
        tituloOro.setAttribute('disabled', 'disabled');
        tituloOro.checked = false;
        // El aviso solo aparece si el cambio de nivel le acaba de quitar la
        // marca al usuario: si nunca la puso, no hace falta explicarle nada.
        if (avisoTituloOro) avisoTituloOro.classList.toggle('d-none', !teniaMarcado);
      }
    }
  }

  if (nivelEduc) {
    nivelEduc.addEventListener('change', aplicarReglasDeNivel);
    if (window.jQuery) jQuery(nivelEduc).on('change', aplicarReglasDeNivel);
    aplicarReglasDeNivel();
  }

  // ---------------------------------------------------------------------------
  // Envío
  // ---------------------------------------------------------------------------

  formulario.addEventListener('submit', function (e) {
    function hayAviso(selector) {
      var el = formulario.querySelector(selector);
      return !!el && !el.classList.contains('d-none');
    }

    var problemas =
      hayAviso('#error_ci_exist') ||
      hayAviso('#error_ci_len') ||
      hayAviso('#error_serie_exist') ||
      hayAviso('#error_serie_len') ||
      hayAviso('#error_movil_exist') ||
      (ciInput && ciInput.value.length !== 11) ||
      formulario.querySelectorAll('.border-warning').length > 0 ||
      formulario.querySelectorAll('.is-invalid').length > 0;

    if (!problemas) return;  // Deja fluir el evento al confirmador global (.swal-confirm).

    e.preventDefault();
    // Crítico: sin esto saltaría igualmente el "¿seguro que quiere guardar?" global.
    e.stopImmediatePropagation();

    Swal.fire({
      title: 'Atención',
      text: 'Revise los campos resaltados en rojo o amarillo.',
      icon: 'warning',
      confirmButtonText: 'OK',
      customClass: { confirmButton: 'btn btn-primary' },
      buttonsStyling: false,
    });
  });

  if (window.htmx) htmx.process(formulario);
};
