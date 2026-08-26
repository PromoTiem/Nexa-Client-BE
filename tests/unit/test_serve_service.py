import pytest

from app.application.services.serve_service import (
    SERVE_TRANSITIONS,
    ServeTransitionError,
    assert_transition,
    normalize_serve_status,
    update_stage_log,
)


class TestNormalizeServeStatus:
    def test_none_returns_none(self):
        assert normalize_serve_status(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_serve_status("") is None

    def test_valid_status_returned(self):
        assert normalize_serve_status("requested") == "requested"
        assert normalize_serve_status("live") == "live"
        assert normalize_serve_status("failed") == "failed"


class TestUpdateStageLog:
    def test_none_log_creates_new_dict(self):
        result = update_stage_log(None, "requested")
        assert "requested_at" in result
        assert result["requested_at"] is not None

    def test_empty_dict_log(self):
        result = update_stage_log({}, "verified")
        assert "verified_at" in result

    def test_existing_log_preserved(self):
        existing = {"requested_at": "2025-01-01T00:00:00"}
        result = update_stage_log(existing, "serving")
        assert result["requested_at"] == "2025-01-01T00:00:00"
        assert "serving_at" in result

    def test_none_target_no_timestamp(self):
        result = update_stage_log(None, None)
        assert result == {}

    def test_non_dict_log_treated_as_empty(self):
        result = update_stage_log("invalid", "live")
        assert "live_at" in result
        assert len(result) == 1


class TestAssertTransition:
    def test_valid_transition_passes(self):
        assert_transition(None, "requested")
        assert_transition("requested", "verifying")
        assert_transition("requested", "failed")
        assert_transition("verifying", "verified")
        assert_transition("verifying", "failed")
        assert_transition("verified", "serving")
        assert_transition("serving", "live")
        assert_transition("serving", "failed")
        assert_transition("live", "stopped")
        assert_transition("failed", "requested")
        assert_transition("stopped", "requested")

    def test_invalid_transition_raises(self):
        with pytest.raises(ServeTransitionError):
            assert_transition(None, "live")

        with pytest.raises(ServeTransitionError):
            assert_transition("requested", "serving")

        with pytest.raises(ServeTransitionError):
            assert_transition("verified", "failed")

        with pytest.raises(ServeTransitionError):
            assert_transition("live", "verifying")

    def test_unknown_current_state_raises(self):
        with pytest.raises(ServeTransitionError):
            assert_transition("unknown", "requested")


class TestServeTransitions:
    def test_all_transitions_are_valid_sets(self):
        for _current, allowed in SERVE_TRANSITIONS.items():
            assert isinstance(allowed, set)
            for target in allowed:
                assert isinstance(target, str) or target is None

    def test_complete_lifecycle(self):
        """Verify the full happy-path lifecycle is valid."""
        lifecycle = [
            (None, "requested"),
            ("requested", "verifying"),
            ("verifying", "verified"),
            ("verified", "serving"),
            ("serving", "live"),
            ("live", "stopped"),
            ("stopped", "requested"),
        ]
        for current, target in lifecycle:
            assert_transition(current, target)

    def test_failure_and_recovery(self):
        """Verify failure -> retry lifecycle is valid."""
        assert_transition("requested", "failed")
        assert_transition("failed", "requested")
        assert_transition("serving", "failed")
        assert_transition("failed", "requested")
