-- Add account authentication to an existing NewsIntentRec MySQL 8 database.
-- A separate locked sequence avoids altering the externally referenced app_user primary key.
CREATE TABLE IF NOT EXISTS auth_user_id_sequence (
  sequence_key VARCHAR(64) NOT NULL,
  next_user_id BIGINT NOT NULL,
  PRIMARY KEY (sequence_key)
) ENGINE=InnoDB COMMENT='Locked ID allocation for users created by the application.';

INSERT INTO auth_user_id_sequence (sequence_key, next_user_id)
SELECT 'registered_user', GREATEST(1000000000, COALESCE(MAX(user_id), 0) + 1)
FROM app_user
ON DUPLICATE KEY UPDATE next_user_id = GREATEST(
  auth_user_id_sequence.next_user_id,
  VALUES(next_user_id)
);

CREATE TABLE IF NOT EXISTS user_account (
  user_id BIGINT NOT NULL,
  email VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_user_account_email (email),
  CONSTRAINT fk_user_account_user FOREIGN KEY (user_id) REFERENCES app_user (user_id)
) ENGINE=InnoDB COMMENT='Login credentials linked one-to-one with recommendation users.';
