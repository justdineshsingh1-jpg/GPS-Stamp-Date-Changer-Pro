"""
GPS Stamp Date Changer Pro - Date Engine
Handles date range parsing, weekday calculation, sequence generation,
and distribution modes (Sequential, Even Distribution, Custom, Preserve).
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def parse_date_string(date_str: str) -> Optional[datetime]:
    """
    Parses various date formats into a datetime object.
    Supports DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, MM/DD/YYYY, etc.
    """
    if not date_str or not str(date_str).strip():
        return None
        
    s = str(date_str).strip()
    # Strip any time component if present
    if " " in s:
        s = s.split(" ")[0]
        
    formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%m/%d/%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
            
    return None


def get_weekday_name(dt: datetime) -> str:
    """Calculates the exact weekday name for a given datetime object (never guessed)."""
    return dt.strftime("%A")


def generate_date_range(start_dt: datetime, end_dt: datetime) -> List[datetime]:
    """
    Generates a list of all calendar dates between start_dt and end_dt (inclusive).
    """
    if start_dt > end_dt:
        raise ValueError(f"Start date ({start_dt.strftime('%d/%m/%Y')}) cannot be after End date ({end_dt.strftime('%d/%m/%Y')})")
        
    dates = []
    curr = start_dt
    while curr <= end_dt:
        dates.append(curr)
        curr += timedelta(days=1)
    return dates


def assign_dates(
    total_images: int,
    start_date_str: str,
    end_date_str: str,
    mode: str = "sequential",
    overflow_policy: str = "cycle",
    custom_dates: Optional[List[Optional[str]]] = None,
    preserve_mask: Optional[List[bool]] = None,
    existing_dates: Optional[List[Optional[str]]] = None
) -> List[Dict[str, Any]]:
    """
    Assigns dates and weekdays to a list of images based on selected mode.
    
    Modes:
      - 'sequential': Assigns start_dt + 0, start_dt + 1...
         Overflow options if images > days:
           * 'cycle': wrap around back to start
           * 'stop': stop assigning when end_dt reached (remaining set to None / unassigned)
           * 'distribute': spread images across the available dates
      - 'even_distribution': Distributes images as evenly as possible across the calendar range.
      - 'custom': Uses date provided per item in custom_dates.
      - 'preserve': If preserve_mask[i] is True, keeps existing_dates[i]; otherwise assigns from range.
      
    Returns a list of dicts:
      [
        {
          "index": int,
          "date_dt": datetime or None,
          "date_str": "DD/MM/YYYY",
          "weekday": "Thursday",
          "mode_applied": str,
          "is_preserved": bool
        },
        ...
      ]
    """
    start_dt = parse_date_string(start_date_str)
    end_dt = parse_date_string(end_date_str)
    
    if start_dt is None or end_dt is None:
        raise ValueError("Invalid Start Date or End Date provided.")
        
    if start_dt > end_dt:
        raise ValueError(f"From Date ({start_dt.strftime('%d/%m/%Y')}) cannot be later than To Date ({end_dt.strftime('%d/%m/%Y')})")
        
    calendar_dates = generate_date_range(start_dt, end_dt)
    num_days = len(calendar_dates)
    
    assignments = []
    
    if mode == "even_distribution" or (mode == "sequential" and overflow_policy == "distribute" and total_images > num_days):
        # Evenly spread images across dates
        for idx in range(total_images):
            if total_images <= 1 or num_days <= 1:
                assigned_dt = calendar_dates[0]
            else:
                day_idx = int((idx / (total_images - 1)) * (num_days - 1))
                assigned_dt = calendar_dates[min(day_idx, num_days - 1)]
                
            assignments.append({
                "index": idx,
                "date_dt": assigned_dt,
                "date_str": assigned_dt.strftime("%d/%m/%Y"),
                "weekday": get_weekday_name(assigned_dt),
                "mode_applied": "even_distribution",
                "is_preserved": False
            })
            
    elif mode == "sequential":
        for idx in range(total_images):
            if idx < num_days:
                assigned_dt = calendar_dates[idx]
            else:
                if overflow_policy == "cycle":
                    assigned_dt = calendar_dates[idx % num_days]
                elif overflow_policy == "stop":
                    assigned_dt = None
                else:
                    assigned_dt = calendar_dates[-1]
                    
            if assigned_dt is not None:
                assignments.append({
                    "index": idx,
                    "date_dt": assigned_dt,
                    "date_str": assigned_dt.strftime("%d/%m/%Y"),
                    "weekday": get_weekday_name(assigned_dt),
                    "mode_applied": "sequential",
                    "is_preserved": False
                })
            else:
                assignments.append({
                    "index": idx,
                    "date_dt": None,
                    "date_str": "",
                    "weekday": "",
                    "mode_applied": "sequential_stopped",
                    "is_preserved": False
                })
                
    elif mode == "custom":
        for idx in range(total_images):
            custom_val = custom_dates[idx] if custom_dates and idx < len(custom_dates) else None
            custom_dt = parse_date_string(custom_val) if custom_val else None
            
            if custom_dt is None:
                # Fallback to sequential start
                custom_dt = calendar_dates[idx % num_days]
                
            assignments.append({
                "index": idx,
                "date_dt": custom_dt,
                "date_str": custom_dt.strftime("%d/%m/%Y"),
                "weekday": get_weekday_name(custom_dt),
                "mode_applied": "custom",
                "is_preserved": False
            })
            
    elif mode == "preserve":
        for idx in range(total_images):
            should_preserve = preserve_mask[idx] if preserve_mask and idx < len(preserve_mask) else False
            existing_val = existing_dates[idx] if existing_dates and idx < len(existing_dates) else None
            existing_dt = parse_date_string(existing_val) if existing_val else None
            
            if should_preserve and existing_dt is not None:
                assigned_dt = existing_dt
                is_pres = True
            else:
                assigned_dt = calendar_dates[idx % num_days]
                is_pres = False
                
            assignments.append({
                "index": idx,
                "date_dt": assigned_dt,
                "date_str": assigned_dt.strftime("%d/%m/%Y"),
                "weekday": get_weekday_name(assigned_dt),
                "mode_applied": "preserve" if is_pres else "assigned",
                "is_preserved": is_pres
            })
    else:
        # Default fallback
        for idx in range(total_images):
            assigned_dt = calendar_dates[idx % num_days]
            assignments.append({
                "index": idx,
                "date_dt": assigned_dt,
                "date_str": assigned_dt.strftime("%d/%m/%Y"),
                "weekday": get_weekday_name(assigned_dt),
                "mode_applied": "sequential",
                "is_preserved": False
            })
            
    return assignments


def get_distribution_statistics(assignments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarizes date assignment distribution:
    - total images
    - total calendar days
    - images per date breakdown
    - min / max / avg per day
    """
    date_counts = {}
    for item in assignments:
        d_str = item.get("date_str")
        if d_str:
            date_counts[d_str] = date_counts.get(d_str, 0) + 1
            
    counts = list(date_counts.values()) if date_counts else [0]
    return {
        "total_images": len(assignments),
        "unique_dates_assigned": len(date_counts),
        "breakdown": [
            {"date": d, "count": c, "weekday": parse_date_string(d).strftime("%A") if parse_date_string(d) else ""}
            for d, c in sorted(date_counts.items(), key=lambda x: parse_date_string(x[0]) or datetime.min)
        ],
        "min_per_date": min(counts) if counts else 0,
        "max_per_date": max(counts) if counts else 0,
        "avg_per_date": round(sum(counts) / max(1, len(counts)), 1)
    }
