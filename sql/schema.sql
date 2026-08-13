-- 为已配置的 NewsIntentRec 运行时数据库定义 MySQL 8.0 模式。
-- 原始 MIND 文件及规范化/模型制品仅作为离线输入。
-- 在线服务必须将下列 MySQL 表作为唯一的运行时事实来源。

DROP TABLE IF EXISTS event_outbox;
DROP TABLE IF EXISTS user_event;
DROP TABLE IF EXISTS event_idempotency;
DROP TABLE IF EXISTS feed_request;
DROP TABLE IF EXISTS sponsored_delivery;
DROP TABLE IF EXISTS sponsored_user_daily_frequency;
DROP TABLE IF EXISTS sponsored_campaign_daily_state;
DROP TABLE IF EXISTS sponsored_creative;
DROP TABLE IF EXISTS sponsored_campaign_topic;
DROP TABLE IF EXISTS sponsored_campaign;
DROP TABLE IF EXISTS user_profile;
DROP TABLE IF EXISTS system_profile_seed;
DROP TABLE IF EXISTS hot_answer_snapshot;
DROP TABLE IF EXISTS query_topic_map;
DROP TABLE IF EXISTS answer_topic;
DROP TABLE IF EXISTS question_topic;
DROP TABLE IF EXISTS answer;
DROP TABLE IF EXISTS question;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS author;
DROP TABLE IF EXISTS topic;
DROP TABLE IF EXISTS worker_heartbeat;

CREATE TABLE topic (
  topic_id BIGINT NOT NULL,
  display_name VARCHAR(128) NULL COMMENT 'MIND category or subcategory label.',
  answer_count INT NOT NULL DEFAULT 0,
  question_count INT NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL DEFAULT 'mind_small',
  PRIMARY KEY (topic_id)
) ENGINE=InnoDB COMMENT='News category dimension.';

CREATE TABLE author (
  author_id BIGINT NOT NULL,
  display_name VARCHAR(128) NULL COMMENT 'Source domain compatibility dimension.',
  is_excellent_author TINYINT(1) NOT NULL DEFAULT 0,
  follower_count INT NOT NULL DEFAULT 0,
  is_excellent_answerer TINYINT(1) NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL DEFAULT 'mind_small',
  PRIMARY KEY (author_id)
) ENGINE=InnoDB COMMENT='Source-domain compatibility records.';

CREATE TABLE app_user (
  user_id BIGINT NOT NULL,
  display_name VARCHAR(128) NULL COMMENT 'Demo persona label.',
  register_ts BIGINT NULL,
  gender TINYINT NULL,
  login_frequency TINYINT NULL,
  follower_count INT NOT NULL DEFAULT 0,
  followed_topic_count INT NOT NULL DEFAULT 0,
  answer_count INT NOT NULL DEFAULT 0,
  question_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  thanks_received_count INT NOT NULL DEFAULT 0,
  likes_received_count INT NOT NULL DEFAULT 0,
  province VARCHAR(64) NULL,
  city VARCHAR(64) NULL,
  followed_topic_ids_json JSON NULL,
  is_demo_user TINYINT(1) NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL DEFAULT 'mind_small',
  PRIMARY KEY (user_id)
) ENGINE=InnoDB COMMENT='MIND-derived demo users and compatibility records.';

CREATE TABLE event_idempotency (
  external_event_id VARCHAR(128) NOT NULL,
  payload_fingerprint CHAR(64) NOT NULL,
  user_id BIGINT NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (external_event_id),
  KEY idx_event_idempotency_user_created (user_id, created_at),
  CONSTRAINT fk_event_idempotency_user
    FOREIGN KEY (user_id) REFERENCES app_user (user_id)
) ENGINE=InnoDB COMMENT='Atomic claim table for retry-safe event processing.';

CREATE TABLE feed_request (
  request_id VARCHAR(128) NOT NULL,
  user_id BIGINT NOT NULL,
  page_size INT NOT NULL,
  debug TINYINT(1) NOT NULL,
  include_sponsored TINYINT(1) NOT NULL,
  experiment_arm VARCHAR(64) NOT NULL,
  as_of_ts BIGINT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (request_id),
  KEY idx_feed_request_user_created (user_id, created_at),
  CONSTRAINT fk_feed_request_user
    FOREIGN KEY (user_id) REFERENCES app_user (user_id)
) ENGINE=InnoDB COMMENT='Idempotency claim for feed loads that may reserve sponsored delivery.';

