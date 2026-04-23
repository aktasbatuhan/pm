import json

from tools import pm_brief_tools


def test_normalize_action_items_parses_and_applies_defaults(monkeypatch):
    monkeypatch.setattr(
        pm_brief_tools,
        "_extract_references",
        lambda text: [{"type": "issue", "url": "https://example.com/1", "title": text.strip()}],
    )

    items, error = pm_brief_tools._normalize_action_items(
        json.dumps(
            [
                {"title": "Investigate drop", "description": "Check conversion regression"},
                {
                    "category": "team",
                    "title": "Sync with eng",
                    "description": "Review blockers",
                    "priority": "high",
                    "references": [{"type": "pr", "url": "https://example.com/pr/1", "title": "PR 1"}],
                },
            ]
        )
    )

    assert error is None
    assert items == [
        {
            "category": "risk",
            "title": "Investigate drop",
            "description": "Check conversion regression",
            "priority": "medium",
            "references": [
                {
                    "type": "issue",
                    "url": "https://example.com/1",
                    "title": "Investigate drop Check conversion regression",
                }
            ],
        },
        {
            "category": "team",
            "title": "Sync with eng",
            "description": "Review blockers",
            "priority": "high",
            "references": [{"type": "pr", "url": "https://example.com/pr/1", "title": "PR 1"}],
        },
    ]


def test_normalize_action_items_rejects_invalid_json():
    items, error = pm_brief_tools._normalize_action_items('{"not":"an array"}')
    assert items is None
    assert error == "action_items must be valid JSON array"


def test_normalize_action_items_rejects_non_list_input():
    items, error = pm_brief_tools._normalize_action_items({"title": "invalid"})
    assert items is None
    assert error == "action_items must be valid JSON array"
