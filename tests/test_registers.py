"""The register map and the read plan.

The plan is worth testing precisely because it is generated. A hand-written table
is wrong in ways you can see by reading it; a computed one is wrong in ways that
only show up as a sensor that is permanently unavailable, or as a bus doing twice
the work it needs to.
"""

from __future__ import annotations

import pytest

from custom_components.maxa_advantix.registers import (
    ALARM_REGISTERS,
    MAX_BLOCK,
    MAX_GAP,
    PER_REGISTER_MS,
    READ_BLOCKS,
    READ_REGISTERS,
    REQUIRED_ADDRESSES,
    STATUS_REGISTERS,
    TRANSACTION_OVERHEAD_MS,
    ReadBlock,
    plan_blocks,
)


def test_every_required_address_is_covered_by_some_block():
    """The failure this prevents reads as "that sensor never has a value"."""
    for address in REQUIRED_ADDRESSES:
        assert any(address in block for block in READ_BLOCKS), address


def test_blocks_are_sorted_and_do_not_overlap():
    for earlier, later in zip(READ_BLOCKS, READ_BLOCKS[1:], strict=False):
        assert earlier.end < later.start


def test_no_block_exceeds_the_ceiling():
    for block in READ_BLOCKS:
        assert 1 <= block.count <= MAX_BLOCK


def test_the_plan_is_cheaper_than_one_read_per_register():
    """The whole point: fewer transactions than registers."""
    assert len(READ_BLOCKS) < len(set(REQUIRED_ADDRESSES)) / 3


def test_the_plan_does_not_waste_the_bus():
    """Reading gaps is the price of merging; it should stay a small price."""
    fetched = sum(block.count for block in READ_BLOCKS)
    wanted = len(set(REQUIRED_ADDRESSES))
    assert fetched < wanted * 3


def test_register_keys_are_unique():
    keys = [register.key for register in READ_REGISTERS]
    assert len(keys) == len(set(keys))


def test_register_addresses_are_unique():
    addresses = [register.address for register in READ_REGISTERS]
    assert len(addresses) == len(set(addresses))


def test_status_registers_are_not_entity_backed():
    """Status bitmaps are decoded, not published raw, so they have no register entry."""
    entity_addresses = {register.address for register in READ_REGISTERS}
    for address in STATUS_REGISTERS:
        assert address not in entity_addresses


def test_alarm_words_are_contiguous_and_in_one_block():
    assert ALARM_REGISTERS == (950, 951, 952)
    holding = [block for block in READ_BLOCKS if 950 in block]
    assert len(holding) == 1
    assert all(address in holding[0] for address in ALARM_REGISTERS)


# ── the planner itself ────────────────────────────────────────────────────────
def test_planning_nothing_gives_nothing():
    assert plan_blocks([]) == ()


def test_a_single_address_is_one_block_of_one():
    assert plan_blocks([400]) == (ReadBlock(400, 1),)


def test_adjacent_addresses_merge():
    assert plan_blocks([400, 401, 402]) == (ReadBlock(400, 3),)


def test_duplicates_and_disorder_do_not_matter():
    assert plan_blocks([402, 400, 401, 400]) == (ReadBlock(400, 3),)


def test_a_gap_within_tolerance_is_bridged():
    """Reading three registers nobody wants beats a second round trip."""
    assert plan_blocks([400, 404], max_gap=8) == (ReadBlock(400, 5),)


def test_a_gap_beyond_tolerance_splits():
    assert plan_blocks([400, 500], max_gap=8) == (ReadBlock(400, 1), ReadBlock(500, 1))


def test_the_gap_boundary_is_inclusive():
    assert plan_blocks([400, 409], max_gap=8) == (ReadBlock(400, 10),)
    assert plan_blocks([400, 410], max_gap=8) == (ReadBlock(400, 1), ReadBlock(410, 1))


def test_a_long_run_is_split_at_the_ceiling():
    blocks = plan_blocks(range(400, 500), max_gap=8, max_block=32)
    assert all(block.count <= 32 for block in blocks)
    covered = {address for block in blocks for address in range(block.start, block.end + 1)}
    assert covered >= set(range(400, 500))


@pytest.mark.parametrize("max_gap", [0, 1, 8, 16, 64])
def test_coverage_holds_for_any_tolerance(max_gap):
    addresses = [200, 253, 254, 305, 400, 401, 444, 950, 952, 7000, 7216]
    blocks = plan_blocks(addresses, max_gap=max_gap)
    for address in addresses:
        assert any(address in block for block in blocks), (address, max_gap)


def test_zero_tolerance_gives_one_block_per_contiguous_run():
    assert plan_blocks([400, 401, 500], max_gap=0) == (
        ReadBlock(400, 2),
        ReadBlock(500, 1),
    )


def test_block_repr_is_readable_in_diagnostics():
    assert str(ReadBlock(400, 15)) == "400-414 (15)"


# ── the tuning ────────────────────────────────────────────────────────────────
def _line_time(blocks: tuple[ReadBlock, ...]) -> float:
    """Estimated bus time for one poll, in milliseconds."""
    return len(blocks) * TRANSACTION_OVERHEAD_MS + sum(
        block.count for block in blocks
    ) * PER_REGISTER_MS


def test_the_chosen_tolerance_is_still_the_cheapest():
    """Guards the tuning: changing MAX_GAP to something worse fails here.

    The cost curve is flat across a range of tolerances and rises on both sides, so
    the assertion is that no other value beats the chosen one, not that the chosen
    one is unique.
    """
    chosen = _line_time(plan_blocks(REQUIRED_ADDRESSES, max_gap=MAX_GAP))
    for candidate in (0, 1, 2, 4, 6, 8, 10, 12, 20, 24, 32, 48, 64, 128):
        other = _line_time(plan_blocks(REQUIRED_ADDRESSES, max_gap=candidate))
        assert chosen <= other, (
            f"max_gap={candidate} would cost {other:.0f} ms against {chosen:.0f} ms"
        )


def test_the_plan_beats_reading_every_register_separately():
    """The comparison that justifies the planner existing at all."""
    separate = tuple(ReadBlock(address, 1) for address in sorted(set(REQUIRED_ADDRESSES)))
    assert _line_time(READ_BLOCKS) < _line_time(separate) * 0.75
