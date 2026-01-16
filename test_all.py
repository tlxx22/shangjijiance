"""
网站可爬取性批量测试脚本（合并版）
用法: python test_all.py [--host HOST]

自动发送请求并解析 SSE 返回，判断每个网站是否可爬取
"""

import requests
import json
import sys
from datetime import datetime, timedelta

HOST = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--host" else "http://localhost:80"

SITES = [
    # Batch 1
    {"name": "航天云商", "url": "http://bd.ispacechina.com/retrieve.do?typflag=1"},
    {"name": "中铁建电子采购", "url": "https://www.crccep.cn/findNoticesList?index=BiddingAnnouncement"},
    {"name": "山钢交易平台", "url": "https://zb.sggylpt.com/jyxx/trade.html"},
    {"name": "中节能电商平台", "url": "https://sp.iccec.cn/searchList?type=98"},
    {"name": "宁波港招标", "url": "https://hgdzzb.nbport.com.cn/zjhgcms//category/purchaseListNew.html?dates=300&categoryId=2&tenderMethod=00&tabName=%E5%9F%BA%E5%B1%82%E4%B8%93%E6%A0%8F&page=1"},
    # Batch 2
    {"name": "江苏港口集团", "url": "https://ecg.portjs.cn:20909/#/jiaoyi?index=1&noticeType=1&type=0"},
    {"name": "烟港惠采", "url": "https://yghc.sd-port.com/jyxx/012001/012001001/prej_project.html"},
    {"name": "中水北方", "url": "http://www.csnwd.com.cn/xxgk/zbcg/"},
    {"name": "中水北方-候选人", "url": "https://zc.csnwd.com.cn:8443/cms/zd26nsbd/webfile/zd26=jsgczbhxr/index.html"},
    {"name": "中水北方-公告", "url": "https://zc.csnwd.com.cn:8443/cms/zd26nsbd/webfile/zd26=jsgcgg/index.html"},
    # Batch 3
    {"name": "中国能建", "url": "https://ec.ceec.net.cn/HomeInfo/ProjectList.aspx?InfoLevel=MQA=&bigType=QwBHAFkARwA="},
    {"name": "中国电建-招标", "url": "https://bid.powerchina.cn/consult/notice"},
    {"name": "中国电建-公示", "url": "https://bid.powerchina.cn/consult/publicity"},
    {"name": "中石油-招标", "url": "https://www.cnpcbidding.com/#/tenders"},
    {"name": "中石油-候选", "url": "https://www.cnpcbidding.com/#/candidate"},
    # Batch 4
    {"name": "中石化-询价150", "url": "https://ec.sinopec.com//f/supp/bid/inquiryNoticeList.do?type=150"},
    {"name": "中石化-招标20", "url": "https://ec.sinopec.com//f/supp/bid/bidNoticeList.do?type=20"},
    {"name": "中石化-招标40", "url": "https://ec.sinopec.com//f/supp/bid/bidNoticeList.do?type=40"},
    {"name": "中石化-招标50", "url": "https://ec.sinopec.com//f/supp/bid/bidNoticeList.do?type=50"},
    {"name": "中石化-公示", "url": "https://ec.sinopec.com//f/supp/bid/onlypublicitybillList.do"},
    # Batch 5
    {"name": "中石化-询价110", "url": "https://ec.sinopec.com//f/supp/bid/inquiryNoticeList.do?type=110"},
    {"name": "中石化-询价130", "url": "https://ec.sinopec.com//f/supp/bid/inquiryNoticeList.do?type=130"},
    {"name": "国电电商-咨询", "url": "https://emall.epec.com/advisoryNotice"},
    {"name": "中海油-招标", "url": "https://bid.cnooc.com.cn/home/#/newsAlertList?index=0&childrenActive=0&type="},
    {"name": "中海油-结果", "url": "https://bid.cnooc.com.cn/home/#/newsAlertList?index=1&childrenActive=0&type="},
    {"name": "中海油采办", "url": "https://buy.cnooc.com.cn/cbjyweb/001/moreinfo.html"},
    {"name": "国电电商-招标", "url": "https://bidding.epec.com/tenderInfoOne"},
    {"name": "中国政府采购网", "url": "https://www.ccgp.gov.cn/cggg/zygg/"},
]

def test_site(site: dict, index: int, total: int) -> dict:
    """测试单个网站，返回结果"""
    today = datetime.now()
    date_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    date_end = today.strftime("%Y-%m-%d")
    
    payload = {
        "site": {"name": site["name"], "url": site["url"], "login_required": False},
        "date_start": date_start,
        "date_end": date_end,
        "category": "ALL",
        "max_pages": 1,
        "timeout_seconds": 300
    }
    
    result = {"name": site["name"], "url": site["url"], "status": "unknown", "items_count": 0, "error": None}
    
    try:
        print(f"\n{'='*60}")
        print(f"[{index}/{total}] 测试: {site['name']}")
        print(f"URL: {site['url']}")
        print(f"{'='*60}")
        
        response = requests.post(f"{HOST}/crawl", json=payload, stream=True, timeout=320)
        
        items = []
        final_result = None
        
        for line in response.iter_lines():
            if not line:
                continue
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
    print(f"# 网站可爬取性批量测试")
    print(f"# 服务地址: {HOST}")
    print(f"# 测试网站数: {len(SITES)}")
    print(f"{'#'*60}")
    
    results = []
    for i, site in enumerate(SITES, 1):
        result = test_site(site, i, len(SITES))
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
    with open("test_results_all.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 test_results_all.json")


if __name__ == "__main__":
    main()
