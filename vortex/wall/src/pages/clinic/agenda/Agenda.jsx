import { useCallback, useEffect, useState } from "react";
import SectionHeader from "../../../components/ui/SectionHeader";
import Card from "../../../components/ui/Card";
import Button from "../../../components/ui/Button";
import { CancelRangeDialog, CancelVisitDialog } from "./CancelDialogs";
import "./agenda.css";

const STORAGE_KEY = "vortex.clinic.doctorName";
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function addDays(iso, days) {
  const [year, month, day] = iso.split("-").map(Number);
  const next = new Date(year, month - 1, day + days);
  const mm = String(next.getMonth() + 1).padStart(2, "0");
  const dd = String(next.getDate()).padStart(2, "0");
  return `${next.getFullYear()}-${mm}-${dd}`;
}

function visitKey(visit) {
  if (!visit) return "";
  return `${visit.date || ""}-${visit.time}-${visit.provider_id || ""}-${visit.full_name}`;
}

function loadName() {
  try {
    return sessionStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function saveName(name) {
  try {
    sessionStorage.setItem(STORAGE_KEY, name);
  } catch {
    /* private mode */
  }
}

function filterVisits(visits, site, typeId) {
  return visits.filter((visit) => {
    if (site && visit.location_id !== site) return false;
    if (typeId && visit.appointment_type_id !== typeId) return false;
    return true;
  });
}

export default function Agenda() {
  const [name, setName] = useState(loadName);
  const [month, setMonth] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [focusDay, setFocusDay] = useState("");
  const [calView, setCalView] = useState("month");
  const [site, setSite] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [typeId, setTypeId] = useState("");
  const [options, setOptions] = useState({
    doctors: [],
    sites: [],
    specialties: [],
    types: [],
  });
  const [rangeOpen, setRangeOpen] = useState(false);
  const [confirmVisit, setConfirmVisit] = useState(null);

  useEffect(() => {
    fetch("/api/wall/agenda-options")
      .then((res) => res.json())
      .then((payload) => {
        if (payload.ok) {
          setOptions({
            doctors: payload.doctors || [],
            sites: payload.sites || [],
            specialties: payload.specialties || [],
            types: payload.types || [],
          });
        }
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async (who, monthStart, spec) => {
    setLoading(true);
    const params = new URLSearchParams();
    if (who.trim()) params.set("name", who.trim());
    if (spec) params.set("specialty", spec);
    if (monthStart) params.set("month", monthStart.slice(0, 7));
    const res = await fetch(`/api/wall/doctor-agenda?${params}`);
    const payload = await res.json();
    setLoading(false);
    if (!payload.ok) {
      setData(null);
      setError(payload.error === "ambiguous"
        ? "There are several matches. Choose the full name."
        : "No schedule found for that name.");
      return;
    }
    setError("");
    setData(payload);
    setMonth(payload.month);
  }, []);

  useEffect(() => {
    load(name, month, specialty);
  }, [name, month, specialty, load]);

  function afterCancel() {
    // The cancelled slots come back as free on the refetch — the visit the
    // detail pane was showing may be one of them, so it closes too.
    setSelected(null);
    load(name, month, specialty);
  }

  function pickDoctor(who) {
    const next = who.trim();
    saveName(next);
    setMonth("");
    setSelected(null);
    setFocusDay("");
    setCalView("month");
    setName(next);
  }

  function backToWeek() {
    setSelected(null);
    setCalView("month");
  }

  function openDay(day) {
    setSelected(null);
    setFocusDay(day.date);
    setCalView("day");
    if (!day.in_month) {
      setMonth(`${day.date.slice(0, 8)}01`);
    }
  }

  function openVisit(day, visit) {
    setFocusDay(day.date);
    setSelected(visit);
    setCalView("day");
    if (!day.in_month) {
      setMonth(`${day.date.slice(0, 8)}01`);
    }
  }

  const selectedKey = visitKey(selected);
  const weeks = (data?.weeks || []).map((row) =>
    row.map((day) => ({ ...day, visits: filterVisits(day.visits, site, typeId) }))
  );
  const lookingAt = focusDay || data?.today || "";
  const focused = weeks.flat().find((day) => day.date === lookingAt);
  const dayVisits = focused ? focused.visits : [];
  const lookingLabel = lookingAt
    ? `${lookingAt.slice(8, 10)}/${lookingAt.slice(5, 7)}`
    : "";
  const weekRow = weeks.find((row) => row.some((day) => day.date === lookingAt))
    || weeks.find((row) => row.some((day) => day.today))
    || weeks[0]
    || [];
  const weekTitle = weekRow.length && data
    ? `${weekRow[0].day}–${weekRow[6].day} ${data.month_label}`
    : (data?.month_label || "");
  const doctors = (options.doctors || []).filter(
    (row) => !specialty || row.specialty_id === specialty
  );

  return (
    <div className="agenda-page">
      <SectionHeader
        eyebrow="Agenda"
        title={data?.doctor?.name || "Schedule"}
        subtitle={
          data?.doctor?.specialty
            || "Choose a specialty or doctor. The calendar shows the pack's appointments."
        }
        action={
          <Button variant="secondary" type="button" onClick={() => setRangeOpen(true)}>
            Cancel
          </Button>
        }
      />
      <div className="agenda-toolbar">
        <label className="agenda-label" htmlFor="agenda-doctor">Doctor</label>
        <select
          id="agenda-doctor"
          className="ui-select agenda-filter"
          value={name}
          onChange={(event) => pickDoctor(event.target.value)}
        >
          <option value="">Any</option>
          {doctors.map((row) => (
            <option key={row.name} value={row.name}>{row.name}</option>
          ))}
        </select>
        <label className="agenda-label" htmlFor="agenda-specialty">Specialty</label>
        <select
          id="agenda-specialty"
          className="ui-select agenda-filter"
          value={specialty}
          onChange={(event) => {
            const next = event.target.value;
            setSpecialty(next);
            setSelected(null);
            const still = (options.doctors || []).filter(
              (row) => !next || row.specialty_id === next
            );
            if (name && !still.some((row) => row.name === name)) {
              pickDoctor("");
            }
          }}
        >
          <option value="">All</option>
          {options.specialties.map((row) => (
            <option key={row.id} value={row.id}>{row.name}</option>
          ))}
        </select>
        <label className="agenda-label" htmlFor="agenda-site">Site</label>
        <select
          id="agenda-site"
          className="ui-select agenda-filter"
          value={site}
          onChange={(event) => {
            setSite(event.target.value);
            setSelected(null);
          }}
        >
          <option value="">All</option>
          {options.sites.map((row) => (
            <option key={row.id} value={row.id}>{row.name}</option>
          ))}
        </select>
        <label className="agenda-label" htmlFor="agenda-type">Appointment type</label>
        <select
          id="agenda-type"
          className="ui-select agenda-filter"
          value={typeId}
          onChange={(event) => {
            setTypeId(event.target.value);
            setSelected(null);
          }}
        >
          <option value="">All</option>
          {options.types.map((row) => (
            <option key={row.id} value={row.id}>{row.name}</option>
          ))}
        </select>
        {error && <p className="agenda-error">{error}</p>}
      </div>

      {loading && !data ? (
        <Card padding="lg">
          <div className="agenda-empty">
            <p>Loading schedule…</p>
          </div>
        </Card>
      ) : !data ? (
        <Card padding="lg">
          <div className="agenda-empty">
            <p>No schedules for these filters.</p>
          </div>
        </Card>
      ) : selected ? (
        <div className="agenda-day-stack">
          <Button variant="secondary" type="button" className="agenda-back" onClick={backToWeek}>
            ‹ Back to calendar
          </Button>
          <div className="agenda-consult">
          <Card padding="lg" className="agenda-day-pane">
            <SectionHeader
              eyebrow={focused?.today ? "Today" : lookingLabel}
              title={lookingLabel}
              subtitle={dayVisits.length === 1 ? "1 appointment" : `${dayVisits.length} appointments`}
            />
            <DayList
              visits={dayVisits}
              selectedKey={selectedKey}
              onPick={(visit) => setSelected(visit)}
            />
          </Card>
          <VisitDetail visit={selected} onCancel={() => setConfirmVisit(selected)} />
          </div>
        </div>
      ) : calView === "day" ? (
        <div className="agenda-day-stack">
          <Button variant="secondary" type="button" className="agenda-back" onClick={backToWeek}>
            ‹ Back to calendar
          </Button>
        <Card padding="lg" className="agenda-day-pane">
          <SectionHeader
            eyebrow={focused?.today ? "Today" : lookingLabel}
            title={lookingLabel}
            subtitle={dayVisits.length === 1 ? "1 appointment" : `${dayVisits.length} appointments`}
          />
          <DayList
            visits={dayVisits}
            selectedKey={selectedKey}
            onPick={(visit) => setSelected(visit)}
          />
        </Card>
        </div>
      ) : (
        <Card padding="lg" className="agenda-week-card">
            <div className="agenda-week-bar">
              <div className="agenda-week-nav">
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() => {
                    if (calView === "month") {
                      const next = addDays(`${data.month.slice(0, 8)}01`, -1);
                      const jump = `${next.slice(0, 8)}01`;
                      setFocusDay(jump);
                      setMonth(jump);
                      return;
                    }
                    const next = addDays(lookingAt, -7);
                    setFocusDay(next);
                    setMonth(`${next.slice(0, 8)}01`);
                  }}
                >
                  ‹
                </Button>
                <span className="agenda-week-label">
                  {calView === "month" ? data.month_label : weekTitle}
                </span>
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() => {
                    if (calView === "month") {
                      const start = `${data.month.slice(0, 8)}01`;
                      const next = addDays(start, 32).slice(0, 8) + "01";
                      setFocusDay(next);
                      setMonth(next);
                      return;
                    }
                    const next = addDays(lookingAt, 7);
                    setFocusDay(next);
                    setMonth(`${next.slice(0, 8)}01`);
                  }}
                >
                  ›
                </Button>
              </div>
              {calView === "week" ? (
                <Button variant="ghost" type="button" onClick={() => setCalView("month")}>
                  Month
                </Button>
              ) : (
                <Button variant="ghost" type="button" onClick={() => setCalView("week")}>
                  Week
                </Button>
              )}
            </div>
            {calView === "month" ? (
              <MonthGrid
                weeks={weeks}
                lookingAt={lookingAt}
                selectedKey={selectedKey}
                onDay={openDay}
                onVisit={openVisit}
              />
            ) : (
              <WeekStrip
                days={weekRow}
                lookingAt={lookingAt}
                selectedKey={selectedKey}
                onDay={openDay}
                onVisit={openVisit}
              />
            )}
          </Card>
      )}
      <CancelRangeDialog
        open={rangeOpen}
        onClose={() => setRangeOpen(false)}
        doctors={options.doctors || []}
        initialProviderId={(options.doctors.find((row) => row.name === name) || {}).id}
        today={data?.today}
        onDone={afterCancel}
      />
      <CancelVisitDialog
        visit={confirmVisit}
        doctorName={confirmVisit?.provider_name || data?.doctor?.name}
        onClose={() => setConfirmVisit(null)}
        onDone={afterCancel}
      />
    </div>
  );
}

function MonthGrid({ weeks, lookingAt, selectedKey, onDay, onVisit }) {
  return (
    <div className="agenda-month-wrap">
      <div className="agenda-month-head">
        {DOW.map((label) => (
          <div key={label} className="agenda-month-dow">{label}</div>
        ))}
      </div>
      <div className="agenda-month">
        {weeks.flat().map((day) => (
          <DayCell
            key={day.date}
            day={day}
            lookingAt={lookingAt}
            selectedKey={selectedKey}
            onDay={onDay}
            onVisit={onVisit}
          />
        ))}
      </div>
    </div>
  );
}

function WeekStrip({ days, lookingAt, selectedKey, onDay, onVisit }) {
  return (
    <div className="agenda-week-strip">
      {days.map((day, index) => (
        <div key={day.date} className="agenda-week-col">
          <div className={`agenda-month-dow${day.today ? " today" : ""}`}>
            {DOW[index]}
          </div>
          <DayCell
            day={day}
            lookingAt={lookingAt}
            selectedKey={selectedKey}
            onDay={onDay}
            onVisit={onVisit}
            tall
          />
        </div>
      ))}
    </div>
  );
}

function DayCell({ day, lookingAt, selectedKey, onDay, onVisit, tall }) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={[
        "agenda-month-day",
        tall ? "tall" : "",
        day.in_month ? "" : "muted",
        day.today ? "today" : "",
        lookingAt === day.date ? "on" : "",
      ].filter(Boolean).join(" ")}
      onClick={() => onDay(day)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDay(day);
        }
      }}
    >
      <span className="agenda-month-num">{day.day}</span>
      <span className="agenda-month-events">
        {day.visits.map((visit) => (
          <button
            key={visitKey(visit)}
            type="button"
            className={`agenda-event${visitKey(visit) === selectedKey ? " on" : ""}`}
            onClick={(event) => {
              event.stopPropagation();
              onVisit(day, visit);
            }}
          >
            {visit.time} {visit.full_name}
            {visit.provider_name ? ` · ${visit.provider_name}` : ""}
          </button>
        ))}
      </span>
    </div>
  );
}

