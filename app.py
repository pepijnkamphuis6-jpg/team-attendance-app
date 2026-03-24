import sqlite3
from contextlib import closing
from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st

DB_NAME = "attendance_app.db"

st.set_page_config(
    page_title="Team Attendance Pro",
    page_icon="🏑",
    layout="wide",
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1200px;
}
h1, h2, h3 {
    margin-bottom: 0.4rem;
}
.signal-good {
    padding: 12px;
    border-radius: 12px;
    background: rgba(34,197,94,0.12);
    border: 1px solid rgba(34,197,94,0.35);
    margin-bottom: 8px;
}
.signal-warn {
    padding: 12px;
    border-radius: 12px;
    background: rgba(245,158,11,0.12);
    border: 1px solid rgba(245,158,11,0.35);
    margin-bottom: 8px;
}
.signal-bad {
    padding: 12px;
    border-radius: 12px;
    background: rgba(239,68,68,0.12);
    border: 1px solid rgba(239,68,68,0.35);
    margin-bottom: 8px;
}
@media (max-width: 768px) {
    .block-container {
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }
}
</style>
""", unsafe_allow_html=True)

STATUS_OPTIONS = [
    "aanwezig",
    "te_laat",
    "deels_aanwezig",
    "afgemeld",
    "geblesseerd",
    "afwezig",
]

STATUS_LABELS = {
    "aanwezig": "Aanwezig",
    "te_laat": "Te laat",
    "deels_aanwezig": "Deels aanwezig",
    "afgemeld": "Afgemeld",
    "geblesseerd": "Geblesseerd",
    "afwezig": "Afwezig",
}

STATUS_POINTS = {
    "aanwezig": 1.0,
    "te_laat": 0.75,
    "deels_aanwezig": 0.5,
    "afgemeld": 0.0,
    "geblesseerd": 0.0,
    "afwezig": 0.0,
}

STATUS_COLORS = {
    "aanwezig": "🟢",
    "te_laat": "🟡",
    "deels_aanwezig": "🟠",
    "afgemeld": "🟠",
    "geblesseerd": "⚫",
    "afwezig": "🔴",
}

# Voor compatibiliteit met oudere data die nog Engelse waardes in de database kunnen hebben
OLD_STATUS_MAP = {
    "present": "aanwezig",
    "late": "te_laat",
    "partial": "deels_aanwezig",
    "reported_absent": "afgemeld",
    "injured": "geblesseerd",
    "absent": "afwezig",
}


def normalize_status(status: str) -> str:
    if status in STATUS_OPTIONS:
        return status
    return OLD_STATUS_MAP.get(status, "aanwezig")


def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_db():
    with closing(get_connection()) as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            age_group TEXT,
            season TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            jersey_number TEXT,
            role TEXT,
            team_id INTEGER,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            session_date TEXT NOT NULL,
            start_time TEXT,
            session_type TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, player_id),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
        """)

        conn.commit()


def migrate_old_statuses():
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        for old_status, new_status in OLD_STATUS_MAP.items():
            cur.execute(
                "UPDATE attendance SET status = ? WHERE status = ?",
                (new_status, old_status)
            )
        conn.commit()


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return d


def color_for_percentage(pct: float) -> str:
    if pct >= 80:
        return "🟢"
    elif pct >= 60:
        return "🟠"
    return "🔴"


def run_query(query: str, params: tuple = (), fetch: bool = False):
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        if fetch:
            return cur.fetchall()
        conn.commit()


def run_query_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def pct_or_zero(df: pd.DataFrame, player_id: int) -> float:
    part = df[df["player_id"] == player_id]
    if part.empty:
        return 0.0
    return float(part["attendance_pct"].iloc[0])


def safe_sessions_count(df: pd.DataFrame, player_id: int) -> int:
    part = df[df["player_id"] == player_id]
    if part.empty:
        return 0
    return int(part["sessions_count"].iloc[0])


def get_teams() -> pd.DataFrame:
    return run_query_df("""
        SELECT id, name, age_group, season
        FROM teams
        ORDER BY name
    """)


