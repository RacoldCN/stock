"""
游戏引擎模块
负责：时间推进、事件触发、价格计算、K线生成、杠杆处理
"""
import random
import json
from stock_data import STOCKS, TOTAL_DAYS, CIRCUIT_BREAKER
from events import EVENTS, RANDOM_EVENT_POOL, CAUSE_CHAINS
from database import (
    get_db, get_stock_price, get_holding, update_holding, delete_holding,
    add_transaction, update_user_cash, get_user, get_game_state,
)


def random_delay_days() -> int:
    """新闻发布1天后直接生效"""
    return 1


def random_duration_days() -> int:
    """事件影响持续1~3天"""
    return random.randint(1, 3)


def random_impact(min_val: float, max_val: float) -> float:
    """在范围内随机生成影响值"""
    return random.uniform(min_val, max_val)


def _gen_impact_values(stocks: list, impact_min: float, impact_max: float) -> str:
    """为受影响股票生成随机影响值JSON"""
    return json.dumps({sid: random_impact(impact_min, impact_max) for sid in stocks})


def _insert_event(conn, user_id: int, idx: int, event_def: dict, current_day: int, delay: int, effective_day: int):
    """插入固定时间线事件（复用连接），影响持续1~3天"""
    duration = random_duration_days()
    conn.execute(
        """INSERT INTO event_log 
           (user_id, event_index, title, description, trigger_day, delay_days,
            effective_day, stocks_affected, impact_type, impact_values, 
            duration_days, status, announced_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'announced', ?)""",
        (user_id, idx, event_def["title"], event_def["description"], current_day, delay,
         effective_day, json.dumps(event_def["stocks_affected"]), event_def["impact_type"],
         _gen_impact_values(event_def["stocks_affected"], event_def["impact_min"], event_def["impact_max"]),
         duration, current_day)
    )


def _insert_event_with_id(conn, user_id: int, idx: int, event_def: dict, current_day: int, delay: int,
                           effective_day: int, event_id: str):
    """插入随机事件（带event_id用于去重，复用连接），影响持续1~3天"""
    duration = random_duration_days()
    conn.execute(
        """INSERT INTO event_log 
           (user_id, event_index, event_id, title, description, trigger_day, delay_days,
            effective_day, stocks_affected, impact_type, impact_values, 
            duration_days, status, announced_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'announced', ?)""",
        (user_id, idx, event_id, event_def["title"], event_def["description"], current_day, delay,
         effective_day, json.dumps(event_def["stocks_affected"]), event_def["impact_type"],
         _gen_impact_values(event_def["stocks_affected"], event_def["impact_min"], event_def["impact_max"]),
         duration, current_day)
    )


def _insert_chain_cause(conn, user_id: int, chain_def: dict, current_day: int, effective_day: int):
    """
    插入因果链起因事件（复用连接）
    插入两行：
    1. 起因事件（立即生效，status='announced'）
    2. 待触发标记（status='pending_chain'，effective_day为经过触发日）
    """
    # 起因事件（立即生效），影响持续1~3天
    cause_duration = random_duration_days()
    conn.execute(
        """INSERT INTO event_log 
           (user_id, event_index, chain_id, title, description, trigger_day, delay_days,
            effective_day, stocks_affected, impact_type, impact_values, 
            duration_days, status, announced_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'announced', ?)""",
        (user_id, -1, chain_def["id"], chain_def["title_cause"], chain_def["desc_cause"],
         current_day, 0, current_day,
         json.dumps(chain_def["stocks_affected_cause"]), chain_def["impact_cause"],
         _gen_impact_values(chain_def["stocks_affected_cause"],
                            chain_def["impact_min_cause"], chain_def["impact_max_cause"]),
         cause_duration, current_day)
    )
    # 待触发经过标记
    conn.execute(
        """INSERT INTO event_log 
           (user_id, event_index, chain_id, title, description, trigger_day, delay_days,
            effective_day, stocks_affected, impact_type, impact_values, 
            duration_days, status, announced_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_chain', ?)""",
        (user_id, -1, chain_def["id"], "【待触发】" + chain_def["title_process"], chain_def["desc_process"],
         current_day, 0, effective_day,
         json.dumps([]), "mixed", json.dumps({}), 0, current_day)
    )