function DayList({ visits, selectedKey, onPick }) {
  if (visits.length === 0) {
    return (
      <div className="agenda-empty">
        <p>No appointments this day.</p>
      </div>
    );
  }
  return (
    <div className="agenda-visit-list">
      {visits.map((visit) => (
        <button
          type="button"
          key={visitKey(visit)}
          className={`agenda-visit-row${visitKey(visit) === selectedKey ? " on" : ""}`}
          onClick={() => onPick(visit)}
        >
          <strong>{visit.time}</strong>
          <span>{visit.full_name}{visit.provider_name ? ` · ${visit.provider_name}` : ""}</span>
          <em>{visit.duration_minutes || 15} min</em>
        </button>
      ))}
    </div>
  );
}

function VisitDetail({ visit, onCancel }) {
  return (
    <Card padding="lg" className="agenda-visit-wide">
      <div className="agenda-visit-head">
        <h3>{visit.time} · {visit.full_name}</h3>
        <span>
          {visit.appointment_type || "Appointment"} · {visit.duration_minutes || 15} min
        </span>
      </div>
      {visit.note ? (
        <div className="agenda-symptom">
          <span>Treatment note</span>
          <p>{visit.note}</p>
        </div>
      ) : null}
      <div className="agenda-pills">
        <span>{visit.has_visited_before ? "Returning patient" : "New patient"}</span>
        {visit.sex ? <span>{visit.sex}</span> : null}
        {visit.age ? <span>{visit.age}</span> : null}
      </div>
      <dl className="agenda-kv">
        <div><dt>Patient</dt><dd>{visit.full_name}</dd></div>
        {visit.provider_name ? <div><dt>Doctor</dt><dd>{visit.provider_name}</dd></div> : null}
        <div><dt>When</dt><dd>{visit.when}</dd></div>
        <div><dt>Duration</dt><dd>{visit.duration_minutes || 15} min</dd></div>
        <div><dt>Site</dt><dd>{visit.location_name || "—"}</dd></div>
        <div><dt>Insurance</dt><dd>{visit.insurer || "—"}</dd></div>
        <div><dt>Phone</dt><dd>{visit.phone || "—"}</dd></div>
      </dl>
      {visit.provider_id && visit.slot ? (
        <div className="agenda-visit-actions">
          <Button variant="secondary" type="button" onClick={onCancel}>
            Cancel this appointment
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
