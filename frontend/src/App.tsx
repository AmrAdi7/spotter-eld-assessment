import L from 'leaflet'
import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

type Coordinate = {
  lat: number
  lng: number
}

type TripForm = {
  currentLocation: string
  pickupLocation: string
  dropoffLocation: string
  currentCycleUsed: string
}

type TimelineEvent = {
  day: number
  type: string
  status: DutyStatus
  startTime: number
  endTime: number
  startClock: string
  endClock: string
  duration: number
  hours: number
  location: string
  coordinate: Coordinate
  miles: number
  description: string
  label: string
}

type DutyStatus = 'offDuty' | 'sleeperBerth' | 'driving' | 'onDuty'

type LogSegment = {
  status: DutyStatus
  type: string
  startHour: number
  endHour: number
  duration: number
  label: string
  location: string
  miles: number
}

type DailyLog = {
  day: number
  dateLabel: string
  carrier: string
  truck: string
  route: string
  totalHours: number
  total: number
  offDuty: number
  sleeperBerth: number
  driving: number
  onDuty: number
  miles: number
  segments: LogSegment[]
  remarks: Array<{ time: string; text: string }>
}

type TripPlan = {
  summary: {
    distanceMiles: number
    driveHours: number
    estimatedDriveHours: number
    tripDays: number
    estimatedDays: number
    fuelStops: number
    cycleHoursAvailableAtStart: number
    assumptions: string[]
  }
  route: {
    distanceMiles: number
    durationHours: number
    geometry: Coordinate[]
    points: Array<{
      label: string
      location: string
      coordinate: Coordinate
      distanceMiles: number
    }>
  }
  stops: Array<{
    type: string
    label: string
    location: string
    coordinate: Coordinate
    day?: number
    time?: string
  }>
  timeline: TimelineEvent[]
  dailyLogs: DailyLog[]
}

