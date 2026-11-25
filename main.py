"""
数字化分货系统 - 后端 (FastAPI + SQLite)
学习演示版，可直接部署
"""
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import hashlib
import secrets
import json
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

# ==================== 配置 ====================
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "drp.db"
DB_PATH.parent.mkdir(exist_ok=True)

app = FastAPI(title="数字化分货系统", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简单 session 存储（生产环境建议用 Redis）
sessions = {}  # token -> user_id

# ==================== 数据库 ====================
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            city TEXT DEFAULT ''
        );
        
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            applicant TEXT NOT NULL,
            applicant_name TEXT NOT NULL,
            city TEXT NOT NULL,
            category TEXT NOT NULL,
            product TEXT NOT NULL,
            memory TEXT NOT NULL,
            color TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            remark TEXT DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            history TEXT NOT NULL
        );
        """)
        
        users = [
            ("ka01", "张伟", "ka", "乌鲁木齐"),
            ("city01", "李强", "city_manager", "乌鲁木齐"),
            ("pm01", "王芳", "product_manager", ""),
            ("sales01", "赵敏", "sales_manager", ""),
            ("dist01", "刘洋", "distribution", ""),
            ("admin", "系统管理员", "province", ""),
        ]
        pwd_hash = hashlib.sha256("123456".encode()).hexdigest()
        for uid, name, role, city in users:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, password_hash, name, role, city) VALUES (?, ?, ?, ?, ?)",
                (uid, pwd_hash, name, role, city)
            )
        
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if count == 0:
            sample_orders = [
                {
                    "id": "ORD20261125001",
                    "applicant": "ka01",
                    "applicant_name": "张伟",
                    "city": "乌鲁木齐",
                    "category": "智能手机",
                    "product": "Mate 60 Pro",
                    "memory": "12GB+256GB",
                    "color": "雅川青",
                    "quantity": 50,
                    "remark": "重点客户紧急需求",
                    "status": "pending_city",
                    "created_at": "2026-11-24 10:20:00",
                    "history": json.dumps([{"time": "2026-11-24 10:20:00", "user": "张伟", "action": "提交需求"}], ensure_ascii=False)
                },
                {
                    "id": "ORD20261124002",
                    "applicant": "ka01",
                    "applicant_name": "张伟",
                    "city": "乌鲁木齐",
                    "category": "智能手机",
                    "product": "Pura 70 Ultra",
                    "memory": "16GB+512GB",
                    "color": "黑色",
                    "quantity": 30,
                    "remark": "",
                    "status": "pending_product",
                    "created_at": "2026-11-23 15:40:00",
                    "history": json.dumps([
                        {"time": "2026-11-23 15:40:00", "user": "张伟", "action": "提交需求"},
                        {"time": "2026-11-23 16:10:00", "user": "李强", "action": "地市审批通过"}
                    ], ensure_ascii=False)
                },
                {
                    "id": "ORD20261123003",
                    "applicant": "ka01",
                    "applicant_name": "张伟",
                    "city": "乌鲁木齐",
                    "category": "平板电脑",
                    "product": "MatePad Pro 13.2",
                    "memory": "12GB+256GB",
                    "color": "黑色",
                    "quantity": 20,
                    "remark": "渠道备货",
                    "status": "approved",
                    "created_at": "2026-11-22 09:15:00",
                    "history": json.dumps([
                        {"time": "2026-11-22 09:15:00", "user": "张伟", "action": "提交需求"},
                        {"time": "2026-11-22 10:00:00", "user": "李强", "action": "地市审批通过"},
                        {"time": "2026-11-22 11:20:00", "user": "王芳", "action": "产品审视通过"},
                        {"time": "2026-11-22 14:00:00", "user": "赵敏", "action": "销售审批通过"},
                        {"time": "2026-11-22 15:30:00", "user": "刘洋", "action": "分货完成，已批准"}
                    ], ensure_ascii=False)
                }
            ]
            for o in sample_orders:
                conn.execute("""
                    INSERT INTO orders (id, applicant, applicant_name, city, category, product, memory, color, quantity, remark, status, created_at, history)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (o["id"], o["applicant"], o["applicant_name"], o["city"], o["category"], o["product"],
                      o["memory"], o["color"], o["quantity"], o["remark"], o["status"], o["created_at"], o["history"]))

init_db()

# ==================== 模型 ====================
class LoginRequest(BaseModel):
    username: str
    password: str

class OrderCreate(BaseModel):
    category: str
    product: str
    memory: str
    color: str
    quantity: int
    city: str = "乌鲁木齐"
    remark: str = ""

class ActionRequest(BaseModel):
    action: str

# ==================== 工具 ====================
def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = sessions[token]
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="用户不存在")
        return dict(row)

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def gen_order_id():
    return f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(2).upper()}"

ROLE_NAMES = {
    "ka": "KA客户",
    "city_manager": "地市主管",
    "product_manager": "产品经理",
    "sales_manager": "销售主管",
    "distribution": "分货专员",
    "province": "省级管理员"
}

# ==================== API ====================
@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (req.username,)).fetchone()
        if not user or user["password_hash"] != hash_pwd(req.password):
            return {"success": False, "message": "用户名或密码错误"}
        
        token = secrets.token_hex(16)
        sessions[token] = user["id"]
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7
        )
        return {
            "success": True,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "role": user["role"],
                "roleName": ROLE_NAMES.get(user["role"], user["role"]),
                "city": user["city"]
            }
        }

@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token and token in sessions:
        del sessions[token]
    response.delete_cookie("session_token")
    return {"success": True}

@app.get("/api/me")
def me(user=Depends(get_current_user)):
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "role": user["role"],
            "roleName": ROLE_NAMES.get(user["role"], user["role"]),
            "city": user["city"]
        }
    }

