from hello import hello


def test_hello_returns_greeting():
    assert hello() == "Hello, world!"
