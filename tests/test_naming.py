from datetime import datetime
from pathlib import Path

import pytest

from igprep.core import naming as nm

WHEN = datetime(2026, 9, 22, 14, 5, 9)


def _render(template, **kw):
    kw.setdefault("name", "DSC_0042")
    kw.setdefault("when", WHEN)
    return nm.render(template, **kw)


def test_suffix_preset():
    assert _render(nm.PRESET_SUFFIX) == "DSC_0042_ig"


def test_custom_preset_pads_the_counter():
    assert _render(nm.PRESET_CUSTOM, custom="iceland", n=7) == "iceland_007"


def test_all_tokens_resolve():
    out = _render(
        "{name}-{custom}-{n}-{ratio}-{w}x{h}-{date}-{time}",
        custom="c", n=3, ratio="3:4", w=1080, h=1440,
    )
    assert out == "DSC_0042-c-3-3x4-1080x1440-2026-09-22-140509"


def test_ratio_colon_becomes_filesystem_safe():
    assert _render("{ratio}", ratio="1.91:1") == "1.91x1"


def test_illegal_characters_are_replaced():
    """One dash per illegal character, including a trailing one."""
    assert _render("{name}", name='a/b:c*d?') == "a-b-c-d-"


def test_trailing_dots_and_spaces_are_stripped():
    """Windows drops these silently, which would break collision detection."""
    assert _render("{name}", name="photo. ") == "photo"


def test_reserved_device_names_are_escaped():
    assert _render("{name}", name="CON") == "_CON"
    assert _render("{name}", name="NUL.jpg") == "_NUL.jpg"


def test_unknown_token_names_the_valid_ones():
    with pytest.raises(nm.NamingError) as exc:
        _render("{filename}")
    assert "{name}" in str(exc.value)


def test_positional_placeholder_is_rejected():
    with pytest.raises(nm.NamingError):
        _render("{}")


def test_attribute_access_is_rejected():
    with pytest.raises(nm.NamingError):
        _render("{name.upper}")


def test_empty_result_is_rejected():
    with pytest.raises(nm.NamingError):
        _render("{custom}", custom="   ")


def test_validate_accepts_the_presets():
    assert nm.validate(nm.PRESET_SUFFIX) is None
    assert nm.validate(nm.PRESET_CUSTOM) is None


def test_validate_flags_a_constant_template():
    """Every photo in a batch would overwrite the last."""
    assert "every photo" in nm.validate("holiday").lower()


def test_validate_flags_empty_and_bad_templates():
    assert nm.validate("   ") is not None
    assert nm.validate("{nope}") is not None


def test_validate_never_raises():
    for junk in ["{", "}", "{n:z}", "{name", "{{}}", "{name:.2f}"]:
        assert isinstance(nm.validate(junk), (str, type(None)))


def test_unique_path_leaves_a_free_name_alone(tmp_path):
    target = tmp_path / "a.jpg"
    assert nm.unique_path(target) == target


def test_unique_path_increments_past_collisions(tmp_path):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "a_2.jpg").touch()
    assert nm.unique_path(tmp_path / "a.jpg") == tmp_path / "a_3.jpg"
