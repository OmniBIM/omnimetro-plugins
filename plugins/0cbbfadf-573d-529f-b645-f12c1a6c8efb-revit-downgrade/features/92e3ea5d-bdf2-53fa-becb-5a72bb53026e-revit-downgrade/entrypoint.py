# -*- coding: utf-8 -*-
import os
import sys

FEATURE_ROOT = os.path.dirname(os.path.realpath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(FEATURE_ROOT))
LIB_ROOT = os.path.join(PLUGIN_ROOT, 'lib')
PAYLOAD_ROOT = os.path.join(FEATURE_ROOT, 'payload')
SOURCE_SCRIPT = os.path.join(PAYLOAD_ROOT, 'script.py')

if not os.path.isfile(SOURCE_SCRIPT):
    raise RuntimeError('Migrated payload is missing script.py')

inserted_paths = []
old_cwd = os.getcwd()
try:
    for path in [LIB_ROOT, PAYLOAD_ROOT]:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
            inserted_paths.append(path)
    os.chdir(PAYLOAD_ROOT)
    globals()['__file__'] = SOURCE_SCRIPT
    execfile(SOURCE_SCRIPT, globals())
finally:
    os.chdir(old_cwd)
    for path in inserted_paths:
        try:
            sys.path.remove(path)
        except Exception:
            pass
