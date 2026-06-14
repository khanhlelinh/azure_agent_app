# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# --- SYSTEM CONFIGURATIONS ---
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 5))

# --- DYNAMIC CONFIGURATIONS DEFAULTS ---
OLLAMA_HOST_LIST = [
    "127.0.0.1",
    "legion-laptop",
    "DESKTOP-0A1VDGF"
]
DEFAULT_PORT = "11434"

# Đẩy Qwen3-VL lên đầu danh sách để ComboBox tự động focus vào model Vision SOTA
OLLAMA_MODEL_LIST = [
    "qwen3-vl:235b-cloud",
    "kimi-k2.6:cloud",
    "qwen3.5:397b-cloud",
    "nemotron-3-super:cloud",
    "glm-5:cloud",
    "deepseek-v3.2:cloud",
    "devstral-2:123b-cloud",
    "deepseek-v4-pro:cloud",
    "minimax-m2.7:cloud"    
]

# --- DOMAIN CONSTANTS ---
QUESTION_CATEGORIES = [
    "Chưa phân loại",
    "Plan and implement data platform resources",
    "Implement a secure environment",
    "Monitor, configure, and optimize database resources",
    "Configure and manage automation of tasks",
    "Plan and configure a high availability and disaster recovery (HA/DR) environment"
]