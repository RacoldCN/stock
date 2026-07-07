"""
校园证券交易所 - FastAPI 主服务器
运行方式: python main.py
访问地址: http://localhost:8000
"""
import json
import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, FileSystemLoader, select_autoescape

from database import init_db, init_stock_prices
from stock_data import STOCKS, get_semester_info, get_week, TOTAL_DAYS, INITIAL_CASH, LEVERAGE_OPTIONS, get_dynamic_category, BREAK_NAMES
from events import EVENTS
from game_engine import advance_day, execute_buy, execute_sell
from quiz import QUIZ_QUESTIONS

# 初始化
init_db()
init_stock_prices(STOCKS)

app = FastAPI(title="校园证券交易所")
app.add_middleware(SessionMiddleware, secret_key="campus-stock-exchange-2025")

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 模板引擎（直接使用，绕过 Starlette Jinja2Templates 兼容问题）
jinja2_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def render_template(name: str, context: dict) -> HTMLResponse:
    """渲染 Jinja2 模板并返回 HTML 响应"""
    template = jinja2_env.get_template(name)
    return HTMLResponse(template.render(**context))


# ===== 辅助函数 =====

def get_current_user(request: Request) -> dict | None:
    """从 session 获取当前登录用户"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    from database import get_user
    return get_user(user_id)


def require_login(request: Request):
    """检查登录状态，未登录则跳转"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


# ===== 页面路由 =====

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 → 登录页或仪表盘"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录/注册页"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return render_template("login.html", {"request": request})


def get_news_for_template(user_id: int):
    """获取最近新闻（供各页面侧边栏使用）"""
    from database import get_all_events
    events_data = get_all_events(user_id, limit=20)
    news = []
    for e in events_data:
        if e["status"] == "expired":
            continue
        status_map = {"announced": "📢 已发布", "active": "🔥 生效中"}
        news.append({
            "title": e["title"],
            "description": e["description"],
            "status": e["status"],
            "status_label": status_map.get(e["status"], e["status"]),
            "trigger_day": e["trigger_day"],
        })
    return news


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """主仪表盘"""
    user = require_login(request)
    from database import get_game_state, get_all_prices, get_holdings, get_transactions
    state = get_game_state(user["id"])
    prices = get_all_prices(user["id"])
    holdings = get_holdings(user["id"])
    transactions = get_transactions(user["id"], limit=20)
    
    # 计算持仓市值和盈亏
    portfolio_value = 0.0
    holdings_data = []
    for h in holdings:
        sid = h["stock_id"]
        current_price = prices.get(sid, {}).get("current", 0)
        market_value = current_price * h["quantity"]
        cost = h["avg_price"] * h["quantity"]
        profit = market_value - cost
        if h["margin"] > 0:
            leveraged_return = profit / h["margin"] * 100
        else:
            leveraged_return = 0
        
        portfolio_value += market_value
        
        holdings_data.append({
            **h,
            "code": STOCKS[sid].get("code", sid),
            "stock_name": STOCKS[sid]["name"],
            "category": get_dynamic_category(current_price, STOCKS[sid]["category_name"]),
            "current_price": current_price,
            "market_value": market_value,
            "profit": profit,
            "profit_pct": (current_price / h["avg_price"] - 1) * 100 if h["avg_price"] > 0 else 0,
            "leveraged_return": leveraged_return,
        })
    
    total_assets = user["cash"] + portfolio_value
    total_profit = total_assets - INITIAL_CASH
    
    market_data = []
    for sid in STOCKS:
        price_info = prices.get(sid, {})
        current_p = price_info.get("current", STOCKS[sid]["init_price"])
        prev_p = price_info.get("prev", STOCKS[sid]["init_price"])
        change = current_p - prev_p
        change_pct = (change / prev_p * 100) if prev_p > 0 else 0
        dyn_category = get_dynamic_category(current_p, STOCKS[sid]["category_name"])
        market_data.append({
            "id": sid,
            "code": STOCKS[sid].get("code", sid),
            "name": STOCKS[sid]["name"],
            "category": dyn_category,
            "price": current_p,
            "change": change,
            "change_pct": change_pct,
        })
    
    semester = get_semester_info(state["current_day"])
    
    return render_template("dashboard.html", {
        "request": request,
        "user": user,
        "state": state,
        "semester": semester,
        "week": get_week(state["current_day"]) if state["current_day"] > 0 else 0,
        "total_days": TOTAL_DAYS,
        "holdings": holdings_data,
        "market_data": market_data,
        "total_assets": total_assets,
        "total_profit": total_profit,
        "transactions": [dict(t) for t in transactions],
        "stock_names": {s["id"]: s["name"] for s in market_data},
        "news": get_news_for_template(user["id"]),
    })


