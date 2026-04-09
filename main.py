from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid

# 升级为 v1.2 分类约局版
app = FastAPI(title="Campus Blink API v1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= 🚀 改造：定义前端传过来的新“气泡”数据结构 =================
class Bubble(BaseModel):
    user_id: str
    lat: float
    lng: float
    icon: str
    text: str
    expire_minutes: int
    category: str = "chat"            # 新增：默认是 chat (吐槽/心情)，或者是 activity (约局)
    start_time: Optional[str] = None  # 新增：例如 "14:00" (非必填)
    end_time: Optional[str] = None    # 新增：例如 "16:00" (非必填)

bubbles_db = {}
active_connections: Dict[str, List[WebSocket]] = {}

# 防刷屏冷却系统
user_last_post_time: Dict[str, float] = {}
COOLDOWN_SECONDS = 10 # 冷却时间：10秒

@app.get("/")
def read_root():
    return {"status": "success", "message": "v1.2 分类约局版 (精确定位) 后端运行中！"}

@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    current_time = time.time()
    
    # 【安全拦截】检查该用户上次发送的时间
    if bubble.user_id in user_last_post_time:
        time_passed = current_time - user_last_post_time[bubble.user_id]
        if time_passed < COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail="你发得太快啦，请休息几秒钟再试！")
            
    # 记录这次成功发送的时间
    user_last_post_time[bubble.user_id] = current_time

    # 生成随机唯一 ID 和过期时间
    bubble_id = str(uuid.uuid4())
    expire_timestamp = current_time + bubble.expire_minutes * 60
    
    # ================= 🚀 改造：将新字段一并存入数据库 =================
    bubble_data = {
        "id": bubble_id,
        "user_id": bubble.user_id,
        "lat": bubble.lat,               # 恢复精确的真实坐标
        "lng": bubble.lng,               # 恢复精确的真实坐标
        "icon": bubble.icon,
        "text": bubble.text,
        "expire_timestamp": expire_timestamp,
        "category": bubble.category,     # 存入分类
        "start_time": bubble.start_time, # 存入开始时间
        "end_time": bubble.end_time      # 存入结束时间
    }
    
    bubbles_db[bubble_id] = bubble_data
    
    # 阅后即焚逻辑保持不变
    expired_bubbles = [bid for bid, bdata in bubbles_db.items() if current_time > bdata["expire_timestamp"]]
    for bid in expired_bubbles:
        del bubbles_db[bid]
        
    return {"status": "success", "message": "气泡发射成功！", "data": bubble_data}

@app.get("/api/bubbles")
def get_bubbles():
    return {"status": "success", "data": list(bubbles_db.values())}

# ================= 实时聊天室 (WebSocket) 逻辑 =================
@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    active_connections[bubble_id].append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[bubble_id].remove(websocket)
        if len(active_connections[bubble_id]) == 0:
            del active_connections[bubble_id]