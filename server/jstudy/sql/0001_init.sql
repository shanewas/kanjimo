CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE users (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email       text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower ON users (lower(email));

CREATE TABLE login_codes (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email       text NOT NULL,                 -- lower-cased
  code_hash   bytea NOT NULL,                -- HMAC-SHA256(SESSION_PEPPER, email || ':' || code)
  ip          inet,
  attempts    smallint NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,          -- created_at + 10 min
  used_at     timestamptz
);
CREATE INDEX login_codes_email_created ON login_codes (email, created_at);
CREATE INDEX login_codes_ip_created ON login_codes (ip, created_at);

CREATE TABLE sessions (
  token_hash   bytea PRIMARY KEY,            -- sha256(raw cookie token)
  user_id      bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,         -- last_seen_at + 30 d, capped at created_at + 365 d
  ip           inet,
  user_agent   text
);
CREATE INDEX sessions_user ON sessions (user_id);

CREATE TABLE progress (
  user_id     bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  rev         bigint NOT NULL DEFAULT 1,
  store       jsonb NOT NULL,
  bytes       integer NOT NULL CHECK (bytes <= 1048576),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE entitlements (
  user_id                bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  plan                   text NOT NULL CHECK (plan IN ('free', 'paid')),
  source                 text NOT NULL CHECK (source IN ('stripe', 'manual')),
  stripe_customer_id     text UNIQUE,
  stripe_subscription_id text UNIQUE,
  stripe_status          text,               -- mirror: active | trialing | past_due | canceled | unpaid | ...
  paid_until             timestamptz,        -- period end + 7 d grace; NULL with plan='paid' means no expiry (manual)
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stripe_webhook_inbox (
  event_id        text PRIMARY KEY,
  event_type      text NOT NULL,
  livemode        boolean NOT NULL,
  payload         jsonb NOT NULL,
  state           text NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending', 'processing', 'succeeded', 'failed', 'dead_letter')),
  attempts        smallint NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error      text,
  received_at     timestamptz NOT NULL DEFAULT now(),
  processed_at    timestamptz
);
CREATE INDEX inbox_claim ON stripe_webhook_inbox (state, next_attempt_at);

CREATE TABLE payments (                    -- idempotent money ledger; survives account deletion (7-year retention)
  stripe_event_id    text PRIMARY KEY,
  user_id            bigint REFERENCES users(id) ON DELETE SET NULL,
  stripe_customer_id text NOT NULL,
  kind               text NOT NULL,          -- invoice.paid | charge.refunded
  amount             integer NOT NULL,       -- minor units, negative for refunds
  currency           text NOT NULL,
  stripe_invoice_id  text,
  occurred_at        timestamptz NOT NULL
);

CREATE TABLE data_hits (                   -- per-user daily budget for gated files
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day     date NOT NULL,
  hits    integer NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);

CREATE TABLE settings (key text PRIMARY KEY, value text NOT NULL);
INSERT INTO settings VALUES ('billing_enabled', 'false') ON CONFLICT DO NOTHING;
