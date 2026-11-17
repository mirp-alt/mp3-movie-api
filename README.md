# MP3 Movie API

MP3 is a REST API which is built using FastAPI and stores a movie collection in a SQLite database, so the data stays saved even after the server restarts. main.py has the endpoints, src/database.py creates the connection and the movies table, src/storage.py runs all the SQL queries, src/cache.py handles the cache using fakeredis, and data_pipeline/ reuses the MP1 validation and cleaning functions. POST /upload accepts a CSV file with the four movie columns and replaces the stored collection in one SQL transaction. GET /movies returns up to limit movies along with the total count, and it checks the cache first so repeated requests do not need to query the database. GET /movies/search uses SQL to filter movies by a minimum rating and sorts them from highest to lowest rating. POST /movies/process validates and cleans the stored movies with the MP1 functions and saves the cleaned version back to SQLite. After every successful upload or processing, the cache is cleared so the API never returns outdated movies. The API also uses middleware that logs every request with a request ID, and it is tested using pytest and TestClient.

## Running the API

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs.

## Running the Tests

```bash
python -m pytest tests -v
```

## Sample Processing Request

After uploading `fixtures/sample_movies.csv`, send this body to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {"enabled": true, "columns": ["rating"], "method": "iqr", "threshold": 1.5}
  }
}
```

Expected result:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```
