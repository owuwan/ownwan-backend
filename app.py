from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from saju_calculator import calculate_saju
from datetime import datetime, timedelta
import os
from openai import OpenAI
from dotenv import load_dotenv
import pytz
from pymongo import MongoClient
from functools import wraps
import jwt
import requests
import json

# .env 파일 로드
load_dotenv()

app = Flask(__name__)
# CORS 설정 - credentials 지원
CORS(app, 
     supports_credentials=True,
     origins=[
         "http://localhost:3000",
         "http://localhost:3004",
         "http://10.226.90.251:3004",
         "http://10.226.90.18:3004",
         "https://ownwan.com",
         "https://www.ownwan.com",
         "https://ownwan-frontend.vercel.app"
     ],
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     expose_headers=["Set-Cookie"]
)

# MongoDB 연결 (환경변수 사용)
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['ownwan']

# Collections
users_collection = db['users']
subscriptions_collection = db['subscriptions']
payments_collection = db['payments']
results_collection = db['results']

print(f"✅ MongoDB 연결: {MONGO_URI[:30]}...")

# JWT 설정
JWT_SECRET = "your-secret-key-change-in-production-2025"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30
app.config['SECRET_KEY'] = JWT_SECRET

# OAuth 키
KAKAO_REST_API_KEY = "a7ee610ed33ef0f48bcdd57547922bdf"
NAVER_CLIENT_ID = "e4Wn2U1EEdWVgrTTm5EL"
NAVER_CLIENT_SECRET = "ZTZnTcw_89"
# 토스페이먼츠 테스트 키
TOSS_CLIENT_KEY = "test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq"
TOSS_SECRET_KEY = "test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R"


# ═══════════════════════════════════════
# JWT 인증 미들웨어
# ═══════════════════════════════════════

def login_required(f):
    """JWT 인증 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 헤더에서 토큰 가져오기
        token = request.headers.get('Authorization')
        
        # 🆕 헤더에 없으면 쿠키에서 가져오기
        if not token:
            token = request.cookies.get('access_token')
        
        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 없습니다'}), 401
        
        # Bearer 제거
        if token.startswith('Bearer '):
            token = token[7:]
        
        try:
            # 토큰 검증
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            request.user_id = payload['user_id']
            
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': '토큰이 만료되었습니다'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다'}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# ✅ v20 추가: 운세 캐시 (메모리)
fortune_cache = {}
cache_date = None  # 캐시가 생성된 날짜

print("=" * 50)
print("🎯 EVERY DAY 사주리포트 API 서버 시작!")
print("=" * 50)

@app.route('/api/saju', methods=['POST'])
def get_saju():
    try:
        data = request.json
        print("\n" + "=" * 50)
        print("📨 사주 계산 요청 받음")
        print("=" * 50)
        
        # 입력 데이터
        name = data.get('name')
        birth_year = data.get('birthYear')
        birth_month = data.get('birthMonth')
        birth_day = data.get('birthDay')
        birth_hour = data.get('birthHour', 12)  # 기본값 12시(오시)
        gender = data.get('gender')
        is_lunar = data.get('isLunar', False)
        
        # 필수 데이터 검증
        if not all([name, birth_year, birth_month, birth_day, gender]):
            missing = []
            if not name: missing.append('이름')
            if not birth_year: missing.append('생년')
            if not birth_month: missing.append('생월')
            if not birth_day: missing.append('생일')
            if not gender: missing.append('성별')
            
            error_msg = f"필수 정보가 누락되었습니다: {', '.join(missing)}"
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400
        
        # 데이터 타입 변환 및 검증
        try:
            birth_year = int(birth_year)
            birth_month = int(birth_month)
            birth_day = int(birth_day)
            
            # 범위 검증
            if not (1900 <= birth_year <= 2100):
                raise ValueError("생년은 1900-2100 사이여야 합니다")
            if not (1 <= birth_month <= 12):
                raise ValueError("생월은 1-12 사이여야 합니다")
            if not (1 <= birth_day <= 31):
                raise ValueError("생일은 1-31 사이여야 합니다")
                
        except ValueError as e:
            print(f"❌ 데이터 형식 오류: {e}")
            return jsonify({"error": f"잘못된 데이터 형식: {str(e)}"}), 400
        
        # birth_hour 처리
        if birth_hour == '알 수 없음' or birth_hour is None:
            birth_hour = 12
        elif isinstance(birth_hour, str):
            try:
                if '-' in birth_hour:
                    birth_hour = int(birth_hour.split('-')[0])
                else:
                    birth_hour = int(birth_hour)
            except:
                birth_hour = 12
        
        print(f"이름: {name}")
        print(f"생년월일: {birth_year}년 {birth_month}월 {birth_day}일")
        print(f"태어난 시간: {birth_hour}시")
        print(f"성별: {gender}")
        print(f"음력/양력: {'음력' if is_lunar else '양력'}")
        
        # 사주 계산
        solar_lunar = 'lunar' if is_lunar else 'solar'
        
        saju_result = calculate_saju(
            birth_year, birth_month, birth_day,
            birth_hour, solar_lunar
        )
        

        # 오행 개수 계산
        from saju_calculator import calculate_element_count
        element_count = calculate_element_count(saju_result)
        print(f"🎨 오행 분석: {element_count}")
        print("\n=== 사주 계산 완료 ===")
        print(f"년주: {saju_result['year']}")
        print(f"월주: {saju_result['month']}")
        print(f"일주: {saju_result['day']}")
        print(f"시주: {saju_result['hour']}")
        
        # ✅ v20 수정: 캐싱 시스템 적용
        gpt_fortune = generate_fortune_with_gpt_cached(
            name, gender, birth_year, birth_month, birth_day, birth_hour, saju_result, is_lunar
        )
        
        # 응답 데이터 구성
        response_data = {
            "name": name,
            "birth_date": f"{birth_year}.{birth_month}.{birth_day}",
            "birth_hour": birth_hour,
            "gender": gender,
            "is_lunar": is_lunar,
            "saju": saju_result,
            "element_count": element_count,
            "gpt_fortune": gpt_fortune
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ✅ v20 추가: 캐싱 시스템이 적용된 운세 생성 함수
def generate_fortune_with_gpt_cached(name, gender, year, month, day, hour, saju_data, is_lunar):
    """캐싱 시스템이 적용된 GPT 운세 생성"""
    global fortune_cache, cache_date
    
    # 한국 시간대 설정
    kst = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst)
    today_str = today.strftime('%Y-%m-%d')
    
    # 자정이 지나면 캐시 초기화
    if cache_date != today_str:
        print("\n🔄 날짜가 바뀌어 캐시를 초기화합니다")
        fortune_cache.clear()
        cache_date = today_str
    
    # 캐시 키 생성 (날짜_생년월일_시간)
    cache_key = f"{today_str}_{year}-{month}-{day}_{hour}"
    
    # 캐시 확인
    if cache_key in fortune_cache:
        print(f"\n💾 캐시에서 운세를 가져옵니다: {cache_key}")
        return fortune_cache[cache_key]
    
    # 캐시에 없으면 GPT로 새로 생성
    print(f"\n🆕 새로운 운세를 생성합니다: {cache_key}")
    gpt_fortune = generate_fortune_with_gpt(name, gender, year, month, day, hour, saju_data, is_lunar)
    
    # 캐시에 저장
    fortune_cache[cache_key] = gpt_fortune
    print(f"✅ 캐시에 저장 완료 (현재 캐시 개수: {len(fortune_cache)})")
    
    return gpt_fortune


def generate_fortune_with_gpt(name, gender, year, month, day, hour, saju_data, is_lunar):
    """GPT를 사용하여 15가지 운세 생성 (v19 - 사실 기반 솔직한 표현)"""
    
    # 음력/양력 표시
    calendar_type = "음력" if is_lunar else "양력"
    
    # 한국 시간대 설정
    kst = pytz.timezone('Asia/Seoul')
    today = datetime.now(kst)
    
    # 오늘 날짜 정보
    today_year = today.year
    today_month = today.month
    today_day = today.day
    weekday_kr = ['월', '화', '수', '목', '금', '토', '일'][today.weekday()]
    
    try:
        print("\n🤖 GPT 운세 생성 시작...")
        
        # 프롬프트 작성 - v19 업데이트
        prompt = f"""당신은 전문 사주 명리학자입니다. 
