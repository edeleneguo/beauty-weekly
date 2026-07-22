import json
from pathlib import Path

from build.collect import _load_main_references, _reference_search_url

ROOT = Path(__file__).resolve().parent.parent


def test_reference_policy_is_mandatory_but_not_whitelist():
    data = json.loads((ROOT / "config" / "reference_sources.json").read_text())
    assert "Every source is searched" in data["policy"]["main_reference_semantics"]
    assert "not a whitelist" in data["policy"]["main_reference_semantics"]
    assert "Other valid public sources" in data["policy"]["additional_source_semantics"]


def test_reference_registry_covers_both_markets_and_named_sources():
    refs = _load_main_references()
    names = {item["name"] for item in refs}
    assert {item["market"] for item in refs} == {"CN", "US"}
    for expected in (
        "天猫新品创新中心 (TMIC)",
        "魔镜洞察",
        "飞瓜数据",
        "小红书 美妆 新品",
        "Sephora new beauty",
        "WGSN beauty trends",
        "Circana prestige beauty",
        "Fragrantica new perfumes",
    ):
        assert expected in names


def test_every_reference_has_a_search_url():
    for reference in _load_main_references():
        url = _reference_search_url(reference)
        assert url.startswith("https://news.google.com/rss/search?")
        assert "q=" in url
