import logging
from PIL import Image
from ocrmypdf import hookimpl
from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence
import html
import sys
import os
import re
import traceback

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from dots_ocr.parser import DotsOCRParser
    from dots_ocr.utils.consts import MIN_PIXELS, MAX_PIXELS
except ImportError:
    print("【DEBUG】錯誤: 找不到 dots_ocr")

class HybridOcrEngine(OcrEngine):
    def __init__(self):
        try:
            self.dots_parser = DotsOCRParser(
                min_pixels=MIN_PIXELS,
                max_pixels=MAX_PIXELS,
                use_hf=True
            )
        except Exception:
            traceback.print_exc()

    def __str__(self): return "DotsOCR Structure Engine"
    @staticmethod
    def version(): return "12.0.0 (Structure-Aware)"
    @staticmethod
    def creator_tag(options): return "dots-structure"
    @staticmethod
    def languages(options): return {'eng', 'chi_tra'}
    @staticmethod
    def get_orientation(input_file, options): return OrientationConfidence(0, 1.0)
    @staticmethod
    def get_deskew(input_file, options): return 0.0

    def generate_hocr(self, input_file, output_hocr, output_text, options):
        print(f"\n>>> 【DEBUG】結構化重建模式: {input_file} <<<")
        img = Image.open(input_file)
        width, height = img.size
        
        final_lines = []
        full_text_buffer = []

        try:
            dots_results = self.dots_parser.parse_image(
                input_path=str(input_file),
                filename=input_file.name,
                save_dir=str(input_file.parent),
                prompt_mode="prompt_layout_all_en", 
                fitz_preprocess=True
            )
            
            raw_text = ""
            if dots_results and isinstance(dots_results, list) and len(dots_results) > 0:
                result = dots_results[0]
                if result.get('md_content_path') and os.path.exists(result['md_content_path']):
                    with open(result['md_content_path'], 'r', encoding='utf-8') as f:
                        raw_text = f.read()
                elif result.get('cells_data'):
                    # 嘗試保留原始換行結構
                    raw_text = "\n".join([cell.get('text', '') for cell in result['cells_data']])
            
            if raw_text:
                # 這裡使用更細緻的清洗，保留 Markdown 表格結構
                clean_lines = self._process_structure(raw_text)
                print(f"【DEBUG】結構化處理後: {len(clean_lines)} 行")
                
                # 計算行高與位置
                margin_v = 40
                margin_h = 40
                content_height = height - (margin_v * 2)
                
                # 動態行高：根據字數密度調整
                total_chars = sum(len(l) for l in clean_lines)
                avg_chars_per_line = total_chars / len(clean_lines) if clean_lines else 1
                
                current_y = margin_v
                line_spacing = content_height / (len(clean_lines) + 2)
                line_spacing = max(min(line_spacing, 40), 12) # 限制行高範圍
                
                for line_text in clean_lines:
                    # 偵測是否為表格行 (含有大量空格或分隔符)
                    is_table_row = "  " in line_text
                    
                    # 計算 X 軸起始位置 (模擬縮排)
                    leading_spaces = len(line_text) - len(line_text.lstrip())
                    x1 = margin_h + (leading_spaces * 5) # 每個空格縮進 5px
                    
                    # 計算寬度
                    text_width_est = len(line_text.strip()) * 12 # 假設每個字 12px 寬
                    x2 = min(x1 + text_width_est, width - margin_h)
                    
                    y2 = current_y + line_spacing
                    
                    final_lines.append({
                        'text': line_text.strip(),
                        'bbox': [int(x1), int(current_y), int(x2), int(y2)]
                    })
                    full_text_buffer.append(line_text)
                    
                    current_y += line_spacing
            else:
                print("【DEBUG】❌ VLM 無資料")

        except Exception:
            traceback.print_exc()

        self._write_hocr(final_lines, (width, height), str(input_file), output_hocr)
        
        with open(output_text, "w", encoding="utf-8") as f:
            f.write("\n".join(full_text_buffer))

    def _process_structure(self, text):
        if not text: return []
        
        # 1. 移除 Markdown 圖片
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        
        # 2. 處理 Markdown 表格結構
        # 將 | 轉換為 tab 或多個空格，保留視覺分隔
        text = text.replace('|', '    ')
        
        # 3. 移除其他 Markdown 符號
        text = text.replace('#', '').replace('*', '').replace('-', '')
        
        # 4. 移除 HTML 標籤但保留換行意義
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</tr>', '\n', text) # 表格換行
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # 5. 分行並清理
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            # 移除 CSV 逗號干擾
            line = re.sub(r'(?<=\d),(?=\d)', '<TEMP_COMMA>', line) # 保護數字逗號
            line = line.replace(',', ' ')
            line = line.replace('<TEMP_COMMA>', ',')
            
            # 壓縮過多的空格，但保留適度間隔 (模擬表格欄位)
            line = re.sub(r'\s{4,}', '    ', line) 
            
            if line.strip():
                clean_lines.append(line)
                
        return clean_lines

    def _write_hocr(self, lines, size, filename, output_path):
        width, height = size
        hocr = [
            f"""<?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
            <head><title></title><meta name='ocr-system' content='dots-structure'/></head>
            <body><div class='ocr_page' title='image "{filename}"; bbox 0 0 {width} {height}'>
            <div class='ocr_carea'>"""
        ]
        
        for line in lines:
            x1, y1, x2, y2 = line['bbox']
            text = html.escape(line['text'])
            
            # 使用 ocr_line 包裹，並保留內部的空格結構
            # 這裡我們使用 <span class='ocr_line'> 來確保整行被視為一個單元
            hocr.append(f"""
            <span class='ocr_line' title='bbox {x1} {y1} {x2} {y2}'>
                <span class='ocrx_word' title='bbox {x1} {y1} {x2} {y2}'>{text}</span>
            </span>
            """)
            
        hocr.append("</div></div></body></html>")
        
        with open(output_path, "wb") as f:
            f.write("".join(hocr).encode('utf-8'))

    def generate_pdf(self, input_file, output_pdf, output_text, options): pass

@hookimpl
def get_ocr_engine(): return HybridOcrEngine()