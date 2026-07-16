import pytest

from scripts.smoke_daytona import gateway_origin


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://gateway.example/v1", "https://gateway.example/"),
        ("http://172.20.1.2:4000/api", "http://172.20.1.2:4000/"),
    ],
)
def test_gateway_origin_returns_credential_free_origin(
    value: str, expected: str
) -> None:
    assert gateway_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    ["gateway.example", "ftp://gateway.example", "https://user:secret@gateway.example"],
)
def test_gateway_origin_rejects_unsafe_or_invalid_url(value: str) -> None:
    with pytest.raises(ValueError):
        gateway_origin(value)
