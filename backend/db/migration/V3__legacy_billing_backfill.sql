DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM credit_transactions txn
        LEFT JOIN generation_jobs job ON txn.reason = 'job:' || job.id
        WHERE txn.amount < 0
          AND txn.reason LIKE 'job:%'
          AND job.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot backfill billing: an existing job charge has no matching job';
    END IF;

    IF EXISTS (
        SELECT substring(reason FROM 5)
        FROM credit_transactions
        WHERE amount < 0 AND reason LIKE 'job:%'
        GROUP BY substring(reason FROM 5)
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Cannot backfill billing: a job has multiple legacy charge transactions';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM credit_transactions
        WHERE amount < 0
          AND reason NOT LIKE 'job:%'
          AND reason NOT LIKE 'admin:%'
    ) THEN
        RAISE EXCEPTION 'Cannot backfill billing: an unclassified negative transaction exists';
    END IF;
END $$;

UPDATE generation_jobs job
SET model_label_snapshot = COALESCE(
        (SELECT model.label FROM model_configs model WHERE model.id = job.model),
        job.model
    ),
    provider_id_snapshot = (
        SELECT model.provider_id FROM model_configs model WHERE model.id = job.model
    ),
    provider_name_snapshot = (
        SELECT provider.name
        FROM model_configs model
        JOIN upstream_providers provider ON provider.id = model.provider_id
        WHERE model.id = job.model
    ),
    credit_cost_snapshot = COALESCE(
        (
            SELECT abs(txn.amount)
            FROM credit_transactions txn
            WHERE txn.reason = 'job:' || job.id AND txn.amount < 0
        ),
        (SELECT model.credit_cost FROM model_configs model WHERE model.id = job.model),
        0
    );

UPDATE generation_jobs
SET status = 'FAILED',
    error_message = '系统升级期间生成任务已中断，灵感丝线已自动退回。',
    finished_at = CURRENT_TIMESTAMP,
    execution_token = NULL,
    lease_expires_at = NULL
WHERE status IN ('QUEUED', 'PROCESSING');

UPDATE credit_transactions
SET transaction_type = CASE
        WHEN reason LIKE 'redeem:%' THEN 'redeem'
        WHEN reason LIKE 'job:%' AND amount < 0 THEN 'job_reserve'
        WHEN reason LIKE 'admin:%' THEN 'admin_adjust'
        ELSE 'reconciliation'
    END,
    job_id = CASE WHEN reason LIKE 'job:%' THEN substring(reason FROM 5) ELSE NULL END,
    idempotency_key = 'legacy-transaction:' || id,
    details = json_build_object('legacy_reason', reason);

WITH user_ledger AS (
    SELECT
        user_account.id AS user_id,
        user_account.credits - COALESCE(sum(txn.amount), 0) AS opening_amount,
        COALESCE(min(txn.created_at), user_account.created_at) - INTERVAL '1 microsecond' AS opening_at
    FROM users user_account
    LEFT JOIN credit_transactions txn ON txn.user_id = user_account.id
    GROUP BY user_account.id, user_account.credits, user_account.created_at
), opening_rows AS (
    SELECT
        substring(md5('opening:' || user_id), 1, 8) || '-' ||
        substring(md5('opening:' || user_id), 9, 4) || '-' ||
        substring(md5('opening:' || user_id), 13, 4) || '-' ||
        substring(md5('opening:' || user_id), 17, 4) || '-' ||
        substring(md5('opening:' || user_id), 21, 12) AS id,
        user_id,
        opening_amount,
        opening_at
    FROM user_ledger
    WHERE opening_amount <> 0
)
INSERT INTO credit_transactions (
    id, user_id, amount, balance_after, reason, transaction_type,
    idempotency_key, details, created_at
)
SELECT
    id, user_id, opening_amount, opening_amount, 'migration:opening-balance', 'opening_balance',
    'opening-balance:' || user_id, json_build_object('source', 'flyway-v3'), opening_at
FROM opening_rows;

