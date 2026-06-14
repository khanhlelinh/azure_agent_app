import sys
import os
import sqlite3
import re
import time
import threading
from urllib.parse import urljoin
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QMessageBox, QLineEdit, 
                             QTextEdit, QGroupBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSettings

# =========================================================
# --- TAILWIND CSS STYLING (MODERN & HIGH CONTRAST) ---
# =========================================================
TAILWIND_QSS = """
    QMainWindow { background-color: #F3F4F6; }
    QWidget { font-family: "Segoe UI", sans-serif; color: #111827; font-size: 15px; }
    
    QGroupBox { 
        background-color: #FFFFFF; 
        border: 1px solid #D1D5DB; 
        border-radius: 10px; 
        margin-top: 15px; 
        padding: 20px 15px 15px 15px;
    }
    QGroupBox::title { 
        subcontrol-origin: margin; 
        left: 15px; 
        padding: 0 8px; 
        color: #4F46E5; 
        font-size: 16px; 
        font-weight: bold;
    }
    
    QPushButton { 
        background-color: #3B82F6; 
        color: #FFFFFF; 
        border-radius: 8px; 
        padding: 10px 16px; 
        font-weight: bold; 
        border: 1px solid #2563EB; 
    }
    QPushButton:hover { background-color: #2563EB; border-color: #1D4ED8; }
    QPushButton:disabled { background-color: #E5E7EB; color: #9CA3AF; border: none; }
    
    QPushButton#btnBrowse { 
        background-color: #E5E7EB; 
        color: #000000;  
        font-size: 15px; 
        font-weight: bold;
        border: 1px solid #D1D5DB;
        padding: 8px 12px;
    }
    QPushButton#btnBrowse:hover { background-color: #D1D5DB; border-color: #9CA3AF; }
    
    QPushButton#btnSuccess { background-color: #10B981; color: #FFFFFF; font-size: 16px; border: 1px solid #059669; } 
    QPushButton#btnSuccess:hover { background-color: #059669; }
    
    QPushButton#btnWarning { background-color: #F59E0B; color: #FFFFFF; font-size: 16px; border: 1px solid #D97706; } 
    QPushButton#btnWarning:hover { background-color: #D97706; }
    
    QPushButton#btnDanger { background-color: #EF4444; color: #FFFFFF; font-size: 16px; border: 1px solid #DC2626; } 
    QPushButton#btnDanger:hover { background-color: #DC2626; }
    
    QLineEdit, QTextEdit { 
        border: 1px solid #D1D5DB; 
        border-radius: 8px; 
        padding: 8px 12px; 
        background-color: #FFFFFF; 
        color: #111827;
        font-size: 15px; 
    }
    QLineEdit:focus, QTextEdit:focus { border: 2px solid #4F46E5; outline: none; }
    
    QTextEdit#LogArea { 
        background-color: #111827; 
        color: #10B981; 
        font-family: Consolas, monospace; 
        font-size: 14px;
        border-radius: 8px; 
        padding: 10px;
    }
    
    QRadioButton { font-weight: bold; color: #1F2937; }
    QRadioButton::indicator { width: 18px; height: 18px; }
    
    QMessageBox { background-color: #FFFFFF; }
    QMessageBox QLabel { color: #111827; font-size: 15px; font-weight: 500; }
    QMessageBox QPushButton { min-width: 80px; min-height: 30px; }
"""

# =========================================================================
# --- HÀM LỌC & CHUẨN HÓA VĂN BẢN LỰA CHỌN TỪ WEB ---
# =========================================================================
def clean_examtopics_choices(raw_text):
    if not raw_text: return ""
    
    # --- CẢI TIẾN ĐẮT GIÁ: CẮT BỎ ĐOẠN 'Community vote distribution' TRỞ VỀ SAU ---
    vote_idx = re.search(r"Community\s+vote\s+distribution", raw_text, re.IGNORECASE)
    if vote_idx:
        raw_text = raw_text[:vote_idx.start()]
        
    cleaned = re.sub(r'\[\{.*?\}\]', '', raw_text, flags=re.DOTALL)
    cleaned = re.sub(r'Most Voted', '', cleaned, flags=re.IGNORECASE)
    
    options = re.findall(r'([A-G]\.)\s*([\s\S]*?)(?=(?:[A-G]\.|$))', cleaned)
    if options:
        formatted = []
        for letter, text in options:
            text_clean = re.sub(r'\s+', ' ', text).strip()
            formatted.append(f"{letter} {text_clean}")
        return "\n".join(formatted)
    else:
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
        return "\n".join(lines)

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def derive_topic_label(header_text, default_topic="Topic 1"):
    t_match = re.search(r"Topic\s*(\d+)", header_text, re.IGNORECASE)
    if t_match:
        return f"Topic {t_match.group(1)}"
    return default_topic

