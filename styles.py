# styles.py

TAILWIND_QSS = """
    QWidget { font-family: "Segoe UI", sans-serif; background-color: #F9FAFB; color: #1F2937; }
    QPushButton { background-color: #3B82F6; color: white; border-radius: 6px; padding: 6px 12px; font-weight: bold; border: none; }
    QPushButton:hover { background-color: #2563EB; }
    QPushButton:disabled { background-color: #9CA3AF; color: #E5E7EB; }
    
    /* Nút màu xanh lá cho Export (Từ project cũ) */
    QPushButton#btnExport { background-color: #10B981; }
    QPushButton#btnExport:hover { background-color: #059669; }
    
    /* Bổ sung các nút hành động chuyên dụng cho DB Manager */
    QPushButton#btnDelete { background-color: #EF4444; } 
    QPushButton#btnDelete:hover { background-color: #DC2626; }
    QPushButton#btnEdit { background-color: #F59E0B; } 
    QPushButton#btnEdit:hover { background-color: #D97706; }
    QPushButton#btnSuccess { background-color: #10B981; } 
    QPushButton#btnSuccess:hover { background-color: #059669; }
    
    QPushButton#btnLabNormalize { background-color: #8B5CF6; }
    QPushButton#btnLabNormalize:hover { background-color: #7C3AED; }
    
    QPushButton#btnAI { background-color: #EC4899; }
    QPushButton#btnAI:hover { background-color: #DB2777; }
    
    QTableWidget { 
        background-color: white; 
        border: 1px solid #D1D5DB; 
        gridline-color: #D1D5DB; 
    }
    QHeaderView::section { 
        background-color: #F3F4F6; 
        padding: 8px; 
        font-weight: bold; 
        border: 1px solid #D1D5DB; 
    }
    QGroupBox { border: 1px solid #D1D5DB; border-radius: 8px; margin-top: 10px; font-weight: bold; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; color: #4B5563; }
    
    QLineEdit, QTextEdit, QComboBox { border: 1px solid #D1D5DB; border-radius: 6px; padding: 8px; background: white; }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #3B82F6; outline: none; background-color: #EFF6FF; }
    QLineEdit:read-only, QTextEdit:read-only { background-color: #F3F4F6; color: #6B7280; border: 1px solid #D1D5DB; }
    
    QCheckBox { font-weight: bold; color: #DC2626; }
    QDialog { background-color: #FFFFFF; }
    QScrollArea { border: 1px solid #D1D5DB; border-radius: 6px; background-color: white; }
    
    /* Thành phần LogWindow giữ lại cho Crawler/Quiz App */
    QTextEdit#LogWindow { background-color: #111827; color: #10B981; font-family: Consolas, monospace; padding: 10px; border-radius: 8px; }
"""