@app.get("/trade", response_class=HTMLResponse)
async def trade_page(request: Request, stock: str = ""):
    """交易页"""
    user = require_login(request)
    from database import get_game_state, get_all_prices, get_holdings
    
    state = get_game_state(user["id"])
    prices = get_all_prices(user["id"])
    holdings = get_holdings(user["id"])
    
    # 组织股票数据
    stocks_data = []
    for sid, info in STOCKS.items():
        price_info = prices.get(sid, {})
        current_p = price_info.get("current", info["init_price"])
        prev_p = price_info.get("prev", info["init_price"])
        stocks_data.append({
            "id": sid,
            "code": info.get("code", sid),
            "name": info["name"],
            "category": get_dynamic_category(current_p, info["category_name"]),
            "price": current_p,
            "change": current_p - prev_p,
            "change_pct": (current_p - prev_p) / prev_p * 100 if prev_p > 0 else 0,
        })
    
    holdings_map = {h["stock_id"]: h for h in holdings}
    
    # 构建 stock_names 和 stock_codes 映射（用于卖出下拉）
    stock_name_map = {}
    stock_code_map = {}
    for s in stocks_data:
        stock_name_map[s["id"]] = s["name"]
        stock_code_map[s["id"]] = s["code"]
    
    return render_template("trade.html", {
        "request": request,
        "user": user,
        "state": state,
        "total_days": TOTAL_DAYS,
        "stocks": stocks_data,
        "holdings": holdings_map,
        "leverage_options": LEVERAGE_OPTIONS,
        "stock_names": stock_name_map,
        "stock_codes": stock_code_map,
        "news": get_news_for_template(user["id"]),
        "focus_stock": stock,  # 从仪表盘跳转时指定的股票
    })


@app.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    """新闻/事件页 → 已合并到仪表盘和交易页侧边栏"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


# ===== API 路由 =====

@app.post("/api/register")
async def api_register(request: Request, username: str = Form(...), password: str = Form(...)):
    """注册"""
    if len(username) < 2 or len(username) > 20:
        return JSONResponse({"success": False, "message": "用户名长度 2-20 字符"})
    if len(password) < 3:
        return JSONResponse({"success": False, "message": "密码至少 3 位"})
    
    from database import create_user
    user = create_user(username, password)
    if user:
        request.session["user_id"] = user["id"]
        return JSONResponse({"success": True, "message": "注册成功", "user": user})
    return JSONResponse({"success": False, "message": "用户名已存在"})


@app.post("/api/login")
async def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    """登录"""
    from database import verify_user
    user = verify_user(username, password)
    if user:
        request.session["user_id"] = user["id"]
        return JSONResponse({"success": True, "message": "登录成功", "user": user})
    return JSONResponse({"success": False, "message": "用户名或密码错误"})


@app.get("/api/logout")
async def api_logout(request: Request):
    """退出登录"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.post("/api/advance_day")
async def api_advance_day(request: Request):
    """推进一天"""
    user = require_login(request)
    result = advance_day(user["id"])
    
    # 获取更新后的用户信息
    from database import get_user, get_all_prices, set_game_running
    updated_user = get_user(user["id"])
    prices = get_all_prices(user["id"])
    
    # 检查是否到达寒暑假（每100天）
    break_notice = None
    if result.get("day", 0) in BREAK_NAMES:
        break_notice = BREAK_NAMES[result["day"]]
        set_game_running(user["id"], False)
    else:
        # 非寒暑假时确保 is_running=1（防止状态丢失）
        set_game_running(user["id"], True)
    
    # 获取活跃事件数量
    from database import get_active_events as gae
    active_events = gae(user["id"], result.get("day", 0))
    
    # 获取新闻数据（供前端实时更新）
    news_data = get_news_for_template(user["id"])
    
    return JSONResponse({
        "success": True,
        **result,
        "cash": updated_user["cash"],
        "prices_simple": {k: v["current"] for k, v in prices.items()},
        "break_notice": break_notice,
        "active_event_count": len(active_events),
        "news": news_data,
    })


