# database.py
import sqlite3
import re
from utils import clean_excessive_whitespace

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
            
        conn.commit(); conn.close()

    def get_all_records(self, search_query="", missing_answer_only=False):
        conn = self.get_connection()
        cursor = conn.cursor()
        query = f"%{search_query}%"
        
        base_sql = """
            SELECT source_name, extracted_text, vn_explanation, choices, 
                   final_answer, answer, status, question_type, is_reliable, category
            FROM questions
            WHERE (source_name LIKE ? 
               OR extracted_text LIKE ?
               OR choices LIKE ?
               OR answer LIKE ?
               OR final_answer LIKE ?
               OR question_type LIKE ?
               OR category LIKE ?)
        """
        
        if missing_answer_only:
            base_sql += " AND (final_answer IS NULL OR trim(final_answer) = '')"
            
        cursor.execute(base_sql, (query, query, query, query, query, query, query))
        
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
                final_answer = ?, answer = ?, status = ?, question_type = ?, is_reliable = ?, category = ?
            WHERE source_name = ?
        """, (
            data['source_name'], data['extracted_text'], data['choices'],
            data['final_answer'], data['answer'], data['status'], data['question_type'], 
            data['is_reliable'], data['category'], original_source_name
        ))
        conn.commit(); conn.close()

    def normalize_lab_types(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE questions 
            SET question_type = 'Lab' 
            WHERE source_name LIKE '%lab%'
        """)
        updated_count = cursor.rowcount
        conn.commit(); conn.close()
        return updated_count

    def auto_clean_and_update_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        total_updated = 0
        
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
                new_ans = current_ans.replace("🗳️", "")
                new_ans = clean_excessive_whitespace(new_ans)
                cursor.execute("UPDATE questions SET answer = ? WHERE source_name = ?", (new_ans, source_name))
                total_updated += 1
                
        conn.commit()
        conn.close()
        return total_updated

    def delete_record(self, source_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM questions WHERE source_name = ?", (source_name,))
        conn.commit(); conn.close()