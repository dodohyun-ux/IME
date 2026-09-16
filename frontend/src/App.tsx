import { useState, useRef, useEffect, type ChangeEvent } from 'react'
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

interface InflowRow { id: number; label: string; period: string; inflow: string }
interface ConflictRow { id: number; label: string; period: string; events: string; explosive: string; civilian: string; deaths: string }
interface ForecastInterval {
  low: number
  high: number
}
// ─── Constants ─────────────────────────────────────────────────────────────────

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

const KO_MONTHS = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
const DAY_HEADERS = ['월','화','수','목','금','토','일']

// Default historical placeholder values (최근 8주, oldest→newest)
const DEFAULT_HISTORICAL = [1820, 2140, 1970, 2510, 2890, 3080, 2940, 3210]
const DEFAULT_FORECAST = [3500, 3800, 3600, 4100]

// ─── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [activeNav, setActiveNav] = useState(0)
  const [isPredicting, setIsPredicting] = useState(false)
  const today = useRef(new Date()).current
  const [refMonday, setRefMonday] = useState<Date>(() => getMondayOfWeek(today))

  // ── Step 01 state ──
  const [calOpen, setCalOpen] = useState(false)
  const [calYear, setCalYear] = useState(today.getFullYear())
  const [calMonth, setCalMonth] = useState(today.getMonth())
  const [hoverDay, setHoverDay] = useState<Date | null>(null)
  const calRef = useRef<HTMLDivElement>(null)
  const csvInputRef = useRef<HTMLInputElement>(null)
  const [inflowData, setInflowData] = useState<InflowRow[]>([])
  const [conflictData, setConflictData] = useState<ConflictRow[]>([])
  const [useConflict, setUseConflict] = useState(true)

  // ── Step 02 state ──
  const [forecastValues, setForecastValues] = useState<number[]>(DEFAULT_FORECAST)
  const [forecastIntervals, setForecastIntervals] =
  useState<(ForecastInterval | null)[]>([
    null,
    null,
    null,
    null,
  ])

  const [forecastWithConflict, setForecastWithConflict] =
  useState<number[] | null>(null)

const [forecastWithoutConflict, setForecastWithoutConflict] =
  useState<number[] | null>(null)

  const [hubForecast, setHubForecast] = useState({
  medyka: [0, 0, 0, 0],
  dorohusk: [0, 0, 0, 0],
  korczowa: [0, 0, 0, 0],
})
  const [editingWeek, setEditingWeek] = useState<number | null>(null)
  const [editTemp, setEditTemp] = useState('')
  const [utilRate, setUtilRate] = useState<number>(10)
  const [stayDuration, setStayDuration] = useState(3)

  // ── Step 03 state ──
  const [hubAllocs, setHubAllocs] = useState({ medyka: 40, dorohusk: 35, korczowa: 25 })
  const [warehouse, setWarehouse] = useState({
    food: { current: '', safety: '' },
    blanket: { current: '', safety: '' },
    hygiene: { current: '', safety: '' },
    medical: { current: '', safety: '' },
  })
  const [shelterInv, setShelterInv] = useState({
    medyka: { food: '', blanket: '', hygiene: '', medical: '' },
    dorohusk: { food: '', blanket: '', hygiene: '', medical: '' },
    korczowa: { food: '', blanket: '', hygiene: '', medical: '' },
  })
  const [restockPlan, setRestockPlan] = useState(
    Array.from({ length: 4 }, () => ({ food: '', blanket: '', hygiene: '', medical: '' }))
  )
  const [hubCapacity, setHubCapacity] = useState({ medyka: '', dorohusk: '', korczowa: '' })
  const [budget, setBudget] = useState('')
  const [maintainSafety, setMaintainSafety] = useState(true)
  const [optGoal, setOptGoal] = useState<'unmet' | 'cost' | 'balance'>('unmet')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [consumption, setConsumption] = useState({ food: '1.0', blanket: '0.1', hygiene: '1.0', medical: '0.05' })

  // ── Step 03 new state (API-ready) ──
  type SiteKey = 'medyka' | 'dorohusk' | 'korczowa'
  const [selectedSite, setSelectedSite] = useState<SiteKey>('medyka')
  const [optimizationResult, setOptimizationResult] = useState<any>(null)
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

const STORAGE_KEY = 'poland-relief-planner-data'

