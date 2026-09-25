"""qtrequestory.officina.links: finding, removing and masking upload links.

Synthetic data only (public repository): hosts are ``example.invalid``,
signatures are made-up strings, keys are ``MOD_TEST_*``.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from qtrequestory.officina import links
from qtrequestory.officina.links import UploadLink, find_links, mask, mask_text, remove_links

SIG = "SYNTHETICsig0123456789abcdef%3D"


def sas(se: str | None = "2026-09-20T10%3A00%3A00Z", sp: str = "cw", name: str = "MOD_TEST_A.pdf") -> str:
    query = ["sv=2022-11-02"]
    if se is not None:
        query.append(f"se={se}")
    query += ["sr=b", f"sp={sp}", f"sig={SIG}"]
    return f"https://example.invalid/container/{name}?{'&'.join(query)}"


def _attrs(url: str, att_id: str = "att-1") -> list[dict]:
    return [
        {"key": "attachmentId", "value": att_id},
        {"key": "attachmentUrl", "value": url},
        {"key": "mandateID", "value": "0000000000"},
    ]


def nested_payload(top: str, nested: str) -> dict:
    return {
        "documents": [
            {"template": {"templateKey": "MOD_TEST_A"}, "attributes": _attrs(top)},
            {"template": {"templateKey": "MOD_TEST_B"}, "attributes": [{"key": "mandateID", "value": "1"}]},
        ],
        "dossier": {
            "dossierItems": [
                {"childItems": [
                    {"documents": [{"template": {"templateKey": "MOD_TEST_C"}, "attributes": _attrs(nested, "att-2")}]},
                ]},
            ],
        },
    }


def test_find_links_at_any_depth_with_path_expiry_and_permissions():
    payload = nested_payload(sas(), sas(se="2027-01-01T00:00:00Z", sp="r"))

    found = find_links(payload)

    assert [lk.path for lk in found] == [
        "documents[0].attributes[1]",
        "dossier.dossierItems[0].childItems[0].documents[0].attributes[1]",
    ]
    assert found[0].expires == datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    assert found[0].writable is True
    assert found[1].expires == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert found[1].writable is False
    assert isinstance(found[0], UploadLink)


def test_find_links_without_expiry_or_with_a_garbled_one():
    found = find_links({"documents": [{"attributes": _attrs(sas(se=None))}],
                        "other": [{"attributes": _attrs(sas(se="not-a-date"))}]})
    assert [lk.expires for lk in found] == [None, None]


def test_find_links_ignores_empty_and_non_string_values():
    payload = {"documents": [{"attributes": [{"key": "attachmentUrl", "value": ""},
                                             {"key": "attachmentUrl", "value": None}]}]}
    assert find_links(payload) == []


def test_remove_links_is_a_deep_copy_without_upload_attributes():
    payload = nested_payload(sas(), sas())
    before = copy.deepcopy(payload)

    cleaned = remove_links(payload)

    assert payload == before  # the input is never mutated
    assert find_links(cleaned) == []
    assert cleaned["documents"][0]["attributes"] == [{"key": "mandateID", "value": "0000000000"}]
    nested_doc = cleaned["dossier"]["dossierItems"][0]["childItems"][0]["documents"][0]
    assert nested_doc["attributes"] == [{"key": "mandateID", "value": "0000000000"}]
    assert cleaned["documents"][1] == before["documents"][1]


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


def test_parse_link_of_a_malformed_url_is_treated_as_valid():
    for url in MALFORMED:
        link = links.parse_link("x", url)
        assert link.expires is None
        assert not link.expired(datetime(2030, 1, 1, tzinfo=timezone.utc))


def test_upload_link_repr_hides_the_signature():
    link = find_links(nested_payload(sas(), sas()))[0]
    assert SIG not in repr(link)
    assert SIG not in str(link)


def test_a_repeated_se_is_not_trusted():
    url = sas() + "&se=2020-01-01T00%3A00%3A00Z"
    assert links.parse_link("x", url).expires is None
    assert links.parse_link("x", url.replace("&se=2020", "&SE=2020")).expires is None


def test_expiry_has_a_clock_skew_margin():
    link = links.parse_link("x", sas(se="2026-09-25T12%3A00%3A00Z"))
    assert not link.expired(datetime(2026, 9, 25, 12, 4, tzinfo=timezone.utc))
    assert link.expired(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))


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
