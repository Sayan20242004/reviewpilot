from app.redact import redact


def test_redacts_aws_key():
    assert "AKIA" not in redact("key = AKIAABCDEFGHIJKLMNOP")


def test_redacts_assignment():
    assert "hunter2hunter2" not in redact('password = "hunter2hunter2"')


def test_redacts_private_key():
    s = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    assert redact(s) == "[REDACTED]"


def test_leaves_normal_code():
    assert redact("def add(a, b): return a + b") == "def add(a, b): return a + b"