// 저장된 데이터 불러오기
useEffect(() => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)

    if (saved) {
      const data = JSON.parse(saved)

      if (data.activeNav !== undefined) {
        setActiveNav(data.activeNav)
      }

      if (data.refMonday) {
        setRefMonday(new Date(data.refMonday))
      }

      if (data.inflowData) {
        setInflowData(data.inflowData)
      }

      if (data.conflictData) {
        setConflictData(data.conflictData)
      }

      if (data.useConflict !== undefined) {
        setUseConflict(data.useConflict)
      }

      if (data.forecastValues) {
        setForecastValues(data.forecastValues)
      }

      if (data.forecastIntervals) {
  setForecastIntervals(data.forecastIntervals)
}

if (data.forecastWithConflict) {
  setForecastWithConflict(data.forecastWithConflict)
}

if (data.forecastWithoutConflict) {
  setForecastWithoutConflict(data.forecastWithoutConflict)
}
      if (data.hubForecast) {
        setHubForecast(data.hubForecast)
      }

      if (data.utilRate !== undefined) {
        setUtilRate(data.utilRate)
      }

      if (data.stayDuration !== undefined) {
        setStayDuration(data.stayDuration)
      }

      if (data.selectedSite) {
        setSelectedSite(data.selectedSite)
      }

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

      if (data.optimizationResult) {
        setOptimizationResult(data.optimizationResult)
      }

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
    activeNav,
    refMonday: refMonday.toISOString(),

    inflowData,
    conflictData,
    useConflict,

    forecastValues,
    hubForecast,
    utilRate,
    stayDuration,

    selectedSite,
    initialInventory,
    weeklySupplyLimits,
    itemPrices,
    itemVolumes,
    warehouseCapacities,
    budget,

    optimizationResult,
    resultWeek,
  }

  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(dataToSave)
  )
}, [
  storageLoaded,
  activeNav,
  refMonday,
  inflowData,
  conflictData,
  useConflict,
  forecastValues,
  hubForecast,
  utilRate,
  stayDuration,
  selectedSite,
  initialInventory,
  weeklySupplyLimits,
  itemPrices,
  itemVolumes,
  warehouseCapacities,
  budget,
  optimizationResult,
  resultWeek,
])

 // Rebuild Step 01 rows when reference week changes
// 기존 입력값은 유지
useEffect(() => {
  setInflowData(prev =>
    Array.from({ length: 8 }, (_, i) => {
      const start = addDays(refMonday, -i * 7)

      return {
        id: i,
        label: i === 0 ? '이번주' : `${i}주 전`,
        period: `${fmt(start)} – ${fmt(addDays(start, 6))}`,
        inflow: prev[i]?.inflow ?? '',
      }
    })
  )

  setConflictData(prev =>
    Array.from({ length: 4 }, (_, i) => {
      const start = addDays(refMonday, -i * 7)

      return {
        id: i,
        label: i === 0 ? '이번주' : `${i}주 전`,
        period: `${fmt(start)} – ${fmt(addDays(start, 6))}`,
        events: prev[i]?.events ?? '',
        explosive: prev[i]?.explosive ?? '',
        civilian: prev[i]?.civilian ?? '',
        deaths: prev[i]?.deaths ?? '',
      }
    })
  )
}, [refMonday])

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
  function selectDay(d: Date) { setRefMonday(getMondayOfWeek(d)); setCalOpen(false); setHoverDay(null) }
  function prevMo() { if (calMonth === 0) { setCalYear(y => y - 1); setCalMonth(11) } else setCalMonth(m => m - 1) }
  function nextMo() { if (calMonth === 11) { setCalYear(y => y + 1); setCalMonth(0) } else setCalMonth(m => m + 1) }
  function updateInflow(id: number, val: string) { setInflowData(prev => prev.map(r => r.id === id ? { ...r, inflow: val } : r)) }
  function updateConflict(id: number, field: keyof ConflictRow, val: string) { setConflictData(prev => prev.map(r => r.id === id ? { ...r, [field]: val } : r)) }
  function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let insideQuotes = false

  for (let i = 0; i < line.length; i++) {
    const char = line[i]

    if (char === '"') {
      if (insideQuotes && line[i + 1] === '"') {
        current += '"'
        i++
      } else {
        insideQuotes = !insideQuotes
      }
    } else if (char === ',' && !insideQuotes) {
      result.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }

  result.push(current.trim())
  return result
}

function normalizeCsvHeader(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s._·\-()]/g, '')
}

function cleanCsvNumber(value: string): string {
  return value
    .replace(/,/g, '')
    .trim()
}

function parseWeekIndex(value: string, fallback: number): number {
  const text = value.trim()

  if (text === '' || text === '이번주') {
    return text === '이번주' ? 0 : fallback
  }

  if (text === '0') return 0

  const match = text.match(/\d+/)

  if (match) {
    return Number(match[0])
  }

  return fallback
}

