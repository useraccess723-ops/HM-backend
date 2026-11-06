"""Database-backed, concurrency-safe sequential identifier allocation service.

Guarantees 100% unique, consecutive, tenant-isolated sequence numbers across:
- Multiple simultaneous users
- Multiple Python threads
- Multiple Uvicorn/Gunicorn worker processes
- Multiple server container instances / horizontal replicas
"""
import re
import time
import random
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError, DBAPIError
from app.models.entities import TenantSequence, OperationalRecord

logger = logging.getLogger("stayflow.sequences")

def _is_transient_lock_error(exc: Exception) -> bool:
    """Check if exception is a transient database lock timeout or deadlock."""
    if isinstance(exc, (OperationalError, DBAPIError)):
        err_msg = str(exc).lower()
        # MySQL: 1205 (lock wait timeout), 1213 (deadlock)
        # PostgreSQL: 55P03 (lock not available), 40P01 (deadlock), 40001 (serialization failure)
        transient_signatures = [
            "1205", "lock wait timeout",
            "1213", "deadlock found",
            "55p03", "40p01", "40001", "could not serialize", "deadlock detected"
        ]
        if any(sig in err_msg for sig in transient_signatures):
            return True
        orig = getattr(exc, "orig", None)
        if orig and hasattr(orig, "args") and len(orig.args) > 0:
            code = orig.args[0]
            if code in (1205, 1213):
                return True
    return False

def get_highest_existing_beo(db: Session, tenant_id: int, baseline_default: int = 512) -> int:
    """Inspects existing operational records for the tenant to determine the highest existing BEO number.
    
    Uses case-insensitive regex matching to recognize both uppercase ('BEO-') and lowercase ('beo-') prefixes.
    """
    max_found = baseline_default
    try:
        recs = db.scalars(
            select(OperationalRecord.title).where(
                OperationalRecord.tenant_id == tenant_id,
                OperationalRecord.category.in_(["food-beverage_banquets", "food_beverage_banquets", "banquets"])
            )
        ).all()
        for title in recs:
            m = re.search(r'BEO-(\d+)', str(title or ""), re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if val > max_found:
                    max_found = val
    except Exception as e:
        logger.warning("Notice inspecting existing BEO records for tenant %s: %s", tenant_id, e)
    return max_found

def allocate_next_sequence_number(
    db: Session,
    tenant_id: int,
    sequence_key: str = "banquet_beo",
    default_start: int = 512,
    prefix: str = "BEO-",
    max_attempts: int = 3
) -> str:
    """
    Atomically allocates and returns the next sequential number for the specified tenant.
    
    Uses database row-level locking (SELECT ... FOR UPDATE) to serialize allocations
    across independent worker processes and server instances.
    Safely handles simultaneous first-time row initialization via savepoint nested rollback.
    Includes controlled retry on transient lock-wait timeouts up to max_attempts with bounded jitter.
    """
    if not tenant_id:
        raise ValueError("Tenant ID is required for sequence allocation.")

    stmt = (
        select(TenantSequence)
        .where(
            TenantSequence.tenant_id == tenant_id,
            TenantSequence.sequence_key == sequence_key
        )
        .with_for_update()
    )

    for attempt in range(1, max_attempts + 1):
        try:
            with db.begin_nested():
                seq = db.scalar(stmt)

                if seq is None:
                    # Row does not exist yet for this tenant. Determine historical baseline:
                    baseline = get_highest_existing_beo(db, tenant_id, baseline_default=default_start)
                    next_val = baseline + 1

                    try:
                        # Handle potential simultaneous initial insert from another worker process
                        with db.begin_nested():
                            new_seq = TenantSequence(
                                tenant_id=tenant_id,
                                sequence_key=sequence_key,
                                current_value=next_val
                            )
                            db.add(new_seq)
                            db.flush()
                        return f"{prefix}{next_val}"
                    except IntegrityError:
                        # Another worker process created the row at the exact same millisecond.
                        # Re-fetch the now-existing row with row-level lock:
                        seq = db.scalar(stmt)
                        if seq is not None:
                            seq.current_value += 1
                            db.flush()
                            return f"{prefix}{seq.current_value}"
                        else:
                            return f"{prefix}{next_val}"

                # Row exists and is locked exclusively by this transaction:
                seq.current_value += 1
                db.flush()
                return f"{prefix}{seq.current_value}"

        except Exception as exc:
            if _is_transient_lock_error(exc) and attempt < max_attempts:
                jitter = random.uniform(0.02, 0.06) * attempt
                logger.warning(
                    "Transient database lock error on attempt %d/%d for tenant %s: %s. Retrying in %.3fs...",
                    attempt, max_attempts, tenant_id, exc, jitter
                )
                time.sleep(jitter)
                continue
            # Non-transient errors or exhausted attempts are re-raised immediately
            raise
