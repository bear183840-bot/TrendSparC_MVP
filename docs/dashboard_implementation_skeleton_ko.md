# TrendSparC 대시보드 구현 뼈대

이 문서는 최종 디자인이 확정되기 전에 프론트엔드와 백엔드의 연결 지점만 정의한다. 현재 구현은 색상, 카드 배치, 차트 종류, 그리드 비율을 결정하지 않는다.

## 현재 화면이 하는 일

입력 화면은 다음 값을 받는다.

- 질문
- 첨부자료
- 청중
- 계열사/섹터 또는 자동 감지
- 실제 분석/구조 확인 선택

결과 화면은 질문과 분석 메타데이터를 표시한 뒤 `layout.blocks`를 백엔드가 준 순서대로 출력한다.

## 블록 계약

```json
{
  "block_id": "03_issue",
  "section": "issue",
  "title": "Issue",
  "block_type": "auto",
  "content": {
    "summary": "...",
    "risks": ["..."],
    "evidence": ["..."]
  },
  "data": null,
  "config": {}
}
```

- `block_id`: 화면과 인터랙션에서 사용할 안정적인 키
- `section`: 보고서의 의미 단위
- `title`: 표시 제목
- `block_type`: 표시 방법. 현재 Layout Generator는 전부 `auto`로 설정한다.
- `content`: Report Generator가 만든 구조화 문장과 목록
- `data`: 향후 표·차트·그래프 등에 필요한 별도 데이터
- `config`: 축, 열, 정렬 등 표시 설정. 디자인 확정 전에는 비어 있다.

## 수용 가능한 표시 타입

렌더러에는 다음 연결 지점만 마련되어 있다.

- `auto`: 시각화 방식을 정하지 않은 일반 구조
- `text`
- `metric`, `metrics`
- `list`
- `table`
- `chart`
- `timeline`
- `graph`
- `matrix`
- `evidence`
- `custom`

현재 `chart`, `timeline`, `graph`, `matrix`는 실제 디자인을 만들지 않고 데이터 슬롯만 보여준다. 정민님 최종 시안에서 어떤 질문과 섹션에 어떤 표현이 적합한지 결정된 뒤 전용 렌더러를 등록한다.

목록에 없는 새로운 `block_type`이 들어와도 오류를 내지 않고 `custom` fallback으로 전달한다. 따라서 최종 시안에서 새로운 컴포넌트가 생겨도 파이프라인 계약을 다시 만들 필요가 없다.

## 최종 시안 이후 연결 순서

1. 질문별 최종 대시보드 3~4개에서 반복되는 컴포넌트와 질문별 전용 컴포넌트를 구분한다.
2. 각 컴포넌트가 요구하는 실제 데이터 필드를 확인한다.
3. Layout Generator가 해당 블록에 `block_type`, `data`, `config`를 지정하도록 매핑한다.
4. Streamlit renderer에 해당 타입의 표시 함수만 등록한다.
5. 데이터가 없는 수치·담당자·기간은 임의 생성하지 않고 빈 상태로 처리한다.

## 현재 의도적으로 하지 않은 것

- 브랜드 컬러와 로고 적용
- 카드 크기와 열 배치 결정
- 섹션별 차트 종류 자동 추정
- 데이터가 없는 그래프 생성
- 경영진/실무자별 최종 시각 스타일 결정
- 정민님 시안을 가정한 임시 디자인

관련 파일:

- `reporting/dashboard_streamlit/app.py`: 입력 및 결과 화면 껍데기
- `reporting/dashboard_streamlit/renderer.py`: 블록 타입별 연결 지점과 fallback
- `core/layout_generator/generator.py`: 디자인 중립 블록 생성
- `common/contracts.py`: `DashboardBlock` 데이터 계약
