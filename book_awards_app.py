"""
book_awards_app.py
Streamlit app: search book awards CSV, leaderboard, Goodreads ratings, mark-as-read + personal rating.
"""

import streamlit as st
import pandas as pd
import requests
import sqlite3
import time
import urllib.parse
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
import numpy as np
from bs4 import BeautifulSoup
import os
from datetime import datetime
import altair as alt

# ---------- CONFIG ----------
DB_PATH = "user_books.db"      # local sqlite file to persist read status & personal ratings
GOODREADS_SEARCH = "https://goodreads-unofficial.herokuapp.com/search?q={q}"
GOODREADS_BOOK = "https://goodreads-unofficial.herokuapp.com/book/{book_id}"
# Note: This is an unofficial endpoint useful for small/personal projects; may be rate-limited or go down.
# Replace with your preferred 3rd-party API if needed.

# ---------- DATABASE HELPERS ----------
def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_books (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT,
            read INTEGER DEFAULT 0,
            rating INTEGER,            -- user's personal rating 0.5-5
            updated_at REAL
        )
        """
    )
    conn.commit()

def upsert_user_book(conn, title, author, read=None, rating=None):
    now = time.time()
    cur = conn.cursor()
    # Check if exists
    cur.execute("SELECT id FROM user_books WHERE title = ? AND (author = ? OR author IS NULL OR ? IS NULL)", (title, author, author))
    row = cur.fetchone()
    if row:
        # update
        set_fields = []
        params = []
        if read is not None:
            set_fields.append("read = ?")
            params.append(1 if read else 0)
        if rating is not None:
            set_fields.append("rating = ?")
            params.append(int(rating) if rating is not None and not pd.isna(rating) else None)
        set_fields.append("updated_at = ?")
        params.append(now)
        params.append(title)
        params.append(author)
        sql = f"UPDATE user_books SET {', '.join(set_fields)} WHERE title = ? AND (author = ? OR author IS NULL OR ? IS NULL)"
        cur.execute(sql, params)
    else:
        cur.execute(
            "INSERT INTO user_books (title, author, read, rating, updated_at) VALUES (?,?,?,?,?)",
            (title, author, 1 if read else 0 if read is not None else 0, int(rating) if rating is not None and not pd.isna(rating) else None, now),
        )
    conn.commit()

def get_user_book(conn, title, author):
    cur = conn.cursor()
    cur.execute("SELECT read, rating FROM user_books WHERE title = ? AND (author = ? OR author IS NULL OR ? IS NULL)", (title, author, author))
    r = cur.fetchone()
    if r:
        return {"read": bool(r[0]), "rating": int(r[1]) if r[1] is not None else None}
    return {"read": False, "rating": None}

def get_all_user_books(conn):
    df = pd.read_sql("SELECT * FROM user_books", conn)
    return df

# ---------- APP UI ----------
st.set_page_config(page_title="Book Accolades Library", layout="wide")
st.markdown(
    """
    <div style="
        text-align: left;
        font-size: 36px;
        font-weight: bold;
        color: #333333;
        text-shadow: 
            0 0 5px #8FBC8F,
            0 0 10px #8FBC8F,
            0 0 15px #8FBC8F;
    ">
        Book Accolades Library
    </div>
    <hr style="border: 1px solid #ccc; margin-top: 10px; margin-bottom: 20px;">
    """,
    unsafe_allow_html=True
)

# DB connection
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
conn = engine.raw_connection()
init_db(conn)

# Load CSVs
df_awards = pd.read_csv("Export/Awards_Lists_Clubs.csv")
df_books = pd.read_csv("Export/books_with_ratings_and_info.csv")

# Normalize column names
df_awards.columns = df_awards.columns.str.strip()
df_books.columns = df_books.columns.str.strip()

# Identify author-only accolades in df_awards
df_awards["Is_Author_Only"] = df_awards["Title"].isna() | (df_awards["Title"].str.strip() == "")

# Compute book-specific award counts
award_counts = df_awards.groupby(["Title", "Author"], dropna=False).size().reset_index(name="Accolade_Count")

# Merge book info into award_counts
info_cols = ["Title", "Author", "average_rating", "num_ratings", "published_year", "genres", "description", "notes"]
info_df = df_books[info_cols].drop_duplicates(subset=["Title", "Author"])
award_counts = award_counts.merge(info_df, on=["Title", "Author"], how="left")

# Compute author-only accolades (Nobel Prizes etc.)
author_only_acc = (
    df_awards[df_awards["Is_Author_Only"]]
    .groupby("Author", as_index=False)
    .agg({"Accolade": "nunique"})
    .rename(columns={"Accolade": "Author_Only_Accolades"})
)

award_counts = award_counts.merge(author_only_acc, on="Author", how="left")
award_counts["Author_Only_Accolades"] = award_counts["Author_Only_Accolades"].fillna(0)

# Total accolades = book + author-only
award_counts["Total_Accolades"] = award_counts["Accolade_Count"] + award_counts["Author_Only_Accolades"]

# Initialize base_df
base_df = None

# Main app
# Sidebar navigation
st.sidebar.title("Navigation")
view = st.sidebar.radio(
    "Go to:",
    [
        "📚 Top by Accolades",
        "🔍 Search Books",
        "🏆 Search Accolades",
        "📖 Your Books"
    ]
)

# Default to Top by Accolades if nothing is selected (though radio always selects first)
if view not in ["📚 Top by Accolades", "🔍 Search Books", "🏆 Search Accolades", "📖 Your Books"]:
    view = "📚 Top by Accolades"

# Info box below navigation
info_box = st.sidebar.container()
with info_box:
    if view == "📚 Top by Accolades":
        st.markdown(
            """
            **Top by Accolades**

            Shows books sorted by the number of awards they've won, then average Goodreads rating, then by number of Goodreads ratings. 
            Select a book using the box in the Select column to view additional details about the book.
            """
        )
    elif view == "🔍 Search Books":
        st.markdown(
            """
            **Search Books**

            Search for specific books by title or author.
            """
        )
    elif view == "🏆 Search Accolades":
        st.markdown(
            """
            **Search Accolades**

            See which books won specific awards. If you select multiple awards it will display the books that have won both or all awards that are selected.
            """
        )
    elif view == "📖 Your Books":
        st.markdown(
            """
            **Your Books**

            View your full reading history and ratings. Visualize Goodreads data. View all the book titles and authors in the database. 
            """
        )

# Map selection to your existing page logic
choice = view.replace("📚 ", "").replace("🔍 ", "").replace("🏆 ", "").replace("📖 ", "")

if choice == "Top by Accolades":
    st.subheader("Top Books by Accolade")
    top_n = st.slider("How many top books?", 5, 50, 10)

    # Sort by Total_Accolades, average_rating, then num_ratings
    top = (
        award_counts
        .groupby(["Title", "Author"], as_index=False)
        .agg({
            "Total_Accolades": "max",
            "average_rating": "max",
            "num_ratings": "max",
        })
        .sort_values(
            by=["Total_Accolades", "average_rating", "num_ratings"],
            ascending=[False, False, False]  # all descending
        )
        .head(top_n)
        .rename(columns={"Total_Accolades": "Accolade_Count"})
    )

    base_df = top

elif choice == "Search Books":
    st.subheader("Search Books")
    query = st.text_input("Enter book title or author to search:")

    if query:
        filtered = award_counts[
            award_counts["Title"].str.contains(query, case=False, na=False) |
            award_counts["Author"].str.contains(query, case=False, na=False)
        ]

        base_df = (
    filtered
    .groupby(["Title", "Author"], as_index=False)
    .agg({
        "Total_Accolades": "max",
        "average_rating": "max",
        "num_ratings": "max"
    })
    .sort_values(
        by=["Total_Accolades", "average_rating", "num_ratings"],
        ascending=[False, False, False]
    )
    .rename(columns={"Total_Accolades": "Accolade_Count"})
    )

    else:
    # create an empty dataframe with all expected columns
        base_df = award_counts.iloc[0:0][[
        "Title", "Author", "Total_Accolades", "average_rating", "num_ratings"
        ]].copy()
        base_df = base_df.rename(columns={"Total_Accolades": "Accolade_Count"})

elif choice == "Search Accolades":
    st.subheader("Search Accolades")

    # Step 1: select accolade(s)
    selected_accolades = st.multiselect("Select accolade(s):", df_awards["Accolade"].unique())

    # Start with all awards if none selected
    filtered = df_awards.copy()

    if selected_accolades:
        # Filter to only rows with selected accolades
        filtered = filtered[filtered["Accolade"].isin(selected_accolades)]

        # If multiple accolades are selected, keep only authors/books who have ALL selected accolades
        if len(selected_accolades) > 1:
            counts = (
                filtered.groupby(["Author", "Title"])["Accolade"]
                .nunique()
                .reset_index(name="award_count")
            )
            filtered = filtered.merge(
                counts[counts["award_count"] == len(selected_accolades)][["Author", "Title"]],
                on=["Author", "Title"],
                how="inner"
            )

        # Include all Nobel winners if Nobel is selected
        if any("Nobel" in a for a in selected_accolades):
            nobel_winners = df_awards[df_awards["Accolade"].str.contains("Nobel", case=False, na=False)].copy()
            nobel_winners["Title"] = nobel_winners["Title"].fillna("N/A")
            filtered = pd.concat([filtered, nobel_winners], ignore_index=True).drop_duplicates()

    # Optional category filter
    categories = filtered["Category"].dropna().unique()
    if len(categories) > 0:
        selected_category = st.selectbox("Select category (optional):", ["All"] + list(categories))
        if selected_category != "All":
            filtered = filtered[filtered["Category"] == selected_category]

    # Optional result filter
    results = filtered["Result"].dropna().unique()
    if len(results) > 0:
        selected_result = st.selectbox("Select result (optional):", ["All"] + list(results))
        if selected_result != "All":
            filtered = filtered[filtered["Result"] == selected_result]

    # Year slider
    filtered["Year"] = pd.to_numeric(filtered["Year"], errors="coerce")
    with_year = filtered.dropna(subset=["Year"])
    without_year = filtered[filtered["Year"].isna()]

    if not with_year.empty:
        min_year = int(with_year["Year"].min())
        max_year = int(with_year["Year"].max())

        slider_key = f"search_accolades_year_slider_{'_'.join(selected_accolades) if selected_accolades else 'all'}"
        selected_year_range = st.slider(
            "Select Year Range",
            min_year,
            max_year,
            (min_year, max_year),
            step=1,
            key=slider_key
        )
        with_year_filtered = with_year[
            (with_year["Year"] >= selected_year_range[0]) &
            (with_year["Year"] <= selected_year_range[1])
        ]
        display_table = pd.concat([with_year_filtered, without_year], ignore_index=True)
    else:
        display_table = filtered.copy()

    # Aggregate by Title + Author for display
    display_table_unique = (
        display_table
        .groupby(["Title", "Author"], as_index=False)
        .agg({
            "Year": "min",
            "Category": lambda x: ", ".join(x.dropna().unique()),
            "Result": lambda x: ", ".join(x.dropna().unique())
        })
    )

    st.write(f"**Books displayed:** {len(display_table_unique)}")
    st.dataframe(display_table_unique[["Title", "Author", "Year", "Category", "Result"]])

else:  # All Books view
    st.subheader("Your Read Books")

    u = get_all_user_books(conn)
    u_filtered = u[(u["read"] == True) | (u["rating"].notnull() & (u["rating"] > 0))]
    u_filtered = u_filtered.drop_duplicates(subset=["title"], keep="first")

    if u.empty:
        st.info("No books recorded yet.")
    else:
        tracked = u_filtered[["title", "author", "rating"]].rename(
            columns={"title": "Title", "author": "Author", "rating": "Your Rating"}
        )
        st.write(f"**Books displayed:** {len(tracked)}")
        st.dataframe(tracked)

        # ---------------- Chart 1: Your rating vs Goodreads avg ----------------
        df_books["Title"] = df_books["Title"].str.strip()
        df_books["Author"] = df_books["Author"].str.strip()
        merged_ratings = tracked.merge(
            df_books[["Title", "Author", "average_rating"]],
            on=["Title", "Author"],
            how="left"
        )

        merged_ratings["Your Rating"] = merged_ratings["Your Rating"].astype(float)

# Chart 1: Your rating vs Goodreads average
    chart1 = (
    alt.Chart(merged_ratings)
    .mark_circle(size=80, color="#6A5ACD")  # slate blue points
    .encode(
        x=alt.X("average_rating", title="Goodreads Avg Rating",
                scale=alt.Scale(domain=[0, 5], nice=False),
                axis=alt.Axis(values=[i/2 for i in range(11)])),  # 0, 0.5, ..., 5
        y=alt.Y("Your Rating", title="Your Rating",
                scale=alt.Scale(domain=[0, 5], nice=False),
                axis=alt.Axis(values=[i/2 for i in range(11)])),
        tooltip=["Title", "Author", "Your Rating", "average_rating"]
    )
    .properties(
        width=600,
        height=400,
        title="Your Ratings vs Goodreads Average"
    )
)

    # Add diagonal 1:1 line
    line = (
    alt.Chart(pd.DataFrame({"x": [0, 5], "y": [0, 5]}))
    .mark_line(color="#8FBC8F", strokeDash=[5, 5], strokeWidth=0.5)  # dark sea green, thinner
    .encode(x="x", y="y")
)

    # ---------------- Chart 2: Accolades vs Goodreads avg rating ----------------
    # Filter out author-only awards (like Nobel) and prepare merge
    book_awards = df_awards[df_awards["Title"].notna() & (df_awards["Title"].str.strip() != "")].copy()
    book_awards["Title"] = book_awards["Title"].str.strip()
    book_awards["Author"] = book_awards["Author"].str.strip()

    acc_ratings = book_awards.merge(
        df_books[["Title", "Author", "average_rating"]],
        on=["Title", "Author"],
        how="left"
    )

    # Fix duplicate column names
    if "average_rating_y" in acc_ratings.columns:
        acc_ratings["average_rating"] = acc_ratings["average_rating_y"]
        acc_ratings = acc_ratings.drop(columns=["average_rating_x", "average_rating_y"])

    # Drop rows without ratings
    acc_ratings = acc_ratings[acc_ratings["average_rating"].notna()]

    if not acc_ratings.empty:
        acc_rating_summary = (
            acc_ratings.groupby("Accolade", as_index=False)["average_rating"]
            .mean()
            .sort_values("average_rating", ascending=False)
            .head(20)
        )

        chart2 = (
    alt.Chart(acc_rating_summary)
    .mark_bar(color="#6A5ACD")  # slate blue bars
    .encode(
        x=alt.X("average_rating", title="Avg Goodreads Rating",
                scale=alt.Scale(domain=[0, 5], nice=False),
                axis=alt.Axis(values=[i/2 for i in range(11)])),
        y=alt.Y("Accolade", sort="-x"),
        tooltip=["Accolade", "average_rating"]
    )
    .properties(
        width=600,
        height=500,
        title="Top 20 Accolades by Goodreads Avg Rating"
    )
)
        
tab1, tab2 = st.tabs(["Your Ratings vs Goodreads Avg", "Top Accolades by Avg Rating"])

with tab1:
    st.altair_chart(line + chart1, use_container_width=True)

with tab2:
    if not acc_ratings.empty:
        st.altair_chart(chart2, use_container_width=True)
    else:
        st.warning("No book accolades have associated Goodreads ratings to display in this chart.")

    # ---------------- Optional: Show all books with accolades ----------------
    if st.checkbox("Show all books with accolades"):
        st.subheader("All Books")
        all_agg = (
            award_counts
            .groupby(["Title", "Author"], as_index=False)
            .agg({"Total_Accolades": "max"})
            .sort_values("Total_Accolades", ascending=False)
            .rename(columns={"Total_Accolades": "Accolade Count"})
        )
        st.write(f"**Books displayed:** {len(all_agg)}")
        st.dataframe(all_agg[["Title", "Author", "Accolade Count"]])

# Editable table for base_df (book list with accolades)
# ---------- Editable table (Top by Accolades & Search Books only) ----------
if choice in ["Top by Accolades", "Search Books"] and base_df is not None:
    user_df = get_all_user_books(conn)
    if not user_df.empty:
        merged = base_df.merge(
            user_df[["title", "author", "read", "rating"]].rename(columns={"title": "Title", "author": "Author"}),
            on=["Title", "Author"],
            how="left"
        )
        display_df = merged.fillna({"read": False, "rating": np.nan})
    else:
        display_df = base_df.copy()
        display_df["read"] = False
        display_df["rating"] = None

    # Drop unwanted columns from display
    for col in ["published_year", "genres", "description"]:
        if col in display_df.columns:
            display_df.drop(columns=[col], inplace=True)

    if "Select" not in display_df.columns:
        display_df["Select"] = False

    display_df["read"] = display_df["read"].fillna(False).astype(bool)

    # Make sure table is sorted by accolade count descending
    if "Accolade_Count" in display_df.columns:
        display_df = display_df.sort_values(by="Accolade_Count", ascending=False)

    # Ensure num_ratings is numeric (int)
    display_df["num_ratings"] = display_df["num_ratings"].fillna(0).astype(int)

# ---------- Reset Table Sorting (only for Top by Accolades page) ----------
reset_key = "books_table"  # default key

if choice == "Top by Accolades":
    if "default_display_df" not in st.session_state:
        st.session_state.default_display_df = display_df.sort_values(
            by=["Accolade_Count", "average_rating", "num_ratings"],
            ascending=[False, False, False]
        )

    if st.button("Reset Table Sorting"):
        # Increment the key to force st.data_editor to refresh
        reset_key = f"books_table_reset_{st.session_state.get('reset_counter', 0)}"
        st.session_state.reset_counter = st.session_state.get("reset_counter", 0) + 1
        display_df = st.session_state.default_display_df.copy()

# ---------- Editable table (only for pages that use base_df) ----------
if choice in ["Top by Accolades", "Search Books"] and base_df is not None:
    selected_df = st.data_editor(
        display_df,
        use_container_width=True,
        key=reset_key,
        column_config={
            "Title": st.column_config.TextColumn("Title"),
            "Author": st.column_config.TextColumn("Author"),
            "Accolade_Count": st.column_config.NumberColumn("Accolades"),
            "average_rating": st.column_config.NumberColumn("Avg Rating", format="%.2f"),
            "num_ratings": st.column_config.NumberColumn("Number of Ratings"),
            "read": st.column_config.CheckboxColumn("Read"),
            "rating": st.column_config.NumberColumn("Your Rating"),
            "Select": st.column_config.CheckboxColumn("Select"),
        },
        hide_index=True
    )

    selected_books = selected_df[selected_df["Select"] == True]

    if selected_books.empty:
        st.info("Select a book by checking the box to view its details.")
    else:
        sel_title = selected_books.iloc[0]["Title"]
        sel_author = selected_books.iloc[0]["Author"]

        # Filter accolades for the selected book
        book_accolades = df_awards[(df_awards["Title"] == sel_title) & (df_awards["Author"] == sel_author)]

        # Author-only accolades (including Nobel prizes)
        author_only_accolades = df_awards[
            (df_awards["Author"] == sel_author) &
            ((df_awards["Title"].isna()) | (df_awards["Title"].str.strip() == "") |
             df_awards["Accolade"].str.contains("Nobel", case=False, na=False))
        ]

        accolades_rows = pd.concat([book_accolades, author_only_accolades], ignore_index=True)

        # Display Accolades Table
        st.markdown(f"### **{sel_title}** by {sel_author}")
        st.dataframe(
            accolades_rows[["Accolade", "Category", "Year", "Result"]].sort_values("Year", ascending=False),
            use_container_width=True,
        )

        # Book info
        book_info = df_books[(df_books["Title"] == sel_title) & (df_books["Author"] == sel_author)].iloc[0]

        published_year = book_info.get("published_year", "N/A")
        if isinstance(published_year, (float, int)) and not pd.isna(published_year):
            published_year = str(int(published_year))
        else:
            published_year = "N/A"

        genres = book_info.get("genres", "N/A")
        description = book_info.get("description", "No description available.")
        notes = book_info.get("notes", "")
        if pd.isna(notes) or str(notes).strip() == "":
            notes = "No notes."

        st.markdown(f"- **Published Year:** {published_year}")
        st.markdown(f"- **Genres:** {genres}")
        st.write(description)
        st.markdown(f"- **Notes:** {notes}")

        if st.button("Save read/rating status"):
            for _, row in selected_df.iterrows():
                upsert_user_book(conn, row["Title"], row["Author"], read=row["read"], rating=row["rating"])
            st.success("All statuses saved!")
        
# Close DB connection when done
conn.close()

#Add time updated timestamp
csv_path = "Export/books_with_ratings_and_info.csv"
if os.path.exists(csv_path):
    mod_time = os.path.getmtime(csv_path)
    last_updated = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"<sub>Database last updated: {last_updated}</sub>", unsafe_allow_html=True)