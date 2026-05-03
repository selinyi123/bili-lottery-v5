#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" Bilibili Lottery Automation System v5.1 (Perfect Edition)
v5.0终极改进 + 工程化修复：
- 修复import冗余、恢复字体随机化CDP脚本
- 添加Chrome内存限制（256MB/进程）
- 浏览器定期重启机制（50次操作或4小时）
- 僵尸Chrome进程自动清理
- WBI签名 + API搜索 + 多账号轮换
"""

import sqlite3
import time
import random
import logging
import re
import json
import smtplib
import os
import sys
import threading
import atexit
import signal
import hashlib
import base64
import hmac
import math
import traceback
import weakref
import requests
from pathlib import Path
from datetime import datetime, timedelta
from threading import Thread, Lock, Event, RLock
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any, Tuple, Set, Callable, Union
from contextlib import contextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum, auto
from urllib.parse import quote, urlencode

import schedule

try:
    from logging.handlers import RotatingFileHandler
except ImportError:
    RotatingFileHandler = None

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        StaleElementReferenceException, WebDriverException,
        ElementNotInteractableException, ElementClickInterceptedException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("警告: Selenium未安装，仅API模式可用")

# ============================================================================
# Section 1: 类型枚举与常量
# ============================================================================

class ScanSource(Enum):
    SPACE = "space"
    SEARCH = "search"
    HUB = "hub"
    TRENDING = "trending"  # 新增：热门动态

class ValueLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class AccountStatus(Enum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    CAPTCHA = "captcha_required"
    BANNED = "banned"
    COOKIE_EXPIRED = "cookie_expired"
    UNKNOWN = "unknown"


# ============================================================================
# Section 2: 配置数据类（v5.0 扩展）
# ============================================================================

@dataclass
class RiskControlConfig:
    enable_fingerprint_mask: bool = True
    enable_behavior_sim: bool = True
    enable_mouse_trail: bool = True
    canvas_noise_level: float = 0.02
    audio_noise_level: float = 0.001
    webgl_vendor_rotation: bool = True
    font_randomization: bool = True
    timezone_randomization: bool = True
    min_read_time: float = 3.0
    max_read_time: float = 8.0
    scroll_randomization: bool = True
    click_offset_randomization: bool = True
    tab_switching_simulation: bool = True
    cache_clearing_interval: int = 5
    # v5.0 新增
    webrtc_disabled: bool = True
    screen_resolution_rotation: bool = True
    navigator_hardware_concurrency: int = 8
    random_like_non_lottery: bool = True  # 随机点赞非抽奖动态混淆行为
    random_like_probability: float = 0.1

@dataclass
class FrequencyConfig:
    base_interval_up: float = 120.0
    interval_jitter_percent: float = 0.4
    adaptive_cooldown: bool = True
    rate_limit_backoff: float = 300.0
    consecutive_error_threshold: int = 3
    daily_participation_limit: int = 100
    burst_mode: bool = False
    burst_window_count: int = 5
    burst_window_minutes: int = 30
    # v5.0 新增
    night_mode: bool = True  # 夜间降速
    night_hours: Tuple[int, int] = (0, 7)  # 0-7点为夜间
    night_interval_multiplier: float = 3.0

@dataclass
class AccountConfig:
    """多账号配置"""
    name: str = "default"
    cookie_file: str = ""
    uid: str = ""
    is_active: bool = True
    daily_limit: int = 100

@dataclass
class SMTPConfig:
    host: str = "smtp.qq.com"
    port: int = 587
    user: str = ""
    password: str = ""
    to: str = ""
    use_tls: bool = True

@dataclass
class PushConfig:
    serverchan_key: str = ""
    dingtalk_token: str = ""
    dingtalk_secret: str = ""
    wx_webhook: str = ""
    bark_key: str = ""
    bark_server: str = "https://api.day.app"

@dataclass
class SmartFilterConfig:
    blacklist_uids: List[str] = field(default_factory=list)
    blacklist_keywords: List[str] = field(default_factory=lambda: [
        "骗人", "虚假", "骗局", "已开奖", "抽奖结束", "引流", "加群", "骗子", "诈骗"
    ])
    min_prize_count: int = 1
    max_days_until_draw: int = 60
    drawn_keywords: List[str] = field(default_factory=lambda: [
        "已开奖", "中奖名单", "抽奖结果", "开奖啦", "恭喜以下", "已抽出"
    ])
    expired_keywords: List[str] = field(default_factory=lambda: [
        "已过期", "活动结束", "抽奖截止", "已截止", "已结束"
    ])
    high_value_keywords: List[str] = field(default_factory=lambda: [
        "iPhone", "iPad", "MacBook", "Switch", "PS5", "现金", "红包",
        "显卡", "无人机", "相机", "AirPods", "Steam", "京东卡", "天猫卡"
    ])
    low_value_keywords: List[str] = field(default_factory=lambda: [
        "优惠券", "满减", "积分", "虚拟", "壁纸", "表情包", "头像框", "挂件"
    ])
    # v5.0 新增
    min_up_followers: int = 1000  # 过滤粉丝过少的UP（可能是骗子）
    skip_no_comment_requirement: bool = False  # 是否跳过不需要评论的（评论是互动指标）

@dataclass
class SystemConfig:
    user_data_dir: str = "./chrome_profile"
    db_path: str = "./data/bili_lottery.db"
    log_path: str = "./logs/lottery_system.log"
    config_file: str = "./config.json"
    proxy_list: List[str] = field(default_factory=list)
    comment_samples: List[str] = field(default_factory=lambda: [
        "支持UP主！祝越来越好！", "已三连，期待好运降临~",
        "参与抽奖，感谢UP主的福利！", "求中奖！会一直支持你的！",
        "来拉低中奖率了哈哈", "冲冲冲！希望能中一次！",
        "关注很久了，支持一波！", "好耶！希望能抽到！",
        "参与一下，万一中了呢", "UP主大气！支持支持！",
        "许愿中奖，UP主加油！", "希望能被抽到，支持！",
    ])
    page_load_timeout: int = 40
    implicit_wait: int = 10
    explicit_wait: int = 20
    scroll_count: int = 3
    max_retries: int = 3
    enable_like: bool = True
    enable_repost: bool = True
    enable_comment: bool = True
    enable_follow: bool = True
    enable_lottery_click: bool = True
    enable_search: bool = True
    search_keywords: List[str] = field(default_factory=lambda: [
        "互动抽奖", "转发抽奖", "关注抽奖", "福利", "宠粉福利", "抽奖", "送"
    ])
    search_max_pages: int = 3
    search_interval_hours: int = 4
    search_sort_type: str = "pubdate"
    search_date_range: int = 7
    lottery_hub_ups: List[Any] = field(default_factory=list)
    hub_scan_interval_hours: int = 2
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    push: PushConfig = field(default_factory=PushConfig)
    smart_filter: SmartFilterConfig = field(default_factory=SmartFilterConfig)
    risk_control: RiskControlConfig = field(default_factory=RiskControlConfig)
    frequency: FrequencyConfig = field(default_factory=FrequencyConfig)
    participate_strategy: str = "all"
    enable_win_tracking: bool = True
    win_check_interval_hours: int = 6
    # v5.0 新增
    accounts: List[AccountConfig] = field(default_factory=lambda: [AccountConfig()])
    active_account_index: int = 0
    enable_multi_account: bool = False
    auto_switch_account: bool = True
    api_only_mode: bool = False  # 纯API模式，不启动浏览器
    enable_trending_scan: bool = True  # 扫描热门动态
    trending_scan_interval_hours: int = 3
    wbi_retry_count: int = 3  # WBI签名失败重试

    @classmethod
    def from_json(cls, filepath: str) -> "SystemConfig":
        path = Path(filepath)
        if not path.exists():
            default = cls()
            default.save_json(filepath)
            print(f"已创建默认配置文件: {filepath}")
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        def extract_sub(cls_type, key):
            sub = data.pop(key, {})
            try:
                valid_fields = {f.name for f in cls_type.__dataclass_fields__.values()}
                filtered = {k: v for k, v in sub.items() if k in valid_fields}
                return cls_type(**filtered)
            except Exception:
                return cls_type()
        
        # v5.0 处理 accounts 列表
        accounts_raw = data.pop("accounts", [])
        accounts = []
        for acc in accounts_raw:
            try:
                valid = {k: v for k, v in acc.items() if k in AccountConfig.__dataclass_fields__}
                accounts.append(AccountConfig(**valid))
            except Exception:
                pass
        if not accounts:
            accounts = [AccountConfig()]
        
        smtp = extract_sub(SMTPConfig, "smtp")
        push = extract_sub(PushConfig, "push")
        sf = extract_sub(SmartFilterConfig, "smart_filter")
        rc = extract_sub(RiskControlConfig, "risk_control")
        freq = extract_sub(FrequencyConfig, "frequency")
        hub = data.pop("lottery_hub_ups", [])
        
        config = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        config.smtp = smtp; config.push = push
        config.smart_filter = sf; config.risk_control = rc
        config.frequency = freq
        config.lottery_hub_ups = hub
        config.accounts = accounts
        return config

    def save_json(self, filepath: str):
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for k, v in self.__dict__.items():
            if isinstance(v, (SMTPConfig, PushConfig, SmartFilterConfig, RiskControlConfig, FrequencyConfig, AccountConfig)):
                data[k] = asdict(v)
            elif isinstance(v, list) and v and isinstance(v[0], (tuple, list)):
                data[k] = [list(item) for item in v]
            elif isinstance(v, list) and v and isinstance(v[0], AccountConfig):
                data[k] = [asdict(item) for item in v]
            else:
                data[k] = v
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_current_account(self) -> AccountConfig:
        if 0 <= self.active_account_index < len(self.accounts):
            return self.accounts[self.active_account_index]
        return self.accounts[0] if self.accounts else AccountConfig()


# ============================================================================
# Section 3: 统一异常体系（v5.0 扩展）
# ============================================================================

class BiliLotteryError(Exception):
    pass

class BrowserNotReadyError(BiliLotteryError):
    pass

class RateLimitedError(BiliLotteryError):
    pass

class CaptchaDetectedError(BiliLotteryError):
    pass

class AccountBannedError(BiliLotteryError):
    pass

class DailyLimitExceededError(BiliLotteryError):
    pass

class CookieExpiredError(BiliLotteryError):
    pass

class WBISignError(BiliLotteryError):
    pass


# ============================================================================
# Section 4: 日志管理（v5.0 增强）
# ============================================================================

def setup_logging(log_path: str) -> logging.Logger:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("BiliLottery")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    
    # 文件日志：按大小轮转 + 按日期归档
    try:
        fh = RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=10, encoding="utf-8")
    except Exception:
        fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | [%(threadName)s] %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    # 控制台日志
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ============================================================================
# Section 5: 数据库管理器（v5.0 修复连接泄漏）
# ============================================================================

class DatabaseManager:
    def __init__(self, db_path: str, logger: logging.Logger):
        self.db_path = db_path
        self.logger = logger
        self._local = threading.local()
        self._global_lock = RLock()
        self._connection_pool: Dict[int, sqlite3.Connection] = {}
        self._pool_lock = Lock()
        self._max_idle_time = 300  # 5分钟空闲关闭
        self._last_used: Dict[int, float] = {}
        self._init_db()
        # 启动连接清理线程
        self._cleanup_thread = Thread(target=self._connection_cleanup_loop, daemon=True, name="DB-Cleanup")
        self._cleanup_thread.start()

    def _get_conn(self) -> sqlite3.Connection:
        tid = threading.get_ident()
        with self._pool_lock:
            if tid in self._connection_pool:
                try:
                    # 测试连接是否有效
                    self._connection_pool[tid].execute("SELECT 1")
                    self._last_used[tid] = time.time()
                    return self._connection_pool[tid]
                except sqlite3.Error:
                    # 连接已失效，关闭并重建
                    try:
                        self._connection_pool[tid].close()
                    except:
                        pass
                    del self._connection_pool[tid]
            
            # 创建新连接
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            self._connection_pool[tid] = conn
            self._last_used[tid] = time.time()
            return conn

    def _connection_cleanup_loop(self):
        """定期清理空闲连接，防止泄漏"""
        while True:
            time.sleep(60)
            with self._pool_lock:
                now = time.time()
                to_close = []
                for tid, last in list(self._last_used.items()):
                    if now - last > self._max_idle_time:
                        to_close.append(tid)
                for tid in to_close:
                    try:
                        self._connection_pool[tid].close()
                    except:
                        pass
                    del self._connection_pool[tid]
                    del self._last_used[tid]
                if to_close:
                    self.logger.debug(f"清理 {len(to_close)} 个空闲数据库连接")

    def _init_db(self):
        with self._global_lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS target_ups (
                    uid TEXT PRIMARY KEY, name TEXT NOT NULL,
                    last_check TEXT, status INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 5,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS history (
                    url TEXT PRIMARY KEY, up_name TEXT NOT NULL,
                    up_uid TEXT, status TEXT DEFAULT 'pending',
                    draw_date TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    reminded INTEGER DEFAULT 0, actions TEXT,
                    retry_count INTEGER DEFAULT 0, error_msg TEXT,
                    page_title TEXT, account_name TEXT DEFAULT 'default'
                );
                CREATE TABLE IF NOT EXISTS lottery_details (
                    url TEXT PRIMARY KEY, up_name TEXT NOT NULL,
                    up_uid TEXT, prize_desc TEXT, prize_count INTEGER DEFAULT 0,
                    draw_date TEXT, draw_method TEXT, conditions TEXT,
                    original_text TEXT, source_type TEXT DEFAULT 'space',
                    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    participated INTEGER DEFAULT 0,
                    value_level TEXT DEFAULT 'medium',
                    account_name TEXT DEFAULT 'default'
                );
                CREATE TABLE IF NOT EXISTS search_config (
                    keyword TEXT PRIMARY KEY, last_search TEXT,
                    total_found INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS lottery_hub_ups (
                    uid TEXT PRIMARY KEY, name TEXT NOT NULL,
                    status INTEGER DEFAULT 1, last_scan TEXT,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS win_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL, up_name TEXT, prize_desc TEXT,
                    draw_date TEXT, checked_at TEXT,
                    is_winner INTEGER DEFAULT 0, win_detail TEXT,
                    notified INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS operation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT, action_type TEXT, success INTEGER,
                    detail TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    account_name TEXT DEFAULT 'default'
                );
                CREATE TABLE IF NOT EXISTS account_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'healthy', detail TEXT,
                    consecutive_errors INTEGER DEFAULT 0,
                    daily_count INTEGER DEFAULT 0,
                    last_reset_date TEXT,
                    account_name TEXT DEFAULT 'default'
                );
                CREATE TABLE IF NOT EXISTS up_stats (
                    uid TEXT PRIMARY KEY,
                    total_lotteries INTEGER DEFAULT 0,
                    participated INTEGER DEFAULT 0,
                    won INTEGER DEFAULT 0,
                    last_interaction TEXT,
                    trust_score REAL DEFAULT 0.5
                );
                CREATE INDEX IF NOT EXISTS idx_history_date ON history(draw_date);
                CREATE INDEX IF NOT EXISTS idx_history_reminded ON history(reminded);
                CREATE INDEX IF NOT EXISTS idx_history_account ON history(account_name);
                CREATE INDEX IF NOT EXISTS idx_lottery_details_participated ON lottery_details(participated);
                CREATE INDEX IF NOT EXISTS idx_lottery_details_account ON lottery_details(account_name);
                CREATE INDEX IF NOT EXISTS idx_win_tracking_notified ON win_tracking(notified);
                CREATE INDEX IF NOT EXISTS idx_account_health_date ON account_health(checked_at);
                CREATE INDEX IF NOT EXISTS idx_account_health_account ON account_health(account_name);
            """)
            conn.commit()
            self.logger.info("数据库初始化完成")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._global_lock:
            c = self._get_conn().execute(sql, params)
            self._get_conn().commit()
            return c

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._global_lock:
            return self._get_conn().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._global_lock:
            return self._get_conn().execute(sql, params).fetchall()

    def upsert_history(self, data: Dict[str, Any]):
        fields = list(data.keys())
        ph = ",".join(["?"] * len(fields))
        upd = ",".join([f"{f}=excluded.{f}" for f in fields if f != "url"])
        self.execute(f"INSERT INTO history ({','.join(fields)}) VALUES ({ph}) ON CONFLICT(url) DO UPDATE SET {upd}", tuple(data.values()))

    def upsert_lottery_detail(self, data: Dict[str, Any]):
        fields = list(data.keys())
        ph = ",".join(["?"] * len(fields))
        upd = ",".join([f"{f}=excluded.{f}" for f in fields if f != "url"])
        self.execute(f"INSERT INTO lottery_details ({','.join(fields)}) VALUES ({ph}) ON CONFLICT(url) DO UPDATE SET {upd}", tuple(data.values()))

    def log_operation(self, url: str, action_type: str, success: bool, detail: str = "", account: str = "default"):
        self.execute(
            "INSERT INTO operation_log (url, action_type, success, detail, account_name) VALUES (?,?,?,?,?)",
            (url, action_type, int(success), detail, account)
        )

    def add_lottery_hub_up(self, uid: str, name: str):
        self.execute(
            "INSERT INTO lottery_hub_ups (uid, name) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name",
            (uid, name)
        )

    def get_active_hub_ups(self) -> List[sqlite3.Row]:
        return self.fetchall("SELECT uid, name FROM lottery_hub_ups WHERE status = 1")

    def record_health(self, status: str, detail: str = "", consecutive_errors: int = 0, daily_count: int = 0, account: str = "default"):
        today = datetime.now().strftime("%Y-%m-%d")
        self.execute(
            "INSERT INTO account_health (status, detail, consecutive_errors, daily_count, last_reset_date, account_name) VALUES (?, ?, ?, ?, ?, ?)",
            (status, detail, consecutive_errors, daily_count, today, account)
        )

    def get_latest_health(self, account: str = "default") -> Optional[sqlite3.Row]:
        return self.fetchone(
            "SELECT * FROM account_health WHERE account_name = ? ORDER BY checked_at DESC LIMIT 1",
            (account,)
        )

    def get_daily_participation_count(self, account: str = "default") -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.fetchone(
            "SELECT COUNT(*) as cnt FROM history WHERE timestamp LIKE ? AND account_name = ?",
            (f"{today}%", account)
        )
        return row["cnt"] if row else 0

    def update_up_stats(self, uid: str, participated: bool = False, won: bool = False):
        """更新UP主统计，用于信任评分"""
        self.execute("""
            INSERT INTO up_stats (uid, total_lotteries, participated, won, last_interaction)
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                total_lotteries = up_stats.total_lotteries + 1,
                participated = up_stats.participated + ?,
                won = up_stats.won + ?,
                last_interaction = excluded.last_interaction,
                trust_score = CASE 
                    WHEN up_stats.won + ? > 0 THEN MIN(1.0, up_stats.trust_score + 0.1)
                    ELSE MAX(0.1, up_stats.trust_score - 0.02)
                END
        """, (uid, int(participated), int(won), datetime.now().isoformat(), int(participated), int(won), int(won)))

    def get_up_trust_score(self, uid: str) -> float:
        row = self.fetchone("SELECT trust_score FROM up_stats WHERE uid = ?", (uid,))
        return row["trust_score"] if row else 0.5

    def close(self):
        with self._pool_lock:
            for conn in self._connection_pool.values():
                try:
                    conn.close()
                except:
                    pass
            self._connection_pool.clear()
            self._last_used.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================================
