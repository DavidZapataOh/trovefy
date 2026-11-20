"""``guiones/ADnn.yaml`` (los escribe Claude) y ``escenas.yaml``: lectura y validación pura (plan 21, Tareas 4, 5 y 7).

Estático: ``{formato, fondo: {tipo: color|escena|ficha|mockup|portada, ref}, bloques: [{texto, rol, posicion}]}``.

Vídeo (todos llevan voz, L2 15:25): ``{plantilla, gancho, clip_gancho: {prompt, segundos, texto_voz},
segmentos: [{texto_voz, texto_pantalla, clip: {prompt, tipo: texto|imagen, ref}|null, imagen: <ref>|null,
paginas: [n]|null, segundos}], cierre: {texto, cta, segundos, texto_voz}, voz: true}``. Las partes del vídeo son el
gancho (clip corto generado, L1 56:40), los segmentos y el cierre; cada parte tiene su trozo de voz. La suma de
segundos está en ``video.duracion_s``. En ``broll_voz`` cada segmento lleva clip (cortes de 1,5 s); en ``3d``, 4
capítulos con clip; en ``ugc``, cada segmento es la persona generada (clip con ``tipo: imagen``) que habla con su
trozo de voz; en ``zoom_lento``, imágenes fijas; en ``scroll_pdf``, páginas del PDF vigente.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from trovefy.config.yaml_config import cargar_yaml
from trovefy.creativos.config import ConfigCreativos

CARPETA = "guiones"
ROLES = ("gancho", "apoyo", "precio", "cta")
POSICIONES = ("arriba", "centro", "abajo")
FONDOS = ("color", "escena", "ficha", "mockup", "portada")
_ID_ESCENA = re.compile(r"e\d{2}")
PROPORCIONES_ESCENA = ("4:5", "9:16")
CLIP_MIN_S, CLIP_MAX_S = 4, 15


class GuionInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Bloque:
    texto: str
    rol: str
    posicion: str


@dataclass(frozen=True)
class GuionEstatico:
    ad: str
    formato: str
    fondo_tipo: str
    fondo_ref: str | None
    bloques: tuple[Bloque, ...]


@dataclass(frozen=True)
class Clip:
    prompt: str
    tipo: str  # texto | imagen
    ref: str | None
    segundos_pedidos: int


@dataclass(frozen=True)
class Parte:
    n: int  # 0 = gancho; 1..k = segmentos; k+1 = cierre
    clave: str  # g, s01…, c
    texto_voz: str
    texto_pantalla: str
    segundos: float
    clip: Clip | None
    imagen: str | None
    paginas: tuple[int, ...]


@dataclass(frozen=True)
class GuionVideo:
    ad: str
    plantilla: str
    gancho: str
    partes: tuple[Parte, ...]
    cta: str

    @property
    def duracion(self) -> float:
        return sum(p.segundos for p in self.partes)

    @property
    def texto_voz(self) -> str:
        return " ".join(p.texto_voz for p in self.partes if p.texto_voz)

    @property
    def clips(self) -> tuple[tuple[str, Clip], ...]:
        return tuple((p.clave, p.clip) for p in self.partes if p.clip is not None)

    @property
    def segmentos(self) -> tuple[Parte, ...]:
        return self.partes[1:-1]


def ruta_guion(carpeta: Path, ad: str) -> Path:
    return Path(carpeta) / CARPETA / f"{ad}.yaml"


def _leer(ruta: Path) -> object:
    if not ruta.is_file():
        raise FileNotFoundError(f"falta {ruta.parent.name}/{ruta.name}: escríbelo")
    try:
        return cargar_yaml(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GuionInvalido(f"{ruta.name} no se puede leer: {exc}") from None


def _txt(d: dict, k: str, donde: str, *, obligatorio: bool = True) -> str:
    v = d.get(k)
    if isinstance(v, str) and v.strip():
        return v.strip()
    if obligatorio:
        raise GuionInvalido(f"{donde}: falta {k}")
    return ""


def validar_estatico(ad: str, datos: object, cfg: ConfigCreativos) -> GuionEstatico:
    if not isinstance(datos, dict):
        raise GuionInvalido(f"{ad}: el guion no es un mapa")
    formato = _txt(datos, "formato", ad)
    if formato not in cfg.formatos_estaticos:
        raise GuionInvalido(f"{ad}: formato «{formato}» no es de estático")
    fondo = datos.get("fondo") or {"tipo": "color"}
    if not isinstance(fondo, dict) or fondo.get("tipo") not in FONDOS:
        raise GuionInvalido(f"{ad}: fondo.tipo es {', '.join(FONDOS)}")
    ref = fondo.get("ref") if isinstance(fondo.get("ref"), str) else None
    if fondo["tipo"] != "color" and not ref:
        raise GuionInvalido(f"{ad}: un fondo {fondo['tipo']} necesita ref (un id de medios.json)")
    if formato == "tipografico" and fondo["tipo"] != "color":
        raise GuionInvalido(f"{ad}: el tipográfico no lleva imagen")
    bloques = []
    for i, b in enumerate(datos.get("bloques") or [], 1):
        if not isinstance(b, dict):
            raise GuionInvalido(f"{ad}: bloque {i} no es un mapa")
        rol, pos = b.get("rol"), b.get("posicion", "centro")
        if rol not in ROLES or pos not in POSICIONES:
            raise GuionInvalido(f"{ad}: bloque {i}: rol {ROLES}, posicion {POSICIONES}")
        bloques.append(Bloque(_txt(b, "texto", f"{ad} bloque {i}"), rol, pos))
    if not bloques:
        raise GuionInvalido(f"{ad}: un estático lleva al menos un bloque de texto (el gancho)")
    return GuionEstatico(ad, formato, fondo["tipo"], ref, tuple(bloques))


def _segundos(v: object, donde: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise GuionInvalido(f"{donde}: segundos debe ser un número mayor que 0")
    return float(v)


def _clip(d: object, donde: str, segundos: float) -> Clip | None:
    if d is None:
        return None
    if not isinstance(d, dict):
        raise GuionInvalido(f"{donde}: clip es un mapa {{prompt, tipo, ref}}")
    tipo = d.get("tipo", "texto")
    if tipo not in ("texto", "imagen"):
        raise GuionInvalido(f"{donde}: clip.tipo es texto o imagen")
    ref = d.get("ref") if isinstance(d.get("ref"), str) else None
    if tipo == "imagen" and not ref:
        raise GuionInvalido(f"{donde}: un clip desde imagen necesita ref")
    pedidos = min(max(CLIP_MIN_S, math.ceil(segundos)), CLIP_MAX_S)
    return Clip(_txt(d, "prompt", f"{donde} clip"), tipo, ref, pedidos)


def validar_video(ad: str, datos: object, cfg: ConfigCreativos) -> GuionVideo:
    if not isinstance(datos, dict):
        raise GuionInvalido(f"{ad}: el guion no es un mapa")
    plantilla = _txt(datos, "plantilla", ad)
    if plantilla not in cfg.formatos_video:
        raise GuionInvalido(f"{ad}: plantilla «{plantilla}» no es de vídeo")
    if datos.get("voz") is not True:
        raise GuionInvalido(f"{ad}: todos los vídeos llevan voz (voz: true; L2 15:25)")
    gancho = _txt(datos, "gancho", ad)
    if len(gancho.split()) > 8:
        raise GuionInvalido(f"{ad}: el gancho pasa de 8 palabras")
    cg = datos.get("clip_gancho")
    if cfg.clip_gancho and not isinstance(cg, dict):
        raise GuionInvalido(f"{ad}: falta clip_gancho (un clip corto de gancho con texto grande, L1 56:40)")
    cg = cg or {}
    seg_g = _segundos(cg.get("segundos", cfg.gancho_s), f"{ad} clip_gancho")
    partes = [Parte(0, "g", _txt(cg, "texto_voz", f"{ad} clip_gancho", obligatorio=False) or gancho, gancho, seg_g,
                    _clip(cg, f"{ad} clip_gancho", seg_g) if cg else None, None, ())]
    crudos = datos.get("segmentos")
    if not isinstance(crudos, list) or not crudos:
        raise GuionInvalido(f"{ad}: faltan segmentos")
    for i, s in enumerate(crudos, 1):
        donde = f"{ad} segmento {i}"
        if not isinstance(s, dict):
            raise GuionInvalido(f"{donde}: no es un mapa")
        seg = _segundos(s.get("segundos"), donde)
        paginas = s.get("paginas") or []
        if not isinstance(paginas, list) or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1
                                                    for n in paginas):
            raise GuionInvalido(f"{donde}: paginas es una lista de números desde 1")
        imagen = s.get("imagen") if isinstance(s.get("imagen"), str) else None
        partes.append(Parte(i, f"s{i:02d}", _txt(s, "texto_voz", donde), _txt(s, "texto_pantalla", donde,
                                                                              obligatorio=False),
                            seg, _clip(s.get("clip"), donde, seg), imagen, tuple(paginas)))
    cierre = datos.get("cierre")
    if not isinstance(cierre, dict):
        raise GuionInvalido(f"{ad}: falta el cierre {{texto, cta, segundos}}")
    seg_c = _segundos(cierre.get("segundos", 3), f"{ad} cierre")
    texto_c = _txt(cierre, "texto", f"{ad} cierre")
    partes.append(Parte(len(crudos) + 1, "c", _txt(cierre, "texto_voz", f"{ad} cierre", obligatorio=False) or texto_c,
                        texto_c, seg_c, None, None, ()))
    g = GuionVideo(ad, plantilla, gancho, tuple(partes), _txt(cierre, "cta", f"{ad} cierre"))
    _reglas_plantilla(g, cfg)
    total = g.duracion
    if not cfg.duracion_s[0] <= total <= cfg.duracion_s[1]:
        raise GuionInvalido(f"{ad}: dura {total:g} s; debe durar de {cfg.duracion_s[0]} a {cfg.duracion_s[1]} s")
    return g


def _reglas_plantilla(g: GuionVideo, cfg: ConfigCreativos) -> None:
    segs = g.segmentos
    if g.plantilla in ("broll_voz", "claymation", "3d", "ugc") and any(s.clip is None for s in segs):
        raise GuionInvalido(f"{g.ad}: en {g.plantilla} cada segmento lleva su clip generado (L2 16:01)")
    if g.plantilla == "3d" and len(segs) != 4:
        raise GuionInvalido(f"{g.ad}: el 3D va en 4 capítulos (L2 16:01); hay {len(segs)}")
    if g.plantilla == "ugc" and any(s.clip.tipo != "imagen" for s in segs):
        raise GuionInvalido(f"{g.ad}: en el UGC cada clip parte de la imagen de la persona generada (tipo: imagen)")
    if g.plantilla == "zoom_lento" and any(not s.imagen for s in segs):
        raise GuionInvalido(f"{g.ad}: en zoom_lento cada segmento es una imagen fija (imagen: <id>)")
    if g.plantilla == "scroll_pdf" and any(not s.paginas for s in segs):
        raise GuionInvalido(f"{g.ad}: en scroll_pdf cada segmento dice qué páginas del PDF se ven")
    for s in segs:
        if s.clip is None and not s.imagen and not s.paginas:
            raise GuionInvalido(f"{g.ad} segmento {s.n}: sin clip, imagen ni páginas no hay nada que ver")


def cargar_guion(carpeta: Path, ad: str, tipo: str, cfg: ConfigCreativos) -> GuionEstatico | GuionVideo:
    datos = _leer(ruta_guion(carpeta, ad))
    return validar_video(ad, datos, cfg) if tipo == "video" else validar_estatico(ad, datos, cfg)


@dataclass(frozen=True)
class Escena:
    id: str
    prompt: str
    proporcion: str
    referencias: tuple[str, ...]


def cargar_escenas(carpeta: Path) -> list[Escena]:
    """``escenas.yaml``: ``[{id: e01…, prompt, proporcion: 4:5|9:16, referencias: [ids]}]`` ([] si no hay)."""
    ruta = Path(carpeta) / "escenas.yaml"
    if not ruta.is_file():
        return []
    datos = _leer(ruta) or []
    if not isinstance(datos, list):
        raise GuionInvalido("escenas.yaml es una lista de escenas")
    salida, vistos = [], set()
    for i, e in enumerate(datos, 1):
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not _ID_ESCENA.fullmatch(e["id"]):
            raise GuionInvalido(f"escena {i}: id e01, e02…")
        if e["id"] in vistos:
            raise GuionInvalido(f"escena {e['id']} repetida")
        vistos.add(e["id"])
        if e.get("proporcion") not in PROPORCIONES_ESCENA:
            raise GuionInvalido(f"{e['id']}: proporcion 4:5 o 9:16")
        refs = e.get("referencias") or []
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            raise GuionInvalido(f"{e['id']}: referencias es una lista de ids")
        salida.append(Escena(e["id"], _txt(e, "prompt", e["id"]), e["proporcion"], tuple(refs)))
    return salida
