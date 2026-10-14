"""
历史报告归档
"""
import os
import shutil
import logging
from datetime import datetime
from glob import glob

logger = logging.getLogger(__name__)


def archive(output_dir: str = "output"):
    """把最新报告归档到 output/history/YYYY-MM-DD/"""
    today = datetime.now().strftime("%Y-%m-%d")
    archive_dir = os.path.join(output_dir, "history", today)
    os.makedirs(archive_dir, exist_ok=True)

    # 找最新一批文件（1 小时内修改的）
    now_ts = datetime.now().timestamp()
    patterns = ["recommend_*.md", "recommend_*.json",
                "parlay_*.md", "parlay_*.json"]
    count = 0
    for pattern in patterns:
        for f in glob(os.path.join(output_dir, pattern)):
            if now_ts - os.path.getmtime(f) < 3600:
                shutil.copy2(f, archive_dir)
                count += 1

    logger.info(f"归档 {count} 个文件到 {archive_dir}")
    return archive_dir
