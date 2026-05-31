#!/usr/bin/env python3
"""最简化的 JSON 引号修复"""
import re
import json

# AI 输出的问题 JSON
raw = '''{
"tool": "shell_exec",
"params": {
"command": "mkdir -p "$HOME/Desktop/MCP协议报告""
},
"id": "1"
}'''

def fix_json_quotes_simple(s):
    """简化策略：修复 "key": "value" 中 value 内的未转义引号"""
    # 匹配 "key": "value" 模式中的 value 部分
    # 但要排除已经是转义引号 \" 的情况
    
    result = []
    lines = s.split('\n')
    for line in lines:
        # 检查这行是否包含 "key": "value" 模式
        # 匹配 "xxx": "yyy" 其中 yyy 包含未转义的引号
        match = re.match(r'^(\s*"[^"]+":\s*")(.+?)(")(\s*[,}]?\s*)$', line)
        if match:
            prefix = match.group(1)  # "key": "
            value = match.group(2)    # value (可能包含引号)
            first_quote = match.group(3)  # 第一个引号
            suffix = match.group(4)  # 后面部分
            
            # 检查 value 是否包含需要转义的引号
            # 如果 value 里有 " 但前面不是 \，说明是未转义的
            if '"' in value and not value.endswith('\\"'):
                # 需要修复 value 内的引号
                fixed_value = value.replace('"', '\\"')
                line = prefix + fixed_value + first_quote + suffix
        result.append(line)
    return '\n'.join(result)

print("原始 JSON:")
print(raw)
print()

fixed = fix_json_quotes_simple(raw)
print("修复后:")
print(fixed)
print()

try:
    obj = json.loads(fixed)
    print("解析成功! tool =", obj['tool'])
    print("command =", obj['params']['command'])
except json.JSONDecodeError as e:
    print("解析失败:", e)