async function handleCsvUpload(e: ChangeEvent<HTMLInputElement>) {
  const file = e.target.files?.[0]

  if (!file) return

  try {
    const rawText = await file.text()
    const text = rawText.replace(/^\uFEFF/, '')

    const lines = text
      .split(/\r?\n/)
      .filter(line => line.trim() !== '')

    if (lines.length < 2) {
      throw new Error('CSV 파일에 데이터가 없습니다.')
    }

    const rows = lines.map(parseCsvLine)

    const headers = rows[0].map(normalizeCsvHeader)
    const dataRows = rows.slice(1)

    const findColumn = (...aliases: string[]) => {
      const normalizedAliases = aliases.map(normalizeCsvHeader)

      return headers.findIndex(header =>
        normalizedAliases.includes(header)
      )
    }

    const weekCol = findColumn(
      'week',
      '주차'
    )

    const inflowCol = findColumn(
      'inflow',
      '유입량',
      '난민유입량'
    )

    const eventsCol = findColumn(
      'events',
      '전체사건',
      '전체 사건'
    )

    const explosiveCol = findColumn(
      'explosive',
      '폭발원격',
      '폭발·원격',
      '폭발 원격'
    )

    const civilianCol = findColumn(
      'civilian',
      '민간인폭력',
      '민간인 폭력'
    )

    const deathsCol = findColumn(
      'deaths',
      '사망자'
    )

    if (inflowCol === -1) {
      throw new Error(
        'CSV에 inflow 또는 유입량 열이 필요합니다.'
      )
    }

    const conflictColumns = [
      eventsCol,
      explosiveCol,
      civilianCol,
      deathsCol,
    ]

    const hasSomeConflict =
      conflictColumns.some(col => col !== -1)

    const hasAllConflict =
      conflictColumns.every(col => col !== -1)

    if (hasSomeConflict && !hasAllConflict) {
      throw new Error(
        '분쟁정보를 넣으려면 events, explosive, civilian, deaths 열을 모두 포함해주세요.'
      )
    }

    const rowsByWeek = new Map<number, string[]>()

    dataRows.forEach((row, index) => {
      const weekIndex =
        weekCol !== -1
          ? parseWeekIndex(row[weekCol] ?? '', index)
          : index

      if (
        weekIndex >= 0 &&
        weekIndex <= 7 &&
        !rowsByWeek.has(weekIndex)
      ) {
        rowsByWeek.set(weekIndex, row)
      }
    })

    for (let week = 0; week < 8; week++) {
      if (!rowsByWeek.has(week)) {
        throw new Error(
          `${week === 0 ? '이번주' : `${week}주 전`} 유입량 데이터가 없습니다.`
        )
      }
    }

    const newInflows = inflowData.map(row => {
      const csvRow = rowsByWeek.get(row.id)!

      const value = cleanCsvNumber(
        csvRow[inflowCol] ?? ''
      )

      if (
        value === '' ||
        !Number.isFinite(Number(value))
      ) {
        throw new Error(
          `${row.label} 유입량 값이 올바르지 않습니다.`
        )
      }

      return {
        ...row,
        inflow: value,
      }
    })

    setInflowData(newInflows)

    if (hasAllConflict) {
      const newConflict = conflictData.map(row => {
        const csvRow = rowsByWeek.get(row.id)

        if (!csvRow) return row

        const events = cleanCsvNumber(
          csvRow[eventsCol] ?? ''
        )
        const explosive = cleanCsvNumber(
          csvRow[explosiveCol] ?? ''
        )
        const civilian = cleanCsvNumber(
          csvRow[civilianCol] ?? ''
        )
        const deaths = cleanCsvNumber(
          csvRow[deathsCol] ?? ''
        )

        const values = [
          events,
          explosive,
          civilian,
          deaths,
        ]

        if (
          values.some(
            value =>
              value === '' ||
              !Number.isFinite(Number(value))
          )
        ) {
          throw new Error(
            `${row.label} 분쟁정보 값이 올바르지 않습니다.`
          )
        }

        return {
          ...row,
          events,
          explosive,
          civilian,
          deaths,
        }
      })

      setConflictData(newConflict)
    }

    alert('CSV 데이터를 불러왔습니다.')
  } catch (error) {
    console.error(error)

    alert(
      error instanceof Error
        ? error.message
        : 'CSV 파일을 읽는 중 오류가 발생했습니다.'
    )
  }

  e.target.value = ''
}
  function handleReset() {
    setInflowData(prev => prev.map(r => ({ ...r, inflow: '' })))
    setConflictData(prev => prev.map(r => ({ ...r, events: '', explosive: '', civilian: '', deaths: '' })))
  }
async function runPrediction() {
  try {
    const inflows = inflowData.map(r => Number(r.inflow))

    if (inflowData.some(r => r.inflow.trim() === '')) {
      alert('최근 8주 유입량을 모두 입력해주세요.')
      return
    }

    if (
      useConflict &&
      conflictData.some(r =>
        [r.events, r.explosive, r.civilian, r.deaths]
          .some(v => v.trim() === '')
      )
    ) {
      alert('최근 4주 분쟁정보를 모두 입력해주세요.')
      return
    }
    setIsPredicting(true)

    const referenceDate =
      `${refMonday.getFullYear()}-` +
      `${String(refMonday.getMonth() + 1).padStart(2, '0')}-` +
      `${String(refMonday.getDate()).padStart(2, '0')}`

    const requestPrediction = async (
  withConflict: boolean
) => {
  const response = await fetch(
    'http://127.0.0.1:8000/predict',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        reference_date: referenceDate,
        inflow: inflows,
        use_conflict: withConflict,

        conflict: conflictData.map(r => ({
          events: Number(r.events || 0),
          explosive: Number(r.explosive || 0),
          civilian: Number(r.civilian || 0),
          deaths: Number(r.deaths || 0),
        })),
      }),
    }
  )

  if (!response.ok) {
    const errorText = await response.text()
    console.error(errorText)
    throw new Error('예측 요청 실패')
  }

  return response.json()
}

let data: any
let comparisonData: any = null

