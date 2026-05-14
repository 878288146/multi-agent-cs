"""
天气查询Agent — 获取城市实时天气信息
通过 wttr.in（免费，无需API Key）获取天气数据。
"""

from __future__ import annotations

from typing import Any

import httpx

from tracing.otel_config import trace_agent_call

WTTR_URL = "https://wttr.in/{city}?format=%C|%t|%h|%w|%p"


async def fetch_weather(city: str) -> dict:
    """调用 wttr.in 获取天气数据"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                WTTR_URL.format(city=city),
                headers={"User-Agent": "curl/8.0"},
            )
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            parts = resp.text.strip().split("|")
            return {
                "city": city,
                "condition": parts[0] if len(parts) > 0 else "未知",
                "temperature": parts[1] if len(parts) > 1 else "未知",
                "humidity": parts[2] if len(parts) > 2 else "未知",
                "wind": parts[3] if len(parts) > 3 else "未知",
                "precipitation": parts[4] if len(parts) > 4 else "未知",
            }
    except Exception as e:
        return {
            "city": city,
            "condition": "未知",
            "temperature": "未知",
            "humidity": "未知",
            "wind": "未知",
            "precipitation": "未知",
            "error": str(e),
        }


def format_weather(data: dict) -> str:
    """将天气数据格式化为自然语言"""
    if data.get("condition") == "未知" or "error" in data:
        return f"抱歉，暂时无法获取 {data['city']} 的天气信息，请稍后重试。"

    return (
        f"🌤️ {data['city']} 实时天气\n\n"
        f"🌡️ 天气状况：{data['condition']}\n"
        f"🌡️ 温度：{data['temperature']}\n"
        f"💧 湿度：{data['humidity']}\n"
        f"🌬️ 风力：{data['wind']}\n"
        f"☔ 降水量：{data['precipitation']}"
    )


# 常见城市名称列表（用于规则提取）
COMMON_CITIES = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "天津",
    "重庆", "苏州", "西安", "长沙", "青岛", "大连", "厦门", "福州", "合肥",
    "郑州", "昆明", "沈阳", "哈尔滨", "贵阳", "南宁", "海口", "拉萨", "银川",
    "西宁", "兰州", "呼和浩特", "乌鲁木齐", "香港", "澳门", "台北",
    "Tokyo", "London", "New York", "Paris", "Sydney", "Singapore",
    "Bangkok", "Seoul", "Dubai",
]

# 景点/地标 → 城市映射
LANDMARK_CITY = {
    "西湖": "杭州", "外滩": "上海", "故宫": "北京", "长城": "北京",
    "天安门": "北京", "颐和园": "北京", "鸟巢": "北京",
    "东方明珠": "上海", "迪士尼": "上海",
    "小蛮腰": "广州", "珠江": "广州",
    "洪崖洞": "重庆", "解放碑": "重庆", "磁器口": "重庆",
    "宽窄巷子": "成都", "锦里": "成都", "大熊猫": "成都",
    "鼓浪屿": "厦门", "芙蓉镇": "厦门",
    "大唐不夜城": "西安", "兵马俑": "西安", "大雁塔": "西安",
    "橘子洲": "长沙", "岳麓山": "长沙",
    "夫子庙": "南京", "中山陵": "南京",
    "拙政园": "苏州", "虎丘": "苏州", "寒山寺": "苏州",
    "布达拉宫": "拉萨", "大昭寺": "拉萨",
    "洱海": "大理", "古城": "大理", "苍山": "大理",
    "丽江古城": "丽江", "玉龙雪山": "丽江",
    "黄山": "黄山", "泰山": "泰安",
    "庐山": "九江", "张家界": "张家界",
    "黄鹤楼": "武汉", "东湖": "武汉",
    "维多利亚港": "香港", "太平山": "香港", "旺角": "香港",
}


def _extract_city(message: str) -> tuple[str, bool]:
    """从用户消息中提取城市名。

    Returns:
        (城市名, 是否明确匹配到城市/景点)
    """
    # 先检查景点/地标
    for landmark, city in LANDMARK_CITY.items():
        if landmark in message:
            return city, True
    # 再检查城市名
    for city in COMMON_CITIES:
        if city in message:
            return city, True
    # 未找到明确城市
    return "", False


class WeatherAgent:
    """天气查询Agent"""

    @trace_agent_call("weather_process")
    async def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """作为Graph节点处理状态"""
        messages = state.get("messages", [])
        if not messages:
            return state

        last_message = messages[-1].content

        city, found = _extract_city(last_message)

        if not found:
            # 不确定城市，让用户补充
            return {
                **state,
                "sub_results": {
                    **state.get("sub_results", {}),
                    "weather": "请问您想查询哪个城市的天气？",
                },
            }

        weather_data = await fetch_weather(city)

        result = format_weather(weather_data)

        return {
            **state,
            "sub_results": {
                **state.get("sub_results", {}),
                "weather": result,
            },
        }
