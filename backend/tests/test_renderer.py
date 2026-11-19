from __future__ import annotations

import math

from app.config import AppSettings, Mapping, MappingParams, NightSchedule
from app.renderer import (
    PreviewRenderer,
    ZoneRef,
    apply_night,
    build_base_frame,
    render_mapping_for_target,
    storage_colour,
    temperature_colour,
)


def lit(colors: list[tuple[int, int, int]]) -> int:
    return sum(1 for color in colors if max(color) > 8)


def test_storage_fill_is_proportional() -> None:
    assert lit(PreviewRenderer.storage(10, 0)) == 0
    assert lit(PreviewRenderer.storage(10, 100)) == 10
    assert lit(PreviewRenderer.storage(10, 50)) == 5
    partial = PreviewRenderer.storage(10, 55)
    assert lit(partial) == 6
    assert max(partial[5]) < max(partial[4])


def test_storage_reverse_direction() -> None:
    params = MappingParams(reverse=True)
    colors = PreviewRenderer.storage(8, 50, params)
    assert lit(colors[:4]) == 0
    assert lit(colors[4:]) == 4


def test_storage_colours_shift_with_free_space() -> None:
    cyan = storage_colour(100)
    amber = storage_colour(30)
    orange = storage_colour(10)
    red = storage_colour(2)
    assert cyan[2] > cyan[0]
    assert amber[0] > amber[2]
    assert orange[0] > orange[1]
    assert red[0] > red[1]


def test_critical_pulse_changes_brightness() -> None:
    params = MappingParams(critical_pulse=True)
    first = PreviewRenderer.storage(8, 98, params, now=0.0)
    later = PreviewRenderer.storage(8, 98, params, now=0.4)
    assert max(first[0]) != max(later[0])


def test_master_brightness_scales_output() -> None:
    mapping = Mapping(
        id="m1",
        target_type="zone",
        target_id="z1",
        mode="static",
        params=MappingParams(color="#ffffff", brightness=100),
    )
    settings = AppSettings(brightness=50)
    colors = render_mapping_for_target(
        mapping,
        [ZoneRef("z1", "d1", 0, 0, "zone", 4)],
        {"storage": {}, "cpu": {}, "memory": {}},
        settings,
        0.0,
        0.5,
    )["z1"]
    assert colors[0] == (127, 127, 127) or colors[0] == (128, 128, 128)


def test_temperature_gradient_endpoints() -> None:
    cool = temperature_colour(30, 30, 90)
    hot = temperature_colour(90, 30, 90)
    assert cool[2] > cool[0]
    assert hot[0] > hot[2]


def test_extend_layout_splits_a_single_bar() -> None:
    mapping = Mapping(
        id="m",
        target_type="group",
        target_id="g",
        mode="storage",
        params=MappingParams(layout="extend", critical_pulse=False),
    )
    zones = [
        ZoneRef("a", "d", 0, 0, "RAM A", 4),
        ZoneRef("b", "d", 0, 1, "RAM B", 4),
    ]
    telemetry = {"storage": {"/": {"used_percent": 50.0}}, "cpu": {}, "memory": {}}
    rendered = render_mapping_for_target(mapping, zones, telemetry, AppSettings(), 0.0, 1.0)
    assert len(rendered["a"]) == 4
    assert len(rendered["b"]) == 4
    assert lit(rendered["a"]) == 4
    assert lit(rendered["b"]) == 0


def test_base_frame_priority_and_group_membership() -> None:
    devices = [
        {
            "key": "d1",
            "index": 0,
            "zones": [
                {"id": "d1:z0", "index": 0, "name": "A", "led_count": 4},
                {"id": "d1:z1", "index": 1, "name": "B", "led_count": 4},
            ],
        }
    ]
    group = type("G", (), {"id": "g1", "name": "pair", "zones": ["d1:z0", "d1:z1"]})()
    mappings = [
        Mapping(
            id="zone",
            target_type="zone",
            target_id="d1:z0",
            mode="static",
            params=MappingParams(color="#ff0000"),
        ),
        Mapping(
            id="group",
            target_type="group",
            target_id="g1",
            mode="static",
            params=MappingParams(color="#00ff00"),
        ),
    ]
    frame, owners = build_base_frame(
        devices,
        [group],  # type: ignore[list-item]
        mappings,
        {"storage": {}, "cpu": {}, "memory": {}},
        AppSettings(),
        0.0,
    )
    assert set(frame) == {"d1:z0", "d1:z1"}
    assert owners["d1:z0"].id == "group"
    assert frame["d1:z0"][0][1] > frame["d1:z0"][0][0]


def test_night_off_is_black() -> None:
    frame = {"z": [(255, 255, 255)] * 4}
    settings = AppSettings(night=NightSchedule(enabled=True, behaviour="off"))
    night = apply_night(frame, settings, True)
    assert night["z"] == [(0, 0, 0)] * 4


def test_storage_colour_is_continuous() -> None:
    # Values one point apart should not jump to an unrelated hue.
    a = storage_colour(49.9)
    b = storage_colour(50.0)
    distance = math.dist(a, b)
    assert distance < 10
