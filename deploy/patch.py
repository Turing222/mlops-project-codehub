import json
from pathlib import Path

file_path = Path(__file__).parent / "monitoring" / "dashboards" / "mlops_main.json"
with file_path.open(encoding="utf-8") as f:
    data = json.load(f)

# 1. 增加变量选项
data["templating"]["list"] = [
    {
        "name": "service",
        "type": "query",
        "datasource": {"type": "loki", "uid": "loki"},
        "query": "label_values(service)",
        "refresh": 1,
        "hide": 0,
        "includeAll": True,
        "allValue": ".*",
        "multi": False,
        "label": "选择服务",
    }
]

# 2. 修改现有的面板（包含排版）
new_panels = []
for p in data.get("panels", []):
    title = p.get("title", "")

    if "平均响应延迟" in title:
        p["gridPos"] = {"h": 8, "w": 24, "x": 0, "y": 8}

    elif "数据库连接数量" in title:
        p["gridPos"] = {"h": 8, "w": 12, "x": 0, "y": 16}

    elif "Redis 内存消耗" in title:
        p["gridPos"] = {"h": 8, "w": 12, "x": 12, "y": 16}

    elif "后端实时业务日志" in title:
        # 这个原本是铺满屏幕，现在变成宽度十二（占据左边一半）
        p["gridPos"] = {"h": 14, "w": 12, "x": 0, "y": 24}
        p["title"] = "常规日志与分析 ($service)"
        # 加上 $service 变量的过滤
        p["targets"][0]["expr"] = (
            '{service=~"$service"} | json | line_format "[{{.service}}] {{.message}}"'
        )

    new_panels.append(p)

# 3. 追加错误和告警面板（占据右边一半）
alert_panel = {
    "title": "🚨 告警与错误日志",
    "type": "logs",
    "gridPos": {"h": 14, "w": 12, "x": 12, "y": 24},
    "datasource": {"type": "loki", "uid": "loki"},
    "targets": [
        {
            "expr": '{level=~"error|warn"} | json | line_format "[{{.service}}] {{.message}}"',
            "refId": "B",
        }
    ],
    "options": {
        "showTime": False,
        "showLabels": False,
        "showLevel": True,
        "enableLogDetails": True,
        "sortOrder": "Descending",
    },
}
new_panels.append(alert_panel)

data["panels"] = new_panels

with open(file_path, "w") as f:
    json.dump(data, f, indent=4, ensure_ascii=False)
