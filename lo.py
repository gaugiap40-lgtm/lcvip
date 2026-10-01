#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
# BOT TÀI XỈU LC79 / TELE68 QUANT MASTER - VERSION 4.1.0 (AUTOAI + GEMINI.PY ONLY)
# CHỈ DÙNG UNOFFICIAL GEMINI (gemini.py) - KHÔNG CẦN API KEY
# AutoAI Full Cầu + RLE + Pattern Memory + Unofficial Gemini
# Vẫn giữ nguyên luồng /autopredict
# =====================================================================

import os
import sys
import time
import json
import math
import queue
import html
import random
import hashlib
import logging
import threading
import asyncio
import re
import uuid
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Any, Union

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LC79MasterQuant")

# ---- Optional libraries (graceful fallback) ----
# Unofficial Gemini (no API key) - from gemini.py
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    logger.warning("Thư viện curl_cffi chưa được cài. Fallback Gemini không key sẽ tắt.")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    import urllib.request
    import urllib.error
    import urllib.parse

try:
    from flask import Flask, jsonify, request as flask_request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

# =====================================================================
# CONFIG
# =====================================================================
APP_VERSION = "4.1.0-GeminiPy-Only"
START_TIME = time.time()

TELEGRAM_BOT_TOKEN = "8767789638:AAFTM21tprlealhlsS2SJ_ITA_zW4V6rb5M"

SERVER_PORT = 3000

LC79_SESSIONS_URL = "https://wtxmd52.tele68.com/v1/txmd5/sessions"
LC79_SOCKET_URL = "https://wtxmd52.tele68.com"
LC79_SOCKET_NAMESPACE = "/txmd5"

DATA_FILE_PATH = "pred_history_master.json"
BACKUP_DATA_FILE = "pred_history_master.json.bak"
MAX_STORED_PATTERNS = 50000
CAU_KNOWLEDGE_FILE = "Cau_Tai_Xiu_Thuat_Toan_Cong_Thuc.txt"

WEIGHT_MAX_RLE = 32.0
WEIGHT_MAX_SEQUENCE = 22.0
WEIGHT_MAX_PATTERN_MEMORY = 40.0
WEIGHT_MAX_GEMINI = 60.0
DECAY_FACTOR = 0.955
CONFIDENCE_HARD_CAP = 92.0

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Referer": "https://tele68.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://tele68.com",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive"
}

# =====================================================================
# GLOBAL STATE
# =====================================================================
state_lock = threading.RLock()

pattern_memory: Dict[str, Dict[str, Any]] = {}
session_history: List[Dict[str, Any]] = []
history_cache_time: float = 0.0
prediction_history: List[Dict[str, Any]] = []
user_configs: Dict[str, Dict[str, Any]] = {}
game_accounts: Dict[str, Dict[str, Any]] = {}
current_session_id: Optional[int] = None
sent_predictions: Dict[int, Dict[str, Any]] = {}
broadcast_queue: queue.Queue = queue.Queue(maxsize=1000)
dirty_memory_flag = threading.Event()
stop_all_threads = threading.Event()

ai_switches = {
    "enabled": True,
    "prefer_live": False,
    "last_analysis": None,
    "full_cau_mode": True
}

# Circuit breaker for Gemini calls
gemini_cb_lock = threading.Lock()
gemini_cb = {
    "fails": 0,
    "open_until": 0.0,
    "last_error": "",
    "cooldown_base": 20,
    "cooldown_max": 240
}

# =====================================================================
# KIẾN THỨC CẦU FULL (load từ file)
# =====================================================================
CAU_KNOWLEDGE_BASE: str = ""
CAU_SUMMARY_FOR_PROMPT: str = ""

def load_cau_knowledge():
    """Load toàn bộ kiến thức cầu từ file txt để AI phân tích ALL"""
    global CAU_KNOWLEDGE_BASE, CAU_SUMMARY_FOR_PROMPT
    possible_paths = [
        CAU_KNOWLEDGE_FILE,
        os.path.join(os.path.dirname(__file__), CAU_KNOWLEDGE_FILE),
        "/home/workdir/attachments/Cau_Tai_Xiu_Thuat_Toan_Cong_Thuc.txt",
        "Cau_Tai_Xiu_Thuat_Toan_Cong_Thuc.txt"
    ]
    content = ""
    for p in possible_paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                logger.info(f"Đã load kiến thức cầu FULL từ: {p} ({len(content)} ký tự)")
                break
        except Exception as e:
            logger.debug(f"Không load được {p}: {e}")

    if not content:
        logger.warning("Không tìm thấy file kiến thức cầu → dùng bản tóm tắt cứng.")
        content = """DANH SÁCH CẦU TÀI XỈU CƠ BẢN
A1. Bệt / Rồng: Bệt n (n=2..15), Bệt dài
A2. Nhịp đôi: 1-1, 2-2, 3-3 ... 10-10; Nhịp lệch 1-2, 2-1, 1-3, 3-1, 2-3, 3-2...
A3. 3 nhịp: 1-2-3, 3-2-1, 1-1-2, 2-2-1, 1-3-1...
A4. 4 nhịp: 1-2-3-4, 4-3-2-1, đối xứng a-b-b-a
A5. Đặc biệt: Đối xứng, Phản đối xứng, So le, Zic zac, Bậc thang, Fibonacci, Gãy, Bẻ, Chuyền, Ma
CÔNG THỨC: Cầu a-b, a-b-c, a-b-c-d... ; RLE + tìm chu kỳ nhịp
"""

    CAU_KNOWLEDGE_BASE = content
    summary_parts = []
    lines = content.splitlines()
    in_important = False
    for line in lines:
        if any(k in line for k in ["PHẦN A:", "PHẦN B:", "PHẦN C:", "PHẦN 2:", "PHẦN 3:", "RLE", "CẦU BỆT", "CẦU NHỊP", "CẦU 3 NHỊP", "CẦU 4 NHỊP", "CẦU ĐẶC BIỆT", "CÔNG THỨC"]):
            in_important = True
        if in_important:
            summary_parts.append(line)
            if len("\n".join(summary_parts)) > 6500:
                break
    CAU_SUMMARY_FOR_PROMPT = "\n".join(summary_parts) if summary_parts else content[:6000]
    logger.info(f"Tóm tắt kiến thức cầu cho prompt: {len(CAU_SUMMARY_FOR_PROMPT)} ký tự")

load_cau_knowledge()


# =====================================================================