아래 사주 정보를 바탕으로 오늘의 운세를 작성해주세요.

**사용자 정보:**
- 이름: {name}
- 성별: {gender}
- 생년월일: {year}년 {month}월 {day}일 ({calendar_type})
- 출생시간: {hour}시
- 오늘 날짜: {today_year}년 {today_month}월 {today_day}일 ({weekday_kr}요일)

**사주 팔자:**
년주: {saju_data['year']}
월주: {saju_data['month']}
일주: {saju_data['day']}
시주: {saju_data['hour']}

**작성 지침:**

1. 종합운: 오늘 하루 전반적인 운세 (사주 팔자에 따라 좋으면 긍정적, 나쁘면 부정적, 중간이면 중립적으로 솔직하게 작성, 2-3문장)
2. 애정운: 연인, 배우자, 이성 관계 운세 (사주 팔자에 따라 솔직하게, 2문장)
3. 사업운: 직장, 업무, 사업 관련 운세 (사주 팔자에 따라 솔직하게, 2문장)
4. 금전운: 재물, 투자, 소비 관련 운세 (사주 팔자에 따라 솔직하게, 2문장)
5. 건강운: 신체, 정신 건강 관련 운세 (사주 팔자에 따라 솔직하게, 2문장)
6. 대인관계운: 가족 외 사람들과의 관계 운세 (사주 팔자에 따라 솔직하게, 2문장)
7. 가족운: 부모, 자녀, 형제 등 가족 관계 운세 (사주 팔자에 따라 솔직하게, 2문장)
8. 학업운: 공부, 학습, 자격증 등 (사주 팔자에 따라 솔직하게, 2문장)
9. 여행운: 이동, 여행, 외출 관련 운세 (사주 팔자에 따라 솔직하게, 2문장)
10. 부동산운: 집, 땅, 건물 관련 운세 (사주 팔자에 따라 솔직하게, 2문장)

11. 행운의 장소: 오늘 방문하면 좋을 구체적인 장소 1곳과 부연설명
   - 형식: "장소명" - 부연설명
   - 장소는 **200가지 이상 중에서 무작위로 선택**
   - **중요: 최소 15일 동안 같은 장소가 중복되지 않도록 매우 다양하게 선택**
   - 예: 식물원이 오늘 나왔으면 최소 15일 후에나 다시 선택 가능
   - 매번 완전히 다른 카테고리에서 선택하세요 (오늘 문화시설이면 내일은 운동시설, 모레는 상업시설 등)
   - 장소 예시: 인근 공원, 도서관, 카페, 서점, 미술관, 박물관, 갤러리, 공연장, 영화관, 극장, 음악당, 오페라하우스, 콘서트홀, 강변, 산책로, 등산로, 트레킹 코스, 자전거길, 조깅 코스, 쇼핑몰, 백화점, 아울렛, 전통시장, 재래시장, 야시장, 플리마켓, 수제품 가게, 빈티지샵, 앤티크샵, 북카페, 브런치 카페, 디저트 카페, 베이커리, 파티시에, 레스토랑, 비스트로, 펍, 와인바, 루프탑 카페, 뷰맛집, 수목원, 식물원, 온실, 정원, 한옥마을, 고궁, 성, 요새, 전망대, 타워, 관측소, 천문대, 해변, 바닷가, 해수욕장, 항구, 선착장, 등대, 호숫가, 강가, 계곡, 폭포, 약수터, 온천, 사찰, 절, 성당, 교회, 성지, 명상센터, 요가센터, 필라테스, 헬스장, 체육관, 스포츠센터, 수영장, 사우나, 찜질방, 스파, 마사지샵, 태닝샵, 네일샵, 헤어샵, 미용실, 피부과, 한의원, 병원, 약국, 동물병원, 애완동물샵, 펫샵, 꽃집, 화원, 문구점, 팬시점, 장난감 가게, 취미용품점, 악기점, 레코드샵, 만화책방, 중고서점, 헌책방, 전자상가, IT몰, 가전매장, 가구점, 인테리어샵, 철물점, 공구상, 낚시점, 캠핑용품점, 등산용품점, 스포츠용품점, 골프연습장, 볼링장, 당구장, 스크린골프, 탁구장, 배드민턴장, 테니스장, 야구장, 축구장, 농구장, 실내체육관, 빙상장, 스케이트장, 스키장, 워터파크, 놀이공원, 테마파크, 동물원, 수족관, 과학관, 역사박물관, 전쟁기념관, 민속촌, 체험관, 키즈카페, 보드게임카페, 방탈출카페, VR체험관, PC방, 오락실, 노래방, 코인노래방, 스터디카페, 코워킹스페이스, 공유오피스, 도서관 열람실, 은행, 우체국, 동사무소, 주민센터, 세무서, 경찰서, 소방서, 지하철역, 버스터미널, 기차역, 공항, 면세점, 여행사, 렌터카, 세차장, 주유소, 정비소, 타이어샵, 주차장, 편의점, 마트, 슈퍼마켓, 대형마트, 창고형 할인매장 등
   - 부연설명은 긍정적인 메시지 (예: "마음을 비우고 산책하기 좋은 날이에요", "새로운 영감을 얻을 수 있는 시간", "맛있는 음식과 함께 여유를", "좋은 에너지를 충전할 수 있어요")

