import os
import shutil
import subprocess
import uuid
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import sys

# ================= 配置區 =================
# 限制同時執行的 OCR 任務數量，防止 4090 顯存爆炸
# 建議設為 1 (安全) 或 2 (如果顯存夠大)
MAX_CONCURRENT_JOBS = 1 

TEMP_DIR = Path("temp_workspace")
TEMP_DIR.mkdir(exist_ok=True)
DB_PATH = "tasks.db"

# 初始化 Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("OCR_Server")

app = FastAPI(title="DotsOCR Async Server")

# 建立全域執行緒池
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

# ================= 資料庫管理 =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id TEXT PRIMARY KEY, 
                  filename TEXT, 
                  status TEXT, 
                  progress TEXT, 
                  created_at TEXT, 
                  completed_at TEXT)''')
    conn.commit()
    conn.close()

def update_job_status(job_id, status, progress=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if progress:
        c.execute("UPDATE jobs SET status=?, progress=? WHERE id=?", (status, progress, job_id))
    else:
        c.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    
    if status in ["COMPLETED", "FAILED"]:
        c.execute("UPDATE jobs SET completed_at=? WHERE id=?", (datetime.now().isoformat(), job_id))
    
    conn.commit()
    conn.close()

def get_job_info(job_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "filename": row[1], "status": row[2],
            "progress": row[3], "created_at": row[4], "completed_at": row[5]
        }
    return None

# 初始化 DB
init_db()

# ================= 核心工作邏輯 (Worker) =================
def run_ocr_process(job_id: str, input_path: str, output_path: str):
    """這是在背景執行緒中運行的函數"""
    logger.info(f"[{job_id}] 開始執行 OCR 任務...")
    update_job_status(job_id, "PROCESSING", "初始化模型中...")

    cmd = [
        "ocrmypdf",
        "--jobs", "1", # 內部並行，視顯存調整
        "--plugin", "plugin.py",
        "--pdf-renderer", "hocr",
        "--output-type", "pdf",
        "--redo-ocr",
        "--verbose", "1",
        str(input_path),
        str(output_path)
    ]

    try:
        # 使用 Popen 即時捕獲輸出
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8', 
            errors='replace'
        )

        # 逐行讀取 Log，並更新到資料庫讓 Client 看到
        for line in process.stdout:
            line = line.strip()
            if not line: continue
            
            # 簡單過濾，只更新有意義的進度
            if "Page" in line or "Scanning" in line or "postprocessing" in line:
                # 這裡將 ocrmypdf 的 log 寫入 DB 的 progress 欄位
                # 例如: "Page 5 / 319"
                update_job_status(job_id, "PROCESSING", line[-100:]) # 限制長度
            
            # 同時印在 Server Console 方便除錯
            print(f"[{job_id}] LOG: {line}")

        process.wait()

        if process.returncode == 0:
            update_job_status(job_id, "COMPLETED", "處理完成")
            logger.info(f"[{job_id}] 任務成功完成")
        else:
            update_job_status(job_id, "FAILED", f"錯誤代碼: {process.returncode}")
            logger.error(f"[{job_id}] 任務失敗")

    except Exception as e:
        logger.error(f"[{job_id}] 發生例外: {e}")
        update_job_status(job_id, "FAILED", str(e))

# ================= API Endpoints =================

@app.post("/ocr/submit")
async def submit_job(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    input_p = TEMP_DIR / f"{job_id}.pdf"
    
    # 存檔
    with open(input_p, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    # 寫入 DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO jobs (id, filename, status, progress, created_at) VALUES (?, ?, ?, ?, ?)",
              (job_id, file.filename, "QUEUED", "等待佇列中...", datetime.now().isoformat()))
    conn.commit()
    conn.close()

    # 提交到執行緒池 (不會阻塞 API)
    output_p = TEMP_DIR / f"{job_id}_done.pdf"
    executor.submit(run_ocr_process, job_id, str(input_p), str(output_p))

    return {"job_id": job_id, "status": "QUEUED", "message": "任務已提交，請使用 Job ID 查詢進度"}

@app.get("/ocr/status/{job_id}")
async def check_status(job_id: str):
    info = get_job_info(job_id)
    if not info:
        raise HTTPException(status_code=404, detail="Job not found")
    return info

@app.get("/ocr/download/{job_id}")
async def download_result(job_id: str):
    info = get_job_info(job_id)
    if not info or info['status'] != "COMPLETED":
        raise HTTPException(status_code=400, detail="File not ready or failed")
    
    output_p = TEMP_DIR / f"{job_id}_done.pdf"
    if not output_p.exists():
        raise HTTPException(status_code=404, detail="Result file missing")
        
    return FileResponse(output_p, filename=f"searchable_{info['filename']}")

if __name__ == "__main__":
    import uvicorn
    # 啟動 Server
    uvicorn.run(app, host="0.0.0.0", port=8000)