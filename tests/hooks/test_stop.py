def ev(tool, cwd="/", **inp):
    return {"tool_name": tool, "tool_input": inp, "cwd": cwd}


def activar(vault):
    (vault / ".trovefy/STOP").write_text("")


def test_stop_bloquea_el_buzon(correr_hook, vault_tmp):
    activar(vault_tmp)
    e = {"tool_name": "Write", "tool_input": {"file_path": "/var/spool/trovefy/entrada/P-1.json", "content": "{}"}}
    decision, motivo = correr_hook("stop", e, vault_tmp)
    assert decision == "deny" and "STOP activo: no se deposita nada" in motivo


def test_sin_stop_no_bloquea(correr_hook, vault_tmp):
    e = {"tool_name": "Write", "tool_input": {"file_path": str(vault_tmp / "propuestas/P-1.md"), "content": "x"}}
    assert correr_hook("stop", e, vault_tmp)[0] == "allow"
    e = ev("Write", file_path="/var/spool/trovefy/entrada/P-1.json", content="{}")
    assert correr_hook("stop", e, vault_tmp)[0] == "allow"


def test_stop_bloquea_propuestas_en_todas_las_herramientas(correr_hook, vault_tmp):
    activar(vault_tmp)
    destino = str(vault_tmp / "propuestas/P-1.md")
    assert correr_hook("stop", ev("Write", file_path=destino, content="x"), vault_tmp)[0] == "deny"
    assert correr_hook("stop", ev("Edit", file_path=destino, old_string="a", new_string="b"), vault_tmp)[0] == "deny"
    assert correr_hook("stop", ev("MultiEdit", file_path=destino, edits=[]), vault_tmp)[0] == "deny"
    indirecta = str(vault_tmp / "wiki/../propuestas/P-1.md")
    assert correr_hook("stop", ev("Write", file_path=indirecta, content="x"), vault_tmp)[0] == "deny"
    rel = ev("Write", cwd=str(vault_tmp), file_path="propuestas/P-1.md", content="x")
    assert correr_hook("stop", rel, vault_tmp)[0] == "deny"


def test_stop_enlace_a_propuestas(correr_hook, vault_tmp):
    activar(vault_tmp)
    (vault_tmp / "propuestas").mkdir()
    (vault_tmp / "wiki/enlace").symlink_to(vault_tmp / "propuestas", target_is_directory=True)
    e = ev("Write", file_path=str(vault_tmp / "wiki/enlace/P-1.md"), content="x")
    assert correr_hook("stop", e, vault_tmp)[0] == "deny"


def test_stop_no_bloquea_otras_rutas_ni_lecturas(correr_hook, vault_tmp):
    activar(vault_tmp)
    assert correr_hook("stop", ev("Write", file_path=str(vault_tmp / "wiki/x.md"), content="x"), vault_tmp)[0] == "allow"
    assert correr_hook("stop", ev("Write", file_path=str(vault_tmp / "propuestas-viejas/x.md"), content="x"), vault_tmp)[0] == "allow"
    assert correr_hook("stop", ev("Read", file_path="/var/spool/trovefy/entrada/P-1.json"), vault_tmp)[0] == "allow"


def test_stop_bash(correr_hook, vault_tmp):
    activar(vault_tmp)
    v = str(vault_tmp)
    for cmd in [
        "cp x.json /var/spool/trovefy/entrada/P-1.json",
        "echo '{}' > '/var/spool/trovefy/entrada/P-1.json'",
        f"echo x > {v}/propuestas/P-1.md",
        'echo x > "$TROVEFY_VAULT/propuestas/P-1.md"',
        "echo x > ${TROVEFY_VAULT}/propuestas/P-1.md",
        f"cd {v} && echo x > propuestas/P-1.md",
    ]:
        decision, motivo = correr_hook("stop", ev("Bash", command=cmd), vault_tmp)
        assert decision == "deny" and "STOP activo" in motivo, cmd
    assert correr_hook("stop", ev("Bash", command="ls /tmp && echo hola"), vault_tmp)[0] == "allow"