CREATE TABLE question (
  question_id BIGINT NOT NULL,
  create_ts BIGINT NULL,
  answer_count INT NOT NULL DEFAULT 0,
  follower_count INT NOT NULL DEFAULT 0,
  invitation_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  token_ids_json JSON NULL COMMENT 'Reserved compatibility field.',
  topic_ids_json JSON NULL,
  display_title VARCHAR(255) NULL COMMENT 'MIND article headline.',
  source VARCHAR(32) NOT NULL DEFAULT 'mind_small',
  PRIMARY KEY (question_id)
) ENGINE=InnoDB COMMENT='Article headline compatibility table.';

CREATE TABLE answer (
  answer_id BIGINT NOT NULL,
  question_id BIGINT NULL,
  author_id BIGINT NULL,
  is_anonymous TINYINT(1) NOT NULL DEFAULT 0,
  is_high_value TINYINT(1) NOT NULL DEFAULT 0,
  is_editor_recommended TINYINT(1) NOT NULL DEFAULT 0,
  create_ts BIGINT NULL,
  has_picture TINYINT(1) NOT NULL DEFAULT 0,
  has_video TINYINT(1) NOT NULL DEFAULT 0,
  thanks_count INT NOT NULL DEFAULT 0,
  likes_count INT NOT NULL DEFAULT 0,
  comment_count INT NOT NULL DEFAULT 0,
  collection_count INT NOT NULL DEFAULT 0,
  dislike_count INT NOT NULL DEFAULT 0,
  report_count INT NOT NULL DEFAULT 0,
  helpless_count INT NOT NULL DEFAULT 0,
  token_ids_json JSON NULL COMMENT 'Reserved compatibility field.',
  topic_ids_json JSON NULL,
  display_summary TEXT NULL COMMENT 'MIND article abstract.',
  vector_key VARCHAR(128) NULL COMMENT 'Lookup key for ANN/vector assets built offline.',
  is_demo_selected TINYINT(1) NOT NULL DEFAULT 0,
  hot_score DOUBLE NOT NULL DEFAULT 0,
  click_count INT NOT NULL DEFAULT 0,
  impression_count INT NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL DEFAULT 'mind_small',
  PRIMARY KEY (answer_id),
  KEY idx_answer_question (question_id),
  KEY idx_answer_author (author_id),
  KEY idx_answer_hot_score (hot_score),
  CONSTRAINT fk_answer_question FOREIGN KEY (question_id) REFERENCES question (question_id),
  CONSTRAINT fk_answer_author FOREIGN KEY (author_id) REFERENCES author (author_id)
) ENGINE=InnoDB COMMENT='Main recommendation entity for the project.';

CREATE TABLE question_topic (
  question_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  source_rank SMALLINT NOT NULL DEFAULT 0 COMMENT '0=category, 1=subcategory.',
  PRIMARY KEY (question_id, topic_id),
  KEY idx_question_topic_topic (topic_id),
  CONSTRAINT fk_question_topic_question FOREIGN KEY (question_id) REFERENCES question (question_id),
  CONSTRAINT fk_question_topic_topic FOREIGN KEY (topic_id) REFERENCES topic (topic_id)
) ENGINE=InnoDB COMMENT='Many-to-many bridge between questions and topics.';

CREATE TABLE answer_topic (
  answer_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  source_rank SMALLINT NOT NULL DEFAULT 0 COMMENT '0=category, 1=subcategory.',
  PRIMARY KEY (answer_id, topic_id),
  KEY idx_answer_topic_topic (topic_id),
  CONSTRAINT fk_answer_topic_answer FOREIGN KEY (answer_id) REFERENCES answer (answer_id),
  CONSTRAINT fk_answer_topic_topic FOREIGN KEY (topic_id) REFERENCES topic (topic_id)
) ENGINE=InnoDB COMMENT='Many-to-many bridge between answers and topics.';

