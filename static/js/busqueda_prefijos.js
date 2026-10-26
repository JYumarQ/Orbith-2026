/*
 * Ayuda y avisos de la búsqueda con prefijos (E:, N:, CI:, CA:, U:, COD:).
 *
 * Se activa en cualquier buscador con `data-prefijos="E,N,CI"` (los que entiende
 * esa pantalla) y `data-pantalla="Contratos"` (para el aviso):
 *
 *   - Añade un botón «?» junto al buscador con la ayuda: qué prefijos valen ahí,
 *     con un ejemplo de cada uno, y cómo se combinan.
 *   - Mientras se escribe, si aparece un prefijo que esa pantalla no entiende,
 *     muestra un aviso pequeño debajo. El servidor ya lo ignora (no filtra nada);
 *     esto solo lo explica, sin hacer ninguna petición.
 *
 * La lista y los textos son los de `core/busqueda.py::PREFIJOS`: si se añade o se
 * cambia un prefijo allí, hay que traerlo aquí también.
 */
(function () {
  const PREFIJOS = {
    E: ['Expediente', 'E:8855'],
    N: ['Nombre y/o apellidos', 'N:Juan Pérez'],
    CI: ['Carnet de identidad (vale el principio)', 'CI:85010112345'],
    CA: ['Cargo', 'CA:ayudante'],
    U: ['Unidad organizativa (vale parte del nombre)', 'U:flor'],
    COD: ['Código de regla de Subsanación (vale el principio)', 'COD:CTR-011'],
  };
  const PATRON = /(?:^|\s)(COD|CI|CA|E|N|U):/gi;

  function ayudaHtml(validos) {
    const filas = validos.map(function (clave) {
      const p = PREFIJOS[clave];
      return '<tr><td class="fw-bold pe-2">' + clave + ':</td><td>' + p[0] +
        '<div class="text-muted"><code>' + p[1] + '</code></div></td></tr>';
    }).join('');
    // El ejemplo de combinar usa solo prefijos de esta pantalla (en Aspirantes no hay U:).
    const ejemplo = validos.indexOf('U') >= 0 ? 'N:Juan U:Florida' : 'N:Juan CI:85';
    return '<table class="mb-2" style="font-size:.8rem">' + filas + '</table>' +
      '<div style="font-size:.75rem" class="text-muted">' +
      'Se pueden combinar: <code>' + ejemplo + '</code>. Cada prefijo abarca hasta el ' +
      'siguiente. Lo escrito antes del primer prefijo se busca como siempre. ' +
      'Da igual mayúsculas o acentos.</div>';
  }

  function prefijosEscritos(texto) {
    const encontrados = new Set();
    let m;
    PATRON.lastIndex = 0;
    while ((m = PATRON.exec(texto)) !== null) encontrados.add(m[1].toUpperCase());
    return Array.from(encontrados);
  }

  function preparar(input) {
    if (input.dataset.prefijosListo) return;
    input.dataset.prefijosListo = '1';
    const validos = (input.dataset.prefijos || '').split(',').map(function (s) {
      return s.trim().toUpperCase();
    }).filter(function (s) { return PREFIJOS[s]; });
    const pantalla = input.dataset.pantalla || 'esta pantalla';
    const grupo = input.closest('.input-group') || input.parentElement;

    // Botón «?» con la ayuda, al final del propio grupo del buscador.
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'input-group-text border-0 bg-transparent text-muted';
    boton.title = 'Cómo buscar';
    boton.setAttribute('aria-label', 'Cómo buscar con prefijos');
    boton.innerHTML = '<i class="bx bx-help-circle"></i>';
    grupo.appendChild(boton);
    if (window.bootstrap && bootstrap.Popover) {
      new bootstrap.Popover(boton, {
        html: true, trigger: 'focus', placement: 'bottom', sanitize: false,
        title: 'Búsqueda con prefijos', content: ayudaHtml(validos),
      });
    }

    // Aviso de prefijos que aquí no se aplican.
    const aviso = document.createElement('div');
    aviso.className = 'small text-warning mt-1 d-none';
    aviso.style.fontSize = '.75rem';
    grupo.insertAdjacentElement('afterend', aviso);

    function revisar() {
      const ajenos = prefijosEscritos(input.value).filter(function (p) {
        return validos.indexOf(p) === -1;
      });
      if (!ajenos.length) {
        aviso.classList.add('d-none');
        return;
      }
      aviso.textContent = ajenos.map(function (p) { return p + ':'; }).join(', ') +
        (ajenos.length === 1 ? ' no se aplica' : ' no se aplican') + ' en ' + pantalla +
        ': no filtra nada.';
      aviso.classList.remove('d-none');
    }
    input.addEventListener('input', revisar);
    revisar();
  }

  function prepararTodo(raiz) {
    (raiz || document).querySelectorAll('input[data-prefijos]').forEach(preparar);
  }

  document.addEventListener('DOMContentLoaded', function () { prepararTodo(); });
  // Los paneles que llegan por HTMX (Subsanación) traen su propio buscador.
  document.addEventListener('htmx:afterSwap', function (e) { prepararTodo(e.target); });
})();
