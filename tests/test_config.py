"""Tests for core/config.py. Everything is synthetic: no real hostnames."""
from __future__ import annotations

import json
import logging
import re
from datetime import time
from pathlib import Path

import pytest

from qtrequestory.core import config as cfgmod
from qtrequestory.core import paths
from qtrequestory.core.config import (
    Config,
    Environment,
    IndexSettings,
    ScheduleSettings,
    SyncSettings,
    default_config,
    detect_editor,
    find_sidecar_environments,
    import_environments_file,
    is_first_run,
    load_config,
    save_config,
    validate,
)

URL_A = "https://example.invalid/AutoDeploy/Input/"
URL_B = "http://example.invalid:8080/AutoDeploy/Input/"


def _sample_config(tmp_path: Path) -> Config:
    return Config(
        schema_version=cfgmod.CONFIG_VERSION,
        mirror_root=tmp_path / "mirror",
        environments=[Environment("svil", URL_A), Environment("coll", URL_B, enabled=False)],
        default_window_days=7,
        editor_path=tmp_path / "editor.exe",
        output_dir=tmp_path / "out",
        output_retention_hours=48,
        compaction_time=time(18, 30),
        sync=SyncSettings(index_timeout_s=5, download_timeout_s=10, chunk_size=1024, retries=3),
        index=IndexSettings(parse_json=False),
        schedule=ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=6,
                                  run_at_logon=False),
        log_level="DEBUG",
    )


# ------------------------------------------------------------ defaults ---


def test_default_config_values_match_spec():
    cfg = default_config()
    assert cfg.schema_version == cfgmod.CONFIG_VERSION == 1
    assert cfg.mirror_root == paths.default_mirror_root()
    assert cfg.environments == []
    assert cfg.default_window_days == 30
    assert cfg.editor_path is None
    assert cfg.output_dir is None
    assert cfg.output_retention_hours == 24
    assert cfg.compaction_time == time(18, 30)
    assert cfg.sync == SyncSettings(
        index_timeout_s=15, download_timeout_s=60, chunk_size=1_048_576, retries=1
    )
    assert cfg.index == IndexSettings(parse_json=True)
    assert cfg.log_level == "INFO"


def test_the_default_schedule_is_the_one_the_task_used_to_hard_code():
    """09:00, hourly for 9 h, plus the logon trigger.

    These four values were compiled into ``TaskSpec``; an installation that
    upgrades must keep the very same schedule, so the defaults are not a taste
    decision but a compatibility requirement.
    """
    assert default_config().schedule == ScheduleSettings()
    assert ScheduleSettings() == ScheduleSettings(
        start_time="09:00", repeat_every_h=1, repeat_for_h=9, run_at_logon=True
    )


def test_config_module_contains_no_hostnames():
    """Public repo: the only URLs allowed in code are scheme prefixes, never hosts."""
    src = Path(cfgmod.__file__).read_text(encoding="utf-8")
    assert "cliente" not in src.lower()
    assert not re.search(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}", src)


