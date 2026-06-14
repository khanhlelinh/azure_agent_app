# workers.py
import os
import re
import time
import sqlite3
from PyQt6.QtCore import QThread, pyqtSignal
from utils import natural_sort_key

try:
    import ollama
except ImportError:
    ollama = None

class AutoExtractThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_scan = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, db_path, base_img_folder, model_name):
        super().__init__()
        self.db_path = db_path
        self.base_img_folder = base_img_folder
        self.model_name = model_name

    def run(self):
        if not ollama:
            self.error.emit("Thư viện 'ollama' chưa được cài đặt. Hãy chạy lệnh: pip install ollama")
            return

        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT source_name FROM questions WHERE final_answer IS NULL OR trim(final_answer) = ''")
            records = cursor.fetchall()
            total = len(records)
            
            if total == 0:
                self.finished_scan.emit(0)
                return

            updated_count = 0
            vision_prompt = (
                "You are an expert automated exam scoring AI. Look closely at this exam explanation/answer image. "
                "Identify the correct answer section. Extract ONLY the final correct answer letter(s) (e.g., A, B, C, D). "
                "If there are multiple answers mapped to specific order/drag-and-drop slots, output them strictly separated by commas in the correct visual sequence from top to bottom or left to right (Example format: E,D,F,C). "
                "CRITICAL: Output absolutely nothing else. Do not include introductory text, explanations, markdown formatting, or backticks."
            )

            for idx, row in enumerate(records):
                source_name = row[0]
                self.progress.emit(idx + 1, total, f"Đang phân tích AI: {source_name}...")
                
                ans_img_path = None
                clean_source = source_name.replace("📁 ", "").strip()
                full_dir = os.path.join(self.base_img_folder, clean_source)
                
                if os.path.isdir(full_dir):
                    valid_exts = ('.png', '.jpg', '.jpeg')
                    all_files = [f for f in os.listdir(full_dir) if f.lower().endswith(valid_exts)]
                    for fname in sorted(all_files, key=natural_sort_key):
                        if "-answer" in fname.lower():
                            ans_img_path = os.path.join(full_dir, fname)
                            break
                
                if ans_img_path and os.path.isfile(ans_img_path):
                    try:
                        res = ollama.chat(
                            model=self.model_name,
                            messages=[{
                                'role': 'user',
                                'content': vision_prompt,
                                'images': [ans_img_path]
                            }]
                        )
                        raw_output = res.get('message', {}).get('content', '').strip()
                        clean_ans = re.sub(r'```.*?```', '', raw_output).replace('`', '').strip()
                        
                        if ":" in clean_ans:
                            clean_ans = clean_ans.split(":")[-1].strip()
                            
                        clean_ans = ",".join([part.strip().upper() for part in clean_ans.split(",") if part.strip()])

                        if clean_ans:
                            cursor.execute("UPDATE questions SET final_answer = ? WHERE source_name = ?", (clean_ans, source_name))
                            conn.commit()
                            updated_count += 1
                            
                    except Exception as e:
                        print(f"Ollama API Error at [{source_name}]: {e}")
                        continue
                        
                time.sleep(0.2)
                
            self.finished_scan.emit(updated_count)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if conn:
                conn.close()