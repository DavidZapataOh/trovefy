// Trovefy · aviso de cookies propio: Microsoft Clarity solo tras «aceptar» (plan 19, Tarea 7; regla europea).
// Antes de aceptar no se pide nada a ningún tercero. La elección se guarda en este navegador y se puede cambiar.
(function () {
  var aviso = document.getElementById("tf-consentimiento");
  if (!aviso) return;
  var proyecto = aviso.getAttribute("data-tf-clarity") || "";
  var CLAVE = "tf-consentimiento";
  function leer() {
    try { return window.localStorage.getItem(CLAVE); } catch (e) { return null; }
  }
  function guardar(valor) {
    try { window.localStorage.setItem(CLAVE, valor); } catch (e) { /* sin almacenamiento: se pregunta otra vez */ }
  }
  function cargar() {
    if (!/^[a-z0-9]{6,20}$/.test(proyecto) || window.clarity) return;
    window.clarity = function () { (window.clarity.q = window.clarity.q || []).push(arguments); };
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.clarity.ms/tag/" + proyecto;
    document.head.appendChild(s);
  }
  function dominios() {
    // Clarity pone sus cookies en el dominio raíz: se borran en el host y en cada dominio padre.
    var partes = window.location.hostname.split(".");
    var lista = [""];
    if (/^[0-9.]+$/.test(window.location.hostname) || partes.length < 2) return lista;
    for (var i = 0; i < partes.length - 1; i++) lista.push("; domain=." + partes.slice(i).join("."));
    return lista;
  }
  function borrarCookies() {
    var ds = dominios();
    ["_clck", "_clsk", "CLID", "ANONCHK", "MR", "MUID", "SM"].forEach(function (n) {
      ds.forEach(function (d) {
        document.cookie = n + "=; Max-Age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/" + d;
      });
    });
  }
  function retirar() {
    // Primero se le dice a Clarity que ya no hay consentimiento (deja de escribir cookies), después se borran.
    try { if (typeof window.clarity === "function") window.clarity("consent", false); } catch (e) { /* sigue */ }
    borrarCookies();
    window.location.reload();
  }
  function elegir(valor) {
    var antes = leer();
    guardar(valor);
    aviso.hidden = true;
    if (valor === "si") cargar();
    else if (antes === "si") retirar();
  }
  aviso.querySelectorAll("[data-tf-consentimiento]").forEach(function (b) {
    b.addEventListener("click", function () { elegir(b.getAttribute("data-tf-consentimiento")); });
  });
  document.querySelectorAll("[data-tf-consentimiento-cambiar]").forEach(function (a) {
    a.addEventListener("click", function (ev) { ev.preventDefault(); aviso.hidden = false; });
  });
  var elegido = leer();
  if (elegido === "si") cargar();
  else if (elegido !== "no") aviso.hidden = false;
})();
