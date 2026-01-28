```
dots_ocr_project/
├── app.py              # FastAPI 伺服器：處理佇列、非同步執行 OCR 任務
├── plugin.py           # OCRmyPDF 自定義插件：實作結構化重建與 hOCR 生成
├── aligner.py          # 文字對齊工具：用於將 VLM 文字回填至座標框
├── win_OCRclient.py    # Windows 客戶端：負責上傳、輪詢進度與下載結果
├── requirements.txt    # Python 依賴套件列表
└── README.md           # 專案說明文件
```

## ✨ 功能特色

- **結構化還原**：透過 `plugin.py` 中的 `HybridOcrEngine`，結合 VLM/LLM 的能力，將圖片內容轉為帶有 Markdown 結構（如表格、段落）的文字，而非單純的文字流。
- **非同步任務佇列**：使用 SQLite 管理任務狀態 (`QUEUED`, `PROCESSING`, `COMPLETED`)，避免多個重型 OCR 任務同時執行導致顯存 (VRAM) 溢出。
- **自動化批次處理**：提供 Python 客戶端腳本，可自動掃描資料夾、上傳 PDF 並下載雙層 PDF (Searchable PDF)。
- **GPU 資源管理**：伺服器端可配置 `MAX_CONCURRENT_JOBS` 以限制並發數（針對 RTX 4090 等顯卡優化）。

## 🚀 安裝與部署 (伺服器端)

本專案建議部署於 Linux 環境 (如 Ubuntu 24.04)，需預先安裝 Tesseract 與 Ghostscript。

### 1. 系統依賴安裝

Bash

```
sudo apt update
sudo apt install tesseract-ocr ghostscript -y
```

### 2. Python 環境設定

請確保已安裝 `dots_ocr` (本專案的核心依賴) 及其他套件：

Bash

```
# 安裝 Python 依賴
pip install -r requirements.txt

# (若 dots_ocr 未發布於 PyPI，需手動安裝)
# pip install -e /path/to/dots_ocr
```

### 3. 啟動伺服器

Bash

```
python app.py
```

伺服器預設運作於 `0.0.0.0:8000`。

------

## 💻 使用方法 (Windows 客戶端)

客戶端腳本用於將本地 PDF 傳送至伺服器進行處理。

### 1. 配置客戶端

開啟 `win_OCRclient.py` 並修改以下設定：

Python

```
SERVER_IP = "192.168.xx.xx"       # 替換為伺服器的 IP
INPUT_DIR = r"C:\Path\To\Input"   # 待處理 PDF 資料夾
OUTPUT_DIR = r"C:\Path\To\Output" # 結果輸出資料夾
```

### 2. 執行批次作業

PowerShell

```
python win_OCRclient.py
```

程式將會：

1. 自動掃描 `INPUT_DIR` 中的 PDF 檔。
2. 上傳至伺服器並取得 Job ID。
3. 顯示即時進度 (如：`Page 5 / 20`)。
4. 處理完成後自動下載至 `OUTPUT_DIR`，檔名後綴為 `_searchable.pdf`。

## 🛠️ 技術細節

### OCR 流程 (Pipeline)

1. **上傳**：Client 上傳 PDF，Server 生成 UUID 並存入 `temp_workspace`。
2. **排程**：`ThreadPoolExecutor` 從 SQLite 佇列中取出任務。
3. **執行**：呼叫 `ocrmypdf` 並掛載 `plugin.py`。
   - 插件呼叫 `DotsOCRParser` 進行圖像理解。
   - 清洗文字並還原 Markdown 表格結構。
   - 計算虛擬座標 (Bounding Box) 並生成 hOCR。
4. **合成**：OCRmyPDF 將 hOCR 注入原始 PDF，生成雙層 PDF。

### 資料庫

使用 SQLite (`tasks.db`) 記錄任務狀態，欄位包含：

- `id`: 任務 UUID
- `status`: `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`
- `progress`: 即時 Log 訊息 (例如掃描頁數)

## ⚠️ 注意事項

- **顯存控制**：`app.py` 中的 `MAX_CONCURRENT_JOBS` 預設為 1，若您的 GPU 顯存較大 (如 24GB+)，可適度調整為 2。
- **DotsOCR 依賴**：本專案依賴外部模組 `dots_ocr`，請確保該模組路徑正確且模型已下載。