def add_team(name: str, age_group: str, season: str):
    run_query(
        "INSERT INTO teams (name, age_group, season) VALUES (?, ?, ?)",
        (name.strip(), age_group.strip(), season.strip())
    )


def get_players(team_id: Optional[int] = None, active_only: bool = True) -> pd.DataFrame:
    query = """
        SELECT p.id, p.name, p.jersey_number, p.role, p.team_id, p.active, t.name AS team_name
        FROM players p
        LEFT JOIN teams t ON p.team_id = t.id
        WHERE 1=1
    """
    params = []

    if team_id is not None:
        query += " AND p.team_id = ?"
        params.append(team_id)

    if active_only:
        query += " AND p.active = 1"

    query += " ORDER BY p.name"

    return run_query_df(query, tuple(params))


def add_player(name: str, jersey_number: str, role: str, team_id: int):
    run_query("""
        INSERT INTO players (name, jersey_number, role, team_id, active)
        VALUES (?, ?, ?, ?, 1)
    """, (name.strip(), jersey_number.strip(), role.strip(), team_id))


def deactivate_player(player_id: int):
    run_query("UPDATE players SET active = 0 WHERE id = ?", (player_id,))


def get_sessions(team_id: Optional[int] = None) -> pd.DataFrame:
    query = """
        SELECT s.id, s.title, s.session_date, s.start_time, s.session_type, s.notes, s.team_id, t.name AS team_name
        FROM sessions s
        JOIN teams t ON s.team_id = t.id
        WHERE 1=1
    """
    params = []

    if team_id is not None:
        query += " AND s.team_id = ?"
        params.append(team_id)

    query += " ORDER BY s.session_date DESC, s.start_time DESC"

    return run_query_df(query, tuple(params))


