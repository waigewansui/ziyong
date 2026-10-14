"""
天气数据模块
数据源：OpenWeatherMap（免费，需注册 API Key）
"""
import os
import time
import random
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

# OpenWeatherMap API Key（免费版：https://openweathermap.org/api）
OWM_API_KEY = os.environ.get("OWM_API_KEY", "")
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

# 城市名映射（懂球帝队名 → 城市）
CITY_MAP = {
    "曼城": "Manchester", "曼联": "Manchester", "利物浦": "Liverpool",
    "阿森纳": "London", "切尔西": "London", "热刺": "London",
    "皇马": "Madrid", "巴萨": "Barcelona", "马竞": "Madrid",
    "罗马": "Rome", "国米": "Milan", "AC米兰": "Milan", "尤文": "Turin",
    "拜仁": "Munich", "多特蒙德": "Dortmund", "莱比锡": "Leipzig",
    "巴黎圣曼": "Paris", "巴黎圣日耳曼": "Paris",
    "波尔图": "Porto", "本菲卡": "Lisbon", "里斯本": "Lisbon",
    "阿贾克斯": "Amsterdam", "埃因霍温": "Eindhoven",
    "加拉塔萨": "Istanbul", "费内巴切": "Istanbul",
    "神户胜利": "Kobe", "横滨水手": "Yokohama", "柏太阳神": "Kashiwa",
    "全北现代": "Jeonju", "首尔FC": "Seoul", "大田市民": "Daejeon",
    "墨胜利": "Melbourne", "墨尔本胜利": "Melbourne",
    "弗鲁米嫩": "Rio de Janeiro", "帕梅拉斯": "São Paulo",
    "圣路易城": "St. Louis", "温哥华": "Vancouver",
    "博德闪耀": "Bodø", "LASK林茨": "Linz",
}


def fetch_weather(home: str) -> Dict[str, Any]:
    """
    获取主队所在城市的天气
    返回：{temp, description, wind_speed, rain, impact}
    """
    if not OWM_API_KEY:
        logger.debug("OWM_API_KEY 未配置，跳过天气")
        return {"available": False}

    city = CITY_MAP.get(home, "")
    if not city:
        logger.debug(f"未找到 {home} 的城市映射")
        return {"available": False}

    params = {
        "q": city,
        "appid": OWM_API_KEY,
        "units": "metric",
        "lang": "zh_cn",
    }

    try:
        time.sleep(random.uniform(0.2, 0.5))
        r = requests.get(OWM_URL, params=params, timeout=8)
        if r.status_code != 200:
            logger.warning(f"天气 API 返回 {r.status_code}")
            return {"available": False}
        data = r.json()
    except Exception as e:
        logger.warning(f"天气请求失败: {e}")
        return {"available": False}

    weather = {
        "available": True,
        "city": city,
        "temp": data.get("main", {}).get("temp", 0),
        "description": data.get("weather", [{}])[0].get("description", ""),
        "wind_speed": data.get("wind", {}).get("speed", 0),
        "rain": data.get("rain", {}).get("1h", 0),
        "impact": "",
    }

    # 影响分析
    desc = weather["description"]
    rain = weather["rain"]
    wind = weather["wind_speed"]

    impacts = []
    if rain > 2:
        impacts.append("大雨→小球")
        weather["goal_factor"] = 0.85
    elif rain > 0.5:
        impacts.append("小雨→略小")
        weather["goal_factor"] = 0.95
    else:
        weather["goal_factor"] = 1.0

    if wind > 10:
        impacts.append("大风→定位球多")
        weather["goal_factor"] *= 1.05

    if "雪" in desc:
        impacts.append("雪天→冷门多")

    weather["impact"] = "；".join(impacts) if impacts else "无影响"

    logger.info(f"  🌤️ 天气 {city}: {desc} {weather['temp']}°C, {weather['impact']}")
    return weather


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    print(json.dumps(fetch_weather("曼城"), ensure_ascii=False, indent=2))
