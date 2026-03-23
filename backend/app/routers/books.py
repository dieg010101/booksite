"""Books router — catalog, entries (logs/reviews), reading statuses, search, explore."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import (
    ActivityTypeEnum,
    Book,
    BookEntry,
    ReadingStatus,
    ReadingStatusEnum,
    User,
)
from app.schemas.books import (
    BookCreate,
    BookList,
    BookRead,
    EntryCreate,
    EntryRead,
    EntryUpdate,
    ReadingStatusRead,
    ReadingStatusSet,
)

router = APIRouter(prefix="/api/v1", tags=["books"])


# ═══════════════════════════════════════════════════════════════════════════
# BOOK CATALOG
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/books", response_model=BookRead, status_code=status.HTTP_201_CREATED)
def create_book(
    body: BookCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a book to the catalog."""
    existing = (
        db.query(Book).filter(Book.external_api_id == body.external_api_id).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Book already exists in catalog")

    if body.isbn_13:
        isbn_dup = db.query(Book).filter(Book.isbn_13 == body.isbn_13).first()
        if isbn_dup:
            raise HTTPException(status_code=409, detail="ISBN already exists")

    book = Book(**body.model_dump())
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


@router.get("/books", response_model=BookList)
def list_books(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List active books with pagination."""
    query = db.query(Book).filter(Book.is_active == True)
    total = query.count()
    books = query.order_by(Book.title).offset(offset).limit(limit).all()
    return BookList(books=books, total=total)


@router.get("/books/search", response_model=BookList)
def search_books(
    q: str = Query(min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Full-text search on book titles using PostgreSQL tsvector."""
    ts_query = func.plainto_tsquery("english", q)
    query = db.query(Book).filter(
        Book.is_active == True, Book.search_vector.op("@@")(ts_query)
    )
    total = query.count()
    books = query.order_by(Book.title).offset(offset).limit(limit).all()
    return BookList(books=books, total=total)


@router.get("/books/trending", response_model=list[BookRead])
def trending_books(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Books with the most currently-reading users."""
    books = (
        db.query(Book)
        .filter(Book.is_active == True)
        .order_by(Book.currently_reading_count.desc())
        .limit(limit)
        .all()
    )
    return books


@router.get("/books/popular", response_model=list[BookRead])
def popular_books(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most-logged books."""
    books = (
        db.query(Book)
        .filter(Book.is_active == True)
        .order_by(Book.log_count.desc())
        .limit(limit)
        .all()
    )
    return books


@router.get("/books/top-rated", response_model=list[BookRead])
def top_rated_books(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Highest-rated books (only those with ratings)."""
    books = (
        db.query(Book)
        .filter(Book.is_active == True, Book.avg_rating.isnot(None))
        .order_by(Book.avg_rating.desc())
        .limit(limit)
        .all()
    )
    return books


@router.get("/books/{book_id}", response_model=BookRead)
def get_book(book_id: UUID, db: Session = Depends(get_db)):
    """Get a single book by ID."""
    book = (
        db.query(Book).filter(Book.book_id == book_id, Book.is_active == True).first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


# ═══════════════════════════════════════════════════════════════════════════
# BOOK ENTRIES (logs / reviews)
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/books/{book_id}/entries",
    response_model=EntryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_entry(
    book_id: UUID,
    body: EntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Log/review a book. Fans out to followers' timelines."""
    book = (
        db.query(Book).filter(Book.book_id == book_id, Book.is_active == True).first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    entry = BookEntry(
        user_id=current_user.user_id,
        book_id=book_id,
        **body.model_dump(),
    )
    db.add(entry)
    db.flush()  # assigns entry_id so we can use it in fan-out

    # Fan-out: push REVIEW activity to followers' timelines
    from app.routers.feed import _fan_out_to_followers

    _fan_out_to_followers(db, current_user, entry.entry_id, ActivityTypeEnum.REVIEW)

    db.commit()
    db.refresh(entry)
    return entry


@router.get("/books/{book_id}/entries", response_model=list[EntryRead])
def list_book_entries(
    book_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all active entries for a book."""
    entries = (
        db.query(BookEntry)
        .filter(
            BookEntry.book_id == book_id,
            BookEntry.is_deleted == False,
        )
        .order_by(BookEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return entries


@router.get("/entries/{entry_id}", response_model=EntryRead)
def get_entry(entry_id: UUID, db: Session = Depends(get_db)):
    """Get a single entry by ID."""
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.patch("/entries/{entry_id}", response_model=EntryRead)
def update_entry(
    entry_id: UUID,
    body: EntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update your own entry."""
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your entry")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete your own entry."""
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your entry")

    entry.is_deleted = True
    db.commit()


@router.get("/users/{username}/entries", response_model=list[EntryRead])
def list_user_entries(
    username: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List all active entries by a user (profile feed)."""
    user = (
        db.query(User)
        .filter(User.username == username, User.is_deleted == False)
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    entries = (
        db.query(BookEntry)
        .filter(
            BookEntry.user_id == user.user_id,
            BookEntry.is_deleted == False,
        )
        .order_by(BookEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return entries


# ═══════════════════════════════════════════════════════════════════════════
# READING STATUS
# ═══════════════════════════════════════════════════════════════════════════


@router.put("/books/{book_id}/status", response_model=ReadingStatusRead)
def set_reading_status(
    book_id: UUID,
    body: ReadingStatusSet,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set or update your reading status for a book (upsert)."""
    book = (
        db.query(Book).filter(Book.book_id == book_id, Book.is_active == True).first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    db_status = ReadingStatusEnum(body.status.value)

    existing = (
        db.query(ReadingStatus)
        .filter(
            ReadingStatus.user_id == current_user.user_id,
            ReadingStatus.book_id == book_id,
        )
        .first()
    )

    if existing:
        existing.status = db_status
        db.commit()
        db.refresh(existing)
        return existing
    else:
        rs = ReadingStatus(
            user_id=current_user.user_id,
            book_id=book_id,
            status=db_status,
        )
        db.add(rs)
        db.commit()
        db.refresh(rs)
        return rs


@router.get("/books/{book_id}/status", response_model=ReadingStatusRead)
def get_reading_status(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get your reading status for a book."""
    rs = (
        db.query(ReadingStatus)
        .filter(
            ReadingStatus.user_id == current_user.user_id,
            ReadingStatus.book_id == book_id,
        )
        .first()
    )
    if rs is None:
        raise HTTPException(status_code=404, detail="No reading status set")
    return rs


@router.delete("/books/{book_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def delete_reading_status(
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove your reading status for a book."""
    rs = (
        db.query(ReadingStatus)
        .filter(
            ReadingStatus.user_id == current_user.user_id,
            ReadingStatus.book_id == book_id,
        )
        .first()
    )
    if rs is None:
        raise HTTPException(status_code=404, detail="No reading status set")

    db.delete(rs)
    db.commit()
