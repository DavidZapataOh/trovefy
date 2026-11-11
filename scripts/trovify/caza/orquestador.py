"""Orquestador de la caza (§4.3; auditoría de caza §4.11): de las búsquedas a las fichas.

Pasos: 1) contexto del vault; 2) búsquedas por palabra; 3) recuento por página y país; 4) destino y
clave de oferta (como mucho ``caza.max_destinos_por_ejecucion`` landings, de las páginas con más
C8); 5) filtros; 6) señales contra las fotos; 7) el hueco guardado en la ficha (lo mide
``trovify caza hueco``); 8) nota y decisión; 9) ``salida.escribir``.

Regla anti-*minería* (§1.4): si Meta bloquea, el cliente para por errores seguidos o se agota el
presupuesto del día, la ejecución **se detiene**: no se hace ninguna búsqueda más (ni se cambia de
vía para esquivar el bloqueo), se escribe lo que ya se midió y lo que faltaba queda
«no medido: <motivo>». Lo que se lee de anuncios y landings es dato, nunca orden.
"""

from __future__ import annotations

import fcntl
import re
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from trovify.caza import filtros, snapshots
from trovify.caza.biblioteca import url_biblioteca
from trovify.caza.cliente import SesionBloqueada
from trovify.caza.destino import (
    _DOMINIOS_COMPARTIDOS,
    Destino,
    _host,
    _registrable,
    deshacer_redireccion_fb,
    veredicto_landing,
)
from trovify.caza.hueco import HuecoPais, hueco_pais
from trovify.caza.modelo import AnuncioBiblioteca, ResultadoBusqueda
from trovify.caza.nota import Nota, calcular_nota, decidir, validar_perfil
from trovify.caza.oferta import Oferta, agrupar, marcar_original
from trovify.caza.presupuesto import (
    ContadorIlegible,
    ParadaDelDia,
    ParadaPorErrores,
    PresupuestoAgotado,
)
from trovify.caza.salida import (
    CifraPagina,
    Consulta,
    Ejecucion,
    ResultadoOferta,
    _cabecera_via,
    _comas,
    _tabla_huecos,
    escribir,
    formatear_medida,
    linea_hueco,
    mejor_pais,
    texto_pendientes,
)
from trovify.caza.senales import VENTANA_FOTO, Medida, calcular_senales, crecimiento
from trovify.config import mercados as cfg_mercados
from trovify.config import umbrales as cfg_umbrales
from trovify.navegador import NavegadorError
from trovify.vault import frontmatter
from trovify.vault.escritura import ZONA_NEGOCIO, anadir_log

Modo = Literal["nicho", "barrido", "vigilar", "oferta"]
MODOS: tuple[str, ...] = ("nicho", "barrido", "vigilar", "oferta")
# Un resolver recibe el enlace del anuncio y devuelve el destino (con el texto de la landing si lo
# tiene) o None si no se pudo abrir. Nunca abre facebook.com (``resolver_destino`` lo desenvuelve).
Resolver = Callable[[str], "Destino | tuple[Destino, str] | None"]

_PARADAS = (SesionBloqueada, ParadaPorErrores, PresupuestoAgotado)
_MAX_ANUNCIOS = 60  # anuncios por lectura (lo que trae una página de la Biblioteca y su desplazamiento)
_VIGILADAS = ("A", "B", "observar")
_FALLOS = ("observar", "descartada")
_ORDEN = {"A": 0, "B": 1, "observar": 2, "descartada": 3}
_DIAS_C8 = 8  # definición de la cohorte C8 (igual que en senales.py)
# Búsquedas extra que puede necesitar una oferta nueva (original, parados, recuento con frase).
# Ronda 1, decisión del controlador (I3): con menos restantes, la oferta queda pendiente.
_BUSQUEDAS_POR_NUEVA = 3


def _ahora() -> datetime:
    return datetime.now(UTC)


def _dia_de(t: datetime) -> date:
    """Día de negocio (America/Bogota) de un instante; uno sin zona se toma como UTC."""
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(ZONA_NEGOCIO).date()


def hoy_negocio() -> date:
    """Día de negocio: el corte de día es el de America/Bogota."""
    return _ahora().astimezone(ZONA_NEGOCIO).date()


# --- texto de landings ------------------------------------------------------------------------

_PIE = re.compile(
    r"©|\(c\)\s*\d{4}|copyright|all rights reserved|todos los derechos|todos os direitos|toate drepturile|"
    r"tutti i diritti|tous droits|privacy|privacidad|privacidade|confiden[tț]ialitate|términos|terminos|termos|"
    r"terms of|terms and|termeni|condiții|conditii|condiciones|condições|aviso legal|legal notice|"
    r"mentions légales|impressum|disclaimer|descargo de responsabilidad|facebook|meta platforms|"
    r"not part of the|no es parte|não faz parte|nu face parte|cookie policy|política de cookies|"
    r"politica de cookies|we use cookies|usamos cookies|utilizamos cookies|refund policy|"
    r"política de reembolso|politica de rambursare|contact us|contáctanos|fale conosco",
    re.IGNORECASE,
)
_MAX_LINEA_PIE = 300  # una línea larga con esas palabras es contenido, no pie


def texto_sin_pie(texto: str) -> str:
    """Texto de la landing sin pie ni avisos legales y sin líneas repetidas (menús, botones).

    El aviso «no es parte de Facebook», la política de privacidad o los términos repiten palabras
    que no dicen nada de la oferta y podrían disparar filtros (aviso de la Tarea 3)."""
    vistas: set[str] = set()
    lineas: list[str] = []
    for linea in (texto or "").splitlines():
        limpia = " ".join(linea.split())
        if not limpia or limpia.casefold() in vistas:
            continue
        if len(limpia) <= _MAX_LINEA_PIE and _PIE.search(limpia):
            continue
        vistas.add(limpia.casefold())
        lineas.append(limpia)
    return "\n".join(lineas)


def resolver_por_defecto() -> Resolver:
    """Abre cada landing con Chromium móvil efímero (nunca Meta) y guarda el texto de la landing."""
    from trovify.caza.destino import (
        NavegadorLandingEfimero,
        pedir_como_robot_http,
        resolver_destino,
    )

    navegador = NavegadorLandingEfimero()

    def resolver(url: str):
        textos: list[str] = []

        class _Grabador:
            def abrir_landing(self, u: str, espera_s: float = 3.5):
                p = navegador.abrir_landing(u, espera_s)
                textos.append(p.texto)
                return p

        d = resolver_destino(url, _Grabador(), pedir_como_robot_http)
        return d, (textos[0] if textos else "")

    return resolver


# --- búsquedas con parada -------------------------------------------------------------------


def clasificar_corte(exc: BaseException) -> tuple[str, str]:
    """``(tipo, motivo)`` de una excepción que corta las búsquedas.

    - ``meta``: Meta bloqueó (ahora o antes hoy): dura el día entero.
    - ``errores``: racha de errores, navegador que no arranca o contador ilegible: solo este proceso.
    - ``cuota``: se acabaron las búsquedas del día (tuyas o de la rutina): un final normal.
    """
    motivo = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (SesionBloqueada, ParadaDelDia)):
        return "meta", motivo
    if isinstance(exc, NavegadorError):
        return "errores", f"navegador no disponible: {exc}"
    if isinstance(exc, (ParadaPorErrores, ContadorIlegible)):
        return "errores", motivo
    return "cuota", str(exc)