@app.post("/api/buy")
async def api_buy(
    request: Request,
    stock_id: str = Form(...),
    quantity: int = Form(...),
    leverage: float = Form(1.0),
):
    """买入股票"""
    user = require_login(request)
    result = execute_buy(user["id"], stock_id, quantity, leverage)
    return JSONResponse(result)


@app.post("/api/sell")
async def api_sell(
    request: Request,
    stock_id: str = Form(...),
    quantity: int = Form(...),
):
    """卖出股票"""
    user = require_login(request)
    result = execute_sell(user["id"], stock_id, quantity)
    return JSONResponse(result)


@app.get("/api/game_state")
async def api_game_state(request: Request):
    """获取当前游戏状态"""
    user = require_login(request)
    from database import get_game_state, get_all_prices, get_holdings, get_user
    state = get_game_state(user["id"])
    prices = get_all_prices(user["id"])
    holdings = get_holdings(user["id"])
    updated_user = get_user(user["id"])
    semester = get_semester_info(state["current_day"])
    
    return JSONResponse({
        "day": state["current_day"],
        "week": get_week(state["current_day"]) if state["current_day"] > 0 else 0,
        "semester": semester,
        "is_running": state["is_running"],
        "cash": updated_user["cash"],
        "prices": {k: v["current"] for k, v in prices.items()},
        "holdings": holdings,
    })


@app.get("/api/kline/{stock_id}")
async def api_kline(request: Request, stock_id: str):
    """获取K线数据"""
    user = require_login(request)
    from database import get_kline
    data = get_kline(user["id"], stock_id, limit=180)  # 最近180天
    return JSONResponse({"success": True, "data": data, "stock_name": STOCKS.get(stock_id, {}).get("name", stock_id)})


@app.get("/api/portfolio")
async def api_portfolio(request: Request):
    """获取用户持仓"""
    user = require_login(request)
    from database import get_holdings, get_user, get_all_prices
    holdings = get_holdings(user["id"])
    prices = get_all_prices(user["id"])
    updated_user = get_user(user["id"])
    
    holdings_data = []
    total_market_value = 0
    for h in holdings:
        sid = h["stock_id"]
        cp = prices.get(sid, {}).get("current", 0)
        mv = cp * h["quantity"]
        cost = h["avg_price"] * h["quantity"]
        profit = mv - cost
        total_market_value += mv
        holdings_data.append({
            **h,
            "stock_name": STOCKS[sid]["name"],
            "current_price": cp,
            "market_value": mv,
            "profit": profit,
            "profit_pct": (cp / h["avg_price"] - 1) * 100 if h["avg_price"] > 0 else 0,
        })
    
    return JSONResponse({
        "cash": updated_user["cash"],
        "holdings": holdings_data,
        "total_market_value": total_market_value,
        "total_assets": updated_user["cash"] + total_market_value,
    })


@app.post("/api/reset")
async def api_reset(request: Request):
    """重置当前用户游戏数据"""
    user = require_login(request)
    from database import reset_game
    reset_game(user["id"])
    from database import init_stock_prices
    init_stock_prices(STOCKS, user_id=user["id"])
    return JSONResponse({"success": True, "message": "游戏已重置，资金恢复为初始值"})


# ===== 知识答题 =====

@app.get("/quiz", response_class=HTMLResponse)
async def quiz_page(request: Request):
    """答题页面"""
    user = require_login(request)
    from database import get_quiz_record
    record = get_quiz_record(user["id"])
    return render_template("quiz.html", {
        "request": request,
        "user": user,
        "questions": QUIZ_QUESTIONS,
        "total_questions": len(QUIZ_QUESTIONS),
        "quiz_record": record,
    })


@app.post("/api/submit_quiz")
async def api_submit_quiz(request: Request):
    """提交答题结果"""
    user = require_login(request)
    body = await request.json()
    answers = body.get("answers", {})

    correct = 0
    for q in QUIZ_QUESTIONS:
        qid = str(q["id"])
        if answers.get(qid) == q["answer"]:
            correct += 1

    from database import submit_quiz_result
    result = submit_quiz_result(user["id"], correct)
    result["success"] = True
    return JSONResponse(result)


# ===== 启动 =====

if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  校园证券交易所")
    print("  访问地址: http://localhost:8080")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8080)
