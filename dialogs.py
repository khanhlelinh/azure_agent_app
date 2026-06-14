# dialogs.py
import os
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QWidget, QScrollArea, 
                             QFormLayout, QLineEdit, QTextEdit, QComboBox, QCheckBox, QPushButton, QLabel)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

# --- IMPORT CHÉO TỪ CÁC TẦNG KIẾN TRÚC ---
from styles import TAILWIND_QSS
from config import QUESTION_CATEGORIES
from utils import format_choices_newlines, clean_excessive_whitespace, natural_sort_key

class EditDialog(QDialog):
    def __init__(self, parent=None, record_data=None, base_image_folder=""):
        super().__init__(parent)
        self.record_data = record_data or {}
        
        self.setWindowTitle("Chỉnh sửa Dữ liệu nâng cao")
        self.setStyleSheet(TAILWIND_QSS)
        
        self.txt_source = QLineEdit(self.record_data.get('source_name', ''))
        
        self.txt_extract = QTextEdit()
        self.txt_extract.setPlainText(self.record_data.get('extracted_text', ''))
        
        formatted_choices = format_choices_newlines(self.record_data.get('choices', ''))
        self.txt_choices = QTextEdit()
        self.txt_choices.setPlainText(formatted_choices)
        
        self.txt_final_ans = QTextEdit()
        self.txt_final_ans.setPlainText(self.record_data.get('final_answer', ''))
        self.txt_final_ans.setMaximumHeight(80) 
        
        clean_ans_text = clean_excessive_whitespace(self.record_data.get('answer', ''))
        self.txt_answer = QTextEdit()
        self.txt_answer.setPlainText(clean_ans_text)
        
        self.txt_status = QLineEdit(self.record_data.get('status', 'done'))
        
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["Chọn", "Kéo thả", "Lab"])
        self.cmb_type.setCurrentText(self.record_data.get('question_type', 'Chọn'))
        
        self.txt_category = QLineEdit()
        self.txt_category.setText(self.record_data.get('category', 'Chưa phân loại'))
        self.txt_category.setReadOnly(True)
        self.txt_category.setToolTip("Cột Chủ đề được hệ thống tự động trích xuất vĩnh viễn, không hỗ trợ chỉnh sửa tay.")
        
        self.chk_reliable = QCheckBox("Câu hỏi này đã chuẩn (Đáng tin cậy)")
        is_reliable = self.record_data.get('is_reliable', 1)
        self.chk_reliable.setChecked(bool(is_reliable))

        main_layout = QHBoxLayout(self)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 10)
        
        scroll_form = QScrollArea()
        scroll_form.setWidgetResizable(True)
        scroll_form.setStyleSheet("border: none; background: white;")
        
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.addRow("Tên File (Source):", self.txt_source)
        form_layout.addRow("Loại câu hỏi:", self.cmb_type)
        form_layout.addRow("Chủ đề (Category):", self.txt_category)
        form_layout.addRow("Độ tin cậy:", self.chk_reliable)
        form_layout.addRow("Đáp án:", self.txt_final_ans)
        form_layout.addRow("Trạng thái:", self.txt_status)
        form_layout.addRow("Nội dung trích xuất:", self.txt_extract)
        form_layout.addRow("Các lựa chọn:", self.txt_choices)
        form_layout.addRow("Giải thích Đáp án:", self.txt_answer)
        
        scroll_form.setWidget(form_container)
        left_layout.addWidget(scroll_form, stretch=1)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Lưu thay đổi")
        btn_save.setObjectName("btnSuccess")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        left_layout.addLayout(btn_layout)
        
        main_layout.addWidget(left_widget, stretch=1)

        q_images = []
        ans_images = []
        
        if base_image_folder:
            source_name = self.record_data.get('source_name', '')
            valid_exts = ('.png', '.jpg', '.jpeg')
            full_dir = ""
            if source_name.startswith("📁 "):
                folder_name = source_name.replace("📁 ", "").strip()
                full_dir = os.path.join(base_image_folder, folder_name)
            else:
                full_path = os.path.join(base_image_folder, source_name)
                if os.path.isfile(full_path):
                    q_images.append(full_path)
                    
            if full_dir and os.path.isdir(full_dir):
                all_files = [f for f in os.listdir(full_dir) if f.lower().endswith(valid_exts)]
                for fname in sorted(all_files, key=natural_sort_key):
                    fpath = os.path.join(full_dir, fname)
                    if "-answer" in fname.lower():
                        ans_images.append(fpath)
                    else:
                        q_images.append(fpath)

        has_any_image = bool(q_images or ans_images)
        self.resize(1400 if has_any_image else 800, 650) 
        
        if has_any_image:
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(15, 0, 0, 0)
            
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_content = QWidget()
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            
            if q_images:
                scroll_layout.addWidget(QLabel("<h3 style='color: #3B82F6; margin-bottom: 5px;'>🖼️ Ảnh Đề bài (Questions)</h3>"))
                for p in q_images:
                    self.append_image_to_layout(scroll_layout, p)
            
            if ans_images:
                if q_images:
                    spacer = QLabel("<hr style='margin: 15px 0; border: 0; border-top: 1px solid #D1D5DB;'>")
                    scroll_layout.addWidget(spacer)
                    
                scroll_layout.addWidget(QLabel("<h3 style='color: #F59E0B; margin-bottom: 5px;'>💡 Ảnh Đáp án (Answers)</h3>"))
                for p in ans_images:
                    self.append_image_to_layout(scroll_layout, p)
        
            scroll_area.setWidget(scroll_content)
            right_layout.addWidget(scroll_area)
            main_layout.addWidget(right_widget, stretch=1)

    def append_image_to_layout(self, layout, img_path):
        lbl_img = QLabel()
        lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(img_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(650, 3000, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_img.setPixmap(scaled_pixmap)
        else:
            lbl_img.setText(f"❌ Lỗi tải ảnh: {os.path.basename(img_path)}")
        
        lbl_name = QLabel(f"<b>{os.path.basename(img_path)}</b>")
        lbl_name.setStyleSheet("color: #4B5563; font-size: 13px; margin-top: 8px;")
        
        layout.addWidget(lbl_name)
        layout.addWidget(lbl_img)

    def get_data(self):
        return {
            'source_name': self.txt_source.text().strip(),
            'question_type': self.cmb_type.currentText(),
            'category': self.txt_category.text().strip(),
            'is_reliable': 1 if self.chk_reliable.isChecked() else 0,
            'extracted_text': self.txt_extract.toPlainText(),
            'choices': self.txt_choices.toPlainText(),
            'final_answer': self.txt_final_ans.toPlainText().strip(),
            'answer': self.txt_answer.toPlainText(),
            'status': self.txt_status.text().strip()
        }