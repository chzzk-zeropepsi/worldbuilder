"""장르 지식베이스 — 장르 선택 시 자동 로드되는 기본 통용 정보.

각 장르: cliches(기본 클리셰) / expectations(독자 기대 요소) /
conflicts(자주 쓰이는 갈등) / developments(대표 전개) / settings(설정 기본값 제안).

이 값들은 '기본값'일 뿐 — 사용자가 수정하면 사용자 값이 항상 우선한다.
AI 생성 시 참조 순위: 사용자 수정 > 프로젝트 설정 > 장르 클리셰 > 일반 지식.
"""

# 프로젝트 설정 질문(설정 생성 단계). value 타입: bool | choice | number
SETTINGS_QUESTIONS = [
    {"key": "system", "label": "시스템/상태창 존재", "type": "bool"},
    {"key": "level", "label": "레벨/등급 시스템", "type": "bool"},
    {"key": "magic", "label": "마법/초능력 존재", "type": "bool"},
    {"key": "scale", "label": "세계 규모", "type": "choice",
     "options": ["단일 도시", "단일 국가", "대륙", "전 세계", "다중 차원"]},
    {"key": "nations", "label": "주요 국가/세력 수", "type": "choice",
     "options": ["없음", "1~2", "3~5", "6 이상"]},
    {"key": "races", "label": "종족 구성", "type": "choice",
     "options": ["인간만", "소수 종족", "다종족"]},
]


