# SPDX-License-Identifier: AGPL-3.0-or-later
"""The LMT image copies single files: every local module they import must be copied too."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LmtImageModules(unittest.TestCase):
    def test_every_imported_server_module_is_copied_into_the_image(self):
        dockerfile = (ROOT / 'server/Dockerfile.lmt').read_text(encoding='utf-8')
        copied = {Path(name).name for line in dockerfile.splitlines() if line.startswith('COPY server/')
                  for name in line.split()[1:-1]}
        local = {path.stem for path in (ROOT / 'server').glob('*.py')}
        seen = {name[:-3] for name in copied if name.endswith('.py')}
        todo = list(seen)
        while todo:
            source = (ROOT / 'server' / (todo.pop() + '.py')).read_text(encoding='utf-8')
            for name in re.findall(r'^\s*(?:from|import)\s+([A-Za-z_]\w*)', source, re.M):
                if name in local and name not in seen:
                    seen.add(name)
                    todo.append(name)
        self.assertEqual(sorted(name for name in seen if name + '.py' not in copied), [])


if __name__ == '__main__':
    unittest.main()
