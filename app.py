import hashlib
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st

DB_NAME = "attendance_app.db"

st.set_page_config(
    page_title="Aanwezigheidsapp Team",
    page_icon="🏑",
    layout="wide",
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
    max-width: 1250px;
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
.login-box {
    max-width: 520px;
    margin: 0 auto;
    padding: 20px;
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.03);
}
.info-box {
    padding: 12px;
    border-radius: 12px;
    border: 1px solid rgba(59,130,246,0.25);
    background: rgba(59,130,246,0.10);
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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams(id)
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


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384,
        r=8,
        p=1
    )
    return f"{salt}${hashed.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, hashed_hex = stored_hash.split("$", 1)
        new_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16384,
            r=8,
            p=1
        ).hex()
        return secrets.compare_digest(new_hash, hashed_hex)
    except Exception:
        return False


def count_users() -> int:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        return int(cur.fetchone()[0])


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


# -----------------------------
# AUTH
# -----------------------------
def get_user_by_username(username: str) -> Optional[dict]:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.team_id, u.full_name, u.username, u.password_hash, t.name
            FROM users u
            JOIN teams t ON u.team_id = t.id
            WHERE LOWER(u.username) = LOWER(?)
        """, (username.strip(),))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "team_id": row[1],
            "full_name": row[2],
            "username": row[3],
            "password_hash": row[4],
            "team_name": row[5],
        }


def create_team_and_user(team_name: str, age_group: str, season: str, full_name: str, username: str, password: str):
    with closing(get_connection()) as conn:
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO teams (name, age_group, season) VALUES (?, ?, ?)",
            (team_name.strip(), age_group.strip(), season.strip())
        )
        team_id = cur.lastrowid

        cur.execute(
            "INSERT INTO users (team_id, full_name, username, password_hash) VALUES (?, ?, ?, ?)",
            (team_id, full_name.strip(), username.strip(), hash_password(password))
        )
        conn.commit()


def create_extra_user_for_team(team_id: int, full_name: str, username: str, password: str):
    run_query(
        "INSERT INTO users (team_id, full_name, username, password_hash) VALUES (?, ?, ?, ?)",
        (team_id, full_name.strip(), username.strip(), hash_password(password))
    )


def update_current_user_password(user_id: int, new_password: str):
    run_query(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user_id)
    )


def login(username: str, password: str) -> bool:
    user = get_user_by_username(username)
    if not user:
        return False

    if not verify_password(password, user["password_hash"]):
        return False

    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user["id"]
    st.session_state["team_id"] = user["team_id"]
    st.session_state["team_name"] = user["team_name"]
    st.session_state["full_name"] = user["full_name"]
    st.session_state["username"] = user["username"]
    return True


def logout():
    for key in ["logged_in", "user_id", "team_id", "team_name", "full_name", "username"]:
        if key in st.session_state:
            del st.session_state[key]


def require_login():
    return st.session_state.get("logged_in", False)


# -----------------------------
# DATA
# -----------------------------
def get_team(team_id: int) -> pd.DataFrame:
    return run_query_df("SELECT * FROM teams WHERE id = ?", (team_id,))


def get_players(team_id: int, active_only: bool = True) -> pd.DataFrame:
    query = """
        SELECT p.id, p.name, p.jersey_number, p.role, p.team_id, p.active
        FROM players p
        WHERE p.team_id = ?
    """
    params = [team_id]

    if active_only:
        query += " AND p.active = 1"

    query += " ORDER BY p.name"
    return run_query_df(query, tuple(params))


def add_player(name: str, jersey_number: str, role: str, team_id: int):
    run_query("""
        INSERT INTO players (name, jersey_number, role, team_id, active)
        VALUES (?, ?, ?, ?, 1)
    """, (name.strip(), jersey_number.strip(), role.strip(), team_id))


def deactivate_player(player_id: int, team_id: int):
    run_query("UPDATE players SET active = 0 WHERE id = ? AND team_id = ?", (player_id, team_id))


def get_sessions(team_id: int) -> pd.DataFrame:
    return run_query_df("""
        SELECT id, title, session_date, start_time, session_type, notes, team_id
        FROM sessions
        WHERE team_id = ?
        ORDER BY session_date DESC, start_time DESC
    """, (team_id,))


def add_session(team_id: int, title: str, session_date: str, start_time: str, session_type: str, notes: str):
    run_query("""
        INSERT INTO sessions (team_id, title, session_date, start_time, session_type, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (team_id, title.strip(), session_date, start_time, session_type.strip(), notes.strip()))


