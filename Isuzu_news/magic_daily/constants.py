import re

QQ_SOURCES = {"qq_gateway", "napcat_qq"}

EMPTY_HITOKOTO = {"hitokoto": "", "from": ""}

SECTION_KEYS = (
    "moyu",
    "bili_hot",
    "today_anime",
    "world_news",
    "it_news",
    "hitokoto",
)
DEFAULT_SECTIONS = list(SECTION_KEYS)

GREETING_STYLES = ("character", "custom", "off")

WEEKDAYS_CN = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}

NUMBER_PREFIX_PATTERN = re.compile(r"^\d+[\.、\s]*")
