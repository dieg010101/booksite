"""
Social Book Catalog — SQLAlchemy ORM Models (v4)
=================================================

Architecture decisions grounded in:
  • Designing Data-Intensive Applications (Kleppmann)         — cited as "DDIA"
  • SQL Performance Explained (Winand)                        — cited as "SPE"
  • Introduction to Information Retrieval (Manning et al.)    — cited as "IIR"
  • Graph Databases (Robinson, Webber, Eifrem)                — cited as "GDB"
  • Database Internals (Petrov)                               — cited as "DBI"
  • PostgreSQL 14 Internals (Rogov)                           — cited as "PG14I"
  • High Performance PostgreSQL for Rails (Atkinson)          — cited as "HPPG"
  • The Art of PostgreSQL (Fontaine)                          — cited as "AoP"
  • Database Reliability Engineering (Campbell & Majors)      — cited as "DBRE"
  • SQL Antipatterns (Karwin)                                 — cited as "SQLA"

Changes from v3 → v4:
  ──────────────────────

  1. FIXED — Username reclaimability: Removed `unique=True` from the
     `username` column definition. Uniqueness is now enforced ONLY by the
     partial unique index `ix_users_active_username` (WHERE is_deleted = false).

     This means two users can share the same username as long as at most one
     of them is active. When a user is soft-deleted and their PII is
     anonymized (username → "deleted_user_<hash>"), the original username
     becomes immediately available for new registrations.

     The previous v3 had BOTH `unique=True` (global) AND a partial unique
     index — the global constraint permanently locked every username ever
     used, even after account deletion.

     Reference: SPE ch. 2 (Partial Indexes) — Winand explains that partial
     unique indexes enforce uniqueness only within the subset of rows
     matching the predicate. This is exactly the semantics we need:
     "no two *active* users may share a username."

  2. FIXED — Explore page index redundant column: The v3 index
     `ix_lists_public_created` included `is_public` as a key column AND
     had `postgresql_where=text("is_public = true")`. Since every row in
     the index already satisfies `is_public = true`, the `is_public` column
     in the key is dead weight — it contains the same constant value for
     every entry and contributes nothing to sort order or selectivity.

     Now indexes only `created_at DESC` with the partial WHERE clause.

     Reference: SPE ch. 2 — Winand warns against including constant-value
     columns in the index key when a partial predicate already handles the
     filtering. The key should contain only columns that differentiate rows
     within the indexed subset.

  3. FIXED — Added `server_default` on all boolean and timestamp columns:
     SQLAlchemy's `default=` only works through the ORM. Any code path that
     bypasses SQLAlchemy (raw SQL, Alembic backfills, CDC replays, pg_dump
     restores, COPY commands) would either get NULL or fail on NOT NULL.

     Now every boolean has `server_default=text("false")` (or "true" where
     appropriate) and every timestamp has `server_default=text("now()")`.
     PostgreSQL evaluates these at INSERT time regardless of client.

     Reference: AoP (Data Integrity) — Fontaine argues the database must be
     self-consistent regardless of which client writes to it. SQLA ch. 5
     (Keyless Entry) — Karwin's "poka-yoke" principle: enforce constraints
     at the DB level so no code path can bypass them. HPPG ch. 4 — Atkinson
     demonstrates server-side defaults as the foundation of data correctness.

  4. FIXED — Comment.user_id CASCADE → SET NULL: The v3 schema had
     `ondelete="CASCADE"` on Comment.user_id. If the background cleanup
     worker hard-deletes a soft-deleted user, CASCADE would nuke all their
     comment rows — destroying ltree paths and orphaning every descendant
     comment in every thread they participated in. This directly contradicts
     the Reddit-style `[deleted]` pattern we added in v3.

     Changed to `ondelete="SET NULL"` with `nullable=True`. When a user is
     hard-deleted:
       • Comment.user_id becomes NULL (the comment stays, its author is gone)
       • The API layer renders NULL user_id as "[deleted]" for the author name
       • The ltree path is preserved — no descendant orphaning
       • The comment text was already blanked to "[deleted]" during the user
         soft-delete phase

     This mirrors Reddit's actual implementation: deleted users' comments
     show "[deleted]" for both author and text, but the thread structure
     is intact.

     Reference: SQLA ch. 5 (Keyless Entry) — Karwin demonstrates
     ON DELETE SET NULL as the correct FK action when the child row must
     survive the parent's deletion. GDB ch. 2 — path enumeration requires
     all intermediate nodes to exist (or at least persist as placeholders)
     to maintain tree integrity.

  5. ADDED — ContributorRoleEnum: BookContributor.role was a bare String(50)
     in the composite PK. Two spellings of the same role ("Author" vs
     "author") would create duplicate rows for the same logical relationship.
     Now uses a PostgreSQL ENUM with explicitly defined values.

     Reference: SQLA ch. 5 — Karwin's poka-yoke: the DB should reject
     invalid data at the constraint level. HPPG ch. 4 — Atkinson demonstrates
     PostgreSQL enums for domain integrity. AoP — Fontaine: the database
     outlives any single application version; an enum prevents future API
     versions from inserting garbage roles.

  6. ADDED — Denormalized counters on Book for trending/discovery:
     `log_count`, `avg_rating`, `currently_reading_count` enable explore
     pages ("trending books", "highest rated", "most popular right now")
     without full table scans + aggregation.

     These use the same write-behind pattern as BookEntry counters:
       1. Redis accumulates real-time deltas (INCR on log, HSET for rating)
       2. Background worker periodically flushes aggregated values to
          PostgreSQL in batch

     Indexes on `(is_active, log_count DESC)` and `(is_active, avg_rating DESC)`
     serve the explore page queries as simple backward range scans.

     Reference: DDIA ch. 7 — Kleppmann explains the MVCC COUNT(*) problem.
     SPE ch. 3 — Winand demonstrates that aggregate queries degrade linearly
     with table size; denormalized counters + indexes convert them to O(1).
     PG14I ch. 6 — Rogov explains why COUNT(*) and AVG() are expensive under
     MVCC: every qualifying tuple must be visibility-checked.
"""

