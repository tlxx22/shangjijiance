import requests
from concurrent.futures import ThreadPoolExecutor

# 你的 URL 和 Data
url = "http://localhost:8000/crawl" # 换成你的 URL
data = {
    "site": {"name": "TestSite", "url": "http://example.com", "login_required": False},
    "date_start": "2026-01-06",
    "date_end": "2026-01-07",
    "category": "fuwu",
    "max_pages": 1
}

def send_request(i):
    try:
        print(f"第 {i} 个请求发射...")
        response = requests.post(url, json=data)
        print(f"第 {i} 个请求结束, 状态码: {response.status_code}")
    except Exception as e:
        print(f"第 {i} 个请求失败: {e}")

# 10 个并发同时跑
print("开始并发测试...")
with ThreadPoolExecutor(max_workers=10) as executor:
    # 提交 10 个任务
    for i in range(1, 11):
        executor.submit(send_request, i)