"""#1023 (epic #1015): request.pdhc reads EPS_* with IPS_* as the fallback.

ips.pdhc is being renamed eps.pdhc. Until phase 4 removes the old names, a
container may carry EPS_*, IPS_* or both; the new name must win, the old one
must still work on its own, and with neither set the service must behave as
it did before the rename.

Two layers are tested: `_eps_env` itself, and `Config` as a fresh interpreter
builds it from the environment — the class attributes are evaluated at import,
so only a new process shows what a container would actually get. Every read
of the patient registry (patient proxy, clinic need-to-know, validate-
identifier #813, spärr, consent-at-dispatch) and the worker take the URL and
key from these two config keys, so this covers all of them.
"""
import os
import subprocess
import sys

import pytest

from app.config import _eps_env

GATEWAY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ("EPS_BASE_URL", "EPS_API_KEY", "IPS_BASE_URL", "IPS_API_KEY")


@pytest.fixture
def clean_env(monkeypatch):
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    return monkeypatch


def test_new_name_wins(clean_env):
    clean_env.setenv("EPS_BASE_URL", "http://eps.test")
    clean_env.setenv("IPS_BASE_URL", "http://ips.test")
    assert _eps_env("BASE_URL", "d") == "http://eps.test"


def test_old_name_still_works(clean_env):
    clean_env.setenv("IPS_API_KEY", "old-key")
    assert _eps_env("API_KEY", "") == "old-key"


def test_empty_new_name_falls_back_to_old(clean_env):
    clean_env.setenv("EPS_API_KEY", "")
    clean_env.setenv("IPS_API_KEY", "old-key")
    assert _eps_env("API_KEY", "") == "old-key"


def test_both_unset_gives_the_default(clean_env):
    assert _eps_env("API_KEY", "") == ""
    assert _eps_env("BASE_URL", "d") == "d"


def test_empty_old_name_reads_as_empty_as_before(clean_env):
    # Before #1023 this was os.environ.get('IPS_BASE_URL', default): an empty
    # value stayed empty rather than turning into the default.
    clean_env.setenv("IPS_BASE_URL", "")
    assert _eps_env("BASE_URL", "d") == ""


def _config_in_fresh_process(env_overrides):
    env = {k: v for k, v in os.environ.items() if k not in NAMES}
    env.update(env_overrides)
    env["PYTHONPATH"] = GATEWAY
    out = subprocess.run(
        [sys.executable, "-c",
         "from app.config import Config as C; "
         "print(C.IPS_BASE_URL); print(C.IPS_API_KEY)"],
        cwd=GATEWAY, env=env, capture_output=True, text=True, check=True)
    url, key = out.stdout.splitlines()[-2:]
    return url, key


def test_config_prefers_eps_names():
    url, key = _config_in_fresh_process({
        "EPS_BASE_URL": "http://eps.test", "EPS_API_KEY": "new-key",
        "IPS_BASE_URL": "http://ips.test", "IPS_API_KEY": "old-key"})
    assert (url, key) == ("http://eps.test", "new-key")


def test_config_still_reads_ips_names():
    url, key = _config_in_fresh_process({
        "IPS_BASE_URL": "http://ips.test", "IPS_API_KEY": "old-key"})
    assert (url, key) == ("http://ips.test", "old-key")


def test_config_with_neither_set_has_no_key():
    url, key = _config_in_fresh_process({})
    assert key == ""
    assert url == "https://eps.pdhc.se"
