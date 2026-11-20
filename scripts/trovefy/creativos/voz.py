"""Voz en todos los vídeos (plan 21, Tarea 6): TTS de APIMart y, si no se puede, ElevenLabs (S1 8:30).

La voz va por partes (gancho, segmentos y cierre): cada trozo es un envío de pago con su fila en el libro de la
tanda y su medio en ``fuente/medios/voz-<ad>-<parte>.<ext>`` (``origen`` = el proveedor). Así cada trozo cae en su
tramo del vídeo y el UGC sincroniza la persona con su trozo. ``--solo-gancho`` genera solo el primero (la prueba de
5 s, §4.12 paso 5). Proveedor: APIMart si su precio está medido; si no, ElevenLabs con su coste aprobado; si no,
«no medido» y no se envía nada.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from trovefy.apimart.lote import Destino
from trovefy.apimart.voz import PrecioVoz, cuerpo_tts, es_audio, pedir_audio, precio_tts
from trovefy.creativos import coste, pago
from trovefy.creativos.config import ConfigCreativos, fuente_de
from trovefy.creativos.escenas import raiz_fuente
from trovefy.creativos.guion import GuionVideo
from trovefy.producto.medios import (
    CARPETA,
    escribir_medio,
    leer_manifiesto,
    registrar_medio,
)
from trovefy.voz import elevenlabs

PIEZA = "voz"
SIN_VOZ = ("no medido: ni APIMart (precio del TTS sin medir) ni ElevenLabs (plan sin contratar ni aprobar) dan una "
           "voz con precio; no se envía nada")


def precio_elevenlabs(cfg: ConfigCreativos) -> PrecioVoz | None:
    e = cfg.elevenlabs
    if e.usd_por_caracter is None or not e.modelo or not e.voz_id:
        return None
    return PrecioVoz("elevenlabs", e.modelo, e.usd_por_caracter,
                     f"plan {e.plan or 'sin nombre'} de ElevenLabs: {e.coste_mensual_usd} USD/mes ÷ "
                     f"{e.caracteres_mes} caracteres")


def elegir_proveedor(vault: Path, cfg: ConfigCreativos, carpeta: Path, forzar: str | None = None
                     ) -> tuple[PrecioVoz | None, str | None]:
    """(precio, motivo). ``forzar`` = ``apimart`` | ``elevenlabs`` (tras un Whisper que no llega, Tarea 9)."""
    apimart = precio_tts(cfg.modelo_tts, cfg.precio_tts_usd_1000,
                         fuente_de(vault, "apimart.precio_tts_usd_1000_caracteres"))
    eleven = precio_elevenlabs(cfg)
    if forzar == "apimart" or (forzar is None and apimart is not None):
        return (apimart, None) if apimart else (None, "no medido: precio del TTS de APIMart")
    if eleven is None:
        return None, SIN_VOZ
    if not coste.elevenlabs_aprobado(carpeta):
        return None, ("ElevenLabs sin aprobar: enséñale al usuario su coste y apruébalo con sus palabras "
                      "(`trovefy creativos aprobar-coste … --cita`) antes de gastar")
    return eleven, None


def id_voz(ad: str, clave: str) -> str:
    return f"voz-{ad.lower()}-{clave}"


def _sha(precio: PrecioVoz, voz: str, texto: str) -> str:
    return hashlib.sha256(f"{precio.proveedor}|{precio.modelo}|{voz}|{texto}".encode()).hexdigest()


def generar(vault: Path, p_id: str, d: Destino, carpeta: Path, guion: GuionVideo, *, precio: PrecioVoz, voz: str,
            llamar_apimart: Callable[[dict], bytes] | None = None,
            llamar_elevenlabs: Callable[[str, dict], bytes] | None = None, ahora, solo_gancho: bool = False,
            simular: bool = False, depositar=None) -> list[pago.Envio]:
    """Un envío por parte con texto de voz (o solo el gancho). Lo ya hecho con el mismo texto y voz no se repite."""
    fuente = raiz_fuente(carpeta)
    partes = guion.partes[:1] if solo_gancho else guion.partes
    salida = []
    for parte in partes:
        if not parte.texto_voz:
            continue
        id_ = id_voz(guion.ad, parte.clave)
        sha = _sha(precio, voz, parte.texto_voz)
        if pago.ya_hecho(leer_manifiesto(fuente), id_, sha):
            salida.append(pago.Envio(id_, "omitida"))
            continue
        if precio.proveedor == "apimart":
            cuerpo = cuerpo_tts(precio.modelo, parte.texto_voz, voz)

            def llamar(c=cuerpo) -> bytes:
                return llamar_apimart(c)
        else:
            cuerpo = elevenlabs.cuerpo(parte.texto_voz, precio.modelo)

            def llamar(c=cuerpo) -> bytes:
                return llamar_elevenlabs(voz, c)

        def guardar(datos: bytes, _estado, id_=id_, sha=sha, parte=parte) -> Path:
            ext = es_audio(datos) or "wav"
            archivo = f"{id_}.{ext}"
            sha_archivo = escribir_medio(fuente / CARPETA / archivo, datos, base=Path(vault))
            registrar_medio(fuente, id_, archivo, sha_archivo, precio.proveedor, base=Path(vault), prompt_sha256=sha,
                            proveedor=precio.proveedor, modelo=precio.modelo, voz=voz, parte=parte.clave,
                            caracteres=len(parte.texto_voz))
            return fuente / CARPETA / archivo

        kw = {"depositar": depositar} if depositar else {}
        salida.append(pago.enviar(vault, p_id, d, pieza=PIEZA, id_=id_, modelo=f"{precio.proveedor}:{precio.modelo}",
                                  estimado=max(precio.estimado(parte.texto_voz), Decimal("0.000001")),
                                  fuente=precio.fuente, prompt_sha=sha, llamar=llamar, guardar=guardar, ahora=ahora,
                                  simular=simular, **kw))
    return salida


def pistas(carpeta: Path, guion: GuionVideo) -> dict[str, Path]:
    """Clave de la parte → su trozo de voz ya generado (del manifiesto de ``fuente/``)."""
    fuente = raiz_fuente(carpeta)
    m = leer_manifiesto(fuente)
    salida = {}
    for p in guion.partes:
        e = m.get(id_voz(guion.ad, p.clave))
        if e:
            salida[p.clave] = fuente / CARPETA / e["archivo"]
    return salida


def elegir_voz(similitudes: dict[str, Decimal | None]) -> str | None:
    """La voz candidata con mayor similitud de Whisper (C1 51:00); sin ninguna medida, ``None``."""
    medidas = {v: s for v, s in similitudes.items() if s is not None}
    return max(medidas, key=lambda v: (medidas[v], -list(similitudes).index(v))) if medidas else None


def apimart_real(cred, abrir) -> Callable[[dict], bytes]:
    return lambda cuerpo: pedir_audio(cred, cuerpo, abrir)


def elevenlabs_real(cred_el, abrir) -> Callable[[str, dict], bytes]:
    return lambda voz, cuerpo: elevenlabs.generar(cred_el, voz, cuerpo, abrir)
