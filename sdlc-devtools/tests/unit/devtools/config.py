"""Unit tests for devtools/config.py — the packaged-config locator (ast-grep / jscpd paths)."""

import pytest

from devtools.config import Config


def test_config_resolves_packaged_files():
    sg = Config.path("sgconfig")
    js = Config.path("jscpd")
    assert sg.name == "sgconfig.yml" and sg.exists(), "sgconfig resolves to the packaged file"
    assert js.name == "jscpd.json" and js.exists(), "jscpd resolves to the packaged file"
    # sgconfig's ruleDirs: [sg-rules] resolves alongside it — the packaged rules ship next to the config
    assert (sg.parent / "sg-rules").is_dir(), "the ast-grep rule dir ships beside sgconfig.yml"


def test_config_unknown_name_errors():
    with pytest.raises(SystemExit):
        Config.path("nope")


def test_config_main_requires_valid_choice(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["devtools.config", "bogus"])
    with pytest.raises(SystemExit) as exc:
        from devtools import config

        config.main()
    assert exc.value.code == 2, "an invalid choice is an argparse usage error"
