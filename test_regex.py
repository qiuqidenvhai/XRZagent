#!/usr/bin/env python3
"""Verify _try_fix logic"""
import re

def fix_backslash(match):
    return '\\\\' + match.group(1)

def _try_fix(raw):
    # 1. Fix trailing commas
    result = re.sub(r",\s*([}\]])", r"\1", raw)
    # 2. Fix Windows path backslashes
    result = re.sub(r'\\([A-Za-z])', fix_backslash, result)
    return result

# Test cases
tests = [
    # Windows path C:\Users
    ('{"path":"C:\\Users"}', '{"path":"C:\\\\Users"}'),
    # Normal path
    ('{"path":"C:\\test"}', '{"path":"C:\\\\test"}'),
    # Path with spaces
    ('{"path":"C:\\Program Files"}', '{"path":"C:\\\\Program Files"}'),
    # Trailing comma
    ('{"tool":"test","params":{}}', '{"tool":"test","params":{}}'),
    ('{"tool":"test","params":{},}', '{"tool":"test","params":{}}'),
    # Normal escape sequences should NOT be broken
    ('{"text":"line1\\nline2"}', '{"text":"line1\\nline2"}'),
    ('{"path":"C:\\\\Users"}', '{"path":"C:\\\\Users"}'),
    # Mixed: trailing comma + Windows path
    ('{"path":"C:\\Users",}', '{"path":"C:\\\\Users"}'),
]

all_ok = True
for input_str, expected in tests:
    result = _try_fix(input_str)
    status = 'OK' if result == expected else 'FAIL'
    if status == 'FAIL':
        all_ok = False
    print(f'{status}: {repr(input_str)} -> {repr(result)}')
    if status == 'FAIL':
        print(f'       expected: {repr(expected)}')

if all_ok:
    print('\nAll tests passed!')
    
    # Now verify json.loads works after _try_fix
    import json
    print("\nVerifying json.loads after _try_fix:")
    test_json = '{"path":"C:\\Users"}'
    fixed = _try_fix(test_json)
    print(f"  Input: {repr(test_json)}")
    print(f"  Fixed: {repr(fixed)}")
    try:
        obj = json.loads(fixed)
        print(f"  json.loads OK: {obj}")
    except Exception as e:
        print(f"  json.loads FAIL: {e}")
