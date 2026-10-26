/* ==========================================================================
   Aviso de «por qué no se puede guardar» (25-10-2026)
   ==========================================================================

   Antes, cuando faltaba un dato o había un error, el botón Guardar se quedaba
   APAGADO sin decir por qué: con un campo escondido o en otra pestaña, el
   usuario no tenía forma de saber qué le faltaba.

   Ahora, en todo formulario con `data-validacion-visual` (o `data-aviso-guardar`):

     * El botón se sigue VIENDO inactivo mientras falte algo (pista visual sin
       tener que pulsarlo), pero SE PUEDE pulsar.
     * Al pulsarlo con algo pendiente NO se envía: aparece encima del botón un
       recuadro en la página (no una ventana) con la lista de motivos:
       «Falta: Tridente (pestaña Salario)», «Error: …». Cada línea lleva al campo.
     * Las pestañas con campos pendientes muestran cuántos tienen.
     * El recuadro se actualiza solo mientras el usuario corrige y desaparece al
       quedar todo bien.

   CÓMO FUNCIONA SIN TOCAR CADA FORMULARIO
   ---------------------------------------
   Las validaciones de Orbith (`validacion_visual.js` y las propias de algunas
   plantillas) apagan el botón con `boton.disabled = true`. Aquí se intercepta
   esa propiedad en cada botón: «apagado» pasa a ser la clase
   `orb-guardar-bloqueado`, que solo cambia el aspecto. Así ningún formulario
   necesita cambiar su lógica: siguen decidiendo CUÁNDO se puede guardar, y esta
   pieza solo explica POR QUÉ no.

   Los motivos se leen de los propios campos: los obligatorios vacíos (amarillo,
   `border-warning`) y los erróneos (rojo: `campo-invalido`, `is-invalid`,
   `border-danger`), con el texto de su etiqueta y, si lo hay, su mensaje de error.
   ========================================================================== */
