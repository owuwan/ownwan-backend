from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import random
import hashlib
from datetime import datetime

app = Flask(__name__)
CORS(app)

# 천간지지
CHEONGAN = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
JIJI = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']

# 오행
OHAENG_GAN = {
    '갑': '木', '을': '木', '병': '火', '정': '火',
    '무': '土', '기': '土', '경': '金', '신': '金',
    '임': '水', '계': '水'
}

OHAENG_JI = {
    '자': '水', '축': '土', '인': '木', '묘': '木',
    '진': '土', '사': '火', '오': '火', '미': '土',
    '신': '金', '유': '金', '술': '土', '해': '水'
}

class SajuCalculator:
    """사주 계산기"""
    
    def calculate(self, year, month, day, hour):
        # 년주
        year_gan_idx = (year - 4) % 10
        year_ji_idx = (year - 4) % 12
        year_pillar = CHEONGAN[year_gan_idx] + JIJI[year_ji_idx]
        
        # 월주
        month_ji_idx = (month + 1) % 12
        month_gan_idx = (year_gan_idx * 2 + month) % 10
        month_pillar = CHEONGAN[month_gan_idx] + JIJI[month_ji_idx]
        
        # 일주
        base_date = datetime(1900, 1, 1)
        target_date = datetime(year, month, day)
        days_diff = (target_date - base_date).days
        
        day_gan_idx = days_diff % 10
        day_ji_idx = days_diff % 12
        day_pillar = CHEONGAN[day_gan_idx] + JIJI[day_ji_idx]
        
        # 시주
        hour_ji_idx = (hour + 1) // 2 % 12
        hour_gan_idx = (day_gan_idx * 2 + hour_ji_idx) % 10
        hour_pillar = CHEONGAN[hour_gan_idx] + JIJI[hour_ji_idx]
        
        # 오행 분석
        elements = [
            OHAENG_GAN[CHEONGAN[year_gan_idx]],
            OHAENG_JI[JIJI[year_ji_idx]],
            OHAENG_GAN[CHEONGAN[month_gan_idx]],
            OHAENG_JI[JIJI[month_ji_idx]],
            OHAENG_GAN[CHEONGAN[day_gan_idx]],
            OHAENG_JI[JIJI[day_ji_idx]],
            OHAENG_GAN[CHEONGAN[hour_gan_idx]],
            OHAENG_JI[JIJI[hour_ji_idx]]
        ]
        
        element_count = {
            '木': elements.count('木'),
            '火': elements.count('火'),
            '土': elements.count('土'),
            '金': elements.count('金'),
            '水': elements.count('水')
        }
        
        return {
            'year': year_pillar,
            'month': month_pillar,
            'day': day_pillar,
            'hour': hour_pillar,
            'day_gan': CHEONGAN[day_gan_idx],
            'elements': element_count,
            'strongest': max(element_count, key=element_count.get),
            'weakest': min(element_count, key=element_count.get)
        }

def generate_lucky_numbers(date):
    random.seed(date)
    numbers = random.sample(range(1, 46), 7)
    random.seed()
    return sorted(numbers)

def get_daily_color(date):
    colors = [
        {"name": "로얄 퍼플", "hex": "#6B46C1"},
        {"name": "라벤더 골드", "hex": "#9F7AEA"},
        {"name": "트와일라잇 퍼플", "hex": "#7C3AED"}
    ]
    date_hash = int(hashlib.md5(date.encode()).hexdigest(), 16)
    return colors[date_hash % len(colors)]

def get_daily_risks(date):
    risks = ["계단", "물웅덩이", "서두름", "날카로운 물건", "차량"]
    random.seed(date)
    result = random.sample(risks, 3)
    random.seed()
    return result

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({'message': 'API 작동중!', 'status': 'ok'})

@app.route('/api/calculate', methods=['POST'])
def calculate_saju():
    try:
        data = request.json
        
        name = data.get('name')
        year = int(data.get('year'))
        month = int(data.get('month'))
        day = int(data.get('day'))
        hour = int(data.get('hour', 12))
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        calculator = SajuCalculator()
        saju_data = calculator.calculate(year, month, day, hour)
        
        fortune = {
            'total': '오늘은 안정적인 하루입니다.',
            'love': '상대방을 이해하려 노력하세요.',
            'business': '계획대로 진행될 것입니다.',
            'money': '불필요한 지출을 줄이세요.',
            'health': '규칙적인 생활이 필요합니다.',
            'relationship': '소통이 원활한 날입니다.',
            'place': '조용한 카페',
            'summary': '전체적으로 평온한 하루가 될 것입니다.'
        }
        
        lucky_numbers = generate_lucky_numbers(today)
        lucky_color = get_daily_color(today)
        risks = get_daily_risks(today)
        
        result = {
            'success': True,
            'date': today,
            'user_name': name,
            'saju': saju_data,
            'fortune': fortune,
            'lucky_numbers': lucky_numbers,
            'lucky_color': lucky_color,
            'risks': risks
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

if __name__ == '__main__':
    print("🚀 ALL DAY 사주리포트 API 서버 시작!")
    print("✅ http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)