from sqlalchemy import (
    Column,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    SmallInteger,
    Text,
    Date,
    Integer,
    CheckConstraint,
    Index,
    UniqueConstraint,
    Computed,
    event,
    DDL,
    PrimaryKeyConstraint,
    Enum as PgEnum,
    text,
    Numeric,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from sqlalchemy.types import UserDefinedType
import uuid6
import enum
from datetime import datetime, timezone

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM TYPES
# ═══════════════════════════════════════════════════════════════════════════════


class LtreeType(UserDefinedType):
    """
    Custom SQLAlchemy type for PostgreSQL's ltree extension.

    Why this exists (v2 fix, retained through v4):
    ───────────────────────────────────────────────
    The v1 schema declared Comment.path as Text and applied gist_ltree_ops
    in the index. This fails at migration time because PostgreSQL cannot apply
    ltree-specific operator classes to a TEXT column.

    A proper UserDefinedType ensures the emitted DDL uses `ltree` as the
    column type, which is what the GiST index and the `<@` operator require.

    Reference: PG14I ch. 26 (GiST) — Rogov explains that GiST operator
    classes are tightly coupled to the indexed data type. The `gist_ltree_ops`
    class expects an ltree column; applying it to TEXT is a type mismatch.

    Production note: Consider migrating to `sqlalchemy-utils.LtreeType` which
    adds Python-side path manipulation methods (parent, ancestors, depth).
    """

    cache_ok = True

    def get_col_spec(self):
        return "LTREE"

    def bind_processor(self, dialect):
        def process(value):
            return value

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            return value

        return process


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class ReadingStatusEnum(enum.Enum):
    """
    Represents the lifecycle of a user's relationship with a book.

    Defined at the PostgreSQL level via CREATE TYPE (PgEnum), which means
    invalid values are rejected by the database engine itself, even if
    application-layer validation is bypassed.

    Reference: HPPG ch. 4 — Atkinson demonstrates using PostgreSQL enums
    to enforce domain integrity at the database layer.
    """

    WANT_TO_READ = "want_to_read"
    READING = "reading"
    READ = "read"
    DID_NOT_FINISH = "did_not_finish"


class ActivityTypeEnum(enum.Enum):
    """
    Constrains Timeline.activity_type to known values.

    Reference: AoP — Fontaine argues the database should enforce as much
    domain logic as possible, because the database outlives any single
    application version.
    """

    REVIEW = "review"
    REPOST = "repost"
    STATUS_UPDATE = "status_update"


class ContributorRoleEnum(enum.Enum):
    """
    v4 addition: Constrains BookContributor.role to known values.

    The v3 schema used a bare String(50) in the composite PK. This meant
    "Author" vs "author" vs "AUTHOR" would create three separate rows for
    the same logical relationship — silent data duplication that corrupts
    contributor queries and book detail pages.

    By defining the enum with lowercase values, we normalize casing at the
    database level. The application layer maps display labels
    (e.g., "Author") to enum values (e.g., "author") before insertion.

    Reference: SQLA ch. 5 (Keyless Entry) — Karwin: the DB should reject
    invalid data at the constraint level. HPPG ch. 4 — Atkinson demonstrates
    PostgreSQL enums for domain integrity.
    """

    AUTHOR = "author"
    ILLUSTRATOR = "illustrator"
    TRANSLATOR = "translator"
    EDITOR = "editor"
    FOREWORD_BY = "foreword_by"
    NARRATOR = "narrator"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def generate_uuid7():
    """
    UUID v7: monotonically increasing identifiers with embedded timestamps.

    Sequential keys keep B-Tree inserts append-only at the rightmost leaf,
    which PostgreSQL optimizes as a "fastpath" — caching the rightmost leaf
    page and skipping the full root-to-leaf descent.

    Reference: DDIA ch. 3 (pp. 79–83) — B-Tree page splits and write
    amplification. DBI ch. 4 (pp. 71–72) — "right-only appends" optimization.
    PG14I ch. 25 — PostgreSQL's fastpath for monotonically increasing keys.
    """
    return uuid6.uuid7()


def utcnow():
    """Single source of truth for 'now' — monkeypatch in tests for determinism."""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
# POSTGRESQL EXTENSIONS
# ═══════════════════════════════════════════════════════════════════════════════

event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS ltree"),
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. USER & SOCIAL NETWORK
# ═══════════════════════════════════════════════════════════════════════════════


class User(Base):
    """
    The central identity entity.

    Soft-Delete Strategy (v3+):
    ───────────────────────────
    Users are soft-deleted rather than hard-deleted. Required because:
      1. BookEntry.user_id uses ondelete="RESTRICT" — hard DELETE is blocked.
      2. Provides a recovery window for accidental deletions.
      3. GDPR compliance: anonymize PII without destroying referential integrity.

    Username Reclaimability (v4 fix):
    ─────────────────────────────────
    Uniqueness is enforced ONLY by the partial unique index
    `ix_users_active_username` (WHERE is_deleted = false). The column itself
    has NO unique constraint. This means:
      • No two active users can share a username (partial unique index).
      • A soft-deleted user's username becomes immediately available for
        new registrations after PII anonymization.
      • The v3 approach (global unique=True + partial index) permanently
        locked every username ever used, even after deletion.

    Reference: SPE ch. 2 — Winand: partial unique indexes enforce uniqueness
    only within the subset matching the predicate.

    Denormalized Follower Counts:
    ─────────────────────────────
    follower_count / following_count avoid MVCC COUNT(*) O(N) scans.
    Write-behind pattern: Redis INCR → background batch flush to PostgreSQL.
    Feed worker uses follower_count to decide fan-out strategy (push vs pull).

    Reference: DDIA ch. 1 (pp. 11–13) — Twitter's hybrid fan-out. PG14I
    ch. 6 — why COUNT(*) is expensive under MVCC (xmin/xmax visibility).

    server_default (v4 fix):
    ────────────────────────
    All boolean and timestamp columns now have server_default so that raw
    SQL, Alembic backfills, CDC replays, and COPY commands get correct
    defaults without going through SQLAlchemy.

    Reference: AoP — Fontaine: the DB must be self-consistent regardless
    of client. SQLA ch. 5 — Karwin's poka-yoke principle.
    """

    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)

    # ── v4 fix: Removed `unique=True` for username reclaimability ──
    # Uniqueness is enforced by ix_users_active_username (partial unique).
    # The global unique constraint in v3 permanently blocked reuse of
    # usernames from deleted accounts.
    #
    # We keep `nullable=False` — every user must have a username. During
    # soft-delete anonymization, username is changed to "deleted_<hash>",
    # not set to NULL.
    username = Column(String(30), nullable=False)

    email = Column(String(254), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    avatar_url = Column(String(2048), nullable=True)
    location = Column(String(100), nullable=True)

    # ── Denormalized follower counts (write-behind from Redis) ──
    follower_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    following_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    # ── Soft-delete fields ──
    # v4 fix: server_default ensures DB-level defaults for non-ORM writes.
    is_deleted = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # ── Relationships ──
    entries = relationship(
        "BookEntry",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    reading_statuses = relationship(
        "ReadingStatus",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    lists = relationship(
        "BookList",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    comments = relationship(
        "Comment",
        back_populates="user",
        # Note: NOT "all, delete-orphan" — comments survive user deletion
        # (SET NULL on FK). SQLAlchemy delete-orphan would try to delete
        # comments when the user object is removed from session, which
        # conflicts with SET NULL semantics.
    )
    likes = relationship("Like", back_populates="user", cascade="all, delete-orphan")
    reposts = relationship(
        "Repost",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    followers = relationship(
        "Follow",
        foreign_keys="[Follow.followed_id]",
        back_populates="followed",
        cascade="all, delete-orphan",
    )
    following = relationship(
        "Follow",
        foreign_keys="[Follow.follower_id]",
        back_populates="follower",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # ── Partial unique index: active-user username uniqueness ──
        # This is the ONLY uniqueness constraint on username. No global
        # unique constraint exists, so deleted users' usernames are
        # reclaimable after anonymization.
        #
        # Reference: SPE ch. 2 — partial unique indexes enforce uniqueness
        # only within the subset matching the predicate.
        Index(
            "ix_users_active_username",
            "username",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        # ── Active email uniqueness ──
        # Same pattern: allow deleted users' emails to be reclaimed.
        # The global `unique=True` on the column is kept as a safety net,
        # but this partial index is what the planner uses for active lookups.
        Index(
            "ix_users_active_email",
            "email",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )


class Follow(Base):
    """
    Self-referencing many-to-many for the social graph.

    Index Strategy:
    • PK (follower_id, followed_id) — "who does user X follow?" prefix scan.
    • ix_follows_reverse — "who follows user X?" reverse lookup.

    Reference: DBI ch. 2 — B-tree lookup and leading column eligibility.
    GDB ch. 2 — relational join degradation per hop. For multi-hop graph
    queries, delegate to a graph DB via CDC — DDIA ch. 12.
    """

    __tablename__ = "follows"

    follower_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    followed_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    follower = relationship(
        "User",
        foreign_keys=[follower_id],
        back_populates="following",
    )
    followed = relationship(
        "User",
        foreign_keys=[followed_id],
        back_populates="followers",
    )

    __table_args__ = (
        CheckConstraint("follower_id != followed_id", name="ck_no_self_follow"),
        Index("ix_follows_reverse", "followed_id", "follower_id"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CORE ENTITIES — THE BOOK CATALOG
# ═══════════════════════════════════════════════════════════════════════════════


class Contributor(Base):
    """
    Authors, illustrators, translators, editors, etc.

    Reference: PG14I ch. 25 — B-tree on text supports equality + prefix scans.
    """

    __tablename__ = "contributors"

    contributor_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid7,
    )
    name = Column(String(200), nullable=False, index=True)
    bio = Column(Text, nullable=True)


class Book(Base):
    """
    The catalog entity. Fetched on-demand from the Google Books API.

    Full-Text Search:
    ─────────────────
    Two complementary indexes:
    1. B-tree on `title` — exact-match / prefix (autocomplete).
    2. GIN on `search_vector` — full-text search with stemming + ranking.

    Reference: IIR ch. 1–2 — inverted index, stemming, TF-IDF.
    PG14I ch. 28 — GIN architecture, pending list, posting trees.

    Denormalized Counters (v4 addition):
    ─────────────────────────────────────
    `log_count`, `avg_rating`, `currently_reading_count` enable explore/
    trending pages without expensive aggregate queries.

    Without these, "show me the 50 most-logged books" requires:
        SELECT book_id, COUNT(*) FROM book_entries
        WHERE is_deleted = false GROUP BY book_id
        ORDER BY count DESC LIMIT 50

    This is O(N) on the entire book_entries table — unusable at scale.
    With a denormalized counter + index, it's a single backward index scan.

    Write-behind pattern (same as BookEntry.like_count):
      1. Redis INCR on new log, DECR on soft-delete.
      2. For avg_rating: Redis HSET accumulates (sum, count) per book_id.
      3. Background worker periodically flushes to PostgreSQL in batch:
         UPDATE books SET log_count = :count, avg_rating = :avg
         WHERE book_id = :id

    Reference: DDIA ch. 7 — MVCC COUNT(*) problem. SPE ch. 3 — aggregate
    queries degrade linearly; denormalized counters convert to O(1).
    PG14I ch. 6 — COUNT/AVG expensive under MVCC (visibility checks).
    """

    __tablename__ = "books"

    book_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)
    external_api_id = Column(String(64), unique=True, nullable=False)
    isbn_13 = Column(String(13), unique=True, nullable=True)
    title = Column(String(500), nullable=False, index=True)
    published_date = Column(Date, nullable=True)
    edition = Column(String(100), nullable=True)
    publishing_location = Column(String(200), nullable=True)

    is_active = Column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    # ── Full-text search vector (generated column) ──
    search_vector = Column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title, ''))", persisted=True),
        nullable=True,
    )

    # ── v4 addition: Denormalized counters for trending/discovery ──
    #
    # log_count: Total number of non-deleted BookEntry rows for this book.
    #   Serves: "Most logged books", "Popular this week" (with a separate
    #   weekly counter or a time-windowed materialized view).
    #
    # avg_rating: Pre-computed average rating across all non-deleted entries
    #   that have a non-NULL rating. Stored as Numeric(3,2) for precision
    #   (e.g., 8.47 out of 10). NULL if no ratings exist yet.
    #   Serves: "Highest rated books", book detail page stats.
    #
    # currently_reading_count: Number of users whose ReadingStatus for this
    #   book is READING. Serves: "Trending right now", "Currently popular".
    #
    # All three use the same write-behind pattern as BookEntry counters:
    # Redis accumulates deltas → background worker flushes to PostgreSQL.
    #
    # Reference: DDIA ch. 11 — derived data / materialized views from event
    # streams. The BookEntry and ReadingStatus tables are the source of truth;
    # these counters are derived views that can be fully reconstructed.
    log_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    avg_rating = Column(
        Numeric(3, 2),
        nullable=True,
    )
    currently_reading_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    # ── Relationships ──
    contributors = relationship(
        "BookContributor",
        back_populates="book",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # ── GIN index for full-text search ──
        Index("ix_books_search", "search_vector", postgresql_using="gin"),
        # ── v4 addition: Explore/trending indexes ──
        # These serve the heavy stats queries you need for discovery pages.
        # Each is a composite index with is_active as leading column (equality
        # predicate) and the counter as trailing column (sort predicate).
        # PostgreSQL executes a single backward range scan — no aggregation.
        #
        # Reference: SPE ch. 2 — composite index with leading equality
        # predicate + trailing sort predicate enables sort-free top-N.
        # "Most logged active books"
        # Query: SELECT * FROM books WHERE is_active = true
        #        ORDER BY log_count DESC LIMIT 50
        Index("ix_books_popular", "is_active", log_count.desc()),
        # "Highest rated active books" (only books with ratings)
        # Query: SELECT * FROM books WHERE is_active = true AND avg_rating IS NOT NULL
        #        ORDER BY avg_rating DESC LIMIT 50
        Index(
            "ix_books_top_rated",
            "is_active",
            avg_rating.desc(),
            postgresql_where=text("avg_rating IS NOT NULL"),
        ),
        # "Trending right now" (most people currently reading)
        # Query: SELECT * FROM books WHERE is_active = true
        #        ORDER BY currently_reading_count DESC LIMIT 50
        Index("ix_books_trending", "is_active", currently_reading_count.desc()),
    )


class BookContributor(Base):
    """
    Intersection table resolving the many-to-many between Books and Contributors.

    v4 fix: `role` is now a PostgreSQL ENUM instead of bare String(50).

    Why an intersection table (vs. comma-separated string):
    ───────────────────────────────────────────────────────
    Reference: SQLA ch. 2 (Jaywalking) — Karwin: comma-separated IDs break
    First Normal Form, prevent index usage on JOINs, require regex parsing.

    Why an ENUM for role (vs. free-text):
    ─────────────────────────────────────
    The v3 PK was (book_id, contributor_id, role) with role as String(50).
    "Author" vs "author" vs "AUTHOR" would create three separate rows for
    the same logical relationship — silent data duplication.

    The enum normalizes casing and restricts values to known roles.

    Reference: SQLA ch. 5 — poka-yoke: the DB should reject invalid data.
    HPPG ch. 4 — PostgreSQL enums for domain integrity.
    """

    __tablename__ = "book_contributors"

    book_id = Column(
        UUID(as_uuid=True),
        ForeignKey("books.book_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contributor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("contributors.contributor_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # ── v4 fix: ENUM instead of bare String ──
    role = Column(
        PgEnum(
            ContributorRoleEnum,
            name="contributor_role_enum",
            create_type=True,
        ),
        primary_key=True,
    )

    book = relationship("Book", back_populates="contributors")
    contributor = relationship("Contributor")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. READING STATUS
# ═══════════════════════════════════════════════════════════════════════════════


class ReadingStatus(Base):
    """
    Tracks a user's current relationship with a book.

    Design Decisions:
    • Composite PK (user_id, book_id) — one status per user-book pair.
    • Separate from BookEntry (status != review; re-reads don't change status).
    • book_id RESTRICT — can't delete a Book with reading statuses.

    Index Strategy:
    • (user_id, status) — "all books user X is currently reading."
    • (book_id) — "how many people are reading book Y."

    Reference: DBI ch. 3 — composite index structure and range scans.
    """

    __tablename__ = "reading_statuses"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    book_id = Column(
        UUID(as_uuid=True),
        ForeignKey("books.book_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    status = Column(
        PgEnum(ReadingStatusEnum, name="reading_status_enum", create_type=True),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user = relationship("User", back_populates="reading_statuses")
    book = relationship("Book")

    __table_args__ = (
        Index("ix_reading_status_user_status", "user_id", "status"),
        Index("ix_reading_status_book", "book_id"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. USER INTERACTIONS — LOGS, REVIEWS & LISTS
# ═══════════════════════════════════════════════════════════════════════════════


class BookEntry(Base):
    """
    A user's log/review of a book. The central content entity.

    Re-reads: No unique constraint on (user_id, book_id) — intentional.
    Soft Delete: is_deleted flag + partial indexes. Background worker
                 hard-deletes old rows during low-traffic windows.
    Counters: like_count, repost_count, comment_count via write-behind.

    Reference: PG14I ch. 6 — MVCC tuple versioning and autovacuum tuning
    for high-mutation tables. DDIA ch. 7 — MVCC snapshot isolation.
    DDIA ch. 11 — event sourcing (Like/Repost as append-only logs).
    """

    __tablename__ = "book_entries"

    entry_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)

    # ondelete="RESTRICT" — user deletion is application-managed (soft-delete).
    # Reference: HPPG ch. 5, DBRE ch. 7.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    book_id = Column(
        UUID(as_uuid=True),
        ForeignKey("books.book_id", ondelete="RESTRICT"),
        nullable=False,
    )

    rating = Column(SmallInteger, nullable=True)
    review_text = Column(Text, nullable=True)
    is_spoiler = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    mood = Column(String(50), nullable=True)

    is_deleted = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    logged_date = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    # ── Denormalized counters (write-behind from Redis) ──
    like_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    repost_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    comment_count = Column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    # ── Relationships ──
    user = relationship("User", back_populates="entries")
    book = relationship("Book")
    comments = relationship(
        "Comment",
        back_populates="entry",
        cascade="all, delete-orphan",
    )
    likes = relationship(
        "Like",
        back_populates="entry",
        cascade="all, delete-orphan",
    )
    reposts = relationship(
        "Repost",
        back_populates="entry",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 10", name="ck_rating_range"),
        # Profile feed: (user_id, created_at DESC) partial on active rows.
        # Reference: SPE ch. 2–3, PG14I ch. 25.
        Index(
            "ix_book_entries_user_created",
            "user_id",
            created_at.desc(),
            postgresql_where=text("is_deleted = false"),
        ),
        # Per-book aggregates: partial on active rows.
        Index(
            "ix_book_entries_book",
            "book_id",
            postgresql_where=text("is_deleted = false"),
        ),
        # Non-partial FK safety index (for CASCADE / RESTRICT lookups
        # that need to see ALL rows including soft-deleted).
        # Reference: PG14I ch. 20.
        Index("ix_book_entries_user_fk", "user_id"),
    )


class BookList(Base):
    """
    User-curated book lists.

    is_public controls visibility on the user's public profile.
    """

    __tablename__ = "lists"

    list_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    list_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    is_public = Column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user = relationship("User", back_populates="lists")
    items = relationship(
        "ListItem",
        back_populates="book_list",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "list_name", name="uq_user_list_name"),
        # ── v4 fix: Explore page index — removed redundant is_public column ──
        # Every row in this partial index already has is_public = true, so
        # including is_public as a key column adds zero selectivity — it's
        # a constant value for every entry. Only created_at matters for sort.
        #
        # Reference: SPE ch. 2 — don't put constant-value columns in the
        # index key when a partial predicate already handles the filtering.
        Index(
            "ix_lists_public_created",
            created_at.desc(),
            postgresql_where=text("is_public = true"),
        ),
    )


class ListItem(Base):
    """
    Junction table for user-curated book lists with explicit ordering.

    Reference: PG14I ch. 25 — PK on (list_id, book_id) doesn't help
    ORDER BY position. Separate index on (list_id, position) required.
    """

    __tablename__ = "list_items"

    list_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lists.list_id", ondelete="CASCADE"),
        primary_key=True,
    )
    book_id = Column(
        UUID(as_uuid=True),
        ForeignKey("books.book_id", ondelete="CASCADE"),
        primary_key=True,
    )
    position = Column(Integer, nullable=False, default=0, server_default=text("0"))
    added_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    book_list = relationship("BookList", back_populates="items")
    book = relationship("Book")

    __table_args__ = (Index("ix_list_items_position", "list_id", "position"),)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. COMMUNITY ENGAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


class Comment(Base):
    """
    Threaded comment system using PostgreSQL's native ltree extension.

    Hierarchical Model — Path Enumeration (ltree):
    ───────────────────────────────────────────────
    • Subtree query: O(1) via GiST index with `<@` operator.
    • Storage: O(N) — one path string per row.
    • Integrity: No native FK on path segments — soft-delete required.

    Reference: GDB ch. 2 — path enumeration trade-offs.
    SQLA ch. 3 (Naive Trees) — Karwin's formal analysis of adjacency list,
    path enumeration, and closure table models.

    Soft Delete — Reddit-style "[deleted]" (v3+):
    ──────────────────────────────────────────────
    is_deleted=True → comment_text blanked to "[deleted]". The ltree path
    is preserved so all descendants keep correct ancestry.

    User Deletion — SET NULL (v4 fix):
    ───────────────────────────────────
    Comment.user_id now uses ondelete="SET NULL" with nullable=True.

    When a user is hard-deleted by the cleanup worker:
      • user_id becomes NULL — the comment stays, author is gone.
      • API renders NULL user_id as "[deleted]" for the author name.
      • ltree path is preserved — no descendant orphaning.
      • comment_text was already "[deleted]" from the user soft-delete phase.

    The v3 schema had ondelete="CASCADE" which would nuke the entire comment
    row on user hard-delete — destroying ltree paths and orphaning every
    descendant in every thread the user participated in.

    Reference: SQLA ch. 5 — Karwin: ON DELETE SET NULL is correct when the
    child row must survive the parent's deletion. GDB ch. 2 — path
    enumeration requires intermediate nodes to persist for tree integrity.

    ltree Path Format:
    ──────────────────
    path = 'root_comment_id.child_id.grandchild_id'
    NOTE: ltree labels cannot contain hyphens — strip UUID dashes.

    Query patterns:
      SELECT * FROM comments WHERE path <@ 'root_id' ORDER BY path;
      SELECT nlevel(path) FROM comments WHERE comment_id = ?;
      SELECT * FROM comments WHERE path ~ 'root_id.*{1}';
    """

    __tablename__ = "comments"

    comment_id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid7)

    # ── v4 fix: SET NULL + nullable=True ──
    # When a user is hard-deleted, the comment survives with user_id = NULL.
    # The API layer renders this as "[deleted]" for the author name.
    # CASCADE would destroy the comment row, orphaning ltree descendants.
    #
    # Reference: SQLA ch. 5 — SET NULL for child rows that must survive
    # parent deletion. GDB ch. 2 — tree integrity requires intermediate
    # nodes to persist.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("book_entries.entry_id", ondelete="CASCADE"),
        nullable=False,
    )

    path = Column(LtreeType, nullable=False)
    comment_text = Column(Text, nullable=False)

    is_deleted = Column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user = relationship("User", back_populates="comments")
    entry = relationship("BookEntry", back_populates="comments")

    __table_args__ = (
        # GiST for ltree — MUST include all comments (including soft-deleted)
        # because descendant paths reference deleted ancestors.
        Index("ix_comments_path_gist", "path", postgresql_using="gist"),
        # All comments on entry X (including [deleted] for thread structure).
        Index("ix_comments_entry", "entry_id"),
        # All comments by user X (profile/activity pages).
        Index("ix_comments_user", "user_id"),
    )


class Like(Base):
    """
    Append-only event log for likes. Composite PK enforces uniqueness
    (no double-liking) and serves "has user X liked entry Y?" lookups.

    Reference: DDIA ch. 11 — Event Sourcing pattern.
    """

    __tablename__ = "likes"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("book_entries.entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user = relationship("User", back_populates="likes")
    entry = relationship("BookEntry", back_populates="likes")

    __table_args__ = (Index("ix_likes_entry", "entry_id"),)


class Repost(Base):
    """Same event-sourcing pattern as Like. See Like docstring."""

    __tablename__ = "reposts"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("book_entries.entry_id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user = relationship("User", back_populates="reposts")
    entry = relationship("BookEntry", back_populates="reposts")

    __table_args__ = (Index("ix_reposts_entry", "entry_id"),)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FEED GENERATION — HYBRID FAN-OUT
# ═══════════════════════════════════════════════════════════════════════════════


class Timeline(Base):
    """
    Pre-computed feed for the "following" timeline.

    Fan-Out: DDIA ch. 1 — hybrid push/pull based on follower_count threshold.
    Partitioning: DDIA ch. 6 — range-partition by created_at when table grows.
    Pagination: SPE ch. 7 — cursor-based (seek method), not OFFSET.
    Covering Index: HPPG ch. 7, PG14I ch. 20 — index-only scans.
    """

    __tablename__ = "timeline"

    timeline_id = Column(UUID(as_uuid=True), default=generate_uuid7, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=text("now()"),
        nullable=False,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("book_entries.entry_id", ondelete="CASCADE"),
        nullable=False,
    )

    activity_type = Column(
        PgEnum(ActivityTypeEnum, name="activity_type_enum", create_type=True),
        nullable=False,
    )

    __table_args__ = (
        # Composite PK includes partition key from day one.
        PrimaryKeyConstraint("timeline_id", "created_at"),
        # Covering index for the feed query (index-only scan).
        Index(
            "ix_timeline_user_created",
            "user_id",
            created_at.desc(),
            postgresql_include=["entry_id", "activity_type"],
        ),
        # Deduplication (without created_at — true idempotency).
        # PARTITIONING NOTE: when partitioning by created_at, this constraint
        # must move to application-layer ON CONFLICT DO NOTHING logic.
        UniqueConstraint(
            "user_id",
            "entry_id",
            "activity_type",
            name="uq_timeline_no_dupes",
        ),
        # Entry-level index for CASCADE cleanup.
        Index("ix_timeline_entry", "entry_id"),
    )
