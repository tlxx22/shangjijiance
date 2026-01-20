"""
OSS 上传客户端

将截图上传到阿里云 OSS，并返回可访问的完整 URL。
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import oss2


def _normalize_endpoint(endpoint: str) -> str:
	"""
	规范化 endpoint（去掉 http(s):// 前缀和尾部 /）

	示例：
	- https://oss-cn-shanghai.aliyuncs.com -> oss-cn-shanghai.aliyuncs.com
	"""
	endpoint = (endpoint or "").strip()
	for prefix in ("https://", "http://"):
		if endpoint.startswith(prefix):
			endpoint = endpoint[len(prefix):]
	return endpoint.rstrip("/")


def _safe_path_segment(value: str, max_length: int = 50) -> str:
	"""
	将任意字符串转为较安全的 OSS 路径片段
	"""
	value = (value or "").strip()
	value = re.sub(r"[\\\\/]+", "_", value)
	value = re.sub(r"\s+", "_", value)
	value = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "", value)
	return value[:max_length] or "unknown"


class OSSClient:
	def __init__(self):
		self.access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "").strip()
		self.access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "").strip()
		self.bucket_name = os.getenv("OSS_BUCKET", "").strip()
		self.endpoint = _normalize_endpoint(os.getenv("OSS_ENDPOINT", ""))

		# 返回给业务侧的访问域名（可以是 CDN 域名或 bucket 域名）
		default_domain = (
			f"https://{self.bucket_name}.{self.endpoint}" if self.bucket_name and self.endpoint else ""
		)
		self.cdn_domain = (os.getenv("OSS_CDN_DOMAIN") or default_domain).rstrip("/")

		if not (self.access_key_id and self.access_key_secret and self.bucket_name and self.endpoint):
			raise ValueError(
				"OSS 配置不完整，请设置 OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET/OSS_ENDPOINT/OSS_BUCKET"
			)

		auth = oss2.Auth(self.access_key_id, self.access_key_secret)
		self.bucket = oss2.Bucket(auth, f"https://{self.endpoint}", self.bucket_name)

	def upload(self, img_bytes: bytes, site_name: str, prefix: str = "crawler") -> str:
		"""
		上传截图到 OSS 并返回完整 URL

		Args:
			img_bytes: PNG 图片 bytes
			site_name: 网站名（用于路径分组）
			prefix: OSS 路径前缀

		Returns:
			完整 URL（包含 cdn_domain）
		"""
		if not img_bytes:
			raise ValueError("img_bytes 为空")

		date_str = datetime.now().strftime("%Y-%m-%d")
		timestamp = datetime.now().strftime("%H%M%S%f")
		safe_site = _safe_path_segment(site_name, max_length=50)

		key = f"{prefix}/{date_str}/{safe_site}/{timestamp}.png"
		self.bucket.put_object(key, img_bytes)

		# cdn_domain 为空时，至少返回 key（避免抛异常）
		if not self.cdn_domain:
			return key
		return f"{self.cdn_domain}/{key}"