12. 행운의 숫자: 1-45 사이 숫자 6개를 **완전 랜덤**으로 선택 (중복 없이, 쉼표로 구분)
   - **중요: 번호대별 균등 분배를 하지 마세요. 완전 랜덤으로 선택하세요.**
   - 같은 번호대에 여러 개 몰려도 전혀 무관합니다
   - 나쁜 예시: 3, 17, 22, 31, 38, 42 (각 번호대 1개씩 균등 배치)
   - 좋은 예시: 7, 12, 15, 18, 23, 44 (10번대 4개, 40번대 1개 등 불균등 OK)
   - 좋은 예시: 2, 5, 8, 11, 13, 41 (10번대 미만 5개, 40번대 1개 등 극단적 불균등도 OK)

13. 행운의 컬러: 오늘 입거나 소지하면 좋을 색상 (다양하고 세련된 컬러명 사용)
   - **200가지 이상의 다양한 컬러명 중에서 무작위로 선택**
   - 빨강 계열: 로즈 레드, 체리 레드, 크림슨 레드, 와인 레드, 버건디, 마룬, 루비 레드, 스칼렛, 버밀리온, 카디널 레드, 라즈베리, 스트로베리, 코랄 핑크, 살몬 핑크, 피치 핑크, 더스티 로즈, 애쉬 로즈, 핫 핑크, 푸시아, 매젠타
   - 주황 계열: 피치, 살구색, 코랄, 탠저린, 선셋 오렌지, 버밍 오렌지, 카라멜, 테라코타, 시에나, 번트 시에나, 어텀 오렌지, 퍼시몬, 만다린, 팜킨, 행커초프 오렌지
   - 노랑 계열: 레몬 옐로우, 카나리아 옐로우, 선플라워 옐로우, 골든 옐로우, 머스타드, 크림 옐로우, 바나나 옐로우, 버터 옐로우, 샴페인, 베이지, 샌드, 카키, 밀크티, 라떼, 아이보리, 에그셸
   - 초록 계열: 라임 그린, 민트 그린, 스프링 그린, 애플 그린, 올리브 그린, 포레스트 그린, 헌터 그린, 에메랄드, 제이드, 비리디안, 티파니 블루, 터쿼이즈, 아쿠아민트, 시그널 그린, 네온 그린, 모스 그린, 세이지 그린, 피스타치오, 차트리스
   - 파랑 계열: 스카이 블루, 베이비 블루, 파우더 블루, 라이트 블루, 네이비 블루, 로얄 블루, 코발트 블루, 울트라마린, 세룰리안 블루, 아쿠아 블루, 시안, 터키석, 틸 블루, 페트롤 블루, 오션 블루, 데님 블루, 인디고, 미드나잇 블루, 프러시안 블루
   - 보라 계열: 라벤더, 퍼플, 바이올렛, 아메티스트, 자주색, 플럼, 라일락, 모브, 퍼플 헤이즈, 그레이프, 오키드, 히아신스, 퍼플 레인, 로열 퍼플, 딥 퍼플
   - 분홍 계열: 베이비 핑크, 블러쉬 핑크, 로즈 쿼츠, 밀레니얼 핑크, 다스티 핑크, 뮤트 핑크, 솔티드 핑크, 누드 핑크
   - 갈색 계열: 브라운, 초콜릿, 코코아, 에스프레소, 커피, 카푸치노, 모카, 체스트넛, 마호가니, 세피아, 탄, 카멜, 토프
   - 무채색 계열: 화이트, 스노우 화이트, 펄 화이트, 크림 화이트, 아이보리 화이트, 라이트 그레이, 실버 그레이, 애쉬 그레이, 차콜 그레이, 다크 그레이, 슬레이트 그레이, 건메탈, 블랙, 제트 블랙, 오닉스 블랙
   - 메탈릭 계열: 실버, 골드, 로즈 골드, 샴페인 골드, 브론즈, 코퍼, 플래티넘, 메탈릭 그레이
   - 파스텔 계열: 파스텔 핑크, 파스텔 블루, 파스텔 그린, 파스텔 옐로우, 파스텔 퍼플, 파스텔 오렌지
   - 비비드 계열: 비비드 레드, 비비드 오렌지, 네온 옐로우, 네온 그린, 일렉트릭 블루, 네온 핑크

14. 리스크: 오늘 조심해야 할 점이나 피해야 할 일 
   - **경각심을 주는 강력한 톤으로 작성** (예: "절대 주의하세요", "반드시 확인하세요", "각별히 조심하세요")
   - 구체적이고 현실적인 위험 요소 명시 (2-3문장)

