export const HISTORY_WEEKS = 2
const HUBS = ['medyka','dorohusk','korczowa'] as const
type History = Record<typeof HUBS[number], string[]>

// Migrate previously stored eight-week inputs without retaining hidden input cells.
export function normalizeHistory(value: unknown): History {
  const source = value && typeof value === 'object' ? value as Record<string,unknown> : {}
  return Object.fromEntries(HUBS.map(hub => {
    const row = Array.isArray(source[hub]) ? source[hub] as unknown[] : []
    return [hub,Array.from({length:HISTORY_WEEKS},(_,i)=>row[i] == null ? '' : String(row[i]))]
  })) as History
}

function csvLine(line: string): string[] {
  const cells: string[]=[];let text='';let quoted=false
  for(let i=0;i<line.length;i++) {
    const c=line[i]
    if(c==='"') {if(quoted && line[i+1]==='"'){text+='"';i++}else quoted=!quoted}
    else if(c===',' && !quoted){cells.push(text.trim());text=''}else text+=c
  }
  if(quoted) throw new Error('CSV 따옴표가 닫히지 않았습니다.')
  cells.push(text.trim());return cells
}

export function parseInflowCsv(raw: string): History {
  const rows=raw.replace(/^\uFEFF/,'').split(/\r?\n/).filter(s=>s.trim()!=='').map(csvLine)
  if(rows.length!==HISTORY_WEEKS+1)throw new Error('CSV는 헤더와 기준 주·1주 전의 데이터 2행이 필요합니다.')
  const header=rows[0].map(s=>s.trim().toLowerCase().replace(/[\s._·\-()]/g,''))
  const columns=HUBS.map(h=>header.indexOf(h))
  if(columns.some(i=>i<0))throw new Error('CSV에 medyka, dorohusk, korczowa 열이 모두 필요합니다.')
  const weekColumn=header.findIndex(s=>s==='week'||s==='주차')
  const byWeek=new Map<number,string[]>()
  rows.slice(1).forEach((row,i)=> {
    const label=weekColumn<0 ? String(i) : (row[weekColumn]??'').replace(/\s/g,'')
    const week=label==='기준주'||label==='0' ? 0 : label==='1'||label==='1주전' ? 1 : -1
    if(week<0||byWeek.has(week))throw new Error('주차는 기준 주(0)와 1주 전(1)을 한 번씩 입력해주세요.')
    byWeek.set(week,row)
  })
  const result=normalizeHistory(null)
  HUBS.forEach((hub,k)=> {
    result[hub]=Array.from({length:HISTORY_WEEKS},(_,i)=> {
      const v=(byWeek.get(i)?.[columns[k]]??'').replace(/,/g,'').trim()
      if(v===''||!Number.isFinite(Number(v))||Number(v)<0||Number(v)>500000)
        throw new Error(`${i===0?'기준 주':'1주 전'} ${hub} 유입량은 0~500000의 숫자여야 합니다.`)
      return v
    })
  })
  return result
}
