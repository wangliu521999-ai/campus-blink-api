from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid
import json
import sqlite3
from contextlib import closing

app = FastAPI(title="Campus Blink API v1.7.1 - DB Realtime Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🗄️ 数据库初始化：建立保险柜
# ==========================================
DB_FILE = "campus_blink.db"

def init_db():
    with closing(sqlite3.connect(DB_FILE)) as conn:
        with conn:
            # 建立气泡表
            conn.execute('''CREATE TABLE IF NOT EXISTS bubbles (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                lat REAL,
                lng REAL,
                icon TEXT,
                text TEXT,
                expire_timestamp REAL,
                category TEXT,
                max_people INTEGER,
                start_time TEXT,
                end_time TEXT,
                current_people INTEGER DEFAULT 0
            )''')
            # 建立聊天记录表
            conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bubble_id TEXT,
                message TEXT,
                timestamp REAL
            )''')

init_db()

# ==========================================
# 🛡️ 安全防线：敏感词检查
# ==========================================
SENSITIVE_WORDS = ["诈骗", "兼职", "加微信", "赌博", "贷款", "色情", "代写"]

def check_sensitive(text: str) -> bool:
    for word in SENSITIVE_WORDS:
        if word in text: return True
    return False

class Bubble(BaseModel):
    user_id: str
    lat: float
    lng: float
    icon: str
    text: str
    expire_minutes: int
    category: str = "chat"
    max_people: int = 10 
    start_time: Optional[str] = None
    end_time: Optional[str] = None

# 实时连接管理（这个必须留在内存里）
active_connections: Dict[str, List[WebSocket]] = {}

@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    if check_sensitive(bubble.text) or check_sensitive(bubble.icon):
        raise HTTPException(status_code=400, detail="内容包含违规词汇")

    bubble_id = str(uuid.uuid4())
    expire_timestamp = time.time() + bubble.expire_minutes * 60
    
    with closing(sqlite3.connect(DB_FILE)) as conn:
        with conn:
            conn.execute('''INSERT INTO bubbles 
                (id, user_id, lat, lng, icon, text, expire_timestamp, category, max_people, start_time, end_time) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                (bubble_id, bubble.user_id, bubble.lat, bubble.lng, bubble.icon, 
                 bubble.text, expire_timestamp, bubble.category, bubble.max_people, 
                 bubble.start_time, bubble.end_time))
            
    return {"status": "success", "data": {"id": bubble_id}}

@app.get("/api/bubbles")
def get_bubbles(category: Optional[str] = None):
    current_time = time.time()
    with closing(sqlite3.connect(DB_FILE)) as conn:
        # 1. 自动清理过期数据
        with conn:
            conn.execute("DELETE FROM bubbles WHERE expire_timestamp < ?", (current_time,))
            conn.execute("DELETE FROM chat_history WHERE bubble_id NOT IN (SELECT id FROM bubbles)")
        
        # 2. 查询数据
        query = "SELECT * FROM bubbles"
        params = []
        if category and category != "all":
            query += " WHERE category = ?"
            params.append(category)
            
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        
        # ==========================================
        # 🚀 核心修复：动态获取真实的实时在线人数
        # ==========================================
        bubble_list = []
        for row in rows:
            b_dict = dict(row)
            # 从内存中查当前有几条 WebSocket 连接
            b_dict["current_people"] = len(active_connections.get(b_dict["id"], []))
            bubble_list.append(b_dict)
            
        return {"status": "success", "data": bubble_list}

@app.delete("/api/bubbles/{bubble_id}")
async def delete_bubble(bubble_id: str, user_id: str):
    with closing(sqlite3.connect(DB_FILE)) as conn:
        conn.row_factory = sqlite3.Row
        bubble = conn.execute("SELECT * FROM bubbles WHERE id = ?", (bubble_id,)).fetchone()
        
        if bubble and bubble["user_id"] == user_id:
            if bubble_id in active_connections:
                msg = json.dumps({"userId": "system", "text": "⚠️ 气泡已由发起人撤销。"})
                for ws in active_connections[bubble_id]:
                    await ws.send_text(msg)
            
            with conn:
                conn.execute("DELETE FROM bubbles WHERE id = ?", (bubble_id,))
                conn.execute("DELETE FROM chat_history WHERE bubble_id = ?", (bubble_id,))
            return {"status": "success"}
    raise HTTPException(status_code=403, detail="无权操作")

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    
    with closing(sqlite3.connect(DB_FILE)) as conn:
        conn.row_factory = sqlite3.Row
        bubble = conn.execute("SELECT * FROM bubbles WHERE id = ?", (bubble_id,)).fetchone()
        
        if not bubble:
            await websocket.send_text(json.dumps({"userId": "system", "text": "⚠️ 气泡已失效"}))
            await websocket.close(); return

        if bubble_id not in active_connections: active_connections[bubble_id] = []
        
        if len(active_connections[bubble_id]) >= bubble["max_people"]:
            await websocket.send_text(json.dumps({"userId": "system", "text": "❌ 房间已满员"}))
            await websocket.close(); return

        active_connections[bubble_id].append(websocket)
        
        # 获取历史消息
        history = conn.execute("SELECT message FROM chat_history WHERE bubble_id = ? ORDER BY id ASC", (bubble_id,)).fetchall()
        for row in history:
            await websocket.send_text(row["message"])

        # 系统欢迎语
        welcome_msg = json.dumps({"userId": "system", "text": "👋 一位校友加入了闪现..."})
        with conn:
            conn.execute("INSERT INTO chat_history (bubble_id, message, timestamp) VALUES (?, ?, ?)", 
                         (bubble_id, welcome_msg, time.time()))
        for connection in active_connections[bubble_id]:
            await connection.send_text(welcome_msg)

    try:
        while True:
            data = await websocket.receive_text()
            # 敏感词检查
            try:
                msg_obj = json.loads(data)
                user_text = msg_obj.get("text", "")
            except: user_text = data
                
            if check_sensitive(user_text):
                await websocket.send_text(json.dumps({"userId": "system", "text": "⚠️ 消息违规"}))
                continue

            # 持久化聊天记录
            with closing(sqlite3.connect(DB_FILE)) as conn:
                with conn:
                    conn.execute("INSERT INTO chat_history (bubble_id, message, timestamp) VALUES (?, ?, ?)", 
                                 (bubble_id, data, time.time()))
            
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[bubble_id].remove(websocket)