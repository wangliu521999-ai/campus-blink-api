from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional
import time
import uuid
import json

app = FastAPI(title="Campus Blink API v1.6")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🚀 核心安全防线：敏感词库
# ==========================================
SENSITIVE_WORDS = ["诈骗", "兼职", "加微信", "赌博", "贷款", "色情", "代写"]

def check_sensitive(text: str) -> bool:
    for word in SENSITIVE_WORDS:
        if word in text:
            return True
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

bubbles_db = {}
active_connections: Dict[str, List[WebSocket]] = {}
chat_history_db: Dict[str, List[str]] = {}

@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    # 🚀 敏感词拦截
    if check_sensitive(bubble.text) or check_sensitive(bubble.icon):
        raise HTTPException(status_code=400, detail="内容包含违规词汇，请文明发布！")

    bubble_id = str(uuid.uuid4())
    bubble_data = bubble.dict()
    bubble_data["id"] = bubble_id
    bubble_data["expire_timestamp"] = time.time() + bubble.expire_minutes * 60
    bubble_data["current_people"] = 0 
    
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
    if category and category != "all":
        all_bubbles = [b for b in all_bubbles if b["category"] == category]
        
    return {"status": "success", "data": all_bubbles}

@app.delete("/api/bubbles/{bubble_id}")
async def delete_bubble(bubble_id: str, user_id: str):
    if bubble_id in bubbles_db and bubbles_db[bubble_id]["user_id"] == user_id:
        if bubble_id in active_connections:
            for ws in active_connections[bubble_id]:
                # 🚀 格式化系统消息
                await ws.send_text(json.dumps({"userId": "system", "text": "⚠️ 气泡已由发起人撤销。"}))
        del bubbles_db[bubble_id]
        return {"status": "success"}
    raise HTTPException(status_code=403, detail="无权操作")

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    await websocket.accept()
    
    bubble = bubbles_db.get(bubble_id)
    if not bubble:
        await websocket.send_text(json.dumps({"userId": "system", "text": "⚠️ 气泡已失效"}))
        await websocket.close()
        return
        
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    
    if len(active_connections[bubble_id]) >= bubble["max_people"]:
        await websocket.send_text(json.dumps({"userId": "system", "text": "❌ 房间已满员，无法进入聊天"}))
        await websocket.close()
        return

    active_connections[bubble_id].append(websocket)
    bubbles_db[bubble_id]["current_people"] = len(active_connections[bubble_id])
    
    if bubble_id not in chat_history_db:
        chat_history_db[bubble_id] = []
        
    # 推送历史消息
    for msg in chat_history_db[bubble_id]:
        await websocket.send_text(msg)

    # 🚀 进群欢迎系统消息！
    welcome_msg = json.dumps({"userId": "system", "text": "👋 一位校友加入了闪现..."})
    chat_history_db[bubble_id].append(welcome_msg)
    for connection in active_connections[bubble_id]:
        await connection.send_text(welcome_msg)

    try:
        while True:
            data = await websocket.receive_text()
            
            # 解析前端发来的 JSON，检查敏感词
            try:
                msg_obj = json.loads(data)
                user_text = msg_obj.get("text", "")
            except:
                user_text = data
                
            if check_sensitive(user_text):
                await websocket.send_text(json.dumps({"userId": "system", "text": "⚠️ 消息违规，发送失败"}))
                continue

            chat_history_db[bubble_id].append(data)
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[bubble_id].remove(websocket)
        bubbles_db[bubble_id]["current_people"] = len(active_connections[bubble_id])