"""Offline unit tests: type detection, merging, timeline dates, favicon hash, OCR parsing, watch filters."""
import datetime as dt
import subprocess

import pytest

import catalog
import merge
import timeline
from plugins.favicon import favicon_hash, mmh3_32


@pytest.mark.parametrize("value,expected", [
    ("torvalds", "username"), ("john.doe", "username"), ("linux_foundation", "username"),
    ("someone@example.com", "email"), ("+90 532 123 45 67", "phone"), ("Emre Tuna Ulaş", "name"),
    ("Ada Lovelace", "name"), ("github.com", "domain"), ("example.com.tr", "domain"), ("8.8.8.8", "ip"),
    ("https://www.instagram.com/natgeo/", "url"),
    ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "crypto"), ("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "crypto"),
    ("", None),
])
def test_detect_type(value, expected):
    assert catalog.detect_type(value) == expected


def test_eval_default_conditions():
    assert catalog.eval_default(True, "x", {}) is True
    assert catalog.eval_default("key:hibp_api_key", "a@b.c", {"hibp_api_key": True}) is True
    assert catalog.eval_default("key:hibp_api_key", "a@b.c", {}) is False
    assert catalog.eval_default("video", "https://youtu.be/abc", {}) is True
    assert catalog.eval_default("imageurl", "https://x.org/a.jpg?s=1", {}) is True
    assert catalog.eval_default("gmail", "a@gmail.com", {"ghunt_login": False}) is False


def test_fill_and_build_include_plugins():
    assert catalog.fill({"username": "$", "top": 5}, "bob") == {"username": "bob", "top": 5}
    registry = [{"id": "maigret"}, {"id": "demo", "accepts": {"crypto": {"fields": {"address": "$"}, "default": True}}}]
    m = catalog.build(registry)
    assert [x["id"] for x in m["username"]][:2] == ["sherlock", "maigret"]
    assert m["crypto"] == [{"id": "demo", "fields": {"address": "$"}, "default": True}]


def test_merge_dedupes_and_ranks():
    results = {
        "A": [{"title": "GitHub", "url": "https://github.com/bob/", "status": "found"},
              {"title": "nope", "url": "https://x.com/bob", "status": "notfound"},
              {"title": "Search", "url": "https://www.google.com/search?q=bob", "status": "found"}],
        "B": [{"title": "GitHub", "url": "https://www.github.com/bob", "status": "maybe", "image": "https://i/a.png"},
              {"title": "Reddit", "url": "https://reddit.com/u/bob", "status": "found"}],
    }
    items, info = merge.merge(results)
    assert [x["title"] for x in items] == ["GitHub", "Reddit"]
    assert items[0]["tools"] == ["A", "B"] and items[0]["status"] == "found" and items[0]["image"]
    assert [r["title"] for r in info] == ["Search"]


def test_merge_email_groups_by_site():
    items, _ = merge.merge({"Holehe": [{"title": "spotify", "url": "https://spotify.com", "status": "found"}],
                            "Blackbird": [{"title": "Spotify", "url": "https://open.spotify.com/user/x", "status": "found"}]}, "email")
    assert len(items) == 1 and items[0]["tools"] == ["Holehe", "Blackbird"]


@pytest.mark.parametrize("text,expected", [
    ("2011-09-03T10:00:00Z", dt.date(2011, 9, 3)), ("03.09.2011", dt.date(2011, 9, 3)),
    ("January 23, 2004", dt.date(2004, 1, 23)), ("23 Ocak 2004", None), ("1969", dt.date(1969, 1, 1)), ("hello", None),
])
def test_timeline_parse_date(text, expected):
    got = timeline.parse_date(text)
    assert (got[0] if got else None) == expected


def test_timeline_build_orders_and_dedupes():
    case = {"items": [
        {"id": 1, "title": "GitHub", "url": "u1", "tool": "github", "meta": {"Hesap açılışı": "2011-09-03", "Konum": "Portland"}},
        {"id": 2, "title": "Chess", "url": "u2", "tool": "gaming", "meta": {"Joined": "2004-01-23", "Joined again": "2004-01-23"}},
    ]}
    ev = timeline.build(case)
    assert [e["date"] for e in ev] == ["2004-01-23", "2004-01-23", "2011-09-03"]


def test_mmh3_reference_vectors():
    # Values of the reference MurmurHash3 x86_32 (mmh3.hash) — what Shodan uses
    assert mmh3_32(b"foo") == -156908512
    assert mmh3_32(b"hello") == 613153351
    assert mmh3_32(b"") == 0
    assert isinstance(favicon_hash(b"\x00\x01icon"), int)


def test_tesseract_tsv_parsing(monkeypatch):
    import geo
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t96\tGALATA",
        "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t90\tKULESI",
        "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t20\tnoise",
        "4\t1\t2\t1\t1\t0\t0\t0\t1\t1\t-1\t",
    ])
    monkeypatch.setattr(geo.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(geo.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=tsv, stderr=""))
    assert geo._tesseract("x.jpg") == ["GALATA KULESI"]


def test_watch_profile_filter_and_norm():
    import watch
    assert watch.NOT_PROFILE.search("https://orcid.org/orcid-search/search?searchQuery=x")
    assert watch.NOT_PROFILE.search("https://api.mixcloud.com/x/")
    assert not watch.NOT_PROFILE.search("https://github.com/torvalds")
    assert watch.norm("https://www.GitHub.com/Torvalds/") == "github.com/torvalds"
