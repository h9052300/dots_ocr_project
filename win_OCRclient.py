import time
import requests
import logging
from pathlib import Path

# 配置區
SERVER_IP = "192.168.204.34"  # 請確認你的 IP
API_URL = f"http://{SERVER_IP}:8000"
INPUT_DIR = r"C:\Users\x1090102\Downloads\batch_input"
OUTPUT_DIR = r"C:\Users\x1090102\Downloads\batch_output"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def process_pipeline(file_path, output_dir):
    filename = file_path.name
    logger.info(f"🚀 [1/3] 上傳檔案: {filename}")

    # 1. 提交任務 (Submit)
    try:
        with open(file_path, 'rb') as f:
            resp = requests.post(f"{API_URL}/ocr/submit", files={'file': f}, timeout=600)
            if resp.status_code != 200:
                logger.error(f"❌ 上傳失敗: {resp.text}")
                return
            data = resp.json()
            job_id = data['job_id']
            logger.info(f"✅ 上傳成功! Job ID: {job_id}")
    except Exception as e:
        logger.error(f"❌ 連線錯誤: {e}")
        return

    # 2. 輪詢進度 (Poll)
    logger.info(f"⏳ [2/3] 等待伺服器處理... (您可以隨時關閉此視窗，任務不會中斷)")
    last_progress = ""

    while True:
        try:
            status_resp = requests.get(f"{API_URL}/ocr/status/{job_id}", timeout=10)
            if status_resp.status_code != 200:
                print(f"\r❌ 查詢失敗...", end="")
                time.sleep(5)
                continue

            info = status_resp.json()
            status = info['status']
            progress = info.get('progress', '')

            # 只在進度文字改變時才印出，避免洗版
            if progress != last_progress:
                print(f"\r🔹 [{status}] 進度: {progress}" + " " * 20)
                last_progress = progress

            if status == "COMPLETED":
                print("")  # 換行
                logger.info("🎉 伺服器處理完畢!")
                break
            elif status == "FAILED":
                print("")
                logger.error(f"❌ 任務失敗: {progress}")
                return

            time.sleep(5)  # 每 5 秒檢查一次

        except KeyboardInterrupt:
            logger.warning("使用者中斷監控 (伺服器仍在背景執行)")
            return
        except Exception as e:
            logger.error(f"輪詢錯誤: {e}")
            time.sleep(10)

    # 3. 下載結果 (Download)
    logger.info(f"⬇️ [3/3] 下載結果...")
    try:
        download_resp = requests.get(f"{API_URL}/ocr/download/{job_id}", stream=True, timeout=3600)
        if download_resp.status_code == 200:
            output_file = Path(output_dir) / f"{file_path.stem}_searchable.pdf"
            with open(output_file, 'wb') as f:
                for chunk in download_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"✅ 檔案已儲存: {output_file}")
        else:
            logger.error("❌ 下載失敗")
    except Exception as e:
        logger.error(f"❌ 下載過程錯誤: {e}")


def main():
    input_path = Path(INPUT_DIR)
    if not input_path.exists():
        logger.error("找不到輸入資料夾")
        return

    files = list(input_path.glob("*.pdf"))
    logger.info(f"發現 {len(files)} 個 PDF，開始處理佇列...")

    for f in files:
        process_pipeline(f, OUTPUT_DIR)
        print("-" * 50)


if __name__ == "__main__":
    main()