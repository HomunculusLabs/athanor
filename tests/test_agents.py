import json
from datetime import UTC, datetime, timedelta

from athanor import agents, palette

NOW = datetime(2026, 10, 7, 4, 0, tzinfo=UTC)


def record(root, agent, limits, **extra):
    data = {"id": agent, "ready": True, "limits": limits, **extra}
    (root / f"{agent}.json").write_text(json.dumps(data))


def limit(label, percent, hours=3):
    return {
        "label": label,
        "percent": percent,
        "resetsAt": (NOW + timedelta(hours=hours)).isoformat(),
    }


def test_load_reads_claude_then_codex(tmp_path):
    record(tmp_path, "codex", [limit("Weekly (7-day)", 0.0)], tierLabel="pro")
    record(tmp_path, "claude", [limit("Session (5-hour)", 0.01)], tierLabel="Max 20x")
    plans = agents.load(tmp_path)
    assert [p.name for p in plans] == ["Claude", "ChatGPT"]
    assert plans[1].tier == "Pro"


def test_missing_records_are_skipped(tmp_path):
    record(tmp_path, "claude", [limit("Session (5-hour)", 0.2)])
    assert [p.id for p in agents.load(tmp_path)] == ["claude"]


def test_short_labels():
    assert agents.Limit("Session (5-hour)", 0, None).short == "5h"
    assert agents.Limit("Weekly (7-day)", 0, None).short == "wk"
    assert agents.Limit("Fable Weekly", 0, None).short == "fable"


def test_model_weekly_only_on_bar_when_hot(tmp_path):
    record(
        tmp_path,
        "claude",
        [limit("Session (5-hour)", 0.1), limit("Weekly (7-day)", 0.1), limit("Fable Weekly", 0.2)],
    )
    plan = agents.load(tmp_path)[0]
    assert [lim.short for lim in agents.shown(plan)] == ["wk"]  # the session is tooltip-only
    record(
        tmp_path,
        "claude",
        [limit("Session (5-hour)", 0.1), limit("Weekly (7-day)", 0.1), limit("Fable Weekly", 0.6)],
    )
    plan = agents.load(tmp_path)[0]
    assert [lim.short for lim in agents.shown(plan)] == ["wk", "fable"]


def test_meter_is_mana_left():
    assert agents.meter(1.0) == ("▰" * 10, "")
    assert agents.meter(0.98) == ("▰" * 9, "▱")  # touched at all: the last cell goes
    assert agents.meter(0.01) == ("▰", "▱" * 9)  # anything left: one cell stays lit
    assert agents.meter(0.0) == ("", "▱" * 10)


def test_low_energy_keeps_its_colour_and_tooltip_gives_the_refill(tmp_path):
    record(tmp_path, "claude", [limit("Session (5-hour)", 0.85, hours=1)])
    colors = agents.colors(palette.load("umber"))
    plans = agents.load(tmp_path)
    text, classes = agents.markup(plans, colors, NOW)
    assert classes == []
    assert colors["bar_warn"] not in text and colors["active"] not in text
    assert colors["energy.claude"] in text and " 15" not in text  # numbers are in the tooltip
    assert "full again in 1h00" in agents.tooltip(plans, NOW)


def test_each_source_has_its_own_energy(tmp_path):
    record(tmp_path, "claude", [limit("Session (5-hour)", 0.0)])
    record(tmp_path, "codex", [limit("Weekly (7-day)", 0.0)])
    colors = agents.colors(palette.load("umber"))
    claude, codex = agents.load(tmp_path)
    claude_text, classes = agents.markup_one(claude, None, colors, NOW)
    codex_text, _ = agents.markup_one(codex, None, colors, NOW)
    assert classes == []
    assert colors["energy.claude"] in claude_text and "\u263f" in claude_text
    assert colors["energy.codex"] in codex_text and "\U0001f70d" in codex_text
    assert colors["energy.claude"] != colors["energy.codex"]


def test_energies_read_on_every_bar():
    for name in ("umber", "vellum", "orpiment", "cinnabar"):
        scheme = palette.load(name)
        colors = agents.colors(scheme)
        for agent in agents.ENERGIES:
            assert palette.contrast(colors[f"energy.{agent}"], scheme.roles["bar"]) >= 4.5


