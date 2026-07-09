from __future__ import annotations

from unittest import mock

from wudup import web_demo_fixtures


def test_static_demo_fixture_generation_matches_read_only_contract() -> None:
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=AssertionError("static demo fixture generation must not use network"),
    ):
        data = web_demo_fixtures.generate_static_demo_fixtures()

    assert data["auth"]["session"]["dev_auth_bypass"] is False
    assert data["auth"]["session"]["mutations_enabled"] is False
    assert data["planCases"] == []
    assert data["removalCases"] == []
    assert data["retagCases"] == []
    assert data["pending"]["count"] == 7
    assert data["pending"]["snoozed_candidates"] == [
        web_demo_fixtures.DEMO_PENDING_SNOOZED_CANDIDATE
    ]

    doctor_checks = {check["code"]: check for check in data["doctor"]["checks"]}
    assert doctor_checks["webui-authentication"]["status"] == "PASS"
    assert doctor_checks["webui-authentication"]["detail"] == (
        "development auth bypass is disabled"
    )
    assert doctor_checks["webui-mutation-gate"]["status"] == "PASS"
    assert doctor_checks["webui-mutation-gate"]["detail"] == (
        "browser mutations are disabled"
    )

    diagnostics_checks = {
        check["code"]: check
        for check in data["diagnostics"]["doctor_result"]["checks"]
    }
    assert diagnostics_checks["webui-mutation-gate"]["detail"] == (
        "browser mutations are disabled"
    )

    apply_checks = {
        check["code"]: check
        for check in data["selfUpdatePlan"]["plan"]["apply_preflight"]["checks"]
    }
    assert apply_checks["mutations-enabled"]["status"] == "FAIL"
    assert apply_checks["mutations-enabled"]["detail"] == (
        web_demo_fixtures.STATIC_DEMO_READ_ONLY_MESSAGE
    )

    assert (
        web_demo_fixtures.GENERATED_FIXTURE_PATH.read_text(encoding="utf-8")
        == web_demo_fixtures.render_static_demo_fixtures_ts(data)
    )
