import re

# ==========================================
# 1. HÀM CẦN TEST (Trích xuất từ quiz_app.py)
# ==========================================
def normalize_answer(ans):
    """
    Robust Parsing: Xử lý khoảng trắng, chữ hoa/thường, dấu phẩy thừa và thứ tự đáp án.
    """
    if not ans: return ""
    cleaned = ans.upper().replace(" ", "")
    parts = [p for p in cleaned.split(',') if p]
    parts.sort() # Đảm bảo "C,B" khớp với "B,C"
    return ",".join(parts)

def check_answer(user_input, ground_truth):
    """Hàm mô phỏng logic chấm điểm trong submit_quiz()"""
    return normalize_answer(user_input) == normalize_answer(ground_truth)

# ==========================================
# 2. BỘ UNIT TEST (EDGE CASES)
# ==========================================
def run_grading_tests():
    print("🚀 Đang chạy bộ kiểm thử hàm chấm điểm (Output Parsing)...\n")

    test_cases = [
        # --- 1. Test chữ hoa / chữ thường cơ bản ---
        ("a", "A", True, "Chữ thường -> Chữ hoa"),
        ("A", "a", True, "Chữ hoa -> Chữ thường"),
        
        # --- 2. Test khoảng trắng (Whitespace) ---
        (" A ", "A", True, "Khoảng trắng 2 đầu"),
        ("a, b", "A,B", True, "Khoảng trắng sau dấu phẩy"),
        (" a , b ", "A,B", True, "Khoảng trắng lộn xộn"),
        (" a , b ", "A,   B", True, "Khoảng trắng lộn xộn 2"),
        ("a,b", "A, B", True, "Khoảng trắng lộn xộn 2"),
        
        # --- 3. Test sai thứ tự (Unordered Sets) - RẤT QUAN TRỌNG ---
        ("B,A", "A,B", True, "Sai thứ tự 2 phần tử"),
        ("c, a, b", "A,B,C", True, "Sai thứ tự 3 phần tử"),
        ("d, c, a, b", "A,B,C,D", True, "Sai thứ tự 4 phần tử"),
        
        # --- 4. Test dấu phẩy thừa (Trailing/Leading Commas) ---
        ("A,", "A", True, "Dấu phẩy ở cuối"),
        (",A", "A", True, "Dấu phẩy ở đầu"),
        ("A,,B", "A,B", True, "Nhiều dấu phẩy ở giữa"),
        (",,b, a,, ,", "A,B", True, "Dấu phẩy và khoảng trắng hỗn loạn"),
        
        # --- 5. Test đầu vào rỗng (Null/Empty Fallbacks) ---
        ("", "", True, "Cả hai đều rỗng"),
        (None, "", True, "User truyền None"),
        ("   ", "", True, "Chỉ chứa toàn dấu cách"),
        (",,,", "", True, "Chỉ chứa toàn dấu phẩy"),
        
        # --- 6. Test kết quả SAI (False Positives Prevention) ---
        ("A", "B", False, "Khác đáp án hoàn toàn"),
        ("A,B", "A,B,C", False, "Thiếu đáp án"),
        ("A,B,C", "A,B", False, "Thừa đáp án"),
        ("A,C", "A,B", False, "Sai 1 trong nhiều đáp án")
    ]

    passed = 0
    failed = []

    for idx, (user_ans, truth, expected_result, description) in enumerate(test_cases):
        actual_result = check_answer(user_ans, truth)
        if actual_result == expected_result:
            passed += 1
            print(f"✅ Pass Test {idx+1:02d}: {description} | Input: '{user_ans}' vs '{truth}'")
        else:
            failed.append((description, user_ans, truth, expected_result, actual_result))
            print(f"❌ FAIL Test {idx+1:02d}: {description} | Input: '{user_ans}' vs '{truth}'")

    print("-" * 50)
    if not failed:
        print(f"🎉 TUYỆT VỜI! 100% ({passed}/{len(test_cases)}) Test Cases đã PASS.")
        print("Hàm normalize_answer của bạn đủ tiêu chuẩn Production-ready!")
    else:
        print(f"⚠️ CẢNH BÁO: Có {len(failed)} Test Cases bị FAIL. Vui lòng kiểm tra lại parser.")

if __name__ == "__main__":
    run_grading_tests()