def test_config_paths_derived_from_mirror_root(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    hidden = tmp_path / "mirror" / ".qtrequestory"
    assert cfg.index_path == hidden / "index.sqlite"
    assert cfg.state_path == hidden / "sync-state.json"
    assert cfg.lock_path == hidden / "sync.lock"


def test_resolved_output_dir_falls_back_to_default(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    assert cfg.resolved_output_dir == tmp_path / "out"
    cfg.output_dir = None
    assert cfg.resolved_output_dir == paths.default_output_dir()


def test_env_lookup_and_enabled(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    assert cfg.env("svil").url == URL_A
    assert cfg.enabled_environments() == [Environment("svil", URL_A)]
    with pytest.raises(KeyError):
        cfg.env("nope")


# ------------------------------------------------------------ first run ---


def test_first_run_yields_defaults_without_creating_the_file(tmp_path: Path):
    """Reading must not answer the "did the user ever configure this?" question.

    ``load_config`` creating the file is how a cancelled first-run wizard used
    to disappear forever: the next launch found a config.json and never asked
    again.
    """
    path = tmp_path / "config.json"
    assert is_first_run(path) is True
    cfg = load_config(path)
    assert not path.exists()
    assert cfg == default_config()
    assert cfg.environments == []
    assert is_first_run(path) is True


def test_saving_is_what_ends_the_first_run(tmp_path: Path):
    path = tmp_path / "config.json"
    save_config(load_config(path), path)
    assert is_first_run(path) is False
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == cfgmod.CONFIG_VERSION
    assert on_disk["environments"] == []
    assert on_disk["compaction_time"] == "18:30"


# ------------------------------------------------------------ roundtrip ---


def test_roundtrip_preserves_every_field(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = _sample_config(tmp_path)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded == cfg
    assert isinstance(loaded.mirror_root, Path)
    assert isinstance(loaded.editor_path, Path)
    assert isinstance(loaded.output_dir, Path)
    assert isinstance(loaded.compaction_time, time)
    assert loaded.environments[1].enabled is False


def test_save_is_json_utf8_indent2_no_tmp_left(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = _sample_config(tmp_path)
    cfg.environments = [Environment("città", URL_A)]
    save_config(cfg, path)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "città".encode("utf-8") in raw  # ensure_ascii=False
    text = raw.decode("utf-8")
    assert text.startswith("{\n  ")  # indent=2
    on_disk = json.loads(text)
    assert on_disk["mirror_root"] == str(cfg.mirror_root)
    assert on_disk["editor_path"] == str(cfg.editor_path)
    assert on_disk["compaction_time"] == "18:30"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("config")] == ["config.json"]


def test_save_creates_parent_directory(tmp_path: Path):
    path = tmp_path / "nested" / "deeper" / "config.json"
    save_config(default_config(), path)
    assert path.exists()


# ------------------------------------------------------- lenient loading ---


def test_unknown_keys_ignored_and_missing_defaulted(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_window_days": 90,
                "sync": {"retries": 4, "bogus": 1},
                "totally_unknown": "x",
            }
        ),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.default_window_days == 90
    assert cfg.sync.retries == 4
    assert cfg.sync.index_timeout_s == 15  # defaulted inside nested block
    assert cfg.environments == []
    assert cfg.compaction_time == time(18, 30)
    assert cfg.mirror_root == paths.default_mirror_root()
    assert "totally_unknown" in caplog.text
    assert "bogus" in caplog.text


def test_corrupt_json_renamed_and_defaults_returned(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg == default_config()
    broken = list(tmp_path.glob("config.json.broken-*"))
    assert len(broken) == 1
    assert broken[0].read_text(encoding="utf-8") == "{ this is not json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == cfgmod.CONFIG_VERSION
    assert "broken" in caplog.text


def test_non_object_json_is_treated_as_corrupt(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = load_config(path)
    assert cfg == default_config()
    assert list(tmp_path.glob("config.json.broken-*"))


def test_malformed_compaction_time_falls_back_to_default(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "compaction_time": "half past six"}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.compaction_time == time(18, 30)
    assert "compaction_time" in caplog.text


def test_wrong_typed_scalar_falls_back_to_default(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "default_window_days": "abc", "sync": {"retries": "x"}}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.default_window_days == 30
    assert cfg.sync.retries == 1
    assert "default_window_days" in caplog.text
    assert "retries" in caplog.text


def test_malformed_environment_item_is_skipped_with_warning(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"schema_version": 1, "environments": [{"name": "ok", "url": URL_A}, {"url": URL_B}, "junk"]})
    )
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.environments == [Environment("ok", URL_A)]
    assert "environments[1]" in caplog.text
    assert "environments[2]" in caplog.text


def test_newer_schema_version_is_kept_and_warned(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 99, "default_window_days": 5}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.schema_version == 99
    assert cfg.default_window_days == 5
    assert "99" in caplog.text


def test_wrong_typed_path_falls_back_to_default(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "mirror_root": 5, "editor_path": ["x"]}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.mirror_root == paths.default_mirror_root()
    assert cfg.editor_path is None
    assert "mirror_root" in caplog.text
    assert "editor_path" in caplog.text


def test_non_string_log_level_falls_back_to_default(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "log_level": 5}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.log_level == "INFO"
    assert "log_level" in caplog.text


@pytest.mark.parametrize("version", [0, -3])
def test_schema_version_below_one_is_treated_as_corrupt(tmp_path: Path, caplog, version: int):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": version, "default_window_days": 5}))
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg == default_config()
    assert len(list(tmp_path.glob("config.json.broken-*"))) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == cfgmod.CONFIG_VERSION
    assert "schema_version" in caplog.text


# ------------------------------------------------------------ validation ---


def test_validate_valid_config_is_clean(tmp_path: Path):
    assert validate(_sample_config(tmp_path)) == []
    assert validate(default_config()) == []


def test_validate_reports_each_problem(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    cfg.environments = [
        Environment("svil", URL_A),
        Environment("SVIL", URL_B),  # duplicate, case-insensitive
        Environment("bad name!", "example.invalid/AutoDeploy/Input/"),  # bad chars, no scheme
        Environment("noslash", "https://example.invalid/AutoDeploy/Input"),  # no trailing slash
    ]
    cfg.default_window_days = 0
    cfg.output_retention_hours = 0
    errors = validate(cfg)
    joined = "\n".join(errors)
    assert any("SVIL" in e or "svil" in e for e in errors)  # duplicate
    assert "bad name!" in joined
    assert "example.invalid/AutoDeploy/Input/" in joined  # scheme error
    assert "noslash" in joined
    assert "default_window_days" in joined
    assert "output_retention_hours" in joined
    assert len(errors) == 6


def test_validate_window_upper_bound(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    cfg.default_window_days = 3650
    assert validate(cfg) == []
    cfg.default_window_days = 3651
    assert len(validate(cfg)) == 1


# ------------------------------------------------------------ migrations ---


def test_migration_chain_applied_with_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "default_window_days": 12}), encoding="utf-8")
    calls: list[int] = []

    def v1_to_v2(raw: dict) -> dict:
        calls.append(raw["schema_version"])
        out = dict(raw)
        out["default_window_days"] = raw["default_window_days"] * 2
        return out

    monkeypatch.setattr(cfgmod, "MIGRATIONS", {1: v1_to_v2})
    monkeypatch.setattr(cfgmod, "CONFIG_VERSION", 2)

    cfg = load_config(path)
    assert calls == [1]
    assert cfg.default_window_days == 24
    assert cfg.schema_version == 2
    backup = tmp_path / "config.json.bak-v1"
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8"))["default_window_days"] == 12
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_no_migration_does_not_rewrite_or_backup(tmp_path: Path):
    path = tmp_path / "config.json"
    save_config(_sample_config(tmp_path), path)
    before = path.read_bytes()
    load_config(path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("config.json.bak-*"))


def test_missing_migration_step_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    monkeypatch.setattr(cfgmod, "MIGRATIONS", {})
    monkeypatch.setattr(cfgmod, "CONFIG_VERSION", 2)
    with pytest.raises(cfgmod.ConfigError):
        load_config(path)


# ------------------------------------------------ environments import ---


def test_import_environments_file_happy_path(tmp_path: Path):
    f = tmp_path / "environments.json"
    f.write_text(
        json.dumps(
            [
                {"name": "svil", "url": URL_A},
                {"name": "coll", "url": URL_B, "enabled": False},
            ]
        ),
        encoding="utf-8",
    )
    assert import_environments_file(f) == [
        Environment("svil", URL_A, True),
        Environment("coll", URL_B, False),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "svil", "url": URL_A},  # not a list
        [{"url": URL_A}],  # missing name
        [{"name": "svil"}],  # missing url
        [{"name": 3, "url": URL_A}],  # wrong type
        [{"name": "svil", "url": URL_A, "enabled": "yes"}],  # enabled not bool
        ["svil"],  # item not an object
    ],
)
def test_import_environments_file_malformed(tmp_path: Path, payload):
    f = tmp_path / "environments.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        import_environments_file(f)


