import { useState } from 'react'
import RouteMap from './RouteMap'
import { roadDisplay } from './planValidity'

type Geometry = { coordinates: number[][] }
type Trip = {
  trip_id: string; truck_id: string; departure_at: string; arrival_at: string; return_at: string
  cargo: Record<string, number>; weight_kg: number; volume_m3: number; payload_limit_kg: number
  round_trip_distance_km: number; destination_node: string; origin_node: string
  transport_cost?: number; cost_breakdown?: Record<string, number>
  outbound_geometry?: Geometry[]; return_geometry?: Geometry[]
  timeline: { kind: string; node?: string; start_at: string; end_at: string }[]
}
const card = { background: '#fff', padding: 20, border: '1px solid #e2e8f0', borderRadius: 12, marginBottom: 20 }
const number = (n: number) => n.toLocaleString('ko-KR', { maximumFractionDigits: 1 })
const time = (s: string) => new Intl.DateTimeFormat('ko-KR', { timeZone: 'Europe/Warsaw', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(s))

export default function RoadResults({ result }: { result: any }) {
  const trips: Trip[] = result.truck_plan ?? []
  const [selected, setSelected] = useState('')
  const [phase, setPhase] = useState<'outbound' | 'return'>('outbound')
  const trip = trips.find(t=>t.trip_id===selected) ?? trips[0]
  const scenario = result.road_scenario
  const display = roadDisplay(result.model_info)
  const button = (active: boolean) => ({ border: '1px solid #cbd5e1', borderRadius: 8, padding: '6px 12px', background: active ? '#eff6ff' : '#fff', color: active ? '#1e40af' : '#64748b', cursor: 'pointer' })
  return <div style={card}>
    <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>트럭별 적재·운행 계획</div>
    <p style={{ fontSize: 12, color: '#64748b', lineHeight: 1.7, margin: '0 0 12px' }}>
      {scenario ? `${scenario.warehouse_address} → ${scenario.destination_address}` : '입력 도로망의 왕복 계획'}<br />
      총 {trips.length}회 운행 · 모든 시각은 폴란드 현지 시간 · {display.kind}
      {scenario && ` · 평균 ${scenario.transport_controls?.speed_kph ?? scenario.vehicle_preset.scenario.speed_kph}km/h 가정`}
    </p>
    {scenario && <p style={{ fontSize:12,color:'#64748b' }}>운송비는 입력한 비용 성분의 합계입니다. 기본값은 세전 거리비 참고값이며 누락된 숙박·기사·세금 등과 실제 지급 총비용은 검증되지 않았습니다. 경로 중간과 도착지의 휴식은 시나리오 가정입니다.</p>}
    {display.official && <p style={{ fontSize:12,color:'#64748b' }}>확보한 도로의 연결과 입력한 출발 후보 안에서 계산합니다. 일방통행·현장 진입·실시간 교통은 검증하지 않았습니다.{scenario?.missing_tile_count > 0 && ` 이 구간 자료에는 미확보 도로 타일 ${scenario.missing_tile_count}개가 있어 전체 도로망 최적성을 뜻하지 않습니다.`}</p>}
    {!trips.length ? <p style={{ padding: 12, background: '#f8fafc', borderRadius: 8, fontSize: 13 }}>현재 조건에서는 선택된 운행이 없습니다. 이미 보관된 재고로 충당했거나 차량·납기·조달·예산 조건 때문에 운송이 불가능할 수 있습니다. 아래 충족률과 부족량을 함께 확인해주세요.</p> : <>
      <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', minWidth: 800, borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
        <thead><tr style={{ background: '#f8fafc', color: '#64748b' }}>{['차량 / 운행','물 (L)','식량 (1일분)','위생키트 (개)','담요 (개)','적재 kg / m³','출발 · 도착 · 복귀','왕복 km'].map(label=><th key={label} style={{ padding: 10, whiteSpace: 'nowrap' }}>{label}</th>)}</tr></thead>
        <tbody>{trips.map((t,i)=><tr key={t.trip_id} style={{ borderTop: '1px solid #e2e8f0', background: t.trip_id===trip.trip_id ? '#eff6ff' : '#fff' }}>
          <td style={{ padding: 10 }}><button style={button(t.trip_id===trip.trip_id)} onClick={()=>setSelected(t.trip_id)} aria-label={`${t.truck_id} ${i+1}번째 운행 경로 보기`}>{t.truck_id}<br />운행 {i+1}</button></td>
          {['water','food','hygiene_kit','blanket'].map(item=><td key={item} style={{ padding: 10 }}>{number(t.cargo[item] ?? 0)}</td>)}
          <td style={{ padding: 10, whiteSpace: 'nowrap' }}>{number(t.weight_kg)} / {number(t.volume_m3)}</td>
          <td style={{ padding: 10, whiteSpace: 'nowrap', lineHeight: 1.8 }}>출발 {time(t.departure_at)}<br />도착 {time(t.arrival_at)}<br />복귀 {time(t.return_at)}</td>
          <td style={{ padding: 10 }}>{number(t.round_trip_distance_km)}</td>
        </tr>)}</tbody>
      </table></div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '18px 0 10px' }}>
        <strong style={{ fontSize: 13 }}>{trip.truck_id}의 선택 운행 경로</strong>
        <button style={button(phase==='outbound')} aria-pressed={phase==='outbound'} onClick={()=>setPhase('outbound')}>배송 경로</button>
        <button style={button(phase==='return')} aria-pressed={phase==='return'} onClick={()=>setPhase('return')}>복귀 경로</button>
      </div>
      <RouteMap trip={trip} phase={phase} warehouseAddress={scenario?.warehouse_address} destinationAddress={scenario?.destination_address} />
      {trip.cost_breakdown && <p style={{ fontSize:12,color:'#475569' }}>선택 운행 비용 ${number(trip.transport_cost ?? 0)} · 고정 ${number(trip.cost_breakdown.fixed)} · 거리 ${number(trip.cost_breakdown.distance)} · 시간 ${number(trip.cost_breakdown.time)} · 최소요금 보정 ${number(trip.cost_breakdown.minimum_adjustment)} · 야간 ${number(trip.cost_breakdown.overnight)} · 통행 ${number(trip.cost_breakdown.toll)}</p>}
      <p style={{ fontSize: 11, color: '#64748b', margin: '8px 0' }}>경로: {display.source} · 배경지도: OpenStreetMap · 실시간 교통은 반영하지 않습니다. {display.official ? '표시는 창고·구호소 주소 가까이 연결한 도로 끝점입니다.' : '지도는 입력 좌표를 표시하며 실제 운행 가능성을 보증하지 않습니다.'}</p>
      {trip.timeline.some(event=>event.kind==='break' || event.kind==='daily_rest') && <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.8 }}>
        {trip.timeline.filter(event=>event.kind==='break' || event.kind==='daily_rest').map((event,i)=><div key={i}>{event.kind==='daily_rest' ? '다음 근무일 복귀 전 휴식' : '기사 휴식'} · {event.node===trip.destination_node ? '도착 구호소' : event.node===trip.origin_node ? '출발 창고' : '경로상 가정 휴식 노드'} · {time(event.start_at)} ~ {time(event.end_at)}</div>)}
      </div>}
    </>}
  </div>
}
