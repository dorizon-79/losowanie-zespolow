import streamlit as st
import pandas as pd
import random
from io import BytesIO
import unicodedata

st.set_page_config(page_title="Losowanie zespołów", layout="wide")
st.title("👥 Losowanie osób do zespołów")

# ===== Wspólny magazyn danych (współdzielony między sesjami) =====
@st.cache_resource
def get_store():
    # Mutowalny obiekt współdzielony: działa między sesjami na Streamlit Cloud
    return {"balanced_teams": None, "team_lookup": None}

STORE = get_store()

# ===== Pomocnicze =====
def normalize_col(col):
    return col.strip().lower().replace(".", "")

def strip_accents(s: str) -> str:
    # usunięcie ogonków – tak, żeby "Dobrzyński" == "DobrzyNski" == "dobrzynski"
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def norm_name(s: str) -> str:
    # normalizacja wpisu użytkownika: spacje, wielkość, ogonki
    s = strip_accents(s or "")
    s = " ".join(s.split())  # zbicie wielu spacji
    return s.lower()

def build_keys(first_name: str, last_name: str):
    # zwróć dwa klucze: "imie nazwisko" i "nazwisko imie" po normalizacji
    key1 = norm_name(f"{first_name} {last_name}")
    key2 = norm_name(f"{last_name} {first_name}")
    return {key1, key2}

expected_cols_map = {
    'lp': 'Lp.',
    'nazwisko': 'Nazwisko',
    'imię': 'Imię',
    'imi': 'Imię',
    'stanowisko': 'Stanowisko',
    'dział': 'DZIAŁ',
    'dzial': 'DZIAŁ'
}

mode = st.radio("Wybierz tryb", ["🎛️ Organizator", "🔍 Uczestnik"])

# ====== ORGANIZATOR ======
if mode == "🎛️ Organizator":
    uploaded_file = st.file_uploader("📂 Wybierz plik Excel (.xlsx) z listą osób", type=["xlsx"])

    if uploaded_file:
        try:
            df_raw = pd.read_excel(uploaded_file)
            cleaned_cols = [normalize_col(c) for c in df_raw.columns]
            mapped_cols = {}
            for i, col in enumerate(cleaned_cols):
                if col in expected_cols_map:
                    mapped_cols[expected_cols_map[col]] = df_raw.columns[i]

            required_keys = ['Lp.', 'Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']
            if not all(col in mapped_cols for col in required_keys):
                missing = [col for col in required_keys if col not in mapped_cols]
                st.error(f"❌ Brakuje kolumn: {', '.join(missing)}")
            else:
                df = df_raw.rename(columns={v: k for k, v in mapped_cols.items()})
                st.success("✅ Plik poprawnie wczytany.")

                num_teams = st.number_input("🔢 Liczba zespołów", min_value=2, max_value=20, value=7)

                if st.button("🎯 Rozlosuj zespoły"):
                    participants = df.copy()

                    # 1) rozkład wg działów (tasowanie w działach)
                    teams = [[] for _ in range(num_teams)]
                    for dept, group in participants.groupby("DZIAŁ"):
                        shuffled = group.sample(frac=1).to_dict("records")
                        for i, person in enumerate(shuffled):
                            teams[i % num_teams].append(person)

                    # 2) wyrównanie liczebności (różnica <= 1)
                    flat_people = [p for team in teams for p in team]
                    random.shuffle(flat_people)
                    base = len(flat_people) // num_teams
                    extra = len(flat_people) % num_teams

                    balanced_teams = []
                    start = 0
                    for i in range(num_teams):
                        size = base + (1 if i < extra else 0)
                        team = sorted(flat_people[start:start+size], key=lambda x: x["Nazwisko"])
                        balanced_teams.append(team)
                        start += size

                    # 3) lookup dla wyszukiwarki (akceptujemy oba układy nazw)
                    team_lookup = {}
                    for i, team in enumerate(balanced_teams):
                        for person in team:
                            for key in build_keys(person['Imię'], person['Nazwisko']):
                                team_lookup[key] = {"team_number": i + 1, "team_members": team}

                    # zapis do sesji organizatora
                    st.session_state["balanced_teams"] = balanced_teams
                    st.session_state["team_lookup"] = team_lookup

                    # podgląd
                    cols = st.columns(num_teams)
                    for i, col in enumerate(cols):
                        col.markdown(f"### 👥 Zespół {i + 1}")
                        for person in balanced_teams[i]:
                            col.markdown(f"- {person['Nazwisko']} {person['Imię']} ({person['DZIAŁ']})")

                # Publikacja do wspólnego magazynu (dla wszystkich uczestników)
                if "balanced_teams" in st.session_state and st.session_state["balanced_teams"]:
                    if st.button("📣 Opublikuj wyniki dla uczestników"):
                        STORE["balanced_teams"] = st.session_state["balanced_teams"]
                        STORE["team_lookup"] = st.session_state["team_lookup"]
                        st.success("✅ Opublikowano! Uczestnicy mogą już wyszukiwać swoje zespoły.")

                    # eksport XLSX
                    def to_excel(teams):
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            for i, team in enumerate(teams):
                                team_df = pd.DataFrame(team)
                                team_df = team_df[['Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']]
                                team_df.to_excel(writer, index=False, sheet_name=f'Zespół {i+1}')
                        output.seek(0)
                        return output

                    excel_data = to_excel(st.session_state["balanced_teams"])
                    st.download_button(
                        label="💾 Pobierz wyniki jako Excel",
                        data=excel_data,
                        file_name="wyniki_losowania.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        except Exception as e:
            st.error(f"❌ Błąd: {e}")

# ====== UCZESTNIK ======
if mode == "🔍 Uczestnik":
    if not STORE["team_lookup"]:
        st.warning("🔒 Wyniki nie są jeszcze opublikowane przez organizatora.")
    else:
        st.subheader("🔍 Sprawdź swój zespół")
        full_name_in = st.text_input("Wpisz imię i nazwisko **lub** nazwisko i imię (dokładnie):")

        if full_name_in:
            key = norm_name(full_name_in)
            info = STORE["team_lookup"].get(key)
            if info:
                st.success(f"✅ Jesteś w Zespole {info['team_number']}")
                st.markdown("👥 **Skład zespołu:**")
                for member in info["team_members"]:
                    st.markdown(f"- {member['Nazwisko']} {member['Imię']} ({member['DZIAŁ']})")
            else:
                st.error("❌ Nie znaleziono takiej osoby.")
