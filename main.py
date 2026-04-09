from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid
import asyncio

app = FastAPI(title="Campus Blink API v1.4")

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
chat_history_db: Dict[str, List[str]] = {}
user_last_post_time: Dict[str, float] = {}
COOLDOWN_SECONDS = 10 

@app.get("/")
def read_root():
    return {"status": "success", "message": "v1.4 拥有撤销机制的服务器已上线！"}

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
    
    expired_bubbles = [bid for bid, bdata in bubbles_db.items() if current_time > bdata["expire_timestamp"]]
    for bid in expired_bubbles:
        del bubbles_db[bid]
        if bid in chat_history_db:
            del chat_history_db[bid]
            
    return {"status": "success", "data": bubble_data}

@app.get("/api/bubbles")
def get_bubbles():
    return {"status": "success", "data": list(bubbles_db.values())}

# ================= 🚀 新增：撤销/删除气泡接口 =================
@app.delete("/api/bubbles/{bubble_id}")
async def delete_bubble(bubble_id: str, user_id: str):
    if bubble_id not in bubbles_db:
        raise HTTPException(status_code=404, detail="该气泡已经消失啦~")
        
    # 鉴权：只有发起人自己才能删除
    if bubbles_db[bubble_id]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="你没有权限撤销别人的气泡哦！")

    # 1. 强制通知聊天室里的所有人：“局散了”
    if bubble_id in active_connections:
        for ws in active_connections[bubble_id]:
            try:
                await ws.send_text("⚠️ 发起人已撤销该闪现，活动取消/聊天室解散。")
            except:
                pass

    # 2. 从数据库和记忆库中彻底抹除
    del bubbles_db[bubble_id]
    if bubble_id in chat_history_db:
        del chat_history_db[bubble_id]
        
    return {"status": "success", "message": "撤销成功"}

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    
    if bubble_id not in chat_history_db:
        chat_history_db[bubble_id] = []

    active_connections[bubble_id].append(websocket)
    
    for msg in chat_history_db[bubble_id]:
        await websocket.send_text(msg)

    try:
        while True:
            data = await websocket.receive_text()
            chat_history_db[bubble_id].append(data)
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[bubble_id].remove(websocket)
        if len(active_connections[bubble_id]) == 0:
            del active_connections[bubble_id]