def _insert_chain_process(conn, user_id: int, chain_def: dict, current_day: int, pending: dict):
    """插入因果链经过事件（复用连接），影响持续1~3天"""
    process_duration = random_duration_days()
    conn.execute(
        """INSERT INTO event_log 
           (user_id, event_index, chain_id, title, description, trigger_day, delay_days,
            effective_day, stocks_affected, impact_type, impact_values, 
            duration_days, status, announced_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'announced', ?)""",
        (user_id, -1, chain_def["id"], chain_def["title_process"], chain_def["desc_process"],
         current_day, 0, current_day,
         json.dumps(chain_def["stocks_affected_process"]), chain_def["impact_process"],
         _gen_impact_values(chain_def["stocks_affected_process"],
                            chain_def["impact_min_process"], chain_def["impact_max_process"]),
         process_duration, current_day)
    )


def generate_daily_impacts(total_impact: float, num_days: int) -> list:
    """
    将总影响分散到N天，每天的影响不同（模拟真实的价格发现过程）
    使用加权分配：前几天影响较大，后几天递减
    """
    if num_days <= 0:
        return []
    
    # 生成递减权重
    weights = [max(0.1, 1.0 - i * 0.15) for i in range(num_days)]
    total_weight = sum(weights)
    
    # 按权重分配
    impacts = [total_impact * w / total_weight for w in weights]
    
    # 添加一些随机噪声（±20%），但保持总和不变
    noisy = []
    for i, impact in enumerate(impacts):
        noise = random.uniform(0.8, 1.2)
        noisy.append(impact * noise)
    
    # 重新归一化
    noisy_sum = sum(noisy)
    normalized = [impact * total_impact / noisy_sum for impact in noisy]
    
    return normalized