class _Buscador:
    """Envuelve el cliente: tras la primera parada o con la cuota agotada no vuelve a llamarlo nunca."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.parada: str | None = None
        self.tipo_parada: str | None = None  # «meta» o «errores»
        self.cuota: str | None = None  # motivo si se acabó la cuota del día (final normal)
        self.via: Counter[str] = Counter()
        self.creditos = 0
        self.creditos_desconocidos = False
        self.navegadas = self.bloqueos = self.vacios = 0
        p = self._presupuesto()
        self._inicio = (p.usadas, p.bloqueos, p.vacios) if p is not None else None

    def _presupuesto(self):
        return getattr(self.cliente, "presupuesto", None)

    @property
    def corte(self) -> str | None:
        """Por qué ya no se busca: la parada o la cuota agotada; None si se puede seguir."""
        if self.parada is not None:
            return self.parada
        return f"cuota del día agotada ({self.cuota})" if self.cuota is not None else None

    def buscar(self, pais: str, **kw) -> ResultadoBusqueda | None:
        if self.corte is not None:
            return None
        p = self._presupuesto()
        antes = p.usadas if p is not None else None
        try:
            r = self.cliente.buscar(pais, max_anuncios=_MAX_ANUNCIOS, **kw)
        except (*_PARADAS, NavegadorError) as exc:  # Chromium que no arranca: parada controlada
            tipo, motivo = clasificar_corte(exc)
            if tipo == "cuota":
                self.cuota = motivo
            else:
                self.parada, self.tipo_parada = motivo, tipo
            return None
        navego = p is None or p.usadas > antes
        if navego:
            self.navegadas += 1
            self.via[r.via] += 1
            if r.via == "firecrawl":
                if r.creditos is None:
                    self.creditos_desconocidos = True
                else:
                    self.creditos += r.creditos
            if r.estado == "vacio":
                self.vacios += 1
        if r.estado == "bloqueado":
            self.bloqueos += 1
            self.parada, self.tipo_parada = f"bloqueo de Meta: {r.motivo or 'acceso bloqueado'}", "meta"
        return r

    def restantes(self) -> int | None:
        """Búsquedas que quedan hoy a este proceso; None si el cliente no lo sabe."""
        if self.corte is not None:
            return 0
        f = getattr(self._presupuesto(), "restantes", None)
        return f() if callable(f) else None

    def cuentas(self) -> tuple[int, int, int]:
        p = self._presupuesto()
        if p is not None and self._inicio is not None:
            return p.usadas - self._inicio[0], p.bloqueos - self._inicio[1], p.vacios - self._inicio[2]
        return self.navegadas, self.bloqueos, self.vacios

    def creditos_totales(self) -> int | None:
        if not self.via.get("firecrawl") or self.creditos_desconocidos:
            return None
        return self.creditos


# --- contexto del vault ----------------------------------------------------------------------


def _exclusiones(vault: Path) -> set[str]:
    """Claves u ``oferta_id`` de ``wiki/caza/exclusiones.md`` (líneas «- fecha · qué · motivo · fuente»)."""
    ruta = vault / "wiki/caza/exclusiones.md"
    if not ruta.exists():
        return set()
    _, cuerpo = frontmatter.leer(ruta)
    out: set[str] = set()
    for linea in cuerpo.splitlines():
        t = linea.strip()
        if not t.startswith(("- ", "* ")):
            continue
        partes = [p.strip().strip("`") for p in t[2:].split("·")]
        que = partes[1] if len(partes) >= 2 else partes[0]
        if que:
            out.add(que)
    return out


def _propias(vault: Path) -> set[str]:
    out: set[str] = set()
    raiz = vault / "productos"
    if not raiz.is_dir():
        return out
    for ruta in raiz.rglob("*.md"):
        try:
            meta, _ = frontmatter.leer(ruta)
        except Exception:  # noqa: BLE001, S112 - una ficha ilegible no rompe la caza
            continue
        for clave in ("oferta_id", "clave"):
            v = meta.get(clave) if isinstance(meta, dict) else None
            if isinstance(v, str) and v:
                out.add(v)
    return out


def _fichas(vault: Path) -> dict[str, dict]:
    fichas: dict[str, dict] = {}
    for ruta in sorted((vault / "wiki/ofertas").glob("*.md")):
        try:
            meta, _ = frontmatter.leer(ruta)
        except Exception:  # noqa: BLE001, S112 - una ficha ilegible no rompe la caza
            continue
        if isinstance(meta, dict):
            fichas[str(meta.get("oferta_id") or ruta.stem)] = meta
    return fichas


def _mercados(vault: Path):
    ruta = vault / "config/mercados.yaml"
    return cfg_mercados.cargar(ruta) if ruta.exists() else {}


# --- hueco guardado en la ficha ------------------------------------------------------------


def hueco_a_dict(h: HuecoPais, dia: date) -> dict:
    return {
        "competencia": None if h.competencia.valor is None else int(h.competencia.valor),
        "competencia_suelo": bool(h.competencia.suelo),
        "competencia_motivo": h.competencia.motivo,
        "original": h.original,
        "hueco": h.hueco,
        "motivo": h.motivo,
        "enlaces": list(h.enlaces),
        "fecha": dia.isoformat(),
    }


def huecos_de(meta: dict | None) -> list[HuecoPais]:
    out: list[HuecoPais] = []
    for pais, d in sorted(((meta or {}).get("huecos") or {}).items()):
        if not isinstance(d, dict):
            continue
        v = d.get("competencia")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            comp = Medida(float(v), suelo=bool(d.get("competencia_suelo")))
        else:
            comp = Medida(None, d.get("competencia_motivo") or "no medido: sin dato guardado")
        hueco = d.get("hueco") if d.get("hueco") in (True, False) else None
        out.append(HuecoPais(str(pais), comp, str(d.get("original") or "no_medido"), hueco,
                             list(d.get("enlaces") or []), d.get("motivo")))
    return out


def _hay_hueco(huecos: list[HuecoPais]) -> bool | None:
    """A pide hueco en al menos un país: True si alguno lo tiene; None si alguno no se comprobó."""
    if any(h.hueco is True for h in huecos):
        return True
    if not huecos or any(h.hueco is None for h in huecos):
        return None
    return False


# --- strikes -------------------------------------------------------------------------------


_NADA_MEDIDO = "nada medido"


def _limite_plantilla() -> float:
    from trovify.vault.andamio import PLANTILLA

    return cfg_umbrales.cargar(PLANTILLA / "config/umbrales.yaml")["caza.poda.strikes"].valor


def aplicar_strikes(
    fichas: dict[str, dict], resultados: dict[str, tuple[str, str]], limite: float | None = None
) -> dict[str, dict]:
    """Strikes de ``vigilar`` (idea de un repo de referencia, reescrita). Pura: devuelve copias.

    - ``resultados``: ``oferta_id`` → ``(estado, motivo)`` de esta ejecución; las vigiladas sin
      resultado (no medidas) no cambian.
    - Bajar a observar o descartada suma un strike si el motivo es el mismo que el anterior; con
      otro motivo la cuenta vuelve a 1. Al llegar a ``limite`` (``caza.poda.strikes``; por defecto el
      de la plantilla) pasa a ``estado: podada`` y deja de vigilarse. Si sube, vuelve a 0.
    - Si con 2 o más vigiladas medidas fallan más de la mitad a la vez, es un fallo de entorno y no
      se cuenta ningún strike.
    """
    limite = _limite_plantilla() if limite is None else limite
    out = {k: dict(v) for k, v in fichas.items()}
    # «nada medido» es un fallo de medición, nunca de la oferta: no cuenta.
    medidas = {k: v for k, v in resultados.items() if k in out and v[1] != _NADA_MEDIDO}
    fallan = [k for k, (estado, _) in medidas.items() if estado in _FALLOS]
    if len(medidas) >= 2 and 2 * len(fallan) > len(medidas):
        return out
    for k, (estado, motivo) in medidas.items():
        f = out[k]
        if estado in _FALLOS:
            previos = int(f.get("strikes") or 0)
            if previos and f.get("motivo_strike") == motivo:
                f["strikes"] = previos + 1
            else:
                f["strikes"] = 1
                f["motivo_strike"] = motivo
            f["estado"] = "podada" if f["strikes"] >= limite else estado
        else:
            f["strikes"] = 0
            f.pop("motivo_strike", None)
            f["estado"] = estado
    return out


def _motivo_strike(r: ResultadoOferta) -> str:
    """Motivo corto de la caída. Una nota sin medir nunca llega aquí (no es un strike)."""
    if r.descarte is not None:
        return r.descarte.codigo
    if "cayendo" in r.senales.banderas:
        return "cayendo"
    return "nota baja"


# --- palabras y resumen ---------------------------------------------------------------------


def palabras_a_reescribir(consultas: list[Consulta], minimo: float) -> list[Consulta]:
    """Consultas medidas con menos de ``minimo`` resultados (``caza.palabra.min_resultados``).
    Una consulta no medida no se marca: no se sabe cuánto rinde."""
    return [c for c in consultas if c.resultados is not None and c.resultados < minimo]


def resumen(e: Ejecucion, minimo_palabra: float, usadas_hoy: tuple[int, int] | None = None) -> str:
    """Resumen corto para la terminal y el registro de la rutina."""
    def lista(estado: str) -> str:
        rs = [r for r in e.resultados if r.decision == estado]
        return ", ".join(f"{r.oferta.oferta_id} ({r.pais}, {_nota(r.nota)})" for r in rs) or "ninguna"

    lineas = [f"Caza del {e.dia.isoformat()} · {e.region} · modo {e.modo} · perfil {e.perfil}", ""]
    lineas += [f"A: {lista('A')}", f"B: {lista('B')}", f"Observar: {lista('observar')}"]
    vistas = [r for r in e.resultados if r.descarte is not None and r.descarte.codigo == "ya_visto"]
    descartadas = [r for r in e.resultados if r.decision == "descartada" and r not in vistas]
    if descartadas:
        lineas.append("Descartadas:")
        lineas += [f"  - {r.oferta.oferta_id} ({r.pais}): {r.explicacion}" for r in descartadas]
    else:
        lineas.append("Descartadas: ninguna")
    if vistas:
        lineas.append("Ya vistas (ya en el cerebro; su ficha manda): "
                      + ", ".join(f"{r.oferta.oferta_id} ({r.pais})" for r in vistas))
    if e.pendientes:
        lineas.append(texto_pendientes(e))
    paises: dict[str, list[float]] = {}
    for r in e.resultados:
        if r.decision in ("A", "B", "observar"):
            paises.setdefault(r.pais, []).append(r.senales.c8.valor or 0.0)
    top = sorted(paises.items(), key=lambda kv: (-len(kv[1]), -sum(kv[1]), kv[0]))
    lineas.append("Top de países: " + (", ".join(
        f"{p} ({len(v)} {'candidata' if len(v) == 1 else 'candidatas'})" for p, v in top[:5]) or "ninguno"))
    lineas += ["", _cabecera_via(e)]
    if usadas_hoy is not None:
        lineas.append(f"Búsquedas usadas hoy (tu sesión y la rutina): {usadas_hoy[0]} de {usadas_hoy[1]}")
    lineas.append(f"Bloqueos: {e.bloqueos} · búsquedas sin resultados: {e.vacios}")
    flojas = palabras_a_reescribir(e.consultas, minimo_palabra)
    if flojas:
        lineas.append(f"Palabras a reescribir (menos de {minimo_palabra:g} resultados): " + ", ".join(
            f"«{c.palabra}» ({c.pais}: {'≈ ' if c.aproximado else ''}{c.resultados})" for c in flojas))
    rinden = [c for c in e.consultas if c not in flojas and c.resultados is not None]
    if rinden:
        lineas.append("Palabras que rinden: " + ", ".join(
            f"«{c.palabra}» ({c.pais}: {'≈ ' if c.aproximado else ''}{c.resultados})" for c in rinden))
    if e.parada and e.tipo_parada == "errores":
        lineas += ["", (f"INTERRUMPIDA: {e.parada}. No es un bloqueo de Meta: esta ejecución no buscó nada más y "
                        "lo que faltaba quedó «no medido»; se puede volver a cazar más tarde.")]
    elif e.parada:
        lineas += ["", (f"PARADA: {e.parada}. Meta bloqueó: no se buscó nada más y lo que faltaba quedó "
                        "«no medido». Hoy no se vuelve a buscar.")]
    elif e.cuota:
        lineas += ["", (f"Cuota del día agotada: {e.cuota}. Es un final normal: "
                        f"{e.pendientes_por.get('cuota', 0)} quedan pendientes para la próxima caza.")]
    if e.errores:
        lineas += ["", "Avisos:"] + [f"  - {x}" for x in e.errores]
    lineas += ["", f"Informe: wiki/caza/{e.dia.isoformat()}/ · decisión del usuario: wiki/caza/{e.dia.isoformat()}/veredicto.md"]
    return "\n".join(lineas)


def _nota(n: Nota) -> str:
    return "nota no medida" if n.valor is None else f"nota {n.valor:.1f}".replace(".", ",")


# --- la corrida ------------------------------------------------------------------------------


def _c8(anuncios: list[AnuncioBiblioteca], hoy: date) -> int:
    return sum(1 for a in anuncios if a.activo and (hoy - a.inicio).days >= _DIAS_C8)


def _vara(perfil: str, u) -> tuple[str, float] | None:
    clave = perfil.replace("-", "_")
    if f"caza.perfil.{clave}.c7_min" in u:
        return "C7", u[f"caza.perfil.{clave}.c7_min"].valor
    if f"caza.perfil.{clave}.c8_min" in u:
        return "C8", u[f"caza.perfil.{clave}.c8_min"].valor
    return None


def _frase(o: Oferta, page_id: str) -> str | None:
    """Una frase del creativo de la oferta en esa página: el título más repetido o el arranque del texto."""
    propios = [a for a in o.anuncios if a.page_id == page_id]
    titulos = Counter(" ".join((a.titulo or "").split()) for a in propios if (a.titulo or "").strip())
    if titulos:
        return titulos.most_common(1)[0][0][:80]
    textos = Counter(" ".join(a.texto.split()[:5]) for a in propios if a.texto.strip())
    return textos.most_common(1)[0][0][:80] if textos else None


def _dominio(o: Oferta) -> str | None:
    d = o.destino
    if d is None or d.estado != "ok" or d.red_social:
        return None
    host = _host(d.url_final or d.url_anuncio).removeprefix("www.")
    if not host:
        return None
    if any(host == x or host.endswith("." + x) for x in _DOMINIOS_COMPARTIDOS):
        return host
    return _registrable(host)


@dataclass
class _Corrida:
    vault: Path
    modo: str
    perfil: str
    hoy: date
    u: dict
    mercados: dict
    b: _Buscador
    resolver: Resolver
    errores: list[str] = field(default_factory=list)
    lecturas: dict[tuple[str, str], ResultadoBusqueda] = field(default_factory=dict)
    destinos: dict[str, Destino] = field(default_factory=dict)
    landings: dict[str, str] = field(default_factory=dict)
    # (oferta_id, page_id, pais) → anuncios de la oferta en la página según un recuento con frase
    # completo, con count exacto y sin ningún anuncio ajeno (vale como total exacto de la oferta).
    recuentos: dict[tuple[str, str, str], int] = field(default_factory=dict)
    sin_abrir: set[str] = field(default_factory=set)  # enlaces de landings sin abrir por el tope
    # (oferta_id, page_id, pais) → URL del recuento con frase que trajo anuncios de la oferta: es el
    # enlace que reproduce sus cifras en una página que lleva otras ofertas.
    frases_url: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # La planificación dejó trabajo fuera porque no quedaban búsquedas hoy (sin llegar a agotarlas).
    cuota_plan: str | None = None

    def sin_medir(self, que: str) -> None:
        self.errores.append(f"no medido: {self.b.corte}: {que}")

    # paso 2
    def consultas(self, consultas: list[tuple[str, str]]):
        salida: list[Consulta] = []
        anuncios: list[AnuncioBiblioteca] = []
        ids: list[tuple[str, set[str]]] = []
        for pais, frase in consultas:
            url = url_biblioteca(pais, q=frase)
            r = self.b.buscar(pais, q=frase)
            if r is None:
                self.sin_medir(f"consulta «{frase}» ({pais}) sin hacer")
                salida.append(Consulta(frase, pais, None, url))
                ids.append((pais, set()))
                continue
            if r.estado not in ("ok", "vacio"):
                self.errores.append(f"no medido: consulta «{frase}» ({pais}): {r.motivo or r.estado}")
                salida.append(Consulta(frase, pais, None, r.url))
                ids.append((pais, set()))
                continue
            n = r.total_aprox if r.total_aprox is not None else (len(r.anuncios) if r.completo else None)
            aprox = r.total_aprox is not None and not r.total_exacto and r.estado == "ok"
            salida.append(Consulta(frase, pais, n, r.url, aproximado=aprox, sin_recuento=n is None))
            ids.append((pais, {a.library_id for a in r.anuncios}))
            anuncios += r.anuncios
        return salida, anuncios, ids

    # paso 3
    def recontar(self, pares: list[tuple[str, str]]) -> None:
        for page_id, pais in pares:
            if (page_id, pais) in self.lecturas:
                continue
            r = self.b.buscar(pais, page_id=page_id)
            if r is None:
                self.sin_medir(f"página {page_id} en {pais} sin recontar")
            elif r.estado in ("ok", "vacio"):
                self.lecturas[(page_id, pais)] = r
            else:
                self.errores.append(f"no medido: recuento de la página {page_id} en {pais}: {r.motivo or r.estado}")

    # paso 4
    def resolver_destinos(self, anuncios: list[AnuncioBiblioteca]) -> None:
        maximo = int(self.u["caza.max_destinos_por_ejecucion"].valor)
        por_pagina: dict[str, list[AnuncioBiblioteca]] = {}
        for a in anuncios:
            por_pagina.setdefault(a.page_id, []).append(a)
        orden = sorted(por_pagina, key=lambda p: (-_c8(por_pagina[p], self.hoy), -len(por_pagina[p]), p))
        colas = []
        for p in orden:
            enlaces = Counter(a.enlace_destino for a in por_pagina[p] if a.enlace_destino)
            colas.append([u for u, _ in sorted(enlaces.items(), key=lambda kv: (-kv[1], kv[0]))])
        abiertas, intentadas = 0, set()
        while abiertas < maximo and any(colas):
            for cola in colas:
                while cola and cola[0] in intentadas:
                    cola.pop(0)
                if not cola or abiertas >= maximo:
                    continue
                url = cola.pop(0)
                intentadas.add(url)
                abiertas += 1
                self._resolver(url)
        quedan = {u for cola in colas for u in cola if u not in intentadas}
        self.sin_abrir = quedan
        if quedan:
            self.errores.append(
                f"no medido: {len(quedan)} landings sin abrir por el tope caza.max_destinos_por_ejecucion "
                f"({maximo}); sus anuncios quedan sin evaluar (sin ficha) hasta que se abran en otra caza"
            )

    def _resolver(self, url: str) -> None:
        try:
            res = self.resolver(url)
        except Exception:  # noqa: BLE001 - una landing que no abre no para la caza
            res = None
        if res is None:
            return
        destino, texto = (res, "") if isinstance(res, Destino) else res
        self.destinos[url] = destino
        if texto:
            self.landings[destino.url_anuncio] = texto_sin_pie(texto)

    # varias ofertas en una página
    def ampliar(self, o: Oferta, multi: set[str]) -> Oferta:
        nuevos: dict[tuple[str, str], AnuncioBiblioteca] = {(a.library_id, a.pais): a for a in o.anuncios}
        propios = {d.url_anuncio for d in o.destinos}
        for page_id in o.page_ids:
            if page_id not in multi:
                continue
            frase = _frase(o, page_id)
            if not frase:
                continue
            for pais in sorted({a.pais for a in o.anuncios if a.page_id == page_id}):
                r = self.b.buscar(pais, q=frase, page_id=page_id)
                if r is None:
                    self.sin_medir(f"recuento de {o.oferta_id} dentro de la página {page_id} ({pais})")
                    return replace(o, anuncios=list(nuevos.values()))
                if r.estado not in ("ok", "vacio"):
                    continue
                todos_propios = True
                for a in r.anuncios:
                    # solo los anuncios cuyo destino es el de esta oferta: lo demás no se atribuye
                    if a.page_id == page_id and a.enlace_destino in propios:
                        nuevos.setdefault((a.library_id, a.pais), a)
                        self.frases_url[(o.oferta_id, page_id, pais)] = r.url
                    else:
                        todos_propios = False
                leidos = {a.library_id for a in r.anuncios}
                conocidos = {a.library_id for a in o.anuncios if a.page_id == page_id and a.pais == pais}
                # además debe traer todos los anuncios que ya se sabían de la oferta en la página
                if (r.completo and r.total_exacto and r.total_aprox is not None and todos_propios
                        and conocidos <= leidos):
                    self.recuentos[(o.oferta_id, page_id, pais)] = r.total_aprox
        return replace(o, anuncios=list(nuevos.values()))

    # buscar el original
    def buscar_original(self, o: Oferta) -> Oferta:
        dominio = _dominio(o)
        if not dominio:
            return o
        pais = Counter(a.pais for a in o.anuncios).most_common(1)[0][0]
        r = self.b.buscar(pais, q=dominio)
        if r is None:
            self.sin_medir(f"búsqueda del original de {o.oferta_id} por «{dominio}»")
            return o
        if r.estado != "ok":
            return o
        con_destino = [a for a in r.anuncios if a.enlace_destino]
        ajenos = [a for a in con_destino if dominio not in deshacer_redireccion_fb(a.enlace_destino).lower()]
        if ajenos:
            self.errores.append(
                f"no medido: dominio contaminado: la búsqueda «{dominio}» ({pais}) trae {len(ajenos)} anuncios "
                f"con otro destino; no se usa para buscar el original de {o.oferta_id} · {r.url}"
            )
            return o
        otras = [a for a in con_destino if a.page_id not in o.page_ids]
        if not otras:
            return o
        paginas = list(dict.fromkeys([*o.page_ids, *(a.page_id for a in otras)]))
        m = marcar_original(replace(o, page_ids=paginas, anuncios=[*o.anuncios, *otras]))
        if m.original_page_id in o.page_ids:
            return replace(o, origen="original", original_page_id=m.original_page_id,
                           copias=[p for p in o.page_ids if p != m.original_page_id])
        return replace(o, origen="copia", original_page_id=m.original_page_id, copias=list(o.page_ids))

    def inactivos(self, o: Oferta, pais: str, multi: set[str]) -> list[AnuncioBiblioteca] | None:
        """Anuncios de una lectura completa ``estado="all"`` de todas sus páginas; si no, None."""
        if any(p in multi for p in o.page_ids):
            return None
        lista: list[AnuncioBiblioteca] = []
        for page_id in o.page_ids:
            r = self.b.buscar(pais, page_id=page_id, estado="all")
            if r is None:
                self.sin_medir(f"anuncios parados de {o.oferta_id} en {pais}")
                return None
            if r.estado not in ("ok", "vacio") or not r.completo:
                return None
            lista += r.anuncios
        return lista


class CazaEnCurso(ValueError):
    """Otra caza (la rutina u otra sesión) está usando la Biblioteca en este cerebro."""


@contextmanager
def _cerrojo_caza(vault: Path):
    """Una sola caza a la vez por cerebro: dos procesos no consultan a Meta al mismo tiempo."""
    ruta = Path(vault) / "data/caza/.caza.lock"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CazaEnCurso(
                "otra caza está en marcha en este cerebro (la rutina u otra sesión): espera a que termine y "
                "vuelve a lanzarla; dos cazas a la vez doblarían el ritmo de búsquedas a Meta"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ejecutar(vault: Path, *args, **kw) -> Ejecucion:
    """Una ejecución de la caza con el cerrojo del cerebro (:func:`_ejecutar`; ``CazaEnCurso`` si
    otra caza está en marcha)."""
    with _cerrojo_caza(Path(vault)):
        return _ejecutar(vault, *args, **kw)


def _ejecutar(
    vault: Path,
    modo: Modo,
    consultas: list[tuple[str, str]],
    perfil: str,
    max_nuevas: int,
    page_ids: list[str] | None = None,
    cliente=None,
    resolver: Resolver | None = None,
    hoy: date | None = None,
    *,
    region: str | None = None,
    paises: list[str] | None = None,
    max_vigiladas: int | None = None,
    max_busquedas_rutina: int | None = None,
) -> Ejecucion:
    """Una ejecución de la caza; escribe con ``salida.escribir`` y devuelve la :class:`Ejecucion`.

    - ``consultas``: ``[(pais, frase)]``; ``page_ids`` y ``paises`` (por defecto ``["ALL"]``) se
      recuentan en ``oferta``; en ``vigilar`` se vuelven a medir las fichas A, B y observar por
      ``page_id`` y país.
    - ``cliente`` por defecto: ``ClienteBibliotecaPublica`` con el presupuesto del día del vault y
      la caché de ``data/cache/biblioteca`` (Firecrawl si hay clave [D-11b], si no Playwright).
    - Como mucho ``max_nuevas`` ofertas nuevas pasan los filtros; el resto cuenta como ``pendientes``
      (también si quedan menos de ``_BUSQUEDAS_POR_NUEVA`` búsquedas hoy: nunca se mide a medias).
    - ``max_vigiladas``: tope del día de fichas vigiladas (``rutina.max_vigiladas_por_dia``); se
      miden las que hace más tiempo que no se miden.
    - ``max_busquedas_rutina``: cuota del día de la rutina (``rutina.max_busquedas``).
    """
    vault = Path(vault)
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; usa {', '.join(MODOS)}")
    if modo == "oferta" and not page_ids:
        raise ValueError("el modo oferta necesita al menos un --page-id")
    hoy = hoy or hoy_negocio()
    u = cfg_umbrales.cargar(vault / "config/umbrales.yaml")
    perfil = validar_perfil(u, perfil)  # antes de cualquier búsqueda
    if cliente is None:
        from trovify.caza.cache import Cache
        from trovify.caza.cliente import ClienteBibliotecaPublica
        from trovify.caza.presupuesto import Presupuesto

        # = Cache.por_defecto() con el vault de TROVIFY_VAULT; aquí sale del vault recibido.
        cliente = ClienteBibliotecaPublica(Presupuesto.desde_umbrales(vault, hoy, max_rutina=max_busquedas_rutina),
                                           cache=Cache(vault / "data" / "cache" / "biblioteca"))
    c = _Corrida(vault, modo, perfil, hoy, u, _mercados(vault), _Buscador(cliente),
                 resolver or resolver_por_defecto())

    # 1) contexto
    fichas = _fichas(vault)
    excluidas = _exclusiones(vault)
    if modo in ("nicho", "barrido"):
        excluidas |= set(fichas)  # ya vistas: se informan, no se vuelven a juzgar
    ctx = filtros.ContextoFiltros(excluidas, _propias(vault), u, c.landings)

    # 2) búsquedas por palabra
    salida_consultas, de_palabras, ids_consulta = c.consultas(list(consultas))

    # 3) recuento por página y país, planificado con las búsquedas que quedan hoy (I4: agotar la
    # cuota es un final normal; lo que no cabe queda pendiente, nunca medido a medias)
    pendientes_por: Counter[str] = Counter()
    pares: list[tuple[str, str]] = []
    vigiladas: dict[str, dict] = {}
    pares_de: dict[str, list[tuple[str, str]]] = {}
    if modo == "vigilar":
        quedan = c.b.restantes()
        sin_cuota: list[str] = []
        for oid, meta in _turno_de_vigilancia(c, fichas, hoy, max_vigiladas).items():
            propios = list(dict.fromkeys(
                (str(p), str(pais)) for pais in (meta.get("paises") or {}) if not paises or pais in paises
                for p in meta.get("page_ids") or []))
            extra = [x for x in propios if x not in pares]
            if quedan is not None and len(pares) + len(extra) > quedan:
                sin_cuota.append(oid)
                continue
            vigiladas[oid], pares_de[oid] = meta, propios
            pares += extra
        if sin_cuota:
            c.cuota_plan = f"quedaban {quedan} búsquedas hoy"
            pendientes_por["cuota"] += len(sin_cuota)
            c.errores.append(f"no medido: cuota del día agotada: {', '.join(sin_cuota)} se vigilan otro día "
                             f"(quedaban {quedan} búsquedas); no cuenta como strike")
    for p in page_ids or []:
        pares += [(p, pais) for pais in (paises or ["ALL"])]
    if de_palabras:
        por_par: dict[tuple[str, str], list[AnuncioBiblioteca]] = {}
        for a in de_palabras:
            por_par.setdefault((a.page_id, a.pais), []).append(a)
        # Las páginas de fichas ya guardadas van al final: sus ofertas ya se vieron (se informan aparte).
        conocidas = {str(p) for m in fichas.values() for p in (m.get("page_ids") or [])}
        orden = sorted(por_par, key=lambda k: (k[0] in conocidas, -_c8(por_par[k], hoy), -len(por_par[k]), k))
        candidatos = [k for k in orden if k not in pares]
        maximo = int(u["caza.max_destinos_por_ejecucion"].valor)
        tope = maximo
        quedan = c.b.restantes()
        if quedan is not None:
            # Se reservan las búsquedas extra de las ofertas nuevas que caben hoy; si no cabe
            # ninguna, no se recuenta nada (no se gasta en cifras que no se podrían evaluar).
            libres = max(quedan - len(dict.fromkeys(pares)), 0)
            caben = min(max_nuevas, libres // (1 + _BUSQUEDAS_POR_NUEVA))
            tope = min(maximo, libres - _BUSQUEDAS_POR_NUEVA * caben) if caben else 0
        pares += candidatos[:tope]
        if len(candidatos) > maximo:
            c.errores.append(f"no medido: {len(candidatos) - maximo} páginas de las búsquedas sin recontar "
                             f"(tope caza.max_destinos_por_ejecucion: {maximo}); las de más C8 primero")
        por_cuota = min(len(candidatos), maximo) - min(len(candidatos), tope)
        if por_cuota > 0:
            c.cuota_plan = f"quedaban {quedan} búsquedas hoy"
            c.errores.append(f"no medido: cuota del día agotada: {por_cuota} páginas de las búsquedas sin recontar "
                             f"(quedaban {quedan} búsquedas; se guardan para medir ofertas nuevas)")
    c.recontar(list(dict.fromkeys(pares)))

    pool: dict[tuple[str, str], AnuncioBiblioteca] = {}
    for r in c.lecturas.values():
        for a in r.anuncios:
            pool[(a.library_id, a.pais)] = a
    for a in de_palabras:
        if (a.page_id, a.pais) not in c.lecturas:
            pool.setdefault((a.library_id, a.pais), a)
    anuncios = list(pool.values())

    # 4) destinos y clave de oferta
    c.resolver_destinos(anuncios)
    ofertas = [marcar_original(o) for o in agrupar(anuncios, c.destinos, c.mercados)]
    claves_por_pagina: dict[str, set[str]] = {}
    sin_atribuir: dict[tuple[str, str], set[str]] = {}  # (página, país) → grupos sin destino resuelto
    for o in ofertas:
        for p in o.page_ids:
            claves_por_pagina.setdefault(p, set()).add(o.clave)
        if o.clave.startswith("pagina:"):
            for a in o.anuncios:
                sin_atribuir.setdefault((a.page_id, a.pais), set()).add(o.clave)
    multi = {p for p, cl in claves_por_pagina.items() if len(cl) > 1}

    # 5) filtros, tope de nuevas, recuento dentro de la página y búsqueda del original
    evaluar: list[tuple[Oferta, filtros.Descarte | None, bool]] = []
    nuevas = 0
    inactivos: dict[tuple[str, str], list[AnuncioBiblioteca] | None] = {}
    for o in sorted(ofertas, key=lambda x: (-_c8(x.anuncios, hoy), x.oferta_id)):
        if modo == "vigilar" and o.oferta_id not in vigiladas:
            continue  # en vigilar solo se miden las vigiladas
        es_nueva = o.oferta_id not in fichas
        if es_nueva and o.clave.startswith("pagina:") and any(a.enlace_destino in c.sin_abrir for a in o.anuncios):
            # Landing sin abrir por el tope: su clave cambiará cuando se abra; sin ficha hasta entonces.
            pendientes_por["landing_sin_abrir"] += 1
            continue
        descarte = filtros.filtrar(o, ctx)
        if descarte is None:
            if es_nueva and nuevas >= max_nuevas:
                pendientes_por["tope_nuevas"] += 1
                continue
            quedan = c.b.restantes()
            if es_nueva and quedan is not None and quedan < _BUSQUEDAS_POR_NUEVA:
                pendientes_por["cuota"] += 1  # no se mide a medias: sale en la próxima caza
                c.cuota_plan = c.cuota_plan or f"quedaban {quedan} búsquedas hoy"
                continue
            o = c.ampliar(o, multi)
            if es_nueva:
                o = c.buscar_original(o)
                descarte = filtros.filtrar(o, ctx)
            if descarte is None:
                if es_nueva:
                    nuevas += 1
                if es_nueva or modo == "oferta":
                    for pais in sorted({a.pais for a in o.anuncios}):
                        inactivos[(o.oferta_id, pais)] = c.inactivos(o, pais, multi)
        evaluar.append((o, descarte, es_nueva))
    for oid in vigiladas:
        if oid not in {o.oferta_id for o, _, _ in evaluar}:
            motivo = c.b.corte or "no apareció en la relectura de sus páginas"
            c.errores.append(f"no medido: {oid}: {motivo}; no cuenta como strike")

    # 6–8) señales, nota y decisión
    resultados: list[ResultadoOferta] = []
    conn = snapshots.abrir(vault / "data/caza/snapshots.sqlite")
    try:
        for (p, pais), r in c.lecturas.items():  # total de cada página: un hecho de la página
            if r.total_exacto and r.total_aprox is not None:
                snapshots.guardar_pagina(conn, p, pais, hoy, r.total_aprox, r.url)
        alcance = _Alcance(claves_por_pagina, sin_atribuir)
        for o, descarte, _ in evaluar:
            ya_visto = descarte is not None and descarte.codigo == "ya_visto"
            for pais in sorted({a.pais for a in o.anuncios}):
                resultados.append(_evaluar(c, conn, o, pais, descarte, ya_visto, ctx, fichas, inactivos,
                                           alcance, salida_consultas, ids_consulta))
    finally:
        conn.close()

    for consulta, (pais, ids) in zip(salida_consultas, ids_consulta, strict=True):
        for r in resultados:
            if r.pais == pais and r.oferta.oferta_id not in consulta.ofertas and any(
                    a.library_id in ids for a in r.oferta.anuncios):
                consulta.ofertas.append(r.oferta.oferta_id)

    busquedas, bloqueos, vacios = c.b.cuentas()
    errores = list(c.errores)
    if c.b.parada and c.b.tipo_parada == "meta":
        errores.insert(0, f"Parada: {c.b.parada}. No se hizo ninguna búsqueda más ni se cambió de vía; "
                          "lo que faltaba quedó «no medido». Hoy no se vuelve a buscar (hora de Colombia).")
    elif c.b.parada:
        errores.insert(0, f"Interrumpida: {c.b.parada}. No es un bloqueo de Meta: esta ejecución no buscó nada "
                          "más y lo que faltaba quedó «no medido»; se puede volver a cazar más tarde.")
    cuota = c.b.cuota or c.cuota_plan
    if not c.b.parada and cuota:
        errores.insert(0, f"Cuota del día agotada: {cuota}. Es un final normal: lo que no cupo quedó "
                          "pendiente o «no medido» para la próxima caza.")
    e = Ejecucion(
        dia=hoy, region=region or modo, modo=modo, perfil=perfil, busquedas=busquedas, bloqueos=bloqueos,
        vacios=vacios, errores=errores, resultados=resultados, pendientes=sum(pendientes_por.values()),
        via=dict(c.b.via), creditos=c.b.creditos_totales(), consultas=salida_consultas, vara=_vara(perfil, u),
        parada=c.b.parada, tipo_parada=c.b.tipo_parada, cuota=cuota, pendientes_por=dict(pendientes_por),
    )
    escribir(vault, e)

    # strikes de vigilar
    if modo == "vigilar":
        enteras = {oid for oid, pares_oid in pares_de.items()
                   if e.parada is None and pares_oid and all(x in c.lecturas for x in pares_oid)}
        _strikes(vault, e, vigiladas, u, enteras)
    return e


def _turno_de_vigilancia(c: _Corrida, fichas: dict[str, dict], hoy: date, maximo: int | None) -> dict[str, dict]:
    """Fichas A, B y observar que toca medir hoy: las que hace más tiempo que no se miden, hasta
    ``maximo`` en el día. Solo gastan turno las ya vigiladas hoy (``vigilada``), no las que escribió
    hoy una caza nicho o barrido. Sin ``maximo``, todas."""
    todas = {k: m for k, m in fichas.items() if m.get("estado") in _VIGILADAS}
    if maximo is None:
        return todas
    hoy_txt = hoy.isoformat()
    hechas = sorted(k for k, m in todas.items() if str(m.get("vigilada") or "") == hoy_txt)
    resto = sorted((k for k in todas if k not in hechas), key=lambda k: (str(todas[k].get("ultima_vez") or ""), k))
    turno = max(int(maximo) - len(hechas), 0)
    if resto[turno:]:
        c.errores.append(
            f"no medido: turno de vigilancia: {', '.join(resto[turno:])} se miden otro día (tope del día "
            f"rutina.max_vigiladas_por_dia: {int(maximo)}; ya vigiladas hoy: {', '.join(hechas) or 'ninguna'})"
        )
    return {k: todas[k] for k in resto[:turno]}


@dataclass
class _Alcance:
    """Qué ofertas lleva cada página según lo leído (para no tomar cifras de página por cifras de oferta)."""

    claves_por_pagina: dict[str, set[str]]
    sin_atribuir: dict[tuple[str, str], set[str]]

    def solo_esta(self, o: Oferta, page_id: str) -> bool:
        return self.claves_por_pagina.get(page_id, set()) == {o.clave}

    def atribuida(self, o: Oferta, page_id: str, pais: str) -> bool:
        """Ningún anuncio de la página en ``pais`` quedó sin oferta (landing sin abrir o sin destino)."""
        return not (self.sin_atribuir.get((page_id, pais), set()) - {o.clave})


def _total_de_pagina(c: _Corrida, o: Oferta, page_id: str, pais: str, alcance: _Alcance) -> int | None:
    """Anuncios EXACTOS de la oferta en una página, o None.

    Vale (a) la lectura de la página si es completa, con count exacto, y la página no lleva otra
    oferta ni anuncios sin atribuir; o (b) un recuento con frase completo, exacto y sin ajenos."""
    r = c.lecturas.get((page_id, pais))
    if (r is not None and r.completo and r.total_exacto and r.total_aprox is not None
            and alcance.solo_esta(o, page_id) and alcance.atribuida(o, page_id, pais)):
        return r.total_aprox
    return c.recuentos.get((o.oferta_id, page_id, pais))


def _crecimiento_paginas(c: _Corrida, conn, o: Oferta, pais: str, alcance: _Alcance) -> list[tuple[str, Medida, str]]:
    """Crecimiento de cada página con el total exacto de Meta de la PÁGINA (todas sus ofertas), solo
    si todo lo leído de la página va a esta oferta. Es un dato de la página, nunca el de la oferta."""
    out: list[tuple[str, Medida, str]] = []
    for p in o.page_ids:
        r = c.lecturas.get((p, pais))
        if r is None or not r.total_exacto or r.total_aprox is None:
            continue
        if not (alcance.solo_esta(o, p) and alcance.atribuida(o, p, pais)):
            continue
        fotos = [f for f in snapshots.historial_pagina(conn, p, pais, c.hoy - timedelta(days=VENTANA_FOTO[1]))
                 if f.dia < c.hoy]
        m = crecimiento(r.total_aprox, fotos, c.hoy)
        if m.valor is not None:
            out.append((p, m, url_biblioteca(pais, page_id=p)))
    return out


def _evaluar(c: _Corrida, conn, o: Oferta, pais: str, descarte, ya_visto: bool, ctx, fichas, inactivos,
             alcance: _Alcance, consultas: list[Consulta], ids_consulta) -> ResultadoOferta:
    hoy, u = c.hoy, c.u
    lecturas = [c.lecturas.get((p, pais)) for p in o.page_ids]
    # Completa: cada página se leyó entera y ningún anuncio suyo quedó sin atribuir a una oferta.
    # Un grupo «pagina:<id>» son justo los anuncios sin atribuir: nunca es una lectura completa.
    completo = not o.clave.startswith("pagina:") and all(r is not None and r.completo for r in lecturas) and all(
        alcance.atribuida(o, p, pais) for p in o.page_ids)
    # Total exacto de la OFERTA (Snapshot.total, crecimiento): solo de recuentos de la oferta.
    por_pagina = [_total_de_pagina(c, o, p, pais, alcance) for p in o.page_ids]
    total_meta = sum(por_pagina) if all(x is not None for x in por_pagina) else None
    vistos = None
    # Una lectura capturada otro día de negocio (caché vieja) nunca se registra como la de hoy.
    de_otro_dia = any(r is not None and _dia_de(r.capturado_en) != hoy for r in lecturas)
    if completo and not ya_visto and not de_otro_dia:
        activos = {a.library_id for a in o.anuncios if a.activo and a.pais == pais}
        n, par = snapshots.registrar_vistos(conn, o.oferta_id, pais, activos, hoy, completo=True)
        vistos = (n, par, snapshots.dia_anterior(conn, o.oferta_id, pais, hoy))
    historial = [s for s in snapshots.historial(conn, o.oferta_id, pais, hoy - timedelta(days=VENTANA_FOTO[1]))
                 if s.dia < hoy]
    s = calcular_senales(
        o, pais, hoy, historial, inactivos.get((o.oferta_id, pais)), total_meta, completo,
        total_meta=total_meta, umbrales=u, vistos=vistos, mercados=c.mercados,
    )
    if de_otro_dia and completo:
        s.nuevos = s.parados = Medida(None, "no medido: lectura de otro día (caché)")
    s.banderas += [x for x in filtros.banderas(o, ctx) if x not in s.banderas]
    nota = calcular_nota(s, u)
    huecos = huecos_de(fichas.get(o.oferta_id))
    landing = veredicto_landing(o.destino) if o.destino is not None else "dudoso"
    decision, motivo = decidir(nota, s.c8, c.perfil, _hay_hueco(huecos), descarte, u, landing, c7=s.c7)
    return ResultadoOferta(o, pais, s, nota, decision, motivo, descarte, huecos,
                           _enlace(c, o, pais, consultas, ids_consulta), dia=hoy, total_meta=total_meta,
                           completo=completo, crecimiento_pagina=_crecimiento_paginas(c, conn, o, pais, alcance),
                           paginas_cifras=_cifras_por_pagina(c, o, pais, alcance))


def _cifras_por_pagina(c: _Corrida, o: Oferta, pais: str, alcance: _Alcance) -> dict[str, CifraPagina]:
    """De dónde sale la cifra de la oferta en cada página: el recuento con frase si lo hubo (la
    página aparte) y, si no, la lectura de la página, diciendo si lleva otras ofertas."""
    out: dict[str, CifraPagina] = {}
    for p in o.page_ids:
        lect = c.lecturas.get((p, pais))
        pagina = lect.url if lect is not None else url_biblioteca(pais, page_id=p)
        out[p] = CifraPagina(
            enlace=c.frases_url.get((o.oferta_id, p, pais)) or pagina,
            pagina=pagina,
            total_pagina=lect.total_aprox if lect is not None and lect.total_exacto else None,
            leidos_pagina=len(lect.anuncios) if lect is not None else None,
            otras_ofertas=not (alcance.solo_esta(o, p) and alcance.atribuida(o, p, pais)),
        )
    return out


def _enlace(c: _Corrida, o: Oferta, pais: str, consultas: list[Consulta], ids_consulta) -> str:
    """El enlace reproducible de donde salen las cifras de la oferta en ``pais``."""
    if len(o.page_ids) == 1:
        frase = c.frases_url.get((o.oferta_id, o.page_ids[0], pais))
        if frase is not None:  # la cifra salió del recuento con frase dentro de la página
            return frase
        r = c.lecturas.get((o.page_ids[0], pais))
        if r is not None:
            return r.url
    for consulta, (p, ids) in zip(consultas, ids_consulta, strict=True):
        if p == pais and any(a.library_id in ids for a in o.anuncios):
            return consulta.enlace
    return url_biblioteca(pais, page_id=o.original_page_id or o.page_ids[0])


def _strikes(vault: Path, e: Ejecucion, vigiladas: dict[str, dict], u, enteras: set[str]) -> None:
    """Solo cuentan las vigiladas medidas enteras: sin parada, todas sus páginas y países releídos, la
    nota medida en cada país y C8/C7 sin cota inferior. Lo demás no suma ni resta strikes."""
    por_oferta: dict[str, ResultadoOferta] = {}
    sin_nota = {r.oferta.oferta_id for r in e.resultados if r.nota.valor is None}
    # Una cohorte con cota inferior (lectura parcial) no es una medición entera: no hay strike.
    con_suelo = {r.oferta.oferta_id for r in e.resultados if r.senales.c8.suelo or r.senales.c7.suelo}
    for r in e.resultados:
        oid = r.oferta.oferta_id
        if oid not in vigiladas or oid not in enteras or oid in sin_nota or oid in con_suelo:
            continue
        if oid not in por_oferta or _ORDEN[r.decision] < _ORDEN[por_oferta[oid].decision]:
            por_oferta[oid] = r
    if not por_oferta:
        return
    rutas = {oid: vault / "wiki/ofertas" / f"{oid}.md" for oid in por_oferta}
    actuales = {oid: frontmatter.leer(ruta)[0] for oid, ruta in rutas.items() if ruta.exists()}
    nuevas = aplicar_strikes(actuales, {oid: (r.decision, _motivo_strike(r)) for oid, r in por_oferta.items()},
                             u["caza.poda.strikes"].valor)
    for oid, meta in nuevas.items():
        _, cuerpo = frontmatter.leer(rutas[oid])
        if meta.get("estado") == "podada":
            meta["motivo"] = (f"podada: {int(meta['strikes'])} veces seguidas por «{meta.get('motivo_strike')}»; "
                              "deja de vigilarse")
            cuerpo = _linea_estado(cuerpo, "podada", meta["motivo"])
        frontmatter.escribir(rutas[oid], meta, cuerpo)


# --- hueco por país (trovify caza hueco) ------------------------------------------------------

_ESTADO = re.compile(r"^Estado: \*\*[^*]+\*\*.*$", re.MULTILINE)
_SECCION_HUECO = re.compile(r"(## Hueco por país\n\n)(.*?)(?=\n## |\Z)", re.DOTALL)


def _linea_pais(cuerpo: str, que: str, pais: str, texto: str) -> str:
    """Cambia la línea «<que> en <pais>: …» de la sección del país, si la ficha la tiene."""
    patron = re.compile(rf"^{re.escape(que)} en {re.escape(pais)}: .*$", re.MULTILINE)
    return patron.sub(lambda _: f"{que} en {pais}: {texto}", cuerpo, count=1)


def _linea_estado(cuerpo: str, estado: str, motivo: str) -> str:
    nueva = f"Estado: **{estado}** — {_comas(motivo)}"
    return _ESTADO.sub(lambda _: nueva, cuerpo, count=1) if _ESTADO.search(cuerpo) else cuerpo


def _medida_ficha(valor, suelo: bool, nombre: str) -> Medida:
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return Medida(float(valor), suelo=suelo)
    return Medida(None, f"no medido: sin {nombre} en la ficha")


class _VigiaDeParada:
    """Cliente para el hueco: anota el primer corte (y su tipo) y, tras él, no vuelve a llamar a Meta."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.parada: str | None = None
        self.tipo: str | None = None  # «meta», «errores» o «cuota» (ver :func:`clasificar_corte`)

    def buscar(self, pais: str, **kw) -> ResultadoBusqueda:
        if self.parada is not None:
            raise SesionBloqueada(self.parada)
        try:
            r = self.cliente.buscar(pais, **kw)
        except (*_PARADAS, NavegadorError) as exc:
            self.tipo, self.parada = clasificar_corte(exc)
            if self.tipo == "cuota":
                self.parada = f"cuota del día agotada ({self.parada})"
            raise
        if r.estado == "bloqueado":
            self.tipo, self.parada = "meta", f"bloqueo de Meta: {r.motivo or 'acceso bloqueado'}"
        return r