INSERT INTO job_charges (
    id, job_id, user_id, amount, status, reserve_transaction_id,
    model_label, provider_name, created_at, settled_at
)
SELECT
    job.id,
    job.id,
    txn.user_id,
    abs(txn.amount),
    CASE WHEN job.status = 'SUCCEEDED' THEN 'settled' ELSE 'reserved' END,
    txn.id,
    COALESCE(job.model_label_snapshot, job.model),
    job.provider_name_snapshot,
    txn.created_at,
    CASE WHEN job.status = 'SUCCEEDED' THEN COALESCE(job.finished_at, CURRENT_TIMESTAMP) ELSE NULL END
FROM credit_transactions txn
JOIN generation_jobs job ON txn.job_id = job.id
WHERE txn.transaction_type = 'job_reserve';

WITH refundable AS (
    SELECT
        charge.job_id,
        charge.user_id,
        charge.amount,
        charge.reserve_transaction_id,
        charge.model_label,
        charge.provider_name,
        job.finished_at,
        job.created_at
    FROM job_charges charge
    JOIN generation_jobs job ON job.id = charge.job_id
    WHERE job.status = 'FAILED' AND charge.status = 'reserved'
), refund_rows AS (
    SELECT
        substring(md5('legacy-refund:' || refundable.job_id), 1, 8) || '-' ||
        substring(md5('legacy-refund:' || refundable.job_id), 9, 4) || '-' ||
        substring(md5('legacy-refund:' || refundable.job_id), 13, 4) || '-' ||
        substring(md5('legacy-refund:' || refundable.job_id), 17, 4) || '-' ||
        substring(md5('legacy-refund:' || refundable.job_id), 21, 12) AS id,
        refundable.*,
        user_account.credits + sum(refundable.amount) OVER (
            PARTITION BY refundable.user_id
            ORDER BY refundable.created_at, refundable.job_id
        ) AS balance_after
    FROM refundable
    JOIN users user_account ON user_account.id = refundable.user_id
)
INSERT INTO credit_transactions (
    id, user_id, amount, balance_after, reason, transaction_type, job_id,
    related_transaction_id, idempotency_key, details, created_at
)
SELECT
    id,
    user_id,
    amount,
    balance_after,
    'job-refund:' || job_id,
    'job_refund',
    job_id,
    reserve_transaction_id,
    'legacy-job-refund:' || job_id,
    json_build_object('model_label', model_label, 'provider_name', provider_name, 'source', 'flyway-v3'),
    COALESCE(finished_at, CURRENT_TIMESTAMP)
FROM refund_rows;

WITH refund_totals AS (
    SELECT user_id, sum(amount) AS amount
    FROM credit_transactions
    WHERE transaction_type = 'job_refund' AND idempotency_key LIKE 'legacy-job-refund:%'
    GROUP BY user_id
)
UPDATE users user_account
SET credits = user_account.credits + refund_totals.amount
FROM refund_totals
WHERE user_account.id = refund_totals.user_id;

UPDATE job_charges charge
SET status = 'refunded',
    refund_transaction_id = txn.id,
    refunded_at = txn.created_at
FROM credit_transactions txn
WHERE txn.job_id = charge.job_id
  AND txn.transaction_type = 'job_refund'
  AND txn.idempotency_key LIKE 'legacy-job-refund:%';

-- The synthetic opening balance changes every later historical ending balance.
-- Recompute the complete ledger once, before the append-only trigger is enabled,
-- so imported statements remain internally consistent and auditable.
WITH running_balances AS (
    SELECT
        id,
        sum(amount) OVER (
            PARTITION BY user_id
            ORDER BY created_at, id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS balance_after
    FROM credit_transactions
)
UPDATE credit_transactions txn
SET balance_after = running_balances.balance_after
FROM running_balances
WHERE running_balances.id = txn.id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM users user_account
        LEFT JOIN (
            SELECT user_id, sum(amount) AS ledger_balance
            FROM credit_transactions
            GROUP BY user_id
        ) ledger ON ledger.user_id = user_account.id
        WHERE user_account.credits <> COALESCE(ledger.ledger_balance, 0)
    ) THEN
        RAISE EXCEPTION 'Cannot finish billing backfill: cached balance does not match immutable ledger';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION prevent_credit_transaction_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'credit_transactions is append-only';
END;
$$;

CREATE TRIGGER credit_transactions_append_only
BEFORE UPDATE OR DELETE ON credit_transactions
FOR EACH ROW EXECUTE FUNCTION prevent_credit_transaction_mutation();