def update_session(session_id: int, team_id: int, title: str, session_date: str, start_time: str, session_type: str, notes: str):
    run_query("""
        UPDATE sessions
        SET title = ?, session_date = ?, start_time = ?, session_type = ?, notes = ?
        WHERE id = ? AND team_id = ?
    """, (title.strip(), session_date, start_time, session_type.strip(), notes.strip(), session_id, team_id))


def delete_session(session_id: int, team_id: int):
    session_df = run_query_df("SELECT id FROM sessions WHERE id = ? AND team_id = ?", (session_id, team_id))
    if session_df.empty:
        return
    run_query("DELETE FROM attendance WHERE session_id = ?", (session_id,))
    run_query("DELETE FROM sessions WHERE id = ? AND team_id = ?", (session_id, team_id))


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
    for pid in player_ids:
        upsert_attendance(session_id, pid, status, "", "")


def get_attendance_for_session(session_id: int, team_id: int) -> pd.DataFrame:
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
        JOIN sessions s ON a.session_id = s.id
        WHERE a.session_id = ? AND s.team_id = ?
        ORDER BY p.name
    """, (session_id, team_id))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)
    return df


def get_attendance_with_sessions(team_id: int) -> pd.DataFrame:
    df = run_query_df("""
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
            s.title,
            s.session_date,
            s.session_type
        FROM attendance a
        JOIN players p ON a.player_id = p.id
        JOIN sessions s ON a.session_id = s.id
        WHERE s.team_id = ?
        ORDER BY s.session_date DESC
    """, (team_id,))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)
    return df


def get_player_history(player_id: int, team_id: int) -> pd.DataFrame:
    df = run_query_df("""
        SELECT
            s.session_date,
            s.title,
            s.session_type,
            a.status,
            a.reason,
            a.note
        FROM attendance a
        JOIN sessions s ON a.session_id = s.id
        JOIN players p ON a.player_id = p.id
        WHERE a.player_id = ? AND p.team_id = ?
        ORDER BY s.session_date DESC
    """, (player_id, team_id))

    if not df.empty:
        df["status"] = df["status"].apply(normalize_status)
    return df


# -----------------------------
# ANALYSE
# -----------------------------
def calculate_player_stats(team_id: int, days: Optional[int] = None) -> pd.DataFrame:
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


def get_player_session_type_stats(team_id: int, player_id: int) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)
    if df.empty:
        return pd.DataFrame()

    df = df[df["player_id"] == player_id].copy()
    if df.empty:
        return pd.DataFrame()

    df["points"] = df["status"].map(STATUS_POINTS).fillna(0.0)
    grouped = df.groupby("session_type", as_index=False).agg(
        aanwezigheid_pct=("points", lambda x: round((x.sum() / len(x)) * 100, 1)),
        sessies=("points", "count")
    )
    grouped = grouped.sort_values(["aanwezigheid_pct", "session_type"], ascending=[False, True])
    return grouped


def get_player_status_distribution(team_id: int, player_id: int, limit_sessions: int = 12) -> pd.DataFrame:
    df = get_attendance_with_sessions(team_id)
    if df.empty:
        return pd.DataFrame()

    df = df[df["player_id"] == player_id].copy()
    if df.empty:
        return pd.DataFrame()

    df["session_date"] = pd.to_datetime(df["session_date"])
    df = df.sort_values("session_date", ascending=False).head(limit_sessions)
    grouped = df.groupby("status", as_index=False).agg(aantal=("status", "count"))
    grouped["status_label"] = grouped["status"].map(lambda x: STATUS_LABELS.get(x, x))
    grouped = grouped.sort_values("aantal", ascending=False)
    return grouped


def build_signals(team_id: int) -> dict:
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    all_att = get_attendance_with_sessions(team_id)

    signals = {"good": [], "warn": [], "bad": []}

    if not stats_4w.empty:
        for _, row in stats_4w.head(3).iterrows():
            if row["sessions_count"] >= 2:
                signals["good"].append(f"{row['player_name']} zit op {row['attendance_pct']}% in de laatste 4 weken.")

        low = stats_4w[stats_4w["attendance_pct"] < 60].head(5)
        for _, row in low.iterrows():
            signals["bad"].append(f"{row['player_name']} zit op slechts {row['attendance_pct']}% in de laatste 4 weken.")

    if not stats_3m.empty:
        shaky = stats_3m[(stats_3m["attendance_pct"] >= 60) & (stats_3m["attendance_pct"] < 80)].head(5)
        for _, row in shaky.iterrows():
            signals["warn"].append(f"{row['player_name']} zit op {row['attendance_pct']}% in de laatste 3 maanden.")

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


def build_player_signals(team_id: int, player_id: int, player_name: str) -> list[str]:
    signals = []
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    hist = get_player_history(player_id, team_id)

    pct4 = pct_or_zero(stats_4w, player_id)
    pct3 = pct_or_zero(stats_3m, player_id)

    if pct4 >= 90 and safe_sessions_count(stats_4w, player_id) >= 3:
        signals.append(f"{player_name} heeft een sterke aanwezigheid in de laatste 4 weken ({pct4}%).")
    elif 0 < pct4 < 60:
        signals.append(f"{player_name} vraagt aandacht in de laatste 4 weken ({pct4}%).")

    if pct3 >= 85 and safe_sessions_count(stats_3m, player_id) >= 5:
        signals.append(f"{player_name} is structureel sterk aanwezig over de laatste 3 maanden ({pct3}%).")
    elif 0 < pct3 < 60:
        signals.append(f"{player_name} zit ook over 3 maanden onder de gewenste norm ({pct3}%).")

    if not hist.empty:
        hist = hist.copy()
        hist["session_date"] = pd.to_datetime(hist["session_date"])

        present_streak = 0
        for _, row in hist.iterrows():
            if row["status"] == "aanwezig":
                present_streak += 1
            else:
                break
        if present_streak >= 4:
            signals.append(f"{player_name} is {present_streak} sessies op rij volledig aanwezig.")

        absent_streak = 0
        for _, row in hist.iterrows():
            if row["status"] in ["afwezig", "afgemeld", "geblesseerd"]:
                absent_streak += 1
            else:
                break
        if absent_streak >= 2:
            signals.append(f"{player_name} heeft {absent_streak} sessies op rij gemist.")

    if not signals:
        signals.append(f"Nog geen opvallende analyse voor {player_name}.")
    return signals


def build_shareable_summary(team_name: str, team_id: int) -> str:
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    latest = get_recent_session_for_team(team_id)

    lines = [f"Teamoverzicht {team_name}", ""]

    if latest is not None:
        lines.append(f"Laatste sessie: {latest['title']} op {fmt_date(latest['session_date'])} ({latest['session_type']})")
        att = get_attendance_for_session(int(latest["id"]), team_id)
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


# -----------------------------
# PAGINA'S LOGIN
# -----------------------------
def page_first_setup():
    st.title("🔐 Eerste keer instellen")
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.write("Maak hieronder het eerste teamaccount aan.")

    with st.form("first_setup_form"):
        team_name = st.text_input("Teamnaam", placeholder="Bijv. O16-1")
        age_group = st.text_input("Leeftijdsgroep", placeholder="Bijv. O16")
        season = st.text_input("Seizoen", placeholder="Bijv. 2025-2026")
        full_name = st.text_input("Jouw naam", placeholder="Bijv. Pepijn")
        username = st.text_input("Gebruikersnaam", placeholder="Bijv. o16coach")
        password = st.text_input("Wachtwoord", type="password")
        password_repeat = st.text_input("Herhaal wachtwoord", type="password")
        submitted = st.form_submit_button("Account aanmaken")

        if submitted:
            if not team_name.strip() or not full_name.strip() or not username.strip() or not password.strip():
                st.error("Vul alle verplichte velden in.")
            elif password != password_repeat:
                st.error("De wachtwoorden zijn niet gelijk.")
            elif len(password) < 6:
                st.error("Kies een wachtwoord van minimaal 6 tekens.")
            else:
                try:
                    create_team_and_user(team_name, age_group, season, full_name, username, password)
                    st.success("Teamaccount aangemaakt. Log nu in.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Deze teamnaam of gebruikersnaam bestaat al.")

    st.markdown("</div>", unsafe_allow_html=True)


def page_login():
    st.title("🏑 Inloggen")
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("Gebruikersnaam")
        password = st.text_input("Wachtwoord", type="password")
        submitted = st.form_submit_button("Inloggen")

        if submitted:
            if login(username, password):
                st.success("Succesvol ingelogd.")
                st.rerun()
            else:
                st.error("Onjuiste gebruikersnaam of wachtwoord.")

    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# PAGINA'S APP
# -----------------------------
def page_dashboard(team_id: int, team_name: str):
    st.title(f"🏑 Dashboard — {team_name}")

    players_df = get_players(team_id)
    sessions_df = get_sessions(team_id)
    stats_4w = calculate_player_stats(team_id, days=28)
    stats_3m = calculate_player_stats(team_id, days=90)
    stats_all = calculate_player_stats(team_id)
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
            att = get_attendance_for_session(int(latest_session["id"]), team_id)
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
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**Teamaanwezigheid per maand**")
            monthly_team = get_monthly_team_attendance(team_id)
            if monthly_team.empty:
                st.info("Nog geen data.")
            else:
                st.bar_chart(monthly_team.set_index("month")[["attendance_pct"]])

        with col_b:
            st.markdown("**Aanwezigheid per sessie**")
            session_summary = get_session_attendance_summary(team_id)
            if session_summary.empty:
                st.info("Nog geen data.")
            else:
                st.line_chart(session_summary.tail(20).set_index("session_date")[["attendance_pct"]])

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


def page_manage_players(team_id: int):
    st.title("🏃 Spelers beheren")

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
                deactivate_player(player_map[selected], team_id)
                st.success("Speler gedeactiveerd.")
                st.rerun()


def page_sessions(team_id: int):
    st.title("📅 Sessies")

    tab1, tab2 = st.tabs(["Nieuwe sessie", "Sessie bewerken"])

    with tab1:
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

    with tab2:
        sessions_df = get_sessions(team_id)
        if sessions_df.empty:
            st.info("Nog geen sessies om te bewerken.")
        else:
            session_map = {
                f"{row['session_date']} - {row['title']} ({row['session_type']})": int(row["id"])
                for _, row in sessions_df.iterrows()
            }
            chosen_label = st.selectbox("Kies sessie", list(session_map.keys()))
            chosen_id = session_map[chosen_label]

            current = sessions_df[sessions_df["id"] == chosen_id].iloc[0]

            with st.form("edit_session_form"):
                new_title = st.text_input("Titel", value=current["title"])
                current_date = pd.to_datetime(current["session_date"]).date()
                new_date = st.date_input("Datum", value=current_date)
                new_time = st.text_input("Starttijd", value=current["start_time"] if pd.notna(current["start_time"]) else "")
                type_options = ["training", "wedstrijd", "teammeeting", "activiteit"]
                default_type_index = type_options.index(current["session_type"]) if current["session_type"] in type_options else 0
                new_type = st.selectbox("Type", type_options, index=default_type_index)
                new_notes = st.text_area("Notities", value=current["notes"] if pd.notna(current["notes"]) else "")

                c1, c2 = st.columns(2)
                with c1:
                    save = st.form_submit_button("Sessie opslaan", use_container_width=True)
                with c2:
                    delete = st.form_submit_button("Sessie verwijderen", use_container_width=True)

                if save:
                    if not new_title.strip():
                        st.error("Vul een titel in.")
                    else:
                        update_session(
                            chosen_id,
                            team_id,
                            new_title,
                            new_date.strftime("%Y-%m-%d"),
                            new_time,
                            new_type,
                            new_notes,
                        )
                        st.success("Sessie bijgewerkt.")
                        st.rerun()

                if delete:
                    delete_session(chosen_id, team_id)
                    st.success("Sessie verwijderd.")
                    st.rerun()

    st.divider()

    st.subheader("Bestaande sessies")
    sessions_df = get_sessions(team_id)
    if sessions_df.empty:
        st.info("Nog geen sessies.")
    else:
        show_df = sessions_df[["title", "session_date", "start_time", "session_type", "notes"]].copy()
        show_df.columns = ["Titel", "Datum", "Tijd", "Type", "Notities"]
        st.dataframe(show_df, use_container_width=True, hide_index=True)


def page_attendance(team_id: int):
    st.title("✅ Snelle aanwezigheid invoeren")

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

    existing_df = get_attendance_for_session(session_id, team_id)

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

        base_df = base_df.drop(columns=["player_id", "status_saved", "reason_saved", "note_saved"], errors="ignore")

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
            "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, required=True),
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

    current_df = get_attendance_for_session(session_id, team_id)
    st.subheader("Huidige opgeslagen aanwezigheid")

    if current_df.empty:
        st.info("Nog geen opgeslagen aanwezigheid voor deze sessie.")
    else:
        current_df = current_df.copy()
        current_df["Status zichtbaar"] = current_df["status"].map(lambda x: f"{STATUS_COLORS.get(x, '')} {STATUS_LABELS.get(x, x)}")
        show_df = current_df[["player_name", "Status zichtbaar", "reason", "note"]].copy()
        show_df.columns = ["Speler", "Status", "Reden", "Notitie"]
        st.dataframe(show_df, use_container_width=True, hide_index=True)


def page_player_overview(team_id: int):
    st.title("📊 Spelersoverzicht & analyse")

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

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "Trend",
        "Per type sessie",
        "Statusverdeling",
        "Historie & signalen"
    ])

    with tab1:
        monthly_player = get_monthly_player_attendance(team_id, player_id)
        if monthly_player.empty:
            st.info("Nog geen data voor deze speler.")
        else:
            st.markdown("**Maandtrend aanwezigheid**")
            st.bar_chart(monthly_player.set_index("month")[["attendance_pct"]])

            trend_df = monthly_player.copy()
            trend_df.columns = ["Maand", "Aanwezigheid %", "Sessies"]
            st.dataframe(trend_df, use_container_width=True, hide_index=True)

    with tab2:
        type_df = get_player_session_type_stats(team_id, player_id)
        if type_df.empty:
            st.info("Nog geen sessietypes om te analyseren.")
        else:
            st.markdown("**Aanwezigheid per type sessie**")
            chart_df = type_df.set_index("session_type")[["aanwezigheid_pct"]]
            st.bar_chart(chart_df)

            show_type_df = type_df.copy()
            show_type_df.columns = ["Type sessie", "Aanwezigheid %", "Sessies"]
            st.dataframe(show_type_df, use_container_width=True, hide_index=True)

    with tab3:
        dist_df = get_player_status_distribution(team_id, player_id, limit_sessions=12)
        if dist_df.empty:
            st.info("Nog geen recente statusdata.")
        else:
            st.markdown("**Statusverdeling laatste 12 sessies**")
            chart_df = dist_df.set_index("status_label")[["aantal"]]
            st.bar_chart(chart_df)

            show_dist_df = dist_df[["status_label", "aantal"]].copy()
            show_dist_df.columns = ["Status", "Aantal"]
            st.dataframe(show_dist_df, use_container_width=True, hide_index=True)

    with tab4:
        st.markdown("**Automatische analyse**")
        for s in build_player_signals(team_id, player_id, selected_player_name):
            st.write(f"- {s}")

        history_df = get_player_history(player_id, team_id)
        if history_df.empty:
            st.info("Nog geen historie.")
        else:
            history_df["Status"] = history_df["status"].map(lambda x: f"{STATUS_COLORS.get(x, '')} {STATUS_LABELS.get(x, x)}")
            history_df["session_date"] = history_df["session_date"].apply(fmt_date)
            show_history = history_df[["session_date", "title", "session_type", "Status", "reason", "note"]].copy()
            show_history.columns = ["Datum", "Sessie", "Type", "Status", "Reden", "Notitie"]
            st.dataframe(show_history, use_container_width=True, hide_index=True)


def page_staff_view(team_id: int, team_name: str):
    st.title("🔗 Staf / deelweergave")

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
        "session_date", "title", "session_type",
        "player_name", "status", "reason", "note"
    ]].copy()

    export_df["status"] = export_df["status"].map(lambda x: STATUS_LABELS.get(x, x))
    export_df.columns = ["Datum", "Sessie", "Type", "Speler", "Status", "Reden", "Notitie"]

    st.markdown("**Volledige export**")
    st.dataframe(export_df, use_container_width=True, hide_index=True)

    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name=f"attendance_{team_name.replace(' ', '_')}.csv",
        mime="text/csv",
    )


def page_account(team_id: int):
    st.title("🔐 Account beheren")

    st.subheader("Wachtwoord wijzigen")
    with st.form("change_password_form"):
        new_password = st.text_input("Nieuw wachtwoord", type="password")
        repeat_password = st.text_input("Herhaal nieuw wachtwoord", type="password")
        submitted = st.form_submit_button("Wachtwoord opslaan")

        if submitted:
            if not new_password.strip():
                st.error("Vul een nieuw wachtwoord in.")
            elif len(new_password) < 6:
                st.error("Kies een wachtwoord van minimaal 6 tekens.")
            elif new_password != repeat_password:
                st.error("De wachtwoorden zijn niet gelijk.")
            else:
                update_current_user_password(st.session_state["user_id"], new_password)
                st.success("Wachtwoord bijgewerkt.")

    st.divider()

    st.subheader("Extra gebruiker voor dit team toevoegen")
    with st.form("extra_user_form"):
        full_name = st.text_input("Naam nieuwe gebruiker")
        username = st.text_input("Gebruikersnaam nieuwe gebruiker")
        password = st.text_input("Wachtwoord nieuwe gebruiker", type="password")
        submitted_user = st.form_submit_button("Gebruiker toevoegen")

        if submitted_user:
            if not full_name.strip() or not username.strip() or not password.strip():
                st.error("Vul alle velden in.")
            elif len(password) < 6:
                st.error("Kies een wachtwoord van minimaal 6 tekens.")
            else:
                try:
                    create_extra_user_for_team(team_id, full_name, username, password)
                    st.success("Gebruiker toegevoegd aan dit team.")
                except sqlite3.IntegrityError:
                    st.error("Deze gebruikersnaam bestaat al.")


# -----------------------------
# MAIN
# -----------------------------
def main():
    init_db()
    migrate_old_statuses()

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if count_users() == 0:
        page_first_setup()
        return

    if not require_login():
        page_login()
        return

    team_id = st.session_state["team_id"]
    team_name = st.session_state["team_name"]
    full_name = st.session_state["full_name"]

    st.sidebar.title("Navigatie")
    st.sidebar.markdown(f"**Ingelogd als:** {full_name}")
    st.sidebar.markdown(f"**Team:** {team_name}")

    if st.sidebar.button("Uitloggen", use_container_width=True):
        logout()
        st.rerun()

    page = st.sidebar.radio(
        "Ga naar",
        [
            "Dashboard",
            "Spelers beheren",
            "Sessies",
            "Aanwezigheid",
            "Spelersoverzicht",
            "Staf / deelweergave",
            "Account beheren",
        ]
    )

    if page == "Dashboard":
        page_dashboard(team_id, team_name)
    elif page == "Spelers beheren":
        page_manage_players(team_id)
    elif page == "Sessies":
        page_sessions(team_id)
    elif page == "Aanwezigheid":
        page_attendance(team_id)
    elif page == "Spelersoverzicht":
        page_player_overview(team_id)
    elif page == "Staf / deelweergave":
        page_staff_view(team_id, team_name)
    elif page == "Account beheren":
        page_account(team_id)


if __name__ == "__main__":
    main()
