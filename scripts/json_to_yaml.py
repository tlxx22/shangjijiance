import json, yaml, sys

if len(sys.argv) > 1:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        raw = f.read()
else:
    raw = sys.stdin.read()

raw = raw.strip()

# 如果输入不是以 { 开头，自动包一层大括号
if not raw.startswith("{"):
    raw = "{" + raw + "}"

# 只取第一个完整的 JSON 对象
start = raw.find("{")
depth = 0
end = start
for i, ch in enumerate(raw[start:], start):
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            end = i
            break

data = json.loads(raw[start:end + 1])

# 如果 JSON 外层有 "data" 包裹，取里面的内容
if "data" in data and isinstance(data["data"], dict):
    data = data["data"]

out = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)

out_path = "output.yaml"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(out)
print(f"✓ 已写入 {out_path}")