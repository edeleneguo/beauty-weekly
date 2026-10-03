import json

from build.generate_monthly import (
    _dedupe_cross_tier_panels,
    _dedupe_market_observation_panels,
    _generate_panel_drafts,
)

PANELS = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")


def test_panel_generation_calls_each_panel_independently():
    calls = []

    def fake_call(_system_prompt, user_prompt, max_tokens=8000):
        panel = next(panel for panel in PANELS if f"[PANEL={panel}]" in user_prompt)
        calls.append(panel)
        return json.dumps(
            {
                "heat_rankings": [{"name": f"{panel} heat"}],
                "new_product_radar": [{"name": f"{panel} radar"}],
            }
        )

    result = _generate_panel_drafts(
        "system",
        {panel: f"evidence for {panel}" for panel in PANELS},
        call=fake_call,
    )

    assert calls == list(PANELS)
    assert result["heat_rankings"]["US MASSTIGE"][0]["name"] == "US MASSTIGE heat"
    assert result["new_product_radar"]["CN MASSTIGE"][0]["name"] == "CN MASSTIGE radar"


def test_panel_generation_accepts_legacy_nested_shape():
    def fake_call(_system_prompt, user_prompt, max_tokens=8000):
        panel = next(panel for panel in PANELS if f"[PANEL={panel}]" in user_prompt)
        return json.dumps(
            {
                "heat_rankings": {panel: [{"name": panel}]},
                "new_product_radar": {panel: []},
            }
        )

    result = _generate_panel_drafts(
        "system", {panel: "evidence" for panel in PANELS}, call=fake_call
    )

    assert all(result["heat_rankings"][panel] == [{"name": panel}] for panel in PANELS)


def test_cn_masstige_prompt_defines_accessible_tier_for_mixed_roundups():
    prompts = {}

    def fake_call(_system_prompt, user_prompt, max_tokens=8000):
        panel = next(panel for panel in PANELS if f"[PANEL={panel}]" in user_prompt)
        prompts[panel] = user_prompt
        return json.dumps({"heat_rankings": [], "new_product_radar": []})

    _generate_panel_drafts(
        "system", {panel: "mixed-tier roundup evidence" for panel in PANELS}, call=fake_call
    )

    cn_prompt = prompts["CN MASSTIGE"]
    assert "accessible-prestige, lifestyle, indie, celebrity, and mainstream" in cn_prompt
    assert "does not require the brand to be headquartered in mainland China" in cn_prompt
    assert "CN, TW, or HK" in cn_prompt


def test_cross_tier_duplicates_keep_only_the_first_market_panel():
    result = {
        "heat_rankings": {
            "CN LUXURY": [{"name": "Narciso all of me"}],
            "CN MASSTIGE": [
                {"name": "Narciso all of me"},
                {"name": "SW19 5pm Rose Petal"},
            ],
        },
        "new_product_radar": {},
    }

    _dedupe_cross_tier_panels(result)

    assert [p["name"] for p in result["heat_rankings"]["CN LUXURY"]] == [
        "Narciso all of me"
    ]
    assert [p["name"] for p in result["heat_rankings"]["CN MASSTIGE"]] == [
        "SW19 5pm Rose Petal"
    ]


def test_market_observation_deduplicates_products_repeated_across_sections():
    result = {
        "market_observation": {
            "CN LUXURY": [
                {"name": "Tom Ford Architecture Foundation", "score": 82},
                {"name": "  tom ford architecture foundation ", "score": 79},
                {"name": "Albion Studio Foundation", "score": 77},
            ]
        }
    }

    _dedupe_market_observation_panels(result)

    assert [
        product["name"]
        for product in result["market_observation"]["CN LUXURY"]
    ] == ["Tom Ford Architecture Foundation", "Albion Studio Foundation"]


def test_masstige_prompt_excludes_products_already_used_in_luxury_panel():
    prompts = {}

    def fake_call(_system_prompt, user_prompt, max_tokens=8000):
        panel = next(panel for panel in PANELS if f"[PANEL={panel}]" in user_prompt)
        prompts[panel] = user_prompt
        rows = (
            [{"name": "Narciso all of me", "name_cn": "Narciso 倾我淡香精"}]
            if panel == "CN LUXURY"
            else []
        )
        return json.dumps({"heat_rankings": rows, "new_product_radar": rows})

    _generate_panel_drafts(
        "system", {panel: "evidence" for panel in PANELS}, call=fake_call
    )

    assert "Do not repeat products already assigned to CN LUXURY" in prompts["CN MASSTIGE"]
    assert "Narciso all of me" in prompts["CN MASSTIGE"]
    assert "Narciso 倾我淡香精" in prompts["CN MASSTIGE"]
