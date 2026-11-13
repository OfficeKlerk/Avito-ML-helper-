from datetime import date

from devkit.fullstack import absence_day, no_stubs


def test_no_stubs_flags_working_service_pointing_at_stub():
    config = {"services": {
        "core-api": {"environment": {"CORP_MOCK_URL": "http://stub-corp-mock:8070", "PORT": "8080"}},
        "agent": {"environment": {"MCP_URL": "http://corp-mock:8070/mcp"}},
        "stub-agent": {"environment": {"STUB_SERVICE": "agent"}},
        "devkit": {"environment": {"STUB_AGENT_URL": "http://stub-agent:8090"}},
    }}
    assert no_stubs(config) == ["core-api: CORP_MOCK_URL указывает на заглушку (http://stub-corp-mock:8070)"]


def test_absence_day_skips_weekend():
    assert absence_day(date(2026, 11, 13)) == date(2026, 11, 16)  # пятница → понедельник
    assert absence_day(date(2026, 11, 10)) == date(2026, 11, 12)  # вторник → четверг