15. 오늘 조심할 물건: 오늘 특히 주의해야 할 물건 1개와 경각심 있는 부연설명
   - 형식: "물건명" - 부연설명
   - **200가지 이상의 물건 중에서 무작위로 선택**
   - **중요: 최소 15일 동안 같은 물건이 중복되지 않도록 매우 다양하게 선택**
   - 예: 가위가 오늘 나왔으면 최소 15일 후에나 다시 선택 가능
   - **중요: 날카로운 물건(칼, 가위, 커터 등)만 반복하지 말고 다양한 카테고리에서 선택하세요**
   - 카테고리 다양화: 날카로운 물건, 뜨거운 물건, 깨지기 쉬운 물건, 전기제품, 가스제품, 화학제품, 전자기기, 귀중품, 약품, 차량관련, 계단/높은곳, 미끄러운 바닥 등
   - 물건 예시: 날카로운 커터칼, 식칼, 과도, 가위, 면도칼, 조각칼, 송곳, 칼, 도끼, 톱, 망치, 드라이버, 펜치, 니퍼, 전기드릴, 그라인더, 전동공구, 뜨거운 냄비, 프라이팬, 주전자, 찜통, 압력솥, 오븐, 그릴, 토치, 인두, 용접기, 유리컵, 도자기, 접시, 그릇, 화분, 거울, 액자, 유리창, 샤워부스, 어항, 전기 콘센트, 멀티탭, 연장선, 충전기, 어댑터, 전선, 배선, 누전차단기, 다리미, 고데기, 헤어드라이어, 전기면도기, 전기장판, 전기히터, 전기난로, 온풍기, 선풍기, 에어컨, 가습기, 제습기, 공기청정기, 전기밥솥, 전기포트, 토스터, 믹서기, 블렌더, 에어프라이어, 전자레인지, 인덕션, 가스레인지, 가스버너, 부탄가스, 라이터, 성냥, 초, 향, 모기향, 살충제, 세제, 표백제, 락스, 화학약품, 농약, 페인트, 신너, 접착제, 본드, 시너, 아세톤, 휴대폰, 스마트폰, 태블릿, 노트북, 컴퓨터, 모니터, 키보드, 마우스, 하드디스크, USB, 이어폰, 헤드폰, 카메라, DSLR, 렌즈, 드론, 게임기, 리모컨, 차 열쇠, 집 열쇠, 사무실 열쇠, 금고 열쇠, 지갑, 핸드백, 백팩, 캐리어, 귀중품, 보석, 시계, 반지, 목걸이, 귀걸이, 팔찌, 안경, 선글라스, 렌즈, 약, 영양제, 비타민, 약병, 주사기, 체온계, 혈압계, 화장품, 향수, 헤어스프레이, 매니큐어, 립스틱, 우산, 양산, 장우산, 접이식 우산, 가방, 지갑, 신용카드, 현금, 수표, 통장, 도장, 인감, 계약서, 서류, 책, 노트, 다이어리, 펜, 볼펜, 만년필, 자, 커터, 스테이플러, 클립, 압정, 신발, 구두, 운동화, 샌들, 슬리퍼, 하이힐, 부츠, 자전거, 킥보드, 전동킥보드, 스케이트보드, 인라인스케이트, 오토바이, 자동차, 계단, 에스컬레이터, 엘리베이터, 문턱, 턱, 미끄러운 바닥, 젖은 타일, 빙판, 뾰족한 모서리, 날카로운 모서리, 유리문, 회전문, 자동문, 철봉, 그네, 미끄럼틀, 시소, 사다리, 높은 곳, 창문, 베란다, 난간, 계단 손잡이
   - 부연설명은 **경각심을 주는 강력한 톤**으로 작성
   - 예시: "항상 조심할 물건이지만 오늘은 더욱더 신경쓰세요!", "작은 부주의가 큰 사고로 이어질 수 있습니다. 반드시 주의하세요!", "안전하게 다루는 것이 매우 중요한 날입니다!", "절대 소홀히 하지 마세요!", "각별한 주의가 필요합니다!", "오늘만큼은 꼭 조심하세요!"

**중요 사항:**
- 1~10번 항목은 **사주 팔자에 따라 사실 그대로 작성**
  * 좋은 운세: 긍정적으로 표현
  * 나쁜 운세: 부정적으로 솔직하게 표현
  * 중간 운세: 중립적으로 표현
  * 무조건 긍정적으로 쓰지 말고, 진짜 사주 풀이처럼 솔직하게!
- 14번(리스크)와 15번(조심할 물건)은 **경각심을 주는 강력한 톤**으로 작성
- **행운의 장소는 최소 15일 동안 중복되지 않도록** 200가지 중 매우 다양하게 선택
- **오늘 조심할 물건은 최소 15일 동안 중복되지 않도록** 200가지 중 매우 다양하게 선택
- **오늘 조심할 물건은 다양한 카테고리를 순환하며 선택** (오늘 날카로운 물건이면 내일은 전자기기, 모레는 귀중품 등)
- **행운의 숫자는 완전 랜덤** (번호대별 균등 분배 금지, 한 번호대에 여러 개 몰려도 OK)
- 한 달 동안 매일 다른 리포트를 받아도 중복이 최소화되고 내용이 다양하도록

**출력 형식:**
각 항목을 아래 형식으로 정확히 작성해주세요:

1. 종합운: [내용]
2. 애정운: [내용]
3. 사업운: [내용]
4. 금전운: [내용]
5. 건강운: [내용]
6. 대인관계운: [내용]
7. 가족운: [내용]
8. 학업운: [내용]
9. 여행운: [내용]
10. 부동산운: [내용]
11. 행운의 장소: [내용]
12. 행운의 숫자: [내용]
13. 행운의 컬러: [내용]
14. 리스크: [내용]
15. 오늘 조심할 물건: [내용]
"""
        
        print("   📡 OpenAI API 호출 중...")
        
        # GPT API 호출
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 전문 사주 명리학자입니다. 사주 팔자에 따라 좋은 운세는 긍정적으로, 나쁜 운세는 부정적으로 솔직하게 작성합니다. 무조건 긍정적으로 쓰지 않고 진짜 사주 풀이처럼 사실 그대로 표현합니다. 14번(리스크)과 15번(조심할 물건)은 경각심을 주는 강력한 톤으로 작성합니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.95,
            max_tokens=2000
        )
        
        # GPT의 답변 가져오기
        fortune_text = response.choices[0].message.content.strip()
        
        print("   ✅ GPT 운세 생성 완료!")
        print(f"   📝 생성된 운세 길이: {len(fortune_text)}자")
        print("=" * 50)
        print(fortune_text)
        print("=" * 50)
        
        return {
            "success": True,
            "fortune": fortune_text
        }
        
    except Exception as e:
        print(f"   ❌ GPT 오류: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ============================================
# 🆕 월간 운세 기능
# ============================================

def generate_monthly_fortune_with_gpt(name, gender, saju_data, year, month):
    """GPT를 사용하여 월간 운세 생성"""
    try:
        print("\n🗓️ GPT 월간 운세 생성 시작...")
        
        # 프롬프트 작성
        prompt = f"""당신은 전문 사주 명리학자입니다. 
아래 사주 정보를 바탕으로 {year}년 {month}월 한 달간의 운세를 작성해주세요.

[사주 정보]
이름: {name}
성별: {gender}
년주: {saju_data['year']}
월주: {saju_data['month']}
일주: {saju_data['day']}
시주: {saju_data['hour']}

