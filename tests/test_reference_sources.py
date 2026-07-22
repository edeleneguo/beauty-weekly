import contextlib
import json
from pathlib import Path

from build.collect import _load_main_references, _reference_search_url
from build.generate_weekly import generate_products

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


def test_generation_prompt_uses_bounded_balanced_evidence(monkeypatch):
    articles = []
    for market in ("CN", "US"):
        for index in range(100):
            articles.append(
                {
                    "source": f"{market}-{index}",
                    "title": f"{market} Product {index}",
                    "url": f"https://example.org/{market.lower()}/{index}",
                    "date": "2026-07-22",
                    "summary": "x" * 500,
                    "market": market,
                }
            )

    captured = {}

    def fake_call_llm(system_prompt, user_prompt, max_tokens=8000):
        captured["user_prompt"] = user_prompt
        return '{"heat_rankings": {}, "new_product_radar": {}}'

    monkeypatch.setattr("build.generate_weekly.call_llm", fake_call_llm)
    with contextlib.suppress(ValueError):
        generate_products(
            {"articles": articles},
            "makeup",
            "2026-W30",
            "Jul 20 – Jul 26, 2026",
            "2026-07-22T00:00:00Z",
        )

    prompt = captured["user_prompt"]
    assert prompt.count("(URL:") == 30
    assert "CN Product 14" in prompt
    assert "US Product 14" in prompt
    assert "CN Product 15" not in prompt
    assert len(prompt.encode("utf-8")) < 20_000
