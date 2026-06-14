import sys
import os
import sqlite3
import re
import time
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, 
                             QLabel, QHeaderView, QMessageBox, QLineEdit, QSplitter, 
                             QDialog, QFormLayout, QTextEdit, QComboBox, QCheckBox, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QThread
from PyQt6.QtGui import QColor, QPixmap

# --- KẾT NỐI TOÀN BỘ CÁC BỘ CẤU HÌNH GỐC ---
try:
    from config import OLLAMA_MODEL_LIST, OLLAMA_HOST_LIST, DEFAULT_PORT, QUESTION_CATEGORIES
    from styles import TAILWIND_QSS
except ImportError:
    print("Lỗi: Không tìm thấy file config.py hoặc styles.py trong thư mục.")
    sys.exit(1)

# =========================================================================
# --- HÀM SẮP XẾP & LÀM SẠCH KHOẢNG TRỐNG VĂN BẢN ---
# =========================================================================
def custom_exam_sort_key(s):
    if isinstance(s, dict):
        s_str = s.get('source_name', '')
    else:
        s_str = str(s)
        
    s_clean = s_str.replace("📁 ", "").strip()
    topic_match = re.search(r"Topic[- ](\d+)", s_clean, re.IGNORECASE)
    topic_num = int(topic_match.group(1)) if topic_match else 0
    
    q_match = re.match(r"^(\d+)", s_clean)
    q_num = int(q_match.group(1)) if q_match else 0
    
    return (topic_num, q_num, s_clean.lower())

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def format_choices_newlines(text):
    if not text: return ""
    return re.sub(r'(?<!\n)\s+([A-G]\.)', r'\n\1', text.strip())

def clean_excessive_whitespace(text):
    if not text: return ""
    lines = [line.strip() for line in text.split('\n')]
    cleaned_lines = []
    for l in lines:
        if l == "":
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
        else:
            cleaned_lines.append(l)
    return "\n".join(cleaned_lines).strip()

class AutoSaveTextEdit(QTextEdit):
    focusOut = pyqtSignal(str)
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusOut.emit(self.toPlainText())

class AutoSaveLineEdit(QLineEdit):
    focusOut = pyqtSignal(str)
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusOut.emit(self.text())

# =========================================================================
# --- WORKER THREADS: TRÍCH XUẤT ĐÁP ÁN (ANSWER) ---
# =========================================================================
class SingleExtractThread(QThread):
    finished = pyqtSignal(str, str)  
    error = pyqtSignal(str, str)     

    def __init__(self, host_address, model_name, img_path, source_name):
        super().__init__()
        self.host_address = host_address
        self.model_name = model_name
        self.img_path = img_path
        self.source_name = source_name

    def run(self):
        try:
            from ollama import Client
        except ImportError:
            self.error.emit(self.source_name, "Thư viện 'ollama' chưa được cài đặt. Dùng lệnh: pip install ollama")
            return

        try:
            base_url = f"http://{self.host_address}:{DEFAULT_PORT}"
            client = Client(host=base_url)

            vision_prompt = (
                "You are an expert automated exam scoring AI. Look closely at this exam explanation/answer image. "
                "Identify the correct answer section. Extract ONLY the final correct answer letter(s) (e.g., A, B, C, D). "
                "If there are multiple answers mapped to specific order/drag-and-drop slots, output them strictly separated by commas in the correct visual sequence from top to bottom or left to right (Example format: E,D,F,C). "
                "CRITICAL: Output absolutely nothing else. Do not include introductory text, explanations, markdown formatting, or backticks."
            )

            res = client.chat(
                model=self.model_name,
                messages=[{
                    'role': 'user',
                    'content': vision_prompt,
                    'images': [self.img_path]
                }]
            )
            
            raw_output = res.get('message', {}).get('content', '').strip()
            clean_ans = re.sub(r'```.*?```', '', raw_output).replace('`', '').strip()
            if ":" in clean_ans: clean_ans = clean_ans.split(":")[-1].strip()
            clean_ans = ",".join([part.strip().upper() for part in clean_ans.split(",") if part.strip()])
            
            self.finished.emit(self.source_name, clean_ans)
        except Exception as e:
            self.error.emit(self.source_name, f"Không thể kết nối Host [{self.host_address}]: {str(e)}")

class AutoExtractThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_scan = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, db_path, base_img_folder, host_address, model_name):
        super().__init__()
        self.db_path = db_path
        self.base_img_folder = base_img_folder
        self.host_address = host_address
        self.model_name = model_name

    def run(self):
        try:
            from ollama import Client
        except ImportError:
            self.error.emit("Thư viện 'ollama' chưa được cài đặt.")
            return

        conn = None
        try:
            base_url = f"http://{self.host_address}:{DEFAULT_PORT}"
            client = Client(host=base_url)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT source_name FROM questions WHERE final_answer IS NULL OR trim(final_answer) = ''")
            records = cursor.fetchall()
            total = len(records)
            if total == 0:
                self.finished_scan.emit(0); return

            updated_count = 0
            vision_prompt = (
                "You are an expert automated exam scoring AI. Look closely at this exam explanation/answer image. "
                "Identify the correct answer section. Extract ONLY the final correct answer letter(s) (e.g., A, B, C, D). "
                "CRITICAL: Output absolutely nothing else."
            )

            for idx, row in enumerate(records):
                source_name = row[0]
                self.progress.emit(idx + 1, total, f"Đang trích xuất Đáp Án ({self.host_address}): {source_name}...")
                
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
                        res = client.chat(
                            model=self.model_name,
                            messages=[{'role': 'user', 'content': vision_prompt, 'images': [ans_img_path]}]
                        )
                        raw_output = res.get('message', {}).get('content', '').strip()
                        clean_ans = re.sub(r'```.*?```', '', raw_output).replace('`', '').strip()
                        if ":" in clean_ans: clean_ans = clean_ans.split(":")[-1].strip()
                        clean_ans = ",".join([part.strip().upper() for part in clean_ans.split(",") if part.strip()])

                        if clean_ans:
                            # Lấy đáp án thì VẪN HẠ CỜ TIN CẬY để user duyệt lại
                            cursor.execute("UPDATE questions SET final_answer = ?, is_reliable = 0 WHERE source_name = ?", (clean_ans, source_name))
                            conn.commit()
                            updated_count += 1
                    except Exception as e:
                        print(f"Ollama Error at [{source_name}]: {e}")
                        continue
                time.sleep(0.2)
            self.finished_scan.emit(updated_count)
        except Exception as e:
            self.error.emit(f"Lỗi luồng Bulk Extract: {str(e)}")
        finally:
            if conn: conn.close()

# =========================================================================
# --- WORKER THREADS: PHÂN LOẠI STUDY AREA ---
# =========================================================================
class SingleClassifyThread(QThread):
    finished = pyqtSignal(str, str)  
    error = pyqtSignal(str, str)     

    def __init__(self, host_address, model_name, question_text, img_path, source_name):
        super().__init__()
        self.host_address = host_address
        self.model_name = model_name
        self.question_text = question_text
        self.img_path = img_path
        self.source_name = source_name

    def run(self):
        try:
            from ollama import Client
        except ImportError:
            self.error.emit(self.source_name, "Thiếu thư viện 'ollama'.")
            return

        try:
            base_url = f"http://{self.host_address}:{DEFAULT_PORT}"
            client = Client(host=base_url)

            categories_str = "\n".join([f"- {c}" for c in QUESTION_CATEGORIES if c != "Chưa phân loại"])
            prompt = f"""You are an expert IT certification classifier.
Analyze the following exam question (provided via text and/or image) and classify it into exactly ONE of the following Study Areas:
{categories_str}

Question Text:
{self.question_text}

CRITICAL RULE: Return ONLY the exact text of the matching Study Area from the list above. Do not add explanations, intro, or markdown formatting."""

            msg_payload = {'role': 'user', 'content': prompt}
            if self.img_path and os.path.isfile(self.img_path):
                msg_payload['images'] = [self.img_path]

            res = client.chat(model=self.model_name, messages=[msg_payload])
            raw_output = res.get('message', {}).get('content', '').strip()
            clean_cat = re.sub(r'```.*?```', '', raw_output).replace('`', '').strip()

            final_area = "Chưa phân loại"
            for valid_cat in QUESTION_CATEGORIES:
                if valid_cat.lower() in clean_cat.lower() and valid_cat != "Chưa phân loại":
                    final_area = valid_cat
                    break

            self.finished.emit(self.source_name, final_area)
        except Exception as e:
            self.error.emit(self.source_name, f"Lỗi phân loại Study Area: {str(e)}")

class AutoClassifyThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished_scan = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, db_path, base_img_folder, host_address, model_name):
        super().__init__()
        self.db_path = db_path
        self.base_img_folder = base_img_folder
        self.host_address = host_address
        self.model_name = model_name

    def run(self):
        try:
            from ollama import Client
        except ImportError:
            self.error.emit("Thiếu thư viện 'ollama'.")
            return

        conn = None
        try:
            base_url = f"http://{self.host_address}:{DEFAULT_PORT}"
            client = Client(host=base_url)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT source_name, extracted_text FROM questions WHERE study_area IS NULL OR study_area = 'Chưa phân loại' OR study_area = ''")
            records = cursor.fetchall()
            total = len(records)
            if total == 0:
                self.finished_scan.emit(0); return

            updated_count = 0
            categories_str = "\n".join([f"- {c}" for c in QUESTION_CATEGORIES if c != "Chưa phân loại"])

            for idx, row in enumerate(records):
                source_name, extracted_text = row[0], row[1] or ""
                self.progress.emit(idx + 1, total, f"Đang phân loại Study Area: {source_name}...")
                
                q_img_path = None
                clean_source = source_name.replace("📁 ", "").strip()
                full_dir = os.path.join(self.base_img_folder, clean_source)
                
                if os.path.isdir(full_dir):
                    valid_exts = ('.png', '.jpg', '.jpeg')
                    all_files = [f for f in os.listdir(full_dir) if f.lower().endswith(valid_exts)]
                    for fname in sorted(all_files, key=natural_sort_key):
                        if "-answer" not in fname.lower():
                            q_img_path = os.path.join(full_dir, fname)
                            break
                
                prompt = f"""You are an expert IT certification classifier.
Analyze the following exam question (provided via text and/or image) and classify it into exactly ONE of the following Study Areas:
{categories_str}

Question Text:
{extracted_text}

CRITICAL RULE: Return ONLY the exact text of the matching Study Area from the list above. No intro, no explanations, no markdown."""

                msg_payload = {'role': 'user', 'content': prompt}
                if q_img_path and os.path.isfile(q_img_path):
                    msg_payload['images'] = [q_img_path]

                try:
                    res = client.chat(model=self.model_name, messages=[msg_payload])
                    raw_output = res.get('message', {}).get('content', '').strip()
                    clean_cat = re.sub(r'```.*?```', '', raw_output).replace('`', '').strip()
                    
                    final_area = "Chưa phân loại"
                    for valid_cat in QUESTION_CATEGORIES:
                        if valid_cat.lower() in clean_cat.lower() and valid_cat != "Chưa phân loại":
                            final_area = valid_cat
                            break

                    if final_area != "Chưa phân loại":
                        # Chỉ Update Cột Study_area, giữ nguyên is_reliable
                        cursor.execute("UPDATE questions SET study_area = ? WHERE source_name = ?", (final_area, source_name))
                        conn.commit()
                        updated_count += 1
                except Exception as e:
                    print(f"Ollama Classify Error at [{source_name}]: {e}")
                    continue
                time.sleep(0.2)
                
            self.finished_scan.emit(updated_count)
        except Exception as e:
            self.error.emit(f"Lỗi luồng Bulk Classify: {str(e)}")
        finally:
            if conn: conn.close()

