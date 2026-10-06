const ITEMS = ['water', 'food', 'hygiene_kit', 'blanket'] as const
export type LogisticsDraft = {
  enabled: boolean; fields: Record<string, string>; advanced: Record<string, unknown> | null
  mode?: 'road' | 'weekly'; warehouseId?: string; truckCount?: string
  overnightReturn?: boolean; intermediateRest?: boolean
}
export type RoadOptions = {
  warehouses: { id: string; address: string; source_url: string }[]
  preset: { label: string; source_url: string; default_warehouse_id: string; max_truck_count: number
    vehicle: { payload_kg: number; volume_m3: number }; scenario: { speed_kph: number; fixed_trip_cost: number; cost_per_km: number; cost_per_hour: number; minimum_trip_cost: number; overnight_cost: number } }
}
export const emptyLogistics = (): LogisticsDraft => ({ enabled: true, mode: 'road', fields: {}, advanced: null,
  warehouseId: 'przemysl-lwowska-36', truckCount: '1' })

// Old saved drafts have no mode and continue to use the weekly model.
export const usesRoadPlanner = (draft: LogisticsDraft) => draft.enabled && draft.mode === 'road' && !draft.advanced
export function buildRoadPlanning(draft: LogisticsDraft, referenceDate: string) {
  if (!usesRoadPlanner(draft)) return undefined
  const count = Number(draft.truckCount ?? '1')
  if (!Number.isInteger(count) || count < 1 || count > 3) throw new Error('차량 대수는 1~3대의 정수로 입력해주세요.')
  const controls: Record<string, number | boolean> = {}
  for (const key of ['speed_kph','fixed_trip_cost','cost_per_km','cost_per_hour','minimum_trip_cost','overnight_cost']) {
    const s = draft.fields[`transport_${key}`]?.trim()
    if (!s) continue
    const v = Number(s)
    if (!Number.isFinite(v) || v < 0 || (key === 'speed_kph' && (v < 30 || v > 90))) throw new Error('운송 단가를 확인해주세요. 평균 주행속도는 30~90 km/h입니다.')
    controls[key] = v
  }
  if (draft.overnightReturn !== undefined) controls.allow_overnight_return = draft.overnightReturn
  if (draft.intermediateRest !== undefined) controls.assumed_intermediate_rest = draft.intermediateRest
  return { warehouse_id: draft.warehouseId ?? 'przemysl-lwowska-36', truck_count: count, reference_date: referenceDate,
    ...(Object.keys(controls).length ? {transport_controls: controls} : {}) }
}

export function buildLogistics(draft: LogisticsDraft, site: string, inventory: Record<string, number>) {
  if (!draft.enabled) return undefined
  if (draft.advanced) {
    const network = draft.advanced.road_network as { destination_site?: string } | undefined
    const routes = draft.advanced.routes as { destination?: string }[] | undefined
    if (network ? network.destination_site !== site || routes !== undefined : !Array.isArray(routes) || routes.some(r => r.destination !== site))
      throw new Error('물류 파일 형식 또는 도착 구호소가 현재 선택과 다릅니다.')
    return draft.advanced
  }
  const n = (key: string, nullable = false) => {
    const s = draft.fields[key]?.trim() ?? ''
    if (s === '' && nullable) return null
    if (s === '' || !Number.isFinite(Number(s)) || Number(s) < 0) throw new Error('운송·기한 조건의 필수 값을 0 이상의 숫자로 입력해주세요.')
    if (key.startsWith('weight_') && Number(s) === 0) throw new Error('품목별 중량은 0보다 커야 합니다.')
    return Number(s)
  }
  const itemMap = (key: string, nullable = false) => Object.fromEntries(ITEMS.map(i => [i, n(`${key}_${i}`, nullable)]))
  const weekly = (key: string) => Object.fromEntries([1,2,3,4].map(w => [w, n(`${key}_${w}`)!]))
  const common = {
    item_weight_kg: itemMap('weight'), procurement_lead_days: itemMap('lead'), shelf_life_days: itemMap('shelf', true),
    initial_lots: ITEMS.filter(i => inventory[i] > 0).map(i => ({ id: `opening:${i}`, item: i, quantity: inventory[i], expiry_week: n(`expiry_${i}`, true) })),
    pipeline_lots: [], disposal_cost: itemMap('disposal'),
    disposal_capacity: Object.fromEntries(ITEMS.map(i => [i, Object.fromEntries([1,2,3,4].map(w => [w, n(`disposecap_${i}`)]))])),
  }
  if (draft.mode === 'road') return common
  const available = weekly('available'), slots = weekly('slots')
  const weight = n('payload')!, volume = n('volume')!
  return { ...common, vehicles: { truck: { payload_kg: weight, volume_m3: volume, available } },
    routes: [{ id: 'direct-scenario', destination: site, vehicle_type: 'truck', transit_days: n('transit'),
      round_trip_days: n('roundtrip'), trip_cost: n('tripcost'), corridor: 'local-access', corridor_delay_days: n('crossing'), allowed_items: [...ITEMS],
      max_trips: slots, max_weight_kg: Object.fromEntries([1,2,3,4].map(w => [w, slots[w]*weight])),
      max_volume_m3: Object.fromEntries([1,2,3,4].map(w => [w, slots[w]*volume])) }], corridors: { 'local-access': slots },
  }
}

export function withSyntheticItemConditions(draft: LogisticsDraft): LogisticsDraft {
  const fields = { ...draft.fields }
  for (const [item, weight, shelf] of [['water', '1.02', '365'], ['food', '0.6', '180'], ['hygiene_kit', '0.5', ''], ['blanket', '1.5', '']]) {
    Object.assign(fields, { [`weight_${item}`]: weight, [`lead_${item}`]: '0', [`shelf_${item}`]: shelf,
      [`expiry_${item}`]: shelf ? '20' : '', [`disposal_${item}`]: '0.1', [`disposecap_${item}`]: '100000' })
  }
  return { ...draft, fields }
}
