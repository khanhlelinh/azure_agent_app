import sys
import os
import re
import datetime
import sqlite3
import json
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, 
                             QLabel, QHeaderView, QMessageBox, QComboBox, QGroupBox, QTextEdit, QSplitter, QLineEdit, QSpinBox)
from PyQt6.QtCore import Qt, QThreadPool, QSettings, QRunnable, pyqtSignal, QObject
from PyQt6.QtGui import QColor

# --- IMPORTS TỪ CÁC MODULE ĐÃ TÁCH ---
from config import MAX_CONCURRENT_TASKS, OLLAMA_HOST_LIST, OLLAMA_MODEL_LIST, DEFAULT_PORT
from styles import TAILWIND_QSS
from workers import AgentTask

QUESTION_CATEGORIES = [
    "Chưa phân loại",
    "Plan and implement data platform resources",
    "Implement a secure environment",
    "Monitor, configure, and optimize database resources",
    "Configure and manage automation of tasks",
    "Plan and configure a high availability and disaster recovery (HA/DR) environment"
]

# =========================================================================
# --- HÀM SẮP XẾP CHUYÊN DỤNG (Ưu tiên Topic trước -> Số Câu -> Tự nhiên) ---
# =========================================================================
def custom_exam_sort_key(s):
    if isinstance(s, dict):
        s_str = s.get('source_name', '')
    else:
        s_str = str(s)
        
    s_clean = s_str.replace("📁 ", "").strip()
    
    # 1. Quét tìm số Topic (VD: "1-Topic-1" -> 1)
    topic_match = re.search(r"Topic[- ](\d+)", s_clean, re.IGNORECASE)
    topic_num = int(topic_match.group(1)) if topic_match else 0
    
    # 2. Quét tìm số Câu hỏi đứng ở đầu (VD: "1-Topic-1" -> 1)
    q_match = re.match(r"^(\d+)", s_clean)
    q_num = int(q_match.group(1)) if q_match else 0
    
    return (topic_num, q_num, s_clean.lower())