(function () {
    'use strict';

    var CLASE = 'orb-guardar-bloqueado';
    var SELECTOR_FORM = 'form[data-validacion-visual], form[data-aviso-guardar]';
    var SELECTOR_PENDIENTE = '.border-warning:not(.campo-opcional), .campo-invalido, .is-invalid, .border-danger';

    function botonesDe(form) {
        var botones = Array.prototype.slice.call(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
        if (form.id) {
            botones = botones.concat(Array.prototype.slice.call(
                document.querySelectorAll('button[type="submit"][form="' + form.id + '"]')));
        }
        // Botón fuera del formulario y de tipo «button» (el modal de Baja):
        // se indica con `data-boton-guardar="#selector"`.
        var externo = form.getAttribute('data-boton-guardar');
        if (externo) {
            botones = botones.concat(Array.prototype.slice.call(document.querySelectorAll(externo)));
        }
        return botones;
    }

    /* `boton.disabled = x` deja de apagar el botón: pone o quita la clase. El
       atributo `disabled` escrito en el HTML se convierte igual al instalar. */
    function instalarEnBoton(boton, form) {
        if (boton.__orbAvisoGuardar) return;
        boton.__orbAvisoGuardar = true;
        boton.__orbForm = form;
        var inicial = boton.hasAttribute('disabled');
        boton.removeAttribute('disabled');
        Object.defineProperty(boton, 'disabled', {
            configurable: true,
            get: function () { return false; },
            set: function (valor) { marcar(boton, !!valor); },
        });
        marcar(boton, inicial);
        // Por si alguna validación usa el atributo en lugar de la propiedad.
        new MutationObserver(function () {
            if (boton.hasAttribute('disabled')) {
                boton.removeAttribute('disabled');
                marcar(boton, true);
            }
        }).observe(boton, { attributes: true, attributeFilter: ['disabled'] });
    }

    /* Bloqueos que no dependen de un campo (plaza sobregirada, 25-10-2026): un
       elemento con `data-bloqueo-guardar="motivo"` dentro del formulario deja
       Guardar inactivo mientras exista, diga lo que diga la validación propia. */
    function bloqueosDe(form) {
        return form ? Array.prototype.slice.call(form.querySelectorAll('[data-bloqueo-guardar]')) : [];
    }

    function marcar(boton, bloqueado) {
        bloqueado = bloqueado || bloqueosDe(boton.__orbForm).length > 0;
        boton.classList.toggle(CLASE, bloqueado);
        boton.setAttribute('aria-disabled', bloqueado ? 'true' : 'false');
        var form = boton.__orbForm;
        if (!form) return;
        if (!bloqueado) {
            quitarAviso(form);
        } else if (form.__orbAvisoVisible) {
            pintarAviso(form);   // ya estaba a la vista: se actualiza solo
        }
        contarEnPestanas(form);
    }

    /* ------------------------------------------------------------ motivos */

    function textoDeEtiqueta(campo, form) {
        var etiqueta = campo.id ? form.querySelector('label[for="' + campo.id + '"]') : null;
        if (!etiqueta) {
            var caja = campo.closest('.col, [class*="col-"], .mb-3, .form-group');
            etiqueta = caja ? caja.querySelector('label') : null;
        }
        var texto = etiqueta ? etiqueta.textContent : '';
        if (!texto.trim()) {
            // Plantillas que escriben la etiqueta como texto suelto junto al campo
            // (`{{ form.duracion.label }}` sin <label>): se toman esos textos.
            var caja2 = campo.closest('.col, [class*="col-"], .mb-3, .form-group');
            texto = caja2 ? Array.prototype.filter.call(caja2.childNodes, function (n) { return n.nodeType === 3; })
                .map(function (n) { return n.textContent; }).join(' ') : '';
        }
        if (!texto.trim()) texto = campo.getAttribute('placeholder') || campo.name || 'Campo';
        return texto.replace(/[*:]/g, '').replace(/\s+/g, ' ').trim();
    }

    function campoReal(elemento) {
        // Select2: lo pintado es `.select2-selection`; el campo es el <select> de antes.
        var contenedor = elemento.closest('.select2-container');
        if (contenedor && contenedor.previousElementSibling) return contenedor.previousElementSibling;
        if (elemento.matches('input, select, textarea')) return elemento;
        return elemento.querySelector('input, select, textarea');
    }

    function pestanaDe(campo, form) {
        var panel = campo.closest('.tab-pane');
        if (!panel || !panel.id) return null;
        var boton = form.querySelector('[data-bs-target="#' + panel.id + '"], [href="#' + panel.id + '"]');
        return boton ? { boton: boton, nombre: boton.textContent.replace(/\s+\d+$/, '').replace(/\s+/g, ' ').trim() } : null;
    }

    function motivos(form) {
        var vistos = [];
        var lista = bloqueosDe(form).map(function (el) {
            return { campo: el, tipo: 'Bloqueo', texto: el.getAttribute('data-bloqueo-guardar'), pestana: pestanaDe(el, form) };
        });
        form.querySelectorAll(SELECTOR_PENDIENTE).forEach(function (elemento) {
            var campo = campoReal(elemento);
            if (!campo || campo.type === 'hidden' || campo.disabled || vistos.indexOf(campo) !== -1) return;
            vistos.push(campo);
            // Rojo, o amarillo con un mensaje de error a la vista (la fecha de una
            // baja anterior al último evento): es un «Error». Si no, «Falta».
            var rojo = ['is-invalid', 'campo-invalido', 'border-danger'].some(function (c) {
                return elemento.classList.contains(c) || campo.classList.contains(c);
            });
            var mensaje = mensajeVisible(campo);
            if (rojo && !mensaje) mensaje = campo.validationMessage || 'el dato no es válido';
            lista.push({
                campo: campo,
                tipo: mensaje ? 'Error' : 'Falta',
                texto: textoDeEtiqueta(campo, form) + (mensaje ? ': ' + mensaje : ''),
                pestana: pestanaDe(campo, form),
            });
        });
        return lista;
    }

    /* El mensaje de error que la pantalla enseña junto al campo, si lo hay. El
       asterisco rojo de las etiquetas («Fecha *») no cuenta. */
    function mensajeVisible(campo) {
        var caja = campo.closest('.col, [class*="col-"], .mb-3, .form-group') || campo.parentElement;
        if (!caja) return '';
        var candidatos = caja.querySelectorAll('.invalid-feedback, .error-cronologico, .text-danger, .errorlist li');
        for (var i = 0; i < candidatos.length; i++) {
            var aviso = candidatos[i];
            if (aviso.closest('label')) continue;
            var texto = aviso.textContent.replace(/\s+/g, ' ').trim().replace(/^error\s*:\s*/i, '');
            var visible = aviso.offsetParent !== null || aviso.classList.contains('d-block');
            if (visible && texto.length > 1) return texto;
        }
        return '';
    }

    /* ------------------------------------------------------------ recuadro */

    function contenedorDelBoton(form) {
        var boton = botonesDe(form)[0];
        if (!boton) return null;
        return boton.closest('.modal-footer, .d-flex, .text-end, .card-footer') || boton.parentElement;
    }

    function pintarAviso(form) {
        var lista = motivos(form);
        var caja = form.__orbAviso;
        if (!caja) {
            caja = document.createElement('div');
            caja.className = 'orb-aviso-guardar alert alert-warning py-2 px-3 mb-2';
            caja.setAttribute('role', 'alert');
            caja.setAttribute('aria-live', 'polite');
            var ancla = contenedorDelBoton(form);
            if (!ancla) return;
            ancla.parentElement.insertBefore(caja, ancla);
            form.__orbAviso = caja;
        }
        form.__orbAvisoVisible = true;
        var html = '<div class="fw-semibold mb-1"><i class="bx bx-error-circle me-1"></i>No se puede guardar todavía</div>';
        if (!lista.length) {
            html += '<div class="small">Revise los campos marcados en amarillo o en rojo.</div>';
        } else {
            html += '<ul class="mb-0 ps-3 small">';
            lista.forEach(function (m, i) {
                html += '<li><a href="#" class="orb-aviso-ir" data-i="' + i + '"><b>' + m.tipo + ':</b> '
                      + escapar(m.texto) + (m.pestana ? ' <span class="text-muted">(pestaña ' + escapar(m.pestana.nombre) + ')</span>' : '')
                      + '</a></li>';
            });
            html += '</ul>';
        }
        caja.innerHTML = html;
        caja.querySelectorAll('.orb-aviso-ir').forEach(function (enlace) {
            enlace.addEventListener('click', function (e) {
                e.preventDefault();
                irAlCampo(lista[parseInt(enlace.dataset.i, 10)]);
            });
        });
    }

    function quitarAviso(form) {
        form.__orbAvisoVisible = false;
        if (form.__orbAviso) {
            form.__orbAviso.remove();
            form.__orbAviso = null;
        }
    }

    function irAlCampo(motivo) {
        if (!motivo) return;
        if (motivo.pestana && window.bootstrap) {
            bootstrap.Tab.getOrCreateInstance(motivo.pestana.boton).show();
        }
        setTimeout(function () {
            var visible = motivo.campo.nextElementSibling && motivo.campo.nextElementSibling.classList.contains('select2-container')
                ? motivo.campo.nextElementSibling : motivo.campo;
            visible.scrollIntoView({ block: 'center', behavior: 'smooth' });
            if (window.jQuery && jQuery(motivo.campo).hasClass('select2-hidden-accessible')) jQuery(motivo.campo).select2('open');
            else motivo.campo.focus();
        }, 200);
    }

    function contarEnPestanas(form) {
        var cuenta = {};
        var botones = {};
        motivos(form).forEach(function (m) {
            if (!m.pestana) return;
            var clave = m.pestana.boton.getAttribute('data-bs-target') || m.pestana.boton.getAttribute('href');
            cuenta[clave] = (cuenta[clave] || 0) + 1;
            botones[clave] = m.pestana.boton;
        });
        form.querySelectorAll('.orb-aviso-cuenta').forEach(function (b) { b.remove(); });
        Object.keys(cuenta).forEach(function (clave) {
            var marca = document.createElement('span');
            marca.className = 'orb-aviso-cuenta badge rounded-pill bg-warning text-dark ms-1';
            marca.textContent = cuenta[clave];
            marca.title = cuenta[clave] + (cuenta[clave] === 1 ? ' campo pendiente' : ' campos pendientes');
            botones[clave].appendChild(marca);
        });
    }

    function escapar(texto) {
        return String(texto).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    /* ------------------------------------------------------------ envío */

    // Fase de captura: se adelanta a los manejadores de cada plantilla.
    document.addEventListener('click', function (e) {
        var boton = e.target.closest && e.target.closest('.' + CLASE);
        if (!boton || !boton.__orbForm) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        pintarAviso(boton.__orbForm);
    }, true);

    document.addEventListener('submit', function (e) {
        var form = e.target;
        var bloqueado = form.matches && form.matches(SELECTOR_FORM)
            && botonesDe(form).some(function (b) { return b.classList.contains(CLASE); });
        if (!bloqueado) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        pintarAviso(form);
    }, true);

    // Mientras el recuadro está a la vista, se recalcula con cada cambio.
    ['input', 'change'].forEach(function (evento) {
        document.addEventListener(evento, function (e) {
            var form = e.target.closest && e.target.closest(SELECTOR_FORM);
            if (!form) return;
            setTimeout(function () {
                if (form.__orbAvisoVisible) pintarAviso(form);
                contarEnPestanas(form);
            }, 60);
        }, true);
    });

    /* ------------------------------------------------------------ arranque */

    function instalarEn(raiz) {
        (raiz.querySelectorAll ? raiz : document).querySelectorAll(SELECTOR_FORM).forEach(function (form) {
            botonesDe(form).forEach(function (boton) { instalarEnBoton(boton, form); });
        });
    }

    var estilo = document.createElement('style');
    estilo.textContent = '.' + CLASE + '{opacity:.55;cursor:help;}'
        + '.orb-aviso-guardar ul a{color:var(--bs-heading-color, var(--bs-body-color));text-decoration:none;}'
        + '.orb-aviso-guardar ul a b{color:var(--bs-warning-text-emphasis, #997404);}'
        + '.orb-aviso-guardar ul a:hover{text-decoration:underline;}';
    document.head.appendChild(estilo);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { instalarEn(document); });
    } else {
        instalarEn(document);
    }
    document.addEventListener('htmx:afterSettle', function (e) { instalarEn(e.target); });
    document.addEventListener('shown.bs.modal', function (e) { instalarEn(e.target); });
    // Formularios que llegan por jQuery `.load()` o se reemplazan tras un error.
    new MutationObserver(function (cambios) {
        cambios.forEach(function (c) {
            c.addedNodes.forEach(function (nodo) {
                if (nodo.nodeType === 1) instalarEn(nodo.matches && nodo.matches(SELECTOR_FORM) ? nodo.parentElement || document : nodo);
            });
        });
    }).observe(document.documentElement, { childList: true, subtree: true });

    window.OrbithAvisoGuardar = { instalarEn: instalarEn, motivos: motivos };
})();
