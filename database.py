"""
数据库操作模块 v3
每个用户拥有独立的游戏世界（game_state / stock_prices / kline / event_log 均按 user_id 隔离）
"""
import sqlite3
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "game.db")
INITIAL_CASH = 1000.0


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构（兼容旧版自动迁移）"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        -- 用户表
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            cash REAL DEFAULT 1000.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 游戏状态（每个用户独立一行）
        CREATE TABLE IF NOT EXISTS game_state (
            user_id INTEGER PRIMARY KEY,
            current_day INTEGER DEFAULT 0,
            is_running INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- 当前股票价格（每个用户独立）
        CREATE TABLE IF NOT EXISTS stock_prices (
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            current_price REAL NOT NULL,
            prev_price REAL NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, stock_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- K线数据（每个用户独立）
        CREATE TABLE IF NOT EXISTS kline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            day INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER DEFAULT 0,
            UNIQUE(user_id, stock_id, day),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- 持仓表
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            avg_price REAL NOT NULL,
            leverage REAL DEFAULT 1.0,
            margin REAL DEFAULT 0.0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, stock_id)
        );

        -- 交易记录
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            leverage REAL DEFAULT 1.0,
            total_amount REAL NOT NULL,
            created_at_day INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- 答题记录
        CREATE TABLE IF NOT EXISTS quiz_records (
            user_id INTEGER NOT NULL,
            score INTEGER DEFAULT 0,
            best_score INTEGER DEFAULT 0,
            total_attempts INTEGER DEFAULT 0,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- 事件记录（每个用户独立）
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_index INTEGER NOT NULL,
            event_id TEXT DEFAULT '',
            chain_id TEXT DEFAULT '',
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            trigger_day INTEGER NOT NULL,
            delay_days INTEGER NOT NULL,
            effective_day INTEGER NOT NULL,
            stocks_affected TEXT NOT NULL,
            impact_type TEXT NOT NULL,
            impact_values TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            status TEXT DEFAULT 'announced',
            announced_at_day INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    # 兼容旧版表结构：如果旧表存在且缺少 user_id 列，自动迁移
    try:
        cursor.execute("ALTER TABLE event_log ADD COLUMN user_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE event_log ADD COLUMN event_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE event_log ADD COLUMN chain_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE kline ADD COLUMN user_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE stock_prices ADD COLUMN user_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# ===== 用户操作 =====

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(username: str, password: str, initial_cash: float = INITIAL_CASH) -> dict | None:
    """创建新用户，同时初始化个人游戏世界"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, cash) VALUES (?, ?, ?)",
            (username, hash_password(password), initial_cash)
        )
        conn.commit()
        user = conn.execute(
            "SELECT id, username, cash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if not user:
            return None
        uid = user["id"]

        # 初始化个人游戏状态（Day 0）
        conn.execute(
            "INSERT OR IGNORE INTO game_state (user_id, current_day, is_running) VALUES (?, 0, 0)",
            (uid,)
        )

        # 初始化个人股票价格
        from stock_data import STOCKS
        for sid, info in STOCKS.items():
            price = info["init_price"]
            conn.execute(
                "INSERT OR IGNORE INTO stock_prices (user_id, stock_id, current_price, prev_price) VALUES (?, ?, ?, ?)",
                (uid, sid, price, price)
            )

        # 插入Day 0的K线（初始锚点）
        for sid, info in STOCKS.items():
            price = info["init_price"]
            conn.execute(
                """INSERT OR IGNORE INTO kline (user_id, stock_id, day, open, high, low, close, volume)
                   VALUES (?, ?, 0, ?, ?, ?, ?, 1000)""",
                (uid, sid, price, price, price, price)
            )

        conn.commit()
        return dict(user)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_user(username: str, password: str) -> dict | None:
    conn = get_db()
    user = conn.execute(
        "SELECT id, username, cash FROM users WHERE username = ? AND password_hash = ?",
        (username, hash_password(password))
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user(user_id: int) -> dict | None:
    conn = get_db()
    user = conn.execute("SELECT id, username, cash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def update_user_cash(user_id: int, new_cash: float):
    conn = get_db()
    conn.execute("UPDATE users SET cash = ? WHERE id = ?", (new_cash, user_id))
    conn.commit()
    conn.close()


# ===== 游戏状态（每个用户独立） =====

def get_game_state(user_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM game_state WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else {"user_id": user_id, "current_day": 0, "is_running": 0}


def update_game_day(user_id: int, day: int, is_running: int = 1):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO game_state (user_id, current_day, is_running, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (user_id, day, is_running)
    )
    conn.commit()
    conn.close()


def set_game_running(user_id: int, running: bool):
    conn = get_db()
    conn.execute(
        "UPDATE game_state SET is_running = ? WHERE user_id = ?",
        (1 if running else 0, user_id)
    )
    conn.commit()
    conn.close()


# ===== 股票价格（每个用户独立） =====

def init_stock_prices(stocks: dict, user_id: int = None):
    """初始化股票价格（可指定用户，否则从 users 表批量初始化所有用户）"""
    conn = get_db()
    if user_id is not None:
        user_ids = [user_id]
    else:
        rows = conn.execute("SELECT id FROM users").fetchall()
        user_ids = [r["id"] for r in rows]

    for uid in user_ids:
        for stock_id, info in stocks.items():
            price = info["init_price"]
            conn.execute(
                "INSERT OR IGNORE INTO stock_prices (user_id, stock_id, current_price, prev_price) VALUES (?, ?, ?, ?)",
                (uid, stock_id, price, price)
            )
    conn.commit()
    conn.close()


def get_all_prices(user_id: int) -> dict:
    conn = get_db()
    rows = conn.execute(
        "SELECT stock_id, current_price, prev_price FROM stock_prices WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    conn.close()
    return {row["stock_id"]: {"current": row["current_price"], "prev": row["prev_price"]} for row in rows}


def get_stock_price(user_id: int, stock_id: str) -> float:
    conn = get_db()
    row = conn.execute(
        "SELECT current_price FROM stock_prices WHERE user_id = ? AND stock_id = ?",
        (user_id, stock_id)
    ).fetchone()
    conn.close()
    return row["current_price"] if row else 0.0


# ===== K线数据（每个用户独立） =====

def get_kline(user_id: int, stock_id: str, limit: int = 90) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT day, open, high, low, close, volume FROM kline WHERE user_id = ? AND stock_id = ? ORDER BY day DESC LIMIT ?",
        (user_id, stock_id, limit)
    ).fetchall()
    conn.close()
    return [dict(row) for row in reversed(rows)]


# ===== 持仓 =====

def get_holdings(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT stock_id, quantity, avg_price, leverage, margin FROM holdings WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_holding(user_id: int, stock_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT stock_id, quantity, avg_price, leverage, margin FROM holdings WHERE user_id = ? AND stock_id = ?",
        (user_id, stock_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_holding(user_id: int, stock_id: str, quantity: int, avg_price: float, leverage: float, margin: float):
    conn = get_db()
    conn.execute(
        """INSERT INTO holdings (user_id, stock_id, quantity, avg_price, leverage, margin)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, stock_id) DO UPDATE SET
           quantity = ?, avg_price = ?, leverage = ?, margin = ?""",
        (user_id, stock_id, quantity, avg_price, leverage, margin,
         quantity, avg_price, leverage, margin)
    )
    conn.commit()
    conn.close()


def delete_holding(user_id: int, stock_id: str):
    conn = get_db()
    conn.execute("DELETE FROM holdings WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
    conn.commit()
    conn.close()


# ===== 交易记录 =====

def add_transaction(user_id: int, stock_id: str, txn_type: str, quantity: int,
                    price: float, leverage: float, total_amount: float, day: int):
    conn = get_db()
    conn.execute(
        """INSERT INTO transactions (user_id, stock_id, type, quantity, price, leverage, total_amount, created_at_day)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, stock_id, txn_type, quantity, price, leverage, total_amount, day)
    )
    conn.commit()
    conn.close()


