"""The one sentence that describes the automatic synchronisation, in words.

Two pages show it — the summary under the Impostazioni fields and the status
line of the Sincronizzazione page — and they must never disagree, so both read
it from :func:`~qtrequestory.ui.pages.schedule_text.schedule_sentence`.

Pure Python: no ``QApplication``, no widgets, no core. The arithmetic the user
would otherwise have to do in their head (when does the retry window end?) is
exactly what is tested here.
"""
from __future__ import annotations

from qtrequestory.ui.contracts import ScheduleSettings
from qtrequestory.ui.pages.schedule_text import schedule_sentence


def sentence(**kw) -> str:
    return schedule_sentence(ScheduleSettings(**kw))


def test_the_default_schedule_reads_like_the_task_it_registers():
    assert sentence() == "Ogni giorno alle 09:00, riprova ogni ora fino alle 18:00, e al login"


def test_the_sentence_carries_no_full_stop_of_its_own():
    """The Sincronizzazione line puts it between " · " separators; whoever
    frames the sentence (Impostazioni, the wizard) closes it."""
    assert not sentence().endswith(".")
    assert not sentence(repeat_for_h=0, run_at_logon=False).endswith(".")


def test_a_wider_interval_is_plural_and_the_end_time_follows_it():
    assert sentence(start_time="07:30", repeat_every_h=2, repeat_for_h=6) == (
        "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30, e al login"
    )


def test_a_one_digit_hour_is_shown_the_way_the_task_will_run_it():
    """``config.validate`` accepts "7:30" and the trigger starts at 07:30."""
    assert sentence(start_time="7:30") == sentence(start_time="07:30")


def test_without_the_logon_trigger_the_sentence_stops_at_the_window():
    assert sentence(start_time="07:30", repeat_every_h=2, repeat_for_h=6, run_at_logon=False) == (
        "Ogni giorno alle 07:30, riprova ogni 2 ore fino alle 13:30"
    )


def test_a_zero_window_is_a_single_daily_run_and_says_nothing_about_retries():
    assert sentence(repeat_for_h=0) == "Ogni giorno alle 09:00, e al login"
    assert sentence(repeat_for_h=0, run_at_logon=False) == "Ogni giorno alle 09:00"


def test_a_window_that_crosses_midnight_says_so():
    """20:00 + 9 h is 05:00 — of the *next* day, which is the whole point of
    showing the sentence: nobody should have to work that out."""
    line = sentence(start_time="20:00", repeat_for_h=9)
    assert "fino alle 05:00 del giorno dopo" in line


def test_a_window_that_lands_exactly_on_midnight_is_still_the_next_day():
    assert "00:00 del giorno dopo" in sentence(start_time="01:00", repeat_for_h=23)


def test_a_hand_edited_interval_is_described_as_it_will_actually_run():
    """``spec_from_config`` clamps 0 to 1 h before registering; saying "ogni 0
    ore" here would describe a task nobody has."""
    assert sentence(repeat_every_h=0) == sentence(repeat_every_h=1)
    assert sentence(repeat_for_h=99) == sentence(repeat_for_h=23)


def test_an_unparsable_start_time_falls_back_instead_of_crashing():
    """A hand-edited ``config.json`` must not take the page down with it;
    ``config.validate`` is what tells the user the value is wrong."""
    assert sentence(start_time="mezzogiorno") == sentence(start_time="09:00")


def test_the_formatter_stays_widget_free():
    """It is shared by two pages and unit-tested without a ``QApplication``;
    a Qt import here would make both of those accidents waiting to happen."""
    from pathlib import Path

    import qtrequestory.ui.pages.schedule_text as module

    assert "PySide6" not in Path(module.__file__).read_text(encoding="utf-8")