다음 항목들을 각각 3-4문장으로 작성해주세요:
1. 이번 달 총운: 전반적인 운세와 흐름
2. 애정운: 연애/결혼/인간관계의 한 달 흐름
3. 사업운: 직장/사업/학업의 한 달 전망
4. 금전운: 재물/투자/소비 관련 조언
5. 건강운: 건강 상태와 주의사항
6. 대인관계운: 사람들과의 관계 조언
7. 가족운: 가정 내 화목과 조화
8. 학업운: 공부나 배움의 기회
9. 여행운: 이동이나 여행 관련
10. 부동산운: 주거나 부동산 관련
11. 행운의 날: 이번 달 중 특별히 좋은 날짜 3개 (예: {month}월 7일, 15일, 23일)
12. 행운의 컬러: 이번 달 행운을 부르는 색상 1개
13. 주의할 시기: 이번 달 중 조심해야 할 날짜나 시기
14. 이번 달 조언: 한 달을 잘 보내기 위한 종합 조언

[중요 지시사항]
- 각 항목은 반드시 "숫자. 제목: 내용" 형식으로 작성
- 11-14번 항목은 간단명료하게 작성
- 한 달 전체의 흐름과 특징을 파악할 수 있도록 작성
- 긍정적이면서도 현실적으로 작성