CREATE TABLE query_topic_map (
  query_key VARCHAR(512) NOT NULL COMMENT 'Normalized token-ID sequence or a synthetic demo alias.',
  display_query VARCHAR(255) NULL COMMENT 'Optional synthetic query string shown in the demo UI.',
  query_tokens_json JSON NULL,
  topic_id BIGINT NOT NULL,
  score DECIMAL(10, 6) NOT NULL COMMENT 'Offline co-occurrence score used for topic-aware recall boost.',
  evidence_query_count INT NOT NULL DEFAULT 0,
  evidence_user_count INT NOT NULL DEFAULT 0,
  match_rank INT NOT NULL DEFAULT 0,
  source_method VARCHAR(64) NOT NULL DEFAULT 'offline_user_topic_cooccurrence',
  PRIMARY KEY (query_key, topic_id),
  KEY idx_query_topic_topic (topic_id),
  KEY idx_query_topic_rank (query_key, match_rank),
  CONSTRAINT fk_query_topic_topic FOREIGN KEY (topic_id) REFERENCES topic (topic_id)
) ENGINE=InnoDB COMMENT='English query aliases and category mappings.';

CREATE TABLE hot_answer_snapshot (
  snapshot_key VARCHAR(64) NOT NULL COMMENT 'Named news hotness snapshot.',
  rank_position INT NOT NULL,
  answer_id BIGINT NOT NULL,
  hot_score DOUBLE NOT NULL,
  click_count INT NOT NULL DEFAULT 0,
  impression_count INT NOT NULL DEFAULT 0,
  source_window VARCHAR(64) NOT NULL DEFAULT 'selected_mind_impressions',
  PRIMARY KEY (snapshot_key, rank_position),
  UNIQUE KEY uq_hot_snapshot_answer (snapshot_key, answer_id),
  KEY idx_hot_answer_answer (answer_id),
  CONSTRAINT fk_hot_answer_snapshot_answer FOREIGN KEY (answer_id) REFERENCES answer (answer_id)
) ENGINE=InnoDB COMMENT='Fallback pool for hot articles.';

CREATE TABLE system_profile_seed (
  seed_key VARCHAR(64) NOT NULL,
  topic_weights_json JSON NOT NULL,
  recent_clicked_answers_json JSON NULL,
  recent_queries_json JSON NULL,
  behavior_score DOUBLE NOT NULL DEFAULT 0,
  notes VARCHAR(255) NULL,
  PRIMARY KEY (seed_key)
) ENGINE=InnoDB COMMENT='Reusable cold-start or bootstrap profile seeds.';

CREATE TABLE user_profile (
  user_id BIGINT NOT NULL,
  cold_start_seed_key VARCHAR(64) NOT NULL DEFAULT 'cold_start_default',
  topic_weights_json JSON NOT NULL,
  recent_clicked_answers_json JSON NOT NULL,
  recent_queries_json JSON NOT NULL,
  behavior_score DOUBLE NOT NULL DEFAULT 0,
  user_vector_json JSON NULL COMMENT 'Optional compact vector summary used by retrieval services.',
  notes VARCHAR(255) NULL COMMENT 'Importer or debug note for the current seeded profile state.',
  last_event_ts BIGINT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  KEY idx_user_profile_seed (cold_start_seed_key),
  CONSTRAINT fk_user_profile_user FOREIGN KEY (user_id) REFERENCES app_user (user_id),
  CONSTRAINT fk_user_profile_seed FOREIGN KEY (cold_start_seed_key) REFERENCES system_profile_seed (seed_key)
) ENGINE=InnoDB COMMENT='Single-table user profile storage.';

CREATE TABLE sponsored_campaign (
  campaign_id BIGINT NOT NULL,
  campaign_name VARCHAR(128) NOT NULL,
  status ENUM('draft', 'active', 'paused', 'ended') NOT NULL DEFAULT 'draft',
  start_ts BIGINT NOT NULL,
  end_ts BIGINT NOT NULL,
  daily_budget_micros BIGINT NOT NULL,
  pacing_mode ENUM('even', 'asap') NOT NULL DEFAULT 'even',
  frequency_cap_per_user_per_day INT NOT NULL DEFAULT 2,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (campaign_id),
  KEY idx_sponsored_campaign_status_window (status, start_ts, end_ts)
) ENGINE=InnoDB COMMENT='Synthetic local sponsored campaigns; not a billing source of truth.';

