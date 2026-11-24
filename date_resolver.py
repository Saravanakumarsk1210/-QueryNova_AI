import re
from datetime import datetime, timedelta
import config

class DateResolver:
    """Deterministic Relative Date Expression & ISO Boundary Resolver."""

    @classmethod
    def resolve_date_phrase(cls, query: str) -> dict:
        q_lower = query.lower().strip()
        now = datetime.now()
        default_year = getattr(config, 'DATASET_DEFAULT_YEAR', 2023)
        date_col = getattr(config, 'TARGET_DATE_COLUMN', 'DATE(start_time)')

        # Check if query is looking up a specific ID or code
        is_id_lookup = bool(re.search(r'\b(id|ticket_id|attendee_id|company_id|room_id|presentation_id|mr_no|surgery_id|\d{6,})\b', q_lower))
        if is_id_lookup:
            return cls._empty_response()

        # Check if an explicit 4-digit year (e.g. 2023, 2024, 2025) is present
        explicit_year_match = re.search(r'\b(20\d{2})\b', q_lower)
        explicit_year = int(explicit_year_match.group(1)) if explicit_year_match else None
        target_year = explicit_year if explicit_year else default_year

        # 1. Day + Month match (e.g. "15th Feb", "15th February", "Feb 15", "15 Feb")
        day_month_match = re.search(
            r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',
            q_lower
        ) or re.search(
            r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?\b',
            q_lower
        )

        months_map = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10, "oct": 10,
            "november": 11, "nov": 11, "december": 12, "dec": 12
        }

        if day_month_match:
            g1, g2 = day_month_match.group(1), day_month_match.group(2)
            if g1.isdigit():
                day_val = int(g1)
                month_str = g2
            else:
                month_str = g1
                day_val = int(g2)

            month_num = months_map.get(month_str.lower())
            if month_num and 1 <= day_val <= 31:
                date_str = f"{target_year}-{month_num:02d}-{day_val:02d}"
                clause_str = f"{date_col} = '{date_str}'"
                return {
                    "start_date": date_str,
                    "end_date": date_str,
                    "clause": clause_str,
                    "sql_clause": clause_str,
                    "matched_phrase": f"{day_val} {month_str.capitalize()} {target_year}",
                    "resolved": True
                }

        # 2. Quarter match (e.g. "Q1 2023", "Q1", "quarter 1")
        q_match = re.search(r'\b(?:q([1-4])|quarter\s*([1-4]))\b', q_lower)
        if q_match:
            q_num = int(q_match.group(1) or q_match.group(2))
            q_ranges = {
                1: (f"{target_year}-01-01", f"{target_year}-03-31"),
                2: (f"{target_year}-04-01", f"{target_year}-06-30"),
                3: (f"{target_year}-07-01", f"{target_year}-09-30"),
                4: (f"{target_year}-10-01", f"{target_year}-12-31"),
            }
            start_d, end_d = q_ranges[q_num]
            clause_str = f"{date_col} BETWEEN '{start_d}' AND '{end_d}'"
            return {
                "start_date": start_d,
                "end_date": end_d,
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": f"Q{q_num} {target_year}",
                "resolved": True
            }

        # 3. Month match (e.g. "February", "for Feb 2023")
        for m_name, m_num in months_map.items():
            if re.search(r'\b' + m_name + r'\b', q_lower):
                m_str = f"{m_num:02d}"
                if m_num in [1, 3, 5, 7, 8, 10, 12]:
                    last_day = 31
                elif m_num in [4, 6, 9, 11]:
                    last_day = 30
                else:
                    # Leap year check for Feb
                    last_day = 29 if (target_year % 4 == 0 and (target_year % 100 != 0 or target_year % 400 == 0)) else 28
                
                start_d = f"{target_year}-{m_str}-01"
                end_d = f"{target_year}-{m_str}-{last_day:02d}"
                clause_str = f"{date_col} BETWEEN '{start_d}' AND '{end_d}'"
                return {
                    "start_date": start_d,
                    "end_date": end_d,
                    "clause": clause_str,
                    "sql_clause": clause_str,
                    "matched_phrase": f"{m_name.capitalize()} {target_year}",
                    "resolved": True
                }

        # 4. Explicit Year match alone (e.g. "in 2023", "for 2023")
        if explicit_year:
            clause_str = f"{date_col} BETWEEN '{explicit_year}-01-01' AND '{explicit_year}-12-31'"
            return {
                "start_date": f"{explicit_year}-01-01",
                "end_date": f"{explicit_year}-12-31",
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": f"Year {explicit_year}",
                "resolved": True
            }

        # 5. Relative phrase matching
        if "today" in q_lower:
            d_str = now.strftime("%Y-%m-%d")
            clause_str = f"{date_col} = '{d_str}'"
            return {
                "start_date": d_str,
                "end_date": d_str,
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": "Today",
                "resolved": True
            }

        if "yesterday" in q_lower:
            d_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            clause_str = f"{date_col} = '{d_str}'"
            return {
                "start_date": d_str,
                "end_date": d_str,
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": "Yesterday",
                "resolved": True
            }

        if "last month" in q_lower or "previous month" in q_lower:
            m_num = now.month - 1 if now.month > 1 else 12
            yr = default_year
            m_str = f"{m_num:02d}"
            last_day = 31 if m_num in [1,3,5,7,8,10,12] else (30 if m_num in [4,6,9,11] else 28)
            start_d = f"{yr}-{m_str}-01"
            end_d = f"{yr}-{m_str}-{last_day:02d}"
            clause_str = f"{date_col} BETWEEN '{start_d}' AND '{end_d}'"
            return {
                "start_date": start_d,
                "end_date": end_d,
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": f"Last Month ({start_d} to {end_d})",
                "resolved": True
            }

        if "last year" in q_lower or "previous year" in q_lower:
            yr = default_year - 1
            clause_str = f"{date_col} BETWEEN '{yr}-01-01' AND '{yr}-12-31'"
            return {
                "start_date": f"{yr}-01-01",
                "end_date": f"{yr}-12-31",
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": f"Year {yr}",
                "resolved": True
            }

        if "last 7 days" in q_lower or "last week" in q_lower or "past week" in q_lower:
            start_d = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            end_d = now.strftime("%Y-%m-%d")
            clause_str = f"{date_col} BETWEEN '{start_d}' AND '{end_d}'"
            return {
                "start_date": start_d,
                "end_date": end_d,
                "clause": clause_str,
                "sql_clause": clause_str,
                "matched_phrase": "Last 7 Days",
                "resolved": True
            }

        return cls._empty_response()

    @staticmethod
    def _empty_response():
        return {
            "start_date": None,
            "end_date": None,
            "clause": None,
            "sql_clause": None,
            "matched_phrase": None,
            "resolved": False
        }
