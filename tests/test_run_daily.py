from datetime import datetime

from scripts.run_daily import STEPS, SUNDAY_STEPS, build_steps, run_steps


class _FakeCompletedProcess:
    def __init__(self, returncode):
        self.returncode = returncode


def test_run_steps_runs_every_step_when_all_succeed(monkeypatch):
    calls = []

    def fake_run(step):
        calls.append(step)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr("scripts.run_daily.subprocess.run", fake_run)
    steps = [["a"], ["b"], ["c"]]
    exit_code = run_steps(steps)
    assert exit_code == 0
    assert calls == steps


def test_run_steps_stops_at_first_failure(monkeypatch):
    calls = []

    def fake_run(step):
        calls.append(step)
        return _FakeCompletedProcess(1 if step == ["b"] else 0)

    monkeypatch.setattr("scripts.run_daily.subprocess.run", fake_run)
    steps = [["a"], ["b"], ["c"]]
    exit_code = run_steps(steps)
    assert exit_code == 1
    # "c" must never run -- a failed upstream step means downstream steps
    # would read incomplete/stale data.
    assert calls == [["a"], ["b"]]


def test_build_steps_appends_reasoning_audit_on_sunday():
    sunday = datetime(2026, 9, 13)  # a real Sunday
    assert build_steps(sunday) == STEPS + SUNDAY_STEPS


def test_build_steps_omits_reasoning_audit_on_other_days():
    monday = datetime(2026, 9, 14)  # a real Monday
    assert build_steps(monday) == STEPS
    saturday = datetime(2026, 9, 12)  # a real Saturday
    assert build_steps(saturday) == STEPS
