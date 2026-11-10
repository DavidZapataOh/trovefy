"""Caché de búsquedas de la Biblioteca en ``<vault>/data/cache/biblioteca/``.

Clave: sha256 de la URL reproducible. Caduca a las 12 h. Solo se guardan resultados ``ok`` y
``vacio`` (nunca bloqueos ni errores) y nunca medios: el anuncio no los lleva, solo texto y enlaces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from trovify.caza.modelo import AnuncioBiblioteca, ResultadoBusqueda
from trovify.vault.escritura import escribir_atomico
from trovify.vault.rutas import vault_root

_GUARDABLES = ("ok", "vacio")


def _anuncio_a_dict(a: AnuncioBiblioteca) -> dict:
    return {
        "library_id": a.library_id, "page_id": a.page_id, "page_name": a.page_name,
        "inicio": a.inicio.isoformat(), "fin": a.fin.isoformat() if a.fin else None,
        "activo": a.activo, "plataformas": list(a.plataformas), "texto": a.texto,
        "titulo": a.titulo, "enlace_destino": a.enlace_destino,
        "collation_id": a.collation_id, "collation_count": a.collation_count, "pais": a.pais,
    }


def _anuncio_de_dict(d: dict) -> AnuncioBiblioteca:
    return AnuncioBiblioteca(
        library_id=d["library_id"], page_id=d["page_id"], page_name=d["page_name"],
        inicio=date.fromisoformat(d["inicio"]), fin=date.fromisoformat(d["fin"]) if d["fin"] else None,
        activo=d["activo"], plataformas=tuple(d["plataformas"]), texto=d["texto"], titulo=d["titulo"],
        enlace_destino=d["enlace_destino"], collation_id=d["collation_id"],
        collation_count=d["collation_count"], pais=d["pais"],
    )


class Cache:
    def __init__(self, dir: Path, ttl_h: float = 12, ahora: Callable[[], datetime] | None = None):
        self.dir = Path(dir)
        self.ttl = timedelta(hours=ttl_h)
        self._ahora = ahora or (lambda: datetime.now(UTC))

    @classmethod
    def por_defecto(cls) -> Cache:
        return cls(vault_root() / "data" / "cache" / "biblioteca")

    def _ruta(self, url: str, max_anuncios: int) -> Path:
        # La clave incluye cuántos anuncios se pidieron: una petición corta no envenena una larga.
        clave = f"{url}|{max_anuncios}"
        return self.dir / (hashlib.sha256(clave.encode("utf-8")).hexdigest() + ".json")

    def leer(self, url: str, max_anuncios: int = 60) -> ResultadoBusqueda | None:
        """El resultado guardado si existe, es de la misma URL y petición, no ha caducado y está completo."""
        try:
            d = json.loads(self._ruta(url, max_anuncios).read_text(encoding="utf-8"))
            if d["url"] != url or d["estado"] not in _GUARDABLES:
                return None
            completo = d.get("completo") is True
            # Con menos anuncios de los pedidos, solo vale si era completo (Meta no tenía más).
            if d["estado"] == "ok" and len(d["anuncios"]) < max_anuncios and not completo:
                return None
            capturado = datetime.fromisoformat(d["capturado_en"])
            if self._ahora() - capturado > self.ttl:
                return None
            return ResultadoBusqueda(
                d["estado"], d["url"], d["total_aprox"],
                [_anuncio_de_dict(a) for a in d["anuncios"]], d["motivo"], capturado, completo,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None  # ausente o ilegible: es un fallo de caché, no un error

    def guardar(self, url: str, r: ResultadoBusqueda, max_anuncios: int = 60) -> None:
        if r.estado not in _GUARDABLES:
            return
        d = {
            "url": url, "estado": r.estado, "total_aprox": r.total_aprox, "motivo": r.motivo,
            "capturado_en": r.capturado_en.isoformat(), "completo": r.completo, "anuncios": [_anuncio_a_dict(a) for a in r.anuncios],
        }
        escribir_atomico(self._ruta(url, max_anuncios), json.dumps(d, ensure_ascii=False, indent=1) + "\n")
