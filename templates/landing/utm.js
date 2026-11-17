// Trovefy · reenvía utm_* y fbclid de la página a cada botón de checkout (plan 18). Sin red ni temporizadores.
(function () {
  var pagina = new URLSearchParams(window.location.search);
  var pares = [];
  pagina.forEach(function (valor, clave) {
    if (clave === "fbclid" || clave.indexOf("utm_") === 0) pares.push([clave, valor]);
  });
  if (!pares.length) return;
  document.querySelectorAll("a[data-tf-checkout]").forEach(function (a) {
    var original = a.getAttribute("href") || "";
    var url = new URL(original, window.location.href);
    var cambia = false;
    pares.forEach(function (par) {
      if (!url.searchParams.has(par[0])) { url.searchParams.append(par[0], par[1]); cambia = true; }
    });
    if (!cambia) return;
    var relativa = original.charAt(0) === "/" && original.charAt(1) !== "/";
    a.setAttribute("href", relativa ? url.pathname + url.search + url.hash : url.href);
  });
})();
