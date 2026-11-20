"""Ficha de la tanda (plan 21, Tarea 3): 20 briefs candidatos y 10 elegidos, como funciones puras.

Claude escribe ``brief.yaml``; aquí solo se valida y se escribe ``TANDA.md``. Los 20 son briefs de texto
(gratis) y solo se producen los 10 elegidos (añadido, no cambia el método). Ningún candidato cita material ajeno:
cada referencia de imagen tiene que ser un medio propio (contrato 4).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.contexto import Contexto, numero_tanda
from trovefy.idioma import detectar
from trovefy.landing.diacriticos import revisar_texto
from trovefy.producto.medios import leer_manifiesto
from trovefy.secretos import buscar_secreto

NOMBRE = "brief.yaml"
ESCENAS = "escenas.yaml"
USOS = ("test", "reserva", "renovacion")
_AD = re.compile(r"AD\d{2}")
_BRIEF = re.compile(r"b\d{2}")
_CAMPOS_BRIEF = ("objetivo", "audiencia", "linea_ancla", "tono", "restricciones", "angulo", "angulo_es",
                 "respaldo", "hook", "formato", "gancho", "texto", "titulo", "descripcion")
_OPCIONALES = ("cta", "precio_dicho", "voz", "referencias", "tipo")
_ALFABETO = ("homoglifo", "letra_rusa", "letra_ajena", "cedilla")
_LARGO_IDIOMA = 60  # con menos letras lingua no da señal: lo mira el nativo


class BriefInvalido(ValueError):
    def __init__(self, motivos: list[str]) -> None:
        super().__init__("brief.yaml no vale:\n" + "\n".join(f"- {m}" for m in motivos))
        self.motivos = motivos


@dataclass(frozen=True)
class Brief:
    id: str
    objetivo: str
    audiencia: str
    linea_ancla: str
    tono: str
    restricciones: str
    angulo: str
    angulo_es: str
    respaldo: str
    hook: str
    formato: str
    tipo: str  # imagen | video
    gancho: str
    texto: str
    titulo: str
    descripcion: str
    cta: str
    precio_dicho: str | None
    voz: str | None
    referencias: tuple[str, ...]


@dataclass(frozen=True)
class Eleccion:
    ad: str
    brief: str
    uso: str
    orden: int
    angulo_corto: str


@dataclass(frozen=True)
class FichaTanda:
    tanda: str
    grupo: str
    candidatos: tuple[Brief, ...]
    elegidos: tuple[Eleccion, ...]

    def brief(self, ad: str) -> Brief:
        e = self.eleccion(ad)
        return next(b for b in self.candidatos if b.id == e.brief)

    def eleccion(self, ad: str) -> Eleccion:
        for e in self.elegidos:
            if e.ad == ad:
                return e
        raise KeyError(f"{ad} no está entre los elegidos de la tanda")

    def nombre(self, ad: str) -> str:
        return f"{ad} {self.grupo} {self.eleccion(ad).angulo_corto}"


@dataclass(frozen=True)
class Renovacion:
    """Lo que pide el plan de renovación (Tarea 13) a ``brief.yaml``."""
    piezas: int
    angulo_ganador: str
    sobre_ganador: int
    nuevos: int


def leer_brief(carpeta: Path) -> dict:
    r = Path(carpeta) / NOMBRE
    if not r.is_file():
        raise FileNotFoundError(f"falta {NOMBRE} en la tanda: escríbelo (paso 1)")
    try:
        datos = cargar_yaml(r.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BriefInvalido([f"{NOMBRE} no se puede leer: {exc}"]) from None
    return datos if isinstance(datos, dict) else {}


def ids_propios(ctx: Contexto, carpeta: Path | None) -> set[str]:
    """Medios que un brief puede citar: los del entregable, las escenas pedidas y lo generado en la tanda."""
    ids = set(ctx.medios_propios)
    if carpeta is not None:
        r = Path(carpeta) / ESCENAS
        if r.is_file():
            try:
                escenas = cargar_yaml(r.read_text(encoding="utf-8")) or []
            except yaml.YAMLError:
                escenas = []
            ids |= {e["id"] for e in escenas if isinstance(e, dict) and isinstance(e.get("id"), str)}
        try:
            ids |= {k for k, v in leer_manifiesto(Path(carpeta) / "fuente").items()
                    if v.get("origen") in ("apimart", "propio")}
        except ValueError:
            pass
    return ids


def _respaldo(oferta: dict, clave: str) -> bool:
    """¿Existe ``clave`` (``core.mecanismo_pasos[1]``, índice desde 0) en el frontmatter de OFERTA.md?"""
    actual: object = oferta
    for parte in clave.split("."):
        m = re.fullmatch(r"([A-Za-z_][\w]*)(?:\[(\d+)\])?", parte)
        if not m or not isinstance(actual, dict) or m.group(1) not in actual:
            return False
        actual = actual[m.group(1)]
        if m.group(2) is not None:
            i = int(m.group(2))
            if not isinstance(actual, list) or i >= len(actual):
                return False
            actual = actual[i]
    return actual not in (None, "", [], {})


def _texto(d: dict, k: str) -> str | None:
    v = d.get(k)
    return v.strip() if isinstance(v, str) and v.strip() else None


def _leer_candidato(d: object, n: int, cfg: ConfigCreativos, motivos: list[str]) -> Brief | None:
    if not isinstance(d, dict):
        motivos.append(f"candidato {n}: no es un mapa")
        return None
    id_ = d.get("id")
    donde = id_ if isinstance(id_, str) else f"candidato {n}"
    if not isinstance(id_, str) or not _BRIEF.fullmatch(id_):
        motivos.append(f"{donde}: id mal escrito (b01…b{cfg.briefs_candidatos:02d})")
    sobran = set(d) - {"id", *_CAMPOS_BRIEF, *_OPCIONALES}
    if sobran:
        motivos.append(f"{donde}: campos desconocidos {', '.join(sorted(map(str, sobran)))}")
    faltan = [k for k in _CAMPOS_BRIEF if _texto(d, k) is None]
    if faltan:
        motivos.append(f"{donde}: faltan {', '.join(faltan)}")
        return None
    formato = d["formato"].strip()
    posibles = ({"video"} if formato in cfg.formatos_video else set()) | (
        {"imagen"} if formato in cfg.formatos_estaticos else set())
    tipo = d.get("tipo")
    if not posibles:
        motivos.append(f"{donde}: formato «{formato}» no está en config/creativos.yaml")
        tipo = tipo if tipo in ("imagen", "video") else "imagen"
    elif tipo is None and len(posibles) == 2:
        motivos.append(f"{donde}: «{formato}» vale para imagen y para vídeo: di tipo: imagen o tipo: video")
        tipo = "imagen"
    elif tipo is None:
        tipo = posibles.pop()
    elif tipo not in posibles:
        motivos.append(f"{donde}: un {tipo} con formato «{formato}», que no es de {tipo}")
    refs = d.get("referencias") or []
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        motivos.append(f"{donde}: referencias es una lista de ids de medios")
        refs = []
    return Brief(id=id_ if isinstance(id_, str) else f"?{n}", objetivo=d["objetivo"].strip(),
                 audiencia=d["audiencia"].strip(), linea_ancla=d["linea_ancla"].strip(), tono=d["tono"].strip(),
                 restricciones=d["restricciones"].strip(), angulo=d["angulo"].strip(),
                 angulo_es=d["angulo_es"].strip(), respaldo=d["respaldo"].strip(), hook=d["hook"].strip(),
                 formato=formato, tipo=tipo, gancho=d["gancho"].strip(), texto=d["texto"].strip(),
                 titulo=d["titulo"].strip(), descripcion=d["descripcion"].strip(),
                 cta=_texto(d, "cta") or cfg.cta_por_defecto, precio_dicho=_texto(d, "precio_dicho"),
                 voz=_texto(d, "voz"), referencias=tuple(refs))


def _revisar_candidato(b: Brief, ctx: Contexto, cfg: ConfigCreativos, propios: set[str],
                       motivos: list[str]) -> None:
    donde = b.id
    if b.hook not in cfg.hooks:
        motivos.append(f"{donde}: hook «{b.hook}» no es uno de {', '.join(cfg.hooks)}")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,59}", b.cta):
        motivos.append(f"{donde}: cta «{b.cta}» no es un código de Meta (p. ej. LEARN_MORE)")
    if not _respaldo(ctx.oferta, b.respaldo):
        motivos.append(f"{donde}: respaldo «{b.respaldo}» no existe en OFERTA.md (cada ángulo se apoya en un "
                       "hecho de nuestra oferta)")
    if len(b.texto) > cfg.principal_max:
        motivos.append(f"{donde}: el texto principal tiene {len(b.texto)} letras (máximo {cfg.principal_max})")
    if len(b.titulo) > cfg.titulo_max:
        motivos.append(f"{donde}: el título tiene {len(b.titulo)} letras (máximo {cfg.titulo_max})")
    if len(b.descripcion) > cfg.descripcion_max:
        motivos.append(f"{donde}: la descripción tiene {len(b.descripcion)} letras (máximo {cfg.descripcion_max})")
    if len(b.gancho.split()) > 8:
        motivos.append(f"{donde}: el gancho pasa de 8 palabras")
    if b.gancho.casefold() not in b.texto[:cfg.principal_visible].casefold():
        motivos.append(f"{donde}: el gancho no está en las primeras {cfg.principal_visible} letras del texto")
    if b.tipo == "video" and not b.voz:
        motivos.append(f"{donde}: un vídeo sin guion de voz (todos los vídeos llevan voz, L2 15:25)")
    if b.precio_dicho is not None and (ctx.precio_texto is None or ctx.precio_texto not in b.precio_dicho):
        motivos.append(f"{donde}: el precio dicho «{b.precio_dicho}» no es el del front en el formato del país "
                       f"({ctx.precio_texto or 'no medido'})")
    for r in b.referencias:
        if r not in propios:
            motivos.append(f"{donde}: la referencia «{r}» no es un medio propio (entregable o escenas de la tanda); "
                           "nada ajeno entra en una tanda")
    for texto in (b.texto, b.titulo, b.descripcion, b.gancho, b.voz or ""):
        malos = [h for h in revisar_texto(texto, ctx.idioma) if h.regla in _ALFABETO]
        for h in malos:
            motivos.append(f"{donde}: {h.detalle}")
    if len(b.texto) >= _LARGO_IDIOMA:
        idioma = detectar(b.texto, list(cfg.idiomas_candidatos))
        if idioma is not None and idioma != ctx.idioma:
            motivos.append(f"{donde}: el texto parece {idioma}, no {ctx.idioma}")


def _mezcla_y_plantillas(elegidos: list[Brief], ctx: Contexto, cfg: ConfigCreativos, motivos: list[str]) -> None:
    imagenes, videos = cfg.mezcla(ctx.mezcla_imagenes_pct)
    hay_i = sum(1 for b in elegidos if b.tipo == "imagen")
    hay_v = len(elegidos) - hay_i
    if (hay_i, hay_v) != (imagenes, videos):
        fuente = (f"mezcla medida del competidor ({ctx.mezcla_imagenes_pct} % imágenes, L1 46:54)"
                  if ctx.mezcla_imagenes_pct is not None else "sin mezcla medida (C2 6:50)")
        motivos.append(f"los elegidos son {hay_i} imágenes y {hay_v} vídeos; deben ser {imagenes} y {videos}: "
                       f"{fuente}")
    if videos >= len(cfg.plantillas):
        faltan = [p for p in cfg.plantillas if p not in {b.formato for b in elegidos}]
        if faltan:
            motivos.append(f"con {videos} vídeos va al menos uno de cada plantilla (L2 0:02:55, L2 16:01); "
                           f"falta {', '.join(faltan)}")


def validar_brief(datos: object, ctx: Contexto, cfg: ConfigCreativos, *, carpeta: Path | None = None,
                  renovacion: Renovacion | None = None) -> FichaTanda:
    """``FichaTanda`` si ``brief.yaml`` cumple; si no, ``BriefInvalido`` con todos los motivos."""
    motivos: list[str] = []
    if not isinstance(datos, dict):
        raise BriefInvalido(["brief.yaml no es un mapa con tanda, grupo, candidatos y elegidos"])
    tanda = datos.get("tanda")
    grupo = datos.get("grupo")
    try:
        n = numero_tanda(tanda)
        if grupo != f"G{n}":
            motivos.append(f"grupo «{grupo}»: el grupo de la tanda {tanda} es G{n}")
    except ValueError as exc:
        motivos.append(str(exc))
    crudos = datos.get("candidatos") if isinstance(datos.get("candidatos"), list) else []
    crudos_e = datos.get("elegidos") if isinstance(datos.get("elegidos"), list) else []
    piezas = renovacion.piezas if renovacion else cfg.piezas
    if renovacion is None and len(crudos) != cfg.briefs_candidatos:
        motivos.append(f"hay {len(crudos)} candidatos y deben ser {cfg.briefs_candidatos}")
    if renovacion is not None and len(crudos) < piezas:
        motivos.append(f"hay {len(crudos)} candidatos y hacen falta al menos {piezas}")
    if len(crudos_e) != piezas:
        motivos.append(f"hay {len(crudos_e)} elegidos y deben ser {piezas}")
    candidatos = [b for i, d in enumerate(crudos, 1) if (b := _leer_candidato(d, i, cfg, motivos))]
    ids = Counter(b.id for b in candidatos)
    for id_, c in ids.items():
        if c > 1:
            motivos.append(f"el candidato {id_} está repetido")
    propios = ids_propios(ctx, carpeta)
    for b in candidatos:
        _revisar_candidato(b, ctx, cfg, propios, motivos)
    por_id = {b.id: b for b in candidatos}

    elegidos: list[Eleccion] = []
    for i, e in enumerate(crudos_e, 1):
        if not isinstance(e, dict):
            motivos.append(f"elegido {i}: no es un mapa")
            continue
        ad, brief, uso, orden, corto = (e.get("ad"), e.get("brief"), e.get("uso"), e.get("orden"),
                                        e.get("angulo_corto"))
        if not isinstance(ad, str) or not _AD.fullmatch(ad):
            motivos.append(f"elegido {i}: ad «{ad}» mal escrito (AD01, AD02…)")
            continue
        if brief not in por_id:
            motivos.append(f"{ad}: el brief «{brief}» no está entre los candidatos")
        if uso not in USOS:
            motivos.append(f"{ad}: uso «{uso}» no es {', '.join(USOS)}")
        if isinstance(orden, bool) or not isinstance(orden, int) or orden < 1:
            motivos.append(f"{ad}: orden debe ser 1, 2…")
            orden = 0
        if not isinstance(corto, str) or not corto.strip() or len(corto.strip()) > 30:
            motivos.append(f"{ad}: angulo_corto de 1 a 30 letras en el idioma del país")
            corto = "?"
        elif any(h.regla in _ALFABETO for h in revisar_texto(corto, ctx.idioma)):
            motivos.append(f"{ad}: angulo_corto mezcla alfabetos")
        elegidos.append(Eleccion(ad, brief if isinstance(brief, str) else "?", uso if isinstance(uso, str) else "?",
                                 orden, corto.strip()))
    for campo in ("ad", "brief", "orden"):
        repetidos = [k for k, c in Counter(getattr(e, campo) for e in elegidos).items() if c > 1]
        if repetidos:
            motivos.append(f"elegidos con {campo} repetido: {', '.join(map(str, repetidos))}")
    if sorted(e.orden for e in elegidos) != list(range(1, len(elegidos) + 1)):
        motivos.append("el orden de los elegidos va de 1 a N sin huecos")
    elegidos_b = [por_id[e.brief] for e in elegidos if e.brief in por_id]

    if renovacion is None:
        _mezcla_y_plantillas(elegidos_b, ctx, cfg, motivos)
        usos = Counter(e.uso for e in elegidos)
        if usos.get("test", 0) != cfg.al_test or usos.get("reserva", 0) != cfg.reserva:
            motivos.append(f"uso: {usos.get('test', 0)} test y {usos.get('reserva', 0)} reserva; deben ser "
                           f"{cfg.al_test} y {cfg.reserva} (§4.1)")
        test = [por_id[e.brief] for e in elegidos if e.uso == "test" and e.brief in por_id]
        angulos = Counter(b.angulo for b in test)
        if test and (len(angulos) < 3 or max(angulos.values()) > 2):
            motivos.append("las piezas de test deben probar ángulos: al menos 3 distintos y ninguno más de 2 veces")
        if any(b.tipo == "video" for b in elegidos_b) and test and not any(b.tipo == "video" for b in test):
            motivos.append("al menos un vídeo entre las piezas de test (resolución 3)")
    else:
        if any(e.uso != "renovacion" for e in elegidos):
            motivos.append("en una renovación todos los elegidos son uso: renovacion")
        sobre = sum(1 for b in elegidos_b if b.angulo == renovacion.angulo_ganador)
        nuevos = sum(1 for b in elegidos_b if b.angulo != renovacion.angulo_ganador)
        if sobre < renovacion.sobre_ganador or nuevos < renovacion.nuevos:
            motivos.append(f"la renovación pide al menos {renovacion.sobre_ganador} piezas sobre el ángulo ganador "
                           f"«{renovacion.angulo_ganador}» y {renovacion.nuevos} de ángulo nuevo (T3 18:55)")

    todo = "\n".join(f"{b.texto}\n{b.titulo}\n{b.descripcion}\n{b.gancho}\n{b.voz or ''}" for b in candidatos)
    todo += "\n" + "\n".join(e.angulo_corto for e in elegidos)
    if buscar_secreto(todo):
        motivos.append("un texto trae algo con forma de secreto; quítalo")
    if motivos:
        raise BriefInvalido(motivos)
    return FichaTanda(tanda, grupo, tuple(candidatos), tuple(sorted(elegidos, key=lambda e: e.orden)))


def cargar_ficha(carpeta: Path, ctx: Contexto, cfg: ConfigCreativos, renovacion: Renovacion | None = None
                 ) -> FichaTanda:
    return validar_brief(leer_brief(carpeta), ctx, cfg, carpeta=carpeta, renovacion=renovacion)


def _celda(t: str) -> str:
    return t.replace("|", "/").replace("\n", " ")


def escribir_ficha(vault: Path, ctx: Contexto, ficha: FichaTanda, ahora: datetime, carpeta: Path,
                   tipo: str = "test") -> Path:
    """``TANDA.md``: contexto usado, matriz hook × formato de los candidatos, los elegidos con su porqué y los
    «no medido». Conserva el estado (aprobación, rehacer) y el historial."""
    meta, _, hist = tanda_md.leer(carpeta)
    lineas = [f"# Tanda {ficha.tanda} · {ctx.producto} · {ctx.pais} ({ficha.grupo})", "",
              "## Contexto usado", "",
              (f"- Idioma {ctx.idioma}, precio del front {ctx.precio_texto or 'no medido'}, landing "
               f"{ctx.landing_url or 'no medido'}"),
              "- Mezcla del competidor: "
              + (f"{ctx.mezcla_imagenes_pct} % imágenes (L1 46:54)" if ctx.mezcla_imagenes_pct is not None
                 else "no medido → 7 vídeos y 3 imágenes (C2 6:50)"),
              f"- Mecanismo: {ctx.mecanismo or 'no medido'}; villano: {ctx.villano or 'no medido'}", "",
              "## Matriz hook × formato (candidatos)", "", "| Hook | Formatos |", "|---|---|"]
    matriz: dict[str, list[str]] = {}
    for b in ficha.candidatos:
        matriz.setdefault(b.hook, []).append(f"{b.id} {b.formato}")
    lineas += [f"| {h} | {_celda(', '.join(v))} |" for h, v in sorted(matriz.items())]
    lineas += ["", "## Elegidos", "", "| Orden | Anuncio | Uso | Brief | Tipo | Formato | Ángulo | Por qué |",
               "|---|---|---|---|---|---|---|---|"]
    for e in ficha.elegidos:
        b = ficha.brief(e.ad)
        lineas.append(f"| {e.orden} | {_celda(ficha.nombre(e.ad))} | {e.uso} | {b.id} | {b.tipo} | {b.formato} | "
                      f"{_celda(b.angulo_es)} | {_celda(b.objetivo)} |")
    lineas += ["", "## No medido", ""] + ([f"- {m}" for m in ctx.motivos] or ["- nada"])
    meta = {**meta, "tipo": meta.get("tipo", tipo), "producto": ctx.producto, "pais": ctx.pais,
            "tanda": ficha.tanda, "grupo": ficha.grupo}
    hist.append(f"- {ahora:%Y-%m-%d %H:%M} · brief validado ({len(ficha.candidatos)} candidatos, "
                f"{len(ficha.elegidos)} elegidos)")
    return tanda_md.guardar(carpeta, meta, "\n".join(lineas), hist)
