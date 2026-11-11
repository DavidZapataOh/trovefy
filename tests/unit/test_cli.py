from trovefy.cli import main


def test_cli_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "trovefy 0.1.0"


def test_cli_sin_argumentos_muestra_ayuda(capsys):
    assert main([]) == 2
    err = capsys.readouterr().err.lower()
    assert "uso" in err or "usage" in err
