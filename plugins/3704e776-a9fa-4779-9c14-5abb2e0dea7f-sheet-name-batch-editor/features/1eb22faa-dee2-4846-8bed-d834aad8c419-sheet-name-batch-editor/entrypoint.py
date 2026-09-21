# -*- coding: utf-8 -*-
import os
import sys

FEATURE_ROOT = os.path.dirname(os.path.realpath(__file__))
PAYLOAD_ROOT = os.path.join(FEATURE_ROOT, 'payload')
SOURCE_SCRIPT = os.path.join(PAYLOAD_ROOT, 'script.py')
if not os.path.isfile(SOURCE_SCRIPT):
    raise RuntimeError('Migrated payload is missing script.py')

added_path = False
old_cwd = os.getcwd()
try:
    if PAYLOAD_ROOT not in sys.path:
        sys.path.insert(0, PAYLOAD_ROOT)
        added_path = True
    os.chdir(PAYLOAD_ROOT)
    globals()['__file__'] = SOURCE_SCRIPT
    execfile(SOURCE_SCRIPT, globals())
finally:
    os.chdir(old_cwd)
    if added_path:
        try:
            sys.path.remove(PAYLOAD_ROOT)
        except ValueError:
            pass
