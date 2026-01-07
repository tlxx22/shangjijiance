"""
Prompt 模板管理
"""
from pathlib import Path
from fastapi import HTTPException


# 模板目录：相对于此文件的位置
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt_template(category: str) -> str:
    """
    加载指定 category 的提示词模板
    
    Args:
        category: 类别名称，如 "fuwu"
    
    Returns:
        模板内容
    
    Raises:
        ValueError: category 对应的模板不存在
    """
    path = PROMPTS_DIR / f"{category}.txt"
    if not path.exists():
        raise ValueError(f"未知 category: {category}，模板文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, category: str, **kwargs) -> str:
    """
    渲染提示词模板
    
    Args:
        template: 模板内容
        category: 类别名称（用于错误信息）
        **kwargs: 占位符参数，如 site_name, date_start, date_end
    
    Returns:
        渲染后的提示词
    
    Raises:
        HTTPException 500: 模板缺少占位符
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise HTTPException(500, f"模板 {category} 缺少占位符: {e}")