def test_import_environments_file_invalid_json(tmp_path: Path):
    f = tmp_path / "environments.json"
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        import_environments_file(f)


def test_find_sidecar_environments(tmp_path: Path):
    assert find_sidecar_environments(tmp_path) is None
    side = tmp_path / "environments.json"
    side.write_text("[]", encoding="utf-8")
    assert find_sidecar_environments(tmp_path) == side


# ------------------------------------------------------------ editor ---


def test_detect_editor_none_when_candidates_missing(tmp_path: Path):
    assert detect_editor([tmp_path / "a.exe", tmp_path / "b.exe", None]) is None


def test_detect_editor_returns_first_existing(tmp_path: Path):
    exe = tmp_path / "notepad++.exe"
    exe.write_bytes(b"")
    assert detect_editor([tmp_path / "missing.exe", exe]) == exe


def test_detect_editor_default_candidates_do_not_crash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    monkeypatch.setattr(cfgmod.shutil, "which", lambda *_: None)
    assert detect_editor() is None


# ------------------------------------------------------------ schedule ---

#: How the block reads in ``config.json``.
SCHEDULE_RAW = {"start_time": "07:30", "repeat_every_h": 2, "repeat_for_h": 6,
                "run_at_logon": False}


def test_a_config_written_before_the_schedule_existed_still_loads(tmp_path: Path):
    """The block is additive: no migration, no schema bump, same behaviour.

    Every installation out there has a ``config.json`` without it, and the
    defaults ARE what those installations are already doing.
    """
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "default_window_days": 7}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.schedule == ScheduleSettings()
    assert validate(cfg) == []


