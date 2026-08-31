"""
🏛️ PRV CAPITAL | EXCHANGE TRADING CALENDARS
Comprehensive, timezone-aware holiday and schedule validation for:
- London Stock Exchange (LSE) - UK
- New York Stock Exchange & NASDAQ (NYSE/NASDAQ) - US
"""
from datetime import date, timedelta
from typing import Optional, Dict, Tuple, Set


def get_easter_sunday(year: int) -> date:
    """
    Computes Easter Sunday for any Gregorian calendar year using the Meeus/Jones/Butcher algorithm.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _get_nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    Returns the n-th occurrence of a given weekday in a month.
    weekday: 0 = Monday, 6 = Sunday.
    n: 1-indexed (e.g. 1 = 1st, 3 = 3rd).
    """
    first_day = date(year, month, 1)
    day_offset = (weekday - first_day.weekday()) % 7
    first_occurrence = first_day + timedelta(days=day_offset)
    return first_occurrence + timedelta(weeks=n - 1)


def _get_last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """
    Returns the last occurrence of a given weekday in a month.
    weekday: 0 = Monday, 6 = Sunday.
    """
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    day_offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=day_offset)


class ExchangeCalendar:
    """
    Accurate Holiday & Market Schedule Engine for LSE and US Exchanges.
    """
    
    @classmethod
    def get_uk_lse_holidays(cls, year: int) -> Dict[date, str]:
        """
        Returns all official London Stock Exchange (LSE) market holidays for a given year.
        """
        holidays: Dict[date, str] = {}
        
        # 1. New Year's Day (Jan 1, substitute Monday if weekend)
        nyd = date(year, 1, 1)
        if nyd.weekday() == 5:  # Sat -> Mon Jan 3
            holidays[date(year, 1, 3)] = "New Year's Day (Observed)"
        elif nyd.weekday() == 6:  # Sun -> Mon Jan 2
            holidays[date(year, 1, 2)] = "New Year's Day (Observed)"
        else:
            holidays[nyd] = "New Year's Day"
            
        # 2. Good Friday & Easter Monday
        easter = get_easter_sunday(year)
        good_friday = easter - timedelta(days=2)
        easter_monday = easter + timedelta(days=1)
        holidays[good_friday] = "Good Friday"
        holidays[easter_monday] = "Easter Monday"
        
        # 3. Early May Bank Holiday (First Monday in May)
        early_may = _get_nth_weekday_of_month(year, 5, 0, 1)
        holidays[early_may] = "Early May Bank Holiday"
        
        # 4. Spring Bank Holiday (Last Monday in May)
        spring_bank = _get_last_weekday_of_month(year, 5, 0)
        holidays[spring_bank] = "Spring Bank Holiday"
        
        # 5. Summer Bank Holiday (Last Monday in August)
        summer_bank = _get_last_weekday_of_month(year, 8, 0)
        holidays[summer_bank] = "Summer Bank Holiday"
        
        # 6. Christmas Day & Boxing Day (with UK substitute rules)
        xmas = date(year, 12, 25)
        boxing = date(year, 12, 26)
        
        if xmas.weekday() == 4:  # Fri
            holidays[xmas] = "Christmas Day"
            holidays[date(year, 12, 28)] = "Boxing Day (Observed)"
        elif xmas.weekday() == 5:  # Sat
            holidays[date(year, 12, 27)] = "Christmas Day (Observed)"
            holidays[date(year, 12, 28)] = "Boxing Day (Observed)"
        elif xmas.weekday() == 6:  # Sun
            holidays[date(year, 12, 26)] = "Boxing Day"
            holidays[date(year, 12, 27)] = "Christmas Day (Observed)"
        else:
            holidays[xmas] = "Christmas Day"
            if boxing.weekday() == 5:  # Sat
                holidays[date(year, 12, 28)] = "Boxing Day (Observed)"
            elif boxing.weekday() == 6:  # Sun
                holidays[date(year, 12, 28)] = "Boxing Day (Observed)"
            else:
                holidays[boxing] = "Boxing Day"
                
        # Historical / Special one-off UK public holidays
        if year == 2022:
            holidays[date(2022, 6, 3)] = "Platinum Jubilee Bank Holiday"
            holidays[date(2022, 9, 19)] = "State Funeral of Queen Elizabeth II"
        elif year == 2023:
            holidays[date(2023, 5, 8)] = "Coronation of King Charles III"
            
        return holidays

    @classmethod
    def get_us_nyse_holidays(cls, year: int) -> Dict[date, str]:
        """
        Returns all official NYSE / NASDAQ market holidays for a given year.
        """
        holidays: Dict[date, str] = {}
        
        # 1. New Year's Day (Jan 1)
        nyd = date(year, 1, 1)
        if nyd.weekday() == 6:  # Sun -> Mon Jan 2
            holidays[date(year, 1, 2)] = "New Year's Day (Observed)"
        elif nyd.weekday() == 5:  # Sat -> Fri Dec 31 of previous year (if applicable)
            pass
        else:
            holidays[nyd] = "New Year's Day"
            
        # 2. Martin Luther King, Jr. Day (3rd Monday in January)
        mlk = _get_nth_weekday_of_month(year, 1, 0, 3)
        holidays[mlk] = "Martin Luther King, Jr. Day"
        
        # 3. Washington's Birthday / Presidents' Day (3rd Monday in February)
        presidents = _get_nth_weekday_of_month(year, 2, 0, 3)
        holidays[presidents] = "Washington's Birthday (Presidents' Day)"
        
        # 4. Good Friday (Friday before Easter Sunday)
        easter = get_easter_sunday(year)
        good_friday = easter - timedelta(days=2)
        holidays[good_friday] = "Good Friday"
        
        # 5. Memorial Day (Last Monday in May)
        memorial = _get_last_weekday_of_month(year, 5, 0)
        holidays[memorial] = "Memorial Day"
        
        # 6. Juneteenth National Independence Day (June 19, since 2022)
        if year >= 2022:
            june19 = date(year, 6, 19)
            if june19.weekday() == 5:  # Sat -> Fri June 18
                holidays[date(year, 6, 18)] = "Juneteenth (Observed)"
            elif june19.weekday() == 6:  # Sun -> Mon June 20
                holidays[date(year, 6, 20)] = "Juneteenth (Observed)"
            else:
                holidays[june19] = "Juneteenth National Independence Day"
                
        # 7. Independence Day (July 4)
        july4 = date(year, 7, 4)
        if july4.weekday() == 5:  # Sat -> Fri July 3
            holidays[date(year, 7, 3)] = "Independence Day (Observed)"
        elif july4.weekday() == 6:  # Sun -> Mon July 5
            holidays[date(year, 7, 5)] = "Independence Day (Observed)"
        else:
            holidays[july4] = "Independence Day"
            
        # 8. Labor Day (First Monday in September)
        labor = _get_nth_weekday_of_month(year, 9, 0, 1)
        holidays[labor] = "Labor Day"
        
        # 9. Thanksgiving Day (Fourth Thursday in November)
        thanksgiving = _get_nth_weekday_of_month(year, 11, 3, 4)
        holidays[thanksgiving] = "Thanksgiving Day"
        
        # 10. Christmas Day (Dec 25)
        xmas = date(year, 12, 25)
        if xmas.weekday() == 5:  # Sat -> Fri Dec 24
            holidays[date(year, 12, 24)] = "Christmas Day (Observed)"
        elif xmas.weekday() == 6:  # Sun -> Mon Dec 26
            holidays[date(year, 12, 26)] = "Christmas Day (Observed)"
        else:
            holidays[xmas] = "Christmas Day"
            
        return holidays

    @classmethod
    def get_uk_holiday_name(cls, d: date) -> Optional[str]:
        """Returns the UK holiday name if date is a holiday, else None."""
        holidays = cls.get_uk_lse_holidays(d.year)
        return holidays.get(d)

    @classmethod
    def get_us_holiday_name(cls, d: date) -> Optional[str]:
        """Returns the US holiday name if date is a holiday, else None."""
        holidays = cls.get_us_nyse_holidays(d.year)
        return holidays.get(d)

    @classmethod
    def is_uk_holiday(cls, d: date) -> bool:
        return cls.get_uk_holiday_name(d) is not None

    @classmethod
    def is_us_holiday(cls, d: date) -> bool:
        return cls.get_us_holiday_name(d) is not None

    @classmethod
    def is_uk_early_close(cls, d: date) -> bool:
        """
        LSE closes early (12:30 London time) on Christmas Eve and New Year's Eve (if weekdays).
        """
        if d.weekday() >= 5:
            return False
        if d.month == 12 and d.day in (24, 31):
            return True
        return False

    @classmethod
    def is_us_early_close(cls, d: date) -> bool:
        """
        US Markets close early (13:00 NY time) on:
        - Day after Thanksgiving (Black Friday)
        - Christmas Eve (Dec 24, if weekday)
        - Day before July 4th (July 3, if July 4 is weekday/Fri)
        """
        if d.weekday() >= 5:
            return False
        # Black Friday (Friday after 4th Thursday in Nov)
        thanksgiving = _get_nth_weekday_of_month(d.year, 11, 3, 4)
        black_friday = thanksgiving + timedelta(days=1)
        if d == black_friday:
            return True
        # Christmas Eve
        if d.month == 12 and d.day == 24:
            return True
        # Day before Independence Day
        if d.month == 7 and d.day == 3 and date(d.year, 7, 4).weekday() != 6:
            return True
        return False


exchange_calendar = ExchangeCalendar()
