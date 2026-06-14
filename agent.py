import base64
import time
from typing import TypedDict, List
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from config import MAX_RETRIES

class QuestionState(TypedDict):
    source_name: str
    image_paths: List[str]
    extracted_text: str
    choices: str
    final_answer: str
    answer: str
    status: str
    
    host_url: str
    vision_model: str
    translator_model: str
    reasoning_model: str

def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def retry_on_fail(func):
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                time.sleep(2 ** attempt)
        return {"status": f"error: {str(last_exception)}"}
    return wrapper

@retry_on_fail
def extract_text_node(state: QuestionState):
    if state.get("extracted_text", "").strip():
        return {"status": "extracting"}

    llm = ChatOllama(model=state["vision_model"], base_url=state["host_url"], temperature=0)
    content = [{"type": "text", "text": "Extract all text from the provided image(s) exactly as written. Do not summarize or alter the text. No markdown formatting."}]
    for img_path in state["image_paths"]:
        img_base64 = encode_image(img_path)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}})
    
    response = llm.invoke([HumanMessage(content=content)])
    return {"extracted_text": response.content.strip(), "status": "extracting"}

@retry_on_fail
def get_choices_node(state: QuestionState):
    if "error" in state.get("status", ""): return state
    llm = ChatOllama(model=state["translator_model"], base_url=state["host_url"], temperature=0)
    
    prompt = f"""Bạn là một công cụ trích xuất văn bản (Data Extractor) tự động. 
Hãy trích xuất Y NGUYÊN các lựa chọn (choices/options - ví dụ: A, B, C, D...) từ văn bản dưới đây.

YÊU CẦU KỶ LUẬT THÉP:
1. Chỉ COPY Y HỆT từ văn bản gốc sang. 
2. TUYỆT ĐỐI KHÔNG tự động sửa lỗi chính tả, KHÔNG thay đổi thứ tự, KHÔNG tự chế ra đáp án dựa trên kiến thức của bạn.
3. Không bao gồm phần thân đề bài.
4. Nếu văn bản không có các lựa chọn rõ ràng, hãy trả về đúng 1 chữ: "None".

Văn bản gốc cần trích xuất:
{state['extracted_text']}"""
    
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"choices": response.content.strip(), "status": "extracting_choices"}

@retry_on_fail
def answer_node(state: QuestionState):
    if "error" in state.get("status", ""): return state
    llm = ChatOllama(model=state["reasoning_model"], base_url=state["host_url"], temperature=0.1)
    
    prompt = f"""Bạn là một chuyên gia Microsoft Azure và SQL Server. Hãy đọc câu hỏi và danh sách các lựa chọn được cung cấp dưới đây để tìm ra đáp án ĐÚNG NHẤT.

Câu hỏi: 
{state['extracted_text']}

Các lựa chọn BẮT BUỘC phải tuân theo: 
{state['choices']}

Nhiệm vụ:
1. Đưa ra CÁC CHỮ CÁI của đáp án đúng (Ví dụ: A hoặc A, C, D). Chỉ ghi chữ cái, cách nhau bằng dấu phẩy. Chú ý chỉ được chọn dựa trên "Các lựa chọn BẮT BUỘC phải tuân theo" ở trên.
2. Giải thích lý do chọn đáp án này bằng tiếng Việt. Giữ nguyên thuật ngữ kỹ thuật tiếng Anh (song ngữ). Tuyệt đối không dùng dấu sao (*) hoặc markdown.

Kết quả trả về phải tuân thủ đúng định dạng parser sau:
ANSWER_START
[Chỉ ghi chữ cái đáp án]
ANSWER_END
EXPLAIN_START
[Phần giải thích chi tiết]
EXPLAIN_END
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    res_text = response.content.strip().replace("*", "")
    
    try:
        final_ans = res_text.split("ANSWER_START")[1].split("ANSWER_END")[0].strip()
        explain_ans = res_text.split("EXPLAIN_START")[1].split("EXPLAIN_END")[0].strip()
    except:
        final_ans = "N/A"
        explain_ans = res_text

    return {"final_answer": final_ans, "answer": explain_ans, "status": "done"}

# Gắn luồng Workflow (Bỏ node explain)
workflow = StateGraph(QuestionState)
workflow.add_node("extract", extract_text_node)
workflow.add_node("get_choices", get_choices_node)
workflow.add_node("answer", answer_node)

workflow.set_entry_point("extract")
workflow.add_edge("extract", "get_choices")
workflow.add_edge("get_choices", "answer") # Nối thẳng từ get_choices sang answer
workflow.add_edge("answer", END)

agent_app = workflow.compile()