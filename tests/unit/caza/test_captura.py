from types import SimpleNamespace

from trovefy.caza.captura import escuchar_respuestas


class _Pagina:
    def on(self, _evento, oyente):
        self.oyente = oyente


def _respuesta(url, post_data, cuerpo="{}"):
    peticion = SimpleNamespace(post_data=post_data, headers={"cookie": "c_user=1"})
    return SimpleNamespace(url=url, status=200, request=peticion, text=lambda: cuerpo,
                           headers={"set-cookie": "x"})


def test_guarda_el_nombre_de_la_consulta_y_nada_mas():
    pagina = _Pagina()
    respuestas = escuchar_respuestas(pagina, max_respuestas=5)
    secreto = "lsd" + "=" + "A" * 12
    pagina.oyente(_respuesta("https://www.facebook.com/api/graphql/",
                             f"av=0&{secreto}&fb_api_req_friendly_name=AdLibrarySearchPaginationQuery&variables=%7B%7D"))
    pagina.oyente(_respuesta("https://www.facebook.com/api/graphql/", None))
    assert respuestas == [
        {"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": "{}",
         "consulta": "AdLibrarySearchPaginationQuery"},
        {"url": "https://www.facebook.com/api/graphql/", "estado": 200, "cuerpo": "{}", "consulta": None},
    ]
