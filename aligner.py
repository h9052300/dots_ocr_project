import logging
import difflib

log = logging.getLogger(__name__)

class TextAligner:
    """
    位置感知型對齊器 (Position-Aware Aligner)
    不依賴 Tesseract 的文字識別結果，只利用它的座標框框。
    """
    @staticmethod
    def align(tesseract_words, vlm_text):
        if not vlm_text: return []
        
        # 1. 預處理 VLM 文字 (變成單字列表，不包含空白)
        # 例如: "城市智能" -> ['城', '市', '智', '能']
        vlm_chars = list(vlm_text.replace(" ", ""))
        if not vlm_chars: return []

        # 2. 預處理 Tesseract 框框
        # 過濾掉太小或太奇怪的框，並按照 Y 座標分行，再按 X 座標排序
        # 這樣我們能得到一條條的「物理行」
        tess_boxes = [w for w in tesseract_words if w['text'].strip()]
        if not tess_boxes: 
            # 如果完全沒框，回退到平均分佈
            return TextAligner._distribute_blindly(vlm_chars, 800, 1000)

        # 簡單的分行算法 (Y軸接近視為同一行)
        rows = TextAligner._group_into_rows(tess_boxes)
        
        # 3. 貪婪匹配 (Greedy Matching)
        # 嘗試將 VLM 的字填入最接近的行
        aligned_results = []
        char_idx = 0
        
        for row in rows:
            if char_idx >= len(vlm_chars): break
            
            # 這一行的框框數量
            num_boxes = len(row)
            
            # 嘗試從 VLM 取出對應數量的字
            # 但考慮到 Tesseract 可能把兩個字認成一個，或者漏字
            # 這裡做一個簡單的長度映射：有多少框，就填多少字
            # (進階版可以用寬度估算，但這裡先求穩)
            
            chunk_size = min(num_boxes, len(vlm_chars) - char_idx)
            chunk_chars = vlm_chars[char_idx : char_idx + chunk_size]
            
            for k, char in enumerate(chunk_chars):
                box = row[k]
                new_word = {
                    'text': char,
                    'bbox': box['bbox'],
                    'line_key': box.get('line_key', (-1,-1,-1))
                }
                aligned_results.append(new_word)
            
            char_idx += chunk_size
            
        # 4. 處理剩餘的字 (如果有)
        # 如果 VLM 字比框框多，就把剩下的字全部塞在最後一個框後面
        if char_idx < len(vlm_chars):
            last_box = aligned_results[-1]['bbox'] if aligned_results else [0,0,10,10]
            remaining = vlm_chars[char_idx:]
            
            # 虛擬延伸
            x_start = last_box[2] + 5
            char_w = 15 # 預設字寬
            
            for k, char in enumerate(remaining):
                x1 = x_start + (k * char_w)
                bbox = [x1, last_box[1], x1 + char_w, last_box[3]]
                aligned_results.append({
                    'text': char,
                    'bbox': bbox,
                    'line_key': (-1,-1,-1)
                })

        return aligned_results

    @staticmethod
    def _group_into_rows(boxes, y_threshold=10):
        # 按 Y 排序
        boxes.sort(key=lambda b: b['bbox'][1])
        rows = []
        if not boxes: return rows
        
        current_row = [boxes[0]]
        for i in range(1, len(boxes)):
            box = boxes[i]
            prev_box = current_row[-1]
            
            # 如果 Y 軸中心點接近，視為同一行
            y_center_curr = (box['bbox'][1] + box['bbox'][3]) / 2
            y_center_prev = (prev_box['bbox'][1] + prev_box['bbox'][3]) / 2
            
            if abs(y_center_curr - y_center_prev) < y_threshold:
                current_row.append(box)
            else:
                # 結束這一行，先對這一行按 X 排序
                current_row.sort(key=lambda b: b['bbox'][0])
                rows.append(current_row)
                current_row = [box]
        
        # 加入最後一行
        if current_row:
            current_row.sort(key=lambda b: b['bbox'][0])
            rows.append(current_row)
            
        return rows

    @staticmethod
    def _distribute_blindly(chars, w, h):
        # 沒框框時的備案
        results = []
        lines = 20
        per_line = len(chars) // lines + 1
        h_step = h / lines
        
        for i, char in enumerate(chars):
            row = i // per_line
            col = i % per_line
            x1 = 10 + col * 15
            y1 = 10 + row * h_step
            results.append({
                'text': char,
                'bbox': [x1, y1, x1+15, y1+20]
            })
        return results