GENRE_KB = {
    "판타지": {
        "cliches": ["선택받은 용사", "마왕/마족의 위협", "엘프·드워프 등 이종족", "고대 예언", "마법 학원"],
        "expectations": ["광활한 세계관", "마법 체계", "모험과 성장", "선악 대결"],
        "conflicts": ["종족 간 전쟁", "왕위 계승 다툼", "봉인된 악의 부활"],
        "developments": ["평범한 주인공의 각성", "동료 규합", "최종 결전"],
        "settings": {"magic": True, "scale": "대륙", "nations": "3~5", "races": "다종족"},
    },
    "현대판타지": {
        "cliches": ["현실에 숨겨진 이능력", "각성", "비밀 조직/협회", "이능력자 사회"],
        "expectations": ["현실+초자연 융합", "능력 성장", "정체 은닉의 긴장"],
        "conflicts": ["조직 간 암투", "일반인 세계와의 충돌", "능력 통제"],
        "developments": ["우연한 각성", "조직 입성", "숨은 진실 폭로"],
        "settings": {"magic": True, "scale": "단일 국가", "nations": "1~2", "races": "인간만"},
    },
    "무협": {
        "cliches": ["기연(우연한 비급/영약)", "문파", "정파 vs 사파", "복수", "내공/경지"],
        "expectations": ["무공 성장", "강호의 의리", "경지 돌파", "비무"],
        "conflicts": ["문파 간 분쟁", "사문의 원수", "무림 패권"],
        "developments": ["몰락 후 기연", "은원 관계", "천하제일 도전"],
        "settings": {"magic": True, "scale": "단일 국가", "nations": "3~5", "races": "인간만"},
    },
    "회귀": {
        "cliches": ["미래 기억 보유", "과거로 회귀", "비극 회피", "정보 우위"],
        "expectations": ["미래 예측", "복수", "효율적 성장", "사이다 전개"],
        "conflicts": ["과거 원흉과의 재대결", "역사 수정의 나비효과", "아는 미래와 어긋남"],
        "developments": ["약자에서 재시작", "선점/투자", "비극의 원인 제거"],
        "settings": {"system": False, "scale": "단일 국가"},
    },
    "헌터": {
        "cliches": ["게이트 발생", "각성자", "등급 시스템(E~S)", "길드", "레이드", "던전"],
        "expectations": ["성장과 강해짐", "희귀 능력/직업", "랭킹", "각성"],
        "conflicts": ["길드 분쟁", "배신", "국가 간 헌터 경쟁", "스탬피드"],
        "developments": ["최약체 시작", "히든 클래스 각성", "랭커 도약"],
        "settings": {"system": True, "level": True, "magic": True, "scale": "전 세계", "nations": "6 이상", "races": "인간만"},
    },
    "아포칼립스": {
        "cliches": ["재난 발생", "생존 경쟁", "자원 부족", "변종/좀비", "안전지대"],
        "expectations": ["긴장감", "생존과 성장", "세력전", "인간성 시험"],
        "conflicts": ["자원 쟁탈", "집단 내 분열", "변종의 위협", "약탈자"],
        "developments": ["재난 직전/직후 시작", "은신처 구축", "세력 확장"],
        "settings": {"system": False, "scale": "전 세계", "nations": "없음", "races": "인간만"},
    },
    "로맨스": {
        "cliches": ["운명적 만남", "삼각관계", "오해와 화해", "신분 차이", "계약 관계"],
        "expectations": ["감정선", "설렘", "관계 발전", "해피엔딩"],
        "conflicts": ["연적의 등장", "오해", "외부의 반대", "과거의 상처"],
        "developments": ["대립으로 시작", "가까워짐", "위기와 극복"],
        "settings": {"magic": False, "scale": "단일 도시", "races": "인간만"},
    },
    "추리": {
        "cliches": ["밀실 살인", "의외의 범인", "탐정과 조수", "알리바이 트릭", "다잉 메시지"],
        "expectations": ["논리적 단서", "반전", "공정한 추리", "진상 규명"],
        "conflicts": ["연쇄 사건", "용의자들의 거짓말", "탐정 vs 범인 두뇌전"],
        "developments": ["사건 발생", "단서 수집", "추리와 해결"],
        "settings": {"magic": False, "scale": "단일 도시", "races": "인간만"},
    },
    "SF": {
        "cliches": ["AI/로봇", "우주 항해", "외계 문명", "디스토피아 사회", "시간여행"],
        "expectations": ["과학적 설정", "사고실험", "기술과 인간", "스케일"],
        "conflicts": ["AI 반란", "자원·식민 전쟁", "기술 윤리", "외계와의 접촉"],
        "developments": ["발견/사건", "탐사", "패러다임 전환"],
        "settings": {"magic": False, "scale": "다중 차원", "nations": "6 이상", "races": "다종족"},
    },
    "스팀펑크": {
        "cliches": ["증기기관 문명", "기계장치", "발명가", "계급 사회", "비행선"],
        "expectations": ["레트로퓨처 미감", "발명과 모험", "산업과 마법의 결합"],
        "conflicts": ["계급 갈등", "신기술 패권", "산업화의 그늘"],
        "developments": ["발명/발견", "음모 연루", "체제 충돌"],
        "settings": {"magic": False, "scale": "대륙", "nations": "3~5", "races": "소수 종족"},
    },
    "군상극": {
        "cliches": ["다수 시점", "교차하는 운명", "각자의 사연", "한 사건으로 수렴"],
        "expectations": ["입체적 군상", "시점 전환의 재미", "복합 서사"],
        "conflicts": ["인물 간 이해 충돌", "진영 대립", "정보 비대칭"],
        "developments": ["여러 갈래 시작", "교차", "하나의 절정으로 수렴"],
        "settings": {"scale": "단일 국가", "nations": "3~5"},
    },
    "정치물": {
        "cliches": ["권력 암투", "파벌", "음모", "후계 다툼", "배신과 동맹"],
        "expectations": ["권모술수", "두뇌전", "세력 균형", "명분과 실리"],
        "conflicts": ["파벌 다툼", "왕위/대권 계승", "외세 개입", "내부 반란"],
        "developments": ["몰락/입성", "세력 규합", "정변/대권 장악"],
        "settings": {"magic": False, "scale": "단일 국가", "nations": "3~5", "races": "인간만"},
    },
}


def merge_settings(genres):
    """선택한 장르들의 추천 설정값을 병합(뒤 장르가 우선)."""
    merged = {}
    for g in genres:
        merged.update(GENRE_KB.get(g, {}).get("settings", {}))
    return merged


def kb_context(genres):
    """LLM 프롬프트에 넣을 장르 지식 요약 문자열."""
    lines = []
    for g in genres:
        kb = GENRE_KB.get(g)
        if not kb:
            continue
        lines.append(
            f"[{g}] 클리셰: {', '.join(kb['cliches'])} / "
            f"기대요소: {', '.join(kb['expectations'])} / "
            f"갈등: {', '.join(kb['conflicts'])}"
        )
    return "\n".join(lines)
