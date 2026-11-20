"""Estimación del coste de la tanda tal como está escrita (plan 21, Tarea 4): «te muestra el costo» (L2 15:25).

Partidas: escenas (imágenes de APIMart), clips por plantilla (segundos pedidos), voz (caracteres de todos los
guiones, más 2 voces candidatas del primer gancho para elegir por Whisper, C1 51:00) y música. Lo que no tiene
precio medido sale «no medido» y no deja aprobar el coste.
"""

from __future__ import annotations

from pathlib import Path

from trovefy.apimart.precios import Precio
from trovefy.apimart.voz import precio_tts
from trovefy.creativos.brief import FichaTanda
from trovefy.creativos.clips import ruta_musica
from trovefy.creativos.config import ConfigCreativos, fuente_de
from trovefy.creativos.coste import Estimacion, Partida
from trovefy.creativos.guion import (
    GuionInvalido,
    GuionVideo,
    cargar_escenas,
    cargar_guion,
)
from trovefy.creativos.voz import precio_elevenlabs
from trovefy.producto.medios import leer_manifiesto

CANDIDATAS_VOZ = 2


def estimar(vault: Path, cfg: ConfigCreativos, carpeta: Path, ficha: FichaTanda, precio_imagen: Precio | None,
            *, forzar_voz: str | None = None) -> Estimacion:
    partidas: list[Partida] = []
    hechas = leer_manifiesto(Path(carpeta) / "fuente")
    escenas = [e for e in cargar_escenas(carpeta) if e.id not in hechas]
    if escenas:
        partidas.append(Partida(f"escenas de APIMart ({precio_imagen.modelo if precio_imagen else 'sin modelo'})",
                                len(escenas), "imagen", precio_imagen.usd_por_imagen if precio_imagen else None,
                                precio_imagen.fuente if precio_imagen else "no medido: precio de la imagen"))
    guiones: list[GuionVideo] = []
    for e in ficha.elegidos:
        if ficha.brief(e.ad).tipo != "video":
            continue
        try:
            g = cargar_guion(carpeta, e.ad, "video", cfg)
        except (FileNotFoundError, GuionInvalido) as exc:
            partidas.append(Partida(f"guion de {e.ad} ({exc})", 1, "guion", None, "escríbelo antes de estimar"))
            continue
        guiones.append(g)  # type: ignore[arg-type]
    por_plantilla: dict[str, int] = {}
    for g in guiones:
        segs = sum(c.segundos_pedidos for clave, c in g.clips
                   if f"clip-{g.ad.lower()}-{clave}" not in hechas)
        por_plantilla[g.plantilla] = por_plantilla.get(g.plantilla, 0) + segs
    usd_seg = cfg.precio_video_usd_segundo if cfg.modelo_video else None
    for plantilla, segs in sorted(por_plantilla.items()):
        if segs:
            partidas.append(Partida(f"clips {plantilla} ({cfg.modelo_video or 'sin modelo'})", segs, "segundo",
                                    usd_seg, fuente_de(vault, "apimart.precio_video_usd_segundo") or "config"))
    letras = sum(len(p.texto_voz) for g in guiones for p in g.partes
                 if p.texto_voz and f"voz-{g.ad.lower()}-{p.clave}" not in hechas)
    if guiones and not any(k.startswith("voz-") for k in hechas):
        letras += CANDIDATAS_VOZ * len(guiones[0].partes[0].texto_voz)
    if letras:
        apimart = precio_tts(cfg.modelo_tts, cfg.precio_tts_usd_1000,
                             fuente_de(vault, "apimart.precio_tts_usd_1000_caracteres"))
        eleven = precio_elevenlabs(cfg)
        if forzar_voz == "elevenlabs" or (apimart is None and eleven is not None and forzar_voz != "apimart"):
            partidas.append(Partida("voz ElevenLabs", letras, "carácter", eleven.usd_por_caracter if eleven else None,
                                    eleven.fuente if eleven else "no medido: plan de ElevenLabs"))
        else:
            partidas.append(Partida(f"voz de APIMart ({cfg.modelo_tts})", letras, "carácter",
                                    apimart.usd_por_caracter if apimart else None,
                                    apimart.fuente if apimart else "no medido: precio del TTS de APIMart"))
    if guiones and ruta_musica(carpeta) is None and cfg.licencia_musica_comercial is True:
        partidas.append(Partida(f"música de APIMart ({cfg.modelo_musica})", 1, "pista", cfg.precio_musica_usd_pista,
                                fuente_de(vault, "apimart.precio_musica_usd_pista") or "config"))
    return Estimacion(tuple(partidas))


def total_texto(est: Estimacion) -> str:
    return f"{est.total} USD" if not est.no_medido else f"{est.total} USD + lo no medido"