def test_the_schedule_roundtrips_through_the_file(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = _sample_config(tmp_path)
    save_config(cfg, path)
    assert json.loads(path.read_text(encoding="utf-8"))["schedule"] == SCHEDULE_RAW
    assert load_config(path).schedule == cfg.schedule


def test_a_hand_edited_schedule_field_falls_back_instead_of_blocking_the_app(tmp_path: Path, caplog):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"schema_version": 1,
                    "schedule": {"start_time": 900, "repeat_every_h": "2", "bogus": 1}}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="qtrequestory.core.config"):
        cfg = load_config(path)
    assert cfg.schedule.start_time == "09:00"   # 900 is not a string: defaulted
    assert cfg.schedule.repeat_every_h == 2     # "2" is a number: coerced
    assert cfg.schedule.repeat_for_h == 9       # missing: defaulted
    assert "schedule.start_time" in caplog.text


@pytest.mark.parametrize(
    "schedule, expected",
    [
        (ScheduleSettings(), []),
        (ScheduleSettings(start_time="00:00", repeat_every_h=12, repeat_for_h=0), []),
        (ScheduleSettings(start_time="23:59", repeat_every_h=1, repeat_for_h=23), []),
        (ScheduleSettings(start_time="9:00"), []),          # HH:MM accepts a one-digit hour
        (ScheduleSettings(start_time="25:00"), ["start_time"]),
        (ScheduleSettings(start_time="09.00"), ["start_time"]),
        (ScheduleSettings(start_time=""), ["start_time"]),
        (ScheduleSettings(repeat_every_h=0), ["repeat_every_h"]),
        (ScheduleSettings(repeat_every_h=13), ["repeat_every_h"]),
        (ScheduleSettings(repeat_every_h=-1), ["repeat_every_h"]),
        (ScheduleSettings(repeat_for_h=24), ["repeat_for_h"]),
        (ScheduleSettings(repeat_for_h=-1), ["repeat_for_h"]),
        (ScheduleSettings(start_time="x", repeat_every_h=99, repeat_for_h=99),
         ["start_time", "repeat_every_h", "repeat_for_h"]),
    ],
)
def test_validate_checks_the_schedule(tmp_path: Path, schedule: ScheduleSettings,
                                      expected: list[str]):
    cfg = _sample_config(tmp_path)
    cfg.schedule = schedule
    errors = validate(cfg)
    assert len(errors) == len(expected), errors
    for field_name in expected:
        assert any(field_name in e for e in errors), errors


@pytest.mark.parametrize(
    "stored, expected",
    [
        (ScheduleSettings(), ScheduleSettings()),
        (ScheduleSettings(start_time="7:30"), ScheduleSettings(start_time="07:30")),
        (ScheduleSettings(start_time="mezzogiorno"), ScheduleSettings()),
        (ScheduleSettings(repeat_every_h=0), ScheduleSettings(repeat_every_h=1)),
        (ScheduleSettings(repeat_every_h=99), ScheduleSettings(repeat_every_h=12)),
        (ScheduleSettings(repeat_for_h=-4), ScheduleSettings(repeat_for_h=0)),
        (ScheduleSettings(repeat_for_h=99), ScheduleSettings(repeat_for_h=23)),
        (ScheduleSettings(run_at_logon=False), ScheduleSettings(run_at_logon=False)),
    ],
)
def test_sanitised_schedule_is_what_the_task_will_really_do(stored, expected):
    """``validate`` reports a bad value; this repairs it, because the task has to
    be registered anyway and the UI must describe what will actually run."""
    assert cfgmod.sanitised_schedule(stored) == expected


def test_a_sanitised_schedule_always_validates_clean(tmp_path: Path):
    cfg = _sample_config(tmp_path)
    cfg.schedule = ScheduleSettings(start_time="boh", repeat_every_h=-5, repeat_for_h=48)
    assert validate(cfg) != []
    cfg.schedule = cfgmod.sanitised_schedule(cfg.schedule)
    assert validate(cfg) == []


def test_parse_hhmm_accepts_exactly_what_validate_accepts():
    assert cfgmod.parse_hhmm("09:00") == time(9, 0)
    assert cfgmod.parse_hhmm("7:05") == time(7, 5)
    assert cfgmod.parse_hhmm("24:00") is None
    assert cfgmod.parse_hhmm("nonsense") is None
