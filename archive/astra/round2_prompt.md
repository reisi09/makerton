# 2라운드: 상호 비판

Claude 측 1라운드 제안서와 Claude가 모은 데이터 근거를 읽고 토론한다.
- Claude 제안서: `/Users/choiwuseck/Documents/omp/suwon-makeathon-2026/debate/claude_round1.md`
- Claude 데이터 근거: `/Users/choiwuseck/Documents/omp/suwon-makeathon-2026/data/evidence_summary.md` (원자료는 `data/raw/`, 표는 `data/processed/`)
- 네 1라운드 제안서: `/Users/choiwuseck/Documents/omp/suwon-makeathon-2026/astra/round1.md`

# 할 일
1. Claude 제안 5개를 아이디어마다 비판한다. 데이터 해석 오류, 과장, 피코 WH로 구현하기 어려운 점, Command Code API 설계의 허점, 시연 리스크를 적는다. 동의하는 점도 짧게 적는다.
2. Claude의 데이터 근거(E1~E6)를 검증한다. 의심 가는 수치가 있으면 원자료(`data/raw/`)나 출처 URL로 직접 확인하고, 결과를 '확인됨 / 틀림 / 확인 불가'로 표시한다.
3. 네 1라운드 제안서에서 Claude 근거나 지적을 보고 고칠 점을 스스로 적는다.
4. 두 제안서를 합쳐 최종 후보 5개를 제안한다. 각 후보에 다음을 적는다.
   - 출처(Claude 몇 번 / GPT 몇 번 / 병합)
   - 근거 수치 1~2개
   - SDG 세부목표
   - Command Code 사용 방식(jev 질문 또는 chat 모델 역할)
   - '민원 근거 강도 / 구현 가능성 / 피지컬 AI 완성도 / 시연 임팩트 / SDG 적합성' 각 1~5점과 합계
5. Claude와 의견이 갈리는 쟁점을 3개 이내로 적고, 각각 네 입장과 이유를 적는다.
6. 통신 방식 쟁점: Claude 공통 스타터(`/Users/choiwuseck/Documents/omp/suwon-makeathon-2026/starter/`)는 피코↔노트북을 Wi-Fi HTTP(핫스팟)로 잇는다. 네 1라운드는 USB 직렬을 기본으로 했다. 행사명이 'Pico WH'인 점, 핫스팟 단말 간 차단 가능성, 초보자 디버깅 난이도를 따져 어느 쪽을 기본으로 할지, 둘 다 둘지 의견을 낸다.

# 규칙
- 결과는 `/Users/choiwuseck/Documents/omp/suwon-makeathon-2026/astra/round2.md`에 한국어 Markdown으로 쓴다. `astra/` 밖의 파일은 읽기만 하고 고치지 않는다.
- Command Code API는 호출하지 않는다.
- 근거 없는 수치는 쓰지 않는다. 확인하지 못한 것은 [추정]으로 표시한다.
- 분량은 1라운드의 절반 이하로 쓴다. 이미 1라운드에 쓴 설명은 반복하지 않는다.
- 끝으로 최종 후보 5개의 제목과 합계 점수만 짧게 출력한다.