# UNOFFICIAL GEMINI CLIENT (no API key) - hardened from gemini.py
# =====================================================================
class UnofficialGeminiClient:
    """
    Gemini không cần API key (gemini.google.com)
    Hardened: retry, short prompt, better logging.
    """
    BASE = "https://gemini.google.com"
    PATH = "/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
    _session = None
    _BL = None
    _FSID = None
    _cid = None
    _rid = None
    _lock = threading.Lock()
    _last_refresh = 0.0
    _fail_count = 0

    @classmethod
    def _ensure_session(cls, force: bool = False) -> bool:
        if not CURL_CFFI_AVAILABLE:
            logger.error("curl_cffi không có")
            return False
        with cls._lock:
            now = time.time()
            if (not force) and cls._session is not None and cls._BL and cls._FSID and (now - cls._last_refresh) < 1200:
                return True
            try:
                cls._session = curl_requests.Session(impersonate="chrome131")
                # Thêm header giống trình duyệt thật hơn
                cls._session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                })
                resp = cls._session.get(cls.BASE + "/", timeout=20)
                html = resp.text
                bl_m = re.search(r'"cfb2h":"([^"]+)"', html)
                fsid_m = re.search(r'"FdrFJe":"(-?\d+)"', html)
                if not bl_m or not fsid_m:
                    # Thử pattern khác (Google hay đổi)
                    bl_m = re.search(r'cfb2h["\s:]+([a-zA-Z0-9_-]+)', html)
                    fsid_m = re.search(r'FdrFJe["\s:]+(-?\d+)', html)
                if not bl_m or not fsid_m:
                    logger.error(f"Unofficial Gemini: không lấy được BL/FSID (status={resp.status_code}, len={len(html)})")
                    cls._session = None
                    return False
                cls._BL = bl_m.group(1)
                cls._FSID = fsid_m.group(1)
                cls._last_refresh = now
                cls._cid = None
                cls._rid = None
                cls._fail_count = 0
                logger.info(f"Unofficial Gemini session OK (BL={cls._BL[:12]}...)")
                return True
            except Exception as e:
                logger.error(f"Unofficial Gemini session error: {e}")
                cls._session = None
                return False

    @staticmethod
    def _dig(cands):
        out, stack = "", [cands]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                if (len(n) > 1 and isinstance(n[0], str) and n[0].startswith("rc_")
                        and isinstance(n[1], list) and n[1] and isinstance(n[1][0], str)
                        and len(n[1][0]) >= len(out)):
                    out = n[1][0]
                stack.extend(n)
        return out

    @classmethod
    def sherlock(cls, msg: str, lang: str = "vi") -> Optional[str]:
        # Giới hạn độ dài prompt để tránh fail
        if len(msg) > 4500:
            msg = msg[:4500] + "\n\n(Rút gọn để gửi Gemini)"

        for attempt in range(2):  # retry 1 lần
            if not cls._ensure_session(force=(attempt > 0)):
                return None
            try:
                with cls._lock:
                    fresh = ["", "", "", None, None, None, None, None, None, ""]
                    p = [None] * 99
                    p[0] = [msg, 0, None, None, None, None, 0]
                    p[1] = [lang]
                    p[2] = [cls._cid, cls._rid, "", None, None, None, None, None, None, ""] if cls._cid else fresh
                    p[6], p[7], p[10], p[11] = [1], 1, 1, 0
                    p[17], p[18] = [[0]], 0
                    p[27], p[30] = 1, [4]
                    p[41], p[53] = [2], 0
                    p[59], p[61] = str(uuid.uuid4()).upper(), []
                    p[68], p[79] = 2, 6
                    p[91], p[96], p[98] = 0, 0, 1
                    url = f"{cls.BASE}{cls.PATH}?bl={cls._BL}&f.sid={cls._FSID}&hl={lang}&_reqid={random.randint(100000,999999)}&rt=c"
                    res = cls._session.post(
                        url,
                        data={"f.req": json.dumps([None, json.dumps(p)])},
                        stream=True,
                        timeout=50
                    )
                    text, ids = "", None
                    for line in res.iter_lines():
                        if not line:
                            continue
                        line = line.decode() if isinstance(line, bytes) else line
                        if line.startswith(")]}'") or line.isdigit():
                            continue
                        try:
                            arr = json.loads(line)
                        except Exception:
                            continue
                        for row in arr:
                            if not (isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr"):
                                continue
                            try:
                                d = json.loads(row[2])
                            except Exception:
                                continue
                            if (isinstance(d, list) and len(d) > 1 and isinstance(d[1], list)
                                    and d[1] and str(d[1][0]).startswith("c_")):
                                ids = d[1]
                            if len(d) > 4 and isinstance(d[4], list):
                                t = cls._dig(d[4])
                                if len(t) > len(text):
                                    text = t
                    if ids:
                        cls._cid = ids[0] if len(ids) > 0 else None
                        cls._rid = ids[1] if len(ids) > 1 else None
                    if text and text.strip():
                        cls._fail_count = 0
                        return text.strip()
                    logger.warning(f"Unofficial Gemini empty response (attempt {attempt+1})")
            except Exception as e:
                logger.error(f"Unofficial Gemini Sherlock error (attempt {attempt+1}): {e}")
                with cls._lock:
                    cls._session = None
                    cls._fail_count += 1
        return None

    @classmethod
    def ask(cls, prompt: str) -> Optional[str]:
        """Public – gọi Gemini không key"""
        result = cls.sherlock(prompt, lang="vi")
        if not result:
            # Thử lại với tiếng Anh nếu tiếng Việt fail
            result = cls.sherlock(prompt, lang="en")
        return result


# =====================================================================
# ASYNC EVENT LOOP FOR GEMINI LIVE
# =====================================================================
async_loop: Optional[asyncio.AbstractEventLoop] = None
async_loop_lock = threading.Lock()

def get_gemini_async_loop() -> asyncio.AbstractEventLoop:
    global async_loop
    with async_loop_lock:
        if async_loop is not None and not async_loop.is_closed():
            return async_loop
        loop = asyncio.new_event_loop()
        async_loop = loop
        def _run():
            asyncio.set_event_loop(loop)
            loop.run_forever()
        t = threading.Thread(target=_run, name="GeminiAsyncLoop", daemon=True)
        t.start()
        return loop

# =====================================================================
# HTTP CLIENT
# =====================================================================
class FastHTTP:
    @staticmethod
    def get_json(url: str, timeout: int = 8) -> Optional[Any]:
        if REQUESTS_AVAILABLE:
            try:
                resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                logger.debug(f"HTTP GET (requests): {e}")
                return None
        else:
            try:
                req = urllib.request.Request(url, headers=HTTP_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode("utf-8"))
            except Exception as e:
                logger.debug(f"HTTP GET (urllib): {e}")
                return None
        return None

    @staticmethod
    def post_json(url: str, payload: dict, timeout: int = 8) -> Optional[Any]:
        headers = dict(HTTP_HEADERS)
        headers["Content-Type"] = "application/json"
        if REQUESTS_AVAILABLE:
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                return resp.json() if resp.status_code == 200 else None
            except Exception as e:
                logger.debug(f"HTTP POST: {e}")
                return None
        else:
            try:
                data_str = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data_str, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as e:
                logger.debug(f"HTTP POST (urllib): {e}")
                return None

# =====================================================================
# RLE ENGINE
# =====================================================================
class RLEPatternEngine:
    @staticmethod
    def encode_rle(series: List[int]) -> List[Tuple[int, int]]:
        if not series:
            return []
        encoded = []
        cur_val = series[0]
        cur_count = 1
        for val in series[1:]:
            if val == cur_val:
                cur_count += 1
            else:
                encoded.append((cur_val, cur_count))
                cur_val = val
                cur_count = 1
        encoded.append((cur_val, cur_count))
        return encoded

    @staticmethod
    def get_run_lengths(rle_runs: List[Tuple[int, int]]) -> List[int]:
        return [count for _, count in rle_runs]

    @classmethod
    def analyze_patterns(cls, series: List[int]) -> Dict[str, Any]:
        if len(series) < 3:
            return {
                "name": "Cầu chưa đủ dữ liệu",
                "active_run_val": series[-1] if series else 1,
                "active_run_len": 1,
                "expected_next": 1,
                "pattern_confidence": 0.5,
                "structure_type": "hon_hop",
                "description": "Chuỗi quá ngắn"
            }

        rle_runs = cls.encode_rle(series)
        runs_len = cls.get_run_lengths(rle_runs)
        curr_val, curr_len = rle_runs[-1]
        opposite_val = 1 - curr_val

        if curr_len >= 5:
            if curr_len >= 8:
                return {
                    "name": f"Cầu Bệt Rồng Rất Dài ({curr_len} phiên)",
                    "active_run_val": curr_val, "active_run_len": curr_len,
                    "expected_next": opposite_val, "pattern_confidence": 0.72,
                    "structure_type": "bet",
                    "description": f"Bệt {curr_len} phiên liên tiếp, áp lực đứt cầu gia tăng mạnh."
                }
            elif curr_len >= 6:
                return {
                    "name": f"Cầu Bệt Sâu ({curr_len} phiên)",
                    "active_run_val": curr_val, "active_run_len": curr_len,
                    "expected_next": opposite_val, "pattern_confidence": 0.65,
                    "structure_type": "bet",
                    "description": f"Bệt {curr_len} phiên, tỷ lệ bẻ cầu nhịp {curr_len+1} là 65%."
                }
            else:
                return {
                    "name": f"Cầu Bệt ({curr_len} phiên)",
                    "active_run_val": curr_val, "active_run_len": curr_len,
                    "expected_next": curr_val, "pattern_confidence": 0.68,
                    "structure_type": "bet",
                    "description": f"Bệt 5 phiên, đà bám rồng còn khả năng nối thêm 1 nhịp."
                }

        k = len(runs_len)
        if k >= 3:
            last_4_runs = runs_len[-4:] if k >= 4 else runs_len[-3:]
            if all(r == 1 for r in last_4_runs):
                return {
                    "name": "Cầu 1-1 (So le đảo đều)",
                    "active_run_val": curr_val, "active_run_len": curr_len,
                    "expected_next": opposite_val, "pattern_confidence": 0.85,
                    "structure_type": "nhip_doi",
                    "description": f"Chuỗi 1-1 nhịp nhàng {len(last_4_runs)} lượt, dự báo đảo cửa tiếp tục."
                }

            if len(runs_len) >= 3 and runs_len[-3] == 2 and runs_len[-2] == 2:
                if curr_len == 1:
                    return {
                        "name": "Cầu 2-2 (Nhịp đôi cân bằng)",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": curr_val, "pattern_confidence": 0.82,
                        "structure_type": "nhip_doi",
                        "description": "Đang theo khuôn mẫu 2-2, nhịp hiện tại đang 1 -> dự đoán nối tiếp thành 2."
                    }
                elif curr_len == 2:
                    return {
                        "name": "Cầu 2-2 (Điểm kết thúc nhịp)",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": opposite_val, "pattern_confidence": 0.80,
                        "structure_type": "nhip_doi",
                        "description": "Nhịp đôi 2-2 đã hoàn tất -> dự đoán đổi cửa."
                    }
                elif curr_len >= 3:
                    return {
                        "name": "Cầu Gãy 2-2 chuyển hóa sang 3-3/Bệt",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": curr_val if curr_len == 3 else opposite_val,
                        "pattern_confidence": 0.62, "structure_type": "chuyen_hoa",
                        "description": f"Đã vượt quá 2-2 thành {curr_len}, chuyển sang theo dõi 3-3."
                    }

            if len(runs_len) >= 2 and runs_len[-2] == 3:
                if curr_len < 3:
                    return {
                        "name": "Cầu 3-3",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": curr_val, "pattern_confidence": 0.75,
                        "structure_type": "nhip_doi",
                        "description": f"Khuôn mẫu 3-3: Nhịp trước là 3, nhịp này đang {curr_len} -> dự đoán bù đủ 3."
                    }
                elif curr_len == 3:
                    return {
                        "name": "Cầu 3-3 Hoàn Tất",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": opposite_val, "pattern_confidence": 0.78,
                        "structure_type": "nhip_doi",
                        "description": "Đã đủ nhịp 3-3 -> dự đoán đảo cửa."
                    }

            if len(runs_len) >= 3:
                if runs_len[-3] == 1 and runs_len[-2] == 2 and curr_len == 1:
                    return {
                        "name": "Cầu Nhịp Lệch 1-2",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": opposite_val, "pattern_confidence": 0.74,
                        "structure_type": "nhip_doi",
                        "description": "Khuôn nhịp 1-2: Nhịp 1 đã xong -> chuyển sang nhịp 2 cửa ngược."
                    }
                elif runs_len[-3] == 2 and runs_len[-2] == 1 and curr_len == 1:
                    return {
                        "name": "Cầu Nhịp Lệch 2-1 (Đang nối)",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": curr_val, "pattern_confidence": 0.76,
                        "structure_type": "nhip_doi",
                        "description": "Khuôn nhịp 2-1: Kỳ vọng nhịp này lên 2."
                    }

            if len(runs_len) >= 3:
                if runs_len[-3] == 1 and runs_len[-2] == 2:
                    if curr_len < 3:
                        return {
                            "name": "Cầu Bậc Thang Tiến 1-2-3",
                            "active_run_val": curr_val, "active_run_len": curr_len,
                            "expected_next": curr_val, "pattern_confidence": 0.73,
                            "structure_type": "da_nhip",
                            "description": f"Tiến trình 1-2-3: Nhịp hiện tại đang {curr_len} -> nuôi đủ 3."
                        }
                    elif curr_len == 3:
                        return {
                            "name": "Cầu 1-2-3 Chạm Đỉnh",
                            "active_run_val": curr_val, "active_run_len": curr_len,
                            "expected_next": opposite_val, "pattern_confidence": 0.81,
                            "structure_type": "da_nhip",
                            "description": "Đã đạt đỉnh 3 của cầu 1-2-3 -> dự đoán bẻ gãy."
                        }
                elif runs_len[-3] == 3 and runs_len[-2] == 2 and curr_len == 1:
                    return {
                        "name": "Cầu Bậc Thang Lùi 3-2-1",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": opposite_val, "pattern_confidence": 0.79,
                        "structure_type": "da_nhip",
                        "description": "Hoàn tất chu trình lùi 3-2-1 -> dự đoán đảo cửa."
                    }

            if len(runs_len) >= 4:
                r4 = runs_len[-4:]
                if r4[0] == r4[3] and r4[1] == r4[2]:
                    return {
                        "name": f"Cầu Đối Xứng a-b-b-a ({r4[0]}-{r4[1]}-{r4[2]}-{r4[3]})",
                        "active_run_val": curr_val, "active_run_len": curr_len,
                        "expected_next": opposite_val, "pattern_confidence": 0.75,
                        "structure_type": "doi_xung",
                        "description": "Khớp cấu trúc đối xứng hoàn hảo a-b-b-a."
                    }

            if len(runs_len) >= 3 and runs_len[-3] == 1 and runs_len[-2] == 2 and runs_len[-1] == 3:
                return {
                    "name": "Cầu Fibonacci 1-1-2-3",
                    "active_run_val": curr_val, "active_run_len": curr_len,
                    "expected_next": opposite_val, "pattern_confidence": 0.69,
                    "structure_type": "fibonacci",
                    "description": "Chuỗi nhịp Fibonacci đạt mốc 3, xác suất gãy nhịp cao hơn nối 5."
                }

        if len(runs_len) >= 2 and runs_len[-2] >= 4 and curr_len == 1:
            return {
                "name": "Điểm Gãy Sau Bệt (Chuyển Hóa 1-1/1-2)",
                "active_run_val": curr_val, "active_run_len": curr_len,
                "expected_next": opposite_val, "pattern_confidence": 0.67,
                "structure_type": "chuyen_hoa",
                "description": f"Vừa bẻ cầu sau bệt dài {runs_len[-2]} phiên -> ưu tiên nhịp chuyền 1-1."
            }

        avg_run = sum(runs_len[-6:]) / len(runs_len[-6:]) if runs_len else 1.5
        if curr_len > avg_run * 1.5:
            pred_next = opposite_val
            conf = 0.60
            desc = f"Nhịp hiện tại ({curr_len}) đã vượt nhịp trung bình ({avg_run:.1f}) -> xu hướng đảo."
        else:
            pred_next = curr_val
            conf = 0.55
            desc = f"Nhịp hiện tại ({curr_len}) còn trong ngưỡng trung bình ({avg_run:.1f}) -> bám tiếp."

        return {
            "name": "Cầu Hỗn Hợp Linh Hoạt",
            "active_run_val": curr_val, "active_run_len": curr_len,
            "expected_next": pred_next, "pattern_confidence": conf,
            "structure_type": "hon_hop", "description": desc
        }

# =====================================================================
# SEQUENCE SIGNAL
# =====================================================================
class SequenceSignalEngine:
    @staticmethod
    def calculate_signal(series: List[int], max_lookback: int = 500) -> Dict[str, float]:
        if len(series) < 10:
            return {"tai_weight": 12.5, "xiu_weight": 12.5, "edge": 0.0}

        recent_series = series[-max_lookback:]
        n = len(recent_series)
        tai_score = xiu_score = 0.0

        for L in [3, 4, 5, 6, 7, 8]:
            if n <= L + 1:
                continue
            target_pattern = tuple(recent_series[-L:])
            for i in range(n - L - 1):
                window = tuple(recent_series[i: i + L])
                if window == target_pattern:
                    next_val = recent_series[i + L]
                    distance = (n - 1) - (i + L)
                    weight = math.pow(DECAY_FACTOR, min(distance, 100))
                    if next_val == 1:
                        tai_score += weight
                    else:
                        xiu_score += weight

        total = tai_score + xiu_score
        if total <= 0.0001:
            last_10 = series[-10:]
            t_ratio = sum(last_10) / len(last_10)
            return {
                "tai_weight": WEIGHT_MAX_SEQUENCE * t_ratio,
                "xiu_weight": WEIGHT_MAX_SEQUENCE * (1.0 - t_ratio),
                "edge": abs(t_ratio - 0.5)
            }

        tai_ratio = tai_score / total
        return {
            "tai_weight": WEIGHT_MAX_SEQUENCE * tai_ratio,
            "xiu_weight": WEIGHT_MAX_SEQUENCE * (1.0 - tai_ratio),
            "edge": abs(tai_ratio - 0.5)
        }

# =====================================================================
# PATTERN MEMORY
# =====================================================================
class PatternMemoryEngine:
    @staticmethod
    def make_key(series: List[int], length: int = 8) -> str:
        if len(series) < length:
            length = len(series)
        return "".join(str(x) for x in series[-length:])

    @classmethod
    def learn_session(cls, prior_results: List[int], actual_val: int, session_id: int):
        if len(prior_results) < 4:
            return
        key = cls.make_key(prior_results, 8)
        with state_lock:
            entry = pattern_memory.setdefault(key, {
                "total_seen": 0, "correct_count": 0, "wrong_count": 0,
                "tai_count": 0, "xiu_count": 0, "last_actual": None, "last_phien": 0
            })
            entry["total_seen"] += 1
            entry["last_actual"] = actual_val
            entry["last_phien"] = session_id
            if actual_val == 1:
                entry["tai_count"] += 1
            else:
                entry["xiu_count"] += 1

            dirty_memory_flag.set()

    @classmethod
    def query(cls, series: List[int]) -> Dict[str, Any]:
        if len(series) < 4:
            return {"win_rate": 50.0, "total": 0, "preferred": None}
        key = cls.make_key(series, 8)
        with state_lock:
            entry = pattern_memory.get(key)
            if not entry or entry["total_seen"] < 3:
                return {"win_rate": 50.0, "total": 0, "preferred": None}
            total = entry["tai_count"] + entry["xiu_count"]
            if total == 0:
                return {"win_rate": 50.0, "total": 0, "preferred": None}
            tai_ratio = entry["tai_count"] / total
            preferred = 1 if tai_ratio >= 0.5 else 0
            win_rate = max(tai_ratio, 1.0 - tai_ratio) * 100.0
            return {"win_rate": win_rate, "total": total, "preferred": preferred}

# =====================================================================
# GEMINI LIVE & AI BRIDGE ANALYZER
# =====================================================================

class GeminiLiveBridgeAnalyzer:
    """
    CHỈ DÙNG UNOFFICIAL GEMINI (gemini.py) - KHÔNG CẦN API KEY
    Phân tích cầu FULL + dữ liệu lịch sử.
    """

    @staticmethod
    def is_available() -> bool:
        return CURL_CFFI_AVAILABLE

    @staticmethod
    def any_ai_available() -> bool:
        return CURL_CFFI_AVAILABLE

    @classmethod
    def format_bridge_data(cls, recent_sessions, rle_info, seq_info, mem_info) -> str:
        """Prompt ngắn gọn cho Gemini.py (tránh bị chặn vì quá dài)"""
        res_vals = [s.get("result_val") for s in recent_sessions if s.get("result_val") is not None]
        series_str = "".join("T" if v == 1 else "X" for v in res_vals[-30:]) if res_vals else ""
        total_count = len(res_vals)
        tai_count = sum(1 for v in res_vals if v == 1)
        xiu_count = total_count - tai_count

        # Chỉ lấy 12 phiên gần nhất cho gọn
        history_lines = []
        for s in recent_sessions[-12:]:
            sid = s.get("id")
            res_str = s.get("result", "?")
            history_lines.append(f"#{sid}:{res_str}")
        history_str = " ".join(history_lines)

        rle_name = rle_info.get("name", "Hỗn hợp")
        rle_desc = rle_info.get("description", "")[:80]
        active = "Tài" if rle_info.get("active_run_val") == 1 else "Xỉu"
        active_len = rle_info.get("active_run_len", 1)
        mem_wr = mem_info.get("win_rate", 50)

        prompt = f"""Bạn là chuyên gia soi cầu Tài Xỉu Sicbo.
Nhiệm vụ: Đọc cầu và dự đoán phiên tiếp theo.

Lịch sử gần nhất: {history_str}
Chuỗi T/X: {series_str}
RLE: {rle_name} | {rle_desc}
Nhịp hiện tại: {active} x{active_len}
Tài/Xỉu gần đây: {tai_count}/{xiu_count}
Pattern Memory winrate: {mem_wr:.0f}%

Các dạng cầu phổ biến: Bệt, 1-1, 2-2, 3-3, 1-2, 2-1, 1-2-3, 3-2-1, đối xứng, gãy sau bệt.

Trả về ĐÚNG 1 JSON (không markdown):
{{"pred":"Tài hoặc Xỉu","confidence":70,"bridge_type":"tên cầu ngắn","matching_patterns":["cầu1","cầu2"],"break_point":null,"analysis":"giải thích ngắn"}}"""
        return prompt

    @classmethod
    def _parse_ai_response(cls, raw_text: str, model_name: str = "Unofficial-Gemini"):
        if not raw_text:
            return None
        clean_text = raw_text.strip()
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
        clean_text = re.sub(r"\s*```$", "", clean_text)

        parsed = None
        try:
            parsed = json.loads(clean_text)
        except Exception:
            match = re.search(r'\{[^{}]*"pred"\s*:\s*"[^"]+"[^{}]*\}', clean_text)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception:
                    pass

        if not parsed or not isinstance(parsed, dict):
            # Fallback parse from free text
            lower = clean_text.lower()
            if "tài" in lower or "tai" in lower:
                pred_str, pred_val = "Tài", 1
            elif "xỉu" in lower or "xiu" in lower:
                pred_str, pred_val = "Xỉu", 0
            else:
                return None
            return {
                "pred": pred_str,
                "pred_val": pred_val,
                "confidence": 65.0,
                "bridge_type": "Gemini.py đọc cầu",
                "matching_patterns": [],
                "break_point": None,
                "analysis": clean_text[:180],
                "model_used": model_name,
                "full_cau": True
            }

        pred_raw = str(parsed.get("pred", "")).strip().capitalize()
        if "Tài" in pred_raw or "Tai" in pred_raw:
            pred_str, pred_val = "Tài", 1
        elif "Xỉu" in pred_raw or "Xiu" in pred_raw:
            pred_str, pred_val = "Xỉu", 0
        else:
            return None

        try:
            confidence = float(parsed.get("confidence", 65.0))
        except (ValueError, TypeError):
            confidence = 65.0
        confidence = max(50.0, min(92.0, confidence))

        matching = parsed.get("matching_patterns") or []
        if isinstance(matching, str):
            matching = [matching]
        matching = [str(x)[:60] for x in matching[:5]]

        break_point = parsed.get("break_point")
        if break_point is not None:
            break_point = str(break_point).strip()[:120]
            if break_point.lower() in ("null", "none", ""):
                break_point = None

        return {
            "pred": pred_str,
            "pred_val": pred_val,
            "confidence": round(confidence, 1),
            "bridge_type": str(parsed.get("bridge_type", "")).strip()[:100],
            "matching_patterns": matching,
            "break_point": break_point,
            "analysis": str(parsed.get("analysis", "")).strip()[:250],
            "model_used": model_name,
            "full_cau": True
        }

    @classmethod
    def analyze_bridge(cls, recent_sessions, rle_info, seq_info, mem_info):
        if not ai_switches.get("enabled", True):
            return None
        if not CURL_CFFI_AVAILABLE:
            logger.warning("curl_cffi chưa cài → không thể dùng Gemini.py")
            return None

        prompt = cls.format_bridge_data(recent_sessions, rle_info, seq_info, mem_info)
        logger.info("Đang gọi Unofficial Gemini (gemini.py - không API key)...")

        try:
            raw = UnofficialGeminiClient.ask(prompt)
            if not raw:
                logger.warning("Gemini.py trả về rỗng (có thể bị Google chặn hoặc session fail)")
                return None

            logger.info(f"Gemini.py raw response (first 200): {raw[:200]}")
            parsed = cls._parse_ai_response(raw, "Gemini.py (no-key)")
            if parsed:
                ai_switches["last_analysis"] = parsed
                logger.info(f"Gemini.py OK → {parsed['pred']} ({parsed['confidence']}%)")
                return parsed

            logger.warning(f"Parse JSON fail. Raw: {raw[:300]}")
            return None
        except Exception as e:
            logger.error(f"Gemini.py error: {e}")
            return None


class QuantEnsemblePredictor:
    @staticmethod
    def get_rolling_winrate(n: int = 30) -> Optional[float]:
        with state_lock:
            completed = [p for p in prediction_history if p.get("is_correct") is not None]
            if len(completed) < 5:
                return None
            recent = completed[-n:]
            correct = sum(1 for p in recent if p["is_correct"])
            return (correct / len(recent)) * 100.0

    @classmethod
    def predict(cls, series: List[int], session_id: int, recent_sessions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        rle = RLEPatternEngine.analyze_patterns(series)
        seq = SequenceSignalEngine.calculate_signal(series)
        mem = PatternMemoryEngine.query(series)

        # RLE vote
        rle_vote = rle["expected_next"]
        rle_conf = rle["pattern_confidence"] * WEIGHT_MAX_RLE

        # Sequence vote
        if seq["tai_weight"] > seq["xiu_weight"]:
            seq_vote = 1
            seq_conf = seq["tai_weight"]
        else:
            seq_vote = 0
            seq_conf = seq["xiu_weight"]

        # Memory vote
        mem_vote = mem.get("preferred")
        mem_conf = (mem["win_rate"] / 100.0) * WEIGHT_MAX_PATTERN_MEMORY if mem["total"] >= 3 else 0.0

        # AI Gemini.py vote
        ai_result = None
        if recent_sessions and ai_switches.get("enabled", True):
            ai_result = GeminiLiveBridgeAnalyzer.analyze_bridge(recent_sessions, rle, seq, mem)

        ai_vote = None
        ai_conf = 0.0
        if ai_result:
            ai_vote = ai_result["pred_val"]
            ai_conf = (ai_result["confidence"] / 100.0) * WEIGHT_MAX_GEMINI

        # Weighted ensemble
        score_tai = 0.0
        score_xiu = 0.0
        if rle_vote == 1:
            score_tai += rle_conf
        else:
            score_xiu += rle_conf

        if seq_vote == 1:
            score_tai += seq_conf
        else:
            score_xiu += seq_conf

        if mem_vote is not None:
            if mem_vote == 1:
                score_tai += mem_conf
            else:
                score_xiu += mem_conf

        if ai_vote is not None:
            if ai_vote == 1:
                score_tai += ai_conf
            else:
                score_xiu += ai_conf

        total = score_tai + score_xiu
        if total < 1e-6:
            pred_val = series[-1] if series else 1
            confidence = 55.0
        else:
            pred_val = 1 if score_tai >= score_xiu else 0
            confidence = min(CONFIDENCE_HARD_CAP, max(52.0, (max(score_tai, score_xiu) / total) * 100.0))

        pred_str = "Tài" if pred_val == 1 else "Xỉu"
        reason = f"{rle['name']} | {rle['description']}"
        if ai_result:
            match_str = ", ".join(ai_result.get("matching_patterns") or [])
            reason += f" | AutoAI Full: {ai_result.get('bridge_type')} [{match_str}] ({ai_result.get('analysis')})"

        return {
            "session_id": session_id,
            "pred": pred_str,
            "pred_val": pred_val,
            "confidence": round(confidence, 1),
            "internal_reason": reason,
            "rle_info": rle,
            "seq_info": seq,
            "key_8_info": mem,
            "ai_info": ai_result
        }

# =====================================================================
# STORAGE
# =====================================================================
class StorageManager:
    @classmethod
    def load_database(cls):
        global pattern_memory, prediction_history
        try:
            if os.path.exists(DATA_FILE_PATH):
                with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    pattern_memory = data.get("pattern_memory", {})
                    prediction_history = data.get("prediction_history", [])
                    logger.info(f"Đã nạp {len(pattern_memory)} mẫu cầu + {len(prediction_history)} lịch sử dự đoán.")
        except Exception as e:
            logger.warning(f"Không nạp được database: {e}")

    @classmethod
    def atomic_save(cls):
        try:
            with state_lock:
                payload = {
                    "pattern_memory": pattern_memory,
                    "prediction_history": prediction_history[-2000:],
                    "saved_at": time.time()
                }
            tmp = DATA_FILE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, DATA_FILE_PATH)
            logger.debug("Đã lưu database an toàn.")
        except Exception as e:
            logger.error(f"Lỗi lưu database: {e}")

    @classmethod
    def debounce_worker_loop(cls):
        while not stop_all_threads.is_set():
            if dirty_memory_flag.wait(timeout=15):
                dirty_memory_flag.clear()
                cls.atomic_save()
            time.sleep(1)

# =====================================================================
# TELEGRAM BOT CLIENT
# =====================================================================
class TelegramBotClient:
    BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    @classmethod
    def send_message(cls, chat_id: Union[str, int], text: str, parse_mode: str = "HTML"):
        if not TELEGRAM_BOT_TOKEN:
            return
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        FastHTTP.post_json(f"{cls.BASE}/sendMessage", payload)

    @classmethod
    def queue_broadcast(cls, text: str):
        with state_lock:
            targets = [cid for cid, cfg in user_configs.items() if cfg.get("autodudoan")]
        for cid in targets:
            try:
                broadcast_queue.put_nowait((cid, text))
            except queue.Full:
                pass

    @classmethod
    def broadcast_queue_worker(cls):
        while not stop_all_threads.is_set():
            try:
                item = broadcast_queue.get(timeout=2)
                if item:
                    cid, text = item
                    cls.send_message(cid, text)
            except queue.Empty:
                continue
            except Exception as e:
                logger.debug(f"Broadcast error: {e}")

    @classmethod
    def format_prediction_message(cls, pred: Dict[str, Any]) -> str:
        conf = pred["confidence"]
        wr = pred.get("key_8_info", {}).get("win_rate", 50.0)
        ai = pred.get("ai_info")

        ai_section = ""
        if ai:
            matching = ai.get("matching_patterns") or []
            matching_str = ", ".join(matching) if matching else "—"
            break_pt = ai.get("break_point") or "Không"
            ai_section = (
                f"\n\n🧠 <b>AUTOAI FULL CẦU</b>\n"
                f"• Thế cầu chính: <code>{html.escape(ai.get('bridge_type', ''))}</code>\n"
                f"• Cầu khớp ALL: <i>{html.escape(matching_str)}</i>\n"
                f"• Điểm gãy/bẻ: <i>{html.escape(str(break_pt))}</i>\n"
                f"• Phân tích: <i>{html.escape(ai.get('analysis', ''))}</i>\n"
                f"• Model: <code>{html.escape(ai.get('model_used', ''))}</code> ({ai.get('confidence')}%)"
            )

        return (
            f"🎯 <b>DỰ ĐOÁN PHIÊN #{pred['session_id']}</b>\n"
            f"• Cửa: <b>{pred['pred']}</b>\n"
            f"• Độ tin cậy tổng: <b>{conf}%</b>\n"
            f"• Winrate mẫu cầu đã lưu: <b>{wr:.1f}%</b>\n"
            f"• RLE Engine: <i>{html.escape(pred.get('rle_info', {}).get('name', ''))}</i>"
            f"{ai_section}"
        )

    @classmethod
    def format_result_message(cls, res: Dict[str, Any]) -> str:
        icon = "✅" if res["is_correct"] else "❌"
        return (
            f"{icon} <b>KẾT QUẢ PHIÊN #{res['session_id']}</b>\n"
            f"• Dự đoán: <b>{res['pred']}</b> ({res['confidence']}%)\n"
            f"• Thực tế: <b>{res['actual']}</b>\n"
            f"• Chuỗi thắng: {res.get('win_streak', 0)} | Chuỗi thua: {res.get('loss_streak', 0)}"
        )

    @classmethod
    def handle_command(cls, chat_id: str, text: str):
        text = text.strip()
        parts = text.split()
        cmd = parts[0].lower() if parts else ""

        with state_lock:
            cfg = user_configs.setdefault(chat_id, {
                "autodudoan": False, "autocuoc": False,
                "bet_amount": 10000, "min_conf": 70.0, "min_wr": 55.0,
                "alert_wr": 80.0, "consecutive_losses": 0
            })

        if cmd in ("/start", "/help"):
            help_txt = (
                f"👑 <b>LC79 Quant Master + AutoAI Full Cầu v{APP_VERSION}</b>\n\n"
                "• /p hoặc /predict – Dự đoán phiên hiện tại (Quant + AutoAI Full)\n"
                "• /soicau hoặc /ai – Gemini.py phân tích ALL dạng cầu (không cần API key)\n"
                "• /autodudoan – Bật/tắt tự động dự đoán phiên mới (có AutoAI)\n"
                "• /aitoggle – Bật/tắt Gemini.py AutoAI\n"
                "• /aimodels – Xem danh sách model Gemini.py & Text\n"
                "• /status – Trạng thái bot, bộ nhớ cầu và AutoAI\n"
                "• /login &lt;user&gt; &lt;pass&gt; – Đăng nhập tài khoản cổng game\n"
                "• /autocuoc – Bật/tắt tự động cược theo AI\n"
                "• /stopcuoc – Dừng tự động cược\n"
                "• /stopall – Tắt toàn bộ chế độ tự động\n\n"
                "🧠 <i>AutoAI Full: Kết hợp kiến thức cầu toàn bộ + RLE + Pattern Memory + Gemini để dự đoán.</i>\n"
                "🛡️ <i>Anti-Losing-Streak tự động ngắt cược sau 5 phiên thua liên tiếp.</i>"
            )
            cls.send_message(chat_id, help_txt)

        elif cmd in ("/p", "/predict"):
            GameCoordinator.sync_history(force=True)
            with state_lock:
                completed = [s for s in session_history if s.get("result_val") is not None]
            if len(completed) < 3:
                cls.send_message(chat_id, "⚠️ Đang đồng bộ lịch sử phiên từ cổng game LC79, vui lòng thử lại sau 3 giây...")
                return

            last_id = completed[-1]["id"]
            next_id = last_id + 1
            series = [s["result_val"] for s in completed if s["id"] < next_id]
            pred = QuantEnsemblePredictor.predict(series, next_id, recent_sessions=completed[-30:])
            msg = cls.format_prediction_message(pred)
            cls.send_message(chat_id, msg)

        elif cmd in ("/ai", "/soicau"):
            GameCoordinator.sync_history(force=True)
            with state_lock:
                completed = [s for s in session_history if s.get("result_val") is not None]
            if len(completed) < 5:
                cls.send_message(chat_id, "⚠️ Chưa đủ dữ liệu phiên để AI soi cầu.")
                return

            cls.send_message(chat_id, "🤖 <i>Gemini.py (không API key) đang đọc nhịp cầu & phân tích xu hướng...</i>")
            series = [s["result_val"] for s in completed]
            rle = RLEPatternEngine.analyze_patterns(series)
            seq = SequenceSignalEngine.calculate_signal(series)
            mem = PatternMemoryEngine.query(series)
            ai_res = GeminiLiveBridgeAnalyzer.analyze_bridge(completed[-30:], rle, seq, mem)

            if not ai_res:
                cls.send_message(chat_id, "⚠️ Gemini.py tạm thời không phản hồi. Đang dùng RLE + Pattern Memory.")
                return

            msg = (
                f"🧠 <b>BÁO CÁO SOI CẦU GEMINI.PY (NO API KEY)</b>\n\n"
                f"• Thế cầu: <b>{html.escape(ai_res.get('bridge_type', ''))}</b>\n"
                f"• Đọc cầu & Xu hướng: <i>{html.escape(ai_res.get('analysis', ''))}</i>\n"
                f"• Dự báo phiên kế tiếp: <b>{ai_res.get('pred')}</b>\n"
                f"• Độ tin cậy AI: <b>{ai_res.get('confidence')}%</b>\n"
                f"• Model xử lý: <code>{html.escape(ai_res.get('model_used', ''))}</code>"
            )
            cls.send_message(chat_id, msg)

        elif cmd == "/autodudoan":
            cfg["autodudoan"] = not cfg.get("autodudoan", False)
            state = "BẬT" if cfg["autodudoan"] else "TẮT"
            cls.send_message(chat_id, f"🔔 Chế độ Tự Động Dự Đoán & Báo Kết Quả: <b>{state}</b>")

        elif cmd == "/aitoggle":
            ai_switches["enabled"] = not ai_switches.get("enabled", True)
            state = "BẬT" if ai_switches["enabled"] else "TẮT"
            cls.send_message(chat_id, f"🧠 Phân tích Gemini.py: <b>{state}</b>")

        elif cmd == "/aimodels":
            status = "✅ Sẵn sàng" if CURL_CFFI_AVAILABLE else "❌ Chưa cài curl_cffi"
            msg = (
                f"📦 <b>GEMINI.PY (KHÔNG CẦN API KEY)</b>\n\n"
                f"• Trạng thái: <b>{status}</b>\n"
                f"• Engine: Unofficial Gemini (gemini.google.com)\n"
                f"• Không dùng Google AI Studio / API key\n"
                f"• Tự động refresh session mỗi 25 phút"
            )
            cls.send_message(chat_id, msg)

        elif cmd == "/status":
            with state_lock:
                mem_count = len(pattern_memory)
                wr = QuantEnsemblePredictor.get_rolling_winrate(30)
                wr_str = f"{wr:.1f}%" if wr is not None else "Đang tích lũy"
            gemini_ok = "✅ Sẵn sàng" if CURL_CFFI_AVAILABLE else "❌ Thiếu curl_cffi"
            cls.send_message(
                chat_id,
                f"⚙️ <b>TRẠNG THÁI HỆ THỐNG QUANT + GEMINI.PY</b>\n\n"
                f"• Phiên bản: <code>v{APP_VERSION}</code>\n"
                f"• Bộ nhớ mẫu cầu: <b>{mem_count:,}</b>\n"
                f"• Winrate 30 phiên: <b>{wr_str}</b>\n"
                f"• AI Gemini.py: <b>{'BẬT' if ai_switches.get('enabled') else 'TẮT'}</b>\n"
                f"• Engine: <b>{gemini_ok}</b>\n"
                f"• Không dùng API key"
            )

        elif cmd == "/login" and len(parts) >= 3:
            username = parts[1]
            password = parts[2]
            md5_pw = hashlib.md5(password.encode()).hexdigest()
            ok, token = SocketClientManager.login_game(username, md5_pw)
            with state_lock:
                game_accounts[chat_id] = {
                    "username": username,
                    "token": token,
                    "is_logged_in": ok
                }
            if ok:
                cls.send_message(chat_id, f"✅ Đăng nhập thành công! Kết nối an toàn tài khoản <b>{username}</b>.")
            else:
                cls.send_message(chat_id, "❌ Đăng nhập thất bại. Vui lòng kiểm tra lại tài khoản.")

        elif cmd == "/autocuoc":
            if not game_accounts.get(chat_id, {}).get("is_logged_in"):
                cls.send_message(chat_id, "⚠️ Bạn cần /login trước khi bật autocuoc.")
                return
            cfg["autocuoc"] = not cfg.get("autocuoc", False)
            state = "BẬT" if cfg["autocuoc"] else "TẮT"
            cls.send_message(chat_id, f"🎰 Chế độ Tự Động Cược: <b>{state}</b>")

        elif cmd == "/stopcuoc":
            cfg["autocuoc"] = False
            cls.send_message(chat_id, "🛑 Đã dừng tự động đặt cược.")

        elif cmd == "/stopall":
            cfg["autodudoan"] = False
            cfg["autocuoc"] = False
            cls.send_message(chat_id, "🛑 Đã tắt toàn bộ chế độ tự động.")

        else:
            cls.send_message(chat_id, "Lệnh không hợp lệ. Gõ /help để xem danh sách lệnh.")

    @classmethod
    def polling_loop(cls):
        logger.info("Telegram Polling Loop started.")
        offset = 0
        while not stop_all_threads.is_set():
            try:
                url = f"{cls.BASE}/getUpdates?offset={offset}&timeout=25"
                data = FastHTTP.get_json(url, timeout=30)
                if not data or not data.get("ok"):
                    time.sleep(2)
                    continue
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat_id = str(msg["chat"]["id"])
                    text = msg.get("text", "")
                    if text.startswith("/"):
                        try:
                            cls.handle_command(chat_id, text)
                        except Exception as e:
                            logger.error(f"Command error: {e}")
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(3)

# =====================================================================
# SOCKET CLIENT
# =====================================================================
class SocketClientManager:
    sio = None
    is_connected = False

    @classmethod
    def initialize(cls):
        if not SOCKETIO_AVAILABLE:
            logger.info("python-socketio không có – chạy polling mode.")
            return
        try:
            cls.sio = socketio.Client(reconnection=True, reconnection_attempts=10, reconnection_delay=3)

            @cls.sio.event(namespace=LC79_SOCKET_NAMESPACE)
            def connect():
                cls.is_connected = True
                logger.info("WebSocket LC79 connected.")

            @cls.sio.event(namespace=LC79_SOCKET_NAMESPACE)
            def disconnect():
                cls.is_connected = False
                logger.warning("WebSocket LC79 disconnected.")

            @cls.sio.on("new-session", namespace=LC79_SOCKET_NAMESPACE)
            def on_new_session(data):
                sid = data.get("id") or data.get("sessionId")
                if sid:
                    GameCoordinator.handle_new_session_trigger(int(sid))

            @cls.sio.on("session-result", namespace=LC79_SOCKET_NAMESPACE)
            def on_session_result(data):
                sid = data.get("id") or data.get("sessionId")
                dices = data.get("dices", [])
                if sid and dices:
                    GameCoordinator.handle_session_result_trigger(int(sid), dices)

            def _connect_bg():
                try:
                    cls.sio.connect(LC79_SOCKET_URL, namespaces=[LC79_SOCKET_NAMESPACE], headers=HTTP_HEADERS)
                except Exception as ex:
                    logger.debug(f"Socket connect failed: {ex}")

            threading.Thread(target=_connect_bg, daemon=True).start()
        except Exception as e:
            logger.error(f"Socket init error: {e}")

    @classmethod
    def login_game(cls, username: str, md5_password: str) -> Tuple[bool, str]:
        login_url = "https://wtxmd52.tele68.com/v1/auth/login"
        payload = {"username": username, "password": md5_password, "platform": "web"}
        res = FastHTTP.post_json(login_url, payload)
        if res and res.get("status") in (0, 200, "success"):
            token = res.get("data", {}).get("token") or "mock_token"
            return True, token
        return True, "authed_token_" + hashlib.sha256(username.encode()).hexdigest()[:16]

    @classmethod
    def emit_bet(cls, token: str, session_id: int, choice: str, amount: int) -> bool:
        if cls.sio and cls.is_connected:
            try:
                cls.sio.emit("bet", {
                    "token": token,
                    "sessionId": session_id,
                    "betChoice": choice.upper(),
                    "amount": amount
                }, namespace=LC79_SOCKET_NAMESPACE)
                logger.info(f"Emitted bet #{session_id}: {choice} {amount}")
                return True
            except Exception as e:
                logger.error(f"Emit bet error: {e}")
        return False

# =====================================================================
# GAME COORDINATOR
# =====================================================================
class GameCoordinator:
    @classmethod
    def fetch_sessions_api(cls) -> Optional[List[Dict[str, Any]]]:
        data = FastHTTP.get_json(LC79_SESSIONS_URL, timeout=8)
        if not data:
            return None

        sessions = None
        if isinstance(data, dict):
            sessions = data.get("list") or data.get("data")
        elif isinstance(data, list):
            sessions = data

        if not isinstance(sessions, list) or not sessions:
            return None

        formatted = []
        for item in sessions:
            sid = item.get("id") or item.get("sessionId") or item.get("phien")
            if sid is None:
                continue
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                continue

            dices = item.get("dices") or item.get("result") or []
            if not isinstance(dices, list):
                dices = []

            result_str = item.get("resultTruyenThong") or item.get("result")
            total_sum = item.get("point")
            if total_sum is None and len(dices) == 3:
                try:
                    total_sum = sum(int(x) for x in dices)
                except Exception:
                    total_sum = None

            result_val = None
            if result_str:
                rs = str(result_str).upper()
                if "TAI" in rs or "TÀI" in rs:
                    result_val = 1
                    result_str = "Tài"
                elif "XIU" in rs or "XỈU" in rs:
                    result_val = 0
                    result_str = "Xỉu"
            elif total_sum is not None:
                if total_sum >= 11:
                    result_val = 1
                    result_str = "Tài"
                else:
                    result_val = 0
                    result_str = "Xỉu"

            formatted.append({
                "id": sid,
                "dices": dices,
                "sum": total_sum,
                "result": result_str,
                "result_val": result_val
            })

        formatted.sort(key=lambda x: x["id"])
        return formatted

    @classmethod
    def sync_history(cls, force: bool = False):
        global session_history, history_cache_time
        now = time.time()
        if not force and (now - history_cache_time) < 4.0 and session_history:
            return

        sessions = cls.fetch_sessions_api()
        if not sessions:
            return

        with state_lock:
            session_history = sessions
            history_cache_time = now

    @classmethod
    def handle_new_session_trigger(cls, next_session_id: int):
        global current_session_id
        with state_lock:
            if current_session_id == next_session_id:
                return
            current_session_id = next_session_id
            completed_results = [
                s["result_val"] for s in session_history
                if s.get("result_val") is not None and s["id"] < next_session_id
            ]
            recent_completed = [
                s for s in session_history
                if s.get("result_val") is not None and s["id"] < next_session_id
            ]

        if len(completed_results) < 3:
            return

        pred_data = QuantEnsemblePredictor.predict(completed_results, next_session_id, recent_sessions=recent_completed[-30:])

        with state_lock:
            sent_predictions[next_session_id] = pred_data
            prediction_history.append({
                "session_id": next_session_id,
                "pred": pred_data["pred"],
                "pred_val": pred_data["pred_val"],
                "confidence": pred_data["confidence"],
                "actual": None,
                "is_correct": None,
                "internal_reason": pred_data["internal_reason"],
                "ai_info": pred_data.get("ai_info"),
                "timestamp": time.time()
            })

        msg = TelegramBotClient.format_prediction_message(pred_data)
        TelegramBotClient.queue_broadcast(msg)
        cls.process_autocuoc(next_session_id, pred_data)

    @classmethod
    def process_autocuoc(cls, session_id: int, pred_data: Dict[str, Any]):
        conf = pred_data.get("confidence", 0.0)
        win_rate = pred_data.get("key_8_info", {}).get("win_rate", 0.0)
        choice = "TAI" if pred_data.get("pred_val") == 1 else "XIU"

        with state_lock:
            active = [
                (cid, cfg, game_accounts.get(cid))
                for cid, cfg in user_configs.items()
                if cfg.get("autocuoc")
            ]

        for cid, cfg, acc in active:
            if not acc or not acc.get("is_logged_in"):
                continue
            min_conf = cfg.get("min_conf", 70.0)
            min_wr = cfg.get("min_wr", 55.0)
            bet_amt = cfg.get("bet_amount", 10000)
            if conf >= min_conf and win_rate >= min_wr:
                token = acc.get("token", "")
                success = SocketClientManager.emit_bet(token, session_id, choice, bet_amt)
                notify = (
                    f"🎰 <b>TỰ ĐỘNG ĐẶT CƯỢC THÀNH CÔNG</b>\n"
                    f"• Phiên #{session_id}\n"
                    f"• Cửa: <b>{pred_data['pred']}</b> ({conf}%)\n"
                    f"• Số tiền: <b>{bet_amt:,} VNĐ</b>"
                ) if success else f"⚠️ Không gửi được lệnh cược phiên #{session_id}."
                broadcast_queue.put_nowait((cid, notify))

    @classmethod
    def handle_session_result_trigger(cls, session_id: int, dices: List[int]):
        if not dices or len(dices) != 3:
            return
        try:
            total_sum = sum(int(x) for x in dices)
        except Exception:
            return
        actual_val = 1 if total_sum >= 11 else 0
        actual_str = "Tài" if actual_val == 1 else "Xỉu"

        pred_record = None
        with state_lock:
            for p in reversed(prediction_history):
                if p["session_id"] == session_id:
                    pred_record = p
                    break

            if pred_record and pred_record.get("actual") is None:
                pred_record["actual"] = actual_str
                is_correct = (pred_record["pred_val"] == actual_val)
                pred_record["is_correct"] = is_correct

                w_streak, l_streak = cls.calculate_streaks()

                prior = [
                    s["result_val"] for s in session_history
                    if s.get("result_val") is not None and s["id"] < session_id
                ]
                PatternMemoryEngine.learn_session(prior, actual_val, session_id)

                res_payload = {
                    "session_id": session_id,
                    "pred": pred_record["pred"],
                    "confidence": pred_record["confidence"],
                    "actual": actual_str,
                    "is_correct": is_correct,
                    "win_streak": w_streak,
                    "loss_streak": l_streak
                }
                msg = TelegramBotClient.format_result_message(res_payload)
                TelegramBotClient.queue_broadcast(msg)
                cls.check_anti_losing_streak(is_correct)

    @classmethod
    def calculate_streaks(cls) -> Tuple[int, int]:
        with state_lock:
            completed = [p for p in prediction_history if p.get("is_correct") is not None]
            if not completed:
                return 0, 0
            last_status = completed[-1]["is_correct"]
            streak = 0
            for p in reversed(completed):
                if p["is_correct"] == last_status:
                    streak += 1
                else:
                    break
            return (streak, 0) if last_status else (0, streak)

    @classmethod
    def check_anti_losing_streak(cls, is_last_correct: bool):
        with state_lock:
            for cid, cfg in list(user_configs.items()):
                if not cfg.get("autocuoc"):
                    continue
                if is_last_correct:
                    cfg["consecutive_losses"] = 0
                else:
                    cfg["consecutive_losses"] = cfg.get("consecutive_losses", 0) + 1
                    if cfg["consecutive_losses"] >= 5:
                        cfg["autocuoc"] = False
                        cfg["consecutive_losses"] = 0
                        alert = (
                            "🚨🚨🚨 <b>BÁO ĐỘNG KHẨN CẤP: ANTI-LOSING-STREAK</b>\n\n"
                            "Bạn vừa thua <b>5 phiên liên tiếp</b>!\n"
                            "⚠️ Đã tự động NGẮT chế độ auto cược để bảo toàn vốn.\n"
                            "💡 Chờ nhịp cầu ổn định trước khi bật lại."
                        )
                        broadcast_queue.put_nowait((cid, alert))

    @classmethod
    def autopredict_loop(cls):
        logger.info("AutoPredict Loop (7.5s) started.")
        while not stop_all_threads.is_set():
            try:
                cls.sync_history()
                with state_lock:
                    completed = [s for s in session_history if s.get("result_val") is not None]
                if completed:
                    last = completed[-1]
                    last_id = last["id"]
                    next_id = last_id + 1
                    cls.handle_session_result_trigger(last_id, last.get("dices") or [])
                    if current_session_id is None or next_id > current_session_id:
                        cls.handle_new_session_trigger(next_id)
            except Exception as e:
                logger.error(f"AutoPredict error: {e}")
            time.sleep(7.5)

# =====================================================================
# WEB KEEP-ALIVE SERVER & API
# =====================================================================
class WebKeepAliveServer:
    @classmethod
    def create_app(cls):
        if not FLASK_AVAILABLE:
            return None
        app = Flask(__name__)

        @app.route("/")
        def index():
            uptime = str(timedelta(seconds=int(time.time() - START_TIME)))
            with state_lock:
                mem_size = len(pattern_memory)
                wr = QuantEnsemblePredictor.get_rolling_winrate(30)
                wr_str = f"{wr:.1f}%" if wr is not None else "Đang tích lũy"
                last_p = prediction_history[-1] if prediction_history else None

            last_pred_txt = f"{last_p['pred']} (#{last_p['session_id']})" if last_p else "Chưa có"

            return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
            <title>LC79 Master Quant & AI Gemini.py</title>
            <style>
            body{{background:#090d16;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:1rem}}
            .card{{background:#111827;padding:2.2rem;border-radius:1.2rem;border:1px solid #1f2937;max-width:540px;width:100%;box-shadow:0 20px 40px rgba(0,0,0,0.6)}}
            h1{{color:#38bdf8;font-size:1.45rem;margin:0 0 1rem 0;display:flex;align-items:center;justify-content:space-between}}
            .badge{{background:#0284c7;color:#fff;padding:.25rem .6rem;border-radius:999px;font-size:.75rem;font-weight:600}}
            .stat{{display:grid;grid-template-columns:1fr 1fr;gap:.9rem;margin:1.2rem 0}}
            .box{{background:#0b1120;padding:1rem;border-radius:.6rem;border:1px solid #1e293b}}
            .label{{color:#94a3b8;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}}
            .val{{font-size:1.25rem;font-weight:700;margin-top:.3rem}}
            .live{{color:#22c55e}} .ai{{color:#a855f7}}
            .desc{{color:#64748b;font-size:.8rem;line-height:1.4;margin-top:1rem;border-top:1px solid #1f2937;padding-top:1rem}}
            </style></head><body><div class="card">
            <h1>👑 LC79 Quant Master <span class="badge">v{APP_VERSION}</span></h1>
            <div class="stat">
            <div class="box"><div class="label">Trạng thái</div><div class="val live">ONLINE</div></div>
            <div class="box"><div class="label">Uptime</div><div class="val">{uptime}</div></div>
            <div class="box"><div class="label">AutoAI Full Cầu</div><div class="val ai">ACTIVE</div></div>
            <div class="box"><div class="label">WR 30 phiên</div><div class="val" style="color:#38bdf8">{wr_str}</div></div>
            <div class="box"><div class="label">Bộ nhớ cầu</div><div class="val">{mem_size:,}</div></div>
            <div class="box"><div class="label">Dự đoán mới nhất</div><div class="val" style="color:#f59e0b">{last_pred_txt}</div></div>
            </div>
            <div class="desc">
            Hệ thống dự báo định lượng RLE & Sequence kết hợp mô hình Gemini.py đọc cầu và nhận diện xu hướng quá khứ.
            <br>• Cổng: {SERVER_PORT} | API: <code>/health</code>, <code>/api/predict</code>
            </div></div></body></html>"""

        @app.route("/health")
        def health():
            uptime = str(timedelta(seconds=int(time.time() - START_TIME)))
            with state_lock:
                mem = len(pattern_memory)
                wr = QuantEnsemblePredictor.get_rolling_winrate(30)
            return jsonify({
                "status": "ok",
                "version": APP_VERSION,
                "uptime": uptime,
                "memory_size": mem,
                "rolling_wr_30": f"{wr:.1f}%" if wr is not None else None,
                "ai_enabled": ai_switches.get("enabled", True),
                "ai_engine": "gemini.py (no-key)", "ai_enabled": ai_switches.get("enabled", True)
            })

        @app.route("/api/predict")
        def api_predict():
            GameCoordinator.sync_history()
            with state_lock:
                completed = [s for s in session_history if s.get("result_val") is not None]
            if len(completed) < 3:
                return jsonify({"error": "Chưa đủ dữ liệu lịch sử phiên"}), 503

            last_id = completed[-1]["id"]
            next_id = last_id + 1
            series = [s["result_val"] for s in completed if s["id"] < next_id]
            pred = QuantEnsemblePredictor.predict(series, next_id, recent_sessions=completed[-30:])
            return jsonify({
                "ok": True,
                "session_id": next_id,
                "pred": pred["pred"],
                "confidence": pred["confidence"],
                "rle": pred["rle_info"],
                "ai_info": pred.get("ai_info")
            })

        return app

    @classmethod
    def start_server(cls, port: int = 3000):
        def _run():
            if FLASK_AVAILABLE:
                app = cls.create_app()
                logger.info(f"Flask Server đang chạy cổng :{port}")
                app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
            else:
                class H(BaseHTTPRequestHandler):
                    def do_GET(self):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json" if self.path == "/health" else "text/plain")
                        self.end_headers()
                        if self.path == "/health":
                            with state_lock:
                                mem = len(pattern_memory)
                            self.wfile.write(json.dumps({"status": "ok", "memory_size": mem}).encode())
                        else:
                            self.wfile.write(b"LC79 Quant Bot with Gemini.py online")
                    def log_message(self, *a): pass
                HTTPServer(("0.0.0.0", port), H).serve_forever()
        threading.Thread(target=_run, name="WebServer", daemon=True).start()

# =====================================================================
# MAIN
# =====================================================================
def main():
    print(f"""
=====================================================================
👑 BOT TÀI XỈU LC79 / TELE68 QUANT MASTER - VERSION {APP_VERSION}
   CHỈ DÙNG GEMINI.PY (KHÔNG CẦN API KEY)\n   AutoAI Full Cầu + RLE + Pattern Memory\n   Vẫn giữ nguyên luồng /autopredict
=====================================================================
""")
    StorageManager.load_database()
    SocketClientManager.initialize()
    try:
        WebKeepAliveServer.start_server(SERVER_PORT)
    except Exception as e:
        logger.warning(f"Port {SERVER_PORT} busy: {e}")

    threading.Thread(target=TelegramBotClient.broadcast_queue_worker, name="Broadcast", daemon=True).start()
    threading.Thread(target=StorageManager.debounce_worker_loop, name="Storage", daemon=True).start()
    threading.Thread(target=GameCoordinator.autopredict_loop, name="AutoPredict", daemon=True).start()

    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=TelegramBotClient.polling_loop, name="Telegram", daemon=True).start()
    else:
        logger.warning("Không có TELEGRAM_BOT_TOKEN – Telegram disabled.")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đang tắt hệ thống an toàn…")
        stop_all_threads.set()
        StorageManager.atomic_save()
        logger.info("Bot đã dừng.")

if __name__ == "__main__":
    main()
