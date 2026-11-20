"""Clips y música de la tanda con APIMart (plan 21, Tarea 7): clip corto de gancho (L1 56:40), B-roll, persona
generada que habla con su trozo de voz (UGC), claymation y 3D (L2 16:01), y una pista de música por tanda
(L2 15:25) que se guarda para las renovaciones. Misma disciplina que las imágenes (``trovefy.creativos.pago``).

Los clips parten de un prompt o de una imagen **propia** (escena de la tanda o medio del entregable); nada ajeno.
La música de APIMart solo se genera si su licencia comercial está comprobada (``apimart.licencia_musica_comercial``
en ``config/creativos.yaml``); si no, la aporta el usuario con su licencia (``musica --propia``).
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from trovefy.apimart.lote import Destino
from trovefy.apimart.video import cuerpo_video, estimado_clip
from trovefy.creativos import pago
from trovefy.creativos.config import ConfigCreativos
from trovefy.creativos.escenas import raiz_fuente
from trovefy.creativos.guion import GuionVideo
from trovefy.creativos.voz import id_voz
from trovefy.producto.medios import (
    CARPETA,
    escribir_medio,
    leer_manifiesto,
    registrar_medio,
)
from trovefy.vault.escritura import escribir_atomico

PIEZA_CLIP = "clip"
PIEZA_MUSICA = "musica"
ID_MUSICA = "musica"
SIN_PRECIO_VIDEO = ("no medido: modelo o precio por segundo del vídeo de APIMart (config/creativos.yaml); se mide "
                    "antes de producir")
SIN_LICENCIA = ("no medido: licencia comercial de la música de APIMart/Suno; sin ella la música la aporta el usuario "
                "con su licencia (`trovefy creativos musica --propia <archivo>`)")


@dataclass(frozen=True)
class Apimart:
    """Las llamadas reales (o falsas en los tests)."""
    enviar_video: Callable[[dict], str]
    enviar_musica: Callable[[dict], str]
    esperar_video: Callable[[str], object]
    esperar_musica: Callable[[str], object]
    descargar_video: Callable[[str], bytes]
    descargar_audio: Callable[[str], bytes]
    subir_imagen: Callable[[Path], str]
    subir_audio: Callable[[str, bytes], str]


def id_clip(ad: str, clave: str) -> str:
    return f"clip-{ad.lower()}-{clave}"


def _sha(*partes: object) -> str:
    return hashlib.sha256("|".join(map(str, partes)).encode()).hexdigest()


def medios_disponibles(carpeta: Path, propios: dict[str, Path]) -> dict[str, Path]:
    """Medios que un clip o un vídeo pueden usar: los de ``fuente/`` (escenas, copias) y los del entregable."""
    fuente = raiz_fuente(carpeta)
    salida = dict(propios)
    for k, e in leer_manifiesto(fuente).items():
        if e.get("origen") in ("apimart", "propio"):
            salida[k] = fuente / CARPETA / e["archivo"]
    return salida


def estimar_clips(guiones: list[GuionVideo], cfg: ConfigCreativos) -> tuple[int, Decimal | None]:
    """(segundos pedidos a APIMart en total, USD por segundo o ``None``)."""
    segundos = sum(c.segundos_pedidos for g in guiones for _, c in g.clips)
    return segundos, cfg.precio_video_usd_segundo if cfg.modelo_video else None


def generar_clips(vault: Path, p_id: str, d: Destino, carpeta: Path, guion: GuionVideo, cfg: ConfigCreativos, *,
                  propios: dict[str, Path], api: Apimart, ahora, solo_gancho: bool = False, simular: bool = False,
                  depositar=None) -> list[pago.Envio]:
    if not cfg.modelo_video or cfg.precio_video_usd_segundo is None:
        return [pago.Envio("*", "detenido", motivo=SIN_PRECIO_VIDEO)]
    fuente = raiz_fuente(carpeta)
    disponibles = medios_disponibles(carpeta, propios)
    salida = []
    for clave, clip in guion.clips:
        if solo_gancho and clave != "g":
            continue
        id_ = id_clip(guion.ad, clave)
        sha = _sha(cfg.modelo_video, cfg.resolucion_video, clip.prompt, clip.segundos_pedidos, clip.tipo, clip.ref,
                   guion.plantilla)
        if pago.ya_hecho(leer_manifiesto(fuente), id_, sha):
            salida.append(pago.Envio(id_, "omitida"))
            continue
        imagen = None
        if clip.tipo == "imagen":
            if clip.ref not in disponibles:
                salida.append(pago.Envio(id_, "detenido", motivo=f"«{clip.ref}» no es un medio propio; nada ajeno"))
                continue
            imagen = disponibles[clip.ref]
        audio = None
        if guion.plantilla == "ugc" and clave != "g":
            voz = leer_manifiesto(fuente).get(id_voz(guion.ad, clave))
            if voz is None:
                salida.append(pago.Envio(id_, "detenido", motivo="primero la voz de esta parte: el UGC la sincroniza"))
                continue
            audio = fuente / CARPETA / voz["archivo"]

        def llamar(clip=clip, imagen=imagen, audio=audio) -> str:
            imgs = [api.subir_imagen(imagen)] if imagen else None
            auds = [api.subir_audio(audio.stem, audio.read_bytes())] if audio else None
            cuerpo = cuerpo_video(cfg.modelo_video, clip.prompt, clip.segundos_pedidos,
                                  resolucion=cfg.resolucion_video, imagenes=imgs, audios=auds)
            return api.enviar_video(cuerpo)

        def guardar(datos: bytes, estado, id_=id_, sha=sha, clave=clave) -> Path:
            archivo = f"{id_}.mp4"
            sha_archivo = escribir_medio(fuente / CARPETA / archivo, datos, base=Path(vault))
            registrar_medio(fuente, id_, archivo, sha_archivo, "apimart", base=Path(vault), prompt_sha256=sha,
                            modelo=cfg.modelo_video, parte=clave, task_id=getattr(estado, "task_id", ""))
            return fuente / CARPETA / archivo

        kw = {"depositar": depositar} if depositar else {}
        salida.append(pago.enviar(vault, p_id, d, pieza=PIEZA_CLIP, id_=id_, modelo=cfg.modelo_video,
                                  estimado=estimado_clip(clip.segundos_pedidos, cfg.precio_video_usd_segundo),
                                  fuente="config/creativos.yaml → apimart.precio_video_usd_segundo", prompt_sha=sha,
                                  llamar=llamar, guardar=guardar, ahora=ahora, simular=simular,
                                  esperar=api.esperar_video, descargar=api.descargar_video, **kw))
    return salida


def clips_descargados(carpeta: Path, guion: GuionVideo) -> dict[str, Path]:
    fuente = raiz_fuente(carpeta)
    m = leer_manifiesto(fuente)
    return {clave: fuente / CARPETA / m[id_clip(guion.ad, clave)]["archivo"]
            for clave, _ in guion.clips if id_clip(guion.ad, clave) in m}


# --- música ------------------------------------------------------------------------------------------------------


def ruta_musica(carpeta: Path) -> Path | None:
    fuente = raiz_fuente(carpeta)
    e = leer_manifiesto(fuente).get(ID_MUSICA)
    licencia = Path(carpeta) / "musica" / "LICENCIA.md"
    return fuente / CARPETA / e["archivo"] if e and licencia.is_file() else None


def _licencia(vault: Path, carpeta: Path, texto: str) -> Path:
    ruta = Path(carpeta) / "musica" / "LICENCIA.md"
    escribir_atomico(ruta, texto)
    return ruta


def generar_musica(vault: Path, p_id: str, d: Destino, carpeta: Path, cfg: ConfigCreativos, prompt: str, *,
                   api: Apimart, ahora, simular: bool = False, fuente_licencia: str = "", depositar=None) -> pago.Envio:
    from trovefy.apimart.musica import cuerpo_musica

    if cfg.licencia_musica_comercial is not True:
        return pago.Envio(ID_MUSICA, "detenido", motivo=SIN_LICENCIA)
    if not cfg.modelo_musica or cfg.precio_musica_usd_pista is None:
        return pago.Envio(ID_MUSICA, "detenido", motivo="no medido: precio de la música de APIMart")
    fuente = raiz_fuente(carpeta)
    sha = _sha(cfg.modelo_musica, cfg.version_musica, prompt)
    if pago.ya_hecho(leer_manifiesto(fuente), ID_MUSICA, sha) and ruta_musica(carpeta):
        return pago.Envio(ID_MUSICA, "omitida")
    cuerpo = cuerpo_musica(cfg.modelo_musica, cfg.version_musica, prompt)

    def guardar(datos: bytes, estado) -> Path:
        archivo = "musica.mp3"
        sha_archivo = escribir_medio(fuente / CARPETA / archivo, datos, base=Path(vault))
        registrar_medio(fuente, ID_MUSICA, archivo, sha_archivo, "apimart", base=Path(vault), prompt_sha256=sha,
                        modelo=cfg.modelo_musica, task_id=getattr(estado, "task_id", ""))
        _licencia(vault, carpeta, f"# Licencia de la música\n\nGenerada con APIMart ({cfg.modelo_musica}). Uso "
                                  f"comercial comprobado: {fuente_licencia or 'config/creativos.yaml'}.\n")
        return fuente / CARPETA / archivo

    kw = {"depositar": depositar} if depositar else {}
    return pago.enviar(vault, p_id, d, pieza=PIEZA_MUSICA, id_=ID_MUSICA, modelo=cfg.modelo_musica,
                       estimado=cfg.precio_musica_usd_pista,
                       fuente="config/creativos.yaml → apimart.precio_musica_usd_pista", prompt_sha=sha,
                       llamar=lambda: api.enviar_musica(cuerpo), guardar=guardar, ahora=ahora, simular=simular,
                       esperar=api.esperar_musica, descargar=api.descargar_audio, **kw)


def musica_propia(vault: Path, carpeta: Path, origen: Path) -> Path:
    """La pista que aporta el usuario en ``config/creativos/musica/`` con su licencia al lado (``<archivo>.licencia.md``):
    se copia a la tanda (``origen: propio``) y la licencia a ``musica/LICENCIA.md``."""
    vault = Path(vault)
    base = (vault / "config" / "creativos" / "musica").resolve()
    origen = Path(origen).resolve()
    if base not in origen.parents or not origen.is_file() or origen.is_symlink():
        raise ValueError("la música propia va en config/creativos/musica/ del vault")
    licencia = origen.with_name(origen.name + ".licencia.md")
    if not licencia.is_file():
        raise ValueError(f"falta la licencia al lado: {licencia.name} (sin licencia comercial la plataforma de música "
                         "puede reclamar el anuncio)")
    if origen.suffix.lower() not in (".mp3", ".wav", ".m4a"):
        raise ValueError("la música va en mp3, wav o m4a")
    fuente = raiz_fuente(carpeta)
    archivo = f"musica{origen.suffix.lower()}"
    sha = escribir_medio(fuente / CARPETA / archivo, origen.read_bytes(), base=vault)
    registrar_medio(fuente, ID_MUSICA, archivo, sha, "propio", base=vault,
                    copia_de=origen.relative_to(vault.resolve()).as_posix())
    _licencia(vault, carpeta, licencia.read_text(encoding="utf-8"))
    return fuente / CARPETA / archivo


def reutilizar_musica(vault: Path, carpeta_origen: Path, carpeta: Path) -> Path:
    """La música guardada de otra tanda del mismo producto-país («la segunda tanda sale casi gratis», L2 15:25)."""
    previa = ruta_musica(carpeta_origen)
    if previa is None:
        raise ValueError(f"la tanda {Path(carpeta_origen).name} no tiene música con su licencia")
    fuente = raiz_fuente(carpeta)
    sha = escribir_medio(fuente / CARPETA / previa.name, previa.read_bytes(), base=Path(vault))
    registrar_medio(fuente, ID_MUSICA, previa.name, sha, "propio", base=Path(vault),
                    copia_de=previa.relative_to(vault).as_posix())
    destino = Path(carpeta) / "musica"
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(carpeta_origen) / "musica" / "LICENCIA.md", destino / "LICENCIA.md")
    return fuente / CARPETA / previa.name
