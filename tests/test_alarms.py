"""Alarm decoding, including the cases that produced false diagnoses."""

from __future__ import annotations

from custom_components.maxa_advantix.alarms import (
    ALARMS,
    ALARMS_BY_CODE,
    count,
    decode,
    is_active,
)


def test_every_code_is_unique():
    """A duplicated code would silently shadow an entity."""
    codes = [alarm.code for alarm in ALARMS]
    assert len(codes) == len(set(codes))


def test_every_bit_position_is_claimed_once():
    positions = [(alarm.word, alarm.bit) for alarm in ALARMS]
    assert len(positions) == len(set(positions))


def test_entity_keys_are_stable_and_lowercase():
    for alarm in ALARMS:
        assert alarm.key == f"alarm_{alarm.code.lower()}"


def test_register_numbers_map_to_the_right_word():
    assert ALARMS_BY_CODE["E001"].register == 950
    assert ALARMS_BY_CODE["E042"].register == 951
    assert ALARMS_BY_CODE["E611"].register == 952


def test_no_alarms_decodes_to_nothing():
    assert decode([0, 0, 0]) == []
    assert count([0, 0, 0]) == 0


def test_single_alarm_decodes_with_code_and_description():
    # E042 is bit 12 of register 951
    active = decode([0, 1 << 12, 0])
    assert len(active) == 1
    assert active[0]["code"] == "E042"
    assert active[0]["register"] == 951
    assert active[0]["bit"] == 12
    # Descriptions use the industry term, DHW, which is what the manuals and the
    # machine's own documentation say. User-facing text is translated separately.
    assert "dhw" in str(active[0]["description"]).lower()


def test_bit_15_is_decoded():
    """Bit 15 is why the alarm words must be read unsigned."""
    active = decode([0, 1 << 15, 0])
    assert [a["code"] for a in active] == ["E102"]


def test_multiple_alarms_across_words():
    words = [1 << 5, 1 << 12, 1 << 0]  # E006, E042, E611
    codes = [a["code"] for a in decode(words)]
    assert codes == ["E006", "E042", "E611"]


def test_reserved_bits_are_counted_but_not_named():
    """A count above the named total is a hint that the map is incomplete."""
    words = [1 << 11, 0, 0]  # bit 11 of 950 is reserved
    assert decode(words) == []
    assert count(words) == 1


def test_failed_reads_are_not_forty_absent_alarms():
    """A negative or missing word means the read failed, not that all is well."""
    assert decode(None) == []
    assert decode([-1, -1, -1]) == []
    assert count([-1, -1, -1]) == 0
    assert count(None) == 0


def test_is_active_tolerates_short_and_empty_input():
    alarm = ALARMS_BY_CODE["E611"]  # lives in word 2
    assert is_active([0, 0], alarm) is False
    assert is_active([], alarm) is False
    assert is_active(None, alarm) is False
