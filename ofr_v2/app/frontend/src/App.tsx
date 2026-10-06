import { useState, useRef, useEffect } from 'react'
import LogisticsPanel from './LogisticsPanel'
import { emptyLogistics, buildLogistics, buildRoadPlanning, usesRoadPlanner, withSyntheticItemConditions, type LogisticsDraft, type RoadOptions } from './logisticsInput'
import RoadResults from './RoadResults'
import { HISTORY_WEEKS, normalizeHistory } from './forecastInput'
import { InputRevision, hasPlanningForecast, supportedPeople } from './planValidity'
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

// ─── Date helpers ──────────────────────────────────────────────────────────────

function getMondayOfWeek(d: Date): Date {
  const date = new Date(d)
  const day = date.getDay()
  const diff = day === 0 ? -6 : 1 - day
  date.setDate(date.getDate() + diff)
  date.setHours(0, 0, 0, 0)
  return date
}

function getISOWeekNumber(date: Date): number {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7))
  const jan4 = new Date(d.getFullYear(), 0, 4)
  return 1 + Math.round(((d.getTime() - jan4.getTime()) / 86400000 - 3 + ((jan4.getDay() + 6) % 7)) / 7)
}

function fmt(date: Date): string {
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
}

function fmtShort(date: Date): string {
  return `${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

function comma(n: number): string {
  return Math.round(n).toLocaleString('ko-KR')
}

// ─── Types ─────────────────────────────────────────────────────────────────────

type SiteKey = 'medyka' | 'dorohusk' | 'korczowa'
interface ForecastInterval {
  low: number
  high: number
}
interface Accuracy {
  period: string
  wape_hub_pct: number
  naive_wape_hub_pct: number
  coverage80_pct: number
}
interface Meta {
  hubs: string[]
  first_reference: string
  last_reference: string
  accuracy: Accuracy | null
  regime_note: string
}
// ─── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000'

const NAV = [
  { id: 0, step: '01', label: '데이터 입력' },
  { id: 1, step: '02', label: '4주 수요 예측' },
  { id: 2, step: '03', label: '구호품 계획' },
  { id: 3, step: '04', label: '최적화 결과' },
]

const HUBS = [
  { name: 'Medyka', color: '#0d9488' },
  { name: 'Dorohusk', color: '#7c3aed' },
  { name: 'Korczowa', color: '#ea580c' },
]

const SITE_KEYS: SiteKey[] = ['medyka', 'dorohusk', 'korczowa']
const SITE_NAMES: Record<SiteKey, string> = { medyka: 'Medyka', dorohusk: 'Dorohusk', korczowa: 'Korczowa' }

const KO_MONTHS = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
const DAY_HEADERS = ['월','화','수','목','금','토','일']

// 기본 기준 주: 이후 4주 실제 자료가 모두 있는 마지막 주
const DEFAULT_REF_MONDAY = '2026-01-26'
const DEFAULT_FORECAST = [0, 0, 0, 0]  // 예측 전에는 값을 보여 주지 않음
const EXAMPLE_INFLOW = { medyka: ['2000', '1800'], dorohusk: ['1600', '1450'], korczowa: ['1350', '1200'] }
const EXAMPLE_CONFLICT = { events: '1000', deaths: '100' } // 시연용 가상 주간 합계

const SOURCE_LABELS: Record<string, string> = {
  example: '시연용 예시 유입량·분쟁 정보로 생성한 모델 예측 · 실제 운영값 아님',
  relief_model: '새 팀원 예측모델 · 입력한 유입량과 기준 주 분쟁 정보를 반영한 예측',
  relief_model_edited: '새 팀원 예측모델 · 원자료와 다른 수정 입력을 반영한 예측',
  backtest: '회고 모드 · 이 기준 주까지의 데이터로만 학습한 모델의 예측(표본 외)',
  final_model: '전체 데이터로 학습한 모델 · 이 기간은 학습에 포함되어 참고용',
  what_if: '입력을 수정한 가정 시나리오',
  manual: '수동 수요 시나리오 · 수정한 주간 총량을 기존 구호소별 비율로 배분한 값',
}

// 합성 예시(실제 운영값 아님)
const SYNTH_INVENTORY: Record<SiteKey, { water: string; food: string; hygiene: string; blanket: string }> = {
  medyka: { water: '12000', food: '800', hygiene: '150', blanket: '180' },
  korczowa: { water: '7000', food: '450', hygiene: '100', blanket: '120' },
  dorohusk: { water: '5000', food: '350', hygiene: '80', blanket: '100' },
}
const SYNTH_SUPPLY = {
  water: ['18000', '18000', '16000', '16000'],
  food: ['1200', '1200', '1000', '1000'],
  hygiene: ['350', '350', '300', '300'],
  blanket: ['400', '400', '350', '350'],
}
const SYNTH_PRICES = { water: '1', food: '10', hygiene: '25', blanket: '30' }
const SYNTH_BUDGET = '110000'
const SYNTH_WAREHOUSE: Record<SiteKey, string> = { medyka: '45', korczowa: '30', dorohusk: '25' }
const SYNTH_VOLUMES = { water: '0.001', food: '0.002', hygiene: '0.010', blanket: '0.020' }

function emptyHubInflow(): Record<SiteKey, string[]> {
  return normalizeHistory(null)
}

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function parseYmd(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (body?.detail) return JSON.stringify(body.detail)
  } catch {
    // ignore
  }
  return fallback
}

// ─── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [activeNav, setActiveNav] = useState(0)
  const mainRef = useRef<HTMLElement | null>(null)
  useEffect(() => { mainRef.current?.scrollTo({ top: 0, left: 0 }) }, [activeNav])
  const [isPredicting, setIsPredicting] = useState(false)
  const today = useRef(new Date()).current
  const [refMonday, setRefMonday] = useState<Date>(() => parseYmd(DEFAULT_REF_MONDAY))
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaError, setMetaError] = useState(false)

  // ── Step 01 state ──
  const [calOpen, setCalOpen] = useState(false)
  const [calYear, setCalYear] = useState(today.getFullYear())
  const [calMonth, setCalMonth] = useState(today.getMonth())
  const [hoverDay, setHoverDay] = useState<Date | null>(null)
  const calRef = useRef<HTMLDivElement>(null)
  // 구호소별 최근 2주 유입량 (index 0 = 기준 주)
  const [hubInflow, setHubInflow] = useState<Record<SiteKey, string[]>>(emptyHubInflow)
  const [hubInflowOriginal, setHubInflowOriginal] = useState<Record<SiteKey, string[]> | null>(null)
  const [hubInflowRef, setHubInflowRef] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [inflowExampleActive, setInflowExampleActive] = useState(false)
  const [conflictInput, setConflictInput] = useState({ events: '', deaths: '' })

  // ── Step 02 state ──
  const [forecastValues, setForecastValues] = useState<number[]>(DEFAULT_FORECAST)
  const [forecastIntervals, setForecastIntervals] =
  useState<(ForecastInterval | null)[]>([
    null,
    null,
    null,
    null,
  ])

  const [hubForecast, setHubForecast] = useState<Record<SiteKey, number[]>>({
  medyka: [0, 0, 0, 0],
  dorohusk: [0, 0, 0, 0],
  korczowa: [0, 0, 0, 0],
})
  const [hubIntervals, setHubIntervals] = useState<Record<SiteKey, (ForecastInterval | null)[]> | null>(null)
  const [hubActual, setHubActual] = useState<Record<SiteKey, (number | null)[]> | null>(null)
  const [predictionSource, setPredictionSource] = useState<string | null>(null)
  const [predictionWarning, setPredictionWarning] = useState<string | null>(null)
  const [accuracy, setAccuracy] = useState<Accuracy | null>(null)
  const [editingWeek, setEditingWeek] = useState<number | null>(null)
  const [editTemp, setEditTemp] = useState('')
  const [utilRate, setUtilRate] = useState<number>(10)
  const [stayDuration, setStayDuration] = useState(3)

  // ── Step 03 state ──
  const [budget, setBudget] = useState('')
  const [priority, setPriority] = useState<'fairness' | 'efficiency'>('fairness')

  // ── Step 03 new state (API-ready) ──
  const [selectedSite, setSelectedSite] = useState<SiteKey>('medyka')
  const [logisticsDrafts, setLogisticsDrafts] = useState<Record<SiteKey, LogisticsDraft>>(() => ({ medyka: emptyLogistics(), dorohusk: emptyLogistics(), korczowa: emptyLogistics() }))
  const [optimizationResult, setOptimizationResult] = useState<any>(null)
  const [isOptimizing, setIsOptimizing] = useState(false)
  const [roadOptions, setRoadOptions] = useState<RoadOptions | null>(null)
  const [roadError, setRoadError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/road-options`).then(async response => {
      if (!response.ok) throw new Error('도로 설정을 불러오지 못했습니다. 서버를 확인하고 새로고침해주세요.')
      const data = await response.json()
      if (!cancelled) setRoadOptions(data)
    }).catch(error => { if (!cancelled) setRoadError(String(error.message)) })
    return () => { cancelled = true }
  }, [])
  const [initialInventory, setInitialInventory] = useState({
    medyka: { water: '', food: '', blanket: '', hygiene: '' },
    dorohusk: { water: '', food: '', blanket: '', hygiene: '' },
    korczowa: { water: '', food: '', blanket: '', hygiene: '' },
  })
  const [weeklySupplyLimits, setWeeklySupplyLimits] = useState(
    Array.from({ length: 4 }, () => ({ water: '', food: '', blanket: '', hygiene: '' }))
  )
  const [itemPrices, setItemPrices] = useState({ water: '', food: '', blanket: '', hygiene: '' })
  const [itemVolumes, setItemVolumes] = useState({ water: '', food: '', blanket: '', hygiene: '' })
  const [warehouseCapacities, setWarehouseCapacities] = useState({ medyka: '', dorohusk: '', korczowa: '' })

  // ── Step 04 state ──
  const [resultWeek, setResultWeek] = useState(0)

  const [storageLoaded, setStorageLoaded] = useState(false)

  const inputGate = useRef(new InputRevision())
  const inputRevision = inputGate.current.update(JSON.stringify({
    reference: ymd(refMonday), hubInflow, conflictInput, hubForecast, predictionSource,
    selectedSite, utilRate, stayDuration, budget, priority, initialInventory,
    weeklySupplyLimits, itemPrices, itemVolumes, warehouseCapacities, logisticsDrafts,
  }))
  const forecastRequestGate = useRef(new InputRevision())
  const forecastRevision = forecastRequestGate.current.update(JSON.stringify([ymd(refMonday), hubInflow, conflictInput, inflowExampleActive]))
  useEffect(() => { setOptimizationResult(null) }, [inputRevision])

const STORAGE_KEY = 'poland-relief-planner-data-v2'

// 저장된 데이터 불러오기
useEffect(() => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)

    if (saved) {
      const data = JSON.parse(saved)

      if (data.activeNav !== undefined) {
        setActiveNav(data.activeNav === 3 ? 2 : data.activeNav)
      }

      if (data.refMonday) {
        const d = new Date(data.refMonday)
        if (!isNaN(d.getTime())) setRefMonday(getMondayOfWeek(d))
      }

      if (data.hubInflow) {
        setHubInflow(normalizeHistory(data.hubInflow))
      }

      if (data.hubInflowOriginal) {
        setHubInflowOriginal(normalizeHistory(data.hubInflowOriginal))
      }

      if (data.hubInflowRef) {
        setHubInflowRef(data.hubInflowRef)
      }
      setInflowExampleActive(data.inflowExampleActive === true)
      if (data.conflictInput) {
        setConflictInput({ events: String(data.conflictInput.events ?? ''), deaths: String(data.conflictInput.deaths ?? '') })
      }

      // Keep actual inputs; recompute forecasts after reload/model replacement.
      if (data.utilRate !== undefined) {
        setUtilRate(data.utilRate)
      }

      if (data.stayDuration !== undefined) {
        setStayDuration(data.stayDuration)
      }

      if (data.selectedSite) {
        setSelectedSite(data.selectedSite)
      }
      if (data.logisticsDrafts) setLogisticsDrafts(data.logisticsDrafts)

      if (data.initialInventory) {
        setInitialInventory(data.initialInventory)
      }

      if (data.weeklySupplyLimits) {
        setWeeklySupplyLimits(data.weeklySupplyLimits)
      }

      if (data.itemPrices) {
        setItemPrices(data.itemPrices)
      }

      if (data.itemVolumes) {
        setItemVolumes(data.itemVolumes)
      }

      if (data.warehouseCapacities) {
        setWarehouseCapacities(data.warehouseCapacities)
      }

      if (data.budget !== undefined) {
        setBudget(data.budget)
      }

      if (data.priority === 'fairness' || data.priority === 'efficiency') {
        setPriority(data.priority)
      }

      // Persist inputs only: a past result has no verified link to current inputs/code.

      if (data.resultWeek !== undefined) {
        setResultWeek(data.resultWeek)
      }
    }
  } catch (error) {
    console.error('저장 데이터 불러오기 실패:', error)
  }

  setStorageLoaded(true)
}, [])

