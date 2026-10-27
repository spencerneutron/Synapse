#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git init -q
cat > slug.py <<'PY'
def slugify(text):
    return text.lower().replace(" ", "-")
PY
cat > test_slug.py <<'PY'
import unittest

from slug import slugify


class SlugTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_trims(self):
        self.assertEqual(slugify("  Trim me  "), "trim-me")
PY
git add -A && git -c user.name=eval -c user.email=eval@example.com -c commit.gpgsign=false commit -qm "slug"