# =========================================================================
# --- DATABASE HELPER ---
# =========================================================================
class DatabaseHelper:
    def __init__(self, db_path):
        self.db_path = db_path
        self.migrate_schema()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def migrate_schema(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(questions)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        if "question_type" not in existing_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN question_type TEXT DEFAULT 'Chọn'")
        if "is_reliable" not in existing_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN is_reliable INTEGER DEFAULT 1")
        if "category" not in existing_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN category TEXT DEFAULT 'Chưa phân loại'")
        if "study_area" not in existing_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN study_area TEXT DEFAULT 'Chưa phân loại'")
            
        conn.commit(); conn.close()

    def get_all_records(self, search_query="", missing_answer_only=False):
        conn = self.get_connection()
        cursor = conn.cursor()
        query = f"%{search_query}%"
        
        base_sql = """
            SELECT source_name, extracted_text, vn_explanation, choices, 
                   final_answer, answer, status, question_type, is_reliable, category, study_area
            FROM questions
            WHERE (source_name LIKE ? 
               OR extracted_text LIKE ?
               OR choices LIKE ?
               OR answer LIKE ?
               OR final_answer LIKE ?
               OR question_type LIKE ?
               OR category LIKE ?
               OR study_area LIKE ?)
        """
        
        if missing_answer_only:
            base_sql += " AND (final_answer IS NULL OR trim(final_answer) = '')"
            
        cursor.execute(base_sql, (query, query, query, query, query, query, query, query))
        columns = [column[0] for column in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return results

    def update_single_field(self, source_name, field_name, new_value):
        conn = self.get_connection()
        cursor = conn.cursor()
        query = f"UPDATE questions SET {field_name} = ? WHERE source_name = ?"
        cursor.execute(query, (new_value, source_name))
        conn.commit(); conn.close()

    def update_record(self, original_source_name, data):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE questions SET 
                source_name = ?, extracted_text = ?, choices = ?, 
                final_answer = ?, answer = ?, status = ?, question_type = ?, is_reliable = ?, category = ?, study_area = ?
            WHERE source_name = ?
        """, (
            data['source_name'], data['extracted_text'], data['choices'],
            data['final_answer'], data['answer'], data['status'], data['question_type'], 
            data['is_reliable'], data['category'], data['study_area'], original_source_name
        ))
        conn.commit(); conn.close()

    def normalize_lab_types(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE questions SET question_type = 'Lab' WHERE source_name LIKE '%lab%'")
        updated_count = cursor.rowcount
        conn.commit(); conn.close()
        return updated_count

    def auto_clean_and_update_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        total_updated = 0
        try:
            cursor.execute("SELECT source_name, category FROM questions WHERE source_name LIKE '%Topic%'")
            for row in cursor.fetchall():
                source_name, current_cat = row[0], row[1]
                clean_source = source_name.replace("📁 ", "").strip()
                match = re.search(r"(Topic[- ]\d+)", clean_source, re.IGNORECASE)
                if match:
                    new_cat = match.group(1).replace("-", " ").title()
                    if new_cat != current_cat:
                        cursor.execute("UPDATE questions SET category = ? WHERE source_name = ?", (new_cat, source_name))
                        total_updated += 1
                        
            cursor.execute("SELECT source_name, answer FROM questions WHERE answer LIKE '%🗳️%'")
            for row in cursor.fetchall():
                source_name, current_ans = row[0], row[1]
                if current_ans:
                    new_ans = clean_excessive_whitespace(current_ans.replace("🗳️", ""))
                    cursor.execute("UPDATE questions SET answer = ? WHERE source_name = ?", (new_ans, source_name))
                    total_updated += 1
            conn.commit()
            return total_updated
        except Exception as e:
            print(f"Lỗi dọn dẹp DB ngầm: {e}")
            return total_updated
        finally:
            conn.close()

    def delete_record(self, source_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM questions WHERE source_name = ?", (source_name,))
        conn.commit(); conn.close()

# =========================================================================
# --- EDIT DIALOG ---
# =========================================================================
class EditDialog(QDialog):
    def __init__(self, parent=None, record_data=None, base_image_folder=""):
        super().__init__(parent)
        self.record_data = record_data or {}
        
        self.setWindowTitle("Chỉnh sửa Dữ liệu nâng cao")
        self.setStyleSheet(TAILWIND_QSS)
        
        self.txt_source = QLineEdit(self.record_data.get('source_name', ''))
        
        self.txt_extract = QTextEdit()
        self.txt_extract.setPlainText(self.record_data.get('extracted_text', ''))
        
        self.txt_choices = QTextEdit()
        self.txt_choices.setPlainText(format_choices_newlines(self.record_data.get('choices', '')))
        
        self.txt_final_ans = QTextEdit()
        self.txt_final_ans.setPlainText(self.record_data.get('final_answer', ''))
        self.txt_final_ans.setMaximumHeight(80) 
        
        self.txt_answer = QTextEdit()
        self.txt_answer.setPlainText(clean_excessive_whitespace(self.record_data.get('answer', '')))
        
        self.txt_status = QLineEdit(self.record_data.get('status', 'done'))
        
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Chọn", "Kéo thả", "Lab"])
        self.cmb_type.setCurrentText(self.record_data.get('question_type', 'Chọn'))
        
        self.txt_category = QLineEdit()
        self.txt_category.setText(self.record_data.get('category', 'Chưa phân loại'))
        self.txt_category.setReadOnly(True)
        
        self.cmb_study_area = QComboBox()
        self.cmb_study_area.addItems(QUESTION_CATEGORIES)
        self.cmb_study_area.setCurrentText(self.record_data.get('study_area', 'Chưa phân loại'))
        
        self.chk_reliable = QCheckBox("Câu hỏi này đã chuẩn (Đáng tin cậy)")
        self.chk_reliable.setChecked(bool(self.record_data.get('is_reliable', 1)))

        main_layout = QHBoxLayout(self)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        scroll_form = QScrollArea()
        scroll_form.setWidgetResizable(True)
        scroll_form.setStyleSheet("border: none; background: white;")
        
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.addRow("Tên File (Source):", self.txt_source)
        form_layout.addRow("Loại câu hỏi:", self.cmb_type)
        form_layout.addRow("Chủ đề (Topic):", self.txt_category)
        form_layout.addRow("Study Area:", self.cmb_study_area)
        form_layout.addRow("Độ tin cậy:", self.chk_reliable)
        form_layout.addRow("Đáp án:", self.txt_final_ans)
        form_layout.addRow("Trạng thái:", self.txt_status)
        form_layout.addRow("Nội dung trích xuất:", self.txt_extract)
        form_layout.addRow("Các lựa chọn:", self.txt_choices)
        form_layout.addRow("Giải thích:", self.txt_answer)
        
        scroll_form.setWidget(form_container)
        left_layout.addWidget(scroll_form, stretch=1)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Lưu thay đổi")
        btn_save.setObjectName("btnSuccess")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch(); btn_layout.addWidget(btn_cancel); btn_layout.addWidget(btn_save)
        left_layout.addLayout(btn_layout)
        main_layout.addWidget(left_widget, stretch=1)

        q_images = []
        ans_images = []
        if base_image_folder:
            source_name = self.record_data.get('source_name', '')
            full_dir = os.path.join(base_image_folder, source_name.replace("📁 ", "").strip())
            if os.path.isdir(full_dir):
                all_files = [f for f in os.listdir(full_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                for fname in sorted(all_files, key=natural_sort_key):
                    fpath = os.path.join(full_dir, fname)
                    if "-answer" in fname.lower(): ans_images.append(fpath)
                    else: q_images.append(fpath)

        has_any_image = bool(q_images or ans_images)
        self.resize(1400 if has_any_image else 800, 700) 
        
        if has_any_image:
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_content = QWidget()
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            
            if q_images:
                scroll_layout.addWidget(QLabel("<h3 style='color: #3B82F6;'>🖼️ Ảnh Đề bài</h3>"))
                for p in q_images: self.append_image_to_layout(scroll_layout, p)
            if ans_images:
                if q_images: scroll_layout.addWidget(QLabel("<hr>"))
                scroll_layout.addWidget(QLabel("<h3 style='color: #F59E0B;'>💡 Ảnh Đáp án</h3>"))
                for p in ans_images: self.append_image_to_layout(scroll_layout, p)
        
            scroll_area.setWidget(scroll_content)
            right_layout.addWidget(scroll_area)
            main_layout.addWidget(right_widget, stretch=1)

    def append_image_to_layout(self, layout, img_path):
        lbl_img = QLabel(); lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            lbl_img.setPixmap(pixmap.scaled(650, 3000, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            lbl_img.setText(f"❌ Lỗi tải ảnh: {os.path.basename(img_path)}")
        layout.addWidget(QLabel(f"<b>{os.path.basename(img_path)}</b>"))
        layout.addWidget(lbl_img)

    def get_data(self):
        return {
            'source_name': self.txt_source.text().strip(),
            'question_type': self.cmb_type.currentText(),
            'category': self.txt_category.text().strip(),
            'study_area': self.cmb_study_area.currentText(),
            'is_reliable': 1 if self.chk_reliable.isChecked() else 0,
            'extracted_text': self.txt_extract.toPlainText(),
            'choices': self.txt_choices.toPlainText(),
            'final_answer': self.txt_final_ans.toPlainText().strip(),
            'answer': self.txt_answer.toPlainText(),
            'status': self.txt_status.text().strip()
        }

# =========================================================================
# --- MAIN WINDOW ---
# =========================================================================
class DBManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SQLite Data Manager - Scalable Production Architecture")
        self.resize(1500, 850)
        self.setStyleSheet(TAILWIND_QSS)
        
        self.settings = QSettings("MyAIWorkspace", "AzureSQLAgent")
        self.base_image_folder = self.settings.value("last_img_folder", "")
        
        self.db_helper = None
        self.all_records_sorted = []
        self.current_page = 0
        self.items_per_page = 50
        
        self.ans_thread = None
        self.class_thread = None
        
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(15, 15, 15, 15)

        # Hàng 1: Nạp File
        top_layout = QHBoxLayout()
        self.btn_load = QPushButton("🗄️ Chọn file SQLite")
        self.btn_load.clicked.connect(self.open_db)
        self.btn_img_folder = QPushButton("📁 Chọn thư mục ảnh")
        self.btn_img_folder.clicked.connect(self.select_img_folder)
        self.btn_normalize_lab = QPushButton("🔬 Chuẩn hóa loại Lab")
        self.btn_normalize_lab.setObjectName("btnLabNormalize")
        self.btn_normalize_lab.clicked.connect(self.auto_normalize_lab_records)
        
        self.lbl_info = QLabel("Chưa tải CSDL.")
        self.lbl_info.setStyleSheet("font-weight: bold; color: #4B5563;")
        self.lbl_img_folder = QLabel(f"📁 Ảnh: {os.path.basename(self.base_image_folder)}" if self.base_image_folder else "Chưa chọn thư mục ảnh.")
        self.lbl_img_folder.setStyleSheet("font-weight: bold; color: #10B981;")
        
        top_layout.addWidget(self.btn_load); top_layout.addWidget(self.btn_img_folder); top_layout.addWidget(self.btn_normalize_lab)
        top_layout.addWidget(self.lbl_info); top_layout.addWidget(self.lbl_img_folder); top_layout.addStretch()
        layout.addLayout(top_layout)

        # Hàng 2: AI Toolkit & Search
        ai_search_layout = QHBoxLayout()
        ai_search_layout.setContentsMargins(0, 5, 0, 5)
        
        self.cmb_ai_host = QComboBox()
        self.cmb_ai_host.addItems(OLLAMA_HOST_LIST)
        if "127.0.0.1" in OLLAMA_HOST_LIST: self.cmb_ai_host.setCurrentText("127.0.0.1")
        elif OLLAMA_HOST_LIST: self.cmb_ai_host.setCurrentText(OLLAMA_HOST_LIST[0])
            
        self.cmb_ai_model = QComboBox()
        self.cmb_ai_model.addItems(OLLAMA_MODEL_LIST)
        if OLLAMA_MODEL_LIST: self.cmb_ai_model.setCurrentText(OLLAMA_MODEL_LIST[0])
            
        self.btn_auto_ai_ans = QPushButton("🤖 Auto Extract Đáp Án")
        self.btn_auto_ai_ans.setObjectName("btnAI")
        self.btn_auto_ai_ans.clicked.connect(self.start_ai_auto_extraction)
        
        self.btn_auto_classify = QPushButton("🏷️ Auto Classify Area (All)")
        self.btn_auto_classify.setStyleSheet("background-color: #8B5CF6; color: white; font-weight: bold; border-radius: 6px; padding: 6px 12px;")
        self.btn_auto_classify.clicked.connect(self.start_ai_auto_classify)
        
        self.chk_missing_ans = QCheckBox("⚠️ Lọc chưa có đáp án")
        self.chk_missing_ans.stateChanged.connect(self.on_search)
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Tìm kiếm theo File, Nội dung, Đáp án, Study Area...")
        self.txt_search.textChanged.connect(self.on_search)
        
        ai_search_layout.addWidget(self.cmb_ai_host); ai_search_layout.addWidget(self.cmb_ai_model)
        ai_search_layout.addWidget(self.btn_auto_ai_ans); ai_search_layout.addWidget(self.btn_auto_classify)
        ai_search_layout.addWidget(self.chk_missing_ans); ai_search_layout.addWidget(self.txt_search, stretch=1)
        layout.addLayout(ai_search_layout)

        # Bảng Dữ Liệu
        self.table = QTableWidget(0, 10) 
        self.table.setShowGrid(True)
        self.table.setHorizontalHeaderLabels([
            "File ảnh", "Nội dung", "Loại", "Chủ đề (Topic)", "Study Area", "Tin cậy?", "Các lựa chọn", "Đáp án", "Giải thích", "Hành động"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(2, 100)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(3, 110)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(4, 250)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive); self.table.setColumnWidth(7, 120) 
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(9, 360) 
        
        self.table.verticalHeader().setDefaultSectionSize(180)
        layout.addWidget(self.table)

        p_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Trang trước")
        self.btn_prev.clicked.connect(self.prev_page)
        self.lbl_page = QLabel("Trang 1 / 1 (50 phần tử/trang)")
        self.btn_next = QPushButton("Trang sau")
        self.btn_next.clicked.connect(self.next_page)
        
        p_layout.addStretch(); p_layout.addWidget(self.btn_prev); p_layout.addWidget(self.lbl_page); p_layout.addWidget(self.btn_next); p_layout.addStretch()
        layout.addLayout(p_layout)
        
        self.update_ui_states()

    def update_ui_states(self):
        is_ready = bool(self.db_helper and self.base_image_folder)
        self.btn_auto_ai_ans.setEnabled(is_ready)
        self.btn_auto_classify.setEnabled(is_ready)
        self.btn_normalize_lab.setEnabled(bool(self.db_helper))

    def select_img_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh", self.base_image_folder)
        if folder:
            self.base_image_folder = folder
            self.settings.setValue("last_img_folder", folder)
            self.lbl_img_folder.setText(f"📁 Ảnh: {os.path.basename(folder)}")
            self.update_ui_states()
            if self.db_helper: self.fetch_and_sort_data()

    def open_db(self):
        db_path, _ = QFileDialog.getOpenFileName(self, "Chọn file SQLite", "", "SQLite Database (*.db *.sqlite)")
        if not db_path: return
        try:
            self.db_helper = DatabaseHelper(db_path)
            self.lbl_info.setText(f"🗄️ Đang làm việc với: {os.path.basename(db_path)}")
            self.current_page = 0
            self.txt_search.clear()
            self.chk_missing_ans.setChecked(False)
            
            if self.base_image_folder:
                self.db_helper.auto_clean_and_update_db()
            self.update_ui_states()
            self.fetch_and_sort_data()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể đọc CSDL:\n{str(e)}")

    def on_search(self):
        if not self.db_helper: return
        self.current_page = 0
        self.fetch_and_sort_data()

    def fetch_and_sort_data(self):
        if not self.db_helper: return
        search_query = self.txt_search.text().strip()
        is_missing_only = self.chk_missing_ans.isChecked()
        raw_records = self.db_helper.get_all_records(search_query, missing_answer_only=is_missing_only)
        self.all_records_sorted = sorted(raw_records, key=custom_exam_sort_key)
        self.render_page()

    def auto_normalize_lab_records(self):
        if not self.db_helper: return
        reply = QMessageBox.question(self, "Xác nhận", "Chuyển các file ảnh chứa 'lab' sang loại 'Lab'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                v_scroll = self.table.verticalScrollBar().value()
                updated = self.db_helper.normalize_lab_types()
                self.fetch_and_sort_data()
                self.table.verticalScrollBar().setValue(v_scroll)
                QMessageBox.information(self, "Thành công", f"Chuẩn hóa {updated} bản ghi!")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", str(e))

    def render_page(self):
        total_items = len(self.all_records_sorted)
        offset = self.current_page * self.items_per_page
        page_records = self.all_records_sorted[offset : offset + self.items_per_page]
        
        self.table.setRowCount(0)
        for d in page_records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            source = d['source_name']
            
            self.table.setItem(row, 0, QTableWidgetItem(source))
            for col in range(1, 10): self.table.setItem(row, col, QTableWidgetItem())
            
            # Cột 1: Content
            txt_content = AutoSaveTextEdit(); txt_content.setPlainText(d.get('extracted_text', ''))
            txt_content.setStyleSheet("border: none; background: transparent;")
            txt_content.focusOut.connect(lambda text, src=source, f="extracted_text": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 1, txt_content)
            
            # Cột 2: Type
            cmb_type = QComboBox(); cmb_type.addItems(["Chọn", "Kéo thả", "Lab"]); cmb_type.setCurrentText(d.get('question_type', 'Chọn'))
            cmb_type.setStyleSheet("QComboBox { border: none; background: transparent; }")
            cmb_type.currentTextChanged.connect(lambda text, src=source, f="question_type": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 2, cmb_type)
            
            # Cột 3: Topic (Read-only)
            cat_item = QTableWidgetItem(d.get('category', 'Chưa phân loại'))
            cat_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 3, cat_item)

            # Cột 4: Study Area
            cmb_study = QComboBox()
            cmb_study.addItems(QUESTION_CATEGORIES)
            cmb_study.setCurrentText(d.get('study_area', 'Chưa phân loại'))
            cmb_study.setStyleSheet("QComboBox { border: none; background: transparent; font-size: 13px; }")
            cmb_study.currentTextChanged.connect(lambda text, src=source, f="study_area": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 4, cmb_study)
            
            # Cột 5: Reliable
            is_rel = d.get('is_reliable', 1)
            btn_rel = QPushButton("✅ Chuẩn" if is_rel == 1 else "⚠️ Xem lại")
            btn_rel.setStyleSheet("color: #1F2937; background: transparent; border: none; font-weight: bold;")
            btn_rel.clicked.connect(lambda checked, src=source: self.toggle_reliable(src))
            self.table.setCellWidget(row, 5, btn_rel)
            
            # Cột 6: Choices
            txt_choices = AutoSaveTextEdit(); txt_choices.setPlainText(d.get('choices', ''))
            txt_choices.setStyleSheet("border: none; background: transparent;")
            txt_choices.focusOut.connect(lambda text, src=source, f="choices": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 6, txt_choices)
            
            # Cột 7: Answer
            cur_ans = d.get('final_answer', '').strip()
            txt_ans = AutoSaveTextEdit(); txt_ans.setPlainText(cur_ans)
            txt_ans.setStyleSheet("border: none; background: transparent;")
            txt_ans.focusOut.connect(lambda text, src=source, f="final_answer": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 7, txt_ans)
            
            # Cột 8: Explanation
            txt_exp = AutoSaveTextEdit(); txt_exp.setPlainText(d.get('answer', ''))
            txt_exp.setStyleSheet("border: none; background: transparent;")
            txt_exp.focusOut.connect(lambda text, src=source, f="answer": self.inline_save(src, f, text))
            self.table.setCellWidget(row, 8, txt_exp)
            
            # Cột 9: Actions (4 Buttons)
            btn_layout = QHBoxLayout(); btn_layout.setContentsMargins(2, 0, 2, 0); btn_layout.setSpacing(4); btn_layout.addStretch()
            
            btn_ai_ans = QPushButton("🤖 Đ.Án")
            btn_ai_ans.setObjectName("btnAI")
            btn_ai_ans.setToolTip("Trích xuất Đáp Án")
            btn_ai_ans.clicked.connect(lambda checked, src=source: self.trigger_single_row_ans(src))
            
            btn_ai_area = QPushButton("🏷️ Phân loại")
            btn_ai_area.setStyleSheet("background-color: #8B5CF6; color: white; border-radius: 4px; padding: 4px;")
            btn_ai_area.setToolTip("Phân tích AI để gán Study Area")
            btn_ai_area.clicked.connect(lambda checked, src=source, txt=d.get('extracted_text',''): self.trigger_single_row_classify(src, txt))
            
            btn_edit = QPushButton("✏️ Sửa"); btn_edit.setObjectName("btnEdit"); btn_edit.clicked.connect(lambda checked, r=d: self.edit_record(r))
            btn_del = QPushButton("🗑️ Xóa"); btn_del.setObjectName("btnDelete"); btn_del.clicked.connect(lambda checked, n=source: self.delete_record(n))
            
            if not cur_ans: 
                btn_layout.addWidget(btn_ai_ans)
                
            btn_layout.addWidget(btn_ai_area) # Luôn luôn hiện nút Phân Loại Area
            btn_layout.addWidget(btn_edit)
            btn_layout.addWidget(btn_del)
            
            btn_container = QWidget()
            btn_container.setLayout(btn_layout)
            self.table.setCellWidget(row, 9, btn_container)
            
            if is_rel == 0:
                for col in range(10):
                    if self.table.item(row, col): self.table.item(row, col).setBackground(QColor("#FEF3C7"))

        total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        filter_text = " (Đang lọc thiếu đáp án)" if self.chk_missing_ans.isChecked() else ""
        self.lbl_page.setText(f"Trang {self.current_page + 1} / {total_pages} — Tổng: {total_items} câu{filter_text}")
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled((offset + self.items_per_page) < total_items)

    def inline_save(self, source_name, field_name, new_text):
        try:
            self.db_helper.update_single_field(source_name, field_name, new_text.strip())
            for r in self.all_records_sorted:
                if r['source_name'] == source_name:
                    r[field_name] = new_text.strip()
                    break
            
            if field_name in ["final_answer", "study_area"]:
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(200, lambda: self.refresh_table_keep_scroll())
        except Exception as e:
            print(f"Auto-save error: {e}")

    def refresh_table_keep_scroll(self):
        v_scroll = self.table.verticalScrollBar().value()
        self.render_page()
        self.table.verticalScrollBar().setValue(v_scroll)

    def toggle_reliable(self, source_name):
        try:
            record = next((r for r in self.all_records_sorted if r['source_name'] == source_name), None)
            if not record: return
            new_status = 0 if record.get('is_reliable', 1) == 1 else 1
            self.db_helper.update_single_field(source_name, 'is_reliable', new_status)
            record['is_reliable'] = new_status
            self.refresh_table_keep_scroll()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", str(e))

    def prev_page(self): self.current_page -= 1; self.render_page()
    def next_page(self): self.current_page += 1; self.render_page()

    def edit_record(self, record_data):
        if not self.base_image_folder:
            QMessageBox.information(self, "Lưu ý", "Chưa 'Chọn thư mục ảnh'. Form không hiện ảnh.")
        dialog = EditDialog(self, record_data, self.base_image_folder)
        if dialog.exec(): 
            try:
                v_scroll = self.table.verticalScrollBar().value()
                self.db_helper.update_record(record_data['source_name'], dialog.get_data())
                self.fetch_and_sort_data() 
                self.table.verticalScrollBar().setValue(v_scroll)
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", str(e))

    def delete_record(self, source_name):
        if QMessageBox.question(self, "Xóa", f"Xóa '{source_name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                v_scroll = self.table.verticalScrollBar().value()
                self.db_helper.delete_record(source_name)
                self.fetch_and_sort_data()
                self.table.verticalScrollBar().setValue(v_scroll)
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", str(e))

    # --- AI: TRÍCH XUẤT ĐÁP ÁN ---
    def trigger_single_row_ans(self, source_name):
        ans_img_path = None
        full_dir = os.path.join(self.base_image_folder, source_name.replace("📁 ", "").strip())
        if os.path.isdir(full_dir):
            for fname in sorted([f for f in os.listdir(full_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))], key=natural_sort_key):
                if "-answer" in fname.lower(): ans_img_path = os.path.join(full_dir, fname); break

        if not ans_img_path: return QMessageBox.warning(self, "Thiếu ảnh", "Không tìm thấy ảnh '-answer'.")

        self.table.setEnabled(False)
        self.lbl_info.setText(f"⏳ Đang lấy Đáp Án: {source_name}...")
        self.ans_thread = SingleExtractThread(self.cmb_ai_host.currentText(), self.cmb_ai_model.currentText(), ans_img_path, source_name)
        self.ans_thread.finished.connect(self.on_single_ans_success)
        self.ans_thread.error.connect(self.on_ai_error)
        self.ans_thread.start()

    def on_single_ans_success(self, source_name, clean_answer):
        self.table.setEnabled(True) 
        self.lbl_info.setText("Hoàn thành."); self.lbl_info.setStyleSheet("color: #10B981;")
        if not clean_answer: return QMessageBox.warning(self, "Cảnh báo", "Không trích xuất được.")
        
        conn = self.db_helper.get_connection()
        conn.cursor().execute("UPDATE questions SET final_answer = ?, is_reliable = 0 WHERE source_name = ?", (clean_answer, source_name))
        conn.commit(); conn.close()
        
        for r in self.all_records_sorted:
            if r['source_name'] == source_name: r['final_answer'] = clean_answer; r['is_reliable'] = 0; break
        self.refresh_table_keep_scroll()

    def start_ai_auto_extraction(self):
        if not self.db_helper or not self.base_image_folder:
            QMessageBox.warning(self, "Lưu ý", "Vui lòng 'Chọn file SQLite' và 'Chọn thư mục ảnh' trước khi chạy AI!")
            return
            
        missing = len(self.db_helper.get_all_records(missing_answer_only=True))
        if missing == 0: return QMessageBox.information(self, "OK", "Đã đủ đáp án!")
        
        if QMessageBox.question(self, "Bulk Extract", f"Lấy đáp án cho {missing} câu?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.table.setEnabled(False)
            self.ans_thread = AutoExtractThread(self.db_helper.db_path, self.base_image_folder, self.cmb_ai_host.currentText(), self.cmb_ai_model.currentText())
            self.ans_thread.progress.connect(self.update_ai_progress)
            self.ans_thread.finished_scan.connect(self.on_bulk_success)
            self.ans_thread.error.connect(self.on_ai_error)
            self.ans_thread.start()

    # --- AI: PHÂN LOẠI STUDY AREA ---
    def trigger_single_row_classify(self, source_name, extracted_text):
        q_img_path = None
        full_dir = os.path.join(self.base_image_folder, source_name.replace("📁 ", "").strip())
        if os.path.isdir(full_dir):
            for fname in sorted([f for f in os.listdir(full_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))], key=natural_sort_key):
                if "-answer" not in fname.lower(): q_img_path = os.path.join(full_dir, fname); break

        self.table.setEnabled(False)
        self.lbl_info.setText(f"⏳ Đang phân loại Study Area: {source_name}...")
        self.class_thread = SingleClassifyThread(self.cmb_ai_host.currentText(), self.cmb_ai_model.currentText(), extracted_text, q_img_path, source_name)
        self.class_thread.finished.connect(self.on_single_class_success)
        self.class_thread.error.connect(self.on_ai_error)
        self.class_thread.start()

    def on_single_class_success(self, source_name, final_area):
        self.table.setEnabled(True) 
        self.lbl_info.setText(f"✅ Đã phân loại: {final_area}"); self.lbl_info.setStyleSheet("color: #10B981;")
        
        conn = self.db_helper.get_connection()
        # Không hạ cờ is_reliable
        conn.cursor().execute("UPDATE questions SET study_area = ? WHERE source_name = ?", (final_area, source_name))
        conn.commit(); conn.close()
        
        for r in self.all_records_sorted:
            if r['source_name'] == source_name: r['study_area'] = final_area; break
        self.refresh_table_keep_scroll()

    def start_ai_auto_classify(self):
        if not self.db_helper or not self.base_image_folder:
            QMessageBox.warning(self, "Lưu ý", "Vui lòng 'Chọn file SQLite' và 'Chọn thư mục ảnh' trước khi chạy AI!")
            return

        conn = self.db_helper.get_connection()
        missing = len(conn.cursor().execute("SELECT source_name FROM questions WHERE study_area IS NULL OR study_area = 'Chưa phân loại' OR study_area = ''").fetchall())
        conn.close()
        
        if missing == 0: return QMessageBox.information(self, "OK", "Tất cả đã được phân loại Study Area!")
        
        if QMessageBox.question(self, "Bulk Classify", f"Phân loại tự động cho {missing} câu?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.table.setEnabled(False)
            self.class_thread = AutoClassifyThread(self.db_helper.db_path, self.base_image_folder, self.cmb_ai_host.currentText(), self.cmb_ai_model.currentText())
            self.class_thread.progress.connect(self.update_ai_progress)
            self.class_thread.finished_scan.connect(self.on_bulk_success)
            self.class_thread.error.connect(self.on_ai_error)
            self.class_thread.start()

    def update_ai_progress(self, current, total, status_msg):
        self.lbl_info.setText(f"🤖 Tiến độ: {current}/{total} — {status_msg}")

    def on_bulk_success(self, updated_count):
        self.table.setEnabled(True)
        self.lbl_info.setText("Hoàn tất."); self.lbl_info.setStyleSheet("color: #4B5563;")
        self.fetch_and_sort_data()
        QMessageBox.information(self, "Thành công", f"Đã cập nhật AI thành công {updated_count} bản ghi.")

    def on_ai_error(self, src_or_msg, err_msg=None):
        self.table.setEnabled(True)
        msg = f"Lỗi tại {src_or_msg}: {err_msg}" if err_msg else src_or_msg
        self.lbl_info.setText("❌ Lỗi AI."); self.lbl_info.setStyleSheet("color: #DC2626;")
        QMessageBox.critical(self, "Lỗi Ollama", msg)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DBManagerWindow()
    window.show()
    sys.exit(app.exec())