def get_transactions(user_id: int, limit: int = 50) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ===== 事件日志（每个用户独立） =====

def get_all_events(user_id: int, limit: int = 50) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM event_log WHERE user_id = ? ORDER BY announced_at_day DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_active_events(user_id: int, current_day: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM event_log
           WHERE user_id = ? AND effective_day <= ? AND effective_day + duration_days > ?
           AND status = 'active'""",
        (user_id, current_day, current_day)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ===== 知识答题 =====

def get_quiz_record(user_id: int) -> dict | None:
    """获取用户答题记录"""
    conn = get_db()
    row = conn.execute(
        "SELECT score, best_score, total_attempts FROM quiz_records WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def submit_quiz_result(user_id: int, score: int) -> dict:
    """
    提交答题结果，更新最高分和现金
    奖励规则：每题正确得 5 点资金，只奖励超过历史最高分的增量部分
    """
    conn = get_db()
    record = conn.execute(
        "SELECT best_score, total_attempts FROM quiz_records WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if record:
        old_best = record["best_score"]
        total_attempts = record["total_attempts"] + 1
        if score > old_best:
            incremental_cash = (score - old_best) * 5
            conn.execute(
                "UPDATE quiz_records SET best_score = ?, total_attempts = ?, score = ?, completed_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (score, total_attempts, score, user_id)
            )
            conn.execute("UPDATE users SET cash = cash + ? WHERE id = ?", (incremental_cash, user_id))
            conn.commit()
            updated_user = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.close()
            return {
                "score": score, "best_score": score, "total_attempts": total_attempts,
                "cash_reward": incremental_cash, "new_cash": updated_user["cash"],
                "is_new_best": True,
                "message": f"恭喜刷新最高分！答对 {score}/28，新增奖励 {incremental_cash:.0f} 点资金！"
            }
        else:
            conn.execute(
                "UPDATE quiz_records SET total_attempts = ?, score = ?, completed_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (total_attempts, score, user_id)
            )
            conn.commit()
            updated_user = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.close()
            return {
                "score": score, "best_score": old_best, "total_attempts": total_attempts,
                "cash_reward": 0, "new_cash": updated_user["cash"],
                "is_new_best": False,
                "message": f"答对 {score}/28，未超过历史最高 {old_best}/28，无额外奖励。继续加油！"
            }
    else:
        cash_reward = score * 5
        conn.execute(
            "INSERT INTO quiz_records (user_id, score, best_score, total_attempts) VALUES (?, ?, ?, 1)",
            (user_id, score, score)
        )
        conn.execute("UPDATE users SET cash = cash + ? WHERE id = ?", (cash_reward, user_id))
        conn.commit()
        updated_user = conn.execute("SELECT cash FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return {
            "score": score, "best_score": score, "total_attempts": 1,
            "cash_reward": cash_reward, "new_cash": updated_user["cash"],
            "is_new_best": True,
            "message": f"首次答题！答对 {score}/28，获得 {cash_reward:.0f} 点资金奖励！"
        }


# ===== 重置 =====

def reset_game(user_id: int = None):
    """
    重置游戏数据。
    如果指定 user_id，只重置该用户；否则重置所有用户（调试用）。
    同时恢复用户资金为初始值。
    """
    conn = get_db()
    if user_id is not None:
        conn.execute("DELETE FROM kline WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM event_log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM stock_prices WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM game_state WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM quiz_records WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE users SET cash = ? WHERE id = ?", (INITIAL_CASH, user_id))

        conn.execute(
            "INSERT INTO game_state (user_id, current_day, is_running) VALUES (?, 0, 0)",
            (user_id,)
        )
        from stock_data import STOCKS
        for sid, info in STOCKS.items():
            price = info["init_price"]
            conn.execute(
                "INSERT INTO stock_prices (user_id, stock_id, current_price, prev_price) VALUES (?, ?, ?, ?)",
                (user_id, sid, price, price)
            )
            conn.execute(
                "INSERT OR IGNORE INTO kline (user_id, stock_id, day, open, high, low, close, volume) VALUES (?, ?, 0, ?, ?, ?, ?, 1000)",
                (user_id, sid, price, price, price, price)
            )
    else:
        conn.executescript("""
            DELETE FROM kline;
            DELETE FROM event_log;
            DELETE FROM transactions;
            DELETE FROM holdings;
            DELETE FROM stock_prices;
            DELETE FROM game_state;
            DELETE FROM quiz_records;
        """)
        conn.execute("UPDATE users SET cash = ?", (INITIAL_CASH,))

        user_rows = conn.execute("SELECT id FROM users").fetchall()
        from stock_data import STOCKS
        for u in user_rows:
            uid = u["id"]
            conn.execute("INSERT INTO game_state (user_id, current_day, is_running) VALUES (?, 0, 0)", (uid,))
            for sid, info in STOCKS.items():
                price = info["init_price"]
                conn.execute(
                    "INSERT INTO stock_prices (user_id, stock_id, current_price, prev_price) VALUES (?, ?, ?, ?)",
                    (uid, sid, price, price)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO kline (user_id, stock_id, day, open, high, low, close, volume) VALUES (?, ?, 0, ?, ?, ?, ?, 1000)",
                    (uid, sid, price, price, price, price)
                )

    conn.commit()
    conn.close()
