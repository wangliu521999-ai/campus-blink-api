from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid

app = FastAPI(title="Campus Blink API v1.5")

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
    max_people: int = 10 # 🚀 新增：人数上限
    start_time: Optional[str] = None
    end_time: Optional[str] = None

bubbles_db = {}
active_connections: Dict[str, List[WebSocket]] = {}
chat_history_db: Dict[str, List[str]] = {}

@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    bubble_id = str(uuid.uuid4())
    bubble_data = bubble.dict()
    bubble_data["id"] = bubble_id
    bubble_data["expire_timestamp"] = time.time() + bubble.expire_minutes * 60
    bubble_data["current_people"] = 0 # 初始人数
    
    bubbles_db[bubble_id] = bubble_data
    return {"status": "success", "data": bubble_data}

@app.get("/api/bubbles")
def get_bubbles(category: Optional[str] = None):
    current_time = time.time()
    # 自动清理过期气泡
    to_delete = [bid for bid, b in bubbles_db.items() if current_time > b["expire_timestamp"]]
    for bid in to_delete:
        del bubbles_db[bid]
        if bid in chat_history_db: del chat_history_db[bid]

    all_bubbles = list(bubbles_db.values())
    # 🚀 优化：增加后端分类筛选逻辑
    if category and category != "all":
        all_bubbles = [b for b in all_bubbles if b["category"] == category]
        
    return {"status": "success", "data": all_bubbles}

@app.delete("/api/bubbles/{bubble_id}")
async def delete_bubble(bubble_id: str, user_id: str):
    if bubble_id in bubbles_db and bubbles_db[bubble_id]["user_id"] == user_id:
        if bubble_id in active_connections:
            for ws in active_connections[bubble_id]:
                await ws.send_text("⚠️ 气泡已由发起人撤销。")
        del bubbles_db[bubble_id]
        return {"status": "success"}
    raise HTTPException(status_code=403, detail="无权操作")

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    
    # 🚀 核心逻辑：检查人数上限
    bubble = bubbles_db.get(bubble_id)
    if not bubble:
        await websocket.send_text("⚠️ 气泡已失效")
        await websocket.close()
        return
        
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    
    if len(active_connections[bubble_id]) >= bubble["max_people"]:
        await websocket.send_text("❌ 房间已满员，无法进入聊天")
        await websocket.close()
        return

    active_connections[bubble_id].append(websocket)
    bubbles_db[bubble_id]["current_people"] = len(active_connections[bubble_id])
    
    if bubble_id not in chat_history_db:
        chat_history_db[bubble_id] = []
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
        bubbles_db[bubble_id]["current_people"] = len(active_connections[bubble_id])