def medir_hueco(vault: Path, *args, **kw) -> tuple[HuecoPais, str | None, str | None]:
    """:func:`_medir_hueco` con el cerrojo del cerebro (``CazaEnCurso`` si otra caza está en marcha)."""
    with _cerrojo_caza(Path(vault)):
        return _medir_hueco(vault, *args, **kw)


def _medir_hueco(
    vault: Path,
    oferta_id: str,
    pais: str,
    frases: list[str],
    cliente=None,
    hoy: date | None = None,
    idioma: str | None = None,
    perfil: str | None = None,
) -> tuple[HuecoPais, str | None, str | None]:
    """Mide el hueco de la oferta en ``pais`` con ``frases`` en el idioma local, lo guarda en la
    ficha (``huecos.<pais>``) y recalcula la decisión de cada país medido de la ficha.

    Devuelve ``(hueco, corte, tipo)``: ``corte`` es el motivo si las búsquedas se cortaron (lo no
    medido queda «no medido» en la ficha) y ``tipo`` es «meta» (bloqueo: dura el día), «errores»
    (solo este proceso) o «cuota» (búsquedas del día agotadas: final normal); None si no hubo corte."""
    vault = Path(vault)
    ruta = vault / "wiki/ofertas" / f"{oferta_id}.md"
    if not ruta.exists():
        raise FileNotFoundError(f"no existe la ficha wiki/ofertas/{oferta_id}.md")
    frases = [f.strip() for f in frases if f and f.strip()]
    if not frases:
        raise ValueError("hace falta al menos una frase en el idioma local")
    hoy = hoy or hoy_negocio()
    u = cfg_umbrales.cargar(vault / "config/umbrales.yaml")
    perfil = validar_perfil(u, perfil or _perfil_config(vault))  # antes de cualquier búsqueda
    if idioma is None:
        mercado = _mercados(vault).get(pais)
        if mercado is None:
            raise ValueError(f"no sé el idioma de {pais}: añade el país a config/mercados.yaml o usa --idioma")
        idioma = mercado.idioma
    if cliente is None:
        from trovify.caza.cache import Cache
        from trovify.caza.cliente import ClienteBibliotecaPublica
        from trovify.caza.presupuesto import Presupuesto

        cliente = ClienteBibliotecaPublica(Presupuesto.desde_umbrales(vault, hoy),
                                           cache=Cache(vault / "data" / "cache" / "biblioteca"))
    meta, cuerpo = frontmatter.leer(ruta)
    page_ids = [str(p) for p in meta.get("page_ids") or []]
    vigia = _VigiaDeParada(cliente)
    h = hueco_pais(vigia, frases, page_ids, pais, idioma, set(page_ids), hoy, u)

    huecos = dict(meta.get("huecos") or {})
    huecos[pais] = hueco_a_dict(h, hoy)
    meta["huecos"] = huecos
    hay = _hay_hueco(huecos_de(meta))
    landing = "modelable" if meta.get("checkout") and meta.get("precio") is not None else "dudoso"
    paises_ficha = meta.get("paises") or {}
    for pais_f, datos in paises_ficha.items():
        if not isinstance(datos, dict) or datos.get("estado") == "descartada":
            continue
        cotas = set(datos.get("cota_inferior") or [])
        nota = Nota(datos.get("nota") if isinstance(datos.get("nota"), (int, float)) else None)
        decision, motivo = decidir(
            nota, _medida_ficha(datos.get("c8"), "c8" in cotas, "C8"), perfil, hay, None, u, landing,
            c7=_medida_ficha(datos.get("c7"), "c7" in cotas, "C7"),
        )
        datos["estado"] = decision
        datos["motivo"] = motivo
        cuerpo = _linea_pais(cuerpo, "Decisión", pais_f, f"**{decision}** — {_comas(motivo)}")
    # Misma regla que la salida de la caza: el mejor país manda en estado, motivo y fuente.
    mejor = mejor_pais({k: d for k, d in paises_ficha.items() if isinstance(d, dict)})
    if mejor is not None and meta.get("estado") != "podada":
        datos = paises_ficha[mejor]
        meta["estado"], meta["motivo"] = datos.get("estado"), datos.get("motivo")
        if datos.get("link_biblioteca"):
            meta["fuente"] = datos["link_biblioteca"]
        varios = f" (el mejor país: {mejor})" if len(paises_ficha) > 1 else ""
        cuerpo = _linea_estado(cuerpo, str(meta["estado"]), f"{meta['motivo'] or 'sin motivo'}{varios}")
    cuerpo = _linea_pais(cuerpo, "Hueco", pais, linea_hueco(huecos_de(meta), pais).split(": ", 1)[1])
    tabla = "\n".join(_tabla_huecos(huecos_de(meta), titulo=False)) + "\n"
    if _SECCION_HUECO.search(cuerpo):
        cuerpo = _SECCION_HUECO.sub(lambda m: m.group(1) + tabla, cuerpo, count=1)
    else:
        cuerpo = cuerpo.rstrip("\n") + "\n\n## Hueco por país\n\n" + tabla
    frontmatter.escribir(ruta, meta, cuerpo)
    texto = {True: "sí", False: "no", None: "no comprobado"}[h.hueco]
    anadir_log(vault, "cazar",
               f"hueco de {oferta_id} en {pais}: {texto} (competencia {formatear_medida(h.competencia)}); "
               f"estado {meta.get('estado')}" + (f"; parada: {vigia.parada}" if vigia.parada else ""),
               [ruta.relative_to(vault).as_posix()])
    return h, vigia.parada, vigia.tipo


def _perfil_config(vault: Path) -> str:
    import yaml

    ruta = vault / "config/caza.yaml"
    if ruta.exists():
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        if isinstance(datos, dict) and isinstance(datos.get("perfil"), str):
            return datos["perfil"]
    return "tomi"
