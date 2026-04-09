from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid

app = FastAPI(title="Campus Blink API v1.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Bubble(BaseModel):
    user_id: str
    lat: float
    lng: float
    icon: str
    text: str
    expire_minutes: int
    category: str = "chat"
    start_time: Optional[str] = None
    end_time: Optional[str] = None

bubbles_db = {}
active_connections: Dict[str, List[WebSocket]] = {}

# ================= 🚀 新增：聊天历史记忆库 =================
chat_history_db: Dict[str, List[str]] = {}
user_last_post_time: Dict[str, float] = {}
COOLDOWN_SECONDS = 10 

@app.get("/")
def read_root():
    return {"status": "success", "message": "v1.3 拥有记忆的聊天室已上线！"}

@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    current_time = time.time()
    
    if bubble.user_id in user_last_post_time:
        if current_time - user_last_post_time[bubble.user_id] < COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail="你发得太快啦，请休息几秒钟再试！")
            
    user_last_post_time[bubble.user_id] = current_time

    bubble_id = str(uuid.uuid4())
    expire_timestamp = current_time + bubble.expire_minutes * 60
    
    bubble_data = {
        "id": bubble_id, "user_id": bubble.user_id,
        "lat": bubble.lat, "lng": bubble.lng,
        "icon": bubble.icon, "text": bubble.text,
        "expire_timestamp": expire_timestamp,
        "category": bubble.category, "start_time": bubble.start_time, "end_time": bubble.end_time
    }
    
    bubbles_db[bubble_id] = bubble_data
    
    # 🧹 清理过期气泡时，同步清理它的聊天记忆，防止内存爆炸
    expired_bubbles = [bid for bid, bdata in bubbles_db.items() if current_time > bdata["expire_timestamp"]]
    for bid in expired_bubbles:
        del bubbles_db[bid]
        if bid in chat_history_db:
            del chat_history_db[bid]
            
    return {"status": "success", "data": bubble_data}

@app.get("/api/bubbles")
def get_bubbles():
    return {"status": "success", "data": list(bubbles_db.values())}

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    
    # 🚀 如果这个房间还没创建记忆库，初始化一个
    if bubble_id not in chat_history_db:
        chat_history_db[bubble_id] = []

    active_connections[bubble_id].append(websocket)
    
    # 🚀 极其关键：新用户连进来时，立刻把这个房间所有的历史消息发给他！
    for msg in chat_history_db[bubble_id]:
        await websocket.send_text(msg)

    try:
        while True:
            data = await websocket.receive_text()
            # 🚀 收到新消息，存入记忆库
            chat_history_db[bubble_id].append(data)
            # 广播给所有人
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[bubble_id].remove(websocket)
        if len(active_connections[bubble_id]) == 0:
            del active_connections[bubble_id]