@app.get("/api/orders")
def list_orders(mode: str = "all", user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        orders = []
        for r in rows:
            o = dict(r)
            o["history"] = json.loads(o["history"])
            orders.append(o)
    
    if mode == "my":
        orders = [o for o in orders if o["applicant"] == user["id"]]
    elif mode == "pending":
        role = user["role"]
        status_map = {
            "city_manager": "pending_city",
            "product_manager": "pending_product",
            "sales_manager": "pending_sales",
            "distribution": "pending_distribution"
        }
        if role == "province":
            orders = [o for o in orders if o["status"].startswith("pending")]
        else:
            target = status_map.get(role)
            orders = [o for o in orders if o["status"] == target] if target else []
    
    return {"success": True, "data": orders}

@app.post("/api/orders")
def create_order(req: OrderCreate, user=Depends(get_current_user)):
    if user["role"] not in ("ka", "province"):
        raise HTTPException(status_code=403, detail="只有KA客户可以提报")
    
    order_id = gen_order_id()
    history = [{"time": now_str(), "user": user["name"], "action": "提交需求"}]
    
    with get_db() as conn:
        conn.execute("""
            INSERT INTO orders (id, applicant, applicant_name, city, category, product, memory, color, quantity, remark, status, created_at, history)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, user["id"], user["name"], req.city or user["city"] or "乌鲁木齐",
            req.category, req.product, req.memory, req.color, req.quantity, req.remark,
            "pending_city", now_str(), json.dumps(history, ensure_ascii=False)
        ))
    
    return {"success": True, "message": "提报成功", "id": order_id}

@app.post("/api/orders/{order_id}/action")
def order_action(order_id: str, req: ActionRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        order = dict(row)
        history = json.loads(order["history"])
        status = order["status"]
        role = user["role"]
        
        if req.action == "reject":
            if not (status.startswith("pending") and (role == "province" or 
                    (role == "city_manager" and status == "pending_city") or
                    (role == "product_manager" and status == "pending_product") or
                    (role == "sales_manager" and status == "pending_sales") or
                    (role == "distribution" and status == "pending_distribution"))):
                raise HTTPException(status_code=403, detail="无权操作")
            new_status = "rejected"
            action_text = "驳回"
        elif req.action == "approve":
            flow = {
                "pending_city": ("pending_product", "地市审批通过", ["city_manager", "province"]),
                "pending_product": ("pending_sales", "产品审视通过", ["product_manager", "province"]),
                "pending_sales": ("pending_distribution", "销售审批通过", ["sales_manager", "province"]),
                "pending_distribution": ("approved", "分货完成，已批准", ["distribution", "province"]),
            }
            if status not in flow:
                raise HTTPException(status_code=400, detail="当前状态不可审批")
            next_status, action_text, allowed_roles = flow[status]
            if role not in allowed_roles:
                raise HTTPException(status_code=403, detail="无权审批此状态")
            new_status = next_status
        else:
            raise HTTPException(status_code=400, detail="无效操作")
        
        history.append({"time": now_str(), "user": user["name"], "action": action_text})
        conn.execute(
            "UPDATE orders SET status = ?, history = ? WHERE id = ?",
            (new_status, json.dumps(history, ensure_ascii=False), order_id)
        )
    
    return {"success": True, "message": action_text, "status": new_status}

@app.get("/api/stats")
def stats(user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT status, quantity FROM orders").fetchall()
    
    total = len(rows)
    pending = sum(1 for r in rows if r["status"].startswith("pending"))
    approved = sum(1 for r in rows if r["status"] == "approved")
    rejected = sum(1 for r in rows if r["status"] == "rejected")
    total_qty = sum(r["quantity"] for r in rows if r["status"] == "approved")
    
    return {
        "success": True,
        "data": {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "totalQty": total_qty
        }
    }

@app.get("/api/users")
def list_users(user=Depends(get_current_user)):
    if user["role"] != "province":
        raise HTTPException(status_code=403, detail="仅管理员可查看")
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, role, city FROM users").fetchall()
    return {
        "success": True,
        "data": [
            {"id": r["id"], "name": r["name"], "role": r["role"], "roleName": ROLE_NAMES.get(r["role"], r["role"]), "city": r["city"]}
            for r in rows
        ]
    }

PRODUCT_TREE = [
    {
        "name": "智能手机",
        "children": [
            {
                "name": "Mate 60 Pro",
                "children": [
                    {"name": "12GB+256GB", "children": [{"name": "雅川青"}, {"name": "南糯紫"}, {"name": "白沙银"}]},
                    {"name": "12GB+512GB", "children": [{"name": "雅川青"}, {"name": "南糯紫"}]}
                ]
            },
            {
                "name": "Pura 70 Ultra",
                "children": [
                    {"name": "16GB+512GB", "children": [{"name": "黑色"}, {"name": "绿色"}, {"name": "棕色"}]},
                    {"name": "16GB+1TB", "children": [{"name": "黑色"}, {"name": "绿色"}]}
                ]
            },
            {
                "name": "nova 12 Pro",
                "children": [
                    {"name": "12GB+256GB", "children": [{"name": "黑色"}, {"name": "白色"}, {"name": "紫色"}]}
                ]
            }
        ]
    },
    {
        "name": "平板电脑",
        "children": [
            {
                "name": "MatePad Pro 13.2",
                "children": [
                    {"name": "12GB+256GB", "children": [{"name": "黑色"}, {"name": "金色"}]},
                    {"name": "16GB+512GB", "children": [{"name": "黑色"}]}
                ]
            }
        ]
    }
]

@app.get("/api/products")
def products(user=Depends(get_current_user)):
    return {"success": True, "data": PRODUCT_TREE}

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
