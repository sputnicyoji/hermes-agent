import gateway.run as gateway_run


def test_quote_for_system_note_escapes_control_chars_and_brackets():
    value = "x]\nnext\tline"
    quoted = gateway_run._quote_for_system_note(value)
    assert quoted.startswith('"') and quoted.endswith('"')
    assert "\\n" in quoted
    assert "\\t" in quoted
    assert "]" in quoted