CREATE TABLE sponsored_campaign_topic (
  campaign_id BIGINT NOT NULL,
  topic_id BIGINT NOT NULL,
  PRIMARY KEY (campaign_id, topic_id),
  KEY idx_sponsored_campaign_topic_topic (topic_id),
  CONSTRAINT fk_sponsored_campaign_topic_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id),
  CONSTRAINT fk_sponsored_campaign_topic_topic
    FOREIGN KEY (topic_id) REFERENCES topic (topic_id)
) ENGINE=InnoDB COMMENT='Normalized topic eligibility for sponsored campaigns.';

CREATE TABLE sponsored_creative (
  creative_id BIGINT NOT NULL,
  campaign_id BIGINT NOT NULL,
  answer_id BIGINT NOT NULL,
  status ENUM('active', 'paused') NOT NULL DEFAULT 'active',
  bid_micros BIGINT NOT NULL COMMENT 'Synthetic bid used only by the local demo.',
  predicted_ctr DECIMAL(10, 8) NOT NULL,
  quality_score DECIMAL(10, 8) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (creative_id),
  UNIQUE KEY uq_sponsored_creative_campaign_answer (campaign_id, answer_id),
  KEY idx_sponsored_creative_answer (answer_id),
  CONSTRAINT fk_sponsored_creative_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id),
  CONSTRAINT fk_sponsored_creative_answer
    FOREIGN KEY (answer_id) REFERENCES answer (answer_id),
  CONSTRAINT chk_sponsored_creative_bid CHECK (bid_micros > 0),
  CONSTRAINT chk_sponsored_creative_ctr CHECK (predicted_ctr >= 0 AND predicted_ctr <= 1),
  CONSTRAINT chk_sponsored_creative_quality CHECK (quality_score >= 0 AND quality_score <= 1)
) ENGINE=InnoDB COMMENT='Sponsored creatives backed by existing answer cards.';

CREATE TABLE sponsored_campaign_daily_state (
  campaign_id BIGINT NOT NULL,
  budget_date DATE NOT NULL,
  expected_spend_micros BIGINT NOT NULL DEFAULT 0,
  served_impression_count INT NOT NULL DEFAULT 0,
  confirmed_impression_count INT NOT NULL DEFAULT 0,
  click_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (campaign_id, budget_date),
  CONSTRAINT fk_sponsored_daily_state_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id)
) ENGINE=InnoDB COMMENT='Daily synthetic expected-spend and delivery counters.';

CREATE TABLE sponsored_user_daily_frequency (
  campaign_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  budget_date DATE NOT NULL,
  served_impression_count INT NOT NULL DEFAULT 0,
  last_served_ts BIGINT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (campaign_id, user_id, budget_date),
  KEY idx_sponsored_frequency_user_date (user_id, budget_date),
  CONSTRAINT fk_sponsored_frequency_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id),
  CONSTRAINT fk_sponsored_frequency_user
    FOREIGN KEY (user_id) REFERENCES app_user (user_id)
) ENGINE=InnoDB COMMENT='Per-user daily sponsored frequency-cap state.';

CREATE TABLE sponsored_delivery (
  delivery_id VARCHAR(128) NOT NULL,
  request_id VARCHAR(128) NOT NULL,
  user_id BIGINT NOT NULL,
  campaign_id BIGINT NOT NULL,
  creative_id BIGINT NOT NULL,
  answer_id BIGINT NOT NULL,
  slot_position SMALLINT NOT NULL,
  budget_date DATE NOT NULL,
  expected_spend_micros BIGINT NOT NULL,
  served_ts BIGINT NOT NULL,
  confirmed_impression_ts BIGINT NULL,
  clicked_ts BIGINT NULL,
  delivery_status ENUM('served', 'confirmed', 'clicked') NOT NULL DEFAULT 'served',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (delivery_id),
  UNIQUE KEY uq_sponsored_delivery_request_creative (request_id, creative_id),
  KEY idx_sponsored_delivery_user_ts (user_id, served_ts),
  KEY idx_sponsored_delivery_campaign_ts (campaign_id, served_ts),
  CONSTRAINT fk_sponsored_delivery_user
    FOREIGN KEY (user_id) REFERENCES app_user (user_id),
  CONSTRAINT fk_sponsored_delivery_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id),
  CONSTRAINT fk_sponsored_delivery_creative
    FOREIGN KEY (creative_id) REFERENCES sponsored_creative (creative_id),
  CONSTRAINT fk_sponsored_delivery_answer
    FOREIGN KEY (answer_id) REFERENCES answer (answer_id)
) ENGINE=InnoDB COMMENT='Server-side sponsored serving ledger and client confirmation state.';

