"""Google Books router — search, lookup, and import books from Google Books API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.google_books import (
    fetch_google_book,
    search_google_books,
    search_google_books_by_isbn,
)
from app.database import get_db
from app.models import Book, BookContributor, Contributor, ContributorRoleEnum, User
from app.schemas.books import BookRead
from app.schemas.google_books import (
    GoogleBookImport,
    GoogleBookResult,
    GoogleBookSearchResponse,
)

router = APIRouter(prefix="/api/v1/google-books", tags=["google-books"])


# ── Search ────────────────────────────────────────────────────────────────


@router.get("/search", response_model=GoogleBookSearchResponse)
async def search(
    q: str = Query(min_length=1, description="Search query (title, author, etc.)"),
    max_results: int = Query(10, ge=1, le=40),
    start_index: int = Query(0, ge=0),
):
    """Search Google Books API. No auth required — this is a public lookup."""
    try:
        results = await search_google_books(
            q, max_results=max_results, start_index=start_index
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Books API error: {str(e)}",
        )
    return GoogleBookSearchResponse(
        results=[GoogleBookResult(**r) for r in results],
        total=len(results),
    )


@router.get("/isbn/{isbn}", response_model=GoogleBookResult | None)
async def lookup_isbn(isbn: str):
    """Look up a book by ISBN (13 or 10). No auth required."""
    try:
        result = await search_google_books_by_isbn(isbn)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Books API error: {str(e)}",
        )
    if result is None:
        raise HTTPException(status_code=404, detail="No book found for this ISBN")
    return GoogleBookResult(**result)


@router.get("/volume/{volume_id}", response_model=GoogleBookResult)
async def lookup_volume(volume_id: str):
    """Look up a single book by Google Books volume ID. No auth required."""
    try:
        result = await fetch_google_book(volume_id)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Books API error: {str(e)}",
        )
    if result is None:
        raise HTTPException(status_code=404, detail="Volume not found")
    return GoogleBookResult(**result)


# ── Import ────────────────────────────────────────────────────────────────


@router.post("/import", response_model=BookRead, status_code=status.HTTP_201_CREATED)
async def import_book(
    body: GoogleBookImport,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a book from Google Books into our catalog.

    Fetches the volume metadata, creates a Book record, and auto-creates
    Contributor + BookContributor records for each author listed.

    If the book already exists (by external_api_id), returns 409.
    """
    # Check if already imported
    existing = db.query(Book).filter(Book.external_api_id == body.volume_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Book already in catalog")

    # Fetch from Google
    try:
        volume_data = await fetch_google_book(body.volume_id)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Books API error: {str(e)}",
        )
    if volume_data is None:
        raise HTTPException(status_code=404, detail="Volume not found on Google Books")

    # Create the Book
    book = Book(
        external_api_id=volume_data["external_api_id"],
        title=volume_data["title"],
        isbn_13=volume_data["isbn_13"],
        published_date=volume_data["published_date"],
    )
    db.add(book)
    db.flush()  # get book_id

    # Auto-create contributors for each author
    for author_name in volume_data.get("authors", []):
        # Check if contributor already exists by exact name match
        contributor = (
            db.query(Contributor).filter(Contributor.name == author_name).first()
        )
        if contributor is None:
            contributor = Contributor(name=author_name)
            db.add(contributor)
            db.flush()

        # Link contributor to book as AUTHOR
        link_exists = (
            db.query(BookContributor)
            .filter(
                BookContributor.book_id == book.book_id,
                BookContributor.contributor_id == contributor.contributor_id,
                BookContributor.role == ContributorRoleEnum.AUTHOR,
            )
            .first()
        )
        if not link_exists:
            db.add(
                BookContributor(
                    book_id=book.book_id,
                    contributor_id=contributor.contributor_id,
                    role=ContributorRoleEnum.AUTHOR,
                )
            )

    db.commit()
    db.refresh(book)
    return book
