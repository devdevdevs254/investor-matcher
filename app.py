import streamlit as st
import pandas as pd
import sqlite3
import os
import pdfkit
import smtplib
from email.message import EmailMessage

DB_FILE = "green_finance.db"

# --- Setup database ---
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS investors (
        id INTEGER PRIMARY KEY,
        name TEXT,
        sector_focus TEXT,
        min_investment_size REAL,
        preferred_esg_criteria TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        name TEXT,
        sector TEXT,
        location TEXT,
        funding_needed REAL,
        sustainability_impact TEXT,
        esg_tags TEXT,
        readiness_level TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_notes (
        investor_name TEXT,
        project_name TEXT,
        interested INTEGER,
        notes TEXT,
        PRIMARY KEY (investor_name, project_name)
    )""")
    conn.commit()
    conn.close()

# --- Upload CSV files to DB ---
def upload_csv_to_db(file, table_name):
    if file is not None:
        try:
            df = pd.read_csv(file)
            conn = sqlite3.connect(DB_FILE)
            df.to_sql(table_name, conn, if_exists="replace", index=False)
            conn.close()
            st.success(f"✅ {table_name.capitalize()} table updated successfully.")
        except Exception as e:
            st.error(f"❌ Failed to upload CSV: {e}")

# --- Parse ESG tags ---
def parse_esg_tags(tags):
    return set(tag.strip().lower() for tag in tags.replace("E:", "").replace("S:", "").replace("G:", "").split(","))

# --- Matching logic with ESG filter ---
def match_projects_to_investor(investor_row, projects_df, selected_tags):
    investor_sector = str(investor_row['sector_focus']).lower()
    try:
        min_investment = float(investor_row['min_investment_size'])
    except ValueError:
        st.error("❌ Invalid value in 'min_investment_size'. Please check your investors.csv.")
        return pd.DataFrame()

    preferred_esg = set(str(investor_row['preferred_esg_criteria']).lower().split(","))
    matches = []

    for _, p in projects_df.iterrows():
        sector = str(p['sector']).lower()
        funding = float(p['funding_needed'])
        esg_tags = parse_esg_tags(p['esg_tags'])
        esg_score = len(preferred_esg.intersection(esg_tags))

        if sector == investor_sector and funding >= min_investment and esg_score > 0:
            if any(tag.strip()[0].upper() in selected_tags for tag in p['esg_tags'].split(",")):
                matches.append({
                    'Project Name': p['name'],
                    'Sector': p['sector'],
                    'Funding Needed': funding,
                    'ESG Score': esg_score,
                    'Readiness': p.get('readiness_level', 'Idea')
                })

    return pd.DataFrame(sorted(matches, key=lambda x: (-x['ESG Score'], x['Funding Needed']))) if matches else pd.DataFrame()

# --- Export PDF report ---
def export_pdf(df, investor_name):
    html = df.to_html(index=False)
    pdfkit.from_string(html, f"{investor_name}_matches.pdf")

# --- Email PDF ---
def send_email_with_pdf(recipient, pdf_path, investor_name):
    msg = EmailMessage()
    msg['Subject'] = f"{investor_name} – Project Matches"
    msg['From'] = "your_email@gmail.com"
    msg['To'] = recipient
    msg.set_content("Attached is your matched project report.")
    with open(pdf_path, 'rb') as f:
        msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename=os.path.basename(pdf_path))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login("your_email@gmail.com", "your_app_password")
        smtp.send_message(msg)

# --- Main App ---
def main():
    st.title("🌱 Green Project-Investor Matcher")

    setup_database()

    st.sidebar.header("⬆️ Upload Data")
    investor_csv = st.sidebar.file_uploader("Upload investors.csv", type=["csv"])
    project_csv = st.sidebar.file_uploader("Upload projects.csv", type=["csv"])

    if st.sidebar.button("📥 Upload & Replace Data"):
        if investor_csv:
            upload_csv_to_db(investor_csv, "investors")
        if project_csv:
            upload_csv_to_db(project_csv, "projects")

    selected_tags = st.sidebar.multiselect("Filter by ESG dimensions", ["E", "S", "G"], default=["E", "S", "G"])

    conn = sqlite3.connect(DB_FILE)
    investors = pd.read_sql("SELECT * FROM investors", conn)
    projects = pd.read_sql("SELECT * FROM projects", conn)
    conn.close()

    if investors.empty or projects.empty:
        st.warning("⚠️ No data found. Please upload both investors and projects CSVs.")
        return

    selected_investor = st.selectbox("Select Investor", investors["name"])
    if selected_investor:
        investor_row = investors[investors["name"] == selected_investor].iloc[0]
        st.subheader("Investor Profile")
        st.write(investor_row)

        st.subheader("🔍 Matched Projects")
        match_df = match_projects_to_investor(investor_row, projects, selected_tags)
        st.write(match_df if not match_df.empty else "❌ No matches found.")

        if not match_df.empty:
            conn = sqlite3.connect(DB_FILE)
            for _, row in match_df.iterrows():
                key = f"{investor_row['name']}_{row['Project Name']}"
                st.markdown(f"### {row['Project Name']}")
                interested = st.checkbox("Interested?", key=f"{key}_check")
                notes = st.text_area("Notes", key=f"{key}_notes")
                conn.execute("""
                    INSERT OR REPLACE INTO project_notes (investor_name, project_name, interested, notes)
                    VALUES (?, ?, ?, ?)
                """, (investor_row['name'], row['Project Name'], int(interested), notes))

                # Show readiness level as badge
                readiness = row.get('Readiness', 'Idea')
                color_map = {"Idea": "gray", "Prototype": "orange", "Piloted": "blue", "Scalable": "green"}
                color = color_map.get(readiness, "black")
                st.markdown(f"<span style='color:{color}; font-weight:bold'>🟢 {readiness}</span>", unsafe_allow_html=True)
            conn.commit()
            conn.close()

            if st.button("📤 Export Report to PDF"):
                export_pdf(match_df, investor_row['name'])

            recipient_email = st.text_input("Enter your email to receive matches")
            if st.button("📧 Email Report") and recipient_email:
                export_pdf(match_df, investor_row['name'])
                send_email_with_pdf(recipient_email, f"{investor_row['name']}_matches.pdf", investor_row['name'])
                st.success("✅ Email sent!")

        st.subheader("📊 Funding Gaps by Sector")
        st.bar_chart(projects.groupby("sector")["funding_needed"].sum())

        st.subheader("🔥 ESG Tag Heatmap")
        all_tags = projects["esg_tags"].str.split(",").explode().str.strip().value_counts()
        st.bar_chart(all_tags)

        st.subheader("🔎 Explore All Projects")
        selected_sector = st.selectbox("Filter by sector", ["All"] + list(projects['sector'].unique()))
        selected_tags_explore = st.multiselect("ESG tags", ["E", "S", "G"])
        min_funding, max_funding = st.slider("Funding range", 0, 100000, (10000, 50000))

        filtered = projects[
            (projects['funding_needed'].between(min_funding, max_funding)) &
            (projects['esg_tags'].str.contains("|".join(selected_tags_explore), case=False)) &
            ((projects['sector'] == selected_sector) if selected_sector != "All" else True)
        ]
        st.dataframe(filtered)

if __name__ == "__main__":
    main()