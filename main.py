import io
import json
import logging
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from src import HealthResponse, MovieDataResponse, MovieProcessingReport, MovieStorage, MovieUploadInfo, ProcessConfig, ProcessingReport, log_requests, setup_logging
from src.storage import MOVIE_COLUMNS
from data_pipeline import create_cleaning_report, process_data, validate_dataframe

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Data Processing API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version=app.version)

@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movie(file: UploadFile = File(...)):
    """Validate a CSV upload and replace the stored movie collection."""
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension != ".csv":
        logger.warning("Unsupported file format: %s", extension)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: '{extension}'. Only .csv files are accepted.",
        )

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except pd.errors.EmptyDataError:
        logger.warning("Empty CSV upload: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="The uploaded CSV file is empty.",
        )
    except pd.errors.ParserError:
        logger.warning("Could not parse CSV upload: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="The uploaded file could not be parsed as CSV.",
        )
    except UnicodeDecodeError:
        logger.warning("Could not decode CSV upload: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not valid UTF-8 text.",
        )

    if sorted(df.columns) != sorted(MOVIE_COLUMNS):
        logger.warning("Invalid movie columns: %s", list(df.columns))
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}",
        )

    if df.empty:
        logger.warning("Movie CSV has no data rows: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="The uploaded CSV file contains no data rows.",
        )

    df = df[MOVIE_COLUMNS]

    storage.save(df)
    logger.info("Uploaded movie: filename=%s, rows=%d", filename, len(df))
    return MovieUploadInfo(
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        column_names=df.columns.tolist(),
    )
        
@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit stored movies and the total count."""
    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    logger.info("Retrieved movies: returned_rows=%d, total_rows=%d", len(data), total_rows)
    return {"data": data, "total_rows": total_rows}

@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1)
):
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        logger.warning("Invalid movie query: error=%s", error)
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%d",
        columns,
        min_rating,
        len(results),
    )
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    df = storage.get()
    if df.empty:
        logger.warning("No movies stored to process")
        raise HTTPException(
            status_code=400,
            detail="No movies stored. Upload a CSV first.",
        )

    config_dict = config.model_dump()
    validation = config_dict["validation"]

    for column in validation["numeric_columns"]:
        if column not in df.columns:
            logger.warning("Numeric column not found: %s", column)
            raise HTTPException(
                status_code=400,
                detail=f"Numeric column not found: {column}",
            )

    try:
        rows_before_validation = len(df)
        validated = validate_dataframe(
            df, validation["required_columns"], validation["numeric_columns"]
        )
        validation_rows_removed = rows_before_validation - len(validated)
        logger.info("Validated movies: rows_removed=%d", validation_rows_removed)
        before_processing = validated.copy()
        processed = process_data(validated, config_dict)
    except ValueError as error:
        logger.warning("Processing failed: error=%s", error)
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    cleaning_report = create_cleaning_report(before_processing, processed)
    storage.save(processed.reindex(columns=MOVIE_COLUMNS))
    logger.info(
        "Processed movies: validation_rows_removed=%d, rows_before=%d, rows_after=%d",
        validation_rows_removed,
        cleaning_report["rows_before"],
        cleaning_report["rows_after"],
    )
    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": cleaning_report,
    }
