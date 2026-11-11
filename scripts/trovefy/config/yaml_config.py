"""Lector YAML de la configuración del cerebro, con booleanos al estilo YAML 1.2.

PyYAML sigue YAML 1.1, que lee ``NO``, ``yes``, ``on`` u ``off`` como booleanos: ``NO:`` (Noruega)
en ``config/mercados.yaml`` acabaría siendo ``False``. Aquí solo ``true``/``false`` son booleanos;
lo demás queda como texto. Así funcionan también los cerebros ya creados con ``NO:`` sin comillas.
"""

from __future__ import annotations

import re

import yaml


class CargadorConfig(yaml.SafeLoader):
    """``SafeLoader`` cuyo único booleano implícito es ``true``/``false`` (YAML 1.2)."""


CargadorConfig.yaml_implicit_resolvers = {
    inicial: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for inicial, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
CargadorConfig.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def cargar_yaml(texto: str):
    """Como ``yaml.safe_load``, pero ``NO``, ``yes``, ``on``, ``off``… quedan como texto."""
    return yaml.load(texto, Loader=CargadorConfig)  # CargadorConfig hereda de SafeLoader