if (useConflict) {
  const [
    withConflictData,
    withoutConflictData,
  ] = await Promise.all([
    requestPrediction(true),
    requestPrediction(false),
  ])

  // 실제 STEP 02에 표시할 결과
  data = withConflictData

  // 비교 카드에 사용할 "유입 데이터만" 결과
  comparisonData = withoutConflictData
} else {
  data = await requestPrediction(false)
}

    const newForecast = [
      Number(data.week1),
      Number(data.week2),
      Number(data.week3),
      Number(data.week4),
    ]
  if (useConflict && comparisonData) {
  const withoutConflictForecast = [
    Number(comparisonData.week1),
    Number(comparisonData.week2),
    Number(comparisonData.week3),
    Number(comparisonData.week4),
  ]

  setForecastWithConflict(newForecast)
  setForecastWithoutConflict(
    withoutConflictForecast
  )
} else {
  setForecastWithConflict(null)
  setForecastWithoutConflict(null)
}

    console.log('실제 joblib 예측값:', newForecast)
    console.log('구호소별 예측:', data.hub_forecast)
setHubForecast({
  medyka: data.hub_forecast?.medyka ?? [0, 0, 0, 0],
  dorohusk: data.hub_forecast?.dorohusk ?? [0, 0, 0, 0],
  korczowa: data.hub_forecast?.korczowa ?? [0, 0, 0, 0],
})
    console.log('예측구간:', data.intervals)

