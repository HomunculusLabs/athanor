from athanor import status

GIB = 2**30
TOTAL = 32754487296  # 30.5 GiB, a 32 GB machine less what the firmware keeps


def test_memory_reads_available_and_total(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       31986804 kB\nMemFree:         7634992 kB\nMemAvailable:   16970000 kB\n"
    )
    assert status.memory(meminfo) == (16970000 * 1024, 31986804 * 1024)


def test_cpu_delta(tmp_path):
    stat = tmp_path / "stat"
    cpu = status.Cpu(stat)
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    assert cpu.percent() is None
    stat.write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")
    assert cpu.percent() == 50


def test_line():
    r = status.Reading(
        workspace=3,
        disk_free=212 * GIB,
        cpu=14,
        mem_free=int(17.6 * GIB),
        mem_total=TOTAL,
        minutes=48213,
    )
    assert status.line(r) == "Dlvl:3  $:212G  Hp:17(31)  Str:14%  T:48213"


def test_low_memory_is_hurt():
    base = dict(workspace=1, disk_free=0, cpu=0, mem_total=TOTAL, minutes=0)
    assert status.classes(status.Reading(mem_free=TOTAL // 2, **base)) == []
    assert status.classes(status.Reading(mem_free=TOTAL // 6, **base)) == ["hurt"]
    assert status.classes(status.Reading(mem_free=TOTAL // 20, **base)) == ["hurt", "dying"]


def test_workspace_events_trigger_a_redraw():
    assert status.wants_redraw(b"activewindow>>foot,zsh\nworkspace>>3\n")
    assert status.wants_redraw(b"workspacev2>>3,3\n")
    assert not status.wants_redraw(b"activewindow>>foot,zsh\nwindowtitle>>56056e\n")


def test_markup_highlights_like_nethack():
    import re

    from athanor import palette

    scheme = palette.load("umber")
    roles, hues = scheme.roles, palette.bar_hues(scheme)
    r = status.Reading(3, 212 * GIB, 14, 20 * GIB, TOTAL, 48)
    text = status.markup(r, roles, hues)
    assert re.sub("<[^>]+>", "", text) == status.line(r)
    assert f'<span foreground="{hues["bar_gold"]}">212G</span>' in text
    assert f'<span foreground="{hues["bar_green"]}">20(31)</span>' in text
    assert '">14%' not in text  # an idle CPU stays plain
    hurt = status.Reading(3, 1, 90, 3 * GIB, TOTAL, 1)
    text = status.markup(hurt, roles, hues)
    assert f'<span foreground="{roles["bar_warn"]}">3(31)</span>' in text
    assert f'<span foreground="{roles["bar_warn"]}">90%</span>' in text
