#三方rpc调用
import requests
import time
import hashlib

def jy_fetch(appid:str = 'jyGy5XQAEEAgRbTUNPKyRU',key_secret:str='I3761u5n',next_page:str=None):
      """ 剑鱼数据获取 返回json数据"""
      url = "https://api.jianyu360.com/data/getalldata"
      data = {
           "appid":appid,
           "next":next_page,
      }
      # 时间戳
      timestamp = int(time.time())
       # 签名 转大写
      signature = hashlib.md5(f"{appid}{str(timestamp)}{key_secret}".encode()).hexdigest().upper()
      response = requests.get(url=url,params=data,headers= {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Accept-Charset": "UTF-8",
            "timestamp":str(timestamp),
            "signature":signature,
      })
      return response.json()


def browser_billing(api_key:str='bu_M5p7ZCZzGa6yZuTpS2yRw3t5NoVUzPjer7JotNZUAI8'):
      """ 浏览器计费 返回json数据"""
      response = requests.get(url="https://api.browser-use.com/api/v2/billing/account",headers= {
            "X-Browser-Use-API-Key": api_key
      })
      return response.json()