def generate_ohlc(prev_close: float, daily_change: float) -> dict:
    """
    生成真实感的OHLC数据
    daily_change 是当日涨跌幅（如 0.05 表示 +5%）
    """
    open_price = prev_close
    close_price = open_price * (1 + daily_change)
    
    # 日内波动率：基于日涨跌幅
    intraday_vol = abs(daily_change) * 0.6 + 0.008
    
    # 生成最高价和最低价
    if daily_change >= 0:
        # 上涨日：开盘低，收盘高
        low = open_price * (1 - random.uniform(0, intraday_vol))
        high = close_price * (1 + random.uniform(0, intraday_vol * 0.5))
    else:
        # 下跌日：开盘高，收盘低
        high = open_price * (1 + random.uniform(0, intraday_vol))
        low = close_price * (1 - random.uniform(0, intraday_vol * 0.5))
    
    # 确保 high >= max(open, close) 且 low <= min(open, close)
    high = max(high, open_price, close_price)
    low = min(low, open_price, close_price)
    
    # 成交量（根据涨跌幅度变化）
    base_volume = random.randint(200, 3000)
    volume_multiplier = 1.0 + abs(daily_change) * 5  # 波动越大成交量越大
    volume = int(base_volume * volume_multiplier)
    
    return {
        "open": round(open_price, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "close": round(close_price, 2),
        "volume": volume,
    }


def calculate_daily_change(stock_id: str, active_events: list, is_event_impact_day: dict) -> float:
    """
    计算某只股票当日的涨跌幅
    包含：基础随机游走 + 活跃事件影响 + 涨跌停限制
    """
    # 基础随机游走（布朗运动）
    base_volatility = 0.006  # 日波动率约 0.6%
    base_change = random.gauss(0, base_volatility)
    
    # 事件影响
    event_impact = 0.0
    for event in active_events:
        try:
            stocks_affected = json.loads(event["stocks_affected"])
            impact_values = json.loads(event["impact_values"])
            current_day = event.get("effective_day", 0)  # will be set by caller
            duration = event["duration_days"]
            day_offset = current_day - event["effective_day"]  # how many days since event became active
            
            if stock_id in stocks_affected and stock_id in impact_values:
                total_impact = impact_values[stock_id]
                daily_impacts = generate_daily_impacts(total_impact, duration)
                
                # 当前是事件的第几天（从生效日开始）
                # Use the key from is_event_impact_day
                key = f"{event['id']}_{stock_id}"
                if key in is_event_impact_day:
                    di = is_event_impact_day[key]
                    if di < len(daily_impacts):
                        event_impact += daily_impacts[di]
        except (json.JSONDecodeError, KeyError):
            continue
    
    # 总变化 = 基础 + 事件
    total_change = base_change + event_impact
    
    # 涨跌停限制 ±15%
    total_change = max(-CIRCUIT_BREAKER, min(CIRCUIT_BREAKER, total_change))
    
    return total_change


def advance_day(user_id: int) -> dict:
    """
    推进一天游戏时间（优化版：使用单连接复用，每个用户独立世界）
    返回当天发生的所有变化
    """
    conn = get_db()
    
    try:
        state = dict(conn.execute("SELECT * FROM game_state WHERE user_id = ?", (user_id,)).fetchone())
    except Exception:
        conn.close()
        return {"game_over": True, "day": 0}
    
    current_day = state["current_day"] + 1
    
    if current_day > TOTAL_DAYS:
        conn.close()
        return {"game_over": True, "day": current_day}
    
    result = {"day": current_day, "new_events": [], "activated_events": [], "prices": {}}
    
    # 1. 一次性获取该用户所有已触发事件的索引
    triggered_indices = {
        row["event_index"] for row in
        conn.execute("SELECT event_index FROM event_log WHERE user_id = ?", (user_id,)).fetchall()
    }
    
    # 2. 固定时间线事件
    for idx, event_def in enumerate(EVENTS):
        if event_def["trigger_day"] == current_day and idx not in triggered_indices:
            delay = random_delay_days()
            effective_day = current_day + delay
            _insert_event(conn, user_id, idx, event_def, current_day, delay, effective_day)
            triggered_indices.add(idx)
            result["new_events"].append({
                "title": event_def["title"],
                "description": event_def["description"],
                "trigger_day": current_day,
                "effective_day": effective_day,
                "delay": delay,
            })
    
    # 2.5 每日随机事件
    roll = random.random()
    num_random = 1 if roll < 0.30 else (2 if roll < 0.40 else 0)
    if num_random > 0:
        triggered_event_ids = {row["event_id"] for row in conn.execute(
            "SELECT event_id FROM event_log WHERE user_id = ? AND event_id IS NOT NULL AND event_id != ''",
            (user_id,)
        ).fetchall()}
        available = [e for e in RANDOM_EVENT_POOL if e["id"] not in triggered_event_ids]
        if available:
            selected = random.sample(available, min(num_random, len(available)))
            for rand_ev in selected:
                delay = random_delay_days()
                effective_day = current_day + delay
                rand_idx = 10000 + hash(rand_ev["id"]) % 90000
                _insert_event_with_id(conn, user_id, rand_idx, rand_ev, current_day, delay, effective_day, rand_ev["id"])
                triggered_indices.add(rand_idx)
                result["new_events"].append({
                    "title": rand_ev["title"],
                    "description": rand_ev["description"],
                    "trigger_day": current_day,
                    "effective_day": effective_day,
                    "delay": delay,
                })
    
    # 2.6 因果关系链
    triggered_chains = {row["chain_id"] for row in conn.execute(
        "SELECT chain_id FROM event_log WHERE user_id = ? AND chain_id IS NOT NULL AND chain_id != ''",
        (user_id,)
    ).fetchall()}
    
    # 检查pending的经过事件是否到期
    pending_rows = conn.execute(
        "SELECT * FROM event_log WHERE user_id = ? AND status = 'pending_chain' AND effective_day <= ?",
        (user_id, current_day)
    ).fetchall()
    for pending in pending_rows:
        chain_id = pending["chain_id"]
        chain_def = next((c for c in CAUSE_CHAINS if c["id"] == chain_id), None)
        if chain_def:
            _insert_chain_process(conn, user_id, chain_def, current_day, pending)
            conn.execute("UPDATE event_log SET status = 'chain_done' WHERE id = ?", (pending["id"],))
            result["new_events"].append({
                "title": chain_def["title_process"],
                "description": chain_def["desc_process"],
                "trigger_day": current_day,
                "effective_day": current_day,
                "delay": 0,
            })
    
    # 随机触发新的因果链起因
    if random.random() < 0.05:
        available_chains = [c for c in CAUSE_CHAINS if c["id"] not in triggered_chains]
        if available_chains:
            chain = random.choice(available_chains)
            delay_after = random.randint(chain["delay_min"], chain["delay_max"])
            effective_day = current_day + delay_after
            _insert_chain_cause(conn, user_id, chain, current_day, effective_day)
            triggered_chains.add(chain["id"])
            result["new_events"].append({
                "title": chain["title_cause"],
                "description": chain["desc_cause"],
                "trigger_day": current_day,
                "effective_day": current_day,
                "delay": 0,
            })
    
    # 3. 激活到达生效日的事件
    activated_rows = conn.execute(
        "SELECT * FROM event_log WHERE user_id = ? AND status = 'announced' AND effective_day <= ?",
        (user_id, current_day)
    ).fetchall()
    for event in activated_rows:
        conn.execute("UPDATE event_log SET status = 'active' WHERE id = ?", (event["id"],))
    result["activated_events"] = [dict(a) for a in activated_rows]
    
    # 4. 标记过期事件
    conn.execute(
        "UPDATE event_log SET status = 'expired' WHERE user_id = ? AND status = 'active' AND effective_day + duration_days <= ?",
        (user_id, current_day)
    )
    
    # 5. 获取当前活跃事件
    active_rows = conn.execute(
        """SELECT * FROM event_log
           WHERE user_id = ? AND effective_day <= ? AND effective_day + duration_days > ?
           AND status = 'active'""",
        (user_id, current_day, current_day)
    ).fetchall()
    active_events = [dict(row) for row in active_rows]
    
    # 为活跃事件生成按天的 impact 索引
    is_event_impact_day = {}
    for event in active_events:
        try:
            stocks_affected = json.loads(event["stocks_affected"])
            impact_values = json.loads(event["impact_values"])
            day_offset = current_day - event["effective_day"]
            for sid in stocks_affected:
                if sid in impact_values:
                    key = f"{event['id']}_{sid}"
                    is_event_impact_day[key] = day_offset
        except (json.JSONDecodeError, KeyError):
            continue
    
    # 6. 获取该用户所有价格
    price_rows = conn.execute(
        "SELECT stock_id, current_price, prev_price FROM stock_prices WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    prices = {row["stock_id"]: {"current": row["current_price"], "prev": row["prev_price"]} for row in price_rows}
    
    # 7. 批量计算所有股票新价格 + 收集K线和价格更新
    kline_batch = []
    price_batch = {}
    for stock_id, info in STOCKS.items():
        prev_close = prices.get(stock_id, {}).get("current", info["init_price"])
        daily_change = calculate_daily_change(stock_id, active_events, is_event_impact_day)
        ohlc = generate_ohlc(prev_close, daily_change)
        
        kline_batch.append((user_id, stock_id, current_day, ohlc["open"], ohlc["high"],
                           ohlc["low"], ohlc["close"], ohlc.get("volume", 0)))
        price_batch[stock_id] = ohlc["close"]
        result["prices"][stock_id] = ohlc
    
    # 批量写入K线
    conn.executemany(
        """INSERT OR REPLACE INTO kline (user_id, stock_id, day, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        kline_batch
    )
    
    # 批量更新股价
    for stock_id, new_price in price_batch.items():
        existing = conn.execute(
            "SELECT current_price FROM stock_prices WHERE user_id = ? AND stock_id = ?",
            (user_id, stock_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE stock_prices SET prev_price = current_price, current_price = ? WHERE user_id = ? AND stock_id = ?",
                (round(new_price, 2), user_id, stock_id)
            )
        else:
            conn.execute(
                "INSERT INTO stock_prices (user_id, stock_id, current_price, prev_price) VALUES (?, ?, ?, ?)",
                (user_id, stock_id, round(new_price, 2), round(new_price, 2))
            )
    
    # 8. 检查强制平仓
    holdings_rows = conn.execute(
        "SELECT stock_id, quantity, avg_price, leverage, margin FROM holdings WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    holdings = [dict(h) for h in holdings_rows]
    
    liquidated = []
    for h in holdings:
        stock_id = h["stock_id"]
        if stock_id not in price_batch:
            continue
        
        current_price = price_batch[stock_id]
        quantity = h["quantity"]
        margin = h["margin"]
        leverage = h["leverage"]
        borrowed = quantity * h["avg_price"] - margin
        
        if current_price * quantity < borrowed * 1.2 and leverage > 1:
            sell_amount = current_price * quantity - borrowed
            user = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()
            new_cash = user["cash"] + sell_amount
            conn.execute("UPDATE users SET cash = ? WHERE id = ?", (max(0, new_cash), user_id))
            conn.execute(
                "INSERT INTO transactions (user_id, stock_id, type, quantity, price, leverage, total_amount, created_at_day) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, stock_id, "sell", quantity, current_price, leverage, sell_amount, current_day)
            )
            conn.execute("DELETE FROM holdings WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
            liquidated.append({
                "stock_id": stock_id, "quantity": quantity,
                "price": current_price, "amount": sell_amount,
            })
    result["liquidated"] = liquidated
    
    # 9. 更新游戏天数
    conn.execute(
        "INSERT OR REPLACE INTO game_state (user_id, current_day, is_running, updated_at) VALUES (?, ?, 1, CURRENT_TIMESTAMP)",
        (user_id, current_day)
    )
    
    conn.commit()
    conn.close()
    
    return result


# ===== 交易操作 =====

def execute_buy(user_id: int, stock_id: str, quantity: int, leverage: float) -> dict:
    """
    执行买入操作
    返回: {"success": bool, "message": str, "transaction": dict}
    """
    if leverage not in [1, 2, 3, 5]:
        return {"success": False, "message": "无效的杠杆倍数，可选：1x, 2x, 3x, 5x"}
    
    if quantity <= 0:
        return {"success": False, "message": "购买数量必须大于0"}
    
    price = get_stock_price(user_id, stock_id)
    if price <= 0:
        return {"success": False, "message": "股票不存在"}
    
    state = get_game_state(user_id)
    user = get_user(user_id)
    
    # 计算成本：总价 / 杠杆 = 保证金
    total_value = price * quantity
    margin = total_value / leverage  # 用户实际支付的保证金
    
    if user["cash"] < margin:
        return {"success": False, "message": f"保证金不足！需要 {margin:.1f} 点，当前现金 {user['cash']:.1f} 点"}
    
    # 扣除保证金
    new_cash = user["cash"] - margin
    update_user_cash(user_id, new_cash)
    
    # 更新持仓
    existing = get_holding(user_id, stock_id)
    if existing:
        # 已有持仓，合并计算
        new_qty = existing["quantity"] + quantity
        # 新平均成本 = (旧保证金+新保证金) / (旧股数+新股数) * 杠杆（简化处理）
        new_avg_price = (existing["avg_price"] * existing["quantity"] + price * quantity) / new_qty
        new_margin = existing["margin"] + margin
        # 综合杠杆
        new_leverage = (existing["leverage"] * existing["margin"] + leverage * margin) / new_margin
        update_holding(user_id, stock_id, new_qty, new_avg_price, new_leverage, new_margin)
    else:
        update_holding(user_id, stock_id, quantity, price, leverage, margin)
    
    # 记录交易
    add_transaction(user_id, stock_id, "buy", quantity, price, leverage, margin, state["current_day"])
    
    return {
        "success": True,
        "message": f"成功买入 {quantity} 股 {STOCKS[stock_id]['name']}，保证金 {margin:.1f} 点",
        "transaction": {
            "stock_id": stock_id,
            "stock_name": STOCKS[stock_id]["name"],
            "quantity": quantity,
            "price": price,
            "leverage": leverage,
            "margin": margin,
            "cash_left": new_cash,
        }
    }


def execute_sell(user_id: int, stock_id: str, quantity: int) -> dict:
    """
    执行卖出操作
    返回: {"success": bool, "message": str, "transaction": dict}
    """
    if quantity <= 0:
        return {"success": False, "message": "卖出数量必须大于0"}
    
    holding = get_holding(user_id, stock_id)
    if not holding:
        return {"success": False, "message": "你没有持有该股票"}
    
    if holding["quantity"] < quantity:
        return {"success": False, "message": f"持仓不足！持有 {holding['quantity']} 股"}
    
    price = get_stock_price(user_id, stock_id)
    state = get_game_state(user_id)
    
    # 计算盈亏
    avg_price = holding["avg_price"]
    leverage = holding["leverage"]
    margin = holding["margin"]
    
    # 按比例计算卖出的保证金和盈亏
    sell_ratio = quantity / holding["quantity"]
    sell_margin = margin * sell_ratio
    
    # 卖出总金额 = 当前价格 × 数量
    total_sale = price * quantity
    
    # 借入金额 = 总成本 - 保证金 = avg_price * quantity - sell_margin
    borrowed = avg_price * quantity - sell_margin
    
    # 归还借款后剩余 = total_sale - borrowed
    cash_back = total_sale - borrowed
    
    # 更新现金
    user = get_user(user_id)
    new_cash = user["cash"] + cash_back
    update_user_cash(user_id, new_cash)
    
    # 更新持仓
    remaining_qty = holding["quantity"] - quantity
    if remaining_qty <= 0:
        delete_holding(user_id, stock_id)
    else:
        remaining_margin = margin - sell_margin
        update_holding(user_id, stock_id, remaining_qty, avg_price, leverage, remaining_margin)
    
    # 记录交易
    add_transaction(user_id, stock_id, "sell", quantity, price, leverage, cash_back, state["current_day"])
    
    profit = cash_back - sell_margin
    
    return {
        "success": True,
        "message": f"成功卖出 {quantity} 股 {STOCKS[stock_id]['name']}，{'盈利' if profit >= 0 else '亏损'} {abs(profit):.1f} 点",
        "transaction": {
            "stock_id": stock_id,
            "stock_name": STOCKS[stock_id]["name"],
            "quantity": quantity,
            "price": price,
            "leverage": leverage,
            "cash_back": cash_back,
            "profit": profit,
            "cash_left": new_cash,
        }
    }
