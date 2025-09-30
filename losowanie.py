import streamlit as st
import pandas as pd
import random
from io import BytesIO

st.set_page_config(page_title="Losowanie zespołów", layout="wide")

st.title("👥 Losowanie osób do zespołów")

# Tryb organizatora lub uczestnika
mode = st.radio("Wybierz tryb", ["🎛️ Organizator", "🔍 Uczestnik"])

# Przechowujemy dane w sesji
if "balanced_teams" not in st.session_state:
    st.session_state.balanced_teams = []
if "team_lookup" not in st.session_state:
    st.session_state.team_lookup = {}

# Organizator
if mode == "🎛️ Organizator":
    uploaded_file = st.file_uploader("📂 Wybierz plik Excel (.xlsx) z listą osób", type=["xlsx"])

    def normalize_col(col):
        return col.strip().lower().replace(".", "")

    expected_cols_map = {
        'lp': 'Lp.',
        'nazwisko': 'Nazwisko',
        'imię': 'Imię',
        'imi': 'Imię',
        'stanowisko': 'Stanowisko',
        'dział': 'DZIAŁ',
        'dzial': 'DZIAŁ'
    }

    if uploaded_file:
        try:
            df_raw = pd.read_excel(uploaded_file)
            cleaned_cols = [normalize_col(c) for c in df_raw.columns]
            mapped_cols = {}
            for i, col in enumerate(cleaned_cols):
                if col in expected_cols_map:
                    mapped_cols[expected_cols_map[col]] = df_raw.columns[i]

            required_keys = ['Lp.', 'Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']
            if all(col in mapped_cols for col in required_keys):
                df = df_raw.rename(columns={v: k for k, v in mapped_cols.items()})
                st.success("✅ Plik poprawnie wczytany.")

                num_teams = st.number_input("🔢 Liczba zespołów", min_value=2, max_value=20, value=7)

                if st.button("🎯 Rozlosuj zespoły"):
                    participants = df.copy()
                    teams = [[] for _ in range(num_teams)]

                    grouped = participants.groupby("DZIAŁ")
                    for dept, group in grouped:
                        shuffled = group.sample(frac=1).to_dict("records")
                        for i, person in enumerate(shuffled):
                            teams[i % num_teams].append(person)

                    flat_people = [p for team in teams for p in team]
                    random.shuffle(flat_people)

                    base_team_size = len(flat_people) // num_teams
                    extra = len(flat_people) % num_teams

                    balanced_teams = []
                    start = 0
                    for i in range(num_teams):
                        size = base_team_size + (1 if i < extra else 0)
                        team = sorted(flat_people[start:start+size], key=lambda x: x["Nazwisko"])
                        balanced_teams.append(team)
                        start += size

                    # Zapisujemy do sesji
                    st.session_state.balanced_teams = balanced_teams
                    team_lookup = {}
                    for i, team in enumerate(balanced_teams):
                        for person in team:
                            key = f"{person['Imię']} {person['Nazwisko']}".strip().lower()
                            team_lookup[key] = {
                                "team_number": i + 1,
                                "team_members": team
                            }
                    st.session_state.team_lookup = team_lookup

                    # Prezentacja zespołów
                    cols = st.columns(num_teams)
                    for i, col in enumerate(cols):
                        col.markdown(f"### 👥 Zespół {i + 1}")
                        for person in balanced_teams[i]:
                            col.markdown(f"- {person['Nazwisko']} {person['Imię']} ({person['DZIAŁ']})")

                    # Eksport
                    def to_excel(teams):
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            for i, team in enumerate(teams):
                                team_df = pd.DataFrame(team)
                                team_df = team_df[['Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']]
                                team_df.to_excel(writer, index=False, sheet_name=f'Zespół {i+1}')
                        output.seek(0)
                        return output

                    excel_data = to_excel(balanced_teams)
                    st.download_button(
                        label="💾 Pobierz wyniki jako Excel",
                        data=excel_data,
                        file_name="wyniki_losowania.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            else:
                missing = [col for col in required_keys if col not in mapped_cols]
                st.error(f"❌ Brakuje kolumn: {', '.join(missing)}")

        except Exception as e:
            st.error(f"❌ Błąd: {e}")

# Uczestnik
if mode == "🔍 Uczestnik":
    if not st.session_state.team_lookup:
        st.warning("🔒 Dane zespołów nie są jeszcze załadowane przez organizatora.")
    else:
        st.subheader("🔍 Sprawdź swój zespół")
        full_name = st.text_input("Wpisz **Imię i Nazwisko** (dokładnie):").strip().lower()

        if full_name:
            if full_name in st.session_state.team_lookup:
                info = st.session_state.team_lookup[full_name]
                st.success(f"✅ Jesteś w Zespole {info['team_number']}")
                st.markdown("👥 **Skład zespołu:**")
                for member in info["team_members"]:
                    st.markdown(f"- {member['Nazwisko']} {member['Imię']} ({member['DZIAŁ']})")
            else:
                st.error("❌ Nie znaleziono takiej osoby.")
