from vortex.observability.icons import NAV, PATHS
from vortex.observability.shell import SECTIONS


def test_every_nav_path_has_an_ink_icon() -> None:
    for _, path, children in SECTIONS:
        assert path in NAV
        assert NAV[path] in PATHS
        for _, sub_path in children:
            if sub_path in NAV:
                assert NAV[sub_path] in PATHS
    assert "wall" in PATHS
    assert "mark" in PATHS
