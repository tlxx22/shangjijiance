"""
网站可爬取性批量测试脚本
用法: python test_batch_1.py [--host HOST]

自动发送请求并解析 SSE 返回，判断每个网站是否可爬取
"""

import requests
import json
import sys
from datetime import datetime, timedelta

HOST = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--host" else "http://localhost:80"

SITES = [
    {"name": "航天云商", "url": "http://bd.ispacechina.com/retrieve.do?typflag=1"},
    {"name": "中铁建电子采购", "url": "https://www.crccep.cn/findNoticesList?index=BiddingAnnouncement"},
    {"name": "山钢交易平台", "url": "https://zb.sggylpt.com/jyxx/trade.html"},
    {"name": "中节能电商平台", "url": "https://sp.iccec.cn/searchList?type=98"},
    {"name": "宁波港招标", "url": "https://hgdzzb.nbport.com.cn/zjhgcms//category/purchaseListNew.html?dates=300&categoryId=2&tenderMethod=00&tabName=%E5%9F%BA%E5%B1%82%E4%B8%93%E6%A0%8F&page=1"},
]

def test_site(site: dict) -> dict:
    """测试单个网站，返回结果"""
    today = datetime.now()
    date_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    date_end = today.strftime("%Y-%m-%d")
    
    payload = {
        "site": {
            "name": site["name"],
            "url": site["url"],
            "login_required": False
        },
        "date_start": date_start,
        "date_end": date_end,
        "category": "ALL",
        "max_pages": 1,
        "timeout_seconds": 300
    }
    
    result = {
        "name": site["name"],
        "url": site["url"],
        "status": "unknown",
        "items_count": 0,
        "error": None
    }
    
    try:
        print(f"\n{'='*60}")
        print(f"测试: {site['name']}")
        print(f"URL: {site['url']}")
        print(f"{'='*60}")
        
        response = requests.post(
            f"{HOST}/crawl",
            json=payload,
            stream=True,
            timeout=320
        )
        
        items = []
        final_result = None
        
        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8')
            
            if line_str.startswith('data: '):
                data_str = line_str[6:]
                try:
                    data = json.loads(data_str)
                    event_type = data.get("type")
                    
                    if event_type == "item":
                        items.append(data.get("data", {}))
                        print(f"  ✓ 获取条目: {data.get('data', {}).get('title', 'unknown')[:40]}...")
                    elif event_type == "result":
                        final_result = data.get("data", {})
                    elif event_type == "error":
                        result["error"] = data.get("message", "未知错误")
                        print(f"  ✗ 错误: {result['error']}")
                except json.JSONDecodeError:
                    pass
        
        result["items_count"] = len(items)
        
        if final_result:
            if final_result.get("saved_count", 0) > 0:
                result["status"] = "success"
            elif final_result.get("risk_control"):
                result["status"] = "risk_control"
                result["error"] = "触发风控"
            else:
                result["status"] = "no_data"
        elif result["error"]:
            result["status"] = "error"
        else:
            result["status"] = "no_response"
            
    except requests.Timeout:
        result["status"] = "timeout"
        result["error"] = "请求超时"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


def main():
    print(f"\n{'#'*60}")
    print(f"# 批量测试脚本 1/5")
    print(f"# 服务地址: {HOST}")
    print(f"# 测试网站数: {len(SITES)}")
    print(f"{'#'*60}")
    
    results = []
    for site in SITES:
        result = test_site(site)
        results.append(result)
    
    # 打印汇总
    print(f"\n\n{'='*60}")
    print("测试结果汇总")
    print(f"{'='*60}")
    
    success = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]
    
    print(f"\n✓ 成功: {len(success)}/{len(results)}")
    for r in success:
        print(f"  - {r['name']}: {r['items_count']} 条")
    
    print(f"\n✗ 失败: {len(failed)}/{len(results)}")
    for r in failed:
        print(f"  - {r['name']}: {r['status']} - {r['error'] or '无详细信息'}")
    
    # 保存结果
    with open("test_results_batch1.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 test_results_batch1.json")


if __name__ == "__main__":
    main()
