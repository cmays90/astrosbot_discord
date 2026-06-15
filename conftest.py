"""
pytest configuration — adds BaseballConsumer and tests/ to sys.path so
production modules and test helpers can be imported without package prefix.
"""
import sys
import os

_root = os.path.dirname(__file__)

# Bot modules use flat imports (no package prefix) because they run from
# inside BaseballConsumer/.  Add that directory so tests can import them too.
sys.path.insert(0, os.path.join(_root, 'BaseballConsumer'))

# Test helpers (mocks/, fixtures/) are importable as top-level modules
# without needing a 'tests.' prefix.
sys.path.insert(0, os.path.join(_root, 'tests'))
