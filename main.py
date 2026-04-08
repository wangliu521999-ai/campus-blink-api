from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
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

# 接口 1：用来测试服务器是否正常工作的探针
@app.get("/")
def read_root():
    return {"status": "success", "message": "校内闪现 (Campus Blink) 后端已启动！"}

# 接口 2：接收前端发来的新气泡
@app.post("/api/bubbles")
def create_bubble(bubble: Bubble):
    # 1. 给这个气泡生成一个随机的唯一 ID 
    bubble_id = str(uuid.uuid4())
    
    # 2. 计算过期时间戳：当前时间 + 有效分钟数
    expire_timestamp = time.time() + bubble.expire_minutes * 60
    
    # 3. 将包含 ID、过期时间戳和气泡原始数据的字典打包
    bubble_data = {
        "id": bubble_id,
        "user_id": bubble.user_id,
        "lat": bubble.lat,
        "lng": bubble.lng,
        "icon": bubble.icon,
        "text": bubble.text,
        "expire_timestamp": expire_timestamp
    }
    
    # 4. 真正把它存进数据库！
    bubbles_db[bubble_id] = bubble_data
    
    # 5. 阅后即焚：删除所有当前时间已经大于过期时间戳的气泡
    current_time = time.time()
    expired_bubbles = [bid for bid, bdata in bubbles_db.items() if current_time > bdata["expire_timestamp"]]
    for bid in expired_bubbles:
        del bubbles_db[bid]
        
    # 把包含了随机 ID 的新数据返回给前端
    return {"status": "success", "message": "气泡接收成功！", "data": bubble_data}

# 接口 3：前端获取地图上所有活跃的气泡
@app.get("/api/bubbles")
def get_bubbles():
    return {"status": "success", "data": list(bubbles_db.values())}
from fastapi import WebSocket, WebSocketDisconnect

# ================= 新增：实时聊天室 (WebSocket) 逻辑 =================

# 存放所有正在进行中的聊天室
# 格式: { "bubble_id": [用户A的连接, 用户B的连接...] }
active_connections: dict[str, list[WebSocket]] = {}

@app.websocket("/ws/{bubble_id}")
async def websocket_endpoint(websocket: WebSocket, bubble_id: str):
    # 1. 接受前端的连接请求
    await websocket.accept()
    
    # 2. 如果这个气泡的聊天室还没建，就建一个
    if bubble_id not in active_connections:
        active_connections[bubble_id] = []
    
    # 3. 把新用户拉进聊天室
    active_connections[bubble_id].append(websocket)
    
    try:
        # 4. 持续监听这个用户发来的消息
        while True:
            data = await websocket.receive_text()
            # 5. 收到消息后，广播给聊天室里的所有人（包括发送者自己）
            for connection in active_connections[bubble_id]:
                await connection.send_text(data)
                
    except WebSocketDisconnect:
        # 6. 如果有人退出了（比如关掉网页），把他从聊天室里踢出去
        active_connections[bubble_id].remove(websocket)
        # 如果聊天室空了，就把房间解散
        if len(active_connections[bubble_id]) == 0:
            del active_connections[bubble_id]