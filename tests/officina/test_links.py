"""qtrequestory.officina.links: masking signed links (payloads are sent as they are).

Synthetic data only (public repository): hosts are ``example.invalid``,
signatures are made-up strings, keys are ``MOD_TEST_*``.
"""
from __future__ import annotations

import pytest

from qtrequestory.officina import links
from qtrequestory.officina.links import mask, mask_text

SIG = "SYNTHETICsig0123456789abcdef%3D"


def sas(se: str | None = "2026-09-20T10%3A00%3A00Z", sp: str = "cw", name: str = "MOD_TEST_A.pdf") -> str:
    query = ["sv=2022-11-02"]
    if se is not None:
        query.append(f"se={se}")
    query += ["sr=b", f"sp={sp}", f"sig={SIG}"]
    return f"https://example.invalid/container/{name}?{'&'.join(query)}"


def test_mask_keeps_scheme_host_and_path_only():
    assert mask(sas()) == "https://example.invalid/container/MOD_TEST_A.pdf?sig=***"
    assert mask("https://example.invalid/a/b") == "https://example.invalid/a/b"
    assert SIG not in mask(sas())


def test_mask_text_masks_every_url_inside_a_message():
    text = f"errore su {sas()} e poi su {sas(name='B.pdf')}."
    masked = mask_text(text)
    assert SIG not in masked
    assert "sig=***" in masked
    assert masked.startswith("errore su https://example.invalid/container/MOD_TEST_A.pdf?sig=***")


def test_module_has_no_real_hostnames():
    import re
    from pathlib import Path
    src = Path(links.__file__).read_text(encoding="utf-8")
    assert not re.search(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}", src)


# ------------------------------------------------------------ fix round 1 ---

MALFORMED = [
    f"https://example.invalid:abc/b?se=2027-01-01&sig={SIG}",  # bad port
    f"https://[example.invalid/b?se=2027-01-01&sig={SIG}",     # broken IPv6 bracket
]


def test_mask_never_raises_on_malformed_urls():
    for url in MALFORMED:
        assert SIG not in mask(url)
        assert SIG not in mask_text(f"vedi {url} qui")


@pytest.mark.parametrize("text", [
    f"a?sv=1&sig%3D{SIG}",
    f"a?sv=1\\u0026sig\\u003d{SIG}",
    f"a?sv=1&amp;sig={SIG}",
    f"a?sv=1&amp;sig&#61;{SIG}",
    f"//example.invalid/c/b.pdf?sv=1&sig={SIG}",
    f'{{"u": "https:\\/\\/example.invalid\\/c?sig={SIG}"}}',
    f"SIG={SIG}",
])
def test_mask_text_masks_signatures_in_any_encoding(text):
    assert SIG not in mask_text(text)
    assert SIG.encode() not in links.mask_bytes(text.encode())
