CREATE TABLE verify_attempts (             -- one row per /api/auth/verify call, keyed by the caller's IP
  ip         inet NOT NULL,
  created_at timestamptz NOT NULL
);
CREATE INDEX verify_attempts_ip_created ON verify_attempts (ip, created_at);
