def ev(tool, cwd="/", **inp):
    return {"tool_name": tool, "tool_input": inp, "cwd": cwd}


def test_raw_nuevo_se_permite_y_existente_se_deniega(correr_hook, vault_tmp):
    nuevo = vault_tmp / "raw/2026-11-10/caza-europa.md"
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(nuevo), content="x"), vault_tmp)[0] == "allow"
    nuevo.parent.mkdir(parents=True); nuevo.write_text("x")
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(nuevo), content="y"), vault_tmp)[0] == "deny"
    assert correr_hook("raw_inmutable", ev("Edit", file_path=str(nuevo), old_string="x", new_string="y"), vault_tmp)[0] == "deny"
    assert correr_hook("raw_inmutable", ev("MultiEdit", file_path=str(nuevo), edits=[{"old_string": "x", "new_string": "y"}]), vault_tmp)[0] == "deny"


def test_log_solo_se_amplia(correr_hook, vault_tmp):
    log = vault_tmp / "log.md"; log.write_text("- a\n")
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(log), content="- a\n- b\n"), vault_tmp)[0] == "allow"
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(log), content="- b\n"), vault_tmp)[0] == "deny"
    assert correr_hook("raw_inmutable", ev("Edit", file_path=str(log), old_string="- a\n", new_string="- a\n- b\n"), vault_tmp)[0] == "allow"
    assert correr_hook("raw_inmutable", ev("Edit", file_path=str(log), old_string="- a\n", new_string="- z\n"), vault_tmp)[0] == "deny"
    ok = {"old_string": "- a\n", "new_string": "- a\n- b\n"}
    ok2 = {"old_string": "- b\n", "new_string": "- b\n- c\n"}
    mal = {"old_string": "- a\n", "new_string": "b"}
    assert correr_hook("raw_inmutable", ev("MultiEdit", file_path=str(log), edits=[ok, ok2]), vault_tmp)[0] == "allow"
    assert correr_hook("raw_inmutable", ev("MultiEdit", file_path=str(log), edits=[ok, mal]), vault_tmp)[0] == "deny"


def test_log_nuevo_se_permite(correr_hook, vault_tmp):
    log = vault_tmp / "log.md"; log.unlink()
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(log), content="x"), vault_tmp)[0] == "allow"


def test_raw_por_ruta_indirecta(correr_hook, vault_tmp):
    f = vault_tmp / "raw/2026-11-10/x.md"; f.parent.mkdir(parents=True); f.write_text("x")
    indirecta = str(vault_tmp / "wiki/../raw/2026-11-10/x.md")
    assert correr_hook("raw_inmutable", ev("Write", file_path=indirecta, content="y"), vault_tmp)[0] == "deny"
    enlace = vault_tmp / "wiki/enlace.md"; enlace.symlink_to(f)
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(enlace), content="y"), vault_tmp)[0] == "deny"
    rel = {"tool_name": "Write", "tool_input": {"file_path": "raw/2026-11-10/x.md", "content": "y"}, "cwd": str(vault_tmp)}
    assert correr_hook("raw_inmutable", rel, vault_tmp)[0] == "deny"


def test_vault_symlink_y_prefijo_de_cadena(correr_hook, vault_tmp, tmp_path):
    f = vault_tmp / "raw/x.md"; f.write_text("x")
    enlace = tmp_path / "v2"; enlace.symlink_to(vault_tmp)
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(enlace / "raw/x.md"), content="y"), enlace)[0] == "deny"
    parecido = vault_tmp / "raw-otro/x.md"; parecido.parent.mkdir(); parecido.write_text("x")
    assert correr_hook("raw_inmutable", ev("Write", file_path=str(parecido), content="y"), vault_tmp)[0] == "allow"


def test_notebook_en_raw(correr_hook, vault_tmp):
    nb = vault_tmp / "raw/a.ipynb"; nb.write_text("{}")
    assert correr_hook("raw_inmutable", ev("NotebookEdit", notebook_path=str(nb), new_source="x"), vault_tmp)[0] == "deny"
    nuevo = vault_tmp / "raw/b.ipynb"
    assert correr_hook("raw_inmutable", ev("NotebookEdit", notebook_path=str(nuevo), new_source="x"), vault_tmp)[0] == "allow"


def test_bash_que_borra_raw(correr_hook, vault_tmp):
    cmd = f"rm -rf {vault_tmp}/raw/2026-11-10"
    assert correr_hook("raw_inmutable", ev("Bash", command=cmd), vault_tmp)[0] == "deny"


