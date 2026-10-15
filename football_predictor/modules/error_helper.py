"""把 subprocess 的原始 stderr 翻译成人话"""
import re


PATTERNS = [
    (r"ModuleNotFoundError: No module named '(\w+)'",
     "缺少依赖：{0}。请运行 `pip install {0}`"),
    (r"FileNotFoundError.*?'([^']+)'",
     "找不到文件：{0}。请检查路径是否正确"),
    (r"ConnectionError|Max retries exceeded",
     "网络异常：无法连接数据源，请检查网络或稍后重试"),
    (r"TimeoutError|ReadTimeout",
     "请求超时：数据源响应太慢，建议重跑一次"),
    (r"KeyError: '([^']+)'",
     "数据字段缺失：{0}。可能是数据源格式变了，贴日志给我"),
    (r"JSONDecodeError",
     "数据解析失败：数据源返回了非 JSON 内容，可能被拦截"),
    (r"PermissionError",
     "文件权限不足：请关闭正在占用的文件后重试"),
]


def friendly_error(stderr: str) -> str:
    """把 raw stderr 转成友好提示"""
    if not stderr:
        return "未知错误，无输出"

    for pat, msg in PATTERNS:
        m = re.search(pat, stderr)
        if m:
            try:
                return "❌ " + msg.format(*m.groups())
            except Exception:
                return "❌ " + msg

    # 兜底：取最后 3 行非空 stderr
    lines = [l for l in stderr.strip().split("\n") if l.strip()]
    tail = "\n".join(lines[-3:])
    return f"❌ 程序异常，最后输出：\n{tail}"


def friendly_log_hint(stdout: str) -> str:
    """从日志里提取进度关键词，给一个'正在做什么'的提示"""
    if not stdout:
        return "正在启动..."
    if "获取赛程" in stdout:
        return "正在拉取赛程..."
    if "获取情报" in stdout:
        return "正在获取情报（懂球帝）..."
    if "λ_h" in stdout:
        return "正在计算模型..."
    if "生成输出" in stdout:
        return "正在生成投注单..."
    return "正在分析..."
