from __future__ import annotations

import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / '.claude-plugin' / 'plugin.json'


def test_option_settings_load():
    # Claude Code refuses the whole plugin when a listed option is empty or the default isn't listed.
    for name, setting in json.loads(MANIFEST.read_text(encoding='utf-8'))['userConfig'].items():
        if 'options' in setting:
            assert all(setting['options']), name
            assert setting['default'] in setting['options'], name
