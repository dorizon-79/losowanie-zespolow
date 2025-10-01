# --- Parametr widoku z URL + layout mobilny dla uczestnika ---
import streamlit as st
view_param = (st.query_params.get("view", "") or "").lower()
locked_participant = view_param in {"ucz", "participant", "u", "p"}

st.set_page_config(
    page_title="Losowanie zespołów",
    layout=("centered" if locked_participant else "wide"),
)

import pandas as pd
import random
from io import BytesIO
import unicodedata
import difflib
import qrcode

# =================== Hasło tylko dla organizatora ===================
ORGANIZER_PASSWORD = st.secrets.get("ORGANIZER_PASSWORD", "warsztaty")

def require_organizer_password():
    if st.session_state.get("authed", False):
        return
    st.markdown("### 🔒 Dostęp organizatora")
    with st.form("login"):
        pwd = st.text_input("Hasło", type="password", placeholder="wpisz hasło…")
        ok = st.form_submit_button("Zaloguj")
    if ok:
        if pwd == ORGANIZER_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Nieprawidłowe hasło.")
    st.stop()

# Krótszy tytuł w widoku uczestnika (telefon), pełny u organizatora
title_text = "👥 Losowanie Zespołów" if locked_participant else "👥 Losowanie osób do zespołów"
st.title(title_text)

# --- Usprawnienia mobilne: przewijanie + mniejsze marginesy + auto-scroll do inputu ---
if locked_participant:
    st.markdown("""
    <style>
      [data-testid="stToolbar"] { display: none !important; }
      html, body, [data-testid="stAppViewContainer"], .block-container {
          height: auto !important;
          overflow: visible !important;
      }
      @media (max-width: 768px) {
        .block-container { padding-top: 0.5rem !important; padding-bottom: 6rem !important; }
        h1 { font-size: 1.6rem !important; }
        h2 { font-size: 1.25rem !important; }
      }
    </style>
    """, unsafe_allow_html=True)
    import streamlit.components.v1 as components
    components.html("""
    <script>
    window.addEventListener('load', function () {
      const root = window.parent.document;
      const inp = root.querySelector('input[type="text"]');
      if (!inp) return;
      ['focus','click'].forEach(ev => {
        inp.addEventListener(ev, () => {
          setTimeout(() => { inp.scrollIntoView({behavior:'smooth', block:'center'}); }, 150);
        });
      });
    });
    </script>
    """, height=0)

# ========= Wspólny magazyn (współdzielony między sesjami) =========
@st.cache_resource
def get_store():
    return {
        "balanced_teams": None,       # list[list[dict]]
        "team_lookup": None,          # key -> {team_number, team_members}
        "all_keys": [],               # list[str]
        "display_name_map": {},       # key -> "Imię Nazwisko" (z ogonkami)
    }
STORE = get_store()

# ======================= Pomocnicze =======================
def normalize_col(col: str) -> str:
    return col.strip().lower().replace(".", "")

def strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def squash_spaces(s: str) -> str:
    return " ".join((s or "").split())

def norm_name(s: str) -> str:
    return squash_spaces(strip_accents(s)).lower()

def build_keys(first_name: str, last_name: str):
    key1 = norm_name(f"{first_name} {last_name}")
    key2 = norm_name(f"{last_name} {first_name}")
    return {key1, key2}

def build_lookup_from_teams(balanced_teams):
    team_lookup, all_keys, display_name_map = {}, [], {}
    for i, team in enumerate(balanced_teams):
        for p in team:
            pretty = f"{p['Imię']} {p['Nazwisko']}".strip()
            for k in build_keys(p['Imię'], p['Nazwisko']):
                team_lookup[k] = {"team_number": i + 1, "team_members": team}
                all_keys.append(k)
                display_name_map[k] = pretty
    return team_lookup, all_keys, display_name_map

def make_qr_png(data: str) -> BytesIO:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

expected_cols_map = {
    'lp': 'Lp.','nazwisko': 'Nazwisko','imię': 'Imię','imi': 'Imię',
    'stanowisko': 'Stanowisko','dział': 'DZIAŁ','dzial': 'DZIAŁ'
}

# =================== Blokada trybu organizatora ===================
if locked_participant:
    mode = "🔍 Uczestnik"
else:
    mode = st.radio("Wybierz tryb", ["🎛️ Organizator", "🔍 Uczestnik"])

