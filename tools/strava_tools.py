import numpy as np
import logging

logger = logging.getLogger(__name__)

def calculate_trimp(duration_minutes: float, avg_hr: float, max_hr: int = 185, rest_hr: int = 55) -> dict:
    """
    Calculate Training Impulse (TRIMP) using Bannister's method.
    Returns a dictionary containing TRIMP score and evaluated intensity.
    """
    try:
        # Calculate Heart Rate Reserve (HRR)
        hrr = (avg_hr - rest_hr) / (max_hr - rest_hr)
        hrr = max(0, hrr) # Ensure HRR is not negative
        
        # Bannister's formula for males
        weight = 0.64 * np.exp(1.92 * hrr)
        trimp = duration_minutes * hrr * weight
        trimp_rounded = round(trimp, 2)
        
        # Evaluate intensity zone based on TRIMP score
        intensity = "Easy/Recovery"
        if trimp_rounded > 120:
            intensity = "High (Overreaching if scheduled for recovery)"
        elif trimp_rounded > 70:
            intensity = "Medium (Tempo/Threshold)"
            
        logger.info(f"[Strava Tool] TRIMP calculated: {trimp_rounded} - {intensity}")
        
        return {
            "trimp": trimp_rounded,
            "intensity_level": intensity,
            "avg_hr": avg_hr,
            "duration": duration_minutes
        }
    except Exception as e:
        logger.error(f"[Strava Tool] Calculation error: {e}")
        return {"error": str(e)}
def calculate_efficiency_factor(avg_speed_mpm, avg_hr):
    """
    Tính Efficiency Factor (EF) = Speed (meters/min) / HR
    EF tăng = Aerobic Fitness tăng.
    """
    if avg_hr == 0: return 0
    return round(avg_speed_mpm / avg_hr, 2)

def calculate_grade_adjusted_pace(velocity_ms, grade_pct):
    """
    Công thức đơn giản hóa của Minetti để tính GAP.
    Cost of running phụ thuộc vào độ dốc.
    """
    # Đây là logic phức tạp, AI Coach có thể ước lượng:
    # Mỗi 1% dốc tương đương giảm pace khoảng 2-3 giây/km (quy tắc ngón tay cái)
    cost = 1 + (grade_pct * 0.045) # Ước lượng
    gap_velocity = velocity_ms * cost
    return gap_velocity

def analyze_decoupling(df):
    """
    Chia bài chạy làm 2 nửa, so sánh tỷ lệ EF (Efficiency Factor).
    Nếu nửa sau kém hơn nửa đầu > 5% => Decoupling (Chưa đủ bền).
    """
    half_point = len(df) // 2
    first_half = df.iloc[:half_point]
    second_half = df.iloc[half_point:]
    
    ef1 = calculate_efficiency_factor(first_half['Velocity_m_s'].mean() * 60, first_half['HR_bpm'].mean())
    ef2 = calculate_efficiency_factor(second_half['Velocity_m_s'].mean() * 60, second_half['HR_bpm'].mean())
    
    decoupling = 0
    if ef1 > 0:
        decoupling = (ef1 - ef2) / ef1 * 100
        
    return round(decoupling, 2)