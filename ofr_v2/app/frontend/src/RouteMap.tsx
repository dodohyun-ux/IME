import { useEffect, useRef, useState } from 'react'
import * as L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './route-map.css'

type Geometry = { coordinates: number[][] }
type MapTrip = {
  outbound_geometry?: Geometry[]
  return_geometry?: Geometry[]
}

// Solver geometry is GeoJSON [longitude, latitude]; Leaflet expects [latitude, longitude].
function mapSegments(geometry: Geometry[] = []): L.LatLngTuple[][] {
  return geometry.map(segment => segment.coordinates
    .filter(([lon, lat]) => Number.isFinite(lon) && Number.isFinite(lat)
      && Math.abs(lon) <= 180 && Math.abs(lat) <= 85.05112878)
    .map(([lon, lat]): L.LatLngTuple => [lat, lon]))
    .filter(segment => segment.length > 1)
}

export default function RouteMap({ trip, phase, warehouseAddress, destinationAddress }: {
  trip: MapTrip
  phase: 'outbound' | 'return'
  warehouseAddress?: string
  destinationAddress?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const routeLayer = useRef<L.LayerGroup | null>(null)
  const routeBounds = useRef<L.LatLngBounds | null>(null)
  const [tileStatus, setTileStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const segments = mapSegments(trip[`${phase}_geometry`])
  const hasRoute = segments.length > 0

  useEffect(() => {
    if (!container.current || !hasRoute) return
    const instance = L.map(container.current, { scrollWheelZoom: false, maxZoom: 19 })
    map.current = instance
    let loadedTiles = 0
    let timeout: ReturnType<typeof setTimeout>
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
      maxZoom: 19,
      // Only request the viewport; normal browser HTTP caching remains enabled.
      keepBuffer: 0,
      referrerPolicy: 'strict-origin-when-cross-origin',
    })
    tiles.on('loading', () => {
      loadedTiles = 0
      setTileStatus('loading')
      clearTimeout(timeout)
      timeout = setTimeout(() => { if (!loadedTiles) setTileStatus('unavailable') }, 15000)
    })
    tiles.on('tileload', () => { loadedTiles += 1; setTileStatus('ready') })
    tiles.on('load', () => { clearTimeout(timeout); setTileStatus(loadedTiles ? 'ready' : 'unavailable') })
    tiles.addTo(instance)
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(instance)
    routeLayer.current = L.layerGroup().addTo(instance)
    const observer = new ResizeObserver(() => {
      instance.invalidateSize({ pan: false })
      if (routeBounds.current) instance.fitBounds(routeBounds.current, { padding: [72, 40], maxZoom: 13, animate: false })
    })
    observer.observe(container.current)
    return () => {
      clearTimeout(timeout)
      observer.disconnect()
      tiles.off()
      instance.remove()
      map.current = null
      routeLayer.current = null
      routeBounds.current = null
    }
  }, [hasRoute])

  useEffect(() => {
    const instance = map.current
    const layer = routeLayer.current
    if (!instance || !layer) return
    layer.clearLayers()
    const paths = mapSegments(trip[`${phase}_geometry`])
    if (!paths.length) return
    const color = phase === 'outbound' ? '#2563eb' : '#0d9488'
    L.polyline(paths, { color: '#ffffff', weight: 8, opacity: 0.9, interactive: false }).addTo(layer)
    L.polyline(paths, { color, weight: 4, opacity: 0.95, interactive: false }).addTo(layer)
    const first = paths[0][0]
    const last = paths[paths.length - 1][paths[paths.length - 1].length - 1]
    const warehouse = phase === 'outbound' ? first : last
    const destination = phase === 'outbound' ? last : first
    const mark = (point: L.LatLngTuple, label: string, address: string | undefined, markerColor: string) => {
      const popup = document.createElement('div')
      const title = document.createElement('strong')
      title.textContent = label
      popup.append(title)
      if (address) { const detail = document.createElement('div'); detail.textContent = address; popup.append(detail) }
      L.circleMarker(point, { radius: 7, color: '#ffffff', weight: 3, fillColor: markerColor, fillOpacity: 1 })
        .bindTooltip(label, { permanent: true, direction: label === '출발 창고' ? 'left' : 'right', className: 'route-map-label' })
        .bindPopup(popup).addTo(layer)
    }
    mark(warehouse, '출발 창고', warehouseAddress, '#2563eb')
    mark(destination, '도착 구호소', destinationAddress, '#ea580c')
    const points = [...mapSegments(trip.outbound_geometry), ...mapSegments(trip.return_geometry)].flat()
    const bounds = L.latLngBounds(points)
    routeBounds.current = bounds
    instance.invalidateSize({ pan: false })
    instance.fitBounds(bounds, { padding: [72, 40], maxZoom: 13, animate: false })
  }, [trip, phase, warehouseAddress, destinationAddress, hasRoute])

  if (!hasRoute) return <p>표시할 도로 선형이 없습니다. 경로를 다시 계산해주세요.</p>
  return <div className="route-map" role="region" aria-label={phase === 'outbound' ? '지도 위의 배송 경로' : '지도 위의 복귀 경로'}>
    <div className="route-map-toolbar">
      <div className="route-map-legend">
        <span><i style={{ background: phase === 'outbound' ? '#2563eb' : '#0d9488' }} />{phase === 'outbound' ? '배송 경로' : '복귀 경로'}</span>
        <span><i className="route-map-dot" style={{ background: '#2563eb' }} />창고</span>
        <span><i className="route-map-dot" style={{ background: '#ea580c' }} />구호소</span>
      </div>
      <button type="button" onClick={() => {
        if (routeBounds.current) map.current?.fitBounds(routeBounds.current, { padding: [72, 40], maxZoom: 13 })
      }}>전체 경로 보기</button>
    </div>
    <div ref={container} className="route-map-canvas" />
    {tileStatus !== 'ready' && <div className="route-map-status" role="status">
      {tileStatus === 'loading' ? '배경지도를 불러오는 중…' : '배경지도를 불러오지 못했습니다. 인터넷 연결을 확인해주세요. 계산된 경로는 계속 표시됩니다.'}
    </div>}
  </div>
}