출력 형식 예시:
1. 이번 달 총운: 이번 달은...
2. 애정운: 애정운은...
...
11. 행운의 날: {month}월 7일, 15일, 23일
12. 행운의 컬러: 보라색
13. 주의할 시기: {month}월 중순
14. 이번 달 조언: 이번 달은..."""

        print("   📡 OpenAI API 호출 중...")
        
        # GPT API 호출
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 전문 사주 명리학자입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=2000
        )
        
        # GPT의 답변 가져오기
        fortune_text = response.choices[0].message.content
        
        print("   ✅ GPT 월간 운세 생성 완료!")
        print(f"   📝 생성된 운세 길이: {len(fortune_text)}자")
        print("=" * 50)
        print(fortune_text)
        print("=" * 50)
        
        return {
            "success": True,
            "fortune": fortune_text
        }
        
    except Exception as e:
        print(f"   ❌ GPT 오류: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.route('/api/monthly-saju', methods=['POST'])
def get_monthly_saju():
    """월간 사주 운세 생성 API"""
    try:
        data = request.json
        print("\n" + "=" * 50)
        print("📅 월간 사주 계산 요청 받음")
        print("=" * 50)
        
        # 입력 데이터
        name = data.get('name')
        birth_year = data.get('birthYear')
        birth_month = data.get('birthMonth')
        birth_day = data.get('birthDay')
        birth_hour = data.get('birthHour', 12)
        gender = data.get('gender')
        is_lunar = data.get('isLunar', False)
        target_year = data.get('targetYear')  # 조회할 년도
        target_month = data.get('targetMonth')  # 조회할 월
        
        # 필수 데이터 검증
        if not all([name, birth_year, birth_month, birth_day, gender, target_year, target_month]):
            missing = []
            if not name: missing.append('이름')
            if not birth_year: missing.append('생년')
            if not birth_month: missing.append('생월')
            if not birth_day: missing.append('생일')
            if not gender: missing.append('성별')
            if not target_year: missing.append('조회년도')
            if not target_month: missing.append('조회월')
            
            error_msg = f"필수 정보가 누락되었습니다: {', '.join(missing)}"
            print(f"❌ {error_msg}")
            return jsonify({"error": error_msg}), 400
        
        # 데이터 타입 변환 및 검증
        try:
            birth_year = int(birth_year)
            birth_month = int(birth_month)
            birth_day = int(birth_day)
            target_year = int(target_year)
            target_month = int(target_month)
            
            # 범위 검증
            if not (1900 <= birth_year <= 2100):
                raise ValueError("생년은 1900-2100 사이여야 합니다")
            if not (1 <= birth_month <= 12):
                raise ValueError("생월은 1-12 사이여야 합니다")
            if not (1 <= birth_day <= 31):
                raise ValueError("생일은 1-31 사이여야 합니다")
            if not (2020 <= target_year <= 2100):
                raise ValueError("조회년도는 2020-2100 사이여야 합니다")
            if not (1 <= target_month <= 12):
                raise ValueError("조회월은 1-12 사이여야 합니다")
                
        except ValueError as e:
            print(f"❌ 데이터 형식 오류: {e}")
            return jsonify({"error": f"잘못된 데이터 형식: {str(e)}"}), 400
        
        # birth_hour 처리
        if birth_hour == '알 수 없음' or birth_hour is None:
            birth_hour = 12
        elif isinstance(birth_hour, str):
            try:
                if '-' in birth_hour:
                    birth_hour = int(birth_hour.split('-')[0])
                else:
                    birth_hour = int(birth_hour)
            except:
                birth_hour = 12
        
        print(f"이름: {name}")
        print(f"생년월일: {birth_year}년 {birth_month}월 {birth_day}일")
        print(f"태어난 시간: {birth_hour}시")
        print(f"성별: {gender}")
        print(f"음력/양력: {'음력' if is_lunar else '양력'}")
        print(f"조회 대상: {target_year}년 {target_month}월")
        
        # 사주 계산
        solar_lunar = 'lunar' if is_lunar else 'solar'
        
        saju_result = calculate_saju(
            birth_year, birth_month, birth_day,
            birth_hour, solar_lunar
        )
        
        print("\n=== 사주 계산 완료 ===")
        print(f"년주: {saju_result['year']}")
        print(f"월주: {saju_result['month']}")
        print(f"일주: {saju_result['day']}")
        print(f"시주: {saju_result['hour']}")
        
        # GPT로 월간 운세 생성
        gpt_fortune = generate_monthly_fortune_with_gpt(
            name, gender, saju_result, target_year, target_month
        )
        
        # 응답 데이터 구성
        response_data = {
            "name": name,
            "birth_date": f"{birth_year}.{birth_month}.{birth_day}",
            "birth_hour": birth_hour,
            "gender": gender,
            "is_lunar": is_lunar,
            "target_year": target_year,
            "target_month": target_month,
            "saju": saju_result,
            "gpt_fortune": gpt_fortune
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/test')
def test():
    return jsonify({
        "message": "서버 연결 성공!",
        "status": "ok"
    })


# ═══════════════════════════════════════
# 카카오 OAuth
# ═══════════════════════════════════════

@app.route('/api/auth/kakao/callback', methods=['POST'])
def kakao_callback():
    """카카오 로그인 콜백"""
    try:
        data = request.json
        code = data.get('code')
        redirect_uri = data.get('redirect_uri', 'http://localhost:3004/auth/kakao/callback')
        
        print(f"\n🔐 카카오 로그인 시도")

        # 카카오 토큰 요청
        token_url = "https://kauth.kakao.com/oauth/token"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": KAKAO_REST_API_KEY,
            "redirect_uri": redirect_uri,
            "code": code
        }
        token_response = requests.post(token_url, data=token_data)
        token_result = token_response.json()
        
        if "access_token" not in token_result:
            print("❌ 토큰 발급 실패:", token_result)
            return jsonify({'success': False, 'message': '토큰 발급 실패'}), 401
        
        kakao_token = token_result['access_token']
        print("✅ 토큰 발급 성공")
        
        # 카카오 사용자 정보 조회
        headers = {"Authorization": f"Bearer {kakao_token}"}
        response = requests.get("https://kapi.kakao.com/v2/user/me", headers=headers)
        user_info = response.json()
        
        if response.status_code != 200:
            print(f"❌ 카카오 인증 실패")
            return jsonify({'success': False, 'message': '카카오 인증 실패'}), 401
        
        kakao_id = user_info['id']
        kakao_account = user_info.get('kakao_account', {})
        
        print(f"✅ 카카오 사용자 정보 조회 성공: {kakao_id}")
        
        # 기존 회원 확인
        user_id = f'kakao_{kakao_id}'
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            # 신규 회원 생성
            user = {
                'user_id': user_id,
                'provider': 'kakao',
                'name': kakao_account.get('profile', {}).get('nickname', ''),
                'email': kakao_account.get('email', ''),
                'phone': kakao_account.get('phone_number', ''),
                'birth': None,
                'gender': None,
                'kakao_opt_in': False,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            users_collection.insert_one(user)
            print(f"✅ 신규 회원 생성: {user_id}")
        else:
            print(f"✅ 기존 회원 로그인: {user_id}")
        
        # JWT 토큰 발급
        token_payload = {
            'user_id': user['user_id'],
            'exp': datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS)
        }
        token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        print(f"✅ JWT 토큰 발급 완료")
        
        # 응답 생성
        response = make_response(jsonify({
            'success': True,
            'token': token,
            'user': {
                'user_id': user['user_id'],
                'name': user['name'],
                'has_birth_info': user['birth'] is not None
            }
        }))
        
        # 쿠키 설정 👍
        response.set_cookie(
    'access_token',
    token,
    httponly=True,
    samesite='None',
    secure=True,
    path='/',
    max_age=30*24*60*60
)
        
        return response
        
    except Exception as e:
        print(f"❌ 카카오 로그인 에러: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    

# ═══════════════════════════════════════
# 네이버 OAuth
# ═══════════════════════════════════════

@app.route('/api/auth/naver/callback', methods=['POST'])
def naver_callback():
    """네이버 로그인 콜백 - 디버깅 강화 버전"""
    try:
        data = request.json
        code = data.get('code')
        state = data.get('state')
        
        print(f"\n" + "="*60)
        print(f"✅ 네이버 로그인 시도")
        print(f"code: {code}")
        print(f"state: {state}")
        print("="*60)
        
        # 1. 네이버 액세스 토큰 요청
        token_url = "https://nid.naver.com/oauth2.0/token"
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': os.getenv('NAVER_CLIENT_ID'),
            'client_secret': os.getenv('NAVER_CLIENT_SECRET'),
            'code': code,
            'state': state
        }
        
        # 🔍 요청 내용 출력
        print(f"\n📤 네이버 API 요청:")
        print(f"URL: {token_url}")
        print(f"요청 데이터:")
        print(f"  - grant_type: {token_data['grant_type']}")
        print(f"  - client_id: {token_data['client_id']}")
        print(f"  - client_secret: {token_data['client_secret']}")
        print(f"  - code: {token_data['code']}")
        print(f"  - state: {token_data['state']}")
        
        token_response = requests.post(token_url, data=token_data)
        
        # 🔍 응답 상태 출력
        print(f"\n📥 네이버 API 응답:")
        print(f"Status Code: {token_response.status_code}")
        print(f"Headers: {dict(token_response.headers)}")
        
        # 🔍 응답 본문 출력 (JSON)
        try:
            token_result = token_response.json()
            print(f"응답 JSON: {json.dumps(token_result, indent=2, ensure_ascii=False)}")
        except:
            print(f"응답 텍스트: {token_response.text}")
            token_result = {}
        
        # 토큰 발급 실패 처리
        if 'access_token' not in token_result:
            print(f"\n❌ 네이버 토큰 발급 실패!")
            print(f"에러 코드: {token_result.get('error', '없음')}")
            print(f"에러 설명: {token_result.get('error_description', '없음')}")
            
            error_msg = token_result.get('error_description', '네이버 토큰 발급 실패')
            return jsonify({
                'success': False, 
                'message': error_msg,
                'error_detail': token_result
            }), 401
        
        access_token = token_result['access_token']
        print(f"\n✅ 네이버 액세스 토큰 발급 성공!")
        print(f"access_token: {access_token[:20]}...")
        
        # 2. 네이버 사용자 정보 조회
        profile_url = "https://openapi.naver.com/v1/nid/me"
        headers = {'Authorization': f"Bearer {access_token}"}
        
        print(f"\n📤 네이버 프로필 조회 요청:")
        print(f"URL: {profile_url}")
        print(f"Authorization: Bearer {access_token[:20]}...")
        
        profile_response = requests.get(profile_url, headers=headers)
        profile_data = profile_response.json()
        
        print(f"\n📥 네이버 프로필 응답:")
        print(f"Status Code: {profile_response.status_code}")
        print(f"응답 JSON: {json.dumps(profile_data, indent=2, ensure_ascii=False)}")
        
        if profile_data.get('resultcode') != '00':
            print(f"\n❌ 네이버 프로필 조회 실패!")
            return jsonify({
                'success': False, 
                'message': '네이버 프로필 조회 실패',
                'error_detail': profile_data
            }), 401
        
        user_info = profile_data['response']
        naver_id = user_info.get('id')
        name = user_info.get('name', '네이버 사용자')
        
        print(f"\n✅ 네이버 사용자 정보 조회 성공!")
        print(f"naver_id: {naver_id}")
        print(f"name: {name}")

        # 🆕 MongoDB에 사용자 저장
        user_id = f'naver_{naver_id}'
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            # 신규 회원 생성
            user = {
                'user_id': user_id,
                'provider': 'naver',
                'name': name,
                'email': user_info.get('email', ''),
                'phone': user_info.get('mobile', ''),
                'birth': None,
                'gender': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            users_collection.insert_one(user)
            print(f"✅ 네이버 신규 회원 생성: {user_id}")
        else:
            print(f"✅ 네이버 기존 회원 로그인: {user_id}")
        
        # 3. JWT 토큰 생성
        jwt_token = jwt.encode({
            'user_id': user_id,
            'name': name,
            'provider': 'naver',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        print(f"\n✅ JWT 토큰 생성 완료")
        print("="*60 + "\n")
        
                # 응답 생성
        response = make_response(jsonify({
            'success': True,
            'token': jwt_token,
            'user': {
                'id': naver_id,
                'name': name,
                'provider': 'naver'
            }
        }))
        
        # 쿠키 설정 🔥
        response.set_cookie(
    'access_token',
    jwt_token,
    httponly=True,
    samesite='None',
    secure=True,
    path='/',
    max_age=30*24*60*60
)
        
        return response
        
    except Exception as e:
        print(f"\n💥 네이버 로그인 오류:")
        print(f"에러 타입: {type(e).__name__}")
        print(f"에러 메시지: {str(e)}")
        import traceback
        print(f"상세 트레이스:\n{traceback.format_exc()}")
        print("="*60 + "\n")
        
        return jsonify({
            'success': False, 
            'message': str(e)
        }), 500
    # ═══════════════════════════════════════
# 테스트 로그인 (토스페이먼츠 심사용)
# ═══════════════════════════════════════
@app.route('/api/auth/test-login', methods=['POST'])
def test_login():
    """토스페이먼츠 심사용 테스트 로그인"""
    try:
        print(f"\n" + "="*60)
        print(f"🧪 테스트 계정 로그인 시도")
        print("="*60)
        
        # 테스트 유저 ID
        user_id = 'test_toss_reviewer'
        
        # DB에서 테스트 유저 확인
        user = users_collection.find_one({'user_id': user_id})
        
        if not user:
            # 테스트 유저 생성
            user = {
                'user_id': user_id,
                'provider': 'test',
                'name': '토스 심사용 테스트',
                'email': 'test@tosspayments.com',
                'phone': '010-0000-0000',
                'birth': {
                    'year': '1990',
                    'month': '01',
                    'day': '01',
                    'hour': '12',
                    'minute': '00',
                    'isLunar': False,
                    'gender': 'male'
                },
                'gender': 'male',
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            users_collection.insert_one(user)
            print(f"✅ 테스트 유저 생성: {user_id}")
        else:
            print(f"✅ 테스트 유저 로그인: {user_id}")
        
        # JWT 토큰 생성
        jwt_token = jwt.encode({
            'user_id': user_id,
            'name': '토스 심사용 테스트',
            'provider': 'test',
            'exp': datetime.utcnow() + timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        print(f"✅ JWT 토큰 생성 완료")
        print("="*60 + "\n")
        
        # 응답 생성
        response = make_response(jsonify({
            'success': True,
            'token': jwt_token,
            'user': {
                'user_id': user_id,
                'name': '토스 심사용 테스트',
                'provider': 'test',
                'has_birth_info': True
            }
        }))
        
        # 쿠키 설정
        response.set_cookie(
            'access_token',
            jwt_token,
            httponly=True,
            samesite='None',
            secure=True,
            path='/',
            max_age=30*24*60*60
        )
        
        return response
        
    except Exception as e:
        print(f"💥 테스트 로그인 오류: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ═══════════════════════════════════════
# 프로필 API
# ═══════════════════════════════════════

@app.route('/api/user/profile', methods=['GET'])
@login_required
def get_profile():
    """회원 정보 조회"""
    try:
        user = users_collection.find_one({'user_id': request.user_id})
        if not user:
            return jsonify({'success': False, 'message': '회원 정보 없음'}), 404
        
        # MongoDB ObjectId 제거
        user.pop('_id', None)
        
        print(f"✅ 프로필 조회: {request.user_id}")
        
        return jsonify({
            'success': True,
            'user': user
        })
        
    except Exception as e:
        print(f"❌ 프로필 조회 에러: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/user/profile', methods=['PUT'])
@login_required
def update_profile():
    """회원 정보 업데이트 (생년월일 입력)"""
    try:
        data = request.json
        
        # 업데이트할 정보
        update_data = {
            'birth': {
                'year': int(data.get('year')),
                'month': int(data.get('month')),
                'day': int(data.get('day')),
                'hour': int(data.get('hour')),
                'is_lunar': bool(data.get('is_lunar', False))
            },
            'gender': data.get('gender'),
            'kakao_opt_in': bool(data.get('kakao_opt_in', False)),
            'updated_at': datetime.now()
        }
        
        users_collection.update_one(
            {'user_id': request.user_id},
            {'$set': update_data}
        )
        
        print(f"✅ 프로필 업데이트: {request.user_id}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ 프로필 업데이트 에러: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ✅ 🆕 생년월일 정보 업데이트 API (MyPage용)
@app.route('/api/profile/update-birth-info', methods=['POST'])
@login_required
def update_birth_info():
    """생년월일 정보 업데이트 (MyPage.jsx 전용)"""
    try:
        data = request.json
        
        print(f"\n📝 생년월일 정보 업데이트 시도: {request.user_id}")
        print(f"받은 데이터: {data}")
        
        # 필수 필드 검증
        required_fields = ['birth_year', 'birth_month', 'birth_day', 'birth_hour', 'birth_minute', 'gender']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'{field} 필드가 누락되었습니다'
                }), 400
        
        # 값 추출 및 변환
        birth_year = int(data.get('birth_year'))
        birth_month = int(data.get('birth_month'))
        birth_day = int(data.get('birth_day'))
        birth_hour = int(data.get('birth_hour'))
        birth_minute = int(data.get('birth_minute'))
        gender = data.get('gender')
        phone = data.get('phone', '')
        
        # 범위 검증
        if not (1900 <= birth_year <= 2024):
            return jsonify({'success': False, 'message': '올바른 출생 연도를 입력해주세요 (1900-2024)'}), 400
        
        if not (1 <= birth_month <= 12):
            return jsonify({'success': False, 'message': '올바른 월을 입력해주세요 (1-12)'}), 400
        
        if not (1 <= birth_day <= 31):
            return jsonify({'success': False, 'message': '올바른 일을 입력해주세요 (1-31)'}), 400
        
        if not (0 <= birth_hour <= 23):
            return jsonify({'success': False, 'message': '올바른 시간을 입력해주세요 (0-23)'}), 400
        
        if not (0 <= birth_minute <= 59):
            return jsonify({'success': False, 'message': '올바른 분을 입력해주세요 (0-59)'}), 400
        
        if gender not in ['남자', '여자']:
            return jsonify({'success': False, 'message': '올바른 성별을 선택해주세요'}), 400
        
        # MongoDB 업데이트
        update_data = {
            'birth': {
                'year': birth_year,
                'month': birth_month,
                'day': birth_day,
                'hour': birth_hour,
                'minute': birth_minute,
                'is_lunar': False  # 기본값
            },
            'gender': gender,
            'updated_at': datetime.now()
        }
        
        if phone:
            update_data['phone'] = phone
        
        result = users_collection.update_one(
            {'user_id': request.user_id},
            {'$set': update_data}
        )
        
        if result.matched_count == 0:
            print(f"❌ 사용자를 찾을 수 없음: {request.user_id}")
            return jsonify({
                'success': False,
                'message': '사용자를 찾을 수 없습니다'
            }), 404
        
        print(f"✅ 생년월일 정보 업데이트 완료!")
        print(f"   - user_id: {request.user_id}")
        print(f"   - birth: {birth_year}/{birth_month}/{birth_day} {birth_hour}:{birth_minute}")
        print(f"   - gender: {gender}")
        
        return jsonify({
            'success': True,
            'message': '생년월일 정보가 저장되었습니다'
        })
        
    except ValueError as e:
        print(f"❌ 데이터 형식 오류: {e}")
        return jsonify({
            'success': False,
            'message': '잘못된 형식의 데이터입니다'
        }), 400
        
    except Exception as e:
        print(f"❌ 생년월일 정보 업데이트 에러: {e}")
        import traceback
        print(f"트레이스백:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': '생년월일 정보 저장에 실패했습니다'
        }), 500



# =============================================
# 사용자 정보 조회 API (MyPage용)
# =============================================

@app.route('/api/profile', methods=['GET'])
@login_required
def get_my_profile():
    """사용자 정보 조회 (MyPage.jsx에서 사용)"""
    try:
        print(f"\n📋 사용자 정보 조회: {request.user_id}")
        
        # MongoDB에서 사용자 찾기
        user = users_collection.find_one({'user_id': request.user_id})
        
        if not user:
            print(f"❌ 사용자를 찾을 수 없음: {request.user_id}")
            return jsonify({
                'success': False,
                'message': '사용자를 찾을 수 없습니다'
            }), 404
        
        # 응답 데이터 구성
        response_data = {
            'success': True,
            'user_id': user.get('user_id'),
            'email': user.get('email'),
            'name': user.get('name'),
            'provider': user.get('provider')
        }
        
        # birth 정보가 있으면 추가
        if 'birth' in user and user['birth']:
            response_data['birth'] = {
                'year': user['birth'].get('year'),
                'month': user['birth'].get('month'),
                'day': user['birth'].get('day'),
                'hour': user['birth'].get('hour'),
                'minute': user['birth'].get('minute', 0),
                'is_lunar': user['birth'].get('is_lunar', False)
            }
        
        # gender 정보가 있으면 추가
        if 'gender' in user and user['gender']:
            response_data['gender'] = user['gender']
        
        # phone 정보가 있으면 추가
        if 'phone' in user and user['phone']:
            response_data['phone'] = user['phone']
        
        print(f"✅ 사용자 정보 조회 완료: {request.user_id}")
        print(f"   - birth: {response_data.get('birth', '없음')}")
        print(f"   - gender: {response_data.get('gender', '없음')}")
        print(f"   - phone: {response_data.get('phone', '없음')}")
        
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"❌ 사용자 정보 조회 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': '사용자 정보 조회 실패'
        }), 500
    

    # ==============================================================
# 🚪 로그아웃 API
# ==============================================================
@app.route('/api/logout', methods=['POST'])
def logout():
    """로그아웃 - 쿠키 삭제"""
    try:
        print('🚪 로그아웃 시도')
        
        # 쿠키 삭제
        response = make_response(jsonify({
            'success': True,
            'message': '로그아웃 성공'
        }))
        
        # access_token 쿠키 삭제
        response.set_cookie(
    'access_token',
    '',
    max_age=0,
    httponly=True,
    samesite='None',
    secure=True,
    path='/'
)
        
        print('✅ 로그아웃 완료!')
        return response
        
    except Exception as e:
        print(f'❌ 로그아웃 실패: {str(e)}')
        return jsonify({'error': str(e)}), 500
# ====================================
# 결제 API
# ====================================

@app.route('/api/payment/initialize', methods=['POST'])
@login_required
def payment_initialize():
    """결제 준비"""
    try:
        data = request.json
        product = data.get('product')  # daily, monthly, lifetime
        
        # 금액 설정
        amounts = {
            'daily': 9900,
            'monthly': 11000,
            'lifetime': 29900
        }
        amount = amounts.get(product)
        
        if not amount:
            return jsonify({'success': False, 'message': '잘못된 상품'}), 400
        
        # 주문 ID 생성
        order_id = f"ord_{datetime.now().strftime('%Y%m%d%H%M%S')}_{request.user_id}"
        
        print(f"✅ 결제 준비: {order_id} / {product} / {amount}원")
        
        return jsonify({
            'success': True,
            'order_id': order_id,
            'amount': amount,
            'product': product,
            'client_key': TOSS_CLIENT_KEY
        })
        
    except Exception as e:
        print(f"❌ 결제 준비 에러: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/api/payment/confirm', methods=['POST'])
@login_required
def payment_confirm():
    """결제 확인"""
    try:
        data = request.json
        payment_key = data.get('paymentKey')
        order_id = data.get('orderId')
        amount = data.get('amount')
        
        # 토스페이먼츠 결제 승인
        import base64
        auth = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
        
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        }
        
        confirm_data = {
            "paymentKey": payment_key,
            "orderId": order_id,
            "amount": amount
        }
        
        response = requests.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            json=confirm_data,
            headers=headers
        )
        
        if response.status_code == 200:
            payment_info = response.json()
            
            # Payment DB 저장
            payment_doc = {
                'payment_id': payment_key,
                'user_id': request.user_id,
                'product': order_id.split('_')[2] if len(order_id.split('_')) > 2 else 'unknown',
                'amount': amount,
                'status': 'completed',
                'payment_method': payment_info.get('method'),
                'order_id': order_id,
                'payment_key': payment_key,
                'payment_date': datetime.now(),
                'refund_date': None
            }
            payments_collection.insert_one(payment_doc)
            
            print(f"✅ 결제 완료: {payment_key}")
            
            return jsonify({
                'success': True,
                'payment_id': payment_key,
                'payment_info': payment_info
            })
        else:
            error_data = response.json()
            print(f"❌ 결제 실패: {error_data}")
            return jsonify({
                'success': False,
                'message': error_data.get('message', '결제 실패')
            }), 400
            
    except Exception as e:
        print(f"❌ 결제 확인 에러: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)