ALTER TABLE users ADD COLUMN is_admin boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN disabled_at timestamptz;   -- set: no sign-in, no sessions, no gated files

CREATE TABLE invites (                                 -- pending only: the row is deleted when its user signs in
  email      text PRIMARY KEY,                         -- lower-cased
  invited_by bigint REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
