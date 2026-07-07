"""
股票数据定义
17只社团股
"""

# 学期映射：根据天数返回当前学期信息
def get_semester_info(day: int) -> dict:
    """根据教学日返回学期信息，共6个学期，每学期100天（20周×5天）"""
    if day <= 0:
        return {"name": "准备阶段", "year": "——", "short": "准备"}
    
    sem_idx = (day - 1) // 100  # 0-5
    week_in_sem = ((day - 1) % 100) // 5 + 1
    
    semesters = [
        {"name": "高一上", "year": "2025.9 - 2026.1", "short": "高一上"},
        {"name": "高一下", "year": "2026.2 - 2026.7", "short": "高一下"},
        {"name": "高二上", "year": "2026.9 - 2027.1", "short": "高二上"},
        {"name": "高二下", "year": "2027.2 - 2027.7", "short": "高二下"},
        {"name": "高三上", "year": "2027.9 - 2028.1", "short": "高三上"},
        {"name": "高三下", "year": "2028.2 - 2028.6", "short": "高三下"},
    ]
    
    if sem_idx >= len(semesters):
        return {"name": "毕业", "year": "游戏结束", "short": "毕业"}
    
    return {
        **semesters[sem_idx],
        "week_in_sem": week_in_sem,
    }

def get_week(day: int) -> int:
    """返回当前是第几教学周"""
    return (day - 1) // 5 + 1

# 所有股票定义
# 股票代码规则：社团股 xmst001-017
STOCKS = {
    # ===== 热门社团 (初始价 >75) =====
    "om-brain": {
        "id": "om-brain",
        "code": "xmst001",
        "name": "头脑奥林匹克创新社",
        "category": "hot_club",
        "category_name": "热门社团",
        "init_price": 78.0,
    },
    "basketball": {
        "id": "basketball",
        "code": "xmst002",
        "name": "篮球社",
        "category": "hot_club",
        "category_name": "热门社团",
        "init_price": 82.0,
    },
    "mayfly-band": {
        "id": "mayfly-band",
        "code": "xmst003",
        "name": "蜉蝣天空乐队",
        "category": "hot_club",
        "category_name": "热门社团",
        "init_price": 88.0,
    },
    "aero-model": {
        "id": "aero-model",
        "code": "xmst004",
        "name": "航模社",
        "category": "hot_club",
        "category_name": "热门社团",
        "init_price": 76.0,
    },
    "181-band": {
        "id": "181-band",
        "code": "xmst005",
        "name": "181乐队",
        "category": "hot_club",
        "category_name": "热门社团",
        "init_price": 85.0,
    },

    # ===== 普通社团 (初始价 56-65) =====
    "reporter": {
        "id": "reporter",
        "code": "xmst006",
        "name": "记者社",
        "category": "normal_club",
        "category_name": "普通社团",
        "init_price": 60.0,
    },
    "mun": {
        "id": "mun",
        "code": "xmst007",
        "name": "模联社",
        "category": "normal_club",
        "category_name": "普通社团",
        "init_price": 62.0,
    },
    "football": {
        "id": "football",
        "code": "xmst008",
        "name": "足球社",
        "category": "normal_club",
        "category_name": "普通社团",
        "init_price": 56.0,
    },
    "debate": {
        "id": "debate",
        "code": "xmst011",
        "name": "辩论社",
        "category": "normal_club",
        "category_name": "普通社团",
        "init_price": 58.0,
    },
    # ===== 潜力社团 (初始价 35-50) =====
    "badminton": {
        "id": "badminton",
        "code": "xmst009",
        "name": "羽毛球",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 48.0,
    },
    "super-sci": {
        "id": "super-sci",
        "code": "xmst010",
        "name": "超科学社（智能小车社团）",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 45.0,
    },
    "robot": {
        "id": "robot",
        "code": "xmst012",
        "name": "机器人社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 37.0,
    },
    "xuanling": {
        "id": "xuanling",
        "code": "xmst013",
        "name": "悬铃影社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 41.0,
    },

    # ===== 潜力社团 (初始价 15-30) =====
    "computer": {
        "id": "computer",
        "code": "xmst014",
        "name": "计算机社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 22.0,
    },
    "shanghai": {
        "id": "shanghai",
        "code": "xmst015",
        "name": "沪语社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 18.0,
    },
    "percussion": {
        "id": "percussion",
        "code": "xmst016",
        "name": "打击乐社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 25.0,
    },
    "curling": {
        "id": "curling",
        "code": "xmst017",
        "name": "冰壶社",
        "category": "potential_club",
        "category_name": "潜力社团",
        "init_price": 20.0,
    },

}

# 股票排序用列表
STOCK_ORDER = list(STOCKS.keys())

# 游戏常量
TOTAL_DAYS = 600          # 总教学日（120周 × 5天）
DAYS_PER_SEMESTER = 100   # 每学期教学日
DAYS_PER_WEEK = 5         # 每周教学日
WEEKS_PER_BREAK = 20      # 每20周（100天）放一次寒暑假
CIRCUIT_BREAKER = 0.15    # 涨跌停幅度 ±15%
INITIAL_CASH = 1000.0     # 初始资金
LEVERAGE_OPTIONS = [1, 2, 3, 5]  # 可选杠杆倍数

BREAK_NAMES = {
    100: "寒假来啦！❄️",
    200: "暑假来啦！☀️",
    300: "寒假来啦！❄️",
    400: "暑假来啦！☀️",
    500: "寒假来啦！❄️（高考冲刺前的最后一个假期）",
}


def get_dynamic_category(current_price: float, base_category: str) -> str:
    """根据现价动态计算社团分类"""
    if current_price > 75:
        return "热门社团"
    elif current_price > 55:
        return "普通社团"
    else:
        return "潜力社团"
