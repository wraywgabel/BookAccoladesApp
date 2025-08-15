import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import ftfy
import html
from rapidfuzz import fuzz
import os

def clean_description(text: str) -> str:
    """Clean and fix mojibake / HTML / entities in book descriptions."""
    if not text or not isinstance(text, str):
        return text

    # 1) Remove HTML tags but keep spacing
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()

    # 2) Unescape HTML entities (&amp;, &nbsp;, etc.)
    text = html.unescape(text)

    # 3) First pass with ftfy (best-effort automatic fixes)
    try:
        text = ftfy.fix_text(text)
    except Exception:
        # if ftfy isn't available for some reason, continue with raw text
        pass

    # 4) If it still contains suspicious mojibake sequences, try recoding heuristics
    if re.search(r"(â|Ã|Â|â€™|â€œ|â€\u009d|Ã©)", text):
        for enc in ("latin-1", "cp1252"):
            try:
                candidate = text.encode(enc, errors="replace").decode("utf-8", errors="replace")
                # run ftfy again on candidate
                try:
                    candidate = ftfy.fix_text(candidate)
                except Exception:
                    pass

                # Heuristic: pick candidate if it reduces mojibake markers
                def mojibake_score(s):
                    return len(re.findall(r"(â|Ã|Â|�)", s))

                if mojibake_score(candidate) < mojibake_score(text):
                    text = candidate
                    break
            except Exception:
                # if this encoding attempt fails, try next
                continue

    # 5) Final small replacements for leftover common sequences
    replacements = {
        "â€": "",
        "â€¢": "",
        "â€“": "",
        "â€™": "’",
        "â€œ": "“",
        "â€�": "”",
        "â€”": "—",
        "â€“": "–",
        "â€¦": "…",
        "Ã©": "é",
        "Ã¨": "è",
        "Ãª": "ê",
        "Ã¶": "ö",
        "Ã¶": "ö", 
        "Â": "",   # stray Â often appears before non-breaking spaces
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # 6) Collapse any repeated whitespace and return
    text = re.sub(r"\s+", " ", text).strip()
    return text

def scrape_goodreads_rating(title, author, min_ratings_threshold=1000, similarity_threshold=95):
    """
    Search Goodreads for a book and return the average rating and number of ratings,
    with possible misreads recorded if similarity is low.
    """
    def get_top_candidate(query, top_n=5):
        """Return the candidate with the most ratings from the top N results"""
        url = f"https://www.goodreads.com/search?q={query.replace(' ', '+')}"
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except Exception as e:
            print(f"Request failed for query '{query}': {e}")
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = soup.select("table.tableList tr")[:top_n]
        best_avg, best_num, best_title, best_author = None, None, None, None

        for result in results:
            rating_span = result.select_one("span.minirating")
            title_link = result.select_one("a.bookTitle")
            author_link = result.select_one("a.authorName")

            if not rating_span or not title_link or not author_link:
                continue

            rating_text = rating_span.get_text(strip=True)
            avg_match = re.search(r"(\d+\.\d+)", rating_text)
            avg = float(avg_match.group(1)) if avg_match else None

            num_match = re.search(r"—\s*([\d,]+)\s+ratings", rating_text)
            num = int(num_match.group(1).replace(",", "")) if num_match else None

            candidate_title = title_link.get_text(strip=True)
            candidate_author = author_link.get_text(strip=True)

            if num and (best_num is None or num > best_num):
                best_avg, best_num, best_title, best_author = avg, num, candidate_title, candidate_author

        if best_num is None:
            return None
        return {
            "avg_rating": best_avg,
            "num_ratings": best_num,
            "title": best_title,
            "author": best_author
        }

    # Step 1: Search title + author
    query1 = f"{title} {author}".strip()
    candidate_1 = get_top_candidate(query1)

    possible_misread = None  # placeholder

    # Step 2: Check similarity of candidate_1
    if candidate_1:
        title_sim_1 = fuzz.ratio(candidate_1["title"].lower(), title.lower())
        author_sim_1 = fuzz.ratio(candidate_1["author"].lower(), author.lower())

        if title_sim_1 >= similarity_threshold and author_sim_1 >= similarity_threshold and candidate_1["num_ratings"] >= min_ratings_threshold:
            # High similarity and enough ratings: accept
            return candidate_1["avg_rating"], candidate_1["num_ratings"], None
        else:
            # Step 3: Fallback search using title only
            query2 = f'"{title}"'
            candidate_2 = get_top_candidate(query2)

            if candidate_2:
                title_sim_2 = fuzz.ratio(candidate_2["title"].lower(), title.lower())
                author_sim_2 = fuzz.ratio(candidate_2["author"].lower(), author.lower())

                # Step 4 & 5: Choose the one with higher similarity
                sim_score_1 = (title_sim_1 + author_sim_1) / 2
                sim_score_2 = (title_sim_2 + author_sim_2) / 2

                if sim_score_2 > sim_score_1:
                    # candidate_2 is better match
                    final = candidate_2
                    possible_misread = candidate_1
                else:
                    # candidate_1 is better match
                    final = candidate_1
                    possible_misread = candidate_2

                return final["avg_rating"], final["num_ratings"], possible_misread

    # If no candidates found, return None
    return None, None, None

def fetch_google_books_info(title, author=None):
    """Fetch published year, genres, and description from Google Books API."""
    
    def query_google(query):
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Google Books API request failed for '{title}': {e}")
            return None
        return data.get('items', None)
    
    # 1) Strict search: title + author
    query = f'intitle:"{title}"'
    if author:
        query += f'+inauthor:{author}'
    items = query_google(query)
    
    # 2) Fallback: title only
    if not items:
        query = f'intitle:"{title}"'
        items = query_google(query)
    
    if not items:
        print(f"No Google Books results found for '{title}'")
        return None, None, None
    
    volume_info = items[0]['volumeInfo']
    
    published_date = volume_info.get('publishedDate', None)
    year = published_date.split('-')[0] if published_date else None
    
    genres = volume_info.get('categories', [])
    genres_str = ", ".join(genres[:3]) if genres else None
    
    description = volume_info.get('description', None)
    if description:
        description = clean_description(description)
    
    return year, genres_str, description

# Load CSV
df_full = pd.read_csv("Export/Awards_Lists_Clubs.csv")

# Clean
df_full = df_full[df_full["Title"].notna() & (df_full["Title"].str.strip() != "")]

# Deduplicate for scraping only
df_unique = df_full.drop_duplicates(subset=["Title", "Author"])

csv_path = "Export/books_with_ratings_and_info.csv"

# Load previous results if they exist
if os.path.exists(csv_path):
    existing_df = pd.read_csv(csv_path)
else:
    existing_df = pd.DataFrame()

# Ensure 'notes' column exists
if "notes" not in existing_df.columns:
    existing_df["notes"] = ""

# For loop
for idx, row in df_unique.iterrows():
    title = row["Title"]
    author = row["Author"]

    print(f"Scraping Goodreads rating for: {title} by {author}")
    avg_rating, num_ratings, possible_misread = scrape_goodreads_rating(title, author)
    print(f"  → Goodreads rating: {avg_rating}, Number of ratings: {num_ratings}")
    if possible_misread:
        print(f"  → Possible misread: {possible_misread['title']} by {possible_misread['author']} — {possible_misread['num_ratings']} ratings")

    print(f"Fetching Google Books info for: {title} by {author}")
    year, genres, description = fetch_google_books_info(title, author)
    print(f"  → Published year: {year}, Genres: {genres}")

    # Default note is blank
    note = ""

    # If scraper failed, try to keep old values from existing_df
    if (avg_rating is None or num_ratings is None):
        old_row = existing_df[(existing_df["Title"] == title) & (existing_df["Author"] == author)]
        if not old_row.empty:
            if avg_rating is None:
                avg_rating = old_row.iloc[0]["average_rating"]
            if num_ratings is None:
                num_ratings = old_row.iloc[0]["num_ratings"]
            note = "The average rating and number of ratings may not be up to date on this book."

    # Update main dataframe
    df_unique.loc[idx, "average_rating"] = avg_rating
    df_unique.loc[idx, "num_ratings"] = num_ratings
    df_unique.loc[idx, "published_year"] = year
    df_unique.loc[idx, "genres"] = genres
    df_unique.loc[idx, "description"] = description
    df_unique.loc[idx, "notes"] = note  # store note

    if possible_misread:
        misread_str = f"{possible_misread['title']} by {possible_misread['author']} — {possible_misread['num_ratings']} ratings"
        df_unique.loc[idx, "possible_misread"] = misread_str

    time.sleep(2)

# Merge into full awards dataframe
df_merged = df_full.merge(
    df_unique[["Title", "Author", "average_rating", "num_ratings", "published_year", "genres", "description", "possible_misread", "notes"]],
    on=["Title", "Author"],
    how="left"
)

# Save updated CSV
df_merged.to_csv(csv_path, index=False)
print("Done! Saved updated CSV with ratings, year, genres, description, possible misreads, and notes.")