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