# =========================================================
# --- THREAD CRAWLER WORKER (PLAYWRIGHT AUTOMATION) ---
# =========================================================
class CrawlerThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    paused_confirmed_signal = pyqtSignal() 

    def __init__(self, mode, target_path, db_path, img_folder):
        super().__init__()
        self.mode = mode          
        self.target_path = target_path 
        self.db_path = db_path
        self.img_folder = img_folder
        self.start_crawl_event = threading.Event()
        
        self.is_running = True
        self.is_pause_requested = False  
        self.resume_event = threading.Event() 
        self.resume_event.set() 

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.error_signal.emit("Không tìm thấy thư viện Playwright! Vui lòng mở Terminal chạy lệnh:\npip install playwright\nplaywright install")
            return

        cache_dir = r"C:\ExamTopicsCrawlerCache"
        os.makedirs(cache_dir, exist_ok=True)

        with sync_playwright() as p:
            self.log_signal.emit(f"🌐 Đang khởi tạo Chromium Playwright (Persistent Cache tại {cache_dir})...")
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=cache_dir,
                    headless=False,
                    no_viewport=True,
                    args=["--start-maximized"]
                )
            except Exception as e:
                self.error_signal.emit(f"Lỗi khởi chạy trình duyệt (Vui lòng tắt các cửa sổ Chromium cache đang mở): \n{str(e)}")
                return

            page = context.new_page()
            current_topic = "Topic 1" 

            # =========================================================================
            # --- CHẾ ĐỘ 1: CRAWL TỪ CÁC FILE HTML LƯU TRONG THƯ MỤC NỘI BỘ ---
            # =========================================================================
            if self.mode == "local_folder":
                self.log_signal.emit(f"📁 Chế độ: Quét Thư mục HTML Nội bộ tại: {self.target_path}")
                if not os.path.isdir(self.target_path):
                    self.error_signal.emit("Thư mục chứa HTML nội bộ không tồn tại hợp lệ.")
                    context.close(); return

                html_files = [f for f in os.listdir(self.target_path) if f.lower().endswith(('.html', '.htm'))]
                html_files_sorted = sorted(html_files, key=natural_sort_key)
                
                if not html_files_sorted:
                    self.log_signal.emit("⚠️ Không tìm thấy file .html nào trong thư mục được chọn.")
                    context.close(); self.finished_signal.emit(); return

                self.log_signal.emit(f"📋 Tìm thấy {len(html_files_sorted)} file HTML. Đang tiến hành trích xuất siêu tốc...")
                
                for file_idx, fname in enumerate(html_files_sorted, 1):
                    if not self.is_running: break
                    
                    file_path = os.path.abspath(os.path.join(self.target_path, fname))
                    file_url = f"file:///{file_path.replace(os.sep, '/')}"
                    
                    self.log_signal.emit(f"\n📄 --- ĐANG QUÉT FILE NỘI BỘ [{file_idx}/{len(html_files_sorted)}]: {fname} ---")
                    try: page.goto(file_url, timeout=30000)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ Lỗi tải file nội bộ {fname}: {str(e)}")
                        continue

                    topic_cards = page.locator(".topic-card").all()
                    for t_card in topic_cards:
                        current_topic = derive_topic_label(t_card.text_content() or "", current_topic)
                        self.log_signal.emit(f"🏷️ Phát hiện chủ đề mới: {current_topic}")

                    cards = page.locator(".exam-question-card").all()
                    self.log_signal.emit(f"📊 Phát hiện {len(cards)} câu hỏi trong file {fname}.")

                    for card_idx, card in enumerate(cards, 1):
                        if not self.is_running: break
                        
                        header_text = card.locator(".card-header").text_content() or ""
                        q_num_match = re.search(r"Question\s*#\s*(\d+)", header_text, re.IGNORECASE)
                        q_num = q_num_match.group(1) if q_num_match else f"f{file_idx}_{card_idx}"
                        
                        category = derive_topic_label(header_text, current_topic)
                        clean_topic_name = category.replace(" ", "-") # "Topic-1"
                        folder_name = f"{q_num}-{clean_topic_name}"

                        self.log_signal.emit(f"🔄 Trích xuất: Câu hỏi #{q_num} | Chủ đề: {category} | Định danh: {folder_name}")

                        reveal_btn = card.locator(".reveal-solution")
                        if reveal_btn.count() > 0 and reveal_btn.first.is_visible():
                            try: reveal_btn.first.click(timeout=3000); time.sleep(0.3)
                            except: pass

                        body_loc = card.locator(".question-body")
                        q_text_loc = body_loc.locator("> .card-text").first
                        extracted_text = q_text_loc.text_content().strip() if q_text_loc.count() > 0 else ""
                        extracted_text = re.sub(r'\n+', '\n', extracted_text).strip()

                        choices_loc = body_loc.locator(".question-choices-container")
                        raw_choices_text = choices_loc.text_content().strip() if choices_loc.count() > 0 else "None"
                        choices_text = clean_examtopics_choices(raw_choices_text)

                        ans_block = card.locator(".question-answer")
                        raw_ans_text = ans_block.text_content().strip() if ans_block.count() > 0 else ""
                        
                        # Cắt bỏ phần Community vote distribution rác ra khỏi khối giải thích (nếu có bị lẹm)
                        vote_ans_idx = re.search(r"Community\s+vote\s+distribution", raw_ans_text, re.IGNORECASE)
                        if vote_ans_idx: raw_ans_text = raw_ans_text[:vote_ans_idx.start()]
                        ans_text = re.sub(r'\n+', '\n', raw_ans_text).strip()

                        final_answer_val = ""
                        correct_ans_box = card.locator(".correct-answer-box")
                        full_ans_block_text = correct_ans_box.first.text_content() if correct_ans_box.count() > 0 else ans_text
                            
                        if full_ans_block_text:
                            match_ans = re.search(r"Correct\s+Answer:\s*([A-Z]+)", full_ans_block_text, re.IGNORECASE)
                            if match_ans:
                                final_answer_val = ",".join(list(match_ans.group(1).upper()))
                                self.log_signal.emit(f"    🎯 Đã bóc tách tự động Đáp án: '{final_answer_val}'")

                        q_type = "Chọn"
                        if any(k in extracted_text.lower() for k in ["drag drop", "drag and drop", "hotspot"]): q_type = "Kéo thả"
                        elif any(k in extracted_text.lower() for k in ["simulation", "lab"]): q_type = "Lab"

                        all_imgs = body_loc.locator("img").all()
                        target_dir = os.path.join(self.img_folder, folder_name)
                        source_name = f"📁 {folder_name}"  
                        
                        if len(all_imgs) > 0:
                            os.makedirs(target_dir, exist_ok=True)
                            img_counter = 1; ans_counter = 1
                            
                            for img in all_imgs:
                                src = img.get_attribute("src")
                                if not src: continue
                                
                                abs_url = urljoin(page.url, src)
                                is_answer_img = img.evaluate("node => !!node.closest('.question-answer')")
                                
                                ext = abs_url.split(".")[-1].split("?")[0]
                                if len(ext) > 5 or not ext: ext = "png"
                                
                                filename = f"{q_num}-{ans_counter}-answer.{ext}" if is_answer_img else f"{q_num}-{img_counter}.{ext}"
                                if is_answer_img: ans_counter += 1
                                else: img_counter += 1
                                    
                                filepath = os.path.join(target_dir, filename)
                                
                                try:
                                    if abs_url.startswith("http"):
                                        res = context.request.get(abs_url)
                                        if res.ok:
                                            with open(filepath, "wb") as f: f.write(res.body())
                                            self.log_signal.emit(f"    📥 Đã tải ảnh: {filename}")
                                    elif abs_url.startswith("file:///"):
                                        local_img_path = abs_url.replace("file:///", "")
                                        if os.path.exists(local_img_path):
                                            with open(local_img_path, "rb") as fin, open(filepath, "wb") as fout:
                                                fout.write(fin.read())
                                            self.log_signal.emit(f"    📥 Đã chép ảnh nội bộ: {filename}")
                                except Exception as e:
                                    self.log_signal.emit(f"    ⚠️ Lỗi chép ảnh {filename}: {str(e)}")
                        else:
                            os.makedirs(target_dir, exist_ok=True)

                        # Lưu DB
                        try:
                            conn = sqlite3.connect(self.db_path); cursor = conn.cursor()
                            cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                                source_name TEXT UNIQUE, extracted_text TEXT, vn_explanation TEXT,
                                choices TEXT, final_answer TEXT, answer TEXT, status TEXT, 
                                question_type TEXT DEFAULT 'Chọn', is_reliable INTEGER DEFAULT 1,
                                category TEXT DEFAULT 'Chưa phân loại', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                            
                            cursor.execute("PRAGMA table_info(questions)")
                            existing_cols = [c[1] for c in cursor.fetchall()]
                            if "category" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN category TEXT DEFAULT 'Chưa phân loại'")
                            if "question_type" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN question_type TEXT DEFAULT 'Chọn'")
                            if "is_reliable" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN is_reliable INTEGER DEFAULT 1")

                            cursor.execute('''INSERT OR REPLACE INTO questions 
                                (source_name, extracted_text, choices, final_answer, answer, status, question_type, is_reliable, category)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                                source_name, extracted_text, choices_text, final_answer_val, ans_text, "done", q_type, 1, category
                            ))
                            conn.commit(); conn.close()
                            self.log_signal.emit(f"    💾 Đã lưu thành công {source_name} vào Database.")
                        except Exception as e:
                            self.log_signal.emit(f"    ❌ Lỗi ghi Database tại {source_name}: {str(e)}")

                    time.sleep(0.2)

                self.log_signal.emit("\n" + "★"*60)
                self.log_signal.emit("🏁 ĐÃ HOÀN TẤT QUÉT TOÀN BỘ THƯ MỤC HTML NỘI BỘ THÀNH CÔNG!")
                self.log_signal.emit("★"*60)

            # =========================================================================
            # --- CHẾ ĐỘ 2: CRAWL TỪ URL WEB TRỰC TUYẾN (HỖ TRỢ PAUSE/RESUME) ---
            # =========================================================================
            else:
                page.goto(self.target_path, timeout=60000)
                self.log_signal.emit("\n" + "="*60)
                self.log_signal.emit("✅ TRÌNH DUYỆT ĐÃ MỞ THÀNH CÔNG!")
                self.log_signal.emit("1. Vui lòng đăng nhập tài khoản trên trình duyệt để xem trọn vẹn các trang.")
                self.log_signal.emit("2. Vượt qua các bước xác thực Captcha (nếu có).")
                self.log_signal.emit("3. Sau khi hoàn tất, bấm nút [🚀 Bắt đầu lấy data] trên ứng dụng.")
                self.log_signal.emit("="*60 + "\n")

                while self.is_running and not self.start_crawl_event.is_set():
                    time.sleep(0.5)

                if not self.is_running: context.close(); return
                self.log_signal.emit("🚀 BẮT ĐẦU QUÁ TRÌNH TRÍCH XUẤT VÀ CRAWL DỮ LIỆU TỰ ĐỘNG...")
                
                page_num = 1
                while self.is_running:
                    if self.is_pause_requested:
                        self.log_signal.emit("\n" + "⏸️"*30)
                        self.log_signal.emit(f"⏸️ ĐÃ HOÀN TẤT TRANG {page_num - 1}. HỆ THỐNG ĐANG TẠM DỪNG THEO YÊU CẦU.")
                        self.log_signal.emit("Bấm nút [▶️ Tiếp tục lấy data] để tiến sang trang tiếp theo.")
                        self.log_signal.emit("⏸️"*30 + "\n")
                        
                        self.resume_event.clear(); self.paused_confirmed_signal.emit()
                        while not self.resume_event.is_set() and self.is_running: time.sleep(0.5)
                        if not self.is_running: break
                        self.log_signal.emit("▶️ ĐÃ MỞ KHÓA. TIẾP TỤC QUÁ TRÌNH CRAWL...")

                    self.log_signal.emit(f"\n📄 --- ĐANG QUÉT DỮ LIỆU TRANG {page_num} ---")
                    
                    topic_cards = page.locator(".topic-card").all()
                    for t_card in topic_cards:
                        current_topic = derive_topic_label(t_card.text_content() or "", current_topic)
                        self.log_signal.emit(f"🏷️ Phát hiện chủ đề mới: {current_topic}")

                    try: page.wait_for_selector(".exam-question-card", timeout=15000)
                    except: self.log_signal.emit("⚠️ Không tìm thấy thẻ câu hỏi (.exam-question-card) nào trên trang này.")
                    
                    cards = page.locator(".exam-question-card").all()
                    self.log_signal.emit(f"📊 Phát hiện {len(cards)} câu hỏi trên trang hiện tại.")

                    for card_idx, card in enumerate(cards, 1):
                        if not self.is_running: break
                        
                        header_text = card.locator(".card-header").text_content() or ""
                        q_num_match = re.search(r"Question\s*#\s*(\d+)", header_text, re.IGNORECASE)
                        q_num = q_num_match.group(1) if q_num_match else f"p{page_num}_{card_idx}"
                        
                        category = derive_topic_label(header_text, current_topic)
                        clean_topic_name = category.replace(" ", "-")
                        folder_name = f"{q_num}-{clean_topic_name}"

                        self.log_signal.emit(f"🔄 Trích xuất: Câu hỏi #{q_num} | Chủ đề: {category} | Định danh: {folder_name}")

                        try: card.scroll_into_view_if_needed()
                        except: pass

                        reveal_btn = card.locator(".reveal-solution")
                        if reveal_btn.count() > 0 and reveal_btn.first.is_visible():
                            try: reveal_btn.first.click(timeout=5000); time.sleep(0.5)
                            except: pass

                        body_loc = card.locator(".question-body")
                        q_text_loc = body_loc.locator("> .card-text").first
                        extracted_text = q_text_loc.text_content().strip() if q_text_loc.count() > 0 else ""
                        extracted_text = re.sub(r'\n+', '\n', extracted_text).strip()

                        choices_loc = body_loc.locator(".question-choices-container")
                        raw_choices_text = choices_loc.text_content().strip() if choices_loc.count() > 0 else "None"
                        choices_text = clean_examtopics_choices(raw_choices_text)

                        ans_block = card.locator(".question-answer")
                        raw_ans_text = ans_block.text_content().strip() if ans_block.count() > 0 else ""
                        
                        vote_ans_idx = re.search(r"Community\s+vote\s+distribution", raw_ans_text, re.IGNORECASE)
                        if vote_ans_idx: raw_ans_text = raw_ans_text[:vote_ans_idx.start()]
                        ans_text = re.sub(r'\n+', '\n', raw_ans_text).strip()

                        final_answer_val = ""
                        correct_ans_box = card.locator(".correct-answer-box")
                        full_ans_block_text = correct_ans_box.first.text_content() if correct_ans_box.count() > 0 else ans_text
                            
                        if full_ans_block_text:
                            match_ans = re.search(r"Correct\s+Answer:\s*([A-Z]+)", full_ans_block_text, re.IGNORECASE)
                            if match_ans:
                                final_answer_val = ",".join(list(match_ans.group(1).upper()))
                                self.log_signal.emit(f"    🎯 Đã bóc tách tự động Đáp án: '{final_answer_val}'")

                        q_type = "Chọn"
                        if any(k in extracted_text.lower() for k in ["drag drop", "drag and drop", "hotspot"]): q_type = "Kéo thả"
                        elif any(k in extracted_text.lower() for k in ["simulation", "lab"]): q_type = "Lab"

                        all_imgs = body_loc.locator("img").all()
                        target_dir = os.path.join(self.img_folder, folder_name)
                        source_name = f"📁 {folder_name}"  
                        
                        if len(all_imgs) > 0:
                            os.makedirs(target_dir, exist_ok=True)
                            img_counter = 1; ans_counter = 1
                            
                            for img in all_imgs:
                                src = img.get_attribute("src")
                                if not src: continue
                                
                                abs_url = urljoin(page.url, src)
                                is_answer_img = img.evaluate("node => !!node.closest('.question-answer')")
                                
                                ext = abs_url.split(".")[-1].split("?")[0]
                                if len(ext) > 5 or not ext: ext = "png"
                                
                                filename = f"{q_num}-{ans_counter}-answer.{ext}" if is_answer_img else f"{q_num}-{img_counter}.{ext}"
                                if is_answer_img: ans_counter += 1
                                else: img_counter += 1
                                    
                                filepath = os.path.join(target_dir, filename)
                                
                                try:
                                    res = context.request.get(abs_url)
                                    if res.ok:
                                        with open(filepath, "wb") as f: f.write(res.body())
                                        self.log_signal.emit(f"    📥 Đã tải ảnh: {filename}")
                                except Exception as e:
                                    self.log_signal.emit(f"    ⚠️ Lỗi kết nối tải ảnh {filename}: {str(e)}")
                        else:
                            os.makedirs(target_dir, exist_ok=True)

                        try:
                            conn = sqlite3.connect(self.db_path); cursor = conn.cursor()
                            cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                                source_name TEXT UNIQUE, extracted_text TEXT, vn_explanation TEXT,
                                choices TEXT, final_answer TEXT, answer TEXT, status TEXT, 
                                question_type TEXT DEFAULT 'Chọn', is_reliable INTEGER DEFAULT 1,
                                category TEXT DEFAULT 'Chưa phân loại', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                            
                            cursor.execute("PRAGMA table_info(questions)")
                            existing_cols = [c[1] for c in cursor.fetchall()]
                            if "category" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN category TEXT DEFAULT 'Chưa phân loại'")
                            if "question_type" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN question_type TEXT DEFAULT 'Chọn'")
                            if "is_reliable" not in existing_cols: cursor.execute("ALTER TABLE questions ADD COLUMN is_reliable INTEGER DEFAULT 1")

                            cursor.execute('''INSERT OR REPLACE INTO questions 
                                (source_name, extracted_text, choices, final_answer, answer, status, question_type, is_reliable, category)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                                source_name, extracted_text, choices_text, final_answer_val, ans_text, "done", q_type, 1, category
                            ))
                            conn.commit(); conn.close()
                            self.log_signal.emit(f"    💾 Đã lưu thành công {source_name} vào Database.")
                        except Exception as e:
                            self.log_signal.emit(f"    ❌ Lỗi ghi Database tại {source_name}: {str(e)}")

                        time.sleep(0.3)  

                    next_btn = page.locator("a:has-text('Next Questions')")
                    if next_btn.count() > 0 and next_btn.first.is_visible():
                        self.log_signal.emit(f"➡️ Đang chuẩn bị chuyển sang trang tiếp theo (Trang {page_num + 1})...")
                        try: next_btn.first.click(timeout=15000); page_num += 1; time.sleep(4)  
                        except Exception as e:
                            self.log_signal.emit(f"⚠️ Lỗi khi bấm chuyển trang: {str(e)}"); break
                    else:
                        self.log_signal.emit("\n" + "★"*60)
                        self.log_signal.emit("🏁 KHÔNG TÌM THẤY NÚT SANG TRANG. ĐÃ CRAWL HOÀN TẤT TOÀN BỘ WEB!")
                        self.log_signal.emit("★"*60)
                        break

            context.close()
            self.finished_signal.emit()

    def request_pause(self):
        self.is_pause_requested = True

    def request_resume(self):
        self.is_pause_requested = False
        self.resume_event.set()

    def stop(self):
        self.is_running = False
        self.resume_event.set() 

class CrawlerMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web Exam Crawler - Playwright Automation")
        self.resize(1100, 850)
        self.setStyleSheet(TAILWIND_QSS)
        
        self.settings = QSettings("MyAIWorkspace", "AzureSQLCrawler")
        self.crawler_thread = None
        
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_title = QLabel("🌐 HỆ THỐNG CRAWL CÂU HỎI THI TỰ ĐỘNG")
        lbl_title.setStyleSheet("font-size: 26px; font-weight: bold; color: #1F2937; margin-bottom: 5px;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        grp_config = QGroupBox("1. Cấu hình Tham số & Nguồn Dữ liệu (Bắt buộc)")
        cfg_layout = QVBoxLayout(grp_config)
        cfg_layout.setSpacing(12)

        mode_layout = QHBoxLayout()
        lbl_mode = QLabel("Chế độ Lấy Dữ liệu:"); lbl_mode.setFixedWidth(150); lbl_mode.setStyleSheet("font-weight: bold;")
        
        self.opt_url_mode = QRadioButton("🌐 Crawl từ URL trực tuyến")
        self.opt_local_mode = QRadioButton("📁 Crawl từ Thư mục HTML Nội bộ (Chống block)")
        
        self.btn_group_mode = QButtonGroup(self)
        self.btn_group_mode.addButton(self.opt_url_mode)
        self.btn_group_mode.addButton(self.opt_local_mode)
        
        saved_mode = self.settings.value("crawl_source_mode", "url")
        if saved_mode == "local_folder": self.opt_local_mode.setChecked(True)
        else: self.opt_url_mode.setChecked(True)
        
        self.opt_url_mode.toggled.connect(self.on_mode_switched)
        
        mode_layout.addWidget(lbl_mode); mode_layout.addWidget(self.opt_url_mode)
        mode_layout.addWidget(self.opt_local_mode); mode_layout.addStretch()
        cfg_layout.addLayout(mode_layout)

        self.row_source = QHBoxLayout()
        self.lbl_source_title = QLabel("Đường dẫn Web:")
        self.lbl_source_title.setFixedWidth(150); self.lbl_source_title.setStyleSheet("font-weight: bold;")
        
        self.txt_target_path = QLineEdit()
        self.btn_browse_html_folder = QPushButton("📁 Chọn thư mục HTML")
        self.btn_browse_html_folder.setObjectName("btnBrowse")
        self.btn_browse_html_folder.setFixedWidth(180)
        self.btn_browse_html_folder.clicked.connect(self.browse_html_folder)
        
        self.row_source.addWidget(self.lbl_source_title)
        self.row_source.addWidget(self.txt_target_path)
        self.row_source.addWidget(self.btn_browse_html_folder)
        cfg_layout.addLayout(self.row_source)

        row_db = QHBoxLayout()
        self.btn_browse_db = QPushButton("🗄️ Chọn file SQLite")
        self.btn_browse_db.setObjectName("btnBrowse"); self.btn_browse_db.setFixedWidth(180)
        self.btn_browse_db.clicked.connect(self.browse_db)
        
        saved_db = str(self.settings.value("last_db_path", ""))
        self.lbl_db_path = QLabel(saved_db if saved_db else "⚠️ Chưa chọn file SQLite (Bắt buộc)")
        self.lbl_db_path.setWordWrap(True); self.lbl_db_path.setStyleSheet("font-weight: bold; color: #111827;")
        row_db.addWidget(self.btn_browse_db); row_db.addWidget(self.lbl_db_path, stretch=1)
        cfg_layout.addLayout(row_db)

        row_img = QHBoxLayout()
        self.btn_browse_img = QPushButton("📁 Chọn thư mục ảnh")
        self.btn_browse_img.setObjectName("btnBrowse"); self.btn_browse_img.setFixedWidth(180)
        self.btn_browse_img.clicked.connect(self.browse_img)
        
        saved_img = str(self.settings.value("last_img_folder", ""))
        self.lbl_img_path = QLabel(saved_img if saved_img else "⚠️ Chưa chọn thư mục lưu ảnh gốc (Bắt buộc)")
        self.lbl_img_path.setWordWrap(True); self.lbl_img_path.setStyleSheet("font-weight: bold; color: #111827;")
        row_img.addWidget(self.btn_browse_img); row_img.addWidget(self.lbl_img_path, stretch=1)
        cfg_layout.addLayout(row_img)

        layout.addWidget(grp_config)

        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 5, 0, 5); action_layout.setSpacing(15)

        self.btn_open_browser = QPushButton("🌐 Lấy câu hỏi thi (Mở trình duyệt)")
        self.btn_open_browser.setObjectName("btnWarning"); self.btn_open_browser.setMinimumHeight(55)
        self.btn_open_browser.clicked.connect(self.start_crawler_execution)
        
        self.btn_start_crawling = QPushButton("🚀 Bắt đầu lấy data")
        self.btn_start_crawling.setObjectName("btnSuccess"); self.btn_start_crawling.setMinimumHeight(55)
        self.btn_start_crawling.setEnabled(False)  
        self.btn_start_crawling.clicked.connect(self.trigger_automation_crawl)

        self.btn_toggle_pause = QPushButton("⏸️ Dừng ở cuối trang")
        self.btn_toggle_pause.setObjectName("btnDanger"); self.btn_toggle_pause.setMinimumHeight(55)
        self.btn_toggle_pause.setEnabled(False) 
        self.btn_toggle_pause.clicked.connect(self.on_toggle_pause_clicked)

        action_layout.addWidget(self.btn_open_browser, stretch=3)
        action_layout.addWidget(self.btn_start_crawling, stretch=3)
        action_layout.addWidget(self.btn_toggle_pause, stretch=2)
        layout.addLayout(action_layout)

        grp_logs = QGroupBox("🖥️ Trạng thái & Nhật ký hoạt động (Logs)")
        log_layout = QVBoxLayout(grp_logs)
        self.txt_log = QTextEdit(); self.txt_log.setObjectName("LogArea"); self.txt_log.setReadOnly(True)
        log_layout.addWidget(self.txt_log)
        layout.addWidget(grp_logs, stretch=1)

        self.on_mode_switched() 
        self.append_log("Ứng dụng Crawler sẵn sàng. Hỗ trợ trích xuất cả Online và Nội bộ!")

    def on_mode_switched(self):
        if self.opt_local_mode.isChecked():
            self.settings.setValue("crawl_source_mode", "local_folder")
            self.lbl_source_title.setText("Thư mục HTML:")
            self.txt_target_path.setPlaceholderText("Chọn hoặc dán đường dẫn thư mục chứa các file .html đã lưu...")
            saved_local = self.settings.value("last_local_html_folder", "")
            self.txt_target_path.setText(str(saved_local))
            self.btn_browse_html_folder.setVisible(True)
            
            self.btn_open_browser.setText("⚡ Lấy dữ liệu nội bộ (Bắt đầu ngay)")
            self.btn_open_browser.setObjectName("btnSuccess") 
            self.btn_start_crawling.setVisible(False) 
            self.btn_toggle_pause.setVisible(False)   
        else:
            self.settings.setValue("crawl_source_mode", "url")
            self.lbl_source_title.setText("Đường dẫn Web:")
            self.txt_target_path.setPlaceholderText("Nhập URL trang câu hỏi thi (VD: https://www.examtopics.com/view/)...")
            saved_url = self.settings.value("last_crawl_url", "https://www.examtopics.com/exams/microsoft/dp-300/view/")
            self.txt_target_path.setText(str(saved_url))
            self.btn_browse_html_folder.setVisible(False)
            
            self.btn_open_browser.setText("🌐 Lấy câu hỏi thi (Mở trình duyệt)")
            self.btn_open_browser.setObjectName("btnWarning") 
            self.btn_start_crawling.setVisible(True)
            self.btn_toggle_pause.setVisible(True)
            
        self.btn_open_browser.style().unpolish(self.btn_open_browser)
        self.btn_open_browser.style().polish(self.btn_open_browser)

    def browse_html_folder(self):
        initial = self.txt_target_path.text() if os.path.isdir(self.txt_target_path.text()) else ""
        path = QFileDialog.getExistingDirectory(self, "Chọn Thư mục chứa các File HTML đã lưu", initial)
        if path:
            self.txt_target_path.setText(path)
            self.settings.setValue("last_local_html_folder", path)
            self.append_log(f"Đã chọn Thư mục HTML nguồn: {path}")

    def browse_db(self):
        initial = os.path.dirname(self.lbl_db_path.text()) if os.path.exists(self.lbl_db_path.text()) else ""
        path, _ = QFileDialog.getSaveFileName(self, "Chọn hoặc Tạo file SQLite DB", initial, "SQLite Database (*.db *.sqlite)")
        if path:
            self.lbl_db_path.setText(path)
            self.settings.setValue("last_db_path", path)
            self.append_log(f"Đã chọn CSDL: {path}")
            
            try:
                conn = sqlite3.connect(path); cursor = conn.cursor()
                cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                    source_name TEXT UNIQUE, extracted_text TEXT, vn_explanation TEXT,
                    choices TEXT, final_answer TEXT, answer TEXT, status TEXT, 
                    question_type TEXT DEFAULT 'Chọn', is_reliable INTEGER DEFAULT 1,
                    category TEXT DEFAULT 'Chưa phân loại', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                
                cursor.execute("DELETE FROM questions")
                deleted_rows = cursor.rowcount
                conn.commit(); conn.close()
                
                self.append_log(f"🗑️ Đã dọn dẹp sạch sẽ CSDL (Xóa {deleted_rows} bản ghi cũ, giữ nguyên cấu trúc bảng).")
                QMessageBox.information(self, "Dọn dẹp CSDL", f"Đã kết nối và xóa sạch {deleted_rows} câu hỏi cũ trong file CSDL.\nCấu trúc bảng được giữ nguyên, sẵn sàng cho phiên tải mới!")
            except Exception as e:
                self.append_log(f"❌ Lỗi khi dọn dẹp CSDL: {str(e)}")
                QMessageBox.critical(self, "Lỗi Database", f"Không thể dọn dẹp dữ liệu cũ trong CSDL:\n{str(e)}")

    def browse_img(self):
        initial = self.lbl_img_path.text() if os.path.exists(self.lbl_img_path.text()) else ""
        path = QFileDialog.getExistingDirectory(self, "Chọn Thư mục lưu Ảnh gốc", initial)
        if path:
            self.lbl_img_path.setText(path)
            self.settings.setValue("last_img_folder", path)
            self.append_log(f"Đã chọn thư mục ảnh: {path}")

    def append_log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{timestamp}] {text}")
        scrollbar = self.txt_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_crawler_execution(self):
        target_path = self.txt_target_path.text().strip()
        db_path = self.lbl_db_path.text().strip()
        img_folder = self.lbl_img_path.text().strip()
        mode = "local_folder" if self.opt_local_mode.isChecked() else "url"

        if not target_path:
            QMessageBox.warning(self, "Lỗi đầu vào", "Vui lòng cung cấp Đường dẫn Web hoặc Thư mục nguồn HTML hợp lệ!"); return
        if mode == "url" and not target_path.startswith("http"):
            QMessageBox.warning(self, "Lỗi đầu vào", "Vui lòng nhập đường dẫn Web (URL) bắt đầu bằng http/https!"); return
        if mode == "local_folder" and not os.path.isdir(target_path):
            QMessageBox.warning(self, "Lỗi đầu vào", "Thư mục nguồn HTML không hợp lệ hoặc không tồn tại!"); return
        if "⚠️" in db_path or not db_path:
            QMessageBox.warning(self, "Lỗi đầu vào", "Vui lòng chọn hoặc tạo file SQLite Database (Bắt buộc)!"); return
        if "⚠️" in img_folder or not os.path.exists(img_folder):
            QMessageBox.warning(self, "Lỗi đầu vào", "Vui lòng chọn thư mục lưu ảnh gốc hợp lệ (Bắt buộc)!"); return

        if mode == "url": self.settings.setValue("last_crawl_url", target_path)
        else: self.settings.setValue("last_local_html_folder", target_path)

        self.btn_open_browser.setEnabled(False); self.btn_browse_db.setEnabled(False); self.btn_browse_img.setEnabled(False)
        self.btn_browse_html_folder.setEnabled(False); self.txt_target_path.setEnabled(False)
        self.opt_url_mode.setEnabled(False); self.opt_local_mode.setEnabled(False)
        
        if mode == "url": self.btn_start_crawling.setEnabled(True)

        self.crawler_thread = CrawlerThread(mode, target_path, db_path, img_folder)
        self.crawler_thread.log_signal.connect(self.append_log)
        self.crawler_thread.error_signal.connect(self.handle_thread_error)
        self.crawler_thread.finished_signal.connect(self.handle_thread_finish)
        self.crawler_thread.paused_confirmed_signal.connect(self.handle_thread_paused) 
        
        if mode == "local_folder": self.crawler_thread.start_crawl_event.set()
        self.crawler_thread.start()

    def trigger_automation_crawl(self):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.btn_start_crawling.setEnabled(False); self.btn_toggle_pause.setEnabled(True) 
            self.append_log("Đã nhận xác nhận đăng nhập từ người dùng. Kích hoạt tự động hóa...")
            self.crawler_thread.start_crawl_event.set()

    def on_toggle_pause_clicked(self):
        if not self.crawler_thread: return
        if self.crawler_thread.is_pause_requested:
            self.crawler_thread.request_resume()
            self.btn_toggle_pause.setText("⏸️ Dừng ở cuối trang"); self.btn_toggle_pause.setObjectName("btnDanger")
            self.btn_toggle_pause.setStyleSheet("") 
            self.append_log("▶️ Người dùng yêu cầu TIẾP TỤC. Hệ thống sẽ tiến sang trang tiếp theo...")
        else:
            self.crawler_thread.request_pause()
            self.btn_toggle_pause.setText("⏳ Đang chờ hết trang..."); self.btn_toggle_pause.setEnabled(False) 
            self.append_log("⏳ Đã tiếp nhận lệnh DỪNG. Hệ thống sẽ tiếp tục làm hết trang hiện tại rồi mới tạm dừng.")

    def handle_thread_paused(self):
        self.btn_toggle_pause.setEnabled(True); self.btn_toggle_pause.setText("▶️ Tiếp tục lấy data"); self.btn_toggle_pause.setObjectName("btnSuccess")
        self.btn_toggle_pause.setStyleSheet("background-color: #10B981; color: white; border: 1px solid #059669;") 

    def handle_thread_error(self, err_msg):
        QMessageBox.critical(self, "Lỗi Playwright", err_msg); self.handle_thread_finish()

    def handle_thread_finish(self):
        self.btn_open_browser.setEnabled(True); self.btn_browse_db.setEnabled(True); self.btn_browse_img.setEnabled(True)
        self.btn_browse_html_folder.setEnabled(True); self.txt_target_path.setEnabled(True)
        self.opt_url_mode.setEnabled(True); self.opt_local_mode.setEnabled(True)
        
        self.btn_start_crawling.setEnabled(False); self.btn_toggle_pause.setEnabled(False)
        self.btn_toggle_pause.setText("⏸️ Dừng ở cuối trang"); self.btn_toggle_pause.setStyleSheet("")
        self.append_log("Tiến trình đã kết thúc hoàn toàn.")

    def closeEvent(self, event):
        if self.crawler_thread and self.crawler_thread.isRunning():
            self.crawler_thread.stop(); self.crawler_thread.start_crawl_event.set(); self.crawler_thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv); window = CrawlerMainWindow(); window.show(); sys.exit(app.exec())