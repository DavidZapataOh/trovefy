from trovify.idioma import detectar


def test_detectar():
    assert detectar("Fișe de terapie gata de printat, acces imediat după plată", ["ro", "it", "es"]) == "ro"
    assert detectar("Schede pronte per il sostegno scolastico, accesso immediato", ["ro", "it", "es"]) == "it"
    assert detectar("PDF", ["ro", "it"]) is None


def test_un_solo_candidato_o_ninguno():
    assert detectar("Schede pronte per il sostegno scolastico, accesso immediato", []) is None
    assert detectar("Schede pronte per il sostegno scolastico, accesso immediato", ["xx"]) is None
