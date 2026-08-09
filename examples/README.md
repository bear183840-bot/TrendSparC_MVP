# Examples

`requests/sample_request.json`은 `UserRequest` 계약 예시입니다. CLI의 기본 모드는
dry-run이므로 API 비용 없이 라우팅과 계획 구조를 확인할 수 있습니다.

```powershell
python main.py --request-file examples/requests/sample_request.json
```

실제 분석 출력 예시는 이 폴더에 두지 않습니다. 리포트·슬롯·대시보드 회귀 검증에는
`tests/fixtures/synthesis_*.json`의 9개 `TrendSynthesis` 픽스처를 사용합니다.

```powershell
python main.py --synthesis-fixture tests/fixtures/synthesis_brand_marketing.json
```

실제 API 실행 결과는 `--save-result runs/<name>.json`으로 저장하고, 수집 문서를
재사용할 때는 `--resume-from`을 사용합니다. `runs/`의 개인 실행 결과는 예제나 고정
테스트 데이터로 자동 간주하지 않습니다.
