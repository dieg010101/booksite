"""Book lists router — user-curated lists with ordered items."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import Book, BookList, ListItem, User
from app.schemas.lists import (
    ListCreate,
    ListItemAdd,
    ListItemRead,
    ListItemReorder,
    ListRead,
    ListUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["lists"])


# ═══════════════════════════════════════════════════════════════════════════
# LIST CRUD
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/lists", response_model=ListRead, status_code=status.HTTP_201_CREATED)
def create_list(
    body: ListCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new book list."""
    # Check duplicate name for this user
    existing = (
        db.query(BookList)
        .filter(
            BookList.user_id == current_user.user_id,
            BookList.list_name == body.list_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="You already have a list with this name"
        )

    book_list = BookList(
        user_id=current_user.user_id,
        list_name=body.list_name,
        description=body.description,
        is_public=body.is_public,
    )
    db.add(book_list)
    db.commit()
    db.refresh(book_list)
    return book_list


@router.get("/lists/explore", response_model=list[ListRead])
def explore_lists(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Browse recently created public lists."""
    lists = (
        db.query(BookList)
        .filter(BookList.is_public == True)
        .order_by(BookList.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return lists


@router.get("/lists/{list_id}", response_model=ListRead)
def get_list(list_id: UUID, db: Session = Depends(get_db)):
    """Get a list by ID (public lists only, unless it's yours)."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    return book_list


@router.patch("/lists/{list_id}", response_model=ListRead)
def update_list(
    list_id: UUID,
    body: ListUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update list metadata (name, description, visibility)."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if book_list.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your list")

    update_data = body.model_dump(exclude_unset=True)

    # If renaming, check for duplicate
    if "list_name" in update_data:
        dup = (
            db.query(BookList)
            .filter(
                BookList.user_id == current_user.user_id,
                BookList.list_name == update_data["list_name"],
                BookList.list_id != list_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=409, detail="You already have a list with this name"
            )

    for field, value in update_data.items():
        setattr(book_list, field, value)
    db.commit()
    db.refresh(book_list)
    return book_list


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list(
    list_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a list and all its items (CASCADE)."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if book_list.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your list")

    db.delete(book_list)
    db.commit()


# ── Browse lists ──────────────────────────────────────────────────────────


@router.get("/users/{username}/lists", response_model=list[ListRead])
def list_user_lists(
    username: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List a user's public lists."""
    user = (
        db.query(User)
        .filter(User.username == username, User.is_deleted == False)
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    lists = (
        db.query(BookList)
        .filter(BookList.user_id == user.user_id, BookList.is_public == True)
        .order_by(BookList.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return lists


# ═══════════════════════════════════════════════════════════════════════════
# LIST ITEMS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/lists/{list_id}/items",
    response_model=ListItemRead,
    status_code=status.HTTP_201_CREATED,
)
def add_list_item(
    list_id: UUID,
    body: ListItemAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a book to a list."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if book_list.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your list")

    book = (
        db.query(Book)
        .filter(Book.book_id == body.book_id, Book.is_active == True)
        .first()
    )
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Check if book already in list
    existing = (
        db.query(ListItem)
        .filter(ListItem.list_id == list_id, ListItem.book_id == body.book_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Book already in list")

    # Determine position
    if body.position is not None:
        position = body.position
    else:
        # Append: get max position + 1
        max_pos = (
            db.query(ListItem.position)
            .filter(ListItem.list_id == list_id)
            .order_by(ListItem.position.desc())
            .first()
        )
        position = (max_pos[0] + 1) if max_pos else 0

    item = ListItem(list_id=list_id, book_id=body.book_id, position=position)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/lists/{list_id}/items", response_model=list[ListItemRead])
def list_items(list_id: UUID, db: Session = Depends(get_db)):
    """Get all items in a list, ordered by position."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")

    items = (
        db.query(ListItem)
        .filter(ListItem.list_id == list_id)
        .order_by(ListItem.position)
        .all()
    )
    return items


@router.delete(
    "/lists/{list_id}/items/{book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_list_item(
    list_id: UUID,
    book_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a book from a list."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if book_list.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your list")

    item = (
        db.query(ListItem)
        .filter(ListItem.list_id == list_id, ListItem.book_id == book_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Book not in list")

    db.delete(item)
    db.commit()


@router.put("/lists/{list_id}/items/reorder", response_model=list[ListItemRead])
def reorder_list_items(
    list_id: UUID,
    body: ListItemReorder,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reorder items in a list. Send the full ordered list of book_ids."""
    book_list = db.query(BookList).filter(BookList.list_id == list_id).first()
    if book_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if book_list.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your list")

    for position, book_id in enumerate(body.book_ids):
        item = (
            db.query(ListItem)
            .filter(ListItem.list_id == list_id, ListItem.book_id == book_id)
            .first()
        )
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=f"Book {book_id} not in list",
            )
        item.position = position

    db.commit()

    # Return updated items in order
    items = (
        db.query(ListItem)
        .filter(ListItem.list_id == list_id)
        .order_by(ListItem.position)
        .all()
    )
    return items