def test_bash_operadores(correr_hook, vault_tmp):
    v = str(vault_tmp)
    denegar = [
        f"mv {v}/raw/a /tmp/a", f"sed -i s/a/b/ {v}/raw/a", f"truncate -s0 {v}/log.md",
        f"echo x > {v}/log.md", f"echo x | tee {v}/raw/a", f"cp /tmp/a {v}/raw/a",
        f"chmod 777 {v}/raw/a", f"ln -sf /tmp/a {v}/raw/a", "rm -rf $TROVEFY_VAULT/raw/x",
        f"rm {v}/log.md",
    ]
    for c in denegar:
        assert correr_hook("raw_inmutable", ev("Bash", command=c), vault_tmp)[0] == "deny", c
    permitir = [
        f"cat {v}/raw/a", f"echo x >> {v}/log.md", f"echo x | tee -a {v}/log.md",
        f"ls {v}/raw 2>&1", "rm -rf /tmp/otra", f"rm {v}/wiki/a.md",
    ]
    for c in permitir:
        assert correr_hook("raw_inmutable", ev("Bash", command=c), vault_tmp)[0] == "allow", c


def test_bash_relativo_con_cwd_en_vault(correr_hook, vault_tmp):
    e = ev("Bash", cwd=str(vault_tmp), command="rm -rf raw/2026-11-10")
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "deny"
    e = ev("Bash", cwd="/tmp", command="rm -rf raw/2026-11-10")
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "allow"


def _bash(correr_hook, vault, cmd, cwd="/"):
    return correr_hook("raw_inmutable", ev("Bash", cwd=cwd, command=cmd), vault)[0]


def test_bash_vault_con_tilde_y_home(correr_hook, vault_tmp, tmp_path, monkeypatch):
    home = tmp_path / "casa"; (home / "trovefy-cerebro/raw").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    v = home / "trovefy-cerebro"
    for c in ("rm -rf ~/trovefy-cerebro/raw/x", "rm $HOME/trovefy-cerebro/log.md",
              "rm ${HOME}/trovefy-cerebro/raw/x"):
        assert _bash(correr_hook, v, c) == "deny", c
    assert _bash(correr_hook, v, "cat ~/trovefy-cerebro/raw/x") == "allow"


def test_bash_env_del_vault_con_tilde(correr_hook, vault_tmp, tmp_path, monkeypatch):
    home = tmp_path / "casa"; (home / "v").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert _bash(correr_hook, "~/v", "rm ~/v/raw/x") == "deny"
    assert _bash(correr_hook, "$HOME/v", "rm $HOME/v/log.md") == "deny"


def test_bash_sed_inplace_en_cualquier_posicion(correr_hook, vault_tmp):
    v = str(vault_tmp)
    for c in (f"sed 's/a/b/' -i {v}/raw/a", f"sed -E 's/a/b/' -i {v}/raw/a",
              f"sed -n -i.bak p {v}/raw/a", f"sed --in-place s/a/b/ {v}/raw/a"):
        assert _bash(correr_hook, vault_tmp, c) == "deny", c
    assert _bash(correr_hook, vault_tmp, f"sed -n p {v}/raw/a") == "allow"


def test_bash_redireccion_ampersand(correr_hook, vault_tmp):
    v = str(vault_tmp)
    for c in (f"echo x >&{v}/log.md", f"echo x &>{v}/log.md"):
        assert _bash(correr_hook, vault_tmp, c) == "deny", c
    for c in (f"echo x &>>{v}/log.md", f"ls {v}/raw 2>&1", f"ls {v}/raw >&-"):
        assert _bash(correr_hook, vault_tmp, c) == "allow", c


def test_bash_tee_sin_append_aunque_haya_otro_con_append(correr_hook, vault_tmp):
    v = str(vault_tmp)
    assert _bash(correr_hook, vault_tmp, f"echo x | tee -a /tmp/z | tee {v}/log.md") == "deny"
    assert _bash(correr_hook, vault_tmp, f"echo x | tee --append {v}/log.md") == "allow"


def test_bash_cd_al_vault_y_relativo(correr_hook, vault_tmp):
    v = str(vault_tmp)
    for c in ('cd "$TROVEFY_VAULT" && rm -rf raw/x', f"cd {v}; rm -rf raw/x",
              "cd ${TROVEFY_VAULT} && rm log.md"):
        assert _bash(correr_hook, vault_tmp, c) == "deny", c
    assert _bash(correr_hook, vault_tmp, "cd /tmp && rm -rf raw/x") == "allow"


def test_edit_log_solo_al_final_y_no_vacio(correr_hook, vault_tmp):
    log = vault_tmp / "log.md"; log.write_text("- a\n- b\n")
    medio = ev("Edit", file_path=str(log), old_string="- a\n", new_string="- a\n- x\n")
    assert correr_hook("raw_inmutable", medio, vault_tmp)[0] == "deny"
    vacio = ev("Edit", file_path=str(log), old_string="", new_string="zzz")
    assert correr_hook("raw_inmutable", vacio, vault_tmp)[0] == "deny"
    final = ev("Edit", file_path=str(log), old_string="- b\n", new_string="- b\n- c\n")
    assert correr_hook("raw_inmutable", final, vault_tmp)[0] == "allow"


