"""Contributors router — manage contributors and book-contributor links."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import Book, BookContributor, Contributor, ContributorRoleEnum, User
from app.schemas.contributors import (
    BookContributorAdd,
    BookContributorDetail,
    BookContributorRead,
    ContributorCreate,
    ContributorRead,
    ContributorUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["contributors"])


# ═══════════════════════════════════════════════════════════════════════════
# CONTRIBUTOR CRUD
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/contributors",
    response_model=ContributorRead,
    status_code=status.HTTP_201_CREATED,
)
def create_contributor(
    body: ContributorCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new contributor (author, illustrator, etc.) to the system."""
    contributor = Contributor(name=body.name, bio=body.bio)
    db.add(contributor)
    db.commit()
    db.refresh(contributor)
    return contributor


@router.get("/contributors", response_model=list[ContributorRead])
def list_contributors(
    q: str | None = Query(default=None, min_length=1, description="Search by name"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List or search contributors."""
    query = db.query(Contributor)
    if q:
        query = query.filter(Contributor.name.ilike(f"%{q}%"))
    contributors = query.order_by(Contributor.name).offset(offset).limit(limit).all()
    return contributors


@router.get("/contributors/{contributor_id}", response_model=ContributorRead)
def get_contributor(contributor_id: UUID, db: Session = Depends(get_db)):
    """Get a single contributor."""
    contributor = (
        db.query(Contributor)
        .filter(Contributor.contributor_id == contributor_id)
        .first()
    )
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found")
    return contributor


@router.patch("/contributors/{contributor_id}", response_model=ContributorRead)
def update_contributor(
    contributor_id: UUID,
    body: ContributorUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update contributor name or bio."""
    contributor = (
        db.query(Contributor)
        .filter(Contributor.contributor_id == contributor_id)
        .first()
    )
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(contributor, field, value)
    db.commit()
    db.refresh(contributor)
    return contributor


# ═══════════════════════════════════════════════════════════════════════════
# BOOK ↔ CONTRIBUTOR LINKS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/books/{book_id}/contributors",
    response_model=BookContributorRead,
    status_code=status.HTTP_201_CREATED,
)
def add_book_contributor(
    book_id: UUID,
    body: BookContributorAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Link a contributor to a book with a specific role."""
    book = (
        db.query(Book).filter(Book.book_id == book_id, Book.is_active == True).first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    contributor = (
        db.query(Contributor)
        .filter(Contributor.contributor_id == body.contributor_id)
        .first()
    )
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found")

    # Map Pydantic enum to SQLAlchemy enum
    db_role = ContributorRoleEnum(body.role.value)

    # Check for duplicate (same book + contributor + role)
    existing = (
        db.query(BookContributor)
        .filter(
            BookContributor.book_id == book_id,
            BookContributor.contributor_id == body.contributor_id,
            BookContributor.role == db_role,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="Contributor already has this role on this book"
        )

    link = BookContributor(
        book_id=book_id,
        contributor_id=body.contributor_id,
        role=db_role,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/books/{book_id}/contributors", response_model=list[BookContributorDetail])
def list_book_contributors(book_id: UUID, db: Session = Depends(get_db)):
    """List all contributors for a book with their roles."""
    links = db.query(BookContributor).filter(BookContributor.book_id == book_id).all()

    results = []
    for link in links:
        contributor = (
            db.query(Contributor)
            .filter(Contributor.contributor_id == link.contributor_id)
            .first()
        )
        if contributor:
            results.append(
                BookContributorDetail(
                    contributor_id=contributor.contributor_id,
                    name=contributor.name,
                    bio=contributor.bio,
                    role=link.role.value,
                )
            )
    return results


@router.delete(
    "/books/{book_id}/contributors/{contributor_id}/{role}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_book_contributor(
    book_id: UUID,
    contributor_id: UUID,
    role: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a contributor-role link from a book."""
    try:
        db_role = ContributorRoleEnum(role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role}")

    link = (
        db.query(BookContributor)
        .filter(
            BookContributor.book_id == book_id,
            BookContributor.contributor_id == contributor_id,
            BookContributor.role == db_role,
        )
        .first()
    )
    if link is None:
        raise HTTPException(
            status_code=404, detail="Contributor role not found on this book"
        )

    db.delete(link)
    db.commit()


@router.get(
    "/contributors/{contributor_id}/books", response_model=list[BookContributorDetail]
)
def list_contributor_books(contributor_id: UUID, db: Session = Depends(get_db)):
    """List all books a contributor is linked to (with their roles)."""
    contributor = (
        db.query(Contributor)
        .filter(Contributor.contributor_id == contributor_id)
        .first()
    )
    if contributor is None:
        raise HTTPException(status_code=404, detail="Contributor not found")

    links = (
        db.query(BookContributor)
        .filter(BookContributor.contributor_id == contributor_id)
        .all()
    )

    results = []
    for link in links:
        results.append(
            BookContributorDetail(
                contributor_id=contributor.contributor_id,
                name=contributor.name,
                bio=contributor.bio,
                role=link.role.value,
            )
        )
    return results
