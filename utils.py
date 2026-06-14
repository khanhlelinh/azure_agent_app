# utils.py
import re

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