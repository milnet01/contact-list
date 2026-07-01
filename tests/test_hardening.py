"""Tests for the audit/review hardening follow-ups (CL-0008..CL-0021)."""

from __future__ import annotations

import os
import stat


class TestEnsurePrivateDir:
    def test_creates_dir_0700(self, tmp_path):
        import config
        target = tmp_path / 'cfg'
        config.ensure_private_dir(str(target))
        assert target.is_dir()
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700, f'expected 0700, got {oct(mode)}'

    def test_tightens_existing_loose_dir(self, tmp_path):
        import config
        target = tmp_path / 'cfg'
        target.mkdir(mode=0o755)
        config.ensure_private_dir(str(target))
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700, f'expected 0700, got {oct(mode)}'
