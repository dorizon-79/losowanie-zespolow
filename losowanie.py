import streamlit as st
import pandas as pd
import random
from io import BytesIO
import unicodedata
import difflib

st.set_page_config(page_title="Losowanie zespołów", layout="wide")
st.title("👥 Losowanie osób do zespołów")

# ===== współdzielony store między sesjami =====
@st.cache_resource
def get_store():
    # spójny magazyn: zespoły + lookup + lista kluczy
    return {"balanced_teams": None, "team_lookup": None, "all_keys": []}

STORE = get_store()

# ===== pomocnicze =====
def normalize_col(col): return col.strip().lower().replace(".", "")

def strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def squash_spaces(s: str) -> str:
    return " ".join((s or "").split())

def norm_name(s: str) -> str:
    # bez ogonków, małe litery, zbite spacje
    return squash_spaces(strip_accents(s)).lower()

def build_keys(first_name: str, last_name: str):
    # akceptujemy "imie nazwisko" i "nazwisko imie"
    key1 = norm_name(f"{first_name} {last_name}")
    key2 = norm_name(f"{last_name} {first_name}")
    return {key1, key2}

def build_lookup_from_teams(balanced_teams):
    team_lookup, all_keys = {}, []
    for i, team in enumerate(balanced_teams):
        for p in team:
            for k in build_keys(p['Imię'], p['Nazwisko']):
                team_lookup[k] = {"team_number": i + 1, "team_members": team}
                all_keys.append(k)
    return team_lookup, all_keys

expected_cols_map = {
    'lp': 'Lp.','nazwisko': 'Nazwisko','imię': 'Imię','imi': 'Imię',
    'stanowisko': 'Stanowisko','dział': 'DZIAŁ','dzial': 'DZIAŁ'
}

mode = st.radio("Wybierz tryb", ["🎛️ Organizator", "🔍 Uczestnik"])

# ====== ORGANIZATOR ======
if mode == "🎛️ Organizator":
    uploaded_file = st.file_uploader("📂 Wybierz plik Excel (.xlsx) z listą osób", type=["xlsx"])

    if uploaded_file:
        try:
            df_raw = pd.read_excel(uploaded_file)
            cleaned_cols = [normalize_col(c) for c in df_raw.columns]
            mapped_cols = { expected_cols_map[c]: df_raw.columns[i]
                            for i, c in enumerate(cleaned_cols) if c in expected_cols_map }
            required = ['Lp.', 'Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']
            if not all(c in mapped_cols for c in required):
                st.error(f"❌ Brakuje kolumn: {', '.join([c for c in required if c not in mapped_cols])}")
            else:
                df = df_raw.rename(columns={v:k for k,v in mapped_cols.items()})
                # czyszczenie pól tekstowych
                for col in ['Imię','Nazwisko','Stanowisko','DZIAŁ']:
                    df[col] = df[col].astype(str).map(squash_spaces)

                st.success(f"✅ Plik wczytany. Osób: {len(df)}")
                num_teams = st.number_input("🔢 Liczba zespołów", 2, 20, 7)

                if st.button("🎯 Rozlosuj zespoły"):
                    participants = df.copy()
                    # 1) rozkład wg działów
                    raw_teams = [[] for _ in range(num_teams)]
                    for _, grp in participants.groupby("DZIAŁ"):
                        for i, person in enumerate(grp.sample(frac=1).to_dict("records")):
                            raw_teams[i % num_teams].append(person)
                    # 2) wyrównanie
                    pool = [p for t in raw_teams for p in t]
                    random.shuffle(pool)
                    base, extra = len(pool)//num_teams, len(pool)%num_teams
                    balanced = []
                    s = 0
                    for i in range(num_teams):
                        size = base + (1 if i < extra else 0)
                        team = sorted(pool[s:s+size], key=lambda x: x["Nazwisko"])
                        balanced.append(team); s += size

                    st.session_state["balanced_teams"] = balanced

                    # podgląd
                    cols = st.columns(num_teams)
                    for i, col in enumerate(cols):
                        col.markdown(f"### 👥 Zespół {i+1}")
                        for p in balanced[i]:
                            col.markdown(f"- {p['Nazwisko']} {p['Imię']} ({p['DZIAŁ']})")

                if st.session_state.get("balanced_teams"):
                    # publikacja buduje lookup od zera -> spójnie
                    if st.button("📣 Opublikuj wyniki dla uczestników"):
                        lookup, keys = build_lookup_from_teams(st.session_state["balanced_teams"])
                        STORE["balanced_teams"] = st.session_state["balanced_teams"]
                        STORE["team_lookup"] = lookup
                        STORE["all_keys"] = keys
                        st.success("✅ Opublikowano! Uczestnicy mogą już wyszukiwać.")

                    # opcjonalnie: wyczyść publikację
                    if st.button("🧹 Wyczyść publikację"):
                        STORE["balanced_teams"] = None
                        STORE["team_lookup"] = None
                        STORE["all_keys"] = []
                        st.info("🧹 Publikacja wyczyszczona.")

                    # eksport
                    def to_excel(teams):
                        out = BytesIO()
                        with pd.ExcelWriter(out, engine='openpyxl') as w:
                            for i, t in enumerate(teams):
                                pd.DataFrame(t)[['Nazwisko','Imię','Stanowisko','DZIAŁ']].to_excel(
                                    w, index=False, sheet_name=f'Zespół {i+1}')
                        out.seek(0); return out
                    st.download_button("💾 Pobierz wyniki jako Excel",
                        to_excel(st.session_state["balanced_teams"]),
                        "wyniki_losowania.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"❌ Błąd: {e}")

# ====== UCZESTNIK ======
if mode == "🔍 Uczestnik":
    if not STORE["team_lookup"]:
        st.warning("🔒 Wyniki nie są jeszcze opublikowane przez organizatora.")
    else:
        st.subheader("🔍 Sprawdź swój zespół")
        full_name_in = st.text_input("Wpisz imię i nazwisko **lub** nazwisko i imię (dokładnie):")
        selected_key = None

        if full_name_in:
            key = norm_name(full_name_in)
            info = STORE["team_lookup"].get(key)

            if not info:
                # klikalne podpowiedzi
                suggestions = difflib.get_close_matches(key, STORE.get("all_keys", []), n=5, cutoff=0.75)
                if suggestions:
                    st.error("❌ Nie znaleziono takiej osoby. Może chodzi o:")
                    cols = st.columns(min(len(suggestions), 5))
                    for i, s in enumerate(suggestions):
                        if cols[i].button(s.title(), key=f"sugg_{i}"):
                            selected_key = s
                else:
                    st.error("❌ Nie znaleziono takiej osoby.")

            # jeżeli kliknięto podpowiedź – pokaż wynik
            if selected_key:
                info = STORE["team_lookup"].get(selected_key)

            if info:
                st.success(f"✅ Jesteś w Zespole {info['team_number']}")
                st.markdown("👥 **Skład zespołu:**")
                for m in info["team_members"]:
                    st.markdown(f"- {m['Nazwisko']} {m['Imię']} ({m['DZIAŁ']})")
