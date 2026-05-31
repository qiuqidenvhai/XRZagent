#!/usr/bin/env python3
"""Fix the esc function in _try_fix to return double backslash"""
import sys
sys.path.insert(0, r"D:\软件\XianRenZhangAgent")

path = r"D:\软件\XianRenZhangAgent\agent_core\protocol.py"
with open(path, encoding='utf-8') as f:
    content = f.read()

# Find and show the current state of the esc function
idx = content.find('def esc(m):')
chunk = content[idx:idx+100]
print(f"Current file content around esc:\n{chunk}\n")

# Count exact backslashes in the return line
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'return' in line and 'm.group' in line and 'def esc' not in line:
        print(f"Return line {i+1}: {repr(line)}")
        # Count backslashes
        bs_count = line.count('\\')
        print(f"Backslash count: {bs_count}")
        # Find the string literal
        import re
        m = re.search(r'return "([^"]+)"', line)
        if m:
            print(f"String content: {repr(m.group(1))}, len={len(m.group(1))}")

# The fix: we want "\\\\" (TWO backslashes in file)
# Current file has: "\X" (ONE backslash + letter in file)
# We need: "\\X" (TWO backslashes + letter in file)
# The string in file needs to be: \\U (two backslashes + U)
# In the return line: return "\U" + m.group(1) should become return "\\U" + m.group(1)
# In file bytes: return " + \ + U + " -> return " + \ + \ + U + "

# Find the specific line and do a direct character-level replacement
new_lines = []
for line in lines:
    if 'return "\\"' in line and 'm.group' in line:
        # Replace the pattern: return "\X" where X is any letter
        import re
        # Match: return " followed by a single backslash then a letter then "
        match = re.search(r'(return ")\\(.)(")', line)
        if match:
            # Build replacement: return " + \\ + letter + "
            new_line = match.group(1) + '\\\\' + match.group(2) + match.group(3) + line[match.end():]
            print(f"\nFixing: {repr(line)}")
            print(f"       -> {repr(new_line)}")
            line = new_line
    new_lines.append(line)

new_content = '\n'.join(new_lines)

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

import ast
try:
    ast.parse(new_content)
    print("Syntax OK!")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")

# Verify the fix
idx = new_content.find('def esc(m):')
print(f"\nAfter fix:\n{new_content[idx:idx+100]}")

# Count backslashes in the return line of the fixed file
for line in new_content.split('\n'):
    if 'return' in line and 'm.group' in line and 'def esc' not in line:
        print(f"\nFinal return line: {repr(line)}")
        print(f"Backslash count: {line.count(chr(92))}")
        import re
        m = re.search(r'return "([^"]+)"', line)
        if m:
            print(f"String content: {repr(m.group(1))}, len={len(m.group(1))}")
