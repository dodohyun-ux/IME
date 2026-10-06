// A request may complete after its inputs change, even when they later change back.
export class InputRevision {
  private signature = ''
  private revision = 0

  update(signature: string): number {
    if (signature !== this.signature) {
      this.signature = signature
      this.revision += 1
    }
    return this.revision
  }

  isCurrent(revision: number): boolean {
    return revision === this.revision
  }
}

export function hasPlanningForecast(source: string | null, values: number[]): boolean {
  return source !== null && values.length === 4 && values.every(v => Number.isFinite(v) && v >= 0)
}

export function roadDisplay(info: { road_graph_data_kind?: string; geography?: { publisher?: string } } = {}) {
  if (info.road_graph_data_kind === 'official_geometry_scenario') {
    return { kind: '공식 도로 선형을 사용하는 프로젝트 시나리오',
      source: `${info.geography?.publisher ?? '공식 자료'} 도로 선형`, official: true }
  }
  if (info.road_graph_data_kind === 'synthetic') {
    return { kind: '합성 도로망 · 계산 검증용 시나리오', source: '합성 입력 도로망', official: false }
  }
  return { kind: '사용자 제공 도로망 · 출처·운행 조건 별도 확인', source: '사용자 제공 입력 도로망', official: false }
}

// The optimizer rounds supported persons up before forming item demand.
export function supportedPeople(forecast: number, utilizationPercent: number): number {
  return Math.ceil(forecast * utilizationPercent / 100)
}