def test_stop_bash_cwd_en_subdirectorio_del_vault(correr_hook, vault_tmp):
    activar(vault_tmp)
    (vault_tmp / "propuestas").mkdir()
    casos = [
        (str(vault_tmp / "propuestas"), "echo x > P.md"),
        (str(vault_tmp / "wiki"), "echo x > ../propuestas/P.md"),
        (str(vault_tmp), "cd propuestas && touch P.md"),
    ]
    for cwd, cmd in casos:
        decision, motivo = correr_hook("stop", ev("Bash", cwd=cwd, command=cmd), vault_tmp)
        assert decision == "deny" and "STOP activo" in motivo, (cwd, cmd)
    for cwd, cmd in [(str(vault_tmp / "propuestas"), "ls"), (str(vault_tmp / "wiki"), "echo x > n.md")]:
        assert correr_hook("stop", ev("Bash", cwd=cwd, command=cmd), vault_tmp)[0] == "allow", (cwd, cmd)


def test_stop_escrituras_no_destructivas_por_cwd_o_ruta_relativa(correr_hook, vault_tmp):
    activar(vault_tmp)
    (vault_tmp / "propuestas").mkdir()
    p, w = str(vault_tmp / "propuestas"), str(vault_tmp / "wiki")
    casos = [
        (p, "echo x >> P.md"),
        (w, "echo x >> ../propuestas/P.md"),
        (w, "echo x | tee -a ../propuestas/P.md"),
        (w, "echo x | tee ../propuestas/P.md"),
        (p, """python3 -c 'open("P.md","w")'"""),
        (w, "cd ../propuestas && python3 -c 'pass'"),
        (str(vault_tmp), "cd propuestas && cat P.md > otro.md"),
        (p, "find . -delete"),
        (p, "find . -exec rm {} ;"),
        (p, "echo x > P.md"),
        (p, "cat P.md; sed -i s/a/b/ P.md"),
    ]
    for cwd, cmd in casos:
        decision, motivo = correr_hook("stop", ev("Bash", cwd=cwd, command=cmd), vault_tmp)
        assert decision == "deny" and "STOP activo" in motivo, (cwd, cmd)


def test_stop_lecturas_en_propuestas_siguen_permitidas(correr_hook, vault_tmp):
    activar(vault_tmp)
    (vault_tmp / "propuestas").mkdir()
    p, w = str(vault_tmp / "propuestas"), str(vault_tmp / "wiki")
    for cwd, cmd in [(p, "ls -la"), (p, "cat P.md | grep x | wc -l"), (p, "head -n 3 P.md"),
                     (p, "find . -name '*.md'"), (p, "pwd && stat P.md"), (p, "echo hola"),
                     (p, "ls 2>/dev/null"), (w, "cat ../propuestas/P.md"), (w, "echo x >> n.md")]:
        assert correr_hook("stop", ev("Bash", cwd=cwd, command=cmd), vault_tmp)[0] == "allow", (cwd, cmd)


def test_sin_stop_escrituras_en_propuestas_se_permiten(correr_hook, vault_tmp):
    (vault_tmp / "propuestas").mkdir()
    e = ev("Bash", cwd=str(vault_tmp / "propuestas"), command="echo x >> P.md")
    assert correr_hook("stop", e, vault_tmp)[0] == "allow"


def test_file_ya_no_es_de_solo_lectura(correr_hook, vault_tmp):
    activar(vault_tmp)
    (vault_tmp / "propuestas").mkdir()
    p = str(vault_tmp / "propuestas")
    for cmd in ("file -C -m magic", "file P.md"):
        decision, motivo = correr_hook("stop", ev("Bash", cwd=p, command=cmd), vault_tmp)
        assert decision == "deny" and "STOP activo" in motivo, cmd