CREATE TABLE user_event (
  event_id BIGINT NOT NULL AUTO_INCREMENT,
  external_event_id VARCHAR(128) NULL COMMENT 'Idempotency key from browser, importer, or Kafka producer.',
  user_id BIGINT NOT NULL,
  event_type ENUM(
    'search_query',
    'recommendation_click',
    'search_result_click',
    'feed_impression',
    'detail_view',
    'dwell',
    'upvote',
    'downvote',
    'share'
  ) NOT NULL,
  answer_id BIGINT NULL,
  sponsored_delivery_id VARCHAR(128) NULL,
  campaign_id BIGINT NULL,
  creative_id BIGINT NULL,
  query_key VARCHAR(512) NULL COMMENT 'Direct query key for search_query or matched_query_key carried by click events.',
  query_tokens_json JSON NULL,
  topic_ids_json JSON NULL COMMENT 'Topics used when updating the profile.',
  surface VARCHAR(32) NOT NULL DEFAULT 'feed',
  request_id VARCHAR(128) NULL,
  dwell_ms BIGINT NULL,
  derived_from_raw TINYINT(1) NOT NULL DEFAULT 0,
  source_confidence ENUM('confirmed', 'heuristic', 'not_applicable') NOT NULL DEFAULT 'not_applicable',
  event_ts BIGINT NOT NULL,
  debug_payload_json JSON NULL,
  PRIMARY KEY (event_id),
  UNIQUE KEY uq_user_event_external_event_id (external_event_id),
  KEY idx_user_event_user_ts (user_id, event_ts),
  KEY idx_user_event_type_ts (event_type, event_ts),
  KEY idx_user_event_answer (answer_id),
  KEY idx_user_event_request_answer (request_id, answer_id),
  KEY idx_user_event_campaign_ts (campaign_id, event_ts),
  CONSTRAINT fk_user_event_user FOREIGN KEY (user_id) REFERENCES app_user (user_id),
  CONSTRAINT fk_user_event_answer FOREIGN KEY (answer_id) REFERENCES answer (answer_id),
  CONSTRAINT fk_user_event_sponsored_delivery
    FOREIGN KEY (sponsored_delivery_id) REFERENCES sponsored_delivery (delivery_id),
  CONSTRAINT fk_user_event_campaign
    FOREIGN KEY (campaign_id) REFERENCES sponsored_campaign (campaign_id),
  CONSTRAINT fk_user_event_creative
    FOREIGN KEY (creative_id) REFERENCES sponsored_creative (creative_id)
) ENGINE=InnoDB COMMENT='Event log for closed-loop updates and replay.';

CREATE TABLE event_outbox (
  outbox_id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(128) NOT NULL,
  topic VARCHAR(255) NOT NULL,
  message_key VARCHAR(255) NOT NULL,
  payload_fingerprint CHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  status ENUM('pending', 'publishing', 'published', 'dead') NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  published_at DATETIME(6) NULL,
  last_error TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (outbox_id),
  UNIQUE KEY uq_event_outbox_event_topic (event_id, topic),
  KEY idx_event_outbox_ready (status, available_at, outbox_id)
) ENGINE=InnoDB COMMENT='Transactional Kafka outbox with at-least-once delivery.';

CREATE TABLE worker_heartbeat (
  worker_name VARCHAR(64) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  last_progress_at DATETIME(6) NULL,
  lag_messages BIGINT NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (worker_name)
) ENGINE=InnoDB COMMENT='Readiness heartbeat and progress state for local Kafka workers.';