def test_multiedit_log_malformado(correr_hook, vault_tmp):
    log = vault_tmp / "log.md"; log.write_text("- a\n")
    for edits in ("no-lista", [], ["texto"], [{"old_string": "", "new_string": "x"}]):
        e = ev("MultiEdit", file_path=str(log), edits=edits)
        assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "deny", edits


def test_edit_log_replace_all_y_ocurrencias_repetidas(correr_hook, vault_tmp):
    log = vault_tmp / "log.md"; log.write_text("- a\n- b\n- a\n")
    e = ev("Edit", file_path=str(log), old_string="- a\n", new_string="- a\n- x\n")
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "deny"
    e = ev("Edit", file_path=str(log), old_string="- a\n", new_string="- a\n- x\n", replace_all=True)
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "deny"
    log.write_text("- b\n- a\n")
    e["tool_input"]["replace_all"] = True
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "deny"
    e["tool_input"]["replace_all"] = False
    assert correr_hook("raw_inmutable", e, vault_tmp)[0] == "allow"
    m = ev("MultiEdit", file_path=str(log), edits=[
        {"old_string": "- a\n", "new_string": "- a\n- x\n", "replace_all": True}])
    assert correr_hook("raw_inmutable", m, vault_tmp)[0] == "deny"


def test_bash_comillas_entre_base_y_subruta(correr_hook, vault_tmp, tmp_path, monkeypatch):
    home = tmp_path / "casa"; (home / "trovefy-cerebro").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    v = home / "trovefy-cerebro"
    for c in ('rm "$TROVEFY_VAULT"/raw/x', 'rm "$HOME"/trovefy-cerebro/raw/x',
              "rm '$HOME'/trovefy-cerebro/log.md", 'cd "$TROVEFY_VAULT"/ && rm raw/x',
              f'cd -- {v} && rm raw/x', f'pushd "{v}" && rm raw/x'):
        assert _bash(correr_hook, v, c) == "deny", c
    assert _bash(correr_hook, v, 'cat "$TROVEFY_VAULT"/raw/x') == "allow"


def test_bash_cwd_en_subdirectorio_del_vault(correr_hook, vault_tmp):
    (vault_tmp / "raw/2026-11-10").mkdir()
    r, w = str(vault_tmp / "raw"), str(vault_tmp / "wiki")
    dia = str(vault_tmp / "raw/2026-11-10")
    casos = [
        (r, "rm -rf 2026-11-10"),
        (dia, "echo y > x.md"),
        (w, "rm -rf ../raw/2026-11-10"),
        (w, "echo x >> ../log.md; truncate -s 0 ../log.md"),
        (str(vault_tmp), "cd raw && rm -rf 2026-11-10"),
        (w, "cd ../raw && rm -rf x"),
        (w, "cd " + r + " && rm x"),
    ]
    for cwd, cmd in casos:
        assert _bash(correr_hook, vault_tmp, cmd, cwd) == "deny", (cwd, cmd)


def test_bash_cwd_en_subdirectorio_sin_falsos_positivos(correr_hook, vault_tmp):
    w = str(vault_tmp / "wiki")
    assert _bash(correr_hook, vault_tmp, "rm -rf notas-viejas", w) == "allow"
    assert _bash(correr_hook, vault_tmp, "ls ../raw", w) == "allow"
    assert _bash(correr_hook, vault_tmp, "cat 2026-11-10/x.md", str(vault_tmp / "raw")) == "allow"
    assert _bash(correr_hook, vault_tmp, "rm x", "/tmp") == "allow"


def test_bash_cadena_de_cd_con_cwd_dentro_del_vault(correr_hook, vault_tmp):
    w, v = str(vault_tmp / "wiki"), str(vault_tmp)
    for cmd in ("cd $TROVEFY_VAULT && rm -rf raw/x", f"cd {v} && rm -rf raw/x",
                "cd .. && rm -rf raw/x", 'cd "$TROVEFY_VAULT" ; rm raw/x',
                f"cd /tmp || cd {v} && rm log.md"):
        assert _bash(correr_hook, vault_tmp, cmd, w) == "deny", cmd


def test_bash_cadena_de_cd_sin_falsos_positivos(correr_hook, vault_tmp):
    w = str(vault_tmp / "wiki")
    assert _bash(correr_hook, vault_tmp, "cd /tmp && rm -rf raw/x", w) == "allow"
    assert _bash(correr_hook, vault_tmp, "cd /tmp && ls raw", w) == "allow"