def add_session(team_id: int, title: str, session_date: str, start_time: str, session_type: str, notes: str):
    run_query("""
        INSERT INTO sessions (team_id, title, session_date, start_time, session_type, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (team_id, title.strip(), session_date, start_time, session_type.strip(), notes.strip()))


def get_recent_session_for_team(team_id: int) -> Optional[pd.Series]:
    df = run_query_df("""
        SELECT *
        FROM sessions
        WHERE team_id = ?
        ORDER BY session_date DESC, start_time DESC
        LIMIT 1
    """, (team_id,))
    if df.empty:
        return None
    return df.iloc[0]


def upsert_attendance(session_id: int, player_id: int, status: str, reason: str = "", note: str = ""):
    status = normalize_status(status)

    run_query("""
        INSERT INTO attendance (session_id, player_id, status, reason, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id, player_id)
        DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            note = excluded.note
    """, (session_id, player_id, status, reason.strip(), note.strip()))


def bulk_set_status_for_session(session_id: int, player_ids: list[int], status: str):
    status = normalize_status(status)
    for pid in player_ids:
        upsert_attendance(session_id, pid, status, "", "")


def get_attendance_for_session(session_id: int) -> pd.DataFrame:
    df = run_query_df("""
        SELECT
            a.id,
            a.session_id,
            a.player_id,
            p.name AS player_name,
            p.jersey_number,
            p.role,
            a.status,
            a.reason,
            a.note
        FROM attendance a
        JOIN players p ON a.player_id = p.id
        WHERE a.session_id = ?
        ORDER BY p.name
    """, (session_id,))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)

    return df


def get_attendance_with_sessions(team_id: Optional[int] = None) -> pd.DataFrame:
    query = """
        SELECT
            a.id,
            a.session_id,
            a.player_id,
            a.status,
            a.reason,
            a.note,
            p.name AS player_name,
            p.jersey_number,
            p.role,
            p.team_id,
            s.title,
            s.session_date,
            s.session_type,
            t.name AS team_name
        FROM attendance a
        JOIN players p ON a.player_id = p.id
        JOIN sessions s ON a.session_id = s.id
        JOIN teams t ON s.team_id = t.id
        WHERE 1=1
    """
    params = []

    if team_id is not None:
        query += " AND s.team_id = ?"
        params.append(team_id)

    query += " ORDER BY s.session_date DESC"

    df = run_query_df(query, tuple(params))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)

    return df


def get_player_history(player_id: int) -> pd.DataFrame:
    df = run_query_df("""
        SELECT
            s.session_date,
            s.title,
            s.session_type,
            a.status,
            a.reason,
            a.note,
            t.name AS team_name
        FROM attendance a
        JOIN sessions s ON a.session_id = s.id
        JOIN teams t ON s.team_id = t.id
        WHERE a.player_id = ?
        ORDER BY s.session_date DESC
    """, (player_id,))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)

    return df


def calculate_player_stats(team_id: Optional[int] = None, days: Optional[int] = None) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)

    if df.empty:
        return pd.DataFrame(columns=[
            "player_id", "player_name", "sessions_count", "presence_points",
            "attendance_pct", "present_count", "absent_count", "reported_absent_count",
            "injured_count", "late_count", "partial_count"
        ])

    df["session_date"] = pd.to_datetime(df["session_date"])

    if days is not None:
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        df = df[df["session_date"] >= cutoff]

    if df.empty:
        return pd.DataFrame(columns=[
            "player_id", "player_name", "sessions_count", "presence_points",
            "attendance_pct", "present_count", "absent_count", "reported_absent_count",
            "injured_count", "late_count", "partial_count"
        ])

    df["points"] = df["status"].map(STATUS_POINTS).fillna(0.0)

    grouped = df.groupby(["player_id", "player_name"], as_index=False).agg(
        sessions_count=("session_id", "count"),
        presence_points=("points", "sum"),
        present_count=("status", lambda x: (x == "aanwezig").sum()),
        absent_count=("status", lambda x: (x == "afwezig").sum()),
        reported_absent_count=("status", lambda x: (x == "afgemeld").sum()),
        injured_count=("status", lambda x: (x == "geblesseerd").sum()),
        late_count=("status", lambda x: (x == "te_laat").sum()),
        partial_count=("status", lambda x: (x == "deels_aanwezig").sum()),
    )

    grouped["attendance_pct"] = (grouped["presence_points"] / grouped["sessions_count"] * 100).round(1)
    grouped = grouped.sort_values(by=["attendance_pct", "player_name"], ascending=[False, True])
    return grouped


def get_monthly_team_attendance(team_id: int) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)
    if df.empty:
        return pd.DataFrame()

    df["session_date"] = pd.to_datetime(df["session_date"])
    df["month"] = df["session_date"].dt.to_period("M").astype(str)
    df["points"] = df["status"].map(STATUS_POINTS).fillna(0.0)

    grouped = df.groupby("month", as_index=False).agg(
        attendance_pct=("points", lambda x: round((x.sum() / len(x)) * 100, 1)),
        records=("points", "count")
    )
    return grouped


def get_monthly_player_attendance(team_id: int, player_id: int) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)
    if df.empty:
        return pd.DataFrame()

    df = df[df["player_id"] == player_id].copy()
    if df.empty:
        return pd.DataFrame()

    df["session_date"] = pd.to_datetime(df["session_date"])
    df["month"] = df["session_date"].dt.to_period("M").astype(str)
    df["points"] = df["status"].map(STATUS_POINTS).fillna(0.0)

    grouped = df.groupby("month", as_index=False).agg(
        attendance_pct=("points", lambda x: round((x.sum() / len(x)) * 100, 1)),
        sessions=("points", "count")
    )
    return grouped


def get_session_attendance_summary(team_id: int) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)
    if df.empty:
        return pd.DataFrame()

    df["points"] = df["status"].map(STATUS_POINTS).fillna(0.0)
    grouped = df.groupby(["session_date", "title"], as_index=False).agg(
        attendance_pct=("points", lambda x: round((x.sum() / len(x)) * 100, 1)),
        records=("points", "count")
    )
    grouped = grouped.sort_values("session_date")
    return grouped


def build_signals(team_id: int) -> dict:
    stats_4w = calculate_player_stats(team_id=team_id, days=28)
    stats_3m = calculate_player_stats(team_id=team_id, days=90)
    all_att = get_attendance_with_sessions(team_id)

    signals = {
        "good": [],
        "warn": [],
        "bad": [],
    }

    if not stats_4w.empty:
        top = stats_4w.head(3)
        for _, row in top.iterrows():
            if row["sessions_count"] >= 2:
                signals["good"].append(
                    f"{row['player_name']} zit op {row['attendance_pct']}% in de laatste 4 weken."
                )

        low = stats_4w[stats_4w["attendance_pct"] < 60].head(5)
        for _, row in low.iterrows():
            signals["bad"].append(
                f"{row['player_name']} zit op slechts {row['attendance_pct']}% in de laatste 4 weken."
            )

    if not stats_3m.empty:
        shaky = stats_3m[(stats_3m["attendance_pct"] >= 60) & (stats_3m["attendance_pct"] < 80)].head(5)
        for _, row in shaky.iterrows():
            signals["warn"].append(
                f"{row['player_name']} zit op {row['attendance_pct']}% in de laatste 3 maanden."
            )

    if not all_att.empty:
        all_att["session_date"] = pd.to_datetime(all_att["session_date"])

        for player_name, pdf in all_att.groupby("player_name"):
            pdf = pdf.sort_values("session_date", ascending=False)

            absent_streak = 0
            for _, row in pdf.iterrows():
                if row["status"] in ["afwezig", "afgemeld", "geblesseerd"]:
                    absent_streak += 1
                else:
                    break
            if absent_streak >= 3:
                signals["bad"].append(f"{player_name} mist al {absent_streak} sessies op rij.")

            present_streak = 0
            for _, row in pdf.iterrows():
                if row["status"] == "aanwezig":
                    present_streak += 1
                else:
                    break
            if present_streak >= 4:
                signals["good"].append(f"{player_name} is al {present_streak} sessies op rij volledig aanwezig.")

    return signals


def build_shareable_summary(team_name: str, team_id: int) -> str:
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    latest = get_recent_session_for_team(team_id)

    lines = []
    lines.append(f"Teamoverzicht {team_name}")
    lines.append("")

    if latest is not None:
        lines.append(f"Laatste sessie: {latest['title']} op {fmt_date(latest['session_date'])} ({latest['session_type']})")
        att = get_attendance_for_session(int(latest["id"]))
        if not att.empty:
            counts = att["status"].value_counts().to_dict()
            lines.append(
                f"Aanwezig: {counts.get('aanwezig', 0)}, te laat: {counts.get('te_laat', 0)}, "
                f"deels aanwezig: {counts.get('deels_aanwezig', 0)}, afwezig: {counts.get('afwezig', 0)}, "
                f"afgemeld: {counts.get('afgemeld', 0)}, geblesseerd: {counts.get('geblesseerd', 0)}"
            )
        lines.append("")

    if not stats_4w.empty:
        lines.append("Top aanwezigheid laatste 4 weken:")
        for _, row in stats_4w.head(5).iterrows():
            lines.append(f"- {row['player_name']}: {row['attendance_pct']}%")

    lines.append("")

    if not stats_3m.empty:
        lines.append("Spelers die aandacht vragen laatste 3 maanden:")
        issues = stats_3m[stats_3m["attendance_pct"] < 60]
        if issues.empty:
            lines.append("- Geen directe aandachtssignalen.")
        else:
            for _, row in issues.head(5).iterrows():
                lines.append(f"- {row['player_name']}: {row['attendance_pct']}%")

    return "\n".join(lines)


def page_dashboard():
    st.title("🏑 Dashboard Pro")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe bij 'Teams beheren'.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    selected_team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[selected_team_name]

    players_df = get_players(team_id)
    sessions_df = get_sessions(team_id)
    stats_all = calculate_player_stats(team_id)
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    latest_session = get_recent_session_for_team(team_id)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Actieve spelers", len(players_df))
    c2.metric("Sessies totaal", len(sessions_df))
    c3.metric("Gem. 4 weken", f"{round(stats_4w['attendance_pct'].mean(), 1) if not stats_4w.empty else 0}%")
    c4.metric("Gem. 3 maanden", f"{round(stats_3m['attendance_pct'].mean(), 1) if not stats_3m.empty else 0}%")

    st.divider()

    col1, col2 = st.columns([1.1, 1])

    with col1:
        st.subheader("Laatste sessie")
        if latest_session is None:
            st.info("Nog geen sessies.")
        else:
            st.write(f"**{latest_session['title']}**")
            st.write(f"{fmt_date(latest_session['session_date'])} · {latest_session['session_type']}")
            att = get_attendance_for_session(int(latest_session["id"]))
            if att.empty:
                st.info("Nog geen aanwezigheid ingevuld.")
            else:
                counts = att["status"].value_counts().to_dict()
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Aanwezig", counts.get("aanwezig", 0))
                mc2.metric("Afwezig", counts.get("afwezig", 0) + counts.get("afgemeld", 0) + counts.get("geblesseerd", 0))
                mc3.metric("Gedeeltelijk", counts.get("te_laat", 0) + counts.get("deels_aanwezig", 0))

    with col2:
        st.subheader("Belangrijkste signalen")
        signals = build_signals(team_id)

        if not any(signals.values()):
            st.info("Nog geen signalen.")
        else:
            for msg in signals["good"][:3]:
                st.markdown(f"<div class='signal-good'>{msg}</div>", unsafe_allow_html=True)
            for msg in signals["warn"][:3]:
                st.markdown(f"<div class='signal-warn'>{msg}</div>", unsafe_allow_html=True)
            for msg in signals["bad"][:4]:
                st.markdown(f"<div class='signal-bad'>{msg}</div>", unsafe_allow_html=True)

    st.divider()

    tab1, tab2, tab3 = st.tabs(["📊 Grafieken", "🏅 Top / aandacht", "📋 Overzicht"])

    with tab1:
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("**Teamaanwezigheid per maand**")
            monthly_team = get_monthly_team_attendance(team_id)
            if monthly_team.empty:
                st.info("Nog geen data.")
            else:
                chart_df = monthly_team.set_index("month")[["attendance_pct"]]
                st.bar_chart(chart_df)

        with chart_col2:
            st.markdown("**Aanwezigheid per sessie**")
            session_summary = get_session_attendance_summary(team_id)
            if session_summary.empty:
                st.info("Nog geen data.")
            else:
                chart_df = session_summary.tail(20).set_index("session_date")[["attendance_pct"]]
                st.line_chart(chart_df)

    with tab2:
        left, right = st.columns(2)

        with left:
            st.markdown("**Beste aanwezigheid laatste 4 weken**")
            if stats_4w.empty:
                st.info("Nog geen data.")
            else:
                top_df = stats_4w.head(5)[["player_name", "attendance_pct", "sessions_count"]].copy()
                top_df.columns = ["Speler", "Aanwezigheid %", "Sessies"]
                st.dataframe(top_df, use_container_width=True, hide_index=True)

        with right:
            st.markdown("**Spelers die aandacht vragen**")
            if stats_3m.empty:
                st.info("Nog geen data.")
            else:
                issue_df = stats_3m[stats_3m["attendance_pct"] < 60][["player_name", "attendance_pct", "sessions_count"]].copy()
                if issue_df.empty:
                    st.success("Geen spelers onder 60% in de laatste 3 maanden.")
                else:
                    issue_df.columns = ["Speler", "Aanwezigheid %", "Sessies"]
                    st.dataframe(issue_df, use_container_width=True, hide_index=True)

    with tab3:
        if stats_all.empty:
            st.info("Nog geen data.")
        else:
            overview_df = stats_all.copy()
            overview_df["Signaal"] = overview_df["attendance_pct"].apply(color_for_percentage)
            overview_df = overview_df[[
                "Signaal", "player_name", "attendance_pct", "sessions_count",
                "present_count", "late_count", "partial_count",
                "absent_count", "reported_absent_count", "injured_count"
            ]]
            overview_df.columns = [
                "", "Speler", "Seizoen %", "Sessies",
                "Aanwezig", "Te laat", "Deels aanwezig",
                "Afwezig", "Afgemeld", "Geblesseerd"
            ]
            st.dataframe(overview_df, use_container_width=True, hide_index=True)


def page_manage_teams():
    st.title("👥 Teams beheren")

    with st.form("team_form"):
        name = st.text_input("Teamnaam", placeholder="Bijv. O16-1")
        age_group = st.text_input("Leeftijdsgroep", placeholder="Bijv. O16")
        season = st.text_input("Seizoen", placeholder="Bijv. 2025-2026")
        submitted = st.form_submit_button("Team toevoegen")

        if submitted:
            if not name.strip():
                st.error("Vul een teamnaam in.")
            else:
                try:
                    add_team(name, age_group, season)
                    st.success("Team toegevoegd.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Dit team bestaat al.")

    st.divider()
    teams = get_teams()
    if teams.empty:
        st.info("Nog geen teams.")
    else:
        st.dataframe(teams, use_container_width=True, hide_index=True)


def page_manage_players():
    st.title("🏃 Spelers beheren")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[team_name]

    with st.form("player_form"):
        name = st.text_input("Naam speler")
        jersey_number = st.text_input("Rugnummer")
        role = st.selectbox("Rol", ["Veldspeler", "Keeper", "Coach", "Anders"])
        submitted = st.form_submit_button("Speler toevoegen")

        if submitted:
            if not name.strip():
                st.error("Vul een naam in.")
            else:
                add_player(name, jersey_number, role, team_id)
                st.success("Speler toegevoegd.")
                st.rerun()

    st.divider()

    players_df = get_players(team_id, active_only=True)
    if players_df.empty:
        st.info("Nog geen spelers.")
    else:
        show_df = players_df[["name", "jersey_number", "role"]].copy()
        show_df.columns = ["Naam", "Rugnummer", "Rol"]
        st.dataframe(show_df, use_container_width=True, hide_index=True)

        player_map = {f"{row['name']} ({row['role']})": int(row["id"]) for _, row in players_df.iterrows()}
        if player_map:
            selected = st.selectbox("Speler deactiveren", list(player_map.keys()))
            if st.button("Deactiveer speler"):
                deactivate_player(player_map[selected])
                st.success("Speler gedeactiveerd.")
                st.rerun()


def page_sessions():
    st.title("📅 Sessies")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[team_name]

    with st.form("session_form"):
        title = st.text_input("Titel", placeholder="Bijv. Training dinsdag")
        session_date = st.date_input("Datum", value=date.today())
        start_time = st.text_input("Starttijd", placeholder="18:30")
        session_type = st.selectbox("Type", ["training", "wedstrijd", "teammeeting", "activiteit"])
        notes = st.text_area("Notities")
        submitted = st.form_submit_button("Sessie toevoegen")

        if submitted:
            if not title.strip():
                st.error("Vul een titel in.")
            else:
                add_session(
                    team_id,
                    title,
                    session_date.strftime("%Y-%m-%d"),
                    start_time,
                    session_type,
                    notes,
                )
                st.success("Sessie toegevoegd.")
                st.rerun()

    st.divider()

    sessions_df = get_sessions(team_id)
    if sessions_df.empty:
        st.info("Nog geen sessies.")
    else:
        show_df = sessions_df[["title", "session_date", "start_time", "session_type", "notes"]].copy()
        show_df.columns = ["Titel", "Datum", "Tijd", "Type", "Notities"]
        st.dataframe(show_df, use_container_width=True, hide_index=True)


def page_attendance():
    st.title("✅ Snelle aanwezigheid invoeren")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[team_name]

    sessions_df = get_sessions(team_id)
    players_df = get_players(team_id)

    if sessions_df.empty:
        st.info("Maak eerst een sessie aan.")
        return

    if players_df.empty:
        st.info("Voeg eerst spelers toe.")
        return

    session_map = {
        f"{row['session_date']} - {row['title']} ({row['session_type']})": int(row["id"])
        for _, row in sessions_df.iterrows()
    }
    session_label = st.selectbox("Kies sessie", list(session_map.keys()))
    session_id = session_map[session_label]

    existing_df = get_attendance_for_session(session_id)

    base_df = players_df[["id", "name", "role"]].copy()
    base_df["status"] = "aanwezig"
    base_df["reason"] = ""
    base_df["note"] = ""

    if not existing_df.empty:
        existing_small = existing_df[["player_id", "status", "reason", "note"]].copy()
        base_df = base_df.merge(
            existing_small,
            left_on="id",
            right_on="player_id",
            how="left",
            suffixes=("", "_saved")
        )

        base_df["status"] = base_df["status_saved"].fillna(base_df["status"])
        base_df["reason"] = base_df["reason_saved"].fillna(base_df["reason"])
        base_df["note"] = base_df["note_saved"].fillna(base_df["note"])

        base_df = base_df.drop(
            columns=["player_id", "status_saved", "reason_saved", "note_saved"],
            errors="ignore"
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Iedereen aanwezig"):
            bulk_set_status_for_session(session_id, players_df["id"].tolist(), "aanwezig")
            st.success("Iedereen is op aanwezig gezet.")
            st.rerun()
    with c2:
        if st.button("Iedereen afgemeld"):
            bulk_set_status_for_session(session_id, players_df["id"].tolist(), "afgemeld")
            st.success("Iedereen is op afgemeld gezet.")
            st.rerun()
    with c3:
        if st.button("Iedereen afwezig"):
            bulk_set_status_for_session(session_id, players_df["id"].tolist(), "afwezig")
            st.success("Iedereen is op afwezig gezet.")
            st.rerun()

    st.divider()
    st.markdown("**Pas hieronder de aanwezigheid aan en klik daarna opnieuw op opslaan.**")

    editor_df = pd.DataFrame({
        "player_id": base_df["id"],
        "Speler": base_df["name"],
        "Rol": base_df["role"],
        "Status": base_df["status"],
        "Reden": base_df["reason"],
        "Notitie": base_df["note"],
    })

    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        key=f"attendance_editor_{session_id}",
        column_config={
            "player_id": st.column_config.NumberColumn("ID", disabled=True),
            "Speler": st.column_config.TextColumn("Speler", disabled=True),
            "Rol": st.column_config.TextColumn("Rol", disabled=True),
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=STATUS_OPTIONS,
                required=True,
            ),
            "Reden": st.column_config.TextColumn("Reden"),
            "Notitie": st.column_config.TextColumn("Notitie"),
        },
        disabled=["player_id", "Speler", "Rol"],
    )

    col_save, col_reset = st.columns(2)

    with col_save:
        if st.button("💾 Aanwezigheid opslaan", type="primary", use_container_width=True):
            for _, row in edited_df.iterrows():
                upsert_attendance(
                    session_id=int(session_id),
                    player_id=int(row["player_id"]),
                    status=str(row["Status"]),
                    reason="" if pd.isna(row["Reden"]) else str(row["Reden"]),
                    note="" if pd.isna(row["Notitie"]) else str(row["Notitie"]),
                )
            st.success("Aanwezigheid opgeslagen of bijgewerkt.")
            st.rerun()

    with col_reset:
        if st.button("Herlaad opgeslagen gegevens", use_container_width=True):
            st.rerun()

    st.divider()

    current_df = get_attendance_for_session(session_id)
    st.subheader("Huidige opgeslagen aanwezigheid")

    if current_df.empty:
        st.info("Nog geen opgeslagen aanwezigheid voor deze sessie.")
    else:
        current_df = current_df.copy()
        current_df["Status zichtbaar"] = current_df["status"].map(
            lambda x: f"{STATUS_COLORS.get(x, '')} {STATUS_LABELS.get(x, x)}"
        )
        show_df = current_df[["player_name", "Status zichtbaar", "reason", "note"]].copy()
        show_df.columns = ["Speler", "Status", "Reden", "Notitie"]
        st.dataframe(show_df, use_container_width=True, hide_index=True)


def page_player_overview():
    st.title("📊 Spelersoverzicht")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[team_name]

    players_df = get_players(team_id)
    if players_df.empty:
        st.info("Nog geen spelers.")
        return

    stats_all = calculate_player_stats(team_id)
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)

    rows = []
    for _, player in players_df.iterrows():
        pid = int(player["id"])
        rows.append({
            "": color_for_percentage(pct_or_zero(stats_all, pid)),
            "Speler": player["name"],
            "Rol": player["role"],
            "Laatste 4 weken %": pct_or_zero(stats_4w, pid),
            "Laatste 3 maanden %": pct_or_zero(stats_3m, pid),
            "Seizoen %": pct_or_zero(stats_all, pid),
            "Sessies": safe_sessions_count(stats_all, pid),
        })

    show_df = pd.DataFrame(rows)
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.divider()

    player_map = {row["name"]: int(row["id"]) for _, row in players_df.iterrows()}
    selected_player_name = st.selectbox("Speler detail", list(player_map.keys()))
    player_id = player_map[selected_player_name]

    c1, c2, c3 = st.columns(3)
    c1.metric("Seizoen", f"{pct_or_zero(stats_all, player_id)}%")
    c2.metric("Laatste 4 weken", f"{pct_or_zero(stats_4w, player_id)}%")
    c3.metric("Laatste 3 maanden", f"{pct_or_zero(stats_3m, player_id)}%")

    monthly_player = get_monthly_player_attendance(team_id, player_id)
    if not monthly_player.empty:
        st.markdown("**Maandgrafiek speler**")
        st.bar_chart(monthly_player.set_index("month")[["attendance_pct"]])

    history_df = get_player_history(player_id)
    if history_df.empty:
        st.info("Nog geen historie.")
    else:
        history_df["Status"] = history_df["status"].map(lambda x: f"{STATUS_COLORS.get(x, '')} {STATUS_LABELS.get(x, x)}")
        history_df["session_date"] = history_df["session_date"].apply(fmt_date)
        show_history = history_df[["session_date", "title", "session_type", "Status", "reason", "note"]].copy()
        show_history.columns = ["Datum", "Sessie", "Type", "Status", "Reden", "Notitie"]
        st.dataframe(show_history, use_container_width=True, hide_index=True)


def page_staff_view():
    st.title("🔗 Staf / deelweergave")

    teams = get_teams()
    if teams.empty:
        st.info("Voeg eerst een team toe.")
        return

    team_options = {row["name"]: int(row["id"]) for _, row in teams.iterrows()}
    team_name = st.selectbox("Kies team", list(team_options.keys()))
    team_id = team_options[team_name]

    st.markdown("**Samenvatting om te delen met staf of teammanager**")
    summary = build_shareable_summary(team_name, team_id)
    st.text_area("Deeltekst", value=summary, height=260)

    st.download_button(
        "Download samenvatting als txt",
        data=summary.encode("utf-8"),
        file_name=f"samenvatting_{team_name.replace(' ', '_')}.txt",
        mime="text/plain",
    )

    export_df = get_attendance_with_sessions(team_id)
    if export_df.empty:
        st.info("Nog geen exportdata.")
        return

    export_df = export_df[[
        "team_name", "session_date", "title", "session_type",
        "player_name", "status", "reason", "note"
    ]].copy()

    export_df["status"] = export_df["status"].map(lambda x: STATUS_LABELS.get(x, x))

    export_df.columns = [
        "Team", "Datum", "Sessie", "Type",
        "Speler", "Status", "Reden", "Notitie"
    ]

    st.markdown("**Volledige export**")
    st.dataframe(export_df, use_container_width=True, hide_index=True)

    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=f"attendance_{team_name.replace(' ', '_')}.csv",
        mime="text/csv",
    )

    st.info(
        "Zodra je deze app op Streamlit Cloud zet, kun je de link delen met staf of teammanager. "
        "Iedereen met de link kan dan meekijken. Voor echte privé-accounts en logins is later een volgende versie nodig."
    )


def main():
    init_db()
    migrate_old_statuses()

    st.sidebar.title("Navigatie")
    page = st.sidebar.radio(
        "Ga naar",
        [
            "Dashboard",
            "Teams beheren",
            "Spelers beheren",
            "Sessies",
            "Aanwezigheid",
            "Spelersoverzicht",
            "Staf / deelweergave",
        ]
    )

    if page == "Dashboard":
        page_dashboard()
    elif page == "Teams beheren":
        page_manage_teams()
    elif page == "Spelers beheren":
        page_manage_players()
    elif page == "Sessies":
        page_sessions()
    elif page == "Aanwezigheid":
        page_attendance()
    elif page == "Spelersoverzicht":
        page_player_overview()
    elif page == "Staf / deelweergave":
        page_staff_view()


if __name__ == "__main__":
    main()