"""Cierre del checkout: el país pasa de ``con_landing`` a ``con_checkout`` (plan 19, Tarea 16).

**Qué hacen los vídeos:** «no lanzar sin píxel + checkout verificados» (V2 0:19:45) y el checklist final con lo
verificado y lo pendiente (V1 1:14:15).

Siete requisitos, en este orden (`REQUISITOS`); cada uno es ``True`` (verde), ``False`` (falla), ``None`` («no
medido: <motivo>») o una `ExcepcionAprobada`:

1. ``tracking verificado``: ``TRACKING.md`` en ``verificado``;
2. ``dataset en límites del ejecutor``: lo que dejó el ejecutor (dataset y página permitidos, y lo lee);
3. ``checkout completo``: ``CHECKOUT.md`` en ``completo`` y cada ajuste con fuente ``mcp``, ``fuera`` o ``captura``;
4. ``embudo demo ok``: ``embudo.md`` en ``ok``;
5. ``compra de prueba registrada``: ``paises.<PAIS>.compra_prueba`` vista en la plataforma (MCP o captura), o la
   captura o el texto del pedido que pegó el usuario (resolución 31); su palabra sola no basta;
6. ``reembolso registrado``: ``compra_prueba.reembolso.procesado`` o la captura del reembolso;
7. ``esquema de pedidos``: ``config/esquemas/impultienda-pedidos.yaml``; «no medido (P-20)» no bloquea.

**Excepciones aprobadas por el usuario** (no por Claude): un requisito que no está en verde puede cerrarse igual si
el usuario lo aprueba con sus palabras literales. Se registra en
``productos/<p-id>/decisiones/<AAAA-MM-DD>-excepcion-<clave>.md`` (como la excepción de R16 de
`trovefy.modelar.aprobacion`) con ``pais``, ``requisito``, ``motivo`` y ``palabras_del_usuario``. Nunca cuenta como
verde: `requisitos_checkout` devuelve una `ExcepcionAprobada` (falsa en un ``if``, distinta de ``True``), `cerrar` la
acepta como no bloqueante y la lista en la evidencia de ``avanzar_estado`` y en ``log.md``. ``checkout completo`` y
``compra de prueba registrada`` no admiten excepción (`SIN_EXCEPCION`): sin checkout armado ni una compra real no
hay nada que vender.

Solo lee el vault, salvo `registrar_excepcion` (la decisión) y `cerrar` (el estado, con
``trovefy.vault.producto.avanzar_estado``, resolución 1).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import yaml

from trovefy.embudo.contexto import EstadoIncorrecto
from trovefy.embudo.pegado import indice
from trovefy.tracking.salida import leer_tracking
from trovefy.vault import frontmatter
from trovefy.vault.escritura import ZONA_NEGOCIO, anadir_log, escribir_atomico
from trovefy.vault.producto import (
    avanzar_estado,
    estado_pais,
    ruta_producto,
    secreto_en,
)

TRACKING = "tracking verificado"
EJECUTOR = "dataset en límites del ejecutor"
CHECKOUT = "checkout completo"
EMBUDO = "embudo demo ok"
COMPRA = "compra de prueba registrada"
REEMBOLSO = "reembolso registrado"
ESQUEMA = "esquema de pedidos"
REQUISITOS: tuple[str, ...] = (TRACKING, EJECUTOR, CHECKOUT, EMBUDO, COMPRA, REEMBOLSO, ESQUEMA)
SIN_EXCEPCION = frozenset({CHECKOUT, COMPRA})
FUENTES_CHECKOUT = ("mcp", "fuera", "captura")
RUTA_ESQUEMA = ("config", "esquemas", "impultienda-pedidos.yaml")
_PRUEBAS_PEGADAS = ("captura", "texto")  # lo que pega el usuario; su palabra sola («dicho») no basta
_DECISION = "excepcion_checkout"
_SKILL = "checkout"
_PAIS = re.compile(r"[A-Z]{2}")


@dataclass(frozen=True)
class ExcepcionAprobada:
    """Un requisito que no está en verde y que el usuario aprobó cerrar igual. Nunca es verde: es falsa en un
    ``if`` y distinta de ``True``; quien la acepte tiene que preguntarlo con ``isinstance``."""

    requisito: str
    palabras: str
    motivo: str
    ruta: str  # relativa al vault
    fecha: str

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"excepción aprobada: «{self.palabras}»"


Estado = bool | None | ExcepcionAprobada


# --- claves de los requisitos ------------------------------------------------------------------------------------


def clave(requisito: str) -> str:
    """La clave para el nombre del archivo: «dataset en límites del ejecutor» → ``dataset-en-limites-del-ejecutor``."""
    t = unicodedata.normalize("NFKD", requisito.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return "-".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def resolver_requisito(texto: object) -> str:
    """El requisito por su nombre (``tracking verificado``) o su clave (``tracking-verificado``); ``ValueError``
    si no es ninguno de los siete."""
    if isinstance(texto, str) and texto.strip():
        buscado = clave(texto)
        for r in REQUISITOS:
            if clave(r) == buscado:
                return r
    raise ValueError(f"requisito desconocido «{texto}»: usa uno de " + ", ".join(f"«{r}»" for r in REQUISITOS))


def _pais(pais: str) -> str:
    codigo = pais.strip().upper() if isinstance(pais, str) else ""
    if not _PAIS.fullmatch(codigo):
        raise ValueError(f"país mal escrito: «{pais}»; usa su código de dos letras (por ejemplo BG)")
    return codigo


def _con_zona(ahora: datetime | None) -> datetime:
    if ahora is None:
        return datetime.now(ZONA_NEGOCIO)
    if not isinstance(ahora, datetime) or ahora.utcoffset() is None:
        raise ValueError(f"ahora sin zona horaria: {ahora!r}")
    return ahora.astimezone(ZONA_NEGOCIO)


# --- excepciones ---------------------------------------------------------------------------------------------------


def _texto_obligatorio(valor: object, que: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"faltan {que}")
    c1 = sorted({f"U+{ord(c):04X}" for c in valor if 0x80 <= ord(c) <= 0x9F})
    if c1:
        raise ValueError(f"{que} llevan caracteres de control ({', '.join(c1)}), que no se ven al leerlas: "
                         "escríbelas de nuevo sin ellos")
    patron = secreto_en(valor)
    if patron:
        raise ValueError(f"{que}: aparece algo con forma de secreto ({patron}); no se guarda nada")
    return valor.strip()


def _destino(carpeta: Path, hoy: date, sufijo: str) -> Path:
    """``AAAA-MM-DD-<sufijo>.md`` es siempre la última del día; una anterior del mismo día pasa a
    ``AAAA-MM-DD-N-<sufijo>.md`` (mismo criterio que las decisiones de ``/modelar``)."""
    ruta = carpeta / f"{hoy.isoformat()}-{sufijo}.md"
    if ruta.exists():
        n = 1
        while (carpeta / f"{hoy.isoformat()}-{n}-{sufijo}.md").exists():
            n += 1
        ruta.rename(carpeta / f"{hoy.isoformat()}-{n}-{sufijo}.md")
    return ruta


def registrar_excepcion(vault: Path, producto: str, pais: str, requisito: str, palabras: str | None, motivo: str,
                        ahora: datetime | None = None) -> Path:
    """Escribe ``decisiones/<AAAA-MM-DD>-excepcion-<clave>.md``: el usuario aprueba cerrar el checkout sin ese
    requisito en verde. ``ValueError`` sin escribir nada si el requisito no existe o no admite excepción
    (`SIN_EXCEPCION`), si faltan las palabras literales del usuario o el motivo, o si llevan un secreto.

    Que las palabras sean de verdad del usuario lo comprueba la CLI (`trovefy checkout excepcion`) antes de llamar."""
    vault = Path(vault)
    ahora = _con_zona(ahora)
    pais = _pais(pais)
    nombre = resolver_requisito(requisito)
    if nombre in SIN_EXCEPCION:
        raise ValueError(f"«{nombre}» no admite excepción: sin checkout armado y una compra real comprobada no se "
                         "puede vender; hay que completarlo")
    palabras = _texto_obligatorio(palabras, "las palabras literales del usuario (--dicho)")
    motivo = _texto_obligatorio(motivo, "el motivo de la excepción (--motivo)")
    ruta_prod = ruta_producto(vault, producto)
    if not ruta_prod.is_file():
        raise FileNotFoundError(f"no existe productos/{producto}/PRODUCTO.md")
    hoy = ahora.date()
    meta = {"tipo": "decision", "decision": _DECISION, "fecha": hoy.isoformat(),
            "registrada": ahora.isoformat(timespec="seconds"), "fuente": "usuario", "producto": producto,
            "pais": pais, "requisito": nombre, "motivo": motivo, "palabras_del_usuario": palabras}
    lineas = [f"# Excepción aprobada · {nombre} · {producto} · {pais} ({hoy.isoformat()})", "",
              (f"El requisito «{nombre}» del cierre del checkout no está en verde y el usuario aprueba cerrar igual. "
               "No cuenta como verde: el cierre lo lista como excepción."), "",
              f"Motivo: {motivo}", "",
              "Palabras del usuario (cita literal):", "",
              *(f"> {x}" if x else ">" for x in palabras.split("\n")), ""]
    texto = frontmatter.renderizar(meta, "\n".join(lineas))
    patron = secreto_en(meta) or secreto_en(texto)
    if patron:
        raise ValueError(f"la excepción lleva algo con forma de secreto ({patron}); no se guarda nada")
    carpeta = ruta_prod.parent / "decisiones"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = _destino(carpeta, hoy, f"excepcion-{clave(nombre)}")
    escribir_atomico(destino, texto)
    anadir_log(vault, _SKILL, f"{producto} {pais}: excepción aprobada por el usuario en «{nombre}»",
               [destino.relative_to(vault).as_posix()], ahora=ahora)
    return destino


def _fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return None
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and len(valor) == 10:
        try:
            return date.fromisoformat(valor)
        except ValueError:
            return None
    return None


def excepciones(vault: Path, producto: str, pais: str) -> dict[str, ExcepcionAprobada]:
    """Las excepciones válidas del producto-país, la más reciente por requisito. Vale solo una completa:
    ``tipo: decision``, ``decision: excepcion_checkout``, ``fuente: usuario``, el producto y el país, un requisito que
    admite excepción, ``motivo`` y ``palabras_del_usuario`` no vacíos y una ``fecha`` AAAA-MM-DD. Lo ilegible se
    salta."""
    vault = Path(vault)
    pais = _pais(pais)
    carpeta = ruta_producto(vault, producto).parent / "decisiones"
    candidatas: dict[str, tuple] = {}
    for ruta in sorted(carpeta.glob("*-excepcion-*.md")) if carpeta.is_dir() else ():
        try:
            meta, _ = frontmatter.leer(ruta)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(meta, dict):
            continue
        if (meta.get("tipo"), meta.get("decision"), meta.get("fuente")) != ("decision", _DECISION, "usuario"):
            continue
        if meta.get("producto") != producto or meta.get("pais") != pais:
            continue
        requisito = meta.get("requisito")
        if requisito not in REQUISITOS or requisito in SIN_EXCEPCION:
            continue
        palabras, motivo = meta.get("palabras_del_usuario"), meta.get("motivo")
        if not (isinstance(palabras, str) and palabras.strip() and isinstance(motivo, str) and motivo.strip()):
            continue
        fecha = _fecha(meta.get("fecha"))
        if fecha is None:
            continue
        orden = (fecha.isoformat(), str(meta.get("registrada") or ""), ruta.name)
        x = ExcepcionAprobada(requisito, palabras.strip(), motivo.strip(), ruta.relative_to(vault).as_posix(),
                              fecha.isoformat())
        if requisito not in candidatas or orden > candidatas[requisito][0]:
            candidatas[requisito] = (orden, x)
    return {r: x for r, (_, x) in candidatas.items()}


# --- los siete requisitos --------------------------------------------------------------------------------------------


def _carpeta_pais(vault: Path, producto: str, pais: str) -> Path:
    return ruta_producto(vault, producto).parent / "checkout" / pais


def _leer_meta(ruta: Path) -> tuple[dict | None, str, str | None]:
    """``(meta, cuerpo, problema)``: ``problema`` si el archivo no se puede leer."""
    try:
        meta, cuerpo = frontmatter.leer(ruta)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        return None, "", f"{ruta.name} no se puede leer ({type(exc).__name__})"
    if not isinstance(meta, dict):
        return None, "", f"{ruta.name} no tiene frontmatter"
    return meta, cuerpo, None


def _req_tracking(t) -> tuple[Estado, str]:
    if t is None:
        return None, "no medido: falta checkout/<PAIS>/TRACKING.md (/trovefy:tracking)"
    if t.estado == "verificado":
        return True, f"verificado (dataset {t.dataset_id}, eventos {t.fuente_eventos}, CAPI {t.capi})"
    motivos = [m for m in t.motivos if m]
    return False, f"estado {t.estado}" + (f": {'; '.join(motivos)}" if motivos else "")


def _req_ejecutor(t) -> tuple[Estado, str]:
    if t is None:
        return None, "no medido: falta TRACKING.md (/trovefy:tracking)"
    e = t.ejecutor
    if e is None:
        return None, ("no medido: el ejecutor aún no lo comprobó (trovefy tracking ejecutor, y los comandos que "
                      "ejecutas tú)")
    faltan = [que for que, k in (("el dataset no está en límites", "dataset_permitido"),
                                 ("la página no está en límites", "pagina_permitida"),
                                 ("el ejecutor no lo lee", "lectura_ok")) if e.get(k) is not True]
    if faltan:
        return False, "; ".join(faltan) + f" ({e.get('fecha')})"
    return True, f"dataset y página en límites; el ejecutor lo lee ({e.get('fecha')})"


def _filas_checkout(cuerpo: str) -> list[tuple[str, str]]:
    """``(ajuste, fuente)`` de cada fila de la tabla de ``CHECKOUT.md``."""
    filas: list[tuple[str, str]] = []
    dentro = False
    for linea in cuerpo.splitlines():
        texto = linea.strip()
        if not texto.startswith("|"):
            if dentro:
                break
            continue
        celdas = [c.strip() for c in texto.strip("|").split("|")]
        if celdas[:4] == ["ajuste", "pedido", "releído", "fuente"]:
            dentro = True
            continue
        if not dentro or set("".join(celdas)) <= set("-: "):
            continue
        if len(celdas) >= 4:
            filas.append((celdas[0], celdas[3]))
    return filas


def _req_checkout(carpeta: Path) -> tuple[Estado, str]:
    ruta = carpeta / "CHECKOUT.md"
    if not ruta.is_file():
        return None, "no medido: falta CHECKOUT.md (trovefy checkout releer / comprobar)"
    meta, cuerpo, problema = _leer_meta(ruta)
    if problema:
        return False, problema
    estado = meta.get("estado")
    if estado != "completo":
        return False, f"CHECKOUT.md en «{estado}»: lee sus secciones «A medias» y «A mano»"
    filas = _filas_checkout(cuerpo)
    if not filas:
        return False, "CHECKOUT.md no trae la tabla de ajustes"
    flojos = [f"{a} ({f})" for a, f in filas if f not in FUENTES_CHECKOUT]
    if flojos:
        return False, ("ajustes sin evidencia fuerte (mcp, fuera o captura): " + ", ".join(flojos)
                       + "; tu palabra sola no basta: pega una captura o compruébalo desde fuera")
    return True, f"completo; {len(filas)} ajustes con fuente mcp, fuera o captura"


def _req_embudo(carpeta: Path) -> tuple[Estado, str]:
    ruta = carpeta / "embudo.md"
    if not ruta.is_file():
        return None, "no medido: falta embudo.md (trovefy checkout demo)"
    meta, _, problema = _leer_meta(ruta)
    if problema:
        return False, problema
    estado = meta.get("estado")
    return (True, "recorrido demo ok") if estado == "ok" else (False, f"recorrido demo en «{estado}» (embudo.md)")


def _compra_prueba(vault: Path, producto: str, pais: str) -> dict:
    meta, _, problema = _leer_meta(ruta_producto(vault, producto))
    if problema:
        return {}
    paises = meta.get("paises")
    bloque = paises.get(pais) if isinstance(paises, dict) else None
    compra = bloque.get("compra_prueba") if isinstance(bloque, dict) else None
    return compra if isinstance(compra, dict) else {}


def _pegados(vault: Path, producto: str, pais: str, clave_pegado: str) -> list:
    try:
        return indice(vault, SimpleNamespace(vault=vault, producto=producto, pais=pais)).get(clave_pegado, [])
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return []


def _por_pegado(vault: Path, producto: str, pais: str, clave_pegado: str, que: str) -> tuple[Estado, str]:
    pegados = _pegados(vault, producto, pais, clave_pegado)
    fuertes = [p for p in pegados if p.tipo in _PRUEBAS_PEGADAS]
    if fuertes:
        return True, f"{que}: {fuertes[-1].tipo} que pegaste ({fuertes[-1].ruta})"
    if pegados:
        return False, (f"{que}: solo tu palabra (dicho, {pegados[-1].ruta}); falta verlo en la plataforma (MCP) o "
                       f"una captura: trovefy checkout evidencia --clave {clave_pegado} --desde <captura>")
    return None, f"no medido: {que} sin registrar (MCP o trovefy checkout evidencia --clave {clave_pegado})"


def _req_compra(vault: Path, producto: str, pais: str, compra: dict) -> tuple[Estado, str]:
    plataforma = compra.get("plataforma") if isinstance(compra.get("plataforma"), dict) else {}
    if compra.get("pedido") and plataforma.get("visto") is True and plataforma.get("fuente") in ("mcp", "captura"):
        return True, f"pedido {compra['pedido']} visto en la plataforma ({plataforma.get('fuente')})"
    return _por_pegado(vault, producto, pais, "pedido", "la compra de prueba")


def _req_reembolso(vault: Path, producto: str, pais: str, compra: dict) -> tuple[Estado, str]:
    reembolso = compra.get("reembolso") if isinstance(compra.get("reembolso"), dict) else {}
    if reembolso.get("procesado") is True:
        return True, f"reembolso procesado ({reembolso.get('fecha')}, {reembolso.get('evidencia')})"
    return _por_pegado(vault, producto, pais, "reembolso", "el reembolso")


def _req_esquema(vault: Path) -> tuple[Estado, str]:
    ruta = vault.joinpath(*RUTA_ESQUEMA)
    if not ruta.is_file():
        return None, ("no medido (P-20): falta config/esquemas/impultienda-pedidos.yaml (trovefy checkout "
                      "esquema-pedidos); no bloquea")
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return False, f"impultienda-pedidos.yaml no se puede leer ({type(exc).__name__})"
    if not isinstance(datos, dict) or not datos:
        return False, "impultienda-pedidos.yaml está vacío o no es un mapa"
    return True, f"esquema de pedidos ({datos.get('fuente') or 'sin fuente'}, {datos.get('fecha') or 'sin fecha'})"


def _no_bloquea(nombre: str, estado: Estado) -> bool:
    return estado is True or isinstance(estado, ExcepcionAprobada) or (nombre == ESQUEMA and estado is None)


def requisitos_checkout(vault: Path, producto: str, pais: str) -> list[tuple[str, Estado, str]]:
    """Los siete requisitos del cierre (`REQUISITOS`, en orden): ``(nombre, estado, detalle)``. Un requisito que
    no está en verde pero tiene una excepción válida del usuario sale como `ExcepcionAprobada`, con el detalle
    «excepción aprobada: «<palabras>» …» y lo que tenía debajo. No escribe nada."""
    vault = Path(vault)
    pais = _pais(pais)
    carpeta = _carpeta_pais(vault, producto, pais)
    try:
        t = leer_tracking(vault, producto, pais)
        roto = None
    except (ValueError, OSError, yaml.YAMLError) as exc:
        t, roto = None, f"TRACKING.md no se puede leer: {exc}"
    compra = _compra_prueba(vault, producto, pais)
    base = {
        TRACKING: (False, roto) if roto else _req_tracking(t),
        EJECUTOR: (False, roto) if roto else _req_ejecutor(t),
        CHECKOUT: _req_checkout(carpeta),
        EMBUDO: _req_embudo(carpeta),
        COMPRA: _req_compra(vault, producto, pais, compra),
        REEMBOLSO: _req_reembolso(vault, producto, pais, compra),
        ESQUEMA: _req_esquema(vault),
    }
    aprobadas = excepciones(vault, producto, pais)
    salida: list[tuple[str, Estado, str]] = []
    for nombre in REQUISITOS:
        estado, detalle = base[nombre]
        x = aprobadas.get(nombre)
        if x is not None and not _no_bloquea(nombre, estado):
            salida.append((nombre, x, f"{x} ({x.ruta}); motivo: {x.motivo}; sin la excepción: {detalle}"))
        else:
            salida.append((nombre, estado, detalle))
    return salida


def etiqueta(nombre: str, estado: Estado) -> str:
    """Cómo se lee cada estado: ``ok``, ``falla``, ``no medido`` o ``excepción`` (nunca verde)."""
    if isinstance(estado, ExcepcionAprobada):
        return "excepción"
    if estado is True:
        return "ok"
    if estado is None:
        return "no medido" + (", no bloquea" if nombre == ESQUEMA else "")
    return "falla"


def _evidencia(nombre: str, estado: Estado, detalle: str) -> str:
    if isinstance(estado, ExcepcionAprobada):
        return (f"{nombre}: excepción aprobada por el usuario, no es verde: «{estado.palabras}» "
                f"({estado.ruta}); motivo: {estado.motivo}")
    if estado is True:
        return f"{nombre}: ok — {detalle}"
    return f"{nombre}: {detalle}"


def cerrar(vault: Path, producto: str, pais: str, ahora: datetime | None = None) -> str:
    """Pasa el país de ``con_landing`` a ``con_checkout`` si los siete requisitos no bloquean (verde, excepción del
    usuario donde se admite, o el esquema de pedidos «no medido (P-20)»). ``EstadoIncorrecto`` si el país no está en
    ``con_landing``; ``ValueError`` con lo que falta si algo bloquea. En los dos casos no escribe nada. Devuelve el
    resumen para el usuario."""
    vault = Path(vault)
    ahora = _con_zona(ahora)
    pais = _pais(pais)
    actual = estado_pais(vault, producto, pais)
    if actual != "con_landing":
        raise EstadoIncorrecto(f"{producto} {pais} está en «{actual or 'sin estado'}»: el cierre del checkout solo "
                               "avanza desde «con_landing»")
    reqs = requisitos_checkout(vault, producto, pais)
    faltan = [f"- {n} [{etiqueta(n, e)}]: {d}" for n, e, d in reqs if not _no_bloquea(n, e)]
    if faltan:
        raise ValueError("el checkout no se cierra; falta:\n" + "\n".join(faltan))
    evidencia = [_evidencia(n, e, d) for n, e, d in reqs]
    avanzar_estado(vault, producto, pais, desde="con_landing", hacia="con_checkout", evidencia=evidencia,
                   skill=_SKILL, ahora=ahora)
    aprobadas = [e for _, e, _ in reqs if isinstance(e, ExcepcionAprobada)]
    que = f"{producto} {pais}: checkout cerrado (con_checkout); " + (
        "excepciones aprobadas: " + ", ".join(x.requisito for x in aprobadas) if aprobadas else "todo en verde")
    anadir_log(vault, _SKILL, que,
               [*(x.ruta for x in aprobadas), ruta_producto(vault, producto).relative_to(vault).as_posix()],
               ahora=ahora)
    lineas = [f"{producto} {pais}: con_landing → con_checkout."]
    lineas += [f"  [{etiqueta(n, e)}] {n}: {d}" for n, e, d in reqs]
    if aprobadas:
        lineas.append("Ojo: " + ", ".join(f"«{x.requisito}»" for x in aprobadas)
                      + " no está en verde; se cierra por tu excepción.")
    return "\n".join(lineas)
