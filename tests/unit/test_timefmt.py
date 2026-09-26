from datetime import datetime, timezone

from creopdm.utils.timefmt import as_utc, format_local, format_local_pretty, to_local


def test_format_local_converts_utc_to_machine_clock():
    stamp = datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc)
    assert format_local(stamp) == stamp.astimezone().strftime("%Y-%m-%d %H:%M")
    assert format_local(stamp, "%Y%m%d%H%M%S") == stamp.astimezone().strftime("%Y%m%d%H%M%S")


def test_naive_datetime_is_treated_as_utc():
    naive = datetime(2026, 9, 18, 10, 30)
    aware = datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc)
    assert as_utc(naive) == aware
    assert to_local(naive) == aware.astimezone()
    assert format_local(naive) == format_local(aware)


def test_format_local_empty():
    assert format_local(None) == ""


def test_format_local_pretty_shape():
    # Fixed offset so weekday/hour are deterministic in CI.
    stamp = datetime(2026, 7, 23, 21, 30, tzinfo=timezone.utc)
    local = stamp.astimezone()
    pretty = format_local_pretty(stamp)
    assert local.strftime("%A") in pretty
    assert local.strftime("%B") in pretty
    assert str(local.day) in pretty
    assert "2026" in pretty
    assert " at " in pretty
    assert pretty.endswith("am") or pretty.endswith("pm")
    assert format_local_pretty(None) == ""
    assert format_local_pretty("2026-07-23 17:30") == "Thursday, July 23, 2026 at 5:30pm"


def test_local_time_is_available_to_templates():
    from creopdm.api.pages import templates

    assert templates.env.filters["local_time"] is format_local
    assert templates.env.globals["local_time"] is format_local
    assert templates.env.filters["local_time_pretty"] is format_local_pretty
    assert templates.env.globals["local_time_pretty"] is format_local_pretty
    rendered = templates.env.from_string(
        "{{ local_time(stamp) }}"
    ).render(stamp=datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc))
    assert rendered == format_local(datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc))