const initialForm: TripForm = {
  currentLocation: '',
  pickupLocation: '',
  dropoffLocation: '',
  currentCycleUsed: '',
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

const statusRows: Array<{ key: DutyStatus; label: string }> = [
  { key: 'offDuty', label: 'Off Duty' },
  { key: 'sleeperBerth', label: 'Sleeper Berth' },
  { key: 'driving', label: 'Driving' },
  { key: 'onDuty', label: 'On Duty' },
]

const mapLegend = [
  { type: 'start', label: 'Start' },
  { type: 'pickup', label: 'Pickup' },
  { type: 'break', label: 'Break' },
  { type: 'rest', label: 'Rest' },
  { type: 'fuel', label: 'Fuel' },
  { type: 'dropoff', label: 'Dropoff' },
]

function App() {
  const [form, setForm] = useState<TripForm>(initialForm)
  const [plan, setPlan] = useState<TripPlan | null>(null)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const groupedTimeline = useMemo(() => {
    if (!plan) return []
    return plan.dailyLogs.map((log) => ({
      day: log.day,
      events: plan.timeline.filter((event) => event.day === log.day),
    }))
  }, [plan])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsLoading(true)
    setError('')

    try {
      const response = await fetch(`${apiBaseUrl}/api/trip-plan/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          currentCycleUsed: Number(form.currentCycleUsed),
        }),
      })
      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Unable to build the trip plan.')
      }

      setPlan(data)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to build the trip plan.')
    } finally {
      setIsLoading(false)
    }
  }

  function updateField(field: keyof TripForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  return (
    <main className="app-shell">
      <section className="planner-panel">
        <div className="panel-header">
          <p className="eyebrow">Spotter ELD assessment</p>
          <h1>Trip planner with HOS-ready logs</h1>
          <p>
            Build a compliant property-carrying trip plan using the 70-hour cycle,
            11-hour drive limit, 14-hour window, breaks, pickup, dropoff, and fuel stops.
          </p>
        </div>

        <form className="trip-form" onSubmit={handleSubmit}>
          <label>
            Current location
            <input
              value={form.currentLocation}
              onChange={(event) => updateField('currentLocation', event.target.value)}
              placeholder="City, ST"
            />
          </label>
          <label>
            Pickup location
            <input
              value={form.pickupLocation}
              onChange={(event) => updateField('pickupLocation', event.target.value)}
              placeholder="City, ST"
            />
          </label>
          <label>
            Dropoff location
            <input
              value={form.dropoffLocation}
              onChange={(event) => updateField('dropoffLocation', event.target.value)}
              placeholder="City, ST"
            />
          </label>
          <label>
            Current cycle used
            <input
              min="0"
              max="70"
              step="0.25"
              type="number"
              value={form.currentCycleUsed}
              onChange={(event) => updateField('currentCycleUsed', event.target.value)}
            />
          </label>

          <button disabled={isLoading} type="submit">
            {isLoading ? 'Planning route...' : 'Build trip plan'}
          </button>
          {error && <p className="form-error">{error}</p>}
        </form>
      </section>

      <section className="results-panel">
        {plan ? (
          <>
            <div className="metric-grid">
              <Metric label="Distance" value={`${plan.summary.distanceMiles.toLocaleString()} mi`} />
              <Metric label="Drive time" value={`${plan.summary.driveHours} hr`} />
              <Metric label="Trip length" value={`${plan.summary.tripDays} days`} />
              <Metric label="Fuel stops" value={String(plan.summary.fuelStops)} />
            </div>

            <div className="route-strip">
              {plan.route.points.map((stop) => (
                <div className="route-stop" key={stop.label}>
                  <span>{stop.label}</span>
                  <strong>{stop.location}</strong>
                </div>
              ))}
            </div>

            <section className="section-block map-block">
              <div className="section-title">
                <h2>Route map</h2>
                <span>OpenStreetMap + OSRM route</span>
              </div>
              <RouteMap plan={plan} />
              <div className="map-legend" aria-label="Map marker legend">
                {mapLegend.map((item) => (
                  <span className="legend-item" key={item.type}>
                    <span className={`map-marker ${item.type}`}>
                      <span>{markerLabel(item.type)}</span>
                    </span>
                    {item.label}
                  </span>
                ))}
              </div>
            </section>

            <div className="content-grid">
              <section className="section-block">
                <div className="section-title">
                  <h2>Planned events</h2>
                  <span>{plan.timeline.length} stops and duty changes</span>
                </div>
                <div className="timeline">
                  {groupedTimeline.map((group) => (
                    <div className="day-group" key={group.day}>
                      <h3>Day {group.day}</h3>
                      {group.events.map((event, index) => (
                        <div className="timeline-row" key={`${group.day}-${index}`}>
                          <span className={`event-dot ${event.type}`}></span>
                          <div>
                            <strong>{event.label}</strong>
                            <p>
                              {event.startClock}-{event.endClock} · {event.hours} hr
                              {event.miles ? ` · ${Math.round(event.miles)} mi` : ''}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </section>

              <section className="section-block">
                <div className="section-title">
                  <h2>Daily totals</h2>
                  <span>Derived from event timeline</span>
                </div>
                <div className="log-list">
                  {plan.dailyLogs.map((log) => (
                    <article className="log-card" key={log.day}>
                      <div className="log-card-header">
                        <h3>Day {log.day}</h3>
                        <span>{log.total} hr</span>
                      </div>
                      <LogBar label="Off duty" value={log.offDuty} total={log.total} />
                      <LogBar label="Sleeper berth" value={log.sleeperBerth} total={log.total} />
                      <LogBar label="Driving" value={log.driving} total={log.total} />
                      <LogBar label="On duty" value={log.onDuty} total={log.total} />
                    </article>
                  ))}
                </div>
              </section>
            </div>

            <section className="section-block eld-section">
              <div className="section-title">
                <h2>Daily ELD log sheets</h2>
                <span>24-hour graph grid</span>
              </div>
              <div className="eld-list">
                {plan.dailyLogs.map((log) => (
                  <EldSheet log={log} key={log.day} />
                ))}
              </div>
            </section>
          </>
        ) : (
          <div className="empty-state">
            <h2>Ready for the first route</h2>
            <p>Submit the form to generate the trip summary, stops, route map, and daily log sheets.</p>
          </div>
        )}
      </section>
    </main>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  )
}

function RouteMap({ plan }: { plan: TripPlan }) {
  const routePositions = plan.route.geometry.map((point) => [point.lat, point.lng] as [number, number])

  return (
    <MapContainer className="route-map" center={routePositions[0]} zoom={6} scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Polyline positions={routePositions} pathOptions={{ color: '#2563eb', weight: 5 }} />
      {plan.stops.map((stop, index) => (
        <Marker
          icon={markerIcon(stop.type)}
          key={`${stop.type}-${index}`}
          position={[stop.coordinate.lat, stop.coordinate.lng]}
        >
          <Popup>
            <strong>{stop.label}</strong>
            <br />
            {stop.location}
            {stop.time ? (
              <>
                <br />
                Day {stop.day} · {stop.time}
              </>
            ) : null}
          </Popup>
        </Marker>
      ))}
      <FitBounds positions={routePositions} />
    </MapContainer>
  )
}

function FitBounds({ positions }: { positions: Array<[number, number]> }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length > 1) {
      map.fitBounds(positions, { padding: [24, 24] })
    }
  }, [map, positions])
  return null
}

function markerIcon(type: string) {
  const className = `map-marker ${type}`
  const label = markerLabel(type)
  return L.divIcon({
    className,
    html: `<span>${label}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

function markerLabel(type: string) {
  const labels: Record<string, string> = {
    start: 'S',
    pickup: 'P',
    dropoff: 'D',
    fuel: 'F',
    break: 'B',
    rest: 'R',
    restart: '34',
  }
  return labels[type] || '•'
}

function LogBar({ label, value, total }: { label: string; value: number; total: number }) {
  const width = total ? `${Math.max((value / total) * 100, value > 0 ? 4 : 0)}%` : '0%'

  return (
    <div className="log-row">
      <div className="log-label">
        <span>{label}</span>
        <strong>{value} hr</strong>
      </div>
      <div className="bar-track">
        <span style={{ width }}></span>
      </div>
    </div>
  )
}

function EldSheet({ log }: { log: DailyLog }) {
  return (
    <article className="eld-sheet">
      <div className="eld-header">
        <div>
          <span>Date</span>
          <strong>{log.dateLabel}</strong>
        </div>
        <div>
          <span>Total miles driving today</span>
          <strong>{Math.round(log.miles)} mi</strong>
        </div>
        <div>
          <span>Carrier</span>
          <strong>{log.carrier}</strong>
        </div>
        <div>
          <span>Truck</span>
          <strong>{log.truck}</strong>
        </div>
      </div>

      <div className="eld-route">
        <span>Route</span>
        <strong>{log.route}</strong>
      </div>

      <div className="eld-grid" aria-label={`Day ${log.day} duty status grid`}>
        <div className="eld-time-row">
          <span></span>
          {Array.from({ length: 25 }, (_, hour) => (
            <span key={hour}>{hour}</span>
          ))}
        </div>
        {statusRows.map((row) => (
          <div className="eld-status-row" key={row.key}>
            <div className="eld-status-label">{row.label}</div>
            <div className="eld-track">
              {Array.from({ length: 24 }, (_, hour) => (
                <span className="eld-hour" key={hour}></span>
              ))}
              {log.segments
                .filter((segment) => segment.status === row.key)
                .map((segment, index) => (
                  <span
                    className={`eld-segment ${segment.type}`}
                    key={`${segment.status}-${index}`}
                    style={{
                      left: `${(segment.startHour / 24) * 100}%`,
                      width: `${((segment.endHour - segment.startHour) / 24) * 100}%`,
                    }}
                    title={`${segment.label}: ${segment.startHour}-${segment.endHour}`}
                  ></span>
                ))}
            </div>
          </div>
        ))}
      </div>

      <div className="eld-footer">
        <div className="eld-totals">
          <span>Off Duty: {log.offDuty} hr</span>
          <span>Sleeper: {log.sleeperBerth} hr</span>
          <span>Driving: {log.driving} hr</span>
          <span>On Duty: {log.onDuty} hr</span>
          <strong>Total: {log.totalHours} hr</strong>
        </div>
        <div className="remarks">
          <h3>Remarks</h3>
          {log.remarks.length ? (
            log.remarks.map((remark, index) => (
              <p key={`${remark.time}-${index}`}>
                <strong>{remark.time}</strong> {remark.text}
              </p>
            ))
          ) : (
            <p>No duty-status remarks for this day.</p>
          )}
        </div>
      </div>
    </article>
  )
}

export default App
