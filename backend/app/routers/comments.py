"""Comments router — threaded comments using PostgreSQL ltree."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import BookEntry, Comment, User
from app.schemas.comments import CommentCreate, CommentRead, CommentThread

router = APIRouter(prefix="/api/v1", tags=["comments"])


def _uuid_to_ltree_label(uuid: UUID) -> str:
    """Convert a UUID to a valid ltree label (no hyphens allowed)."""
    return str(uuid).replace("-", "")


# ── Create comment / reply ────────────────────────────────────────────────


@router.post(
    "/entries/{entry_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    entry_id: UUID,
    body: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a top-level comment or a reply to an existing comment.

    ltree path construction:
    - Top-level: path = "<comment_id>"
    - Reply:     path = "<parent_path>.<comment_id>"

    We flush after add to get the generated comment_id, then set the path.
    """
    # Verify entry exists and is active
    entry = (
        db.query(BookEntry)
        .filter(BookEntry.entry_id == entry_id, BookEntry.is_deleted == False)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    comment = Comment(
        user_id=current_user.user_id,
        entry_id=entry_id,
        comment_text=body.comment_text,
        path="placeholder",  # will be set after flush gives us comment_id
    )
    db.add(comment)
    db.flush()  # assigns comment_id

    label = _uuid_to_ltree_label(comment.comment_id)

    if body.parent_comment_id is not None:
        # Verify parent exists and belongs to the same entry
        parent = (
            db.query(Comment)
            .filter(
                Comment.comment_id == body.parent_comment_id,
                Comment.entry_id == entry_id,
            )
            .first()
        )
        if parent is None:
            raise HTTPException(
                status_code=404,
                detail="Parent comment not found on this entry",
            )
        comment.path = f"{parent.path}.{label}"
    else:
        comment.path = label

    db.commit()
    db.refresh(comment)
    return comment


# ── List thread ───────────────────────────────────────────────────────────


@router.get("/entries/{entry_id}/comments", response_model=CommentThread)
def list_comments(
    entry_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List all comments on an entry, sorted by ltree path (thread order).

    This includes soft-deleted comments (they show as [deleted]) because
    their paths are needed to maintain thread structure for descendants.
    """
    query = db.query(Comment).filter(Comment.entry_id == entry_id)
    total = query.count()
    comments = query.order_by(Comment.path).offset(offset).limit(limit).all()
    return CommentThread(comments=comments, total=total)


# ── Get single comment ────────────────────────────────────────────────────


@router.get("/comments/{comment_id}", response_model=CommentRead)
def get_comment(comment_id: UUID, db: Session = Depends(get_db)):
    """Get a single comment by ID."""
    comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


# ── Get subtree (replies to a specific comment) ──────────────────────────


@router.get("/comments/{comment_id}/replies", response_model=CommentThread)
def get_replies(
    comment_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Get all replies (descendants) of a specific comment using ltree <@ operator."""
    parent = db.query(Comment).filter(Comment.comment_id == comment_id).first()
    if parent is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Use ltree descendant operator: path <@ parent_path AND path != parent_path
    query = db.query(Comment).filter(
        Comment.path.op("<@")(parent.path),
        Comment.comment_id != comment_id,  # exclude the parent itself
    )
    total = query.count()
    comments = query.order_by(Comment.path).offset(offset).limit(limit).all()
    return CommentThread(comments=comments, total=total)


# ── Soft-delete comment ───────────────────────────────────────────────────


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a comment (Reddit-style: text → [deleted], path preserved).

    Only the comment author can delete. The ltree path stays intact so
    descendant comments keep their correct ancestry.
    """
    comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.is_deleted:
        raise HTTPException(status_code=404, detail="Comment already deleted")
    if comment.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your comment")

    comment.is_deleted = True
    comment.comment_text = "[deleted]"
    db.commit()
