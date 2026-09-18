from datetime import datetime, timezone

from creopdm.utils.timefmt import as_utc, format_local, to_local


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


def test_local_time_is_available_to_templates():
    from creopdm.api.pages import templates

    assert templates.env.filters["local_time"] is format_local
    assert templates.env.globals["local_time"] is format_local
    rendered = templates.env.from_string(
        "{{ local_time(stamp) }}"
    ).render(stamp=datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc))
    assert rendered == format_local(datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc))
