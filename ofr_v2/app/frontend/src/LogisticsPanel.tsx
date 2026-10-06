import type { ChangeEvent } from 'react'
import { type LogisticsDraft, type RoadOptions } from './logisticsInput'

const ITEMS = ['water', 'food', 'hygiene_kit', 'blanket'] as const
const LABELS: Record<string, string> = { water: '물 (L)', food: '식량 (1일분)', hygiene_kit: '위생키트 (개)', blanket: '담요 (개)' }
export default function LogisticsPanel({ draft, onChange, roadOptions, roadError, planningStart }: { draft: LogisticsDraft; onChange: (d: LogisticsDraft) => void; roadOptions: RoadOptions | null; roadError: string | null; planningStart: string }) {
  const roadMode = draft.mode === 'road'
  const set = (key: string, value: string) => onChange({ ...draft, fields: { ...draft.fields, [key]: value } })
  const input = (key: string, nullable = false) => <input aria-label={key} type="number" min="0" step="any" value={draft.fields[key] ?? ''}
    placeholder={nullable ? '기한 없음' : '필수'} onChange={e => set(key, e.target.value)}
    style={{ width: 95, border: '1px solid #cbd5e1', borderRadius: 6, padding: 6, background: '#f8fafc' }} />
  const row = (key: string, label: string) => <label key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>{label}{input(key)}</label>
  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const obj = JSON.parse(await file.text())
      if (!obj || Array.isArray(obj) || typeof obj !== 'object') throw new Error('물류 조건 파일은 JSON 객체여야 합니다.')
      onChange({ ...draft, enabled: true, mode: obj.road_network ? 'road' : 'weekly', advanced: obj })
    } catch (error) { alert(error instanceof Error ? error.message : '물류 조건 파일을 읽을 수 없습니다.') }
    e.target.value = ''
  }
  return <div style={{ background: 'white', padding: 20, border: '1px solid #e2e8f0', borderRadius: 12, marginBottom: 20, fontSize: 12 }}>
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontWeight: 700, fontSize: 14 }}>
      <input type="checkbox" checked={draft.enabled} onChange={e => onChange({ ...draft, enabled: e.target.checked })} /> 운송 경로·리드타임·유통기한 적용
    </label>
    <p style={{ color: '#64748b', margin: '8px 0' }}>선택한 구호소의 물품 계획과 차량 운행을 함께 계산합니다. 기존 재고는 도착 구호소에 보관된 물품으로 사용합니다.</p>
    {draft.enabled && <>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0' }}>
        {(['road', 'weekly'] as const).map(mode => <button key={mode} onClick={() => onChange({ ...draft, mode, advanced: null })}
          style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid #cbd5e1', background: (roadMode ? 'road' : 'weekly') === mode ? '#eff6ff' : '#fff', color: (roadMode ? 'road' : 'weekly') === mode ? '#1e40af' : '#64748b', fontWeight: 600 }}>
          {mode === 'road' ? '실제 도로망 · 트럭별 계획' : '기존 주별 운송 계획'}
        </button>)}
      </div>
      {roadMode && !draft.advanced && <>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
          <label style={{ flex: '1 1 300px' }}>출발 창고 후보
            <select aria-label="출발 창고 후보" value={draft.warehouseId ?? 'przemysl-lwowska-36'} onChange={e => onChange({ ...draft, warehouseId: e.target.value })}
              style={{ display: 'block', width: '100%', marginTop: 6, border: '1px solid #cbd5e1', borderRadius: 8, padding: 8, background: '#f8fafc' }}>
              {(roadOptions?.warehouses ?? []).map(w => <option key={w.id} value={w.id}>{w.address}</option>)}
            </select>
          </label>
          <label>차량 대수 (1~3대)
            <input aria-label="차량 대수" type="number" min="1" max="3" step="1" value={draft.truckCount ?? '1'} onChange={e => onChange({ ...draft, truckCount: e.target.value })}
              style={{ display: 'block', width: 100, marginTop: 6, border: '1px solid #cbd5e1', borderRadius: 8, padding: 8, background: '#f8fafc' }} />
          </label>
        </div>
        {roadError && <p role="alert" style={{ color: '#b91c1c' }}>{roadError} 기존 주별 계획은 계속 사용할 수 있습니다.</p>}
        {!roadOptions && !roadError && <p>도로·차량 설정을 불러오는 중입니다.</p>}
        {roadOptions && <div style={{ padding: 12, borderRadius: 8, background: '#f8fafc', color: '#475569', lineHeight: 1.8 }}>
          <strong>{roadOptions.preset.label}</strong> · 화물 {roadOptions.preset.vehicle.payload_kg.toLocaleString('ko-KR')} kg · {roadOptions.preset.vehicle.volume_m3} m³
          {' · '}<a href={roadOptions.preset.source_url} target="_blank" rel="noreferrer">제조사 공식 제원</a><br />
          배차 시작 {planningStart} · 폴란드 시간 · 월·목 09:00 출발 후보 · 최단거리 도로 경로<br />
          시나리오 기본값: 평균 {roadOptions.preset.scenario.speed_kph} km/h, km당 ${roadOptions.preset.scenario.cost_per_km.toFixed(3)} (세전 거리 요금 성분), 상·하차 각 30분.<br />
          <a href="https://www.pgkimlubsko.pl/cennik.html" target="_blank" rel="noreferrer">공공업체 밴 요금표</a>의 8.50 PLN/km (2025-02-03 적용)를 <a href="https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-03-16/?format=json" target="_blank" rel="noreferrer">NBP 2026-03-16 환율</a>로 환산한 참고값입니다. 실제 견적·지급액이 아니며 최신 요금 여부는 미확인입니다.
          <details style={{ marginTop: 6 }}><summary style={{ cursor: 'pointer' }}>운송 속도·비용·다음 날 복귀 조건</summary>
            <div style={{ display:'flex',gap:12,flexWrap:'wrap',margin:'8px 0' }}>{([
              ['speed_kph','평균 주행 km/h'],['fixed_trip_cost','운행 고정비 USD'],['cost_per_km','거리 USD/km'],
              ['cost_per_hour','시간 USD/h'],['minimum_trip_cost','최소 운행비 USD'],['overnight_cost','1회 숙박 추가비 USD'],
            ] as const).map(([key,label])=><label key={key}>{label}<input aria-label={label} type="number" min={key==='speed_kph' ? 30 : 0} max={key==='speed_kph' ? 90 : undefined} step="any"
              value={draft.fields[`transport_${key}`] ?? ''} placeholder={roadOptions.preset.scenario[key].toFixed(3)}
              onChange={e=>set(`transport_${key}`,e.target.value)} style={{ display:'block',width:110,padding:6,border:'1px solid #cbd5e1',borderRadius:6 }} /></label>)}</div>
            <label><input type="checkbox" checked={draft.overnightReturn ?? true} onChange={e=>onChange({...draft,overnightReturn:e.target.checked})} /> 하루에 왕복이 어려우면 도착지에서 11시간 이상 쉬고 다음 근무일 복귀</label><br />
            <label><input type="checkbox" checked={draft.intermediateRest ?? true} onChange={e=>onChange({...draft,intermediateRest:e.target.checked})} /> 경로 중간의 휴식 가능 지점 가정 적용</label>
            <p>중간 지점·도착지의 휴식은 계산용 가정이며 확인된 시설이 아닙니다. 비용은 max(최소비, 고정비+거리비+시간비)+숙박 추가비+통행료입니다. 시간비는 적재 시작~복귀 중 야간 휴식을 제외합니다. 공식 시간 요금은 별도 기준이라 자동 합산하지 않습니다. 비어 있는 추가비의 0은 계산에서 제외됨을 뜻합니다. 실제 운행 총비용에는 견적에 따른 세금·숙박·기사·기타 비용 입력이 필요합니다.</p>
          </details>
          <details style={{ marginTop: 6 }}><summary style={{ cursor: 'pointer' }}>기본 창고·차량 대수 선정 이유</summary>
            Lwowska 36은 두 후보 중 Medyka·Korczowa까지 더 짧고 Dorohusk까지의 차이는 약 0.4km입니다. 현재 운영 확정이 아닌 지리적 기준 후보입니다.
            차량 1대는 최소 운행 자원부터 비교하기 위한 기본값이며 최적 대수나 실제 보유 대수는 아닙니다.
          </details>
        </div>}
      </>}
      {!roadMode && <p style={{ color: '#92400e', background: '#fffbeb', padding: 10 }}>주 단위 보수적 계획입니다. 조달·편도 일수는 각각 7일 단위로 올림하며, 차량은 왕복기간 동안 사용 중입니다.</p>}
      <label style={{ display: 'block', marginBottom: 12 }}>상세 차량·노선·재고 배치는 조건 파일로도 불러올 수 있습니다. <input type="file" accept=".json,application/json" onChange={upload} /></label>
      {draft.advanced ? <div style={{ padding: 12, background: '#eff6ff' }}>상세 조건 파일을 사용 중입니다. 최적화 실행 시 전체 조건을 검증합니다. <button onClick={() => onChange({ ...draft, advanced: null })}>직접 입력으로 전환</button></div> : <>
        {!roadMode && <>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, margin: '12px 0' }}>
          {row('payload', '차량 1대 실제 적재중량 (kg)')}{row('volume', '차량 1대 적재부피 (m³)')}
          {row('transit', '노선 편도 운송·대기·하역 (일)')}{row('roundtrip', '차량 왕복·복귀까지 (일)')}
          {row('crossing', '출발부터 통과 구간 진입까지 (일)')}
          {row('tripcost', '출발 1회 운송비 (입력 통화)')}
        </div>
        <table style={{ width: '100%', textAlign: 'center', margin: '12px 0' }}><thead><tr><th>출발 주</th><th>가용 차량 수</th><th>노선·통과 허용 횟수</th></tr></thead><tbody>
          {[1,2,3,4].map(w => <tr key={w}><td>{w}주</td><td>{input(`available_${w}`)}</td><td>{input(`slots_${w}`)}</td></tr>)}
        </tbody></table>
        <p style={{ color: '#64748b' }}>노선 폐쇄 주에는 허용 횟수를 0으로 입력합니다. 가용 차량 수는 이미 예약된 운행을 뺀 수입니다. 폴란드 내 배송에 국경 통과 제약을 자동 적용하지 않습니다.</p>
        </>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '12px 0' }}>
          <strong>품목별 조달·재고 기한</strong>
          <span style={{ color: '#64748b' }}>품목 중량·조달·기한·폐기는 사용자 입력 또는 합성 예시값입니다.</span>
        </div>
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', textAlign: 'center' }}><thead><tr>
          <th>품목</th><th>포장 포함 kg/단위</th><th>조달 (일)</th><th>출발 때 잔여기한 (일)</th><th>현재 재고 첫 사용불가 주</th><th>폐기비/단위</th><th>주별 폐기 한도</th>
        </tr></thead><tbody>{ITEMS.map(i => <tr key={i}><td>{LABELS[i]}</td><td>{input(`weight_${i}`)}</td><td>{input(`lead_${i}`)}</td>
          <td>{input(`shelf_${i}`, true)}</td><td>{input(`expiry_${i}`, true)}</td><td>{input(`disposal_${i}`)}</td><td>{input(`disposecap_${i}`)}</td></tr>)}</tbody></table></div>
        <p style={{ color: '#64748b', marginTop: 8 }}>현재 재고량은 위에서 입력한 값을 사용합니다. 품목별 현재 재고의 기한이 모두 같다고 가정하는 입력 화면입니다. 서로 다른 기한은 상세 조건 파일의 배치별 목록으로 입력합니다. 첫 사용불가 주가 1이면 이미 사용 불가, 2이면 1주에만 사용 가능합니다. 기한이 실제로 없는 품목만 기한 칸을 비워두세요.</p>
      </>}
      <p style={{ marginTop: 12 }}>근거: <a href="https://log.logcluster.org/en/sending-goods-road" target="_blank" rel="noreferrer">WFP Logistics Cluster 운송 지침</a> · <a href="https://log.logcluster.org/en/procurement" target="_blank" rel="noreferrer">조달 지침</a> · <a href="https://log.logcluster.org/en/physical-storage-guidelines" target="_blank" rel="noreferrer">재고·기한 관리 지침</a></p>
    </>}
  </div>
}
