#三方rpc调用
import os
import requests
import time
import hashlib

def bidcenter_post(upstream_url: str, form_data: dict, timeout: float = 120.0) -> requests.Response:
    """
    bidcenter 类接口通用 POST（上游：application/x-www-form-urlencoded）。
    upstream_url 由调用方传入，不在此写死。
    form_data 为扁平键值，与上游文档一致（搜索、详情等）。
    """
    return requests.post(
        upstream_url,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept-Charset": "UTF-8",
        },
        timeout=timeout,
    )

def jy_fetch(appid:str = 'jyGy5XQAEEAgRbTUNPKyRU',key_secret:str='I3761u5n',timestamp:str=None,signature:str=None,next_page:str=None):
      """ 剑鱼数据获取 返回json数据"""
      url = "https://api.jianyu360.com/data/getalldata"
      data = {
           "appid":appid,
           "next":next_page,
      }
      response = requests.get(url=url,params=data,headers= {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Accept-Charset": "UTF-8",
            "timestamp":timestamp,
            "signature":signature,
      })
      return response.json()


def browser_billing(api_key:str='bu_M5p7ZCZzGa6yZuTpS2yRw3t5NoVUzPjer7JotNZUAI8'):
      """ 浏览器计费 返回json数据"""
      response = requests.get(url="https://api.browser-use.com/api/v2/billing/account",headers= {
            "X-Browser-Use-API-Key": api_key
      })
      return response.json()

if __name__ == "__main__":
      t = time.time()
      print(int(t))