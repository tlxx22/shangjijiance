"""
SSE 事件格式化
"""
import json
from datetime import datetime


def sse_event(payload: dict, request_id: str) -> str:
    """
    生成 SSE 事件字符串
    
    Args:
        payload: 事件数据，必须包含 type 字段
        request_id: 请求 ID
    
    Returns:
        SSE 格式字符串：data: {...}\n\n
    """
    # 确保 request_id 在 payload 中
    payload["request_id"] = request_id
    
    # 如果是 heartbeat，添加时间戳
    if payload.get("type") == "heartbeat":
        payload["ts"] = datetime.utcnow().isoformat() + "Z"
    
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