const newIntervals: (ForecastInterval | null)[] =
  Array.from({ length: 4 }, (_, i) => {
    const interval = data.intervals?.[i]

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
  })

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
  try {
    const siteNames: Record<SiteKey, string> = {
      medyka: 'Medyka',
      dorohusk: 'Dorohusk',
      korczowa: 'Korczowa',
    }

    const apiSite = siteNames[selectedSite]
    const forecast = hubForecast[selectedSite]
    const inventory = initialInventory[selectedSite]

    if (!forecast || forecast.every(v => Number(v) === 0)) {
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
    }

    console.log('최적화 요청값:', requestBody)

    const response = await fetch(
      'http://127.0.0.1:8000/optimize',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      }
    )

    if (!response.ok) {
      const errorText = await response.text()
      console.error('최적화 서버 오류:', errorText)
      throw new Error(errorText)
    }

    const result = await response.json()

    console.log('실제 최적화 결과:', result)

   setOptimizationResult(result)
   setResultWeek(0)
   setActiveNav(3)

  } catch (error) {
    console.error(error)

    alert(
      '최적화 실행 중 오류가 발생했습니다. 백엔드 터미널을 확인해주세요.'
    )
  }
}
  const missingInflow = inflowData.filter(r => r.inflow.trim() === '').length
  const missingConflict = useConflict ? conflictData.filter(r => [r.events, r.explosive, r.civilian, r.deaths].some(v => v.trim() === '')).length : 0
  const filledInflows = inflowData.map((r, i) => ({ v: Number(r.inflow), filled: r.inflow.trim() !== '' }))
  const outlierCount = filledInflows.filter(x => x.filled && (x.v < 0 || x.v > 500000)).length
  const totalMissing = missingInflow + missingConflict
  const isReady = totalMissing === 0 && outlierCount === 0

  const weekNum = getISOWeekNumber(refMonday)
  const weekEnd = addDays(refMonday, 6)
  const calDays = buildDays(calYear, calMonth)

  // ── Step 02 helpers ──
  const effectiveUtil = utilRate
  const forecastStart = addDays(refMonday, 7) // 1주차 starts the week after reference

  // Chart data: 8 historical + 4 forecast (connecting at boundary)
  const historicalVals = inflowData.map((r, i) => {
    const filled = r.inflow.trim() !== ''
    return filled ? Number(r.inflow) : DEFAULT_HISTORICAL[7 - i] // inflowData[0] is most recent
  }).reverse() // oldest first

  const chartData = [
    // 8 historical points (oldest to newest)
    ...historicalVals.map((v, i) => {
      const start = addDays(refMonday, -(7 - i) * 7)
      return {
  label: i === 7 ? '이번주' : `${7 - i}주 전`,
  actual: v,
  forecast: i === 7 ? v : null,
  interval: null,
  isHistory: true,
}
    }),
    // 4 forecast points
    ...forecastValues.map((v, i) => {
  const start = addDays(forecastStart, i * 7)
  const interval = forecastIntervals[i]

  return {
    label: `${i + 1}주 후`,
    actual: null,
    forecast: v,
    interval: interval
      ? [interval.low, interval.high]
      : null,
    isHistory: false,
  }
}),
  ]
  // The boundary: index 7 has both actual and forecast

  function startEdit(i: number) {
    setEditingWeek(i)
    setEditTemp(String(forecastValues[i]))
  }
  function confirmEdit(i: number) {
  const v = parseFloat(editTemp)

  if (!isNaN(v) && v >= 0) {
    setForecastValues(prev =>
      prev.map((x, j) =>
        j === i ? Math.round(v) : x
      )
    )

    setForecastIntervals(prev =>
      prev.map((interval, j) =>
        j === i ? null : interval
      )
    )
    setForecastWithConflict(null)
setForecastWithoutConflict(null)
  }

  setEditingWeek(null)
}

  // Weekly demand calculations
  function weekDemand(forecastVal: number) {
    const shelterUsers = forecastVal * (effectiveUtil / 100)
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
      <main className="flex-1 overflow-y-auto">

        {/* ═══════════════════════════════════════ STEP 01 ═══════════════════════════════════════ */}
        {activeNav === 0 && (
          <div className="px-8 py-7 max-w-[1100px]">
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-1">
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#2563eb', fontWeight: 500 }}>STEP 01</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>·</span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>데이터 입력</span>
              </div>
              <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, lineHeight: 1.3 }}>최근 유입량 및 분쟁정보 입력</h1>
              <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>최근 주별 데이터를 기반으로 향후 4주 난민 유입량을 예측합니다.</p>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-3 mb-5">
              <div className="relative" ref={calRef}>
                <button onClick={() => setCalOpen(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', borderRadius: 10, border: '1.5px solid #e2e8f0', background: calOpen ? '#eff6ff' : '#ffffff', cursor: 'pointer', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
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
                        const inRef = inRefWeek(d); const inHov = inHoverWeek(d)
                        const isToday = sameDay(d, today); const inCurMo = d.getMonth() === calMonth
                        const isRefMon = sameDay(d, getMondayOfWeek(refMonday)); const isRefSun = sameDay(d, addDays(getMondayOfWeek(refMonday), 6))
                        const isHovMon = hoverDay ? sameDay(d, getMondayOfWeek(hoverDay)) : false; const isHovSun = hoverDay ? sameDay(d, addDays(getMondayOfWeek(hoverDay), 6)) : false
                        let bg = 'transparent', textColor = inCurMo ? '#374151' : '#d1d5db', br = '6px'
                        if (inRef) { bg = '#dbeafe'; textColor = '#1e40af'; br = isRefMon ? '6px 0 0 6px' : isRefSun ? '0 6px 6px 0' : '0' }
                        else if (inHov) { bg = '#f0fdf4'; textColor = '#166534'; br = isHovMon ? '6px 0 0 6px' : isHovSun ? '0 6px 6px 0' : '0' }
                        return (
                          <div key={idx} onClick={() => selectDay(d)} onMouseEnter={() => setHoverDay(d)} onMouseLeave={() => setHoverDay(null)}
                            style={{ textAlign: 'center', fontSize: 12, padding: '5px 2px', cursor: 'pointer', borderRadius: br, background: bg, color: textColor, fontWeight: isToday ? 700 : 400, position: 'relative' }}>
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
                  </div>
                )}
              </div>

              <div style={{ flex: 1 }} />
            <input
  ref={csvInputRef}
  type="file"
  accept=".csv,text/csv"
  onChange={handleCsvUpload}
  style={{ display: 'none' }}
/>

<button
  onClick={() => csvInputRef.current?.click()}
  style={btnSecondary}
>
  <svg
    width="13"
    height="13"
    viewBox="0 0 13 13"
    fill="none"
  >
    <path
      d="M2 7.5V10.5H5L10.5 5 7.5 2 2 7.5Z"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinejoin="round"
    />
  </svg>
  CSV 업로드
</button>
            
              <button onClick={handleReset} style={btnGhost}>초기화</button>
            </div>

            {/* Cards */}
            <div className="grid grid-cols-2 gap-5 mb-4">
              {/* LEFT */}
              <div style={card}>
                <div style={cardHeader}>
                  <div><div style={cardTitle}>난민 유입량</div><div style={cardSub}>이번주 포함 8주</div></div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#94a3b8', alignSelf: 'flex-end' }}>단위: 명</div>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <th style={th}>주차</th><th style={th}>기간</th><th style={{ ...th, textAlign: 'right' }}>유입량 (명)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inflowData.map((row, idx) => {
                      const missing = row.inflow.trim() === ''
                      const outlier = row.inflow.trim() !== '' && (Number(row.inflow) < 0 || Number(row.inflow) > 500000)
                      return (
                        <tr key={row.id} style={{ borderBottom: idx < inflowData.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                          <td style={td}><span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: idx === 0 ? '#eff6ff' : '#f8fafc', color: idx === 0 ? '#2563eb' : '#64748b' }}>{row.label}</span></td>
                          <td style={{ ...td, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#94a3b8' }}>{row.period}</td>
                          <td style={{ ...td, textAlign: 'right' }}>
                            <input type="number" value={row.inflow} onChange={e => updateInflow(row.id, e.target.value)} placeholder="—"
                              style={{ width: 100, textAlign: 'right', padding: '4px 8px', borderRadius: 6, border: `1.5px solid ${outlier ? '#fca5a5' : missing ? '#fde68a' : '#e2e8f0'}`, background: outlier ? '#fef2f2' : missing ? '#fffbeb' : '#f8fafc', fontSize: 13, fontWeight: 500, color: '#0f172a', outline: 'none', fontFamily: "'JetBrains Mono', monospace" }}
                              onFocus={e => { e.target.style.borderColor = '#2563eb'; e.target.style.background = '#eff6ff' }}
                              onBlur={e => { const v = e.target.value; const out = v !== '' && (Number(v) < 0 || Number(v) > 500000); e.target.style.borderColor = out ? '#fca5a5' : v === '' ? '#fde68a' : '#e2e8f0'; e.target.style.background = out ? '#fef2f2' : v === '' ? '#fffbeb' : '#f8fafc' }}
                            />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* RIGHT */}
              <div style={card}>
                <div style={cardHeader}>
                  <div><div style={cardTitle}>우크라이나 분쟁정보</div><div style={cardSub}>이번주 포함 4주</div></div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: '#94a3b8', alignSelf: 'flex-end' }}>ACLED 기준</div>
                </div>
                <div style={{ opacity: useConflict ? 1 : 0.4, transition: 'opacity 0.2s', overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 420 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <th style={th}>주차</th>
                        <th style={{ ...th, textAlign: 'right' }}>전체 사건</th>
                        <th style={{ ...th, textAlign: 'right' }}>폭발·원격</th>
                        <th style={{ ...th, textAlign: 'right' }}>민간인 폭력</th>
                        <th style={{ ...th, textAlign: 'right' }}>사망자</th>
                      </tr>
                    </thead>
                    <tbody>
                      {conflictData.map((row, idx) => (
                        <tr key={row.id} style={{ borderBottom: idx < conflictData.length - 1 ? '1px solid #f8fafc' : 'none' }}>
                          <td style={td}><span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: idx === 0 ? '#eff6ff' : '#f8fafc', color: idx === 0 ? '#2563eb' : '#64748b' }}>{row.label}</span></td>
                          {(['events','explosive','civilian','deaths'] as const).map(field => (
                            <td key={field} style={{ ...td, textAlign: 'right' }}>
                              <input type="number" value={row[field]} onChange={e => updateConflict(row.id, field, e.target.value)} disabled={!useConflict} placeholder="—"
                                style={{ width: 68, textAlign: 'right', padding: '4px 6px', borderRadius: 6, border: `1.5px solid ${row[field].trim() === '' && useConflict ? '#fde68a' : '#e2e8f0'}`, background: row[field].trim() === '' && useConflict ? '#fffbeb' : '#f8fafc', fontSize: 12, fontWeight: 500, color: '#0f172a', outline: 'none', fontFamily: "'JetBrains Mono', monospace", cursor: useConflict ? 'text' : 'not-allowed' }}
                                onFocus={e => { e.target.style.borderColor = '#2563eb'; e.target.style.background = '#eff6ff' }}
                                onBlur={e => { const v = e.target.value; e.target.style.borderColor = v === '' && useConflict ? '#fde68a' : '#e2e8f0'; e.target.style.background = v === '' && useConflict ? '#fffbeb' : '#f8fafc' }}
                              />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ marginTop: 20, borderTop: '1px solid #f1f5f9', paddingTop: 14, display: 'flex', gap: 6 }}>
                  {[
                    { val: true, label: '유입 + 분쟁 데이터 사용' },
                    { val: false, label: '유입 데이터만 사용' },
                  ].map(opt => (
                    <button key={String(opt.val)} onClick={() => setUseConflict(opt.val)}
                      style={{ flex: 1, padding: '7px 0', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: `1.5px solid ${useConflict === opt.val ? '#2563eb' : '#e2e8f0'}`, background: useConflict === opt.val ? '#eff6ff' : '#f8fafc', color: useConflict === opt.val ? '#1e40af' : '#64748b', transition: 'all 0.15s' }}>
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Data quality */}
            <div style={{ background: '#ffffff', borderRadius: 10, padding: '12px 20px', border: '1px solid #e8edf2', boxShadow: '0 1px 3px rgba(0,0,0,0.05)', display: 'flex', alignItems: 'center', gap: 0, marginBottom: 5 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', marginRight: 20, whiteSpace: 'nowrap', letterSpacing: '0.04em' }}>데이터 품질</div>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
                {[
                  { label: '결측', ok: totalMissing === 0, detail: totalMissing === 0 ? '없음' : `${totalMissing}개` },
                  { label: '이상치', ok: outlierCount === 0, detail: outlierCount === 0 ? '없음' : `${outlierCount}개` },
                  { label: '기간 일치', ok: true, detail: '8주 연속' },
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
      ? '실제 유입'
      : '예측 유입',
  ]
}}
                    />
                    <ReferenceLine x="이번주" stroke="#e2e8f0" strokeDasharray="4 3" />
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
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div style={{ display: 'flex', gap: 20, marginTop: 10, justifyContent: 'flex-end' }}>
                {[{ color: '#64748b', dash: false, label: '최근 8주 실제 유입' }, { color: '#2563eb', dash: true, label: '향후 4주 예측' }].map(l => (
                  <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <svg width="20" height="4"><line x1="0" y1="2" x2="20" y2="2" stroke={l.color} strokeWidth="2" strokeDasharray={l.dash ? '5 3' : 'none'} /></svg>
                    <span style={{ fontSize: 11, color: '#64748b' }}>{l.label}</span>
                  </div>
                ))}
              </div>
            </div>
            {/* ── 분쟁정보 반영 효과 비교 ── */}
            {forecastWithConflict &&
              forecastWithoutConflict &&
              (() => {
                const withTotal =
                  forecastWithConflict.reduce(
                    (sum, value) => sum + value,
                    0
                  )

                const withoutTotal =
                  forecastWithoutConflict.reduce(
                    (sum, value) => sum + value,
                    0
                  )

                const difference =
                  withTotal - withoutTotal

                const percentage =
                  withoutTotal > 0
                    ? (difference / withoutTotal) * 100
                    : 0

                const isIncrease = difference > 0
                const isDecrease = difference < 0

                return (
                  <div
                    style={{
                      ...card,
                      marginBottom: 12,
padding: '10px 14px',
                    }}
                  >
                    {/* 제목 */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: 8,
                      }}
                    >
                      <div>
                        <div
                          style={{
                            fontSize: 11,
                            fontWeight: 700,
                            color: '#0f172a',
                          }}
                        >
                          분쟁정보 반영 효과
                        </div>

                        <div
                          style={{
                            fontSize: 11,
                            color: '#94a3b8',
                            marginTop: 3,
                          }}
                        >
                          동일한 최근 유입량에서 분쟁정보 반영 여부에 따른
                          향후 4주 예측 비교
                        </div>
                      </div>

                      <div
                        style={{
                          padding: '4px 9px',
                          borderRadius: 6,
                          background: '#eff6ff',
                          color: '#2563eb',
                          fontSize: 8,
                          fontWeight: 700,
                        }}
                      >
                        MODEL COMPARISON
                      </div>
                    </div>

                    {/* 비교 영역 */}
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 36px 1fr 1fr',
                        gap: 12,
                        alignItems: 'center',
                      }}
                    >
                      {/* 유입 데이터만 */}
                      <div
                        style={{
padding: '6px 10px',                          background: '#f8fafc',
                          borderRadius: 7,
                          border: '1px solid #e2e8f0',
                        }}
                      >
                        <div
                          style={{
                            fontSize: 11,
                            color: '#64748b',
                            marginBottom: 6,
                          }}
                        >
                          유입 데이터만
                        </div>

                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: '#334155',
                            fontFamily:
                              "'JetBrains Mono', monospace",
                          }}
                        >
                          {comma(withoutTotal)}
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 400,
                              marginLeft: 4,
                            }}
                          >
                            명
                          </span>
                        </div>
                      </div>

                      {/* 화살표 */}
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 20,
                          color: '#94a3b8',
                        }}
                      >
                        →
                      </div>

                      {/* 유입 + 분쟁 */}
                      <div
                        style={{
padding: '8px 10px',                          background: '#eff6ff',
                          borderRadius: 10,
                          border: '1px solid #bfdbfe',
                        }}
                      >
                        <div
                          style={{
                            fontSize: 11,
                            color: '#2563eb',
                            fontWeight: 600,
                            marginBottom: 6,
                          }}
                        >
                          유입 + 분쟁 데이터
                        </div>

                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: '#1d4ed8',
                            fontFamily:
                              "'JetBrains Mono', monospace",
                          }}
                        >
                          {comma(withTotal)}
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 400,
                              marginLeft: 4,
                            }}
                          >
                            명
                          </span>
                        </div>
                      </div>

                      {/* 변화량 */}
                      <div
                        style={{
padding: '6px 10px',                          borderRadius: 10,

                          background: isIncrease
                            ? '#fff7ed'
                            : isDecrease
                            ? '#f0fdf4'
                            : '#f8fafc',

                          border: isIncrease
                            ? '1px solid #fed7aa'
                            : isDecrease
                            ? '1px solid #bbf7d0'
                            : '1px solid #e2e8f0',
                        }}
                      >
                        <div
                          style={{
                            fontSize: 11,
                            color: '#64748b',
                            marginBottom: 6,
                          }}
                        >
                          예측 변화
                        </div>

                        <div
                          style={{
                            fontSize: 13,
                            fontWeight: 700,

                            color: isIncrease
                              ? '#ea580c'
                              : isDecrease
                              ? '#16a34a'
                              : '#64748b',

                            fontFamily:
                              "'JetBrains Mono', monospace",
                          }}
                        >
                          {difference > 0 ? '+' : ''}
                          {comma(difference)}
                          <span
                            style={{
                              fontSize: 11,
                              marginLeft: 4,
                            }}
                          >
                            명
                          </span>
                        </div>

                        <div
                          style={{
                            marginTop: 3,
                            fontSize: 11,
                            fontWeight: 600,

                            color: isIncrease
                              ? '#ea580c'
                              : isDecrease
                              ? '#16a34a'
                              : '#64748b',
                          }}
                        >
                          {percentage > 0 ? '+' : ''}
                          {percentage.toFixed(1)}%
                        </div>
                      </div>
                    </div>

                    {/* 설명 */}
                    <div
                      style={{
                        marginTop: 12,
                        paddingTop: 12,
                        borderTop: '1px solid #f1f5f9',
                        fontSize: 11,
                        color: '#64748b',
                      }}
                    >
                      {difference > 0
                        ? `분쟁정보를 반영한 경우 향후 4주 예상 유입량이 ${comma(
                            Math.abs(difference)
                          )}명 증가했습니다.`
                        : difference < 0
                        ? `분쟁정보를 반영한 경우 향후 4주 예상 유입량이 ${comma(
                            Math.abs(difference)
                          )}명 감소했습니다.`
                        : '분쟁정보 반영 여부에 따른 예측 차이가 없습니다.'}
                    </div>
                  </div>
                )
              })()}

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
          const numSel = 1
          const weekDemands = forecastValues.map(v => weekDemand(v))
          const maxWeeklyShelter = Math.max(...weekDemands.map(d => d.shelterUsers))
          const hubPeakUsers = maxWeeklyShelter / numSel  // equal split preview

          const HUB_CFG3 = [
            { key: 'medyka' as HK, name: 'Medyka', color: '#0d9488', bg: '#f0fdfa', border: '#a7f3d0' },
            { key: 'dorohusk' as HK, name: 'Dorohusk', color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe' },
            { key: 'korczowa' as HK, name: 'Korczowa', color: '#ea580c', bg: '#fff7ed', border: '#fed7aa' },
          ]
          const NEW_ITEMS = [
            { id: 'water' as IK, label: '물', unit: 'L', pUnit: 'USD/L', vUnit: '㎥/L' },
            { id: 'food' as IK, label: '식량', unit: '팩', pUnit: 'USD/팩', vUnit: '㎥/팩' },
            { id: 'blanket' as IK, label: '담요', unit: '개', pUnit: 'USD/개', vUnit: '㎥/개' },
            { id: 'hygiene' as IK, label: '위생키트', unit: '개', pUnit: 'USD/개', vUnit: '㎥/개' },
          ]
          function setInv(hub: HK, item: IK, val: string) {
            setInitialInventory(prev => ({ ...prev, [hub]: { ...prev[hub], [item]: val } }))
          }
          function setSupply(week: number, item: IK, val: string) {
            setWeeklySupplyLimits(prev => prev.map((r, i) => i === week ? { ...r, [item]: val } : r))
          }
          const canOptimize = selectedKeys.length > 0

          // Demand preview per hub (equal allocation, for card display only)
          const hubWaterDemand = hubPeakUsers * stayDuration * 15
          const hubFoodDemand = hubPeakUsers

          const FAKE_allocTotal = 100 // kept for Step 04 compat (hubAllocs unchanged)

          const ITEMS = [
            { id: 'food' as const, label: '식량 키트' },
            { id: 'blanket' as const, label: '담요' },
            { id: 'hygiene' as const, label: '위생 키트' },
            { id: 'medical' as const, label: '의료 키트' },
          ]

          void FAKE_allocTotal // suppress unused warning

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
              </div>

              {/* ── S1: 계획 대상 구호소 선택 ── */}
              <div className="mb-2"><SectionLabel label="계획 대상 구호소 선택" /></div>
              {/* Hub selection cards */}
              <div className="grid grid-cols-3 gap-4 mb-2">
                {HUB_CFG3.map(h => {
                  const sel = selectedSite === h.key
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
                          {comma(hubPeakUsers)}<span style={{ fontSize: 12, fontWeight: 400, color: '#64748b', marginLeft: 3 }}>명</span>
                        </div>
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
                <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 12 }}>전체 3개 구호소 합산 주별 조달 한도 (A_it)</div>
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
                </div>
                {/* Advanced: kept for Step 04 compat */}
                <div style={{ marginTop: 16, borderTop: '1px solid #f1f5f9', paddingTop: 14 }}>
                  <button onClick={() => setAdvancedOpen(v => !v)}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ transform: advancedOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s', color: '#64748b' }}>
                      <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    <span style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>고급 설정 · 물품 필요량 기준</span>
                  </button>
                  {advancedOpen && (
                    <div style={{ marginTop: 12, padding: '8px 10px', background: '#f8fafc', borderRadius: 10, border: '1px solid #e8edf2' }}>
                      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10 }}>1인당 소모량 (내부 계산용)</div>
                      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                        {(['food','blanket','hygiene','medical'] as const).map(k => (
                          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 12, color: '#475569', width: 60 }}>{{ food:'식량', blanket:'담요', hygiene:'위생', medical:'의료' }[k]}</span>
                            <input type="number" value={consumption[k]} onChange={e => setConsumption(prev => ({ ...prev, [k]: e.target.value }))}
                              style={{ width: 60, padding: '4px 8px', borderRadius: 6, border: '1.5px solid #e2e8f0', background: '#ffffff', fontSize: 12, fontWeight: 600, color: '#374151', outline: 'none', fontFamily: "'JetBrains Mono', monospace", textAlign: 'right' }} />
                            <span style={{ fontSize: 11, color: '#94a3b8' }}>개/인</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* CTA */}
              <div className="flex justify-end">
                <button onClick={runOptimization}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 32px', borderRadius: 10, border: 'none', background: canOptimize ? '#2563eb' : '#93c5fd', color: '#ffffff', fontSize: 14, fontWeight: 700, cursor: canOptimize ? 'pointer' : 'not-allowed', boxShadow: canOptimize ? '0 4px 14px rgba(37,99,235,0.35)' : 'none', transition: 'all 0.2s' }}>
                  4주 물품배분 최적화
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </button>
              </div>
            </div>
          )
        })()}

{/* ═══════════════════════════════════════ STEP 04 ═══════════════════════════════════════ */}
{activeNav === 3 && (() => {

  if (!optimizationResult) {
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
    food: '일일식량',
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
    Number(summary.total_procurement_cost ?? 0)

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
            label: '총 조달비용',
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
                실제 충족량
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