def natural_sort_key(s):
    """Giữ lại cho sắp xếp tuần tự các file ảnh con (VD: 1-1.png, 1-2.png)"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

EXTENDED_QSS = TAILWIND_QSS + """
    QLineEdit, QSpinBox { border: 1px solid #D1D5DB; border-radius: 6px; padding: 8px; background: white; font-size: 14px; }
    QLineEdit:focus, QSpinBox:focus { border: 1px solid #3B82F6; outline: none; }
    QPushButton#btnLoadDB { background-color: #8B5CF6; }
    QPushButton#btnLoadDB:hover { background-color: #7C3AED; }
    QPushButton#btnClassifyAll { background-color: #059669; }
    QPushButton#btnClassifyAll:hover { background-color: #047857; }
"""

class ClassifySignals(QObject):
    update = pyqtSignal(int, str) 
    finished = pyqtSignal(int)
    log = pyqtSignal(str)

class ClassificationTask(QRunnable):
    def __init__(self, row_index: int, data: dict, host_url: str, model_name: str):
        super().__init__()
        self.row_index = row_index
        self.data = data
        self.host_url = host_url
        self.model_name = model_name
        self.signals = ClassifySignals()
        self.source = data.get("source_name", "Unknown")

    def run(self):
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage

        self.signals.log.emit(f"🏷️ Bắt đầu phân loại: {self.source}...")
        try:
            content_to_classify = self.data.get("extracted_text", "").strip()
            if not content_to_classify:
                self.signals.log.emit(f"⚠️ [{self.source}] Không có nội dung text để phân loại.")
                self.signals.update.emit(self.row_index, "Chưa phân loại")
                return

            llm = ChatOllama(model=self.model_name, base_url=self.host_url, temperature=0.0)
            
            prompt = f"""Bạn là một chuyên gia phân loại dữ liệu Microsoft Azure SQL.
Hãy đọc nội dung câu hỏi dưới đây, đối chiếu với các tiêu chí chi tiết của từng danh mục, và gán nó vào ĐÚNG MỘT danh mục gốc duy nhất.

[CÁC DANH MỤC GỐC VÀ TIÊU CHÍ CHI TIẾT]:
1. Plan and implement data platform resources
2. Implement a secure environment
3. Monitor, configure, and optimize database resources
4. Configure and manage automation of tasks
5. Plan and configure a high availability and disaster recovery (HA/DR) environment

[NỘI DUNG CÂU HỎI]:
{content_to_classify}

Chỉ trả về CHỈ MỘT tên danh mục gốc (tên tiếng Anh chính xác từ 1 đến 5). Tuyệt đối không giải thích."""

            response = llm.invoke([HumanMessage(content=prompt)])
            res_text = response.content.strip()

            matched_category = "Chưa phân loại"
            for cat in QUESTION_CATEGORIES:
                if cat != "Chưa phân loại" and cat.lower() in res_text.lower():
                    matched_category = cat
                    break
            
            if matched_category == "Chưa phân loại" and res_text in QUESTION_CATEGORIES:
                matched_category = res_text

            self.signals.update.emit(self.row_index, matched_category)
            self.signals.log.emit(f"✅ [{self.source}] Đã phân loại: {matched_category}")

        except Exception as e:
            self.signals.log.emit(f"❌ [{self.source}] Lỗi phân loại: {str(e)}")
            self.signals.update.emit(self.row_index, "Chưa phân loại")
        finally:
            self.signals.finished.emit(self.row_index)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Azure SQL Agentic Workspace - Production Ready")
        self.resize(1650, 950)
        self.setStyleSheet(EXTENDED_QSS)
        
        self.settings = QSettings("MyAIWorkspace", "AzureSQLAgent")
        self.all_data = []         
        self.filtered_data = []    
        self.current_page = 0
        self.items_per_page = 50 
        
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(MAX_CONCURRENT_TASKS)
        self.active_tasks = 0
        
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(15, 15, 15, 15)

        config_group = QGroupBox("⚙️ Cấu hình Model & Server")
        c_layout = QHBoxLayout()
        
        self.cmb_server = QComboBox()
        self.cmb_server.addItems(OLLAMA_HOST_LIST)
        self.cmb_server.setEditable(True)
        
        self.cmb_vision = QComboBox()
        self.cmb_vision.addItems(OLLAMA_MODEL_LIST)
        self.cmb_vision.setCurrentText("qwen3-vl:235b-cloud")
        
        self.cmb_translator = QComboBox()
        self.cmb_translator.addItems(OLLAMA_MODEL_LIST)
        self.cmb_translator.setCurrentText("kimi-k2.6:cloud")
        
        self.cmb_reasoning = QComboBox()
        self.cmb_reasoning.addItems(OLLAMA_MODEL_LIST)
        self.cmb_reasoning.setCurrentText("minimax-m2.7:cloud") 
        
        self.cmb_classifier = QComboBox()
        self.cmb_classifier.addItems(OLLAMA_MODEL_LIST)
        self.cmb_classifier.setCurrentText("kimi-k2.6:cloud") 
        
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 50)
        self.spin_workers.setValue(MAX_CONCURRENT_TASKS)
        
        c_layout.addWidget(QLabel("Server:")); c_layout.addWidget(self.cmb_server)
        c_layout.addWidget(QLabel("Vision:")); c_layout.addWidget(self.cmb_vision)
        c_layout.addWidget(QLabel("Translator:")); c_layout.addWidget(self.cmb_translator)
        c_layout.addWidget(QLabel("Reasoning:")); c_layout.addWidget(self.cmb_reasoning)
        c_layout.addWidget(QLabel("Classifier:")); c_layout.addWidget(self.cmb_classifier)
        c_layout.addWidget(QLabel(" | Số luồng:")); c_layout.addWidget(self.spin_workers)
        
        config_group.setLayout(c_layout)
        layout.addWidget(config_group)

        a_layout = QHBoxLayout()
        btn_load = QPushButton("📁 Chọn thư mục ảnh")
        btn_load.clicked.connect(self.load_folder)
        
        btn_load_db = QPushButton("🗄️ Load from SQLite")
        btn_load_db.setObjectName("btnLoadDB")
        btn_load_db.clicked.connect(self.load_sqlite)
        
        btn_answer_all = QPushButton("⚡ Chạy tất cả (Kết quả lọc)")
        btn_answer_all.clicked.connect(self.answer_all)

        btn_classify_all = QPushButton("🏷️ Phân loại tất cả")
        btn_classify_all.setObjectName("btnClassifyAll")
        btn_classify_all.clicked.connect(self.classify_all)
        
        btn_export = QPushButton("💾 Export to SQLite")
        btn_export.setObjectName("btnExport")
        btn_export.clicked.connect(self.export_sqlite)
        
        self.lbl_status = QLabel("Ready.")
        self.lbl_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        a_layout.addWidget(btn_load)
        a_layout.addWidget(btn_load_db)
        a_layout.addWidget(btn_answer_all)
        a_layout.addWidget(btn_classify_all)
        a_layout.addWidget(btn_export)
        a_layout.addWidget(self.lbl_status)
        a_layout.addStretch()
        layout.addLayout(a_layout)

        search_layout = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Tìm kiếm theo File ảnh hoặc Nội dung câu hỏi (Search kiểu LIKE %text%)...")
        self.txt_search.textChanged.connect(self.on_search)
        search_layout.addWidget(self.txt_search)
        layout.addLayout(search_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)

        t_container = QWidget()
        t_layout = QVBoxLayout(t_container)
        t_layout.setContentsMargins(0, 0, 0, 0)
        
        self.table = QTableWidget(0, 9)
        self.table.setShowGrid(True)
        self.table.setHorizontalHeaderLabels([
            "File ảnh", "Nội dung", "Giải thích câu hỏi", "Các lựa chọn", "Đáp án", "Giải thích đáp án", "Phân loại (Category)", "Status", "Action"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)            
        self.table.setColumnWidth(8, 120)
        
        self.table.verticalHeader().setDefaultSectionSize(120)
        t_layout.addWidget(self.table)
        
        p_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Trang trước")
        self.btn_prev.clicked.connect(self.prev_page)
        self.lbl_page = QLabel(f"Trang 1 / 1 ({self.items_per_page} phần tử/trang)")
        self.btn_next = QPushButton("Trang sau")
        self.btn_next.clicked.connect(self.next_page)
        
        p_layout.addStretch(); p_layout.addWidget(self.btn_prev); p_layout.addWidget(self.lbl_page); p_layout.addWidget(self.btn_next); p_layout.addStretch()
        t_layout.addLayout(p_layout)
        splitter.addWidget(t_container)

        l_group = QGroupBox("🖥️ System Logs")
        l_layout = QVBoxLayout()
        self.txt_log = QTextEdit()
        self.txt_log.setObjectName("LogWindow")
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        l_layout.addWidget(self.txt_log)
        l_group.setLayout(l_layout)
        splitter.addWidget(l_group)
        splitter.setSizes([700, 200])

    def load_sqlite(self):
        last_dir = self.settings.value("last_folder", "")
        db_path, _ = QFileDialog.getOpenFileName(self, "Chọn file SQLite", last_dir, "SQLite Database (*.db *.sqlite);;All Files (*)")
        if not db_path: return
        
        try:
            self.append_log(f"📂 Đang tải dữ liệu từ CSDL: {db_path}...")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions'")
            if not cursor.fetchone():
                QMessageBox.warning(self, "Lỗi định dạng", "File SQLite này không chứa bảng 'questions' hợp lệ của hệ thống!")
                conn.close()
                return
            
            cursor.execute("PRAGMA table_info(questions)")
            existing_columns = [col[1] for col in cursor.fetchall()]
            if "category" not in existing_columns:
                self.append_log("⚠️ Phát hiện DB cũ, đang tự động thêm cột 'category'...")
                cursor.execute("ALTER TABLE questions ADD COLUMN category TEXT DEFAULT 'Chưa phân loại'")
                conn.commit()

            cursor.execute('SELECT source_name, extracted_text, vn_explanation, choices, final_answer, answer, status, category FROM questions')
            rows = cursor.fetchall()
            
            self.all_data = []
            for row in rows:
                self.all_data.append({
                    "source_name": row[0] or "", "image_paths": [], "extracted_text": row[1] or "",
                    "vn_explanation": row[2] or "", "choices": row[3] or "", "final_answer": row[4] or "",
                    "answer": row[5] or "", "status": row[6] or "pending", 
                    "category": row[7] or "Chưa phân loại"  
                })
            conn.close()
            
            # --- ÁP DỤNG SO SÁNH: Sắp xếp theo thứ tự Topic -> Question ---
            self.all_data.sort(key=custom_exam_sort_key)
            self.filtered_data = self.all_data.copy()
            self.current_page = 0; self.txt_search.clear(); self.update_table()
            self.lbl_status.setText(f"🗄️ CSDL: {os.path.basename(db_path)} | Đã tải {len(self.all_data)} mục.")
            self.append_log(f"✅ Tải thành công {len(self.all_data)} dòng từ SQLite.")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi Load DB", f"Có lỗi xảy ra khi đọc SQLite:\n{str(e)}")
            self.append_log(f"❌ Lỗi Load SQLite: {str(e)}")

    def export_sqlite(self):
        if not self.all_data:
            QMessageBox.warning(self, "Cảnh báo", "Không có dữ liệu nào để Export!")
            return
            
        last_dir = self.settings.value("last_folder", "")
        db_path, _ = QFileDialog.getSaveFileName(self, "Lưu file SQLite", os.path.join(last_dir, "azure_questions.sqlite"), "SQLite Database (*.db *.sqlite);;All Files (*)")
        if not db_path: return 
            
        try:
            self.append_log("💾 Bắt đầu quá trình lưu cơ sở dữ liệu SQLite...")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
                    source_name TEXT UNIQUE, extracted_text TEXT, vn_explanation TEXT,
                    choices TEXT, final_answer TEXT, answer TEXT, status TEXT, 
                    category TEXT DEFAULT 'Chưa phân loại', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            
            cursor.execute("PRAGMA table_info(questions)")
            cols = [c[1] for c in cursor.fetchall()]
            if "category" not in cols:
                cursor.execute("ALTER TABLE questions ADD COLUMN category TEXT DEFAULT 'Chưa phân loại'")

            success_count = 0
            for data in self.all_data:
                if data["status"] != "pending":
                    cursor.execute('''INSERT OR REPLACE INTO questions 
                        (source_name, extracted_text, vn_explanation, choices, final_answer, answer, status, category)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (
                        data.get("source_name", ""), data.get("extracted_text", ""), data.get("vn_explanation", ""),
                        data.get("choices", ""), data.get("final_answer", ""), data.get("answer", ""), 
                        data.get("status", ""), data.get("category", "Chưa phân loại")
                    ))
                    success_count += 1
            conn.commit(); conn.close()
            QMessageBox.information(self, "Thành công", f"Đã xuất thành công {success_count} dòng dữ liệu vào SQLite!")
            self.append_log(f"✅ Đã xuất CSDL thành công tại: {db_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi Export", f"Có lỗi xảy ra khi lưu SQLite:\n{str(e)}")
            self.append_log(f"❌ Lỗi Export SQLite: {str(e)}")

    def create_textarea(self, text):
        w = QTextEdit()
        w.setPlainText(text) # Giữ nguyên mọi dấu xuống dòng
        w.setStyleSheet("background: transparent; border: none;")
        return w

    def append_log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"<span style='color: #6B7280;'>[{timestamp}]</span> {message}")
        sb = self.txt_log.verticalScrollBar(); sb.setValue(sb.maximum())

    def get_host_url(self):
        host = self.cmb_server.currentText().strip()
        return host if host.startswith("http") else f"http://{host}:{DEFAULT_PORT}"

    def load_folder(self):
        last_dir = self.settings.value("last_folder", "")
        f = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh", last_dir)
        if not f: return
        
        self.settings.setValue("last_folder", f); self.all_data = []
        valid_exts = ('.png', '.jpg', '.jpeg')
        self.append_log(f"Đang quét thư mục: {f}")
        
        # --- ÁP DỤNG SO SÁNH: Sắp xếp danh mục con theo Topic -> Question ---
        root_items = sorted(os.listdir(f), key=custom_exam_sort_key)
        for n in root_items:
            p = os.path.join(f, n)
            if os.path.isfile(p) and n.lower().endswith(valid_exts):
                self.all_data.append({"source_name": n, "image_paths": [p], "extracted_text": "", "vn_explanation": "", "choices": "", "final_answer": "", "answer": "", "status": "pending", "category": "Chưa phân loại"})
            elif os.path.isdir(p):
                img_names = [i for i in os.listdir(p) if i.lower().endswith(valid_exts)]
                # Sắp xếp các file bên trong thư mục con một cách tự nhiên
                img_names_sorted = sorted(img_names, key=natural_sort_key)
                imgs = [os.path.join(p, img_name) for img_name in img_names_sorted]
                if imgs: 
                    self.all_data.append({"source_name": f"📁 {n}", "image_paths": imgs, "extracted_text": "", "vn_explanation": "", "choices": "", "final_answer": "", "answer": "", "status": "pending", "category": "Chưa phân loại"})
                    
        self.all_data.sort(key=custom_exam_sort_key)
        self.filtered_data = self.all_data.copy()
        self.current_page = 0; self.txt_search.clear(); self.update_table()
        self.lbl_status.setText(f"📁 Thư mục: {f} | Đã tải {len(self.all_data)} mục.")
        self.append_log(f"Đã tìm thấy {len(self.all_data)} câu hỏi (Đã sắp xếp Topic -> Question).")

    def on_search(self, text):
        query = text.lower().strip()
        if not query:
            self.filtered_data = self.all_data.copy()
        else:
            self.filtered_data = [
                d for d in self.all_data 
                if query in d.get("extracted_text", "").lower() or query in d.get("source_name", "").lower()
            ]
        self.current_page = 0; self.update_table()

    def update_table(self):
        self.table.setRowCount(0)
        start = self.current_page * self.items_per_page
        page = self.filtered_data[start : start + self.items_per_page]
        
        for i, d in enumerate(page):
            row = self.table.rowCount(); self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(d["source_name"]))
            for col in range(1, 9): self.table.setItem(row, col, QTableWidgetItem()) 
                
            self.table.setCellWidget(row, 1, self.create_textarea(d.get("extracted_text", "")))
            self.table.setCellWidget(row, 2, self.create_textarea(d.get("vn_explanation", "")))
            self.table.setCellWidget(row, 3, self.create_textarea(d.get("choices", "")))
            self.table.setItem(row, 4, QTableWidgetItem(d.get("final_answer", "")))
            self.table.setCellWidget(row, 5, self.create_textarea(d.get("answer", "")))
            
            cat_widget = QWidget()
            cat_layout = QVBoxLayout(cat_widget)
            cat_layout.setContentsMargins(5, 5, 5, 5)
            
            cmb_cat = QComboBox()
            cmb_cat.addItems(QUESTION_CATEGORIES)
            cmb_cat.setCurrentText(d.get("category", "Chưa phân loại"))
            cmb_cat.setStyleSheet("QComboBox { border: 1px solid #D1D5DB; background: white; padding: 2px; }")
            
            true_idx = self.all_data.index(d)
            cmb_cat.currentTextChanged.connect(lambda text, idx=true_idx: self.on_manual_category_change(idx, text))
            
            btn_classify = QPushButton("🏷️ Phân loại")
            btn_classify.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_classify.clicked.connect(lambda checked, idx=true_idx: self.submit_classify_task(idx))
            
            cat_layout.addWidget(cmb_cat)
            cat_layout.addWidget(btn_classify)
            self.table.setCellWidget(row, 6, cat_widget)
            
            self.table.setItem(row, 7, QTableWidgetItem(d.get("status", "")))
            
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("margin: 30px 10px;")
            btn.clicked.connect(lambda checked, idx=true_idx: self.submit_task(idx))
            
            status = d.get("status", "")
            if status in ["queued", "extracting", "extracting_choices", "explaining", "answering"]: btn.setEnabled(False); btn.setText("Đang chạy...")
            elif status == "done": btn.setEnabled(True); btn.setText("Chạy lại")
            elif "error" in status: btn.setEnabled(True); btn.setText("Thử lại")
            else: btn.setEnabled(True); btn.setText("Chạy Agent")
                
            self.table.setCellWidget(row, 8, btn)
            self.apply_color(row, status)
        
        total_items = len(self.filtered_data)
        total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        self.lbl_page.setText(f"Trang {self.current_page + 1} / {total_pages} ({self.items_per_page} phần tử/trang - Tổng: {total_items})")
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled((start + self.items_per_page) < total_items)

    def on_manual_category_change(self, global_index, new_text):
        self.all_data[global_index]["category"] = new_text

    def apply_color(self, row_index, status):
        if status == "done": color = QColor("#D1FAE5")
        elif "error" in status: color = QColor("#FEE2E2")
        elif status in ["extracting", "extracting_choices", "explaining", "answering", "queued"]: color = QColor("#FEF3C7")
        else: color = QColor("#FFFFFF")
        for col in range(9): 
            if self.table.item(row_index, col): self.table.item(row_index, col).setBackground(color)

    def prev_page(self): self.current_page -= 1; self.update_table()
    def next_page(self): self.current_page += 1; self.update_table()

    def answer_all(self):
        for d in self.filtered_data:
            if d["status"] not in ["done", "queued", "extracting", "extracting_choices", "explaining", "answering"]:
                true_idx = self.all_data.index(d)
                self.submit_task(true_idx)

    def classify_all(self):
        tasks_submitted = 0
        for d in self.filtered_data:
            if d.get("category", "Chưa phân loại") == "Chưa phân loại":
                true_idx = self.all_data.index(d)
                self.submit_classify_task(true_idx)
                tasks_submitted += 1
                
        if tasks_submitted == 0:
            QMessageBox.information(self, "Thông báo", "Tất cả các câu hỏi trong danh sách lọc hiện tại đều đã được phân loại!")

    def submit_classify_task(self, global_index):
        current_max_threads = self.spin_workers.value()
        self.threadpool.setMaxThreadCount(current_max_threads)
        
        state = self.all_data[global_index]
        if state in self.filtered_data:
            filtered_index = self.filtered_data.index(state)
            start = self.current_page * self.items_per_page
            if start <= filtered_index < start + self.items_per_page:
                local_row = filtered_index - start
                w_ext = self.table.cellWidget(local_row, 1)
                if isinstance(w_ext, QTextEdit): 
                    self.all_data[global_index]["extracted_text"] = w_ext.toPlainText()

        host_url = self.get_host_url()
        classifier_model = self.cmb_classifier.currentText()

        task = ClassificationTask(global_index, self.all_data[global_index], host_url, classifier_model)
        task.signals.update.connect(self.on_classify_update)
        task.signals.finished.connect(self.on_task_finished)
        task.signals.log.connect(self.append_log)

        self.active_tasks += 1
        self.lbl_status.setText(f"Đang phân loại... ({self.active_tasks} tiến trình ngầm)")
        self.threadpool.start(task)

    def on_classify_update(self, global_index, new_category):
        self.all_data[global_index]["category"] = new_category
        self.sync_row_ui(global_index)

    def submit_task(self, global_index):
        if self.all_data[global_index]["status"] in ["queued", "extracting", "extracting_choices", "explaining", "answering"]: return

        current_max_threads = self.spin_workers.value()
        self.threadpool.setMaxThreadCount(current_max_threads)

        state = self.all_data[global_index]
        if state in self.filtered_data:
            filtered_index = self.filtered_data.index(state)
            start = self.current_page * self.items_per_page
            if start <= filtered_index < start + self.items_per_page:
                local_row = filtered_index - start
                w_ext = self.table.cellWidget(local_row, 1); w_exp = self.table.cellWidget(local_row, 2); w_cho = self.table.cellWidget(local_row, 3)
                
                if isinstance(w_ext, QTextEdit): self.all_data[global_index]["extracted_text"] = w_ext.toPlainText()
                if isinstance(w_exp, QTextEdit): self.all_data[global_index]["vn_explanation"] = w_exp.toPlainText()
                if isinstance(w_cho, QTextEdit): self.all_data[global_index]["choices"] = w_cho.toPlainText()

        self.all_data[global_index].update({
            "status": "queued", "host_url": self.get_host_url(), "vision_model": self.cmb_vision.currentText(),
            "translator_model": self.cmb_translator.currentText(), "reasoning_model": self.cmb_reasoning.currentText()
        })
        self.sync_row_ui(global_index)
        
        task = AgentTask(global_index, self.all_data[global_index])
        task.signals.update.connect(self.on_task_update)
        task.signals.finished.connect(self.on_task_finished)
        task.signals.log.connect(self.append_log)
        
        self.active_tasks += 1
        self.lbl_status.setText(f"Đang chạy... ({self.active_tasks} tiến trình ngầm)")
        self.threadpool.start(task)

    def on_task_update(self, global_index, updated_state):
        self.all_data[global_index].update(updated_state)
        self.sync_row_ui(global_index)

    def on_task_finished(self, global_index):
        self.active_tasks -= 1
        if self.active_tasks == 0:
            self.lbl_status.setText(f"Hoàn tất toàn bộ tiến trình.")
        else:
            self.lbl_status.setText(f"Đang chạy... ({self.active_tasks} tiến trình ngầm)")

    def sync_row_ui(self, global_index):
        state = self.all_data[global_index]
        if state not in self.filtered_data: return
        
        filtered_index = self.filtered_data.index(state)
        start = self.current_page * self.items_per_page
        
        if start <= filtered_index < start + self.items_per_page:
            local_row = filtered_index - start
            
            def update_text_widget(col, text):
                widget = self.table.cellWidget(local_row, col)
                if isinstance(widget, QTextEdit):
                    sb = widget.verticalScrollBar(); at_bottom = sb.value() == sb.maximum()
                    widget.setPlainText(text)
                    if at_bottom: sb.setValue(sb.maximum())

            update_text_widget(1, state.get("extracted_text", "")); update_text_widget(2, state.get("vn_explanation", "")); update_text_widget(3, state.get("choices", ""))
            self.table.setItem(local_row, 4, QTableWidgetItem(state.get("final_answer", "")))
            update_text_widget(5, state.get("answer", ""))
            
            cat_w = self.table.cellWidget(local_row, 6)
            if cat_w:
                cmb = cat_w.findChild(QComboBox)
                if cmb:
                    cmb.blockSignals(True)
                    cmb.setCurrentText(state.get("category", "Chưa phân loại"))
                    cmb.blockSignals(False)

            self.table.setItem(local_row, 7, QTableWidgetItem(state.get("status", "")))
            
            btn = self.table.cellWidget(local_row, 8)
            if isinstance(btn, QPushButton):
                status = state.get("status", "")
                if status in ["queued", "extracting", "extracting_choices", "explaining", "answering"]: btn.setEnabled(False); btn.setText("Đang chạy...")
                elif status == "done": btn.setEnabled(True); btn.setText("Chạy lại")
                elif "error" in status: btn.setEnabled(True); btn.setText("Thử lại")
                else: btn.setEnabled(True); btn.setText("Chạy Agent")
            
            self.apply_color(local_row, state.get("status", ""))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())