"""
队名解析器 - 自动学习 + 模糊匹配 + 本地缓存
"""
import os
import json
import logging
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "team_aliases.json"
)

# 核心映射表（英文别名必须足够具体，避免 substring 误匹配）
CORE_ALIASES = {
    "皇马": ["real madrid"],
    "巴萨": ["barcelona", "barca", "fc barcelona"],
    "利物浦": ["liverpool", "liverpool fc"],
    "曼城": ["manchester city", "man city"],
    "曼联": ["manchester united", "man united", "manchester utd"],
    "阿森纳": ["arsenal"],
    "切尔西": ["chelsea"],
    "热刺": ["tottenham", "spurs", "tottenham hotspur"],
    "拜仁": ["bayern munich", "bayern münchen", "bayern"],
    "多特蒙德": ["borussia dortmund", "dortmund", "bvb"],
    "巴黎圣曼": ["paris saint-germain", "paris sg", "psg", "paris saint germain"],
    "国米": ["inter milan", "internazionale", "inter"],
    "AC米兰": ["ac milan", "milan"],
    "尤文": ["juventus", "juve"],
    "罗马": ["as roma", "roma"],
    "那不勒斯": ["napoli"],
    "马竞": ["atletico madrid", "atl. madrid", "atletico"],
    "波尔图": ["fc porto", "porto"],
    "本菲卡": ["benfica", "sl benfica"],
    "里斯本": ["sporting cp", "sporting lisbon", "sporting"],
    "阿贾克斯": ["ajax", "afc ajax"],
    "埃因霍温": ["psv eindhoven", "psv"],
    "加拉塔萨": ["galatasaray"],
    "费内巴切": ["fenerbahce", "fenerbahçe"],
    "博德闪耀": ["bodo/glimt", "bodo glimt", "bodø/glimt", "bodo"],
    "LASK林茨": ["lask linz", "lask"],
    "维拉": ["aston villa", "villa"],
    "横滨水手": ["yokohama f. marinos", "yokohama marinos"],
    "神户胜利": ["vissel kobe", "kobe"],
    "柏太阳神": ["kashiwa reysol"],
    "全北现代": ["jeonbuk hyundai", "jeonbuk"],
    "首尔FC": ["fc seoul", "seoul fc"],
    "弗鲁米嫩": ["fluminense"],
    "帕梅拉斯": ["palmeiras"],
    "贝蒂斯": ["real betis", "betis"],
    "科莫": ["como"],
    "费耶诺德": ["feyenoord"],
    "布鲁日": ["club brugge"],
    "圣路易城": ["st. louis city", "st louis city"],
    "温哥华": ["vancouver whitecaps", "vancouver"],
    "大田市民": ["daejeon"],
    "墨胜利": ["melbourne victory"],
}


class TeamNameResolver:
    """
    队名解析器
    - 学习：从懂球帝返回自动学习（带双向检查，避免误学）
    - 匹配：精确 → 缓存(精确) → 核心表 → 模糊
    - 持久化：学到新映射自动存本地
    """

    def __init__(self):
        self.aliases = {}
        self._load()

    def _load(self):
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    self.aliases = json.load(f)
                logger.debug(f"队名缓存加载: {len(self.aliases)} 条")
            except Exception as e:
                logger.warning(f"队名缓存加载失败: {e}")
                self.aliases = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.aliases, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"队名缓存保存失败: {e}")

    def learn(self, cn_name: str, en_name: str):
        """自动学习：中文名 → 英文别名（带双向检查，避免误学）"""
        if not cn_name or not en_name:
            return
        cn_name = cn_name.strip()
        en_name = en_name.strip()
        if not cn_name or not en_name or cn_name == en_name:
            return
        if not any("\u4e00" <= c <= "\u9fff" for c in cn_name):
            return

        en_lower = en_name.lower()

        # 检查 1：这个英文名是否已被"其他队"学过？
        for other_cn, aliases in self.aliases.items():
            if other_cn == cn_name:
                continue
            for a in aliases:
                if a.lower() == en_lower:
                    logger.debug(f"跳过学习: {en_name} 已属于 {other_cn}")
                    return

        # 检查 2：这个英文名是否命中"其他队"的核心表（全词匹配）？
        for other_cn, aliases in CORE_ALIASES.items():
            if other_cn == cn_name:
                continue
            for a in aliases:
                if a == en_lower:
                    logger.debug(f"跳过学习: {en_name} 属于 {other_cn} (核心表)")
                    return

        # 检查 3：反向 —— 目标英文名是否被其他队的更具体别名覆盖？
        # 例如 "Atl. Madrid" 包含 "madrid"，但 "atletico" 更具体 → 归马竞
        for other_cn, aliases in CORE_ALIASES.items():
            if other_cn == cn_name:
                continue
            # 如果 en_name 包含了其他队的 ≥6 字符别名，且该别名更具体（长度更长）
            for a in aliases:
                if len(a) >= 8 and a in en_lower and len(a) > len(en_lower) / 2:
                    logger.debug(f"跳过学习: {en_name} 可能属于 {other_cn} (别名 {a})")
                    return

        # 通过所有检查，学习
        self.aliases.setdefault(cn_name, [])
        if en_name not in self.aliases[cn_name]:
            self.aliases[cn_name].append(en_name)
            self._save()
            logger.info(f"  📚 学到新别名: {cn_name} ← {en_name}")

    def matches(self, cn_name: str, target_name: str,
                threshold: float = 0.55) -> bool:
        """判断中文名和英文名是否指向同一支球队"""
        if not cn_name or not target_name:
            return False

        cn_lower = cn_name.lower().strip()
        target_lower = target_name.lower().strip()

        # 1. 完全相同
        if cn_lower == target_lower:
            return True

        # 2. 学习缓存命中（精确匹配 + 安全的 substring）
        for alias in self.aliases.get(cn_name, []):
            a = alias.lower()
            if a == target_lower:
                return True
            if f" {a} " in f" {target_lower} ":
                return True
            if len(a) >= 8 and a in target_lower:
                return True

        # 3. 核心表命中
        for alias in CORE_ALIASES.get(cn_name, []):
            if alias == target_lower:
                self.learn(cn_name, target_name)
                return True
            if f" {alias} " in f" {target_lower} ":
                self.learn(cn_name, target_name)
                return True
            if len(alias) >= 8 and alias in target_lower:
                self.learn(cn_name, target_name)
                return True

        # 4. 反向：target 是中文，cn_name 是英文
        for cn, en_list in CORE_ALIASES.items():
            if cn.lower() == target_lower:
                if any(e == cn_lower or (len(e) >= 8 and e in cn_lower) for e in en_list):
                    return True
            if cn.lower() in target_lower or target_lower in cn.lower():
                if any(e in cn_lower for e in en_list if len(e) >= 8):
                    return True

        # 5. 模糊匹配（纯英文）
        if cn_lower.isascii() and target_lower.isascii():
            ratio = SequenceMatcher(None, cn_lower, target_lower).ratio()
            if ratio >= threshold:
                return True

        return False

    def extract_and_learn(self, intel: dict, cn_name: str):
        """从 intel 数据里自动学习（如有英文名字段）"""
        if not intel:
            return
        info = intel.get("info", {}) or {}
        for key in ["home_team_name_en", "away_team_name_en",
                    "home_en", "away_en"]:
            en = info.get(key, "")
            if en and cn_name:
                self.learn(cn_name, en)


_resolver: Optional[TeamNameResolver] = None


def get_resolver() -> TeamNameResolver:
    global _resolver
    if _resolver is None:
        _resolver = TeamNameResolver()
    return _resolver
