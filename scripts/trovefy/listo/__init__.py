"""`/listo` (plan 20): los once gates que dicen, con evidencia, si un producto-país «se puede comprar».

Solo lee el vault, salvo `trovefy.listo.ficha.registrar_listo`, que sustituye ``paises.<PAIS>.listo`` en
``PRODUCTO.md``, añade el informe al cuerpo y, con todo en verde (o con excepciones aprobadas por el usuario donde se
admiten), pasa el país de ``con_checkout`` a ``listo`` con ``trovefy.vault.producto.avanzar_estado``.

**Excepciones aprobadas por el usuario.** Son las mismas del cierre del checkout (`trovefy.checkout.cierre`), con los
mismos archivos (``productos/<p-id>/decisiones/<fecha>-excepcion-<clave>.md``) y el mismo subcomando
(``trovefy checkout excepcion``). `EXCEPCION_DE_GATE` dice qué requisito de excepción cubre cada gate (o ``None`` si
el gate no la admite). Una excepción nunca cuenta como verde: el informe la muestra como «excepción» y el país puede
pasar a ``listo`` con ella; `trovefy.listo.veredicto.listo_para_activar` (fase 3) nunca la acepta.
"""
from __future__ import annotations

from trovefy.checkout.cierre import DOMINIO, REEMBOLSO, TRACKING, UTM

GATES: tuple[str, ...] = ("landing_movil", "utm_checkout", "compra", "entrega", "reembolso", "dominio", "dataset",
                          "creativos", "caja", "ejecutor", "stop")

# gate de /listo → requisito de excepción que lo cubre (o None: no admite excepción).
EXCEPCION_DE_GATE: dict[str, str | None] = {
    "landing_movil": None,      # sin landing que cargue en el móvil no se vende; además se mide en el instante
    "utm_checkout": UTM,        # «utm hasta el checkout»: solo /listo lo mide
    "compra": None,             # compra de prueba vista en la plataforma y una sola vez en Events Manager
    "entrega": None,            # el comprador recibe el producto
    "reembolso": REEMBOLSO,     # «reembolso registrado»: la misma excepción del cierre del checkout
    "dominio": DOMINIO,         # «dominio verificado»: solo /listo lo mide
    "dataset": TRACKING,        # «tracking verificado»: solo la parte de los eventos (TRACKING.md); un dataset
                                # compartido, mal nombrado o con dos emisores nunca se excusa
    "creativos": None,          # no aplica hasta la fase 3 (Decisión del plan 20)
    "caja": None,               # se miden en el instante: una excepción guardada taparía un fallo futuro
    "ejecutor": None,
    "stop": None,
}
