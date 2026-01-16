"""批量测试脚本 3/5"""

import requests
import json
import sys
from datetime import datetime, timedelta

HOST = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--host" else "http://localhost:80"

SITES = [
    {"name": "中国能建", "url": "https://ec.ceec.net.cn/HomeInfo/ProjectList.aspx?InfoLevel=MQA=&bigType=QwBHAFkARwA="},
    {"name": "中国电建-招标", "url": "https://bid.powerchina.cn/consult/notice"},
    {"name": "中国电建-公示", "url": "https://bid.powerchina.cn/consult/publicity"},
    {"name": "中石油-招标", "url": "https://www.cnpcbidding.com/#/tenders"},
    {"name": "中石油-候选", "url": "https://www.cnpcbidding.com/#/candidate"},
]

def test_site(site: dict) -> dict:
    today = datetime.now()
    date_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    date_end = today.strftime("%Y-%m-%d")
    
    payload = {
        "site": {"name": site["name"], "url": site["url"], "login_required": False},
        "date_start": date_start, "date_end": date_end,
        "category": "ALL", "max_pages": 1, "timeout_seconds": 300
    }
    
    result = {"name": site["name"], "url": site["url"], "status": "unknown", "items_count": 0, "error": None}
    
    try:
        print(f"\n{'='*60}\n测试: {site['name']}\nURL: {site['url']}\n{'='*60}")
        response = requests.post(f"{HOST}/crawl", json=payload, stream=True, timeout=320)
        
        items = []
        final_result = None
        
        for line in response.iter_lines():
            if not line: continue
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                try:
                    data = json.loads(line_str[6:])
                    if data.get("type") == "item":
                        items.append(data.get("data", {}))
                        print(f"  ✓ 获取条目: {data.get('data', {}).get('title', '')[:40]}...")
                    elif data.get("type") == "result":
                        final_result = data.get("data", {})
                    elif data.get("type") == "error":
                        result["error"] = data.get("message")
                except: pass
        
        result["items_count"] = len(items)
        if final_result:
            result["status"] = "success" if final_result.get("saved_count", 0) > 0 else ("risk_control" if final_result.get("risk_control") else "no_data")
        elif result["error"]:
            result["status"] = "error"
    except requests.Timeout:
        result["status"], result["error"] = "timeout", "请求超时"
    except Exception as e:
        result["status"], result["error"] = "error", str(e)
    
    return result

def main():
    print(f"\n{'#'*60}\n# 批量测试脚本 3/5\n# 服务地址: {HOST}\n{'#'*60}")
    results = [test_site(s) for s in SITES]
    
    print(f"\n\n{'='*60}\n测试结果汇总\n{'='*60}")
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]
    print(f"\n✓ 成功: {len(success)}/{len(results)}")
    for r in success: print(f"  - {r['name']}: {r['items_count']} 条")
    print(f"\n✗ 失败: {len(failed)}/{len(results)}")
    for r in failed: print(f"  - {r['name']}: {r['status']} - {r['error'] or ''}")
    
    with open("test_results_batch3.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