# ========================== ORGANIZATOR ==========================
if mode == "🎛️ Organizator":
    require_organizer_password()

    uploaded_file = st.file_uploader("📂 Wybierz plik Excel (.xlsx) z listą osób", type=["xlsx"])

    if uploaded_file:
        try:
            df_raw = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"❌ Błąd odczytu pliku: {e}")
        else:
            cleaned_cols = [normalize_col(c) for c in df_raw.columns]
            mapped_cols = { expected_cols_map[c]: df_raw.columns[i]
                            for i, c in enumerate(cleaned_cols) if c in expected_cols_map }
            required = ['Lp.', 'Nazwisko', 'Imię', 'Stanowisko', 'DZIAŁ']
            if not all(c in mapped_cols for c in required):
                st.error(f"❌ Brakuje kolumn: {', '.join([c for c in required if c not in mapped_cols])}")
            else:
                df = df_raw.rename(columns={v:k for k,v in mapped_cols.items()})
                for col in ['Imię','Nazwisko','Stanowisko','DZIAŁ']:
                    df[col] = df[col].astype(str).map(squash_spaces)

                st.success(f"✅ Plik wczytany. Osób: {len(df)}")
                num_teams = st.number_input("🔢 Liczba zespołów", 2, 20, 7)

                if st.button("🎯 Rozlosuj zespoły"):
                    participants = df.copy()
                    N = len(participants)
                    K = num_teams

                    # Docelowe rozmiary zespołów (różnica ≤ 1)
                    base = N // K
                    extra = N % K
                    targets = [base + (1 if i < extra else 0) for i in range(K)]

                    # Puste zespoły + licznik zajętości
                    teams = [[] for _ in range(K)]
                    sizes = [0] * K

                    # Aby nie faworyzować kolejności działów – tasujemy ich listę
                    depts = list(participants.groupby("DZIAŁ"))
                    random.shuffle(depts)

                    # Przydział działami – rundami – z poszanowaniem capacity (targets)
                    for dept, group in depts:
                        members = group.sample(frac=1).to_dict("records")  # tasujemy osoby w dziale
                        # RUNDY: najpierw po 1 na zespół (z capacity), potem nadwyżki
                        while members:
                            # kandydaci: zespoły z wolnym miejscem
                            candidates = [i for i in range(K) if sizes[i] < targets[i]]
                            if not candidates:
                                # teoretycznie nie powinno się zdarzyć, ale na wszelki wypadek
                                candidates = list(range(K))
                            random.shuffle(candidates)  # aby nadwyżki szły losowo
                            for ti in candidates:
                                if not members:
                                    break
                                # przydziel 1 osobę z tego działu do zespołu 'ti'
                                person = members.pop()
                                teams[ti].append(person)
                                sizes[ti] += 1
                                # nie dodajemy więcej z tego działu do tego zespołu w tej rundzie,
                                # bo idziemy dalej po kandydatach -> "po jednej zanim zaczniemy dublować"

                    # Sortowanie w zespołach po nazwisku do prezentacji/eksportu
                    for i in range(K):
                        teams[i] = sorted(teams[i], key=lambda x: x["Nazwisko"])

                    st.session_state["balanced_teams"] = teams

                # podgląd + publikacja
                if st.session_state.get("balanced_teams"):
                    teams = st.session_state["balanced_teams"]
                    K = len(teams)

                    st.markdown("### 📋 Podgląd zespołów")
                    cols = st.columns(K)
                    for i, col in enumerate(cols):
                        col.markdown(f"### 👥 Zespół {i+1}")
                        for p in teams[i]:
                            # BEZ DZIAŁU
                            col.markdown(f"- {p['Nazwisko']} {p['Imię']}")

                    if st.button("📣 Opublikuj wyniki dla uczestników"):
                        lookup, keys, display_map = build_lookup_from_teams(teams)
                        STORE["balanced_teams"]   = teams
                        STORE["team_lookup"]      = lookup
                        STORE["all_keys"]         = keys
                        STORE["display_name_map"] = display_map
                        st.success("✅ Opublikowano! Poniżej link i QR tylko dla uczestników.")

                    if STORE["team_lookup"]:
                        st.markdown("---")
                        st.markdown("### 🔗 Link i QR dla uczestników (tylko wyszukiwarka)")
                        base_url = st.text_input(
                            "Wklej adres Twojej aplikacji (bez parametrów):",
                            placeholder="https://twoja-nazwa.streamlit.app"
                        )
                        if base_url:
                            participant_url = base_url.rstrip("/") + "/?view=ucz"
                            st.code(participant_url, language="text")
                            png = make_qr_png(participant_url)
                            st.image(png, caption="QR dla uczestników")
                            st.download_button("📥 Pobierz QR (PNG)", data=png,
                                file_name="qr_uczestnik.png", mime="image/png")

                        # eksport XLSX (dla organizatora pełne dane)
                        def to_excel(teams):
                            out = BytesIO()
                            with pd.ExcelWriter(out, engine='openpyxl') as w:
                                for i, t in enumerate(teams):
                                    pd.DataFrame(t)[['Nazwisko','Imię','Stanowisko','DZIAŁ']].to_excel(
                                        w, index=False, sheet_name=f'Zespół {i+1}')
                            out.seek(0); return out
                        st.download_button("💾 Pobierz wyniki jako Excel",
                            to_excel(teams),
                            "wyniki_losowania.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                    if st.button("🚪 Wyloguj organizatora"):
                        st.session_state["authed"] = False
                        st.success("Wylogowano.")
                        st.rerun()

# ========================== UCZESTNIK ==========================
if mode == "🔍 Uczestnik":
    if not STORE["team_lookup"]:
        st.warning("🔒 Wyniki nie są jeszcze opublikowane przez organizatora.")
    else:
        st.subheader("🔍 Sprawdź swój zespół")
        full_name_in = st.text_input("Wpisz imię i nazwisko **lub** nazwisko i imię (dokładnie):")
        selected_key = None
        info = None

        def norm_query(q: str) -> str:
            return norm_name(q)

        if full_name_in:
            key = norm_query(full_name_in)
            info = STORE["team_lookup"].get(key)

            if not info:
                suggestions = difflib.get_close_matches(key, STORE.get("all_keys", []), n=5, cutoff=0.75)
                if suggestions:
                    st.info("🔎 Nie znaleziono dokładnego dopasowania. Może chodzi o:")
                    cols = st.columns(min(len(suggestions), 5))
                    for i, s in enumerate(suggestions):
                        pretty = STORE["display_name_map"].get(s, s.title())
                        if cols[i].button(pretty, key=f"sugg_{i}"):
                            selected_key = s
                else:
                    st.error("❌ Nie znaleziono takiej osoby.")

            if selected_key:
                info = STORE["team_lookup"].get(selected_key)

        if info:
            st.success(f"✅ Jesteś w Zespole {info['team_number']}")
            st.markdown("👥 **Skład zespołu:**")
            for m in info["team_members"]:
                # BEZ DZIAŁU
                st.markdown(f"- {m['Nazwisko']} {m['Imię']}")
