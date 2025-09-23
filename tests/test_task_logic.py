import pytest

from tbot.task_logic import (
    ActivityEntry,
    GlobalStatus,
    PersonalStatus,
    calculate_global_status,
    filter_activity_feed,
    personal_section,
    recipients_on_confirmation,
    recipients_on_take,
    should_show_take_button,
    visible_participants,
)


def test_personal_section_titles():
    assert personal_section(PersonalStatus.NEW) == "Новые"
    assert personal_section(PersonalStatus.IN_PROGRESS) == "В работе"
    assert personal_section(PersonalStatus.ON_REVIEW) == "На проверке"
    assert personal_section(PersonalStatus.CONFIRMED) == "Выполненные"
    assert personal_section(PersonalStatus.DONE) == "Выполненные"


def test_visible_participants_excludes_author():
    participants = [1, 2, 3, 4]
    assert visible_participants(participants, 2) == [1, 3, 4]


@pytest.mark.parametrize(
    "author_id,responsible_id,user_id,expected",
    [
        (1, None, 1, True),
        (1, 3, 1, True),
        (1, 1, 1, False),
        (1, 1, 2, True),
    ],
)
def test_should_show_take_button(author_id, responsible_id, user_id, expected):
    assert should_show_take_button(author_id, responsible_id, user_id) is expected


@pytest.mark.parametrize(
    "statuses,manual,expected",
    [
        ([], False, GlobalStatus.NEW),
        ([PersonalStatus.NEW], False, GlobalStatus.NEW),
        (
            [
                PersonalStatus.CONFIRMED,
                PersonalStatus.DONE,
                PersonalStatus.CONFIRMED,
            ],
            False,
            GlobalStatus.COMPLETED,
        ),
        (
            [
                PersonalStatus.ON_REVIEW,
                PersonalStatus.CONFIRMED,
                PersonalStatus.DONE,
            ],
            False,
            GlobalStatus.ON_REVIEW,
        ),
        (
            [PersonalStatus.IN_PROGRESS, PersonalStatus.NEW],
            False,
            GlobalStatus.IN_PROGRESS,
        ),
        (
            [PersonalStatus.NEW, PersonalStatus.IN_PROGRESS],
            True,
            GlobalStatus.COMPLETED,
        ),
    ],
)
def test_calculate_global_status(statuses, manual, expected):
    assert calculate_global_status(statuses, manual_completed=manual) is expected


@pytest.mark.parametrize(
    "author_id,responsible_id,actor_id,participant_id,expected",
    [
        (1, 2, 1, 3, {2, 3}),
        (1, 2, 2, 3, {1, 3}),
        (1, None, 1, 3, {3}),
        (1, 2, 2, 2, {1, 2}),
    ],
)
def test_recipients_on_confirmation(author_id, responsible_id, actor_id, participant_id, expected):
    assert (
        recipients_on_confirmation(author_id, responsible_id, actor_id, participant_id)
        == expected
    )


@pytest.mark.parametrize(
    "author_id,responsible_id,actor_id,expected",
    [
        (1, 2, 3, {1, 2}),
        (1, None, 3, {1}),
        (1, 2, 1, {2}),
        (1, 2, 2, {1}),
        (1, 1, 1, set()),
    ],
)
def test_recipients_on_take(author_id, responsible_id, actor_id, expected):
    assert recipients_on_take(author_id, responsible_id, actor_id) == expected


def test_filter_activity_feed_for_author():
    entries = [
        ActivityEntry(actor_id=1, description="a"),
        ActivityEntry(actor_id=2, description="b"),
    ]
    assert filter_activity_feed(entries, viewer_id=1, author_id=1) == entries


def test_filter_activity_feed_for_participant():
    entries = [
        ActivityEntry(actor_id=2, description="a"),
        ActivityEntry(actor_id=3, description="b"),
        ActivityEntry(
            actor_id=4,
            description="c",
            is_status_change=True,
            related_participants=frozenset({5, 6}),
        ),
        ActivityEntry(
            actor_id=7,
            description="d",
            is_status_change=True,
            related_participants=frozenset({3, 8}),
        ),
    ]
    visible = filter_activity_feed(entries, viewer_id=3, author_id=1)
    assert visible == [entries[1], entries[3]]