useEffect(() => {
  if (!storageLoaded) return

  const dataToSave = {
    // Large road geometry stays in memory; persist inputs and return to planning after reload.
    activeNav: activeNav === 3 ? 2 : activeNav,
    refMonday: refMonday.toISOString(),

    hubInflow: normalizeHistory(hubInflow),
    hubInflowOriginal: hubInflowOriginal ? normalizeHistory(hubInflowOriginal) : null,
    hubInflowRef,
    inflowExampleActive,
    conflictInput,

    forecastValues,
    forecastIntervals,
    hubForecast,
    hubIntervals,
    hubActual,
    predictionSource,
    predictionWarning,
    utilRate,
    stayDuration,

    selectedSite,
    logisticsDrafts,
    initialInventory,
    weeklySupplyLimits,
    itemPrices,
    itemVolumes,
    warehouseCapacities,
    budget,
    priority,

    optimizationResult: null,
    resultWeek,
  }

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dataToSave))
  } catch (error) {
    // Full storage or a large uploaded graph must not crash the current plan.
    console.warn('브라우저 입력 저장 실패: 현재 화면은 계속 사용할 수 있습니다.', error)
  }
}, [
  storageLoaded,
  activeNav,
  refMonday,
  hubInflow,
  hubInflowOriginal,
  hubInflowRef,
  inflowExampleActive,
  conflictInput,
  forecastValues,
  forecastIntervals,
  hubForecast,
  hubIntervals,
  hubActual,
  predictionSource,
  predictionWarning,
  utilRate,
  stayDuration,
  selectedSite,
  logisticsDrafts,
  initialInventory,
  weeklySupplyLimits,
  itemPrices,
  itemVolumes,
  warehouseCapacities,
  budget,
  priority,
  optimizationResult,
  resultWeek,
])

// 데이터 범위(/meta) 불러오기
useEffect(() => {
  let cancelled = false
  fetch(`${API_BASE}/meta`)
    .then(res => {
      if (!res.ok) throw new Error('meta 요청 실패')
      return res.json()
    })
    .then((data: Meta) => {
      if (!cancelled) setMeta(data)
    })
    .catch(error => {
      console.error(error)
      if (!cancelled) setMetaError(true)
    })
  return () => { cancelled = true }
}, [])

const firstRef = meta ? parseYmd(meta.first_reference) : null
const lastRef = meta ? parseYmd(meta.last_reference) : null

function isRefWeekAllowed(mon: Date): boolean {
  if (!firstRef || !lastRef) return true
  return mon >= firstRef && mon <= lastRef
}

