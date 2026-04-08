from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
import time
import uuid

# 创建 API 应用实例
app = FastAPI(title="Campus Blink API")

# 配置跨域 (CORS) - 允许前端访问后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 定义前端传过来的“气泡”数据结构
class Bubble(BaseModel):
    user_id: str
    lat: float
    lng: float
    icon: str
    text: str
    expire_minutes: int

# 模拟 Redis 数据库，用来存放所有气泡
bubbles_db = {}

# 存放所有正在进行中的聊天室 (修正了 Python 版本兼容性问题)
active_connections: Dict[str, List[WebSocket]] = {}

# 接口 1：用来测试服务器是否正常工作的探针
@app.get("/")
def read_root():
    return {"status": "success", "message": "太棒了，校内闪现 (Campus Blink) 后端已启动！"}

# 接口 2：接收前端发来的新气泡
@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    bubble_id = str(uuid.uuid4())
    expire_timestamp = time.time() + bubble.expire_minutes * 60
    
    bubble_data = {
        "id": bubble_id,
        "user_id": bubble.user_id,
        "lat": bubble.lat,
        "lng": bubble.lng,
        "icon": bubble.icon,
        "text": bubble.text,
        "expire_timestamp": expire_timestamp
    }
    
    bubbles_db[bubble_id] = bubble_data
    
    current_time = time.time()
    expired_bubbles = [bid for bid, bdata in bubbles_db.items() if current_time > bdata["expire_timestamp"]]
    for bid in expired_bubbles:
        del bubbles_db[bid]
        
    return {"status": "success", "message": "气泡接收成功！", "data": bubble_data}

# 接口 3：前端获取地图上所有活跃的气泡
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