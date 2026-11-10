def test_entrada_ilegible_deniega(correr_hook, vault_tmp):
    for mala in ["", "{no es json", '"una cadena"', '{"tool_name": "Write", "tool_input": 3}']:
        decision, motivo = correr_hook("meta_guard", mala, vault_tmp)
        assert decision == "deny" and "ilegible" in motivo


def test_hook_que_explota_deniega(correr_hook, vault_tmp):
    # _prueba_explota.py es un hook de prueba cuyo decidir() lanza RuntimeError
    decision, motivo = correr_hook("_prueba_explota", {"tool_name": "Read", "tool_input": {}}, vault_tmp)
    assert decision == "deny" and "fallo interno" in motivo