// 저장된 기준 주가 데이터 범위를 벗어나면 기본 기준 주로 되돌림
useEffect(() => {
  if (!storageLoaded || !meta) return
  if (!isRefWeekAllowed(refMonday)) {
    clearPrediction()
    setConflictInput({ events: '', deaths: '' })
    setRefMonday(parseYmd(DEFAULT_REF_MONDAY))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [storageLoaded, meta, refMonday])

function clearPrediction() {
  setForecastValues(DEFAULT_FORECAST)
  setForecastIntervals([null, null, null, null])
  setHubForecast({ medyka: [0, 0, 0, 0], dorohusk: [0, 0, 0, 0], korczowa: [0, 0, 0, 0] })
  setHubIntervals(null)
  setHubActual(null)
  setPredictionSource(null)
  setPredictionWarning(null)
  setOptimizationResult(null)
}

// 기준 주가 바뀌면 구호소별 최근 2주 유입량을 원자료에서 불러옴
useEffect(() => {
  if (!storageLoaded || !meta) return
  if (!isRefWeekAllowed(refMonday)) return
  const refKey = ymd(refMonday)
  if (inflowExampleActive && hubInflowRef === refKey) return
  // 같은 기준 주의 저장된 입력(수정 포함)은 유지
  if (hubInflowRef === refKey && hubInflowOriginal) return

  let cancelled = false
  setHistoryLoading(true)
  setHistoryError(null)
  fetch(`${API_BASE}/history?reference_date=${refKey}`)
    .then(async res => {
      if (!res.ok) throw new Error(await readErrorDetail(res, '유입량 원자료를 불러오지 못했습니다.'))
      return res.json()
    })
    .then(data => {
      if (cancelled) return
      const loaded = emptyHubInflow()
      for (const hub of SITE_KEYS) {
        const values: (number | null)[] = data.hub_inflow?.[hub] ?? []
        loaded[hub] = Array.from({ length: HISTORY_WEEKS }, (_, i) => {
          const v = values[i]
          return v === null || v === undefined ? '' : String(Math.round(Number(v)))
        })
      }
      setHubInflow(loaded)
      setHubInflowOriginal(loaded)
      setHubInflowRef(refKey)
      setHistoryError(data.warning ?? null)
      // 다른 기준 주의 예측·최적화 결과가 남아 실제값과 섞이지 않도록 비움
      clearPrediction()
    })
    .catch(error => {
      console.error(error)
      if (!cancelled) setHistoryError(error instanceof Error ? error.message : '유입량 원자료를 불러오지 못했습니다.')
    })
    .finally(() => {
      if (!cancelled) setHistoryLoading(false)
    })
  return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [storageLoaded, meta, refMonday, inflowExampleActive])

  // Close calendar on outside click
  useEffect(() => {
    if (!calOpen) return
    function onDown(e: MouseEvent) {
      if (calRef.current && !calRef.current.contains(e.target as Node)) {
        setCalOpen(false); setHoverDay(null)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [calOpen])

  // ── Step 01 helpers ──
  function buildDays(y: number, m: number): Date[] {
    const first = new Date(y, m, 1)
    const mon = getMondayOfWeek(first)
    const days: Date[] = []
    let d = new Date(mon)
    while (days.length < 42) {
      days.push(new Date(d))
      d.setDate(d.getDate() + 1)
      if (days.length >= 28 && d.getMonth() !== m && days.length % 7 === 0) break
    }
    return days
  }
  function inRefWeek(d: Date): boolean {
    const mon = getMondayOfWeek(refMonday)
    return d >= mon && d <= addDays(mon, 6)
  }
  function inHoverWeek(d: Date): boolean {
    if (!hoverDay) return false
    const mon = getMondayOfWeek(hoverDay)
    return d >= mon && d <= addDays(mon, 6)
  }
  function selectDay(d: Date) {
    const mon = getMondayOfWeek(d)
    if (!isRefWeekAllowed(mon)) return
    clearPrediction()
    setInflowExampleActive(false)
    setConflictInput({ events: '', deaths: '' })
    setRefMonday(mon); setCalOpen(false); setHoverDay(null)
  }
  function prevMo() { if (calMonth === 0) { setCalYear(y => y - 1); setCalMonth(11) } else setCalMonth(m => m - 1) }
  function nextMo() { if (calMonth === 11) { setCalYear(y => y + 1); setCalMonth(0) } else setCalMonth(m => m + 1) }
  function toggleCal() {
    if (!calOpen) { setCalYear(refMonday.getFullYear()); setCalMonth(refMonday.getMonth()) }
    setCalOpen(v => !v)
  }
  function updateHubInflow(hub: SiteKey, idx: number, val: string) {
    clearPrediction()
    setHubInflow(prev => ({ ...prev, [hub]: prev[hub].map((v, i) => i === idx ? val : v) }))
  }
  function fillInflowExample() {
    clearPrediction()
    setRefMonday(parseYmd(DEFAULT_REF_MONDAY))
    setHubInflow(normalizeHistory(EXAMPLE_INFLOW))
    setHubInflowOriginal(null)
    setHubInflowRef(DEFAULT_REF_MONDAY)
    setInflowExampleActive(true)
    setConflictInput({ ...EXAMPLE_CONFLICT })
    setHistoryLoading(false)
    setHistoryError(null)
    setCalOpen(false)
    setUtilRate(10)
    setStayDuration(3)
  }
  function handleRestoreOriginal() {
    if (inflowExampleActive) { clearPrediction(); setConflictInput({ events: '', deaths: '' }); setHistoryLoading(true); setInflowExampleActive(false); return }
    if (hubInflowOriginal) { clearPrediction(); setHubInflow(hubInflowOriginal) }
  }
async function runPrediction() {
  const requestRevision = forecastRevision
  try {
    if (SITE_KEYS.some(hub => hubInflow[hub].some(v => v.trim() === ''))) {
      alert('구호소별 최근 2주 유입량을 모두 입력해주세요.')
      return
    }
    if (!isConflictReady) {
      alert('기준 주 분쟁 사건 수와 사망자 수를 0 이상의 정수로 모두 입력해주세요.')
      return
    }

    setIsPredicting(true)

    const response = await fetch(
      `${API_BASE}/predict`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          reference_date: ymd(refMonday),
          hub_inflow: {
            medyka: hubInflow.medyka.slice(0,HISTORY_WEEKS).map(Number),
            dorohusk: hubInflow.dorohusk.slice(0,HISTORY_WEEKS).map(Number),
            korczowa: hubInflow.korczowa.slice(0,HISTORY_WEEKS).map(Number),
          },
          conflict: [{ events: Number(conflictInput.events), deaths: Number(conflictInput.deaths) }],
        }),
      }
    )

    if (!response.ok) {
      const detail = await readErrorDetail(response, '예측 요청 실패')
      alert(`모델 예측 중 오류가 발생했습니다.\n${detail}`)
      return
    }

    const data = await response.json()
    if (!forecastRequestGate.current.isCurrent(requestRevision)) return

    const newForecast = [
      Number(data.week1),
      Number(data.week2),
      Number(data.week3),
      Number(data.week4),
    ]

    const toInterval = (interval: any): ForecastInterval | null => {
      if (!interval) return null

      const low = Number(interval.low)
      const high = Number(interval.high)

      if (
        !Number.isFinite(low) ||
        !Number.isFinite(high)
      ) {
        return null
      }

      return {
        low,
        high,
      }
    }

setHubForecast({
  medyka: data.hub_forecast?.medyka ?? [0, 0, 0, 0],
  dorohusk: data.hub_forecast?.dorohusk ?? [0, 0, 0, 0],
  korczowa: data.hub_forecast?.korczowa ?? [0, 0, 0, 0],
})

    const newHubIntervals = {} as Record<SiteKey, (ForecastInterval | null)[]>
    for (const hub of SITE_KEYS) {
      newHubIntervals[hub] = Array.from({ length: 4 }, (_, i) => toInterval(data.hub_intervals?.[hub]?.[i]))
    }
    setHubIntervals(newHubIntervals)

    if (data.hub_actual && !inflowExampleActive) {
      const newHubActual = {} as Record<SiteKey, (number | null)[]>
      for (const hub of SITE_KEYS) {
        newHubActual[hub] = Array.from({ length: 4 }, (_, i) => {
          const v = data.hub_actual?.[hub]?.[i]
          return v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v)
        })
      }
      setHubActual(newHubActual)
    } else {
      setHubActual(null)
    }

    setPredictionSource(inflowExampleActive ? 'example' : data.source ?? null)
    setPredictionWarning(data.warning ?? null)
    setAccuracy(data.accuracy ?? null)

const newIntervals: (ForecastInterval | null)[] =
  Array.from({ length: 4 }, (_, i) => toInterval(data.intervals?.[i]))

setForecastValues(newForecast)
setForecastIntervals(newIntervals)

setActiveNav(1)

 } catch (error) {
  console.error(error)
  alert('모델 예측 중 오류가 발생했습니다. Python 서버를 확인해주세요.')
} finally {
  setIsPredicting(false)
}
}

async function runOptimization() {
  if (isOptimizing) return
  const requestRevision = inputRevision
  setOptimizationResult(null)
  setIsOptimizing(true)
  try {
    if (usesRoadPlanner(logisticsDrafts[selectedSite]) && !roadOptions) throw new Error(roadError ?? '도로 설정을 불러오는 중입니다.')
    const apiSite = SITE_NAMES[selectedSite]
    const forecast = hubForecast[selectedSite]
    const inventory = initialInventory[selectedSite]

    if (!hasPlanningForecast(predictionSource, forecast)) {
      alert('먼저 STEP 01에서 4주 유입량 예측을 실행해주세요.')
      return
    }

    const requiredValues = [
      inventory.water,
      inventory.food,
      inventory.blanket,
      inventory.hygiene,

      ...weeklySupplyLimits.flatMap(w => [
        w.water,
        w.food,
        w.blanket,
        w.hygiene,
      ]),

      itemPrices.water,
      itemPrices.food,
      itemPrices.blanket,
      itemPrices.hygiene,

      itemVolumes.water,
      itemVolumes.food,
      itemVolumes.blanket,
      itemVolumes.hygiene,

      warehouseCapacities[selectedSite],
      budget,
    ]

    if (requiredValues.some(v => String(v).trim() === '')) {
      alert('최적화에 필요한 값을 모두 입력해주세요.')
      return
    }

    const requestBody = {
      ml_forecast: {
        [apiSite]: {
          1: Number(forecast[0]),
          2: Number(forecast[1]),
          3: Number(forecast[2]),
          4: Number(forecast[3]),
        },
      },

      selected_site: apiSite,

      utilization_rate: utilRate / 100,
      stay_days: stayDuration,

      initial_inventory: {
        [apiSite]: {
          water: Number(inventory.water),
          food: Number(inventory.food),
          hygiene_kit: Number(inventory.hygiene),
          blanket: Number(inventory.blanket),
        },
      },

      weekly_supply: {
        water: {
          1: Number(weeklySupplyLimits[0].water),
          2: Number(weeklySupplyLimits[1].water),
          3: Number(weeklySupplyLimits[2].water),
          4: Number(weeklySupplyLimits[3].water),
        },

        food: {
          1: Number(weeklySupplyLimits[0].food),
          2: Number(weeklySupplyLimits[1].food),
          3: Number(weeklySupplyLimits[2].food),
          4: Number(weeklySupplyLimits[3].food),
        },

        hygiene_kit: {
          1: Number(weeklySupplyLimits[0].hygiene),
          2: Number(weeklySupplyLimits[1].hygiene),
          3: Number(weeklySupplyLimits[2].hygiene),
          4: Number(weeklySupplyLimits[3].hygiene),
        },

        blanket: {
          1: Number(weeklySupplyLimits[0].blanket),
          2: Number(weeklySupplyLimits[1].blanket),
          3: Number(weeklySupplyLimits[2].blanket),
          4: Number(weeklySupplyLimits[3].blanket),
        },
      },

      unit_cost: {
        water: Number(itemPrices.water),
        food: Number(itemPrices.food),
        hygiene_kit: Number(itemPrices.hygiene),
        blanket: Number(itemPrices.blanket),
      },

      total_budget: Number(budget),

      warehouse_capacity_m3: {
        [apiSite]: Number(warehouseCapacities[selectedSite]),
      },

      item_volume_m3: {
        water: Number(itemVolumes.water),
        food: Number(itemVolumes.food),
        hygiene_kit: Number(itemVolumes.hygiene),
        blanket: Number(itemVolumes.blanket),
      },

      priority,
      road_planning: buildRoadPlanning(logisticsDrafts[selectedSite], ymd(refMonday)),
      logistics: buildLogistics(logisticsDrafts[selectedSite], apiSite, {
        water: Number(inventory.water), food: Number(inventory.food),
        hygiene_kit: Number(inventory.hygiene), blanket: Number(inventory.blanket),
      }),
    }

    console.log('최적화 요청값:', requestBody)

    const response = await fetch(
      `${API_BASE}/optimize`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      }
    )

    if (!response.ok) {
      const detail = await readErrorDetail(response, '최적화 요청 실패')
      console.error('최적화 서버 오류:', detail)
      alert(`최적화 실행 중 오류가 발생했습니다.\n${detail}`)
      return
    }

    const result = await response.json()

    console.log('실제 최적화 결과:', result)

   if (!inputGate.current.isCurrent(requestRevision)) {
     alert('계산 중 입력이 변경되어 이전 결과를 표시하지 않았습니다. 현재 조건으로 다시 실행해주세요.')
     return
   }
   setOptimizationResult({ ...result, _uiRevision: requestRevision })
   setResultWeek(0)
   setActiveNav(3)

  } catch (error) {
    console.error(error)

    alert(
      error instanceof Error ? error.message : '최적화 실행 중 오류가 발생했습니다.'
    )
  } finally {
    setIsOptimizing(false)
  }
}
  const inflowCells = SITE_KEYS.flatMap(hub => hubInflow[hub])
  const conflictCells = Object.values(conflictInput)
  const isConflictReady = conflictCells.every(v => v.trim() !== '' && Number.isInteger(Number(v)) && Number(v) >= 0)
  const totalMissing = [...inflowCells, ...conflictCells].filter(v => v.trim() === '').length
  const outlierCount = inflowCells.filter(v => v.trim() !== '' && (!Number.isFinite(Number(v)) || Number(v) < 0 || Number(v) > 500000)).length
    + conflictCells.filter(v => v.trim() !== '' && (!Number.isInteger(Number(v)) || Number(v) < 0)).length
  const isReady = totalMissing === 0 && outlierCount === 0 && !historyLoading
  const isInflowEdited = inflowExampleActive || hubInflowOriginal !== null &&
    SITE_KEYS.some(hub => hubInflow[hub].some((v, i) => v !== (hubInflowOriginal[hub]?.[i] ?? '')))

  const weekNum = getISOWeekNumber(refMonday)
  const weekEnd = addDays(refMonday, 6)
  const calDays = buildDays(calYear, calMonth)

  // ── Step 02 helpers ──
  const effectiveUtil = utilRate
  const forecastStart = addDays(refMonday, 7) // 1주차 starts the week after reference
  const shownAccuracy = predictionSource === 'manual' ? null : accuracy ?? meta?.accuracy ?? null

  // 구호소 3곳 합계 (index 0 = 기준 주), 입력이 비어 있으면 null
  const historyTotals = Array.from({ length: HISTORY_WEEKS }, (_, i) => {
    const vals = SITE_KEYS.map(hub => hubInflow[hub][i] ?? '')
    return vals.some(v => v.trim() === '') ? null : vals.reduce((a, v) => a + Number(v), 0)
  })

  // 예측 주별 실제 합계 (3개 구호소 모두 값이 있을 때만)
  const actualTotals = Array.from({ length: 4 }, (_, i) => {
    if (!hubActual) return null
    const vals = SITE_KEYS.map(hub => hubActual[hub]?.[i] ?? null)
    return vals.some(v => v === null) ? null : vals.reduce((a: number, v) => a + (v as number), 0)
  })
  const hasActual = actualTotals.some(v => v !== null)

  // Chart data: 8 historical + 4 forecast (connecting at boundary)
  const historicalVals = [...historyTotals].reverse() // oldest first

  const chartData = [
    // 2 historical points (oldest to newest)
    ...historicalVals.map((v, i) => {
      return {
  label: i === HISTORY_WEEKS - 1 ? '기준 주' : `${HISTORY_WEEKS - 1 - i}주 전`,
  actual: v,
  forecast: i === HISTORY_WEEKS - 1 ? v : null,
  observed: i === HISTORY_WEEKS - 1 && hasActual && actualTotals[0] !== null ? v : null,
  interval: null,
  isHistory: true,
}
    }),
    // 4 forecast points
    ...forecastValues.map((v, i) => {
  const interval = forecastIntervals[i]

  return {
    label: `${i + 1}주 후`,
    actual: null,
    forecast: v,
    observed: actualTotals[i],
    interval: interval
      ? [interval.low, interval.high]
      : null,
    isHistory: false,
  }
}),
  ]
  // The boundary: index 1 has both actual and forecast

  function startEdit(i: number) {
    setEditingWeek(i)
    setEditTemp(String(forecastValues[i]))
  }
  function confirmEdit(i: number) {
  const v = parseFloat(editTemp)

  if (Number.isFinite(v) && v >= 0) {
    setPredictionSource('manual')
    const newTotal = Math.round(v)

    setForecastValues(prev =>
      prev.map((x, j) =>
        j === i ? newTotal : x
      )
    )

    setForecastIntervals(prev =>
      prev.map((interval, j) =>
        j === i ? null : interval
      )
    )

    // 구호소별 예측도 같은 비율로 조정 (최적화에 수정값 반영)
    setHubForecast(prev => {
      const hubSum = SITE_KEYS.reduce((a, hub) => a + Number(prev[hub][i] ?? 0), 0)
      const next = { ...prev }
      for (const hub of SITE_KEYS) {
        const share = hubSum > 0 ? Number(prev[hub][i] ?? 0) / hubSum : 1 / SITE_KEYS.length
        next[hub] = prev[hub].map((x, j) => j === i ? newTotal * share : x)
      }
      return next
    })

    setHubIntervals(prev => {
      if (!prev) return prev
      const next = { ...prev }
      for (const hub of SITE_KEYS) {
        next[hub] = prev[hub].map((interval, j) => j === i ? null : interval)
      }
      return next
    })
  }

  setEditingWeek(null)
}

  // Weekly demand calculations
  function weekDemand(forecastVal: number) {
    const shelterUsers = supportedPeople(forecastVal, effectiveUtil)
    const personDays = shelterUsers * stayDuration
    // peakOccupancy: avg daily occupancy, kept for Steps 03/04
    const peakOccupancy = personDays / 7
    return { shelterUsers, personDays, peakOccupancy }
  }

  const totalForecast = forecastValues.reduce((a, b) => a + b, 0)
  const week1Demand = weekDemand(forecastValues[0])

  // ── Shared styles ──
  const navStyle = (active: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '9px 12px', borderRadius: 8, width: '100%', textAlign: 'left',
    border: 'none', cursor: 'pointer', transition: 'background 0.15s',
    background: active ? '#1e40af' : 'transparent',
    color: active ? '#ffffff' : '#94a3b8',
  })

  return (
    <div style={{ fontFamily: "'Noto Sans KR', sans-serif" }} className="flex h-screen overflow-hidden bg-slate-100">

      {/* ── Sidebar ── */}
      <aside className="w-60 flex-shrink-0 flex flex-col" style={{ background: '#0d1b33' }}>
        <div className="px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-500/90 flex items-center justify-center flex-shrink-0">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1L13 4V10L7 13L1 10V4L7 1Z" stroke="white" strokeWidth="1.4" strokeLinejoin="round"/>
                <circle cx="7" cy="7" r="2" fill="white" opacity="0.85"/>
              </svg>
            </div>
            <div>
              <div className="text-white text-xs font-semibold leading-snug">폴란드 구호 플래너</div>
              <div className="text-blue-400 text-[11px] leading-snug">Poland Relief Planner</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(item => (
            <button key={item.id} onClick={() => setActiveNav(item.id)} style={navStyle(activeNav === item.id)}
              onMouseEnter={e => { if (activeNav !== item.id) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.06)' }}
              onMouseLeave={e => { if (activeNav !== item.id) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
            >
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: activeNav === item.id ? '#93c5fd' : '#475569', fontWeight: 500, width: 20, flexShrink: 0 }}>
                {item.step}
              </span>
              <span style={{ fontSize: 13, fontWeight: activeNav === item.id ? 600 : 400 }}>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="px-5 py-4 border-t border-white/10">
          <div style={{ fontSize: 10, color: '#475569', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>구호소</div>
          <div className="space-y-2">
            {HUBS.map(h => (
              <div key={h.name} className="flex items-center gap-2.5">
                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: h.color }} />
                <span style={{ fontSize: 12, color: '#94a3b8' }}>{h.name}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <main ref={mainRef} className="flex-1 overflow-y-auto">

        {/* ═══════════════════════════════════════ STEP 01 ═══════════════════════════════════════ */}
        {activeNav === 0 && (
          <div className="px-8 py-7 max-w-[1100px]">
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-1">
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#2563eb', fontWeight: 500 }}>STEP 01</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>데이터 입력</span>
              </div>
              <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, lineHeight: 1.3 }}>구호소별 최근 유입량</h1>
              <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>저장된 일별 입국 자료의 주간 합계가 기준 주에 맞춰 채워집니다. 저장 자료가 없는 주는 실제 유입량을 직접 입력하세요. 입력값으로 매번 새 예측을 계산합니다.</p>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-3 mb-5">
              <div className="relative" ref={calRef}>
                <button onClick={toggleCal} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', borderRadius: 10, border: '1.5px solid #e2e8f0', background: calOpen ? '#eff6ff' : '#ffffff', cursor: 'pointer', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ color: '#2563eb', flexShrink: 0 }}>
                    <rect x="1" y="2.5" width="12" height="10" rx="2" stroke="currentColor" strokeWidth="1.3"/>
                    <path d="M4.5 1v3M9.5 1v3M1 6h12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                  </svg>
                  <div style={{ textAlign: 'left' }}>
                    <div style={{ fontSize: 11, color: '#64748b' }}>기준 주차</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{refMonday.getFullYear()}년 {weekNum}번째 주</div>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#64748b' }}>{fmt(refMonday)} – {fmt(weekEnd)}</div>
                  </div>
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ color: '#94a3b8', marginLeft: 4 }}>
                    <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </button>

                {calOpen && (
                  <div style={{ position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 50, background: '#ffffff', borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.14)', border: '1px solid #e2e8f0', padding: 16, width: 280 }}>
                    <div className="flex items-center justify-between mb-3">
                      <button onClick={prevMo} style={calNavBtn}>←</button>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{calYear}년 {KO_MONTHS[calMonth]}</span>
                      <button onClick={nextMo} style={calNavBtn}>→</button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2, marginBottom: 4 }}>
                      {DAY_HEADERS.map(d => <div key={d} style={{ textAlign: 'center', fontSize: 10, color: '#94a3b8', fontWeight: 600, padding: '2px 0' }}>{d}</div>)}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2 }}>
                      {calDays.map((d, idx) => {
                        const disabled = !isRefWeekAllowed(getMondayOfWeek(d))
                        const inRef = inRefWeek(d); const inHov = !disabled && inHoverWeek(d)
                        const isToday = sameDay(d, today); const inCurMo = d.getMonth() === calMonth
                        const isRefMon = sameDay(d, getMondayOfWeek(refMonday)); const isRefSun = sameDay(d, addDays(getMondayOfWeek(refMonday), 6))
                        const isHovMon = hoverDay ? sameDay(d, getMondayOfWeek(hoverDay)) : false; const isHovSun = hoverDay ? sameDay(d, addDays(getMondayOfWeek(hoverDay), 6)) : false
                        let bg = 'transparent', textColor = inCurMo ? '#374151' : '#d1d5db', br = '6px'
                        if (inRef) { bg = '#dbeafe'; textColor = '#1e40af'; br = isRefMon ? '6px 0 0 6px' : isRefSun ? '0 6px 6px 0' : '0' }
                        else if (inHov) { bg = '#f0fdf4'; textColor = '#166534'; br = isHovMon ? '6px 0 0 6px' : isHovSun ? '0 6px 6px 0' : '0' }
                        else if (disabled) { textColor = '#e2e8f0' }
                        return (
                          <div key={idx} onClick={() => selectDay(d)} onMouseEnter={() => setHoverDay(disabled ? null : d)} onMouseLeave={() => setHoverDay(null)}
                            title={disabled ? '선택 가능한 완료 기준 주 범위 밖입니다' : undefined}
                            style={{ textAlign: 'center', fontSize: 12, padding: '5px 2px', cursor: disabled ? 'not-allowed' : 'pointer', borderRadius: br, background: bg, color: textColor, fontWeight: isToday ? 700 : 400, position: 'relative' }}>
                            {isToday && <div style={{ position: 'absolute', bottom: 2, left: '50%', transform: 'translateX(-50%)', width: 3, height: 3, borderRadius: '50%', background: '#2563eb' }} />}
                            {d.getDate()}
                          </div>
                        )
                      })}
                    </div>
                    <div style={{ marginTop: 12, padding: '8px 10px', background: '#eff6ff', borderRadius: 8, textAlign: 'center' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#1e40af' }}>{refMonday.getFullYear()}년 {weekNum}번째 주</div>
                      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#3b82f6', marginTop: 2 }}>{fmt(refMonday)} – {fmt(weekEnd)}</div>
                    </div>
                    {meta && (
                      <div style={{ marginTop: 8, fontSize: 10, color: '#94a3b8', textAlign: 'center' }}>
                        선택 가능한 기준 주 · {fmt(parseYmd(meta.first_reference))} – {fmt(parseYmd(meta.last_reference))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div style={{ flex: 1 }} />
              <button onClick={fillInflowExample} disabled={isPredicting} style={btnSecondary}>예시 값 입력</button>
            
              <button onClick={handleRestoreOriginal} disabled={!isInflowEdited}
                style={{ ...btnGhost, cursor: isInflowEdited ? 'pointer' : 'not-allowed', opacity: isInflowEdited ? 1 : 0.5 }}>유입 원자료로 되돌리기</button>
            </div>

            {metaError && (
              <div style={{ marginBottom: 12, padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, fontSize: 12, color: '#dc2626', fontWeight: 500 }}>
                서버에 연결할 수 없습니다. 백엔드 주소({API_BASE})를 확인해주세요.
              </div>
            )}
            {historyError && (
              <div style={{ marginBottom: 12, padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, fontSize: 12, color: '#dc2626', fontWeight: 500 }}>
                {historyError}
              </div>
            )}

            {/* Card */}
            <div style={{ ...card, marginBottom: 16 }}>
              <div style={cardHeader}>
                <div>
                  <div style={cardTitle}>주간 유입량</div>
                  <div style={cardSub}>{inflowExampleActive ? '기준 주 포함 2주 · 시연용 가상 유입량' : '기준 주 포함 2주 · 폴란드 국경수비대 일별 자료의 주간 합계'}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, alignSelf: 'flex-end' }}>
                  {historyLoading && <span style={{ fontSize: 11, color: '#2563eb' }}>원자료 불러오는 중…</span>}
                  {isInflowEdited && !historyLoading && (
                    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: '#fff7ed', color: '#c2410c', border: '1px solid #fed7aa' }}>수정됨 · 가정 시나리오</span>
                  )}
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#94a3b8' }}>단위: 명</div>
                </div>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <th style={th}>주차</th>
                    <th style={th}>기간</th>
                    {SITE_KEYS.map((hub, h) => (
                      <th key={hub} style={{ ...th, textAlign: 'right', color: HUBS[h].color }}>{SITE_NAMES[hub]}</th>
                    ))}
                    <th style={{ ...th, textAlign: 'right' }}>합계</th>
                  </tr>
                </thead>
                <tbody>
                  {Array.from({ length: HISTORY_WEEKS }, (_, idx) => {
                    const start = addDays(refMonday, -idx * 7)
                    const total = historyTotals[idx]
                    return (
                      <tr key={idx} style={{ borderBottom: idx < HISTORY_WEEKS - 1 ? '1px solid #f8fafc' : 'none' }}>
                        <td style={td}><span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: idx === 0 ? '#eff6ff' : '#f8fafc', color: idx === 0 ? '#2563eb' : '#64748b' }}>{idx === 0 ? '기준 주' : `${idx}주 전`}</span></td>
                        <td style={{ ...td, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#94a3b8' }}>{fmt(start)} – {fmt(addDays(start, 6))}</td>
                        {SITE_KEYS.map(hub => {
                          const value = hubInflow[hub][idx] ?? ''
                          const missing = value.trim() === ''
                          const outlier = !missing && (Number(value) < 0 || Number(value) > 500000)
                          const edited = hubInflowOriginal !== null && value !== (hubInflowOriginal[hub]?.[idx] ?? '')
                          return (
                            <td key={hub} style={{ ...td, textAlign: 'right' }}>
                              <input type="number" value={value} onChange={e => updateHubInflow(hub, idx, e.target.value)} placeholder="—"
                                title={edited ? `원자료: ${hubInflowOriginal?.[hub]?.[idx] || '—'}` : undefined}
                                style={{ width: 96, textAlign: 'right', padding: '4px 8px', borderRadius: 6, border: `1.5px solid ${outlier ? '#fca5a5' : missing ? '#fde68a' : edited ? '#fdba74' : '#e2e8f0'}`, background: outlier ? '#fef2f2' : missing ? '#fffbeb' : edited ? '#fff7ed' : '#f8fafc', fontSize: 13, fontWeight: 500, color: '#0f172a', outline: 'none', fontFamily: "'JetBrains Mono', monospace" }}
                                onFocus={e => { e.target.style.borderColor = '#2563eb'; e.target.style.background = '#eff6ff' }}
                                onBlur={e => { const v = e.target.value; const out = v !== '' && (Number(v) < 0 || Number(v) > 500000); const ed = hubInflowOriginal !== null && v !== (hubInflowOriginal[hub]?.[idx] ?? ''); e.target.style.borderColor = out ? '#fca5a5' : v === '' ? '#fde68a' : ed ? '#fdba74' : '#e2e8f0'; e.target.style.background = out ? '#fef2f2' : v === '' ? '#fffbeb' : ed ? '#fff7ed' : '#f8fafc' }}
                              />
                            </td>
                          )
                        })}
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#0f172a' }}>
                          {total === null ? '—' : comma(total)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div style={{ marginTop: 12, borderTop: '1px solid #f1f5f9', paddingTop: 10, fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
                {inflowExampleActive ? '시연용 가상 유입량 · 기준 주 2026.01.26 · 실제 운영값 아님. 분쟁 정보도 예시 값으로 함께 채워집니다.' : '각 구호소의 기준 주와 1주 전 실제 유입량을 입력하세요. 예시 값 입력으로 유입량·분쟁 정보를 한 번에 채울 수 있습니다.'}
              </div>
            </div>

            <div style={{ ...card, marginBottom: 16 }}>
              <div style={cardHeader}>
                <div>
                  <div style={cardTitle}>기준 주 분쟁 정보</div>
                  <div style={cardSub}>우크라이나 전체 · {fmt(refMonday)} – {fmt(weekEnd)} 주간 합계</div>
                </div>
                {inflowExampleActive && <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: '#fff7ed', color: '#c2410c', border: '1px solid #fed7aa' }}>시연용 가상값</span>}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
                {([['events', '분쟁 사건 수', '건'], ['deaths', '분쟁 사망자 수', '명']] as const).map(([key, label, unit]) => {
                  const value = conflictInput[key]
                  const invalid = value.trim() !== '' && (!Number.isInteger(Number(value)) || Number(value) < 0)
                  return <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#475569' }}>
                    {label}
                    <input type="number" min="0" step="1" aria-label={label} value={value} placeholder="—"
                      onChange={e => { clearPrediction(); setConflictInput(prev => ({ ...prev, [key]: e.target.value })) }}
                      style={{ width: 112, textAlign: 'right', padding: '6px 10px', borderRadius: 6, border: `1.5px solid ${invalid ? '#fca5a5' : value.trim() === '' ? '#fde68a' : '#e2e8f0'}`, background: invalid ? '#fef2f2' : value.trim() === '' ? '#fffbeb' : '#f8fafc', fontSize: 13, color: '#0f172a', fontFamily: "'JetBrains Mono', monospace" }} />
                    {unit}
                  </label>
                })}
              </div>
              <div style={{ marginTop: 12, fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
                기준 주 사건 수·사망자 수를 유입량과 함께 예측에 반영합니다. 향후 분쟁 수준은 기준 주 수준이 유지된다고 가정합니다. 0은 실제 집계가 0일 때 입력하세요.
              </div>
            </div>

            {/* Data quality */}
            <div style={{ background: '#ffffff', borderRadius: 10, padding: '12px 20px', border: '1px solid #e8edf2', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', display: 'flex', alignItems: 'center', gap: 0, marginBottom: 5 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', marginRight: 20, whiteSpace: 'nowrap', letterSpacing: '0.04em' }}>데이터 품질</div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
                {[
                  { label: '결측', ok: totalMissing === 0, detail: totalMissing === 0 ? '없음' : `${totalMissing}개` },
                  { label: '이상치', ok: outlierCount === 0, detail: outlierCount === 0 ? '없음' : `${outlierCount}개` },
                  { label: '기간 일치', ok: true, detail: '유입 2주 · 분쟁 1주' },
                  { label: '분석 가능', ok: isReady, detail: isReady ? '준비됨' : '미완료' },
                ].map((q, i, arr) => (
                  <div key={q.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 7, background: q.ok ? '#f0fdf4' : '#fef2f2', border: `1px solid ${q.ok ? '#bbf7d0' : '#fecaca'}` }}>
                      <div style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: q.ok ? '#16a34a' : '#dc2626' }} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: q.ok ? '#166534' : '#991b1b' }}>{q.label}</span>
                      <span style={{ fontSize: 11, color: q.ok ? '#4ade80' : '#f87171', fontFamily: "'JetBrains Mono', monospace" }}>{q.detail}</span>
                    </div>
                    {i < arr.length - 1 && <div style={{ width: 24, height: 1, background: '#e2e8f0', flexShrink: 0 }} />}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end pt-3">
              <button
  onClick={runPrediction}
  disabled={!isReady || isPredicting}
  style={{
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '11px 28px',
    borderRadius: 10,
    border: 'none',
    background: isReady ? '#2563eb' : '#93c5fd',
    color: '#ffffff',
    fontSize: 14,
    fontWeight: 700,
    cursor: !isReady || isPredicting ? 'not-allowed' : 'pointer',
    boxShadow: isReady
      ? '0 4px 14px rgba(37,99,235,0.35)'
      : 'none',
    transition: 'all 0.2s',
    opacity: isPredicting ? 0.85 : 1,
  }}
>
  {isPredicting ? '예측 중...' : '향후 4주 유입량 예측'}

  {isPredicting ? (
    <span className="prediction-spinner" />
  ) : (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
    >
      <path
        d="M3 8h10M9 4l4 4-4 4"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )}
</button>
            </div>
          </div>
        )}

        {/* ═══════════════════════════════════════ STEP 02 ═══════════════════════════════════════ */}
        {activeNav === 1 && (
          <div className="px-8 py-7 max-w-[1100px]">
            {/* Header */}
            <div className="mb-7">
              <div className="flex items-center gap-2 mb-1">
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#2563eb', fontWeight: 500 }}>STEP 02</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>4주 수요 예측</span>
              </div>
              <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, lineHeight: 1.3 }}>향후 4주 난민 및 구호소 수요 예측</h1>
              {shownAccuracy && (
                <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', background: '#f8fafc', borderRadius: 20, border: '1px solid #e2e8f0', fontSize: 11, color: '#475569' }}>
                    <span>검증 오차(WAPE) <b style={{ color: '#2563eb' }}>{shownAccuracy.wape_hub_pct}%</b></span>
                    <span style={{ color: '#cbd5e1' }}>·</span>
                    <span>지난주 그대로 <b style={{ color: '#64748b' }}>{shownAccuracy.naive_wape_hub_pct}%</b></span>
                    <span style={{ color: '#cbd5e1' }}>·</span>
                    <span>80% 구간 적중 <b style={{ color: '#2563eb' }}>{shownAccuracy.coverage80_pct}%</b></span>
                  </div>
                  <span style={{ fontSize: 10, color: '#94a3b8' }}>검증 기간 · {shownAccuracy.period}</span>
                </div>
              )}
              {predictionSource && SOURCE_LABELS[predictionSource] && (
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 8, padding: '4px 12px', borderRadius: 20, fontSize: 11, fontWeight: 600,
                  background: predictionSource === 'what_if' ? '#fff7ed' : predictionSource === 'backtest' ? '#eff6ff' : '#f8fafc',
                  border: `1px solid ${predictionSource === 'what_if' ? '#fed7aa' : predictionSource === 'backtest' ? '#bfdbfe' : '#e2e8f0'}`,
                  color: predictionSource === 'what_if' ? '#c2410c' : predictionSource === 'backtest' ? '#1e40af' : '#475569' }}>
                  {SOURCE_LABELS[predictionSource]}
                </div>
              )}
              {!predictionSource && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#475569', lineHeight: 1.5 }}>
                  아직 이 기준 주의 예측을 실행하지 않았습니다. STEP 01에서 예측을 실행해 주세요.
                </div>
              )}
              {predictionWarning && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e', lineHeight: 1.5 }}>
                  {predictionWarning}
                </div>
              )}
            </div>

            {/* ── SECTION 1: 주차별 국경 유입량 예측 ── */}
            <div className="mb-2">
              <SectionLabel label="주차별 국경 유입량 예측" />
            </div>

            {/* 4 forecast cards */}
            <div className="grid grid-cols-4 gap-4 mb-5">
              {forecastValues.map((val, i) => {
                const wkStart = addDays(forecastStart, i * 7)
                const wkEnd = addDays(wkStart, 6)
                const isEditing = editingWeek === i
                const interval = forecastIntervals[i]
                return (
                  <div key={i} style={{ ...card, position: 'relative' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#2563eb', marginBottom: 6 }}>{i + 1}주 후</div>

                    {isEditing ? (
                      <div style={{ marginBottom: 8 }}>
                        <input
                          autoFocus
                          type="number"
                          value={editTemp}
                          onChange={e => setEditTemp(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') confirmEdit(i); if (e.key === 'Escape') setEditingWeek(null) }}
                          onBlur={() => confirmEdit(i)}
                          style={{ width: '100%', padding: '6px 8px', borderRadius: 8, border: '2px solid #2563eb', background: '#eff6ff', fontSize: 20, fontWeight: 700, color: '#0f172a', outline: 'none', fontFamily: "'JetBrains Mono', monospace" }}
                        />
                        <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 4 }}>Enter로 확인</div>
                      </div>
                    ) : (
                      <div style={{ marginBottom: 8 }}>
                        <div style={{ fontSize: 28, fontWeight: 700, color: '#0f172a', lineHeight: 1.1, letterSpacing: '-0.5px' }}>
                          {comma(val)}<span style={{ fontSize: 14, fontWeight: 500, color: '#64748b', marginLeft: 3 }}>명</span>
                        </div>
                      </div>
                    )}

                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#94a3b8' }}>
                      {fmtShort(wkStart)} – {fmtShort(wkEnd)}
                    </div>
                    {interval && !isEditing && (
  <div
    style={{
      marginTop: 10,
      padding: '7px 9px',
      borderRadius: 7,
      background: '#eff6ff',
      border: '1px solid #dbeafe',
    }}
  >
    <div
      style={{
        fontSize: 10,
        color: '#64748b',
        marginBottom: 2,
      }}
    >
      80% 예측범위
    </div>

    <div
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        fontWeight: 600,
        color: '#2563eb',
      }}
    >
      {comma(interval.low)} ~ {comma(interval.high)}명
    </div>
  </div>
)}

                    {!isEditing && (
                      <button onClick={() => startEdit(i)} title="수동 수정"
                        style={{ position: 'absolute', top: 12, right: 12, padding: '3px 7px', borderRadius: 6, border: '1px solid #e2e8f0', background: '#f8fafc', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, transition: 'all 0.15s' }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = '#eff6ff'; (e.currentTarget as HTMLElement).style.borderColor = '#bfdbfe' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '#f8fafc'; (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0' }}
                      >
                        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                          <path d="M8.5 1.5l2 2-7 7H1.5v-2l7-7z" stroke="#64748b" strokeWidth="1.2" strokeLinejoin="round"/>
                        </svg>
                        <span style={{ fontSize: 10, color: '#64748b', fontWeight: 500 }}>수정</span>
                      </button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Total + chart */}
            <div
  style={{
    ...card,
    marginBottom: 16,
    padding: '16px 18px',
  }}
>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 20 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>4주 총 예상 유입량</span>
                <span style={{ fontSize: 32, fontWeight: 700, color: '#0f172a', letterSpacing: '-1px' }}>{comma(totalForecast)}</span>
                <span style={{ fontSize: 15, color: '#64748b' }}>명</span>
              </div>

              <div style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
<ComposedChart
  data={chartData}
  margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
>                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: "'Noto Sans KR', sans-serif" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8', fontFamily: "'JetBrains Mono', monospace" }} axisLine={false} tickLine={false} width={48}
                      tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)} />
                    <Tooltip
                      contentStyle={{ background: '#1e293b', border: 'none', borderRadius: 8, padding: '8px 12px' }}
                      labelStyle={{ fontSize: 11, color: '#94a3b8', marginBottom: 4, fontFamily: "'Noto Sans KR', sans-serif" }}
                      itemStyle={{ fontSize: 12, color: '#ffffff', fontFamily: "'JetBrains Mono', monospace" }}
                      formatter={(value: any, name: any) => {
  if (name === 'interval' && Array.isArray(value)) {
    return [
      `${comma(Number(value[0]))} ~ ${comma(Number(value[1]))}명`,
      '80% 예측범위',
    ]
  }

  return [
    `${comma(Number(value))}명`,
    name === 'actual'
      ? '최근 유입'
      : name === 'observed'
        ? '실제 유입'
        : '예측 유입',
  ]
}}
                    />
                    <ReferenceLine x="기준 주" stroke="#e2e8f0" strokeDasharray="4 3" />
                    <Area
  type="monotone"
  dataKey="interval"
  stroke="none"
  fill="#2563eb"
  fillOpacity={0.12}
  connectNulls={false}
  name="interval"
/>
                    <Line
                      type="monotone" dataKey="actual" stroke="#64748b" strokeWidth={2}
                      dot={{ r: 3, fill: '#64748b', strokeWidth: 0 }}
                      activeDot={{ r: 5, fill: '#64748b' }}
                      connectNulls={false} name="actual"
                    />
                    <Line
                      type="monotone" dataKey="forecast" stroke="#2563eb" strokeWidth={2}
                      strokeDasharray="6 3"
                      dot={{ r: 3, fill: '#2563eb', strokeWidth: 0 }}
                      activeDot={{ r: 5, fill: '#2563eb' }}
                      connectNulls={false} name="forecast"
                    />
                    {hasActual && (
                      <Line
                        type="monotone" dataKey="observed" stroke="#16a34a" strokeWidth={2}
                        dot={{ r: 3, fill: '#16a34a', strokeWidth: 0 }}
                        activeDot={{ r: 5, fill: '#16a34a' }}
                        connectNulls={false} name="observed"
                      />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div style={{ display: 'flex', gap: 20, marginTop: 10, justifyContent: 'flex-end' }}>
                {[
                  { color: '#64748b', dash: false, label: '최근 2주 유입 (3개 구호소 합계)' },
                  { color: '#2563eb', dash: true, label: '향후 4주 예측' },
                  ...(hasActual ? [{ color: '#16a34a', dash: false, label: '실제' }] : []),
                ].map(l => (
                  <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <svg width="20" height="4"><line x1="0" y1="2" x2="20" y2="2" stroke={l.color} strokeWidth="2" strokeDasharray={l.dash ? '5 3' : 'none'} /></svg>
                    <span style={{ fontSize: 11, color: '#64748b' }}>{l.label}</span>
                  </div>
                ))}
              </div>
            </div>
            {/* ── 구호소별 예측 ── */}
            <div className="mb-2">
              <SectionLabel label="구호소별 예측" />
            </div>

            <div style={{ ...card, marginBottom: 20 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <th style={th}>구호소</th>
                    {[0, 1, 2, 3].map(i => (
                      <th key={i} style={{ ...th, textAlign: 'right' }}>{i + 1}주 후</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SITE_KEYS.map((hub, h) => (
                    <tr key={hub} style={{ borderBottom: h < SITE_KEYS.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                      <td style={td}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: HUBS[h].color, flexShrink: 0 }} />
                          <span style={{ fontWeight: 600, color: '#0f172a' }}>{SITE_NAMES[hub]}</span>
                        </div>
                      </td>
                      {[0, 1, 2, 3].map(i => {
                        const interval = hubIntervals?.[hub]?.[i] ?? null
                        const actual = hubActual?.[hub]?.[i] ?? null
                        return (
                          <td key={i} style={{ ...td, textAlign: 'right' }}>
                            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#0f172a' }}>{comma(Number(hubForecast[hub][i] ?? 0))}</div>
                            {interval && (
                              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#94a3b8', marginTop: 2 }}>{comma(interval.low)}–{comma(interval.high)}</div>
                            )}
                            {actual !== null && (
                              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#16a34a', fontWeight: 600, marginTop: 2 }}>실제 {comma(actual)}</div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8' }}>
                {hubActual ? '구호소별 예측값과 저장된 실제값을 표시합니다.' : '구호소별 예측값을 표시합니다.'} 새 모델의 80% 예측범위는 위의 3개 구호소 총 유입량에만 제공됩니다. (단위: 명)
              </div>
            </div>

            {/* ── SECTION 2: 구호소 운영 시나리오 ── */}
            <div className="mb-2">
              <SectionLabel label="구호소 운영 시나리오" />
            </div>

            <div style={{ ...card, marginBottom: 16 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                {/* Control 1: 구호소 이용률 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', width: 200, flexShrink: 0 }}>
                    국경 유입자 중 구호소 이용률
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[5, 10, 20].map(v => (
                      <button key={v} onClick={() => setUtilRate(v)} style={presetBtn(utilRate === v)}>{v}%</button>
                    ))}
                  </div>
                </div>

                <div style={{ height: 1, background: '#f1f5f9' }} />

                {/* Control 2: 평균 체류기간 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', width: 200, flexShrink: 0 }}>
                    평균 체류기간
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[1, 2, 3, 4].map(v => (
                      <button key={v} onClick={() => setStayDuration(v)} style={presetBtn(stayDuration === v)}>{v}일</button>
                    ))}
                  </div>
                </div>
              </div>

            </div>

            {/* ── SECTION 3: 주차별 운영수요 ── */}
            <div className="mb-2">
              <SectionLabel label="주차별 운영수요" />
            </div>

            <div style={{ ...card, marginBottom: 20 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #f1f5f9' }}>
                    <th style={th}>주차</th>
                    <th style={{ ...th, textAlign: 'right' }}>예상 유입 (명)</th>
                    <th style={{ ...th, textAlign: 'right' }}>구호소 이용 예상인원 (명)</th>
                    <th style={{ ...th, textAlign: 'right' }}>평균 체류기간 (일)</th>
                    <th style={{ ...th, textAlign: 'right' }}>총 체류수요 (인·일)</th>
                  </tr>
                </thead>
                <tbody>
                  {forecastValues.map((val, i) => {
                    const d = weekDemand(val)
                    const wkStart = addDays(forecastStart, i * 7)
                    return (
                      <tr key={i} style={{ borderBottom: i < forecastValues.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                        <td style={td}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, background: '#eff6ff', color: '#2563eb' }}>{i + 1}주 후</span>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#cbd5e1' }}>
                              {fmtShort(wkStart)} – {fmtShort(addDays(wkStart, 6))}
                            </span>
                          </div>
                        </td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 }}>{comma(val)}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 }}>{comma(d.shelterUsers)}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 500, color: '#64748b' }}>{stayDuration}</td>
                        <td style={{ ...td, textAlign: 'right' }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#0f172a', fontSize: 14 }}>{comma(d.personDays)}</span>
                        </td>
                      </tr>
                    )
                  })}
                  {/* Totals row */}
                  <tr style={{ borderTop: '2px solid #f1f5f9', background: '#f8fafc' }}>
                    <td style={{ ...td, fontWeight: 700, color: '#0f172a' }}>합계</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#0f172a' }}>{comma(totalForecast)}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: '#0f172a' }}>{comma(forecastValues.reduce((a, v) => a + weekDemand(v).shelterUsers, 0))}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 500, color: '#94a3b8' }}>—</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
                      {comma(forecastValues.reduce((a, v) => a + weekDemand(v).personDays, 0))}
                      <span style={{ fontSize: 10, fontWeight: 400, color: '#94a3b8', marginLeft: 3 }}>인·일</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* CTA */}
            <div className="flex justify-end">
              <button onClick={() => setActiveNav(2)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 28px', borderRadius: 10, border: 'none', background: '#2563eb', color: '#ffffff', fontSize: 14, fontWeight: 700, cursor: 'pointer', boxShadow: '0 4px 14px rgba(37,99,235,0.35)', transition: 'all 0.2s' }}>
                구호품 계획 설정으로 이동
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
              </button>
            </div>
          </div>
        )}

        {/* ═══════════════════════════════════════ STEP 03 ═══════════════════════════════════════ */}
        {activeNav === 2 && (() => {
          // ── Computed from Step 02 ──
          type HK = 'medyka' | 'dorohusk' | 'korczowa'
          type IK = 'water' | 'food' | 'blanket' | 'hygiene'
          const selectedKeys: HK[] = [selectedSite]
          // 구호소별 주간 최대 예상 이용자 = max_w(구호소 예측 × 이용률)
          const hubPeakUsers = (hub: HK) =>
            Math.max(...hubForecast[hub].map(v => supportedPeople(Number(v), effectiveUtil)))

          const HUB_CFG3 = [
            { key: 'medyka' as HK, name: 'Medyka', color: '#0d9488', bg: '#f0fdfa', border: '#a7f3d0' },
            { key: 'dorohusk' as HK, name: 'Dorohusk', color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
            { key: 'korczowa' as HK, name: 'Korczowa', color: '#ea580c', bg: '#fff7ed', border: '#fed7aa' },
          ]
          const NEW_ITEMS = [
            { id: 'water' as IK, label: '물', unit: 'L', pUnit: 'USD/L', vUnit: '㎥/L' },
            { id: 'food' as IK, label: '식량', unit: '1일분', pUnit: 'USD/1일분', vUnit: '㎥/1일분' },
            { id: 'blanket' as IK, label: '담요', unit: '개', pUnit: 'USD/개', vUnit: '㎥/개' },
            { id: 'hygiene' as IK, label: '위생키트', unit: '개', pUnit: 'USD/개', vUnit: '㎥/개' },
          ]
          function setInv(hub: HK, item: IK, val: string) {
            setInitialInventory(prev => ({ ...prev, [hub]: { ...prev[hub], [item]: val } }))
          }
          function setSupply(week: number, item: IK, val: string) {
            setWeeklySupplyLimits(prev => prev.map((r, i) => i === week ? { ...r, [item]: val } : r))
          }
          function fillSyntheticExample() {
            setInitialInventory(Object.fromEntries(SITE_KEYS.map(site => [site, { ...SYNTH_INVENTORY[site] }])) as typeof initialInventory)
            setWeeklySupplyLimits(Array.from({ length: 4 }, (_, w) => ({
              water: SYNTH_SUPPLY.water[w],
              food: SYNTH_SUPPLY.food[w],
              blanket: SYNTH_SUPPLY.blanket[w],
              hygiene: SYNTH_SUPPLY.hygiene[w],
            })))
            setItemPrices({ ...SYNTH_PRICES })
            setItemVolumes({ ...SYNTH_VOLUMES })
            setWarehouseCapacities({ ...SYNTH_WAREHOUSE })
            setBudget(SYNTH_BUDGET)
            setUtilRate(10)
            setStayDuration(3)
            setPriority('fairness')
            setLogisticsDrafts(Object.fromEntries(SITE_KEYS.map(site => [site, {
              ...withSyntheticItemConditions(emptyLogistics()),
              warehouseId: roadOptions?.preset.default_warehouse_id ?? 'przemysl-lwowska-36',
              truckCount: '2', overnightReturn: true, intermediateRest: true,
            }])) as Record<SiteKey, LogisticsDraft>)
          }
          const canOptimize = selectedKeys.length > 0 && hasPlanningForecast(predictionSource, hubForecast[selectedSite])

          return (
            <div className="px-8 py-7 max-w-[1100px]">
              {/* ── Header ── */}
              <div className="mb-5">
                <div className="flex items-center gap-2 mb-1">
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#2563eb', fontWeight: 500 }}>STEP 03</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>구호품 계획</span>
                </div>
                <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, lineHeight: 1.3 }}>구호품 배분 최적화 설정</h1>
                {/* STEP 02 summary pill */}
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 8, padding: '4px 12px', background: '#f8fafc', borderRadius: 20, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 11, color: '#64748b' }}>구호소 이용률</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#2563eb' }}>{effectiveUtil}%</span>
                  <span style={{ fontSize: 11, color: '#cbd5e1' }}>·</span>
                  <span style={{ fontSize: 11, color: '#64748b' }}>평균 체류기간</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#2563eb' }}>{stayDuration}일</span>
                </div>
                {/* 합성 예시 값 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                  <button onClick={fillSyntheticExample} disabled={isOptimizing} style={btnSecondary}>예시 값 입력</button>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>
                    시연용 예시(실제 운영값 아님) · 재고·공급·단가·예산·창고·차량·운송·기한과 이용률·체류기간을 한 번에 채웁니다.
                  </span>
                </div>
              </div>

              {/* ── S1: 계획 대상 구호소 선택 ── */}
              <div className="mb-2"><SectionLabel label="계획 대상 구호소 선택" /></div>
              {/* Hub selection cards */}
              <div className="grid grid-cols-3 gap-4 mb-2">
                {HUB_CFG3.map(h => {
                  const sel = selectedSite === h.key
                  const peakUsers = hubPeakUsers(h.key)
                  const waterDemand = peakUsers * stayDuration * 15
                  const foodDemand = peakUsers * stayDuration
                  return (
                    <div key={h.key} onClick={() => setSelectedSite(h.key as SiteKey)}
                      style={{ ...card, borderTop: `3px solid ${sel ? h.color : '#e2e8f0'}`, padding: '16px 18px', cursor: 'pointer', opacity: sel ? 1 : 0.55, transition: 'all 0.15s', userSelect: 'none' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: sel ? h.color : '#cbd5e1', flexShrink: 0 }} />
                          <span style={{ fontSize: 14, fontWeight: 700, color: sel ? h.color : '#94a3b8' }}>{h.name}</span>
                        </div>
                        <div style={{ width: 18, height: 18, borderRadius: 5, border: `2px solid ${sel ? h.color : '#d1d5db'}`, background: sel ? h.color : '#ffffff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          {sel && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5L8 3" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                        </div>
                      </div>
                      <div style={{ padding: '10px 12px', background: '#f8fafc', borderRadius: 8 }}>
                        <div style={{ fontSize: 10, color: '#94a3b8', fontWeight: 600, marginBottom: 4 }}>주간 최대 예상 이용자</div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', fontFamily: "'JetBrains Mono', monospace" }}>
                          {comma(peakUsers)}<span style={{ fontSize: 12, fontWeight: 400, color: '#64748b', marginLeft: 3 }}>명</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 6, fontFamily: "'JetBrains Mono', monospace" }}>
                          물 {comma(waterDemand)} L · 식량 {comma(foodDemand)} 1일분
                        </div>
                        <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>최대 주의 필요량 (1인 1일 물 15L)</div>
                      </div>
                    </div>
                  )
                })}
              </div>
              {selectedKeys.length === 0 && (
                <div style={{ marginBottom: 16, padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, fontSize: 12, color: '#dc2626', fontWeight: 500 }}>
                  최소 1개 구호소를 선택하세요
                </div>
              )}
              <div style={{ marginBottom: 20 }} />

              {/* ── S2: 구호소별 현재 재고 ── */}
              {selectedKeys.length > 0 && (
                <>
                  <div className="mb-2"><SectionLabel label="구호소별 현재 재고" /></div>
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${selectedKeys.length}, 1fr)`, gap: 16, marginBottom: 20 }}>
                    {HUB_CFG3.filter(h => h.key === selectedSite).map(h => (
                      <div key={h.key} style={{ ...card, padding: '16px 18px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 14 }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: h.color, flexShrink: 0 }} />
                          <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{h.name}</span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                          {NEW_ITEMS.map(item => (
                            <div key={item.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span style={{ fontSize: 12, color: '#475569', minWidth: 52 }}>{item.label}</span>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                <input type="number" value={initialInventory[h.key][item.id]}
                                  onChange={e => setInv(h.key, item.id as IK, e.target.value)}
                                  placeholder="—"
                                  style={{ ...numInput(false), width: 86 }} onFocus={focusStyle} onBlur={blurStyle} />
                                <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 18 }}>{item.unit}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* ── S3: 품목별 주간 공급 가능 최대량 ── */}
              <div className="mb-2"><SectionLabel label="품목별 주간 공급 가능 최대량" /></div>
              <div style={{ ...card, marginBottom: 20 }}>
                <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 12 }}>{logisticsDrafts[selectedSite].enabled ? '선택 구호소에 할당된 주문 주별 공급업체 한도 (A_it)' : '선택 구호소에 할당된 주별 조달 한도 (A_it)'}</div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <th style={th}>주차</th>
                      {NEW_ITEMS.map(item => (
                        <th key={item.id} style={{ ...th, textAlign: 'right' }}>{item.label} ({item.unit})</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {weeklySupplyLimits.map((row, i) => (
                      <tr key={i} style={{ borderBottom: i < 3 ? '1px solid #f8fafc' : 'none' }}>
                        <td style={td}>
                          <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, background: '#eff6ff', color: '#2563eb' }}>{i + 1}주 후</span>
                        </td>
                        {NEW_ITEMS.map(item => (
                          <td key={item.id} style={{ ...td, textAlign: 'right' }}>
                            <input type="number" value={row[item.id]}
                              onChange={e => setSupply(i, item.id as IK, e.target.value)}
                              placeholder="—" style={{ ...numInput(false), width: 90 }} onFocus={focusStyle} onBlur={blurStyle} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* ── S4: 품목별 비용 및 보관정보 ── */}
              <div className="mb-2"><SectionLabel label="품목별 비용 및 보관정보" /></div>
              <div style={{ ...card, marginBottom: 20 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <th style={th}>품목</th>
                      <th style={{ ...th, textAlign: 'right' }}>단가</th>
                      <th style={{ ...th, textAlign: 'right' }}>단위 부피</th>
                    </tr>
                  </thead>
                  <tbody>
                    {NEW_ITEMS.map((item, idx) => (
                      <tr key={item.id} style={{ borderBottom: idx < NEW_ITEMS.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                        <td style={{ ...td, fontWeight: 600, color: '#374151' }}>{item.label}</td>
                        <td style={{ ...td, textAlign: 'right' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                            <input type="number" value={itemPrices[item.id as IK]}
                              onChange={e => setItemPrices(prev => ({ ...prev, [item.id]: e.target.value }))}
                              placeholder="—" style={{ ...numInput(false), width: 90 }} onFocus={focusStyle} onBlur={blurStyle} />
                            <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 52, textAlign: 'left' }}>{item.pUnit}</span>
                          </div>
                        </td>
                        <td style={{ ...td, textAlign: 'right' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
                            <input type="number" value={itemVolumes[item.id as IK]}
                              onChange={e => setItemVolumes(prev => ({ ...prev, [item.id]: e.target.value }))}
                              placeholder="—" style={{ ...numInput(false), width: 90 }} onFocus={focusStyle} onBlur={blurStyle} />
                            <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 52, textAlign: 'left' }}>{item.vUnit}</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* ── S5: 구호소별 창고용량 ── */}
              {selectedKeys.length > 0 && (
                <>
                  <div className="mb-2"><SectionLabel label="구호소별 창고용량" /></div>
                  <div style={{ ...card, marginBottom: 20 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      {HUB_CFG3.filter(h => h.key === selectedSite).map((h, idx, arr) => (
                        <div key={h.key} style={{ display: 'flex', alignItems: 'center', gap: 16, paddingBottom: idx < arr.length - 1 ? 12 : 0, borderBottom: idx < arr.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 7, width: 120, flexShrink: 0 }}>
                            <div style={{ width: 8, height: 8, borderRadius: '50%', background: h.color, flexShrink: 0 }} />
                            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{h.name}</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="number" value={warehouseCapacities[h.key]}
                              onChange={e => setWarehouseCapacities(prev => ({ ...prev, [h.key]: e.target.value }))}
                              placeholder="—"
                              style={{ width: 120, padding: '7px 12px', borderRadius: 8, border: `1.5px solid ${h.border}`, background: h.bg, fontSize: 15, fontWeight: 700, color: h.color, outline: 'none', fontFamily: "'JetBrains Mono', monospace", textAlign: 'right' }}
                              onFocus={e => { e.target.style.borderColor = h.color }}
                              onBlur={e => { e.target.style.borderColor = h.border }}
                            />
                            <span style={{ fontSize: 13, color: '#64748b' }}>㎥</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* ── S6: 총 예산 + 최적화 목표 ── */}
              <div className="mb-2"><SectionLabel label="최적화 조건" /></div>
              <div style={{ ...card, marginBottom: 20 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', width: 140, flexShrink: 0 }}>총 예산 (B)</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <input type="number" value={budget} onChange={e => setBudget(e.target.value)} placeholder="0"
                        style={{ width: 150, padding: '7px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', background: '#f8fafc', fontSize: 14, fontWeight: 600, color: '#0f172a', outline: 'none', fontFamily: "'JetBrains Mono', monospace" }}
                        onFocus={e => { e.target.style.borderColor = '#2563eb'; e.target.style.background = '#eff6ff' }}
                        onBlur={e => { e.target.style.borderColor = '#e2e8f0'; e.target.style.background = '#f8fafc' }}
                      />
                      <span style={{ fontSize: 13, color: '#64748b' }}>USD</span>
                    </div>
                  </div>
                  <div style={{ height: 1, background: '#f1f5f9' }} />
                  <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', width: 140, flexShrink: 0 }}>최적화 목표</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', background: '#eff6ff', borderRadius: 8, border: '1px solid #bfdbfe' }}>
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="5" stroke="#2563eb" strokeWidth="1.2"/><path d="M4 6l1.5 1.5L8 4" stroke="#2563eb" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      <span style={{ fontSize: 12, fontWeight: 600, color: '#1e40af' }}>미충족 수요 최소화</span>
                    </div>
                  </div>
                  <div style={{ height: 1, background: '#f1f5f9' }} />
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', width: 140, flexShrink: 0, paddingTop: 6 }}>우선순위</div>
                    <div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {[
                          { val: 'fairness' as const, label: '공정성 우선 (기본)' },
                          { val: 'efficiency' as const, label: '효율 우선' },
                        ].map(opt => (
                          <button key={opt.val} onClick={() => setPriority(opt.val)} style={presetBtn(priority === opt.val)}>{opt.label}</button>
                        ))}
                      </div>
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <div style={{ fontSize: 11, color: priority === 'fairness' ? '#1e40af' : '#94a3b8' }}>
                          공정성 우선 · 가장 부족한 품목·주의 부족률을 먼저 최소화합니다.
                        </div>
                        <div style={{ fontSize: 11, color: priority === 'efficiency' ? '#1e40af' : '#94a3b8' }}>
                          효율 우선 · 품목별 총수요로 나눈 부족률의 합계를 최소화합니다(일부 품목이 크게 부족할 수 있음).
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* CTA */}
              <LogisticsPanel draft={logisticsDrafts[selectedSite]} roadOptions={roadOptions} roadError={roadError} planningStart={ymd(addDays(refMonday, 7))} onChange={d => {
                  setLogisticsDrafts(prev => ({ ...prev, [selectedSite]: d }))
                  setOptimizationResult(null)
                }} />
              <div className="flex justify-end">
                <button onClick={runOptimization} disabled={isOptimizing || !canOptimize || (usesRoadPlanner(logisticsDrafts[selectedSite]) && !roadOptions)}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 32px', borderRadius: 10, border: 'none', background: canOptimize ? '#2563eb' : '#93c5fd', color: '#ffffff', fontSize: 14, fontWeight: 700, cursor: canOptimize ? 'pointer' : 'not-allowed', boxShadow: canOptimize ? '0 4px 14px rgba(37,99,235,0.35)' : 'none', transition: 'all 0.2s' }}>
                  {isOptimizing ? '도로 탐색·배차 계산 중…' : '최적화 결과 확인'}
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </button>
              </div>
            </div>
          )
        })()}

{/* ═══════════════════════════════════════ STEP 04 ═══════════════════════════════════════ */}
{activeNav === 3 && (() => {

  if (!optimizationResult || optimizationResult._uiRevision !== inputRevision) {
    return (
      <div className="px-8 py-7 max-w-[1100px]">
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                color: '#2563eb',
                fontWeight: 500,
              }}
            >
              STEP 04
            </span>

            <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>

            <span style={{ fontSize: 11, color: '#94a3b8' }}>
              최적화 결과
            </span>
          </div>

          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: '#0f172a',
              margin: 0,
            }}
          >
            4주 구호품 배분 최적화 결과
          </h1>
        </div>

        <div
          style={{
            ...card,
            padding: 30,
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: '#475569',
              marginBottom: 8,
            }}
          >
            아직 최적화 결과가 없습니다.
          </div>

          <div
            style={{
              fontSize: 12,
              color: '#94a3b8',
              marginBottom: 18,
            }}
          >
            구호품 계획에서 입력값을 설정하고 최적화를 실행해주세요.
          </div>

          <button
            onClick={() => setActiveNav(2)}
            style={{
              padding: '9px 18px',
              borderRadius: 8,
              border: 'none',
              background: '#2563eb',
              color: '#ffffff',
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            구호품 계획으로 이동
          </button>
        </div>
      </div>
    )
  }

  const result = optimizationResult as any

  const summary = result.summary ?? {}
  const plan = Array.isArray(result.plan)
    ? result.plan
    : []

  const itemSummary = Array.isArray(result.item_summary)
    ? result.item_summary
    : []

  const warehouseSummary = Array.isArray(result.warehouse_summary)
    ? result.warehouse_summary
    : []

  const weeks: number[] =
    Array.isArray(summary.planning_weeks) &&
    summary.planning_weeks.length > 0
      ? summary.planning_weeks
      : [1, 2, 3, 4]

  const itemLabels: Record<string, string> = {
    water: '물',
    food: '식량',
    hygiene_kit: '위생키트',
    blanket: '담요',
  }

  const itemUnits: Record<string, string> = {
    water: 'L',
    food: '1일분',
    hygiene_kit: '개',
    blanket: '개',
  }

  const fulfillColor = (r: number) =>
    r >= 0.97
      ? '#16a34a'
      : r >= 0.85
        ? '#d97706'
        : '#dc2626'

  const fulfillBg = (r: number) =>
    r >= 0.97
      ? '#f0fdf4'
      : r >= 0.85
        ? '#fffbeb'
        : '#fef2f2'

  const fulfillBorder = (r: number) =>
    r >= 0.97
      ? '#bbf7d0'
      : r >= 0.85
        ? '#fde68a'
        : '#fecaca'

  const weeklySummary = weeks.map(week => {
    const rows = plan.filter(
      (r: any) => Number(r.week) === Number(week)
    )

    const first = rows[0]

    const minFulfillment =
      rows.length > 0
        ? Math.min(
            ...rows.map((r: any) =>
              Number(r.fulfillment_rate ?? 1)
            )
          )
        : 1

   const shortageCount = rows.filter(
  (r: any) => Number(r.unmet_demand ?? 0) >= 0.5
).length

    return {
      week,
      forecast: Number(first?.forecast_arrivals ?? 0),
      supportedPeople: Number(first?.supported_people ?? 0),
      minFulfillment,
      shortageCount,
    }
  })

  const totalSupportedPeople =
    weeklySummary.reduce(
      (sum, row) => sum + row.supportedPeople,
      0
    )

  const overallFulfillment =
    Number(
      summary.overall_weighted_fulfillment_rate ?? 0
    )

  const totalCost =
    Number(summary.total_cost ?? summary.total_procurement_cost ?? 0)

  const budgetRemaining =
    Number(summary.budget_remaining ?? 0)

  const selectedWeek =
    weeks[resultWeek] ?? weeks[0] ?? 1

  const weekPlan = plan.filter(
    (r: any) =>
      Number(r.week) === Number(selectedWeek)
  )

  return (
    <div className="px-8 py-7 max-w-[1100px]">

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: '#2563eb',
              fontWeight: 500,
            }}
          >
            STEP 04
          </span>

          <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>

          <span style={{ fontSize: 11, color: '#94a3b8' }}>
            최적화 결과
          </span>
        </div>

        <h1
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: '#0f172a',
            margin: 0,
          }}
        >
          4주 구호품 배분 최적화 결과
        </h1>

        <div
          style={{
            fontSize: 12,
            color: '#64748b',
            marginTop: 6,
          }}
        >
          계획 구호소 · {summary.selected_site}
          {'  ·  '}
          구호소 이용률 ·
          {' '}
          {(
            Number(summary.utilization_rate ?? 0) * 100
          ).toFixed(0)}%
          {'  ·  '}
          평균 체류기간 · {summary.stay_days}일
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4 mb-6">

        {[
          {
            label: '계획 구호소',
            value: summary.selected_site ?? '—',
            unit: '',
            sub: '선택 구호소',
            color: '#2563eb',
          },

          {
            label: '4주 총 구호소 이용자',
            value: comma(totalSupportedPeople),
            unit: '명',
            sub: '예측값 × 이용률',
            color: '#7c3aed',
          },

          {
            label: '전체 수요 충족률',
            value: (overallFulfillment * 100).toFixed(1),
            unit: '%',
            sub:
              overallFulfillment >= 0.97
                ? '높은 충족 수준'
                : '미충족 수요 존재',
            color: fulfillColor(overallFulfillment),
          },

          {
            label: result.model_info?.logistics_enabled ? '총 조달·운송·폐기비' : '총 조달비용',
            value: `$${comma(totalCost)}`,
            unit: '',
            sub: `잔여 예산 $${comma(budgetRemaining)}`,
            color: '#475569',
          },
        ].map(k => (
          <div
            key={k.label}
            style={{
              ...card,
              padding: '16px 20px',
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: '#64748b',
                fontWeight: 600,
                marginBottom: 8,
              }}
            >
              {k.label}
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 4,
                marginBottom: 4,
              }}
            >
              <span
                style={{
                  fontSize: 25,
                  fontWeight: 700,
                  color: k.color,
                  letterSpacing: '-0.5px',
                  fontFamily:
                    "'JetBrains Mono', monospace",
                }}
              >
                {k.value}
              </span>

              {k.unit && (
                <span
                  style={{
                    fontSize: 13,
                    color: '#94a3b8',
                  }}
                >
                  {k.unit}
                </span>
              )}
            </div>

            <div
              style={{
                fontSize: 11,
                color: '#94a3b8',
              }}
            >
              {k.sub}
            </div>
          </div>
        ))}
      </div>

      {result.model_info?.road_network_enabled && <RoadResults result={result} />}
      {result.model_info?.logistics_enabled && <div style={{ ...card, marginBottom: 20, overflowX: 'auto' }}>
        <div style={cardTitle}>운송과 재고 기한</div>
        <p style={cardSub}>조달 ${comma(summary.total_procurement_cost ?? 0)} · 운송 ${comma(summary.transport_cost ?? 0)} · 폐기 ${comma(summary.disposal_cost ?? 0)}. 폐기 예정량은 현장 승인 및 실제 처리 확인이 필요합니다.</p>
        {!result.model_info?.road_network_enabled && <table style={{ width: '100%', textAlign: 'left', fontSize: 12 }}><thead><tr><th>노선</th><th>출발 주</th><th>통과 주</th><th>도착 주</th><th>출발 횟수</th><th>kg</th><th>m³</th></tr></thead><tbody>
          {(result.transport_plan ?? []).filter((r: any) => r.trips > 0).map((r: any) => <tr key={`${r.route}:${r.week}`}><td>{r.route}</td><td>{r.week}</td><td>{r.crossing_week ?? '—'}</td><td>{r.arrival_week}</td><td>{r.trips}</td><td>{comma(r.weight_kg)}</td><td>{Number(r.volume_m3).toFixed(2)}</td></tr>)}
        </tbody></table>}
        <table style={{ width: '100%', textAlign: 'left', fontSize: 12, marginTop: 16 }}><thead><tr><th>주</th><th>품목</th><th>발주량</th><th>만료량</th><th>폐기량</th><th>격리 잔여량</th></tr></thead><tbody>
          {plan.map((p: any) => <tr key={`${p.item}:${p.week}`}><td>{p.week}</td><td>{itemLabels[p.item]} ({itemUnits[p.item]})</td><td>{comma(p.recommended_order ?? 0)}</td><td>{comma(p.expired_quantity ?? 0)}</td><td>{comma(p.disposed_quantity ?? 0)}</td><td>{comma(p.quarantined_inventory ?? 0)}</td></tr>)}
        </tbody></table>
      </div>}
      {/* 주별 결과 */}
      <div className="mb-2">
        <SectionLabel label="주차별 최적화 결과" />
      </div>

      <div
        style={{
          ...card,
          marginBottom: 20,
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
          }}
        >
          <thead>
            <tr
              style={{
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <th style={th}>주차</th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                예측 유입량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                구호소 이용자
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                최저 품목 충족률
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'center',
                }}
              >
                미충족 품목
              </th>
            </tr>
          </thead>

          <tbody>
            {weeklySummary.map((row, i) => (
              <tr
                key={row.week}
                onClick={() => setResultWeek(i)}
                style={{
                  borderBottom:
                    i < weeklySummary.length - 1
                      ? '1px solid #f8fafc'
                      : 'none',
                  cursor: 'pointer',
                  background:
                    resultWeek === i
                      ? '#fafbff'
                      : 'transparent',
                }}
              >
                <td style={td}>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '2px 8px',
                      borderRadius: 4,
                      fontSize: 11,
                      fontWeight: 700,
                      background: '#eff6ff',
                      color: '#2563eb',
                    }}
                  >
                    {row.week}주차
                  </span>
                </td>

                <td
                  style={{
                    ...td,
                    textAlign: 'right',
                    fontFamily:
                      "'JetBrains Mono', monospace",
                  }}
                >
                  {comma(row.forecast)}명
                </td>

                <td
                  style={{
                    ...td,
                    textAlign: 'right',
                    fontFamily:
                      "'JetBrains Mono', monospace",
                  }}
                >
                  {comma(row.supportedPeople)}명
                </td>

                <td
                  style={{
                    ...td,
                    textAlign: 'right',
                  }}
                >
                  <span
                    style={{
                      fontFamily:
                        "'JetBrains Mono', monospace",
                      fontWeight: 700,
                      color: fulfillColor(
                        row.minFulfillment
                      ),
                    }}
                  >
                    {(
                      row.minFulfillment * 100
                    ).toFixed(1)}%
                  </span>
                </td>

                <td
                  style={{
                    ...td,
                    textAlign: 'center',
                  }}
                >
                  {row.shortageCount === 0 ? (
                    <span
                      style={{
                        padding: '2px 9px',
                        borderRadius: 20,
                        fontSize: 11,
                        fontWeight: 700,
                        background: '#f0fdf4',
                        border: '1px solid #bbf7d0',
                        color: '#166534',
                      }}
                    >
                      없음
                    </span>
                  ) : (
                    <span
                      style={{
                        padding: '2px 9px',
                        borderRadius: 20,
                        fontSize: 11,
                        fontWeight: 700,
                        background: '#fef2f2',
                        border: '1px solid #fecaca',
                        color: '#991b1b',
                      }}
                    >
                      {row.shortageCount}개
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 물품 배분 */}
      <div className="mb-2">
        <SectionLabel label="주차별 물품 배분 계획" />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 6,
          marginBottom: 12,
        }}
      >
        {weeks.map((week, i) => (
          <button
            key={week}
            onClick={() => setResultWeek(i)}
            style={{
              padding: '7px 18px',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              border: `1.5px solid ${
                resultWeek === i
                  ? '#2563eb'
                  : '#e2e8f0'
              }`,
              background:
                resultWeek === i
                  ? '#eff6ff'
                  : '#f8fafc',
              color:
                resultWeek === i
                  ? '#1e40af'
                  : '#64748b',
            }}
          >
            {week}주차
          </button>
        ))}
      </div>

      <div
        style={{
          ...card,
          marginBottom: 20,
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
          }}
        >
          <thead>
            <tr
              style={{
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <th style={th}>품목</th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                필요량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                추천 공급량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                계획 충족량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                미충족
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                기말재고
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                충족률
              </th>
            </tr>
          </thead>

          <tbody>
            {weekPlan.map((row: any, i: number) => {
              const fr =
                Number(row.fulfillment_rate ?? 0)

              return (
                <tr
                  key={`${row.item}-${row.week}`}
                  style={{
                    borderBottom:
                      i < weekPlan.length - 1
                        ? '1px solid #f8fafc'
                        : 'none',
                  }}
                >
                  <td
                    style={{
                      ...td,
                      fontWeight: 600,
                    }}
                  >
                    {itemLabels[row.item] ?? row.item}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      fontFamily:
                        "'JetBrains Mono', monospace",
                    }}
                  >
                    {comma(Number(row.demand ?? 0))}
                    {' '}
                    {itemUnits[row.item] ?? row.unit}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      fontFamily:
                        "'JetBrains Mono', monospace",
                      fontWeight: 700,
                      color: '#2563eb',
                    }}
                  >
                    {comma(
  Number(
    row.recommended_shipment ?? 0
  )
)}
                      
                        
                      
                    
                    {' '}
                    {itemUnits[row.item] ?? row.unit}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      fontFamily:
                        "'JetBrains Mono', monospace",
                    }}
                  >
                    {comma(Number(row.served ?? 0))}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      fontFamily:
                        "'JetBrains Mono', monospace",
                      color:
  Number(row.unmet_demand ?? 0) >= 0.5
    ? '#dc2626'
    : '#16a34a',
                    }}
                  >
                    {comma(
                      Number(row.unmet_demand ?? 0)
                    )}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                      fontFamily:
                        "'JetBrains Mono', monospace",
                    }}
                  >
                    {comma(
                      Number(row.ending_inventory ?? 0)
                    )}
                  </td>

                  <td
                    style={{
                      ...td,
                      textAlign: 'right',
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 700,
                        color: fulfillColor(fr),
                      }}
                    >
                      {(fr * 100).toFixed(1)}%
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 4주 품목 요약 */}
      <div className="mb-2">
        <SectionLabel label="품목별 4주 수요 충족 현황" />
      </div>

      <div
        style={{
          ...card,
          marginBottom: 20,
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
          }}
        >
          <thead>
            <tr
              style={{
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <th style={th}>품목</th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                총 수요
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                총 충족량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                총 미충족량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                충족률
              </th>
            </tr>
          </thead>

          <tbody>
            {itemSummary.map(
              (row: any, i: number) => {
                const fr =
                  Number(row.fulfillment_rate ?? 0)

                return (
                  <tr
                    key={row.item}
                    style={{
                      borderBottom:
                        i < itemSummary.length - 1
                          ? '1px solid #f8fafc'
                          : 'none',
                    }}
                  >
                    <td
                      style={{
                        ...td,
                        fontWeight: 600,
                      }}
                    >
                      {itemLabels[row.item] ?? row.item}
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontFamily:
                          "'JetBrains Mono', monospace",
                      }}
                    >
                      {comma(
                        Number(row.total_demand ?? 0)
                      )}
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontFamily:
                          "'JetBrains Mono', monospace",
                      }}
                    >
                      {comma(
                        Number(row.total_served ?? 0)
                      )}
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontFamily:
                          "'JetBrains Mono', monospace",
                        color:
                         Number(row.total_unmet_demand ?? 0) >= 0.5
  ? '#dc2626'
  : '#16a34a',
                      }}
                    >
                      {comma(
                        Number(
                          row.total_unmet_demand ?? 0
                        )
                      )}
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                      }}
                    >
                      <span
                        style={{
                          fontWeight: 700,
                          color: fulfillColor(fr),
                        }}
                      >
                        {(fr * 100).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                )
              }
            )}
          </tbody>
        </table>
      </div>

      {/* 창고 */}
      <div className="mb-2">
        <SectionLabel label="창고 용량 사용 현황" />
      </div>

      <div
        style={{
          ...card,
          marginBottom: 20,
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
          }}
        >
          <thead>
            <tr
              style={{
                borderBottom: '1px solid #f1f5f9',
              }}
            >
              <th style={th}>주차</th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                최대 보관량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                창고용량
              </th>

              <th
                style={{
                  ...th,
                  textAlign: 'right',
                }}
              >
                사용률
              </th>
            </tr>
          </thead>

          <tbody>
            {warehouseSummary.map(
              (row: any, i: number) => {
                const rate =
                  Number(
                    row.warehouse_utilization_rate ?? 0
                  )

                return (
                  <tr
                    key={row.week}
                    style={{
                      borderBottom:
                        i < warehouseSummary.length - 1
                          ? '1px solid #f8fafc'
                          : 'none',
                    }}
                  >
                    <td style={td}>
                      {row.week}주차
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontFamily:
                          "'JetBrains Mono', monospace",
                      }}
                    >
                      {Number(
                        row.peak_inventory_volume_m3 ??
                          0
                      ).toFixed(2)}
                      ㎥
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontFamily:
                          "'JetBrains Mono', monospace",
                      }}
                    >
                      {Number(
                        row.warehouse_capacity_m3 ?? 0
                      ).toFixed(2)}
                      ㎥
                    </td>

                    <td
                      style={{
                        ...td,
                        textAlign: 'right',
                        fontWeight: 700,
                        color:
                          rate >= 0.9
                            ? '#dc2626'
                            : rate >= 0.75
                              ? '#d97706'
                              : '#16a34a',
                      }}
                    >
                      {(rate * 100).toFixed(1)}%
                    </td>
                  </tr>
                )
              }
            )}
          </tbody>
        </table>
      </div>

      {/* 최적화 설명 */}
      {summary.message && (
        <div
          style={{
            ...card,
            padding: '16px 20px',
            marginBottom: 20,
            background: '#f8fafc',
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: '#64748b',
              marginBottom: 7,
            }}
          >
            최적화 결과 요약
          </div>

          <div
            style={{
              fontSize: 13,
              lineHeight: 1.65,
              color: '#374151',
            }}
          >
            {summary.message}
          </div>
        </div>
      )}

      {/* Bottom */}
      <div className="flex justify-end">
        <button
          onClick={() => setActiveNav(2)}
          style={{
            padding: '9px 18px',
            borderRadius: 8,
            border: '1.5px solid #e2e8f0',
            background: '#f8fafc',
            fontSize: 13,
            fontWeight: 600,
            color: '#64748b',
            cursor: 'pointer',
          }}
        >
          구호품 계획 수정
        </button>
      </div>
    </div>
  )
})()}
      </main>
    </div>
  )
}

// ─── Small shared components ──────────────────────────────────────────────────

function SectionLabel({ label }: { label: string }) {
  return (
    <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10, paddingLeft: 2 }}>
      {label}
    </div>
  )
}

// ─── Style helpers ─────────────────────────────────────────────────────────────

function presetBtn(active: boolean): React.CSSProperties {
  return {
    padding: '6px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
    border: `1.5px solid ${active ? '#2563eb' : '#e2e8f0'}`,
    background: active ? '#eff6ff' : '#f8fafc',
    color: active ? '#1e40af' : '#64748b',
    transition: 'all 0.15s',
  }
}

const calNavBtn: React.CSSProperties = {
  padding: '4px 10px', borderRadius: 6, border: 'none', background: '#f1f5f9', cursor: 'pointer', color: '#475569', fontSize: 14,
}

const card: React.CSSProperties = {
  background: '#ffffff', borderRadius: 12, border: '1px solid #e8edf2',
  boxShadow: '0 1px 4px rgba(0,0,0,0.06)', padding: '20px 20px 18px',
}

const cardHeader: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14,
}

const cardTitle: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: '#0f172a' }
const cardSub: React.CSSProperties = { fontSize: 11, color: '#94a3b8', marginTop: 2 }

const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#94a3b8', textAlign: 'left',
  padding: '6px 8px', letterSpacing: '0.06em', textTransform: 'uppercase' as const, whiteSpace: 'nowrap' as const,
}

const td: React.CSSProperties = {
  fontSize: 13, color: '#374151', padding: '9px 8px', verticalAlign: 'middle',
}

const btnSecondary: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: '1.5px solid #e2e8f0', background: '#ffffff', fontSize: 12, fontWeight: 600, color: '#374151',
  cursor: 'pointer', boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
}

const btnGhost: React.CSSProperties = {
  padding: '8px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', background: 'transparent',
  fontSize: 12, fontWeight: 500, color: '#94a3b8', cursor: 'pointer',
}

function numInput(warning: boolean): React.CSSProperties {
  return {
    width: 90, textAlign: 'right', padding: '4px 8px', borderRadius: 6,
    border: `1.5px solid ${warning ? '#fde68a' : '#e2e8f0'}`,
    background: warning ? '#fffbeb' : '#f8fafc',
    fontSize: 13, fontWeight: 500, color: '#0f172a', outline: 'none',
    fontFamily: "'JetBrains Mono', monospace",
  }
}

function focusStyle(e: React.FocusEvent<HTMLInputElement>) {
  e.target.style.borderColor = '#2563eb'; e.target.style.background = '#eff6ff'
}
function blurStyle(e: React.FocusEvent<HTMLInputElement>) {
  e.target.style.borderColor = '#e2e8f0'; e.target.style.background = '#f8fafc'
}

