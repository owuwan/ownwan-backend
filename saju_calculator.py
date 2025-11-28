from datetime import datetime
from lunarcalendar import Converter, Solar, Lunar

HEAVENLY_STEMS = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
EARTHLY_BRANCHES = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']

def get_year_pillar(year):
    stem_index = (year - 4) % 10
    branch_index = (year - 4) % 12
    return HEAVENLY_STEMS[stem_index] + EARTHLY_BRANCHES[branch_index]

def get_month_pillar(year, month):
    year_stem_index = (year - 4) % 10
    month_stem_index = (year_stem_index * 2 + month) % 10
    month_branch_index = (month + 1) % 12
    return HEAVENLY_STEMS[month_stem_index] + EARTHLY_BRANCHES[month_branch_index]

def get_day_pillar(year, month, day):
    base_date = datetime(1900, 1, 1)
    target_date = datetime(year, month, day)
    days_diff = (target_date - base_date).days
    stem_index = (days_diff + 6) % 10
    branch_index = (days_diff + 8) % 12
    return HEAVENLY_STEMS[stem_index] + EARTHLY_BRANCHES[branch_index]

def get_hour_pillar(hour, day_stem_index):
    # birth_hour가 "14-16" 형식이면 첫 번째 숫자 추출
    # None이거나 '알 수 없음' 같은 값이면 기본값 사용
    if hour is None or hour == '알 수 없음':
        hour = 12  # 기본값 (오시)
    elif isinstance(hour, str):
        if '-' in hour:
            try:
                hour = int(hour.split('-')[0])
            except:
                hour = 12  # 변환 실패시 기본값
        else:
            try:
                hour = int(hour)
            except:
                hour = 12  # 변환 실패시 기본값
    elif not isinstance(hour, int):
        hour = 12  # int가 아니면 기본값
    
    hour_branch_index = (hour + 1) // 2 % 12
    hour_stem_index = (day_stem_index * 2 + hour_branch_index) % 10
    return HEAVENLY_STEMS[hour_stem_index] + EARTHLY_BRANCHES[hour_branch_index]

def calculate_saju(birth_year, birth_month, birth_day, birth_hour, solar_lunar='solar'):
    """
    사주 계산 함수
    
    Parameters:
        birth_year (int): 생년 (1900-2100)
        birth_month (int): 생월 (1-12)
        birth_day (int): 생일 (1-31)
        birth_hour (int): 태어난 시간 (0-23)
        solar_lunar (str): 'solar' 또는 'lunar'
    """
    # 데이터 타입 검증
    try:
        birth_year = int(birth_year)
        birth_month = int(birth_month)
        birth_day = int(birth_day)
        if isinstance(birth_hour, str):
            if '-' in birth_hour:
                birth_hour = int(birth_hour.split('-')[0])
            else:
                birth_hour = int(birth_hour)
        else:
            birth_hour = int(birth_hour) if birth_hour else 12
    except (ValueError, TypeError):
        raise ValueError("입력 데이터가 올바르지 않습니다")
    
    # 음력 변환
    if solar_lunar == 'lunar':
        try:
            lunar = Lunar(birth_year, birth_month, birth_day, isleap=False)
            solar = Converter.Lunar2Solar(lunar)
            birth_year = solar.year
            birth_month = solar.month
            birth_day = solar.day
        except Exception as e:
            raise ValueError(f"음력 변환 실패: {str(e)}")
    
    # 사주 4주 계산
    year_pillar = get_year_pillar(birth_year)
    month_pillar = get_month_pillar(birth_year, birth_month)
    day_pillar = get_day_pillar(birth_year, birth_month, birth_day)
    
    day_stem_index = HEAVENLY_STEMS.index(day_pillar[0])
    hour_pillar = get_hour_pillar(birth_hour, day_stem_index)
    
    return {
        'year': year_pillar,
        'month': month_pillar,
        'day': day_pillar,
        'hour': hour_pillar
    }

def calculate_element_count(saju_data):
    """
    사주팔자의 오행 개수 계산
    
    Parameters:
        saju_data (dict): calculate_saju()의 반환값
                         {'year': '갑자', 'month': '을축', 'day': '병인', 'hour': '정묘'}
    
    Returns:
        dict: {'목': 2, '화': 1, '토': 3, '금': 1, '수': 1}
    """
    # 천간지지 → 오행 매핑
    element_map = {
        # 천간 (10개)
        '갑': '목', '을': '목',
        '병': '화', '정': '화',
        '무': '토', '기': '토',
        '경': '금', '신': '금',
        '임': '수', '계': '수',
        # 지지 (12개)
        '인': '목', '묘': '목',
        '사': '화', '오': '화',
        '진': '토', '술': '토', '축': '토', '미': '토',
        '신': '금', '유': '금',
        '자': '수', '해': '수'
    }
    
    # 개수 초기화
    element_count = {'목': 0, '화': 0, '토': 0, '금': 0, '수': 0}
    
    # 년월일시주 각 2글자씩 = 총 8글자
    for pillar in ['year', 'month', 'day', 'hour']:
        chars = saju_data.get(pillar, '')
        for char in chars:
            element = element_map.get(char)
            if element:
                element_count[element] += 1
    
    return element_count