def test_one_pool_at_a_time_and_toggle(tmp_path):
    record(
        tmp_path,
        "claude",
        [limit("Session (5-hour)", 0.5), limit("Weekly (7-day)", 0.1), limit("Fable Weekly", 0.7)],
    )
    picks = tmp_path / "pools.json"
    colors = agents.colors(palette.load("umber"))
    plan = agents.load(tmp_path)[0]
    text, _ = agents.markup_one(plan, agents.choices(picks).get("claude"), colors, NOW)
    assert "wk" not in text and "▰" * 9 + "<" in text  # the weekly, unlabelled
    tip = agents.tooltip([plan], NOW, agents.choices(picks))
    assert "▸ Weekly (7-day)" in tip and "Session (5-hour)" in tip  # session: tooltip only
    assert agents.toggle("claude", tmp_path, picks) == "fable"
    text, _ = agents.markup_one(plan, agents.choices(picks).get("claude"), colors, NOW)
    assert "fable" not in text and "▰" * 3 + "<" in text  # no label; the tooltip says
    assert "▸ Fable Weekly" in agents.tooltip([plan], NOW, agents.choices(picks))
    assert "Claude" not in text
    assert agents.toggle("claude", tmp_path, picks) == "wk"


def test_hidden_pool_running_low_leaves_the_sigil_alone(tmp_path):
    record(tmp_path, "claude", [limit("Session (5-hour)", 0.1), limit("Weekly (7-day)", 0.9)])
    colors = agents.colors(palette.load("umber"))
    text, classes = agents.markup_one(agents.load(tmp_path)[0], "5h", colors, NOW)
    sigil = text.split("</span>")[0]
    assert colors["energy.claude"] in sigil
    assert classes == []


def test_until():
    assert agents.until(NOW + timedelta(minutes=95), NOW) == "1h35"
    assert agents.until(NOW + timedelta(days=6, hours=8), NOW) == "6d08h"


def test_empty_refresh_keeps_last_limits(tmp_path):
    record(tmp_path, "codex", [limit("Weekly (7-day)", 0.3)], tierLabel="pro")
    assert agents.load(tmp_path)[0].limits[0].percent == 0.3
    record(tmp_path, "codex", [], usageStatusText="Codex limits unavailable")
    plan = agents.load(tmp_path)[0]
    assert plan.limits[0].percent == 0.3
    assert plan.problem == ""


def test_never_had_limits_says_why(tmp_path):
    record(tmp_path, "codex", [], usageStatusText="Codex limits unavailable")
    assert agents.load(tmp_path)[0].problem == "Codex limits unavailable"


ZAI_ANSWER = {
    "limits": [
        {"type": "TIME_LIMIT", "percentage": 3, "nextResetTime": 1792854204999},
        {"type": "TOKENS_LIMIT", "percentage": 29, "nextResetTime": 1791475764064},
    ],
    "level": "max",
}


def test_zai_record_from_quota_answer():
    rec = agents.zai_record(ZAI_ANSWER, NOW)
    assert rec["ready"] and rec["tierLabel"] == "max"
    assert [lim["label"] for lim in rec["limits"]] == ["Session (5-hour)", "MCP calls (month)"]
    assert rec["limits"][0]["percent"] == 0.29
    assert rec["limits"][0]["resetsAt"].startswith("2026-10-08")


def test_zai_burns_up_and_never_warns(tmp_path):
    rec = agents.zai_record(ZAI_ANSWER, NOW)
    rec["limits"][0]["percent"] = 0.95  # nearly all burnt: the goal, not a problem
    (tmp_path / "zai.json").write_text(json.dumps(rec))
    colors = agents.colors(palette.load("umber"))
    plan = agents.load(tmp_path)[0]
    assert plan.name == "Z.ai" and [lim.short for lim in agents.pools(plan)] == ["5h"]
    text, classes = agents.markup_one(plan, None, colors, NOW)
    assert classes == []
    assert "▰" * 9 + "<" in text and " 95" not in text
    assert "5h" not in text  # one pool, so no need to name it
    assert colors["bar_warn"] not in text and colors["active"] not in text
    assert "95% burnt" in agents.tooltip([plan], NOW)


def test_zai_untouched_starts_empty(tmp_path):
    rec = agents.zai_record({"limits": [{"type": "TOKENS_LIMIT", "percentage": 0}]}, NOW)
    (tmp_path / "zai.json").write_text(json.dumps(rec))
    colors = agents.colors(palette.load("umber"))
    text, _ = agents.markup_one(agents.load(tmp_path)[0], None, colors, NOW)
    assert text.endswith("▱" * 10 + "</span>")


def test_energy_hues_are_orange_blue_green():
    colors = agents.colors(palette.load("umber"))
    r, g, b = palette.rgb(colors["energy.claude"])
    assert r > g > b
    r, g, b = palette.rgb(colors["energy.codex"])
    assert b > g > r
    r, g, b = palette.rgb(colors["energy.zai"])
    assert g > r and g > b