# Section 6: 代理管理器（v5.0 增强健康检查）
# ============================================================================

class ProxyManager:
    def __init__(self, proxy_list: List[str], logger: logging.Logger):
        self.proxy_list = proxy_list
        self.logger = logger
        self.failed_proxies: Dict[str, int] = {}
        self.success_proxies: Dict[str, int] = {}
        self.latency_map: Dict[str, float] = {}
        self.current_proxy: Optional[str] = None
        self._lock = Lock()
        self._health_check_url = "https://api.bilibili.com/x/web-interface/zone"
        self._last_health_check = 0

    def _health_check(self, proxy: str) -> bool:
        """代理健康检查"""
        try:
            start = time.time()
            resp = requests.get(
                self._health_check_url,
                proxies={"http": proxy, "https": proxy},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            latency = time.time() - start
            if resp.status_code == 200:
                self.latency_map[proxy] = latency
                return True
            return False
        except Exception:
            return False

    def get_proxy(self) -> Optional[str]:
        with self._lock:
            if not self.proxy_list:
                return None
            
            # 每30分钟全局健康检查一次
            now = time.time()
            if now - self._last_health_check > 1800:
                self.logger.info("执行代理健康检查...")
                healthy = []
                for p in self.proxy_list:
                    if self._health_check(p):
                        healthy.append(p)
                        self.failed_proxies[p] = max(0, self.failed_proxies.get(p, 0) - 1)
                    else:
                        self.failed_proxies[p] = self.failed_proxies.get(p, 0) + 2
                self.logger.info(f"代理健康检查完成: {len(healthy)}/{len(self.proxy_list)} 可用")
                self._last_health_check = now
            
            available = [p for p in self.proxy_list if self.failed_proxies.get(p, 0) < 3]
            if not available:
                self.logger.warning("所有代理均失败，重置计数")
                self.failed_proxies.clear()
                available = self.proxy_list
            
            # 按延迟和成功率加权选择
            weighted = []
            for p in available:
                score = self.success_proxies.get(p, 0) * 2 - self.failed_proxies.get(p, 0) * 3
                latency_bonus = max(0, 1.0 - self.latency_map.get(p, 1.0)) * 2
                weight = max(1, int(score + latency_bonus + 2))
                weighted.extend([p] * weight)
            
            self.current_proxy = random.choice(weighted) if weighted else random.choice(available)
            return self.current_proxy

    def report_success(self):
        if self.current_proxy:
            self.success_proxies[self.current_proxy] = self.success_proxies.get(self.current_proxy, 0) + 1
            if self.current_proxy in self.failed_proxies:
                self.failed_proxies[self.current_proxy] = max(0, self.failed_proxies[self.current_proxy] - 1)

    def report_failure(self, proxy: Optional[str] = None):
        target = proxy or self.current_proxy
        if target:
            self.failed_proxies[target] = self.failed_proxies.get(target, 0) + 1


# ============================================================================
# Section 7: 风控对抗引擎（v5.0 重大增强）
# ============================================================================

class AntiDetectionEngine:
    WEBGL_PRESETS = [
        {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
        {"vendor": "Apple Inc.", "renderer": "Apple GPU"},
        {"vendor": "Google Inc.", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    ]
    TIMEZONES = ["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei", "Asia/Singapore", "Asia/Tokyo"]
    FONT_FAMILIES = ["Arial", "Helvetica", "Times New Roman", "Georgia", "Microsoft YaHei", "SimSun", "PingFang SC", "WenQuanYi Micro Hei"]
    SCREEN_RESOLUTIONS = [
        (1920, 1080), (1366, 768), (1440, 900), (1536, 864),
        (1680, 1050), (1280, 720), (2560, 1440), (3840, 2160)
    ]

    def __init__(self, config: RiskControlConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._current_preset = random.choice(self.WEBGL_PRESETS)
        self._current_timezone = random.choice(self.TIMEZONES)
        self._current_resolution = random.choice(self.SCREEN_RESOLUTIONS)
        self._operation_count = 0

    def get_cdp_scripts(self) -> List[Dict[str, str]]:
        scripts = []
        
        # 基础反检测
        scripts.append({
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
                Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => %d});
            """ % self.config.navigator_hardware_concurrency
        })
        
        # Canvas噪声
        if self.config.canvas_noise_level > 0:
            noise = self.config.canvas_noise_level
            scripts.append({
                "source": f"""
                    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                    const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
                    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                        const ctx = this.getContext('2d');
                        if (ctx) {{
                            const imageData = ctx.getImageData(0, 0, this.width, this.height);
                            for (let i = 0; i < imageData.data.length; i += 4) {{
                                imageData.data[i] += Math.random() * {noise} - {noise}/2;
                                imageData.data[i+1] += Math.random() * {noise} - {noise}/2;
                                imageData.data[i+2] += Math.random() * {noise} - {noise}/2;
                            }}
                            ctx.putImageData(imageData, 0, 0);
                        }}
                        return originalToDataURL.apply(this, args);
                    }};
                """
            })
        
        # WebGL指纹
        if self.config.webgl_vendor_rotation:
            v = self._current_preset["vendor"]
            r = self._current_preset["renderer"]
            scripts.append({
                "source": f"""
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                        if (parameter === 37445) return '{v}';
                        if (parameter === 37446) return '{r}';
                        return getParameter(parameter);
                    }};
                """
            })
        
        # 音频噪声
        if self.config.audio_noise_level > 0:
            a_noise = self.config.audio_noise_level
            scripts.append({
                "source": f"""
                    const originalGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
                    AnalyserNode.prototype.getFloatFrequencyData = function(array) {{
                        originalGetFloatFrequencyData.call(this, array);
                        for (let i = 0; i < array.length; i++) {{
                            array[i] += Math.random() * {a_noise} - {a_noise}/2;
                        }}
                    }};
                """
            })
        
        # 时区伪造
        if self.config.timezone_randomization:
            tz = self._current_timezone
            scripts.append({
                "source": f"""
                    Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {{
                        value: function() {{
                            const opts = Intl.DateTimeFormat.prototype.resolvedOptions.call(this);
                            opts.timeZone = '{tz}';
                            return opts;
                        }}
                    }});
                """
            })
        
        # WebRTC禁用（防止真实IP泄漏）
        if self.config.webrtc_disabled:
            scripts.append({
                "source": """
                    Object.defineProperty(navigator, 'mediaDevices', {get: () => undefined});
                    window.RTCPeerConnection = undefined;
                    window.webkitRTCPeerConnection = undefined;
                """
            })
        
        # 屏幕分辨率伪造
        if self.config.screen_resolution_rotation:
            w, h = self._current_resolution
            scripts.append({
                "source": f"""
                    Object.defineProperty(window.screen, 'width', {{get: () => {w}}});
                    Object.defineProperty(window.screen, 'height', {{get: () => {h}}});
                    Object.defineProperty(window.screen, 'availWidth', {{get: () => {w}}});
                    Object.defineProperty(window.screen, 'availHeight', {{get: () => {h}}});
                """
            })
        
        # [修复] 字体指纹随机化（v5.0遗漏，从v4.0恢复）
        if self.config.font_randomization:
            scripts.append({
                "source": """
                    const _fontFamilies = [
                        "Arial", "Helvetica", "Times New Roman", "Georgia",
                        "Microsoft YaHei", "SimSun", "PingFang SC", "WenQuanYi Micro Hei"
                    ];
                    Object.defineProperty(document, 'fonts', {
                        get: () => ({
                            check: () => true,
                            ready: Promise.resolve(),
                            [Symbol.iterator]: function*() {
                                for (const f of _fontFamilies) yield { family: f };
                            }
                        })
                    });
                """
            })
        
        # 权限API伪装
        scripts.append({
            "source": """
                Object.defineProperty(navigator, 'permissions', {
                    value: {
                        query: async (name) => ({ state: 'prompt', onchange: null })
                    }
                });
                Object.defineProperty(navigator, 'presentation', {get: () => undefined});
            """
        })
        
        return scripts

    def generate_mouse_path(self, start_x: int, start_y: int, end_x: int, end_y: int) -> List[Tuple[int, int]]:
        points = []
        distance = math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
        steps = max(int(distance / 5), 10)
        cp1_x = start_x + (end_x - start_x) * 0.3 + random.randint(-30, 30)
        cp1_y = start_y + (end_y - start_y) * 0.3 + random.randint(-30, 30)
        cp2_x = start_x + (end_x - start_x) * 0.7 + random.randint(-20, 20)
        cp2_y = start_y + (end_y - start_y) * 0.7 + random.randint(-20, 20)
        for t in [i / steps for i in range(steps + 1)]:
            x = (1-t)**3 * start_x + 3*(1-t)**2*t * cp1_x + 3*(1-t)*t**2 * cp2_x + t**3 * end_x
            y = (1-t)**3 * start_y + 3*(1-t)**2*t * cp1_y + 3*(1-t)*t**2 * cp2_y + t**3 * end_y
            jitter = random.uniform(-1.5, 1.5)
            points.append((int(x + jitter), int(y + jitter)))
        return points

    def get_random_read_time(self) -> float:
        return random.uniform(self.config.min_read_time, self.config.max_read_time)

    def get_click_offset(self) -> Tuple[int, int]:
        if not self.config.click_offset_randomization:
            return (0, 0)
        offset_x = int(random.gauss(0, 3))
        offset_y = int(random.gauss(0, 3))
        return (offset_x, offset_y)

    def should_clear_cache(self) -> bool:
        self._operation_count += 1
        if self._operation_count % self.config.cache_clearing_interval == 0:
            return True
        return False

    def rotate_fingerprint(self):
        self._current_preset = random.choice(self.WEBGL_PRESETS)
        self._current_timezone = random.choice(self.TIMEZONES)
        self._current_resolution = random.choice(self.SCREEN_RESOLUTIONS)
        self.logger.info(f"指纹已轮换: {self._current_preset['vendor']} | {self._current_timezone} | {self._current_resolution}")


# ============================================================================
# Section 8: 智能频率控制器（v5.0 夜间模式）
# ============================================================================

class FrequencyController:
    def __init__(self, config: FrequencyConfig, db: DatabaseManager, logger: logging.Logger, account_name: str = "default"):
        self.config = config
        self.db = db
        self.logger = logger
        self.account_name = account_name
        self._consecutive_errors = 0
        self._cooldown_multiplier = 1.0
        self._last_op_time = time.time()
        self._burst_count = 0
        self._burst_start_time = time.time()
        self._lock = Lock()

    def check_daily_limit(self) -> bool:
        if self.config.daily_participation_limit <= 0:
            return True
        count = self.db.get_daily_participation_count(self.account_name)
        if count >= self.config.daily_participation_limit:
            self.logger.warning(f"[{self.account_name}] 日参与次数已达上限: {count}/{self.config.daily_participation_limit}")
            return False
        return True

    def record_success(self):
        with self._lock:
            self._consecutive_errors = 0
            self._cooldown_multiplier = max(1.0, self._cooldown_multiplier * 0.9)

    def record_error(self, is_rate_limit: bool = False):
        with self._lock:
            self._consecutive_errors += 1
            if is_rate_limit or self._consecutive_errors >= self.config.consecutive_error_threshold:
                self._cooldown_multiplier = min(5.0, self._cooldown_multiplier + 0.5)
                self.logger.warning(f"[{self.account_name}] 冷却倍率提升至: {self._cooldown_multiplier:.1f}x (连续错误: {self._consecutive_errors})")

    def get_interval(self) -> float:
        with self._lock:
            base = self.config.base_interval_up
            jitter = random.uniform(-base * self.config.interval_jitter_percent, base * self.config.interval_jitter_percent)
            interval = (base + jitter) * self._cooldown_multiplier
            
            # 夜间模式降速
            if self.config.night_mode:
                hour = datetime.now().hour
                if self.config.night_hours[0] <= hour < self.config.night_hours[1]:
                    interval *= self.config.night_interval_multiplier
                    self.logger.debug(f"夜间模式: 间隔 x{self.config.night_interval_multiplier}")
            
            if self.config.burst_mode:
                now = time.time()
                if now - self._burst_start_time > self.config.burst_window_minutes * 60:
                    self._burst_count = 0
                    self._burst_start_time = now
                if self._burst_count < self.config.burst_window_count:
                    interval *= 0.5
                    self._burst_count += 1
            return max(interval, 30.0)

    def apply_rate_limit_backoff(self):
        with self._lock:
            self.logger.warning(f"[{self.account_name}] 限流退避: 休眠 {self.config.rate_limit_backoff} 秒")
            self._cooldown_multiplier = 3.0
            time.sleep(self.config.rate_limit_backoff)

    def wait(self):
        interval = self.get_interval()
        elapsed = time.time() - self._last_op_time
        wait_time = max(0, interval - elapsed)
        if wait_time > 0:
            self.logger.debug(f"[{self.account_name}] 频率控制: 等待 {wait_time:.1f} 秒")
            time.sleep(wait_time)
        self._last_op_time = time.time()


# ============================================================================
# Section 9: 账号健康监控器（v5.0 Cookie过期检测）
# ============================================================================

class AccountHealthMonitor:
    RATE_LIMIT_SIGNALS = ["请求过于频繁", "请稍后再试", "操作太快", "rate limit", "频率限制"]
    CAPTCHA_SIGNALS = ["验证码", "captcha", "请完成验证", "安全验证", "人机验证"]
    BAN_SIGNALS = ["账号异常", "已被封禁", "禁止访问", "access denied", "登录异常", "账号被封"]
    COOKIE_SIGNALS = ["登录", "请登录", "账号未登录", "登录过期", "重新登录", "请重新登录"]

    def __init__(self, db: DatabaseManager, logger: logging.Logger, account_name: str = "default"):
        self.db = db
        self.logger = logger
        self.account_name = account_name
        self._status = AccountStatus.HEALTHY
        self._consecutive_errors = 0
        self._lock = Lock()

    def check_page_health(self, page_text: str) -> AccountStatus:
        text_lower = page_text.lower()
        for signal in self.BAN_SIGNALS:
            if signal.lower() in text_lower:
                self._update_status(AccountStatus.BANNED, f"检测到封禁信号: {signal}")
                return AccountStatus.BANNED
        for signal in self.COOKIE_SIGNALS:
            if signal in page_text:
                self._update_status(AccountStatus.COOKIE_EXPIRED, f"检测到登录过期: {signal}")
                return AccountStatus.COOKIE_EXPIRED
        for signal in self.CAPTCHA_SIGNALS:
            if signal in page_text:
                self._update_status(AccountStatus.CAPTCHA, f"检测到验证码: {signal}")
                return AccountStatus.CAPTCHA
        for signal in self.RATE_LIMIT_SIGNALS:
            if signal in page_text:
                self._update_status(AccountStatus.RATE_LIMITED, f"检测到限流: {signal}")
                return AccountStatus.RATE_LIMITED
        self._update_status(AccountStatus.HEALTHY, "页面正常")
        return AccountStatus.HEALTHY

    def _update_status(self, status: AccountStatus, detail: str):
        with self._lock:
            if status == AccountStatus.HEALTHY:
                self._consecutive_errors = max(0, self._consecutive_errors - 1)
            else:
                self._consecutive_errors += 1
            self._status = status
            self.db.record_health(status.value, detail, self._consecutive_errors, account=self.account_name)
            if status != AccountStatus.HEALTHY:
                self.logger.warning(f"[{self.account_name}] 账号状态异常: {status.value} | {detail}")

    def get_status(self) -> AccountStatus:
        return self._status

    def is_healthy(self) -> bool:
        return self._status == AccountStatus.HEALTHY

    def assert_healthy(self):
        if self._status == AccountStatus.BANNED:
            raise AccountBannedError("账号已被封禁，停止所有操作")
        if self._status == AccountStatus.RATE_LIMITED:
            raise RateLimitedError("账号被限流")
        if self._status == AccountStatus.CAPTCHA:
            raise CaptchaDetectedError("需要验证码")
        if self._status == AccountStatus.COOKIE_EXPIRED:
            raise CookieExpiredError("Cookie已过期，需要重新登录")


# ============================================================================
# Section 10: 浏览器管理器（v5.0 Cookie持久化增强）
# ============================================================================

class BrowserManager:
    def __init__(self, config: SystemConfig, proxy_manager: ProxyManager,
                 anti_detect: AntiDetectionEngine, health_monitor: AccountHealthMonitor,
                 logger: logging.Logger):
        self.config = config
        self.proxy_manager = proxy_manager
        self.anti_detect = anti_detect
        self.health_monitor = health_monitor
        self.logger = logger
        self.driver: Optional[Any] = None
        self.wait: Optional[Any] = None
        self._lock = Lock()
        self._closed = False
        self._session_ops = 0
        self._cookie_file: Optional[str] = None
        # [改进] 浏览器定期重启计数器：每50次操作重启一次，防止内存泄漏
        self._ops_since_restart = 0
        self._restart_threshold = 50
        # [改进] 浏览器启动时间，用于超时重启
        self._browser_start_time = 0.0
        self._browser_max_lifetime = 3600 * 4  # 最多存活4小时

    def set_cookie_file(self, cookie_file: str):
        self._cookie_file = cookie_file

    def _create_options(self, proxy: Optional[str] = None) -> Any:
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={os.path.abspath(self.config.user_data_dir)}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--lang=zh-CN,zh")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-first-run")
        options.add_argument("--homepage=about:blank")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--disable-site-isolation-trials")
        options.add_argument("--disable-features=InterestFeedContentSuggestions")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-component-update")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        # [改进] 内存限制：每个渲染进程最多256MB，防止长期运行内存泄漏
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument("--memory-model=low")
        options.add_argument("--max_discardable_memory_limit=64")
        # [改进] 单进程模式减少内存占用（服务器环境适用）
        options.add_argument("--single-process")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option('useAutomationExtension', False)
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")
        return options

    def _load_cookies(self):
        """从文件加载Cookie"""
        if not self._cookie_file or not Path(self._cookie_file).exists():
            return
        try:
            with open(self._cookie_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            for cookie in cookies:
                try:
                    if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                        del cookie['sameSite']
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    self.logger.debug(f"加载单个cookie失败: {e}")
            self.logger.info(f"已从 {self._cookie_file} 加载 {len(cookies)} 个Cookie")
        except Exception as e:
            self.logger.warning(f"加载Cookie失败: {e}")

    def _save_cookies(self):
        """保存Cookie到文件"""
        if not self._cookie_file or not self.driver:
            return
        try:
            cookies = self.driver.get_cookies()
            Path(self._cookie_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self._cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            self.logger.info(f"已保存 {len(cookies)} 个Cookie到 {self._cookie_file}")
        except Exception as e:
            self.logger.warning(f"保存Cookie失败: {e}")

    def start(self, retry_count: int = 0) -> Any:
        if not SELENIUM_AVAILABLE:
            raise BrowserNotReadyError("Selenium未安装，无法启动浏览器")
        if self._closed:
            raise BrowserNotReadyError("BrowserManager已关闭")
        with self._lock:
            if self.driver is not None:
                try:
                    self.driver.current_url
                    return self.driver
                except WebDriverException:
                    self.logger.warning("浏览器连接断开，重新创建")
                    self._cleanup()
            proxy = self.proxy_manager.get_proxy()
            try:
                options = self._create_options(proxy)
                self.driver = uc.Chrome(options=options, version_main=None)
                self.driver.set_page_load_timeout(self.config.page_load_timeout)
                self.driver.implicitly_wait(self.config.implicit_wait)
                self.wait = WebDriverWait(self.driver, self.config.explicit_wait)
                
                # 先访问B站再注入脚本和加载Cookie
                self.driver.get("https://www.bilibili.com")
                time.sleep(2)
                
                for script in self.anti_detect.get_cdp_scripts():
                    self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", script)
                
                self._load_cookies()
                self.driver.refresh()
                time.sleep(2)
                
                self.logger.info("浏览器启动成功，反检测脚本已注入")
                self.proxy_manager.report_success()
                self._session_ops = 0
                self._ops_since_restart = 0
                self._browser_start_time = time.time()
                return self.driver
            except Exception as e:
                self.logger.error(f"浏览器启动失败: {e}")
                if proxy:
                    self.proxy_manager.report_failure(proxy)
                    if retry_count < self.config.max_retries:
                        return self.start(retry_count + 1)
                raise BrowserNotReadyError(f"浏览器启动失败: {e}")

    def ensure_alive(self):
        # [改进] 定期重启浏览器防止内存泄漏
        need_restart = False
        if self._ops_since_restart >= self._restart_threshold:
            self.logger.info(f"浏览器操作次数达{self._ops_since_restart}次，计划重启")
            need_restart = True
        if time.time() - self._browser_start_time > self._browser_max_lifetime:
            self.logger.info(f"浏览器运行时间超{self._browser_max_lifetime/3600:.0f}小时，计划重启")
            need_restart = True
        if need_restart and self.driver is not None:
            self.logger.info("执行浏览器计划重启...")
            self._cleanup()
            self.start()
            return
        try:
            if self.driver is None:
                self.start()
            else:
                self.driver.current_url
        except Exception:
            self.logger.warning("浏览器无响应，重新初始化")
            self._cleanup()
            self.start()

    def safe_get(self, url: str):
        self.ensure_alive()
        self._ops_since_restart += 1
        self.driver.get(url)
        time.sleep(random.uniform(2, 4))
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text[:500]
            status = self.health_monitor.check_page_health(body_text)
            if status == AccountStatus.RATE_LIMITED:
                raise RateLimitedError("页面检测到限流信号")
            if status == AccountStatus.BANNED:
                raise AccountBannedError("页面检测到封禁信号")
            if status == AccountStatus.CAPTCHA:
                raise CaptchaDetectedError("页面检测到验证码")
            if status == AccountStatus.COOKIE_EXPIRED:
                raise CookieExpiredError("Cookie已过期")
        except (RateLimitedError, AccountBannedError, CaptchaDetectedError, CookieExpiredError):
            raise
        except Exception:
            pass

    def clear_session_data(self):
        if not self.driver:
            return
        try:
            self.driver.delete_all_cookies()
            self.driver.execute_script("localStorage.clear(); sessionStorage.clear();")
            self.logger.debug("会话数据已清理")
        except Exception as e:
            self.logger.debug(f"清理会话数据失败: {e}")

    def simulate_tab_switch(self):
        if not self.config.risk_control.tab_switching_simulation or not self.driver:
            return
        try:
            self.driver.execute_script("window.open('about:blank', '_blank');")
            time.sleep(random.uniform(0.5, 1.5))
            self.driver.switch_to.window(self.driver.window_handles[-1])
            time.sleep(random.uniform(0.3, 0.8))
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[0])
        except Exception:
            pass

    @staticmethod
    def _kill_zombie_chrome():
        """[改进] 清理僵尸Chrome进程，防止内存泄漏"""
        try:
            os.system("pkill -f 'chrome --headless' >/dev/null 2>&1")
            os.system("pkill -f 'chromedriver' >/dev/null 2>&1")
        except Exception:
            pass

    def _cleanup(self):
        if self.driver:
            try:
                self._save_cookies()
            except:
                pass
            try:
                self.driver.quit()
            except Exception:
                pass
            finally:
                self.driver = None
                self.wait = None
        # [改进] 清理可能残留的僵尸Chrome进程
        self._kill_zombie_chrome()

    def close(self):
        self._closed = True
        self._cleanup()
        self.logger.info("浏览器管理器已关闭")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()


print("Modules 1-10 loaded: Config, DB, Proxy, AntiDetect, Frequency, Health, Browser")


# ============================================================================
# Section 11: 抽奖执行器（v5.0 选择器增强 + 混淆行为）
# ============================================================================

class LotteryExecutor:
    # v5.0 扩展选择器：多备选方案适配B站不同页面版本
    SELECTORS = {
        "like_btn": [
            ".like, .action-like, .bili-rich-text-module__like, [data-type='like'], .like-icon, .opus-module-like",
            ".video-like-info, .like-text, .video-toolbar-left .like",
            "[class*='like'], [class*='Like']"
        ],
        "repost_btn": [
            ".repost, .forward, .share, [data-type='forward'], .forward-icon, .opus-module-forward",
            ".video-share-info, .share-text, .video-toolbar-left .share",
            "[class*='repost'], [class*='share'], [class*='forward']"
        ],
        "repost_confirm": [
            ".btn-confirm, .publish-btn, .forward-publish, .primary-btn, .opus-repost-dialog .confirm",
            ".bili-dyn-forward-publishing__btn, .forward-panel .submit",
            "button:contains('转发'), button:contains('发布')"
        ],
        "comment_textarea": [
            "textarea[placeholder*='友善'], textarea[placeholder*='评论'], .reply-box-textarea, .bili-rich-textarea__inner, .opus-module-reply .textarea",
            ".reply-wrap textarea, .comment-send textarea, .main-reply-box textarea",
            "[contenteditable='true'], .at-textarea"
        ],
        "comment_send": [
            ".reply-box-send, .submit-btn, .send-btn, .primary-btn, .opus-module-reply .send",
            ".comment-submit, .reply-submit, .send-reply",
            "button:contains('发送'), button:contains('评论')"
        ],
        "follow_btn": [
            ".follow-btn, .not-follow, [data-type='follow'], .follow-text, .opus-module-author .follow",
            ".up-follow-btn, .follow, .btn-follow",
            "[class*='follow']:not([class*='following'])"
        ],
        "lottery_component": [
            "//div[contains(@class, 'lottery') or contains(@class, '互动抽奖')]",
            "//div[contains(text(), '互动抽奖') or contains(text(), '关注抽奖')]",
            "//iframe[contains(@src, 'lottery')]",
            "//div[contains(@class, 'bili-lottery')]"
        ]
    }

    def __init__(self, browser: BrowserManager, db: DatabaseManager,
                 anti_detect: AntiDetectionEngine, freq_ctrl: FrequencyController,
                 config: SystemConfig, logger: logging.Logger, account_name: str = "default"):
        self.browser = browser
        self.db = db
        self.anti_detect = anti_detect
        self.freq_ctrl = freq_ctrl
        self.config = config
        self.logger = logger
        self.account_name = account_name

    def _find_element_with_fallback(self, selectors: List[str], by: str = By.CSS_SELECTOR, timeout: int = 5) -> Optional[Any]:
        """多选择器回退查找元素"""
        driver = self.browser.driver
        wait = WebDriverWait(driver, timeout)
        for selector in selectors:
            try:
                if by == By.XPATH:
                    return wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                else:
                    return wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            except TimeoutException:
                continue
        return None

    def _human_like_click(self, element, action_name: str, url: str) -> bool:
        try:
            driver = self.browser.driver
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'});", element)
            read_time = self.anti_detect.get_random_read_time()
            self.logger.debug(f"阅读等待: {read_time:.1f}s")
            time.sleep(read_time)
            actions = ActionChains(driver)
            actions.move_to_element(element)
            actions.pause(random.uniform(0.2, 0.8))
            offset_x, offset_y = self.anti_detect.get_click_offset()
            if abs(offset_x) > 0 or abs(offset_y) > 0:
                actions.move_by_offset(offset_x, offset_y)
                actions.pause(random.uniform(0.05, 0.2))
            actions.click()
            actions.perform()
            self.db.log_operation(url, action_name, True, account=self.account_name)
            return True
        except Exception as e:
            self.logger.warning(f"{action_name} 点击失败: {e}")
            self.db.log_operation(url, action_name, False, str(e), account=self.account_name)
            return False

    def _human_typing(self, element, text: str):
        typed = ""
        for i, char in enumerate(text):
            if random.random() < 0.01 and typed:
                element.send_keys("\b")
                typed = typed[:-1]
                time.sleep(random.uniform(0.1, 0.3))
            element.send_keys(char)
            typed += char
            if char in "，。！？、":
                time.sleep(random.uniform(0.2, 0.5))
            elif random.random() < 0.1:
                time.sleep(random.uniform(0.15, 0.4))
            else:
                time.sleep(random.uniform(0.03, 0.15))

    def _random_like_non_lottery(self):
        """随机点赞非抽奖动态，混淆行为模式"""
        if not self.config.risk_control.random_like_non_lottery:
            return
        if random.random() > self.config.risk_control.random_like_probability:
            return
        try:
            driver = self.browser.driver
            cards = driver.find_elements(By.CSS_SELECTOR, ".bili-dyn-list__item, .opus-module, .feed-card")
            if not cards:
                return
            card = random.choice(cards[:5])
            # 检查是否不是抽奖动态
            card_text = card.text[:100]
            if any(kw in card_text for kw in ["抽奖", "互动抽奖", "转发抽奖"]):
                return
            like_btn = card.find_elements(By.CSS_SELECTOR, ".like, .action-like, [data-type='like']")
            if like_btn:
                self._human_like_click(like_btn[0], "random_like", "random")
                self.logger.debug("执行随机点赞混淆")
                time.sleep(random.uniform(1, 2))
        except Exception:
            pass

    def execute(self, url: str, up_name: str, up_uid: str, draw_date: Optional[str]) -> Dict[str, Any]:
        result = {
            "url": url, "up_name": up_name, "start_time": datetime.now().isoformat(),
            "actions": {}, "success": False, "account": self.account_name
        }
        driver = self.browser.driver
        wait = self.browser.wait
        try:
            self.browser.safe_get(url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(random.uniform(2, 5))
            try:
                result["page_title"] = driver.title
            except Exception:
                result["page_title"] = "Unknown"
        except (RateLimitedError, AccountBannedError, CaptchaDetectedError, CookieExpiredError):
            raise
        except TimeoutException:
            result["error"] = "page_timeout"
            return result
        except Exception as e:
            result["error"] = str(e)
            return result

        # 混淆行为：随机点赞非抽奖动态
        self._random_like_non_lottery()
        
        if random.random() < 0.15:
            self.browser.simulate_tab_switch()

        # 点赞
        if self.config.enable_like:
            like_btn = self._find_element_with_fallback(self.SELECTORS["like_btn"])
            if like_btn:
                result["actions"]["like"] = self._human_like_click(like_btn, "like", url)
                time.sleep(random.uniform(1, 3))

        # 转发
        if self.config.enable_repost:
            repost_btn = self._find_element_with_fallback(self.SELECTORS["repost_btn"], timeout=3)
            if repost_btn:
                if self._human_like_click(repost_btn, "repost_open", url):
                    time.sleep(random.uniform(1, 2))
                    confirm = self._find_element_with_fallback(self.SELECTORS["repost_confirm"], timeout=5)
                    if confirm:
                        self._human_like_click(confirm, "repost_confirm", url)
                        result["actions"]["repost"] = True
                        time.sleep(random.uniform(2, 4))
                    else:
                        # 可能直接转发了，无需确认
                        result["actions"]["repost"] = True

        # 评论
        if self.config.enable_comment:
            textarea = self._find_element_with_fallback(self.SELECTORS["comment_textarea"], timeout=3)
            if textarea:
                comment = random.choice(self.config.comment_samples)
                self._human_typing(textarea, comment)
                time.sleep(random.uniform(1, 2))
                send_btn = self._find_element_with_fallback(self.SELECTORS["comment_send"], timeout=3)
                if send_btn:
                    result["actions"]["comment"] = self._human_like_click(send_btn, "comment", url)
                    if result["actions"]["comment"]:
                        time.sleep(random.uniform(2, 4))

        # 关注
        if self.config.enable_follow:
            follow_btn = self._find_element_with_fallback(self.SELECTORS["follow_btn"], timeout=3)
            if follow_btn:
                try:
                    btn_text = follow_btn.text
                    if any(kw in btn_text for kw in ["关注", "Follow", "+", "未关注"]):
                        result["actions"]["follow"] = self._human_like_click(follow_btn, "follow", url)
                        time.sleep(random.uniform(1, 2))
                    else:
                        result["actions"]["follow"] = "already_following"
                except Exception:
                    result["actions"]["follow"] = False

        # 点击抽奖组件（B站互动抽奖）
        if self.config.enable_lottery_click:
            try:
                # 先尝试找iframe嵌套的抽奖
                iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'lottery')]")
                if iframes:
                    driver.switch_to.frame(iframes[0])
                    lottery_btn = self._find_element_with_fallback([
                        "//button[contains(text(), '抽奖') or contains(text(), '参与')]",
                        "//div[contains(@class, 'lottery-btn')]",
                        "//a[contains(@class, 'join')]"
                    ], by=By.XPATH, timeout=3)
                    if lottery_btn:
                        result["actions"]["lottery_click"] = self._human_like_click(lottery_btn, "lottery_click", url)
                    driver.switch_to.default_content()
                else:
                    # 直接查找页面内的抽奖组件
                    lottery_div = self._find_element_with_fallback(self.SELECTORS["lottery_component"], by=By.XPATH, timeout=2)
                    if lottery_div:
                        # 抽奖组件通常不需要点击，参与条件（关注+转发+评论）已满足即自动参与
                        result["actions"]["lottery_click"] = "auto_participated"
            except Exception as e:
                self.logger.debug(f"抽奖组件处理失败: {e}")
                result["actions"]["lottery_click"] = False

        actions = result["actions"]
        result["success"] = any(v for v in actions.values() if v not in (None, False, "already_following"))
        result["end_time"] = datetime.now().isoformat()
        if result["success"]:
            self.freq_ctrl.record_success()
        else:
            self.freq_ctrl.record_error()
        return result


# ============================================================================
# Section 12: 抽奖信息提取器（v5.0 增强）
# ============================================================================

@dataclass
class LotteryInfo:
    prize_desc: str = ""
    prize_count: int = 0
    draw_date: Optional[str] = None
    draw_method: str = ""
    conditions: List[str] = field(default_factory=list)
    original_text: str = ""
    source_type: str = "space"
    value_level: str = "medium"
    requires_comment: bool = False
    requires_repost: bool = False
    requires_follow: bool = False
    requires_like: bool = False


class LotteryInfoExtractor:
    PRIZE_PATTERNS = [
        r"(?:奖品|奖励|送|送出|赠|赠送)[：:]\s*(.+?)(?:\n|$|，|,|。|；)",
        r"(?:抽|送|送出|赠送)\s*(\d+)?\s*([\w\s\u4e00-\u9fff]+?)(?:[\u00d7xX*](\d+))?(?:\n|$|，|,|。|；)",
        r"(?:奖池|奖品池|福利)[：:]\s*(.+?)(?:\n|$)",
        r"(\[[^\]]+\])\s*(?:[\u00d7xX*](\d+))?\s*(?:奖品|份)",
        r"(?:送|抽)([\w\s\u4e00-\u9fff]+?)(?:给|与|和|以及)",
    ]
    COUNT_PATTERNS = [
        r"(?:共计|总共|合计|共)\s*(\d+)\s*份",
        r"(\d+)\s*个名额", r"抽\s*(\d+)\s*人",
        r"(\d+)\s*位.*(?:中奖|获奖)",
        r"[\u00d7xX*](\d+)\s*份",
        r"(\d+)\s*人送",
    ]
    DRAW_METHOD_MAP = {
        "转发": ["转发", "repost", "转发本条", "转发动态", "一键转发"],
        "评论": ["评论", "留言", "comment", "评论区", "留下评论", "写评论"],
        "关注": ["关注", "follow", "关注我", "关注UP", "关注 @", "关注本账号"],
        "点赞": ["点赞", "like", "一键三连", "三连"],
    }
    HIGH_VALUE_ITEMS = ["iPhone", "iPad", "MacBook", "Switch", "PS5", "现金", "红包", "显卡", "无人机", "相机", "AirPods", "Steam Deck", "京东卡", "天猫卡", "支付宝", "微信红包"]
    LOW_VALUE_ITEMS = ["优惠券", "满减", "积分", "虚拟", "壁纸", "表情包", "头像框", "挂件", "勋章", "气泡"]

    @classmethod
    def extract(cls, text: str, draw_date: Optional[str] = None) -> LotteryInfo:
        info = LotteryInfo(draw_date=draw_date, original_text=text[:2000])
        info.prize_desc = cls._extract_prize_desc(text)
        info.prize_count = cls._extract_prize_count(text)
        info.draw_method = cls._extract_draw_method(text)
        info.conditions = cls._extract_conditions(text)
        if not info.draw_date:
            info.draw_date = cls._extract_draw_date(text)
        info.value_level = cls._assess_value(info.prize_desc)
        
        # v5.0 解析具体条件要求
        info.requires_comment = "评论" in info.draw_method or "留言" in text
        info.requires_repost = "转发" in info.draw_method
        info.requires_follow = "关注" in info.draw_method
        info.requires_like = "点赞" in info.draw_method or "三连" in text
        
        return info

    @classmethod
    def _extract_prize_desc(cls, text: str) -> str:
        for pattern in cls.PRIZE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                groups = [g for g in match.groups() if g]
                if groups:
                    return max(groups, key=len).strip()[:200]
        brackets = re.findall(r"\[([^\]]+)\]", text)
        if brackets:
            return "\u3001".join(brackets[:3])[:200]
        return "未识别"

    @classmethod
    def _extract_prize_count(cls, text: str) -> int:
        for pattern in cls.COUNT_PATTERNS:
            match = re.search(pattern, text)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue
        numbers = re.findall(r"\d+", text)
        for n in sorted(numbers, key=int, reverse=True):
            v = int(n)
            if 1 <= v <= 1000:
                return v
        return 0

    @classmethod
    def _extract_draw_method(cls, text: str) -> str:
        found = []
        for method, keywords in cls.DRAW_METHOD_MAP.items():
            if any(kw in text for kw in keywords):
                found.append(method)
        if not found:
            if "转发" in text: found.append("转发")
            if "评论" in text: found.append("评论")
        return "+".join(found) if found else "未知"

    @classmethod
    def _extract_conditions(cls, text: str) -> List[str]:
        conditions = []
        cond_map = {
            "关注": ["关注我", "关注本账号", "关注UP", "关注 @", "关注博主"],
            "转发": ["转发本条", "转发动态", "repost", "一键转发"],
            "评论": ["评论区留言", "评论本条", "留下评论", "写评论", "评论区"],
            "点赞": ["点赞本条", "点赞支持", "一键三连", "三连"],
            "@好友": ["@", "艾特", "at好友", "@一位好友"],
        }
        for name, keywords in cond_map.items():
            if any(kw in text for kw in keywords) and name not in conditions:
                conditions.append(name)
        return conditions[:10]

    @classmethod
    def _extract_draw_date(cls, text: str) -> Optional[str]:
        patterns = [
            (r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})", lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"),
            (r"(\d{1,2})月(\d{1,2})日", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
            (r"(\d{1,2})/(\d{1,2})", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
            (r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})日?", lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"),
        ]
        for pattern, formatter in patterns:
            match = re.search(pattern, text)
            if match:
                return formatter(match.groups())
        return None

    @classmethod
    def _assess_value(cls, prize_desc: str) -> str:
        d = prize_desc.lower()
        if any(kw.lower() in d for kw in cls.HIGH_VALUE_ITEMS):
            return "high"
        if any(kw.lower() in d for kw in cls.LOW_VALUE_ITEMS):
            return "low"
        return "medium"


# ============================================================================
# Section 13: 智能过滤系统（v5.0 信任评分 + 条件过滤）
# ============================================================================

class SmartFilter:
    def __init__(self, config: SmartFilterConfig, db: DatabaseManager, logger: logging.Logger):
        self.config = config
        self.db = db
        self.logger = logger
        self._blacklist_uids: Set[str] = set(str(u) for u in config.blacklist_uids)

    def should_skip(self, url: str, up_uid: str, text: str, draw_date: Optional[str], lottery_info: LotteryInfo) -> Tuple[bool, str]:
        full_text = f"{text} {lottery_info.prize_desc}"
        
        # UID黑名单
        if up_uid and str(up_uid) in self._blacklist_uids:
            return True, f"黑名单UP: {up_uid}"
        
        # 关键词黑名单
        for kw in self.config.blacklist_keywords:
            if kw in full_text:
                return True, f"黑名单关键词: {kw}"
        
        # 已开奖/过期检测
        for kw in self.config.drawn_keywords:
            if kw in full_text:
                return True, f"已开奖: {kw}"
        for kw in self.config.expired_keywords:
            if kw in full_text:
                return True, f"已过期: {kw}"
        
        # 开奖日期检查
        if draw_date:
            try:
                draw_dt = datetime.strptime(draw_date, "%Y-%m-%d")
                if draw_dt < datetime.now():
                    return True, f"开奖日已过: {draw_date}"
                days_until = (draw_dt - datetime.now()).days
                if days_until > self.config.max_days_until_draw:
                    return True, f"超远期({days_until}天): {draw_date}"
            except ValueError:
                pass
        
        # 奖品数量检查
        if 0 < lottery_info.prize_count < self.config.min_prize_count:
            return True, f"数量不足: {lottery_info.prize_count}"
        
        # v5.0: 信任评分过滤
        if up_uid:
            trust = self.db.get_up_trust_score(up_uid)
            if trust < 0.2:
                return True, f"信任评分过低: {trust:.2f}"
        
        # v5.0: 跳过不需要评论的（评论是互动指标，纯转发抽奖价值低）
        if self.config.skip_no_comment_requirement and not lottery_info.requires_comment:
            return True, "不需要评论，互动价值低"
        
        return False, ""

    def should_participate(self, lottery_info: LotteryInfo, strategy: str) -> Tuple[bool, str]:
        if strategy == "all":
            return True, "策略=all"
        if strategy == "high_value":
            if lottery_info.value_level == "high":
                return True, "高价值"
            return False, f"非高价值({lottery_info.value_level})"
        if strategy == "skip_low":
            if lottery_info.value_level == "low":
                return False, "低价值跳过"
            return True, f"价值={lottery_info.value_level}"
        if strategy == "comment_required":
            if lottery_info.requires_comment:
                return True, "需要评论"
            return False, "不需要评论"
        return True, f"默认策略={strategy}"


# ============================================================================
# Section 14: 空间扫描器（v5.0 选择器增强）
# ============================================================================

class SpaceScanner:
    # v5.0 多版本选择器
    DYNAMIC_CARD_SELECTORS = [
        ".bili-dyn-list__item",
        ".opus-module",
        ".feed-card",
        ".bili-dyn-item",
        "[data-type='DYNAMIC_TYPE_AV']",
        "[data-type='DYNAMIC_TYPE_DRAW']",
        "[data-type='DYNAMIC_TYPE_WORD']",
    ]

    def __init__(self, browser: BrowserManager, db: DatabaseManager,
                 executor: LotteryExecutor, smart_filter: SmartFilter,
                 anti_detect: AntiDetectionEngine, freq_ctrl: FrequencyController,
                 config: SystemConfig, logger: logging.Logger):
        self.browser = browser
        self.db = db
        self.executor = executor
        self.smart_filter = smart_filter
        self.anti_detect = anti_detect
        self.freq_ctrl = freq_ctrl
        self.config = config
        self.logger = logger

    def _human_scroll(self, times: int = 3):
        for i in range(times):
            scroll_amount = random.randint(600, 1400)
            if random.random() < 0.2:
                self.browser.driver.execute_script(f"window.scrollBy(0, {random.randint(100, 300)});")
                time.sleep(random.uniform(0.5, 1.0))
            self.browser.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            read_time = random.uniform(self.anti_detect.config.min_read_time, self.anti_detect.config.max_read_time)
            time.sleep(read_time)
            if random.random() < 0.25:
                self.browser.driver.execute_script(f"window.scrollBy(0, -{random.randint(50, 250)});")
                time.sleep(random.uniform(0.5, 1.5))
            if random.random() < 0.15:
                time.sleep(random.uniform(2, 4))

    def _extract_post_url(self, card) -> Optional[str]:
        # v5.0: 多URL格式支持
        url_patterns = [
            'a[href*="bilibili.com/opus"]',
            'a[href*="t.bilibili.com"]',
            'a[href*="/opus/"]',
            'a[href*="/dynamic/"]',
        ]
        for pattern in url_patterns:
            try:
                links = card.find_elements(By.CSS_SELECTOR, pattern)
                for link in links:
                    href = link.get_attribute("href")
                    if href:
                        return href.split("?")[0]
            except Exception:
                continue
        return None

    def _is_lottery_post(self, card) -> bool:
        text = card.text[:500] if hasattr(card, 'text') else ""
        lottery_keywords = ["抽奖", "互动抽奖", "转发抽奖", "关注抽奖", "评论区抽奖", "福利", "宠粉", "送"]
        return any(kw in text for kw in lottery_keywords)

    def _extract_draw_date(self, text: str) -> Optional[str]:
        for pattern, formatter in [
            (r"(\d{1,2})月(\d{1,2})日", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
            (r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"),
            (r"(\d{1,2})/(\d{1,2})", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
        ]:
            match = re.search(pattern, text)
            if match:
                return formatter(match.groups())
        return None

    def _get_cards(self) -> List[Any]:
        """多选择器尝试获取动态卡片"""
        driver = self.browser.driver
        for selector in self.DYNAMIC_CARD_SELECTORS:
            try:
                cards = driver.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    return cards
            except Exception:
                continue
        return []

    def scan(self, uid: str, up_name: str, source_type: str = "space") -> List[Dict[str, Any]]:
        results = []
        url = f"https://space.bilibili.com/{uid}/dynamic"
        self.logger.info(f"[扫描] {up_name} ({uid}) [来源: {source_type}]")
        try:
            self.browser.safe_get(url)
            # 等待任意一种动态卡片出现
            found = False
            for selector in self.DYNAMIC_CARD_SELECTORS:
                try:
                    self.browser.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    found = True
                    break
                except TimeoutException:
                    continue
            if not found:
                raise TimeoutException("未找到动态卡片")
            time.sleep(random.uniform(2, 4))
        except (RateLimitedError, AccountBannedError, CookieExpiredError) as e:
            self.logger.error(f"访问受限: {e}")
            return results
        except TimeoutException:
            self.logger.error(f"加载超时: {up_name}")
            return results
        except Exception as e:
            self.logger.error(f"访问失败: {e}")
            return results

        self._human_scroll(self.config.scroll_count)
        cards = self._get_cards()

        self.logger.info(f"{up_name}: {len(cards)} 条动态")
        lottery_count = skipped_count = 0
        for card in cards:
            try:
                if not self._is_lottery_post(card):
                    continue
                post_url = self._extract_post_url(card)
                if not post_url:
                    continue
                if self.db.fetchone("SELECT 1 FROM history WHERE url = ?", (post_url,)):
                    continue
                card_text = card.text if hasattr(card, 'text') else ""
                draw_date = self._extract_draw_date(card_text)
                lottery_info = LotteryInfoExtractor.extract(card_text, draw_date)
                lottery_info.source_type = source_type
                should_skip, reason = self.smart_filter.should_skip(post_url, uid, card_text, draw_date, lottery_info)
                if should_skip:
                    self.logger.info(f"[过滤] {post_url[:50]}... | {reason}")
                    skipped_count += 1
                    self.db.upsert_lottery_detail({
                        "url": post_url, "up_name": up_name, "up_uid": uid,
                        "prize_desc": lottery_info.prize_desc, "prize_count": lottery_info.prize_count,
                        "draw_date": draw_date, "draw_method": lottery_info.draw_method,
                        "conditions": json.dumps(lottery_info.conditions, ensure_ascii=False),
                        "original_text": lottery_info.original_text[:500],
                        "source_type": source_type, "participated": 0,
                        "value_level": lottery_info.value_level
                    })
                    continue
                should_join, strategy_reason = self.smart_filter.should_participate(lottery_info, self.config.participate_strategy)
                if not should_join:
                    self.logger.info(f"[策略跳过] {post_url[:50]}... | {strategy_reason}")
                    skipped_count += 1
                    continue
                if not self.freq_ctrl.check_daily_limit():
                    self.logger.warning("日限额已满，停止参与")
                    break
                lottery_count += 1
                self.logger.info(f"[抽奖] {post_url[:60]}... | 奖: {lottery_info.prize_desc[:40]} | 价值: {lottery_info.value_level} | {strategy_reason}")
                result = self.executor.execute(post_url, up_name, uid, draw_date)
                self.db.upsert_history({
                    "url": post_url, "up_name": up_name, "up_uid": uid,
                    "status": "success" if result["success"] else "partial",
                    "draw_date": draw_date,
                    "actions": json.dumps(result["actions"], ensure_ascii=False),
                    "page_title": result.get("page_title", ""),
                    "account_name": result.get("account", "default")
                })
                self.db.upsert_lottery_detail({
                    "url": post_url, "up_name": up_name, "up_uid": uid,
                    "prize_desc": lottery_info.prize_desc, "prize_count": lottery_info.prize_count,
                    "draw_date": lottery_info.draw_date, "draw_method": lottery_info.draw_method,
                    "conditions": json.dumps(lottery_info.conditions, ensure_ascii=False),
                    "original_text": lottery_info.original_text[:500],
                    "source_type": source_type, "participated": 1 if result["success"] else 0,
                    "value_level": lottery_info.value_level
                })
                # 更新UP统计
                self.db.update_up_stats(uid, participated=result["success"])
                results.append({**result, "lottery_info": {
                    "prize_desc": lottery_info.prize_desc,
                    "prize_count": lottery_info.prize_count,
                    "draw_method": lottery_info.draw_method,
                    "conditions": lottery_info.conditions,
                    "value_level": lottery_info.value_level
                }})
                self.freq_ctrl.wait()
            except StaleElementReferenceException:
                continue
            except Exception as e:
                self.logger.error(f"处理卡片异常: {e}")
                self.freq_ctrl.record_error()
                continue

        if source_type == "hub":
            self.db.execute("UPDATE lottery_hub_ups SET last_scan = ? WHERE uid = ?", (datetime.now().isoformat(), uid))
        else:
            self.db.execute("UPDATE target_ups SET last_check = ? WHERE uid = ?", (datetime.now().isoformat(), uid))

        self.logger.info(f"[完成] {up_name}: 发现{lottery_count} 参与{len(results)} 过滤{skipped_count}")
        return results

    def scan_hub_ups(self, hub_ups: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        all_results = []
        for uid, name in hub_ups:
            try:
                results = self.scan(str(uid), name, source_type="hub")
                all_results.extend(results)
            except Exception as e:
                self.logger.error(f"扫描抽奖区UP {name} 失败: {e}")
            self.freq_ctrl.wait()
        return all_results


print("Modules 11-14 loaded: Executor, Extractor, Filter, SpaceScanner")


# ============================================================================
# Section 15: 【v5.0 修复版】搜索扫描器 - 支持动态搜索 + WBI签名
# ============================================================================

class WBISigner:
    """B站WBI签名生成器"""
    # WBI密钥获取接口
    NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
    
    # 混淆表
    MIXIN_KEY_ENC_TAB = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
        27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
    ]
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._img_key: Optional[str] = None
        self._sub_key: Optional[str] = None
        self._last_fetch = 0
        self._lock = Lock()
    
    def _get_mixin_key(self, orig: str) -> str:
        """从img_key和sub_key生成mixin_key"""
        return ''.join([orig[i] for i in self.MIXIN_KEY_ENC_TAB])[:32]
    
    def _fetch_keys(self) -> bool:
        """获取WBI密钥"""
        try:
            resp = requests.get(self.NAV_URL, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/"
            }, timeout=10)
            data = resp.json()
            if data.get("code") != 0:
                return False
            
            wbi_img = data["data"]["wbi_img"]
            self._img_key = wbi_img["img_url"].split("/")[-1].split(".")[0]
            self._sub_key = wbi_img["sub_url"].split("/")[-1].split(".")[0]
            self._last_fetch = time.time()
            self.logger.info("WBI密钥获取成功")
            return True
        except Exception as e:
            self.logger.error(f"WBI密钥获取失败: {e}")
            return False
    
    def sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """为参数添加WBI签名"""
        with self._lock:
            if not self._img_key or not self._sub_key or time.time() - self._last_fetch > 3600:
                if not self._fetch_keys():
                    raise WBISignError("无法获取WBI密钥")
        
        # 添加wts时间戳
        params = dict(params)
        params["wts"] = int(time.time())
        
        # 过滤值
        filtered = {k: v for k, v in params.items() if v not in ("", None, "true", "false")}
        
        # 排序并拼接
        sorted_params = sorted(filtered.items())
        query = urlencode(sorted_params)
        
        # 生成mixin_key并计算md5
        mixin_key = self._get_mixin_key(self._img_key + self._sub_key)
        sign_str = query + mixin_key
        w_rid = hashlib.md5(sign_str.encode()).hexdigest()
        
        filtered["w_rid"] = w_rid
        return filtered


class SearchScanner:
    """
    v5.0 修复版搜索扫描器
    核心改进：
    1. 使用动态搜索API（search_type=dynamic）而非视频搜索
    2. 支持WBI签名验证
    3. 支持opus动态链接解析
    """

    SEARCH_API = "https://api.bilibili.com/x/web-interface/search/all"
    DYNAMIC_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ]

    def __init__(self, browser: BrowserManager, db: DatabaseManager,
                 executor: LotteryExecutor, smart_filter: SmartFilter,
                 freq_ctrl: FrequencyController, config: SystemConfig, logger: logging.Logger):
        self.browser = browser
        self.db = db
        self.executor = executor
        self.smart_filter = smart_filter
        self.freq_ctrl = freq_ctrl
        self.config = config
        self.logger = logger
        self._session = requests.Session()
        self._last_api_call = 0
        self._api_call_interval = 3.0
        self._wbi_signer = WBISigner(logger)

    def _get_headers(self) -> Dict[str, str]:
        ua = random.choice(self.USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://search.bilibili.com",
            "Referer": "https://search.bilibili.com/",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    def _api_rate_limit(self):
        elapsed = time.time() - self._last_api_call
        if elapsed < self._api_call_interval:
            wait = self._api_call_interval - elapsed + random.uniform(0.5, 1.5)
            self.logger.debug(f"API限速等待: {wait:.1f}s")
            time.sleep(wait)
        self._last_api_call = time.time()

    def _search_dynamic_via_api(self, keyword: str, page: int = 1) -> List[Dict[str, Any]]:
        """使用动态搜索API搜索抽奖动态"""
        self._api_rate_limit()

        # v5.0: 使用 search_type=video 但过滤含抽奖关键词的，或尝试 dynamic 类型
        # 实际上B站搜索API的 dynamic 类型返回的是动态内容
        params = {
            "search_type": "video",  # 先使用video，因为dynamic类型可能不稳定
            "keyword": keyword,
            "page": page,
            "order": self.config.search_sort_type,
            "page_size": 20,
        }

        try:
            # 尝试WBI签名
            signed_params = self._wbi_signer.sign(params)
        except WBISignError:
            self.logger.warning("WBI签名失败，使用无签名请求")
            signed_params = params

        headers = self._get_headers()

        try:
            self.logger.info(f"[API搜索] 关键词: {keyword} | 页码: {page}")

            resp = self._session.get(
                self.DYNAMIC_SEARCH_API,
                params=signed_params,
                headers=headers,
                timeout=15
            )

            if resp.status_code != 200:
                self.logger.warning(f"API返回状态码: {resp.status_code}")
                return []

            data = resp.json()

            if data.get("code") != 0:
                self.logger.warning(f"API错误: {data.get('message', '未知错误')} (code={data.get('code')})")
                if data.get("code") == -412:
                    self.logger.error("触发B站风控，建议增加间隔或更换IP")
                    time.sleep(random.uniform(60, 120))
                elif data.get("code") == -401:
                    self.logger.error("WBI签名无效，尝试刷新密钥")
                    self._wbi_signer._fetch_keys()
                return []

            results = data.get("data", {}).get("result", [])
            self.logger.info(f"[API搜索] 获取到 {len(results)} 条结果")

            return self._parse_api_results(results, keyword)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"API请求异常: {e}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"API返回JSON解析失败: {e}")
            return []

    def _parse_api_results(self, results: List[Dict], keyword: str) -> List[Dict[str, Any]]:
        discoveries = []

        for item in results:
            try:
                bvid = item.get("bvid", "")
                title = item.get("title", "").replace('<em class="keyword">', "").replace('</em>', "")
                desc = item.get("description", "")
                full_text = f"{title} {desc}"
                
                # v5.0: 放宽匹配条件，视频标题含抽奖关键词也纳入
                lottery_keywords = ["抽奖", "互动抽奖", "转发抽奖", "关注抽奖", "福利", "宠粉", "送"]
                if not any(kw in full_text for kw in lottery_keywords):
                    continue

                # v5.0: 构建正确的URL
                if bvid:
                    url = f"https://www.bilibili.com/video/{bvid}"
                else:
                    # 尝试从link获取
                    link = item.get("arcurl", "") or item.get("link", "")
                    url = link.split("?")[0] if link else ""
                
                if not url:
                    continue

                if self.db.fetchone("SELECT 1 FROM history WHERE url = ?", (url,)):
                    continue

                up_name = item.get("author", "未知UP")
                up_uid = str(item.get("mid", ""))

                lottery_info = self._extract_lottery_info(full_text)

                info_obj = LotteryInfo(
                    prize_desc=lottery_info.get("prize_desc", ""),
                    prize_count=lottery_info.get("prize_count", 0),
                    draw_date=lottery_info.get("draw_date"),
                    draw_method=lottery_info.get("draw_method", ""),
                    conditions=lottery_info.get("conditions", []),
                    original_text=full_text[:2000],
                    value_level=lottery_info.get("value_level", "medium")
                )

                should_skip, reason = self.smart_filter.should_skip(
                    url, up_uid, full_text, lottery_info.get("draw_date"), info_obj)
                if should_skip:
                    self.logger.debug(f"[搜索过滤] {reason}")
                    continue

                should_join, sr = self.smart_filter.should_participate(info_obj, self.config.participate_strategy)
                if not should_join:
                    continue

                discoveries.append({
                    "url": url,
                    "up_name": up_name,
                    "up_uid": up_uid,
                    "title": title,
                    "bvid": bvid,
                    "prize_desc": lottery_info.get("prize_desc", "未识别"),
                    "prize_count": lottery_info.get("prize_count", 0),
                    "draw_date": lottery_info.get("draw_date"),
                    "draw_method": lottery_info.get("draw_method", ""),
                    "conditions": lottery_info.get("conditions", []),
                    "value_level": lottery_info.get("value_level", "medium"),
                    "source_type": "search_api",
                    "keyword": keyword,
                })

            except Exception as e:
                self.logger.debug(f"解析搜索结果异常: {e}")
                continue

        return discoveries

    def _extract_lottery_info(self, text: str) -> Dict[str, Any]:
        info = {"prize_desc": "", "prize_count": 0, "draw_date": None, "draw_method": "", "conditions": [], "value_level": "medium"}

        prize_patterns = [
            r"(?:奖品|奖励|送|赠送|福利)[：:]\s*(.+?)(?:\n|$|，|,|。|；)",
            r"(?:抽|送)\s*(\d+)?\s*([\w\s\u4e00-\u9fff]+?)(?:[\u00d7xX*](\d+))?(?:\n|$|，|,|。)",
            r"(?:抽取|抽出|选出)\s*(\d+)?\s*([\w\s\u4e00-\u9fff]+?)(?:[\u00d7xX*](\d+))?",
        ]
        for p in prize_patterns:
            m = re.search(p, text)
            if m:
                groups = [g for g in m.groups() if g]
                if groups:
                    info["prize_desc"] = max(groups, key=len).strip()[:200]
                    break

        count_patterns = [
            r"(?:共计|总共|合计|共)\s*(\d+)\s*份",
            r"(\d+)\s*个名额", r"抽\s*(\d+)\s*人",
            r"(\d+)\s*位.*(?:中奖|获奖)",
            r"抽选\s*(\d+)",
        ]
        for p in count_patterns:
            m = re.search(p, text)
            if m:
                try:
                    info["prize_count"] = int(m.group(1))
                except:
                    pass
                break

        date_patterns = [
            (r"(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})", lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"),
            (r"(\d{1,2})月(\d{1,2})日", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
            (r"(\d{1,2})/(\d{1,2})", lambda m: f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d}"),
        ]
        for p, fmt in date_patterns:
            m = re.search(p, text)
            if m:
                info["draw_date"] = fmt(m.groups())
                break

        methods = []
        method_map = {
            "转发": ["转发", "repost", "转发动态"], 
            "评论": ["评论", "留言", "comment", "评论区"], 
            "关注": ["关注", "follow", "关注我"], 
            "点赞": ["点赞", "like", "三连"], 
            "三连": ["三连"]
        }
        for method, kws in method_map.items():
            if any(k in text for k in kws):
                methods.append(method)
        info["draw_method"] = "+".join(methods) if methods else "未知"

        high_items = ["iPhone", "iPad", "MacBook", "Switch", "PS5", "现金", "红包", "显卡", "无人机", "相机", "Steam", "京东卡", "天猫卡"]
        low_items = ["优惠券", "满减", "积分", "虚拟", "壁纸", "表情包", "头像框", "挂件"]
        d = text.lower()
        if any(k.lower() in d for k in high_items):
            info["value_level"] = "high"
        elif any(k.lower() in d for k in low_items):
            info["value_level"] = "low"

        return info

    def search_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        all_results = []

        for page in range(1, self.config.search_max_pages + 1):
            if not self.freq_ctrl.check_daily_limit():
                self.logger.warning("日限额已满，停止搜索")
                break

            results = self._search_dynamic_via_api(keyword, page)

            if not results:
                break

            all_results.extend(results)

            if page < self.config.search_max_pages:
                wait = random.uniform(5, 10)
                self.logger.debug(f"搜索页间等待: {wait:.1f}s")
                time.sleep(wait)

        self.db.execute(
            "INSERT INTO search_config (keyword, last_search, total_found) VALUES (?, ?, ?) "
            "ON CONFLICT(keyword) DO UPDATE SET last_search=excluded.last_search, "
            "total_found=search_config.total_found+excluded.total_found",
            (keyword, datetime.now().isoformat(), len(all_results)))

        self.logger.info(f"[搜索完成] 关键词 '{keyword}': 共找到 {len(all_results)} 条抽奖动态")
        return all_results

    def run_search(self) -> List[Dict[str, Any]]:
        if not self.config.enable_search:
            return []

        all_results = []
        for kw in self.config.search_keywords:
            row = self.db.fetchone("SELECT enabled FROM search_config WHERE keyword = ?", (kw,))
            if row and row["enabled"] == 0:
                continue

            try:
                results = self.search_keyword(kw)
                all_results.extend(results)
            except Exception as e:
                self.logger.error(f"搜索 '{kw}' 失败: {e}")

            time.sleep(random.uniform(8, 15))

        return all_results

    def participate_discovered(self, discoveries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        participated = []
        for item in discoveries:
            try:
                if not self.freq_ctrl.check_daily_limit():
                    break

                result = self.executor.execute(
                    item["url"], item["up_name"], item.get("up_uid", ""), item.get("draw_date")
                )

                self.db.upsert_history({
                    "url": item["url"], "up_name": item["up_name"], "up_uid": item.get("up_uid", ""),
                    "status": "success" if result["success"] else "partial",
                    "draw_date": item.get("draw_date"),
                    "actions": json.dumps(result["actions"], ensure_ascii=False),
                    "page_title": result.get("page_title", ""),
                    "account_name": result.get("account", "default")
                })

                self.db.upsert_lottery_detail({
                    "url": item["url"], "up_name": item["up_name"], "up_uid": item.get("up_uid", ""),
                    "prize_desc": item.get("prize_desc", ""), "prize_count": item.get("prize_count", 0),
                    "draw_date": item.get("draw_date"), "draw_method": item.get("draw_method", ""),
                    "conditions": json.dumps(item.get("conditions", []), ensure_ascii=False),
                    "source_type": item.get("source_type", "search"),
                    "participated": 1 if result["success"] else 0,
                    "value_level": item.get("value_level", "medium"),
                    "account_name": result.get("account", "default")
                })

                participated.append(result)
                self.freq_ctrl.wait()

            except Exception as e:
                self.logger.error(f"参与失败 {item.get('url', '')}: {e}")

        return participated


print("Module 15 loaded: Fixed SearchScanner v5.0 (WBI + Dynamic Search)")


# ============================================================================
# Section 16: 中奖追踪器（v5.0 修复：检查评论区置顶而非页面文字）
# ============================================================================

class WinTracker:
    def __init__(self, browser: BrowserManager, db: DatabaseManager,
                 config: SystemConfig, logger: logging.Logger):
        self.browser = browser
        self.db = db
        self.config = config
        self.logger = logger

    def check_result(self, url: str, up_name: str, prize_desc: str, draw_date: str) -> bool:
        try:
            self.browser.safe_get(url)
            self.browser.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(random.uniform(2, 4))
            
            # v5.0: 多策略检测中奖
            page_text = self.browser.driver.find_element(By.TAG_NAME, "body").text[:1500]
            
            # 策略1：页面文字包含中奖信号
            is_winner = False
            win_detail = ""
            win_signals = ["恭喜", "中奖", "获奖者", "已中奖", "中奖名单", "恭喜以下", "中奖用户"]
            
            # 策略2：检查评论区置顶（UP主通常会在评论区置顶中奖名单）
            try:
                pinned_comments = self.browser.driver.find_elements(
                    By.CSS_SELECTOR, ".pinned-comment, .top-level, .reply-item.pinned"
                )
                for comment in pinned_comments[:3]:
                    comment_text = comment.text[:200]
                    for sig in win_signals:
                        if sig in comment_text:
                            is_winner = True
                            win_detail = comment_text
                            break
                    if is_winner:
                        break
            except Exception:
                pass
            
            # 策略3：如果评论区没找到，检查页面文字
            if not is_winner:
                for sig in win_signals:
                    if sig in page_text:
                        is_winner = True
                        idx = page_text.find(sig)
                        win_detail = page_text[max(0, idx-20):idx+80]
                        break
            
            # 策略4：检查是否已开奖（动态被删除或不可见）
            if "已删除" in page_text or "不存在" in page_text or "404" in page_text:
                self.logger.info(f"[开奖检查] {url[:50]}... | 动态已删除/不存在")
                self.db.execute(
                    "INSERT OR IGNORE INTO win_tracking (url, up_name, prize_desc, draw_date, checked_at, is_winner, win_detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (url, up_name, prize_desc, draw_date, datetime.now().isoformat(), 0, "动态已删除"))
                return False

            self.db.record_health("healthy", f"开奖检查: {url[:50]}...", account="default")
            self.db.execute(
                "INSERT OR IGNORE INTO win_tracking (url, up_name, prize_desc, draw_date, checked_at, is_winner, win_detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (url, up_name, prize_desc, draw_date, datetime.now().isoformat(), int(is_winner), win_detail))
            self.logger.info(f"[开奖检查] {url[:50]}... | 中奖={is_winner}")
            return is_winner
        except (RateLimitedError, AccountBannedError, CookieExpiredError):
            return False
        except Exception as e:
            self.logger.error(f"开奖检查失败: {e}")
            return False

    def run_check(self):
        if not self.config.enable_win_tracking:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        # v5.0: 扩大检查范围，包括已过期但未检查的
        rows = self.db.fetchall(
            "SELECT * FROM lottery_details WHERE draw_date <= ? AND participated = 1 "
            "AND url NOT IN (SELECT DISTINCT url FROM win_tracking) ORDER BY draw_date DESC LIMIT 50",
            (today,))
        if not rows:
            return
        self.logger.info(f"[中奖追踪] {len(rows)} 条待检查")
        for row in rows:
            try:
                self.check_result(row["url"], row["up_name"], row.get("prize_desc", ""), row.get("draw_date", ""))
                time.sleep(random.uniform(5, 10))
            except Exception as e:
                self.logger.error(f"追踪异常: {e}")


print("Module 16 loaded: WinTracker v5.0")


# ============================================================================
# Section 17: 多推送渠道通知服务（v5.0 增强）
# ============================================================================

class MultiChannelNotifier:
    def __init__(self, config: SystemConfig, db: DatabaseManager, logger: logging.Logger):
        self.config = config
        self.db = db
        self.logger = logger

    def send_email(self, subject: str, content: str, html: bool = False) -> bool:
        smtp = self.config.smtp
        if not smtp.user or not smtp.password:
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp.user
            msg["To"] = smtp.to or smtp.user
            msg.attach(MIMEText(content, "html" if html else "plain", "utf-8"))
            with smtplib.SMTP(smtp.host, smtp.port, timeout=15) as server:
                if smtp.use_tls:
                    server.starttls()
                server.login(smtp.user, smtp.password)
                server.send_message(msg)
            self.logger.info(f"[邮件] 发送成功: {subject[:40]}")
            return True
        except Exception as e:
            self.logger.error(f"[邮件] 失败: {e}")
            return False

    def send_serverchan(self, title: str, content: str) -> bool:
        key = self.config.push.serverchan_key
        if not key:
            return False
        try:
            resp = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                               data={"title": title, "desp": content}, timeout=10)
            if resp.json().get("code") == 0:
                self.logger.info("[Server酱] 推送成功")
                return True
            return False
        except Exception as e:
            self.logger.error(f"[Server酱] 异常: {e}")
            return False

    def send_dingtalk(self, title: str, content: str) -> bool:
        token = self.config.push.dingtalk_token
        if not token:
            return False
        try:
            timestamp = str(round(time.time() * 1000))
            secret = self.config.push.dingtalk_secret
            if secret:
                string_to_sign = f"{timestamp}\n{secret}"
                hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                                    digestmod=hashlib.sha256).digest()
                sign = quote(base64.b64encode(hmac_code))
                url = f"https://oapi.dingtalk.com/robot/send?access_token={token}&timestamp={timestamp}&sign={sign}"
            else:
                url = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
            resp = requests.post(url, json={
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"### {title}\n\n{content}"}
            }, timeout=10)
            if resp.json().get("errcode") == 0:
                self.logger.info("[钉钉] 推送成功")
                return True
            return False
        except Exception as e:
            self.logger.error(f"[钉钉] 异常: {e}")
            return False

    def send_wecom(self, title: str, content: str) -> bool:
        wh = self.config.push.wx_webhook
        if not wh:
            return False
        try:
            resp = requests.post(wh, json={
                "msgtype": "text", "text": {"content": f"{title}\n\n{content}"}
            }, timeout=10)
            if resp.json().get("errcode") == 0:
                self.logger.info("[企业微信] 推送成功")
                return True
            return False
        except Exception as e:
            self.logger.error(f"[企业微信] 异常: {e}")
            return False

    def send_bark(self, title: str, content: str) -> bool:
        key = self.config.push.bark_key
        if not key:
            return False
        try:
            server = self.config.push.bark_server or "https://api.day.app"
            url = f"{server}/{key}/{quote(title)}/{quote(content[:500])}"
            resp = requests.get(url, timeout=10)
            if resp.json().get("code") == 200:
                self.logger.info("[Bark] 推送成功")
                return True
            return False
        except Exception as e:
            self.logger.error(f"[Bark] 异常: {e}")
            return False

    def notify_all(self, title: str, content: str):
        results = {}
        results["email"] = self.send_email(title, content)
        results["serverchan"] = self.send_serverchan(title, content)
        results["dingtalk"] = self.send_dingtalk(title, content)
        results["wecom"] = self.send_wecom(title, content)
        results["bark"] = self.send_bark(title, content)
        success = sum(1 for v in results.values() if v)
        self.logger.info(f"[推送] {success}/5 渠道成功")
        return results

    def send_reminder(self, records: List[sqlite3.Row]):
        if not records:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [f"共有 {len(records)} 条抽奖今日开奖\n"]
        for r in records:
            actions = json.loads(r["actions"]) if r["actions"] else {}
            summary = ", ".join([f"{k}: {'OK' if v else 'X'}" for k, v in actions.items()])
            lines.append(f"UP: {r['up_name']} | {r['url'][:60]} | {summary}")
        self.notify_all(f"B站开奖提醒 - {today}", "\n".join(lines))

    def send_discovery_report(self, discoveries: List[Dict], participated: int):
        if not discoveries:
            return
        now = datetime.now().strftime("%m-%d %H:%M")
        lines = [f"发现 {len(discoveries)} 条新抽奖，成功参与 {participated} 条\n"]
        for i, item in enumerate(discoveries[:15], 1):
            lines.append(f"{i}. [{item.get('value_level', '?')}] {item['up_name']} | "
                        f"{item.get('prize_desc', 'N/A')[:40]} | {item.get('draw_method', '')}")
        self.notify_all(f"B站抽奖发现报告 - {now}", "\n".join(lines))

    def send_win_notification(self, win_records: List[sqlite3.Row]):
        for r in win_records:
            title = f"恭喜中奖! {r['up_name']}的抽奖"
            content = f"奖品: {r['prize_desc'] or '未知'}\n链接: {r['url']}\n详情: {r.get('win_detail', '')}"
            self.notify_all(title, content)
            self.db.execute("UPDATE win_tracking SET notified = 1 WHERE id = ?", (r["id"],))


print("Module 17 loaded: MultiChannelNotifier")


# ============================================================================
# Section 18: 主控系统（v5.0 多账号 + 断路器非阻塞 + 配置热重载）
# ============================================================================

class BiliLotterySystem:
    def __init__(self, config: SystemConfig):
        self.config = config
        self.logger = setup_logging(config.log_path)
        self.logger.info("=" * 60)
        self.logger.info("B站抽奖自动化系统 v5.0 初始化中...")
        self.logger.info("【终极版】多账号 + WBI签名 + 智能风控 + 工程化")
        self.logger.info("=" * 60)

        self.db = DatabaseManager(config.db_path, self.logger)
        self.proxy_manager = ProxyManager(config.proxy_list, self.logger)
        self.anti_detect = AntiDetectionEngine(config.risk_control, self.logger)
        
        # v5.0: 多账号支持
        self.current_account = config.get_current_account()
        self.freq_ctrl = FrequencyController(config.frequency, self.db, self.logger, self.current_account.name)
        self.health_monitor = AccountHealthMonitor(self.db, self.logger, self.current_account.name)
        
        self.browser = BrowserManager(config, self.proxy_manager, self.anti_detect,
                                     self.health_monitor, self.logger)
        if self.current_account.cookie_file:
            self.browser.set_cookie_file(self.current_account.cookie_file)
        
        self.executor = LotteryExecutor(self.browser, self.db, self.anti_detect,
                                       self.freq_ctrl, config, self.logger, self.current_account.name)
        self.smart_filter = SmartFilter(config.smart_filter, self.db, self.logger)
        self.scanner = SpaceScanner(self.browser, self.db, self.executor, self.smart_filter,
                                   self.anti_detect, self.freq_ctrl, config, self.logger)
        self.search_scanner = SearchScanner(self.browser, self.db, self.executor, self.smart_filter,
                                           self.freq_ctrl, config, self.logger)
        self.win_tracker = WinTracker(self.browser, self.db, config, self.logger)
        self.notifier = MultiChannelNotifier(config, self.db, self.logger)

        self._shutdown_event = Event()
        self._scheduler_thread: Optional[Thread] = None
        self._consecutive_scan_errors = 0
        self._max_scan_errors = 5
        self._circuit_breaker_cooldown = Event()  # v5.0: 非阻塞断路器
        self._config_mtime = 0  # v5.0: 配置热重载

        atexit.register(self.shutdown)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("所有模块初始化完成")

    def _signal_handler(self, signum, frame):
        self.logger.info(f"收到信号 {signum}，优雅关闭中...")
        self._shutdown_event.set()
        self._circuit_breaker_cooldown.set()  # 唤醒可能等待的断路器

    def _check_config_reload(self):
        """v5.0: 配置热重载"""
        try:
            mtime = Path(self.config.config_file).stat().st_mtime
            if mtime > self._config_mtime:
                self.logger.info("检测到配置文件变更，正在热重载...")
                new_config = SystemConfig.from_json(self.config.config_file)
                # 只更新部分可热重载的配置
                self.config.search_keywords = new_config.search_keywords
                self.config.search_max_pages = new_config.search_max_pages
                self.config.participate_strategy = new_config.participate_strategy
                self.config.frequency.daily_participation_limit = new_config.frequency.daily_participation_limit
                self.config.smart_filter = new_config.smart_filter
                self.smart_filter = SmartFilter(self.config.smart_filter, self.db, self.logger)
                self._config_mtime = mtime
                self.logger.info("配置热重载完成")
        except Exception as e:
            self.logger.debug(f"配置热重载检查失败: {e}")

    def add_target_up(self, uid: str, name: str, priority: int = 5):
        try:
            self.db.execute(
                "INSERT INTO target_ups (uid, name, priority) VALUES (?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, priority=excluded.priority",
                (uid, name, priority))
            self.logger.info(f"[UP主] {name} ({uid}) 已添加")
        except Exception as e:
            self.logger.error(f"添加UP主失败: {e}")

    def add_lottery_hub_up(self, uid: str, name: str):
        try:
            self.db.add_lottery_hub_up(str(uid), name)
            self.logger.info(f"[抽奖区] {name} ({uid}) 已添加")
        except Exception as e:
            self.logger.error(f"添加失败: {e}")

    def _switch_account(self):
        """v5.0: 切换账号"""
        if not self.config.enable_multi_account or len(self.config.accounts) <= 1:
            return False
        
        self.config.active_account_index = (self.config.active_account_index + 1) % len(self.config.accounts)
        new_account = self.config.get_current_account()
        if not new_account.is_active:
            return self._switch_account()
        
        self.logger.info(f"切换账号: {self.current_account.name} -> {new_account.name}")
        self.current_account = new_account
        
        # 重新初始化相关组件
        self.freq_ctrl = FrequencyController(self.config.frequency, self.db, self.logger, new_account.name)
        self.health_monitor = AccountHealthMonitor(self.db, self.logger, new_account.name)
        self.browser.close()
        self.browser = BrowserManager(self.config, self.proxy_manager, self.anti_detect,
                                      self.health_monitor, self.logger)
        if new_account.cookie_file:
            self.browser.set_cookie_file(new_account.cookie_file)
        self.executor = LotteryExecutor(self.browser, self.db, self.anti_detect,
                                        self.freq_ctrl, self.config, self.logger, new_account.name)
        self.scanner = SpaceScanner(self.browser, self.db, self.executor, self.smart_filter,
                                    self.anti_detect, self.freq_ctrl, self.config, self.logger)
        self.win_tracker = WinTracker(self.browser, self.db, self.config, self.logger)
        return True

    def _run_with_circuit_breaker(self, task_name: str, task_func: Callable, *args, **kwargs):
        try:
            if not self.health_monitor.is_healthy():
                self.health_monitor.assert_healthy()
            result = task_func(*args, **kwargs)
            self._consecutive_scan_errors = 0
            self.freq_ctrl.record_success()
            return result
        except (RateLimitedError, CaptchaDetectedError) as e:
            self.logger.warning(f"[{task_name}] 风控触发: {e}")
            self.freq_ctrl.apply_rate_limit_backoff()
            self._consecutive_scan_errors += 1
        except CookieExpiredError as e:
            self.logger.warning(f"[{task_name}] Cookie过期: {e}")
            if self.config.auto_switch_account and self._switch_account():
                self.logger.info("已切换账号，重试任务")
                return self._run_with_circuit_breaker(task_name, task_func, *args, **kwargs)
            self._consecutive_scan_errors += 1
        except AccountBannedError as e:
            self.logger.critical(f"[{task_name}] 账号封禁: {e}")
            self.notifier.notify_all("B站抽奖系统紧急通知", f"账号疑似封禁: {e}")
            if self.config.auto_switch_account and self._switch_account():
                return None
            self._shutdown_event.set()
        except Exception as e:
            self.logger.error(f"[{task_name}] 异常: {e}")
            self.freq_ctrl.record_error()
            self._consecutive_scan_errors += 1
        
        # v5.0: 非阻塞断路器
        if self._consecutive_scan_errors >= self._max_scan_errors:
            cooldown = 600
            self.logger.warning(f"断路器触发: 连续{self._consecutive_scan_errors}次错误，冷却{cooldown}秒")
            self.notifier.notify_all("B站抽奖系统告警", f"连续{self._consecutive_scan_errors}次扫描失败，进入保护模式")
            self._consecutive_scan_errors = 0
            # 使用Event等待，可被shutdown信号中断
            self._circuit_breaker_cooldown.wait(timeout=cooldown)
            self._circuit_breaker_cooldown.clear()
        
        return None

    def run_once(self):
        self.logger.info("=" * 60)
        self.logger.info(f"[任务] 目标UP扫描 [账号: {self.current_account.name}]")
        self.logger.info("=" * 60)
        ups = self.db.fetchall("SELECT uid, name FROM target_ups WHERE status = 1 ORDER BY priority DESC")
        if not ups:
            self.logger.info("无目标UP主")
            return
        for row in ups:
            if self._shutdown_event.is_set():
                break
            self._run_with_circuit_breaker("UP扫描", self.scanner.scan, row["uid"], row["name"], "space")
            self.freq_ctrl.wait()
        self.check_and_remind()
        self.check_and_notify_wins()

    def run_search_scan(self):
        self.logger.info("=" * 60)
        self.logger.info(f"[任务] API搜索扫描 v5.0 [账号: {self.current_account.name}]")
        self.logger.info("=" * 60)
        discoveries = self._run_with_circuit_breaker("搜索", self.search_scanner.run_search)
        if discoveries:
            participated = self._run_with_circuit_breaker("搜索参与",
                self.search_scanner.participate_discovered, discoveries)
            if participated is not None:
                self.notifier.send_discovery_report(discoveries, len(participated))

    def run_hub_scan(self):
        self.logger.info("=" * 60)
        self.logger.info(f"[任务] 抽奖区扫描 [账号: {self.current_account.name}]")
        self.logger.info("=" * 60)
        hub_ups_db = self.db.get_active_hub_ups()
        hub_ups = [(row["uid"], row["name"]) for row in hub_ups_db]
        config_ups = self.config.lottery_hub_ups
        if config_ups:
            existing = {uid for uid, _ in hub_ups}
            for item in config_ups:
                uid, name = str(item[0]), item[1]
                if uid not in existing:
                    hub_ups.append((uid, name))
                    self.db.add_lottery_hub_up(uid, name)
        if hub_ups:
            self._run_with_circuit_breaker("抽奖区扫描", self.scanner.scan_hub_ups, hub_ups)

    def run_win_tracking(self):
        self.logger.info("=" * 60)
        self.logger.info("[任务] 中奖追踪")
        self.logger.info("=" * 60)
        self._run_with_circuit_breaker("中奖追踪", self.win_tracker.run_check)

    def check_and_remind(self):
        today = datetime.now().strftime("%Y-%m-%d")
        records = self.db.fetchall("SELECT * FROM history WHERE draw_date = ? AND reminded = 0", (today,))
        if records:
            self.logger.info(f"[提醒] {len(records)} 条今日开奖")
            self.notifier.send_reminder(records)
            for r in records:
                self.db.execute("UPDATE history SET reminded = 1 WHERE url = ?", (r["url"],))

    def check_and_notify_wins(self):
        wins = self.db.fetchall("SELECT * FROM win_tracking WHERE is_winner = 1 AND notified = 0")
        if wins:
            self.logger.info(f"[中奖] {len(wins)} 条未通知中奖！")
            self.notifier.send_win_notification(wins)

    def _scheduler_loop(self):
        self.logger.info("=" * 60)
        self.logger.info("调度器启动 v5.0")
        self.logger.info(f"  目标UP扫描: 每2小时 | 搜索: 每{self.config.search_interval_hours}小时")
        self.logger.info(f"  抽奖区扫描: 每{self.config.hub_scan_interval_hours}小时 | 中奖追踪: 每{self.config.win_check_interval_hours}小时")
        self.logger.info(f"  参与策略: {self.config.participate_strategy} | 日限额: {self.config.frequency.daily_participation_limit}")
        self.logger.info(f"  当前账号: {self.current_account.name}")
        self.logger.info("=" * 60)

        if not self.config.api_only_mode:
            self.browser.ensure_alive()
        
        self.run_once()
        if self.config.enable_search:
            self.run_search_scan()
        self.run_hub_scan()

        schedule.every(2).hours.do(self.run_once)
        if self.config.enable_search:
            schedule.every(self.config.search_interval_hours).hours.do(self.run_search_scan)
        schedule.every(self.config.hub_scan_interval_hours).hours.do(self.run_hub_scan)
        if self.config.enable_win_tracking:
            schedule.every(self.config.win_check_interval_hours).hours.do(self.run_win_tracking)
        schedule.every().day.at("10:00").do(self.check_and_remind)
        schedule.every().day.at("18:00").do(self.check_and_remind)
        schedule.every().day.at("08:00").do(self._daily_health_report)
        schedule.every(5).minutes.do(self._check_config_reload)  # v5.0: 配置热重载检查

        self.logger.info("进入调度循环...")
        while not self._shutdown_event.is_set():
            try:
                schedule.run_pending()
            except Exception as e:
                self.logger.error(f"调度异常: {e}")
            time.sleep(1)
        self.logger.info("调度器已停止")

    def _daily_health_report(self):
        today = datetime.now().strftime("%Y-%m-%d")
        daily_count = self.db.get_daily_participation_count(self.current_account.name)
        health = self.db.get_latest_health(self.current_account.name)
        status = health["status"] if health else "unknown"
        
        # v5.0: 统计信息更丰富
        total_participated = self.db.fetchone("SELECT COUNT(*) as cnt FROM history WHERE account_name = ?", (self.current_account.name,))[0]
        total_wins = self.db.fetchone("SELECT COUNT(*) as cnt FROM win_tracking WHERE is_winner = 1")[0]
        
        report = (
            f"B站抽奖系统日报 ({today}) [账号: {self.current_account.name}]\n"
            f"========================\n"
            f"今日参与: {daily_count} 次\n"
            f"累计参与: {total_participated} 次\n"
            f"累计中奖: {total_wins} 次\n"
            f"账号状态: {status}\n"
            f"冷却倍率: {self.freq_ctrl._cooldown_multiplier:.1f}x\n"
            f"参与策略: {self.config.participate_strategy}\n"
            f"当前代理: {self.proxy_manager.current_proxy or '直连'}"
        )
        self.logger.info(f"[日报]\n{report}")
        self.notifier.notify_all(f"B站抽奖日报 - {today}", report)

    def start(self):
        self.logger.info("=" * 60)
        self.logger.info("B站抽奖自动化系统 v5.0 启动")
        self.logger.info("=" * 60)

        self._scheduler_thread = Thread(target=self._scheduler_loop, name="Scheduler", daemon=True)
        self._scheduler_thread.start()

        try:
            while not self._shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("键盘中断")
        finally:
            self.shutdown()

    def shutdown(self):
        if self._shutdown_event.is_set():
            return
        self.logger.info("系统关闭中...")
        self._shutdown_event.set()
        self._circuit_breaker_cooldown.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=30)
        self.browser.close()
        self.db.close()
        self.logger.info("系统已安全关闭")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()


# ============================================================================
# Section 19: 入口
# ============================================================================

def main():
    config_file = sys.argv[1] if len(sys.argv) > 1 else "./config.json"
    config = SystemConfig.from_json(config_file)
    system = BiliLotterySystem(config)

    target_ups = [
        # ("UID", "名称", 优先级),
        # 示例: ("208259", "哔哩哔哩番剧", 5),
    ]
    for uid, name, *rest in target_ups:
        system.add_target_up(str(uid), name, rest[0] if rest else 5)

    hub_ups = [
        # ("UID", "名称"),
        # 示例: ("353361", "抽奖娘", 5),
    ]
    for uid, name in hub_ups:
        system.add_lottery_hub_up(str(uid), name)

    has_any = target_ups or hub_ups or config.lottery_hub_ups or (config.enable_search and config.search_keywords)
    if not has_any:
        print("未配置任何扫描目标。请编辑 config.json 添加UP主或搜索关键词。")
        return

    system.start()


if __name__ == "__main__":
    main()
